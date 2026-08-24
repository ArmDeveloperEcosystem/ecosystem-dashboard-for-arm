from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import textwrap
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
    expected_workflow,
    expected_workflow_name,
    expected_workflow_path,
    generate_dispatch_nonce,
    select_exact_registration,
    validate_dispatch_nonce,
    validate_artifacts,
    validate_manifest,
    validate_manifest_text,
    validate_run,
    validate_sha_binding,
)

ORCHESTRATION_ID = "orchestration-123456-2"
EXPECTED_SHA = "a" * 40
BRANCH = "main"
REPOSITORY = "example/dashboard"


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

    def _assert_global_summary_delivery_contract(self, summary: str) -> None:
        preamble, jobs = summary.split("\njobs:\n", maxsplit=1)
        generation, delivery = jobs.split("\n  publish-generated-data:\n", maxsplit=1)

        self.assertIn("permissions:\n  actions: read\n  contents: read", preamble)
        self.assertNotIn("contents: write", preamble)
        self.assertNotIn("pull-requests: write", preamble)
        self.assertNotIn("secrets.", preamble)
        self.assertNotIn("DASHBOARD_DELIVERY_APP", preamble)
        self.assertEqual(preamble.count("TRUSTED_PUBLICATION_BRANCH: main"), 1)

        self.assertIn("  global-summary:\n", f"  {generation}")
        self.assertIn("    permissions:\n      actions: read\n      contents: read", generation)
        self.assertNotIn("secrets.", generation)
        self.assertNotIn("DASHBOARD_DELIVERY_APP", generation)
        self.assertNotIn("contents: write", generation)
        self.assertNotIn("pull-requests: write", generation)
        self.assertIn("generated_test_results_artifact.py pack", generation)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", generation)
        self.assertIn(
            "artifact_name: "
            "${{ steps.package_generated_data.outputs.artifact_name }}",
            generation,
        )
        self.assertIn("artifact_sha256:", generation)
        self.assertIn(
            'artifact_name="generated-test-results-'
            '${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
            generation,
        )
        self.assertIn(
            "name: ${{ steps.package_generated_data.outputs.artifact_name }}",
            generation,
        )

        bind_step = generation.split(
            "- name: Bind exact generated-data base", maxsplit=1
        )[1].split("- name: Validate exact batch-run manifest", maxsplit=1)[0]
        final_validation = generation.split(
            "- name: Revalidate exact publication base", maxsplit=1
        )[1].split(
            "- name: Package exact generated test-results artifact", maxsplit=1
        )[0]
        for step in (bind_step, final_validation):
            self.assertIn(
                "EXPECTED_BRANCH: ${{ env.TRUSTED_PUBLICATION_BRANCH }}", step
            )
            self.assertIn("WORKFLOW_REF: ${{ github.ref }}", step)
            self.assertIn("WORKFLOW_REF_NAME: ${{ github.ref_name }}", step)
            self.assertIn('[[ "$EXPECTED_BRANCH" == "main" ]]', step)
            self.assertIn(
                '[[ "$WORKFLOW_REF" == "refs/heads/${EXPECTED_BRANCH}" ]]',
                step,
            )
            self.assertIn(
                '[[ "$WORKFLOW_REF_NAME" == "$EXPECTED_BRANCH" ]]', step
            )
            self.assertIn('[[ "$EXPECTED_SHA" == "$WORKFLOW_SHA" ]]', step)
            self.assertIn('[[ "$actual_sha" == "$WORKFLOW_SHA" ]]', step)
            self.assertIn('[[ "$remote_sha" == "$WORKFLOW_SHA" ]]', step)

        self.assertIn("environment: generated-data-delivery", delivery)
        self.assertIn("permissions:\n      contents: read", delivery)
        self.assertNotIn("${{ github.token }}", delivery)
        self.assertNotIn("${{ secrets.GITHUB_TOKEN }}", delivery)
        self.assertNotIn("GITHUB_TOKEN", delivery)
        self.assertNotIn("personal-access-token", delivery.casefold())
        self.assertNotRegex(delivery, r"(?i)\bpat\b")
        self.assertEqual(
            set(re.findall(r"secrets\.([A-Z0-9_]+)", delivery)),
            {"DASHBOARD_DELIVERY_APP_ID", "DASHBOARD_DELIVERY_APP_PRIVATE_KEY"},
        )
        self.assertEqual(summary.count("secrets.DASHBOARD_DELIVERY_APP_ID"), 1)
        self.assertEqual(
            summary.count("secrets.DASHBOARD_DELIVERY_APP_PRIVATE_KEY"), 1
        )
        self.assertIn(
            "actions/create-github-app-token@"
            "bcd2ba49218906704ab6c1aa796996da409d3eb1",
            delivery,
        )
        for permission in (
            "permission-contents: write",
            "permission-metadata: read",
            "permission-pull-requests: write",
        ):
            self.assertEqual(delivery.count(permission), 1)
        self.assertNotIn("permission-actions:", delivery)
        self.assertNotIn("permission-workflows:", delivery)
        self.assertNotIn("permission-administration:", delivery)
        self.assertIn(
            "DASHBOARD_DELIVERY_APP_BOT_LOGIN is missing or malformed", delivery
        )
        self.assertIn(
            'login.casefold() == "github-actions[bot]"', delivery
        )
        self.assertIn(
            "expected-pr-author-login: "
            "${{ vars.DASHBOARD_DELIVERY_APP_BOT_LOGIN }}",
            delivery,
        )
        self.assertIn("credential-source: github-app", delivery)
        self.assertIn(
            "name: ${{ needs.global-summary.outputs.artifact_name }}", delivery
        )
        self.assertNotIn("github.run_attempt", delivery)
        self.assertNotIn("github.run_id", delivery)
        self.assertEqual(
            delivery.count("GH_TOKEN: ${{ steps.delivery_token.outputs.token }}"), 1
        )
        self.assertIn("persist-credentials: false", delivery)
        self.assertEqual(delivery.count("${{ github.ref_name }}"), 1)
        self.assertIn(
            "base-branch: ${{ env.TRUSTED_PUBLICATION_BRANCH }}", delivery
        )
        self.assertIn(
            "head-branch: automation/generated-data/global-test-results/"
            "${{ env.TRUSTED_PUBLICATION_BRANCH }}",
            delivery,
        )

        ref_guard = delivery.split(
            "- name: Reject an untrusted publication ref", maxsplit=1
        )[1].split(
            "- name: Reject a missing or malformed App bot login", maxsplit=1
        )[0]
        self.assertIn(
            "EXPECTED_BRANCH: ${{ env.TRUSTED_PUBLICATION_BRANCH }}", ref_guard
        )
        self.assertIn("WORKFLOW_REF: ${{ github.ref }}", ref_guard)
        self.assertIn("WORKFLOW_REF_NAME: ${{ github.ref_name }}", ref_guard)
        self.assertIn('[[ "$EXPECTED_BRANCH" == "main" ]]', ref_guard)
        self.assertIn(
            '[[ "$WORKFLOW_REF" == "refs/heads/${EXPECTED_BRANCH}" ]]',
            ref_guard,
        )
        self.assertIn(
            '[[ "$WORKFLOW_REF_NAME" == "$EXPECTED_BRANCH" ]]', ref_guard
        )

        self.assertEqual(
            delivery.count(
                "MINTED_APP_SLUG: ${{ steps.delivery_token.outputs.app-slug }}"
            ),
            1,
        )
        self.assertIn('minted_bot_login = f"{app_slug}[bot]"', delivery)
        self.assertIn(
            "if configured.casefold() != minted_bot_login.casefold():", delivery
        )
        self.assertIn(
            "configured Dashboard Delivery App bot login does not match minted App",
            delivery,
        )

        restore = delivery.index(
            "Validate and restore only generated test-results data"
        )
        mint = delivery.index("Mint short-lived Dashboard Delivery App token")
        identity = delivery.index(
            "Bind configured bot login to minted App identity"
        )
        reverify = delivery.index(
            "Reverify exact generated bytes after credential minting"
        )
        publish = delivery.index(
            "Open or update aggregated test-results review PR"
        )
        self.assertLess(restore, mint)
        self.assertLess(mint, identity)
        self.assertLess(identity, reverify)
        self.assertLess(reverify, publish)
        self.assertIn("generated_test_results_artifact.py restore", delivery)
        self.assertIn("generated_test_results_artifact.py verify-restored", delivery)
        self.assertIn("digest-mismatch: error", delivery)

        self.assertEqual(summary.count("contents: write"), 1)
        self.assertEqual(summary.count("pull-requests: write"), 1)
        self.assertNotRegex(summary, r"(?m)^\s+contents:\s+write\s*$")
        self.assertNotRegex(summary, r"(?m)^\s+pull-requests:\s+write\s*$")

    def test_global_summary_uses_only_protected_app_delivery(self) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")

        self._assert_global_summary_delivery_contract(summary)

    def test_global_summary_contract_rejects_builtin_token_fallback(self) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutations = (
            summary.replace(
                "GH_TOKEN: ${{ steps.delivery_token.outputs.token }}",
                "GH_TOKEN: ${{ github.token }}",
                1,
            ),
            summary.replace(
                "GH_TOKEN: ${{ steps.delivery_token.outputs.token }}",
                "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
                1,
            ),
            summary.replace(
                "GH_TOKEN: ${{ steps.delivery_token.outputs.token }}",
                "GITHUB_TOKEN: ${{ steps.delivery_token.outputs.token }}",
                1,
            ),
        )

        for mutated in mutations:
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_contract_rejects_partial_rerun_artifact_rebinding(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        recomputed = (
            "generated-test-results-${{ github.run_id }}-"
            "${{ github.run_attempt }}"
        )
        mutations = (
            summary.replace(
                "name: ${{ needs.global-summary.outputs.artifact_name }}",
                f"name: {recomputed}",
                1,
            ),
            summary.replace(
                "artifact_name: "
                "${{ steps.package_generated_data.outputs.artifact_name }}\n",
                "",
                1,
            ),
            summary.replace(
                "name: ${{ steps.package_generated_data.outputs.artifact_name }}",
                f"name: {recomputed}",
                1,
            ),
        )

        for mutated in mutations:
            self.assertNotEqual(mutated, summary)
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_contract_rejects_non_main_publication_context(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutations = (
            summary.replace(
                "TRUSTED_PUBLICATION_BRANCH: main",
                "TRUSTED_PUBLICATION_BRANCH: feature",
                1,
            ),
            summary.replace(
                '[[ "$WORKFLOW_REF" == "refs/heads/${EXPECTED_BRANCH}" ]]',
                '[[ "$WORKFLOW_REF" == "refs/heads/feature" ]]',
                1,
            ),
            summary.replace(
                "base-branch: ${{ env.TRUSTED_PUBLICATION_BRANCH }}",
                "base-branch: ${{ github.ref_name }}",
                1,
            ),
            summary.replace(
                "head-branch: automation/generated-data/global-test-results/"
                "${{ env.TRUSTED_PUBLICATION_BRANCH }}",
                "head-branch: automation/generated-data/global-test-results/"
                "${{ github.ref_name }}",
                1,
            ),
        )

        for mutated in mutations:
            self.assertNotEqual(mutated, summary)
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_publication_ref_guard_rejects_feature_branch(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        ref_step = summary.split(
            "- name: Reject an untrusted publication ref", maxsplit=1
        )[1].split(
            "- name: Reject a missing or malformed App bot login", maxsplit=1
        )[0]
        script = textwrap.dedent(
            ref_step.split("run: |\n", maxsplit=1)[1]
        ).strip()

        main = subprocess.run(
            ["/bin/bash", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env={
                "EXPECTED_BRANCH": "main",
                "WORKFLOW_REF": "refs/heads/main",
                "WORKFLOW_REF_NAME": "main",
            },
        )
        feature = subprocess.run(
            ["/bin/bash", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env={
                "EXPECTED_BRANCH": "main",
                "WORKFLOW_REF": "refs/heads/feature",
                "WORKFLOW_REF_NAME": "feature",
            },
        )

        self.assertEqual(main.returncode, 0, main.stderr)
        self.assertNotEqual(feature.returncode, 0)

    def test_global_summary_contract_rejects_missing_environment_or_app_mint(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutations = (
            summary.replace("environment: generated-data-delivery", "", 1),
            summary.replace(
                "actions/create-github-app-token@"
                "bcd2ba49218906704ab6c1aa796996da409d3eb1",
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                1,
            ),
        )

        for mutated in mutations:
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_contract_rejects_wrong_bot_identity(self) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutated = summary.replace(
            "expected-pr-author-login: "
            "${{ vars.DASHBOARD_DELIVERY_APP_BOT_LOGIN }}",
            "expected-pr-author-login: github-actions[bot]",
            1,
        )

        with self.assertRaises(AssertionError):
            self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_minted_app_identity_rejects_mismatched_bot(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        identity_step = summary.split(
            "- name: Bind configured bot login to minted App identity", maxsplit=1
        )[1].split(
            "- name: Reverify exact generated bytes after credential minting",
            maxsplit=1,
        )[0]
        raw_script = identity_step.split("python3 - <<'PY'\n", maxsplit=1)[1].split(
            "\n          PY", maxsplit=1
        )[0]
        script = textwrap.dedent(raw_script)

        matching = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env={
                "CONFIGURED_BOT_LOGIN": "arm-dashboard-delivery[bot]",
                "MINTED_APP_SLUG": "arm-dashboard-delivery",
            },
        )
        mismatched = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env={
                "CONFIGURED_BOT_LOGIN": "different-app[bot]",
                "MINTED_APP_SLUG": "arm-dashboard-delivery",
            },
        )

        self.assertEqual(matching.returncode, 0, matching.stderr)
        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn("does not match minted App", mismatched.stderr)

    def test_global_summary_contract_rejects_secret_exposure_to_other_jobs(
        self,
    ) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutations = (
            summary.replace(
                'env:\n  PYTHONDONTWRITEBYTECODE: "1"',
                "env:\n"
                "  LEAKED_APP_KEY: "
                "${{ secrets.DASHBOARD_DELIVERY_APP_PRIVATE_KEY }}\n"
                '  PYTHONDONTWRITEBYTECODE: "1"',
                1,
            ),
            summary.replace(
                "    steps:\n      - name: Checkout repository",
                "    env:\n"
                "      LEAKED_APP_KEY: "
                "${{ secrets.DASHBOARD_DELIVERY_APP_PRIVATE_KEY }}\n"
                "    steps:\n"
                "      - name: Checkout repository",
                1,
            ),
        )

        for mutated in mutations:
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

    def test_global_summary_contract_rejects_builtin_write_permissions(self) -> None:
        summary = (
            self.workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        mutations = (
            summary.replace("  contents: read", "  contents: write", 1),
            summary.replace("      contents: read", "      contents: write", 1),
            summary.replace(
                "permissions:\n  actions: read\n  contents: read",
                "permissions:\n  actions: read\n  contents: read\n  pull-requests: write",
                1,
            ),
        )

        for mutated in mutations:
            with self.subTest():
                with self.assertRaises(AssertionError):
                    self._assert_global_summary_delivery_contract(mutated)

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
