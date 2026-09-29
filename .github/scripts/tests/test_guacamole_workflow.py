"""Execute the Guacamole workflow's version and summary shell with controlled CLIs."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit
import package_result_policy as result_policy
import promote_package_results as publisher


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-guacamole.yml"
BANNER = "Guacamole proxy daemon (guacd) version "
VERSION = "1.3.0"
PACKAGE_VERSION = "1.3.0-1.3ubuntu1"


def render_value(source, values):
    def expression(match):
        for term in match[1].split("||"):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if term.isdigit():
                return term
            if values.get(term):
                return str(values[term])
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)


class PMDecisionChecks:
    """Run the same decision contract against each owned workflow's actual shell."""

    def summary_values(self):
        values = {**self.verified(), "steps.install.outcome": "success",
                  "steps.version.outcome": "success"}
        for i in range(1, 7):
            values.update({f"steps.test{i}.outcome": "success",
                           f"steps.test{i}.outputs.status": "passed" if i < 6 else "skipped",
                           f"steps.test{i}.outputs.duration": "0"})
        values["steps.test6.outputs.decision"] = "not_applicable_package_manager"
        return values

    def pm_guard(self, values):
        result, outputs = self.run_step("test6", values)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("0", outputs["duration"])
        values.update({f"steps.test6.outputs.{key}": value for key, value in outputs.items()})
        values["steps.test6.outcome"] = "success"
        return outputs

    def pm_summary(self, values, counts):
        result, outputs = self.run_step("summary", values)
        self.assertEqual(1 if counts[1] else 0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(tuple(map(str, counts)), tuple(outputs[key] for key in
                         ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual("failure" if counts[1] else "success", outputs["overall_status"])
        self.assertEqual("failing" if counts[1] else "passing", outputs["badge_status"])
        values.update({f"steps.summary.outputs.{key}": value for key, value in outputs.items()})
        return outputs

    def pm_collect(self, values, api_overrides=None):
        repo = self.workflow_path.parents[2]
        slug = self.workflow_path.stem.removeprefix("test-")
        job_id = f"test-{slug}"
        values = {**values, "github.job": job_id, "github.run_id": "123",
                  "github.run_attempt": "1", "steps.metadata.outputs.package_slug": slug,
                  "steps.metadata.outputs.dashboard_link": f"/linux/opensource_packages/{slug}",
                  "steps.metadata.outputs.timestamp": "2026-09-09T12:00:00Z"}
        outputs = {key: render_value(value, values) for key, value in self.job["outputs"].items()}
        api_steps = [{"name": self.steps[f"test{i}"]["name"], "number": i,
                      "conclusion": (api_overrides or {}).get(i, values[f"steps.test{i}.outcome"])}
                     for i in range(1, 7)]
        job = {"id": 456, "name": f"{job_id} / {job_id}", "steps": api_steps,
               "conclusion": outputs["run_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456"}
        action = yaml.safe_load((repo / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory(prefix="pm-decision-collector-") as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(repo / ".github/scripts")
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GH_TOKEN="",
                       NEEDS_JSON=json.dumps({job_id: {"result": outputs["run_status"], "outputs": outputs}}),
                       RUN_JOBS_JSON=json.dumps({"jobs": [job]}), BATCH_NUMBER="1", BATCH_TITLE="Batch 1",
                       GITHUB_SERVER_URL="https://github.com", GITHUB_API_URL="https://api.github.com",
                       GITHUB_REPOSITORY="example/project", GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1",
                       GITHUB_OUTPUT=str(root / "outputs"), GITHUB_STEP_SUMMARY=str(root / "summary"))
            result = subprocess.run([sys.executable, "-B", "-c", source], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=30)
            artifact = root / f"test-results/{slug}-test-results/{slug}.json"
            return result, json.loads(artifact.read_text()) if artifact.exists() else None

    def pm_publishable(self, values, summary):
        result, payload = self.pm_collect(values)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        tests, metadata = payload["tests"], payload["metadata"]
        expected = summary["overall_status"]
        self.assertEqual(expected, result_policy.validate_six_test_result(
            details=tests["details"], passed=tests["passed"], failed=tests["failed"],
            skipped=tests["skipped"], core_failed=metadata["core_failed"],
            decision=metadata["regression_decision"]))
        self.assertEqual(expected, result_policy.validate_publishable_result(payload))
        for key in ("passed", "failed", "skipped"):
            self.assertEqual(int(summary[key]), tests[key])
        self.assertEqual(int(summary["core_failed"]), metadata["core_failed"])
        self.assertEqual(int(summary["duration"]), tests["duration_seconds"])
        self.assertEqual(summary["badge_status"], metadata["badge_status"])
        self.assertEqual(values["steps.test6.outputs.decision"], metadata["regression_decision"])
        registration = {
            "batch_title": "Batch 1", "workflow_path": f".github/workflows/{self.workflow_path.name}",
            "run_id": "123", "run_attempt": "1", "job_name": payload["run"]["job_name"],
            "job_url": "https://github.com/example/project/actions/runs/123/job/456",
            "job_conclusion": expected, "job_started_at": "2026-09-09T11:00:00Z",
            "job_completed_at": "2026-09-09T13:00:00Z", "resolution_status": "resolved",
        }
        for policy in ("compatibility", "strict"):
            arguments = dict(expected_slug=metadata["package_slug"], expected_repository="example/project",
                             expected_registration=registration, publication_role="candidate",
                             validation_policy=policy)
            if payload["package"]["version"] == "unknown":
                with self.assertRaisesRegex(publisher.PromotionError, "package version must not be a placeholder"):
                    publisher.validate_persisted_result(payload, **arguments)
            else:
                self.assertEqual(expected, publisher.validate_persisted_result(payload, **arguments))
        return payload

    def test_pm_auditor_sees_all_three_literal_branches(self):
        repo = self.workflow_path.parents[2]
        self.assertEqual("always()", self.steps["test6"]["if"])
        self.assertEqual("always()", self.steps["summary"]["if"])
        self.assertEqual({("not_applicable_package_manager", "skipped"),
                          ("baseline_failed", "skipped"), ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(repo, self.steps["test6"])))
        for key in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(repo, self.steps["summary"], key), key)

    def test_pm_positive_and_each_core_failure_reach_collector_and_publisher(self):
        for failed in range(6):
            with self.subTest(failed=failed):
                values = self.summary_values()
                values.update({f"steps.test{i}.outputs.duration": str(i) for i in range(1, 6)})
                if failed:
                    values.update({f"steps.test{failed}.outputs.status": "failed",
                                   f"steps.test{failed}.outcome": "failure"})
                guard = self.pm_guard(values)
                self.assertEqual("baseline_failed" if failed else "not_applicable_package_manager", guard["decision"])
                summary = self.pm_summary(values, (4, 1, 1, 1) if failed else (5, 0, 1, 0))
                self.assertEqual("15", summary["duration"])
                self.pm_publishable(values, summary)
                if failed:
                    result, payload = self.pm_collect(values, {failed: "success"})
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("emitted failure counts contradict test details", result.stderr)
                    self.assertIsNone(payload)
                    for decision in ("not_applicable_package_manager", "baseline_install_failed"):
                        values["steps.test6.outputs.decision"] = decision
                        self.pm_summary(values, (4, 2, 0, 1))

    def test_pm_core_status_and_outcome_must_both_succeed(self):
        for i in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("unknown", "success"), ("passed", ""), ("passed", "failure"),
                                    ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(test=i, status=status, outcome=outcome):
                    values = self.summary_values()
                    values.update({f"steps.test{i}.outputs.status": status, f"steps.test{i}.outcome": outcome})
                    self.assertEqual("baseline_failed", self.pm_guard(values)["decision"])
                    self.pm_summary(values, (4, 1, 1, 1))

    def test_pm_install_failure_precedes_missing_version_and_core_results(self):
        for outcome in ("failure", "cancelled", "skipped", ""):
            with self.subTest(outcome=outcome):
                values = {"steps.install.outcome": outcome}
                for i in range(1, 6):
                    values[f"steps.test{i}.outcome"] = "skipped"
                self.assertEqual("baseline_install_failed", self.pm_guard(values)["decision"])
                summary = self.pm_summary(values, (0, 5, 1, 5))
                result, payload = self.pm_collect(values)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("emitted failure counts contradict test details", result.stderr)
                self.assertIsNone(payload)
                # A separate visible-failure fixture must carry its own failed API records.
                for i in range(1, 6):
                    values.update({f"steps.test{i}.outcome": "failure",
                                   f"steps.test{i}.outputs.status": "failed"})
                self.assertEqual("baseline_install_failed", self.pm_guard(values)["decision"])
                summary = self.pm_summary(values, (0, 5, 1, 5))
                self.pm_publishable(values, summary)
                values["steps.test6.outputs.decision"] = "baseline_failed"
                self.pm_summary(values, (0, 6, 0, 5))
                values = self.summary_values()
                values["steps.install.outcome"] = outcome
                self.assertEqual("baseline_install_failed", self.pm_guard(values)["decision"])
                self.pm_summary(values, (5, 1, 0, 0))

    def test_pm_version_failure_and_unavailability_cannot_claim_good_baseline(self):
        cases = [("outcome", value) for value in ("failure", "cancelled", "skipped", "")]
        cases += [("outputs.status", value) for value in ("failed", "skipped", "", "unknown")]
        cases += [("outputs.version", value) for value in ("", "unknown")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = self.summary_values()
                values[f"steps.version.{key}"] = value
                self.assertEqual("baseline_failed", self.pm_guard(values)["decision"])
                self.pm_summary(values, (5, 1, 0, 0))
                values.update({"steps.test3.outputs.status": "failed", "steps.test3.outcome": "failure"})
                self.assertEqual("baseline_failed", self.pm_guard(values)["decision"])
                summary = self.pm_summary(values, (4, 1, 1, 1))
                self.pm_publishable(values, summary)

    def test_pm_skip_requires_exact_decision_status_and_successful_outcome(self):
        cases = [("outcome", value) for value in ("failure", "cancelled", "skipped", "")]
        cases += [("outputs.status", value) for value in ("", "passed", "failed", "unknown")]
        cases += [("outputs.decision", value) for value in
                  ("", "not_configured", "baseline_failed", "baseline_install_failed", "runtime_validation_not_automated")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = self.summary_values()
                self.pm_guard(values)
                values[f"steps.test6.{key}"] = value
                self.pm_summary(values, (5, 1, 0, 0))
        self.pm_summary({}, (0, 6, 0, 5))

    def test_pm_durations_are_bounded_decimal_and_required(self):
        for i in range(1, 7):
            for duration in ("", "bad", "-1", "1.5", "1000000", "1+1", " 2"):
                with self.subTest(test=i, duration=duration):
                    values = self.summary_values()
                    self.pm_guard(values)
                    values[f"steps.test{i}.outputs.duration"] = duration
                    summary = self.pm_summary(values, (4, 2, 0, 1) if i < 6 else (5, 1, 0, 0))
                    self.assertEqual("0", summary["duration"])
        values = self.summary_values()
        self.pm_guard(values)
        values.update({f"steps.test{i}.outputs.duration": "08" for i in range(1, 7)})
        self.assertEqual("48", self.pm_summary(values, (5, 0, 1, 0))["duration"])
        values["steps.test6.outputs.duration"] = "999999"
        self.assertEqual("1000039", self.pm_summary(values, (5, 0, 1, 0))["duration"])

    def test_pm_failed_skip_step_cannot_be_hidden_by_emitted_skip(self):
        values = self.summary_values()
        values.update({"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"})
        self.pm_guard(values)
        self.pm_summary(values, (4, 1, 1, 1))
        result, payload = self.pm_collect(values, {6: "failure"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("emitted skipped count contradicts test details", result.stderr)
        self.assertIsNone(payload)
        for outcome in ("failure", "cancelled", "skipped", ""):
            values["steps.test6.outcome"] = outcome
            self.pm_summary(values, (4, 2, 0, 1))


class GuacamoleWorkflowTests(PMDecisionChecks, unittest.TestCase):
    workflow_path = WORKFLOW

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="guacamole-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-guacamole"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, executable in (("python3", sys.executable), ("date", shutil.which("date"))):
            (self.bin / name).symlink_to(executable)
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        GITHUB_OUTPUT=str(self.root / "output"),
                        CLI_STDOUT=BANNER + VERSION + "\n", CLI_STDERR="", CLI_RC="0",
                        PM_OUTPUT=self.package_row(), PM_RC="0", FILES_RC="0",
                        PM_FILES=str(self.bin / "guacd") + "\n")
        self.stub("guacd", """
test "$#" = 1
test "$1" = -v
test "$LC_ALL" = C
printf '%s' "$CLI_STDOUT"
printf '%s' "$CLI_STDERR" >&2
exit "$CLI_RC"
""")
        self.stub("dpkg-query", r"""
case "$1" in
  -W)
    test "$#" = 3
    test "$2" = $'-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Upstream-Version}\n'
    test "$3" = guacd
    printf '%s' "$PM_OUTPUT"
    exit "$PM_RC"
    ;;
  -L)
    test "$#" = 2
    test "$2" = guacd
    printf '%s' "$PM_FILES"
    exit "$FILES_RC"
    ;;
  *) exit 99 ;;
esac
""")

    def package_row(self, version=VERSION, package_version=PACKAGE_VERSION):
        return f"guacd\tinstall ok installed\t{package_version}\tarm64\t{version}\n"

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + script)
        path.chmod(0o755)

    def run_step(self, name, values=None, **env):
        values = values or {}

        def render(text):
            def expression(match):
                for term in match[1].split("||"):
                    term = term.strip()
                    if term.startswith("'") and term.endswith("'"):
                        return term[1:-1]
                    if term.isdigit():
                        return term
                    if values.get(term):
                        return str(values[term])
                return ""
            return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

        step = self.steps[name]
        step_env = {key: render(value) for key, value in step.get("env", {}).items()}
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-c", render(step["run"])],
                                cwd=self.root, env={**self.env, **step_env, **env},
                                capture_output=True, text=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return result, outputs

    def verified(self, version=VERSION):
        return {"steps.version.outputs.version": version,
                "steps.version.outputs.status": "passed"}

    def assert_rejected(self, name="version", values=None, **env):
        result, outputs = self.run_step(name, values or self.verified(), **env)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs.get("status"), "failed")
        self.assertNotIn("version", outputs)
        self.assertNotIn("package_version", outputs)
        if name == "test2":
            self.assertRegex(outputs["duration"], r"^[0-9]+$")
        return outputs

    def test_successful_cli_is_bound_to_installed_package(self):
        for version, package_version in ((VERSION, PACKAGE_VERSION),
                                         ("9.12.3", "2:9.12.3-4+b1"),
                                         ("9.12", "9.12-1ubuntu1")):
            with self.subTest(version=version):
                result, outputs = self.run_step(
                    "version", CLI_STDOUT=BANNER + version + "\n",
                    PM_OUTPUT=self.package_row(version, package_version))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(outputs, {"version": version, "package_version": package_version,
                                           "status": "passed"})

    def test_single_banner_on_stderr_is_valid_after_successful_exit(self):
        result, outputs = self.run_step("version", CLI_STDOUT="",
                                        CLI_STDERR=BANNER + VERSION + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["version"], VERSION)

    def test_malformed_wrong_product_duplicate_and_missing_banners(self):
        valid = BANNER + VERSION + "\n"
        for banner in ("", "Kerberos\n", "(guacd)\n", "Guacamole proxy daemon (other) version 1.3.0\n",
                       BANNER + "unknown\n", BANNER + "1.x.3\n",
                       "prefix " + valid, valid.rstrip() + " suffix\n",
                       valid + valid, "\n" + valid, valid + "\n",
                       "Usage: guacd\n" + valid, valid + "status=passed\n"):
            with self.subTest(banner=banner):
                self.assert_rejected(CLI_STDOUT=banner)

    def test_nonzero_cli_never_publishes_a_version(self):
        for code in ("1", "2", "127", "139"):
            with self.subTest(code=code):
                self.assert_rejected(CLI_RC=code)

    def test_stderr_diagnostics_cannot_hide_behind_a_valid_banner(self):
        self.assert_rejected(CLI_STDERR="invalid option\n")

    def test_missing_executable_is_rejected(self):
        (self.bin / "guacd").unlink()
        self.assert_rejected()
        self.assert_rejected("test2")

    def test_wrong_missing_duplicate_or_uninstalled_package_is_rejected(self):
        row = self.package_row()
        for package in ("", row + row, row.replace("guacd", "other-product"),
                        row.replace("install ok installed", "deinstall ok config-files"),
                        row.replace("arm64", "amd64"), row.replace(PACKAGE_VERSION, "unknown"),
                        row.replace("\t" + VERSION + "\n", "\t9.99.9\n")):
            with self.subTest(package=package):
                self.assert_rejected(PM_OUTPUT=package)

    def test_package_query_failure_is_rejected_even_with_valid_output(self):
        self.assert_rejected(PM_RC="1")
        self.assert_rejected(FILES_RC="1")

    def test_unowned_executable_is_rejected(self):
        self.assert_rejected(PM_FILES="/usr/local/bin/other\n")
        self.assert_rejected(PM_FILES="")

    def test_core_version_check_runs_real_command_and_matches_verified_version(self):
        result, outputs = self.run_step("test2", self.verified())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_core_version_check_rejects_invalid_changed_or_nonzero_output(self):
        valid = BANNER + VERSION + "\n"
        for banner in ("", BANNER + "9.99.9\n", "Guacamole proxy daemon (other) version 1.3.0\n",
                       valid + valid, valid + "\n", "Usage: guacd\n" + valid):
            with self.subTest(banner=banner):
                self.assert_rejected("test2", CLI_STDOUT=banner)
        self.assert_rejected("test2", CLI_RC="1")
        self.assert_rejected("test2", CLI_STDERR="invalid option\n")

    def test_core_version_check_requires_verified_package_identity(self):
        for version in ("", "unknown", "(guacd)", "Kerberos", VERSION + "\n"):
            with self.subTest(version=version):
                self.assert_rejected("test2", self.verified(version))
        values = self.verified()
        values["steps.version.outputs.status"] = "failed"
        self.assert_rejected("test2", values)
        self.assertTrue(self.steps["version"]["continue-on-error"])

    def test_package_manager_regression_skip_and_success_summary(self):
        values = self.summary_values()
        result, regression = self.run_step("test6", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(regression["status"], "skipped")
        self.assertEqual(regression["decision"], "not_applicable_package_manager")
        self.assertEqual(regression["current_version"], VERSION)
        values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
        result, outputs = self.run_step("summary", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {"passed": "5", "failed": "0", "core_failed": "0",
                                   "skipped": "1", "duration": "0",
                                   "overall_status": "success", "badge_status": "passing"})

    def test_core_failure_or_missing_status_has_consistent_summary(self):
        for status in ("failed", ""):
            with self.subTest(status=status):
                values = self.summary_values()
                values["steps.test2.outputs.status"] = status
                self.pm_guard(values)
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["passed"], "4")
                self.assertEqual(outputs["failed"], "1")
                self.assertEqual(outputs["core_failed"], "1")
                self.assertEqual(outputs["skipped"], "1")
                self.assertEqual(outputs["overall_status"], "failure")
                self.assertEqual(outputs["badge_status"], "failing")


if __name__ == "__main__":
    unittest.main()
