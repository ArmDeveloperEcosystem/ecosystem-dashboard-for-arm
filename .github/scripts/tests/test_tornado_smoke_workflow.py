"""Execute Tornado's version check and fail-closed summary with isolated fixtures."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-tornado.yml"


class TornadoSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-tornado"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="tornado-smoke-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.venv = self.root / "venv"
        (self.venv / "bin").mkdir(parents=True)
        self.python = self.venv / "bin/python"
        self.python.write_text('''#!/bin/sh
"$FIXTURE_PYTHON" "$@"
status=$?
if [ "$status" -ne 0 ]; then
  exit "$status"
fi
exit "$FIXTURE_PYTHON_RC"
''')
        self.python.chmod(0o755)
        (self.root / "tornado.py").write_text('''import os
if os.environ.get("FIXTURE_IMPORT_FAIL") == "1":
    raise ImportError("fixture import failure")
version = os.environ["FIXTURE_TORNADO_VERSION"]
''')
        self.env = {
            **os.environ,
            "TORNADO_VENV": str(self.venv),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "PYTHONPATH": str(self.root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "FIXTURE_PYTHON": sys.executable,
            "FIXTURE_PYTHON_RC": "0",
            "FIXTURE_TORNADO_VERSION": "6.6",
            "FIXTURE_IMPORT_FAIL": "0",
        }

    def run_step(self, name, values=None, **environment):
        values = values or {}

        def expression(match):
            key, fallback = (part.strip() for part in match[1].split("||", 1))
            return str(values.get(key) or fallback.strip("'"))

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        # Match the workflow's implicit Bash invocation, including its lack of pipefail.
        result = subprocess.run(
            ["bash", "-e", "-c", script], cwd=self.root,
            env={**self.env, **environment}, capture_output=True, text=True, timeout=10,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def passing_values(self):
        return {key: value for number in range(1, 6) for key, value in (
            (f"steps.test{number}.outputs.status", "passed"),
            (f"steps.test{number}.outputs.duration", str(number)),
        )}

    def assert_summary(self, result, outputs, failed):
        self.assertEqual(1 if failed else 0, result.returncode, result.stderr)
        self.assertEqual(str(5 - failed), outputs["passed"])
        self.assertEqual(str(failed), outputs["failed"])
        self.assertEqual("failure" if failed else "success", outputs["overall_status"])
        self.assertEqual("failing" if failed else "passing", outputs["badge_status"])

    def test_accepts_two_and_three_component_stable_versions(self):
        # Upstream v6.6.0 reports version = "6.6", version_info = (6, 6, 0, 0).
        # https://github.com/tornadoweb/tornado/blob/v6.6.0/tornado/__init__.py#L25-L26
        for version in ("6.6", "6.6.0", "6.5.10"):
            with self.subTest(version=version):
                result, outputs = self.run_step("test2", FIXTURE_TORNADO_VERSION=version)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertGreaterEqual(int(outputs["duration"]), 0)

    def test_rejects_malformed_or_extra_version_output(self):
        for version in (
            "", "6", "6.", "6.6.", "6.x", "garbage", "v6.6", " 6.6", "6.6 ",
            "6.6junk", "6.6.0junk", "6.6.0.1", "6.6\nunexpected", "unexpected\n6.6",
        ):
            with self.subTest(version=version):
                result, outputs = self.run_step("test2", FIXTURE_TORNADO_VERSION=version)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_rejects_prerelease_versions(self):
        for version in ("6.6a1", "6.6b1", "6.6rc1", "6.6.dev1", "6.6.0rc1", "6.6.0.dev1"):
            with self.subTest(version=version):
                result, outputs = self.run_step("test2", FIXTURE_TORNADO_VERSION=version)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_nonzero_command_cannot_pass_even_with_valid_version_output(self):
        for version, code in (("6.6", "1"), ("6.6.0", "23"), ("", "1")):
            with self.subTest(version=version, code=code):
                result, outputs = self.run_step(
                    "test2", FIXTURE_TORNADO_VERSION=version, FIXTURE_PYTHON_RC=code,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_import_failure_cannot_pass(self):
        result, outputs = self.run_step("test2", FIXTURE_IMPORT_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("fixture import failure", result.stderr)
        self.assertEqual("failed", outputs["status"])

    def test_missing_interpreter_cannot_pass(self):
        self.python.unlink()
        result, outputs = self.run_step("test2")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_summary_reports_all_five_passes_and_total_duration(self):
        self.assertEqual("always()", self.steps["summary"]["if"])
        result, outputs = self.run_step("summary", self.passing_values())
        self.assert_summary(result, outputs, failed=0)
        self.assertEqual("15", outputs["duration"])

    def test_summary_rejects_every_nonpassing_or_missing_core_status(self):
        for number in range(1, 6):
            for status in ("failed", "skipped", "", "invalid", None):
                with self.subTest(number=number, status=status):
                    values = self.passing_values()
                    key = f"steps.test{number}.outputs.status"
                    if status is None:
                        values.pop(key)
                    else:
                        values[key] = status
                    result, outputs = self.run_step("summary", values)
                    self.assert_summary(result, outputs, failed=1)
                    self.assertEqual("15", outputs["duration"])

    def test_summary_with_no_core_outputs_is_failure(self):
        result, outputs = self.run_step("summary")
        self.assert_summary(result, outputs, failed=5)
        self.assertEqual("0", outputs["duration"])

    def test_actual_version_failure_reaches_summary_despite_continue_on_error(self):
        for version, code in (("6.6rc1", "0"), ("6.6", "23")):
            with self.subTest(version=version, code=code):
                result, outputs = self.run_step(
                    "test2", FIXTURE_TORNADO_VERSION=version, FIXTURE_PYTHON_RC=code,
                )
                self.assertNotEqual(0, result.returncode)
                values = self.passing_values()
                values.pop("steps.test2.outputs.status")
                values.pop("steps.test2.outputs.duration")
                values.update({f"steps.test2.outputs.{key}": value for key, value in outputs.items()})
                result, summary = self.run_step("summary", values)
                self.assert_summary(result, summary, failed=1)
                self.assertEqual(str(13 + int(outputs.get("duration", 0))), summary["duration"])


if __name__ == "__main__":
    unittest.main()
