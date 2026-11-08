"""Focused tests for TimescaleDB repository-key acquisition."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-timescaledb.yml"


class TimescaleDbWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="timescaledb-workflow-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][
            "test-timescaledb"
        ]
        self.environment = dict(os.environ, **job["env"])
        self.environment["PATH"] = f"{self.bin}:{os.environ['PATH']}"
        install = next(step for step in job["steps"] if step.get("id") == "install")
        self.install_script = install["run"]
        match = re.search(
            r"(?ms)^download_repository_key\(\) \{.*?^\}",
            textwrap.dedent(self.install_script),
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.function = match.group(0)

    def stub(self, name: str, script: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script, encoding="utf-8")
        path.chmod(0o755)

    def run_download(
        self,
        *,
        failures_before_success: int,
        actual_fingerprints: tuple[str, ...] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], int]:
        counter = self.root / "curl-count"
        destination = self.root / "repository-key.asc"
        self.stub(
            "curl",
            'count=0\n'
            'if [ -f "$CURL_COUNT" ]; then count=$(cat "$CURL_COUNT"); fi\n'
            'count=$((count + 1))\n'
            'printf "%s\\n" "$count" > "$CURL_COUNT"\n'
            'destination=""\n'
            'while [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = "--output" ]; then destination="$2"; shift 2; else shift; fi\n'
            'done\n'
            'if [ "$count" -le "$CURL_FAILURES" ]; then exit 56; fi\n'
            'printf "test key\\n" > "$destination"\n',
        )
        self.stub(
            "gpg",
            'IFS="," read -r -a fingerprints <<< "$ACTUAL_FINGERPRINTS"\n'
            'for fingerprint in "${fingerprints[@]}"; do\n'
            '  printf "pub:-:4096:1:0000000000000000:0:0:::::::\\n"\n'
            '  printf "fpr:::::::::%s:\\n" "$fingerprint"\n'
            '  printf "sub:-:4096:1:1111111111111111:0:0:::::::\\n"\n'
            '  printf "fpr:::::::::%s:\\n" "$(printf "%040d" 1)"\n'
            'done\n',
        )
        self.stub("sleep", "exit 0\n")
        expected = self.environment["TIMESCALEDB_APT_KEY_FINGERPRINT"]
        environment = dict(
            self.environment,
            CURL_COUNT=str(counter),
            CURL_FAILURES=str(failures_before_success),
            ACTUAL_FINGERPRINTS=",".join(actual_fingerprints or (expected,)),
        )
        script = (
            f"{self.function}\n"
            f"download_repository_key https://example.invalid/key "
            f"{destination} {expected}\n"
        )
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, int(counter.read_text(encoding="utf-8").strip())

    def test_transient_download_is_retried_and_then_accepted(self) -> None:
        result, attempts = self.run_download(failures_before_success=2)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(3, attempts)

    def test_download_exhaustion_fails_after_exactly_five_attempts(self) -> None:
        result, attempts = self.run_download(failures_before_success=5)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(5, attempts)
        self.assertIn("failed after 5 attempts", result.stderr)

    def test_unexpected_key_fingerprint_fails_closed(self) -> None:
        result, attempts = self.run_download(
            failures_before_success=0,
            actual_fingerprints=("0" * 40,),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, attempts)
        self.assertIn("fingerprint set is not approved", result.stderr)

    def test_additional_primary_key_fails_closed(self) -> None:
        expected = self.environment["TIMESCALEDB_APT_KEY_FINGERPRINT"]
        result, attempts = self.run_download(
            failures_before_success=0,
            actual_fingerprints=(expected, "0" * 40),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, attempts)
        self.assertIn("fingerprint set is not approved", result.stderr)

    def test_workflow_uses_audited_keys_without_streaming_into_gpg(self) -> None:
        self.assertEqual(
            "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8",
            self.environment["POSTGRESQL_APT_KEY_FINGERPRINT"],
        )
        self.assertEqual(
            "1005FB68604CE9B8F6879CF759F18EDF47F24417",
            self.environment["TIMESCALEDB_APT_KEY_FINGERPRINT"],
        )
        self.assertNotRegex(self.install_script, r"curl[^\n]*\|[^\n]*gpg")
        self.assertIn("Acquire::Retries=5", self.install_script)


if __name__ == "__main__":
    unittest.main()
