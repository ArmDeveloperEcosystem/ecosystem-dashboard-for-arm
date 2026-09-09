"""Focused checks for the package workflow's actual Bash steps."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-librecad.yml"


class LibrecadWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="librecad-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-librecad"]
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
        self.env["FIXTURE_WELCOME_DONE"] = str(self.root / "welcome-done")
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
  getwindowname)
    if [ "${FIXTURE_WELCOME:-0}" = 1 ] && [ ! -f "$FIXTURE_WELCOME_DONE" ]; then echo Welcome;
    else echo "${FIXTURE_WINDOW_TITLE:-LibreCAD}"; fi ;;
  getwindowpid) echo "${FIXTURE_WINDOW_PID:-$(cat "$FIXTURE_WINDOW_PID_FILE")}" ;;
  key)
    test "$*" = 'key --window 42 Return'
    if [ "${FIXTURE_STUCK_WELCOME:-0}" != 1 ]; then touch "$FIXTURE_WELCOME_DONE"; fi ;;
  *) exit 99 ;;
esac
''')
        self.stub("xprop", r'''
if [ -n "${FIXTURE_XPROP_DELAY:-}" ]; then sleep "$FIXTURE_XPROP_DELAY"; fi
echo "_NET_WM_PID(CARDINAL) = $(cat "$FIXTURE_WINDOW_PID_FILE")"
printf 'WM_CLASS(STRING) = "AppRun", "%s"\n' "${FIXTURE_WINDOW_CLASS:-LibreCAD}"
exit "${FIXTURE_XPROP_RC:-0}"
''')

    def runtime_fixture(self):
        self.window_fixture()
        self.stub("uname", 'echo "${FIXTURE_ARCH:-aarch64}"\n')
        self.stub("sudo", 'echo apt-diagnostic; exit "${FIXTURE_APT_RC:-0}"\n')
        self.stub("curl", r'''
if [ "${FIXTURE_CURL_RC:-0}" != 0 ]; then echo fetch-failed >&2; exit "$FIXTURE_CURL_RC"; fi
if [[ "$*" == *api.github.com* ]]; then
  printf '%s\n' '{"assets":[{"name":"LibreCAD-aarch64.AppImage","browser_download_url":"https://fixture.invalid/aarch64.AppImage"}]}'
  exit 0
fi
while [ "$1" != -o ]; do shift; done
cp "$FIXTURE_EXTRACTOR" "$2"
''')
        self.stub("file", r'''
arch=aarch64
if [[ "$1" == *.AppImage ]]; then arch="${FIXTURE_IMAGE_ARCH:-aarch64}";
else arch="${FIXTURE_BINARY_ARCH:-aarch64}"; fi
echo "$1: ELF 64-bit LSB pie executable, $arch"
''')
        self.stub("xvfb-run", r'''
test "$1" = -a
test "$2" = -s
test "$3" = '-screen 0 1280x1024x24 -nolisten tcp'
test "$QT_QPA_PLATFORM" = xcb
test "$QT_PLUGIN_PATH" = /usr/lib/aarch64-linux-gnu/qt5/plugins
test "$LD_LIBRARY_PATH" = /usr/lib/aarch64-linux-gnu
test -d "$XDG_RUNTIME_DIR"
shift 3
exec "$@"
''')
        self.stub("dbus-run-session", 'test "$1" = --\nshift\nexec "$@"\n')
        self.stub("fixture-app", r'''
if [ "${1:-}" = --help ]; then
  echo "${FIXTURE_HELP:-Usage: librecad dxf2svg}"
  exit "${FIXTURE_HELP_RC:-0}"
elif [ "${1:-}" = dxf2svg ]; then
  test "$2" = --version
  echo "LibreCAD v${FIXTURE_VERSION:-${LATEST_VERSION:-$BASELINE_VERSION}}"
else
  echo gui-diagnostic
  if [ "${FIXTURE_GUI_RC:-124}" != 124 ]; then exit "$FIXTURE_GUI_RC"; fi
  printf '%s\n' "$$" > "$FIXTURE_GUI_READY"
  sleep 30
fi
''')
        self.stub("fixture-extractor", r'''
test "$1" = --appimage-extract
mkdir -p squashfs-root/usr/bin
cp "$FIXTURE_APP" squashfs-root/usr/bin/librecad
ln -s usr/bin/librecad squashfs-root/AppRun
''')
        self.env.update(FIXTURE_EXTRACTOR=str(self.bin / "fixture-extractor"),
                        FIXTURE_APP=str(self.bin / "fixture-app"))

    def test_runtime_baseline_and_candidate_require_full_probe(self):
        self.runtime_fixture()
        result, output = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("2.2.1.1", output["installed_version"])
        self.assertTrue(output["duration"].isdigit())
        result, _ = self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"],
                                    LATEST_VERSION="2.2.1.5", CANDIDATE_TAG="v2.2.1.5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_runtime_waits_for_complete_window_proof_after_slow_xprop(self):
        self.runtime_fixture()
        for candidate in (False, True):
            with self.subTest(candidate=candidate):
                if candidate:
                    result, _ = self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"],
                                                LATEST_VERSION="2.2.1.5", CANDIDATE_TAG="v2.2.1.5",
                                                FIXTURE_XPROP_DELAY="1.25")
                else:
                    result, output = self.run_step("test5", FIXTURE_XPROP_DELAY="1.25")
                    self.assertEqual("passed", output.get("status"), result.stdout + result.stderr)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        proofs = list(self.root.rglob("window.txt"))
        self.assertEqual(2, len(proofs))
        for proof in proofs:
            self.assertRegex(proof.read_text(), r"(?m)^window_verified pid=\d+ id=42 title=LibreCAD$")

    def test_runtime_rejects_wrong_versions_architectures_help_and_gui_exits(self):
        self.runtime_fixture()
        cases = ({"FIXTURE_ARCH": "x86_64"}, {"FIXTURE_IMAGE_ARCH": "x86-64"},
                 {"FIXTURE_BINARY_ARCH": "x86-64"}, {"FIXTURE_VERSION": "2.2.1.9"},
                 {"FIXTURE_HELP": "unrelated program"}, {"FIXTURE_HELP_RC": "134"},
                 {"FIXTURE_GUI_RC": "0"}, {"FIXTURE_GUI_RC": "134"},
                 {"FIXTURE_GUI_RC": "137"}, {"FIXTURE_CURL_RC": "22"},
                 {"FIXTURE_APT_RC": "100"}, {"FIXTURE_NO_WINDOW": "1"},
                 {"FIXTURE_WINDOW_PID": "99999999"}, {"FIXTURE_WINDOW_TITLE": "unrelated"},
                 {"FIXTURE_XPROP_RC": "1"}, {"FIXTURE_WINDOW_CLASS": "unrelated"},
                 {"FIXTURE_WELCOME": "1", "FIXTURE_STUCK_WELCOME": "1"})
        for env in cases:
            with self.subTest(env=env):
                result, output = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertTrue(output["duration"].isdigit())
                self.assertNotIn("installed_version", output)
                result, _ = self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"],
                                            LATEST_VERSION="2.2.1.5", CANDIDATE_TAG="v2.2.1.5", **env)
                self.assertNotEqual(0, result.returncode)

    def test_runtime_failure_exposes_redirected_diagnostics(self):
        self.runtime_fixture()
        result, output = self.run_step("test5", FIXTURE_GUI_RC="134")
        self.assertEqual("failed", output["status"])
        self.assertIn("gui-diagnostic", result.stdout)
        self.assertIn("Diagnostic:", result.stdout)

    def test_first_run_dialog_must_open_the_owned_main_window(self):
        self.runtime_fixture()
        for candidate in (False, True):
            Path(self.env["FIXTURE_WELCOME_DONE"]).unlink(missing_ok=True)
            if candidate:
                result, _ = self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"],
                                            LATEST_VERSION="2.2.1.5", CANDIDATE_TAG="v2.2.1.5", FIXTURE_WELCOME="1")
            else:
                result, _ = self.run_step("test5", FIXTURE_WELCOME="1")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(Path(self.env["FIXTURE_WELCOME_DONE"]).exists())

    def test_late_failure_overrides_an_earlier_pass_output(self):
        result, output = self.run_step("test5", TEST5_COMMAND='echo status=passed >> "$GITHUB_OUTPUT"; exit 23')
        self.assertEqual(23, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertTrue(output["duration"].isdigit())

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
