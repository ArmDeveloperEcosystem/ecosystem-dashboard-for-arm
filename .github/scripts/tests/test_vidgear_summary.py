"""Run VidGear's summary without installing or changing its known-invalid baseline."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-vidgear.yml"
OUTPUTS = {"passed", "failed", "skipped", "duration", "core_failed", "overall_status", "badge_status"}


def render(script, values):
    def replace(match):
        for part in match[1].split("||"):
            part = part.strip()
            value = part[1:-1] if part.startswith("'") else values.get(part, "")
            if value:
                return value
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)


def passed_values():
    values = {}
    for number in range(1, 7):
        values[f"steps.test{number}.outputs.status"] = "passed"
        values[f"steps.test{number}.outcome"] = "success"
        values[f"steps.test{number}.outputs.duration"] = str(number)
    return values


class VidGearSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = next(iter(yaml.safe_load(WORKFLOW.read_text())["jobs"].values()))
        cls.script = next(step["run"] for step in cls.job["steps"] if step.get("id") == "summary")

    def run_summary(self, overrides=None, empty=False):
        values = {} if empty else passed_values()
        values.update(overrides or {})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", render(self.script, values)],
                                    env=dict(os.environ, GITHUB_OUTPUT=str(output)),
                                    capture_output=True, text=True, timeout=10)
            fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(set(fields), OUTPUTS, result.stderr)
        return result, fields

    def assert_failure(self, result, fields, failed=1, core_failed=1):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((fields["passed"], fields["failed"], fields["skipped"], fields["core_failed"]),
                         (str(6 - failed), str(failed), "0", str(core_failed)))
        self.assertEqual(fields["overall_status"], "failure")
        self.assertEqual(fields["badge_status"], "failing" if core_failed else "passing")

    def test_all_six_pass_and_durations_sum(self):
        result, fields = self.run_summary()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"passed": "6", "failed": "0", "skipped": "0", "core_failed": "0",
                                  "duration": "21", "overall_status": "success", "badge_status": "passing"})

    def test_original_missing_baseline_status_and_failed_outcome_is_five_pass_one_fail(self):
        result, fields = self.run_summary({"steps.test5.outputs.status": "",
                                          "steps.test5.outcome": "failure",
                                          "steps.test5.outputs.duration": ""})
        self.assert_failure(result, fields)
        self.assertEqual(fields["duration"], "16")

    def test_all_missing_outputs_and_outcomes_fail_closed(self):
        result, fields = self.run_summary(empty=True)
        self.assert_failure(result, fields, failed=6, core_failed=5)
        self.assertEqual(fields["duration"], "0")

    def test_candidate_only_failure_keeps_core_badge_passing_but_exits_one(self):
        result, fields = self.run_summary({"steps.test6.outputs.status": "failed",
                                          "steps.test6.outcome": "failure"})
        self.assert_failure(result, fields, core_failed=0)
        self.assertEqual(fields, {"passed": "5", "failed": "1", "skipped": "0", "core_failed": "0",
                                  "duration": "21", "overall_status": "failure", "badge_status": "passing"})

    def test_each_missing_or_invalid_status_fails_even_with_successful_outcome(self):
        for number in range(1, 7):
            for status in ("", "failed", "unknown", "skipped"):
                with self.subTest(number=number, status=status):
                    result, fields = self.run_summary({f"steps.test{number}.outputs.status": status})
                    self.assert_failure(result, fields, core_failed=int(number <= 5))

    def test_passing_output_cannot_override_missing_or_bad_outcome(self):
        for number in range(1, 7):
            for outcome in ("", "failure", "cancelled", "skipped", "unknown"):
                with self.subTest(number=number, outcome=outcome):
                    result, fields = self.run_summary({f"steps.test{number}.outcome": outcome})
                    self.assert_failure(result, fields, core_failed=int(number <= 5))

    def test_only_successful_no_newer_regression_skip_is_approved(self):
        result, fields = self.run_summary({"steps.test6.outputs.status": "skipped",
                                          "steps.test6.outputs.decision": "no_newer_stable_available"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((fields["passed"], fields["failed"], fields["skipped"], fields["core_failed"]),
                         ("5", "0", "1", "0"))
        self.assertEqual(fields["overall_status"], "success")

    def test_invalid_skip_decisions_and_outcomes_are_failures(self):
        for decision in ("", "runtime_validation_not_automated", "not_applicable_package_manager",
                         "current_is_latest_stable", "unknown", "no_newer_stable_available"):
            for outcome in ("success", "", "failure", "cancelled", "skipped"):
                if decision == "no_newer_stable_available" and outcome == "success":
                    continue
                with self.subTest(decision=decision, outcome=outcome):
                    result, fields = self.run_summary({"steps.test6.outputs.status": "skipped",
                        "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
                    self.assert_failure(result, fields, core_failed=0)

    def test_approved_decision_cannot_excuse_failed_or_missing_regression_status(self):
        for status in ("", "failed", "unknown"):
            result, fields = self.run_summary({"steps.test6.outputs.status": status,
                "steps.test6.outputs.decision": "no_newer_stable_available"})
            self.assert_failure(result, fields, core_failed=0)

    def test_summary_has_explicit_inputs_and_preserves_baseline(self):
        self.assertEqual(self.job["env"]["BASELINE_VERSION"], "0.1.0")
        for number in range(1, 7):
            self.assertIn(f'T{number}="${{{{ steps.test{number}.outputs.status', self.script)
            self.assertIn(f'O{number}="${{{{ steps.test{number}.outcome', self.script)
            self.assertIn(f'D{number}="${{{{ steps.test{number}.outputs.duration', self.script)
        self.assertEqual(self.script.strip().splitlines()[-1], 'test "$FAILED" -eq 0')


if __name__ == "__main__":
    unittest.main()
