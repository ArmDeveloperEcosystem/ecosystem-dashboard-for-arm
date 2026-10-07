"""Offline OpenGauss workflow fault tests; Docker fixtures are not Arm evidence."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-opengauss.yml"


class OpenGaussWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="opengauss-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-opengauss"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fixture = self.root / "fixture.tar"
        fixture.write_bytes(b"unit test download fixture, not a Docker image\n")
        digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
        self.env = dict(os.environ | self.job["env"],
                        OPENGAUSS_ARCHIVE_SHA256=digest, OPENGAUSS_NEXT_ARCHIVE_SHA256=digest,
                        GITHUB_WORKSPACE=str(self.root), GITHUB_RUN_ID="unit",
                        RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"), TRACE=str(self.root / "trace"),
                        FIXTURE=str(fixture), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.values = {"steps.install.outputs.install_status": "success",
                       "steps.install.outputs.container_name": "baseline",
                       "steps.install.outputs.image_arch": "arm64",
                       "steps.version.outputs.version": "7.0.0-RC2"}
        self.script("bin/sudo", 'exec "$@"\n')
        self.script("bin/timeout", 'shift\nexec "$@"\n')
        self.script("bin/systemctl", "exit 0\n")
        self.script("bin/sleep", "exit 0\n")
        self.script("bin/uname", 'printf "%s\\n" "${HOST_ARCH:-aarch64}"\n')
        self.script(".github/scripts/download-with-fallback.sh", '''
printf 'download %s\n' "$2" >> "$TRACE"
[ "${DOWNLOAD_RC:-0}" = 0 ] || exit "$DOWNLOAD_RC"
cp "$FIXTURE" "$1"
''')
        docker = self.bin / "docker"
        docker.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["TRACE"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[0] == "load":
    print("Loaded image: opengauss:fixture")
    sys.exit(int(os.environ.get("LOAD_RC", "0")))
elif args[0] == "inspect":
    print(os.environ.get("STATE", "running"))
elif args[:2] == ["image", "inspect"]:
    print(os.environ.get("IMAGE_ARCH", "arm64"))
elif args[0] == "exec":
    command = " ".join(args)
    if "command -v su" in command:
        sys.exit(0)
    if "select version();" in command:
        default = "7.0.0" if "next" in args[1] else "7.0.0-RC2"
        print("(openGauss " + os.environ.get("SQL_VERSION", default) + " build fixture)")
    elif "--help" in command:
        print("Usage: gsql")
    elif "select 1;" in command:
        print("1")
    sys.exit(int(os.environ.get("SQL_RC", "0")))
''')
        docker.chmod(0o755)

    def script(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_step(self, step, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(term, "")
                if value or term.isdigit():
                    return str(value or term)
            return ""
        script = self.steps[step]["run"].replace("/tmp/opengauss-", str(self.root / "opengauss-"))
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        Path(self.env["TRACE"]).write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **environment),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_published_archives_keep_arm_runtime_and_six_checks(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual([f"test{i}" for i in range(1, 7)],
                         [step for step in self.steps if re.fullmatch(r"test\d", step)])
        for prefix, version, os_name, sha in [
            ("OPENGAUSS", "7.0.0-RC2", "openEuler22.03", "16a204e817263bce4b2c920da83ee509e3b54fbe274df1e081663a12804f1725"),
            ("OPENGAUSS_NEXT", "7.0.0", "openEuler24.03", "93147e61b5793c29f21bb630fc263de9b7dd3f5490c05bcf21ae4964657e21c9"),
        ]:
            self.assertEqual(version, self.job["env"][prefix + "_VERSION"])
            self.assertEqual(f"https://opengauss.obs.cn-south-1.myhuaweicloud.com/{version}/{os_name}/arm/openGauss-Docker-{version}-aarch64.tar",
                             self.job["env"][prefix + "_ARCHIVE_URL"])
            self.assertEqual(sha, self.job["env"][prefix + "_ARCHIVE_SHA256"])
        for step in ("install", "version", "test1", "test2", "test3", "test4", "test5", "test6"):
            result, output = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            if step.startswith("test"):
                self.assertEqual("passed", output["status"])
        trace = Path(self.env["TRACE"]).read_text()
        self.assertIn("select version();", trace)
        self.assertIn("select 1;", trace)
        self.assertIn('"image", "inspect"', trace)

    def test_download_errors_and_checksums_block_docker_load_in_both_lanes(self):
        for step, checksum in [("install", "OPENGAUSS_ARCHIVE_SHA256"),
                               ("test6", "OPENGAUSS_NEXT_ARCHIVE_SHA256")]:
            for environment in ({"DOWNLOAD_RC": "22"}, {checksum: "0" * 64}):
                with self.subTest(step=step, environment=environment):
                    result, output = self.run_step(step, **environment)
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotEqual("passed", output.get("status"))
                    self.assertNotEqual("success", output.get("install_status"))
                    self.assertNotIn('["load"', Path(self.env["TRACE"]).read_text())

    def test_sql_version_mismatch_is_not_reported_as_requested_version(self):
        (self.root / "opengauss-baseline-version.txt").write_text("(openGauss 6.0.0 build fixture)\n")
        result, output = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", output)
        for step in ("test2", "test6"):
            result, output = self.run_step(step, SQL_VERSION="7.0.0-other")
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", output.get("status"))

    def test_candidate_load_runtime_and_architecture_failures_remain_failures(self):
        for environment in ({"LOAD_RC": "1"}, {"SQL_RC": "1", "STATE": "exited"},
                            {"IMAGE_ARCH": "amd64"}):
            result, output = self.run_step("test6", **environment)
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", output.get("status"))

    def test_optional_accelerator_is_excluded_without_replacing_sql_checks(self):
        mount = f"type=bind,source={self.root}/opengauss-no-kvecturbo,target=/usr/local/sra_recall/lib,readonly"
        for step in ("install", "test6"):
            result, _ = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            calls = [json.loads(line) for line in Path(self.env["TRACE"]).read_text().splitlines()
                     if line.startswith("[")]
            starts = [call for call in calls if call[0] == "run"]
            self.assertEqual(1, len(starts))
            self.assertIn(mount, starts[0])
            self.assertIn("OTHER_PG_CONF=logging_collector=off", starts[0])
            self.assertEqual([], list((self.root / "opengauss-no-kvecturbo").iterdir()))
            self.assertTrue(any("select version();" in " ".join(call) for call in calls))
        self.assertIn("PQ functionality and default-image accelerator compatibility are not validated", self.steps["test6"]["run"])

    def test_dead_baseline_fails_before_any_sql_success_can_be_reported(self):
        result, output = self.run_step("install", STATE="exited")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["install_status"])
        self.assertNotIn("select version();", Path(self.env["TRACE"]).read_text())

    def test_rc_same_release_and_failed_baseline_are_not_skips(self):
        for version in ("7.0.0-RC3", "7.0.0-RC2"):
            result, output = self.run_step("test6", OPENGAUSS_NEXT_VERSION=version)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
            self.assertEqual("next_install_failed", output["decision"])
        self.values["steps.install.outputs.install_status"] = "failed"
        result, output = self.run_step("test6")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])


if __name__ == "__main__":
    unittest.main()
