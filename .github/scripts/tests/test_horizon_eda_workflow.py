"""Focused checks for the package workflow's actual Bash steps."""

import os
from pathlib import Path
import re
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-horizon-eda.yml"


class HorizonEdaWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="horizon-eda-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-horizon-eda"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        RUNNER_TEMP=str(self.root), TMPDIR=str(self.root),
                        FIXTURE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        (self.root / "baseline-src").mkdir()
        self.values = {"steps.install.outputs.install_mode": "github_source",
                       "steps.install.outputs.install_status": "success"}

    def stub(self, name, content):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + content)
        path.chmod(0o755)

    def run_script(self, script, values=None, **env):
        values = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                key = term.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if line)
        return result, outputs

    def run_step(self, name, values=None, **env):
        return self.run_script(self.steps[name]["run"], values, **env)

    def passing(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}


    def window_fixture(self):
        helper = self.root / "fixture-timeout.py"
        helper.write_text(r'''
import os, signal, subprocess, sys, time
from pathlib import Path

proof = Path(sys.argv[-1])
process = subprocess.Popen(sys.argv[1:], start_new_session=True)
deadline = time.monotonic() + 8
# Only the workflow's completed PID/window check starts the short fixture hold.
while process.poll() is None and time.monotonic() < deadline:
    try:
        lines = proof.read_text().splitlines(keepends=True)
    except FileNotFoundError:
        lines = []
    if any(line.startswith("window_verified ") and line.endswith("\n") for line in lines):
        time.sleep(0.2)
        break
    time.sleep(0.02)
rc = process.poll()
if rc is None:
    rc = 124
    print("fixture timeout: terminating owned process group", file=sys.stderr)
try:
    os.killpg(process.pid, signal.SIGTERM)
except ProcessLookupError:
    pass
try:
    process.wait(timeout=3)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
sys.exit(rc)
''')
        self.env["FIXTURE_TIMEOUT_HELPER"] = str(helper)
        self.env["FIXTURE_WINDOW_PID_FILE"] = str(self.root / "window-pid")
        self.env["FIXTURE_GUI_READY"] = str(self.root / "gui-ready")
        self.stub("timeout", r'''
test "$1" = --kill-after=3s -o "$1" = --kill-after=5s
duration="$2"
shift 2
if [ "$duration" = 15s ]; then
  exec "$FIXTURE_PYTHON" "$FIXTURE_TIMEOUT_HELPER" "$@"
fi
test "$duration" = 30s
exec "$@"
''')
        self.stub("xdotool", r'''
case "$1" in
  search)
    test "$2" = --onlyvisible
    test "$3" = --pid
    printf '%s\n' "$4" > "$FIXTURE_WINDOW_PID_FILE"
    if [ "${FIXTURE_NO_WINDOW:-0}" = 1 ]; then exit 1; fi
    test -f "$FIXTURE_GUI_READY"
    test "$(cat "$FIXTURE_GUI_READY")" = "$4"
    kill -0 "$4"
    echo 42 ;;
  getwindowname) echo "${FIXTURE_WINDOW_TITLE:-Horizon EDA}" ;;
  getwindowpid) echo "${FIXTURE_WINDOW_PID:-$(cat "$FIXTURE_WINDOW_PID_FILE")}" ;;
  *) exit 99 ;;
esac
''')
        self.stub("xprop", r'''
if [ -n "${FIXTURE_XPROP_DELAY:-}" ]; then sleep "$FIXTURE_XPROP_DELAY"; fi
echo "_NET_WM_PID(CARDINAL) = $(cat "$FIXTURE_WINDOW_PID_FILE")"
exit "${FIXTURE_XPROP_RC:-0}"
''')

    def runtime_fixture(self):
        self.window_fixture()
        self.stub("uname", 'echo "${FIXTURE_ARCH:-aarch64}"\n')
        self.stub("sudo", 'echo apt-diagnostic; exit "${FIXTURE_APT_RC:-0}"\n')
        self.stub("python3", 'exec "$FIXTURE_PYTHON" "$@"\n')
        self.stub("file", r'''
case "$1" in
  *horizon-imp) arch="${FIXTURE_IMP_ARCH:-aarch64}" ;;
  *horizon-eda) arch="${FIXTURE_EDA_ARCH:-aarch64}" ;;
  *) exit 97 ;;
esac
echo "$1: ELF 64-bit LSB pie executable, $arch"
''')
        self.stub("xvfb-run", r'''
test "$1" = -a
test "$2" = -s
test "$3" = '-screen 0 1280x1024x24 -nolisten tcp'
test -d "$XDG_CONFIG_HOME/horizon"
test -d "$XDG_CACHE_HOME"
test -d "$XDG_RUNTIME_DIR"
shift 3
exec "$@"
''')
        self.stub("dbus-run-session", 'test "$1" = --\nshift\nexec "$@"\n')
        self.stub("horizon-imp", 'test "$1" = --help\necho "${FIXTURE_HELP:-horizon interactive manipulator}"\nexit "${FIXTURE_HELP_RC:-0}"\n')
        self.stub("horizon-eda", r'''
echo gui-diagnostic
if [ "${FIXTURE_GUI_RC:-124}" != 124 ]; then exit "$FIXTURE_GUI_RC"; fi
printf '%s\n' "$$" > "$FIXTURE_GUI_READY"
sleep 30
''')
        self.env["FIXTURE_BIN"] = str(self.bin)
        self.stub("apt-get", r'''
for argument in "$@"; do
  test "$argument" != install
  if [ "$argument" = download ]; then
    touch "horizon-eda_${BASELINE_VERSION}_arm64.deb"
    exit "${FIXTURE_DOWNLOAD_RC:-0}"
  fi
done
exit 98
''')
        self.stub("dpkg-deb", r'''
case "$1" in
  -f)
    case "$3" in
      Package) echo "${FIXTURE_DEB_NAME:-horizon-eda}" ;;
      Version) echo "${FIXTURE_DEB_VERSION:-$BASELINE_VERSION}" ;;
      Architecture) echo "${FIXTURE_DEB_ARCH:-arm64}" ;;
      *) exit 98 ;;
    esac ;;
  -x)
    mkdir -p "$3/usr/bin"
    cp "$FIXTURE_BIN/horizon-imp" "$FIXTURE_BIN/horizon-eda" "$3/usr/bin/"
    ;;
  -e)
    mkdir -p "$3"
    touch "$3/md5sums"
    ;;
  *) exit 99 ;;
esac
''')
        self.stub("sha256sum", 'echo fixture-archive-digest\n')
        self.stub("md5sum", 'test "$1" = -c\necho payload-diagnostic\nexit "${FIXTURE_PAYLOAD_RC:-0}"\n')
        for source in ("baseline-src", "next-src"):
            scripts = self.root / source / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "stm32_to_json.py").write_text('''
import json, os, sys
from pathlib import Path
import xml.etree.ElementTree as ET
pins = ET.parse(sys.argv[1]).getroot().findall('{*}Pin')
assert [p.attrib['Name'] for p in pins] in (['PA0', 'VDD', 'NRST'], ['PB7', 'VDDA'])
candidate = Path.cwd().name == 'next-src'
data = ({'11': {'pin': 'PB7', 'direction': 'bidirectional', 'alt': ['I2C1_SDA', 'USART1_RX']},
         '12': {'direction': 'power_input'}} if candidate else
        {'1': {'pin': 'PA0', 'direction': 'bidirectional', 'alt': ['USART2_CTS']},
         '2': {'direction': 'power_input'}, '3': {'direction': 'input'}})
print(os.environ.get('FIXTURE_CONVERTER_JSON', json.dumps(data)))
''')
        scripts = self.root / "next-src/scripts"
        (scripts / "make_help.py").write_text('''
import os, sys
from pathlib import Path
assert Path(sys.argv[1]).is_file()
Path(sys.argv[2]).write_text(os.environ.get('FIXTURE_HELP_HEADER', 'class HelpTexts {};'))
Path(sys.argv[3]).write_text(os.environ.get('FIXTURE_HELP_CPP', '#include "help_texts.hpp"'))
''')
        (self.root / "next-src/src").mkdir()
        (self.root / "next-src/src/help_texts.txt").write_text('fixture help input')

    def test_runtime_prepares_sqlite_directory_before_help_and_checks_converter(self):
        self.runtime_fixture()
        result, output = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("1.0.0-1build1", output["installed_version"])
        self.assertTrue(output["duration"].isdigit())

    def test_runtime_waits_for_complete_window_proof_after_slow_xprop(self):
        self.runtime_fixture()
        result, output = self.run_step("test5", FIXTURE_XPROP_DELAY="1.25")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        proof = next(self.root.rglob("window.txt")).read_text()
        self.assertRegex(proof, r"(?m)^window_verified pid=\d+ id=42 title=Horizon EDA$")

    def test_runtime_rejects_wrong_architecture_help_abort_and_early_gui_exit(self):
        self.runtime_fixture()
        for env in ({"FIXTURE_ARCH": "x86_64"}, {"FIXTURE_IMP_ARCH": "x86-64"},
                    {"FIXTURE_EDA_ARCH": "x86-64"}, {"FIXTURE_HELP": "unrelated executable"},
                    {"FIXTURE_HELP_RC": "134"}, {"FIXTURE_GUI_RC": "134"},
                    {"FIXTURE_GUI_RC": "0"}, {"FIXTURE_GUI_RC": "137"},
                    {"FIXTURE_APT_RC": "100"}, {"FIXTURE_DOWNLOAD_RC": "100"},
                    {"FIXTURE_DEB_NAME": "unrelated"}, {"FIXTURE_DEB_VERSION": "2.5.0-1build4"},
                    {"FIXTURE_DEB_ARCH": "amd64"}, {"FIXTURE_PAYLOAD_RC": "1"},
                    {"FIXTURE_NO_WINDOW": "1"}, {"FIXTURE_WINDOW_PID": "99999999"},
                    {"FIXTURE_WINDOW_TITLE": "unrelated"}, {"FIXTURE_XPROP_RC": "1"}):
            with self.subTest(env=env):
                result, output = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertTrue(output["duration"].isdigit())
                self.assertNotIn("installed_version", output)
        result, _ = self.run_step("test5", FIXTURE_GUI_RC="134")
        self.assertIn("gui-diagnostic", result.stdout)

    def test_baseline_converter_rejects_every_changed_pin_assertion(self):
        self.runtime_fixture()
        valid = {"1": {"pin": "PA0", "direction": "bidirectional", "alt": ["USART2_CTS"]},
                 "2": {"direction": "power_input"}, "3": {"direction": "input"}}
        for pin, field in (("1", "pin"), ("1", "direction"), ("1", "alt"),
                           ("2", "direction"), ("3", "direction")):
            with self.subTest(pin=pin, field=field):
                data = json.loads(json.dumps(valid))
                data[pin][field] = "wrong"
                result, output = self.run_step("test5", FIXTURE_CONVERTER_JSON=json.dumps(data))
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])

    def test_candidate_converter_and_generated_cpp_are_actually_checked(self):
        if not shutil.which("g++"):
            self.skipTest("C++ compiler required for generated help check")
        self.runtime_fixture()
        script = self.steps["test6"]["with"]["limited_cpu_probe"]
        result, _ = self.run_script(script)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for env in ({"FIXTURE_CONVERTER_JSON": "{}"}, {"FIXTURE_HELP_HEADER": "wrong"},
                    {"FIXTURE_HELP_CPP": ""}, {"FIXTURE_HELP_CPP": "this is not C++"}):
            with self.subTest(env=env):
                result, _ = self.run_script(script, **env)
                self.assertNotEqual(0, result.returncode)

    def test_docs_response_is_fully_written_and_fetch_failure_is_not_ignored(self):
        self.stub("curl", r'''
test "$1" = -fsL
test "$3" = -o
"$FIXTURE_PYTHON" - "$4" <<'PY'
import os, sys
from pathlib import Path
Path(sys.argv[1]).write_text(os.environ.get('FIXTURE_DOC', 'Linux installation\n') + 'x' * 2000000)
PY
exit "${FIXTURE_CURL_RC:-0}"
''')
        result, output = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", output["status"])
        for env in ({"FIXTURE_CURL_RC": "23"}, {"FIXTURE_CURL_RC": "22"}, {"FIXTURE_DOC": "unrelated"}):
            result, output = self.run_step("test3", **env)
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", output.get("status"))

    def test_late_failure_cannot_leave_a_pass_output(self):
        result, output = self.run_step("test5", TEST5_COMMAND='echo status=passed >> "$GITHUB_OUTPUT"; exit 23')
        self.assertEqual(23, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertTrue(output["duration"].isdigit())

    def test_candidate_source_probe_does_not_claim_an_installed_gui(self):
        self.assertEqual("not_installed", self.job["outputs"]["regression_next_installed_version"])

    def test_summary_requires_both_passed_output_and_successful_outcome(self):
        result, output = self.run_step("summary", self.passing())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", output["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                                 ("outputs.status", "failed"), ("outputs.status", "invalid"),
                                 ("outcome", ""), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped")):
                with self.subTest(i=i, field=field, value=value):
                    values = {**self.passing(), f"steps.test{i}.{field}": value,
                              f"steps.test{i}.conclusion": "success"}
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", output["passed"])
                    self.assertEqual("1", output["failed"])
                    self.assertEqual(str(int(i < 6)), output["core_failed"])
                    self.assertEqual("failure", output["overall_status"])
                    self.assertEqual("failing" if i < 6 else "passing", output["badge_status"])
        result, output = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", output["failed"])
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("0", output["skipped"])

    def test_only_successful_no_newer_candidate_skip_is_allowed(self):
        for decision in ("", "no_newer_stable_available", "not_configured",
                         "runtime_validation_not_automated", "not_applicable_package_manager"):
            for outcome in ("success", "", "failure", "skipped", "cancelled"):
                with self.subTest(decision=decision, outcome=outcome):
                    values = {**self.passing(), "steps.test6.outputs.status": "skipped",
                              "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome}
                    result, output = self.run_step("summary", values)
                    accepted = decision == "no_newer_stable_available" and outcome == "success"
                    self.assertEqual(accepted, result.returncode == 0)
                    self.assertEqual(str(int(accepted)), output["skipped"])
                    self.assertEqual(str(int(not accepted)), output["failed"])
        values = {"steps.test6.outputs.status": "skipped", "steps.test6.outcome": "success",
                  "steps.test6.outputs.decision": "no_newer_stable_available"}
        result, output = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("5", output["failed"])


if __name__ == "__main__":
    unittest.main()
