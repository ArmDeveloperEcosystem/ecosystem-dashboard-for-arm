"""Exercise Restreamer readiness, release discovery, and fail-closed accounting."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-restreamer.yml"


class RestreamerWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="restreamer-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-restreamer"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        DOCKER_CALLS=str(self.root / "docker-calls"),
                        CONTAINER_FILE=str(self.root / "container-name"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.stub("uname", 'echo "${TEST_ARCH:-aarch64}"')
        self.stub("sleep", 'exit 0')
        self.stub("docker", '''
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
if [ "$1" = "${DOCKER_FAILURE:-}" ]; then echo "docker $1 failed" >&2; exit 2; fi
case "$1" in
  manifest)
    printf '{"manifests":[{"platform":{"architecture":"%s","os":"linux"}}]}\\n' "${MANIFEST_ARCH:-arm64}" ;;
  image) echo "${IMAGE_ARCH:-arm64}" ;;
  create)
    test "$2" = --name
    test "$4" = -p && test "$5" = 127.0.0.1::8080
    printf '%s' "$3" > "$CONTAINER_FILE"
    echo container-id ;;
  port) echo 127.0.0.1:19384 ;;
  inspect) echo "${CONTAINER_RUNNING:-true}" ;;
  rm) test "$2" = -f && test "$3" = "$(cat "$CONTAINER_FILE")" ;;
esac
''')
        self.stub("curl", '''
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then shift; TARGET="$1"; fi
  shift
done
printf '%s' "${HTTP_BODY-<html>Restreamer</html>}" > "$TARGET"
if [ "${HTTP_FAILURE:-0}" != 0 ]; then
  echo "curl: Restreamer connection or HTTP failure" >&2
  exit "$HTTP_FAILURE"
fi
''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, **env):
        values = {**{f"steps.test{i}.outcome": "success" for i in range(1, 7)}, **(values or {})}

        def expression(match):
            parts = match[1].split("||")
            return values.get(parts[0].strip()) or (parts[1].strip().strip("'") if len(parts) > 1 else "")

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_historical_source_markers_match_v010_and_missing_source_fails(self):
        _, expectations = self.run_step("expectations")
        values = {"steps.install.outputs.install_mode": "github_source",
                  "steps.install.outputs.install_status": "success",
                  "steps.expectations.outputs.source_markers": expectations["source_markers"]}
        source = self.root / "baseline-src"
        source.mkdir()
        (source / "README.md").touch()
        result, outputs = self.run_step("test1", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        for name in ("src", "conf"):
            (source / name).mkdir()
        for name in ("package.json", "Dockerfile-arm64v8"):
            (source / name).touch()
        result, outputs = self.run_step("test1", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_http_success_requires_product_content_and_running_arm64_container(self):
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        calls = Path(self.env["DOCKER_CALLS"]).read_text()
        name = Path(self.env["CONTAINER_FILE"]).read_text()
        self.assertTrue(name.startswith("restreamer-smoke-"))
        self.assertIn("pull --platform linux/arm64 datarhei/restreamer:2.12.0", calls)
        self.assertIn(f"rm -f {name}", calls)
        self.assertNotIn("rm -f restreamer-next-smoke\n", calls)

    def test_http_errors_and_nonempty_error_bodies_cannot_pass(self):
        for env in ({"HTTP_FAILURE": "7"}, {"HTTP_FAILURE": "22"},
                    {"HTTP_BODY": ""}, {"HTTP_BODY": "<html>Unrelated service</html>"},
                    {"CONTAINER_RUNNING": "false"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                name = Path(self.env["CONTAINER_FILE"]).read_text()
                self.assertIn(f"rm -f {name}", Path(self.env["DOCKER_CALLS"]).read_text())

    def test_manifest_pull_start_and_architecture_failures_cannot_pass(self):
        for env in ({"TEST_ARCH": "x86_64"}, {"MANIFEST_ARCH": "amd64"},
                    {"IMAGE_ARCH": "amd64"}, {"DOCKER_FAILURE": "manifest"},
                    {"DOCKER_FAILURE": "pull"}, {"DOCKER_FAILURE": "create"},
                    {"DOCKER_FAILURE": "start"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                if env.get("DOCKER_FAILURE") == "start":
                    name = Path(self.env["CONTAINER_FILE"]).read_text()
                    self.assertIn(f"rm -f {name}", Path(self.env["DOCKER_CALLS"]).read_text())

    def resolve_candidate(self, pages, current="2.12.0"):
        script = self.steps["test6"]["run"].split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        responses = [io.StringIO(json.dumps(page)) for page in pages]
        output = io.StringIO()
        with patch.dict(os.environ, RESTREAMER_RUNTIME_VERSION=current), \
             patch("urllib.request.urlopen", side_effect=responses), contextlib.redirect_stdout(output):
            exec(compile(script, str(WORKFLOW), "exec"), {})
        return output.getvalue().strip()

    def test_candidate_discovery_uses_current_version_and_all_pages(self):
        def tag(name, arch="arm64"):
            return {"name": name, "images": [{"architecture": arch, "os": "linux"}]}

        pages = [{"results": [tag("2.12.0"), tag("2.20.0-dev"), tag("2.14.0", "amd64")],
                  "next": "https://hub.docker.com/v2/repositories/datarhei/restreamer/tags?page=2"},
                 {"results": [tag("2.13.0"), tag("2.15.0")], "next": None}]
        self.assertEqual("2.13.0", self.resolve_candidate(pages))
        self.assertEqual("2.15.0", self.resolve_candidate(pages, current="2.13.0"))
        self.assertEqual("", self.resolve_candidate(pages, current="2.15.0"))

    def test_invalid_release_responses_never_become_safe_skips(self):
        for page in ({}, {"results": [], "next": "https://example.com/"},
                     {"results": None, "next": None}, {"results": []}):
            with self.subTest(page=page), self.assertRaises((AssertionError, KeyError)):
                self.resolve_candidate([page])

    def test_candidate_runtime_failure_and_failed_baseline_are_truthful(self):
        self.stub("python3", 'cat >/dev/null; echo 2.13.0')
        values = {"steps.test5.outputs.status": "failed"}
        result, outputs = self.run_step("test6", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("smoke status: failed", outputs["comparison"])
        result, outputs = self.run_step("test6", values, HTTP_FAILURE="22")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])
        self.assertEqual("not_installed", outputs["next_installed_version"])

    def test_summary_rejects_missing_core_results_and_unapproved_skips(self):
        for number in range(1, 7):
            for status in ("", "failed", "skipped"):
                with self.subTest(number=number, status=status):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                    values[f"steps.test{number}.outputs.status"] = status
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(number < 6)), outputs["core_failed"])
        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
        values.update({"steps.test6.outputs.status": "skipped",
                       "steps.test6.outputs.decision": "no_newer_stable_available"})
        result, outputs = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("5", outputs["passed"])
        self.assertEqual("1", outputs["skipped"])
        self.assertEqual("success", outputs["overall_status"])


    def test_passed_output_cannot_hide_failed_cancelled_or_missing_outcome(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", ""):
                with self.subTest(number=number, outcome=outcome):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                    values[f"steps.test{number}.outcome"] = outcome
                    result, outputs = self.run_step("summary", values)
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
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("0", outputs["core_failed"])


if __name__ == "__main__":
    unittest.main()
