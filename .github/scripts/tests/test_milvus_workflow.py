"""Focused tests of the Milvus dependency rewrite and startup failure paths."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-milvus.yml"
UPSTREAM = "minio/minio:RELEASE.2023-03-20T20-16-18Z"
REPLACEMENT = (
    "quay.io/" + UPSTREAM
    + "@sha256:d6b74c01202ef9366bb88c304777e8d5d96c6b443e5dc8ac8e31f34469c495e7"
)
HELP_TEXT = """milvus run [server type] [flags]
\tStart a Milvus Server.
[flags]
\t-alias ''
\t\tSet alias
[server type]
\tstandalone
\tmixture
"""


def compose_fixture(version):
    return {
        "version": "3.5",
        "services": {
            "etcd": {"image": "quay.io/coreos/etcd:v3.5.18", "container_name": "milvus-etcd"},
            "minio": {
                "image": UPSTREAM,
                "container_name": "milvus-minio",
                "environment": {"MINIO_ACCESS_KEY": "minioadmin", "MINIO_SECRET_KEY": "minioadmin"},
                "ports": ["9001:9001", "9000:9000"],
                "volumes": ["${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data"],
                "command": 'minio server /minio_data --console-address ":9001"',
                "healthcheck": {"test": ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"],
                                "interval": "30s", "timeout": "20s", "retries": 3},
            },
            "standalone": {
                "image": f"milvusdb/milvus:v{version}",
                "container_name": "milvus-standalone",
                "command": ["milvus", "run", "standalone"],
                "environment": {"MINIO_ADDRESS": "minio:9000", "ETCD_ENDPOINTS": "etcd:2379"},
                "depends_on": ["etcd", "minio"],
                "ports": ["19530:19530", "9091:9091"],
            },
        },
        "networks": {"default": {"name": "milvus"}},
        "x-unrelated": {"image": UPSTREAM, "keep": True},
    }


class MilvusWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="milvus-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-milvus"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        self.compose = self.baseline / "compose.yml"
        self.compose.write_text(yaml.safe_dump(compose_fixture("2.5.6")))
        self.candidate = self.root / "candidate.yml"
        self.candidate.write_text(yaml.safe_dump(compose_fixture("2.5.7")))
        self.env = dict(os.environ, **self.job["env"], PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"), TMPDIR=str(self.root),
                        TRACE=str(self.root / "trace"), FIXTURE=str(self.candidate),
                        PINNED_MINIO=REPLACEMENT, HELP_OUTPUT=HELP_TEXT,
                        PYTHONDONTWRITEBYTECODE="1")
        self.values = {"steps.install_state.outputs.install_status": "success",
                       "steps.install.outputs.compose_path": str(self.compose),
                       "steps.install.outputs.work_dir": str(self.baseline),
                       "steps.install.outputs.standalone_image": "milvusdb/milvus:v2.5.6",
                       "steps.version.outputs.version": "2.5.6",
                       "steps.version.outputs.latest": "2.5.7",
                       "github.run_id": "12345"}
        self.stub("docker", r'''
import json, os, sys
from pathlib import Path
import yaml
args = sys.argv[1:]
with open(os.environ["TRACE"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
if args[0] == "compose":
    config = Path(args[args.index("-f") + 1])
    command = args[args.index("-f") + 2]
    if command == "up":
        data = yaml.safe_load(config.read_text())
        assert data["services"]["minio"]["image"] == os.environ["PINNED_MINIO"]
        print("compose startup diagnostic", flush=True)
        sys.exit(int(os.environ.get("UP_RC", "0")))
    if command == "config":
        print("compose configuration diagnostic")
        sys.exit(int(os.environ.get("CONFIG_RC", "0")))
    if command in ("ps", "logs"):
        print("compose " + command + " diagnostic")
        sys.exit(int(os.environ.get("DIAGNOSTIC_RC", "0")))
elif args[:2] == ["image", "inspect"]:
    print(os.environ.get("ARCH", "arm64"))
elif args[0] == "inspect":
    if args[-1] == "{{.Config.Image}}":
        print(os.environ.get("RUN_IMAGE", os.environ["EXPECTED_IMAGE"]))
    elif args[-1] == "{{.State.Health.Status}}":
        print(os.environ.get("HEALTH", "healthy"))
elif args[0] == "exec":
    print(os.environ["HELP_OUTPUT"])
    sys.exit(int(os.environ.get("STUB_HELP_RC", "0")))
''')
        self.stub("curl", 'import os, sys\nsys.exit(int(os.environ.get("CURL_RC", "0")))\n')
        self.stub("sleep", "pass\n")
        sudo = self.bin / "sudo"
        sudo.write_text('#!/bin/bash\nexec "$@"\n')
        sudo.chmod(0o755)
        download = self.root / ".github/scripts/download-with-fallback.sh"
        download.parent.mkdir(parents=True)
        download.write_text('#!/bin/bash\nset -euo pipefail\n[ "${DOWNLOAD_RC:-0}" = 0 ]\ncp "$FIXTURE" "$1"\n')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def rewrite(self):
        return subprocess.run([sys.executable, "-c", self.env["MILVUS_COMPOSE_MINIO_PATCH"], str(self.compose)],
                              capture_output=True, text=True, timeout=10)

    def run_step(self, step_id, values=None, **env):
        values = {**self.values, **(values or {})}

        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = key[1:-1] if key.startswith("'") else values.get(key)
                if value:
                    return str(value)
                if key.isdigit():
                    return key
            return ""

        # Relocate literal diagnostic paths before inserting fixture paths under /tmp.
        script = self.steps[step_id]["run"].replace("/tmp/milvus-", str(self.root / "milvus-"))
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        # Exercise the same Python body using the test environment's PyYAML.
        script = script.replace("/usr/bin/python3", sys.executable)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        (self.root / "trace").write_text("")
        expected = "milvusdb/milvus:v2.5.7" if step_id == "test6" else "milvusdb/milvus:v2.5.6"
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env=dict(self.env, EXPECTED_IMAGE=expected, **env),
                                capture_output=True, text=True, timeout=30)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        calls = [json.loads(line) for line in (self.root / "trace").read_text().splitlines()]
        return result, outputs, calls

    def test_pinned_versions_six_tests_and_yaml_dependency_are_preserved(self):
        self.assertEqual("2.5.6", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("2.5.7", self.job["env"]["NEXT_VERSION"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual([f"test{i}" for i in range(1, 7)], [s for s in self.steps if re.fullmatch(r"test\d", s)])
        self.assertIn('--packages "curl python3-yaml"', self.steps["install"]["run"])

    def test_rewrite_changes_only_minio_image_for_both_releases_and_is_idempotent(self):
        for version in ("2.5.6", "2.5.7"):
            for flow_style in (False, True):
                with self.subTest(version=version, flow_style=flow_style):
                    original = compose_fixture(version)
                    self.compose.write_text(yaml.safe_dump(original, default_flow_style=flow_style))
                    expected = copy.deepcopy(original)
                    expected["services"]["minio"]["image"] = REPLACEMENT
                    for _ in range(2):
                        result = self.rewrite()
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertEqual(expected, yaml.safe_load(self.compose.read_text()))

    def test_unknown_or_missing_dependency_and_invalid_yaml_fail_without_writing(self):
        fixtures = ["services: [", "null", "services: {}", "services: {minio: {}}"]
        for image in ("minio/minio:latest", "quay.io/" + UPSTREAM, UPSTREAM + "@sha256:bad", None):
            data = compose_fixture("2.5.6")
            data["services"]["minio"]["image"] = image
            fixtures.append(yaml.safe_dump(data))
        for source in fixtures:
            with self.subTest(source=source):
                self.compose.write_text(source)
                result = self.rewrite()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(source, self.compose.read_text())

    def test_baseline_and_candidate_success_reach_original_smoke_checks(self):
        for step in ("test4", "test6"):
            with self.subTest(step=step):
                result, output, calls = self.run_step(step)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", output["status"])
                self.assertTrue(any("up" in call for call in calls))
                if step == "test6":
                    self.assertEqual("next_install_validated", output["decision"])
                    self.assertEqual("2.5.7", output["next_installed_version"])
                    self.assertTrue(any("down" in call for call in calls))

    def test_linux_tmp_fixture_paths_are_not_rewritten_as_diagnostic_paths(self):
        with tempfile.TemporaryDirectory(prefix="milvus-workflow-", dir="/tmp") as directory:
            baseline = Path(directory) / "baseline"
            baseline.mkdir()
            compose = baseline / "compose.yml"
            compose.write_text(yaml.safe_dump(compose_fixture("2.5.6")))
            values = {
                "steps.install.outputs.compose_path": str(compose),
                "steps.install.outputs.work_dir": str(baseline),
            }
            for startup_rc in ("0", "17"):
                with self.subTest(startup_rc=startup_rc):
                    result, output, calls = self.run_step("test4", values=values, UP_RC=startup_rc)
                    self.assertEqual(int(startup_rc != "0"), int(result.returncode != 0))
                    self.assertEqual("passed" if startup_rc == "0" else "failed", output["status"])
                    self.assertIn("compose startup diagnostic", (self.root / "milvus-up.log").read_text())
                    if startup_rc != "0":
                        self.assertIn("compose startup diagnostic", result.stdout)
                    starts = [call for call in calls if "up" in call]
                    self.assertEqual(1, len(starts))
                    self.assertEqual(str(compose), starts[0][starts[0].index("-f") + 1])

    def test_startup_failure_prints_diagnostics_and_remains_failed_even_when_diagnostics_fail(self):
        for step in ("test4", "test6"):
            for diagnostic_rc in ("0", "1"):
                with self.subTest(step=step, diagnostic_rc=diagnostic_rc):
                    result, output, calls = self.run_step(step, UP_RC="17", DIAGNOSTIC_RC=diagnostic_rc)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", output["status"])
                    self.assertTrue(output["duration"].isdigit())
                    for message in ("startup", "ps", "logs"):
                        self.assertIn(f"compose {message} diagnostic", result.stdout)
                    self.assertFalse(any(call[0] in ("inspect", "exec") for call in calls))
                    if step == "test6":
                        self.assertEqual("next_install_failed", output["decision"])
                        self.assertEqual("install_failed", output["next_installed_version"])
                        self.assertTrue(any("down" in call for call in calls))

    def test_rewrite_failure_cannot_start_either_stack(self):
        for step, path in (("test4", self.compose), ("test6", self.candidate)):
            data = compose_fixture("2.5.6" if step == "test4" else "2.5.7")
            data["services"]["minio"]["image"] = "minio/minio:latest"
            path.write_text(yaml.safe_dump(data))
            result, output, calls = self.run_step(step)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
            self.assertIn("Unexpected MinIO dependency image", result.stderr)
            self.assertFalse(any("up" in call for call in calls))

    def test_candidate_download_config_and_runtime_failures_still_fail_and_clean_up(self):
        for env in ({"DOWNLOAD_RC": "1"}, {"CONFIG_RC": "1"}, {"CURL_RC": "1"},
                    {"ARCH": "amd64"}, {"RUN_IMAGE": "milvusdb/milvus:v2.5.6"},
                    {"HEALTH": "unhealthy"}, {"HELP_OUTPUT": "wrong command"}):
            with self.subTest(env=env):
                result, output, calls = self.run_step("test6", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertEqual("next_install_failed", output["decision"])
                self.assertTrue(any("down" in call for call in calls))

    def test_baseline_health_timeout_still_fails(self):
        result, output, _ = self.run_step("test4", CURL_RC="1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def assert_help_rejected(self, step, **env):
        result, output, calls = self.run_step(step, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", output["status"])
        self.assertTrue(output["duration"].isdigit())
        self.assertTrue(any("down" in call for call in calls))
        if "STUB_HELP_RC" in env:
            self.assertIn(f"Milvus standalone help exit code: {env['STUB_HELP_RC']}", result.stdout)
        if step == "test6":
            self.assertEqual("next_install_failed", output["decision"])

    def test_nonzero_help_error_matching_old_substring_fails_both_workflow_steps(self):
        for step in ("test5", "test6"):
            with self.subTest(step=step):
                self.assert_help_rejected(step, STUB_HELP_RC="17",
                                          HELP_OUTPUT="error:milvus run failed toinitialize")

    def test_genuine_help_with_any_nonzero_exit_is_rejected(self):
        for step in ("test5", "test6"):
            for rc in ("1", "17", "125", "126", "127", "137", "255"):
                with self.subTest(step=step, rc=rc):
                    self.assert_help_rejected(step, STUB_HELP_RC=rc)

    def test_zero_exit_requires_help_structure_without_error_diagnostics(self):
        invalid = ["", "milvus run", "error:milvus run failed toinitialize"]
        invalid.extend(HELP_TEXT.replace(marker, "") for marker in (
            "milvus run [server type] [flags]", "[flags]\n", "[server type]\n", "\tstandalone\n"))
        invalid.extend(HELP_TEXT + diagnostic for diagnostic in (
            "error: initialization problem", "FATAL: startup", "panic: startup",
            "initialization failed", "Unknown server type = --help"))
        for step in ("test5", "test6"):
            for output in invalid:
                with self.subTest(step=step, output=output):
                    self.assert_help_rejected(step, HELP_OUTPUT=output)

    def test_supported_standalone_help_succeeds_with_zero_exit(self):
        for step in ("test5", "test6"):
            with self.subTest(step=step):
                result, output, calls = self.run_step(step)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", output["status"])
                self.assertIn(["exec", "milvus-standalone", "/milvus/bin/milvus",
                               "run", "standalone", "--help"], calls)

    def test_summary_retains_all_six_failure_gates(self):
        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        result, output, _ = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", output["passed"])
        self.assertEqual("success", output["overall_status"])
        for i in range(1, 7):
            with self.subTest(test=i):
                result, output, _ = self.run_step("summary", {**values, f"steps.test{i}.outputs.status": "failed"})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", output["overall_status"])
                self.assertEqual("failing", output["badge_status"])
                self.assertEqual("1", output["failed"])
                self.assertEqual(str(int(i < 6)), output["core_failed"])


if __name__ == "__main__":
    unittest.main()
