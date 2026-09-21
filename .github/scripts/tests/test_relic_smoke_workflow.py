"""Execute Relic's workflow shell and unchanged collector with offline producers."""

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


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-relic.yml"
BASELINE = "v8.2.0"


class RelicWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-relic"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}
        action = yaml.safe_load(
            (ROOT / ".github/actions/collect-batch-results/action.yml").read_text()
        )
        cls.collector = action["runs"]["steps"][0]["run"].split(
            "python3 - <<'PY'\n", 1
        )[1].rsplit("\nPY", 1)[0]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="relic-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        for command in ("bash", "awk", "grep", "mkdir", "date"):
            (self.bin / command).symlink_to(shutil.which(command))
        self.output = self.root / "outputs"
        self.env = {
            **os.environ, **self.job["env"], "PATH": str(self.bin),
            "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(self.root),
            "FIXTURE_ROOT": str(self.root), "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "CLI_VERSION": BASELINE, "VERSION_RC": "0", "HELP_RC": "0",
            "HELP_TEXT": "Available Commands:", "COMPLETION_RC": "0",
            "COMPLETION_TEXT": "complete -F _relic relic", "VERIFY_RC": "0",
            "ARCH": "aarch64", "UNAME_RC": "0", "GO_RC": "0",
        }
        self.values = {
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": BASELINE,
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.current_version": BASELINE,
            "steps.test6.outputs.latest_version": "not_applicable",
            "steps.test6.outputs.next_installed_version": "not_applicable",
        }
        for index in range(1, 7):
            self.values.update({
                f"steps.test{index}.outcome": "success",
                f"steps.test{index}.outputs.status": "passed" if index <= 5 else "skipped",
                f"steps.test{index}.outputs.duration": str(index if index <= 5 else 0),
            })
        self.stub("relic", r'''
import os
from pathlib import Path
import sys
with (Path(os.environ["FIXTURE_ROOT"]) / "calls").open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
mode = {
    ("--version",): ("VERSION", "relic version " + os.environ["CLI_VERSION"]),
    ("--help",): ("HELP", os.environ["HELP_TEXT"]),
    ("completion", "bash"): ("COMPLETION", os.environ["COMPLETION_TEXT"]),
    ("verify", "--help"): ("VERIFY", "Usage: relic verify"),
}[tuple(sys.argv[1:])]
if mode[1]:
    print(mode[1])
sys.exit(int(os.environ[mode[0] + "_RC"]))
''')
        self.stub("uname", '''
import os, sys
assert sys.argv[1:] == ["-m"]
print(os.environ["ARCH"])
sys.exit(int(os.environ["UNAME_RC"]))
''')
        self.stub("go", '''
import os
from pathlib import Path
import shutil
import sys
assert sys.argv[1:] == ["install", "github.com/sassoftware/relic/v8@v8.2.0"]
if os.environ["GO_RC"] != "0":
    print("proxy.golang.org: stream error: INTERNAL_ERROR; received from peer", file=sys.stderr)
    sys.exit(int(os.environ["GO_RC"]))
shutil.copyfile(Path(os.environ["FIXTURE_ROOT"]) / "bin/relic", Path(os.environ["GOBIN"]) / "relic")
''')
        self.stub("sudo", '''
from pathlib import Path
import os, sys
assert sys.argv[1:4] == ["install", "-m", "0755"]
assert sys.argv[-1] == "/usr/local/bin/relic"
assert Path(sys.argv[-2]).is_file()
(Path(os.environ["FIXTURE_ROOT"]) / "installed").touch()
''')
        apt = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        apt.parent.mkdir(parents=True)
        apt.write_text('test "$1" = --packages && test "$2" = golang-go\n')

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def expression(self, source, values):
        def atom(term):
            term = term.strip()
            if " == " in term:
                left, right = term.split(" == ", 1)
                return atom(left) == atom(right)
            if term == "always()":
                return True
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if term.isdigit():
                return term
            return values.get(term, "")

        for alternative in source.split("||"):
            result = True
            for term in alternative.split("&&"):
                result = atom(term) if result else result
            if result:
                return str(result)
        return ""

    def render(self, source, values=None):
        return re.sub(
            r"\$\{\{\s*(.*?)\s*\}\}",
            lambda match: self.expression(match[1], {**self.values, **(values or {})}),
            source,
        )

    def shell(self, source, values=None, **environment):
        script = self.render(source, values)
        # Relocate only absolute scratch paths; run the actual assertions unchanged.
        for path in ("/tmp/relic-bin", "/tmp/relic-completion.sh"):
            script = script.replace(path, str(self.root / Path(path).name))
        self.output.write_text("")
        result = subprocess.run(
            [self.bash, "-e", "-o", "pipefail", "-c", script], cwd=self.root,
            env={**self.env, **environment}, capture_output=True, text=True, timeout=10,
        )
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "duplicate terminal outputs")
        return result, dict(pairs)

    def step(self, name, values=None, **environment):
        return self.shell(self.steps[name]["run"], values, **environment)

    def run_checks(self, prerequisites=None, environments=None):
        values = {**self.values, **(prerequisites or {})}
        for index in range(1, 7):
            name = f"test{index}"
            prefix = f"steps.{name}."
            values = {key: value for key, value in values.items() if not key.startswith(prefix)}
            if self.expression(self.steps[name]["if"], values):
                process, fields = self.step(name, values, **(environments or {}).get(name, {}))
                outcome = "success" if process.returncode == 0 else "failure"
            else:
                fields, outcome = {}, "skipped"
            values[prefix + "outcome"] = outcome
            # Explicit empties prevent fixture defaults from supplying missing evidence.
            for field in ("status", "duration", "decision", "current_version", "latest_version",
                          "next_installed_version", "regression_result", "comparison"):
                values[prefix + "outputs." + field] = fields.get(field, "")
        process, summary = self.step("summary", values)
        self.assertEqual(process.returncode == 0, summary["overall_status"] == "success")
        return summary, values

    def collect(self, summary, values=None, conclusions=None):
        context = {
            **self.values, **(values or {}),
            **{f"steps.summary.outputs.{key}": value for key, value in summary.items()},
            "steps.metadata.outputs.package_slug": "relic", "github.job": "test-relic",
            "github.run_id": "123", "github.run_attempt": "1",
        }
        outputs = {key: self.render(value, context) for key, value in self.job["outputs"].items()}
        states = conclusions or [context[f"steps.test{i}.outcome"] for i in range(1, 7)]
        job = {
            "id": 456, "name": "test-relic / test-relic", "conclusion": summary["overall_status"],
            "html_url": "https://github.com/example/project/actions/runs/123/job/456",
            "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": state}
                      for i, state in enumerate(states, 1)],
        }
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            environment = {
                **self.env, "GH_TOKEN": "", "BATCH_NUMBER": "9", "BATCH_TITLE": "Batch 9",
                "NEEDS_JSON": json.dumps({"test-relic": {"result": job["conclusion"], "outputs": outputs}}),
                "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_OUTPUT": str(root / "outputs"), "GITHUB_STEP_SUMMARY": str(root / "summary"),
            }
            process = subprocess.run(
                [sys.executable, "-B", "-c", self.collector], cwd=root, env=environment,
                capture_output=True, text=True, timeout=15,
            )
            path = root / "test-results/relic-test-results/relic.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def assert_counts(self, summary, passed, failed, skipped, core_failed, status):
        self.assertEqual(
            tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed")),
            tuple(map(str, (passed, failed, skipped, core_failed))),
        )
        self.assertEqual(summary["overall_status"], status)
        self.assertEqual(summary["badge_status"], "passing" if status == "success" else "failing")

    def assert_collected(self, summary, values=None):
        process, payload = self.collect(summary, values)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(payload["run"]["status"], summary["overall_status"])
        for field in ("passed", "failed", "skipped"):
            self.assertEqual(payload["tests"][field], int(summary[field]))
        self.assertEqual(payload["metadata"]["core_failed"], int(summary["core_failed"]))
        return payload

    def test_runner_version_and_independent_checks_preserve_raw_failures(self):
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.job["env"], {"RELIC_VERSION": BASELINE})
        for index in range(1, 7):
            step = self.steps[f"test{index}"]
            self.assertNotIn("continue-on-error", step)
            self.assertEqual(step["if"], "always() && steps.install.outcome == 'success' && steps.install.outputs.install_status == 'success' && steps.version.outcome == 'success'")
        self.assertEqual(self.steps["summary"]["if"], "always()")
        self.assertNotIn("Test 6", self.steps["test6"]["name"])

    def test_terminal_and_summary_outputs_are_machine_auditable(self):
        sys.path.insert(0, str(ROOT / ".github/scripts"))
        import package_observation_migration_audit as audit

        for index in range(1, 7):
            for field in ("status", "duration"):
                with self.subTest(index=index, field=field):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[f"test{index}"], field))
        for field in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["summary"], field), field)

    def test_success_is_five_runtime_passes_and_one_applicability_skip(self):
        process, installed = self.step("install")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(installed, {"install_status": "success"})
        self.assertTrue((self.root / "installed").exists())
        process, version = self.step("version")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(version["version"], BASELINE)
        summary, values = self.run_checks()
        self.assert_counts(summary, 5, 0, 1, 0, "success")
        payload = self.assert_collected(summary, values)
        self.assertEqual(payload["tests"]["details"][-1]["status"], "skipped")
        self.assertEqual(payload["metadata"]["regression_applicability"], "not_applicable")
        self.assertIn("completion bash\nverify --help\n", (self.root / "calls").read_text())

    def test_proxy_install_failure_leaves_six_skips_and_no_invented_core_failure(self):
        process, fields = self.step("install", GO_RC="73")
        self.assertEqual(process.returncode, 73, process.stderr)
        self.assertIn("INTERNAL_ERROR", process.stderr)
        self.assertEqual(fields, {})
        self.assertFalse((self.root / "installed").exists())
        summary, values = self.run_checks({
            "steps.install.outcome": "failure", "steps.install.outputs.install_status": "",
            "steps.version.outcome": "skipped", "steps.version.outputs.version": "",
        })
        self.assert_counts(summary, 0, 0, 6, 0, "failure")
        self.assertEqual(summary["duration"], "0")
        self.assertFalse((self.root / "calls").exists())
        self.assert_collected(summary, values)

    def test_all_core_checks_emit_terminal_status_and_duration_on_failure(self):
        cases = [(1, {}), (2, {"CLI_VERSION": "v0.0.0"}), (3, {"HELP_TEXT": "wrong help"}),
                 (4, {"ARCH": "x86_64"}), (5, {"COMPLETION_TEXT": ""}),
                 (5, {"VERIFY_RC": "19"}), (5, {"COMPLETION_RC": "23"})]
        for index, environment in cases:
            with self.subTest(index=index, environment=environment):
                hidden = self.root / "hidden-relic"
                if index == 1:
                    (self.bin / "relic").rename(hidden)
                try:
                    process, fields = self.step(f"test{index}", **environment)
                finally:
                    if hidden.exists():
                        hidden.rename(self.bin / "relic")
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(fields["status"], "failed")
                self.assertGreaterEqual(int(fields["duration"]), 0)

    def test_unexpected_core_errors_reach_collector_without_masking(self):
        for name, environment in (("test2", {"VERSION_RC": "37"}), ("test4", {"UNAME_RC": "41"})):
            with self.subTest(step=name):
                process, fields = self.step(name, **environment)
                self.assertEqual(process.returncode, int(next(iter(environment.values()))))
                self.assertEqual(fields["status"], "failed")
                self.assertGreaterEqual(int(fields["duration"]), 0)
                summary, values = self.run_checks(environments={name: environment})
                self.assertEqual(values[f"steps.{name}.outcome"], "failure")
                self.assertEqual(values["steps.test5.outcome"], "success")
                self.assert_counts(summary, 4, 1, 1, 1, "failure")
                self.assert_collected(summary, values)

    def test_raw_failure_wins_over_false_passed_output(self):
        for index in range(1, 6):
            with self.subTest(index=index):
                values = {f"steps.test{index}.outcome": "failure"}
                process, summary = self.step("summary", values)
                self.assertNotEqual(process.returncode, 0)
                self.assert_counts(summary, 4, 1, 1, 1, "failure")
                self.assert_collected(summary, values)

    def test_missing_status_with_raw_failure_is_still_a_failure(self):
        values = {"steps.test2.outcome": "failure", "steps.test2.outputs.status": ""}
        process, summary = self.step("summary", values)
        self.assertNotEqual(process.returncode, 0)
        self.assert_counts(summary, 4, 1, 1, 1, "failure")
        self.assert_collected(summary, values)

    def test_missing_success_outputs_cannot_report_success(self):
        for index in range(1, 7):
            with self.subTest(index=index):
                values = {f"steps.test{index}.outputs.status": ""}
                process, summary = self.step("summary", values)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(summary["overall_status"], "failure")
                process, payload = self.collect(summary, values)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("emitted failure counts contradict test details", process.stderr)
                self.assertIsNone(payload)

    def test_missing_prerequisites_gate_checks_and_remain_failure(self):
        for missing in ("steps.install.outcome", "steps.install.outputs.install_status", "steps.version.outcome"):
            with self.subTest(missing=missing):
                summary, values = self.run_checks({missing: ""})
                self.assert_counts(summary, 0, 0, 6, 0, "failure")
                self.assert_collected(summary, values)
                process, summary = self.step("summary", {missing: ""})
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(summary["overall_status"], "failure")
        for missing in ("steps.version.outputs.version", "steps.test6.outputs.decision"):
            process, summary = self.step("summary", {missing: ""})
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(summary["overall_status"], "failure")

    def test_notexecuted_and_cancelled_outcomes_have_accurate_counts(self):
        for outcome in ("skipped", ""):
            with self.subTest(outcome=outcome):
                values = {f"steps.test{i}.{field}": value for i in range(1, 7)
                          for field, value in (("outcome", outcome), ("outputs.status", ""),
                                               ("outputs.duration", ""), ("outputs.decision", ""))}
                process, summary = self.step("summary", values)
                self.assertNotEqual(process.returncode, 0)
                self.assert_counts(summary, 0, 0, 6, 0, "failure")
                self.assertEqual(summary["duration"], "0")
                self.assert_collected(summary, values)
        values = {"steps.test2.outcome": "cancelled", "steps.test4.outcome": "skipped"}
        process, summary = self.step("summary", values)
        self.assertNotEqual(process.returncode, 0)
        self.assert_counts(summary, 3, 1, 2, 1, "failure")
        self.assert_collected(summary, values)

    def test_stale_applicability_metadata_cannot_turn_core_skips_into_success(self):
        values = {f"steps.test{i}.outcome": "skipped" for i in range(1, 7)}
        process, summary = self.step("summary", values)
        self.assertNotEqual(process.returncode, 0)
        self.assert_counts(summary, 0, 0, 6, 0, "failure")
        process, payload = self.collect(summary, values)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("passing result contradicts failure evidence", process.stderr)
        self.assertIsNone(payload)

    def test_unexecuted_applicability_is_not_enough_for_success(self):
        values = {"steps.test6.outcome": "skipped"}
        process, summary = self.step("summary", values)
        self.assertNotEqual(process.returncode, 0)
        self.assert_counts(summary, 5, 0, 1, 0, "failure")
        process, payload = self.collect(summary, values)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("passing result contradicts failure evidence", process.stderr)
        self.assertIsNone(payload)

    def test_summary_sums_valid_durations_and_exposes_skips(self):
        process, summary = self.step("summary")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(summary["duration"], "15")
        process, fields = self.step("summary", {
            "steps.test1.outputs.duration": "09", "steps.test2.outputs.duration": "invalid",
            "steps.test3.outputs.duration": "", "steps.test4.outputs.duration": "-1",
        })
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(fields["duration"], "14")
        context = {f"steps.summary.outputs.{key}": value for key, value in summary.items()}
        process, _ = self.shell(self.job["steps"][-1]["run"], context)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("**Tests Skipped:** 1", (self.root / "summary").read_text())

    def test_collector_still_rejects_original_install_failure_contradiction(self):
        summary, values = self.run_checks({"steps.install.outcome": "failure"})
        summary.update(failed="5", core_failed="5", skipped="0")
        process, payload = self.collect(summary, values)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("emitted failed/core=5/5, details failed/core=0/0", process.stderr)
        self.assertIsNone(payload)

    def test_collector_still_rejects_masked_core_failure(self):
        summary, values = self.run_checks(environments={"test3": {"HELP_RC": "1"}})
        process, payload = self.collect(summary, values, conclusions=["success"] * 6)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("emitted failure counts contradict test details", process.stderr)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
