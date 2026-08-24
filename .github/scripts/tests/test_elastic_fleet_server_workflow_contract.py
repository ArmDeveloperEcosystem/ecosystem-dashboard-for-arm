from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-elastic-fleet-server.yml"


class ElasticFleetServerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_elastic_artifact_downloads_use_retrying_http1_curl(self) -> None:
        curl_command = (
            "curl --fail --silent --show-error --location --http1.1 "
            "--retry 5 --retry-delay 10 --retry-all-errors "
            "--connect-timeout 30 --max-time 600"
        )

        self.assertEqual(2, self.workflow.count(curl_command))
        self.assertIn('"$CURRENT_URL" -o "$CURRENT_ARCHIVE"', self.workflow)
        self.assertIn('"$NEXT_URL" -o "$NEXT_ARCHIVE"', self.workflow)
        self.assertNotIn("curl -fsSL", self.workflow)

    def test_candidate_download_failure_emits_explicit_outputs(self) -> None:
        match = re.search(
            r'(?ms)if ! curl .*"\$NEXT_URL" -o "\$NEXT_ARCHIVE"; then\n'
            r"(.*?)\n          fi\n"
            r'          tar -xzf "\$NEXT_ARCHIVE"',
            self.workflow,
        )
        self.assertIsNotNone(match)
        failure_block = match.group(1)

        self.assertIn('echo "next_installed_version=not_installed"', failure_block)
        self.assertIn('echo "decision=next_install_failed"', failure_block)
        self.assertIn(
            'echo "regression_result=Next version download failed on Arm64"',
            failure_block,
        )
        self.assertIn("retrying the artifact fetch with HTTP/1.1", failure_block)
        self.assertIn('echo "status=failed"', failure_block)
        self.assertIn('echo "duration=$((END_TIME - START_TIME))"', failure_block)
        self.assertIn("exit 1", failure_block)


if __name__ == "__main__":
    unittest.main()
