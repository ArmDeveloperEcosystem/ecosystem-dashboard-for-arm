"""Focused Angular CLI workflow regression checks."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-angularcli.yml"


class AngularCliWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="angularcli-workflow-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.output = self.root / "output"
        self.output.touch()
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-angularcli"]
        self.help_script = next(
            step["run"] for step in job["steps"] if step.get("id") == "test3"
        )

    def run_help_check(self, *, help_exit=0, help_text="Commands:\n  build\n  new\n"):
        ng = self.bin / "ng"
        ng.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "if [ \"${1:-}\" = \"--help\" ]; then\n"
            "  printf '%s' \"$HELP_TEXT\"\n"
            "  exit \"$HELP_EXIT\"\n"
            "fi\n"
            "echo 'Error: Unknown argument: help' >&2\n"
            "exit 2\n"
        )
        ng.chmod(0o755)
        environment = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            GITHUB_OUTPUT=str(self.output),
            HELP_EXIT=str(help_exit),
            HELP_TEXT=help_text,
        )
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.help_script],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        fields = dict(
            line.split("=", 1)
            for line in self.output.read_text().splitlines()
            if "=" in line
        )
        return result, fields

    def test_current_option_style_help_is_accepted(self):
        result, fields = self.run_help_check()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertNotIn("ng help", self.help_script)
        self.assertIn("ng --help", self.help_script)

    def test_failed_help_command_cannot_pass_on_matching_output(self):
        result, fields = self.run_help_check(help_exit=1)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", fields["status"])

    def test_success_without_command_inventory_is_rejected(self):
        result, fields = self.run_help_check(help_text="Angular CLI usage\n")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", fields["status"])


if __name__ == "__main__":
    unittest.main()
