"""Exercise CentOS package lookup with the login profile's which function."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-centos.yml"
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "bash is required")
class CentosWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        cls.steps = {
            step["id"]: step["run"]
            for step in workflow["jobs"]["test-centos"]["steps"]
            if "id" in step and "run" in step
        }

    def test_package_lookup_ignores_function_but_requires_install_and_executable(self):
        for step_id in ("test5", "test6"):
            commands = [
                shlex.split(line)[2]
                for line in self.steps[step_id].splitlines()
                if line.strip().startswith("bash -lc ")
            ]
            self.assertEqual(len(commands), 1)
            for binary_mode, install_exit in ((0o755, 0), (None, 0), (0o644, 0), (0o755, 42)):
                with self.subTest(step=step_id, mode=binary_mode, install_exit=install_exit):
                    with tempfile.TemporaryDirectory() as directory:
                        executable = Path(directory) / "which"
                        if binary_mode is not None:
                            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                            executable.chmod(binary_mode)
                        result = subprocess.run(
                            [BASH, "--noprofile", "--norc", "-e", "-c", "\n".join([
                                'dnf() { return "$INSTALL_EXIT"; }',
                                "which() { :; }",
                                commands[0],
                            ])],
                            env={"PATH": directory, "INSTALL_EXIT": str(install_exit)},
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if binary_mode == 0o755 and install_exit == 0:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout.strip(), str(executable))
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual(result.stdout, "")

    def test_summary_preserves_baseline_and_regression_failures(self):
        for baseline, regression in (("passed", "passed"), ("failed", "passed"), ("passed", "failed")):
            with self.subTest(baseline=baseline, regression=regression):
                script = self.steps["summary"]
                for number in range(1, 7):
                    status = baseline if number == 5 else regression if number == 6 else "passed"
                    script = script.replace("${{ steps.test%d.outputs.status }}" % number, status)
                    script = script.replace("${{ steps.test%d.outputs.duration || 0 }}" % number, "1")
                script = script.replace("${{ steps.test6.outputs.status || 'failed' }}", regression)
                self.assertNotIn("${{", script)
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "output"
                    result = subprocess.run(
                        [BASH, "--noprofile", "--norc", "-e", "-c", script],
                        env={**os.environ, "GITHUB_OUTPUT": str(output)},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
                failed = (baseline == "failed") + (regression == "failed")
                self.assertEqual(result.returncode, 1 if failed else 0, result.stderr)
                self.assertEqual(values["failed"], str(failed))
                self.assertEqual(values["passed"], str(6 - failed))
                self.assertEqual(values["core_failed"], "1" if baseline == "failed" else "0")
                self.assertEqual(values["overall_status"], "failure" if failed else "success")


if __name__ == "__main__":
    unittest.main()
