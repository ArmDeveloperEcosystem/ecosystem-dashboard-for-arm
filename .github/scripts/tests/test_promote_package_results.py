from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import promote_package_results as promoter  # noqa: E402


FIXED_TIME = datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc)


def valid_payload(
    slug: str,
    *,
    exact_url: bool = True,
) -> dict:
    details = [
        {"name": f"Test {ordinal} - Baseline", "status": "passed"}
        for ordinal in range(1, 6)
    ]
    details.append(
        {
            "name": "Test 6 - Regression Validation",
            "status": "passed",
            "decision": "next_install_validated",
        }
    )
    url = (
        "https://github.com/example/project/actions/runs/123/job/456"
        if exact_url
        else "https://github.com/example/project/actions/runs/123"
    )
    return {
        "schema_version": "2.0",
        "package": {"name": slug, "version": "1.0.0"},
        "run": {"status": "success", "url": url},
        "tests": {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "details": details,
        },
        "metadata": {
            "package_slug": slug,
            "core_failed": 0,
            "badge_status": "passing",
            "regression_status": "passed",
            "regression_decision": "next_install_validated",
            "regression_applicability": "applicable",
            "regression_reason": "validated",
        },
    }


class PromotePackageResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name) / ".summary-staging"
        self.previous = self.stage / "previous-production-test-results"
        self.candidate = self.stage / "candidate-test-results"
        self.previous.mkdir(parents=True)
        self.candidate.mkdir()

    def write_json(self, directory: Path, slug: str, payload: dict) -> Path:
        path = directory / f"{slug}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def test_valid_candidate_replaces_invalid_legacy_previous(self) -> None:
        (self.previous / "alpha.json").write_text(
            '{"legacy":true}\n', encoding="utf-8"
        )
        candidate = valid_payload("alpha")
        self.write_json(self.candidate, "alpha", candidate)

        report = promoter.promote_package_results(
            self.stage, now=FIXED_TIME
        )

        published_path = (
            self.stage / "publish-data-test-results" / "alpha.json"
        )
        published = json.loads(published_path.read_text(encoding="utf-8"))
        self.assertEqual(1, report["published_count"])
        self.assertEqual(1, report["promoted_count"])
        self.assertEqual("published", report["decisions"]["alpha"]["state"])
        self.assertEqual(
            "2026-08-18T04:00:00+00:00",
            published["metadata"]["production_refreshed_at"],
        )
        self.assertEqual("published", published["metadata"]["publish_state"])

    def test_weak_candidate_retains_only_valid_previous_bytes(self) -> None:
        previous = valid_payload("alpha")
        previous_bytes = json.dumps(previous, separators=(",", ":")) + "\n"
        (self.previous / "alpha.json").write_text(
            previous_bytes, encoding="utf-8"
        )
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha", exact_url=False),
        )

        report = promoter.promote_package_results(
            self.stage, now=FIXED_TIME
        )

        published_path = (
            self.stage / "publish-data-test-results" / "alpha.json"
        )
        self.assertEqual(previous_bytes, published_path.read_text())
        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertEqual(1, report["warning_count"])
        self.assertEqual(0, report["blocked_count"])

    def test_invalid_previous_blocks_without_partial_publish_tree(self) -> None:
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha"),
        )
        self.write_json(
            self.candidate,
            "beta",
            valid_payload("beta", exact_url=False),
        )
        (self.previous / "beta.json").write_text(
            '{"legacy":true}\n', encoding="utf-8"
        )

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            promoter.promote_package_results(self.stage, now=FIXED_TIME)

        report = caught.exception.report
        self.assertEqual(1, report["blocked_count"])
        self.assertEqual(0, report["published_count"])
        self.assertEqual(
            "blocked_invalid_previous",
            report["decisions"]["beta"]["state"],
        )
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )
        self.assertTrue((self.stage / "publish-report.json").is_file())
        self.assertTrue((self.stage / "publish-metrics.env").is_file())

    def test_missing_previous_blocks_without_partial_publish_tree(self) -> None:
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha", exact_url=False),
        )

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            promoter.promote_package_results(self.stage, now=FIXED_TIME)

        self.assertEqual(
            "blocked_no_previous",
            caught.exception.report["decisions"]["alpha"]["state"],
        )
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )

    def test_unreplaced_invalid_previous_is_never_carried_forward(self) -> None:
        (self.previous / "legacy.json").write_text(
            '{"legacy":true}\n', encoding="utf-8"
        )

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            promoter.promote_package_results(self.stage, now=FIXED_TIME)

        self.assertEqual(
            "blocked_invalid_previous",
            caught.exception.report["decisions"]["legacy"]["state"],
        )
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )

    def test_candidate_counter_type_violation_fails_before_materializing(self) -> None:
        candidate = valid_payload("alpha")
        candidate["tests"]["failed"] = "0"
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionError):
            promoter.promote_package_results(self.stage, now=FIXED_TIME)

        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )


if __name__ == "__main__":
    unittest.main()
