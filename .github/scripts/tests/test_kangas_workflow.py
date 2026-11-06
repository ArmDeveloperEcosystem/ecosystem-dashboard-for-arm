"""Keep Kangas downloads bounded without suppressing install failures."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-kangas.yml"


class KangasWorkflowTests(unittest.TestCase):
    def test_install_timeout_and_real_failure_status(self):
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-kangas"]
        step = next(step for step in job["steps"] if step.get("id") == "install")
        self.assertEqual(10, step["timeout-minutes"])
        self.assertNotIn("continue-on-error", step)
        with tempfile.TemporaryDirectory(prefix="kangas-test-") as temporary:
            root = Path(temporary)
            bootstrap = root / ".github/actions/apt-bootstrap/bootstrap.sh"
            bootstrap.parent.mkdir(parents=True)
            bootstrap.write_text("exit 0\n")
            pip = root / "pip"
            pip.write_text('''#!/bin/bash
set -euo pipefail
test "$*" = 'install --break-system-packages --timeout 120 --retries 3 kangas'
exit "$PIP_EXIT"
''')
            pip.chmod(0o755)
            output = root / "output"
            for code in (0, 1):
                with self.subTest(pip_exit=code):
                    output.write_text("")
                    result = subprocess.run(
                        ["bash", "-e", "-o", "pipefail", "-c", step["run"]], cwd=root,
                        env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                                 GITHUB_OUTPUT=str(output), PIP_EXIT=str(code)),
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(code, result.returncode, result.stderr)
                    self.assertIn("install_status=" + ("success" if code == 0 else "failed"),
                                  output.read_text())


if __name__ == "__main__":
    unittest.main()
