"""Execute Gitness functional probes with deterministic Docker fixtures."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gitness.yml"


class GitnessWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gitness-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gitness"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.output = self.root / "output"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ,
            GITHUB_OUTPUT=str(self.output),
            RUNNER_TEMP=str(self.root),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            HTTP_BODY="<!DOCTYPE html><html><title>Gitness</title></html>",
            LOG_HAS_START="1",
            LOG_FAILURE="0",
        )
        self.stub("sudo", 'exec "$@"')
        self.stub("sleep", "exit 0")
        self.stub(
            "curl",
            """
printf '%s\n' "$HTTP_BODY"
exit "${HTTP_FAILURE:-0}"
""",
        )
        self.stub(
            "python3",
            """
cat >/dev/null
printf '3.0.1\n'
""",
        )
        self.stub(
            "docker",
            """
command=$1
shift
case "$command" in
  rm|pull)
    exit 0
    ;;
  image)
    test "$1" = inspect
    printf 'arm64\n'
    ;;
  run)
    if [[ " $* " == *" server --help "* ]]; then
      printf 'Usage: gitness server\n'
    else
      printf 'fixture-container\n'
    fi
    ;;
  logs)
    container=$1
    if [ "$LOG_FAILURE" != 0 ]; then
      printf 'docker logs failed\n' >&2
      exit "$LOG_FAILURE"
    fi
    if [ "$container" = gitness-next-version-probe ]; then
      printf '{"version":"3.0.1"}\n'
      exit 0
    fi
    if [ "$LOG_HAS_START" = 1 ]; then
      printf '{"message":"server started"}\n'
    else
      printf '{"message":"server starting"}\n'
    fi
    for _ in $(seq 1 20000); do
      printf '{"message":"additional startup detail"}\n'
    done
    ;;
  *)
    printf 'unexpected docker command: %s %s\n' "$command" "$*" >&2
    exit 64
    ;;
esac
""",
        )

    def tearDown(self):
        for path in (Path("/tmp/gitness-root.html"), Path("/tmp/gitness-next-root.html")):
            path.unlink(missing_ok=True)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def render_step(self, step_id):
        values = {
            "steps.install.outputs.baseline_image": "fixture-image",
            "steps.version.outputs.version || steps.install.outputs.baseline_version || env.BASELINE_VERSION": "3.0.0",
        }

        def expression(match):
            key = match.group(1).strip()
            if key not in values:
                raise AssertionError(f"unhandled workflow expression: {key}")
            return values[key]

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])

    def run_step(self, step_id, **extra_env):
        self.output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render_step(step_id)],
            cwd=self.root,
            env=dict(self.env, **extra_env),
            capture_output=True,
            text=True,
            timeout=15,
        )
        outputs = dict(
            line.split("=", 1) for line in self.output.read_text().splitlines()
        )
        return result, outputs

    def test_baseline_probe_avoids_legacy_sigpipe_false_negative(self):
        legacy = subprocess.run(
            [
                "bash",
                "-o",
                "pipefail",
                "-c",
                "sudo docker logs gitness-smoke 2>&1 | grep -qi 'server started'",
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(0, legacy.returncode)

        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs["status"])
        log = self.root / "gitness-smoke.log"
        self.assertIn('"message":"server started"', log.read_text())

    def test_baseline_probe_fails_without_each_required_signal(self):
        for env in (
            {"HTTP_BODY": "not html"},
            {"LOG_HAS_START": "0"},
            {"LOG_FAILURE": "19"},
        ):
            with self.subTest(env=env):
                result, outputs = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_candidate_probe_uses_same_strict_non_pipeline_log_check(self):
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual("next_install_validated", outputs["decision"])
        self.assertEqual("3.0.1", outputs["next_installed_version"])

        result, outputs = self.run_step("test6", LOG_HAS_START="0")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])


if __name__ == "__main__":
    unittest.main()
