"""Exercise ZooKeeper's owned shutdown, cleanup, and raw-outcome failure gates."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-zookeeper.yml"


class ZooKeeperWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zookeeper-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(self.restore_permissions)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-zookeeper"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"), TMPDIR=str(self.root),
                        PROCESS_RECORD=str(self.root / "process.json"), PYTHONDONTWRITEBYTECODE="1")
        self.values = {"steps.install.outcome": "success", "steps.install.outputs.install_status": "success",
                       "steps.version.outcome": "success", "steps.version.outputs.version": "3.9.1",
                       "steps.test6.outcome": "success", "steps.test6.outputs.status": "skipped",
                       "steps.test6.outputs.decision": "not_applicable_package_manager"}
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed", f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.stub("zkServer.sh", r'''
import json, os, signal, socket, sys, time
from pathlib import Path
assert sys.argv[1] == "start-foreground", sys.argv
config = Path(sys.argv[2])
values = dict(line.split("=", 1) for line in config.read_text().splitlines())
assert values["clientPortAddress"] == "127.0.0.1"
assert values["admin.enableServer"] == "false"
assert os.environ["JMXDISABLE"] == "true"
assert Path(os.environ["ZOO_LOG_DIR"]).parent == config.parent
assert os.environ["SERVER_JVMFLAGS"] == f"-Dzookeeper.log.dir={config.parent}/logs -Djava.net.preferIPv4Stack=true"
assert config.parent.stat().st_uid == os.getuid()
assert config.parent.stat().st_mode & 0o777 == 0o700
data = Path(values["dataDir"]) / "version-2"
data.mkdir()
for name in ("log.1", "snapshot.0"):
    (data / name).write_text("synthetic test data\n")
if os.environ.get("BLOCK_DELETE"):
    data.chmod(0o500)
if os.environ.get("IGNORE_TERM"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(int(os.environ.get("STOP_RC", "0"))))
listener = None
if not os.environ.get("NO_LISTENER"):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
Path(os.environ["PROCESS_RECORD"]).write_text(json.dumps({"pid": os.getpid(), "root": str(config.parent),
                                                        "listening": listener is not None}))
if os.environ.get("START_RC"):
    sys.exit(int(os.environ["START_RC"]))
while True:
    time.sleep(0.01)
''')
        self.stub("zkCli.sh", r'''
import os, sys
assert sys.argv[1:] == ["-server", "127.0.0.1:22181"], sys.argv
assert sys.stdin.read() == "ls /\nquit\n"
print(os.environ.get("CLI_OUTPUT", "[zookeeper]"))
sys.exit(int(os.environ.get("CLI_RC", "0")))
''')
        self.stub("nc", r'''
import os, sys, time
from pathlib import Path
assert sys.argv[1:] == ["-w", "2", "127.0.0.1", "22181"], sys.argv
assert sys.stdin.read() == "ruok\n"
for _ in range(100):
    if Path(os.environ["PROCESS_RECORD"]).exists():
        break
    time.sleep(0.005)
print(os.environ.get("RUOK_OUTPUT", "imok"))
sys.exit(int(os.environ.get("RUOK_RC", "0")))
''')
        self.stub("ss", r'''
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ["-H", "-ltn", "sport = :22181"]:
    if os.environ.get("OCCUPIED"):
        print('LISTEN 0 128 127.0.0.1:22181 0.0.0.0:*')
    sys.exit(int(os.environ.get("SS_RC", "0")))
assert sys.argv[1:] == ["-H", "-4", "-ltnp", "sport = :22181"], sys.argv
record = Path(os.environ["PROCESS_RECORD"])
if record.exists():
    data = json.loads(record.read_text())
    if data["listening"]:
        pid = str(data["pid"]) + os.environ.get("PID_SUFFIX", "")
        address = os.environ.get("LISTENER_ADDRESS", "127.0.0.1:22181")
        print(f'LISTEN 0 128 {address} 0.0.0.0:* users:(("java",pid={pid},fd=5))')
sys.exit(int(os.environ.get("SS_RC", "0")))
''')
        self.stub("sleep", "import time\ntime.sleep(0.005)\n")
        self.stub("sudo", 'raise SystemExit("Smoke server must not use sudo")\n')

    def restore_permissions(self):
        for path in self.root.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, source=None, **env):
        values = {**self.values, **(values or {})}

        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                if key.startswith("'"):
                    return key[1:-1]
                if key.isdigit():
                    return key
                if values.get(key):
                    return str(values[key])
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source or self.steps[step_id]["run"])
        script = script.replace("/usr/share/zookeeper/bin", str(self.bin))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        process = subprocess.Popen(["bash", "-e", "-c", script], cwd=self.root,
                                   env=dict(self.env, **env), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Result must be emitted once, after cleanup")
        return result, outputs

    def assert_stopped(self):
        record = json.loads(Path(self.env["PROCESS_RECORD"]).read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(record["pid"], 0)
        return Path(record["root"])

    def assert_failed(self, **env):
        result, output = self.run_step("test5", **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", output["status"])
        self.assertTrue(output["duration"].isdigit())
        return result, output

    def test_owned_server_passes_only_after_shutdown_and_directory_removal(self):
        result, output = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertFalse(self.assert_stopped().exists())

    def test_real_permission_denied_cleanup_cannot_pass(self):
        result, _ = self.assert_failed(BLOCK_DELETE="1")
        self.assertIn("Permission denied", result.stderr)
        self.assertTrue(self.assert_stopped().exists())

    def test_unexpected_server_stop_code_cannot_pass(self):
        self.assert_failed(STOP_RC="17")
        self.assertFalse(self.assert_stopped().exists())

    def test_server_requiring_sigkill_is_failed_but_reaped(self):
        result, _ = self.assert_failed(IGNORE_TERM="1")
        self.assertIn("did not stop after SIGTERM", result.stderr)
        self.assertFalse(self.assert_stopped().exists())

    def test_late_failure_after_functional_validation_is_terminal(self):
        source = self.steps["test5"]["run"].replace("\nfinish 0\n", "\nexit 17\nfinish 0\n")
        result, output = self.run_step("test5", source=source)
        self.assertEqual(17, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertFalse(self.assert_stopped().exists())

    def test_failed_start_readiness_and_cli_still_fail_and_clean_up(self):
        for env in ({"START_RC": "17"}, {"RUOK_OUTPUT": "not ready"}, {"CLI_OUTPUT": "no nodes"},
                    {"RUOK_RC": "17"}, {"CLI_RC": "17"}):
            with self.subTest(env=env):
                Path(self.env["PROCESS_RECORD"]).unlink(missing_ok=True)
                self.assert_failed(**env)
                self.assertFalse(self.assert_stopped().exists())

    def test_signal_after_validation_is_failed_and_cleaned_up(self):
        source = self.steps["test5"]["run"].replace("\nfinish 0\n", '\nkill -TERM "$$"\nfinish 0\n')
        result, output = self.run_step("test5", source=source)
        self.assertEqual(143, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertFalse(self.assert_stopped().exists())

    def test_matching_health_cannot_pass_without_exact_owned_private_listener(self):
        for env in ({"NO_LISTENER": "1"}, {"PID_SUFFIX": "9"},
                    {"LISTENER_ADDRESS": "0.0.0.0:22181"}):
            with self.subTest(env=env):
                Path(self.env["PROCESS_RECORD"]).unlink(missing_ok=True)
                self.assert_failed(**env)
                self.assertFalse(self.assert_stopped().exists())

    def test_occupied_port_or_failed_inspection_stops_before_start(self):
        for env in ({"OCCUPIED": "1"}, {"SS_RC": "17"}):
            with self.subTest(env=env):
                self.assert_failed(**env)
                self.assertFalse(Path(self.env["PROCESS_RECORD"]).exists())

    def test_normal_completion_explicitly_calls_finalizer(self):
        self.assertTrue(self.steps["test5"]["run"].rstrip().endswith("finish 0"))
        code = '''
from pathlib import Path
import sys
import yaml
sys.path.insert(0, ".github/scripts")
import package_observation_migration_audit as audit
workflow = yaml.safe_load(Path(".github/workflows/test-zookeeper.yml").read_text())
step = next(s for s in workflow["jobs"]["test-zookeeper"]["steps"] if s.get("id") == "test5")
for output in ("status", "duration"):
    assert audit._step_emits_output(Path.cwd(), step, output), output
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=WORKFLOW.parents[2],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_summary_counts_five_passes_and_one_real_package_manager_skip(self):
        result, output = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"passed": "5", "failed": "0", "skipped": "1", "core_failed": "0",
                          "duration": "15", "overall_status": "success", "badge_status": "passing"}, output)
        self.assertIn('--packages "zookeeperd netcat-openbsd"', self.steps["install"]["run"])
        result, output = self.run_step("test6")
        self.assertEqual(0, result.returncode)
        self.assertEqual("skipped", output["status"])
        self.assertEqual("not_applicable_package_manager", output["decision"])

    def test_each_core_requires_status_and_raw_outcome_not_continue_on_error_conclusion(self):
        for i in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", ""), ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped")):
                with self.subTest(test=i, status=status, outcome=outcome):
                    result, output = self.run_step("summary", {
                        f"steps.test{i}.outputs.status": status, f"steps.test{i}.outcome": outcome,
                        f"steps.test{i}.conclusion": "success"})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("4", output["passed"])
                    self.assertEqual("1", output["failed"])
                    self.assertEqual("1", output["core_failed"])
                    self.assertEqual("failure", output["overall_status"])

    def test_regression_skip_requires_successful_step_and_package_install(self):
        for key, value in (("steps.test6.outcome", "failure"), ("steps.test6.outcome", ""),
                           ("steps.test6.outputs.status", ""), ("steps.test6.outputs.status", "passed"),
                           ("steps.test6.outputs.decision", ""),
                           ("steps.test6.outputs.decision", "not_configured"),
                           ("steps.install.outcome", "failure"),
                           ("steps.install.outputs.install_status", "failed"),
                           ("steps.version.outcome", "failure"), ("steps.version.outputs.version", "")):
            with self.subTest(key=key, value=value):
                result, output = self.run_step("summary", {key: value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", output["failed"])
                self.assertEqual("0", output["skipped"])
                self.assertEqual("failure", output["overall_status"])

    def test_late_test6_failure_cannot_hide_behind_skipped_output(self):
        result, output = self.run_step("test6", source=self.steps["test6"]["run"] + "\nexit 17\n")
        self.assertEqual(17, result.returncode)
        self.assertEqual("skipped", output["status"])
        result, output = self.run_step("summary", {"steps.test6.outcome": "failure"})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", output["overall_status"])


if __name__ == "__main__":
    unittest.main()
