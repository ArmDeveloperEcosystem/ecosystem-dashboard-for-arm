"""Focused package workflow regression checks."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-ragflow.yml"


class RagflowWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ragflow-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-ragflow"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        TMPDIR=str(self.root), RUNNER_TEMP=str(self.root))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.values = {"steps.install.outputs.install_mode": "github_source",
                       "steps.install.outputs.install_status": "success"}

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, **env):
        values = {**self.values, **(values or {})}
        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def passing_values(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}

    def test_summary_requires_passed_output_and_successful_outcome(self):
        values = self.passing_values()
        result, outputs = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "failed"),
                                 ("outputs.status", "skipped"), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped"), ("outcome", "")):
                with self.subTest(i=i, field=field, value=value):
                    changed = {**values, f"steps.test{i}.{field}": value,
                               f"steps.test{i}.conclusion": "success"}
                    result, outputs = self.run_step("summary", changed)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(i < 6)), outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", outputs["failed"])
        self.assertEqual("5", outputs["core_failed"])

    def test_only_explicit_successful_regression_skip_is_allowed(self):
        values = self.passing_values()
        values["steps.test6.outputs.status"] = "skipped"
        allowed = "no_newer_stable_available"
        for decision in ("not_configured", "runtime_validation_not_automated",
                         "metadata_review_required", "no_newer_stable_available",
                         "not_applicable_package_manager"):
            for outcome in ("success", "failure", "cancelled", ""):
                with self.subTest(decision=decision, outcome=outcome):
                    values.update({"steps.test6.outputs.decision": decision,
                                   "steps.test6.outcome": outcome})
                    result, outputs = self.run_step("summary", values)
                    accepted = decision == allowed and outcome == "success"
                    self.assertEqual(accepted, result.returncode == 0)
                    self.assertEqual(str(int(accepted)), outputs["skipped"])
                    self.assertEqual(str(int(not accepted)), outputs["failed"])
                    self.assertEqual("0", outputs["core_failed"])

    def prepare_source(self):
        source = self.root / "baseline-src"
        source.mkdir()
        (source / "README.md").write_text("# RAGFlow\nPinned release documentation.\n")
        (source / "requirements.txt").write_text("numpy\n")
        (source / "web").mkdir()
        (source / "web/package.json").write_text('{"private":true,"scripts":{"build":"umi build"}}')
        result, outputs = self.run_step("expectations")
        self.assertEqual(0, result.returncode, result.stderr)
        self.values.update({f"steps.expectations.outputs.{k}": v for k, v in outputs.items()})
        return source, outputs

    def test_historical_readme_and_requirements_layout_passes_without_pyproject(self):
        source, expectations = self.prepare_source()
        self.assertEqual("0.7.0", self.env["BASELINE_VERSION"])
        self.assertEqual("README.md", expectations["identity_target"])
        self.assertIn("requirements.txt", expectations["source_markers"])
        self.assertFalse((source / "pyproject.toml").exists())
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_missing_or_wrong_project_readme_cannot_pass(self):
        source, _ = self.prepare_source()
        for body in ("", "# Other project\n"):
            (source / "README.md").write_text(body)
            result, outputs = self.run_step("test3")
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", outputs.get("status"))
        (source / "README.md").unlink()
        result, outputs = self.run_step("test3")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("passed", outputs.get("status"))


if __name__ == "__main__":
    unittest.main()

