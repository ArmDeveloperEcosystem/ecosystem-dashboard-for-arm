"""Fault tests for actual MAAS workflow shell; fixtures are not product evidence."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit
from package_result_policy import expected_regression_metadata, validate_six_test_result


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-maas.yml"


class MaasWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="maas-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-maas"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.values = {
            "github.run_id": "unit", "github.run_attempt": "1",
            "steps.install.outcome": "success",
            "steps.install.outputs.installation_method": "deb",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": "3.6.5",
            "steps.version.outputs.installation_method": "deb",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.installation_method": "deb",
        }
        for number in range(1, 7):
            self.values.update({f"steps.test{number}.outcome": "success",
                f"steps.test{number}.outputs.status": "skipped" if number == 6 else "passed",
                f"steps.test{number}.outputs.duration": "1"})
        self.env = {**self.job["env"], "GITHUB_OUTPUT": str(self.root / "output"),
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "HOME": str(self.root), "TMPDIR": str(self.root), "LC_ALL": "C", "LANG": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "DOCKER_RC": "0", "DOCKER_STDOUT": "", "TEST_ARCH": "aarch64"}
        self.tool("docker", 'printf "%s" "$DOCKER_STDOUT"\nexit "$DOCKER_RC"\n')
        self.tool("uname", 'printf "%s\\n" "$TEST_ARCH"\n')
        self.calls = 0

    def tool(self, name, script):
        target = self.bin / name
        target.write_text("#!/bin/bash\nset -eu\n" + script)
        target.chmod(0o755)

    def render(self, source, values=None):
        context = {**self.values, **(values or {})}

        def atom(term):
            term = term.strip()
            if " == " in term:
                left, right = term.split(" == ", 1)
                return atom(left) == atom(right)
            if term == "always()":
                return True
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            return context.get(term, "")

        def expression(match):
            for alternative in match[1].split("||"):
                value = True
                for term in alternative.split("&&"):
                    value = atom(term) if value else value
                if value:
                    return str(value)
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, step, **environment):
        source = self.steps[step]["run"]
        script = self.render(source)
        env = {key: self.render(str(value)) for key, value in self.env.items()}
        env.update(environment)
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
            env=env, cwd=self.root, capture_output=True, text=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        if evidence := os.environ.get("WORKFLOW_EVIDENCE_ROOT"):
            self.calls += 1
            directory = Path(evidence) / self._testMethodName / str(self.calls)
            directory.mkdir(parents=True)
            for name, text in {"source.sh": source, "rendered.sh": script,
                "env.json": json.dumps(env, indent=2),
                "values.json": json.dumps(self.values, indent=2),
                "stdout.txt": result.stdout, "stderr.txt": result.stderr,
                "github-output.txt": output.read_text(), "exit.txt": str(result.returncode),
                "workflow.sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()}.items():
                (directory / name).write_text(text)
        return result, outputs

    def run_checks(self, environments=None):
        for number in range(1, 7):
            name = f"test{number}"
            if self.render("${{ " + self.steps[name]["if"] + " }}"):
                environment = {"DOCKER_STDOUT": "Upgrades database schema for MAAS regiond.\n--database\n"} if number == 3 else {}
                environment.update((environments or {}).get(name, {}))
                process, outputs = self.run_step(name, **environment)
                outcome = "success" if process.returncode == 0 else "failure"
            else:
                outputs, outcome = {}, "skipped"
            self.values[f"steps.{name}.outcome"] = outcome
            for field in ("status", "duration", "decision", "installation_method", "current_version",
                          "latest_version", "next_installed_version", "regression_result", "comparison"):
                self.values[f"steps.{name}.outputs.{field}"] = outputs.get(field, "")
        process, summary = self.run_step("summary")
        self.assertEqual(process.returncode == 0, summary["overall_status"] == "success")
        return summary

    def collect(self, summary, conclusions=None):
        repository = WORKFLOW.parents[2]
        action = yaml.safe_load((repository / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        context = {**{f"steps.summary.outputs.{key}": value for key, value in summary.items()},
                   "steps.metadata.outputs.package_slug": "maas", "github.job": "test-maas",
                   "github.run_id": "123", "github.run_attempt": "1"}
        outputs = {key: self.render(value, context) for key, value in self.job["outputs"].items()}
        states = conclusions or [self.values.get(f"steps.test{i}.outcome", "") for i in range(1, 7)]
        job = {"id": 456, "name": "test-maas / test-maas", "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": state}
                         for i, state in enumerate(states, 1)]}
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(repository / ".github/scripts")
            environment = {**self.env, "GH_TOKEN": "", "BATCH_NUMBER": "14", "BATCH_TITLE": "Batch 14",
                "NEEDS_JSON": json.dumps({"test-maas": {"result": job["conclusion"], "outputs": outputs}}),
                "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_OUTPUT": str(root / "outputs"), "GITHUB_STEP_SUMMARY": str(root / "summary")}
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=root, env=environment,
                                     capture_output=True, text=True, timeout=15)
            path = root / "test-results/maas-test-results/maas.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def assert_collected(self, summary):
        process, payload = self.collect(summary)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(summary["overall_status"], payload["run"]["status"])
        for field in ("passed", "failed", "skipped"):
            self.assertEqual(int(summary[field]), payload["tests"][field])
        self.assertEqual(int(summary["core_failed"]), payload["metadata"]["core_failed"])
        return payload

    def test_raw_core_failures_are_not_masked_and_checks_are_independent(self):
        for number in range(1, 6):
            step = self.steps[f"test{number}"]
            self.assertNotIn("continue-on-error", step)
            self.assertEqual(step["if"], "always() && steps.install.outcome == 'success' && steps.install.outputs.installation_method == 'deb' && steps.version.outcome == 'success'")
        self.assertEqual("always()", self.steps["test6"]["if"])
        self.assertEqual("always()", self.steps["summary"]["if"])

    def test_actual_core_shell_success_and_applicability_reach_unchanged_collector(self):
        summary = self.run_checks()
        self.assertEqual(("5", "0", "1", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual("not_applicable_package_manager", self.values["steps.test6.outputs.decision"])
        payload = self.assert_collected(summary)
        self.assertEqual("skipped", payload["tests"]["details"][-1]["status"])

    def test_raw_core_failure_and_terminal_outputs_reach_unchanged_collector(self):
        for number in range(1, 6):
            with self.subTest(number=number):
                summary = self.run_checks({f"test{number}": {"DOCKER_RC": "37"}})
                self.assertEqual(("4", "1", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
                self.assertEqual("failure", self.values[f"steps.test{number}.outcome"])
                self.assertEqual("failed", self.values[f"steps.test{number}.outputs.status"])
                self.assertTrue(self.values[f"steps.test{number}.outputs.duration"].isdigit())
                self.assertEqual("baseline_failed", self.values["steps.test6.outputs.decision"])
                self.assert_collected(summary)

    def test_every_shell_block_parses(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=self.render(step["run"]),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)

    def run_apt_install_commands(self, fail_at="0"):
        source = self.steps["install"]["run"]
        commands = [line.strip() for line in source.splitlines()
                    if line.strip().startswith(("APT_OPTIONS=", "apt-get "))]
        self.assertEqual(5, len(commands))
        calls = self.root / "apt-calls"
        calls.write_text("")
        self.tool("apt-get", '''
printf '%s\\n' "$*" >> "$HOME/apt-calls"
if [ "$(wc -l < "$HOME/apt-calls" | tr -d ' ')" = "$APT_FAIL_AT" ]; then
  exit 100
fi
''')
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", "\n".join(commands)],
            env={**self.env, "APT_FAIL_AT": fail_at}, cwd=self.root,
            capture_output=True, text=True, timeout=15)
        return result, [shlex.split(line) for line in calls.read_text().splitlines()]

    def test_apt_download_retries_are_bounded_and_partial_indexes_fail_closed(self):
        result, calls = self.run_apt_install_commands()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(4, len(calls))
        options = ["-o", "Acquire::Retries=3", "-o", "Acquire::http::Timeout=30",
                   "-o", "Acquire::https::Timeout=30"]
        for call in calls:
            self.assertEqual(options, call[:6])
        self.assertEqual(["--error-on=any", "update"], calls[0][6:])
        self.assertEqual(["--error-on=any", "update"], calls[2][6:])
        self.assertEqual(["install", "-y", "--no-install-recommends",
                          "maas-region-api=" + self.job["env"]["MAAS_DEB_VERSION"], "postgresql-16"], calls[3][6:])
        self.assertEqual(20, self.job["timeout-minutes"])
        self.assertIn("signed-by=/usr/share/keyrings/maas-smoke.gpg", self.steps["install"]["run"])

    def test_apt_failure_stops_before_subsequent_install_commands(self):
        for fail_at in range(1, 5):
            with self.subTest(fail_at=fail_at):
                result, calls = self.run_apt_install_commands(str(fail_at))
                self.assertEqual(100, result.returncode, result.stderr)
                self.assertEqual(fail_at, len(calls))

    def test_key_download_has_bounded_retries_and_preserves_failure(self):
        source = self.steps["install"]["run"]
        download = source[source.index("curl --fail "):source.index("KEY_FINGERPRINTS=")]
        self.tool("curl", 'printf "%s\\n" "$*" > "$HOME/curl-call"\nexit "$CURL_RC"\n')
        for code in (0, 22, 28, 60):
            with self.subTest(code=code):
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", download],
                    env={**self.env, "CURL_RC": str(code)}, cwd=self.root,
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(code, result.returncode, result.stderr)
        arguments = shlex.split((self.root / "curl-call").read_text())
        for flag, value in (("--connect-timeout", "10"), ("--max-time", "30"),
                            ("--retry", "3"), ("--retry-delay", "5"), ("--retry-max-time", "150")):
            self.assertEqual(value, arguments[arguments.index(flag) + 1])
        self.assertIn("--retry-all-errors", arguments)
        self.assertIn("https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x3AB6DCF1F234E78DAA9C104204E7FDC5684D4A1C", arguments)
        self.assertNotIn("--insecure", arguments)

    def test_signing_key_requires_exactly_one_pinned_primary_and_successful_gpg(self):
        source = "\n".join(line.strip() for line in self.steps["install"]["run"].splitlines()
                           if line.strip().startswith(("KEY_FINGERPRINTS=", 'test "$KEY_FINGERPRINTS"')))
        self.assertEqual(2, len(source.splitlines()))
        fingerprint = "3AB6DCF1F234E78DAA9C104204E7FDC5684D4A1C"
        valid = f"pub:-:4096:1:04E7FDC5684D4A1C::::::\nfpr:::::::::{fingerprint}:\n"
        subkey = "sub:-:4096:1:1234567890ABCDEF::::::\nfpr:::::::::" + "A" * 40 + ":\n"
        wrong = valid.replace(fingerprint, "B" * 40)
        self.tool("gpg", 'printf "%s" "$GPG_LISTING"\nexit "$GPG_RC"\n')
        for listing, code, succeeds in ((valid, 0, True), (valid + subkey, 0, True),
                                        ("", 0, False), (wrong, 0, False),
                                        (valid + wrong, 0, False), (wrong + valid, 0, False),
                                        (subkey, 0, False), (valid, 2, False)):
            with self.subTest(listing=listing, code=code):
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", source],
                    env={**self.env, "GPG_LISTING": listing, "GPG_RC": str(code)},
                    cwd=self.root, capture_output=True, text=True, timeout=15)
                self.assertEqual(succeeds, result.returncode == 0, result.stderr)

    def test_actual_auditor_sees_all_contract_outputs(self):
        for number in range(1, 7):
            for output in ("status", "duration"):
                self.assertTrue(observation_audit._step_emits_output(
                    WORKFLOW.parents[2], self.steps[f"test{number}"], output), (number, output))
        for output in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(
                WORKFLOW.parents[2], self.steps["summary"], output), output)
        for output in ("version", "package_version", "installation_method"):
            self.assertTrue(observation_audit._step_emits_output(
                WORKFLOW.parents[2], self.steps["version"], output), output)
        pairs = set(observation_audit._step_literal_pairs(WORKFLOW.parents[2], self.steps["test6"]))
        self.assertEqual({("baseline_install_failed", "skipped"), ("baseline_failed", "skipped"),
                          ("not_applicable_package_manager", "skipped")}, pairs)
        for decision, status in pairs:
            self.assertEqual("not_applicable" if decision == "not_applicable_package_manager" else status, expected_regression_metadata(
                decision=decision, core_failed=0 if decision == "not_applicable_package_manager" else 1)["status"])

    def test_valid_summary_counts_five_core_and_real_pm_skip(self):
        result, regression = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
        self.values["steps.test6.outputs.duration"] = "1"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "6", "success", "passing"),
            tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status")))
        self.assertEqual("success", self.validate_row(regression, outputs))

    def validate_row(self, regression, summary):
        details = [{"name": self.steps[f"test{i}"]["name"],
                    "status": self.values[f"steps.test{i}.outputs.status"]} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **regression})
        return validate_six_test_result(details=details, decision=regression["decision"],
            **{key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")})

    def test_real_shell_fault_rows_are_accepted_by_unchanged_policy(self):
        original = dict(self.values)
        for number in range(1, 6):
            with self.subTest(number=number):
                self.values = dict(original)
                result, outputs = self.run_step(f"test{number}", DOCKER_RC="37")
                self.assertNotEqual(0, result.returncode)
                self.values[f"steps.test{number}.outcome"] = "failure"
                self.values.update({f"steps.test{number}.outputs.{k}": v for k, v in outputs.items()})
                result, regression = self.run_step("test6")
                self.assertEqual(0, result.returncode)
                self.assertEqual("baseline_failed", regression["decision"])
                self.values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
                result, summary = self.run_step("summary")
                self.assertEqual(1, result.returncode)
                self.assertEqual(("4", "1", "1", "1", "failing"),
                    tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed", "badge_status")))
                self.assertEqual("failure", self.validate_row(regression, summary))
                self.values["steps.test6.outputs.decision"] = "baseline_install_failed"
                result, invalid = self.run_step("summary")
                self.assertEqual("0", invalid["skipped"])

    def test_install_failure_is_a_valid_failure_row_and_has_exact_reason(self):
        self.tool("docker", '''
printf '%s\\n' "$*" >> "$HOME/docker-calls"
case "$1:$2" in
  container:inspect) exit 1 ;;
  exec:*) printf '%s\\n' 'MAAS Noble PPA InRelease: 503 Service Unavailable' >&2; exit 100 ;;
esac
''')
        result, outputs = self.run_step("install")
        self.assertEqual(100, result.returncode, result.stderr)
        self.assertIn("503 Service Unavailable", result.stderr)
        self.assertEqual({}, outputs)
        calls = (self.root / "docker-calls").read_text()
        self.values["steps.install.outcome"] = "failure"
        self.values["steps.install.outputs.installation_method"] = ""
        self.values["steps.version.outcome"] = "skipped"
        self.values["steps.version.outputs.version"] = ""
        self.values["steps.version.outputs.installation_method"] = ""
        summary = self.run_checks()
        self.assertEqual("baseline_install_failed", self.values["steps.test6.outputs.decision"])
        self.assertEqual("success", self.values["steps.test6.outcome"])
        self.assertEqual(("0", "0", "6", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual("failure", summary["overall_status"])
        self.assertEqual(calls, (self.root / "docker-calls").read_text())
        self.assert_collected(summary)
        self.values["steps.test6.outputs.decision"] = "baseline_failed"
        result, invalid = self.run_step("summary")
        self.assertEqual(1, result.returncode)
        self.assertEqual("5", invalid["skipped"])
        self.assertEqual("1", invalid["failed"])

    def test_core_missing_status_outcome_or_duration_never_passes(self):
        for number in range(1, 6):
            for field, invalid in (("outcome", ("", "failure", "cancelled", "skipped")),
                                   ("outputs.status", ("", "failed", "skipped", "unknown")),
                                   ("outputs.duration", ("", "-1", "oops", "1+1", "999999999"))):
                key = f"steps.test{number}.{field}"
                original = self.values[key]
                for value in invalid:
                    with self.subTest(number=number, field=field, value=value):
                        self.values[key] = value
                        result, outputs = self.run_step("summary")
                        self.assertEqual(1, result.returncode, result.stderr)
                        self.assertEqual("0" if field == "outcome" and value in ("", "skipped") else "1", outputs["core_failed"])
                        self.assertEqual("failing", outputs["badge_status"])
                        self.assertEqual("failure", outputs["overall_status"])
                self.values[key] = original

    def test_pm_skip_is_strict_about_decision_outcome_duration_and_evidence(self):
        for key, values in {
            "steps.test6.outputs.decision": ("", "baseline_failed", "baseline_install_failed", "not_configured"),
            "steps.test6.outcome": ("", "failure", "cancelled", "skipped"),
            "steps.test6.outputs.status": ("", "passed", "failed"),
            "steps.test6.outputs.duration": ("", "bad", "-1"),
            "steps.test6.outputs.installation_method": ("", "pip", "source"),
        }.items():
            original = self.values[key]
            for value in values:
                with self.subTest(key=key, value=value):
                    self.values[key] = value
                    result, outputs = self.run_step("summary")
                    self.assertEqual(1, result.returncode, result.stderr)
                    expected = ("5", "0", "1", "0", "failure") if key == "steps.test6.outcome" and value in ("", "skipped") else ("5", "1", "0", "0", "failure")
                    self.assertEqual(expected,
                        tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))
            self.values[key] = original

    def test_install_or_version_failure_invalidates_provenance(self):
        for key in ("steps.install.outcome", "steps.version.outcome",
                    "steps.install.outputs.installation_method", "steps.version.outputs.installation_method",
                    "steps.version.outputs.version"):
            original = self.values[key]
            self.values[key] = ""
            result, outputs = self.run_step("summary")
            self.assertEqual(1, result.returncode)
            self.assertEqual("0", outputs["core_failed"])
            self.values[key] = original

    def test_unexecuted_or_missing_steps_count_as_skips_without_success(self):
        for outcome in ("skipped", ""):
            with self.subTest(outcome=outcome):
                for number in range(1, 7):
                    self.values[f"steps.test{number}.outcome"] = outcome
                    for field in ("status", "duration", "decision", "installation_method"):
                        self.values[f"steps.test{number}.outputs.{field}"] = ""
                result, summary = self.run_step("summary")
                self.assertEqual(1, result.returncode)
                self.assertEqual(("0", "0", "6", "0", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed", "duration")))
                self.assert_collected(summary)

    def test_missing_version_skips_core_checks_and_preserves_baseline_guard(self):
        self.values["steps.version.outcome"] = "failure"
        self.values["steps.version.outputs.version"] = ""
        summary = self.run_checks()
        self.assertEqual("baseline_failed", self.values["steps.test6.outputs.decision"])
        self.assertEqual(("0", "0", "6", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
        self.assert_collected(summary)

    def test_raw_failure_overrides_missing_or_false_passed_output(self):
        for number in range(1, 6):
            for status in ("passed", ""):
                with self.subTest(number=number, status=status):
                    self.run_checks()
                    self.values[f"steps.test{number}.outcome"] = "failure"
                    self.values[f"steps.test{number}.outputs.status"] = status
                    result, regression = self.run_step("test6", DOCKER_RC="97")
                    self.assertEqual(0, result.returncode)
                    self.values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
                    result, summary = self.run_step("summary")
                    self.assertEqual(1, result.returncode)
                    self.assertEqual(("4", "1", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
                    self.assert_collected(summary)

    def test_unchanged_collector_rejects_missing_success_outputs_and_masked_failures(self):
        for field in ("status", "duration"):
            with self.subTest(field=field):
                self.run_checks()
                self.values[f"steps.test5.outputs.{field}"] = ""
                result, summary = self.run_step("summary")
                self.assertEqual(1, result.returncode)
                process, payload = self.collect(summary)
                self.assertNotEqual(0, process.returncode)
                self.assertIn("emitted failure counts contradict test details", process.stderr)
                self.assertIsNone(payload)
        summary = self.run_checks({"test5": {"DOCKER_RC": "37"}})
        process, payload = self.collect(summary, conclusions=["success"] * 6)
        self.assertNotEqual(0, process.returncode)
        self.assertIn("emitted failure counts contradict test details", process.stderr)
        self.assertIsNone(payload)

    def test_unchanged_collector_rejects_original_five_synthetic_failures(self):
        self.values["steps.install.outcome"] = "failure"
        summary = self.run_checks()
        summary.update(failed="5", core_failed="5", skipped="1")
        process, payload = self.collect(summary)
        self.assertNotEqual(0, process.returncode)
        self.assertIn("emitted failed/core=5/5, details failed/core=0/0", process.stderr)
        self.assertIsNone(payload)

    def test_baseline_guards_skip_without_calling_package_manager(self):
        self.values["steps.install.outcome"] = "failure"
        result, outputs = self.run_step("test6", DOCKER_RC="97")
        self.assertEqual(0, result.returncode)
        self.assertEqual(("baseline_install_failed", "skipped"), (outputs["decision"], outputs["status"]))
        self.values["steps.install.outcome"] = "success"
        self.values["steps.test5.outcome"] = "failure"
        result, outputs = self.run_step("test6", DOCKER_RC="97")
        self.assertEqual(0, result.returncode)
        self.assertEqual(("baseline_failed", "skipped"), (outputs["decision"], outputs["status"]))
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in outputs.items()})
        result, summary = self.run_step("summary")
        self.assertEqual(1, result.returncode)
        self.assertEqual(("4", "1", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_failed_real_shell_commands_emit_failed_status_and_duration(self):
        for number in range(1, 6):
            for code in (1, 37, 127):
                with self.subTest(number=number, code=code):
                    result, outputs = self.run_step(f"test{number}", DOCKER_RC=str(code))
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])
                    self.assertTrue(outputs["duration"].isdigit())
        result, outputs = self.run_step("version", DOCKER_RC="37", DOCKER_STDOUT="version=3.6.5\n")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", outputs)
        result, outputs = self.run_step("test6", DOCKER_RC="37")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("decision", outputs)
        self.assertTrue(outputs["duration"].isdigit())

    def test_region_help_and_native_host_assertions_reject_wrong_evidence(self):
        for help_text in ("", "python-libmaas --help", "Upgrades database schema for MAAS regiond."):
            result, outputs = self.run_step("test3", DOCKER_STDOUT=help_text)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
        result, outputs = self.run_step("test4", TEST_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def identity(self, fault=None):
        """Run the actual identity helper with explicitly isolated unit fixtures."""
        version = types.SimpleNamespace(short_version="3.6.5", git_rev="474ecb517")
        maas = types.ModuleType("maasserver")
        maas.__file__ = "/usr/lib/python3/dist-packages/maasserver/__init__.py"
        maas.__version__ = "3.6.5"
        module = types.ModuleType("provisioningserver.utils.version")
        module.get_running_version = lambda: version
        if fault == "runtime": version.short_version = "0.6.8"
        if fault == "source": version.git_rev = "deadbeef0"
        if fault == "module": maas.__version__ = "0.6.8"
        if fault == "path": maas.__file__ = "/tmp/maasserver/__init__.py"
        def query(command, **kwargs):
            if fault == "command": raise subprocess.CalledProcessError(17, command)
            if command[1] == "-W":
                row = f'{command[-1]}\tinstall ok installed\t{self.job["env"]["MAAS_DEB_VERSION"]}\tall\tmaas\n'
                replacements = {"arch": ("\tall\t", "\tamd64\t"), "status": ("installed", "unpacked"),
                    "package": (command[-1], "python-libmaas"), "revision": (self.job["env"]["MAAS_DEB_VERSION"], "0.6.8"),
                    "source-package": ("\tmaas\n", "\tpython-libmaas\n")}
                if fault in replacements: row = row.replace(*replacements[fault])
                if fault == "duplicate": row += row
            else:
                owner = "maas-region-api" if command[-1] == "/usr/sbin/maas-region" else "python3-django-maas"
                row = f'{owner}: {command[-1]}\n'
                if fault == "owner": row = "other: " + command[-1] + "\n"
            return types.SimpleNamespace(stdout=row, stderr="diagnostic" if fault == "stderr" else "")
        with patch.dict(os.environ, self.job["env"]), patch.dict(sys.modules, {
                "maasserver": maas, "provisioningserver.utils.version": module}), \
             patch("subprocess.run", side_effect=query), patch.object(Path, "is_file", return_value=fault != "missing"), \
             patch("importlib.metadata.version", return_value="0.6.8" if fault == "distribution" else "3.6.5"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(self.job["env"]["MAAS_IDENTITY"], "workflow:MAAS_IDENTITY", "exec"), {})
        return output.getvalue()

    def test_identity_helper_rejects_client_wrong_owner_version_arch_and_failed_queries(self):
        self.assertIn("version=3.6.5\n", self.identity())
        for fault in ("runtime", "source", "module", "path", "command", "arch", "status",
                      "package", "revision", "source-package", "duplicate", "owner", "stderr", "missing", "distribution"):
            with self.subTest(fault=fault), self.assertRaises((AssertionError, subprocess.CalledProcessError)):
                self.identity(fault)

    def api_assertions(self, fault=None):
        """Exercise the actual HTTP/SQL assertion code with labeled unit fixtures."""
        state = {}
        name = "maas-smoke-" + "a" * 32
        stage = "create"
        requests = types.ModuleType("requests")
        def request(method, url, **kwargs):
            nonlocal stage
            path = url.removeprefix("http://127.0.0.1:5240/MAAS/api/2.0/")
            status, data = 200, None
            if path == "version/":
                data = {"version": "None" if fault == "version" else "3.6.5", "capabilities": ["authenticate-api"]}
            elif method == "POST" and not kwargs["headers"]:
                status, data = (200 if fault == "unauthorized" else 401), "Forbidden"
            elif method == "POST":
                fields = {k: v[1] for k, v in kwargs["files"].items()}
                state[name] = fields
                data = dict(fields)
                if fault == "created-name": data["name"] = "other"
                if fault == "created-comment": data["comment"] = "other"
            elif method == "PUT":
                stage = "update"
                if fault != "stale-update": state[name]["comment"] = "persisted-update"
                data = dict(state[name])
            elif method == "DELETE":
                stage = "delete"
                del state[name]
                status, data = 204, ""
            elif method == "GET":
                status = 200 if name in state else 404
                data = dict(state[name]) if name in state else "No Tag matches the given query."
                if stage == "delete" and fault == "delete-status": status = 200
            else:
                raise AssertionError((method, path))
            response = types.SimpleNamespace(status_code=status, text=json.dumps(data),
                content=b"" if status == 204 else b"body", headers={"Content-Type": "application/json"})
            response.json = lambda: data
            return response
        requests.request = request
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query, parameters):
                self.parameters = parameters
            def fetchall(self):
                if fault == "db-stale" and stage == "update": return [(name, "created", "")]
                if fault == "db-phantom" and stage == "delete": return [(name, "persisted-update", "")]
                if fault == "db-missing" and stage == "create": return []
                return [(key, value["comment"], value["definition"]) for key, value in sorted(state.items())]
        class Database:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return Cursor()
        pg = types.ModuleType("psycopg2")
        pg.connect = lambda **kwargs: Database()
        oauth = types.ModuleType("oauthlib.oauth1")
        oauth.SIGNATURE_PLAINTEXT = "unit-fixture"
        oauth.Client = lambda *args, **kwargs: types.SimpleNamespace(sign=lambda url, **kw: (url, {"Authorization": "unit-fixture"}, None))
        with patch.dict(os.environ, {"MAAS_VERSION": "3.6.5"}), \
             patch.dict(sys.modules, {"requests": requests, "psycopg2": pg, "oauthlib.oauth1": oauth}), \
             patch.object(Path, "read_text", return_value="unit-consumer:unit-token:unit-secret"), \
             patch("uuid.uuid4", return_value=types.SimpleNamespace(hex="a" * 32)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(self.job["env"]["MAAS_API_PROOF"], "workflow:MAAS_API_PROOF", "exec"), {})
        return output.getvalue()

    def test_api_assertions_reject_wrong_identity_auth_crud_and_database_state(self):
        self.assertIn("MAAS_API_POSTGRES_PROOF_PASSED", self.api_assertions())
        for fault in ("version", "unauthorized", "created-name", "created-comment", "stale-update",
                      "delete-status", "db-stale", "db-phantom", "db-missing"):
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                self.api_assertions(fault)

    def test_production_handler_is_used_without_domain_or_auth_substitutions(self):
        server = self.job["env"]["MAAS_API_SERVER"]
        self.assertIn("WebApplicationHandler()", server)
        self.assertIn("yield start_up(master=True)", server)
        self.assertIn("crochet.no_setup()", server)
        self.assertIn("interface='127.0.0.1'", server)
        smoke = self.steps["test5"]["run"]
        self.assertIn("maas-region dbupgrade", smoke)
        self.assertIn("maas-region migrate --check", smoke)
        self.assertIn("test ! -e /smoke/pgdata", smoke)
        self.assertNotIn("--fake", smoke)


if __name__ == "__main__":
    unittest.main()
