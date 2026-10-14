"""Exercise bounded recovery in the actual package workflow scripts."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]


class SmokeDownloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="smoke-download-recovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TMPDIR=str(self.root), GITHUB_OUTPUT=str(self.root / "outputs"),
                        CALLS=str(self.root / "calls"), PINOT_INSTALL_STATUS="success")
        self.stub("sleep", "exit 0")
        self.stub("timeout", '''
printf 'timeout %s\n' "$*" >> "$CALLS"
if [ "$1" = --kill-after=10s ]; then
  shift
  if [ "$1" = "${TIMED_OUT_BUDGET:-}" ]; then exit 124; fi
fi
shift
exec "$@"
''')
        self.stub(".github/scripts/download-with-fallback.sh", '''
printf 'download %s\n' "$*" >> "$CALLS"
case "$2" in
  *maven*) test "${MAVEN_FAIL:-0}" = 0 ;;
  *) test "${ARCHIVE_FAIL:-0}" = 0 ;;
esac
touch "$1"
''', directory=self.root)
        self.stub("java", '''
test "${JAVA_FAIL:-0}" = 0
case "$*" in
  *QuickStart*) echo 'No QuickStart type provided' ;;
  *AddTable*) echo 'Usage: AddTable -tableConfigFile' ;;
esac
''')
        self.stub("tar", '''
test "${EXTRACT_FAIL:-0}" = 0
while [ "$1" != -C ]; do shift; done
root="$2/apache-dolphinscheduler-${DOLPHINSCHEDULER_NEXT_VERSION}-bin"
mkdir -p "$root/master-server/bin" "$root/master-server/conf" "$root/libs"
touch "$root/master-server/bin/start.sh" "$root/master-server/conf/application.yaml"
if [ "${MISSING_JARS:-0}" = 0 ]; then
  touch "$root/libs/dolphinscheduler-service-${DOLPHINSCHEDULER_NEXT_VERSION}.jar"
fi
''')

    def stub(self, name, body, directory=None):
        path = (directory or self.bin) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def run_step(self, slug, **environment):
        job = yaml.safe_load((ROOT / f".github/workflows/test-{slug}.yml").read_text())["jobs"][f"test-{slug}"]
        step = next(item for item in job["steps"] if item.get("id") == "test6")
        values = {f"env.{key}": value for key, value in job["env"].items()}
        values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)})
        values["steps.install.outputs.install_status"] = "success"
        if slug == "dolphinscheduler":
            values["steps.version.outputs.version"] = job["env"]["DOLPHINSCHEDULER_VERSION"]

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""

        script = step.get("run") or step["with"]["limited_cpu_probe"]
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        Path(self.env["GITHUB_OUTPUT"]).write_text("")
        Path(self.env["CALLS"]).write_text("")
        result = subprocess.run(["/bin/bash", "-euo", "pipefail", "-c", script],
                                cwd=self.root, env={**self.env, **job["env"], **environment},
                                text=True, capture_output=True, timeout=15)
        output = dict(line.split("=", 1) for line in Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        return result, output, Path(self.env["CALLS"]).read_text()

    def test_pinot_timeout_reaches_maven_and_checks_real_cli_paths(self):
        result, output, calls = self.run_step("pinot", TIMED_OUT_BUDGET="5m")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("1.3.0", output["next_installed_version"])
        self.assertIn("timeout --kill-after=10s 5m bash .github/scripts/download-with-fallback.sh", calls)
        self.assertIn("repo.maven.apache.org/maven2/org/apache/pinot/pinot-tools/1.3.0/", calls)
        self.assertIn("PinotAdministrator QuickStart", calls)
        self.assertIn("PinotAdministrator AddTable -help", calls)

    def test_pinot_missing_maven_artifact_or_bad_cli_still_fails(self):
        for failure in ("MAVEN_FAIL", "JAVA_FAIL"):
            with self.subTest(failure=failure):
                result, output, _ = self.run_step("pinot", TIMED_OUT_BUDGET="5m", **{failure: "1"})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])

    def test_dolphinscheduler_current_candidate_keeps_baseline_and_layout_checks(self):
        result, output, calls = self.run_step("dolphinscheduler")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("3.2.1", output["current_version"])
        self.assertEqual("3.4.3", output["next_installed_version"])
        self.assertEqual("passed", output["status"])
        self.assertIn("timeout --kill-after=10s 20m bash .github/scripts/download-with-fallback.sh", calls)
        self.assertIn("https://downloads.apache.org/dolphinscheduler/3.4.3/apache-dolphinscheduler-3.4.3-bin.tar.gz", calls)

    def test_dolphinscheduler_timeout_and_invalid_archives_fail(self):
        for environment in ({"TIMED_OUT_BUDGET": "20m"}, {"ARCHIVE_FAIL": "1"},
                            {"EXTRACT_FAIL": "1"}, {"MISSING_JARS": "1"}):
            with self.subTest(environment=environment):
                result, output, _ = self.run_step("dolphinscheduler", **environment)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])

    def cni_fixture(self):
        source = self.root / "next-src"
        source.mkdir()
        (source / "go.mod").write_text("module github.com/aws/amazon-vpc-cni-k8s\n")
        (source / "main.go").write_text("package main\n")
        (source / "cni.yaml").write_text("kind: DaemonSet\n")
        self.stub("uname", "echo aarch64")
        self.stub("file", 'echo "${BINARY_ARCH:-ELF ARM aarch64}"')
        self.stub("go", '''
printf 'go %s\n' "$*" >> "$CALLS"
test "$GOARCH" = arm64 && test "$GOOS" = linux && test "$CGO_ENABLED" = 0
case "$1" in
  list)
    count=$(grep -c '^go list ' "$CALLS")
    test "$count" -gt "${LIST_FAILURES:-0}"
    echo github.com/aws/amazon-vpc-cni-k8s ;;
  build)
    test "${BUILD_FAIL:-0}" = 0
    touch "$3" ;;
esac
''')

    def test_cni_retries_package_discovery_then_builds(self):
        self.cni_fixture()
        for failures in ("0", "1", "2"):
            with self.subTest(failures=failures):
                result, _, calls = self.run_step("amazon-vpc-cni-k8s", LIST_FAILURES=failures)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(int(failures) + 1, calls.splitlines().count("go list ./..."))
                self.assertIn("timeout --kill-after=10s 180s go list ./...", calls)
                self.assertIn("go build -o", calls)

    def test_cni_three_failed_attempts_or_timeouts_do_not_build(self):
        self.cni_fixture()
        for environment in ({"LIST_FAILURES": "3"}, {"TIMED_OUT_BUDGET": "180s"}):
            result, _, calls = self.run_step("amazon-vpc-cni-k8s", **environment)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(3, calls.count("timeout --kill-after=10s 180s"))
            self.assertNotIn("go build -o", calls)

    def test_cni_build_and_architecture_failures_are_not_retried_or_hidden(self):
        self.cni_fixture()
        for environment in ({"BUILD_FAIL": "1"}, {"BINARY_ARCH": "ELF x86-64"}):
            result, _, calls = self.run_step("amazon-vpc-cni-k8s", **environment)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(1, calls.count("go build -o"))
        (self.root / "next-src/cni.yaml").write_text("unrelated: data\n")
        result, _, _ = self.run_step("amazon-vpc-cni-k8s")
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
