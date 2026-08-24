from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from orchestration_contract import (  # noqa: E402
    BATCH_COUNT,
    ContractError,
    PREFETCH_BATCHES,
    batch_dispatch_payload,
    build_manifest,
    canonical_json,
    expected_artifact,
    expected_run_name,
    expected_summary_run_name,
    expected_workflow,
    expected_workflow_name,
    expected_workflow_path,
    generate_dispatch_nonce,
    select_exact_registration,
    select_exact_summary_registration,
    validate_dispatch_nonce,
    validate_artifacts,
    validate_manifest,
    validate_manifest_text,
    validate_run,
    validate_sha_binding,
    validate_summary_dispatch,
    validate_summary_run,
)

ORCHESTRATION_ID = "orchestration-123456-2"
EXPECTED_SHA = "a" * 40
BRANCH = "main"
REPOSITORY = "example/dashboard"
SUMMARY_RUN_ID = 30_001
SUMMARY_NONCE = "f" * 64


def nonce_for(batch: int) -> str:
    return f"{batch:064x}"


def records() -> list[dict[str, object]]:
    return [
        {
            "batch": batch,
            "workflow": expected_workflow(batch),
            "artifact": expected_artifact(batch),
            "dispatch_nonce": nonce_for(batch),
            "run_id": 10_000 + batch,
            "run_attempt": 1,
        }
        for batch in range(1, BATCH_COUNT + 1)
    ]


def manifest() -> dict[str, object]:
    return build_manifest(
        orchestration_id=ORCHESTRATION_ID,
        expected_sha=EXPECTED_SHA,
        branch=BRANCH,
        records=records(),
    )


def run_payload(
    batch: int,
    *,
    run_id: int | None = None,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict[str, object]:
    return {
        "id": run_id or 10_000 + batch,
        "run_attempt": 1,
        "name": expected_workflow_name(batch),
        "path": expected_workflow_path(batch),
        "display_title": expected_run_name(
            batch,
            ORCHESTRATION_ID,
            nonce_for(batch),
        ),
        "event": "workflow_dispatch",
        "head_branch": BRANCH,
        "head_sha": EXPECTED_SHA,
        "status": status,
        "conclusion": conclusion,
        "repository": {"full_name": REPOSITORY},
    }


def summary_run_payload(
    *,
    run_id: int = SUMMARY_RUN_ID,
    dispatch_nonce: str = SUMMARY_NONCE,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": 1,
        "name": "Global Test Summary (All Batches)",
        "path": ".github/workflows/test-all-packages-summary.yml",
        "display_title": expected_summary_run_name(
            ORCHESTRATION_ID,
            dispatch_nonce,
        ),
        "event": "workflow_dispatch",
        "head_branch": BRANCH,
        "head_sha": EXPECTED_SHA,
        "status": status,
        "conclusion": conclusion,
        "repository": {"full_name": REPOSITORY},
    }


def artifacts_payload(
    batch: int,
    *,
    run_id: int | None = None,
) -> dict[str, object]:
    selected_run_id = run_id or 10_000 + batch
    return {
        "total_count": 1,
        "artifacts": [
            {
                "id": 20_000 + batch,
                "name": expected_artifact(batch),
                "expired": False,
                "workflow_run": {"id": selected_run_id},
            }
        ],
    }


class ManifestContractTests(unittest.TestCase):
    def test_builds_one_canonical_compact_22_record_manifest(self) -> None:
        payload = manifest()
        self.assertEqual(len(payload["batches"]), BATCH_COUNT)
        self.assertEqual(
            [record["batch"] for record in payload["batches"]],
            list(range(1, BATCH_COUNT + 1)),
        )
        rendered = canonical_json(payload)
        self.assertNotIn("\n", rendered)
        self.assertNotIn(": ", rendered)
        self.assertEqual(validate_manifest(copy.deepcopy(payload)), payload)

    def test_rejects_missing_extra_duplicate_and_reordered_records(self) -> None:
        mutations = []

        missing = manifest()
        missing["batches"] = missing["batches"][:-1]
        mutations.append(missing)

        extra = manifest()
        extra["batches"] = [*extra["batches"], copy.deepcopy(extra["batches"][-1])]
        mutations.append(extra)

        duplicate_id = manifest()
        duplicate_id["batches"][1]["run_id"] = duplicate_id["batches"][0]["run_id"]
        mutations.append(duplicate_id)

        duplicate_nonce = manifest()
        duplicate_nonce["batches"][1]["dispatch_nonce"] = duplicate_nonce["batches"][0][
            "dispatch_nonce"
        ]
        mutations.append(duplicate_nonce)

        rerun_attempt = manifest()
        rerun_attempt["batches"][0]["run_attempt"] = 2
        mutations.append(rerun_attempt)

        reordered = manifest()
        reordered["batches"][0], reordered["batches"][1] = (
            reordered["batches"][1],
            reordered["batches"][0],
        )
        mutations.append(reordered)

        for payload in mutations:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractError):
                    validate_manifest(payload)

    def test_rejects_wrong_workflow_artifact_and_unexpected_keys(self) -> None:
        cases = []
        wrong_workflow = manifest()
        wrong_workflow["batches"][0]["workflow"] = "other.yml"
        cases.append(wrong_workflow)
        wrong_artifact = manifest()
        wrong_artifact["batches"][0]["artifact"] = "other-results"
        cases.append(wrong_artifact)
        extra_key = manifest()
        extra_key["unexpected"] = True
        cases.append(extra_key)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractError):
                    validate_manifest(payload)

    def test_rejects_stale_sha_wrong_branch_and_control_payloads(self) -> None:
        with self.assertRaisesRegex(ContractError, "expected_sha"):
            validate_manifest(manifest(), expected_sha="b" * 40)
        with self.assertRaisesRegex(ContractError, "branch"):
            validate_manifest(manifest(), expected_branch="release")

        for field, value in (
            ("orchestration_id", "orchestration-123\n-2"),
            ("expected_sha", "A" * 40),
            ("branch", "../main"),
            ("branch", "main\x00release"),
        ):
            payload = manifest()
            payload[field] = value
            with self.subTest(field=field, value=repr(value)):
                with self.assertRaises(ContractError):
                    validate_manifest(payload)

    def test_summary_input_requires_bounded_canonical_compact_json(self) -> None:
        rendered = canonical_json(manifest())
        self.assertEqual(
            validate_manifest_text(
                rendered,
                expected_sha=EXPECTED_SHA,
                expected_branch=BRANCH,
                repository=REPOSITORY,
            ),
            manifest(),
        )
        for malformed in (
            json.dumps(manifest(), indent=2),
            f" {rendered}",
            f"{rendered}\n",
            '{"schema":"wrong"}',
            rendered + (" " * 20_000),
            '{"branch":"main\\u0000release"}',
        ):
            with self.subTest(malformed=malformed[:80]):
                with self.assertRaises(ContractError):
                    validate_manifest_text(
                        malformed,
                        expected_sha=EXPECTED_SHA,
                        expected_branch=BRANCH,
                        repository=REPOSITORY,
                    )

    def test_stale_workflow_checkout_or_remote_base_is_rejected(self) -> None:
        self.assertEqual(
            validate_sha_binding(
                expected_sha=EXPECTED_SHA,
                workflow_sha=EXPECTED_SHA,
                checkout_sha=EXPECTED_SHA,
                remote_sha=EXPECTED_SHA,
            ),
            EXPECTED_SHA,
        )
        for field in ("workflow_sha", "checkout_sha", "remote_sha"):
            values = {
                "expected_sha": EXPECTED_SHA,
                "workflow_sha": EXPECTED_SHA,
                "checkout_sha": EXPECTED_SHA,
                "remote_sha": EXPECTED_SHA,
            }
            values[field] = "b" * 40
            with self.subTest(field=field):
                with self.assertRaisesRegex(ContractError, field):
                    validate_sha_binding(**values)

    def test_dispatch_nonces_are_unguessable_canonical_and_unique(self) -> None:
        generated = {generate_dispatch_nonce() for _ in range(128)}
        self.assertEqual(len(generated), 128)
        for nonce in generated:
            self.assertEqual(validate_dispatch_nonce(nonce), nonce)
            self.assertRegex(nonce, r"\A[0-9a-f]{64}\Z")
        for invalid in ("", "a" * 32, "A" * 64, "g" * 64, "a" * 63 + "\n"):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ContractError):
                    validate_dispatch_nonce(invalid)

    def test_cli_records_secret_nonce_before_binding_exact_run(self) -> None:
        helper = SCRIPT_ROOT / "orchestration_contract.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records_path = root / "records.json"
            nonce_path = root / "nonce"
            dispatch_path = root / "dispatch.json"
            manifest_path = root / "manifest.json"
            summary_dispatch_path = root / "summary-dispatch.json"
            summary_registration_path = root / "summary-registration.json"
            summary_run_path = root / "summary-run.json"

            def run(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(helper), *arguments],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            run("init-records", "--output", str(records_path))
            generated = run(
                "generate-dispatch-nonce",
                "--output",
                str(nonce_path),
            )
            self.assertEqual(generated.stdout, "")
            nonce = nonce_path.read_text(encoding="ascii")
            self.assertEqual(validate_dispatch_nonce(nonce), nonce)
            self.assertEqual(nonce_path.stat().st_mode & 0o077, 0)

            run(
                "prepare-record",
                "--records",
                str(records_path),
                "--batch",
                "1",
                "--dispatch-nonce-file",
                str(nonce_path),
            )
            pending = json.loads(records_path.read_text(encoding="utf-8"))
            self.assertEqual(pending[0]["dispatch_nonce"], nonce)
            self.assertNotIn("run_id", pending[0])

            run(
                "batch-dispatch-payload",
                "--batch",
                "1",
                "--orchestration-id",
                ORCHESTRATION_ID,
                "--dispatch-nonce-file",
                str(nonce_path),
                "--expected-sha",
                EXPECTED_SHA,
                "--branch",
                BRANCH,
                "--output",
                str(dispatch_path),
            )
            dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
            self.assertEqual(dispatch["inputs"]["dispatch_nonce"], nonce)

            run(
                "bind-record-run",
                "--records",
                str(records_path),
                "--batch",
                "1",
                "--dispatch-nonce-file",
                str(nonce_path),
                "--run-id",
                "10001",
                "--run-attempt",
                "1",
            )
            bound = json.loads(records_path.read_text(encoding="utf-8"))
            self.assertEqual(bound[0]["run_id"], 10_001)
            self.assertEqual(bound[0]["run_attempt"], 1)

            manifest_path.write_text(canonical_json(manifest()), encoding="utf-8")
            summary_nonce_path = root / "summary-nonce"
            run(
                "generate-dispatch-nonce",
                "--output",
                str(summary_nonce_path),
            )
            summary_nonce = summary_nonce_path.read_text(encoding="ascii")
            self.assertEqual(validate_dispatch_nonce(summary_nonce), summary_nonce)

            summary_name = run(
                "summary-run-name",
                "--orchestration-id",
                ORCHESTRATION_ID,
                "--dispatch-nonce",
                summary_nonce,
            )
            self.assertEqual(
                summary_name.stdout.strip(),
                expected_summary_run_name(ORCHESTRATION_ID, summary_nonce),
            )
            summary_endpoint = run(
                "summary-runs-endpoint",
                "--branch",
                BRANCH,
                "--expected-sha",
                EXPECTED_SHA,
                "--repository",
                REPOSITORY,
            )
            self.assertIn(
                "repos/example/dashboard/actions/workflows/"
                "test-all-packages-summary.yml/runs?",
                summary_endpoint.stdout,
            )
            self.assertIn("event=workflow_dispatch", summary_endpoint.stdout)
            self.assertIn("branch=main", summary_endpoint.stdout)
            self.assertIn(f"head_sha={EXPECTED_SHA}", summary_endpoint.stdout)

            run(
                "summary-dispatch-payload",
                "--manifest",
                str(manifest_path),
                "--ref",
                BRANCH,
                "--dispatch-nonce-file",
                str(summary_nonce_path),
                "--output",
                str(summary_dispatch_path),
            )
            summary_dispatch = json.loads(
                summary_dispatch_path.read_text(encoding="utf-8")
            )
            self.assertEqual(summary_dispatch["ref"], BRANCH)
            self.assertEqual(summary_dispatch["inputs"]["expected_sha"], EXPECTED_SHA)
            self.assertEqual(
                summary_dispatch["inputs"]["orchestration_id"],
                ORCHESTRATION_ID,
            )
            self.assertEqual(
                summary_dispatch["inputs"]["dispatch_nonce"],
                summary_nonce,
            )

            run(
                "validate-summary-dispatch",
                "--manifest",
                str(manifest_path),
                "--orchestration-id",
                ORCHESTRATION_ID,
                "--dispatch-nonce",
                summary_nonce,
                "--expected-sha",
                EXPECTED_SHA,
                "--branch",
                BRANCH,
                "--repository",
                REPOSITORY,
            )
            summary_registration_path.write_text(
                json.dumps(
                    {
                        "workflow_runs": [
                            summary_run_payload(
                                dispatch_nonce=summary_nonce,
                                status="queued",
                                conclusion=None,
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selected = run(
                "select-summary-registration",
                "--payload",
                str(summary_registration_path),
                "--manifest",
                str(manifest_path),
                "--dispatch-nonce-file",
                str(summary_nonce_path),
                "--expected-sha",
                EXPECTED_SHA,
                "--branch",
                BRANCH,
                "--repository",
                REPOSITORY,
            )
            self.assertEqual(selected.stdout, f"{SUMMARY_RUN_ID}\n")
            summary_run_path.write_text(
                json.dumps(summary_run_payload(dispatch_nonce=summary_nonce)),
                encoding="utf-8",
            )
            validated = run(
                "validate-summary-run",
                "--payload",
                str(summary_run_path),
                "--manifest",
                str(manifest_path),
                "--dispatch-nonce-file",
                str(summary_nonce_path),
                "--expected-sha",
                EXPECTED_SHA,
                "--branch",
                BRANCH,
                "--repository",
                REPOSITORY,
                "--expected-run-id",
                str(SUMMARY_RUN_ID),
            )
            self.assertEqual(validated.stdout, "completed\tsuccess\n")


class RunIdentityTests(unittest.TestCase):
    def test_overlapping_unrelated_runs_do_not_win_registration(self) -> None:
        exact = run_payload(1, status="queued", conclusion=None)
        unrelated = run_payload(1, run_id=999, status="queued", conclusion=None)
        unrelated["display_title"] = "Arm64 Batch 1 [manual-999-1]"
        payload = {"workflow_runs": [unrelated, exact]}
        self.assertEqual(
            select_exact_registration(
                payload,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            10_001,
        )

    def test_paginated_registration_checks_every_exact_title(self) -> None:
        unrelated = run_payload(1, run_id=999, status="queued", conclusion=None)
        unrelated["display_title"] = "Arm64 Batch 1 [manual-999-1]"
        exact = run_payload(1, status="queued", conclusion=None)
        pages = [
            {"workflow_runs": [unrelated]},
            {"workflow_runs": [exact]},
        ]
        self.assertEqual(
            select_exact_registration(
                pages,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            10_001,
        )

        duplicate = run_payload(
            1,
            run_id=77_777,
            status="queued",
            conclusion=None,
        )
        pages.append({"workflow_runs": [duplicate]})
        with self.assertRaisesRegex(ContractError, "multiple runs"):
            select_exact_registration(
                pages,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )

    def test_duplicate_exact_registration_is_rejected(self) -> None:
        payload = {
            "workflow_runs": [
                run_payload(1, status="queued", conclusion=None),
                run_payload(
                    1,
                    run_id=77_777,
                    status="queued",
                    conclusion=None,
                ),
            ]
        }
        with self.assertRaisesRegex(ContractError, "multiple runs"):
            select_exact_registration(
                payload,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )

    def test_behavior_changing_prefetch_run_cannot_match_orchestration(self) -> None:
        malicious = run_payload(1, status="queued", conclusion=None)
        malicious["display_title"] = (
            f"Arm64 Batch 1 [{ORCHESTRATION_ID}] "
            f"[nonce:{nonce_for(1)}] [prefetch:present]"
        )
        self.assertIsNone(
            select_exact_registration(
                {"workflow_runs": [malicious]},
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )
        )

        exact = run_payload(1, run_id=88_888, status="queued", conclusion=None)
        self.assertEqual(
            select_exact_registration(
                {"workflow_runs": [malicious, exact]},
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            88_888,
        )

    def test_nonce_blocks_predispatch_impersonation_and_late_duplicates(self) -> None:
        attacker = run_payload(
            1,
            run_id=66_666,
            status="queued",
            conclusion=None,
        )
        attacker["display_title"] = expected_run_name(
            1,
            ORCHESTRATION_ID,
            nonce_for(2),
        )
        genuine = run_payload(1, status="queued", conclusion=None)
        self.assertEqual(
            select_exact_registration(
                {"workflow_runs": [attacker, genuine]},
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            10_001,
        )

        duplicate = run_payload(
            1,
            run_id=77_777,
            status="queued",
            conclusion=None,
        )
        with self.assertRaisesRegex(ContractError, "multiple runs"):
            select_exact_registration(
                {"workflow_runs": [genuine, duplicate]},
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )

        manual_title = (
            "Arm64 Batch 1 [manual-123-1] [nonce:manual-only] [prefetch:none]"
        )
        self.assertNotEqual(
            manual_title,
            expected_run_name(1, ORCHESTRATION_ID, nonce_for(1)),
        )

    def test_static_and_dynamic_api_names_are_accepted(self) -> None:
        for api_name in (
            expected_workflow_name(1),
            expected_run_name(1, ORCHESTRATION_ID, nonce_for(1)),
        ):
            payload = run_payload(1)
            payload["name"] = api_name
            with self.subTest(api_name=api_name):
                result = validate_run(
                    payload,
                    batch=1,
                    orchestration_id=ORCHESTRATION_ID,
                    dispatch_nonce=nonce_for(1),
                    expected_sha=EXPECTED_SHA,
                    branch=BRANCH,
                    repository=REPOSITORY,
                    expected_run_id=10_001,
                    require_completed=True,
                )
                self.assertEqual(result["id"], 10_001)

    def test_wrong_sha_branch_workflow_event_title_repo_or_id_is_rejected(self) -> None:
        mutations = {
            "head_sha": "b" * 40,
            "head_branch": "release",
            "name": "Wrong workflow",
            "path": ".github/workflows/wrong.yml",
            "event": "push",
            "display_title": "wrong title",
            "id": 99_999,
            "run_attempt": 2,
        }
        for field, value in mutations.items():
            payload = run_payload(1)
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ContractError):
                    validate_run(
                        payload,
                        batch=1,
                        orchestration_id=ORCHESTRATION_ID,
                        dispatch_nonce=nonce_for(1),
                        expected_sha=EXPECTED_SHA,
                        branch=BRANCH,
                        repository=REPOSITORY,
                        expected_run_id=10_001,
                        require_completed=True,
                    )

        payload = run_payload(1)
        payload["repository"] = {"full_name": "example/other"}
        with self.assertRaises(ContractError):
            validate_run(
                payload,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=10_001,
                require_completed=True,
            )

    def test_incomplete_and_canceled_runs_are_rejected_by_summary(self) -> None:
        incomplete = run_payload(
            1,
            status="in_progress",
            conclusion=None,
        )
        with self.assertRaisesRegex(ContractError, "not completed"):
            validate_run(
                incomplete,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=10_001,
                require_completed=True,
            )
        self.assertEqual(
            validate_run(
                incomplete,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=10_001,
                require_completed=False,
            )["status"],
            "in_progress",
        )

        canceled = run_payload(1, conclusion="cancelled")
        with self.assertRaisesRegex(ContractError, "rejected conclusion"):
            validate_run(
                canceled,
                batch=1,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(1),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=10_001,
                require_completed=True,
            )

    def test_genuine_package_failure_is_allowed_as_completed(self) -> None:
        result = validate_run(
            run_payload(1, conclusion="failure"),
            batch=1,
            orchestration_id=ORCHESTRATION_ID,
            dispatch_nonce=nonce_for(1),
            expected_sha=EXPECTED_SHA,
            branch=BRANCH,
            repository=REPOSITORY,
            expected_run_id=10_001,
            require_completed=True,
        )
        self.assertEqual(result["conclusion"], "failure")


class SummaryRunIdentityTests(unittest.TestCase):
    def test_exact_summary_registration_and_dispatch_are_accepted(self) -> None:
        summary_manifest = manifest()
        exact = summary_run_payload(status="queued", conclusion=None)
        unrelated = summary_run_payload(
            run_id=99_999,
            status="queued",
            conclusion=None,
        )
        unrelated["display_title"] = "Global Summary [manual-999-1] [nonce:wrong]"
        pages = [
            {"workflow_runs": [unrelated]},
            {"workflow_runs": [exact]},
        ]

        self.assertEqual(
            select_exact_summary_registration(
                pages,
                manifest=summary_manifest,
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            SUMMARY_RUN_ID,
        )
        self.assertEqual(
            validate_summary_dispatch(
                summary_manifest,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            ),
            summary_manifest,
        )

        for api_name in (
            "Global Test Summary (All Batches)",
            expected_summary_run_name(ORCHESTRATION_ID, SUMMARY_NONCE),
        ):
            payload = summary_run_payload()
            payload["name"] = api_name
            with self.subTest(api_name=api_name):
                result = validate_summary_run(
                    payload,
                    manifest=summary_manifest,
                    dispatch_nonce=SUMMARY_NONCE,
                    expected_sha=EXPECTED_SHA,
                    branch=BRANCH,
                    repository=REPOSITORY,
                    expected_run_id=SUMMARY_RUN_ID,
                    require_completed=True,
                )
                self.assertEqual(result["id"], SUMMARY_RUN_ID)

    def test_duplicate_exact_summary_registration_is_rejected(self) -> None:
        payload = {
            "workflow_runs": [
                summary_run_payload(status="queued", conclusion=None),
                summary_run_payload(
                    run_id=77_777,
                    status="queued",
                    conclusion=None,
                ),
            ]
        }
        with self.assertRaisesRegex(ContractError, "multiple summary runs"):
            select_exact_summary_registration(
                payload,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )

    def test_wrong_summary_nonce_sha_branch_repo_path_and_id_are_rejected(self) -> None:
        wrong_nonce = "e" * 64
        self.assertIsNone(
            select_exact_summary_registration(
                {"workflow_runs": [summary_run_payload()]},
                manifest=manifest(),
                dispatch_nonce=wrong_nonce,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )
        )
        with self.assertRaises(ContractError):
            validate_summary_run(
                summary_run_payload(),
                manifest=manifest(),
                dispatch_nonce=wrong_nonce,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=True,
            )

        mutations = {
            "head_sha": "b" * 40,
            "head_branch": "release",
            "path": ".github/workflows/wrong.yml",
            "display_title": "wrong title",
            "id": 99_999,
            "run_attempt": 2,
        }
        for field, value in mutations.items():
            payload = summary_run_payload()
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ContractError):
                    validate_summary_run(
                        payload,
                        manifest=manifest(),
                        dispatch_nonce=SUMMARY_NONCE,
                        expected_sha=EXPECTED_SHA,
                        branch=BRANCH,
                        repository=REPOSITORY,
                        expected_run_id=SUMMARY_RUN_ID,
                        require_completed=True,
                    )

        payload = summary_run_payload()
        payload["repository"] = {"full_name": "example/other"}
        with self.assertRaises(ContractError):
            validate_summary_run(
                payload,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=True,
            )

    def test_summary_dispatch_rejects_wrong_manifest_binding(self) -> None:
        for field, value in (
            ("orchestration_id", "orchestration-999-1"),
            ("expected_sha", "b" * 40),
            ("branch", "release"),
        ):
            values = {
                "orchestration_id": ORCHESTRATION_ID,
                "dispatch_nonce": SUMMARY_NONCE,
                "expected_sha": EXPECTED_SHA,
                "branch": BRANCH,
                "repository": REPOSITORY,
            }
            values[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ContractError):
                    validate_summary_dispatch(manifest(), **values)

        with self.assertRaises(ContractError):
            validate_summary_dispatch(
                manifest(),
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce="not-a-nonce",
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
            )
        with self.assertRaises(ContractError):
            validate_summary_dispatch(
                manifest(),
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository="bad repository",
            )

    def test_summary_completion_states_are_validated(self) -> None:
        incomplete = summary_run_payload(status="in_progress", conclusion=None)
        with self.assertRaisesRegex(ContractError, "not completed"):
            validate_summary_run(
                incomplete,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=True,
            )
        self.assertEqual(
            validate_summary_run(
                incomplete,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=False,
            )["status"],
            "in_progress",
        )

        invalid_incomplete = summary_run_payload(
            status="queued",
            conclusion="success",
        )
        with self.assertRaisesRegex(ContractError, "invalid incomplete state"):
            validate_summary_run(
                invalid_incomplete,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=False,
            )

        canceled = summary_run_payload(conclusion="cancelled")
        with self.assertRaisesRegex(ContractError, "rejected conclusion"):
            validate_summary_run(
                canceled,
                manifest=manifest(),
                dispatch_nonce=SUMMARY_NONCE,
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
                repository=REPOSITORY,
                expected_run_id=SUMMARY_RUN_ID,
                require_completed=True,
            )


class ArtifactContractTests(unittest.TestCase):
    def test_accepts_one_nonexpired_artifact_from_exact_run(self) -> None:
        result = validate_artifacts(
            artifacts_payload(1),
            batch=1,
            expected_run_id=10_001,
        )
        self.assertEqual(result["name"], "batch1-test-results")

    def test_accepts_one_exact_artifact_across_complete_pages(self) -> None:
        expected = artifacts_payload(1)["artifacts"][0]
        unrelated = {
            "id": 33_333,
            "name": "package-detail",
            "expired": False,
            "workflow_run": {"id": 10_001},
        }
        pages = [
            {"total_count": 2, "artifacts": [unrelated]},
            {"total_count": 2, "artifacts": [expected]},
        ]
        result = validate_artifacts(
            pages,
            batch=1,
            expected_run_id=10_001,
        )
        self.assertEqual(result["name"], "batch1-test-results")

    def test_rejects_missing_duplicate_expired_and_wrong_run_artifacts(self) -> None:
        missing = {"total_count": 0, "artifacts": []}

        duplicate = artifacts_payload(1)
        duplicate["artifacts"].append(copy.deepcopy(duplicate["artifacts"][0]))
        duplicate["artifacts"][1]["id"] = 88_888
        duplicate["total_count"] = 2

        expired = artifacts_payload(1)
        expired["artifacts"][0]["expired"] = True

        wrong_run = artifacts_payload(1)
        wrong_run["artifacts"][0]["workflow_run"]["id"] = 55_555

        truncated = artifacts_payload(1)
        truncated["total_count"] = 2

        for payload in (missing, duplicate, expired, wrong_run, truncated):
            with self.subTest(payload=payload):
                with self.assertRaises(ContractError):
                    validate_artifacts(
                        payload,
                        batch=1,
                        expected_run_id=10_001,
                    )


class WorkflowExactRunBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = SCRIPT_ROOT.parents[1]
        cls.workflow_root = cls.repository / ".github/workflows"

    def test_all_22_wrappers_have_exact_inputs_and_unique_run_names(self) -> None:
        wrappers = sorted(
            self.workflow_root.glob("test-all-packages-batch*.yml"),
            key=lambda path: int(path.stem.removeprefix("test-all-packages-batch")),
        )
        self.assertEqual(len(wrappers), BATCH_COUNT)
        for batch, wrapper in enumerate(wrappers, start=1):
            text = wrapper.read_text(encoding="utf-8")
            expected = (
                f"run-name: Arm64 Batch {batch} "
                "[${{ inputs.orchestration_id || "
                "format('manual-{0}-{1}', github.run_id, github.run_attempt) }}]"
                " [nonce:${{ inputs.dispatch_nonce || 'manual-only' }}]"
            )
            if batch in PREFETCH_BATCHES:
                expected += (
                    " [prefetch:${{ (inputs.prefetch_run_id == '' && "
                    "inputs.prefetch_artifact_name == '') && "
                    "'none' || 'present' }}]"
                )
            with self.subTest(batch=batch):
                self.assertIn(expected, text)
                dispatch_section = text.split("  workflow_dispatch:", 1)[1].split(
                    "  workflow_call:", 1
                )[0]
                call_section = text.split("  workflow_call:", 1)[1].split(
                    "jobs:", 1
                )[0]

                def input_block(section: str, input_name: str) -> str:
                    lines = section.splitlines()
                    start = lines.index(f"      {input_name}") + 1
                    body = []
                    for line in lines[start:]:
                        if line.startswith("      ") and not line.startswith(
                            "        "
                        ):
                            break
                        body.append(line)
                    return "\n".join(body)

                for input_name in (
                    "orchestration_id:",
                    "dispatch_nonce:",
                    "expected_sha:",
                    "expected_branch:",
                ):
                    self.assertEqual(text.count(input_name), 2)
                    dispatch_input = input_block(dispatch_section, input_name)
                    call_input = input_block(call_section, input_name)
                    self.assertIn("        required: false", dispatch_input)
                    self.assertIn('        default: ""', dispatch_input)
                    self.assertIn("        type: string", dispatch_input)
                    self.assertIn("        required: true", call_input)
                    self.assertIn("        type: string", call_input)
                    self.assertNotIn("default:", call_input)
                self.assertEqual(text.count("workflow_dispatch:"), 1)
                self.assertEqual(text.count("workflow_call:"), 1)
                if batch in PREFETCH_BATCHES:
                    for input_name in (
                        "prefetch_run_id:",
                        "prefetch_artifact_name:",
                    ):
                        self.assertGreaterEqual(text.count(input_name), 2)
                        dispatch_input = input_block(dispatch_section, input_name)
                        call_input = input_block(call_section, input_name)
                        self.assertIn("        required: false", dispatch_input)
                        self.assertIn('        default: ""', dispatch_input)
                        self.assertIn("        type: string", dispatch_input)
                        self.assertIn("        required: false", call_input)
                        self.assertIn('        default: ""', call_input)
                        self.assertIn("        type: string", call_input)

    def test_orchestrator_dispatch_explicitly_disables_prefetch_behavior(self) -> None:
        for batch in range(1, BATCH_COUNT + 1):
            payload = batch_dispatch_payload(
                batch=batch,
                orchestration_id=ORCHESTRATION_ID,
                dispatch_nonce=nonce_for(batch),
                expected_sha=EXPECTED_SHA,
                branch=BRANCH,
            )
            inputs = payload["inputs"]
            with self.subTest(batch=batch):
                self.assertEqual(inputs["dispatch_nonce"], nonce_for(batch))
                if batch in PREFETCH_BATCHES:
                    self.assertEqual(inputs["prefetch_run_id"], "")
                    self.assertEqual(inputs["prefetch_artifact_name"], "")
                else:
                    self.assertNotIn("prefetch_run_id", inputs)
                    self.assertNotIn("prefetch_artifact_name", inputs)

    def test_orchestrator_and_summary_use_only_exact_structured_binding(self) -> None:
        orchestrator = (
            self.workflow_root / "test-all-packages-orchestrator.yml"
        ).read_text(encoding="utf-8")
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "createdAt",
            "start_time",
            "gh run list",
            "head -n",
            "head -1",
        ):
            self.assertNotIn(forbidden, orchestrator)
        self.assertIn("orchestration-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", orchestrator)
        self.assertIn("gh api --paginate --slurp", orchestrator)
        self.assertIn("--expected-sha \"$EXPECTED_SHA\"", orchestrator)
        self.assertIn("generate-dispatch-nonce", orchestrator)
        self.assertIn("prepare-record", orchestrator)
        self.assertIn("bind-record-run", orchestrator)
        self.assertIn("--dispatch-nonce-file \"$nonce_file\"", orchestrator)
        self.assertIn("select-registration", orchestrator)
        self.assertIn("record-runtime", orchestrator)
        self.assertIn("summary-dispatch-payload", orchestrator)
        self.assertIn("--input .orchestration/summary-dispatch.json", orchestrator)
        dispatch_step = orchestrator.split(
            "- name: Dispatch and capture exact batch runs", 1
        )[1].split("- name: Wait for captured batch runs", 1)[0]
        self.assertLess(
            dispatch_step.index("prepare-record"),
            dispatch_step.index("actions/workflows/${WORKFLOW}/dispatches"),
        )
        self.assertNotIn('echo "$DISPATCH_NONCE"', dispatch_step)
        self.assertNotIn('cat "$nonce_file"', dispatch_step)

        self.assertIn("run_manifest:", summary)
        self.assertIn("expected_sha:", summary)
        self.assertIn("required: true", summary)
        self.assertIn("validate-manifest-env", summary)
        self.assertIn("validate-run", summary)
        self.assertIn("validate-artifacts", summary)
        self.assertIn(
            'attestation_helper=".github/scripts/batch_artifact_attestation.py"',
            summary,
        )
        self.assertIn('python3 "$attestation_helper" verify', summary)
        self.assertGreaterEqual(summary.count("select-registration"), 1)
        self.assertIn('[[ "$REGISTERED_RUN_ID" != "$RUN_ID" ]]', summary)
        self.assertIn('source.name == "batch-attestation.json"', summary)
        self.assertIn("source.parent.parent == downloaded_dir", summary)
        self.assertIn('gh run download "$RUN_ID" -n "$ARTIFACT"', summary)
        self.assertNotIn("createdAt", summary)
        self.assertNotIn("start_time", summary)
        self.assertNotIn("gh run list", summary)
        self.assertEqual(summary.count("validate-base"), 2)
        self.assertGreaterEqual(
            summary.count('--remote-sha "$remote_sha"'),
            2,
        )
        self.assertIn("steps.publication_base.outcome == 'success'", summary)
        self.assertIn(".orchestration", summary)
        self.assertIn(
            "head-branch: automation/generated-data/global-test-results/"
            "${{ github.ref_name }}/${{ steps.generated_data_base.outputs.sha }}",
            summary,
        )
        self.assertNotIn(
            "head-branch: automation/generated-data/global-test-results/"
            "${{ github.ref_name }}\n",
            summary,
        )

        checkout_step = summary.split("- name: Checkout repository", 1)[1].split(
            "- name: Bind exact generated-data base", 1
        )[0]
        bind_step = summary.split("- name: Bind exact generated-data base", 1)[
            1
        ].split("- name: Validate exact batch-run manifest", 1)[0]
        self.assertIn("ref: ${{ github.sha }}", checkout_step)
        self.assertNotIn("inputs.expected_sha", checkout_step)
        self.assertIn("persist-credentials: false", checkout_step)
        comparisons = (
            '[[ "$EXPECTED_SHA" == "$WORKFLOW_SHA" ]]',
            '[[ "$actual_sha" == "$WORKFLOW_SHA" ]]',
            '[[ "$remote_sha" == "$WORKFLOW_SHA" ]]',
        )
        helper_index = bind_step.index(
            "python3 .github/scripts/orchestration_contract.py"
        )
        for comparison in comparisons:
            self.assertIn(comparison, bind_step)
            self.assertLess(bind_step.index(comparison), helper_index)
        bind_start = summary.index("- name: Bind exact generated-data base")
        first_helper = summary.index("python3 ")
        self.assertGreater(first_helper, bind_start)
        self.assertLess(first_helper, summary.index("GH_TOKEN:"))

    def test_all_batch_wrappers_cap_permissions_and_pin_summary_actions(self) -> None:
        checkout = (
            "actions/checkout@"
            "3d3c42e5aac5ba805825da76410c181273ba90b1"
        )
        upload = (
            "actions/upload-artifact@"
            "ea165f8d65b6e75b540449e92b4886f43607fa02"
        )
        for batch in range(1, BATCH_COUNT + 1):
            wrapper = (
                self.workflow_root / f"test-all-packages-batch{batch}.yml"
            ).read_text(encoding="utf-8")
            preamble, jobs = wrapper.split("jobs:", 1)
            summary = jobs.split("\n  summary:\n", 1)[1]
            with self.subTest(batch=batch):
                self.assertIn(
                    "permissions:\n  contents: read",
                    preamble,
                )
                self.assertTrue(
                    summary.startswith(
                        "    permissions:\n"
                        "      actions: read\n"
                        "      contents: read\n"
                    )
                )
                self.assertEqual(wrapper.count(checkout), 1)
                self.assertEqual(wrapper.count(upload), 1)
                self.assertEqual(
                    wrapper.count("persist-credentials: false"),
                    1,
                )
                self.assertNotRegex(wrapper, r"(?m)^\s*uses:\s*actions/checkout@v")
                self.assertNotRegex(wrapper, r"(?m)^\s*uses:\s*actions/upload-artifact@v")

    def test_collectors_attest_exact_results_before_artifact_upload(self) -> None:
        for batch in range(1, BATCH_COUNT + 1):
            wrapper = (
                self.workflow_root / f"test-all-packages-batch{batch}.yml"
            ).read_text(encoding="utf-8")
            summary = wrapper.split("\n  summary:\n", 1)[1]
            collect_index = summary.index("- name: Collect batch results")
            attest_index = summary.index("- name: Attest complete batch results")
            upload_index = summary.index("- name: Upload batch test results")
            upload = summary[upload_index:]
            with self.subTest(batch=batch):
                self.assertIn("    if: always()", summary)
                self.assertLess(collect_index, attest_index)
                self.assertLess(attest_index, upload_index)
                self.assertIn(
                    "if: steps.collect.outcome == 'success'",
                    summary[attest_index:upload_index],
                )
                self.assertIn(
                    "if: steps.collect.outcome == 'success' && "
                    "steps.attest.outcome == 'success'",
                    upload,
                )
                self.assertNotIn("if: always()", upload)
                self.assertIn(
                    "batch_artifact_attestation.py create",
                    summary,
                )
                self.assertIn(
                    f'test-all-packages-batch{batch}.yml"',
                    summary,
                )
                self.assertIn("--needs-environment-variable NEEDS_JSON", summary)

    def test_batch21_grants_packages_read_only_to_four_compatible_callers(
        self,
    ) -> None:
        wrapper = (
            self.workflow_root / "test-all-packages-batch21.yml"
        ).read_text(encoding="utf-8")
        callers = {
            "test-ironcore": "test-ironcore.yml",
            "test-openmcp-control-plane-operator": (
                "test-openmcp-control-plane-operator.yml"
            ),
            "test-openmfp-portal": "test-openmfp-portal.yml",
            "test-platform-mesh-operator": "test-platform-mesh-operator.yml",
        }
        self.assertEqual(wrapper.count("      packages: read"), len(callers))
        for job, workflow in callers.items():
            tail = wrapper.split(f"  {job}:\n", 1)[1]
            next_job = re.search(r"(?m)^  [A-Za-z0-9]", tail)
            block = tail[: next_job.start() if next_job else len(tail)].rstrip() + "\n"
            called = (self.workflow_root / workflow).read_text(encoding="utf-8")
            with self.subTest(job=job):
                self.assertEqual(
                    block,
                    "    permissions:\n"
                    "      contents: read\n"
                    "      packages: read\n"
                    f"    uses: ./.github/workflows/{workflow}\n",
                )
                self.assertIn(
                    "permissions:\n  contents: read",
                    called.split("jobs:", 1)[0],
                )
                called_job = called.split("jobs:", 1)[1]
                self.assertIn(
                    "permissions:\n"
                    "      contents: read\n"
                    "      packages: read",
                    called_job,
                )

    def test_all_960_package_workflows_are_registered_exactly_once(self) -> None:
        registrations: list[str] = []
        for wrapper in self.workflow_root.glob("test-all-packages-batch*.yml"):
            registrations.extend(
                re.findall(
                    r"uses:\s+\./\.github/workflows/(test-[A-Za-z0-9._-]+\.yml)",
                    wrapper.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(len(registrations), 960)
        self.assertEqual(len(set(registrations)), 960)
        package_workflow_inventory = {
            path.name
            for path in self.workflow_root.glob("test-*.yml")
            if not path.name.startswith("test-all-packages-")
        }
        self.assertEqual(set(registrations), package_workflow_inventory)
        for workflow in registrations:
            with self.subTest(workflow=workflow):
                self.assertTrue((self.workflow_root / workflow).is_file())


if __name__ == "__main__":
    unittest.main()
