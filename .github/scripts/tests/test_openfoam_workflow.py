"""Execute OpenFOAM workflow shells with fixtures, not native solver evidence."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-openfoam.yml"


class OpenfoamWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="openfoam-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("date", "grep", "cat", "tee", "mkdir", "mktemp", "cp", "test"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-openfoam"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(PATH=str(self.bin), HOME=str(self.root), RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"), **self.job.get("env", {}))
        self.project = self.root / "openfoam"
        (self.project / "etc").mkdir(parents=True)
        (self.project / "etc/controlDict").write_text("configuration fixture\n")
        tutorials = self.root / "examples"
        cavity = tutorials / "incompressible/icoFoam/cavity/cavity"
        for path in ("system/controlDict", "constant/transportProperties", "0/U", "0/p"):
            target = cavity / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("case fixture\n")
        self.env.update(WM_PROJECT_DIR=str(self.project), FOAM_TUTORIALS=str(tutorials),
                        EXPECTED_PROJECT=str(self.project), CALLS=str(self.root / "calls"))
        self.calls = 0
        self.tool("timeout", """
test "$1" = --kill-after=5s
case "$2" in 30s|120s) ;; *) exit 99 ;; esac
echo "timeout $*" >> "$CALLS"
shift 2
if [ "${1##*/}" = "${TIMEOUT_TOOL:-}" ]; then
  echo 'fixture timeout' >&2
  exit 124
fi
exec "$@"
""")
        self.values = {"steps.install.outcome": "success"}
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": "1"})

    def tool(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + script)
        path.chmod(0o755)

    def render(self, script):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.isdigit():
                    return term
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def run_step(self, name, **overrides):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"])],
            cwd=self.root, env={**self.env, **overrides}, capture_output=True,
            text=True, timeout=20)
        pairs = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(pairs)
        self.assertEqual(len(pairs), len(outputs), "Duplicate output keys")
        evidence = os.environ.get("WORKFLOW_EVIDENCE_ROOT")
        if evidence:
            self.calls += 1
            target = Path(evidence) / self._testMethodName / str(self.calls)
            target.mkdir(parents=True)
            (target / "source.sh").write_text(self.steps[name]["run"])
            (target / "rendered.sh").write_text(self.render(self.steps[name]["run"]))
            (target / "workflow-sha256.txt").write_text(
                hashlib.sha256(WORKFLOW.read_bytes()).hexdigest() + "\n")
            (target / "env.json").write_text(json.dumps({**self.env, **overrides}, indent=2))
            (target / "values.json").write_text(json.dumps(self.values, indent=2))
            (target / "stdout.txt").write_text(result.stdout)
            (target / "stderr.txt").write_text(result.stderr)
            (target / "github-output.txt").write_text(output.read_text())
            (target / "exit.txt").write_text(str(result.returncode) + "\n")
            fixtures = target / "fixtures"
            fixtures.mkdir()
            for path in self.bin.iterdir():
                if not path.is_symlink():
                    (fixtures / path.name).write_bytes(path.read_bytes())
        return result, outputs

    def assert_failed(self, result, outputs):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs.get("status"), "failed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def success_tools(self):
        for name, prefix in (("icoFoam", "ICO"), ("blockMesh", "MESH")):
            self.tool(name, f'TOOL={name}\nPREFIX={prefix}\n' + """
test "$WM_PROJECT_DIR" = "$EXPECTED_PROJECT"
test -s "$WM_PROJECT_DIR/etc/controlDict"
echo "$TOOL $*" >> "$CALLS"
if [ "$1" = -help ]; then
  test "$#" = 1
  TEXT_VAR="${PREFIX}_HELP_TEXT"
  RC_VAR="${PREFIX}_HELP_RC"
  printf '%s\n' "${!TEXT_VAR-Usage: $TOOL [OPTIONS]}"
  exit "${!RC_VAR:-0}"
fi
test "$#" = 2
test "$1" = -case
test -s "$2/system/controlDict"
if [ "$TOOL" = blockMesh ]; then
  mkdir -p "$2/constant/polyMesh"
  for field in points faces owner boundary; do
    if [ "${MISSING_FIELD:-}" != "constant/polyMesh/$field" ]; then
      printf 'mesh fixture\n' > "$2/constant/polyMesh/$field"
    fi
  done
  printf '%s\n' "${MESH_TEXT-End}"
  exit "${MESH_RC:-0}"
fi
mkdir -p "$2/0.5"
for field in U p; do
  if [ "${MISSING_FIELD:-}" != "0.5/$field" ]; then
    printf 'solution fixture\n' > "$2/0.5/$field"
  fi
done
printf '%s\n' "${ICO_TEXT-Time = 0.5
smoothSolver: Solving for Ux, Initial residual = 0.1, Final residual = 0
DICPCG: Solving for p, Initial residual = 0.1, Final residual = 0
End}"
exit "${ICO_RC:-0}"
""")
        # A working version helper must never substitute for either target.
        self.tool("foamVersion", "echo OpenFOAM-v1912\n")
        self.tool("foamExec", "echo OpenFOAM\n")

    def test_error_text_with_nonzero_exit_never_passes(self):
        for name in ("icoFoam", "blockMesh", "foamVersion", "foamExec"):
            self.tool(name, 'echo "OpenFOAM FATAL ERROR: case failed" >&2\nexit 42\n')
        for step in ("test3", "test5"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step)
                self.assert_failed(result, outputs)
                self.assertIn("OpenFOAM FATAL ERROR: case failed", result.stdout)
                self.assertIn("exit status: 42", result.stdout)

    def test_successful_help_is_target_specific_and_observable(self):
        self.success_tools()
        result, outputs = self.run_step("test3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        for tool in ("icoFoam", "blockMesh"):
            self.assertIn(f"Usage: {tool} [OPTIONS]", result.stdout)
            self.assertIn(f"{tool} -help exit status: 0; log writer: 0", result.stdout)
        calls = (self.root / "calls").read_text()
        self.assertNotIn("foamVersion", calls)
        self.assertNotIn("--help", calls)

    def test_help_requires_both_successful_exits_even_with_usage_output(self):
        self.success_tools()
        for prefix in ("ICO", "MESH"):
            with self.subTest(prefix=prefix):
                result, outputs = self.run_step("test3", **{f"{prefix}_HELP_RC": "42"})
                self.assert_failed(result, outputs)
                self.assertIn("exit status: 42", result.stdout)

    def test_help_rejects_empty_wrong_target_and_error_output_even_at_zero(self):
        self.success_tools()
        for prefix in ("ICO", "MESH"):
            for text in ("", "OpenFOAM version v1912", "Usage: other [OPTIONS]",
                         "OpenFOAM FATAL ERROR: case failed"):
                with self.subTest(prefix=prefix, text=text):
                    self.assert_failed(*self.run_step("test3", **{f"{prefix}_HELP_TEXT": text}))
        self.assert_failed(*self.run_step("test3", ICO_HELP_TEXT=
            "Usage: icoFoam [OPTIONS]\nFOAM FATAL ERROR: case failed"))

    def test_successful_functional_run_generates_mesh_and_solution(self):
        self.success_tools()
        result, outputs = self.run_step("test5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertIn("Time = 0.5", result.stdout)
        for tool in ("blockMesh", "icoFoam"):
            self.assertIn(f"{tool} exit status: 0; log writer: 0", result.stdout)
        for field in ("0.5/U", "0.5/p", "constant/polyMesh/points"):
            self.assertIn(f"Verified generated {field}", result.stdout)
        calls = (self.root / "calls").read_text()
        self.assertIn("blockMesh -case", calls)
        self.assertIn("icoFoam -case", calls)
        self.assertNotIn("-help", calls)

    def test_mesh_or_solver_nonzero_exit_fails_despite_complete_output(self):
        self.success_tools()
        for prefix in ("MESH", "ICO"):
            with self.subTest(prefix=prefix):
                result, outputs = self.run_step("test5", **{f"{prefix}_RC": "42"})
                self.assert_failed(result, outputs)
                self.assertIn("exit status: 42", result.stdout)

    def test_functional_output_must_prove_time_integration_and_completion(self):
        self.success_tools()
        for text in ("", "Usage: icoFoam [OPTIONS]", "Time = 0.5\nEnd",
                     "Time = 0.005\nSolving for Ux,\nSolving for p,\nEnd",
                     "Time = 0.5\nSolving for Ux,\nSolving for p,",
                     "Time = 0.5\nSolving for Ux,\nSolving for p,\nEnd\nFOAM FATAL ERROR"):
            with self.subTest(text=text):
                self.assert_failed(*self.run_step("test5", ICO_TEXT=text))
        self.assert_failed(*self.run_step("test5", MESH_TEXT="OpenFOAM"))

    def test_missing_generated_mesh_or_solution_fails(self):
        self.success_tools()
        for field in ("constant/polyMesh/points", "constant/polyMesh/faces",
                      "constant/polyMesh/owner", "constant/polyMesh/boundary", "0.5/U", "0.5/p"):
            with self.subTest(field=field):
                self.assert_failed(*self.run_step("test5", MISSING_FIELD=field))

    def test_missing_environment_case_or_binary_fails(self):
        self.success_tools()
        for step in ("test3", "test5"):
            with self.subTest(step=step):
                self.assert_failed(*self.run_step(step, WM_PROJECT_DIR=str(self.root / "absent")))
        self.assert_failed(*self.run_step("test5", FOAM_TUTORIALS=str(self.root / "absent")))
        (self.bin / "icoFoam").unlink()
        for step in ("test3", "test5"):
            self.assert_failed(*self.run_step(step))

    def test_stale_case_artifacts_are_not_accepted(self):
        self.success_tools()
        cavity = Path(self.env["FOAM_TUTORIALS"]) / "incompressible/icoFoam/cavity/cavity"
        for field in ("0.5", "constant/polyMesh"):
            (cavity / field).mkdir()
            self.assert_failed(*self.run_step("test5"))
            (cavity / field).rmdir()

    def test_timeouts_and_log_writer_errors_fail_closed(self):
        self.success_tools()
        for step in ("test3", "test5"):
            for tool in ("icoFoam", "blockMesh"):
                with self.subTest(step=step, tool=tool):
                    result, outputs = self.run_step(step, TIMEOUT_TOOL=tool)
                    self.assert_failed(result, outputs)
                    self.assertIn("exit status: 124", result.stdout)
        (self.bin / "tee").unlink()
        self.tool("tee", "cat >/dev/null\nexit 74\n")
        for step in ("test3", "test5"):
            result, outputs = self.run_step(step)
            self.assert_failed(result, outputs)
            self.assertIn("log writer: 74", result.stdout)

    def test_summary_rejects_failed_raw_outcomes_despite_passed_output(self):
        for number in range(1, 6):
            key = f"steps.test{number}.outcome"
            for outcome in ("failure", "cancelled", "skipped", ""):
                self.values[key] = outcome
                with self.subTest(step=number, outcome=outcome):
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(outputs["badge_status"], "failing")
                    self.assertEqual(outputs["core_failed"], "1")
            self.values[key] = "success"

    def test_summary_requires_passed_outputs_and_counts_core_failures(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {"passed": "5", "failed": "0", "core_failed": "0",
                                  "duration": "5", "overall_status": "success",
                                  "badge_status": "passing"})
        for number in range(1, 6):
            key = f"steps.test{number}.outputs.status"
            for status in ("failed", "skipped", ""):
                self.values[key] = status
                result, outputs = self.run_step("summary")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["core_failed"], "1")
            self.values[key] = "passed"

    def test_distro_paths_apt_policy_and_free_arm_runner_are_preserved(self):
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.job["env"]["WM_PROJECT_DIR"], "/usr/share/openfoam")
        self.assertEqual(self.job["env"]["FOAM_TUTORIALS"],
                         "/usr/share/doc/openfoam-examples/examples")
        self.assertIn("sudo apt-get install -y openfoam; then", self.steps["install"]["run"])
        self.assertIn("decision=not_applicable_package_manager", self.steps["test6"]["run"])
        for step in ("test3", "test5"):
            self.assertNotIn("source ", self.steps[step]["run"])
            self.assertNotIn("|| true", self.steps[step]["run"])
            self.assertIn("timeout --kill-after=5s", self.steps[step]["run"])

    def test_existing_auditor_sees_status_and_duration_for_tests3_and5(self):
        for name in ("test3", "test5"):
            step = self.steps[name]
            for output in ("status", "duration"):
                with self.subTest(step=name, output=output):
                    self.assertTrue(audit._step_emits_output(WORKFLOW.parents[2], step, output))
            with self.subTest(step=name, output="literal statuses"):
                self.assertEqual(set(audit._step_literal_outputs(
                    WORKFLOW.parents[2], step, "status")), {"passed", "failed"})


if __name__ == "__main__":
    unittest.main()
