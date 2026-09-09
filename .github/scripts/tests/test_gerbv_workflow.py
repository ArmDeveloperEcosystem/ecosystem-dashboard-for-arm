"""Exercise the actual gerbv workflow scripts and reject hidden failures."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gerbv.yml"


class GerbvWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gerbv-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gerbv"]
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
        self.values["steps.test6.outputs.decision"] = "not_applicable_package_manager"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped")))
        for decision, outcome in (("", "success"), ("runtime_validation_not_automated", "success"),
                                  ("not_configured", "success"), ("not_applicable_package_manager", "failure"),
                                  ("not_applicable_package_manager", "skipped"), ("not_applicable_package_manager", "")):
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


    def test_logged_export_failure_is_failed_core_with_one_applicable_skip(self):
        self.values["steps.test5.outputs.status"] = ""
        self.values["steps.test5.outcome"] = "failure"
        self.values["steps.test6.outputs.status"] = "skipped"
        self.values["steps.test6.outputs.decision"] = "not_applicable_package_manager"
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("4", "1", "1", "1"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_export_is_sized_bounded_and_cleaned_on_success_or_failure(self):
        gerbv = self.tool("gerbv", 'test "$1" = "-x" && test "$2" = "png" && test "$3" = "-w" && test "$4" = "256x256" || exit 2\n'
                          'if [ -n "$EXPORT_FAIL" ]; then echo "Exporting error" >&2; exit 1; fi\nprintf "PNG fixture" > "$6"\n')
        self.tool("file", 'if [ -n "$BAD_PNG" ]; then echo "empty"; else echo "PNG image data, 256 x 256"; fi\n')
        self.values["steps.install.outputs.command_path"] = str(gerbv)
        for fault in ("EXPORT_FAIL", "BAD_PNG"):
            result, outputs = self.run_step("test5", **{fault: "1"})
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
            self.assertEqual([], list(self.root.glob("gerbv-smoke.*")))
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual([], list(self.root.glob("gerbv-smoke.*")))

    def test_help_with_failed_exit_cannot_pass_from_matching_error_text(self):
        gerbv = self.tool("gerbv", 'echo "gerbv version error"; exit 1\n')
        self.values["steps.install.outputs.command_path"] = str(gerbv)
        self.tool("dpkg-query", 'echo "2.6.0-1"\n')
        for step in ("test2", "test3"):
            result, outputs = self.run_step(step)
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", outputs.get("status"))

    def test_complete_gerbv_usage_with_documented_exit_one_passes(self):
        gerbv = self.tool("gerbv", 'printf "Usage: gerbv [OPTIONS...] [FILE...]\\nAvailable options:\\n  -x, --export=<png|pdf>\\n"\nexit "${FIXTURE_HELP_RESULT:-1}"\n')
        self.values["steps.install.outputs.command_path"] = str(gerbv)
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        for result_code in ("2", "124", "137"):
            result, outputs = self.run_step("test3", FIXTURE_HELP_RESULT=result_code)
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", outputs.get("status"))

if __name__ == "__main__":
    unittest.main()
