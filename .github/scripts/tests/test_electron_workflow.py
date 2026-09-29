"""Execute Electron's CLI workflow checks with offline stubs, not Electron."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit  # noqa: E402


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-electron.yml"
VERSION = "v41.7.1"
ABI = "145"
ORIGINAL_SHA256 = "470271daa4e5ac3bf2453941c6d961a77f4878a2050dfecc2f615063a22ff542"
OLD_NAME = "Test 3 - Check Help Output"
NEW_NAME = "Test 3 - CLI Runtime Version and ABI"
OLD_PROBE = '''set -euo pipefail
START_TIME=$(date +%s)

timeout 20s xvfb-run -a "${{ steps.install.outputs.electron_bin }}" --no-sandbox --help 2>&1 | tee /tmp/electron-help.log || true
if grep -Eqi 'usage|options|debugging|inspect|electron' /tmp/electron-help.log; then
  echo "status=passed" >> "$GITHUB_OUTPUT"
else
  cat /tmp/electron-help.log || true
  echo "status=failed" >> "$GITHUB_OUTPUT"
  exit 1
fi

END_TIME=$(date +%s)
echo "duration=$((END_TIME - START_TIME))" >> "$GITHUB_OUTPUT"
'''
OLD_SUMMARY_CALL = '''          check_test "${{ steps.test3.outputs.status || 'failed' }}" "${{ steps.test3.outputs.duration || 0 }}"
'''
NEW_SUMMARY_CALL = OLD_SUMMARY_CALL.rstrip("\n") + ' "${{ steps.test3.outcome || \'skipped\' }}"\n'


class ElectronWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_bytes().decode("utf-8")
        self.job = yaml.load(self.source, Loader=yaml.BaseLoader)["jobs"]["test-electron"]
        self.steps = {item["id"]: item for item in self.job["steps"] if "id" in item}
        temporary = tempfile.TemporaryDirectory(prefix="electron workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        self.output = self.root / "outputs"
        self.calls = self.root / "calls"
        self.date_started = self.root / "date-started"
        self.electron = self.tool("electron binary", '''[ "$#" -eq 2 ] && [ "$1" = --no-sandbox ] || exit 97
[ "${ELECTRON_RUN_AS_NODE:-}" = "" ] || exit 98
printf 'electron %s\\n' "$2" >> "$FIXTURE_ROOT/calls"
case "$2" in
  --version) value="$VERSION_OUTPUT"; code="$VERSION_EXIT"; signal="$VERSION_SIGNAL";;
  --abi) value="$ABI_OUTPUT"; code="$ABI_EXIT"; signal="$ABI_SIGNAL";;
  *) exit 97;;
esac
printf '%s' "$value"
printf '%s' "$CLI_STDERR" >&2
if [ -n "$signal" ]; then
  ulimit -c 0
  kill -s "$signal" "$$"
fi
exit "$code"
''')
        self.tool("timeout", '''[ "$#" -eq 7 ] || exit 97
[ "$1" = --kill-after=5s ] && [ "$2" = 20s ] && [ "$3" = xvfb-run ] || exit 97
printf 'timeout %s %s\\n' "$1" "$2" >> "$FIXTURE_ROOT/calls"
shift 2
exec "$@"
''')
        self.tool("xvfb-run", '''[ "$#" -eq 4 ] && [ "$1" = -a ] || exit 97
[ "$2" = "$FIXTURE_ELECTRON" ] || exit 97
printf 'xvfb-run %s\\n' "$1" >> "$FIXTURE_ROOT/calls"
if [ "$XVFB_EXIT" != 0 ]; then exit "$XVFB_EXIT"; fi
shift
exec "$@"
''')
        self.tool("date", '''[ "$#" -eq 1 ] && [ "$1" = +%s ] || exit 97
if [ -e "$FIXTURE_ROOT/date-started" ]; then
  printf '107\\n'
else
  : > "$FIXTURE_ROOT/date-started"
  printf '100\\n'
fi
''')
        for name in ("node", "python", "python3", "curl", "wget"):
            self.tool(name, 'echo "Unexpected command" >&2\nexit 98\n')
        self.env = {**os.environ, "PATH": str(self.bin), "HOME": str(self.root),
                    "TMPDIR": str(self.root), "FIXTURE_ROOT": str(self.root),
                    "FIXTURE_ELECTRON": str(self.electron), "GITHUB_OUTPUT": str(self.output),
                    "VERSION_OUTPUT": VERSION + "\n", "ABI_OUTPUT": ABI + "\n",
                    "VERSION_EXIT": "0", "ABI_EXIT": "0", "XVFB_EXIT": "0",
                    "VERSION_SIGNAL": "", "ABI_SIGNAL": "", "CLI_STDERR": ""}
        self.env.pop("ELECTRON_RUN_AS_NODE", None)
        self.values = {"steps.install.outputs.electron_bin": str(self.electron),
                       "steps.version.outputs.version": VERSION}

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{self.bash}\nset -euo pipefail\n" + body)
        path.chmod(0o755)
        return path

    def run_shell(self, step, values=None, **environment):
        context = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if context.get(term):
                    return str(context[term])
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step]["run"])
        self.output.write_text("")
        self.calls.write_text("")
        self.date_started.unlink(missing_ok=True)
        result = subprocess.run([self.bash, "-euo", "pipefail", "-c", script],
                                cwd=self.root, env={**self.env, **environment},
                                capture_output=True, text=True, timeout=10)
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "terminal outputs must not be duplicated")
        return result, dict(pairs)

    def assert_probe_failure(self, result, fields, code=1):
        if code is None:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(fields, {"status": "failed", "duration": "7"})
        self.assertNotIn("status=passed", self.output.read_text())

    def test_only_authorized_test3_and_summary_changes(self):
        current = textwrap.indent(self.steps["test3"]["run"], "          ")
        self.assertEqual(self.source.count(current), 1)
        restored = self.source.replace(current, textwrap.indent(OLD_PROBE, "          "), 1)
        self.assertEqual(restored.count(NEW_NAME), 2)
        restored = restored.replace(NEW_NAME, OLD_NAME)
        outcome_line = "            local outcome=${3:-success}\n"
        self.assertEqual(restored.count(outcome_line), 1)
        restored = restored.replace(outcome_line, "", 1)
        condition = '            if [ "$status" = "passed" ] && [ "$outcome" = "success" ]; then\n'
        self.assertEqual(restored.count(condition), 1)
        restored = restored.replace(condition, '            if [ "$status" = "passed" ]; then\n', 1)
        self.assertEqual(restored.count(NEW_SUMMARY_CALL), 1)
        restored = restored.replace(NEW_SUMMARY_CALL, OLD_SUMMARY_CALL, 1)
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), ORIGINAL_SHA256)
        self.assertEqual(self.steps["test3"]["name"], NEW_NAME)
        self.assertNotIn("ELECTRON_RUN_AS_NODE", self.source)
        self.assertNotIn("--require", self.steps["test3"]["run"])
        self.assertNotIn("|| true", self.steps["test3"]["run"])

    def test_exact_version_and_positive_abi_use_two_bounded_real_cli_invocations(self):
        result, fields = self.run_shell("test3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"status": "passed", "duration": "7"})
        self.assertIn(f"Electron runtime version: {VERSION}\n", result.stdout)
        self.assertIn(f"Electron runtime ABI: {ABI}\n", result.stdout)
        self.assertEqual(self.calls.read_text().splitlines(), [
            "timeout --kill-after=5s 20s", "xvfb-run -a", "electron --version",
            "timeout --kill-after=5s 20s", "xvfb-run -a", "electron --abi",
        ])

    def test_terminal_outputs_remain_visible_to_the_migration_auditor(self):
        root = Path(__file__).resolve().parents[3]
        for output in ("status", "duration"):
            with self.subTest(output=output):
                self.assertTrue(audit._step_emits_output(root, self.steps["test3"], output))

    def test_positive_integer_abi_is_not_hardcoded(self):
        for value in ("1", "145", "99999"):
            with self.subTest(abi=value):
                result, fields = self.run_shell("test3", ABI_OUTPUT=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fields["status"], "passed")

    def test_runtime_version_must_equal_resolved_version_not_a_hardcoded_pin(self):
        result, fields = self.run_shell("test3", {"steps.version.outputs.version": "v42.0.0"},
                                        VERSION_OUTPUT="v42.0.0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")

    def test_empty_wrong_or_noisy_version_is_not_accepted(self):
        for value in ("", " \n", "v41.7.2", "41.7.1", "unknown", "v41.7.10",
                      f"Electron {VERSION}", f"{VERSION}\nerror", f"error\n{VERSION}",
                      "Electron exited with signal SIGTRAP", "Usage: electron [options] [path]"):
            with self.subTest(version=value):
                self.assert_probe_failure(*self.run_shell("test3", VERSION_OUTPUT=value))
                self.assertNotIn("electron --abi", self.calls.read_text())

    def test_missing_reference_version_cannot_match_empty_output(self):
        for expected, actual in (("", ""), ("", VERSION), ("unknown", VERSION)):
            with self.subTest(expected=expected, actual=actual):
                self.assert_probe_failure(*self.run_shell(
                    "test3", {"steps.version.outputs.version": expected}, VERSION_OUTPUT=actual))

    def test_abi_requires_a_complete_positive_integer(self):
        for value in ("", "0", "-1", "+145", "01", "145.0", " 145", "145 ",
                      "ABI: 145", "145\n146", "145\nerror", "Electron SIGTRAP", "unknown"):
            with self.subTest(abi=value):
                self.assert_probe_failure(*self.run_shell("test3", ABI_OUTPUT=value))
                self.assertIn("electron --abi", self.calls.read_text())

    def test_matching_text_never_overrides_nonzero_crash_or_timeout_status(self):
        for probe in ("VERSION", "ABI"):
            for code in (1, 2, 124, 125, 126, 127, 133, 137, 143):
                with self.subTest(probe=probe, code=code):
                    self.assert_probe_failure(*self.run_shell(
                        "test3", **{f"{probe}_EXIT": str(code)}), code=code)

    def test_actual_child_signal_still_records_failed_terminal_outputs(self):
        for probe in ("VERSION", "ABI"):
            with self.subTest(probe=probe):
                self.assert_probe_failure(*self.run_shell(
                    "test3", **{f"{probe}_SIGNAL": "TERM"}), code=143)

    def test_stderr_diagnostics_are_not_mistaken_for_cli_values(self):
        result, fields = self.run_shell("test3", CLI_STDERR="D-Bus diagnostic\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")
        self.assertIn("D-Bus diagnostic", result.stderr)
        for probe, value in (("VERSION", VERSION), ("ABI", ABI)):
            with self.subTest(probe=probe):
                self.assert_probe_failure(*self.run_shell(
                    "test3", CLI_STDERR=value + "\n", **{f"{probe}_OUTPUT": ""}))

    def test_xvfb_failure_records_status_and_duration(self):
        self.assert_probe_failure(*self.run_shell("test3", XVFB_EXIT="3"), code=3)
        self.assertNotIn("electron --version", self.calls.read_text())

    def test_missing_or_nonexecutable_binary_cannot_pass(self):
        self.electron.chmod(0o644)
        self.assert_probe_failure(*self.run_shell("test3"), code=None)
        self.electron.unlink()
        self.assert_probe_failure(*self.run_shell("test3"), code=None)

    def summary_values(self):
        return {**{f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)},
                **{f"steps.test{i}.outputs.duration": "1" for i in range(1, 6)},
                "steps.test3.outcome": "success"}

    def assert_summary_failure(self, values):
        result, fields = self.run_shell("summary", values)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(fields["passed"], "4")
        self.assertEqual(fields["failed"], "1")
        self.assertEqual(fields["overall_status"], "failure")
        self.assertEqual(fields["badge_status"], "failing")

    def test_failed_missing_or_skipped_test3_output_fails_summary(self):
        for status in ("failed", "", "skipped", None):
            with self.subTest(status=status):
                values = self.summary_values()
                values["steps.test3.outputs.status"] = status
                self.assert_summary_failure(values)

    def test_passed_output_cannot_override_unsuccessful_or_missing_outcome(self):
        for outcome in ("failure", "cancelled", "skipped", "", None):
            with self.subTest(outcome=outcome):
                values = self.summary_values()
                values["steps.test3.outcome"] = outcome
                self.assert_summary_failure(values)

    def test_failed_probe_flows_into_summary_without_a_fake_pass(self):
        result, probe = self.run_shell("test3", ABI_EXIT="124")
        self.assert_probe_failure(result, probe, code=124)
        values = self.summary_values()
        values.update({f"steps.test3.outputs.{key}": value for key, value in probe.items()})
        values["steps.test3.outcome"] = "failure"
        self.assert_summary_failure(values)

    def test_other_core_failures_still_fail_summary(self):
        for number in (1, 2, 4, 5):
            with self.subTest(test=number):
                values = self.summary_values()
                values[f"steps.test{number}.outputs.status"] = "failed"
                self.assert_summary_failure(values)

    def test_success_preserves_five_core_passes_and_exact_package_manager_skip(self):
        result, fields = self.run_shell("summary", self.summary_values())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"passed": "5", "failed": "0", "duration": "5",
                                  "overall_status": "success", "badge_status": "passing"})
        result, fields = self.run_shell("test6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {
            "current_version": VERSION, "latest_version": "not_applicable",
            "next_installed_version": "not_applicable", "decision": "not_applicable_package_manager",
            "regression_result": "Regression validation not applicable: tested package installed via package manager in Tests 1-5",
            "comparison": "The tested package is installed via a package manager in Tests 1-5, so version-to-version regression validation is not shown under the current policy.",
            "status": "skipped", "duration": "0",
        })


if __name__ == "__main__":
    unittest.main()
