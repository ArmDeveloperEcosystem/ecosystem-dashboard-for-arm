"""Exercise the actual gluten workflow scripts and reject hidden failures."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gluten.yml"


class GlutenWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gluten-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gluten"]
        self.steps = {step.get("id", step["name"]): step for step in self.job["steps"]}
        self.env = dict(os.environ, **self.job["env"])
        self.env.update(GITHUB_OUTPUT=str(self.root / "output"), RUNNER_TEMP=str(self.root))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.tool("timeout", 'case "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"\n')
        self.values = {}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outcome"] = "success"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
        self.values.update({
            "steps.install.outputs.install_mode": "github_source",
            "steps.install.outputs.install_status": "success",
            "steps.version.outputs.version": self.env["BASELINE_VERSION"],
        })

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def render(self, script):
        def replace(match):
            for term in match.group(1).split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term[1:-1]
                value = self.values.get(term)
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)

    def run_step(self, name, **env):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"])],
            cwd=self.root, env=dict(self.env, **env), capture_output=True, text=True, timeout=15,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_summary_all_checks_pass_and_durations_are_counted(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        self.assertEqual("21", outputs["duration"])
        self.assertEqual("0", outputs["failed"])

    def test_every_core_requires_status_and_successful_actual_outcome(self):
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("skipped", "success"),
                                    ("failed", "success"), ("unknown", "success"),
                                    ("passed", ""), ("passed", "failure"),
                                    ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    self.values[f"steps.test{number}.outputs.status"] = status
                    self.values[f"steps.test{number}.outcome"] = outcome
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["core_failed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("0", outputs["skipped"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])
                self.values[f"steps.test{number}.outputs.status"] = "passed"
                self.values[f"steps.test{number}.outcome"] = "success"

    def test_all_missing_results_fail_closed(self):
        self.values.clear()
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_regression_skip_requires_success_and_exact_applicability(self):
        self.values["steps.test6.outputs.status"] = "skipped"
        self.values["steps.test6.outputs.decision"] = "no_newer_stable_available"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped")))
        for decision, outcome in (("", "success"), ("runtime_validation_not_automated", "success"),
                                  ("not_configured", "success"), ("no_newer_stable_available", "failure"),
                                  ("no_newer_stable_available", "skipped"), ("no_newer_stable_available", "")):
            with self.subTest(decision=decision, outcome=outcome):
                self.values["steps.test6.outputs.decision"] = decision
                self.values["steps.test6.outcome"] = outcome
                result, outputs = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["core_failed"])

    def test_regression_failed_outcome_overrides_passed_output(self):
        self.values["steps.test6.outcome"] = "failure"
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["failed"])


    def test_missing_or_unresolved_baseline_tag_cannot_pass_install(self):
        self.tool("git", 'case "$1" in ls-remote) exit "${TAG_FAILURE:-0}";; *) exit 99;; esac\n')
        for failure in ("0", "1"):
            result, outputs = self.run_step("install", TAG_FAILURE=failure)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["install_status"])

    def test_dashboard_readme_does_not_expand_upstream_pattern(self):
        (self.root / "README.md").write_text("dashboard")
        (self.root / "baseline-src").mkdir()
        (self.root / "baseline-src/README").write_text("Gluten source documentation")
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_logged_failure_and_missing_build_are_two_core_failures(self):
        self.values["steps.test1.outputs.status"] = "failed"
        self.values["steps.test1.outcome"] = "failure"
        self.values["steps.test5.outputs.status"] = ""
        self.values["steps.test5.outcome"] = "failure"
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("4", "2", "0", "2"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_baseline_and_candidate_execute_identical_bounded_probe(self):
        self.assertIn('bash -euo pipefail -c "$GLUTEN_SMOKE"', self.steps["test5"]["run"])
        self.assertIn('bash -euo pipefail -c "$GLUTEN_SMOKE"', self.steps["test6"]["with"]["limited_cpu_probe"])
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])

    def test_source_evidence_has_real_module_patterns(self):
        (self.root / "baseline-src/gluten-core").mkdir(parents=True)
        page = self.root / self.env["PACKAGE_PAGE"]
        page.parent.mkdir(parents=True)
        page.write_text("Gluten")
        result, outputs = self.run_step("test1")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_compile_uses_supported_profile_and_scala_class_directory(self):
        (self.root / "baseline-src/gluten-core").mkdir(parents=True)
        for file in ("pom.xml", "gluten-core/pom.xml"):
            (self.root / "baseline-src" / file).write_text("<project/>")
        self.tool("mvn", 'case " $* " in *" -Pspark-3.4 -pl gluten-core -am clean compile "*) ;; *) exit 2;; esac\n'
                  'if [ -n "$BUILD_FAIL" ]; then echo "fixture missing Spark shim"; exit 1; fi\n'
                  'if [ -z "$NO_CLASSES" ]; then mkdir -p gluten-core/target/scala-2.12/classes; touch gluten-core/target/scala-2.12/classes/Smoke.class; fi\n')
        for fault in ("BUILD_FAIL", "NO_CLASSES"):
            result, outputs = self.run_step("test5", **{fault: "1"})
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
            if fault == "BUILD_FAIL":
                self.assertIn("fixture missing Spark shim", result.stdout)
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

if __name__ == "__main__":
    unittest.main()
