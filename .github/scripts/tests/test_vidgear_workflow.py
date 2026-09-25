"""VidGear shell failures and opt-in native fault injection against the exact YAML probe.

Run native cases with --native-probes BASELINE_PYTHON CANDIDATE_PYTHON after
installing the two pinned wheels. These cases use real CamGear/WriteGear and
OpenCV, patching one observable failure at a time around their real operations.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit
from package_result_policy import (
    BASELINE_REGRESSION_DECISIONS, FAILED_REGRESSION_DECISIONS,
    PASSED_REGRESSION_DECISIONS, expected_regression_metadata, validate_publishable_result,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-vidgear.yml"


class VidGearWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-vidgear"]
        self.steps = {step.get("id", step["name"]): step for step in self.job["steps"]}
        temporary = tempfile.TemporaryDirectory(prefix="vidgear-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.workdir = self.root / "vidgear.test"
        self.workdir.mkdir()
        self.executable("python", 'exec ' + shlex.quote(sys.executable) + ' "$@"\n')

    def executable(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script)
        path.chmod(0o755)
        return path

    def run_step(self, name, values=None, **environment):
        defaults = {f"steps.test{number}.{key}": value for number in range(1, 6)
                    for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values = {**defaults, "steps.version.outputs.version": "0.1.0",
                  "steps.install.outputs.install_status": "success", **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = self.root / "outputs"
        output.write_text("")
        env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(output),
                   GITHUB_ENV=str(self.root / "environment"), RUNNER_TEMP=str(self.root),
                   VIDGEAR_SOURCE=str(self.workdir / "baseline-src"),
                   VIDGEAR_WORK_DIR=str(self.workdir), VIDGEAR_PYTHON=str(self.bin / "installed-python"),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        env.update(environment)
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], env=env,
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, fields

    def assert_failed(self, result, fields, code=None):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        if code is not None:
            self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(fields["status"], "failed")
        self.assertTrue(fields["duration"].isdigit(), fields)

    def test_approved_versions_and_historical_commits_are_fixed(self):
        self.assertEqual(self.job["env"]["BASELINE_VERSION"], "0.1.0")
        self.assertEqual(self.job["env"]["BASELINE_TAG"], "videgear-0.1.0")
        self.assertEqual(self.job["env"]["BASELINE_COMMIT"], "5e0d04b657e66e25a781aeb8c63e8149b7069eeb")
        self.assertEqual(self.job["env"]["NEXT_VERSION"], "0.3.4")
        self.assertEqual(self.job["env"]["NEXT_TAG"], "vidgear-0.3.4")
        self.assertEqual(self.job["env"]["NEXT_COMMIT"], "84d99c314bb56ab9891fc531222120c18297886c")

    def test_same_probe_is_executed_for_both_versions_and_scope_is_explicit(self):
        for name in ("test5", "test6"):
            self.assertIn(' -I -c "$VIDGEAR_RUNTIME_PROBE"', self.steps[name]["run"])
            self.assertIn("no writer parity or all-frames streaming delivery claim", self.steps[name]["run"])
        self.assertIn("CHECK_WRITER=0", self.steps["test5"]["run"])
        self.assertIn("CHECK_WRITER=1", self.steps["test6"]["run"])
        compile(self.job["env"]["VIDGEAR_RUNTIME_PROBE"], "workflow-probe", "exec")

    def test_all_test_outputs_are_visible_to_the_unchanged_source_auditor(self):
        for number in range(1, 7):
            for field in ("status", "duration"):
                with self.subTest(number=number, field=field):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[f"test{number}"], field))

    def test_literal_decision_pairs_agree_with_existing_policy(self):
        pairs = set(audit._step_literal_pairs(ROOT, self.steps["test6"]))
        self.assertEqual(pairs, {("baseline_failed", "skipped"),
                                 ("next_install_failed", "failed"), ("next_install_validated", "passed")})
        for decision, status in pairs:
            expected = expected_regression_metadata(decision=decision,
                core_failed=1 if decision in BASELINE_REGRESSION_DECISIONS else 0)
            self.assertEqual(expected["status"], status)

    def test_each_bad_baseline_status_or_outcome_prevents_candidate_work(self):
        self.executable("git", 'echo unexpected > candidate-ran\nexit 99\n')
        invalid = [("outputs.status", value) for value in ("", "failed", "skipped", "unknown")]
        invalid += [("outcome", value) for value in ("", "failure", "skipped", "cancelled")]
        for number in range(1, 6):
            for field, value in invalid:
                with self.subTest(number=number, field=field, value=value):
                    result, fields = self.run_step("test6", {f"steps.test{number}.{field}": value})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(fields["decision"], BASELINE_REGRESSION_DECISIONS)
                    self.assertEqual(fields["status"], expected_regression_metadata(
                        decision=fields["decision"], core_failed=1)["status"])
                    self.assertEqual(fields["next_installed_version"], "not_installed")
                    self.assertTrue(fields["duration"].isdigit())
                    self.assertFalse((self.root / "candidate-ran").exists())

    def collect_baseline_guard(self, api_candidate_conclusion="success"):
        overrides = {"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"}
        candidate, candidate_fields = self.run_step("test6", overrides)
        self.assertEqual(candidate.returncode, 0, candidate.stderr)
        overrides.update({f"steps.test6.outputs.{key}": value for key, value in candidate_fields.items()})
        overrides["steps.test6.outcome"] = "success"
        summary, summary_fields = self.run_step("summary", overrides)
        self.assertEqual(summary.returncode, 1, summary.stderr)
        self.assertEqual(tuple(summary_fields[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status")),
                         ("4", "1", "1", "1", "failure"))

        context = {**overrides, **{f"steps.summary.outputs.{key}": value for key, value in summary_fields.items()},
                   "steps.metadata.outputs.package_slug": "vidgear", "steps.version.outputs.version": "0.1.0",
                   "steps.metadata.outputs.timestamp": "2026-09-09T00:00:00Z", "github.run_id": "123",
                   "github.run_attempt": "1", "github.job": "test-vidgear"}
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else context.get(term, "")
                if value:
                    return value
            return ""
        outputs = {key: re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, str(value))
                   for key, value in self.job["outputs"].items()}
        needs = {"test-vidgear": {"result": "failure", "outputs": outputs}}
        job = {"id": 456, "name": "test-vidgear / test-vidgear", "conclusion": "failure",
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{number}"]["name"], "number": number,
                          "conclusion": "failure" if number == 5 else api_candidate_conclusion if number == 6 else "success"}
                         for number in range(1, 7)]}
        collector = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = collector["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        directory = self.root / "collector"
        (directory / ".github").mkdir(parents=True)
        (directory / ".github/scripts").symlink_to(ROOT / ".github/scripts")
        environment = dict(os.environ, NEEDS_JSON=json.dumps(needs), RUN_JOBS_JSON=json.dumps({"jobs": [job]}),
            BATCH_NUMBER="1", BATCH_TITLE="Batch 1", GH_TOKEN="", GITHUB_SERVER_URL="https://github.com",
            GITHUB_API_URL="https://api.github.com", GITHUB_REPOSITORY="example/project",
            GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", GITHUB_OUTPUT=str(directory / "outputs"),
            GITHUB_STEP_SUMMARY=str(directory / "summary"))
        result = subprocess.run([sys.executable, "-B", "-c", source], cwd=directory, env=environment,
                                capture_output=True, text=True, timeout=30)
        path = directory / "test-results/vidgear-test-results/vidgear.json"
        return result, json.loads(path.read_text()) if path.exists() else None

    def test_actual_guard_and_summary_collect_as_four_pass_one_fail_one_skip(self):
        result, payload = self.collect_baseline_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(tuple(payload["tests"][key] for key in ("passed", "failed", "skipped")), (4, 1, 1))
        self.assertEqual([detail["status"] for detail in payload["tests"]["details"]],
                         ["passed"] * 4 + ["failed", "skipped"])
        self.assertEqual(validate_publishable_result(payload), "failure")

    def test_collector_rejects_the_previous_failing_api_guard(self):
        result, payload = self.collect_baseline_guard(api_candidate_conclusion="failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("emitted skipped count contradicts test details", result.stderr)
        self.assertIsNone(payload)

    def test_missing_installed_version_never_reports_requested_version(self):
        result, fields = self.run_step("version")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("version", fields)

    def test_wrong_or_empty_installed_version_fails_version_and_test2(self):
        for version in ("", "0.1.00", "0.1.1", "0.3.4", "unknown"):
            with self.subTest(version=version):
                self.executable("installed-python", f"printf '%s\\n' {shlex.quote(version)}\n")
                result, fields = self.run_step("version")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("version", fields)
                result, fields = self.run_step("test2")
                self.assert_failed(result, fields)

    def test_baseline_clone_failure_propagates_without_fallback(self):
        self.executable("timeout", 'shift\nexec "$@"\n')
        self.executable("git", 'printf "%s\\n" "$*" >> git-calls\nexit 37\n')
        result, fields = self.run_step("install")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(fields["install_status"], "failed")
        calls = (self.root / "git-calls").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn("--branch videgear-0.1.0", calls[0])
        self.assertNotIn("default_branch", self.steps["install"]["run"])
        self.assertNotIn("external_artifact", self.steps["install"]["run"])

    def test_wrong_source_commit_fails_before_package_install(self):
        self.executable("timeout", 'shift\nexec "$@"\n')
        self.executable("git", 'if [ "$1" = clone ]; then exit 0; fi\necho wrong-commit\n')
        result, fields = self.run_step("install")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(fields["install_status"], "failed")

    def test_candidate_source_comparison_allows_only_newline_differences(self):
        script = self.steps["test6"]["run"].split('"$NEXT_SOURCE" <<\'PY\'\n', 1)[1].split("\nPY", 1)[0]
        source = self.root / "source"
        wheel = self.root / "wheel"
        for directory in (source, wheel):
            (directory / "vidgear/gears").mkdir(parents=True)
        distribution = SimpleNamespace(locate_file=lambda path: wheel / path)
        with patch("importlib.metadata.distribution", return_value=distribution), patch.object(sys, "argv", ["-", str(source)]):
            for module in ("camgear.py", "writegear.py"):
                (source / "vidgear/gears" / module).write_bytes(b"def read():\n    return 1\n")
                (wheel / "vidgear/gears" / module).write_bytes(b"def read():\r\n    return 1\r\n")
            exec(compile(script, "candidate-source-check", "exec"), {})
            changed = wheel / "vidgear/gears/camgear.py"
            changed.write_bytes(b"def read():\r\n    return 2\r\n")
            with self.assertRaises(AssertionError):
                exec(compile(script, "candidate-source-check", "exec"), {})
            changed.unlink()
            with self.assertRaises(FileNotFoundError):
                exec(compile(script, "candidate-source-check", "exec"), {})

    def test_each_core_command_failure_emits_status_duration_and_nonzero_exit(self):
        self.executable("git", "exit 37\n")
        self.executable("installed-python", "exit 37\n")
        self.executable("grep", "exit 37\n")
        self.executable("uname", "exit 37\n")
        self.executable("timeout", 'shift 2\nexec "$@"\n')
        for number in range(1, 6):
            with self.subTest(number=number):
                result, fields = self.run_step(f"test{number}")
                self.assert_failed(result, fields)

    def test_timeout_failure_remains_failure(self):
        self.executable("timeout", "exit 124\n")
        result, fields = self.run_step("test5")
        self.assert_failed(result, fields, 124)

    def test_candidate_must_be_a_newer_numeric_release(self):
        for current, candidate in (("0.3.4", "0.3.4"), ("0.3.5", "0.3.4"),
                                   ("unknown", "0.3.4"), ("0.1.0", ""), ("0.1.0", "0.3.4rc1")):
            with self.subTest(current=current, candidate=candidate):
                result, fields = self.run_step("test6", {"steps.version.outputs.version": current},
                                               NEXT_VERSION=candidate)
                self.assert_failed(result, fields)
                self.assertEqual(fields["decision"], "next_install_failed")
                self.assertEqual(fields["next_installed_version"], "not_installed")

    def test_candidate_clone_failure_is_not_a_successful_composite_action(self):
        self.executable("timeout", 'shift\nexec "$@"\n')
        self.executable("git", "exit 37\n")
        result, fields = self.run_step("test6")
        self.assert_failed(result, fields, 37)
        self.assertEqual(fields["decision"], "next_install_failed")
        self.assertIn(fields["decision"], FAILED_REGRESSION_DECISIONS)
        self.assertEqual(fields["status"], expected_regression_metadata(
            decision=fields["decision"], core_failed=0)["status"])
        self.assertEqual(fields["next_installed_version"], "not_installed")

    def test_candidate_wrong_installed_version_is_reported_but_cannot_pass(self):
        self.executable("timeout", 'shift\nexec "$@"\n')
        self.executable("git", 'if [ "$1" = clone ]; then exit 0; fi\nprintf "%s\\n" "$NEXT_COMMIT"\n')
        self.executable("python", 'if [ "$1" = -m ] && [ "$2" = venv ]; then\n'
                        '  mkdir -p "$3/bin"\n  cp "' + str(self.bin / "candidate-python") + '" "$3/bin/python"\n'
                        'else\n  exec ' + shlex.quote(sys.executable) + ' "$@"\nfi\n')
        for version in ("", "0.1.0", "0.3.40", "unknown"):
            with self.subTest(version=version):
                self.executable("candidate-python", 'if [ "$1" = -m ]; then exit 0; fi\n'
                                + f"printf '%s\\n' {shlex.quote(version)}\n")
                result, fields = self.run_step("test6")
                self.assert_failed(result, fields)
                self.assertEqual(fields["next_installed_version"], version)
                self.assertEqual(fields["decision"], "next_install_failed")

    def test_actual_success_and_probe_failure_outputs_match_policy(self):
        self.executable("timeout", 'if [ "$1" = --kill-after=5s ]; then shift; fi\nshift\nexec "$@"\n')
        self.executable("git", 'if [ "$1" = clone ]; then exit 0; fi\nprintf "%s\\n" "$NEXT_COMMIT"\n')
        self.executable("python", 'if [ "$1" = -m ] && [ "$2" = venv ]; then\n'
                        '  mkdir -p "$3/bin"\n  cp "' + str(self.bin / "candidate-python") + '" "$3/bin/python"\n'
                        'else\n  exec ' + shlex.quote(sys.executable) + ' "$@"\nfi\n')
        for code in (0, 37):
            self.executable("candidate-python", 'if [ "$1" = -m ]; then exit 0; fi\n'
                            'if [ "$2" = -c ]; then\n'
                            '  if [ "$3" = ' + shlex.quote('import importlib.metadata; print(importlib.metadata.version("vidgear"))') + ' ]; then\n'
                            '    echo 0.3.4\n  else\n    exit ' + str(code) + '\n  fi\nfi\n')
            result, fields = self.run_step("test6")
            self.assertEqual(result.returncode, code, result.stderr)
            group = FAILED_REGRESSION_DECISIONS if code else PASSED_REGRESSION_DECISIONS
            self.assertIn(fields["decision"], group)
            self.assertEqual(fields["status"], expected_regression_metadata(
                decision=fields["decision"], core_failed=0)["status"])
            self.assertEqual(fields["next_installed_version"], "0.3.4")
            self.assertTrue(fields["duration"].isdigit())

    def test_cleanup_only_removes_the_owned_temporary_directory(self):
        outside = self.root / "unrelated"
        outside.mkdir()
        result, _ = self.run_step("Clean VidGear temporary environments", VIDGEAR_WORK_DIR=str(outside))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(outside.exists())
        result, _ = self.run_step("Clean VidGear temporary environments")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workdir.exists())
        self.assertTrue(outside.exists())


NATIVE_HARNESS = r'''
from contextlib import ExitStack
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from vidgear.gears import CamGear

request = json.load(sys.stdin)
fault = request["fault"]
os.environ.update(EXPECTED_VERSION=request["version"], CHECK_WRITER=request["writer"])
original_read, original_init, original_stop = CamGear.read, CamGear.__init__, CamGear.stop
original_temp = tempfile.TemporaryDirectory
paths = []

class TrackedTemporaryDirectory(original_temp):
    def __enter__(self):
        name = super().__enter__()
        paths.append(Path(name))
        return name
    def cleanup(self):
        super().cleanup()
        if fault == "fixture_cleanup":
            Path(self.name).mkdir(exist_ok=True)

class StreamView:
    def __init__(self, stream):
        self.stream = stream
    def get(self, property):
        if property == cv2.CAP_PROP_FRAME_COUNT and fault == "frame_count":
            return 2
        return self.stream.get(property)
    def isOpened(self):
        return True if fault == "capture_cleanup" else self.stream.isOpened()
    def __getattr__(self, name):
        return getattr(self.stream, name)

def initialize(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    if fault == "frame_count":
        self.stream = StreamView(self.stream)

def read(self):
    frame = original_read(self)
    if fault == "missing_frame":
        return None
    if fault == "content" and frame is not None:
        frame = frame.copy()
        frame[0, 0, 0] ^= 255
    if fault == "dimensions" and frame is not None:
        return frame[:, :40, :]
    if fault == "eof" and frame is None:
        return np.zeros((48, 80, 3), dtype=np.uint8)
    return frame

stopped = False
def stop(self):
    global stopped
    original_stop(self)
    stopped = True
    if fault == "capture_cleanup":
        self.stream = StreamView(self.stream)
    if fault == "stop_error":
        raise RuntimeError("injected stop failure")

original_enumerate = threading.enumerate
sentinel = object()
def enumerate_threads():
    return original_enumerate() + ([sentinel] if stopped else [])

try:
    with ExitStack() as patches:
        patches.enter_context(patch("tempfile.TemporaryDirectory", TrackedTemporaryDirectory))
        patches.enter_context(patch.object(CamGear, "__init__", initialize))
        patches.enter_context(patch.object(CamGear, "read", read))
        patches.enter_context(patch.object(CamGear, "stop", stop))
        if fault == "wrong_version":
            distribution = importlib.metadata.distribution("vidgear")
            patches.enter_context(patch("importlib.metadata.distribution", return_value=SimpleNamespace(
                version="9.9.9", locate_file=distribution.locate_file)))
        if fault == "missing_version":
            patches.enter_context(patch("importlib.metadata.distribution", side_effect=importlib.metadata.PackageNotFoundError("vidgear")))
        if fault == "eof":
            patches.enter_context(patch("time.monotonic", side_effect=iter([0, 10])))
        if fault == "thread_cleanup":
            patches.enter_context(patch("threading.enumerate", enumerate_threads))
        if request["writer"] == "1":
            from vidgear.gears import WriteGear
            original_write, original_close = WriteGear.write, WriteGear.close
            writes = 0
            def write(self, frame, *args, **kwargs):
                global writes
                writes += 1
                if fault == "writer_content":
                    frame = frame.copy()
                    frame[0, 0, 0] ^= 255
                if fault == "writer_dimensions":
                    frame = frame[:24, :, :]
                if fault == "writer_missing_frame" and writes == 3:
                    return
                original_write(self, frame, *args, **kwargs)
                if fault == "writer_extra_frame" and writes == 6:
                    original_write(self, frame, *args, **kwargs)
            def close(self):
                process = self._WriteGear__process
                original_close(self)
                if fault == "writer_exit":
                    process.returncode = 37
            patches.enter_context(patch.object(WriteGear, "write", write))
            patches.enter_context(patch.object(WriteGear, "close", close))
        exec(compile(request["probe"], "exact-workflow-probe", "exec"), {})
finally:
    # The cleanup mutation deliberately recreates only its tracked fixture directory.
    leftovers = [path for path in paths if path.exists()]
    for path in leftovers:
        shutil.rmtree(path)
    if fault != "fixture_cleanup":
        assert not leftovers, ("probe left fixture directories after failure", leftovers)
'''


def run_native_probes(baseline_python, candidate_python):
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-vidgear"]
    probe = job["env"]["VIDGEAR_RUNTIME_PROBE"]
    cases = [("none", ""), ("wrong_version", "9.9.9"), ("missing_version", "PackageNotFoundError"),
             ("missing_frame", "VidGear returned no frame"), ("content", "wrong frame content"),
             ("dimensions", "wrong dimensions"), ("frame_count", "wrong fixture frame count"),
             ("eof", "VidGear failed to reach EOF"), ("capture_cleanup", "VidGear capture leaked"),
             ("thread_cleanup", "VidGear thread leaked"), ("fixture_cleanup", "fixture cleanup failed"),
             ("stop_error", "injected stop failure")]
    writer_cases = [("writer_content", "wrong frame content"), ("writer_dimensions", "wrong dimensions"),
                    ("writer_missing_frame", "wrong writer frame count"), ("writer_extra_frame", "wrong writer frame count"),
                    ("writer_exit", "VidGear encoder failed")]
    results = []
    for executable, version, writer in ((baseline_python, "0.1.0", "0"), (candidate_python, "0.3.4", "1")):
        for fault, message in cases + (writer_cases if writer == "1" else []):
            result = subprocess.run([executable, "-I", "-c", NATIVE_HARNESS], text=True,
                                    input=json.dumps(dict(fault=fault, version=version, writer=writer, probe=probe)),
                                    capture_output=True, timeout=30,
                                    env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
            output = result.stdout + result.stderr
            passed = result.returncode == 0 if fault == "none" else result.returncode != 0 and message in output
            results.append(dict(version=version, fault=fault, exit=result.returncode, test_passed=passed,
                                stdout=result.stdout, stderr=result.stderr))
            print(f"{version} {fault}: {'PASS' if passed else 'FAIL'}", file=sys.stderr, flush=True)
    print(json.dumps({"workflow_sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest(),
                      "probe_sha256": hashlib.sha256(probe.encode()).hexdigest(), "cases": results}, indent=2))
    return 0 if all(case["test_passed"] for case in results) else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--native-probes":
        raise SystemExit(run_native_probes(sys.argv[2], sys.argv[3]))
    unittest.main()
