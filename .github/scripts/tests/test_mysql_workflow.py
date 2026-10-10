"""Execute the workflow's SQL, identity guards, and summaries with controlled CLIs."""

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

from test_guacamole_workflow import PMDecisionChecks


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-mysql.yml"
VERSION = "8.0.46"
PACKAGE_VERSION = "8.0.46-0ubuntu0.24.04.4"


class MySQLWorkflowTests(PMDecisionChecks, unittest.TestCase):
    workflow_path = WORKFLOW

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mysql-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-mysql"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, executable in (("python3", sys.executable), ("date", shutil.which("date")),
                                 ("mktemp", shutil.which("mktemp")), ("rm", shutil.which("rm")),
                                 ("id", shutil.which("id"))):
            (self.bin / name).symlink_to(executable)
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        GITHUB_OUTPUT=str(self.root / "output"), PROCESS_LOG=str(self.root / "processes"),
                        CLIENT_BANNER=self.banner("mysql"), SERVER_BANNER=self.banner("mysqld"),
                        CLIENT_ROW=self.package_row("client"), SERVER_ROW=self.package_row("server"))
        self.stub("uname", 'print("aarch64")\n')
        self.stub("dpkg-query", r'''
import os
import sys
operation, *args = sys.argv[1:]
kind = "CLIENT" if args[-1] == "mysql-client-core-8.0" else "SERVER"
assert args[-1] in ("mysql-client-core-8.0", "mysql-server-core-8.0")
if operation == "-W":
    assert args[0] == "-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Upstream-Version}\n"
    print(os.environ[kind + "_ROW"], end="")
    sys.exit(int(os.environ.get("PM_RC", "0")))
assert operation == "-L"
print(os.environ.get("PM_FILES", str(__file__).replace("dpkg-query", "mysql" if kind == "CLIENT" else "mysqld")))
sys.exit(int(os.environ.get("FILES_RC", "0")))
''')
        self.stub("mysql", r'''
import os
from pathlib import Path
import signal
import sys
import time
args = sys.argv[1:]
assert args[0] == "--no-defaults"
if "--version" in args:
    print(os.environ["CLIENT_BANNER"], end="")
    print(os.environ.get("CLI_STDERR", ""), end="", file=sys.stderr)
    sys.exit(int(os.environ.get("CLI_RC", "0")))
if "--help" in args:
    print("Usage: mysql [OPTIONS] [database]")
    sys.exit(int(os.environ.get("HELP_RC", "0")))
for flag in ("--protocol=SOCKET", "--user=root", "--batch", "--skip-column-names", "--raw"):
    assert flag in args, args
assert "MYSQL_PWD" not in os.environ
socket = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--socket=")))
assert os.environ["HOME"] == str(socket.parent)
assert os.environ["MYSQL_TEST_LOGIN_FILE"] == str(socket.parent / "unused-login")
sql = next(a.split("=", 1)[1] for a in args if a.startswith("--execute="))
if os.environ.get("QUERY_SIGNAL"):
    os.kill(os.getppid(), signal.SIGTERM)
    time.sleep(2)
if os.environ.get("AUTH_FAILURE"):
    print("ERROR 1045 (28000): Access denied for user 'root'@'localhost'", file=sys.stderr)
    sys.exit(1)
if sql == "SELECT 1;":
    output = os.environ.get("QUERY_OUTPUT", "1\n")
elif sql.startswith("SELECT VERSION()"):
    output = os.environ.get("IDENTITY_OUTPUT", f"8.0.46-0ubuntu0.24.04.4\taarch64\t{socket}\t{socket.parent}/data/\t1\n")
elif sql.startswith("CREATE DATABASE arm_smoke;"):
    output = os.environ.get("DATA_OUTPUT", "42\n")
else:
    print("ERROR 1146 (42S02): Table does not exist", file=sys.stderr)
    sys.exit(1)
print(output, end="")
print(os.environ.get("QUERY_STDERR", ""), end="", file=sys.stderr)
sys.exit(int(os.environ.get("QUERY_RC", "0")))
''')
        self.stub("mysqld", r'''
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time
args = sys.argv[1:]
assert args[0] == "--no-defaults"
if "--version" in args:
    print(os.environ["SERVER_BANNER"], end="")
    sys.exit(int(os.environ.get("SERVER_CLI_RC", "0")))
if "--validate-config" in args:
    assert "--skip-networking" in args and "--mysqlx=0" in args
    sys.exit(int(os.environ.get("CONFIG_RC", "0")))
data = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--datadir=")))
assert data.parent.stat().st_mode & 0o777 == 0o700
with open(os.environ["PROCESS_LOG"], "a") as log:
    log.write(json.dumps({"pid": os.getpid(), "scope": str(data.parent), "args": args}) + "\n")
if "--initialize-insecure" in args:
    data.mkdir()
    sys.exit(int(os.environ.get("INIT_RC", "0")))
assert "--skip-networking" in args and "--mysqlx=0" in args
if os.environ.get("START_FAILURE"):
    sys.exit(1)
listener = socket.socket(socket.AF_UNIX)
listener.bind(str(data.parent / "mysql.sock"))
listener.listen()
signal.signal(signal.SIGTERM, lambda *_: sys.exit(int(os.environ.get("STOP_RC", "0"))))
while True:
    time.sleep(0.1)
''')

    def banner(self, name):
        prefix = str(self.bin / name)
        return f"{prefix}  Ver {PACKAGE_VERSION} for Linux on aarch64 ((Ubuntu))\n"

    def package_row(self, kind):
        return f"mysql-{kind}-core-8.0\tinstall ok installed\t{PACKAGE_VERSION}\tarm64\t{VERSION}\n"

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def verified(self):
        return {"steps.version.outputs.status": "passed", "steps.version.outputs.version": VERSION,
                "steps.version.outputs.package_version": PACKAGE_VERSION,
                "steps.version.outputs.client": str(self.bin / "mysql"),
                "steps.version.outputs.server": str(self.bin / "mysqld")}

    def run_step(self, name, values=None, source=None, **env):
        values = self.verified() if values is None else values

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
        result = subprocess.run(["/bin/bash", "-e", "-c", render(source or step["run"])],
                                cwd=self.root, env={**self.env, **step_env, **env},
                                capture_output=True, text=True, timeout=20)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return result, outputs

    def assert_rejected(self, name, values=None, **env):
        result, outputs = self.run_step(name, values, **env)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "failed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        if name == "version":
            for key in ("version", "package_version", "client", "server"):
                self.assertNotIn(key, outputs)
        return result, outputs

    def assert_cleaned(self):
        for line in (self.root / "processes").read_text().splitlines():
            record = json.loads(line)
            self.assertFalse(Path(record["scope"]).exists(), record)
            with self.assertRaises(ProcessLookupError):
                os.kill(record["pid"], 0)

    def test_real_banner_shape_is_bound_to_both_owned_arm_packages(self):
        result, output = self.run_step("version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["version"], VERSION)
        self.assertEqual(output["package_version"], PACKAGE_VERSION)
        self.assertEqual(output["status"], "passed")

    def test_invalid_wrong_product_architecture_and_duplicate_banners(self):
        for key in ("CLIENT_BANNER", "SERVER_BANNER"):
            for value in ("", "Linux\n", "8.0.46\n", self.env[key] * 2,
                          self.env[key] + "\n", self.env[key].replace("aarch64", "x86_64"),
                          self.env[key].replace(PACKAGE_VERSION, "9.0.1"),
                          self.env[key].replace("mysql", "mariadb")):
                with self.subTest(key=key, value=value):
                    self.assert_rejected("version", **{key: value})

    def test_command_failure_and_diagnostics_cannot_publish_a_version(self):
        for env in ({"CLI_RC": "1"}, {"SERVER_CLI_RC": "1"}, {"PM_RC": "1"},
                    {"FILES_RC": "1"}, {"CLI_STDERR": "invalid option\n"}):
            with self.subTest(env=env):
                self.assert_rejected("version", **env)

    def test_invalid_package_identity_or_unowned_executable_is_rejected(self):
        for key in ("CLIENT_ROW", "SERVER_ROW"):
            row = self.env[key]
            for value in ("", row * 2, row.replace("arm64", "amd64"),
                          row.replace("install ok installed", "deinstall ok config-files"),
                          row.replace("mysql", "mariadb"), row.replace(PACKAGE_VERSION, "Linux"),
                          row.replace("\t" + VERSION + "\n", "\t8.0.45\n")):
                with self.subTest(key=key, value=value):
                    self.assert_rejected("version", **{key: value})
        self.assert_rejected("version", PM_FILES="/unowned/mysql\n")

    def test_client_server_version_disagreement_fails(self):
        self.assert_rejected("version", SERVER_ROW=self.env["SERVER_ROW"].replace("8.0.46", "8.0.45"),
                             SERVER_BANNER=self.env["SERVER_BANNER"].replace("8.0.46", "8.0.45"))

    def test_missing_binary_and_unverified_identity_fail_baseline(self):
        (self.bin / "mysql").unlink()
        self.assert_rejected("version")
        self.assert_rejected("test1")
        values = self.verified()
        values["steps.version.outputs.status"] = "failed"
        for name in ("test1", "test2", "test5"):
            self.assert_rejected(name, values)

    def test_help_and_configuration_nonzero_exit_fail(self):
        self.assert_rejected("test3", HELP_RC="1")
        self.assert_rejected("test4", CONFIG_RC="1")

    def test_private_sql_success_ignores_shared_credentials_and_cleans_up(self):
        result, output = self.run_step("test5", MYSQL_PWD="unrelated-shared-password",
                                       MYSQL_TEST_LOGIN_FILE="/unrelated/login", MYSQL_HOST="shared-db")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "passed")
        self.assertIn("CREATE DATABASE arm_smoke", result.stdout)
        self.assert_cleaned()

    def test_auth_failure_fails_and_cleans_up(self):
        result, _ = self.assert_rejected("test5", AUTH_FAILURE="1")
        self.assertIn("ERROR 1045", result.stderr)
        self.assert_cleaned()

    def test_interrupted_query_fails_and_cleans_up(self):
        self.assert_rejected("test5", QUERY_SIGNAL="1")
        self.assert_cleaned()

    def test_invalid_sql_fails_and_cleans_up(self):
        source = self.steps["test5"]["run"].replace('query("SELECT 1;",', 'query("SELECT * FROM missing_table;",')
        result, _ = self.assert_rejected("test5", source=source)
        self.assertIn("ERROR 1146", result.stderr)
        self.assert_cleaned()

    def test_query_exit_diagnostics_empty_wrong_duplicate_or_data_result_fail(self):
        for env in ({"QUERY_RC": "1"}, {"QUERY_STDERR": "query warning\n"},
                    {"QUERY_OUTPUT": ""}, {"QUERY_OUTPUT": "0\n"}, {"QUERY_OUTPUT": "1\n1\n"},
                    {"DATA_OUTPUT": "40\n"}, {"IDENTITY_OUTPUT": "8.0.46\n"}):
            with self.subTest(env=env):
                result, _ = self.assert_rejected("test5", **env)
                self.assertIn("SQL failed:", result.stderr)
                self.assert_cleaned()

    def test_initialization_start_and_shutdown_failures_fail_and_clean_up(self):
        for env in ({"INIT_RC": "1"}, {"START_FAILURE": "1"}, {"STOP_RC": "1"}):
            with self.subTest(env=env):
                self.assert_rejected("test5", **env)
                self.assert_cleaned()

    def test_wrong_architecture_or_invalid_version_cannot_pass_sql(self):
        self.stub("uname", 'print("x86_64")\n')
        self.assert_rejected("test5")
        self.stub("uname", 'print("aarch64")\n')
        for version in ("", "Linux", "unknown", PACKAGE_VERSION + "\n"):
            self.assert_rejected("test5", MYSQL_VERSION=version)

    def test_package_manager_skip_and_five_pass_summary(self):
        values = self.summary_values()
        result, regression = self.run_step("test6", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(regression["status"], "skipped")
        self.assertEqual(regression["decision"], "not_applicable_package_manager")
        self.assertEqual(regression["current_version"], VERSION)
        values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
        result, output = self.run_step("summary", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"passed": "5", "failed": "0", "core_failed": "0", "skipped": "1",
                    "duration": "0", "overall_status": "success", "badge_status": "passing"})

    def test_every_failed_or_missing_baseline_status_fails_summary(self):
        for i in range(1, 6):
            for status in ("failed", "", "skipped"):
                with self.subTest(test=i, status=status):
                    values = self.summary_values()
                    values[f"steps.test{i}.outputs.status"] = status
                    self.pm_guard(values)
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output["passed"], "4")
                    self.assertEqual(output["failed"], "1")
                    self.assertEqual(output["core_failed"], "1")
                    self.assertEqual(output["skipped"], "1")
                    self.assertEqual(output["overall_status"], "failure")
                    self.assertEqual(output["badge_status"], "failing")

    def test_absent_regression_step_does_not_claim_a_skip_or_success(self):
        values = {key: value for key, value in self.summary_values().items()
                  if not key.startswith("steps.test6.")}
        result, output = self.run_step("summary", values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["skipped"], "0")
        self.assertEqual(output["overall_status"], "failure")

    def test_summary_retains_durations_when_a_core_step_fails(self):
        values = self.summary_values()
        values.update({f"steps.test{i}.outputs.duration": str(i) for i in range(1, 6)})
        values["steps.test6.outputs.duration"] = "0"
        values["steps.test5.outcome"] = "failure"
        values["steps.test5.outputs.status"] = "failed"
        self.pm_guard(values)
        result, output = self.run_step("summary", values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["duration"], "15")

    def test_passed_core_status_with_failed_or_missing_outcome_fails_summary(self):
        for i in range(1, 6):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(test=i, outcome=outcome):
                    values = self.summary_values()
                    values[f"steps.test{i}.outcome"] = outcome
                    self.pm_guard(values)
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output["passed"], "4")
                    self.assertEqual(output["failed"], "1")
                    self.assertEqual(output["core_failed"], "1")
                    self.assertEqual(output["skipped"], "1")
                    self.assertEqual(output["overall_status"], "failure")
                    self.assertEqual(output["badge_status"], "failing")

    def test_package_manager_skip_requires_successful_outcome_and_exact_decision(self):
        cases = [("outcome", value) for value in ("failure", "cancelled", "skipped", "")]
        cases += [("outputs.decision", value) for value in ("", "not_configured", "metadata_review_required")]
        cases += [("outputs.status", value) for value in ("", "passed", "failed")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = self.summary_values()
                values[f"steps.test6.{key}"] = value
                result, output = self.run_step("summary", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output["passed"], "5")
                self.assertEqual(output["failed"], "1")
                self.assertEqual(output["core_failed"], "0")
                self.assertEqual(output["skipped"], "0")
                self.assertEqual(output["overall_status"], "failure")
                self.assertEqual(output["badge_status"], "failing")

    def test_finalizers_are_explicit_and_test_scope_has_no_shared_service_access(self):
        for name in ("version", "test1", "test2", "test3", "test4", "test5"):
            source = self.steps[name]["run"]
            self.assertIn('trap \'finish "$?"\' EXIT', source)
            self.assertTrue(source.rstrip().endswith("finish 0"))
        source = "\n".join(self.steps[name]["run"] for name in ("test4", "test5"))
        for forbidden in ("systemctl", "sudo mysql", "/var/lib/mysql", "--skip-grant-tables"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
