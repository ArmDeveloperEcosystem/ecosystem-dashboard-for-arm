from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SCRIPT_ROOT.parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import promote_package_results as promoter  # noqa: E402


FIXED_TIME = datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc)
REPOSITORY = "example/project"
RUN_ID = "123"
JOB_ID = "456"
JOB_URL = (
    f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}/job/{JOB_ID}"
)
WORKFLOW_PATH = ".github/workflows/test-all-packages-batch1.yml"
JOB_STARTED_AT = "2026-08-18T03:58:00Z"
JOB_COMPLETED_AT = "2026-08-18T04:00:00Z"


def valid_payload(
    slug: str,
    *,
    exact_url: bool = True,
    decision: str = "next_install_validated",
    test6_status: str = "passed",
    include_decision: bool = True,
) -> dict:
    details = [
        {
            "name": f"Test {ordinal} - Baseline",
            "status": "passed",
            "duration_seconds": ordinal,
            "url": f"{JOB_URL}#step:{ordinal}:1",
        }
        for ordinal in range(1, 6)
    ]
    test6 = {
        "name": "Test 6 - Regression Validation",
        "status": test6_status,
        "duration_seconds": 6,
        "url": f"{JOB_URL}#step:6:1",
        "current_version": "1.0.0",
        "latest_version": "1.1.0",
        "next_installed_version": "1.1.0",
        "regression_result": "Candidate version completed its native Arm64 smoke test.",
        "comparison": "Version 1.1.0 passed the same bounded checks as version 1.0.0.",
    }
    if include_decision:
        test6["decision"] = decision
    details.append(test6)
    passed = sum(detail["status"] == "passed" for detail in details)
    failed = sum(detail["status"] == "failed" for detail in details)
    skipped = sum(detail["status"] == "skipped" for detail in details)
    run_status = "failure" if failed else "success"
    metadata = {
        "contract_version": "2.0",
        "package_slug": slug,
        "dashboard_link": f"/linux/opensource_packages/{slug}",
        "badge_status": "failing" if failed else "passing",
        "core_failed": 0,
        "batch_title": "Batch 1",
        "job_url_resolution_status": "central_exact",
        "regression_status": (
            "passed"
            if test6_status == "passed"
            else "failed"
            if test6_status == "failed"
            else "not_applicable"
        ),
        "regression_applicability": (
            "not_applicable" if test6_status == "skipped" else "applicable"
        ),
        "regression_reason": (
            decision if test6_status != "passed" else "validated"
        ),
        "regression_note": (
            "Test 6 produced bounded native Arm64 evidence for this package."
        ),
    }
    if include_decision:
        metadata["regression_decision"] = decision
    return {
        "schema_version": "2.0",
        "package": {"name": slug, "version": "1.0.0"},
        "run": {
            "id": RUN_ID,
            "attempt": "1",
            "url": JOB_URL if exact_url else JOB_URL.rsplit("/job/", 1)[0],
            "timestamp": "2026-08-18T03:59:00Z",
            "status": run_status,
            "runner": {"os": "ubuntu-24.04", "arch": "arm64"},
            "job_name": f"test-{slug} / test-{slug}",
        },
        "tests": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_seconds": 21,
            "details": details,
        },
        "metadata": metadata,
    }


def published_payload(slug: str, **kwargs: object) -> dict:
    payload = valid_payload(slug, **kwargs)
    payload["metadata"]["production_refreshed_at"] = (
        "2026-08-17T04:00:00+00:00"
    )
    payload["metadata"]["publish_state"] = "published"
    return payload


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

    def write_raw(self, directory: Path, slug: str, value: str) -> Path:
        path = directory / f"{slug}.json"
        path.write_text(value, encoding="utf-8")
        return path

    def write_trusted_registrations(
        self, stage: Path | None = None
    ) -> None:
        stage = stage or self.stage
        previous = stage / "previous-production-test-results"
        candidate = stage / "candidate-test-results"
        slugs = {
            path.stem
            for directory in (previous, candidate)
            for path in directory.glob("*.json")
        }
        def registration(slug: str) -> dict:
            return {
                "batch_title": "Batch 1",
                "workflow_path": WORKFLOW_PATH,
                "run_id": RUN_ID,
                "run_attempt": "1",
                "job_name": f"test-{slug} / test-{slug}",
                "job_url": JOB_URL,
                "job_conclusion": "success",
                "job_started_at": JOB_STARTED_AT,
                "job_completed_at": JOB_COMPLETED_AT,
                "resolution_status": "central_exact",
            }
        registrations = {
            slug: registration(slug) for slug in sorted(slugs)
        }
        previous_registrations = {
            path.stem: registration(path.stem)
            for path in sorted(previous.glob("*.json"))
        }
        (stage / "trusted-registrations.json").write_text(
            json.dumps(
                {
                    "schema": "arm-dashboard-summary-registration",
                    "version": 2,
                    "repository": REPOSITORY,
                    "registrations": registrations,
                    "previous_registrations": previous_registrations,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def promote(self, *, policy: str = "strict") -> dict:
        self.write_trusted_registrations()
        return promoter.promote_package_results(
            self.stage,
            validation_policy=policy,
            repository=REPOSITORY,
            now=FIXED_TIME,
        )

    def test_valid_candidate_replaces_invalid_legacy_previous(self) -> None:
        self.write_raw(self.previous, "alpha", '{"legacy":true}\n')
        self.write_json(self.candidate, "alpha", valid_payload("alpha"))

        report = self.promote()

        published_path = (
            self.stage / "publish-data-test-results" / "alpha.json"
        )
        published = json.loads(published_path.read_text(encoding="utf-8"))
        self.assertEqual(1, report["published_count"])
        self.assertEqual(1, report["promoted_count"])
        self.assertEqual("strict", report["validation_policy"])
        self.assertEqual("published", report["decisions"]["alpha"]["state"])
        self.assertEqual(
            "2026-08-18T04:00:00+00:00",
            published["metadata"]["production_refreshed_at"],
        )
        self.assertEqual("published", published["metadata"]["publish_state"])
        index = json.loads(
            (self.stage / "publish-index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["alpha"], list(index))
        self.assertEqual(published, index["alpha"])


    def test_weak_candidate_retains_only_valid_previous_bytes(self) -> None:
        previous = valid_payload("alpha")
        previous["metadata"]["production_refreshed_at"] = (
            "2026-08-17T04:00:00+00:00"
        )
        previous["metadata"]["publish_state"] = "published"
        previous_bytes = json.dumps(previous, separators=(",", ":")) + "\n"
        self.write_raw(self.previous, "alpha", previous_bytes)
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha", exact_url=False),
        )

        report = self.promote()

        published_path = (
            self.stage / "publish-data-test-results" / "alpha.json"
        )
        self.assertEqual(previous_bytes, published_path.read_text())
        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertIn(
            "candidate_contract_violation",
            report["decisions"]["alpha"]["reason"],
        )
        self.assertEqual(1, report["warning_count"])
        self.assertEqual(0, report["blocked_count"])

    def test_normalizer_block_retains_previous(self) -> None:
        previous = published_payload("alpha")
        self.write_json(self.previous, "alpha", previous)
        self.write_json(self.candidate, "alpha", valid_payload("alpha"))
        self.write_json(
            self.stage,
            "normalize-report",
            {
                "blocked_slugs": {"alpha": "duplicate_exact_job_url"},
                "weak_urls": [],
                "duplicate_clusters": {},
                "unresolved": [],
            },
        )

        report = self.promote()

        self.assertEqual(
            {
                "state": "retained_previous",
                "reason": "duplicate_exact_job_url",
            },
            report["decisions"]["alpha"],
        )

    def test_invalid_previous_blocks_without_partial_publish_tree(self) -> None:
        self.write_json(self.candidate, "alpha", valid_payload("alpha"))
        self.write_json(
            self.candidate,
            "beta",
            valid_payload("beta", exact_url=False),
        )
        self.write_raw(self.previous, "beta", '{"legacy":true}\n')

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

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
        self.assertFalse((self.stage / "publish-index.json").exists())
        self.assertTrue((self.stage / "publish-report.json").is_file())
        self.assertTrue((self.stage / "publish-metrics.env").is_file())

    def test_missing_previous_blocks_without_partial_publish_tree(self) -> None:
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha", exact_url=False),
        )

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertEqual(
            "blocked_no_previous",
            caught.exception.report["decisions"]["alpha"]["state"],
        )
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )
        self.assertFalse((self.stage / "publish-index.json").exists())

    def test_valid_previous_only_is_retained_byte_for_byte(self) -> None:
        previous_bytes = json.dumps(
            published_payload("alpha"), separators=(",", ":")
        ) + "\n"
        self.write_raw(self.previous, "alpha", previous_bytes)

        report = self.promote()

        published_path = (
            self.stage / "publish-data-test-results" / "alpha.json"
        )
        self.assertEqual(previous_bytes, published_path.read_text())
        self.assertEqual(
            {
                "state": "retained_previous",
                "reason": "candidate_not_emitted",
            },
            report["decisions"]["alpha"],
        )

    def test_unreplaced_invalid_previous_is_never_carried_forward(self) -> None:
        self.write_raw(self.previous, "legacy", '{"legacy":true}\n')

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertEqual(
            "blocked_invalid_previous",
            caught.exception.report["decisions"]["legacy"]["state"],
        )
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )

    def test_candidate_counter_type_violation_retains_previous(self) -> None:
        previous_bytes = json.dumps(published_payload("alpha")) + "\n"
        self.write_raw(self.previous, "alpha", previous_bytes)
        candidate = valid_payload("alpha")
        candidate["tests"]["failed"] = "0"
        self.write_json(self.candidate, "alpha", candidate)

        report = self.promote()

        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertEqual(
            previous_bytes,
            (
                self.stage / "publish-data-test-results" / "alpha.json"
            ).read_text(),
        )

    def test_candidate_slug_mismatch_blocks_without_previous(self) -> None:
        candidate = valid_payload("other")
        candidate["run"]["job_name"] = "test-alpha / test-alpha"
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "package_slug",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_candidate_missing_run_identity_blocks(self) -> None:
        candidate = valid_payload("alpha")
        del candidate["run"]["id"]
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError):
            self.promote()

    def test_duplicate_json_candidate_is_rejected(self) -> None:
        self.write_raw(
            self.candidate,
            "alpha",
            '{"schema_version":"2.0","schema_version":"2.0"}\n',
        )

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "duplicate JSON key",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_nonfinite_json_candidate_is_rejected(self) -> None:
        raw = json.dumps(valid_payload("alpha")).replace(
            '"passed": 6', '"passed": NaN'
        )
        self.write_raw(self.candidate, "alpha", raw)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "unsupported JSON constant",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_deeply_nested_json_candidate_is_rejected(self) -> None:
        candidate = valid_payload("alpha")
        nested = {}
        cursor = nested
        for _ in range(promoter._MAX_JSON_DEPTH + 1):
            cursor["child"] = {}
            cursor = cursor["child"]
        candidate["unexpected_deep_value"] = nested
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "depth limit",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_json_candidate_exceeding_node_limit_is_rejected(self) -> None:
        candidate = valid_payload("alpha")
        candidate["unexpected_nodes"] = [0] * promoter._MAX_JSON_NODES
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "node limit",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_symlink_candidate_is_rejected_without_reading_target(self) -> None:
        target = self.stage / "target.json"
        target.write_text(json.dumps(valid_payload("alpha")), encoding="utf-8")
        (self.candidate / "alpha.json").symlink_to(target)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "not a regular file",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_malformed_normalize_report_fails_before_publication(self) -> None:
        self.write_json(self.candidate, "alpha", valid_payload("alpha"))
        self.write_json(
            self.stage,
            "normalize-report",
            {
                "blocked_slugs": [],
                "weak_urls": [],
                "duplicate_clusters": {},
                "unresolved": [],
            },
        )

        with self.assertRaises(promoter.PromotionError):
            self.promote()

        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )

    def test_compatibility_previous_may_lack_passed_test6_decision(self) -> None:
        legacy = published_payload(
            "alpha", include_decision=False
        )
        self.write_json(self.previous, "alpha", legacy)

        report = self.promote(policy="compatibility")

        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )

    def test_compatibility_candidate_missing_decision_is_not_promoted(self) -> None:
        legacy = published_payload(
            "alpha", include_decision=False
        )
        previous_bytes = json.dumps(legacy) + "\n"
        self.write_raw(self.previous, "alpha", previous_bytes)
        self.write_json(
            self.candidate,
            "alpha",
            valid_payload("alpha", include_decision=False),
        )

        report = self.promote(policy="compatibility")

        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertEqual(
            previous_bytes,
            (
                self.stage / "publish-data-test-results" / "alpha.json"
            ).read_text(),
        )

    def test_missing_decision_never_justifies_skipped_test6(self) -> None:
        legacy = published_payload(
            "alpha",
            test6_status="skipped",
            include_decision=False,
        )
        self.write_json(self.previous, "alpha", legacy)

        with self.assertRaises(promoter.PromotionBlockedError):
            self.promote(policy="compatibility")

    def test_compatibility_never_weakens_new_candidate_semantics(self) -> None:
        previous = published_payload("alpha")
        self.write_json(self.previous, "alpha", previous)
        candidate = valid_payload("alpha")
        candidate["metadata"]["regression_applicability"] = "not_applicable"
        candidate["metadata"]["regression_reason"] = (
            "package_manager_installed"
        )
        self.write_json(self.candidate, "alpha", candidate)

        report = self.promote(policy="compatibility")

        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertIn(
            "regression_applicability contradicts",
            report["decisions"]["alpha"]["reason"],
        )

    def test_self_consistent_fabricated_job_id_is_rejected(self) -> None:
        candidate = valid_payload("alpha")
        forged_url = (
            f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}/job/999"
        )
        candidate["run"]["url"] = forged_url
        for index, detail in enumerate(
            candidate["tests"]["details"], start=1
        ):
            detail["url"] = f"{forged_url}#step:{index}:1"
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()

        self.assertIn(
            "trusted registration",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_fabricated_previous_job_identity_is_never_retained(self) -> None:
        previous = published_payload("alpha")
        forged_url = (
            f"https://github.com/{REPOSITORY}/actions/runs/999999999/job/999"
        )
        previous["run"]["id"] = "999999999"
        previous["run"]["attempt"] = "9"
        previous["run"]["url"] = forged_url
        for index, detail in enumerate(
            previous["tests"]["details"], start=1
        ):
            detail["url"] = f"{forged_url}#step:{index}:1"
        self.write_json(self.previous, "alpha", previous)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote(policy="compatibility")

        decision = caught.exception.report["decisions"]["alpha"]
        self.assertEqual("blocked_invalid_previous", decision["state"])
        self.assertIn("trusted registration", decision["reason"])
        self.assertFalse(
            (self.stage / "publish-data-test-results").exists()
        )

    def test_previous_timestamp_must_match_trusted_job_window(self) -> None:
        previous = published_payload("alpha")
        previous["run"]["timestamp"] = "2026-08-18T04:01:00Z"
        self.write_json(self.previous, "alpha", previous)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote(policy="compatibility")

        decision = caught.exception.report["decisions"]["alpha"]
        self.assertEqual("blocked_invalid_previous", decision["state"])
        self.assertIn("trusted GitHub job window", decision["reason"])

    def test_missing_historical_registration_blocks_retention(self) -> None:
        self.write_json(self.previous, "alpha", published_payload("alpha"))
        self.write_trusted_registrations()
        manifest_path = self.stage / "trusted-registrations.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["previous_registrations"] = {}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            promoter.promote_package_results(
                self.stage,
                validation_policy="compatibility",
                repository=REPOSITORY,
                now=FIXED_TIME,
            )
        self.assertIn(
            "API-verified historical registration",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_candidate_cannot_supply_publisher_owned_metadata(self) -> None:
        previous = published_payload("alpha")
        self.write_json(self.previous, "alpha", previous)
        candidate = valid_payload("alpha")
        candidate["metadata"]["production_refreshed_at"] = (
            "2026-08-18T03:00:00+00:00"
        )
        candidate["metadata"]["publish_state"] = "published"
        self.write_json(self.candidate, "alpha", candidate)

        report = self.promote()

        self.assertEqual(
            "retained_previous", report["decisions"]["alpha"]["state"]
        )
        self.assertIn(
            "publisher-owned metadata",
            report["decisions"]["alpha"]["reason"],
        )

    def test_previous_row_requires_complete_publication_metadata(self) -> None:
        previous = valid_payload("alpha")
        self.write_json(self.previous, "alpha", previous)

        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote(policy="compatibility")

        self.assertEqual(
            "blocked_invalid_previous",
            caught.exception.report["decisions"]["alpha"]["state"],
        )
        self.assertIn(
            "publisher-owned metadata",
            caught.exception.report["decisions"]["alpha"]["reason"],
        )

    def test_wrong_detail_job_binding_is_rejected(self) -> None:
        candidate = valid_payload("alpha")
        candidate["tests"]["details"][0]["url"] = (
            f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}"
            "/job/999#step:1:1"
        )
        self.write_json(self.candidate, "alpha", candidate)

        with self.assertRaises(promoter.PromotionBlockedError):
            self.promote()

    def test_all_committed_rows_satisfy_previous_row_compatibility(self) -> None:
        paths = sorted(
            (REPOSITORY_ROOT / "data/test-results").glob("*.json")
        )
        self.assertEqual(960, len(paths))
        for path in paths:
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                batch_number = payload["metadata"]["batch_title"].split()[1]
                workflow_path = (
                    f".github/workflows/test-all-packages-batch{batch_number}.yml"
                )
                promoter.validate_persisted_result(
                    payload,
                    expected_slug=path.stem,
                    expected_repository=(
                        "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
                    ),
                    expected_registration={
                        "batch_title": payload["metadata"]["batch_title"],
                        "workflow_path": workflow_path,
                        "run_id": payload["run"]["id"],
                        "run_attempt": payload["run"]["attempt"],
                        "job_name": payload["run"]["job_name"],
                        "job_url": payload["run"]["url"],
                        "job_conclusion": payload["run"]["status"],
                        "job_started_at": payload["run"]["timestamp"],
                        "job_completed_at": payload["run"]["timestamp"],
                        "resolution_status": "central_exact",
                    },
                    publication_role="previous",
                    validation_policy="compatibility",
                    allow_legacy_missing_decision=True,
                )

    def test_cli_success_and_failure_are_explicit(self) -> None:
        self.write_json(self.candidate, "alpha", valid_payload("alpha"))
        self.write_trusted_registrations()
        self.assertEqual(
            0,
            promoter.main(
                [
                    "--stage-root",
                    str(self.stage),
                    "--repository",
                    REPOSITORY,
                ]
            ),
        )

        blocked_stage = Path(self.temp.name) / "blocked"
        (blocked_stage / "previous-production-test-results").mkdir(
            parents=True
        )
        (blocked_stage / "candidate-test-results").mkdir()
        candidate = valid_payload("beta", exact_url=False)
        self.write_json(
            blocked_stage / "candidate-test-results",
            "beta",
            candidate,
        )
        self.write_trusted_registrations(blocked_stage)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = promoter.main(
                [
                    "--stage-root",
                    str(blocked_stage),
                    "--repository",
                    REPOSITORY,
                ]
            )
        self.assertEqual(1, result)
        self.assertIn("package result promotion error", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
