"""Exercise the active collector's embedded program with conflicting evidence."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]


class ActiveCollectorFailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        action = yaml.safe_load(
            (ROOT / ".github/actions/collect-batch-results/action.yml").read_text()
        )
        cls.source = action["runs"]["steps"][0]["run"].split(
            "python3 - <<'PY'\n", 1
        )[1].rsplit("\nPY", 1)[0]

    def setUp(self):
        self.need = {
            "result": "success",
            "outputs": {
                "contract_version": "2.0",
                "package_slug": "alpha",
                "package_name": "Alpha",
                "package_version": "1.0.0",
                "run_status": "success",
                "tests_passed": "6",
                "tests_failed": "0",
                "tests_skipped": "0",
                "core_failed": "0",
                "job_name": "test-alpha",
                "regression_status": "passed",
                "regression_decision": "next_install_validated",
                "regression_current_version": "1.0.0",
                "regression_latest_version": "1.1.0",
                "regression_next_installed_version": "1.1.0",
            },
        }
        self.job = {
            "id": 456,
            "name": "test-alpha / test-alpha",
            "html_url": "https://github.com/example/project/actions/runs/123/job/456",
            "conclusion": "success",
            "steps": [
                {"name": f"Test {index} - Check", "number": index,
                 "conclusion": "success"}
                for index in range(1, 7)
            ],
        }

    def collect(self, need=None, job=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            environment = {
                **os.environ,
                "NEEDS_JSON": json.dumps({"test-alpha": need or self.need}),
                "RUN_JOBS_JSON": json.dumps({"jobs": [job or self.job]}),
                "BATCH_NUMBER": "1", "BATCH_TITLE": "Batch 1", "GH_TOKEN": "",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "example/project",
                "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_OUTPUT": str(root / "outputs"),
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
            }
            process = subprocess.run(
                [sys.executable, "-B", "-c", self.source], cwd=root,
                env=environment, capture_output=True, text=True, timeout=30,
            )
            result = root / "test-results/alpha-test-results/alpha.json"
            return process, json.loads(result.read_text()) if result.exists() else None

    def assert_rejected(self, *, need=None, job=None, message):
        process, payload = self.collect(need, job)
        self.assertNotEqual(0, process.returncode, process.stdout)
        self.assertIn(message, process.stderr)
        self.assertIsNone(payload, "Conflicting evidence must not write package JSON")

    def test_debian_continue_on_error_cannot_erase_emitted_failure(self):
        self.need["result"] = "failure"
        self.need["outputs"].update(
            run_status="failure", tests_passed="5", tests_failed="1"
        )
        self.need["outputs"].pop("core_failed")
        self.job["conclusion"] = "failure"
        self.job["steps"].append({
            "name": "Calculate test summary", "number": 7, "conclusion": "failure"
        })
        self.assert_rejected(message="alpha: emitted failure counts contradict test details")

    def test_each_emitted_failure_signal_survives_successful_api_steps(self):
        for field in ("tests_failed", "core_failed"):
            with self.subTest(field=field):
                need = copy.deepcopy(self.need)
                need["outputs"][field] = "1"
                self.assert_rejected(need=need, message="emitted failure counts contradict")

    def test_failed_needs_result_cannot_become_passing(self):
        for state in ("failure", "cancelled", "skipped"):
            with self.subTest(state=state):
                need = copy.deepcopy(self.need)
                need["result"] = state
                self.assert_rejected(need=need, message="passing result contradicts failure evidence")

    def test_successful_api_steps_cannot_relabel_emitted_skips_as_passes(self):
        self.need["outputs"].update(tests_passed="5", tests_skipped="1")
        self.assert_rejected(message="emitted skipped count contradicts test details")

    def test_regression_skip_cannot_hide_additional_baseline_skips(self):
        self.need["outputs"].update(
            tests_passed="4", tests_skipped="2", regression_status="skipped",
            regression_decision="not_applicable_package_manager"
        )
        self.assert_rejected(message="emitted skipped count contradicts test details")

    def test_nonstandard_detail_count_cannot_hide_a_failed_detail(self):
        for count in (5, 7):
            with self.subTest(count=count):
                job = copy.deepcopy(self.job)
                if count == 5:
                    job["steps"].pop()
                else:
                    job["steps"].append({
                        "name": "Test 7 - Extra check", "number": 7,
                        "conclusion": "success"
                    })
                job["steps"][2]["conclusion"] = "failure"
                self.assert_rejected(job=job, message="passing result contradicts failure evidence")

    def test_regression_classification_cannot_override_baseline_skips(self):
        for count in (1, 2):
            with self.subTest(count=count):
                need, job = copy.deepcopy(self.need), copy.deepcopy(self.job)
                need["outputs"].update(tests_passed=str(6 - count), tests_skipped=str(count))
                for step in job["steps"][:count]:
                    step["conclusion"] = "skipped"
                self.assert_rejected(need=need, job=job,
                                     message="passing result contradicts failure evidence")

    def test_failed_workflow_output_cannot_become_passing(self):
        self.need["outputs"]["run_status"] = "failure"
        self.assert_rejected(message="passing result contradicts failure evidence")

    def test_failed_or_incomplete_exact_job_cannot_become_passing(self):
        for state in ("failure", "cancelled", "timed_out", "skipped", None):
            with self.subTest(state=state):
                job = copy.deepcopy(self.job)
                job["conclusion"] = state
                self.assert_rejected(job=job, message="passing result contradicts failure evidence")

    def test_consistent_failure_still_emits_a_failed_package(self):
        self.need["result"] = self.job["conclusion"] = "failure"
        self.need["outputs"].update(
            run_status="failure", tests_passed="5", tests_failed="1", core_failed="1"
        )
        self.job["steps"][2]["conclusion"] = "failure"
        process, payload = self.collect()
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("failure", payload["run"]["status"])
        self.assertEqual(1, payload["tests"]["failed"])
        self.assertEqual("failed", payload["tests"]["details"][2]["status"])

    def test_consistent_six_test_success_is_unchanged(self):
        process, payload = self.collect()
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("success", payload["run"]["status"])
        self.assertEqual(6, payload["tests"]["passed"])
        self.assertEqual(0, payload["tests"]["failed"])

    def test_actual_api_baseline_failure_wins_over_successful_outputs(self):
        self.job["steps"][2]["conclusion"] = "failure"
        process, payload = self.collect()
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("failure", payload["run"]["status"])
        self.assertEqual(1, payload["tests"]["failed"])
        self.assertEqual(1, payload["metadata"]["core_failed"])

    def test_regression_semantics_cannot_hide_an_actual_failed_step(self):
        self.job["steps"][5]["conclusion"] = "failure"
        self.assert_rejected(message="passing result contradicts failure evidence")

    def test_package_manager_not_applicable_remains_five_passed_one_skip(self):
        self.need["outputs"].update(
            tests_passed="5", regression_status="skipped",
            regression_decision="not_applicable_package_manager"
        )
        self.job["steps"][5]["name"] = "Regression applicability - package manager installed"
        process, payload = self.collect()
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("success", payload["run"]["status"])
        self.assertEqual(5, payload["tests"]["passed"])
        self.assertEqual(1, payload["tests"]["skipped"])


if __name__ == "__main__":
    unittest.main()
