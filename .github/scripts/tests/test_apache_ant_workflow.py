"""Keep Ant's pinned installations and six required checks honest."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-apache_ant.yml"


class ApacheAntWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ant-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-apache_ant"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, **job["env"], TMPDIR=str(self.root))
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        self.values.update({"steps.install.outputs.install_status": "success",
                            "steps.version.outputs.version": "1.10.14"})
        self.stub("ant", 'echo "Apache Ant(TM) version ${ACTUAL_VERSION:-1.10.14} compiled on test"\n')
        self.stub("readlink", 'echo "${ACTUAL_PATH:-/opt/apache-ant-1.10.14/bin/ant}"\n')
        self.stub("curl", "exit 97\n")
        self.stub("wget", "exit 97\n")
        if not shutil.which("sha512sum"):
            self.stub("sha512sum", 'exec shasum -a 512 "$@"\n')
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("exit 0\n")

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script)
        path.chmod(0o755)

    def run_step(self, step_id, **environment):
        def expression(match):
            parts = match[1].split("||", 1)
            value = self.values.get(parts[0].strip(), "")
            return value or (parts[1].strip().strip("'") if len(parts) == 2 else "")

        script = re.sub(r"\$\{\{ (.*?) \}\}", expression, self.steps[step_id]["run"])
        script = script.replace("/tmp/apache-ant", str(self.root / "ant"))
        output = self.root / "output"
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
            env=dict(self.env, GITHUB_OUTPUT=str(output), **environment),
            capture_output=True, text=True, timeout=15,
        )
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def stub_download(self):
        content = "verified Ant download fixture\n"
        digest = hashlib.sha512(content.encode()).hexdigest()
        self.env.update(ANT_SHA512=digest, ANT_NEXT_SHA512=digest,
                        ARTIFACT_CONTENT=content, DOWNLOAD_LOG=str(self.root / "downloads"))
        self.stub("curl", '''
destination=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) destination="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url" >> "$DOWNLOAD_LOG"
case "${DOWNLOAD_MODE:-success}" in
  unavailable) printf 'partial download' > "$destination"; exit 28 ;;
  corrupt) printf 'corrupt archive' > "$destination"; exit 0 ;;
  fallback|corrupt_primary)
    if [[ "$url" != https://repo.huaweicloud.com/* ]]; then
      printf 'partial or corrupt archive' > "$destination"
      if [ "$DOWNLOAD_MODE" = corrupt_primary ]; then exit 0; fi
      exit 28
    fi ;;
esac
printf '%s' "$ARTIFACT_CONTENT" > "$destination"
''')

    def test_both_downloaders_verify_bytes_and_recover_from_failed_or_corrupt_sources(self):
        self.stub_download()
        destination = self.root / "download.tar.gz"
        for step_id in ("install", "test6"):
            helper = re.search(r"(?ms)^download_ant_tarball\(\) \{.*?^\}",
                               self.steps[step_id]["run"])[0]
            self.steps["download"] = {"run": helper + '''
download_ant_tarball https://archive.apache.org/ant.tar.gz \\
  https://downloads.apache.org/ant.tar.gz "$DESTINATION" \\
  https://repo.huaweicloud.com/apache/ant/ant.tar.gz "$ANT_SHA512"
'''}
            for mode in ("success", "fallback", "corrupt_primary", "unavailable", "corrupt"):
                with self.subTest(step=step_id, mode=mode):
                    destination.write_text("stale successful download")
                    Path(str(destination) + ".part").write_text("stale partial download")
                    (self.root / "downloads").write_text("")
                    result, _ = self.run_step("download", DOWNLOAD_MODE=mode,
                                              DESTINATION=str(destination))
                    passed = mode in ("success", "fallback", "corrupt_primary")
                    self.assertEqual(passed, result.returncode == 0, result.stderr)
                    self.assertEqual(passed, destination.exists())
                    self.assertFalse(Path(str(destination) + ".part").exists())
                    if passed:
                        self.assertEqual(self.env["ARTIFACT_CONTENT"], destination.read_text())
                    calls = (self.root / "downloads").read_text().splitlines()
                    self.assertEqual(1 if mode == "success" else 3, len(calls))
                    if mode != "success":
                        self.assertIn("repo.huaweicloud.com", calls[-1])

    def test_baseline_download_failure_or_corruption_remains_a_core_failure(self):
        self.stub_download()
        self.stub("tar", 'touch "$TMPDIR/extracted"; exit 99\n')
        for mode in ("unavailable", "corrupt"):
            with self.subTest(mode=mode):
                result, output = self.run_step("install", DOWNLOAD_MODE=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["install_status"])
                self.assertEqual("baseline_download_failed", output["install_blocker"])
                self.assertFalse((self.root / "extracted").exists())
                self.values["steps.install.outputs.install_status"] = "failed"
                for index in (1, 2, 3, 5, 6):
                    _, check = self.run_step(f"test{index}")
                    self.values[f"steps.test{index}.outputs.status"] = check["status"]
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("1", "1", "1", "4", "failure"),
                                 tuple(summary[key] for key in
                                       ("passed", "failed", "core_failed", "skipped", "overall_status")))

    def test_candidate_download_failure_or_corruption_remains_a_failed_regression(self):
        self.stub_download()
        self.stub("tar", 'touch "$TMPDIR/extracted"; exit 99\n')
        for mode in ("unavailable", "corrupt"):
            with self.subTest(mode=mode):
                result, output = self.run_step("test6", DOWNLOAD_MODE=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertEqual("next_install_failed", output["decision"])
                self.assertFalse((self.root / "extracted").exists())
                self.values["steps.test6.outputs.status"] = output["status"]
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "0", "failure"),
                                 tuple(summary[key] for key in
                                       ("passed", "failed", "core_failed", "skipped", "overall_status")))

    def test_baseline_functional_failure_is_not_a_pass(self):
        self.stub("ant", "exit 7\n")
        result, output = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_preinstalled_binary_cannot_mask_failed_install(self):
        self.values["steps.install.outputs.install_status"] = "failed"
        result, output = self.run_step("test1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_binary_must_resolve_to_the_requested_installation(self):
        for actual, expected in (("/usr/bin/ant", "failed"),
                                 ("/opt/apache-ant-1.10.14/bin/ant", "passed")):
            with self.subTest(actual=actual):
                result, output = self.run_step("test1", ACTUAL_PATH=actual)
                self.assertEqual(expected, output["status"])
                self.assertEqual(expected == "passed", result.returncode == 0)

    def test_version_must_match_the_pinned_baseline(self):
        for version in ("1.10.14", "1.10.15", "2.0.0"):
            with self.subTest(version=version):
                result, output = self.run_step("test2", ACTUAL_VERSION=version)
                self.assertEqual(version == "1.10.14", result.returncode == 0)
                self.assertEqual("passed" if version == "1.10.14" else "failed", output["status"])

    def test_candidate_is_not_attempted_after_failed_skipped_or_missing_baseline(self):
        for index in range(1, 6):
            for status in ("failed", "skipped", ""):
                with self.subTest(index=index, status=status):
                    key = f"steps.test{index}.outputs.status"
                    self.values[key] = status
                    result, output = self.run_step("test6")
                    self.values[key] = "passed"
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("baseline_failed", output["decision"])
                    self.assertEqual("not_installed", output["next_installed_version"])

    def test_summary_rejects_every_failed_skipped_or_missing_required_test(self):
        for index in range(1, 7):
            for status in ("failed", "skipped", ""):
                with self.subTest(index=index, status=status):
                    key = f"steps.test{index}.outputs.status"
                    self.values[key] = status
                    result, output = self.run_step("summary")
                    self.values[key] = "passed"
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failure", output["overall_status"])

    def test_summary_requires_successful_install_even_if_checks_claim_success(self):
        self.values["steps.install.outputs.install_status"] = "failed"
        result, output = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", output["overall_status"])

    def test_summary_accepts_only_complete_six_test_success(self):
        result, output = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", output["overall_status"])
        self.assertEqual("6", output["passed"])
        self.assertEqual("0", output["failed"])
        self.assertEqual("0", output["skipped"])

    def test_candidate_uses_its_own_home_and_propagates_functional_failure(self):
        self.stub_download()
        self.stub("tar", '''
destination="${@: -1}"
mkdir -p "$destination/apache-ant-1.10.15/bin"
printf '#!/bin/bash\\ntest "$ANT_HOME" = "$(cd "$(dirname "$0")/.." && pwd)" || exit 91\\nexit "${FUNCTIONAL_EXIT:-0}"\\n' > "$destination/apache-ant-1.10.15/bin/ant"
chmod +x "$destination/apache-ant-1.10.15/bin/ant"
''')
        self.stub("unzip", 'echo "VERSION=${CANDIDATE_VERSION:-1.10.15}"\n')
        for version, code, mode in (("1.10.15", "0", "success"),
                                    ("1.10.15", "0", "fallback"),
                                    ("1.10.14", "0", "fallback"),
                                    ("1.10.15", "7", "fallback")):
            with self.subTest(version=version, code=code, mode=mode):
                result, output = self.run_step(
                    "test6", ANT_HOME="/wrong-baseline-home", FUNCTIONAL_EXIT=code,
                    CANDIDATE_VERSION=version, DOWNLOAD_MODE=mode,
                )
                passed = version == "1.10.15" and code == "0"
                self.assertEqual(passed, result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual("passed" if passed else "failed", output["status"])


if __name__ == "__main__":
    unittest.main()
