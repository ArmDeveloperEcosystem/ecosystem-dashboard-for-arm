"""Execute Dqlite workflow contracts; native build evidence is recorded separately."""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit
from package_result_policy import expected_regression_metadata

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-dqlite.yml"


class DqliteWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dqlite-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-dqlite"]
        self.steps = {step.get("id", step["name"]): step for step in self.job["steps"]}
        self.env = dict(os.environ, **self.job["env"], RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"), PYTHONDONTWRITEBYTECODE="1")
        self.values = {
            "steps.install.outputs.install_status": "success",
            "steps.install.outputs.install_mode": "github_source",
            "steps.install.outcome": "success",
            "steps.version.outputs.status": "passed",
            "steps.version.outputs.version": self.env["BASELINE_VERSION"],
            "steps.version.outcome": "success",
            "steps.test6.outputs.decision": "validated_next_release",
        }
        for i in range(1, 7):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        result, _ = self.run_step("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = importlib.util.spec_from_file_location(
            "dqlite_check", self.root / "dqlite-tools/check.py")
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)

    def render(self, text):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def run_step(self, name, **env):
        step = self.steps[name]
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        step_env = {key: self.render(value) for key, value in step.get("env", {}).items()}
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(step["run"])],
            cwd=self.root, env={**self.env, **step_env, **env},
            capture_output=True, text=True, timeout=20)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return result, outputs

    def stub_helper(self):
        directory = self.root / "bin"
        directory.mkdir()
        executable = directory / "python3"
        executable.write_text(
            "#!/bin/bash\nset -eu\n"
            'if [[ "$1" == */dqlite-tools/check.py ]]; then\n'
            '  printf "%s\\n" "$2" >> "$RUNNER_TEMP/calls"\n'
            '  if [ "$2" = "${FAIL_MODE:-}" ]; then exit 23; fi\n'
            '  exit 0\nfi\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        executable.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]

    def calls(self):
        path = self.root / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def assert_failed(self, result, outputs):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "failed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_actual_auditor_sees_all_required_outputs(self):
        summary = self.steps["summary"]["run"]
        self.assertTrue(audit._shell_code_contains(summary, "steps.test6.outputs.status"))
        for number in range(1, 7):
            self.assertTrue(audit._shell_code_contains(
                summary, f"steps.test{number}.outputs.duration"))
            for output in ("status", "duration"):
                with self.subTest(number=number, output=output):
                    self.assertTrue(audit._step_emits_output(
                        WORKFLOW.parents[2], self.steps[f"test{number}"], output))
        for output in ("decision", "current_version", "latest_version",
                       "next_installed_version", "regression_result", "comparison"):
            self.assertTrue(audit._step_emits_output(
                WORKFLOW.parents[2], self.steps["test6"], output))
        pairs = set()
        for transaction in audit._github_output_transactions(self.steps["test6"]["run"]):
            values = dict(transaction)
            if "decision" in values and "status" in values:
                pairs.add((values["decision"], values["status"]))
        self.assertEqual(pairs, {("baseline_failed", "skipped"),
                                 ("baseline_install_failed", "skipped"),
                                 ("validated_next_release", "passed"),
                                 ("next_regression_failed", "failed")})
        for decision, status in pairs:
            canonical = expected_regression_metadata(
                decision=decision, core_failed=int(decision.startswith("baseline_")))
            self.assertEqual(status, canonical["status"])

    def test_core_exit_traps_publish_failure_and_duration(self):
        self.stub_helper()
        for number, mode in enumerate(("ownership", "runtime", "metadata", "linkage", "sql"), 1):
            with self.subTest(number=number):
                result, outputs = self.run_step(f"test{number}", FAIL_MODE=mode)
                self.assert_failed(result, outputs)
                result, outputs = self.run_step(f"test{number}")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(outputs["status"], "passed")
                self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_missing_helper_is_failure_for_every_core(self):
        (self.root / "dqlite-tools/check.py").unlink()
        for number in range(1, 6):
            with self.subTest(number=number):
                self.assert_failed(*self.run_step(f"test{number}"))

    def test_version_never_publishes_unverified_release(self):
        self.stub_helper()
        for mode in ("runtime", "metadata"):
            result, outputs = self.run_step("version", FAIL_MODE=mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs, {"status": "failed"})
        result, outputs = self.run_step("version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(outputs, {"status": "passed", "version": "1.18.2"})
        self.values["steps.install.outcome"] = "failure"
        self.assertEqual(self.run_step("version")[1], {"status": "failed"})

    def test_regression_requires_candidate_build_identity_and_runtime(self):
        self.stub_helper()
        result, outputs = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["build", "runtime", "metadata", "sql"])
        self.assertEqual(outputs["status"], "passed")
        self.assertEqual(outputs["decision"], "validated_next_release")
        self.assertEqual(outputs["next_installed_version"], "1.18.7")

    def test_candidate_build_identity_and_sql_faults_fail_closed(self):
        self.stub_helper()
        for mode in ("build", "runtime", "metadata", "sql"):
            with self.subTest(mode=mode):
                result, outputs = self.run_step("test6", FAIL_MODE=mode)
                self.assert_failed(result, outputs)
                self.assertEqual(outputs["decision"], "next_regression_failed")
                self.assertEqual(outputs["next_installed_version"],
                                 "1.18.7" if mode == "sql" else "not_installed")

    def test_candidate_must_be_newer(self):
        self.stub_helper()
        result, outputs = self.run_step("test6", CANDIDATE_VERSION="1.18.2")
        self.assert_failed(result, outputs)
        self.assertEqual(self.calls(), [])

    def test_install_guard_never_calls_candidate(self):
        self.stub_helper()
        for key in ("steps.install.outcome", "steps.install.outputs.install_status",
                    "steps.install.outputs.install_mode"):
            original = self.values[key]
            for value in ("", "failure", "cancelled", "package_manager"):
                self.values[key] = value
                result, outputs = self.run_step("test6")
                self.assertEqual(result.returncode, 0)
                self.assertEqual(outputs["decision"], "baseline_install_failed")
                self.assertEqual(outputs["status"], "skipped")
                self.assertEqual(self.calls(), [])
            self.values[key] = original

    def test_core_and_version_guards_never_call_candidate(self):
        self.stub_helper()
        keys = ["steps.version.outcome", "steps.version.outputs.status",
                "steps.version.outputs.version"]
        keys += [f"steps.test{i}.{field}" for i in range(1, 6)
                 for field in ("outcome", "outputs.status")]
        for key in keys:
            original = self.values[key]
            for value in ("", "failure", "skipped", "unknown"):
                with self.subTest(key=key, value=value):
                    self.values[key] = value
                    result, outputs = self.run_step("test6")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(outputs["decision"], "baseline_failed")
                    self.assertEqual(outputs["status"], "skipped")
                    self.assertEqual(self.calls(), [])
            self.values[key] = original

    def test_six_passes_sum_all_durations(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {"passed": "6", "failed": "0", "core_failed": "0",
                                   "skipped": "0", "duration": "21",
                                   "overall_status": "success", "badge_status": "passing"})

    def test_every_invalid_or_missing_outcome_status_and_duration_fails(self):
        for number in range(1, 7):
            for field, values in (("outcome", ("", "failure", "skipped", "cancelled", "bogus")),
                                  ("outputs.status", ("", "failed", "skipped", "bogus")),
                                  ("outputs.duration", ("", "-1", "1.5", "bogus", "1+2"))):
                key = f"steps.test{number}.{field}"
                original = self.values[key]
                for value in values:
                    with self.subTest(number=number, field=field, value=value):
                        self.values[key] = value
                        result, outputs = self.run_step("summary")
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(outputs["badge_status"], "failing")
                        self.assertEqual(outputs["core_failed"], "0" if number == 6 else "1")
                        self.assertGreaterEqual(int(outputs["failed"]), 1)
                        self.assertEqual(sum(int(outputs[k]) for k in ("passed", "failed", "skipped")), 6)
                self.values[key] = original

    def test_only_approved_baseline_skip_with_core_failure_is_counted(self):
        for decision in ("baseline_failed", "baseline_install_failed"):
            self.values["steps.test6.outputs.status"] = "skipped"
            self.values["steps.test6.outputs.decision"] = decision
            self.assertEqual(self.run_step("summary")[1]["skipped"], "0")
            self.values["steps.test2.outputs.status"] = "failed"
            result, outputs = self.run_step("summary")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((outputs["passed"], outputs["failed"], outputs["skipped"]),
                             ("4", "1", "1"))
            self.assertEqual(outputs["badge_status"], "failing")
            self.assertEqual(outputs["duration"], "21")
            self.values["steps.test2.outputs.status"] = "passed"

    def test_pm_metadata_and_unknown_decisions_cannot_hide_source_regression(self):
        for decision in ("", "not_configured", "not_applicable_package_manager",
                         "validated_next_release_metadata", "next_regression_failed"):
            for status in ("passed", "skipped"):
                self.values["steps.test6.outputs.status"] = status
                self.values["steps.test6.outputs.decision"] = decision
                result, outputs = self.run_step("summary")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["failed"], "1")
                self.assertEqual(outputs["skipped"], "0")

    def test_all_missing_results_are_six_failures(self):
        self.values.clear()
        result, outputs = self.run_step("summary")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((outputs["passed"], outputs["failed"], outputs["skipped"],
                          outputs["core_failed"]), ("0", "6", "0", "5"))

    def test_missing_test6_does_not_invent_a_candidate_decision(self):
        binding = self.job["outputs"]["regression_decision"]
        self.assertEqual(binding, "${{ steps.test6.outputs.decision || 'not_configured' }}")
        for key in list(self.values):
            if key.startswith("steps.test6."):
                del self.values[key]
        self.assertEqual(self.render(binding), "not_configured")
        with self.assertRaisesRegex(ValueError, "unapproved regression decision"):
            expected_regression_metadata(decision=self.render(binding), core_failed=0)
        result, outputs = self.run_step("summary")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((outputs["passed"], outputs["failed"], outputs["skipped"]),
                         ("5", "1", "0"))
        self.assertEqual(outputs["badge_status"], "failing")

    def release(self, version="1.18.2"):
        with patch.dict(os.environ, RUNNER_TEMP=str(self.root)):
            return self.helper.Release(version, self.env["BASELINE_COMMIT"])

    def test_actual_runtime_version_must_equal_requested_release(self):
        release = self.release()
        for number in (11701, 11807, 0, -1):
            with self.subTest(number=number), patch.object(release, "ownership"), \
                    patch.object(Path, "resolve", return_value=Path("/verified/libdqlite.so")), \
                    patch.object(self.helper.ctypes, "CDLL") as library:
                library.return_value.dqlite_version_number.return_value = number
                with self.assertRaisesRegex(RuntimeError, "Installed library reports"):
                    release.runtime()

    def test_official_origin_head_tag_and_dirty_source_are_rejected(self):
        release = self.release()
        expected = [self.helper.OFFICIAL, release.commit, release.commit, ""]
        for index, bad in enumerate(("https://example.org/dqlite.git", "a" * 40,
                                     "b" * 40, " M include/dqlite.h")):
            values = expected.copy()
            values[index] = bad
            with self.subTest(index=index), patch.object(release, "git", side_effect=values):
                with self.assertRaises(RuntimeError):
                    release.source_identity()

    def test_moved_official_tag_is_rejected_before_any_build(self):
        release = self.release()
        with patch.object(self.helper.os, "uname") as uname, \
                patch.object(self.helper, "run") as run, \
                patch.object(release, "git", side_effect=["", "", "f" * 40]):
            uname.return_value.machine = "aarch64"
            with self.assertRaisesRegex(RuntimeError, "Official tag changed"):
                release.build()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0:2], ["git", "init"])

    def test_empty_skipped_or_nonexecuted_sql_output_cannot_pass(self):
        release = self.release()
        for text in ("", "0 of 0 (100%) tests successful, 0 (0%) test skipped",
                     "1 of 1 (100%) tests successful, 1 (100%) test skipped"):
            with self.subTest(text=text), patch.object(release, "linkage"), \
                    patch.object(self.helper, "run", return_value=text):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    release.sql()

    def test_source_only_workflow_keeps_reviewed_action_and_read_permissions(self):
        self.assertEqual(self.job["env"]["BASELINE_COMMIT"], "559328ca8bdeca27cb24967ec632a2f1c68c9f18")
        self.assertEqual(self.job["env"]["CANDIDATE_COMMIT"], "91e3e2f90874e4ec3b45cde965f266342846531b")
        self.assertEqual(yaml.safe_load(WORKFLOW.read_text())["permissions"], {"contents": "read"})
        actions = [step["uses"] for step in self.job["steps"] if "uses" in step]
        self.assertEqual(actions, ["actions/checkout@11d5960a326750d5838078e36cf38b85af677262"])
        self.assertNotIn("ppa:", WORKFLOW.read_text())
        self.assertNotIn("go-dqlite", WORKFLOW.read_text())


if __name__ == "__main__":
    unittest.main()
