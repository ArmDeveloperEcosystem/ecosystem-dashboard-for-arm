from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-madoguchi.yml"
RUST_TOOLCHAIN_ACTION = (
    "dtolnay/rust-toolchain@89b12181fb390509a0842a86cc55eeb8eb928c1d"
)


class MadoguchiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        cls.job = document["jobs"]["test-madoguchi"]
        cls.steps = {
            step.get("id", step.get("name")): step for step in cls.job["steps"]
        }

    def test_native_arm64_lane_is_reproducible(self) -> None:
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        toolchain = self.steps["Setup Rust toolchain"]
        self.assertEqual(RUST_TOOLCHAIN_ACTION, toolchain["uses"])
        self.assertEqual("1.99.1", toolchain["with"]["toolchain"])

        baseline = self.steps["install"]["run"]
        candidate = self.steps["test6"]["run"]
        self.assertIn(
            "cargo build --locked --release --manifest-path madoguchi/Cargo.toml",
            baseline,
        )
        self.assertIn(
            'cargo build --locked --release --manifest-path "$NEXT_DIR/repo/Cargo.toml"',
            candidate,
        )

    def test_six_real_checks_remain_strict(self) -> None:
        for number in range(1, 7):
            self.assertIn(f"test{number}", self.steps)
        self.assertNotIn("continue-on-error", self.steps["test6"])
        self.assertEqual("always()", self.steps["test6"]["if"])
        gate = self.steps["test6"]["run"]
        for number in range(1, 6):
            self.assertEqual(
                f"${{{{ steps.test{number}.outputs.status || 'failed' }}}}",
                self.steps["test6"]["env"][f"TEST{number}_STATUS"],
            )
        self.assertIn('echo "decision=baseline_failed"', gate)
        self.assertIn('echo "status=skipped"', gate)
        self.assertIn("summary", self.steps)

    def test_early_candidate_failure_is_recorded_as_failed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="madoguchi-test6-") as temporary:
            root = Path(temporary)
            output = root / "output"
            output.write_text("")
            binary = root / "bin"
            binary.mkdir()
            git = binary / "git"
            git.write_text('#!/bin/sh\nexit "${GIT_RC:-17}"\n')
            git.chmod(0o755)
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", self.steps["test6"]["run"]],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                    "GITHUB_OUTPUT": str(output),
                    "BASELINE_VERSION": "v0.5.4",
                    "NEXT_VERSION": "v0.6.0",
                    "GIT_RC": "17",
                    "TEST1_STATUS": "passed",
                    "TEST2_STATUS": "passed",
                    "TEST3_STATUS": "passed",
                    "TEST4_STATUS": "passed",
                    "TEST5_STATUS": "passed",
                },
                capture_output=True,
                text=True,
                timeout=15,
            )
            values = dict(
                line.split("=", 1)
                for line in output.read_text().splitlines()
                if "=" in line
            )
            self.assertEqual(17, result.returncode, result.stderr)
            self.assertEqual("failed", values["status"])
            self.assertEqual("next_install_failed", values["decision"])
            self.assertEqual("not_installed", values["next_installed_version"])
            self.assertIn("duration", values)

    def test_baseline_failure_explicitly_defers_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="madoguchi-test6-") as temporary:
            output = Path(temporary) / "output"
            output.write_text("")
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", self.steps["test6"]["run"]],
                env={
                    **os.environ,
                    "GITHUB_OUTPUT": str(output),
                    "BASELINE_VERSION": "v0.5.4",
                    "NEXT_VERSION": "v0.6.0",
                    "TEST1_STATUS": "failed",
                    "TEST2_STATUS": "passed",
                    "TEST3_STATUS": "passed",
                    "TEST4_STATUS": "passed",
                    "TEST5_STATUS": "passed",
                },
                capture_output=True,
                text=True,
                timeout=15,
            )
            values = dict(
                line.split("=", 1)
                for line in output.read_text().splitlines()
                if "=" in line
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("skipped", values["status"])
            self.assertEqual("baseline_failed", values["decision"])
            self.assertEqual("not_installed", values["next_installed_version"])

    def test_regression_summary_fails_closed(self) -> None:
        summary = self.steps["summary"]["run"]
        self.assertIn('local decision="$3"', summary)
        self.assertIn(
            'elif [ "$status" = "skipped" ] && [ "$decision" = "baseline_failed" ] && [ "$CORE_FAILED" -gt 0 ]; then',
            summary,
        )
        self.assertIn(
            '"${{ steps.test6.outputs.decision || \'missing\' }}"',
            summary,
        )


if __name__ == "__main__":
    unittest.main()
