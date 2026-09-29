"""Fixture tests for packaged ActiveMQ help; these are not native Arm proof."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-activemq.yml"

# Actual producer output from run 35035383220, job 104603237925, lines
# 1286-1288 (timestamps removed). The old log did not retain the exit code.
LAUNCHER_FAILURE = r'''INFO: Loading '/usr/share/activemq/activemq-options'
INFO: Using java '/usr/lib/jvm/default-java//bin/java'
/usr/bin/activemq: 437: "/usr/lib/jvm/default-java//bin/java" -Xms512M -Xmx512M -Dorg.apache.activemq.UseDedicatedTaskRunner=true             --add-reads=java.xml=java.logging           --add-opens java.base/java.security=ALL-UNNAMED           --add-opens java.base/java.net=ALL-UNNAMED           --add-opens java.base/java.lang=ALL-UNNAMED           --add-opens java.base/java.util=ALL-UNNAMED           --add-opens java.naming/javax.naming.spi=ALL-UNNAMED           --add-opens java.rmi/sun.rmi.transport.tcp=ALL-UNNAMED           --add-opens java.base/java.util.concurrent=ALL-UNNAMED           --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED           --add-exports=java.base/sun.net.www.protocol.http=ALL-UNNAMED           --add-exports=java.base/sun.net.www.protocol.https=ALL-UNNAMED           --add-exports=java.base/sun.net.www.protocol.jar=ALL-UNNAMED           --add-exports=jdk.xml.dom/org.w3c.dom.html=ALL-UNNAMED           --add-exports=jdk.naming.rmi/com.sun.jndi.url.rmi=ALL-UNNAMED           -Dactivemq.classpath="/var/lib/activemq/conf:/var/lib/activemq/../lib/:"           -Dactivemq.home="/usr/share/activemq"           -Dactivemq.base="/var/lib/activemq/"           -Dactivemq.conf="/var/lib/activemq/conf"           -Dactivemq.data="/var/lib/activemq/data"           -Djolokia.conf="file:/var/lib/activemq/conf/jolokia-access.xml"                      -jar "/usr/share/activemq/bin/activemq.jar" --help : not found
'''

# Actual help body from hosted Arm run 35038406743, job 104612609847,
# lines 1327-1356. Timestamps removed; GitHub's final-line masking retained.
# The producer succeeded, but the original check incorrectly required the
# start description to match a "Start" prefix instead of task-row structure.
VALID_HELP = '''Usage: Main [--extdir <dir>] [task] [task-options] [task data]

Tasks:
    browse                   - Display selected messages in a specified destination.
    bstat                    - Performs a predefined query that displays useful statistics regarding the specified broker
    consumer                 - Receives messages from the broker
    create                   - Creates a runnable broker instance in the specified path.
    decrypt                  - Decrypts given text
    dstat                    - Performs a predefined query that displays useful tabular statistics regarding the specified destination type
    encrypt                  - Encrypts given text
    export                   - Exports a stopped brokers data files to an archive file
    list                     - Lists all available brokers in the specified JMX context
    producer                 - Sends messages to the broker
    purge                    - Delete selected destination's messages that matches the message selector
    query                    - Display selected broker component's attributes and statistics.
    start                    - Creates and starts a broker using a configuration file, or a broker URI.
    stop                     - Stops a running broker specified by the broker name.

Task Options (Options specific to each task):
    --extdir <dir>  - Add the jar files in the directory to the classpath.
    --version       - Display the version information.
    -h,-?,--help    - Display this help information. To display task specific help, use Main [task] -h,-?,--help

Task Data:
    - Information needed by each specific task.

JMX system property options:
    -Dactivemq.jmx.url=<jmx service uri> (default is: 'service:jmx:rmi:///jndi/rmi://localhost:1099/jmxrmi')
    -Dactivemq.jmx.user=<user name>
    -Dactivemq.jmx.***
'''


class ActiveMQWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="activemq-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "package/bin").mkdir(parents=True)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-activemq"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.steps["report"] = next(step for step in self.job["steps"]
                                    if step["name"] == "Create test summary")
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_ENV=str(self.root / "environment"),
                        GITHUB_STEP_SUMMARY=str(self.root / "summary"),
                        ACTIVEMQ_BIN=str(self.root / "package/bin/activemq"),
                        ACTIVEMQ_JAVA=str(self.bin / "packaged-java"),
                        HELP_OUTPUT=VALID_HELP, HELP_RC="0", JAVA_RC="0",
                        COMMAND_LOG=str(self.root / "commands"))
        self.values = {"steps.install.outcome": "success", "steps.install.outputs.install_status": "success",
                       "steps.version.outcome": "success", "steps.version.outputs.version": "5.17.6+dfsg-1",
                       "steps.test6.outcome": "success", "steps.test6.outputs.status": "skipped",
                       "steps.test6.outputs.decision": "not_applicable_package_manager"}
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed", f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.stub(self.env["ACTIVEMQ_BIN"], '''
test "$#" -eq 1 && test "$1" = --help || exit 91
test "$JAVACMD" = "$ACTIVEMQ_JAVA" || exit 92
printf '%s\n' "$HELP_OUTPUT"
exit "$HELP_RC"
''')
        self.stub("packaged-java", '''
test "$#" -eq 1 && test "$1" = -version || exit 93
echo 'openjdk version "21.0.12"' >&2
exit "$JAVA_RC"
''')
        self.stub("java", "exit 0\n")
        self.stub("activemq", "exit 94\n")
        self.stub("sudo", '''
import json, os, sys
from pathlib import Path
assert sys.argv[1:3] == ["-u", "activemq"], sys.argv
with Path(os.environ["COMMAND_LOG"]).open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
os.execvp(sys.argv[3], sys.argv[3:])
''', python=True)
        self.stub("timeout", '''
import os, sys
assert sys.argv[1:4] == ["--signal=TERM", "--kill-after=5s", "30s"], sys.argv
if os.environ.get("TIMEOUT_RC"):
    sys.exit(int(os.environ["TIMEOUT_RC"]))
os.execvp(sys.argv[4], sys.argv[4:])
''', python=True)

    def stub(self, name, source, python=False):
        path = self.bin / name
        header = f"#!{sys.executable}\n" if python else "#!/bin/bash\nset -euo pipefail\n"
        path.write_text(header + source)
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
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env=dict(self.env, **env), text=True, capture_output=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Outputs must be emitted once")
        return result, outputs

    def assert_help_failed(self, **env):
        result, outputs = self.run_step("test3", **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertTrue(outputs["duration"].isdigit())
        return result, outputs

    def test_exact_false_green_launcher_output_is_rejected_even_with_zero_exit(self):
        old_match = subprocess.run(["grep", "-qi", r"usage\|help\|ActiveMQ"],
                                   input=LAUNCHER_FAILURE, text=True)
        self.assertEqual(0, old_match.returncode, "Fixture must reproduce the old false match")
        for code in ("0", "127"):
            with self.subTest(code=code):
                result, outputs = self.assert_help_failed(HELP_OUTPUT=LAUNCHER_FAILURE, HELP_RC=code)
                self.assertEqual(code, outputs["help_exit_code"])
                self.assertIn(LAUNCHER_FAILURE.rstrip(), result.stdout)

    def test_valid_help_requires_successful_producer_and_uses_packaged_user_and_java(self):
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual("0", outputs["help_exit_code"])
        self.assertEqual(["-u", "activemq", "env", "JAVACMD=" + self.env["ACTIVEMQ_JAVA"],
                          self.env["ACTIVEMQ_BIN"], "--help"],
                         json.loads((self.root / "commands").read_text()))
        for code in ("1", "7", "126", "127", "143"):
            with self.subTest(code=code):
                result, outputs = self.assert_help_failed(HELP_RC=code)
                self.assertEqual(int(code), result.returncode)
                self.assertEqual(code, outputs["help_exit_code"])

    def test_help_must_have_usage_tasks_start_and_options_not_just_package_words(self):
        invalid = ["", "ActiveMQ --help", "usage help ActiveMQ", "INFO: Using java '/bin/java'"]
        for fragment in ("Usage: Main", "Tasks:", "    start ", "Task Options (", "    -h,-?,--help"):
            invalid.append("\n".join(line for line in VALID_HELP.splitlines() if not line.startswith(fragment)))
        for text in invalid:
            with self.subTest(output=text):
                self.assert_help_failed(HELP_OUTPUT=text)

    def test_hosted_help_accepts_task_structure_without_requiring_description_prose(self):
        old_match = subprocess.run(
            ["grep", "-Eq", r"^[[:space:]]+start[[:space:]]+-[[:space:]]+Start"],
            input=VALID_HELP, text=True,
        )
        self.assertEqual(1, old_match.returncode, "Captured help must reproduce the hosted rejection")
        for description in ("Creates and starts a broker using a configuration file, or a broker URI.",
                            "Starts a broker using the given configuration file."):
            with self.subTest(description=description):
                help_text = re.sub(r"(?m)^(    start\s+- ).*$", r"\g<1>" + description, VALID_HELP)
                result, outputs = self.run_step("test3", HELP_OUTPUT=help_text)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertEqual("0", outputs["help_exit_code"])

    def test_start_task_row_still_requires_exact_command_separator_and_description(self):
        for row in ("    restart                  - Creates and starts a broker.",
                    "    start                    - ", "    start                    -     ",
                    "    start                      Creates and starts a broker."):
            with self.subTest(row=row):
                help_text = re.sub(r"(?m)^    start .*$", row, VALID_HELP)
                self.assert_help_failed(HELP_OUTPUT=help_text)

    def test_launcher_and_jvm_errors_cannot_hide_beside_help(self):
        for error in (LAUNCHER_FAILURE, 'Error: Unable to access jarfile /missing/activemq.jar',
                      'Error: Could not find or load main class org.apache.activemq.console.Main',
                      'Exception in thread "main" java.lang.NoClassDefFoundError',
                      'ERROR: Configuration variable JAVA_HOME or JAVACMD is not defined correctly.',
                      'Unrecognized option: --bad-option', '/usr/bin/activemq: Permission denied'):
            with self.subTest(error=error):
                self.assert_help_failed(HELP_OUTPUT=VALID_HELP + "\n" + error)

    def test_missing_packaged_launcher_or_runtime_cannot_fall_back_to_path(self):
        for key in ("ACTIVEMQ_BIN", "ACTIVEMQ_JAVA"):
            for path in ("", str(self.root / "missing")):
                with self.subTest(key=key, path=path):
                    self.assert_help_failed(**{key: path})
        self.assertFalse((self.root / "commands").exists())

    def test_help_timeout_is_a_failure(self):
        result, outputs = self.assert_help_failed(TIMEOUT_RC="124")
        self.assertEqual(124, result.returncode)
        self.assertEqual("124", outputs["help_exit_code"])

    def test_late_help_step_failure_is_not_a_pass(self):
        source = self.steps["test3"]["run"].replace("\nfinish 0\n", "\nexit 17\nfinish 0\n")
        result, outputs = self.run_step("test3", source=source)
        self.assertEqual(17, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_finalizer_outputs_are_visible_to_existing_workflow_audit(self):
        self.assertTrue(self.steps["test3"]["run"].rstrip().endswith("finish 0"))
        code = '''
from pathlib import Path
import sys
import yaml
sys.path.insert(0, ".github/scripts")
import package_observation_migration_audit as audit
workflow = yaml.safe_load(Path(".github/workflows/test-activemq.yml").read_text())
step = next(s for s in workflow["jobs"]["test-activemq"]["steps"] if s.get("id") == "test3")
for output in ("status", "duration", "help_exit_code"):
    assert audit._step_emits_output(Path.cwd(), step, output), output
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=WORKFLOW.parents[2],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_java_check_uses_the_launchers_runtime_not_an_unrelated_path_java(self):
        for code in ("0", "9"):
            with self.subTest(code=code):
                result, outputs = self.run_step("test4", JAVA_RC=code)
                self.assertEqual(code == "0", result.returncode == 0)
                self.assertEqual("passed" if code == "0" else "failed", outputs["status"])
        commands = [json.loads(line) for line in (self.root / "commands").read_text().splitlines()]
        self.assertEqual([["-u", "activemq", self.env["ACTIVEMQ_JAVA"], "-version"]] * 2, commands)
        result, outputs = self.run_step("test4", ACTIVEMQ_JAVA=str(self.root / "missing"))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_install_keeps_apt_target_and_exports_the_package_owned_launcher(self):
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text('test "$*" = \'--packages default-jre-headless activemq\'\n')
        self.stub("dpkg", 'test "$*" = "-L activemq"\nprintf "%s\\n" "$ACTIVEMQ_BIN"\n')
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual({f"test{i}" for i in range(1, 7)},
                         {key for key in self.steps if re.fullmatch(r"test\d+", key)})
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("success", outputs["install_status"])
        environment = dict(line.split("=", 1) for line in (self.root / "environment").read_text().splitlines())
        self.assertEqual(self.env["ACTIVEMQ_BIN"], environment["ACTIVEMQ_BIN"])
        self.assertEqual("/usr/lib/jvm/default-java/bin/java", environment["ACTIVEMQ_JAVA"])

    def test_summary_counts_five_passes_and_one_real_package_manager_skip(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"passed": "5", "failed": "0", "skipped": "1", "core_failed": "0",
                          "duration": "15", "overall_status": "success", "badge_status": "passing"}, outputs)
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("not_applicable_package_manager", outputs["decision"])
        self.assertEqual("not_applicable", outputs["next_installed_version"])

    def test_each_core_requires_passed_status_and_raw_success_outcome(self):
        for i in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", ""), ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped")):
                with self.subTest(test=i, status=status, outcome=outcome):
                    result, outputs = self.run_step("summary", {
                        f"steps.test{i}.outputs.status": status, f"steps.test{i}.outcome": outcome,
                        f"steps.test{i}.conclusion": "success"})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("4", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("1", outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])

    def test_exemption_requires_successful_install_version_and_actual_test6(self):
        for key, value in (("steps.install.outcome", "failure"), ("steps.install.outcome", ""),
                           ("steps.install.outputs.install_status", "failed"),
                           ("steps.version.outcome", "failure"), ("steps.version.outputs.version", ""),
                           ("steps.version.outputs.version", "unknown"),
                           ("steps.test6.outcome", "failure"), ("steps.test6.outcome", "cancelled"),
                           ("steps.test6.outcome", "skipped"), ("steps.test6.outcome", ""),
                           ("steps.test6.outputs.status", "passed"), ("steps.test6.outputs.status", ""),
                           ("steps.test6.outputs.decision", ""),
                           ("steps.test6.outputs.decision", "not_configured")):
            with self.subTest(key=key, value=value):
                result, outputs = self.run_step("summary", {key: value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("failure", outputs["overall_status"])

    def test_summary_rejects_invalid_duration_without_losing_failure_outputs(self):
        for duration in ("-1", "garbage", "9999999"):
            with self.subTest(duration=duration):
                result, outputs = self.run_step("summary", {"steps.test3.outputs.duration": duration})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["core_failed"])
                self.assertEqual("failure", outputs["overall_status"])

    def test_human_summary_does_not_repeat_stale_pass_after_step_failure(self):
        result, _ = self.run_step("report", {"steps.test3.outcome": "failure"})
        self.assertEqual(0, result.returncode, result.stderr)
        summary = (self.root / "summary").read_text()
        self.assertIn("3. Check 'activemq --help' output: failed (step outcome: failure)", summary)
        self.assertNotIn("3. Check 'activemq --help' output: passed", summary)


if __name__ == "__main__":
    unittest.main()
