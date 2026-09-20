"""Execute Flume's workflow shell/probe with controlled offline CLI producers."""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-Flume.yml"
BASELINE, CANDIDATE = "1.10.0", "1.10.1"


class FlumeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-flume"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.finalize = self.job["steps"][-1]["run"]
        temporary = tempfile.TemporaryDirectory(prefix="flume-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.addCleanup(self.cleanup_agents)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        for name in ("bash", "cat", "chmod", "date", "grep", "head", "mkdir", "mktemp",
                     "mv", "rm", "sed", "tar", "tr"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "python3").symlink_to(sys.executable)
        self.output = self.root / "output"
        self.env = {**os.environ, **self.job["env"], "PATH": str(self.bin),
                    "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(self.root),
                    "RUNNER_TEMP": str(self.root), "GITHUB_WORKSPACE": str(self.root),
                    "GITHUB_OUTPUT": str(self.output), "GITHUB_ENV": str(self.root / "env"),
                    "GITHUB_PATH": str(self.root / "path"),
                    "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
                    "FLUME_HOME": str(self.root / "flume"), "FLUME_INSTALL_STATUS": "success",
                    "FIXTURE_ROOT": str(self.root), "CLI_VERSION": "auto", "CLI_RC": "0",
                    "AGENT_MODE": "deliver", "HELP_RC": "0",
                    "SHUTDOWN_RC": "0", "SHUTDOWN_SIGNAL": "", "DEFAULT_TERM": "0",
                    "IGNORE_TERM": "0", "SPAWN_CHILD": "0", "LEADER_EXIT": "0"}
        self.values = {"steps.install.outcome": "success",
                       "steps.install.outputs.install_status": "success",
                       "steps.install.outputs.baseline_version": BASELINE,
                       "steps.install_state.outputs.install_status": "success",
                       "steps.version.outcome": "success", "steps.version.outputs.version": BASELINE,
                       "steps.summary.outcome": "success", "steps.summary.outputs.should_fail": "0",
                       "steps.summary.outputs.overall_status": "success"}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outcome"] = "success"
            self.values[f"steps.test{number}.outputs.status"] = "passed"
        self.values.update({"steps.test6.outputs.decision": "next_install_validated",
                            "steps.test6.outputs.current_version": BASELINE,
                            "steps.test6.outputs.latest_version": CANDIDATE,
                            "steps.test6.outputs.next_installed_version": CANDIDATE})
        self.write_stub(self.bin / "uname", "print('aarch64')\n")
        self.write_stub(self.bin / "timeout", """
import subprocess, sys
result = subprocess.run(sys.argv[2:], timeout=float(sys.argv[1]))
raise SystemExit(result.returncode)
""")
        apt = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        apt.parent.mkdir(parents=True)
        apt.write_text('exit "${APT_RC:-0}"\n')
        download = self.root / ".github/scripts/download-with-fallback.sh"
        download.parent.mkdir(parents=True)
        download.write_text('''set -euo pipefail
printf '%s\\n' "$@" >> "$FIXTURE_ROOT/download-calls"
if [ "${DOWNLOAD_RC:-0}" != 0 ]; then exit "$DOWNLOAD_RC"; fi
case "$2" in
  */1.10.0/*) archive=baseline ;;
  */1.10.1/*) archive=candidate ;;
  *) exit 92 ;;
esac
python3 -c 'import shutil,sys; shutil.copyfile(sys.argv[1], sys.argv[2])' "$FIXTURE_ROOT/$archive.tar.gz" "$1"
''')
        for version, archive in ((BASELINE, "baseline"), (CANDIDATE, "candidate")):
            home = self.root / f"apache-flume-{version}-bin"
            (home / "bin").mkdir(parents=True)
            (home / "conf").mkdir()
            (home / "lib").mkdir()
            (home / "lib" / f"flume-ng-core-{version}.jar").touch()
            self.write_stub(home / "bin/flume-ng", r'''
import os
from pathlib import Path
import signal
import sys
import time
root = Path(os.environ['FIXTURE_ROOT'])
with (root / 'cli-calls').open('a') as log:
    log.write(str(Path(__file__).resolve()) + ' ' + ' '.join(sys.argv[1:]) + '\n')
mode = sys.argv[1]
if mode == 'version':
    version = os.environ['CLI_VERSION']
    if version == 'auto':
        version = '1.10.1' if '1.10.1' in __file__ else '1.10.0'
    if version:
        print('Flume ' + version)
    sys.exit(int(os.environ['CLI_RC']))
if mode == 'help':
    print('Usage: flume-ng help')
    sys.exit(int(os.environ['HELP_RC']))
assert mode == 'agent'
(root / 'agent-group').write_text(str(os.getpgrp()))
assert sys.argv[sys.argv.index('--name') + 1] == 'smoke'
config = Path(sys.argv[sys.argv.index('--conf-file') + 1])
props = dict(line.split(' = ', 1) for line in config.read_text().splitlines())
assert props['smoke.sources.source.type'] == 'spooldir'
assert props['smoke.channels.channel.type'] == 'memory'
assert props['smoke.sinks.sink.type'] == 'file_roll'
assert not any('port' in key for key in props)
spool = Path(props['smoke.sources.source.spoolDir'])
sink = Path(props['smoke.sinks.sink.sink.directory'])
mode = os.environ['AGENT_MODE']
if mode == 'exit':
    sys.exit(1)
if mode == 'no-event':
    sys.exit(0)
if mode in ('wrong-event', 'uncommitted'):
    data = (spool / 'event.txt').read_bytes()
    (sink / 'result').write_bytes(b'wrong-event\n' if mode == 'wrong-event' else data)
    if mode != 'uncommitted':
        (spool / 'event.txt').rename(spool / 'event.txt.COMPLETED')
    sys.exit(0)
if os.environ['SPAWN_CHILD'] == '1':
    child = os.fork()
    if child == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        (root / 'agent-child-pid').write_text(str(os.getpid()))
        while True:
            time.sleep(0.05)
    while not (root / 'agent-child-pid').exists():
        time.sleep(0.005)
    if os.environ['LEADER_EXIT'] == '1':
        print('fixture leader exited before cleanup', flush=True)
        sys.exit(0)
(root / 'agent-pid').write_text(str(os.getpid()))
def stop(signum, frame):
    (root / 'agent-stopped').write_text(str(signum))
    print('fixture shutdown exit ' + os.environ['SHUTDOWN_RC'], file=sys.stderr, flush=True)
    if os.environ['SHUTDOWN_SIGNAL']:
        os.kill(os.getpid(), getattr(signal, os.environ['SHUTDOWN_SIGNAL']))
    sys.exit(int(os.environ['SHUTDOWN_RC']))
signal.signal(signal.SIGTERM, signal.SIG_IGN if os.environ['IGNORE_TERM'] == '1' else
              signal.SIG_DFL if os.environ['DEFAULT_TERM'] == '1' else stop)
print('fixture agent ready', flush=True)
if mode == 'deliver':
    (sink / 'result').write_bytes((spool / 'event.txt').read_bytes())
    (spool / 'event.txt').rename(spool / 'event.txt.COMPLETED')
while True:
    time.sleep(0.05)
''')
            with tarfile.open(self.root / f"{archive}.tar.gz", "w:gz") as package:
                package.add(home, arcname=home.name)
        shutil.copytree(self.root / f"apache-flume-{BASELINE}-bin", self.root / "flume")
        result, _ = self.shell(self.steps["probe"]["run"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def write_stub(self, path, source):
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def cleanup_agents(self):
        group_file = self.root / "agent-group"
        if not group_file.exists():
            return
        group = int(group_file.read_text())
        for name in ("agent-pid", "agent-child-pid"):
            path = self.root / name
            if path.exists():
                try:
                    if os.getpgid(int(path.read_text())) == group:
                        os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def assert_owned_agents_gone(self):
        for name in ("agent-pid", "agent-child-pid"):
            path = self.root / name
            if path.exists():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(path.read_text()), 0)
        with self.assertRaises(ProcessLookupError):
            os.killpg(int((self.root / "agent-group").read_text()), 0)

    def expression(self, source, values):
        def atom(term):
            term = term.strip()
            if " == " in term:
                a, b = term.split(" == ", 1)
                return atom(a) == atom(b)
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            return values.get(term, "")

        for alternative in source.split("||"):
            value = True
            for term in alternative.split("&&"):
                value = atom(term) if value else value
            if value:
                return str(value)
        return ""

    def render(self, source, values=None):
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}",
                      lambda m: self.expression(m[1], {**self.values, **(values or {})}), source)

    def shell(self, source, values=None, **environment):
        self.output.write_text("")
        process = subprocess.run([self.bash, "-euo", "pipefail", "-c", self.render(source, values)],
                                 cwd=self.root, env={**self.env, **environment},
                                 capture_output=True, text=True, timeout=25)
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "duplicate workflow output")
        return process, dict(pairs)

    def step(self, name, values=None, **environment):
        return self.shell(self.steps[name]["run"], values, **environment)

    def emit(self, values=None):
        action = yaml.safe_load((ROOT / ".github/actions/emit-package-result/action.yml").read_text())
        inputs = {key: value.get("default", "") for key, value in action["inputs"].items()}
        inputs.update({key: self.render(value, values) for key, value in self.steps["summary"]["with"].items()})
        emitter = action["runs"]["steps"][0]
        environment = {key: inputs[value.removeprefix("${{ inputs.").removesuffix(" }}")]
                       for key, value in emitter["env"].items()}
        return self.shell(emitter["run"], **environment)

    def collect(self, summary, conclusions, *, baseline_failed=False):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        directory = self.root / "collector"
        (directory / ".github").mkdir(parents=True, exist_ok=True)
        if not (directory / ".github/scripts").exists():
            (directory / ".github/scripts").symlink_to(ROOT / ".github/scripts")
        failure = "failure" in conclusions
        outputs = {"contract_version": "2.0", "package_slug": "Flume", "package_name": "Flume",
                   "package_version": "unknown" if baseline_failed else BASELINE,
                   "job_name": "test-flume", "run_status": summary["overall_status"],
                   "tests_passed": summary["passed"], "tests_failed": summary["failed"],
                   "tests_skipped": summary["skipped"], "core_failed": summary["core_failed"],
                   "regression_status": "skipped" if baseline_failed else "passed",
                   "regression_decision": "baseline_failed" if baseline_failed else "next_install_validated",
                   "regression_current_version": "unknown" if baseline_failed else BASELINE,
                   "regression_latest_version": CANDIDATE,
                   "regression_next_installed_version": "not_installed" if baseline_failed else CANDIDATE}
        job = {"id": 456, "name": "test-flume / test-flume", "conclusion": "failure" if failure else "success",
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{n}"]["name"], "number": n, "conclusion": state}
                         for n, state in enumerate(conclusions, 1)]}
        environment = {**self.env, "NEEDS_JSON": json.dumps({"test-flume": {
            "result": job["conclusion"], "outputs": outputs}}), "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
            "BATCH_NUMBER": "6", "BATCH_TITLE": "Batch 6", "GH_TOKEN": "",
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        process = subprocess.run([sys.executable, "-B", "-c", source], cwd=directory, env=environment,
                                 capture_output=True, text=True, timeout=15)
        results = list(directory.glob("test-results/*/*.json"))
        return process, [json.loads(path.read_text()) for path in results]

    def test_pins_exact_case_runner_and_real_api_failure_steps(self):
        self.assertEqual(self.job["env"]["FLUME_BASELINE_VERSION"], BASELINE)
        self.assertEqual(self.job["env"]["FLUME_NEXT_VERSION"], CANDIDATE)
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        for n in range(1, 7):
            self.assertNotIn("continue-on-error", self.steps[f"test{n}"])
        for name in ("version", "test2", "test3", "test4", "test5"):
            self.assertEqual(self.steps[name]["if"],
                             "always() && steps.install_state.outputs.install_status == 'success'")
        self.assertEqual(self.steps["test1"]["if"], "always()")

    def test_install_success_and_resolver_require_successful_step_and_layout(self):
        shutil.rmtree(self.root / "flume")
        shutil.rmtree(self.root / f"apache-flume-{BASELINE}-bin")
        result, output = self.step("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["install_status"], "success")
        result, output = self.step("install_state")
        self.assertEqual(output["install_status"], "success")
        for values in ({"steps.install.outcome": "failure"},
                       {"steps.install.outputs.install_status": "failed"}):
            result, output = self.step("install_state", values)
            self.assertEqual(output["install_status"], "failed", "leftover binary cannot override failure")

    def test_download_failure_is_nonzero_and_test1_fails_instead_of_skipping(self):
        result, output = self.step("install", DOWNLOAD_RC="28")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["install_status"], "failed")
        self.assertEqual(output["install_blocker"], "download_failed")
        result, output = self.step("test1", FLUME_INSTALL_STATUS="failed", FLUME_INSTALL_BLOCKER="download_failed")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")

    def test_corrupt_baseline_archive_fails(self):
        (self.root / "baseline.tar.gz").write_text("not a tarball")
        result, output = self.step("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["install_blocker"], "extract_failed")

    def test_failed_install_resolution_does_not_infer_success_from_step_conclusion(self):
        shutil.rmtree(self.root / "flume")
        result, output = self.step("install_state", {"steps.install.outputs.install_status": "",
                                                     "steps.install.outcome": "failure"})
        self.assertEqual(output["install_status"], "failed")

    def test_observed_baseline_version_and_test2_pass(self):
        result, output = self.step("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"version": BASELINE})
        result, output = self.step("test2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["status"], "passed")

    def test_version_output_cannot_hide_nonzero_empty_or_mismatch(self):
        for version, code in ((BASELINE, "1"), ("", "0"), (CANDIDATE, "0"), (BASELINE + "0", "0")):
            for step in ("version", "test2"):
                with self.subTest(step=step, version=version, code=code):
                    result, output = self.step(step, CLI_VERSION=version, CLI_RC=code)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.get("version", output.get("status")),
                                     "unknown" if step == "version" else "failed")

    def test_help_requires_real_zero_exit_even_with_matching_output(self):
        for code in ("0", "1"):
            result, output = self.step("test3", HELP_RC=code)
            self.assertEqual(result.returncode, int(code), result.stderr)
            self.assertEqual(output["status"], "passed" if code == "0" else "failed")

    def test_test2_cannot_erase_a_failed_version_prerequisite(self):
        result, output = self.step("test2", {"steps.version.outcome": "failure"})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertFalse((self.root / "cli-calls").exists())

    def test_event_delivery_positive_and_owned_process_cleanup(self):
        result, output = self.step("test5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["status"], "passed")
        self.assertIn("spool source -> memory channel -> file sink delivered flume-smoke-", result.stdout)
        self.assertTrue((self.root / "agent-stopped").exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.root / "agent-pid").read_text()), 0)
        self.assertFalse(list(self.root.glob("flume-smoke-*/")))

    def test_expected_owned_sigterm_returns_pass(self):
        for environment in ({"SHUTDOWN_RC": "0"}, {"SHUTDOWN_RC": "143"}, {"DEFAULT_TERM": "1"}):
            with self.subTest(environment=environment):
                result, output = self.step("test5", **environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output["status"], "passed")
                self.assertIn("delivered flume-smoke-", result.stdout)
                self.assert_owned_agents_gone()

    def test_delivered_event_cannot_hide_unexpected_shutdown_exit_or_signal(self):
        for step in ("test5", "test6"):
            for environment in ({"SHUTDOWN_RC": "23"}, {"SHUTDOWN_SIGNAL": "SIGUSR1"}):
                with self.subTest(step=step, environment=environment):
                    result, output = self.step(step, **environment)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output["status"], "failed")
                    self.assertIn("shutdown returned unexpected exit", result.stderr)
                    self.assertIn("fixture shutdown exit", result.stderr)
                    self.assertNotIn("delivered flume-smoke-", result.stdout)
                    self.assert_owned_agents_gone()

    def test_forced_leader_shutdown_fails_and_preserves_log(self):
        result, output = self.step("test5", IGNORE_TERM="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertIn("required forced shutdown", result.stderr)
        self.assertIn("fixture agent ready", result.stderr)
        self.assertNotIn("delivered flume-smoke-", result.stdout)
        self.assert_owned_agents_gone()

    def test_live_descendant_cannot_survive_successful_leader_shutdown(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     start_new_session=True)
        try:
            result, output = self.step("test5", SPAWN_CHILD="1")
            self.assertIsNone(unrelated.poll(), "Cleanup must not target a different process group")
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertIn("forced shutdown", result.stderr)
        self.assertIn("fixture shutdown exit 0", result.stderr)
        self.assertNotIn("delivered flume-smoke-", result.stdout)
        self.assert_owned_agents_gone()

    def test_owned_group_is_cleaned_when_leader_already_exited(self):
        result, output = self.step("test5", SPAWN_CHILD="1", LEADER_EXIT="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertIn("forced shutdown", result.stderr)
        self.assertIn("fixture leader exited before cleanup", result.stderr)
        self.assertNotIn("delivered flume-smoke-", result.stdout)
        self.assert_owned_agents_gone()

    def test_group_permission_uncertainty_is_bounded_and_never_assumed_empty(self):
        driver = """import errno, os, runpy, sys, time
from unittest.mock import patch
real_killpg, real_clock = os.killpg, time.monotonic
start, checks = real_clock(), 0
persistent = sys.argv[3] == 'persistent'
def killpg(pid, sig):
    global checks
    if sig == 0:
        checks += 1
        if persistent or checks == 1:
            raise PermissionError(errno.EPERM, 'fixture uncertain group state')
    return real_killpg(pid, sig)
with patch('os.killpg', side_effect=killpg), patch('time.monotonic', side_effect=lambda: start + (real_clock() - start) * 20):
    sys.argv = [sys.argv[1], 'event', sys.argv[2], '1.10.0']
    runpy.run_path(sys.argv[0], run_name='__main__')
"""
        for mode in ("transient", "persistent"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, "-c", driver, str(self.root / "flume-smoke.py"),
                     self.env["FLUME_HOME"], mode], env=self.env,
                    capture_output=True, text=True, timeout=15,
                )
                if mode == "transient":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("delivered flume-smoke-", result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("remained after forced shutdown", result.stderr)
                    self.assertNotIn("delivered flume-smoke-", result.stdout)
                self.assert_owned_agents_gone()

    def test_directory_or_startup_alone_is_not_functional_success(self):
        for mode in ("exit", "no-event", "wrong-event", "uncommitted"):
            with self.subTest(mode=mode):
                result, output = self.step("test5", AGENT_MODE=mode)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(output["status"], "failed")
                self.assertNotIn("delivered flume-smoke-", result.stdout)

    def test_stalled_agent_hits_deadline_and_cleans_owned_process(self):
        probe = self.root / "flume-smoke.py"
        driver = """import runpy, sys, time
from unittest.mock import patch
real = time.monotonic
start = real()
with patch('time.monotonic', side_effect=lambda: start + (real() - start) * 100):
    sys.argv = [sys.argv[1], 'event', sys.argv[2], '1.10.0']
    runpy.run_path(sys.argv[0], run_name='__main__')
"""
        process = subprocess.run([sys.executable, "-c", driver, str(probe), self.env["FLUME_HOME"]],
                                 env={**self.env, "AGENT_MODE": "stall"}, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("did not deliver and commit", process.stderr)
        self.assertTrue((self.root / "agent-stopped").exists())

    def test_candidate_exact_cli_and_event_pass_with_no_baseline_pass_claim(self):
        result, output = self.step("test6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["status"], "passed")
        self.assertEqual(output["decision"], "next_install_validated")
        self.assertEqual(output["next_installed_version"], CANDIDATE)
        self.assertNotIn("passed smoke", output["comparison"])
        self.assertIn("spool source -> memory channel -> file sink delivered", result.stdout)
        self.assertFalse(list(self.root.glob("flume-next-*")))

    def test_candidate_versioned_jar_cannot_rescue_bad_command(self):
        for version, code in ((CANDIDATE, "1"), ("", "0"), (BASELINE, "0")):
            with self.subTest(version=version, code=code):
                result, output = self.step("test6", CLI_VERSION=version, CLI_RC=code)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(output["status"], "failed")
                self.assertEqual(output["decision"], "next_install_failed")
                self.assertNotEqual(output["next_installed_version"], CANDIDATE)

    def test_candidate_runtime_failure_is_failed_not_deferred(self):
        result, output = self.step("test6", AGENT_MODE="no-event")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertEqual(output["decision"], "next_install_failed")
        self.assertEqual(output["next_installed_version"], CANDIDATE, "version was actually observed before runtime failed")

    def test_candidate_download_and_extract_failures_emit_failed_result(self):
        for mode in ("download", "extract"):
            with self.subTest(mode=mode):
                if mode == "extract":
                    (self.root / "candidate.tar.gz").write_text("broken")
                result, output = self.step("test6", DOWNLOAD_RC="28" if mode == "download" else "0")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(output["decision"], "next_install_failed")
                self.assertEqual(output["status"], "failed")
                self.assertFalse(list(self.root.glob("flume-next-*")))

    def test_baseline_failure_never_attempts_candidate_or_fabricates_observed_version(self):
        result, output = self.step("test6", {"steps.install_state.outputs.install_status": "failed",
                                             "steps.version.outputs.version": ""})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["decision"], "baseline_failed")
        self.assertEqual(output["current_version"], "unknown")
        self.assertFalse((self.root / "download-calls").exists())

    def test_finalize_accepts_only_complete_numeric_success(self):
        result, _ = self.shell(self.finalize)
        self.assertEqual(result.returncode, 0)
        for key, value in (("steps.summary.outputs.should_fail", "1"),
                           ("steps.summary.outputs.should_fail", ""),
                           ("steps.summary.outputs.should_fail", "true"),
                           ("steps.summary.outputs.overall_status", "failure"),
                           ("steps.summary.outcome", "failure"),
                           ("steps.version.outcome", "failure")):
            with self.subTest(key=key, value=value):
                result, _ = self.shell(self.finalize, {key: value})
                self.assertEqual(result.returncode, 1)

    def test_unexpected_failed_step_outcome_overrides_passed_output_in_real_emitter(self):
        for number in range(1, 7):
            with self.subTest(step=number):
                result, output = self.emit({f"steps.test{number}.outcome": "failure"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output["should_fail"], "1")
                self.assertEqual(output["failed"], "1")
                self.assertEqual(output["overall_status"], "failure")

    def test_missing_outputs_cannot_be_inferred_as_passing_from_step_success(self):
        for number in range(1, 7):
            with self.subTest(step=number):
                result, output = self.emit({f"steps.test{number}.outputs.status": ""})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output["should_fail"], "1")
                self.assertEqual(output["failed"], "1")

    def test_all_six_real_step_scripts_feed_successful_emitter_and_collector(self):
        values = {}
        version_result, version = self.step("version")
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        values["steps.version.outputs.version"] = version["version"]
        for number in range(1, 7):
            result, output = self.step(f"test{number}", values)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output["status"], "passed")
            values.update({f"steps.test{number}.outputs.{key}": value for key, value in output.items()})
        result, summary = self.emit(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), ("6", "0", "0"))
        result, payloads = self.collect(summary, ["success"] * 6)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payloads[0]["tests"]["passed"], 6)

    def test_real_emitter_and_collector_accept_six_passing_checks(self):
        result, summary = self.emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), ("6", "0", "0"))
        result, payloads = self.collect(summary, ["success"] * 6)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["tests"]["failed"], 0)

    def test_original_collector_mismatch_fixed_without_weakening_collector(self):
        values = {"steps.install_state.outputs.install_status": "failed",
                  "steps.test1.outcome": "failure", "steps.test1.outputs.status": "failed",
                  "steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "baseline_failed"}
        for n in range(2, 6):
            values[f"steps.test{n}.outcome"] = "skipped"
            values[f"steps.test{n}.outputs.status"] = ""
        result, summary = self.emit(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"], summary["core_failed"]),
                         ("0", "1", "5", "1"))
        result, payloads = self.collect(summary, ["failure"] + ["skipped"] * 4 + ["success"], baseline_failed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["tests"]["failed"], 1)
        self.assertEqual(payloads[0]["tests"]["skipped"], 5)
        # The old all-success API path must still be rejected by the unchanged collector.
        result, _ = self.collect(summary, ["success"] * 6, baseline_failed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("emitted failure counts contradict", result.stderr)


if __name__ == "__main__":
    unittest.main()
