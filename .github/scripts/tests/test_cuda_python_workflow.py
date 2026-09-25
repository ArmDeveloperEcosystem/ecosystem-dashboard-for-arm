"""Run CUDA Python's source preflight and summary with failure fixtures."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-cuda-python.yml"


class CudaPythonWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="cuda-python-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-cuda-python"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], GITHUB_OUTPUT=str(self.root / "output"))
        self.probe = job["env"]["SCOPED_ARM_PREFLIGHT_PROBE"]

    def preflight(self, directory="baseline-src", machine="aarch64"):
        code = self.probe.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        script = (
            "from unittest.mock import patch\n"
            f"with patch('platform.machine', return_value={machine!r}):\n"
            f"    exec(compile({code!r}, '<workflow-preflight>', 'exec'))\n"
        )
        return subprocess.run(
            [sys.executable, "-c", script], cwd=self.root,
            env=dict(self.env, PREFLIGHT_SOURCE_DIR=directory),
            capture_output=True, text=True, timeout=10,
        )

    def source(self, directory, layout, code="# CUDA Python\nvalue = 1\n"):
        package = self.root / directory / layout
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(code)

    def test_legacy_and_current_layouts_compile(self) -> None:
        for directory, layout in (("baseline-src", "cuda"), ("next-src", "cuda_bindings")):
            with self.subTest(layout=layout):
                self.source(directory, layout)
                result = self.preflight(directory)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn(f"python_compile:{layout}", result.stdout)
                manifest = (self.root / ".arm-preflight/cuda-python-manifest.txt").read_text()
                self.assertIn(f"source_root={self.root / directory}", manifest)

    def test_python_syntax_error_fails_both_layouts(self) -> None:
        for directory, layout in (("baseline-src", "cuda"), ("next-src", "cuda_bindings")):
            with self.subTest(layout=layout):
                self.source(directory, layout, "# CUDA Python\ndef broken(:\n")
                result = self.preflight(directory)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("Python source compile failed", result.stderr)
                self.assertNotIn("scoped-arm-preflight-ok:", result.stdout)

    def test_missing_source_and_unrecognized_layout_fail(self) -> None:
        result = self.preflight()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("source tree not found", result.stderr)
        self.source("baseline-src", "unrelated")
        result = self.preflight()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no package-specific source/artifact paths", result.stderr)

    def test_wrong_architecture_and_missing_identity_fail(self) -> None:
        self.source("baseline-src", "cuda", "value = 1\n")
        result = self.preflight(machine="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires an Arm64 runner", result.stderr)
        result = self.preflight()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no package-specific evidence pattern", result.stderr)

    def test_test5_emits_failure_and_keeps_probe_diagnostics(self) -> None:
        output = Path(self.env["GITHUB_OUTPUT"])
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.steps["test5"]["run"]],
            cwd=self.root, env=dict(self.env, SCOPED_ARM_PREFLIGHT_PROBE="echo 'compile failed' >&2; exit 1"),
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("compile failed", result.stderr)
        self.assertIn("status=failed", output.read_text())
        self.assertNotIn("status=passed", output.read_text())

    def test_preflight_preserves_cpu_only_scope(self) -> None:
        candidate = self.steps["test6"]["with"]
        self.assertIn("PREFLIGHT_SOURCE_DIR=next-src", candidate["limited_cpu_probe"])
        self.assertIn("CPU-side preflight evidence only", candidate["limited_cpu_description"])
        self.assertIn("no GPU/CUDA driver/runtime", candidate["limited_cpu_description"])
        self.assertNotEqual("true", candidate.get("defer_on_limited_cpu_probe_failure"))

    def summary(self, statuses, outcomes=None):
        if outcomes is None:
            outcomes = {f"test{n}": "success" for n in range(1, 7)}

        def expression(match):
            key, _, fallback = match.group(1).partition("||")
            step = key.strip().split(".")[1]
            if ".outcome" in key:
                value = outcomes.get(step)
            elif ".status" in key:
                value = statuses.get(step)
            else:
                value = "2"
            return value or fallback.strip().strip("'")

        script = re.sub(r"\$\{\{ (.*?) \}\}", expression, self.steps["summary"]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10,
        )
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, values

    def test_summary_preserves_failure_counts_and_exit_status(self) -> None:
        cases = [(None, "passed"), ("all", ""), ("test6", "skipped")]
        cases += [(f"test{n}", state) for n in range(1, 7) for state in ("failed", "", "invalid")]
        cases += [(f"test{n}", "skipped") for n in range(1, 6)]
        for changed, state in cases:
            with self.subTest(changed=changed, state=state):
                statuses = {f"test{n}": "passed" for n in range(1, 7)}
                if changed == "all":
                    statuses = {}
                elif changed:
                    statuses[changed] = state

                result, values = self.summary(statuses)
                skipped = int(changed == "test6" and state == "skipped")
                failed = 6 if changed == "all" else int(changed is not None and not skipped)
                core = 5 if changed == "all" else int(changed not in (None, "test6"))
                self.assertEqual(int(failed > 0), result.returncode, result.stderr)
                self.assertEqual(str(failed), values["failed"])
                self.assertEqual(str(core), values["core_failed"])
                self.assertEqual(str(6 - failed - skipped), values["passed"])
                self.assertEqual(str(skipped), values["skipped"])
                self.assertEqual("12", values["duration"])
                self.assertEqual("failure" if failed else "success", values["overall_status"])
                self.assertEqual("failing" if core else "passing", values["badge_status"])

    def test_passed_output_cannot_hide_unsuccessful_or_missing_outcome(self) -> None:
        statuses = {f"test{n}": "passed" for n in range(1, 7)}
        for number in range(1, 7):
            for outcome in ("failure", "skipped", "cancelled", ""):
                with self.subTest(number=number, outcome=outcome):
                    outcomes = {f"test{n}": "success" for n in range(1, 7)}
                    outcomes[f"test{number}"] = outcome
                    result, values = self.summary(statuses, outcomes)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("5", values["passed"])
                    self.assertEqual("1", values["failed"])
                    self.assertEqual("0", values["skipped"])
                    self.assertEqual("1" if number <= 5 else "0", values["core_failed"])
                    self.assertEqual("failure", values["overall_status"])
                    self.assertEqual("failing" if number <= 5 else "passing", values["badge_status"])
        result, values = self.summary(statuses, outcomes={})
        self.assertEqual(1, result.returncode)
        self.assertEqual("6", values["failed"])
        self.assertEqual("5", values["core_failed"])

    def test_candidate_skip_requires_successful_outcome(self) -> None:
        statuses = {f"test{n}": "passed" for n in range(1, 6)}
        statuses["test6"] = "skipped"
        for outcome in ("failure", "skipped", "cancelled", ""):
            with self.subTest(outcome=outcome):
                outcomes = {f"test{n}": "success" for n in range(1, 6)}
                outcomes["test6"] = outcome
                result, values = self.summary(statuses, outcomes)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual("1", values["failed"])
                self.assertEqual("0", values["skipped"])
                self.assertEqual("0", values["core_failed"])
                self.assertEqual("failure", values["overall_status"])


if __name__ == "__main__":
    unittest.main()
