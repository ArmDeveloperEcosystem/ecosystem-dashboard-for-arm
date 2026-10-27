"""Workflow policy/shell fixtures only; these tests do not execute the native package."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
SLUG = "libkrun"
WORKFLOW = ROOT / f".github/workflows/test-{SLUG}.yml"
HELPER = ROOT / f".github/scripts/tests/{SLUG}_guest_smoke.sh"
PAGE = ROOT / f"content/linux/opensource_packages/{SLUG}.md"
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
OUTPUTS = {
    "contract_version", "package_slug", "package_name", "package_version",
    "run_status", "badge_status", "core_failed", "tests_passed", "tests_failed",
    "tests_skipped", "duration_seconds", "regression_status", "regression_decision",
    "regression_result", "regression_comparison", "regression_current_version",
    "regression_latest_version", "regression_next_installed_version", "regression_policy", "run_id",
    "run_attempt", "job_name", "dashboard_link", "timestamp",
}
# Preserve Xen's contract and include the requested explicit regression policy output.


class PackageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        self.job = self.doc["jobs"][f"test-{SLUG}"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.values = {
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": self.job["env"]["BASELINE_VERSION"],
            "steps.test6.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "runtime_validation_not_automated",
            "steps.test6.outputs.duration": "0",
        }
        for n in range(1, 6):
            self.values.update({
                f"steps.test{n}.outcome": "success",
                f"steps.test{n}.outputs.status": "passed",
                f"steps.test{n}.outputs.duration": str(n),
            })

    def render(self, source):
        def replace(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, source)

    def run_shell(self, script, extra_env=None):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.touch()
            process = subprocess.run(
                ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                env={**os.environ, "GITHUB_OUTPUT": str(output),
                     "BASELINE_VERSION": self.job["env"]["BASELINE_VERSION"], **(extra_env or {})},
                capture_output=True, text=True, timeout=10,
            )
            lines = [line.split("=", 1) for line in output.read_text().splitlines()]
            self.assertTrue(all(len(line) == 2 for line in lines), lines)
            self.assertEqual(len(lines), len(dict(lines)), "duplicate output keys")
            return process, dict(lines)

    def summary(self):
        return self.run_shell(self.render(self.steps["summary"]["run"]))

    def test_contract_matches_xen_without_global_edits(self):
        reference = yaml.load(
            (ROOT / ".github/workflows/test-xen-hypervisor.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(set(self.job["outputs"]), OUTPUTS)
        reference_keys = set(reference["jobs"]["test-xen-hypervisor"]["outputs"])
        self.assertTrue(reference_keys.issubset(self.job["outputs"]))
        self.assertLessEqual(set(self.job["outputs"]) - reference_keys, {"regression_policy"})
        self.assertEqual(set(self.doc["on"]["workflow_call"]["outputs"]), OUTPUTS)
        self.assertIn("workflow_dispatch", self.doc["on"])
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.job["steps"][0]["uses"], CHECKOUT)
        self.assertEqual(self.job["steps"][0]["with"]["persist-credentials"], "false")
        self.assertNotIn("||", self.steps["version"]["run"])
        self.assertIn("KVM required", self.job["outputs"]["package_name"])

    def test_shell_syntax_and_embedded_python(self):
        for step in self.job["steps"]:
            if "run" not in step:
                continue
            script = self.render(step["run"])
            parsed = subprocess.run(
                ["/bin/bash", "-n"], input=script, text=True, capture_output=True,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            for source in re.findall(r"<<'PY'\n(.*?)\nPY", script, re.S):
                compile(source, str(WORKFLOW), "exec")
        subprocess.run(["/bin/bash", "-n", str(HELPER)], check=True)
        for source in re.findall(r"<<'PY'\n(.*?)\nPY", HELPER.read_text(), re.S):
            compile(source, str(HELPER), "exec")

    def test_baseline_and_declared_deferral(self):
        process, outputs = self.summary()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(outputs["overall_status"], "success")
        self.assertEqual(outputs["badge_status"], "passing")
        self.assertEqual(outputs["passed"], "5")
        self.assertEqual(outputs["skipped"], "1")
        self.assertEqual(outputs["duration"], "15")

    def test_all_core_missing_or_faulted_evidence_is_failure(self):
        for n in range(1, 6):
            for outcome, status in [
                ("failure", "passed"), ("success", "failed"), ("success", ""),
                ("skipped", ""), ("cancelled", ""), ("", ""),
            ]:
                with self.subTest(test=n, outcome=outcome, status=status):
                    saved = dict(self.values)
                    self.values[f"steps.test{n}.outcome"] = outcome
                    self.values[f"steps.test{n}.outputs.status"] = status
                    process, outputs = self.summary()
                    self.assertNotEqual(process.returncode, 0)
                    self.assertEqual(outputs["overall_status"], "failure")
                    self.assertEqual(outputs["badge_status"], "failing")
                    self.assertEqual(outputs["core_failed"], "1")
                    self.assertEqual(sum(int(outputs[k]) for k in ("passed", "failed", "skipped")), 6)
                    self.values = saved

    def test_install_version_and_policy_fail_closed(self):
        for field, value in [
            ("steps.install.outcome", "failure"),
            ("steps.install.outputs.install_status", ""),
            ("steps.version.outcome", "failure"),
            ("steps.version.outputs.version", ""),
            ("steps.version.outputs.version", "wrong-version"),
            ("steps.test6.outcome", "failure"),
            ("steps.test6.outputs.decision", "baseline_failed"),
            ("steps.test6.outputs.status", "passed"),
        ]:
            with self.subTest(field=field):
                saved = dict(self.values)
                self.values[field] = value
                process, outputs = self.summary()
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(outputs["overall_status"], "failure")
                self.values = saved

    def test_core_fault_traps_record_actual_failure_and_duration(self):
        for n in range(1, 6):
            step = self.steps[f"test{n}"]
            self.assertEqual(step["continue-on-error"], "true")
            self.assertIn("steps.install.outcome == 'success'", step["if"])
            self.assertIn("steps.version.outcome == 'success'", step["if"])
            prefix, separator, _ = step["run"].partition("trap finish_test EXIT\n")
            self.assertTrue(separator)
            process, outputs = self.run_shell(prefix + separator + "false\n")
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
            self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_deferral_never_invents_candidate_or_overrides_faults(self):
        step = self.steps["test6"]
        env = {key: self.render(value) for key, value in step["env"].items()}
        process, outputs = self.run_shell(step["run"], env)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(outputs["status"], "skipped")
        self.assertEqual(outputs["decision"], "runtime_validation_not_automated")
        self.assertEqual(outputs["latest_version"], "not_checked")
        self.assertEqual(outputs["next_installed_version"], "not_installed")
        env["CORE_RESULTS"] = "failure:failed"
        process, outputs = self.run_shell(step["run"], env)
        self.assertEqual(outputs["decision"], "baseline_failed")
        env["INSTALL_OUTCOME"] = "failure"
        process, outputs = self.run_shell(step["run"], env)
        self.assertEqual(outputs["decision"], "baseline_install_failed")

    def test_guest_helper_pins_and_requires_real_guest(self):
        source = HELPER.read_text()
        self.assertIn("test -c /dev/kvm", source)
        self.assertIn("test -r /dev/kvm", source)
        self.assertIn("test -w /dev/kvm", source)
        self.assertIn("fcntl.ioctl(fd, 0xAE01, 0)", source)
        self.assertIn("24bb3511a0db7b5114a4aee033c65a8a4148f39b7b80a398e548546db967a36f", source)
        self.assertIn('test "$RC" -eq 23', source)
        self.assertIn('test "$(uname -m)" = aarch64', source)
        self.assertIn('test "$(cat /tmp/probe)"', source)
        self.assertNotIn("--privileged", source)
        self.assertNotIn("chmod 666", source)
        if SLUG == "libkrun":
            self.assertIn("krun_start_enter", source)
            self.assertIn("krun_set_exec", source)
            self.assertIn("grep -Fx LIBKRUN_GUEST_OK", source)
            self.assertIn("libkrun_guest_smoke.sh guest", self.steps["test5"]["run"])
            install = self.steps["install"]["run"]
            self.assertIn("cargo +", install)
            self.assertIn("--locked -p libkrun", install)
            self.assertIn('ctypes.CDLL(str(path))', install)
            self.assertIn('Path("/proc/self/maps")', install)
            self.assertIn('== -errno.EINVAL', install)
            self.assertIn("FIRMWARE_SHA256", self.job["env"])
        else:
            self.assertIn("export MSB_BACKEND=local", source)
            for n, mode in [(2, "preflight"), (3, "guest"), (4, "exit-status"), (5, "lifecycle")]:
                self.assertIn(f"microsandbox_guest_smoke.sh {mode}", self.steps[f"test{n}"]["run"])
            self.assertIn("MICROSANDBOX_LIFECYCLE_OK", source)
            self.assertIn('libkrunfw.so.5.6.1', self.steps["install"]["run"])

    def test_metadata_minimum_is_historical_not_smoke_version(self):
        page = yaml.safe_load(PAGE.read_text().split("---", 2)[1])
        expected = ("0.1.3", "2021/01/27") if SLUG == "libkrun" else ("0.1.0", "2025/05/20")
        minimum = page["supported_minimum_version"]
        self.assertEqual((str(minimum["version_number"]), minimum["release_date"]), expected)
        self.assertNotEqual(str(minimum["version_number"]), self.job["env"]["BASELINE_VERSION"])
        self.assertEqual(page["category"], "Containers and Orchestration")
        self.assertNotIn("recommended_minimum_version", page)
        self.assertIn("/dev/kvm", page["optional_info"]["support_caveats"])
        self.assertIn("Apache-2.0", page["optional_hidden_info"]["other_info"])
        self.assertIn("release_notes__supported_minimum", page["optional_hidden_info"])
        if SLUG == "libkrun":
            self.assertIn(
                "first numbered upstream tag containing the functional KVM/AArch64 fix",
                page["optional_info"]["support_caveats"],
            )
            self.assertIn("inference", page["optional_info"]["support_caveats"])
            for tag in ("v0.1.1", "v0.1.2", "v0.1.3"):
                self.assertIn(
                    "https://api.github.com/repos/libkrun/libkrun/compare/"
                    "66d16b58f3300de84900751a5a8a704a981e7291..." + tag,
                    page["optional_hidden_info"]["other_info"],
                )
        else:
            self.assertIn("Monocore", page["optional_info"]["support_caveats"])
        for key, value in self.job["env"].items():
            if key.endswith("SHA256"):
                self.assertRegex(value, r"^[a-f0-9]{64}$")
        self.assertIn("sha256sum --check --strict", self.steps["install"]["run"])

    def test_missing_kvm_fails_before_any_native_package_execution(self):
        if Path("/dev/kvm").exists():
            self.skipTest("Missing-device fixture must not open a real host KVM device")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "uname"
            binary.write_text(
                '#!/bin/bash\ncase "$1" in -s) echo Linux ;; -m) echo aarch64 ;; *) exit 2 ;; esac\n'
            )
            binary.chmod(0o755)
            process = subprocess.run(
                ["/bin/bash", str(HELPER), "guest"],
                env={**os.environ, "PATH": directory + os.pathsep + os.defpath},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("usable /dev/kvm required", process.stderr)
            self.assertIn("guest execution NOT tested", process.stderr)
            self.assertNotIn("_GUEST_OK", process.stdout)



    def helper_fixture(self, mode="guest", **faults):
        """Execute the exact helper shell with a fake preflight and fake package tools."""
        import json
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "bin"
            tools.mkdir()
            log = root / "calls"
            script = root / "probe.sh"
            source = re.sub(
                r"preflight\(\) \{.*?\n\}\n",
                "preflight() { :; }\n", HELPER.read_text(), count=1, flags=re.S,
            )
            self.assertNotEqual(source, HELPER.read_text())
            script.write_text(source)
            fixture = r'''
import io
import json
import os
from pathlib import Path
import sys
import tarfile

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FIXTURE_CALLS"], "a") as stream:
    stream.write(json.dumps([tool, *args]) + "\n")
if tool == "timeout":
    if args[0] == "-k":
        args = args[2:]
    os.execvp(args[1], args[1:])
elif tool == "pkg-config":
    print("")
elif tool == "cc":
    if os.environ.get("COMPILE_RC"):
        sys.exit(int(os.environ["COMPILE_RC"]))
    target = Path(args[args.index("-o") + 1])
    target.write_text(
        "#!" + sys.executable + "\n"
        "import os, sys\n"
        "if sys.argv[2] == 'exit 23':\n"
        "    sys.exit(int(os.environ.get('NEGATIVE_RC', '23')))\n"
        "if not os.environ.get('MISSING_SENTINEL'):\n"
        "    print('LIBKRUN_GUEST_OK')\n"
        "sys.exit(int(os.environ.get('GUEST_RC', '0')))\n"
    )
    target.chmod(0o755)
elif tool == "docker":
    if args[0] == "create":
        sys.exit(int(os.environ.get("CREATE_RC", "0")))
    if args[0] == "export":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|"):
            pass
    if args[0] == "rm":
        sys.exit(int(os.environ.get("CLEANUP_RC", "0")))
elif tool == "msb":
    if args[0] == "run":
        if args[-1] == "exit 23":
            sys.exit(int(os.environ.get("NEGATIVE_RC", "23")))
        if not os.environ.get("MISSING_SENTINEL"):
            print("MICROSANDBOX_ARM64_OK")
        sys.exit(int(os.environ.get("GUEST_RC", "0")))
    elif args[0] == "create":
        sys.exit(int(os.environ.get("CREATE_RC", "0")))
    elif args[0] == "exec":
        if "MICROSANDBOX_LIFECYCLE_OK" in args[-1]:
            print("MICROSANDBOX_LIFECYCLE_OK")
        sys.exit(int(os.environ.get("EXEC_RC", "0")))
    elif args[0] == "stop":
        sys.exit(int(os.environ.get("STOP_RC", "0")))
    elif args[0] == "rm":
        sys.exit(int(os.environ.get("CLEANUP_RC", "0")))
    else:
        sys.exit(99)
else:
    sys.exit(99)
'''
            for name in ("timeout", "pkg-config", "cc", "docker", "msb"):
                tool = tools / name
                tool.write_text("#!" + sys.executable + "\n" + fixture)
                tool.chmod(0o755)
            env = {
                **os.environ, "PATH": str(tools) + os.pathsep + os.defpath,
                "FIXTURE_CALLS": str(log), "RUNNER_TEMP": str(root),
                "LIBKRUN_PREFIX": str(root / "prefix"), "LIBKRUNFW_DIR": str(root),
                "MSB_PATH": str(tools / "msb"), "MSB_LIBKRUNFW_PATH": str(root / "firmware"),
                "MSB_HOME": str(root / "home"), **{k: str(v) for k, v in faults.items()},
            }
            result = subprocess.run(
                ["/bin/bash", str(script), mode], env=env,
                capture_output=True, text=True, timeout=15,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            leftovers = list(root.glob("*-guest.*"))
            self.assertEqual(leftovers, [], "Owned scratch directory was not removed")
            return result, calls

    def test_helper_success_and_cleanup_are_required(self):
        modes = ("guest",) if SLUG == "libkrun" else ("guest", "exit-status", "lifecycle")
        for mode in modes:
            with self.subTest(mode=mode):
                result, calls = self.helper_fixture(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                tool = "docker" if SLUG == "libkrun" else "msb"
                removed = [c for c in calls if c[:2] == [tool, "rm"]]
                self.assertTrue(removed)
                if SLUG == "microsandbox":
                    self.assertIn("--force", removed[-1])
                    self.assertRegex(removed[-1][-1], r"^arm-smoke-[A-Za-z0-9]+$")
                    for call in calls:
                        if call[:2] == ["msb", "run"] or call[:2] == ["msb", "create"]:
                            self.assertEqual(call[call.index("--name") + 1], removed[-1][-1])
                else:
                    created = next(c for c in calls if c[:2] == ["docker", "create"])
                    self.assertEqual(created[created.index("--name") + 1], removed[-1][-1])

    def test_helper_faults_cannot_be_hidden_by_sentinels_or_cleanup(self):
        cases = [
            ({"GUEST_RC": 37}, 37),
            ({"GUEST_RC": 124}, 124),
            ({"GUEST_RC": 37, "CLEANUP_RC": 44}, 37),
            ({"MISSING_SENTINEL": 1}, 1),
            ({"NEGATIVE_RC": 0}, 1),
        ]
        # libkrun removes its exported-image container before executing the guest.
        if SLUG == "libkrun":
            cases = [c for c in cases if "CLEANUP_RC" not in c[0]]
            cases.extend([({"CREATE_RC": 124}, 124), ({"COMPILE_RC": 41}, 41)])
        else:
            cases.append(({"CLEANUP_RC": 44}, 1))
        for faults, expected in cases:
            with self.subTest(faults=faults):
                mode = "exit-status" if SLUG == "microsandbox" and "NEGATIVE_RC" in faults else "guest"
                result, calls = self.helper_fixture(mode, **faults)
                self.assertEqual(result.returncode, expected, result.stderr)
                if SLUG == "microsandbox" or "CREATE_RC" in faults:
                    tool = "docker" if SLUG == "libkrun" else "msb"
                    self.assertTrue(any(c[:2] == [tool, "rm"] for c in calls))

    def test_metadata_public_caveats_only_describe_requirements_and_history(self):
        page = yaml.safe_load(PAGE.read_text().split("---", 2)[1])
        caveat = page["optional_info"]["support_caveats"]
        for implementation_word in ("dashboard", "workflow", "GitHub", "runner", "smoke"):
            self.assertNotIn(implementation_word, caveat)
        self.assertIn("Implementation status:", page["optional_hidden_info"]["other_info"])

    def test_guest_c_consumer_defines_uid_gid_types_before_libkrun_header(self):
        clt = Path("/Library/Developer/CommandLineTools/usr/bin/clang")
        compiler = str(clt) if clt.is_file() else shutil.which("cc")
        self.assertIsNotNone(compiler, "A C compiler is required for this compile-only fixture")
        compile_command = [compiler]
        if clt.is_file():
            compile_command += ["-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"]
        source = re.search(r"<<'C'\n(.*?)\nC\n", HELPER.read_text(), re.S).group(1)
        self.assertLess(source.index("#include <sys/types.h>"), source.index("#include <libkrun.h>"))
        # Match upstream's requirement that the consumer supplies uid_t/gid_t.
        # This synthetic header is compile evidence only, not native libkrun/KVM evidence.
        header = """#include <stdint.h>
int32_t krun_setuid(uint32_t, uid_t);
int32_t krun_setgid(uint32_t, gid_t);
int32_t krun_create_ctx(void);
int32_t krun_set_vm_config(uint32_t, uint8_t, uint32_t);
int32_t krun_set_root(uint32_t, const char *);
int32_t krun_set_workdir(uint32_t, const char *);
int32_t krun_set_exec(uint32_t, const char *, const char *const[], const char *const[]);
int32_t krun_start_enter(uint32_t);
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "libkrun.h").write_text(header)
            consumer = root / "guest.c"
            for label, text, accepted in [
                ("correct order", source, True),
                ("missing types", source.replace("#include <sys/types.h>\n", ""), False),
                ("types too late", source.replace(
                    "#include <sys/types.h>\n#include <libkrun.h>",
                    "#include <libkrun.h>\n#include <sys/types.h>",
                ), False),
            ]:
                with self.subTest(case=label):
                    consumer.write_text(text)
                    result = subprocess.run(
                        [*compile_command, "-std=c11", "-Wall", "-Wextra", "-Werror",
                         "-fsyntax-only", "-I", str(root), str(consumer)],
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    if not accepted:
                        self.assertIn("uid_t", result.stderr)


if __name__ == "__main__":
    unittest.main()
