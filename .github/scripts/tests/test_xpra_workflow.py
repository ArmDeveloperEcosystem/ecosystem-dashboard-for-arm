"""Execute the Xpra smoke shell, including real child-process exit failures."""

import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-xpra.yml"

XPRA_FIXTURE = r'''
import os
from pathlib import Path
import signal
import sys
import time

root = Path(os.environ["FIXTURE_ROOT"])
mode = os.environ.get("FAULT", "")
command = sys.argv[1]
with (root / "commands").open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
if command == "--version":
    print("xpra fixture")
elif command == "start":
    print("fixture server diagnostics", flush=True)
    if mode == "startup":
        sys.exit(9)
    os.write(3, b"123\n")
    for _ in range(500):
        if (root / "stop").exists():
            if mode == "segfault":
                os.kill(os.getpid(), signal.SIGSEGV)
            sys.exit(7 if mode == "server-exit" else 0)
        time.sleep(0.01)
    sys.exit(8)
elif command == "info":
    if mode != "empty-info":
        print("server version session display")
    sys.exit(7 if mode == "info" else 0)
elif command == "version":
    print("fixture remote version")
    sys.exit(7 if mode == "version" else 0)
elif command == "stop":
    if mode == "stop":
        sys.exit(11)
    (root / "stop").touch()
else:
    sys.exit(2)
'''


class XpraWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="xpra-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-xpra"]
        self.steps = {item.get("id"): item for item in self.job["steps"]}
        self.output = self.root / "output"
        self.env = dict(os.environ, **self.job["env"],
                        GITHUB_OUTPUT=str(self.output), FIXTURE_ROOT=str(self.root))

    def run_script(self, script):
        self.output.write_text("")
        result = subprocess.run(["bash", "-e", "-c", "ulimit -c 0\n" + script],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=200)
        fields = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, fields

    def smoke(self, fault=""):
        binary = self.root / "bin"
        binary.mkdir(exist_ok=True)
        stubs = {
            "xpra": f"#!{sys.executable}\n" + XPRA_FIXTURE,
            "timeout": '#!/bin/bash\nshift\nexec "$@"\n',
            "seq": '#!/bin/bash\nprintf "%s\\n" 1 2 3 4 5 6 7 8 9 10\n',
            "sleep": '#!/bin/bash\n/bin/sleep 0.05\n',
        }
        for name, body in stubs.items():
            executable = binary / name
            executable.write_text(body)
            executable.chmod(0o755)
        self.env.update(PATH=f"{binary}{os.pathsep}{os.environ['PATH']}", FAULT=fault)
        return self.run_script(self.steps["test5"]["run"])

    def test_live_queries_and_clean_server_exit_pass(self):
        result, fields = self.smoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")
        commands = (self.root / "commands").read_text().splitlines()
        self.assertTrue(any(line.startswith("info :123 ") for line in commands))
        self.assertTrue(any(line.startswith("version :123 ") for line in commands))
        self.assertTrue(any(line.startswith("stop :123 ") for line in commands))

    def test_both_optional_gdk_forwarders_are_disabled(self):
        result, _ = self.smoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        start = next(line for line in (self.root / "commands").read_text().splitlines()
                     if line.startswith("start "))
        self.assertIn("--system-tray=no", start.split())
        self.assertIn("--clipboard=no", start.split())

    def test_successful_stop_cannot_hide_server_segfault(self):
        result, fields = self.smoke("segfault")
        self.assertEqual(result.returncode, 139, result.stderr)
        self.assertEqual(fields["status"], "failed")
        self.assertIn("stop :123", (self.root / "commands").read_text())
        self.assertIn("fixture server diagnostics", result.stdout)

    def test_successful_stop_cannot_hide_nonzero_server_exit(self):
        result, fields = self.smoke("server-exit")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(fields["status"], "failed")

    def test_startup_and_query_failures_stay_failed(self):
        for fault in ("startup", "info", "empty-info", "version", "stop"):
            with self.subTest(fault=fault):
                result, fields = self.smoke(fault)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(fields["status"], "failed")

    def test_failed_shutdown_counts_as_one_failed_core(self):
        result, fields = self.smoke("segfault")
        values = {}
        for number in range(1, 7):
            values[f"steps.test{number}.outputs.status"] = "passed"
            values[f"steps.test{number}.outcome"] = "success"
            values[f"steps.test{number}.outputs.duration"] = "0"
        values.update({
            "steps.test5.outputs.status": fields["status"],
            "steps.test5.outcome": "failure" if result.returncode else "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
        })
        result, fields = self.run_summary(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed")),
                         ("4", "1", "1", "1"))
        self.assertEqual(fields["overall_status"], "failure")
        self.assertEqual(fields["badge_status"], "failing")

    def run_summary(self, values):
        def replace(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, self.steps["summary"]["run"])
        return self.run_script(script)

    def test_only_valid_package_manager_skip_can_emit_a_passing_badge(self):
        values = {f"steps.test{number}.{key}": value for number in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        for status, outcome, decision, passed in (
            ("skipped", "success", "not_applicable_package_manager", True),
            ("failed", "failure", "", False),
            ("skipped", "failure", "not_applicable_package_manager", False),
            ("skipped", "success", "", False),
            ("", "", "", False),
        ):
            with self.subTest(status=status, outcome=outcome, decision=decision):
                result, fields = self.run_summary({**values,
                    "steps.test6.outputs.status": status,
                    "steps.test6.outcome": outcome,
                    "steps.test6.outputs.decision": decision,
                })
                self.assertEqual(passed, result.returncode == 0)
                self.assertEqual("0", fields["core_failed"])
                self.assertEqual("0" if passed else "1", fields["failed"])
                self.assertEqual("success" if passed else "failure", fields["overall_status"])
                self.assertEqual("passing" if passed else "failing", fields["badge_status"])

    @unittest.skipUnless(os.environ.get("XPRA_NATIVE_SMOKE") == "1"
                         and platform.system() == "Linux"
                         and platform.machine() == "aarch64",
                         "requires opt-in isolated native Arm container with Xpra and Xvfb")
    def test_native_headless_server_shuts_down_cleanly(self):
        result, fields = self.run_script(self.steps["test5"]["run"])
        server_log = self.root / "xpra-server.log"
        diagnostics = server_log.read_text() if server_log.exists() else ""
        self.assertEqual(result.returncode, 0, result.stderr + diagnostics)
        self.assertEqual(fields["status"], "passed")


if __name__ == "__main__":
    unittest.main()
