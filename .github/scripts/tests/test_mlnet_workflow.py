"""ML.NET workflow error propagation; native workload proof is recorded separately."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-mlnet.yml"


class MLNetWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mlnet-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-mlnet"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        DOTNET_CALLS=str(self.root / "dotnet-calls"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.stub("uname", 'echo "${TEST_ARCH:-aarch64}"')
        self.stub("timeout", 'shift; exec "$@"')
        self.stub("git", 'test "$*" = "-C next-src describe --tags --exact-match"; echo "${TEST_TAG:-v5.0.0}"')
        self.stub("dotnet", '''
printf '%s|%s\\n' "$PWD" "$*" >> "$DOTNET_CALLS"
if [ "$1" = "${DOTNET_FAILURE:-}" ]; then
  echo "dotnet $1 failed: restore, build, or numeric assertion failure" >&2
  exit 7
fi
if [ "$1" = add ]; then
  test "$*" = "add package Microsoft.ML --version $SMOKE_VERSION"
  mkdir -p obj
  printf '{"libraries":{"Microsoft.ML/%s":{}}}\\n' "${ASSET_VERSION:-$SMOKE_VERSION}" > obj/project.assets.json
fi
if [ "$1" = build ]; then
  mkdir -p bin/Release/net8.0
  printf '{"libraries":{"Microsoft.ML/%s":{}}}\\n' "${BUILT_VERSION:-$SMOKE_VERSION}" > bin/Release/net8.0/smoke.deps.json
fi
''')
        candidate = self.root / "next-src"
        (candidate / "src").mkdir(parents=True)
        (candidate / "README.md").write_text("Machine Learning for .NET")
        (candidate / "Microsoft.ML.sln").write_text("Microsoft.ML")

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

    def test_smoke_preserves_restore_build_and_runtime_failures(self):
        for command in ("add", "build", "run"):
            with self.subTest(command=command):
                result, outputs = self.run_script(self.steps["test5"]["run"], DOTNET_FAILURE=command)
                self.assertEqual(7, result.returncode, result.stderr)
                self.assertEqual("failed", outputs["status"])
                self.assertIn(f"dotnet {command} failed", result.stderr)
                self.assertIn("duration", outputs)

    def test_smoke_rejects_wrong_architecture_or_restored_version(self):
        for env in ({"TEST_ARCH": "x86_64"}, {"ASSET_VERSION": "1.6.1"}):
            with self.subTest(env=env):
                result, outputs = self.run_script(self.steps["test5"]["run"], **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_summary_fails_for_each_missing_failed_or_skipped_core_result(self):
        for number in range(1, 6):
            for status in ("", "failed", "skipped", "invalid"):
                with self.subTest(number=number, status=status):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                    values[f"steps.test{number}.outputs.status"] = status
                    result, outputs = self.run_script(self.steps["summary"]["run"], values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("1", outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])

    def test_summary_allows_only_evidenced_regression_pass_or_safe_skip(self):
        for status, decision, failed, skipped in (
            ("passed", "limited_cpu_smoke_validated", 0, 0),
            ("skipped", "no_newer_stable_available", 0, 1),
            ("skipped", "runtime_validation_not_automated", 1, 0),
            ("", "no_newer_stable_available", 1, 0),
            ("failed", "limited_cpu_smoke_failed", 1, 0),
        ):
            with self.subTest(status=status, decision=decision):
                values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
                values.update({"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision})
                result, outputs = self.run_script(self.steps["summary"]["run"], values)
                self.assertEqual(failed, result.returncode, result.stderr)
                self.assertEqual(str(failed), outputs["failed"])
                self.assertEqual(str(skipped), outputs["skipped"])
                self.assertEqual("0", outputs["core_failed"])

    def test_candidate_source_probe_rejects_incorrect_solution_identity(self):
        candidate = self.root / "next-src"
        (candidate / "Microsoft.ML.sln").write_text("unrelated solution")
        result, _ = self.run_candidate()
        self.assertNotEqual(0, result.returncode)
        (candidate / "Microsoft.ML.sln").write_text("Microsoft.ML")
        result, _ = self.run_candidate()
        self.assertEqual(0, result.returncode, result.stderr)

    def run_candidate(self, **env):
        candidate_env = dict(CURRENT_VERSION="1.6.0", LATEST_VERSION="5.0.0", CANDIDATE_TAG="v5.0.0")
        candidate_env.update(env)
        return self.run_script(self.steps["test6"]["with"]["limited_cpu_probe"], **candidate_env)

    def test_candidate_restores_builds_and_runs_its_own_exact_version(self):
        result, _ = self.run_candidate()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = Path(self.env["DOTNET_CALLS"]).read_text()
        self.assertIn("add package Microsoft.ML --version 5.0.0", calls)
        self.assertIn("build --no-restore --configuration Release", calls)
        self.assertIn("run --no-build --configuration Release", calls)
        self.assertNotIn("1.6.0", calls)

    def test_candidate_rejects_baseline_substitution_and_failed_runtime(self):
        cases = ({"LATEST_VERSION": "1.6.0"}, {"CANDIDATE_TAG": "v1.6.0"},
                 {"TEST_TAG": "v4.0.0"}, {"ASSET_VERSION": "1.6.0"},
                 {"BUILT_VERSION": "1.6.0"}, {"DOTNET_FAILURE": "add"},
                 {"DOTNET_FAILURE": "build"}, {"DOTNET_FAILURE": "run"})
        for env in cases:
            with self.subTest(env=env):
                result, _ = self.run_candidate(**env)
                self.assertNotEqual(0, result.returncode)

    def test_composite_never_reports_failed_candidate_as_installed(self):
        action = WORKFLOW.parents[1] / "actions/generic-source-regression-check/action.yml"
        script = yaml.safe_load(action.read_text())["runs"]["steps"][0]["run"]
        helper = re.search(r"(?ms)^run_limited_cpu_probe\(\) \{.*?^\}", script)[0]
        script = helper + '\nrun_limited_cpu_probe "$LATEST_VERSION" "$CANDIDATE_TAG"\n'
        for failure in ("", "run"):
            with self.subTest(failure=failure):
                result, outputs = self.run_script(
                    script, CURRENT="1.6.0", LATEST_VERSION="5.0.0", CANDIDATE_TAG="v5.0.0",
                    REPO="dotnet/machinelearning", DEFER_ON_LIMITED_CPU_PROBE_FAILURE="false",
                    LIMITED_CPU_PROBE=self.steps["test6"]["with"]["limited_cpu_probe"],
                    LIMITED_CPU_DESCRIPTION=self.steps["test6"]["with"]["limited_cpu_description"],
                    DOTNET_FAILURE=failure,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("failed" if failure else "passed", outputs["status"])
                self.assertEqual("limited_cpu_probe_failed" if failure else "5.0.0",
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
