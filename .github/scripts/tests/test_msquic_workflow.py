"""Reject build failures and misleading success exits from the upstream QUIC sample."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-msquic.yml"


class MsQuicWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="msquic-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-msquic"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        CMAKE_FAILURE="build", CMAKE_CALLS=str(self.root / "cmake-calls"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        (self.root / "baseline-src").mkdir()
        (self.root / "smoke-build").mkdir()
        self.stub("uname", 'echo "${TEST_ARCH:-aarch64}"')
        self.stub("git", '''
source="$PWD"
if [ "$1" = -C ]; then source="$2"; shift 2; fi
if [ "$1" = describe ]; then
  case "$source" in
    *next-src) echo "${TEST_TAG:-v2.6.1}" ;;
    *) echo "${TEST_TAG:-v2.1.1}" ;;
  esac
elif [ "$1" = rev-parse ]; then echo fixture-commit; fi
''')
        self.stub("cc", "exit 0")
        self.stub("cmake", '''
printf '%s|%s\\n' "$PWD" "$*" >> "$CMAKE_CALLS"
if [ "$1" = --build ]; then
  if [ "$CMAKE_FAILURE" = build ]; then echo "compile failed" >&2; exit 8; fi
  mkdir -p smoke-build/bin/Release
  cp "$SAMPLE_FIXTURE" smoke-build/bin/Release/quicsample
  touch "smoke-build/bin/Release/libmsquic.so.${BUILD_VERSION:-2.6.1}"
  ln -sf "libmsquic.so.${BUILD_VERSION:-2.6.1}" smoke-build/bin/Release/libmsquic.so.2
fi
''')
        self.stub("file", 'echo "ELF 64-bit ARM aarch64"')
        self.stub("openssl", "exit 0")
        self.stub("ldd", 'echo "libmsquic.so.2 => ${LINKED_DIR:-$PWD/smoke-build/bin/Release}/libmsquic.so.2 (0x1234)"')
        self.stub("stdbuf", 'shift; exec "$@"')
        sample = self.bin / "sample"
        sample.write_text(f"#!{sys.executable}\n" + '''
import os
import sys
server = "-server" in sys.argv
side = "server" if server else "client"
if server:
    if os.environ.get("EARLY_EXIT"):
        sys.exit(2)
    print("Press Enter to exit.", flush=True)
for marker in ("Connected", "Data sent", "Data received"):
    if os.environ.get("OMIT") != side + ":" + marker:
        print(marker, flush=True)
if os.environ.get("ERROR_SIDE") == side:
    print(os.environ.get("ERROR_MESSAGE", "StreamSend failed"), flush=True)
if server:
    sys.stdin.readline()
sys.exit(3 if os.environ.get("BAD_EXIT") == side else 0)
''')
        sample.chmod(0o755)
        self.env["SAMPLE"] = str(sample)
        self.env["SAMPLE_FIXTURE"] = str(sample)
        candidate = self.root / "next-src"
        (candidate / "src/tools/sample").mkdir(parents=True)
        (candidate / "CMakeLists.txt").write_text('set(QUIC_TLS_LIB "openssl")')
        (candidate / "README.md").write_text("MsQuic")
        (candidate / "src/tools/sample/sample.c").write_text("MsQuicOpen2")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_script(self, script, values=None, **env):
        values = {**{f"steps.test{i}.outcome": "success" for i in range(1, 7)}, **(values or {})}

        def expression(match):
            key, fallback = match[1].split("||")
            return values.get(key.strip()) or fallback.strip().strip("'")

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_smoke_preserves_build_architecture_and_tag_failures(self):
        for env in ({}, {"TEST_ARCH": "x86_64"}, {"TEST_TAG": "v2.1.2"}):
            with self.subTest(env=env):
                result, outputs = self.run_script(self.steps["test5"]["run"], **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertIn("duration", outputs)

    def run_loopback_fixture(self, **env):
        script = self.env["MSQUIC_SMOKE_COMMAND"].split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        return self.run_script("python3 - <<'PY'\n" + script + "\nPY\n", **env)[0]

    def test_loopback_requires_handshake_and_both_stream_receipts(self):
        result = self.run_loopback_fixture()
        self.assertEqual(0, result.returncode, result.stderr)
        for side in ("client", "server"):
            for marker in ("Connected", "Data sent", "Data received"):
                with self.subTest(side=side, marker=marker):
                    result = self.run_loopback_fixture(OMIT=f"{side}:{marker}")
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(f"missing {marker}", result.stderr)

    def test_zero_exit_with_error_and_nonzero_exits_are_rejected(self):
        for side in ("client", "server"):
            for error in ("StreamSend failed", "Shut down by transport, 0x1"):
                with self.subTest(side=side, error=error):
                    result = self.run_loopback_fixture(ERROR_SIDE=side, ERROR_MESSAGE=error)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(error, result.stdout)
            result = self.run_loopback_fixture(BAD_EXIT=side)
            self.assertNotEqual(0, result.returncode)
        result = self.run_loopback_fixture(EARLY_EXIT="1")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("exited before listening", result.stderr)

    def test_summary_fails_closed_for_each_core_result_and_candidate(self):
        for number in range(1, 7):
            for status in ("", "failed", "skipped", "invalid"):
                with self.subTest(number=number, status=status):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                    values[f"steps.test{number}.outputs.status"] = status
                    result, outputs = self.run_script(self.steps["summary"]["run"], values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(number < 6)), outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        result, outputs = self.run_script(self.steps["summary"]["run"], values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])

    def test_candidate_source_probe_rejects_missing_msquic_entrypoint(self):
        candidate = self.root / "next-src"
        (candidate / "src/tools/sample/sample.c").write_text("int main(void) {}")
        result, _ = self.run_candidate()
        self.assertNotEqual(0, result.returncode)

    def run_candidate(self, **env):
        candidate_env = dict(CURRENT_VERSION="2.1.1", LATEST_VERSION="2.6.1", CANDIDATE_TAG="v2.6.1",
                             CMAKE_FAILURE="")
        candidate_env.update(env)
        return self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"], **candidate_env)

    def test_candidate_builds_and_runs_from_candidate_checkout_only(self):
        result, _ = self.run_candidate()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = Path(self.env["CMAKE_CALLS"]).read_text().splitlines()
        self.assertTrue(all(Path(line.split("|", 1)[0]).resolve() == (self.root / "next-src").resolve()
                            for line in calls))
        self.assertTrue(any("-DQUIC_TLS_LIB=openssl" in line for line in calls))
        self.assertIn("version: 2.6.1", result.stdout)
        self.assertEqual(2, result.stdout.count("Data received"))

    def test_candidate_rejects_wrong_tag_library_and_runtime_failures(self):
        cases = ({"LATEST_VERSION": "2.1.1"}, {"CANDIDATE_TAG": "v2.1.1"},
                 {"TEST_TAG": "v2.1.1"}, {"BUILD_VERSION": "2.1.1"},
                 {"LINKED_DIR": "/unrelated/baseline-src"}, {"CMAKE_FAILURE": "build"},
                 {"OMIT": "client:Data received"}, {"OMIT": "server:Data received"},
                 {"ERROR_SIDE": "client"}, {"BAD_EXIT": "server"})
        for env in cases:
            with self.subTest(env=env):
                result, _ = self.run_candidate(**env)
                self.assertNotEqual(0, result.returncode)

    def test_composite_never_reports_failed_candidate_as_installed(self):
        action = WORKFLOW.parents[1] / "actions/generic-source-regression-check/action.yml"
        script = yaml.safe_load(action.read_text())["runs"]["steps"][0]["run"]
        helper = re.search(r"(?ms)^run_limited_cpu_probe\(\) \{.*?^\}", script)[0]
        script = helper + '\nrun_limited_cpu_probe "$LATEST_VERSION" "$CANDIDATE_TAG"\n'
        for missing in ("", "client:Data received"):
            with self.subTest(missing=missing):
                result, outputs = self.run_script(
                    script, CURRENT="2.1.1", LATEST_VERSION="2.6.1", CANDIDATE_TAG="v2.6.1",
                    REPO="microsoft/msquic", DEFER_ON_LIMITED_CPU_PROBE_FAILURE="false",
                    LIMITED_CPU_PROBE=self.steps["test6"]["with"]["limited_cpu_probe"],
                    LIMITED_CPU_DESCRIPTION=self.steps["test6"]["with"]["limited_cpu_description"],
                    CMAKE_FAILURE="", OMIT=missing,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("failed" if missing else "passed", outputs["status"])
                self.assertEqual("limited_cpu_probe_failed" if missing else "2.6.1",
                                 outputs["next_installed_version"])


    def test_passed_output_cannot_hide_failed_cancelled_or_missing_outcome(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", ""):
                with self.subTest(number=number, outcome=outcome):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                    values[f"steps.test{number}.outcome"] = outcome
                    result, outputs = self.run_script(self.steps["summary"]["run"], values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(number < 6)), outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])

    def test_safe_skip_requires_successful_regression_step_outcome(self):
        for outcome in ("failure", "cancelled", ""):
            with self.subTest(outcome=outcome):
                values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
                values.update({"steps.test6.outputs.status": "skipped",
                               "steps.test6.outputs.decision": "no_newer_stable_available",
                               "steps.test6.outcome": outcome})
                result, outputs = self.run_script(self.steps["summary"]["run"], values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("0", outputs["core_failed"])


if __name__ == "__main__":
    unittest.main()
