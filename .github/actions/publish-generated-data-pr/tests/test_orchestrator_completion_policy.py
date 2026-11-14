from __future__ import annotations

import os
import subprocess
import textwrap
import unittest
from pathlib import Path


class OrchestratorCompletionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repository = Path(__file__).resolve().parents[4]
        cls.orchestrator = (
            repository / ".github/workflows/test-all-packages-orchestrator.yml"
        ).read_text(encoding="utf-8")

    def _step(self, name: str, next_name: str | None = None) -> str:
        start = self.orchestrator.split(f"- name: {name}", 1)[1]
        if next_name is None:
            return start
        return start.split(f"- name: {next_name}", 1)[0]

    def test_child_conclusions_are_deferred_until_after_summary(self) -> None:
        wait = self._step(
            "Wait for captured batch runs",
            "Dispatch exact global summary",
        )
        summary = self._step(
            "Dispatch exact global summary",
            "Conclude exact orchestration",
        )
        conclude = self._step("Conclude exact orchestration")

        self.assertIn("id: wait", wait)
        self.assertIn('[[ "$RUN_ATTEMPT" == "1" ]]', wait)
        self.assertIn('python3 "$helper" validate-run', wait)
        self.assertIn('failed_batch_count="${#failed_batches[@]}"', wait)
        self.assertIn(
            "printf 'failed_batch_count=%s\\n' "
            '"$failed_batch_count" >> "$GITHUB_OUTPUT"',
            wait,
        )
        child_failure_report = wait.split(
            'if [[ "$failed_batch_count" -gt 0 ]]', 1
        )[1]
        self.assertNotIn("exit 1", child_failure_report)

        self.assertIn("id: summary", summary)
        self.assertIn(
            "if: ${{ steps.wait.outcome == 'success' }}",
            summary,
        )
        self.assertIn("summary-dispatch-payload", summary)
        self.assertIn("validate-summary-run", summary)

        self.assertIn(
            "if: ${{ always() && steps.wait.outcome == 'success' }}",
            conclude,
        )
        self.assertIn(
            "FAILED_BATCH_COUNT: "
            "${{ steps.wait.outputs.failed_batch_count }}",
            conclude,
        )
        self.assertIn(
            "SUMMARY_OUTCOME: ${{ steps.summary.outcome }}",
            conclude,
        )
        self.assertIn('[[ "$FAILED_BATCH_COUNT" -gt 0 ]]', conclude)
        self.assertIn('[[ "$SUMMARY_OUTCOME" != "success" ]]', conclude)
        self.assertIn('[[ "$orchestration_failed" == "true" ]]', conclude)

    def test_status_lookups_retry_but_remain_fail_closed(self) -> None:
        wait = self._step(
            "Wait for captured batch runs",
            "Dispatch exact global summary",
        )
        summary = self._step(
            "Dispatch exact global summary",
            "Conclude exact orchestration",
        )

        self.assertIn('delay="$(retry_delay "$api_failures")"', wait)
        self.assertIn('[[ "$api_failures" -ge 5 ]]', wait)
        self.assertIn(
            'if [[ "$completed" != "true" ]]',
            wait,
        )
        self.assertIn(
            "Run $RUN_ID did not complete within the bounded wait.",
            wait,
        )

        self.assertEqual(
            summary.count(
                'summary_api_failures=$((summary_api_failures + 1))'
            ),
            2,
        )
        self.assertEqual(
            summary.count(
                'delay="$(retry_delay "$summary_api_failures")"'
            ),
            2,
        )
        self.assertGreaterEqual(
            summary.count('[[ "$summary_api_failures" -ge 5 ]]'),
            2,
        )

    def test_final_conclusion_reports_child_and_summary_failures(self) -> None:
        conclude = self._step("Conclude exact orchestration")
        script = textwrap.dedent(conclude.split("run: |", 1)[1])
        cases = (
            ("0", "success", 0),
            ("2", "success", 1),
            ("0", "failure", 1),
            ("2", "failure", 1),
            ("unknown", "success", 1),
        )
        for failed_count, summary_outcome, expected_status in cases:
            with self.subTest(
                failed_count=failed_count,
                summary_outcome=summary_outcome,
            ):
                completed = subprocess.run(
                    ["bash", "-c", script],
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "FAILED_BATCH_COUNT": failed_count,
                        "SUMMARY_OUTCOME": summary_outcome,
                    },
                )
                self.assertEqual(completed.returncode, expected_status)


if __name__ == "__main__":
    unittest.main()

