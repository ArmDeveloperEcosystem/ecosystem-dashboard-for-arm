"""Execute legacy Notary workflow steps with controlled identity and outcome faults."""

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


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-notary.yml"
VERSION = "0.7.0"
REVISION = "0.7.0+ds1-2ubuntu0.24.04.3"
BANNER = "notary\n Version:    \n Git commit: \n Go version: go1.22.2\n"
FORMAT = "-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Package}\t${source:Upstream-Version}\n"


class WorkflowHarness:
    workflow = WORKFLOW

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="version-identity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "home").mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        (self.bin / "date").symlink_to(shutil.which("date"))
        self.job = next(iter(yaml.safe_load(self.workflow.read_text())["jobs"].values()))
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "HOME": str(self.root / "home"),
            "RUNNER_TEMP": str(self.root),
            "TMPDIR": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PM_FORMAT": FORMAT,
        }
        self.values = {
            "steps.install.outcome": "success",
            "steps.version.outputs.version": VERSION,
            "steps.version.outputs.package_version": REVISION,
            "steps.version.outputs.status": "passed",
            "steps.version.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outcome": "success",
            "steps.test6.outputs.duration": "6",
        }
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.calls = 0

    def tool(self, name, source):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + source)
        path.chmod(0o755)
        return path

    def render(self, text):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return str(self.values[term])
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def run_step(self, name, **overrides):
        step = self.steps[name]
        script = self.render(step["run"])
        env = {**self.env,
               **{key: self.render(str(value)) for key, value in step.get("env", {}).items()},
               **overrides}
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=30,
        )
        raw_output = output.read_text()
        pairs = [line.split("=", 1) for line in raw_output.splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs), raw_output)
        outputs = dict(pairs)
        self.assertEqual(len(pairs), len(outputs), "Duplicate output keys")
        evidence = os.environ.get("WORKFLOW_EVIDENCE_ROOT")
        if evidence:
            self.calls += 1
            target = Path(evidence) / self.workflow.stem / self._testMethodName / str(self.calls)
            target.mkdir(parents=True)
            (target / "workflow.yml").write_text(self.workflow.read_text())
            (target / "rendered.sh").write_text(script)
            (target / "env.json").write_text(json.dumps(env, indent=2, sort_keys=True))
            (target / "values.json").write_text(json.dumps(self.values, indent=2, sort_keys=True))
            (target / "stdout.txt").write_text(result.stdout)
            (target / "stderr.txt").write_text(result.stderr)
            (target / "github-output.txt").write_text(raw_output)
            (target / "exit.txt").write_text(str(result.returncode) + "\n")
            stubs = target / "fixtures"
            stubs.mkdir()
            for path in self.bin.iterdir():
                if not path.is_symlink():
                    (stubs / path.name).write_bytes(path.read_bytes())
        return result, outputs

    def rejected(self, step="version", **env):
        result, outputs = self.run_step(step, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs.get("status"))
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        self.assertNotIn("version", outputs)
        self.assertNotIn("package_version", outputs)
        return result, outputs


class ContractChecks:
    def test_actual_auditor_sees_reachable_outputs(self):
        for step in ("version", "test1", "test2", "test3", "test4", "test5"):
            for key in ("status", "duration"):
                with self.subTest(step=step, key=key):
                    self.assertTrue(observation_audit._step_emits_output(
                        self.workflow.parents[2], self.steps[step], key))
        for key in ("version", "package_version"):
            self.assertTrue(observation_audit._step_emits_output(
                self.workflow.parents[2], self.steps["version"], key))
        for key in ("passed", "failed", "skipped", "core_failed", "duration",
                    "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(
                self.workflow.parents[2], self.steps["summary"], key))
        self.assertEqual({("not_applicable_package_manager", "skipped"),
                          ("baseline_failed", "skipped"),
                          ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(
                             self.workflow.parents[2], self.steps["test6"])))

    def test_five_core_checks_and_meaningful_package_manager_skip(self):
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("not_applicable_package_manager", outputs["decision"])
        self.assertEqual(self.values["steps.version.outputs.version"], outputs["current_version"])
        self.assertIn("package manager", outputs["comparison"])
        self.assertEqual("always()", self.steps["test6"]["if"])
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "21", "success", "passing"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped",
                               "core_failed", "duration", "overall_status", "badge_status")))

    def test_every_core_requires_passed_status_and_successful_outcome(self):
        for i in range(1, 6):
            for status, outcome in (
                    ("", "success"), ("failed", "success"), ("skipped", "success"),
                    ("unknown", "success"), ("passed", ""), ("passed", "failure"),
                    ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(test=i, status=status, outcome=outcome):
                    self.values[f"steps.test{i}.outputs.status"] = status
                    self.values[f"steps.test{i}.outcome"] = outcome
                    guard, regression = self.run_step("test6")
                    self.assertEqual(0, guard.returncode, guard.stderr)
                    self.assertEqual("baseline_failed", regression["decision"])
                    self.values.update({f"steps.test6.outputs.{key}": value
                                        for key, value in regression.items()})
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                                     tuple(outputs[key] for key in ("passed", "failed", "skipped",
                                           "core_failed", "overall_status", "badge_status")))
            self.values[f"steps.test{i}.outputs.status"] = "passed"
            self.values[f"steps.test{i}.outcome"] = "success"

    def test_test6_requires_exact_skip_decision_and_successful_outcome(self):
        for status, decision, outcome in (
                ("skipped", "", "success"),
                ("skipped", "not_configured", "success"),
                ("skipped", "runtime_validation_not_automated", "success"),
                ("skipped", "not_applicable_package_manager", ""),
                ("skipped", "not_applicable_package_manager", "failure"),
                ("skipped", "not_applicable_package_manager", "cancelled"),
                ("skipped", "not_applicable_package_manager", "skipped"),
                ("passed", "not_applicable_package_manager", "success"),
                ("failed", "not_applicable_package_manager", "success"),
                ("", "not_applicable_package_manager", "success")):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                self.values.update({"steps.test6.outputs.status": status,
                                    "steps.test6.outputs.decision": decision,
                                    "steps.test6.outcome": outcome})
                result, outputs = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "0", "failure", "failing"),
                                 tuple(outputs[key] for key in ("passed", "failed", "skipped",
                                       "core_failed", "overall_status", "badge_status")))

    def test_all_missing_results_fail_closed(self):
        self.values.clear()
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5", "failing"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped",
                               "core_failed", "badge_status")))

    def test_malformed_durations_fail_and_decimal_durations_are_supported(self):
        for step in ("test2", "test6"):
            for duration in ("bad", "-1", "1.5", "1000000"):
                with self.subTest(step=step, duration=duration):
                    self.values[f"steps.{step}.outputs.duration"] = duration
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failing", outputs["badge_status"])
            self.values[f"steps.{step}.outputs.duration"] = "08"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("29", outputs["duration"])

    def test_test2_rejects_failed_missing_or_changed_baseline(self):
        for key, bad in (("status", "failed"), ("status", ""),
                         ("version", "unknown"), ("version", "9.99.99"),
                         ("package_version", "1.0.0-1")):
            field = f"steps.version.outputs.{key}"
            original = self.values[field]
            self.values[field] = bad
            self.rejected("test2")
            self.values[field] = original
        self.values["steps.version.outcome"] = "failure"
        self.rejected("test2")


def render_pm_expression(text, values):
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


class PMDecisionChecks:
    """Shared Test6/summary checks with the active, unmodified collector."""

    def pm_values(self):
        values = {"steps.install.outcome": "success", "steps.version.outcome": "success",
                  "steps.version.outputs.status": "passed",
                  "steps.version.outputs.version": "1.2.3"}
        for i in range(1, 6):
            values.update({f"steps.test{i}.outputs.status": "passed",
                           f"steps.test{i}.outcome": "success",
                           f"steps.test{i}.outputs.duration": "2"})
        return values

    def pm_run_step(self, name, values):
        self.values = dict(values)
        return self.run_step(name)

    def pm_guard(self, values):
        process, outputs = self.pm_run_step("test6", values)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("0", outputs["duration"])
        values.update({f"steps.test6.outputs.{key}": value for key, value in outputs.items()})
        values["steps.test6.outcome"] = "success"
        return outputs

    def pm_summary(self, values):
        process, outputs = self.pm_run_step("summary", values)
        self.assertEqual(0 if outputs["overall_status"] == "success" else 1, process.returncode)
        values.update({f"steps.summary.outputs.{key}": value for key, value in outputs.items()})
        return outputs

    def pm_collect(self, values, api_overrides=None):
        root = self.workflow.parents[2]
        document = yaml.safe_load(self.workflow.read_text())
        job_id, job = next(iter(document["jobs"].items()))
        slug = self.workflow.stem.removeprefix("test-")
        inputs = {"steps.metadata.outputs.package_slug": slug,
                  "steps.metadata.outputs.dashboard_link": f"/opensource_packages/{slug}",
                  "steps.metadata.outputs.timestamp": "2026-09-09T00:00:00Z",
                  "github.job": job_id, "github.run_id": "123", "github.run_attempt": "1",
                  **values}
        outputs = {key: render_pm_expression(str(value), inputs)
                   for key, value in job["outputs"].items()}
        api_steps = [{"name": self.steps[f"test{i}"]["name"], "number": i,
                      "conclusion": (api_overrides or {}).get(i, values.get(f"steps.test{i}.outcome"))}
                     for i in range(1, 7)]
        api_steps.append({"name": self.steps["summary"]["name"], "number": 7,
                          "conclusion": outputs["run_status"]})
        api_job = {"id": 456, "name": f"{job_id} / {job_id}", "steps": api_steps,
                   "conclusion": outputs["run_status"],
                   "html_url": "https://github.com/example/project/actions/runs/123/job/456"}
        action = yaml.safe_load((root / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory(prefix="pm-collector-") as temporary:
            work = Path(temporary)
            (work / ".github").mkdir()
            (work / ".github/scripts").symlink_to(root / ".github/scripts")
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                NEEDS_JSON=json.dumps({job_id: {"result": outputs["run_status"], "outputs": outputs}}),
                RUN_JOBS_JSON=json.dumps({"jobs": [api_job]}), BATCH_NUMBER="1", BATCH_TITLE="Batch 1",
                GH_TOKEN="", GITHUB_SERVER_URL="https://github.com", GITHUB_API_URL="https://api.github.com",
                GITHUB_REPOSITORY="example/project", GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1",
                GITHUB_OUTPUT=str(work / "outputs"), GITHUB_STEP_SUMMARY=str(work / "summary"))
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=work,
                                     env=environment, capture_output=True, text=True, timeout=30)
            path = work / f"test-results/{slug}-test-results/{slug}.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def pm_assert_counts(self, summary, expected):
        self.assertEqual(tuple(map(str, expected)), tuple(summary[key] for key in
                         ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual("failing" if expected[1] else "passing", summary["badge_status"])

    def pm_assert_publishable(self, values, summary, expected, api_overrides=None):
        process, payload = self.pm_collect(values, api_overrides)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        tests, metadata = payload["tests"], payload["metadata"]
        self.assertEqual(expected, result_policy.validate_six_test_result(
            details=tests["details"], passed=tests["passed"], failed=tests["failed"],
            skipped=tests["skipped"], core_failed=metadata["core_failed"],
            decision=metadata["regression_decision"]))
        self.assertEqual(expected, result_policy.validate_publishable_result(payload))
        for key in ("passed", "failed", "skipped"):
            self.assertEqual(int(summary[key]), tests[key])
        self.assertEqual(int(summary["core_failed"]), metadata["core_failed"])
        self.assertEqual(summary["badge_status"], metadata["badge_status"])
        return payload

    def test_pm_positive_and_each_failed_core_reach_unchanged_publisher(self):
        for failed in range(6):
            with self.subTest(failed=failed):
                values = self.pm_values()
                if failed:
                    values.update({f"steps.test{failed}.outputs.status": "failed",
                                   f"steps.test{failed}.outcome": "failure"})
                guard = self.pm_guard(values)
                self.assertEqual("baseline_failed" if failed else "not_applicable_package_manager",
                                 guard["decision"])
                summary = self.pm_summary(values)
                self.pm_assert_counts(summary, (4, 1, 1, 1) if failed else (5, 0, 1, 0))
                self.assertEqual("10", summary["duration"])
                self.pm_assert_publishable(values, summary, "failure" if failed else "success")
                if failed:
                    process, payload = self.pm_collect(values, {failed: "success"})
                    self.assertNotEqual(0, process.returncode)
                    self.assertIn("emitted failure counts contradict test details", process.stderr)
                    self.assertIsNone(payload)

    def test_pm_install_failure_has_priority_and_publishes_failed_row(self):
        for outcome in ("failure", "cancelled", "skipped", ""):
            with self.subTest(outcome=outcome):
                values = self.pm_values()
                values.update({"steps.install.outcome": outcome, "steps.version.outcome": "failure"})
                for i in range(1, 6):
                    values[f"steps.test{i}.outputs.status"] = "failed"
                    values[f"steps.test{i}.outcome"] = "failure"
                self.assertEqual("baseline_install_failed", self.pm_guard(values)["decision"])
                summary = self.pm_summary(values)
                self.pm_assert_counts(summary, (0, 5, 1, 5))
                self.pm_assert_publishable(values, summary, "failure")
                values["steps.test6.outputs.decision"] = "baseline_failed"
                self.pm_assert_counts(self.pm_summary(values), (0, 6, 0, 5))

    def test_pm_unavailable_prerequisites_and_impossible_passes_fail_closed(self):
        faults = [("steps.install.outcome", value) for value in ("failure", "cancelled", "skipped", "")]
        faults += [(f"steps.version.{key}", value) for key, value in (
            ("outcome", "failure"), ("outcome", "cancelled"), ("outcome", "skipped"), ("outcome", ""),
            ("outputs.status", "failed"), ("outputs.status", ""),
            ("outputs.version", "unknown"), ("outputs.version", ""))]
        for field, value in faults:
            with self.subTest(field=field, value=value):
                values = self.pm_values()
                values[field] = value
                decision = "baseline_install_failed" if field.startswith("steps.install.") else "baseline_failed"
                self.assertEqual(decision, self.pm_guard(values)["decision"])
                summary = self.pm_summary(values)
                self.pm_assert_counts(summary, (5, 1, 0, 0))
                process, payload = self.pm_collect(values)
                self.assertNotEqual(0, process.returncode)
                self.assertIn("emitted failure counts contradict", process.stderr)
                self.assertIsNone(payload)
                values.update({"steps.test2.outputs.status": "failed", "steps.test2.outcome": "failure"})
                self.pm_guard(values)
                summary = self.pm_summary(values)
                self.pm_assert_counts(summary, (4, 1, 1, 1))
                self.pm_assert_publishable(values, summary, "failure")

    def test_pm_contradictory_decisions_are_red_and_rejected(self):
        for failed, wrong_decisions in ((False, ("baseline_failed", "baseline_install_failed")),
                                       (True, ("not_applicable_package_manager", "baseline_install_failed"))):
            for wrong in wrong_decisions:
                with self.subTest(failed=failed, decision=wrong):
                    values = self.pm_values()
                    if failed:
                        values.update({"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"})
                    self.pm_guard(values)
                    values["steps.test6.outputs.decision"] = wrong
                    summary = self.pm_summary(values)
                    self.pm_assert_counts(summary, (4, 2, 0, 1) if failed else (5, 1, 0, 0))
                    process, payload = self.pm_collect(values)
                    self.assertNotEqual(0, process.returncode)
                    self.assertIn("emitted failure counts contradict", process.stderr)
                    self.assertIsNone(payload)

    def test_pm_missing_and_malformed_durations_fail_with_terminal_outputs(self):
        for step in ("test1", "test6"):
            for duration in ("", "bad", "-1", "1.5", "1000000", "1+1"):
                with self.subTest(step=step, duration=duration):
                    values = self.pm_values()
                    self.pm_guard(values)
                    values[f"steps.{step}.outputs.duration"] = duration
                    summary = self.pm_summary(values)
                    self.pm_assert_counts(summary, (4, 2, 0, 1) if step == "test1" else (5, 1, 0, 0))
                    self.assertEqual("8" if step == "test1" else "10", summary["duration"])
        values = self.pm_values()
        self.pm_guard(values)
        values.update({"steps.test1.outputs.duration": "08", "steps.test6.outputs.duration": "08"})
        summary = self.pm_summary(values)
        self.pm_assert_counts(summary, (5, 0, 1, 0))
        self.assertEqual("24", summary["duration"])

    def test_pm_auditor_sees_each_literal_status_decision_pair(self):
        root = self.workflow.parents[2]
        self.assertEqual("always()", self.steps["test6"]["if"])
        self.assertEqual({("not_applicable_package_manager", "skipped"),
                          ("baseline_failed", "skipped"), ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(root, self.steps["test6"])))
        for step, fields in (("test6", ("status", "decision", "duration")),
                             ("summary", ("passed", "failed", "skipped", "core_failed", "duration",
                                          "overall_status", "badge_status"))):
            for field in fields:
                self.assertTrue(observation_audit._step_emits_output(root, self.steps[step], field))


class NotaryWorkflowTests(WorkflowHarness, ContractChecks, PMDecisionChecks, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.env.update(CLI_STDOUT=BANNER, CLI_STDERR="", CLI_RC="0",
                        PM_OUTPUT=self.package_row(), PM_RC="0", FILES_RC="0",
                        PM_FILES=str(self.bin / "notary") + "\n")
        self.tool("notary", r'''
case "$1" in
  version) test "$#" = 1 ;;
  --help) ;;
  --trustDir) test "$3" = key; test "$4" = list ;;
  *) exit 99 ;;
esac
printf '%s' "$CLI_STDOUT"
printf '%s' "$CLI_STDERR" >&2
exit "$CLI_RC"
''')
        self.tool("dpkg-query", r'''
case "$1" in
  -W) test "$#" = 3; test "$2" = "$PM_FORMAT"; test "$3" = notary
      printf '%s' "$PM_OUTPUT"; exit "$PM_RC" ;;
  -L) test "$#" = 2; test "$2" = notary
      printf '%s' "$PM_FILES"; exit "$FILES_RC" ;;
  *) exit 99 ;;
esac
''')

    def package_row(self, upstream="0.7.0+ds1", revision=REVISION):
        return f"notary\tinstall ok installed\t{revision}\tarm64\tnotary\t{upstream}\n"

    def test_native_empty_version_uses_package_upstream_not_go_version(self):
        for step in ("version", "test2"):
            result, outputs = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(VERSION, outputs["version"])
            self.assertEqual(REVISION, outputs["package_version"])
            self.assertEqual("0.7.0+ds1", outputs["source_upstream_version"])
            self.assertEqual("dpkg_upstream_empty_cli_version", outputs["version_source"])
            self.assertEqual("passed", outputs["status"])
            self.assertIn(BANNER, result.stderr)

    def test_nonempty_anchored_cli_version_agrees_with_upstream(self):
        for version, upstream, revision in (
                ("0.7.0", "0.7.0+ds1", REVISION),
                ("9.12.3", "9.12.3", "2:9.12.3-4ubuntu1")):
            result, outputs = self.run_step(
                "version", CLI_STDOUT=BANNER.replace("Version:    ", "Version: v" + version),
                PM_OUTPUT=self.package_row(upstream, revision))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(version, outputs["version"])
            self.assertEqual("cli_and_dpkg", outputs["version_source"])

    def test_wrong_product_malformed_duplicate_or_missing_banner_is_rejected(self):
        for banner in ("", "Version: 0.7.0\n", BANNER.replace("notary\n", "notation\n"),
                       BANNER.replace("Version:    ", "Version: unknown"),
                       BANNER.replace("Version:    ", "Version: 9.9.9"),
                       BANNER.replace("Version:    ", "Version: 1.x.3"),
                       BANNER.replace(" Version:    \n", ""),
                       BANNER + BANNER, BANNER + "\n", "Usage:\n" + BANNER,
                       BANNER + "status=passed\n"):
            for step in ("version", "test2"):
                with self.subTest(step=step, banner=banner):
                    self.rejected(step, CLI_STDOUT=banner)

    def test_complete_successful_banner_on_stderr_is_accepted(self):
        result, outputs = self.run_step("version", CLI_STDOUT="", CLI_STDERR=BANNER)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(VERSION, outputs["version"])

    def test_failed_command_or_diagnostics_cannot_publish_version(self):
        for step in ("version", "test2"):
            for code in ("1", "2", "127", "139"):
                self.rejected(step, CLI_RC=code)
            self.rejected(step, CLI_STDERR="invalid option\n")
            self.rejected(step, PM_RC="1")
            self.rejected(step, FILES_RC="1")

    def test_unowned_missing_or_wrong_package_is_rejected(self):
        row = self.package_row()
        for package in ("", row + row, row.replace("notary", "notation"),
                        row.replace("install ok installed", "deinstall ok config-files"),
                        row.replace("arm64", "amd64"), row.replace(REVISION, "unknown"),
                        row.replace("\t0.7.0+ds1\n", "\t1.22.2\n"),
                        row.replace(REVISION, "0.7.1+ds1-2ubuntu1")):
            for step in ("version", "test2"):
                self.rejected(step, PM_OUTPUT=package)
        self.rejected(PM_FILES="/usr/local/bin/notary\n")
        self.rejected(PM_FILES="")
        (self.bin / "notary").unlink()
        self.env["PATH"] = str(self.bin)
        self.rejected()
        self.rejected("test1")

    def test_help_requires_success_and_legacy_usage(self):
        help_text = "Usage:\n  notary [flags]\n  notary [command]\n"
        result, outputs = self.run_step("test3", CLI_STDOUT=help_text)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.rejected("test3", CLI_STDOUT=help_text, CLI_RC="1")
        self.rejected("test3", CLI_STDOUT=help_text.replace("notary", "notation"))

    def test_local_key_failure_is_reported_with_duration(self):
        self.rejected("test4", CLI_RC="1")
        result, outputs = self.run_step("test4", CLI_STDOUT="")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertIn("no registry, TUF publication, or signing server", result.stdout)


if __name__ == "__main__":
    unittest.main()
