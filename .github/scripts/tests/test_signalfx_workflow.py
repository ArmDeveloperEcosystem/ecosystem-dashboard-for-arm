from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-signalfx-agent.yml"


@unittest.skipUnless(shutil.which("jq"), "jq is required by the workflow")
class SignalFxWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="signalfx-workflow-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.cleanup_fixtures)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-signalfx-agent"]
        self.steps = {step["id"]: step["run"] for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"])
        self.env["GITHUB_OUTPUT"] = str(self.root / "output")
        self.env["VERSION_MARKER"] = str(self.root / "generated-version")
        self.env["BUILD_MARKER"] = str(self.root / "build-directory")
        self.env["TMPDIR"] = str(self.root)
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.env["PATH"] = str(self.tools) + os.pathsep + os.environ["PATH"]
        self.source = self.root / "cached-source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "pkg").mkdir()
        (self.source / "go.mod").write_text("module github.com/signalfx/signalfx-agent\n")
        (self.source / "scripts/current-version").write_text("echo 5.27.0\n")
        (self.source / "scripts/make-versions").write_text('printf "%s\\n" "$AGENT_VERSION" > "$VERSION_MARKER"\n')
        self.apm = self.root / "cached-apm"
        self.apm.mkdir()
        (self.apm / "go.mod").write_text("module github.com/signalfx/signalfx-agent/pkg/apm\n")
        metadata = "\n".join(json.dumps({"Path": module, "Dir": str(directory)}) for module, directory in (
            (self.env["SIGNALFX_MODULE"], self.source),
            (self.env["SIGNALFX_MODULE"] + "/pkg/apm", self.apm),
        ))
        self.stub("go", f"""
if [ "$1" = mod ]; then
  if [ "${{DOWNLOAD_FAIL:-0}}" = 1 ]; then
    echo 'checksum mismatch' >&2
    exit 1
  fi
  printf '%s\\n' {shlex.quote(metadata)}
else
  test -f pkg/apm/go.mod
  test -w pkg/apm/go.mod
  printf '%s\\n' "$PWD" > "$BUILD_MARKER"
  if [ "${{BUILD_FAIL:-0}}" = 1 ]; then exit 1; fi
  printf '%s\\n' '#!/bin/sh' \
    'case "$1" in' \
    '  --help) echo "Usage: signalfx-agent config" ;;' \
    '  -config)' \
    '    if [ "${{OMIT_STARTUP_MARKER:-}}" != configured ]; then echo "Done configuring agent"; fi' \
    '    if [ "${{OMIT_STARTUP_MARKER:-}}" != metrics ]; then echo "Serving internal metrics"; fi ;;' \
    '  *) printf "agent-version: %s, collectd-version: 5.8.0-sfx0\\n" "$(cat "$VERSION_MARKER")" ;;' \
    'esac' > "$3"
  chmod +x "$3"
fi
""")
        self.stub("file", 'echo "$1: ELF 64-bit LSB executable, ARM aarch64"')
        self.stub("timeout", '''
test "$1" = --kill-after=5s
test "$2" = 8s
shift 2
"$@"
exit "${RUNTIME_EXIT:-124}"
''')

    def cleanup_fixtures(self) -> None:
        # Failed copies can leave read-only trees as well as the cache fixtures.
        if self.root.exists():
            for directory, _, files in os.walk(self.root):
                Path(directory).chmod(0o700)
                for name in files:
                    (Path(directory) / name).chmod(0o600)
        self.temp.cleanup()

    def make_cache_read_only(self) -> None:
        for cache in (self.source, self.apm):
            for directory, _, files in os.walk(cache):
                for name in files:
                    (Path(directory) / name).chmod(0o444)
                Path(directory).chmod(0o555)
        with self.assertRaises(PermissionError):
            (self.source / "pkg/apm").mkdir()
        with self.assertRaises(PermissionError):
            (self.apm / "go.mod").open("a")

    def stub(self, name: str, body: str) -> None:
        target = self.tools / name
        target.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
        target.chmod(0o755)

    def run_step(self, step_id: str, **env: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
        script = self.steps[step_id]
        # Keep the workflow's fixed /tmp paths inside this test's private directory.
        script = script.replace("/tmp/signalfx", str(self.root / "signalfx"))
        script = re.sub(r"^bash \.github/actions/apt-bootstrap/bootstrap\.sh.*\n", "", script, flags=re.M)
        values = {
            "steps.version.outputs.version": self.env["SIGNALFX_VERSION"],
            "steps.version.outputs.latest": self.env["SIGNALFX_NEXT_VERSION"],
        }

        def expression(match: re.Match) -> str:
            key, fallback = match.group(1).split("||")
            return values.get(key.strip(), fallback.strip().strip("'"))

        script = re.sub(r"\$\{\{ (.*?) \}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=dict(self.env, **env), text=True, capture_output=True,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_install_restores_nested_apm_module(self) -> None:
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", outputs["install_status"])
        self.assertTrue((self.root / "signalfx-agent/source/pkg/apm/go.mod").is_file())
        self.assertEqual("5.27.0\n", Path(self.env["VERSION_MARKER"]).read_text())

    @unittest.skipIf(os.geteuid() == 0, "requires a non-root user to enforce cache permissions")
    def test_install_restores_read_only_cache_as_non_root(self) -> None:
        self.make_cache_read_only()
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("success", outputs["install_status"])
        source = Path(Path(self.env["BUILD_MARKER"]).read_text().strip())
        self.assertTrue(os.access(source / "pkg/apm/go.mod", os.W_OK))
        self.assertFalse(os.access(self.source / "pkg", os.W_OK))
        self.assertFalse(os.access(self.apm / "go.mod", os.W_OK))
        self.cleanup_fixtures()
        self.assertFalse(self.root.exists())

    @unittest.skipIf(os.geteuid() == 0, "requires a non-root user to enforce cache permissions")
    def test_regression_restores_read_only_cache_as_non_root(self) -> None:
        (self.source / "scripts/current-version").write_text("echo 5.27.1\n")
        self.make_cache_read_only()
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual("next_install_validated", outputs["decision"])
        self.assertEqual("5.27.1", outputs["next_installed_version"])
        self.assertEqual("5.27.1\n", Path(self.env["VERSION_MARKER"]).read_text())
        source = Path(Path(self.env["BUILD_MARKER"]).read_text().strip())
        self.assertFalse(source.parent.exists(), "candidate EXIT trap must remove its source tree")
        self.assertFalse(os.access(self.source / "pkg", os.W_OK))
        self.assertFalse(os.access(self.apm / "go.mod", os.W_OK))
        self.cleanup_fixtures()
        self.assertFalse(self.root.exists())

    def test_install_rejects_failed_checksum_download(self) -> None:
        result, outputs = self.run_step("install", DOWNLOAD_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("success", outputs.get("install_status"))
        self.assertFalse((self.root / "signalfx-agent-arm").exists())
        self.assertFalse(Path(self.env["VERSION_MARKER"]).exists())

    def test_install_rejects_missing_nested_module(self) -> None:
        shutil.rmtree(self.apm)
        result, outputs = self.run_step("install")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("success", outputs.get("install_status"))

    def test_install_rejects_wrong_release_source(self) -> None:
        (self.source / "scripts/current-version").write_text("echo 5.28.0\n")
        result, outputs = self.run_step("install")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("success", outputs.get("install_status"))
        self.assertFalse((self.root / "signalfx-agent-arm").exists())
        self.assertFalse(Path(self.env["VERSION_MARKER"]).exists())

    def test_install_rejects_build_failure(self) -> None:
        result, outputs = self.run_step("install", BUILD_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("success", outputs.get("install_status"))

    def test_version_check_rejects_wrong_or_failing_binary(self) -> None:
        binary = self.root / "signalfx-agent-arm"
        for version, exit_code in (("latest", 0), ("5.27.0", 1), ("5.27.0", 0)):
            with self.subTest(version=version, exit_code=exit_code):
                binary.write_text(f'#!/bin/sh\necho "agent-version: {version}, collectd-version: 5.8.0-sfx0"\nexit {exit_code}\n')
                binary.chmod(0o755)
                result, outputs = self.run_step("test2")
                passed = version == "5.27.0" and exit_code == 0
                self.assertEqual(passed, result.returncode == 0)
                self.assertEqual("passed" if passed else "failed", outputs["status"])

    def assert_runtime_cases(self, step_id: str) -> None:
        cases = ((1, ""), (0, ""), (137, ""), (124, ""),
                 (124, "configured"), (124, "metrics"))
        for exit_code, missing_marker in cases:
            with self.subTest(step=step_id, exit_code=exit_code, missing_marker=missing_marker):
                result, outputs = self.run_step(
                    step_id, RUNTIME_EXIT=str(exit_code), OMIT_STARTUP_MARKER=missing_marker,
                )
                passed = exit_code == 124 and not missing_marker
                self.assertEqual(passed, result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual("passed" if passed else "failed", outputs["status"])
                if step_id == "test6":
                    self.assertEqual(
                        "next_install_validated" if passed else "next_install_failed",
                        outputs["decision"],
                    )
                    self.assertEqual(
                        "5.27.1" if passed else "not_installed", outputs["next_installed_version"],
                    )

    def test_baseline_runtime_requires_timeout_and_both_startup_markers(self) -> None:
        result, _ = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assert_runtime_cases("test5")

    def test_candidate_runtime_requires_timeout_and_both_startup_markers(self) -> None:
        (self.source / "scripts/current-version").write_text("echo 5.27.1\n")
        self.assert_runtime_cases("test6")

    def test_regression_rejects_failed_checksum_download(self) -> None:
        result, outputs = self.run_step("test6", DOWNLOAD_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])
        self.assertEqual("not_installed", outputs["next_installed_version"])

    def test_regression_rejects_wrong_release_before_version_generation(self) -> None:
        result, outputs = self.run_step("test6")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("not_installed", outputs["next_installed_version"])
        self.assertFalse(Path(self.env["VERSION_MARKER"]).exists())

    def test_summary_fails_when_install_prevented_all_tests(self) -> None:
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", outputs["overall_status"])
        self.assertEqual("failing", outputs["badge_status"])
        self.assertEqual("0", outputs["passed"])


if __name__ == "__main__":
    unittest.main()
