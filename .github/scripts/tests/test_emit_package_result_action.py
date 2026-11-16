"""Execute the canonical package-result emitter and verify its fail-closed contract."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
ACTION = ROOT / ".github/actions/emit-package-result/action.yml"


class EmitPackageResultActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        action = yaml.safe_load(ACTION.read_text())
        cls.script = next(
            step["run"] for step in action["runs"]["steps"] if step.get("id") == "emit"
        )

    def run_emitter(self, **overrides):
        with tempfile.TemporaryDirectory(prefix="emit-package-result-") as temporary:
            root = Path(temporary)
            result_path = root / "package-result.json"
            output_path = root / "github-output"
            summary_path = root / "step-summary"
            env = {
                **os.environ,
                "PACKAGE_SLUG": "example",
                "PACKAGE_NAME": "Example",
                "VERSION": "1.2.3",
                "INSTALL_STATUS": "success",
                "RUNNER_LABEL": "ubuntu-24.04-arm",
                "SUMMARY_STYLE": "baseline-artifact",
                "TEST1_LABEL": "",
                "TEST2_LABEL": "",
                "TEST3_LABEL": "",
                "TEST4_LABEL": "",
                "TEST5_LABEL": "",
                "TEST1_STATUS": "passed",
                "TEST2_STATUS": "passed",
                "TEST3_STATUS": "passed",
                "TEST4_STATUS": "passed",
                "TEST5_STATUS": "passed",
                "TEST6_STATUS": "passed",
                "TEST1_DURATION": "1",
                "TEST2_DURATION": "2",
                "TEST3_DURATION": "3",
                "TEST4_DURATION": "4",
                "TEST5_DURATION": "5",
                "TEST6_DURATION": "6",
                "REGRESSION_DECISION": "next_install_validated",
                "REGRESSION_CURRENT_VERSION": "1.2.3",
                "REGRESSION_LATEST_VERSION": "1.2.4",
                "REGRESSION_NEXT_INSTALLED_VERSION": "1.2.4",
                "REGRESSION_RESULT": "Next version passed.",
                "REGRESSION_DETAILS": "Candidate installed and passed.",
                "RESULT_PATH": str(result_path),
                "FAIL_ON_TEST6": "true",
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_STEP_SUMMARY": str(summary_path),
            }
            env.update(overrides)

            completed = subprocess.run(
                ["bash", "-c", self.script],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                0,
                completed.returncode,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            outputs = dict(
                line.split("=", 1)
                for line in output_path.read_text().splitlines()
                if "=" in line
            )
            return outputs, json.loads(result_path.read_text()), summary_path.read_text()

    def assert_result(self, outputs, payload, *, passed, failed, skipped, core_failed,
                      should_fail, overall_status):
        expected = {
            "passed": str(passed),
            "failed": str(failed),
            "skipped": str(skipped),
            "core_failed": str(core_failed),
            "should_fail": str(should_fail),
            "overall_status": overall_status,
            "badge_status": "passing" if overall_status == "success" else "failing",
        }
        self.assertEqual(expected, {key: outputs[key] for key in expected})
        self.assertEqual(
            {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "core_failed": core_failed,
            },
            {key: payload["tests"][key] for key in ("passed", "failed", "skipped", "core_failed")},
        )
        self.assertEqual(overall_status, payload["run"]["status"])
        self.assertEqual(expected["badge_status"], payload["run"]["badge_status"])

    def test_all_six_tests_pass(self):
        outputs, payload, _ = self.run_emitter()
        self.assert_result(
            outputs, payload, passed=6, failed=0, skipped=0, core_failed=0,
            should_fail=0, overall_status="success",
        )
        self.assertEqual("21", outputs["duration"])

    def test_one_baseline_failure_preserves_actual_4_1_1_counts(self):
        outputs, payload, _ = self.run_emitter(
            TEST3_STATUS="failed",
            TEST6_STATUS="skipped",
            REGRESSION_DECISION="baseline_failed",
        )
        self.assert_result(
            outputs, payload, passed=4, failed=1, skipped=1, core_failed=1,
            should_fail=1, overall_status="failure",
        )

    def test_install_failure_preserves_actual_0_1_5_counts(self):
        outputs, payload, _ = self.run_emitter(
            INSTALL_STATUS="failed",
            TEST1_STATUS="failed",
            TEST2_STATUS="skipped",
            TEST3_STATUS="skipped",
            TEST4_STATUS="skipped",
            TEST5_STATUS="skipped",
            TEST6_STATUS="skipped",
            REGRESSION_DECISION="baseline_install_failed",
        )
        self.assert_result(
            outputs, payload, passed=0, failed=1, skipped=5, core_failed=1,
            should_fail=1, overall_status="failure",
        )

    def test_approved_test6_skip_is_safe(self):
        outputs, payload, _ = self.run_emitter(
            TEST6_STATUS="skipped",
            REGRESSION_DECISION="runtime_validation_not_automated",
        )
        self.assert_result(
            outputs, payload, passed=5, failed=0, skipped=1, core_failed=0,
            should_fail=0, overall_status="success",
        )

    def test_unsafe_test6_skip_sets_should_fail(self):
        outputs, payload, _ = self.run_emitter(
            TEST6_STATUS="skipped",
            REGRESSION_DECISION="not_configured",
        )
        self.assert_result(
            outputs, payload, passed=5, failed=0, skipped=1, core_failed=0,
            should_fail=1, overall_status="failure",
        )

    def test_missing_statuses_are_counted_as_skipped_and_fail_closed(self):
        overrides = {f"TEST{number}_STATUS": "" for number in range(1, 7)}
        outputs, payload, _ = self.run_emitter(**overrides)
        self.assert_result(
            outputs, payload, passed=0, failed=0, skipped=6, core_failed=0,
            should_fail=1, overall_status="failure",
        )

    def test_skipped_core_test_fails_without_incrementing_core_failed(self):
        outputs, payload, _ = self.run_emitter(
            TEST4_STATUS="skipped",
            TEST6_STATUS="skipped",
            REGRESSION_DECISION="no_newer_stable_available",
        )
        self.assert_result(
            outputs, payload, passed=4, failed=0, skipped=2, core_failed=0,
            should_fail=1, overall_status="failure",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
