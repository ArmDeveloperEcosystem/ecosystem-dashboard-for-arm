"""Feast's unavailable baseline API must remain a real failure."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-feast.yml"


class FeastWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-feast"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}

    def summary(self, overrides):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values.update(overrides)
        def expression(match):
            terms = match[1].split("||")
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else "")
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps["summary"]["run"])
        with tempfile.TemporaryDirectory(prefix="feast-summary-") as directory:
            output = Path(directory) / "output"
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script], cwd=directory,
                env=dict(os.environ, GITHUB_OUTPUT=str(output)),
                capture_output=True, text=True, timeout=10,
            )
            return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_original_import_error_is_a_failed_core_check_not_a_skip(self):
        result, outputs = self.summary({"steps.test5.outputs.status": "", "steps.test5.outcome": "failure"})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("5", "1", "0", "1", "failure"), tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status")))

    def test_failed_and_missing_outcomes_cannot_be_overridden(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    result, outputs = self.summary({f"steps.test{number}.outcome": outcome})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("1" if number <= 5 else "0", outputs["core_failed"])

    def test_baseline_and_historical_retrieval_are_not_silently_replaced(self):
        self.assertEqual("0.1.0", self.job["env"]["BASELINE_VERSION"])
        smoke = self.steps["test5"]["run"]
        self.assertIn('"feast==$BASELINE_VERSION"', smoke)
        self.assertIn("store.get_historical_features(", smoke)
        self.assertIn('assert float(features["rating"].iloc[0]) == 4.5', smoke)

    def test_genuine_pass_and_no_newer_candidate_keep_exact_counts(self):
        result, outputs = self.summary({})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "0"), tuple(outputs[key] for key in ("passed", "failed", "skipped")))
        result, outputs = self.summary({"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "no_newer_stable_available"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"), tuple(outputs[key] for key in ("passed", "failed", "skipped")))


if __name__ == "__main__":
    unittest.main()
