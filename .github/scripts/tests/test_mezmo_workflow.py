"""Execute the Mezmo workflow probes with isolated positive and failure fixtures."""

from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import package_observation_migration_audit as audit  # noqa: E402


WORKFLOW = ROOT / ".github/workflows/test-mezmo.yml"
JOB = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-mezmo"]
STEPS = {step["id"]: step for step in JOB["steps"] if "id" in step}


def render(script, values):
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
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)


AGENT = r'''
import json
import os
from pathlib import Path
import socket
import sys
import yaml

fixture = json.loads(Path(__file__).with_name("fixture.json").read_text())
mode = fixture.get("mode", "success")
assert not any(key.startswith(("MZ_", "LOGDNA_", "AWS_")) or key == "GH_TOKEN" for key in os.environ)
if sys.argv[1:] == ["--version"]:
    print("LogDNA Agent 3.11.2" if mode != "bad_version" else "unknown")
    sys.exit(fixture.get("exit", 0))
if sys.argv[1:] == ["--help"]:
    print("A resource-efficient log collection agent")
    if mode != "incomplete_help":
        print("USAGE:\n    logdna-agent [FLAGS] [OPTIONS]")
    sys.exit(fixture.get("exit", 0))
assert len(sys.argv) == 4 and sys.argv[1] == "--config" and sys.argv[3] == "--list"
path = Path(sys.argv[2])
config = json.loads(path.read_text())
root = path.parent
assert root.stat().st_mode & 0o777 == 0o700
assert os.environ["HOME"] == str(root / "home")
assert os.environ["TMPDIR"] == str(root)
assert config["http"]["host"].startswith("127.0.0.1:")
assert int(config["http"]["host"].split(":")[1]) not in (19300, 19301)
assert config["http"]["use_ssl"] is False
assert config["http"]["ingestion_key"] == "mezmo-local-smoke-not-a-real-key"
assert config["http"]["params"]["hostname"] == "mezmo-smoke-fixture"
assert config["http"]["retry_dir"] == str(root / "retry")
assert config["log"]["db_path"] == str(root / "state")
assert config["log"]["dirs"] == [str(root / "fixtures")]
assert config["log"]["include"] == {"glob": ["*.log"], "regex": []}
assert (root / "fixtures/synthetic.log").read_text() == "mezmo synthetic smoke fixture\n"
assert len(list((root / "fixtures").iterdir())) == 1
for key in ("use_k8s_enrichment", "log_k8s_events", "log_metric_server_stats"):
    assert config["log"][key] == "never"
assert config["journald"] == {"paths": [], "systemd_journal_tailer": False}
config["http"]["ingestion_key"] = "REDACTED"
if mode == "cloud_host":
    config["http"]["host"] = "logs.logdna.com"
elif mode == "host_logs":
    config["log"]["dirs"] = ["/var/log/"]
elif mode == "journald":
    config["journald"]["systemd_journal_tailer"] = True
elif mode == "unredacted_key":
    config["http"]["ingestion_key"] = "mezmo-local-smoke-not-a-real-key"
elif mode == "wrong_hostname":
    config["http"]["params"]["hostname"] = "unexpected-host"
elif mode == "ingestion":
    with socket.create_connection(("127.0.0.1", int(config["http"]["host"].split(":")[1]))):
        pass
if mode != "missing_marker":
    print("effective configuration:")
if mode == "malformed_yaml":
    print("http: [")
elif mode == "non_mapping":
    print("[]")
else:
    print(yaml.safe_dump(config), end="")
if mode == "duplicate_marker":
    print("effective configuration:")
if mode == "missing_key":
    print("ERROR logdna_agent::_main: Configuration error: http.ingestion_key is missing", file=sys.stderr)
    sys.exit(22)
if mode == "error":
    print("ERROR failed to initialize", file=sys.stderr)
if mode == "fatal":
    print("FATAL failed to initialize", file=sys.stderr)
sys.exit(fixture.get("exit", 0))
'''


class MezmoWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mezmo-workflow-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        agent = self.bin / "logdna-agent"
        agent.write_text(f"#!{sys.executable}\n" + AGENT)
        agent.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        HOME=str(self.root), TMPDIR=str(self.root), RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        MZ_INGESTION_KEY="poison-user-key", MZ_HOST="logs.logdna.com",
                        MZ_LOG_DIRS="/var/log", LOGDNA_AGENT_KEY="poison-legacy-key",
                        AWS_SECRET_ACCESS_KEY="poison-cloud-secret", GH_TOKEN="poison-gh-token")
        self.values = {"steps.version.outputs.version": "3.11.2"}
        for index in range(1, 6):
            self.values.update({f"steps.test{index}.outputs.status": "passed",
                                f"steps.test{index}.outputs.duration": "1",
                                f"steps.test{index}.outcome": "success"})
        self.values.update({"steps.test6.outcome": "success", "steps.test6.outputs.status": "skipped",
                            "steps.test6.outputs.decision": "not_applicable_package_manager"})

    def run_step(self, step, **fixture):
        (self.bin / "fixture.json").write_text(json.dumps(fixture))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", render(STEPS[step]["run"], self.values)],
                                cwd=self.root, env=self.env, text=True, capture_output=True, timeout=40)
        self.output_lines = output.read_text().splitlines()
        outputs = dict(line.split("=", 1) for line in self.output_lines)
        return result, outputs

    def assert_result(self, result, outputs, status):
        self.assertEqual(status == "passed", result.returncode == 0, result.stdout + result.stderr)
        self.assertEqual(status, outputs["status"])
        self.assertGreaterEqual(int(outputs["duration"]), 0)
        counts = Counter(line.split("=", 1)[0] for line in self.output_lines)
        self.assertEqual(1, counts["status"])
        self.assertEqual(1, counts["duration"])

    def test_package_manager_install_and_existing_probe_coverage_are_preserved(self):
        self.assertIn("sudo apt-get install -y logdna-agent python3-yaml", STEPS["install"]["run"])
        self.assertIn("https://assets.logdna.com stable main", STEPS["install"]["run"])
        for index in range(1, 7):
            self.assertIn(f"test{index}", STEPS)
        for index in range(1, 6):
            self.assertNotIn("status=skipped", STEPS[f"test{index}"]["run"])
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("not_applicable_package_manager", outputs["decision"])
        self.assertEqual("3.11.2", outputs["current_version"])

    def test_version_discovery_requires_actual_success_and_version(self):
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("3.11.2", outputs["version"])
        for fixture in ({"exit": 17}, {"mode": "bad_version"}):
            with self.subTest(fixture=fixture):
                result, outputs = self.run_step("version", **fixture)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("version", outputs)

    def test_version_and_help_require_success_with_original_markers(self):
        for step, mode in (("test2", "bad_version"), ("test3", "incomplete_help")):
            with self.subTest(step=step):
                self.assert_result(*self.run_step(step), "passed")
                self.assert_result(*self.run_step(step, exit=17), "failed")
                self.assert_result(*self.run_step(step, mode=mode), "failed")

    def test_isolated_configuration_dry_run_passes_and_emits_outputs_once(self):
        result, outputs = self.run_step("test5")
        self.assert_result(result, outputs, "passed")
        self.assertIn("producer exit: 0", result.stdout)
        self.assertIn("no ingestion connection", result.stdout)
        self.assertNotIn("poison", result.stdout + result.stderr)
        self.assertNotIn("mezmo-local-smoke-not-a-real-key", result.stdout + result.stderr)
        self.assertFalse(list(self.root.glob("mezmo-list-*")))

    def test_configuration_text_cannot_mask_nonzero_producer_exit(self):
        for fixture in ({"mode": "missing_key"}, {"exit": 17}):
            with self.subTest(fixture=fixture):
                result, outputs = self.run_step("test5", **fixture)
                self.assert_result(result, outputs, "failed")
                self.assertIn(f"producer exit: {fixture.get('exit', 22)}", result.stdout)
                self.assertFalse(list(self.root.glob("mezmo-list-*")))

    def test_zero_exit_errors_and_invalid_or_unsafe_configuration_fail_closed(self):
        for mode in ("error", "fatal", "missing_marker", "duplicate_marker", "malformed_yaml",
                     "non_mapping", "cloud_host", "host_logs", "journald", "unredacted_key", "wrong_hostname"):
            with self.subTest(mode=mode):
                self.assert_result(*self.run_step("test5", mode=mode), "failed")

    def test_local_ingestion_attempt_is_rejected(self):
        result, outputs = self.run_step("test5", mode="ingestion")
        self.assert_result(result, outputs, "failed")
        self.assertIn("unexpectedly attempted ingestion", result.stderr)

    def test_core_outputs_are_recognized_by_unmodified_repository_auditor(self):
        for index in range(1, 6):
            for output in ("status", "duration"):
                with self.subTest(step=index, output=output):
                    self.assertTrue(audit._step_emits_output(ROOT, STEPS[f"test{index}"], output))

    def test_summary_counts_five_core_passes_and_one_policy_exemption(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"core_failed": "0", "passed": "5", "failed": "0", "skipped": "1", "duration": "5",
                          "overall_status": "success", "badge_status": "passing"}, outputs)

    def test_summary_rejects_each_failed_missing_or_cancelled_core_outcome(self):
        for index in range(1, 6):
            for field, value in (("outcome", "failure"), ("outcome", "cancelled"), ("outcome", ""),
                                 ("outputs.status", "failed"), ("outputs.status", "")):
                with self.subTest(step=index, field=field, value=value):
                    key = f"steps.test{index}.{field}"
                    previous = self.values[key]
                    self.values[key] = value
                    result, outputs = self.run_step("summary")
                    self.values[key] = previous
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["core_failed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])

    def test_actual_missing_key_failure_reaches_summary(self):
        result, outputs = self.run_step("test5", mode="missing_key")
        self.assert_result(result, outputs, "failed")
        self.values["steps.test5.outcome"] = "failure"
        for key, value in outputs.items():
            self.values[f"steps.test5.outputs.{key}"] = value
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["core_failed"])
        self.assertEqual("failure", outputs["overall_status"])

    def test_unearned_policy_exemption_cannot_make_summary_green(self):
        for field, value in (("outcome", "failure"), ("outcome", ""), ("outputs.status", "passed"),
                             ("outputs.decision", "not_configured")):
            with self.subTest(field=field):
                key = f"steps.test6.{field}"
                previous = self.values[key]
                self.values[key] = value
                result, outputs = self.run_step("summary")
                self.values[key] = previous
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("0", outputs["core_failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("failure", outputs["overall_status"])

    def test_all_shell_steps_parse(self):
        for step in JOB["steps"]:
            if "run" in step:
                with self.subTest(step=step["name"]):
                    result = subprocess.run(["bash", "-n"], input=render(step["run"], self.values),
                                            text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
