from __future__ import annotations

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SCRIPT_ROOT.parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import promote_package_results as promoter  # noqa: E402
import exact_run_aggregation as exact  # noqa: E402
import orchestration_contract as orchestration  # noqa: E402
from test_exact_run_aggregation import ContractFixture  # noqa: E402


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


class FreshPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.topology = exact.discover_topology(REPOSITORY_ROOT)
        cls.manifest = orchestration.build_manifest(
            orchestration_id="orchestration-9000-1",
            expected_sha="a" * 40,
            branch="main",
            records=[
                {
                    "batch": batch.batch,
                    "workflow": orchestration.expected_workflow(batch.batch),
                    "artifact": orchestration.expected_artifact(batch.batch),
                    "dispatch_nonce": f"{batch.batch:064x}",
                    "run_id": 1000 + batch.batch,
                    "run_attempt": 1,
                }
                for batch in cls.topology
            ],
        )
        cls.payloads = {}
        cls.registrations = {}
        for batch in cls.topology:
            for package in batch.packages:
                payload = valid_payload(package.package_slug)
                run_id = str(1000 + batch.batch)
                job_id = 10000 + len(cls.payloads)
                url = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id}"
                payload["run"].update(
                    id=run_id, url=url, job_name=exact.expected_job_name(package)
                )
                payload["metadata"]["batch_title"] = f"Batch {batch.batch}"
                for index, detail in enumerate(payload["tests"]["details"], start=1):
                    detail["url"] = f"{url}#step:{index}:1"
                cls.payloads[package.package_slug] = payload
                cls.registrations[package.package_slug] = {
                    "batch_title": f"Batch {batch.batch}",
                    "workflow_path": batch.workflow_path,
                    "run_id": run_id,
                    "run_attempt": "1",
                    "job_name": exact.expected_job_name(package),
                    "job_url": url,
                    "job_conclusion": "success",
                    "job_started_at": JOB_STARTED_AT,
                    "job_completed_at": JOB_COMPLETED_AT,
                    "resolution_status": "central_exact",
                }

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.stage = Path(temporary.name)
        self.candidate = self.stage / "candidate-test-results"
        self.previous = self.stage / "previous-production-test-results"
        self.candidate.mkdir()
        self.previous.mkdir()
        for slug, payload in self.payloads.items():
            self.write_json(self.candidate / f"{slug}.json", payload)
        self.registration_manifest = {
            "schema": "arm-dashboard-summary-registration",
            "version": 2,
            "repository": REPOSITORY,
            "registrations": copy.deepcopy(self.registrations),
            "previous_registrations": {},
        }
        self.manifest_path = self.stage / "run-manifest.json"
        self.write_json(self.manifest_path, self.manifest)
        self.slug = next(iter(self.payloads))
        self.snapshot_reader = self.enterContext(mock.patch.object(
            exact, "discover_topology_at_commit", return_value=self.topology
        ))
        self.checkout_binding = self.enterContext(mock.patch.object(
            exact, "validate_checkout_binding", return_value=self.manifest["expected_sha"]
        ))

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def promote(self, *, require_all_fresh: bool = True) -> dict:
        self.write_json(self.stage / "trusted-registrations.json", self.registration_manifest)
        original = {
            path: path.read_bytes()
            for directory in (self.candidate, self.previous)
            for path in directory.glob("*.json")
        }
        try:
            return promoter.promote_package_results(
                self.stage,
                repository=REPOSITORY,
                require_all_fresh=require_all_fresh,
                run_manifest=self.manifest_path,
                now=FIXED_TIME,
            )
        finally:
            self.assertEqual(original, {path: path.read_bytes() for path in original})

    def add_previous(self) -> None:
        previous = copy.deepcopy(self.payloads[self.slug])
        previous["metadata"].update(
            production_refreshed_at="2026-08-17T04:00:00+00:00", publish_state="published"
        )
        self.write_json(self.previous / f"{self.slug}.json", previous)
        self.registration_manifest["previous_registrations"][self.slug] = dict(
            self.registrations[self.slug]
        )

    def assert_no_publication(self) -> None:
        for name in (
            "publish-data-test-results", "publish-index.json",
            ".publish-data-test-results.tmp", ".publish-index.json.tmp",
        ):
            self.assertFalse((self.stage / name).exists(), name)

    def test_complete_topology_passes_with_approved_skips(self) -> None:
        skips = (
            (self.slug, "not_applicable_package_manager", "not_applicable", "not_applicable"),
            (self.topology[0].packages[1].package_slug,
             "metadata_review_required", "deferred", "applicable"),
        )
        for slug, decision, status, applicability in skips:
            payload = copy.deepcopy(self.payloads[slug])
            payload["tests"].update(passed=5, skipped=1)
            payload["tests"]["details"][5].update(status="skipped", decision=decision)
            payload["metadata"].update(
                regression_decision=decision, regression_status=status,
                regression_applicability=applicability, regression_reason=decision,
            )
            self.write_json(self.candidate / f"{slug}.json", payload)
        report = self.promote()
        self.assertEqual(960, report["published_count"])
        self.assertEqual(960, report["promoted_count"])
        self.assertEqual(0, report["warning_count"])
        self.assertEqual(0, report["blocked_count"])
        self.assertEqual(set(self.registrations), set(report["decisions"]))
        self.checkout_binding.assert_called_once_with(
            REPOSITORY_ROOT, self.manifest["expected_sha"]
        )
        self.snapshot_reader.assert_called_once_with(
            REPOSITORY_ROOT, self.manifest["expected_sha"]
        )

    def test_missing_or_substituted_topology_is_rejected(self) -> None:
        for substitute in (False, True):
            with self.subTest(substitute=substitute):
                registrations = copy.deepcopy(self.registrations)
                removed = registrations.pop(self.slug)
                if substitute:
                    registrations["unexpected-package"] = removed
                self.registration_manifest["registrations"] = registrations
                with self.assertRaisesRegex(promoter.PromotionError, "committed package topology"):
                    self.promote()
                self.assert_no_publication()

    def test_current_registration_must_match_selected_run_and_topology(self) -> None:
        mutations = {
            "run_id": "987654", "run_attempt": "2", "batch_title": "Batch 22",
            "workflow_path": ".github/workflows/test-all-packages-batch22.yml",
            "job_name": "test-other / test-other",
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                self.registration_manifest["registrations"] = copy.deepcopy(self.registrations)
                record = self.registration_manifest["registrations"][self.slug]
                record[key] = value
                if key == "run_id":
                    record["job_url"] = record["job_url"].replace("/runs/1001/", f"/runs/{value}/")
                with self.assertRaisesRegex(promoter.PromotionError, "accepted manifest/topology"):
                    self.promote()
                self.assert_no_publication()

    def test_duplicate_package_job_identity_is_rejected(self) -> None:
        other = self.topology[0].packages[1].package_slug
        self.registration_manifest["registrations"][other]["job_url"] = (
            self.registrations[self.slug]["job_url"]
        )
        with self.assertRaisesRegex(promoter.PromotionError, "duplicate package jobs"):
            self.promote()
        self.assert_no_publication()

    def test_invalid_parent_manifest_is_rejected(self) -> None:
        for field, value in (("branch", "production"), ("run_attempt", 2), ("run_id", 1002)):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                if field == "branch":
                    manifest[field] = value
                else:
                    manifest["batches"][0][field] = value
                self.write_json(self.manifest_path, manifest)
                with self.assertRaisesRegex(promoter.PromotionError, "fresh publication context"):
                    self.promote()
                self.assert_no_publication()

    def test_previous_only_row_cannot_fill_missing_candidate(self) -> None:
        self.add_previous()
        (self.candidate / f"{self.slug}.json").unlink()
        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()
        self.assertEqual(
            "blocked_not_fresh",
            caught.exception.report["decisions"][self.slug]["state"],
        )
        self.assertEqual(0, caught.exception.report["published_count"])
        self.assert_no_publication()

    def test_malformed_or_synthesized_candidate_cannot_retain_previous(self) -> None:
        self.add_previous()
        for synthesized in (False, True):
            with self.subTest(synthesized=synthesized):
                payload = copy.deepcopy(self.payloads[self.slug])
                if synthesized:
                    payload["metadata"]["synthesis_state"] = (
                        "synthesized_missing_current_run_result"
                    )
                else:
                    payload["tests"]["failed"] = "0"
                self.write_json(self.candidate / f"{self.slug}.json", payload)
                with self.assertRaises(promoter.PromotionBlockedError) as caught:
                    self.promote()
                self.assertEqual(1, caught.exception.report["blocked_count"])
                self.assertEqual(0, caught.exception.report["warning_count"])
                self.assert_no_publication()

    def test_honest_failure_blocks_fresh_mode_but_remains_publishable_standalone(self) -> None:
        payload = copy.deepcopy(self.payloads[self.slug])
        payload["run"]["status"] = "failure"
        payload["tests"].update(passed=5, failed=1)
        payload["tests"]["details"][5].update(status="failed", decision="next_install_failed")
        payload["metadata"].update(
            badge_status="failing", regression_status="failed",
            regression_decision="next_install_failed", regression_reason="next_install_failed",
        )
        self.write_json(self.candidate / f"{self.slug}.json", payload)
        self.registration_manifest["registrations"][self.slug]["job_conclusion"] = "failure"
        with self.assertRaises(promoter.PromotionBlockedError) as caught:
            self.promote()
        self.assertIn(
            "zero package test failures",
            caught.exception.report["decisions"][self.slug]["reason"],
        )
        self.assert_no_publication()
        self.assertEqual(960, self.promote(require_all_fresh=False)["published_count"])

    def test_normalizer_failures_block_even_without_a_blocked_slug(self) -> None:
        self.write_json(self.stage / "normalize-report.json", {
            "blocked_slugs": {}, "weak_urls": ["unresolved"],
            "duplicate_clusters": {}, "unresolved": [],
        })
        with self.assertRaisesRegex(promoter.PromotionError, "zero normalization failures"):
            self.promote()
        self.assert_no_publication()

    def test_cli_requires_manifest_and_explicitly_enables_fresh_mode(self) -> None:
        self.write_json(self.stage / "trusted-registrations.json", self.registration_manifest)
        arguments = [
            "--stage-root", str(self.stage), "--repository", REPOSITORY,
            "--require-all-fresh",
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(1, promoter.main(arguments))
        self.assertIn("requires --run-manifest", stderr.getvalue())
        self.assert_no_publication()
        self.assertEqual(0, promoter.main([*arguments, "--run-manifest", str(self.manifest_path)]))

    def test_summary_invocation_requires_fresh_manifest_bound_results(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/test-all-packages-summary.yml").read_text()
        invocation = workflow.split(
            "python3 .github/scripts/promote_package_results.py", 1
        )[1].split("\n\n", 1)[0]
        self.assertIn("--require-all-fresh", invocation)
        self.assertIn("--run-manifest .orchestration/run-manifest.json", invocation)


class FreshTopologyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ContractFixture()
        self.addCleanup(self.fixture.close)
        for batch in range(3, orchestration.BATCH_COUNT + 1):
            slug = f"package{batch}"
            self.fixture._write_package_workflow(slug)
            self.fixture._write_batch(batch, [slug])
        self.git("init", "-q")
        self.sha = self.commit_topology()
        self.manifest = orchestration.build_manifest(
            orchestration_id="orchestration-9000-1", expected_sha=self.sha,
            branch="main",
            records=[{
                "batch": batch,
                "workflow": orchestration.expected_workflow(batch),
                "artifact": orchestration.expected_artifact(batch),
                "dispatch_nonce": f"{batch:064x}",
                "run_id": 1000 + batch, "run_attempt": 1,
            } for batch in range(1, orchestration.BATCH_COUNT + 1)],
        )
        self.manifest_path = self.fixture.root / "run-manifest.json"
        self.registrations = {}
        for batch in exact.discover_topology(self.fixture.root):
            for package in batch.packages:
                self.registrations[package.package_slug] = {
                    "batch_title": f"Batch {batch.batch}",
                    "workflow_path": batch.workflow_path,
                    "run_id": str(1000 + batch.batch),
                    "run_attempt": "1",
                    "job_name": exact.expected_job_name(package),
                    "job_url": (
                        f"https://github.com/{REPOSITORY}/actions/runs/"
                        f"{1000 + batch.batch}/job/{10000 + batch.batch}"
                    ),
                }
        self.enterContext(mock.patch.object(
            promoter, "__file__",
            str(self.fixture.root / ".github/scripts/promote_package_results.py"),
        ))

    def git(self, *arguments: str) -> str:
        return subprocess.check_output([
            "git", "-C", str(self.fixture.root),
            "-c", "user.name=Freshness Test",
            "-c", "user.email=freshness@example.test",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            *arguments,
        ], text=True).strip()

    def commit_topology(self) -> str:
        self.git("add", ".github")
        self.git("commit", "-qm", "Test topology snapshot")
        return self.git("rev-parse", "HEAD")

    def validate(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        promoter._validate_fresh_registrations(self.registrations, self.manifest_path)

    def test_changed_checkout_sha_is_rejected(self) -> None:
        self.manifest["expected_sha"] = "b" * 40
        with self.assertRaisesRegex(promoter.PromotionError, "checked-out Git commit"):
            self.validate()

    def test_dirty_topology_snapshot_is_rejected(self) -> None:
        workflow = self.fixture.workflows / "test-all-packages-batch1.yml"
        workflow.write_text(workflow.read_text() + "# changed source\n", encoding="utf-8")
        with self.assertRaisesRegex(promoter.PromotionError, "uncommitted or untracked"):
            self.validate()

    def test_ignored_source_cannot_forge_committed_coverage(self) -> None:
        (self.fixture.root / ".git/info/exclude").write_text(
            ".github/workflows/test-forged.yml\n", encoding="utf-8"
        )
        self.fixture._write_package_workflow("forged")
        self.validate()
        self.registrations["forged"] = self.registrations.pop("alpha")
        with self.assertRaisesRegex(promoter.PromotionError, "committed package topology"):
            self.validate()

    def test_next_committed_package_extends_required_coverage(self) -> None:
        self.validate()
        self.assertEqual(22, len(self.registrations))
        self.fixture._write_package_workflow("new-package")
        self.fixture._write_batch(22, ["package22", "new-package"])
        self.manifest["expected_sha"] = self.commit_topology()
        with self.assertRaisesRegex(promoter.PromotionError, "committed package topology"):
            self.validate()
        self.registrations["new-package"] = {
            **self.registrations["package22"],
            "job_name": "test-new-package / test",
            "job_url": f"https://github.com/{REPOSITORY}/actions/runs/1022/job/20000",
        }
        self.validate()
        self.assertEqual(23, len(self.registrations))


if __name__ == "__main__":
    unittest.main()
