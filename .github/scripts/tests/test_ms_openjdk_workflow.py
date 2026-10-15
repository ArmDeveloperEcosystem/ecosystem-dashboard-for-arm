"""Exercise OpenJDK response handling and outcome-aware workflow accounting."""

import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-ms-openjdk.yml"


class MsOpenJdkWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ms-openjdk-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-ms-openjdk"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, **self.job["env"],
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"), TMPDIR=str(self.root),
                        RUNNER_TEMP=str(self.root))
        self.values = {"steps.install.outputs.install_mode": "external_artifact",
                       "steps.install.outputs.install_status": "success",
                       "steps.install.outputs.resolved_tag": "external_artifact"}
        metadata = self.root / "baseline-external/metadata.txt"
        metadata.parent.mkdir()
        metadata.touch()
        self.download = self.root / "download.html"
        self.docs = self.root / "install.html"
        self.releases = self.root / "releases.html"
        # The match precedes more than a pipe buffer, making grep -q close curl early.
        self.download.write_text("OpenJDK\n" + "release details\n" * 262144)
        self.docs.write_text("Ubuntu\n" + "installation details\n" * 262144)
        self.releases.write_text("11.0.12 Linux aarch64\n" + "release details\n" * 262144)
        self.env.update(DOWNLOAD_URL=self.download.as_uri(), OFFICIAL_DOCS=self.docs.as_uri(),
                        RELEASES_URL=self.releases.as_uri())

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, **env):
        values = dict(self.values, **(values or {}))

        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return value
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def passed_values(self):
        return {key: value for number in range(1, 7) for key, value in (
            (f"steps.test{number}.outputs.status", "passed"),
            (f"steps.test{number}.outcome", "success"),
            (f"steps.test{number}.outputs.duration", str(number)))}

    def test_real_curl_reproduces_early_pipe_close_and_complete_reads_pass(self):
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c",
             'curl -fsL "$DOWNLOAD_URL" | grep -Fqi "OpenJDK"'],
            env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(23, result.returncode, result.stderr)
        for number in range(1, 4):
            with self.subTest(number=number):
                result, outputs = self.run_step(f"test{number}")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])

    def test_identity_version_and_installation_content_remain_required(self):
        cases = ((1, self.download, "Another distribution\n"),
                 (2, self.download, "Another distribution\n"),
                 (2, self.releases, "Ubuntu 11.0.28\n"),
                 (3, self.docs, "Windows installation\n"))
        for number, path, body in cases:
            with self.subTest(number=number, body=body):
                original = path.read_text()
                try:
                    path.write_text(body)
                    result, outputs = self.run_step(f"test{number}")
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotEqual("passed", outputs.get("status"))
                finally:
                    path.write_text(original)

    def test_missing_baseline_metadata_cannot_pass(self):
        (self.root / "baseline-external/metadata.txt").unlink()
        result, outputs = self.run_step("test1")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("passed", outputs.get("status"))

    def test_real_curl_fetch_failure_cannot_pass(self):
        for number in range(1, 4):
            with self.subTest(number=number):
                result, outputs = self.run_step(
                    f"test{number}", DOWNLOAD_URL=(self.root / "missing").as_uri(),
                    OFFICIAL_DOCS=(self.root / "missing").as_uri(),
                    RELEASES_URL=(self.root / "missing").as_uri())
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("passed", outputs.get("status"))

    def test_matching_partial_response_cannot_hide_curl_errors(self):
        self.stub("curl", '''
printf 'OpenJDK 11.0.12 Ubuntu\\n'
echo "curl: injected transfer failure $CURL_EXIT" >&2
exit "$CURL_EXIT"
''')
        for number in range(1, 4):
            for code in (7, 22, 23, 28):
                with self.subTest(number=number, code=code):
                    result, outputs = self.run_step(f"test{number}", CURL_EXIT=str(code))
                    self.assertEqual(code, result.returncode, result.stderr)
                    self.assertNotEqual("passed", outputs.get("status"))

    def runtime_fixture(self):
        java = '''#!/bin/bash
set -euo pipefail
printf 'java %s\\n' "$*" >> "$FIXTURE_CALLS"
if [ "$1" = -XshowSettings:properties ]; then
  printf '    java.class.path = \\n    line.separator = \\n    user.timezone = \\n'
  printf '    java.version = %s\\n' "${FIXTURE_VERSION:-$EXPECTED_VERSION}"
  printf '    java.vendor = %s\\n' "${FIXTURE_VENDOR:-Microsoft}"
  printf '    java.vm.vendor = %s\\n' "${FIXTURE_VENDOR:-Microsoft}"
  printf '    os.arch = %s\\n' "${FIXTURE_ARCH:-aarch64}"
  printf '    os.name = Linux\\n'
else
  test -f "$SMOKE_DIR/Hello.class"
  if [ "${FIXTURE_PROGRAM_FAIL:-0}" != 0 ]; then exit 17; fi
  printf 'Hello %s Microsoft aarch64 %s\\n' "$EXPECTED_VERSION" "${FIXTURE_SUM:-50005000}"
fi
'''
        javac = '''#!/bin/bash
set -euo pipefail
printf 'javac %s\\n' "$*" >> "$FIXTURE_CALLS"
test -s "$SMOKE_DIR/Hello.java"
if [ "${FIXTURE_COMPILE_FAIL:-0}" != 0 ]; then exit 16; fi
touch "$SMOKE_DIR/Hello.class"
'''
        archive = self.root / "fixture-jdk.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            for name, body in (("java", java), ("javac", javac)):
                member = tarfile.TarInfo(f"jdk/bin/{name}")
                member.mode = 0o755
                payload = body.encode()
                member.size = len(payload)
                handle.addfile(member, io.BytesIO(payload))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.env.update(FIXTURE_ARCHIVE=str(archive), BASELINE_JDK_SHA256=digest,
                        CANDIDATE_JDK_SHA256=digest, FIXTURE_CALLS=str(self.root / "runtime-calls"),
                        TEST5_COMMAND=self.job["env"]["TEST5_COMMAND"].replace(
                            self.job["env"]["RELEASES_URL"], self.releases.as_uri()))
        self.stub("uname", 'echo "${FIXTURE_HOST_ARCH:-aarch64}"')
        self.stub("file", 'echo "ELF 64-bit LSB executable, ${FIXTURE_BINARY_ARCH:-ARM aarch64}"')
        self.stub("timeout", 'shift; exec "$@"')
        self.stub("curl", '''
if [ "$EXPECTED_VERSION" = 11.0.12 ]; then
  test "$JDK_URL" = https://aka.ms/download-jdk/microsoft-jdk-11.0.12.7.1-linux-aarch64.tar.gz
else
  test "$JDK_URL" = https://aka.ms/download-jdk/microsoft-jdk-11.0.28-linux-aarch64.tar.gz
fi
test "$1" = -fsSL
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then shift; target="$1"; fi
  shift
done
if [ "${CURL_EXIT:-0}" != 0 ]; then exit "$CURL_EXIT"; fi
cp "$FIXTURE_ARCHIVE" "$target"
''')

    def test_versions_and_candidate_runtime_contract_are_preserved(self):
        self.runtime_fixture()
        self.assertEqual("11.0.12", self.job["env"]["BASELINE_VERSION"])
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("11.0.12", outputs["installed_version"])
        self.assertEqual("passed", outputs["status"])
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("11.0.12", outputs["current_version"])
        self.assertEqual("11.0.28", outputs["latest_version"])
        self.assertEqual("11.0.28", outputs["next_installed_version"])
        self.assertEqual("passed", outputs["status"])
        calls = Path(self.env["FIXTURE_CALLS"]).read_text()
        self.assertEqual(2, calls.count("javac "))
        self.assertIn("Hello 11.0.12", calls)
        self.assertIn("Hello 11.0.28", calls)
        self.assertEqual([], list(self.root.glob("ms-openjdk-smoke.*")))

    def test_candidate_fetch_failure_is_failed_and_not_installed(self):
        self.runtime_fixture()
        result, outputs = self.run_step("test6", CURL_EXIT="22")
        self.assertEqual(22, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])
        self.assertEqual("not_installed", outputs["next_installed_version"])
        values = self.passed_values()
        values["steps.test6.outputs.status"] = outputs["status"]
        result, outputs = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", outputs["overall_status"])
        self.assertEqual("passing", outputs["badge_status"])

    def test_runtime_rejects_wrong_version_vendor_architecture_and_program_failures(self):
        self.runtime_fixture()
        for number in (5, 6):
            for env in ({"FIXTURE_VERSION": "11.0.99"}, {"FIXTURE_VENDOR": "Other vendor"},
                        {"FIXTURE_ARCH": "amd64"}, {"FIXTURE_BINARY_ARCH": "x86-64"},
                        {"FIXTURE_HOST_ARCH": "x86_64"}, {"FIXTURE_PROGRAM_FAIL": "1"},
                        {"FIXTURE_COMPILE_FAIL": "1"}, {"FIXTURE_SUM": "0"},
                        {"BASELINE_JDK_SHA256": "0" * 64, "CANDIDATE_JDK_SHA256": "0" * 64}):
                with self.subTest(number=number, env=env):
                    result, outputs = self.run_step(f"test{number}", **env)
                    self.assertNotEqual(0, result.returncode, result.stderr)
                    self.assertEqual("failed", outputs["status"])
                    if "FIXTURE_VERSION" in env:
                        self.assertIn("java.version", result.stderr)
                    if "FIXTURE_VENDOR" in env:
                        self.assertIn("java.vendor", result.stderr)
                    if "FIXTURE_ARCH" in env:
                        self.assertIn("os.arch", result.stderr)
                    if "FIXTURE_PROGRAM_FAIL" in env:
                        self.assertEqual(17, result.returncode)
                    if "FIXTURE_COMPILE_FAIL" in env:
                        self.assertEqual(16, result.returncode)
                    if number == 6:
                        self.assertEqual("not_installed", outputs["next_installed_version"])
                    else:
                        self.assertNotIn("installed_version", outputs)
                    self.assertEqual([], list(self.root.glob("ms-openjdk-smoke.*")))

    def test_baseline_metadata_checks_still_gate_native_smoke(self):
        self.runtime_fixture()
        for body in ("11.0.28 Linux aarch64", "11.0.12 Linux x86", "11.0.12 Windows arm64"):
            with self.subTest(body=body):
                self.releases.write_text(body)
                result, outputs = self.run_step("test5")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertFalse(Path(self.env["FIXTURE_CALLS"]).exists())

    def test_summary_requires_all_six_successful_outcomes_and_passed_outputs(self):
        result, outputs = self.run_step("summary", self.passed_values())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"passed": "6", "failed": "0", "skipped": "0", "duration": "21",
                          "core_failed": "0", "overall_status": "success",
                          "badge_status": "passing"}, outputs)
        for number in range(1, 7):
            for status in ("", "failed", "skipped", "unknown"):
                with self.subTest(number=number, status=status):
                    values = self.passed_values()
                    values[f"steps.test{number}.outputs.status"] = status
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("0", outputs["skipped"])
                    self.assertEqual(str(int(number < 6)), outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])

    def test_passed_output_cannot_hide_failed_cancelled_skipped_or_missing_outcome(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    values = self.passed_values()
                    values[f"steps.test{number}.outcome"] = outcome
                    # continue-on-error may still report a successful conclusion.
                    values[f"steps.test{number}.conclusion"] = "success"
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(number < 6)), outputs["core_failed"])
                    self.assertEqual("failing" if number < 6 else "passing", outputs["badge_status"])

    def test_summary_rejects_original_missing_results_and_all_skipped_steps(self):
        for missing in (range(1, 4), range(1, 7)):
            with self.subTest(missing=list(missing)):
                values = self.passed_values()
                for number in missing:
                    values.pop(f"steps.test{number}.outputs.status")
                    values[f"steps.test{number}.outcome"] = "skipped"
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(str(6 - len(missing)), outputs["passed"])
                self.assertEqual(str(len(missing)), outputs["failed"])
                self.assertEqual(str(min(5, len(missing))), outputs["core_failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("failing", outputs["badge_status"])

    def test_failure_after_emitting_pass_is_rejected_by_summary(self):
        self.stub("date", '''
if [ -f "$TMPDIR/date-called" ]; then exit 9; fi
touch "$TMPDIR/date-called"
echo 100
''')
        result, outputs = self.run_step("test1")
        self.assertEqual(9, result.returncode)
        self.assertEqual("passed", outputs["status"])
        values = self.passed_values()
        values["steps.test1.outputs.status"] = outputs["status"]
        values["steps.test1.outcome"] = "failure"
        result, outputs = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["core_failed"])
        self.assertEqual("failure", outputs["overall_status"])


if __name__ == "__main__":
    unittest.main()
