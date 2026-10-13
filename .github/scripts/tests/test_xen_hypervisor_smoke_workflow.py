"""Exercise actual workflow shells; command fixtures are not native Xen evidence."""

import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_result_policy as result_policy

WORKFLOW = ROOT / ".github/workflows/test-xen-hypervisor.yml"
SOURCE = ROOT / ".github/scripts/xen_toolstack_smoke.c"
VERSION = "4.17.3+10-g091466ba55-1.1ubuntu3"
PACKAGES = ("xen-utils-4.17", "xenstore-utils", "libxen-dev", "libxenmisc4.17t64")
BASH = os.environ.get("XEN_WORKFLOW_BASH", "/bin/bash")
BASH_MAJOR = int(subprocess.check_output(
    [BASH, "-c", 'printf "%s" "${BASH_VERSINFO[0]}"'], text=True))


class XenHypervisorWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="xen-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.document = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.document["jobs"]["test-xen-hypervisor"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.xen_bin = self.root / "xen-bin"
        self.xen_bin.mkdir()
        self.client = self.bin / "xenstore"
        self.library = self.root / "libxlutil.so"
        self.library.write_bytes(b"ELF identity fixture, not a native library")
        scripts = self.root / ".github/scripts"
        scripts.mkdir(parents=True)
        (scripts / SOURCE.name).symlink_to(SOURCE)
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RUNNER_TEMP": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "GITHUB_ENV": str(self.root / "github-env"),
            "XEN_PACKAGE": "xen-utils-4.17",
            "XEN_PACKAGE_VERSION": VERSION,
            "XEN_BIN": str(self.xen_bin),
            "FIXTURE_VERSION": VERSION,
            "FIXTURE_CLIENT": str(self.client),
            "FIXTURE_LIBRARY": str(self.library),
            "CALL_LOG": str(self.root / "calls"),
        }
        self.values = {
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": VERSION,
            "steps.test6.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.duration": "0",
        }
        for number in range(1, 6):
            self.values.update({
                f"steps.test{number}.outcome": "success",
                f"steps.test{number}.outputs.status": "passed",
                f"steps.test{number}.outputs.duration": str(number),
            })
        self.tool("uname", """
key = {"-s": "HOST_OS", "-m": "HOST_ARCH"}[sys.argv[1]]
print(os.environ.get(key, "Linux" if key == "HOST_OS" else "aarch64"))
""")
        self.tool("dpkg", """
assert sys.argv[1:] == ["--print-architecture"]
print(os.environ.get("DPKG_ARCH", "arm64"))
""")
        self.tool("dpkg-query", """
if os.environ.get("QUERY_RC"):
    sys.exit(int(os.environ["QUERY_RC"]))
args = sys.argv[1:]
if args[0] == "-S":
    assert len(args) == 2
    owners = {os.environ["XEN_BIN"] + "/xenstored": "xen-utils-4.17",
              os.environ["FIXTURE_CLIENT"]: "xenstore-utils"}
    owner = os.environ.get("OWNER_OVERRIDE", owners[args[1]])
    print(owner + ": " + args[1])
else:
    assert len(args) == 3 and args[0] == "-W"
    assert args[2] in ("xen-utils-4.17", "xenstore-utils", "libxen-dev", "libxenmisc4.17t64")
    fields = {"-f=${Version}": ("PACKAGE_VERSION", os.environ["FIXTURE_VERSION"]),
              "-f=${Status}": ("PACKAGE_STATUS", "install ok installed"),
              "-f=${Architecture}": ("PACKAGE_ARCH", "arm64")}
    variable, default = fields[args[1]]
    if args[2] == os.environ.get("FAULT_PACKAGE", "xen-utils-4.17"):
        print(os.environ.get(variable, default), end="")
    else:
        print(default, end="")
""")
        self.tool("readelf", """
assert sys.argv[1] == "-h"
assert sys.argv[2] in (os.environ["XEN_BIN"] + "/xenstored",
                       os.environ["FIXTURE_CLIENT"], os.environ["FIXTURE_LIBRARY"])
affected = os.environ.get("ELF_TARGET", sys.argv[2]) == sys.argv[2]
print("ELF Header:")
print("  Class:   " + (os.environ.get("ELF_CLASS", "ELF64") if affected else "ELF64"))
print("  Machine: " + (os.environ.get("ELF_MACHINE", "AArch64") if affected else "AArch64"))
sys.exit(int(os.environ.get("ELF_RC", "0")) if affected else 0)
""")
        self.tool("timeout", """
assert sys.argv[1].endswith("s")
try:
    result = subprocess.run(sys.argv[2:], timeout=int(sys.argv[1][:-1]))
    sys.exit(result.returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
""")
        self.tool("xenstore", "sys.exit(99)\n")
        self.tool("xenstored", """
assert sys.argv[1:] == ["--help"], "No daemon or device operations permitted"
print(os.environ.get("HELP_TEXT", "xenstored <options>\\n--no-domain-init"))
sys.exit(int(os.environ.get("HELP_RC", "0")))
""", directory=self.xen_bin)
        bootstrap = self.root / ".github/actions/apt-bootstrap"
        bootstrap.mkdir(parents=True)
        (bootstrap / "bootstrap.sh").write_text(
            '#!/bin/bash\nset -eu\n'
            'printf "apt-bootstrap %s\\n" "$*" >> "$CALL_LOG"\n'
            'exit "${INSTALL_RC:-0}"\n')
        self.tool("gcc", """
args = sys.argv[1:]
for flag in ("-std=c11", "-Wall", "-Wextra", "-Werror", "-lxlutil"):
    assert flag in args
assert ".github/scripts/xen_toolstack_smoke.c" in args
assert Path(".github/scripts/xen_toolstack_smoke.c").is_file()
if os.environ.get("COMPILE_RC"):
    sys.exit(int(os.environ["COMPILE_RC"]))
output = Path(args[args.index("-o") + 1])
assert output.parent.parent == Path(os.environ["RUNNER_TEMP"])
if not os.environ.get("NO_COMPILED_BINARY"):
    output.write_text("#!/bin/bash\\nset -eu\\n"
                      "test \\\"$#\\\" -eq 0\\n"
                      "printf 'parser-executed\\\\n' >> \\\"$CALL_LOG\\\"\\n"
                      "printf 'xen-toolstack-smoke-ok\\\\n'\\n"
                      "exit \\\"${SMOKE_RC:-0}\\\"\\n")
    output.chmod(0o755)
""")

    def tool(self, name, source, directory=None):
        path = (directory or self.bin) / name
        path.write_text(
            f"#!{sys.executable}\n"
            "import os, subprocess, sys\nfrom pathlib import Path\n"
            "with open(os.environ['CALL_LOG'], 'a') as log:\n"
            "    log.write(Path(sys.argv[0]).name + ' ' + repr(sys.argv[1:]) + '\\n')\n"
            + source)
        path.chmod(0o755)
        return path

    def render(self, text):
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
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def run_step(self, name, **overrides):
        step = self.steps[name]
        script = self.render(step["run"])
        # Relocate only fixed filesystem paths; retain the workflow's shell logic.
        script = script.replace("/usr/bin/xenstore", str(self.client))
        script = script.replace("/usr/lib/aarch64-linux-gnu/libxlutil.so", str(self.library))
        env = {**self.env,
               **{key: self.render(str(value)) for key, value in step.get("env", {}).items()},
               **overrides}
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        process = subprocess.run(
            [BASH, "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=env, text=True, capture_output=True, timeout=30)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return process, outputs

    def assert_failed_check(self, name, **overrides):
        process, outputs = self.run_step(name, **overrides)
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(outputs.get("status"), "failed")
        self.assertRegex(outputs.get("duration", ""), r"^[0-9]+$")
        return process, outputs

    def assert_failed_summary(self):
        process, outputs = self.run_step("summary")
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(outputs["overall_status"], "failure")
        self.assertEqual(outputs["badge_status"], "failing")
        self.assertEqual(sum(int(outputs[key]) for key in ("passed", "failed", "skipped")), 6)
        return outputs

    def run_regression(self):
        process, outputs = self.run_step("test6")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(outputs["status"], "skipped")
        self.assertEqual(outputs["duration"], "0")
        self.values.update({f"steps.test6.outputs.{key}": value
                            for key, value in outputs.items()})
        self.values["steps.test6.outcome"] = "success"
        return outputs

    def validate_summary(self, summary, core_statuses):
        details = [{"name": self.steps[f"test{number}"]["name"], "status": status}
                   for number, status in enumerate(core_statuses, 1)]
        decision = self.values["steps.test6.outputs.decision"]
        details.append({"name": self.steps["test6"]["name"],
                        "status": self.values["steps.test6.outputs.status"],
                        "decision": decision})
        return result_policy.validate_six_test_result(
            details=details, passed=int(summary["passed"]), failed=int(summary["failed"]),
            skipped=int(summary["skipped"]), core_failed=int(summary["core_failed"]),
            decision=decision)

    def test_helper_and_test_changes_are_in_foundation_ci_scope(self):
        path = ROOT / ".github/workflows/exact-run-aggregation-foundation-ci.yml"
        foundation = yaml.safe_load(path.read_text())
        scope = next(step for step in foundation["jobs"]["exact-run-contract"]["steps"]
                     if step.get("id") == "scope")
        for source in (SOURCE, Path(__file__)):
            self.assertIn(source.relative_to(ROOT).as_posix(), scope["run"])

    def test_contract_is_free_arm_runner_and_explicit_userspace_only(self):
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertIn("no hypervisor boot", self.document["name"])
        self.assertIn("not tested", self.job["outputs"]["package_name"])
        self.assertEqual(self.steps["summary"]["if"], "always()")
        self.assertEqual(self.steps["test6"]["if"], "always()")
        self.assertEqual(set(self.steps["test6"]["env"]),
                         {"CURRENT_VERSION", "INSTALL_OUTCOME", "INSTALL_STATUS",
                          "VERSION_OUTCOME", "CORE_RESULTS"})
        for number in range(1, 6):
            self.assertTrue(self.steps[f"test{number}"]["continue-on-error"])
            self.assertIn("steps.install.outcome == 'success'", self.steps[f"test{number}"]["if"])
        self.assertIn("--no-install-recommends true", self.steps["install"]["run"])
        self.assertNotIn("xen-hypervisor-4.17-arm64", self.steps["install"]["run"])
        self.assertNotIn("xen-system-arm64", self.steps["install"]["run"])

    def test_install_success_and_bootstrap_failure(self):
        process, outputs = self.run_step("install")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(outputs, {"install_status": "success"})
        for env in ({"INSTALL_RC": "19"}, {"HOST_ARCH": "x86_64"}):
            with self.subTest(env=env):
                process, outputs = self.run_step("install", **env)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotEqual(outputs.get("install_status"), "success")

    def test_install_and_binary_check_reject_missing_or_nonexecutable_tools(self):
        for path in (self.xen_bin / "xenstored", self.client):
            with self.subTest(path=path):
                path.chmod(0o644)
                process, outputs = self.run_step("install")
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn("install_status", outputs)
                self.assert_failed_check("test1")
                path.chmod(0o755)
        self.client.unlink()
        self.assert_failed_check("test1")

    def test_version_is_full_installed_ubuntu_revision(self):
        process, outputs = self.run_step("version")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(outputs, {"version": VERSION})
        self.assertIn("XEN_PACKAGE_VERSION=" + VERSION, (self.root / "github-env").read_text())
        for env in ({"QUERY_RC": "1"},
                    {"PACKAGE_STATUS": "deinstall ok config-files"}):
            with self.subTest(env=env):
                process, outputs = self.run_step("version", **env)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn("version", outputs)

    @unittest.skipIf(BASH_MAJOR < 4, "Version regex errexit requires the hosted runner's Bash 4+")
    def test_version_rejects_empty_malformed_or_wrong_release_revision(self):
        for version in ("", "unknown", "4.20.0-1", "4.17", "4.17.3\n4.17.3"):
            with self.subTest(version=version):
                process, outputs = self.run_step("version", PACKAGE_VERSION=version)
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertNotIn("version", outputs)

    def test_all_five_actual_check_shells_accept_valid_fixtures(self):
        for number in range(1, 6):
            with self.subTest(number=number):
                process, outputs = self.run_step(f"test{number}")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(outputs["status"], "passed")
                self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_binary_ownership_query_and_wrong_owner_fail(self):
        self.assert_failed_check("test1", OWNER_OVERRIDE="unrelated-package")
        self.assert_failed_check("test1", QUERY_RC="1")

    def test_every_package_requires_matching_version_status_and_arm_architecture(self):
        for package in PACKAGES:
            for fault in ({"PACKAGE_VERSION": "4.17.3+10-g091466ba55-1.1ubuntu99"},
                          {"PACKAGE_STATUS": "deinstall ok config-files"},
                          {"PACKAGE_ARCH": "amd64"}):
                with self.subTest(package=package, fault=fault):
                    self.assert_failed_check("test2", FAULT_PACKAGE=package, **fault)
        self.assert_failed_check("test2", XEN_PACKAGE_VERSION="")
        self.assert_failed_check("test2", QUERY_RC="1")

    def test_help_requires_successful_execution_and_both_expected_options(self):
        for env in ({"HELP_RC": "1"}, {"HELP_RC": "124"}, {"HELP_TEXT": ""},
                    {"HELP_TEXT": "xenstored <options>"},
                    {"HELP_TEXT": "other-program --no-domain-init"}):
            with self.subTest(env=env):
                self.assert_failed_check("test3", **env)

    def test_host_and_package_architecture_must_be_native_linux_arm64(self):
        for env in ({"HOST_OS": "Darwin"}, {"HOST_ARCH": "x86_64"},
                    {"HOST_ARCH": "armv7l"}, {"DPKG_ARCH": "amd64"}):
            with self.subTest(env=env):
                self.assert_failed_check("test4", **env)

    def test_each_elf_header_must_be_read_successfully_and_be_aarch64_elf64(self):
        for path in (self.xen_bin / "xenstored", self.client, self.library):
            for fault in ({"ELF_RC": "1"}, {"ELF_CLASS": "ELF32"},
                          {"ELF_MACHINE": "Advanced Micro Devices X86-64"}):
                with self.subTest(path=path, fault=fault):
                    self.assert_failed_check("test4", ELF_TARGET=str(path), **fault)

    def test_functional_step_executes_program_and_cleans_temporary_build(self):
        process, outputs = self.run_step("test5")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(outputs["status"], "passed")
        calls = (self.root / "calls").read_text()
        self.assertIn("gcc ", calls)
        self.assertIn("parser-executed\n", calls)
        self.assertEqual(list(self.root.glob("xen-parser.*")), [])

    def test_compiler_failure_missing_executable_and_parser_failure_fail_closed(self):
        for env in ({"COMPILE_RC": "7"}, {"NO_COMPILED_BINARY": "1"},
                    {"SMOKE_RC": "1"}, {"SMOKE_RC": "124"}):
            with self.subTest(env=env):
                self.assert_failed_check("test5", **env)
                self.assertEqual(list(self.root.glob("xen-parser.*")), [])

    def test_package_manager_lane_skips_regression_without_running_commands(self):
        outputs = self.run_regression()
        self.assertEqual(outputs["decision"], "not_applicable_package_manager")
        self.assertEqual(outputs["current_version"], VERSION)
        self.assertEqual(outputs["latest_version"], "not_applicable")
        self.assertEqual(outputs["next_installed_version"], "not_applicable")
        self.assertEqual(outputs["duration"], "0")
        self.assertFalse((self.root / "calls").exists())

    def test_regression_prioritizes_failed_install_or_version_over_failed_cores(self):
        faults = [(key, bad)
                  for key in ("steps.install.outcome", "steps.install.outputs.install_status",
                              "steps.version.outcome")
                  for bad in ("", "failure", "skipped", "cancelled")]
        faults += [("steps.version.outputs.version", bad) for bad in ("", "unknown")]
        for key, bad in faults:
            with self.subTest(key=key, bad=bad):
                original = dict(self.values)
                self.values[key] = bad
                self.values["steps.test5.outcome"] = "failure"
                self.values["steps.test5.outputs.status"] = "failed"
                outputs = self.run_regression()
                self.assertEqual(outputs["decision"], "baseline_install_failed")
                self.assertEqual(outputs["current_version"],
                                 self.values.get("steps.version.outputs.version") or "unknown")
                self.assert_failed_summary()
                self.values = original

    def test_summary_counts_five_baselines_and_one_policy_skip(self):
        self.assertEqual(self.run_regression()["decision"], "not_applicable_package_manager")
        process, outputs = self.run_step("summary")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(outputs, {"passed": "5", "failed": "0", "skipped": "1",
                                   "core_failed": "0", "duration": "15",
                                   "overall_status": "success", "badge_status": "passing"})
        self.assertEqual(self.validate_summary(outputs, ["passed"] * 5), "success")

    def test_each_actual_check_failure_produces_a_failed_summary(self):
        faults = {"test1": {"OWNER_OVERRIDE": "wrong-package"},
                  "test2": {"PACKAGE_VERSION": "4.17.4-1"},
                  "test3": {"HELP_RC": "1"},
                  "test4": {"HOST_ARCH": "x86_64"},
                  "test5": {"COMPILE_RC": "1"}}
        for step, env in faults.items():
            with self.subTest(step=step):
                original = dict(self.values)
                _, outputs = self.assert_failed_check(step, **env)
                self.values.update({f"steps.{step}.outputs.{key}": value
                                    for key, value in outputs.items()})
                self.values[f"steps.{step}.outcome"] = "failure"
                self.assertEqual(self.run_regression()["decision"], "baseline_failed")
                summary = self.assert_failed_summary()
                self.assertEqual(summary["core_failed"], "1")
                self.assertEqual(summary["passed"], "4")
                self.assertEqual(summary["failed"], "1")
                self.assertEqual(summary["skipped"], "1")
                core_statuses = [self.values[f"steps.test{i}.outputs.status"] for i in range(1, 6)]
                self.assertEqual(self.validate_summary(summary, core_statuses), "failure")
                self.values = original

    def test_summary_rejects_missing_core_statuses_and_unsuccessful_outcomes(self):
        for number in range(1, 6):
            for field, bad in (("outputs.status", ""), ("outputs.status", "skipped"),
                               ("outputs.status", "failed"), ("outputs.status", "unknown"),
                               ("outcome", ""),
                               ("outcome", "skipped"), ("outcome", "failure"),
                               ("outcome", "cancelled")):
                with self.subTest(number=number, field=field, bad=bad):
                    key = f"steps.test{number}.{field}"
                    original = dict(self.values)
                    self.values[key] = bad
                    self.assertEqual(self.run_regression()["decision"], "baseline_failed")
                    self.assert_failed_summary()
                    self.values = original

    def test_summary_cannot_mask_install_or_version_failure_with_five_passes(self):
        for key in ("steps.install.outcome", "steps.install.outputs.install_status",
                    "steps.version.outcome"):
            for bad in ("", "failure", "skipped", "cancelled"):
                with self.subTest(key=key, bad=bad):
                    original = dict(self.values)
                    self.values[key] = bad
                    self.assertEqual(self.run_regression()["decision"], "baseline_install_failed")
                    self.assert_failed_summary()
                    self.values = original

    def test_summary_rejects_invalid_regression_policy_results(self):
        for field, bad in (("outputs.status", "passed"), ("outputs.status", ""),
                           ("outputs.decision", ""), ("outputs.decision", "not_configured"),
                           ("outputs.decision", "baseline_failed"),
                           ("outputs.decision", "baseline_install_failed"),
                           ("outcome", "failure"), ("outcome", "skipped")):
            key = f"steps.test6.{field}"
            original = self.values[key]
            self.values[key] = bad
            self.assert_failed_summary()
            self.values[key] = original

    def test_all_missing_step_results_fail_closed(self):
        self.values.clear()
        outputs = self.run_regression()
        self.assertEqual(outputs["decision"], "baseline_install_failed")
        self.assertEqual(outputs["current_version"], "unknown")
        summary = self.assert_failed_summary()
        self.assertEqual(tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed")),
                         ("0", "0", "6", "0"))
        with self.assertRaisesRegex(ValueError, "test detail 1 has unsupported status 'skipped'"):
            self.validate_summary(summary, ["skipped"] * 5)

    def test_actual_install_failure_preserves_skipped_cores_and_rejects_publication(self):
        process, outputs = self.run_step("install", INSTALL_RC="19")
        self.assertNotEqual(process.returncode, 0)
        self.values["steps.install.outcome"] = "failure"
        self.values["steps.install.outputs.install_status"] = outputs.get("install_status", "")
        self.values["steps.version.outcome"] = "skipped"
        self.values.pop("steps.version.outputs.version")
        for number in range(1, 6):
            self.values[f"steps.test{number}.outcome"] = "skipped"
            self.values.pop(f"steps.test{number}.outputs.status")
            self.values.pop(f"steps.test{number}.outputs.duration")
        self.assertEqual(self.run_regression()["decision"], "baseline_install_failed")
        summary = self.assert_failed_summary()
        self.assertEqual(summary, {"passed": "0", "failed": "0", "skipped": "6",
                                   "core_failed": "0", "duration": "0",
                                   "overall_status": "failure", "badge_status": "failing"})
        with self.assertRaisesRegex(ValueError, "test detail 1 has unsupported status 'skipped'"):
            self.validate_summary(summary, ["skipped"] * 5)

    def test_each_skipped_core_remains_skipped_and_cannot_be_published(self):
        for number in range(1, 6):
            with self.subTest(number=number):
                original = dict(self.values)
                self.values[f"steps.test{number}.outcome"] = "skipped"
                self.values.pop(f"steps.test{number}.outputs.status")
                self.values.pop(f"steps.test{number}.outputs.duration")
                self.assertEqual(self.run_regression()["decision"], "baseline_failed")
                summary = self.assert_failed_summary()
                self.assertEqual(tuple(summary[key] for key in
                                       ("passed", "failed", "skipped", "core_failed")),
                                 ("4", "0", "2", "0"))
                core_statuses = ["passed"] * 5
                core_statuses[number - 1] = "skipped"
                with self.assertRaisesRegex(
                        ValueError, f"test detail {number} has unsupported status 'skipped'"):
                    self.validate_summary(summary, core_statuses)
                self.values = original

    def test_parser_uses_real_library_getters_and_no_hypervisor_context(self):
        source = SOURCE.read_text()
        for operation in ("xlu_cfg_readdata", "xlu_cfg_get_string", "xlu_cfg_get_long",
                          "xlu_cfg_get_list", "xlu_cfg_get_listitem", "xlu_cfg_destroy"):
            self.assertIn(operation + "(", source)
        for unsafe in ("libxl_ctx_alloc(", "xc_interface_open(", "/dev/xen", "system("):
            self.assertNotIn(unsafe, source)
        self.assertIn("detect-missing-kernel", source)
        self.assertIn("reject-malformed-syntax", source)
        self.assertIn("reject-nonnumeric-memory", source)
        self.assertIn("reject-list-as-number", source)


@unittest.skipUnless(os.environ.get("XEN_TOOLSTACK_SMOKE_BINARY"),
                     "Native parser executable is supplied separately by the native validation lane")
class NativeXenParserTests(unittest.TestCase):
    """Optionally exercise the real compiled harness; never substitute a fake library."""

    def run_parser(self, *args):
        return subprocess.run([os.environ["XEN_TOOLSTACK_SMOKE_BINARY"], *args],
                              text=True, capture_output=True, timeout=20)

    def test_no_arguments_validate_positive_and_negative_library_behaviors(self):
        process = self.run_parser()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        for label in ("valid-arm-guest", "reject-malformed-syntax", "reject-nonnumeric-memory",
                      "reject-list-as-number", "detect-missing-kernel"):
            self.assertIn("PASS " + label, process.stdout)
        self.assertEqual(process.stdout.splitlines()[-1], "xen-toolstack-smoke-ok")

    def test_runtime_inputs_are_returned_by_the_installed_parser(self):
        rng = random.Random(1102)
        for _ in range(4):
            name = f"arm-{rng.randrange(100000, 999999)}"
            memory, vcpus = rng.randrange(128, 8192), rng.randrange(1, 9)
            process = self.run_parser(name, str(memory), str(vcpus))
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertIn(f"name={name} memory={memory} vcpus={vcpus} kernel=/boot/Image-{name}",
                          process.stdout)

    def test_invalid_arguments_never_produce_success(self):
        for args in (("one",), ("", "256", "2"), ("bad'quote", "256", "2"),
                     ("a" * 64, "256", "2"), ("ok", "0", "2"), ("ok", "256", "-1"),
                     ("ok", "garbage", "2"), ("ok", "999999999999999999999", "2")):
            with self.subTest(args=args):
                process = self.run_parser(*args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertNotIn("xen-toolstack-smoke-ok", process.stdout)


if __name__ == "__main__":
    unittest.main()
