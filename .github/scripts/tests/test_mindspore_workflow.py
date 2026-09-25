"""Focused package workflow regression checks."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-mindspore.yml"


class MindsporeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mindspore-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-mindspore"]
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
        allowed = None
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

    def prepare_pages(self):
        self.values["steps.install.outputs.install_mode"] = "external_artifact"
        self.page = self.root / "page.html"
        self.page.write_text("MindSpore pip install wheel\n" + "details\n" * 524288)
        self.env.update(DOWNLOAD_URL=self.page.as_uri(), HOMEPAGE_URL=self.page.as_uri(),
                        OFFICIAL_DOCS=self.page.as_uri())
        doc = self.root / "content/linux/opensource_packages/mindspore.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("name: Mindspore\nworks_on_arm: true\n    version_number: 1.0.0\n")

    def test_real_curl_early_close_is_reproduced_and_fixed_steps_read_to_end(self):
        self.prepare_pages()
        broken = subprocess.run(["bash", "-e", "-o", "pipefail", "-c",
                                 'curl -fsL "$OFFICIAL_DOCS" | grep -Eqi "pip|install|wheel"'],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(23, broken.returncode)
        for step in ("test2", "test3"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])

    def test_matching_partial_responses_do_not_hide_transfer_failures(self):
        self.prepare_pages()
        self.stub("curl", 'printf "MindSpore pip install wheel\\n"\nexit "$CURL_EXIT"\n')
        for step in ("test2", "test3"):
            for code in (7, 22, 23, 28):
                with self.subTest(step=step, code=code):
                    result, outputs = self.run_step(step, CURL_EXIT=str(code))
                    self.assertEqual(code, result.returncode, result.stderr)
                    self.assertNotEqual("passed", outputs.get("status"))

    def test_missing_content_and_real_fetch_failure_are_not_passes(self):
        self.prepare_pages()
        for body in ("", "Unrelated documentation"):
            self.page.write_text(body)
            for step in ("test2", "test3"):
                with self.subTest(step=step, body=body):
                    result, outputs = self.run_step(step)
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotEqual("passed", outputs.get("status"))
        self.page.unlink()
        for step in ("test2", "test3"):
            result, outputs = self.run_step(step)
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", outputs.get("status"))

    def test_late_failure_after_status_emission_fails_summary(self):
        self.prepare_pages()
        self.stub("date", 'if [ -f "$TMPDIR/date-called" ]; then exit 9; fi\n'
                  'touch "$TMPDIR/date-called"\necho 100\n')
        result, outputs = self.run_step("test3")
        self.assertEqual(9, result.returncode)
        self.assertEqual("passed", outputs["status"])
        values = self.passing_values()
        values["steps.test3.outcome"] = "failure"
        result, outputs = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["core_failed"])

    def test_homepage_identity_is_required_after_download_page_matches(self):
        self.prepare_pages()
        wrong = self.root / "wrong.html"
        wrong.write_text("Unrelated homepage")
        result, outputs = self.run_step("test2", HOMEPAGE_URL=wrong.as_uri())
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("passed", outputs.get("status"))


if __name__ == "__main__":
    unittest.main()

