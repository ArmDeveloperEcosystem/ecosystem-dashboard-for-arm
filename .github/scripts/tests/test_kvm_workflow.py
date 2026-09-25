"""Test actual build/ABI workflow bodies; successes are synthetic, not native or VM evidence."""

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
VERSION = f"build-abi@{RELEASE}"
HEADER_PATHS = ("/usr/include/linux/kvm.h", "/usr/include/aarch64-linux-gnu/asm/kvm.h")
HEADER_REVISION = "6.8.0-79.79"
HEADER_CONTENTS = (b"synthetic generic KVM header\n", b"synthetic Arm64 KVM header\n")

# Mock OS/package/program boundaries in a child interpreter. Production shell
# and Python bodies are extracted verbatim; no native binary or VM is executed.
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
original_read_bytes = Path.read_bytes
original_is_file = Path.is_file
original_run = subprocess.run
header_paths = ("/usr/include/linux/kvm.h", "/usr/include/aarch64-linux-gnu/asm/kvm.h")
image_path = "/boot/vmlinuz-" + release
config_path = "/boot/config-" + release
package_paths = (image_path, config_path) + header_paths
files = fault.get("files", {})

def file_record(path):
    default_package = "linux-libc-dev" if path in header_paths else package
    default_revision = "6.8.0-79.79" if path in header_paths else revision
    record = dict(package=default_package, revision=default_revision)
    record.update(files.get(path, {}))
    return record

def read_text(path, *args, **kwargs):
    if str(path) == "/proc/sys/kernel/osrelease":
        return fault.get("proc_release", release) + "\n"
    if str(path) == "/proc/version_signature":
        if fault.get("missing_signature"):
            raise FileNotFoundError(str(path))
        return fault.get("signature", "Ubuntu " + revision + "-" + release.split("-", 2)[2] + " 6.17.12\n")
    if str(path) == config_path:
        return file_record(config_path).get("text", "CONFIG_ARM64=y\nCONFIG_KVM=y\n")
    return original_read_text(path, *args, **kwargs)

def read_bytes(path):
    if str(path) in header_paths:
        record = file_record(str(path))
        if "text" in record:
            return record["text"].encode()
        return original_read_bytes(Path(os.environ["KVM_SMOKE_DIR"]) /
                                   ("header-" + str(header_paths.index(str(path)))))
    return original_read_bytes(path)

def is_file(path):
    if str(path) in package_paths:
        return not (file_record(str(path)).get("missing") or
                    (str(path) == image_path and fault.get("missing_image")))
    return original_is_file(path)

last_path = None
program_calls = 0

def run(args, **kwargs):
    global last_path, program_calls
    assert kwargs == dict(capture_output=True, text=True, timeout=12), kwargs
    with open(os.environ["SYNTHETIC_CALLS"], "a") as stream:
        stream.write(json.dumps(list(args)) + "\n")
    if args[0] == "dpkg-query":
        if args[1] == "-S":
            assert args[2] in package_paths, args
            last_path = args[2]
            record = file_record(last_path)
            stdout = record.get("owner", record["package"] + ": " + last_path + "\n")
            if last_path == image_path:
                stdout = fault.get("owner", stdout)
        else:
            assert args[1:3] == ("-W", "-f=$"+"{Package}\t$"+"{Version}\t$"+"{Architecture}\t$"+"{Status}\n")
            record = file_record(last_path)
            assert args[3] == record["package"], args
            stdout = record.get("row", record["package"] + "\t" + record["revision"] +
                                "\tarm64\tinstall ok installed\n")
            if last_path == image_path:
                stdout = fault.get("row", stdout)
        if record.get("timeout") or fault.get("pm_timeout"):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, record.get("rc", fault.get("pm_rc", 0)),
            stdout, record.get("stderr", fault.get("pm_stderr", "")))
    assert args[0] == os.environ["KVM_SMOKE_DIR"] + "/smoke", args
    if fault.get("timeout"):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    if fault.get("actual_timeout"):
        return original_run(["/bin/sleep", "30"], **kwargs)
    assert len(args) == 2, args
    program_calls += 1
    value = int(args[1])
    address = (value + 1) * 4096
    expected = dict(scope="build-abi-only", header_api=12, memory_size=32,
        one_reg_size=16, vcpu_init_size=32, x0_id=0x6030000000100000,
        pc_id=0x6030000000100040, pstate_id=0x6030000000100042,
        get_api_request=0xAE00, create_vm_request=0xAE01,
        set_memory_request=0x4020AE46, set_one_reg_request=0x4010AEAC,
        input=value, slot=value, flags=1, guest_address=address, region_bytes=4096,
        userspace_address=address + 8192, register_id=0x6030000000100040,
        register_address=address)
    output_fault = fault if fault.get("at_call", program_calls) == program_calls else {}
    expected.update(output_fault.get("result", {}))
    for key in output_fault.get("omit", []):
        expected.pop(key, None)
    stdout = output_fault.get("stdout", json.dumps(expected) + "\n")
    if "duplicate" in output_fault:
        key = output_fault["duplicate"]
        stdout = "{" + json.dumps(key) + ":" + json.dumps(expected[key]) + "," + stdout[1:]
    return subprocess.CompletedProcess(args, fault.get("rc", 0), stdout, fault.get("stderr", ""))

sys.argv = sys.argv[1:]
with mock.patch.object(platform, "uname", return_value=SimpleNamespace(
        system=fault.get("system", "Linux"), machine=fault.get("arch", "aarch64"), release=release)), \
     mock.patch.object(platform, "freedesktop_os_release", return_value={
        "ID": fault.get("distro", "ubuntu"), "VERSION_ID": fault.get("distro_version", "24.04")}), \
     mock.patch.object(Path, "read_text", read_text), \
     mock.patch.object(Path, "read_bytes", read_bytes), \
     mock.patch.object(Path, "is_file", is_file), \
     mock.patch.object(subprocess, "run", run):
    runpy.run_path(sys.argv[0], run_name="__main__")
'''

# The compiler boundary emits synthetic ELF bytes and never invokes a compiler.
COMPILER_FIXTURE = r'''
import json
import os
from pathlib import Path
import sys

driver = Path(os.environ["KVM_SMOKE_DIR"])
with open(os.environ["SYNTHETIC_CALLS"], "a") as stream:
    stream.write(json.dumps(["gcc"] + sys.argv[1:]) + "\n")
assert sys.argv[1:] == ["-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(driver / "smoke.c"), "-o", str(driver / "smoke")]
assert all(key not in os.environ for key in
           ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH"))
assert (driver / "smoke.c").is_file()
rc = int(os.environ["GCC_RC"])
if rc:
    sys.exit(rc)
fault = json.loads(os.environ.get("SYNTHETIC_FAULT", "{}"))
if not fault.get("compiler_missing_output"):
    binary = driver / "smoke"
    binary.write_bytes((driver / "synthetic-elf").read_bytes())
    binary.chmod(0o644 if fault.get("compiler_nonexecutable") else 0o755)
for index in fault.get("compiler_changes_headers", []):
    (driver / ("header-" + str(index))).write_bytes(b"changed during compilation\n")
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
        for name in ("date", "cat", "mkdir", "cmp"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.tool("sha256sum", 'test "$SHA256_RC" = 0\n' +
                  f'exec "{sys.executable}" -c \'import hashlib, pathlib, sys; '
                  'print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(), '
                  '" ", sys.argv[1], sep="")\' "$@"\n')
        self.tool("bash", 'test "$*" = \'.github/actions/apt-bootstrap/bootstrap.sh --packages gcc libc6-dev linux-libc-dev python3\'\nexit "$APT_RC"\n')
        self.tool("uname", 'case "$1" in -m) echo "$ARCH";; -s) echo Linux;; *) exit 99;; esac\n')
        compiler = self.root / "compiler-fixture.py"
        compiler.write_text(COMPILER_FIXTURE)
        self.tool("gcc", f'exec "{sys.executable}" "{compiler}" "$@"\n')
        launcher = self.root / "python-fixture.py"
        launcher.write_text(PYTHON_FIXTURE)
        self.tool("python3", f'exec "{sys.executable}" "{launcher}" "$@"\n')
        self.script = self.driver / "check.py"
        self.script.write_text(embedded(self.steps["install"], "PY"))
        self.c_source = embedded(self.steps["install"], "C")
        (self.driver / "smoke.c").write_text(self.c_source)
        for index, content in enumerate(HEADER_CONTENTS):
            (self.driver / f"header-{index}").write_bytes(content)
        # Synthetic ELF metadata, never executed even when a fixture sets +x.
        raw = bytearray(64)
        raw[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<H", raw, 16, 3)
        struct.pack_into("<H", raw, 18, 183)
        (self.driver / "synthetic-elf").write_bytes(raw)
        self.binary = self.driver / "smoke"
        self.binary.write_bytes(raw)
        self.env = dict(PATH=str(self.bin), HOME=str(self.root), TMPDIR=str(self.root),
                        KVM_SMOKE_DIR=str(self.driver), LC_ALL="C",
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_STEP_SUMMARY=str(self.root / "summary"),
                        PYTHONDONTWRITEBYTECODE="1", ARCH="aarch64", APT_RC="0", GCC_RC="0",
                        SHA256_RC="0",
                        SYNTHETIC_CALLS=str(self.root / "calls"))
        self.values = {
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.test4.outputs.harness_sha256": hashlib.sha256(raw).hexdigest(),
            "steps.version.outcome": "success",
            "steps.version.outputs.status": "passed",
            "steps.version.outputs.version": VERSION,
            "steps.version.outputs.kernel_package": PACKAGE,
            "steps.version.outputs.package_version": REVISION,
            "steps.test6.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.current_version": VERSION,
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
                "exit.txt": str(result.returncode), "EVIDENCE-TYPE.txt": "SYNTHETIC ONLY; NO NATIVE COMPILATION, ABI EXECUTION OR VM EXECUTION\n",
                "workflow-sha256.txt": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()}.items():
                (target / name).write_text(text)
        return result, outputs

    def rejected(self, step, fault=None, **env):
        result, outputs = self.run_step(step, fault, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("AssertionError", result.stderr, "Fixture error must not count as workflow rejection")
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

    def passed(self, step, fault=None, **env):
        result, outputs = self.run_step(step, fault, **env)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs.get("status"))
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        return result, outputs

    def recorded_calls(self, command=None):
        path = self.root / "calls"
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [call for call in calls if command is None or call[0] == command]

    def test_synthetic_package_owned_running_kernel_identity(self):
        for fault in ({}, {"package": "linux-image-unsigned-" + RELEASE},
                      {"owner": PACKAGE + ":arm64: /boot/vmlinuz-" + RELEASE + "\n"},
                      {"release": "6.8.0-1050-aws", "revision": "6.8.0-1050.53"}):
            with self.subTest(fault=fault):
                _, outputs = self.passed("version", fault)
                self.assertEqual("build-abi@" + fault.get("release", RELEASE), outputs["version"])
                self.assertEqual(fault.get("revision", REVISION), outputs["package_version"])
                self.assertEqual(fault.get("package", "linux-image-" + fault.get("release", RELEASE)),
                                 outputs["kernel_package"])

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
                  {"owner": PACKAGE + ":amd64: /boot/vmlinuz-" + RELEASE + "\n"},
                  {"owner": PACKAGE + ": /boot/vmlinuz-wrong\n"},
                  {"row": row.replace(PACKAGE, "linux-modules-" + RELEASE)},
                  {"signature": "Ubuntu " + REVISION + "-aws 6.17.12\nextra\n"},
                  {"pm_rc": 1}, {"pm_stderr": "query failed\n"}, {"pm_timeout": True}]
        for fault in faults:
            with self.subTest(fault=fault):
                self.rejected("version", fault)

    def test_version_check_requires_unchanged_verified_identity(self):
        self.passed("test1")
        for field in ("version", "kernel_package", "package_version"):
            key = f"steps.version.outputs.{field}"
            original = self.values[key]
            for bad in ("wrong", ""):
                self.values[key] = bad
                for step in ("test1", "test2", "test3", "test4", "test5"):
                    with self.subTest(field=field, bad=bad, step=step):
                        result = self.rejected(step)
                        self.assertIn("Verified kernel identity changed", result.stderr)
            self.values[key] = original

    def test_synthetic_config_accepts_signed_unsigned_and_modules_owners(self):
        path = "/boot/config-" + RELEASE
        for image_package in (PACKAGE, "linux-image-unsigned-" + RELEASE):
            self.values["steps.version.outputs.kernel_package"] = image_package
            for config_package in (PACKAGE, "linux-image-unsigned-" + RELEASE, "linux-modules-" + RELEASE):
                for qualifier in ("", ":arm64"):
                    with self.subTest(image=image_package, config=config_package, qualifier=qualifier):
                        fault = dict(package=image_package, files={path: dict(package=config_package,
                            owner=config_package + qualifier + ": " + path + "\n")})
                        result, _ = self.passed("test2", fault)
                        self.assertEqual(dict(config_owner=config_package, kernel_revision=REVISION,
                            scope="kernel-build-configuration-only"), json.loads(result.stdout))

    def test_config_rejects_missing_wrong_owner_arch_revision_and_duplicates(self):
        path = "/boot/config-" + RELEASE
        row = PACKAGE + "\t" + REVISION + "\tarm64\tinstall ok installed\n"
        owner = PACKAGE + ": " + path + "\n"
        for record in ({"missing": True}, {"owner": ""}, {"owner": owner * 2},
                       {"owner": owner.replace(path, "/boot/config-other")},
                       {"owner": owner.replace(PACKAGE, "linux-headers-" + RELEASE)},
                       {"owner": owner.replace(RELEASE, "6.8.0-31-generic")},
                       {"owner": owner.replace(": ", ":amd64: ")},
                       {"row": row * 2}, {"row": row.replace("arm64", "amd64")},
                       {"row": row.replace("installed", "unpacked")}, {"row": ""},
                       {"revision": REVISION + ".1"}, {"rc": 1},
                       {"stderr": "query warning\n"}, {"timeout": True}):
            with self.subTest(record=record):
                self.rejected("test2", {"files": {path: record}})

    def test_config_requires_exactly_one_builtin_arm64_and_kvm_flag(self):
        for key in ("CONFIG_ARM64", "CONFIG_KVM"):
            other = "CONFIG_KVM" if key == "CONFIG_ARM64" else "CONFIG_ARM64"
            for definition in ("", key + "=m\n", key + "=n\n", "# " + key + " is not set\n",
                               (key + "=y\n") * 2, key + "=y\n" + key + "=m\n",
                               key + "=y\n# " + key + " is not set\n", key + "=yes\n"):
                with self.subTest(key=key, definition=definition):
                    result = self.rejected("test2", {"files": {"/boot/config-" + RELEASE:
                        {"text": other + "=y\n" + definition}}})
                    self.assertIn("Expected one built-in " + key + "=y", result.stderr)

    def test_synthetic_headers_record_both_arm64_package_owners_and_digests(self):
        for qualified in (False, True):
            fault = {"files": {path: {"owner": "linux-libc-dev:arm64: " + path + "\n"}
                               for path in HEADER_PATHS}} if qualified else {}
            result, _ = self.passed("test3", fault)
            expected = dict(package="linux-libc-dev", version=HEADER_REVISION, architecture="arm64",
                            paths=list(HEADER_PATHS), sha256=[hashlib.sha256(raw).hexdigest()
                                                           for raw in HEADER_CONTENTS])
            self.assertEqual(expected, json.loads(result.stdout))
            self.assertEqual(expected, json.loads((self.driver / "headers.json").read_text()))
        calls = self.recorded_calls("dpkg-query")
        for path in HEADER_PATHS:
            self.assertEqual(2, calls.count(["dpkg-query", "-S", path]))

    def test_headers_reject_missing_ambiguous_wrong_package_arch_and_versions(self):
        row = "linux-libc-dev\t" + HEADER_REVISION + "\tarm64\tinstall ok installed\n"
        for path in HEADER_PATHS:
            owner = "linux-libc-dev: " + path + "\n"
            for record in ({"missing": True}, {"owner": ""}, {"owner": owner * 2},
                           {"owner": owner.replace("linux-libc-dev", "linux-headers-" + RELEASE)},
                           {"owner": owner.replace(path, "/usr/include/other/kvm.h")},
                           {"owner": owner.replace(": ", ":amd64: ")}, {"row": row * 2},
                           {"row": ""}, {"row": row.replace("arm64", "amd64")},
                           {"row": row.replace("installed", "unpacked")},
                           {"row": row.replace("linux-libc-dev", "other-package")},
                           {"revision": "unknown"}, {"revision": HEADER_REVISION + ".1"},
                           {"rc": 1}, {"stderr": "query warning\n"}, {"timeout": True}):
                with self.subTest(path=path, record=record):
                    self.rejected("test3", {"files": {path: record}})

    def test_synthetic_setup_extracts_exact_sources_without_compilation(self):
        result, outputs = self.run_step("install", GCC_RC="99")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"install_status": "success"}, outputs)
        self.assertEqual(self.c_source, (self.driver / "smoke.c").read_text())
        self.assertEqual(embedded(self.steps["install"], "PY"), self.script.read_text())
        self.assertEqual([], self.recorded_calls())

    def test_setup_failures_cannot_emit_success(self):
        for env in ({"ARCH": "x86_64"}, {"APT_RC": "100"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("install", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs.get("install_status"))
                self.assertNotIn("harness_sha256", outputs)

    def test_synthetic_compiler_hashes_output_and_clears_include_overrides(self):
        self.passed("test3")
        self.binary.unlink()
        _, outputs = self.passed("test4", CPATH="/wrong", C_INCLUDE_PATH="/wrong",
                                 CPLUS_INCLUDE_PATH="/wrong", OBJC_INCLUDE_PATH="/wrong")
        self.assertTrue(os.access(self.binary, os.X_OK))
        self.assertEqual(hashlib.sha256(self.binary.read_bytes()).hexdigest(), outputs["harness_sha256"])
        self.assertEqual(1, len(self.recorded_calls("gcc")))
        self.assertEqual([], self.recorded_calls(str(self.binary)))

    def test_compiler_failures_and_missing_nonexecutable_outputs_fail(self):
        self.passed("test3")
        for fault, env in (({}, {"GCC_RC": "1"}), ({}, {"GCC_RC": "127"}),
                           ({"compiler_missing_output": True}, {}),
                           ({"compiler_nonexecutable": True}, {}), ({}, {"SHA256_RC": "1"})):
            with self.subTest(fault=fault, env=env):
                self.binary.unlink(missing_ok=True)
                result, outputs = self.run_step("test4", fault, **env)
                self.assertNotEqual(0, result.returncode, result.stderr)
                self.assertEqual("failed", outputs.get("status"))
                self.assertNotIn("harness_sha256", outputs)

    def test_compilation_rejects_missing_or_changed_header_record_before_gcc(self):
        self.passed("test3")
        path = self.driver / "headers.json"
        original = path.read_bytes()
        for raw in (None, b"", b"{}\n", b"not JSON\n", original + b"\n"):
            with self.subTest(raw=raw):
                if raw is None:
                    path.unlink()
                else:
                    path.write_bytes(raw)
                self.rejected("test4")
                self.assertEqual([], self.recorded_calls("gcc"))
        path.write_bytes(original)
        for header in HEADER_PATHS:
            with self.subTest(header=header):
                self.rejected("test4", {"files": {header: {"text": "changed header\n"}}})
                self.assertEqual([], self.recorded_calls("gcc"))
        self.rejected("test4", {"files": {header: {"revision": HEADER_REVISION + ".1"}
                                           for header in HEADER_PATHS}})
        self.assertEqual([], self.recorded_calls("gcc"))

    def test_compilation_rejects_either_header_changing_during_gcc(self):
        for index in range(2):
            with self.subTest(index=index):
                self.passed("test3")
                result, outputs = self.run_step("test4", {"compiler_changes_headers": [index]})
                self.assertNotEqual(0, result.returncode, result.stderr)
                self.assertEqual("failed", outputs.get("status"))
                self.assertNotIn("harness_sha256", outputs)
        self.assertEqual(2, len(self.recorded_calls("gcc")))

    def test_synthetic_abi_checker_requires_zero_random_and_maximum_inputs(self):
        result, _ = self.passed("test5")
        calls = self.recorded_calls(str(self.binary))
        self.assertEqual(3, len(calls))
        self.assertEqual("0", calls[0][1])
        self.assertLess(int(calls[1][1]), 2**32)
        self.assertGreaterEqual(int(calls[1][1]), 0)
        self.assertEqual(str(2**32 - 1), calls[2][1])
        self.assertIn("VM execution is not tested", result.stdout)

    def test_abi_command_failures_diagnostics_and_timeouts_fail_closed(self):
        for fault in ({"rc": 1}, {"rc": 124}, {"rc": -11}, {"timeout": True},
                      {"stderr": "unexpected warning\n"}):
            with self.subTest(fault=fault):
                self.rejected("test5", fault)

    def test_actual_subprocess_deadline_reaches_failed_shell_output(self):
        result = self.rejected("test5", {"actual_timeout": True})
        self.assertIn("TimeoutExpired", result.stderr)

    def test_missing_malformed_duplicate_and_wrong_abi_json_fail(self):
        for fault in ({"stdout": ""}, {"stdout": "QEMU emulator version 10.0\n"},
                      {"stdout": "{}\n{}\n"}, {"stdout": '{"header_api":12,"header_api":12}'},
                      {"stdout": "[]"}, {"stdout": "null"}, {"stdout": "true"},
                      {"stdout": "12"}, {"stdout": '"passed"'},
                      {"result": {"header_api": True}}, {"result": {"header_api": 12.0}},
                      {"result": {"header_api": "12"}}, {"result": {"slot": False}},
                      {"result": {"input": False}}, {"result": {"flags": True}},
                      {"result": {"scope": "native-kvm"}}, {"result": {"extra": 1}}):
            with self.subTest(fault=fault):
                self.rejected("test5", fault)

    def test_abi_rejects_each_wrong_or_missing_constant_and_structure_field(self):
        for key in ("header_api", "memory_size", "one_reg_size", "vcpu_init_size", "x0_id",
                    "pc_id", "pstate_id", "get_api_request", "create_vm_request",
                    "set_memory_request", "set_one_reg_request", "input", "slot", "flags",
                    "guest_address", "region_bytes", "userspace_address", "register_id",
                    "register_address", "scope"):
            for fault in ({"result": {key: -1}}, {"omit": [key]}):
                with self.subTest(key=key, fault=fault):
                    self.rejected("test5", fault)

    def test_abi_rejects_duplicate_keys_in_otherwise_valid_results(self):
        for key in ("header_api", "scope", "register_address"):
            with self.subTest(key=key):
                result = self.rejected("test5", {"duplicate": key})
                self.assertIn("Duplicate ABI result key", result.stderr)

    def test_abi_checks_random_and_maximum_structure_results_after_zero_passes(self):
        for call_index in (2, 3):
            for key in ("input", "slot", "guest_address", "userspace_address", "register_address"):
                with self.subTest(call_index=call_index, key=key):
                    before = len(self.recorded_calls(str(self.binary)))
                    result = self.rejected("test5", {"at_call": call_index, "result": {key: -1}})
                    self.assertIn("Incorrect native userspace ABI evidence", result.stderr)
                    calls = self.recorded_calls(str(self.binary))[before:]
                    self.assertEqual(call_index, len(calls))
                    self.assertEqual("0", calls[0][1])
                    if call_index == 3:
                        self.assertEqual(str(2**32 - 1), calls[-1][1])

    def test_abi_rejects_fake_cli_truncated_and_wrong_elf_metadata(self):
        original = self.binary.read_bytes()
        faults = [b"#!/bin/sh\necho passed\n", b"", original[:63]]
        for offset, value in ((0, 0), (4, 1), (5, 2), (6, 0), (16, 1), (18, 62)):
            raw = bytearray(original)
            raw[offset] = value
            faults.append(raw)
        for raw in faults:
            self.binary.write_bytes(raw)
            self.values["steps.test4.outputs.harness_sha256"] = hashlib.sha256(raw).hexdigest()
            with self.subTest(raw=raw):
                result = self.rejected("test5")
                self.assertIn("AArch64 ELF executable", result.stderr)
        self.assertEqual([], self.recorded_calls(str(self.binary)))

    def test_synthetic_abi_accepts_executable_and_pie_elf_types(self):
        for elf_type in (2, 3):
            raw = bytearray(self.binary.read_bytes())
            struct.pack_into("<H", raw, 16, elf_type)
            self.binary.write_bytes(raw)
            self.values["steps.test4.outputs.harness_sha256"] = hashlib.sha256(raw).hexdigest()
            self.passed("test5")

    def test_abi_rejects_missing_changed_binary_and_malformed_digests(self):
        digest = self.values["steps.test4.outputs.harness_sha256"]
        for bad in ("", "0" * 64, digest.upper(), digest[:63], "g" * 64, digest + "\n"):
            with self.subTest(digest=bad):
                self.values["steps.test4.outputs.harness_sha256"] = bad
                result = self.rejected("test5")
                self.assertIn("ABI binary changed after compilation", result.stderr)
        self.values["steps.test4.outputs.harness_sha256"] = digest
        self.binary.write_bytes(self.binary.read_bytes() + b"changed")
        self.rejected("test5")
        self.binary.unlink()
        self.rejected("test5")
        self.assertEqual([], self.recorded_calls(str(self.binary)))

    def test_compile_and_abi_require_original_prerequisite_outcomes(self):
        for step, prerequisite in (("test4", "test3"), ("test5", "test4")):
            for field, bad in (("outcome", "failure"), ("outcome", "cancelled"), ("outcome", "skipped"),
                               ("outcome", ""), ("outputs.status", "failed"),
                               ("outputs.status", "skipped"), ("outputs.status", "")):
                key = f"steps.{prerequisite}.{field}"
                original = self.values[key]
                self.values[key] = bad
                with self.subTest(step=step, field=field, bad=bad):
                    self.rejected(step)
                    self.assertEqual([], self.recorded_calls())
                self.values[key] = original

    def test_core_shells_require_successful_setup_and_identity_outcomes(self):
        for key, bad in (("steps.install.outcome", "failure"), ("steps.install.outcome", ""),
                         ("steps.install.outcome", "cancelled"), ("steps.install.outcome", "skipped"),
                         ("steps.install.outputs.install_status", "failed"),
                         ("steps.version.outcome", "failure"), ("steps.version.outcome", ""),
                         ("steps.version.outcome", "cancelled"), ("steps.version.outcome", "skipped"),
                         ("steps.version.outputs.status", "failed")):
            original = self.values[key]
            self.values[key] = bad
            for i in range(1, 6):
                self.rejected(f"test{i}")
            self.assertEqual([], self.recorded_calls())
            self.values[key] = original

    def test_identity_requires_successful_install_original_outcome(self):
        for field in ("outcome", "outputs.install_status"):
            key = "steps.install." + field
            original = self.values[key]
            for bad in ("failure", "failed", "", "cancelled", "skipped"):
                with self.subTest(field=field, bad=bad):
                    self.values[key] = bad
                    self.rejected("version")
                    self.assertEqual([], self.recorded_calls())
            self.values[key] = original

    def test_synthetic_actual_shell_pipeline_has_five_passes_and_one_pm_skip(self):
        for step in ("install", "version", "test1", "test2", "test3", "test4", "test5"):
            result, outputs = self.run_step(step)
            self.assertEqual(0, result.returncode, step + result.stderr)
            self.assertEqual("success" if step == "install" else "passed",
                             outputs.get("install_status" if step == "install" else "status"))
            self.values.update({f"steps.{step}.outputs.{key}": value for key, value in outputs.items()})
            self.values[f"steps.{step}.outcome"] = "success"
        regression = self.applicability()
        self.assertEqual("not_applicable_package_manager", regression["decision"])
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "success", "passing"),
                         tuple(summary[key] for key in
                               ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))
        self.validate_contract(summary, regression)

    def test_five_core_and_one_skip_satisfy_policy_and_exact_collector(self):
        regression = self.applicability()
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(dict(passed="5", failed="0", skipped="1", core_failed="0",
                              duration="15", overall_status="success", badge_status="passing"), summary)
        self.assertEqual("not_applicable_package_manager", regression["decision"])
        self.assertIn("build/ABI smoke only", regression["comparison"])
        self.assertIn("VM execution are not tested", regression["comparison"])
        self.assertEqual(VERSION, regression["current_version"])
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
        payload["package"] = dict(name=self.job["outputs"]["package_name"], version=VERSION)
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

    def test_failed_headers_compile_and_abi_are_publishable_failure(self):
        for i in (3, 4, 5):
            self.values[f"steps.test{i}.outputs.status"] = "failed"
            self.values[f"steps.test{i}.outcome"] = "failure"
        regression = self.applicability()
        self.assertEqual("baseline_failed", regression["decision"])
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("2", "3", "1", "3", "failure"),
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
                ("steps.version.outputs.version", RELEASE, "baseline_failed"),
                ("steps.version.outputs.version", "build-abi@", "baseline_failed"),
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
        self.assertTrue(observation_audit._step_emits_output(root, self.steps["test4"], "harness_sha256"))
        self.assertNotIn("qemu-", WORKFLOW.read_text().lower())
        for forbidden in ("sudo ", "modprobe", "mknod", "sysctl", "/dev/", "system(",
                          "ioctl(", "KVM_RUN", "open("):
            self.assertNotIn(forbidden, self.c_source)
        self.assertIn("#include <linux/kvm.h>", self.c_source)
        self.assertIn("!defined(__aarch64__)", self.c_source)
        self.assertIn("__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__", self.c_source)
        self.assertIn("_Static_assert(KVM_API_VERSION == 12", self.c_source)
        self.assertIn("memcpy(memory_bytes, &region, sizeof(region))", self.c_source)
        self.assertIn("memcpy(reg_bytes, &reg, sizeof(reg))", self.c_source)

    def test_visible_scope_names_and_free_arm_runner_are_preserved(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual({"test-kvm"}, set(workflow["jobs"]))
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertNotIn("strategy", self.job)
        self.assertNotIn("container", self.job)
        self.assertIn("build/ABI", self.job["outputs"]["package_name"])
        self.assertIn("VM execution not tested", self.job["outputs"]["package_name"])
        self.assertIn("steps.version.outputs.version", self.job["outputs"]["package_version"])
        self.assertIn("build/ABI scope", self.steps["version"]["name"])
        self.assertEqual({f"test{i}" for i in range(1, 7)},
                         {step for step in self.steps if re.fullmatch(r"test[0-9]+", step)})
        for i in range(1, 6):
            self.assertIn("build/ABI", self.steps[f"test{i}"]["name"])
            self.assertLessEqual(self.steps[f"test{i}"]["timeout-minutes"], 2)
        self.assertIn("VM execution not tested", self.steps["test5"]["name"])
        summary = next(step["run"] for step in self.job["steps"]
                       if "GITHUB_STEP_SUMMARY" in step.get("run", ""))
        self.assertIn("Hardware-assisted virtualization and VM execution are not tested", summary)

    def test_all_shell_bodies_have_valid_bash_syntax(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["/bin/bash", "-n"], input=self.render(step["run"]),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)


if __name__ == "__main__":
    unittest.main()
