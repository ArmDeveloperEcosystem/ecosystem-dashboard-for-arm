"""Keep Cobbler's installed CLI proof and all six outcomes fail-closed."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-cobbler.yml"


class CobblerWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-cobbler"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="cobbler-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def render(self, script, overrides=None):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values["steps.version.outputs.version"] = "3.3.6"
        values.update(overrides or {})
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def run_step(self, step, overrides=None, **environment):
        output = self.root / "output"
        output.write_text("")
        env = dict(os.environ, **self.job["env"])
        env.update(GITHUB_OUTPUT=str(output), GITHUB_WORKSPACE=str(self.root),
                   RUNNER_TEMP=str(self.root), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        env.update(environment)
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[step]["run"], overrides)],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def executable(self, name, text):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + text)
        path.chmod(0o755)

    def test_no_baseline_bump_and_candidate_has_exact_version_binding(self):
        self.assertEqual("v3.3.6", self.job["env"]["COBBLER_BASELINE_VERSION"])
        self.assertEqual("v3.3.7", self.job["env"]["COBBLER_NEXT_VERSION"])
        self.assertIn('test "$NEXT_VERSION_REPORTED" = "$LATEST_VERSION"', self.steps["test6"]["run"])
        self.assertIn('assert d.version == os.environ["EXPECTED_VERSION"]', self.job["env"]["COBBLER_CLI_SMOKE"])

    def test_all_outputs_are_visible_to_existing_observation_audit(self):
        for number in range(1, 7):
            for output in ("status", "duration"):
                with self.subTest(number=number, output=output):
                    self.assertTrue(observation_audit._step_emits_output(
                        WORKFLOW.parents[2], self.steps[f"test{number}"], output,
                    ))

    def test_original_skipped_signature_check_is_a_core_failure(self):
        result, outputs = self.run_step("summary", {"steps.test4.outputs.status": "skipped"})
        self.assertEqual(1, result.returncode)
        self.assertEqual(("5", "1", "0", "1", "failure"), tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))

    def test_missing_or_failed_outcomes_cannot_pass(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    result, outputs = self.run_step("summary", {f"steps.test{number}.outcome": outcome})
                    self.assertEqual(1, result.returncode)
                    self.assertEqual("1", outputs["failed"])

    def test_missing_status_cannot_pass(self):
        for number in range(1, 7):
            result, outputs = self.run_step("summary", {f"steps.test{number}.outputs.status": ""})
            self.assertEqual(1, result.returncode)
            self.assertEqual("1", outputs["failed"])

    def test_only_explicit_no_newer_candidate_is_na(self):
        result, outputs = self.run_step("summary")
        self.assertEqual((0, "6", "0", "0"), (result.returncode, outputs["passed"], outputs["failed"], outputs["skipped"]))
        for decision in ("", "baseline_failed", "runtime_validation_not_automated", "no_newer_stable_available"):
            result, outputs = self.run_step("summary", {"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": decision})
            self.assertEqual(0 if decision == "no_newer_stable_available" else 1, result.returncode)

    def test_signature_command_failure_preserves_status_and_duration(self):
        self.executable("timeout", 'shift 3\nexec "$@"\n')
        self.executable("sudo", "exit 37\n")
        result, outputs = self.run_step("test4")
        self.assertEqual(37, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertTrue(outputs["duration"].isdigit())

    def signature_assertions(self, version="3.3.6", commands=None, exit_code=2):
        commands = commands if commands is not None else ["reload", "report", "update"]
        (self.root / "signature-help.log").write_text("Usage: cobbler [options]\n  --name=NAME\n")
        venv = self.root / "venv/bin"
        venv.mkdir(parents=True, exist_ok=True)
        cli = venv / "cobbler"
        cli.write_text("#!/bin/bash\nif [ \"$1\" = --version ]; then\n"
                       + f"  printf '%s\\n' 'Cobbler {version}'\n  exit 0\nfi\n"
                       + "printf '%s\\n' " + " ".join(json.dumps("cobbler signature " + c) for c in commands)
                       + f"\nexit {exit_code}\n")
        cli.chmod(0o755)
        helper = self.job["env"]["COBBLER_CLI_SMOKE"]
        script = helper[helper.index("grep -Fq -- '--name'"):]
        return subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                              env=dict(os.environ, WORKDIR=str(self.root), VENV=str(venv.parent), EXPECTED_VERSION="3.3.6"),
                              capture_output=True, text=True, timeout=10)

    def test_signature_help_requires_all_three_real_commands(self):
        self.assertEqual(0, self.signature_assertions().returncode)
        commands = ["reload", "report", "update"]
        for missing in commands:
            with self.subTest(missing=missing):
                self.assertNotEqual(0, self.signature_assertions(commands=[c for c in commands if c != missing]).returncode)

    def test_signature_help_rejects_wrong_runtime_version_and_exit(self):
        for version in ("3.3.5", "3.3.6.1", "3.3.7", "unknown"):
            self.assertNotEqual(0, self.signature_assertions(version=version).returncode)
        for code in (0, 1, 17):
            self.assertNotEqual(0, self.signature_assertions(exit_code=code).returncode)

    def test_missing_install_metadata_never_falls_back_to_configured_version(self):
        result, outputs = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", outputs)

    def test_candidate_is_failed_not_deferred_after_any_core_failure(self):
        for number in range(1, 6):
            result, outputs = self.run_step("test6", {f"steps.test{number}.outcome": "failure"})
            self.assertEqual(1, result.returncode)
            self.assertEqual("failed", outputs["status"])
            self.assertEqual("baseline_failed", outputs["decision"])
            self.assertTrue(outputs["duration"].isdigit())

    def test_candidate_reported_version_cannot_be_older_or_merely_nonempty(self):
        assertion = next(line.strip() for line in self.steps["test6"]["run"].splitlines()
                         if 'test "$NEXT_VERSION_REPORTED" = "$LATEST_VERSION"' in line)
        for version in ("3.3.6", "3.3.70", "unknown", ""):
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", assertion],
                                    env=dict(os.environ, NEXT_VERSION_REPORTED=version, LATEST_VERSION="3.3.7"),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(1, result.returncode)

    def test_local_services_are_bounded_and_existing_state_is_not_reused(self):
        helper = self.job["env"]["COBBLER_CLI_SMOKE"]
        self.assertIn('test ! -e "$DIRECTORY"', helper)
        self.assertIn('test ! -L "$DIRECTORY"', helper)
        self.assertIn("Listen 127.0.0.1:$HTTP_PORT", helper)
        self.assertIn('"$VENV/bin/cobblerd" -F', helper)
        self.assertIn('"$VENV/bin/cobbler" signature report --help', helper)
        self.assertIn('trap finish EXIT', helper)
        self.assertIn("180s sudo env", self.steps["test4"]["run"])
        self.assertNotIn("signature update\n", helper)


if __name__ == "__main__":
    unittest.main()
