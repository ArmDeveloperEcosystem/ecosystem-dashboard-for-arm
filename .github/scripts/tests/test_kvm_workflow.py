"""Fault-test actual workflow shell. Synthetic successes are not native KVM evidence."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exact_run_aggregation as exact_run
import package_observation_migration_audit as observation_audit
import package_result_policy as result_policy
from test_exact_run_aggregation import ContractFixture, REPOSITORY

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-kvm.yml"
RELEASE = "6.17.0-1017-aws"
REVISION = "6.17.0-1017.17~24.04.1"
PACKAGE = f"linux-image-{RELEASE}"

# Mock only OS/driver boundaries in a child interpreter. Production shell and
# Python bodies are extracted verbatim; no fixture ever opens a real KVM device.
PYTHON_FIXTURE = r'''
import json
import os
from pathlib import Path
import platform
import runpy
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

fault = json.loads(os.environ.get("SYNTHETIC_FAULT", "{}"))
release = fault.get("release", "6.17.0-1017-aws")
revision = fault.get("revision", "6.17.0-1017.17~24.04.1")
package = fault.get("package", "linux-image-" + release)
original_read_text = Path.read_text
original_is_file = Path.is_file
original_run = subprocess.run

def read_text(path, *args, **kwargs):
    if str(path) == "/proc/sys/kernel/osrelease":
        return fault.get("proc_release", release) + "\n"
    if str(path) == "/proc/version_signature":
        if fault.get("missing_signature"):
            raise FileNotFoundError(str(path))
        return fault.get("signature", "Ubuntu " + revision + "-" + release.split("-", 2)[2] + " 6.17.12\n")
    return original_read_text(path, *args, **kwargs)

def is_file(path):
    if str(path).startswith("/boot/vmlinuz-"):
        return not fault.get("missing_image")
    return original_is_file(path)

def run(args, **kwargs):
    assert kwargs == dict(capture_output=True, text=True, timeout=12), kwargs
    with open(os.environ["SYNTHETIC_CALLS"], "a") as stream:
        stream.write(json.dumps(list(args)) + "\n")
    if args[0] == "dpkg-query":
        if args[1] == "-S":
            assert args[2] == "/boot/vmlinuz-" + release
            stdout = fault.get("owner", package + ": " + args[2] + "\n")
        else:
            assert args[1:3] == ("-W", "-f=$"+"{Package}\t$"+"{Version}\t$"+"{Architecture}\t$"+"{Status}\n")
            assert args[3] == package
            stdout = fault.get("row", package + "\t" + revision + "\tarm64\tinstall ok installed\n")
        return subprocess.CompletedProcess(args, fault.get("pm_rc", 0), stdout, fault.get("pm_stderr", ""))
    assert args[0] == os.environ["KVM_SMOKE_DIR"] + "/smoke", args
    if fault.get("timeout"):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    if fault.get("actual_timeout"):
        return original_run(["/bin/sleep", "30"], **kwargs)
    mode = args[1]
    value = int(args[2]) if mode == "guest" else 0
    expected = dict(mode=mode, api=12, value={"api": 12, "vcpu": 0x1234,
                    "invalid-memory": 22, "guest": value + 7}[mode],
                    input=value, memory=value + 7 if mode == "guest" else 0,
                    mmio=value + 7 if mode == "guest" else 0)
    expected.update(fault.get("result", {}))
    for key in fault.get("omit", []):
        expected.pop(key, None)
    stdout = fault.get("stdout", json.dumps(expected) + "\n")
    return subprocess.CompletedProcess(args, fault.get("rc", 0), stdout, fault.get("stderr", ""))

sys.argv = sys.argv[1:]
with mock.patch.object(platform, "uname", return_value=SimpleNamespace(
        system=fault.get("system", "Linux"), machine=fault.get("arch", "aarch64"), release=release)), \
     mock.patch.object(platform, "freedesktop_os_release", return_value={
        "ID": fault.get("distro", "ubuntu"), "VERSION_ID": fault.get("distro_version", "24.04")}), \
     mock.patch.object(Path, "read_text", read_text), \
     mock.patch.object(Path, "is_file", is_file), \
     mock.patch.object(subprocess, "run", run):
    runpy.run_path(sys.argv[0], run_name="__main__")
'''


def embedded(step, marker):
    return step["run"].split(f"<<'{marker}'\n", 1)[1].split(f"\n{marker}\n", 1)[0] + "\n"


class KvmWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="kvm-synthetic-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.driver = self.root / "driver"
        self.driver.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-kvm"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        for name in ("date", "cat", "mkdir"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.tool("sha256sum", "exit 99\n")
        self.tool("bash", 'test "$*" = \'.github/actions/apt-bootstrap/bootstrap.sh --packages gcc libc6-dev linux-libc-dev python3\'\nexit "$APT_RC"\n')
        self.tool("uname", 'case "$1" in -m) echo "$ARCH";; -s) echo Linux;; *) exit 99;; esac\n')
        self.tool("gcc", 'exit "$GCC_RC"\n')
        launcher = self.root / "python-fixture.py"
        launcher.write_text(PYTHON_FIXTURE)
        self.tool("python3", f'exec "{sys.executable}" "{launcher}" "$@"\n')
        self.script = self.driver / "check.py"
        self.script.write_text(embedded(self.steps["install"], "PY"))
        self.c_source = embedded(self.steps["install"], "C")
        # Non-executable synthetic bytes, never run as a program.
        raw = bytearray(64)
        raw[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", raw, 18, 183)
        self.binary = self.driver / "smoke"
        self.binary.write_bytes(raw)
        self.env = dict(PATH=str(self.bin), HOME=str(self.root), TMPDIR=str(self.root),
                        KVM_SMOKE_DIR=str(self.driver), LC_ALL="C",
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_STEP_SUMMARY=str(self.root / "summary"),
                        PYTHONDONTWRITEBYTECODE="1", ARCH="aarch64", APT_RC="0", GCC_RC="1",
                        SYNTHETIC_CALLS=str(self.root / "calls"))
        self.values = {
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.install.outputs.harness_sha256": hashlib.sha256(raw).hexdigest(),
            "steps.version.outcome": "success",
            "steps.version.outputs.status": "passed",
            "steps.version.outputs.version": RELEASE,
            "steps.version.outputs.kernel_package": PACKAGE,
            "steps.version.outputs.package_version": REVISION,
            "steps.test6.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.current_version": RELEASE,
            "steps.test6.outputs.latest_version": "not_applicable",
            "steps.test6.outputs.next_installed_version": "not_applicable",
            "steps.test6.outputs.duration": "0",
            "steps.test6.outputs.regression_result": "Synthetic package manager applicability.",
            "steps.test6.outputs.comparison": "Synthetic five-check fixture.",
        }
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.calls = 0

    def tool(self, name, code):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + code)
        path.chmod(0o755)

    def render(self, source):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return str(self.values[term])
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, step_id, fault=None, **overrides):
        step = self.steps[step_id]
        script = self.render(step["run"])
        env = {**self.env, **{k: self.render(v) for k, v in step.get("env", {}).items()},
               "SYNTHETIC_FAULT": json.dumps(fault or {}), **overrides}
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=25)
        raw = output.read_text()
        pairs = [line.split("=", 1) for line in raw.splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs), raw)
        outputs = dict(pairs)
        self.assertEqual(len(pairs), len(outputs), "Duplicate workflow outputs")
        evidence = os.environ.get("WORKFLOW_EVIDENCE_ROOT")
        if evidence:
            self.calls += 1
            target = Path(evidence) / self._testMethodName / str(self.calls)
            target.mkdir(parents=True)
            for name, text in {"source.sh": step["run"], "rendered.sh": script,
                "env.json": json.dumps(env, indent=2), "values.json": json.dumps(self.values, indent=2),
                "stdout.txt": result.stdout, "stderr.txt": result.stderr, "github-output.txt": raw,
                "exit.txt": str(result.returncode), "EVIDENCE-TYPE.txt": "SYNTHETIC ONLY; NO NATIVE KVM EXECUTION\n",
                "workflow-sha256.txt": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()}.items():
                (target / name).write_text(text)
        return result, outputs

    def rejected(self, step, fault=None, **env):
        result, outputs = self.run_step(step, fault, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs.get("status"))
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        if step == "version":
            self.assertNotIn("version", outputs)
        return result

    def applicability(self):
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in outputs.items()})
        return outputs

    def test_synthetic_package_owned_running_kernel_identity(self):
        for fault in ({}, {"package": "linux-image-unsigned-" + RELEASE},
                      {"owner": PACKAGE + ":arm64: /boot/vmlinuz-" + RELEASE + "\n"},
                      {"release": "6.8.0-1050-aws", "revision": "6.8.0-1050.53"}):
            result, outputs = self.run_step("version", fault)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(fault.get("release", RELEASE), outputs["version"])
            self.assertEqual(fault.get("revision", REVISION), outputs["package_version"])

    def test_identity_rejects_wrong_arch_distro_kernel_and_package(self):
        row = PACKAGE + "\t" + REVISION + "\tarm64\tinstall ok installed\n"
        faults = [{"arch": "x86_64"}, {"system": "Darwin"}, {"distro": "debian"},
                  {"distro_version": "22.04"}, {"release": "QEMU 10.0"},
                  {"proc_release": "6.8.0-31-generic"}, {"missing_image": True},
                  {"owner": ""}, {"owner": "qemu-system-arm: /boot/vmlinuz-" + RELEASE + "\n"},
                  {"owner": (PACKAGE + ": /boot/vmlinuz-" + RELEASE + "\n") * 2},
                  {"row": row * 2}, {"row": row.replace("arm64", "amd64")},
                  {"row": row.replace("installed", "unpacked")}, {"row": ""},
                  {"revision": "6.17.0-9999.1"}, {"revision": "unknown"},
                  {"signature": "Ubuntu wrong-kernel 6.17.12\n"}, {"missing_signature": True},
                  {"pm_rc": 1}, {"pm_stderr": "query failed\n"}]
        for fault in faults:
            with self.subTest(fault=fault):
                self.rejected("version", fault)

    def test_version_check_requires_unchanged_verified_identity(self):
        result, outputs = self.run_step("test2")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        for field in ("version", "kernel_package", "package_version"):
            key = f"steps.version.outputs.{field}"
            original = self.values[key]
            self.values[key] = "wrong"
            self.rejected("test2")
            self.values[key] = original

    def test_setup_failures_cannot_emit_success(self):
        for env in ({"ARCH": "x86_64"}, {"APT_RC": "100"}, {"GCC_RC": "1"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("install", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs.get("install_status"))
                self.assertNotIn("harness_sha256", outputs)

    def test_synthetic_driver_protocol_requires_each_operation(self):
        for step in ("test1", "test3", "test4", "test5"):
            result, outputs = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("passed", outputs["status"])
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual(["api", "vcpu", "invalid-memory", "guest", "guest"], [call[1] for call in calls])
        self.assertLess(int(calls[-2][2]), 2**31)
        self.assertEqual(str(2**32 - 1), calls[-1][2])

    def test_device_denial_command_failures_and_timeouts_fail_closed(self):
        for fault in ({"rc": 1, "stderr": "/dev/kvm: No such file or directory\n"},
                      {"rc": 1, "stderr": "/dev/kvm: Permission denied\n"},
                      {"rc": 124}, {"rc": -11}, {"timeout": True},
                      {"stderr": "unexpected warning\n"}):
            for step in ("test1", "test3", "test4", "test5"):
                with self.subTest(fault=fault, step=step):
                    self.rejected(step, fault)

    def test_actual_subprocess_deadline_reaches_failed_shell_output(self):
        result = self.rejected("test5", {"actual_timeout": True})
        self.assertIn("TimeoutExpired", result.stderr)

    def test_missing_malformed_and_wrong_guest_results_fail(self):
        for fault in ({"stdout": ""}, {"stdout": "QEMU emulator version 10.0\n"},
                      {"stdout": "{}\n{}\n"}, {"stdout": '{"api":12,"api":12}'},
                      {"stdout": "[]"}, {"result": {"api": True}}, {"result": {"api": 11}},
                      {"result": {"value": 0}}, {"result": {"memory": 0}}, {"result": {"mmio": 0}},
                      {"result": {"input": -1}}, {"result": {"mode": "api"}},
                      {"result": {"extra": 1}}, {"omit": ["memory"]}):
            with self.subTest(fault=fault):
                self.rejected("test5", fault)
        self.rejected("test4", {"result": {"value": 0}})

    def test_fake_cli_wrong_elf_and_changed_driver_fail(self):
        for raw in (b"#!/bin/sh\necho passed\n", b"", b"\x7fELF\x02\x01" + b"\0" * 58):
            self.binary.write_bytes(raw)
            self.values["steps.install.outputs.harness_sha256"] = hashlib.sha256(raw).hexdigest()
            self.rejected("test5")
        self.binary.write_bytes(b"changed")
        self.values["steps.install.outputs.harness_sha256"] = "0" * 64
        self.rejected("test1")
        self.binary.unlink()
        self.rejected("test1")

    def test_core_shells_require_successful_setup_and_identity_outcomes(self):
        for key, bad in (("steps.install.outcome", "failure"), ("steps.install.outcome", ""),
                         ("steps.install.outputs.install_status", "failed"),
                         ("steps.version.outcome", "failure"), ("steps.version.outcome", ""),
                         ("steps.version.outputs.status", "failed")):
            original = self.values[key]
            self.values[key] = bad
            for i in range(1, 6):
                self.rejected(f"test{i}")
            self.values[key] = original

    def test_five_core_and_one_skip_satisfy_policy_and_exact_collector(self):
        regression = self.applicability()
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(dict(passed="5", failed="0", skipped="1", core_failed="0",
                              duration="15", overall_status="success", badge_status="passing"), summary)
        self.assertIn("kernel", regression["comparison"])
        self.assertIn("test driver", regression["comparison"])
        self.validate_contract(summary, regression)

    def validate_contract(self, summary, regression):
        fixture = ContractFixture()
        self.addCleanup(fixture.close)
        statuses = [self.values[f"steps.test{i}.outputs.status"] for i in range(1, 6)] + ["skipped"]
        semantic = result_policy.expected_regression_metadata(
            decision=regression["decision"], core_failed=int(summary["core_failed"]))
        payload = fixture.result(1, statuses=statuses, regression_status=semantic["status"],
            regression_decision=regression["decision"], run_status=summary["overall_status"],
            badge_status=summary["badge_status"], core_failed=int(summary["core_failed"]))
        payload["package"] = dict(name="KVM", version=RELEASE)
        payload["tests"]["duration_seconds"] = int(summary["duration"])
        for key in ("passed", "failed", "skipped"):
            payload["tests"][key] = int(summary[key])
        for i, detail in enumerate(payload["tests"]["details"], 1):
            detail["name"] = self.steps[f"test{i}"]["name"]
            detail["duration_seconds"] = int(self.values[f"steps.test{i}.outputs.duration"])
        payload["tests"]["details"][5].update(regression_result=regression["regression_result"],
            comparison=regression["comparison"], current_version=regression["current_version"],
            latest_version=regression["latest_version"], next_installed_version=regression["next_installed_version"])
        self.assertEqual(summary["overall_status"], result_policy.validate_publishable_result(payload))
        kwargs = dict(registration=fixture.topology[0].packages[0], repository=REPOSITORY, batch=1,
                      run=fixture.manifest["batches"][0]["run"], job=fixture.manifest["batches"][0]["jobs"][0])
        if summary["overall_status"] == "failure":
            kwargs["job"]["conclusion"] = "failure"
        exact_run.validate_package_result(payload, **kwargs)
        malformed = copy.deepcopy(payload)
        malformed["tests"]["passed"] = 6
        with self.assertRaises(exact_run.ContractError):
            exact_run.validate_package_result(malformed, **kwargs)
        malformed = copy.deepcopy(payload)
        malformed["package"]["version"] = "unknown"
        with self.assertRaises(exact_run.ContractError):
            exact_run.validate_package_result(malformed, **kwargs)

    def test_expected_missing_kvm_failure_is_publishable_failure(self):
        for i in (1, 3, 4, 5):
            self.values[f"steps.test{i}.outputs.status"] = "failed"
            self.values[f"steps.test{i}.outcome"] = "failure"
        regression = self.applicability()
        self.assertEqual("baseline_failed", regression["decision"])
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("1", "4", "1", "4", "failure"),
            tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))
        self.validate_contract(summary, regression)

    def test_every_missing_or_masked_core_outcome_fails_summary(self):
        for i in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", ""), ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped")):
                with self.subTest(i=i, status=status, outcome=outcome):
                    self.values[f"steps.test{i}.outputs.status"] = status
                    self.values[f"steps.test{i}.outcome"] = outcome
                    regression = self.applicability()
                    self.assertEqual("baseline_failed", regression["decision"])
                    result, summary = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped")))
            self.values[f"steps.test{i}.outputs.status"] = "passed"
            self.values[f"steps.test{i}.outcome"] = "success"

    def test_failed_prerequisites_cannot_be_masked_by_five_passing_outputs(self):
        for key, bad, decision in (
                ("steps.install.outcome", "failure", "baseline_install_failed"),
                ("steps.install.outcome", "", "baseline_install_failed"),
                ("steps.install.outputs.install_status", "", "baseline_install_failed"),
                ("steps.version.outcome", "", "baseline_failed"),
                ("steps.version.outputs.status", "failed", "baseline_failed"),
                ("steps.version.outputs.version", "unknown", "baseline_failed"),
                ("steps.version.outputs.kernel_package", "", "baseline_failed"),
                ("steps.version.outputs.package_version", "", "baseline_failed")):
            original = self.values[key]
            self.values[key] = bad
            regression = self.applicability()
            self.assertEqual(decision, regression["decision"])
            result, summary = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("0", "5", "1", "5"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
            self.values[key] = original

    def test_test6_requires_exact_skip_outcome_and_version_fields(self):
        for field, bad in (("outcome", ""), ("outcome", "failure"), ("outputs.status", "passed"),
                           ("outputs.decision", "baseline_failed"), ("outputs.decision", "not_configured"),
                           ("outputs.current_version", "wrong"), ("outputs.latest_version", "unknown"),
                           ("outputs.next_installed_version", "not_installed"),
                           ("outputs.regression_result", ""), ("outputs.comparison", "")):
            key = "steps.test6." + field
            original = self.values[key]
            self.values[key] = bad
            result, summary = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("5", "1", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped")))
            self.values[key] = original

    def test_missing_and_malformed_durations_never_pass(self):
        for i in range(1, 7):
            key = f"steps.test{i}.outputs.duration"
            original = self.values[key]
            for bad in ("", "-1", "1.5", "n/a", "1000000"):
                self.values[key] = bad
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", summary["overall_status"])
            self.values[key] = original

    def test_workflow_contract_and_auditor_outputs(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual("always()", self.steps["test6"]["if"])
        self.assertEqual("always()", self.steps["summary"]["if"])
        root = WORKFLOW.parents[2]
        for step_id in ("version", "test1", "test2", "test3", "test4", "test5"):
            for key in ("status", "duration"):
                self.assertTrue(observation_audit._step_emits_output(root, self.steps[step_id], key))
        for key in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["summary"], key))
        self.assertEqual({("not_applicable_package_manager", "skipped"), ("baseline_failed", "skipped"),
                          ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(root, self.steps["test6"])))
        self.assertIn("steps.summary.outputs.failed || '6'", self.job["outputs"]["tests_failed"])
        self.assertNotIn("qemu-", WORKFLOW.read_text().lower())
        for forbidden in ("sudo ", "modprobe", "mknod", "sysctl", "/dev/vhost", "system("):
            self.assertNotIn(forbidden, self.c_source)
        self.assertIn('open("/dev/kvm", O_RDWR | O_CLOEXEC)', self.c_source)
        self.assertIn("ioctl(vcpu, KVM_RUN, 0)", self.c_source)
        self.assertIn("alarm(8)", self.c_source)
        self.assertIn("rc == -1 && errno == EINVAL", self.c_source)

    def test_all_shell_bodies_have_valid_bash_syntax(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["/bin/bash", "-n"], input=self.render(step["run"]),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)


if __name__ == "__main__":
    unittest.main()
