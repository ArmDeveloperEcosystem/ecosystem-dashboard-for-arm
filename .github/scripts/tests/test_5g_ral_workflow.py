"""Keep 5G-RAL's execution order compatible with strict result publication."""

import copy
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from package_result_policy import validate_publishable_result


class FiveGRalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = yaml.safe_load((ROOT / ".github/workflows/test-5G-RAL.yml").read_text())
        cls.steps = document["jobs"]["test-5g-ral"]["steps"]
        cls.checks = [step for step in cls.steps if re.fullmatch(r"test[1-6]", step.get("id", ""))]

    def test_checks_execute_in_publisher_ordinal_order(self):
        self.assertEqual([f"test{i}" for i in range(1, 7)], [step["id"] for step in self.checks])
        for ordinal, step in enumerate(self.checks, start=1):
            self.assertRegex(step["name"], rf"^Test {ordinal} - ")
        self.assertIn("ctest --output-on-failure", self.checks[4]["run"])

    def test_step_order_publishes_but_original_swapped_order_is_rejected(self):
        # These passing details are a serialization fixture, not runtime evidence.
        details = [{"name": step["name"], "status": "passed", "duration_seconds": 1}
                   for step in self.checks]
        details[-1]["decision"] = "next_install_validated"
        payload = {
            "run": {"status": "success"},
            "tests": {"passed": 6, "failed": 0, "skipped": 0, "details": details},
            "metadata": {
                "core_failed": 0, "badge_status": "passing",
                "regression_decision": "next_install_validated",
                "regression_status": "passed", "regression_applicability": "applicable",
                "regression_reason": "validated",
            },
        }
        self.assertEqual("success", validate_publishable_result(payload))
        original = copy.deepcopy(payload)
        original["tests"]["details"][3:5] = reversed(original["tests"]["details"][3:5])
        with self.assertRaisesRegex(ValueError, "ordinals exactly 1 through 6"):
            validate_publishable_result(original)

    def test_architecture_check_runs_without_functional_build_outputs(self):
        architecture = next(step for step in self.checks if step["id"] == "test4")
        with tempfile.TemporaryDirectory(prefix="ral-order-") as directory:
            root = Path(directory)
            uname = root / "uname"
            uname.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_ARCH"\n')
            uname.chmod(0o755)
            output = root / "outputs"
            for value, expected in (("aarch64", "passed"), ("x86_64", "failed")):
                with self.subTest(architecture=value):
                    output.write_text("")
                    env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                           "GITHUB_OUTPUT": str(output), "FIXTURE_ARCH": value}
                    env.pop("BUILD_PATH", None)
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", architecture["run"]],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=5)
                    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
                    self.assertEqual(expected == "passed", result.returncode == 0, result.stderr)
                    self.assertEqual(expected, fields["status"])


if __name__ == "__main__":
    unittest.main()
