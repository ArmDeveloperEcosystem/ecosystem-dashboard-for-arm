"""Replay Debian ELTS shell steps with isolated apt and container fixtures."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-debian_elts.yml"
BASH = shutil.which("bash")

CONTAINER_FIXTURE = """
sudo() { "$@"; }
docker() {
  case "$1" in
    pull) return 0 ;;
    inspect) printf '%s\\n' "${IMAGE_ARCH:-arm64}" ;;
    run)
      test "$2" = --rm || return 2
      shift 3
      case "$1" in
        sh)
          case "$3" in
            *apt-get*) "$@" ;;
            *printf*) printf '%s' "${CANDIDATE_VERSION:-12}" ;;
            *grep*) return "${OS_RELEASE_EXIT:-0}" ;;
            *) return 2 ;;
          esac ;;
        uname) printf '%s\\n' "${CONTAINER_ARCH:-aarch64}" ;;
        echo) printf '%s\\n' "${GREETING:-Hello Arm64}" ;;
        *) return 2 ;;
      esac ;;
    *) return 2 ;;
  esac
}
"""


@unittest.skipUnless(BASH, "bash is required")
class DebianEltsWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="debian-elts-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test-debian_elts"]
        self.steps = {step["id"]: step["run"] for step in job["steps"] if "id" in step}
        self.env = {**os.environ, **job["env"]}
        self.sources = self.root / "sources.list"
        self.trace = self.root / "trace"
        self.output = self.root / "output"
        self.env.update(PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.output), TRACE=str(self.trace))
        self.values = {
            "steps.install.outputs.baseline_tag": job["env"]["DEBIAN_ELTS_BASELINE_TAG"],
            "steps.version.outputs.version": "11",
            **{f"steps.test{number}.outputs.status": "passed" for number in range(1, 7)},
            **{f"steps.test{number}.outputs.duration": "1" for number in range(1, 7)},
        }
        self.stub("apt-get", """
printf 'apt-get %s\\n' "$*" >> "$TRACE"
case "$*" in
  update) stage=update ;;
  'install -y ca-certificates')
    test "$DEBIAN_FRONTEND" = noninteractive
    stage=install ;;
  *) exit 2 ;;
esac
if [ "${FAIL_STAGE:-}" = "$stage" ]; then
  echo "apt $stage diagnostic" >&2
  exit 100
fi
""")
        self.stub("dpkg", """
printf 'dpkg %s\\n' "$*" >> "$TRACE"
test "$*" = '-s ca-certificates'
if [ "${FAIL_STAGE:-}" = dpkg ]; then
  echo 'dpkg diagnostic' >&2
  exit 1
fi
printf 'Status: %s\\n' "${PACKAGE_STATUS:-install ok installed}"
""")

    def stub(self, name: str, body: str) -> None:
        path = self.root / name
        path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_step(self, step_id: str, **env: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
        def expression(match: re.Match) -> str:
            for key in match.group(1).split("||"):
                key = key.strip()
                value = key.strip("'") if key.startswith("'") or key.isdigit() else self.values.get(key, "")
                if value:
                    return value
            return ""

        script = re.sub(r"\$\{\{ (.*?) \}\}", expression, self.steps[step_id])
        # Redirect only the container's apt configuration path into this fixture.
        script = script.replace("/etc/apt/sources.list", shlex.quote(str(self.sources)))
        self.output.write_text("", encoding="utf-8")
        self.trace.write_text("", encoding="utf-8")
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-e", "-c", CONTAINER_FIXTURE + script],
            cwd=self.root, env={**self.env, **env}, capture_output=True, text=True, check=False,
        )
        values = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, values

    def test_baseline_uses_signed_release_archive_and_installs_package(self) -> None:
        result, outputs = self.run_step("test3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertEqual(self.sources.read_text(), "deb http://archive.debian.org/debian bullseye main\n")
        self.assertEqual(self.trace.read_text().splitlines(), [
            "apt-get update", "apt-get install -y ca-certificates", "dpkg -s ca-certificates",
        ])

    def test_source_configuration_failure_stops_baseline_install(self) -> None:
        self.sources = self.root / "missing" / "sources.list"
        result, outputs = self.run_step("test3")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs["status"], "failed")
        self.assertEqual(self.trace.read_text(), "")

    def test_apt_and_dpkg_failures_are_visible_and_stop_the_smoke(self) -> None:
        for step in ("test3", "test6"):
            for stage, calls in (("update", 1), ("install", 2), ("dpkg", 3)):
                with self.subTest(step=step, stage=stage):
                    result, outputs = self.run_step(step, FAIL_STAGE=stage)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(outputs["status"], "failed")
                    self.assertIn(stage + " diagnostic", result.stderr)
                    self.assertEqual(len(self.trace.read_text().splitlines()), calls)
                    if step == "test6":
                        self.assertEqual(outputs["decision"], "next_install_failed")

    def test_smoke_requires_installed_package_status(self) -> None:
        for step in ("test3", "test6"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step, PACKAGE_STATUS="deinstall ok config-files")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")

    def test_candidate_success_retains_version_provenance(self) -> None:
        result, outputs = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertEqual(outputs["decision"], "next_install_validated")
        self.assertEqual(outputs["current_version"], "11")
        self.assertEqual(outputs["latest_version"], "12.13")
        self.assertEqual(outputs["next_installed_version"], "12")
        self.assertIn("Baseline Debian 11 passed", outputs["comparison"])
        self.assertFalse(self.sources.exists(), "candidate keeps its own apt sources")

    def test_candidate_requires_version_architecture_os_and_command_checks(self) -> None:
        for key, value in (("CANDIDATE_VERSION", "11"), ("IMAGE_ARCH", "amd64"),
                           ("CONTAINER_ARCH", "x86_64"), ("OS_RELEASE_EXIT", "1"),
                           ("GREETING", "wrong output")):
            with self.subTest(key=key):
                result, outputs = self.run_step("test6", **{key: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")
                self.assertEqual(outputs["decision"], "next_install_failed")

    def test_regression_never_claims_failed_or_missing_baseline_passed(self) -> None:
        for number in range(1, 6):
            for status in ("failed", ""):
                for candidate_failure in ("", "update"):
                    with self.subTest(test=number, status=status, candidate_failure=candidate_failure):
                        key = f"steps.test{number}.outputs.status"
                        self.values[key] = status
                        result, outputs = self.run_step("test6", FAIL_STAGE=candidate_failure)
                        self.values[key] = "passed"
                        self.assertEqual(result.returncode, 1 if candidate_failure else 0)
                        self.assertEqual(outputs["status"], "failed" if candidate_failure else "passed")
                        self.assertIn("Baseline Debian 11 did not pass all", outputs["comparison"])
                        self.assertNotIn("Baseline Debian 11 passed", outputs["comparison"] + result.stdout)
                        self.assertIn("apt-get update", self.trace.read_text())

    def test_summary_counts_baseline_and_candidate_failures(self) -> None:
        for baseline in ("passed", "failed", ""):
            for candidate in ("passed", "failed"):
                with self.subTest(baseline=baseline, candidate=candidate):
                    self.values["steps.test3.outputs.status"] = baseline
                    self.values["steps.test6.outputs.status"] = candidate
                    result, outputs = self.run_step("summary")
                    core_failed = int(baseline != "passed")
                    failed = core_failed + int(candidate != "passed")
                    self.assertEqual(result.returncode, 1 if failed else 0)
                    self.assertEqual(outputs["passed"], str(6 - failed))
                    self.assertEqual(outputs["failed"], str(failed))
                    self.assertEqual(outputs["core_failed"], str(core_failed))
                    self.assertEqual(outputs["badge_status"], "failing" if core_failed else "passing")
                    self.assertEqual(outputs["overall_status"], "failure" if failed else "success")


if __name__ == "__main__":
    unittest.main()
