"""Execute the actual GDB workflow shell with deterministic identity and failure faults."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit
import package_result_policy as result_policy


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gdb.yml"
VERSION = "15.1"
REVISION = "15.1-1ubuntu1~24.04.1"
BANNER = f"GNU gdb (Ubuntu {REVISION}) {VERSION}\nCopyright (C) Free Software Foundation, Inc.\n"
FORMAT = "-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Package}\t${source:Upstream-Version}\n"
DEBUG_OUTPUT = "Breakpoint 1, main () at debug_test.c:4\n$1 = 42\nx is 42\n"


class GdbWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gdb-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("date", "grep", "cat", "rm"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "python3").symlink_to(sys.executable)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gdb"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(PATH=str(self.bin), HOME=str(self.root), TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        PYTHONDONTWRITEBYTECODE="1", PM_FORMAT=FORMAT,
                        CLI_STDOUT=BANNER, CLI_STDERR="", CLI_RC="0",
                        PM_OUTPUT=self.package_row(), PM_RC="0", FILES_RC="0",
                        PM_FILES=str(self.bin / "gdb") + "\n", PM_STDERR="",
                        HELP_OUTPUT="This is the GNU debugger.  Usage:\n\n    gdb [options] [executable-file [core-file or process-id]]\n",
                        HELP_RC="0", DEBUG_OUTPUT=DEBUG_OUTPUT, DEBUG_RC="0",
                        DEBUG_CALLS=str(self.root / "debug-calls"), GCC_RC="0",
                        SERVER_OUTPUT=f"GNU gdbserver (Ubuntu {REVISION}) {VERSION}\n",
                        SERVER_RC="0", APT_RC="0", ARCH="aarch64")
        self.values = {
            "steps.install.outcome": "success",
            "steps.version.outputs.version": VERSION,
            "steps.version.outputs.package_version": REVISION,
            "steps.version.outputs.status": "passed",
            "steps.version.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outcome": "success",
            "steps.test6.outputs.duration": "0",
        }
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.calls = 0
        self.tool("gdb", """
test "$LC_ALL" = C
case "$1" in
  --version)
    test "$#" = 1
    printf '%s' "$CLI_STDOUT"
    printf '%s' "$CLI_STDERR" >&2
    exit "$CLI_RC" ;;
  --help)
    test "$#" = 1
    printf '%s' "$HELP_OUTPUT"
    exit "$HELP_RC" ;;
  --nx)
    test "$*" = '--nx --batch --return-child-result -x gdb_cmds.txt ./debug_test'
    echo call >> "$DEBUG_CALLS"
    printf '%s' "$DEBUG_OUTPUT"
    exit "$DEBUG_RC" ;;
  *) exit 99 ;;
esac
""")
        self.tool("dpkg-query", """
test "$LC_ALL" = C
case "$1" in
  -W)
    test "$#" = 3
    test "$2" = "$PM_FORMAT"
    test "$3" = gdb
    printf '%s' "$PM_OUTPUT"
    printf '%s' "$PM_STDERR" >&2
    exit "$PM_RC" ;;
  -L)
    test "$#" = 2
    test "$2" = gdb
    printf '%s' "$PM_FILES"
    exit "$FILES_RC" ;;
  *) exit 99 ;;
esac
""")
        self.tool("gcc", """
test "$*" = '-g -O0 -o debug_test debug_test.c'
test -f debug_test.c
if [ "$GCC_RC" != 0 ]; then exit "$GCC_RC"; fi
: > debug_test
""")
        self.tool("sudo", 'exec "$@"\n')
        self.tool("apt-get", """
case "$*" in
  update|'install -y gdb gcc'|'install -y gdbserver') exit "$APT_RC" ;;
  *) exit 99 ;;
esac
""")
        self.tool("gdbserver", """
test "$#" = 1
test "$1" = --version
printf '%s' "$SERVER_OUTPUT"
exit "$SERVER_RC"
""")
        self.tool("uname", 'test "$*" = -m\nprintf "%s\\n" "$ARCH"\n')

    def package_row(self, version=VERSION, revision=REVISION):
        return f"gdb\tinstall ok installed\t{revision}\tarm64\tgdb\t{version}\n"

    def tool(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + script)
        path.chmod(0o755)

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
        env = {**self.env,
               **{key: self.render(str(value)) for key, value in step.get("env", {}).items()},
               **overrides}
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        raw_output = output.read_text()
        pairs = [line.split("=", 1) for line in raw_output.splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs), raw_output)
        outputs = dict(pairs)
        self.assertEqual(len(pairs), len(outputs), "Duplicate output keys")
        evidence = os.environ.get("WORKFLOW_EVIDENCE_ROOT")
        if evidence:
            self.calls += 1
            target = Path(evidence) / self._testMethodName / str(self.calls)
            target.mkdir(parents=True)
            (target / "source.sh").write_text(step["run"])
            (target / "rendered.sh").write_text(script)
            (target / "workflow-sha256.txt").write_text(hashlib.sha256(WORKFLOW.read_bytes()).hexdigest() + "\n")
            (target / "env.json").write_text(json.dumps(env, indent=2, sort_keys=True))
            (target / "values.json").write_text(json.dumps(self.values, indent=2, sort_keys=True))
            (target / "stdout.txt").write_text(result.stdout)
            (target / "stderr.txt").write_text(result.stderr)
            (target / "github-output.txt").write_text(raw_output)
            (target / "exit.txt").write_text(str(result.returncode) + "\n")
            fixtures = target / "fixtures"
            fixtures.mkdir()
            for path in self.bin.iterdir():
                if not path.is_symlink():
                    (fixtures / path.name).write_bytes(path.read_bytes())
        return result, outputs

    def rejected(self, step="version", **env):
        result, outputs = self.run_step(step, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs.get("status"))
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        self.assertNotIn("version", outputs)
        self.assertNotIn("package_version", outputs)

    def test_successful_package_bound_version_formats(self):
        for version, revision, vendor in ((VERSION, REVISION, "Ubuntu"),
                                           ("16.3", "16.3-1", "Debian"),
                                           ("7.6.1", "2:7.6.1-4+b1", "GDB")):
            label = vendor if vendor == "GDB" else f"{vendor} {revision}"
            with self.subTest(version=version):
                result, outputs = self.run_step("version",
                    CLI_STDOUT=f"GNU gdb ({label}) {version}\n",
                    PM_OUTPUT=self.package_row(version, revision))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(version, outputs["version"])
                self.assertEqual(revision, outputs["package_version"])
                self.assertEqual("passed", outputs["status"])

    def test_wrong_product_malformed_missing_and_duplicate_banners_fail(self):
        for banner in ("", "GNU gdb\n", "GNU gdb (GDB) unknown\n", "gdb 15.1\n",
                       BANNER.replace("GNU gdb", "GNU gdbserver"),
                       BANNER.replace(" 15.1\n", " 15.1)\n"),
                       "prefix " + BANNER, BANNER + BANNER,
                       BANNER.replace(" 15.1\n", " 15.1 suffix\n"), "\n" + BANNER):
            for step in ("version", "test2"):
                with self.subTest(step=step, banner=banner):
                    self.rejected(step, CLI_STDOUT=banner)

    def test_failed_commands_and_diagnostics_never_publish_version(self):
        for step in ("version", "test2"):
            for env in ({"CLI_RC": "1"}, {"CLI_RC": "127"}, {"CLI_RC": "139"},
                        {"CLI_STDERR": "invalid option\n"}, {"PM_RC": "1"},
                        {"FILES_RC": "1"}, {"PM_STDERR": "query failed\n"}):
                with self.subTest(step=step, env=env):
                    self.rejected(step, **env)

    def test_package_identity_mismatches_fail(self):
        row = self.package_row()
        for package in ("", row + row, row.replace("gdb\t", "other\t", 1),
                        row.replace("installed", "unpacked"), row.replace("arm64", "amd64"),
                        row.replace("\tarm64\tgdb\t", "\tarm64\tother\t"),
                        row.replace(REVISION, "unknown"), row.replace(REVISION, "99.1-1"),
                        row.replace("\t15.1\n", "\t15.2\n")):
            for step in ("version", "test2"):
                with self.subTest(step=step, package=package):
                    self.rejected(step, PM_OUTPUT=package)
        self.rejected(CLI_STDOUT=BANNER.replace(REVISION, "15.1-2"))

    def test_missing_or_unowned_executable_fails(self):
        for step in ("version", "test2"):
            self.rejected(step, PM_FILES="")
            self.rejected(step, PM_FILES="/usr/local/bin/other\n")
        (self.bin / "gdb").unlink()
        for step in ("version", "test1", "test2", "test3", "test4"):
            self.rejected(step)

    def test_version_core_requires_verified_unchanged_baseline(self):
        result, outputs = self.run_step("test2")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        for key, bad in (("outputs.status", "failed"), ("outputs.status", ""),
                         ("outcome", "failure"), ("outcome", ""),
                         ("outputs.version", "unknown"), ("outputs.version", "15.1)"),
                         ("outputs.version", "99.1"), ("outputs.package_version", "15.1-2")):
            field = f"steps.version.{key}"
            original = self.values[field]
            self.values[field] = bad
            self.rejected("test2")
            self.values[field] = original
        self.assertTrue(self.steps["version"]["continue-on-error"])

    def test_help_requires_successful_gdb_usage(self):
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.rejected("test3", HELP_RC="1")
        for text in ("", "Usage: another-tool\n", "options\n"):
            self.rejected("test3", HELP_OUTPUT=text)

    def test_debug_requires_one_successful_run_and_initialized_value(self):
        result, outputs = self.run_step("test4")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual("call\n", (self.root / "debug-calls").read_text())
        for text in ("Breakpoint 1 at 0x1234\n", DEBUG_OUTPUT.replace("$1 = 42", "$1 = 0"),
                     DEBUG_OUTPUT.replace("x is 42\n", ""), ""):
            self.rejected("test4", DEBUG_OUTPUT=text)
        self.rejected("test4", DEBUG_RC="1")
        self.rejected("test4", DEBUG_RC="42")
        self.rejected("test4", GCC_RC="1")

    def test_gdbserver_and_arm64_are_required_without_early_pass(self):
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        for env in ({"APT_RC": "100"}, {"SERVER_RC": "1"}, {"SERVER_OUTPUT": ""},
                    {"SERVER_OUTPUT": BANNER}, {"ARCH": "x86_64"}):
            self.rejected("test5", **env)
        (self.bin / "gdbserver").unlink()
        self.rejected("test5")

    def test_failed_install_does_not_emit_success(self):
        result, outputs = self.run_step("install", APT_RC="100")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("success", outputs.get("install_status"))

    def test_actual_auditor_sees_reachable_outputs_and_exact_skip(self):
        root = WORKFLOW.parents[2]
        for step in ("version", "test1", "test2", "test3", "test4", "test5"):
            for key in ("status", "duration"):
                self.assertTrue(observation_audit._step_emits_output(root, self.steps[step], key))
        for key in ("version", "package_version"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["version"], key))
        for key in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["summary"], key))
        self.assertEqual({("not_applicable_package_manager", "skipped"),
                          ("baseline_failed", "skipped"),
                          ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(root, self.steps["test6"])))

    def test_five_core_checks_and_skip_satisfy_real_decision_policy(self):
        result, regression = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("always()", self.steps["test6"]["if"])
        self.assertEqual("skipped", regression["status"])
        self.assertEqual(VERSION, regression["current_version"])
        self.assertEqual("not_applicable", regression["latest_version"])
        self.assertEqual("not_applicable", regression["next_installed_version"])
        self.assertIn("package manager", regression["comparison"])
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"passed": "5", "failed": "0", "skipped": "1", "core_failed": "0",
                          "duration": "15", "overall_status": "success", "badge_status": "passing"}, summary)
        details = [{"name": self.steps[f"test{i}"]["name"], "status": "passed"} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **regression})
        counters = {key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")}
        self.assertEqual("not_applicable", result_policy.decision_group(regression["decision"]))
        self.assertEqual("success", result_policy.validate_six_test_result(
            details=details, **counters, decision=regression["decision"]))
        details[1]["status"] = "failed"
        with self.assertRaises(ValueError):
            result_policy.validate_six_test_result(details=details, **counters, decision=regression["decision"])
        with self.assertRaises(ValueError):
            result_policy.validate_six_test_result(details=details, passed=4, failed=1, skipped=1,
                                                   core_failed=1, decision=regression["decision"])

    def test_each_core_requires_passed_status_and_successful_outcome(self):
        for i in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("unknown", "success"), ("passed", ""), ("passed", "failure"),
                                    ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(test=i, status=status, outcome=outcome):
                    self.values[f"steps.test{i}.outputs.status"] = status
                    self.values[f"steps.test{i}.outcome"] = outcome
                    skip_result, regression = self.run_step("test6")
                    self.assertEqual(0, skip_result.returncode, skip_result.stderr)
                    self.assertEqual("baseline_failed", regression["decision"])
                    self.values.update({f"steps.test6.outputs.{key}": value
                                        for key, value in regression.items()})
                    result, summary = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                        tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))
            self.values[f"steps.test{i}.outputs.status"] = "passed"
            self.values[f"steps.test{i}.outcome"] = "success"

    def test_test6_requires_exact_semantic_skip_and_successful_outcome(self):
        for status, decision, outcome in (("skipped", "", "success"), ("skipped", "not_configured", "success"),
                ("skipped", "baseline_failed", "success"),
                ("skipped", "baseline_install_failed", "success"),
                ("skipped", "runtime_validation_not_automated", "success"),
                ("skipped", "not_applicable_package_manager", ""),
                ("skipped", "not_applicable_package_manager", "failure"),
                ("skipped", "not_applicable_package_manager", "cancelled"),
                ("skipped", "not_applicable_package_manager", "skipped"),
                ("passed", "not_applicable_package_manager", "success"),
                ("failed", "not_applicable_package_manager", "success")):
            self.values.update({"steps.test6.outputs.status": status,
                                "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
            result, summary = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("5", "1", "0", "0", "failure", "failing"),
                tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))

    def test_failed_core_rows_are_accepted_with_actual_baseline_decision(self):
        original = dict(self.values)
        for failed_test in range(1, 6):
            with self.subTest(failed_test=failed_test):
                self.values = dict(original)
                self.values[f"steps.test{failed_test}.outputs.status"] = "failed"
                self.values[f"steps.test{failed_test}.outcome"] = "failure"
                result, regression = self.run_step("test6")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("baseline_failed", regression["decision"])
                self.values.update({f"steps.test6.outputs.{key}": value
                                    for key, value in regression.items()})
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("4", "1", "1", "1", "failing"),
                    tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "badge_status")))
                details = [{"name": self.steps[f"test{i}"]["name"],
                            "status": self.values[f"steps.test{i}.outputs.status"]}
                           for i in range(1, 6)]
                details.append({"name": self.steps["test6"]["name"], **regression})
                counters = {key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")}
                self.assertEqual("failure", result_policy.validate_six_test_result(
                    details=details, **counters, decision=regression["decision"]))
                for wrong in ("not_applicable_package_manager", "baseline_install_failed"):
                    self.values["steps.test6.outputs.decision"] = wrong
                    result, contradictory = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "2", "0", "1", "failing"),
                        tuple(contradictory[key] for key in ("passed", "failed", "skipped", "core_failed", "badge_status")))

    def test_install_failure_decision_precedes_other_baseline_failures(self):
        for outcome in ("failure", "cancelled", "skipped", ""):
            with self.subTest(outcome=outcome):
                self.values["steps.install.outcome"] = outcome
                for i in range(1, 6):
                    self.values[f"steps.test{i}.outputs.status"] = "failed"
                    self.values[f"steps.test{i}.outcome"] = "failure"
                result, regression = self.run_step("test6")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("baseline_install_failed", regression["decision"])
                self.values.update({f"steps.test6.outputs.{key}": value
                                    for key, value in regression.items()})
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("0", "5", "1", "5", "failing"),
                    tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "badge_status")))
                details = [{"name": self.steps[f"test{i}"]["name"], "status": "failed"}
                           for i in range(1, 6)]
                details.append({"name": self.steps["test6"]["name"], **regression})
                self.assertEqual("failure", result_policy.validate_six_test_result(
                    details=details, passed=0, failed=5, skipped=1, core_failed=5,
                    decision=regression["decision"]))
                self.values["steps.test6.outputs.decision"] = "baseline_failed"
                result, contradictory = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("0", contradictory["skipped"])

    def test_missing_or_failed_version_prerequisites_cannot_be_package_manager_skip(self):
        original = dict(self.values)
        for key, value in (("outcome", "failure"), ("outcome", ""),
                           ("outputs.status", "failed"), ("outputs.status", ""),
                           ("outputs.version", "unknown"), ("outputs.version", "")):
            with self.subTest(key=key, value=value):
                self.values = dict(original)
                self.values[f"steps.version.{key}"] = value
                result, regression = self.run_step("test6")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("baseline_failed", regression["decision"])
                self.values.update({f"steps.test6.outputs.{field}": output
                                    for field, output in regression.items()})
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "0", "failing"),
                    tuple(summary[field] for field in ("passed", "failed", "skipped", "core_failed", "badge_status")))

    def test_missing_results_and_invalid_durations_fail_closed(self):
        for step in ("test2", "test6"):
            for duration in ("bad", "-1", "1.5", "1000000"):
                self.values[f"steps.{step}.outputs.duration"] = duration
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", summary["overall_status"])
            self.values[f"steps.{step}.outputs.duration"] = "08"
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("29", summary["duration"])
        self.values.clear()
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5", "failing"),
            tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "badge_status")))


if __name__ == "__main__":
    unittest.main()
