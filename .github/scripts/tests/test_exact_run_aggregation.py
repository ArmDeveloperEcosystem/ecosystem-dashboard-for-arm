from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import exact_run_aggregation as contract  # noqa: E402


REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
HEAD_SHA = "a" * 40
BRANCH = "main"


class ContractFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workflows = self.root / ".github" / "workflows"
        self.workflows.mkdir(parents=True)
        self.actions = self.root / ".github" / "actions"
        self._write_local_action("collect-batch-results")
        self._write_package_workflow("alpha")
        self._write_package_workflow("bravo")
        self._write_batch(1, ["alpha"])
        self._write_batch(2, ["bravo"])
        self.topology = contract.discover_topology(self.root)
        self.manifest = self._manifest()

    def close(self) -> None:
        self.temporary.cleanup()

    def _write_package_workflow(self, slug: str) -> None:
        (self.workflows / f"test-{slug}.yml").write_text(
            (
                f"name: Test {slug}\n"
                "on:\n"
                "  workflow_call:\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-24.04-arm\n"
            ),
            encoding="utf-8",
        )

    def _write_local_action(self, slug: str, uses: str | None = None) -> None:
        action_root = self.actions / slug
        action_root.mkdir(parents=True, exist_ok=True)
        nested = f"      - uses: {uses}\n" if uses else ""
        (action_root / "action.yml").write_text(
            (
                f"name: {slug}\n"
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                f"{nested}"
                "      - shell: bash\n"
                "        run: echo fixture\n"
            ),
            encoding="utf-8",
        )

    def _write_batch(self, batch: int, slugs: list[str]) -> None:
        jobs = "\n".join(
            f"  test-{slug}:\n    uses: ./.github/workflows/test-{slug}.yml\n"
            for slug in slugs
        )
        needs = ",\n        ".join(f"test-{slug}" for slug in slugs)
        text = f"""name: Test All Packages (Batch {batch}) on Arm64

on:
  workflow_dispatch:

jobs:
{jobs}
  summary:
    needs:
      [
        {needs}
      ]
    runs-on: ubuntu-24.04-arm
    if: always()
    steps:
      - name: Collect batch results
        uses: ./.github/actions/collect-batch-results
        with:
          batch_number: "{batch}"
          batch_title: "Batch {batch}"
      - name: Upload batch test results
        uses: actions/upload-artifact@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
        with:
          name: batch{batch}-test-results
          path: test-results
"""
        (self.workflows / f"test-all-packages-batch{batch}.yml").write_text(
            text, encoding="utf-8"
        )

    def _manifest(self) -> dict:
        batches = []
        for definition in self.topology:
            run_id = 1000 + definition.batch
            archive_raw = self.archive_bytes(definition.batch)
            batches.append(
                {
                    "batch": definition.batch,
                    "workflow_path": definition.workflow_path,
                    "workflow_name": definition.workflow_name,
                    "artifact_name": definition.artifact_name,
                    "dispatch_nonce": f"{definition.batch:064x}",
                    "run": {
                        "id": run_id,
                        "attempt": 1,
                        "workflow_path": definition.workflow_path,
                        "workflow_name": definition.workflow_name,
                        "display_title": contract.expected_run_title(
                            definition,
                            "orchestration-9000-1",
                            f"{definition.batch:064x}",
                        ),
                        "event": "workflow_dispatch",
                        "head_branch": BRANCH,
                        "head_sha": HEAD_SHA,
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2026-08-03T12:00:00Z",
                        "updated_at": "2026-08-03T12:04:00Z",
                    },
                    "jobs": [
                        {
                            "registration_job": registration.job,
                            "workflow_path": registration.workflow_path,
                            "package_slug": registration.package_slug,
                            "id": 300_000 + (definition.batch * 100) + index,
                            "name": contract.expected_job_name(registration),
                            "run_id": run_id,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "2026-08-03T12:01:00Z",
                            "completed_at": "2026-08-03T12:03:00Z",
                            "html_url": (
                                f"https://github.com/{REPOSITORY}/actions/runs/"
                                f"{run_id}/job/{300_000 + (definition.batch * 100) + index}"
                            ),
                        }
                        for index, registration in enumerate(definition.packages)
                    ],
                    "artifact": {
                        "id": 2000 + definition.batch,
                        "name": definition.artifact_name,
                        "size_in_bytes": len(archive_raw),
                        "digest": "sha256:" + hashlib.sha256(archive_raw).hexdigest(),
                        "created_at": "2026-08-03T12:03:00Z",
                        "expired": False,
                        "workflow_run_id": run_id,
                    },
                }
            )
        return {
            "schema": contract.MANIFEST_SCHEMA,
            "version": contract.MANIFEST_VERSION,
            "repository": REPOSITORY,
            "branch": BRANCH,
            "head_sha": HEAD_SHA,
            "topology_sha256": contract.topology_sha256(self.topology),
            "orchestration_id": "orchestration-9000-1",
            "created_at": "2026-08-03T12:05:00Z",
            "batches": batches,
        }

    @staticmethod
    def archive_bytes(batch: int) -> bytes:
        return f"exact-artifact-archive-{batch}".encode("ascii")

    def archive_path(self, batch: int) -> Path:
        return self.root / "archives" / f"batch{batch}.zip"

    def expectations(self) -> dict:
        return {
            "expected_repository": REPOSITORY,
            "expected_branch": BRANCH,
            "expected_sha": HEAD_SHA,
            "expected_orchestration_id": self.manifest["orchestration_id"],
            "expected_dispatch_nonces": [
                record["dispatch_nonce"] for record in self.manifest["batches"]
            ],
            "expected_not_before": "2026-08-03T11:59:00Z",
            "expected_not_after": "2026-08-03T12:06:00Z",
        }

    def run_api(self, batch: int) -> dict:
        definition = self.topology[batch - 1]
        record = self.manifest["batches"][batch - 1]
        run = record["run"]
        return {
            "id": run["id"],
            "run_attempt": run["attempt"],
            "name": definition.workflow_name,
            "path": definition.workflow_path,
            "display_title": contract.expected_run_title(
                definition,
                self.manifest["orchestration_id"],
                record["dispatch_nonce"],
            ),
            "event": "workflow_dispatch",
            "head_branch": BRANCH,
            "head_sha": HEAD_SHA,
            "status": "completed",
            "conclusion": run["conclusion"],
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "repository": {"full_name": REPOSITORY},
        }

    def artifact_api(self, batch: int) -> dict:
        record = self.manifest["batches"][batch - 1]
        artifact = record["artifact"]
        return {
            "id": artifact["id"],
            "name": artifact["name"],
            "size_in_bytes": artifact["size_in_bytes"],
            "digest": artifact["digest"],
            "created_at": artifact["created_at"],
            "expired": artifact["expired"],
            "workflow_run": {"id": artifact["workflow_run_id"]},
        }

    def jobs_api(self, batch: int) -> dict:
        record = self.manifest["batches"][batch - 1]
        return {
            "total_count": len(record["jobs"]) + 1,
            "jobs": [
                {
                    "id": job["id"],
                    "run_id": job["run_id"],
                    "run_attempt": job["run_attempt"],
                    "name": job["name"],
                    "status": job["status"],
                    "conclusion": job["conclusion"],
                    "started_at": job["started_at"],
                    "completed_at": job["completed_at"],
                    "html_url": job["html_url"],
                }
                for job in record["jobs"]
            ]
            + [
                {
                    "id": 900_000 + batch,
                    "run_id": record["run"]["id"],
                    "run_attempt": 1,
                    "name": "summary",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-08-03T12:03:00Z",
                    "completed_at": "2026-08-03T12:04:00Z",
                    "html_url": (
                        f"https://github.com/{REPOSITORY}/actions/runs/"
                        f"{record['run']['id']}/job/{900_000 + batch}"
                    ),
                }
            ],
        }

    def result(
        self,
        batch: int,
        *,
        statuses: list[str] | None = None,
        regression_status: str = "passed",
        regression_decision: str = "next_install_validated",
        run_status: str = "success",
        badge_status: str = "passing",
        core_failed: int = 0,
    ) -> dict:
        definition = self.topology[batch - 1]
        registration = definition.packages[0]
        record = self.manifest["batches"][batch - 1]
        run = record["run"]
        job = record["jobs"][0]
        statuses = statuses or ["passed"] * 6
        if regression_decision in {"baseline_failed", "baseline_install_failed"}:
            regression_applicability = "not_applicable"
            regression_reason = regression_decision
        elif regression_status in {"skipped", "not_applicable"}:
            regression_applicability = "not_applicable"
            regression_reason = regression_decision
        elif regression_status == "deferred":
            regression_applicability = "applicable"
            regression_reason = regression_decision
        elif regression_status == "failed":
            regression_applicability = "applicable"
            regression_reason = regression_decision
        else:
            regression_applicability = "applicable"
            regression_reason = "validated"
        details = []
        for index, status in enumerate(statuses, start=1):
            detail = {
                "name": (
                    f"Test {index} - deterministic validation"
                    if index < 6
                    else "Test 6 - regression validation"
                ),
                "status": status,
                "duration_seconds": 1,
                "url": (
                    f"https://github.com/{REPOSITORY}/actions/runs/"
                    f"{run['id']}/job/{job['id']}#step:{index + 4}:1"
                ),
            }
            if index == 6:
                detail["decision"] = regression_decision
            details.append(detail)
        return {
            "schema_version": "2.0",
            "package": {"name": registration.package_slug, "version": "1.2.3"},
            "run": {
                "id": str(run["id"]),
                "attempt": str(run["attempt"]),
                "url": job["html_url"],
                "timestamp": "2026-08-03T12:02:00Z",
                "status": run_status,
                "runner": {"os": "ubuntu-24.04", "arch": "arm64"},
                "job_name": job["name"],
            },
            "tests": {
                "passed": statuses.count("passed"),
                "failed": statuses.count("failed"),
                "skipped": statuses.count("skipped"),
                "duration_seconds": 6,
                "details": details,
            },
            "metadata": {
                "contract_version": "2.0",
                "package_slug": registration.package_slug,
                "dashboard_link": (
                    f"/linux/opensource_packages/{registration.package_slug}"
                ),
                "badge_status": badge_status,
                "core_failed": core_failed,
                "batch_title": f"Batch {batch}",
                "job_url_resolution_status": "central_exact",
                "regression_status": regression_status,
                "regression_decision": regression_decision,
                "regression_applicability": regression_applicability,
                "regression_reason": regression_reason,
                "regression_note": "Exact Test 6 outcome recorded.",
            },
        }

    def write_artifact(self, batch: int, result: dict | None = None) -> Path:
        definition = self.topology[batch - 1]
        registration = definition.packages[0]
        record = self.manifest["batches"][batch - 1]
        root = self.root / "artifacts" / f"batch{batch}"
        result_dir = root / f"{registration.package_slug}-test-results"
        result_dir.mkdir(parents=True)
        result_path = result_dir / f"{registration.package_slug}.json"
        result_raw = (
            contract.canonical_json(result or self.result(batch)) + "\n"
        ).encode("ascii")
        result_path.write_bytes(result_raw)
        package = {
            "job": registration.job,
            "workflow_path": registration.workflow_path,
            "package_slug": registration.package_slug,
            "result_path": result_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(result_raw).hexdigest(),
        }
        sentinel = {
            "schema": contract.BATCH_ATTESTATION_SCHEMA,
            "version": contract.BATCH_ATTESTATION_VERSION,
            "repository": REPOSITORY,
            "orchestration_id": self.manifest["orchestration_id"],
            "batch": batch,
            "workflow_path": definition.workflow_path,
            "artifact_name": definition.artifact_name,
            "dispatch_nonce": record["dispatch_nonce"],
            "branch": BRANCH,
            "head_sha": HEAD_SHA,
            "run_id": record["run"]["id"],
            "run_attempt": record["run"]["attempt"],
            "collector": {"status": "success", "result_count": 1},
            "packages": [package],
        }
        (root / contract.BATCH_ATTESTATION_NAME).write_text(
            contract.canonical_json(sentinel) + "\n", encoding="ascii"
        )
        self.rebuild_archive(batch, root)
        return root

    def rebuild_archive(self, batch: int, root: Path) -> Path:
        archive_path = self.archive_path(batch)
        archive_path.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(
            archive_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(root.rglob("*")):
                archive.write(path, arcname=path.relative_to(root).as_posix())
        archive_raw = archive_path.read_bytes()
        record = self.manifest["batches"][batch - 1]
        record["artifact"]["size_in_bytes"] = len(archive_raw)
        record["artifact"]["digest"] = (
            "sha256:" + hashlib.sha256(archive_raw).hexdigest()
        )
        return archive_path

    def write_malicious_archive(
        self, batch: int, entries: list[tuple[str, bytes, int]]
    ) -> Path:
        archive_path = self.archive_path(batch)
        archive_path.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            for name, data, mode in entries:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, data)
        archive_raw = archive_path.read_bytes()
        record = self.manifest["batches"][batch - 1]
        record["artifact"]["size_in_bytes"] = len(archive_raw)
        record["artifact"]["digest"] = (
            "sha256:" + hashlib.sha256(archive_raw).hexdigest()
        )
        return archive_path


class ExactRunAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ContractFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def validated_manifest(self) -> dict:
        return contract.validate_manifest(
            self.fixture.manifest,
            topology=self.fixture.topology,
            **self.fixture.expectations(),
        )

    def assert_manifest_rejected(self, mutation) -> None:
        candidate = copy.deepcopy(self.fixture.manifest)
        mutation(candidate)
        with self.assertRaises(contract.ContractError):
            contract.validate_manifest(
                candidate,
                topology=self.fixture.topology,
                **self.fixture.expectations(),
            )

    def test_current_repository_discovers_exact_21_batch_topology(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        topology = contract.discover_topology(repository_root)
        self.assertEqual(len(topology), 21)
        self.assertTrue(contract.topology_payload(topology)["mutable_external_actions"])
        packages = [package for batch in topology for package in batch.packages]
        workflow_root = repository_root / ".github" / "workflows"
        package_files = {
            f".github/workflows/{path.name}"
            for path in workflow_root.glob("test-*.yml")
            if not path.name.startswith("test-all-packages-")
        }
        self.assertEqual({package.workflow_path for package in packages}, package_files)
        payload = contract.topology_payload(topology)
        self.assertTrue(payload["over_capacity_batches"])
        self.assertEqual(payload["target_packages_per_batch"], 45)
        self.assertEqual(len(payload["local_actions"]), 7)

    def test_topology_rejects_unregistered_and_commented_out_contracts(self) -> None:
        unregistered = self.fixture.workflows / "test-charlie.yml"
        unregistered.write_text(
            "name: Test charlie\njobs:\n  test:\n    runs-on: ubuntu-24.04-arm\n",
            encoding="utf-8",
        )
        with self.assertRaises(contract.ContractError):
            contract.discover_topology(self.fixture.root)
        unregistered.unlink()

        batch = self.fixture.workflows / "test-all-packages-batch1.yml"
        text = batch.read_text(encoding="utf-8")
        batch.write_text(
            text.replace(
                "        uses: ./.github/actions/collect-batch-results",
                "        # uses: ./.github/actions/collect-batch-results",
            ),
            encoding="utf-8",
        )
        with self.assertRaises(contract.ContractError):
            contract.discover_topology(self.fixture.root)

    def test_manifest_rejects_mutable_external_action_references(self) -> None:
        batch = self.fixture.workflows / "test-all-packages-batch1.yml"
        batch.write_text(
            batch.read_text(encoding="utf-8").replace(
                "actions/upload-artifact@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "actions/upload-artifact@v4",
            ),
            encoding="utf-8",
        )
        topology = contract.discover_topology(self.fixture.root)
        candidate = copy.deepcopy(self.fixture.manifest)
        candidate["topology_sha256"] = contract.topology_sha256(topology)
        with self.assertRaises(contract.ContractError):
            contract.validate_manifest(
                candidate,
                topology=topology,
                **self.fixture.expectations(),
            )

    def test_topology_scans_job_and_service_container_images(self) -> None:
        workflow = self.fixture.workflows / "test-alpha.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8").replace(
                "    runs-on: ubuntu-24.04-arm\n",
                (
                    "    runs-on: ubuntu-24.04-arm\n"
                    "    container:\n"
                    "      image: ubuntu:latest\n"
                    "    services:\n"
                    "      redis:\n"
                    f"        image: redis@sha256:{'c' * 64}\n"
                ),
            ),
            encoding="utf-8",
        )
        topology = contract.discover_topology(self.fixture.root)
        payload = contract.topology_payload(topology)
        self.assertIn("docker://ubuntu:latest", payload["mutable_external_actions"])
        self.assertIn(f"docker://redis@sha256:{'c' * 64}", payload["external_actions"])
        candidate = copy.deepcopy(self.fixture.manifest)
        candidate["topology_sha256"] = contract.topology_sha256(topology)
        with self.assertRaises(contract.ContractError):
            contract.validate_manifest(
                candidate,
                topology=topology,
                **self.fixture.expectations(),
            )

    def test_topology_recurses_through_local_composite_actions(self) -> None:
        self.fixture._write_local_action(
            "collect-batch-results", uses="example/tool@v1"
        )
        topology = contract.discover_topology(self.fixture.root)
        payload = contract.topology_payload(topology)
        self.assertIn(
            "./.github/actions/collect-batch-results", payload["local_actions"]
        )
        self.assertIn("example/tool@v1", payload["mutable_external_actions"])

        self.fixture._write_local_action(
            "nested", uses="./.github/actions/collect-batch-results"
        )
        self.fixture._write_local_action(
            "collect-batch-results", uses="./.github/actions/nested"
        )
        with self.assertRaises(contract.ContractError):
            contract.discover_topology(self.fixture.root)

    def test_topology_rejects_local_composite_action_without_steps(self) -> None:
        action = self.fixture.actions / "collect-batch-results" / "action.yml"
        action.write_text(
            "name: empty\nruns:\n  using: composite\n  steps: []\n",
            encoding="utf-8",
        )
        with self.assertRaises(contract.ContractError):
            contract.discover_topology(self.fixture.root)

    def test_manifest_is_canonical_exact_and_deterministic(self) -> None:
        manifest = self.validated_manifest()
        raw = (contract.canonical_json(manifest) + "\n").encode("ascii")
        self.assertEqual(
            contract.validate_manifest_text(
                raw,
                topology=self.fixture.topology,
                **self.fixture.expectations(),
            ),
            manifest,
        )
        pretty = json.dumps(manifest, indent=2).encode()
        with self.assertRaises(contract.ContractError):
            contract.validate_manifest_text(
                pretty,
                topology=self.fixture.topology,
                **self.fixture.expectations(),
            )

    def test_checkout_binding_rejects_wrong_sha_and_dirty_topology(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.fixture.root)], check=True)
        subprocess.run(["git", "-C", str(self.fixture.root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.fixture.root),
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract@example.com",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        sha = subprocess.check_output(
            ["git", "-C", str(self.fixture.root), "rev-parse", "HEAD"], text=True
        ).strip()
        self.assertEqual(
            contract.validate_checkout_binding(self.fixture.root, sha), sha
        )
        immutable = contract.discover_topology_at_commit(self.fixture.root, sha)
        self.assertEqual(
            contract.topology_sha256(immutable),
            contract.topology_sha256(self.fixture.topology),
        )
        original_run = subprocess.run
        with (
            mock.patch.object(contract, "MAX_WORKFLOW_FILE_BYTES", 1),
            mock.patch.object(
                contract.subprocess, "run", wraps=original_run
            ) as mocked_run,
            self.assertRaises(contract.ContractError),
        ):
            contract.discover_topology_at_commit(self.fixture.root, sha)
        blob_reads = [
            call.args[0]
            for call in mocked_run.call_args_list
            if call.args and isinstance(call.args[0], list)
        ]
        self.assertFalse(
            any("cat-file" in command and "blob" in command for command in blob_reads)
        )
        with self.assertRaises(contract.ContractError):
            contract.validate_checkout_binding(self.fixture.root, "b" * 40)
        (self.fixture.root / ".git" / "info" / "exclude").write_text(
            ".github/workflows/test-charlie.yml\n", encoding="utf-8"
        )
        self.fixture._write_package_workflow("charlie")
        with self.assertRaises(contract.ContractError):
            contract.discover_topology(self.fixture.root)
        self.assertEqual(
            contract.topology_sha256(
                contract.discover_topology_at_commit(self.fixture.root, sha)
            ),
            contract.topology_sha256(self.fixture.topology),
        )
        batch = self.fixture.workflows / "test-all-packages-batch1.yml"
        batch.write_text(batch.read_text() + "# dirty\n", encoding="utf-8")
        with self.assertRaises(contract.ContractError):
            contract.validate_checkout_binding(self.fixture.root, sha)

        subprocess.run(
            [
                "git",
                "-C",
                str(self.fixture.root),
                "checkout",
                "--",
                ".github/workflows",
            ],
            check=True,
        )
        action = self.fixture.actions / "collect-batch-results" / "action.yml"
        action.write_text(action.read_text(encoding="utf-8") + "# dirty\n")
        with self.assertRaises(contract.ContractError):
            contract.validate_checkout_binding(self.fixture.root, sha)

    def test_api_payloads_bind_one_exact_run_and_artifact(self) -> None:
        definition = self.fixture.topology[0]
        record = self.fixture.manifest["batches"][0]
        run = contract.select_exact_workflow_run(
            {"total_count": 1, "workflow_runs": [self.fixture.run_api(1)]},
            definition=definition,
            repository=REPOSITORY,
            branch=BRANCH,
            head_sha=HEAD_SHA,
            orchestration_id=self.fixture.manifest["orchestration_id"],
            dispatch_nonce=record["dispatch_nonce"],
        )
        artifact = contract.select_exact_artifact(
            {"total_count": 1, "artifacts": [self.fixture.artifact_api(1)]},
            definition=definition,
            run=run,
        )
        jobs = contract.select_exact_jobs(
            self.fixture.jobs_api(1),
            definition=definition,
            repository=REPOSITORY,
            run=run,
        )
        self.assertEqual(
            contract.build_manifest_batch(
                definition=definition,
                dispatch_nonce=record["dispatch_nonce"],
                run=run,
                jobs=jobs,
                artifact=artifact,
            ),
            record,
        )

    def test_api_run_selection_rejects_duplicate_and_mixed_provenance(self) -> None:
        definition = self.fixture.topology[0]
        record = self.fixture.manifest["batches"][0]
        valid = self.fixture.run_api(1)
        cases = [
            {"total_count": 0, "workflow_runs": []},
            {"total_count": 2, "workflow_runs": [valid, copy.deepcopy(valid)]},
            {"total_count": 2, "workflow_runs": [valid]},
            {"total_count": 1, "workflow_runs": [{**valid, "event": "push"}]},
            {"total_count": 1, "workflow_runs": [{**valid, "head_sha": "b" * 40}]},
            {"total_count": 1, "workflow_runs": [{**valid, "run_attempt": 2}]},
            {
                "total_count": 1,
                "workflow_runs": [{**valid, "repository": {"full_name": "other/repo"}}],
            },
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(contract.ContractError):
                contract.select_exact_workflow_run(
                    pages,
                    definition=definition,
                    repository=REPOSITORY,
                    branch=BRANCH,
                    head_sha=HEAD_SHA,
                    orchestration_id=self.fixture.manifest["orchestration_id"],
                    dispatch_nonce=record["dispatch_nonce"],
                )

    def test_api_artifact_selection_rejects_incomplete_duplicate_and_wrong_run(
        self,
    ) -> None:
        definition = self.fixture.topology[0]
        run = self.fixture.manifest["batches"][0]["run"]
        valid = self.fixture.artifact_api(1)
        cases = [
            {"total_count": 0, "artifacts": []},
            {"total_count": 2, "artifacts": [valid, copy.deepcopy(valid)]},
            {"total_count": 2, "artifacts": [valid]},
            {"total_count": 1, "artifacts": [{**valid, "expired": True}]},
            {
                "total_count": 1,
                "artifacts": [{**valid, "workflow_run": {"id": 999}}],
            },
            {"total_count": 1, "artifacts": [{**valid, "digest": "bad"}]},
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(contract.ContractError):
                contract.select_exact_artifact(pages, definition=definition, run=run)

    def test_api_job_selection_rejects_missing_duplicate_and_wrong_identity(
        self,
    ) -> None:
        definition = self.fixture.topology[0]
        run = self.fixture.manifest["batches"][0]["run"]
        valid = self.fixture.jobs_api(1)
        package_job = valid["jobs"][0]
        cases = [
            {"total_count": 0, "jobs": []},
            {
                "total_count": 2,
                "jobs": [package_job, copy.deepcopy(package_job)],
            },
            {"total_count": 2, "jobs": [package_job]},
            {
                **valid,
                "jobs": [{**package_job, "run_id": 999}, *valid["jobs"][1:]],
            },
            {
                **valid,
                "jobs": [
                    {**package_job, "run_attempt": 2},
                    *valid["jobs"][1:],
                ],
            },
            {
                **valid,
                "jobs": [
                    {**package_job, "run_attempt": True},
                    *valid["jobs"][1:],
                ],
            },
            {
                **valid,
                "jobs": [
                    {**package_job, "run_id": float(package_job["run_id"])},
                    *valid["jobs"][1:],
                ],
            },
            {
                **valid,
                "jobs": [
                    {**package_job, "html_url": package_job["html_url"] + "0"},
                    *valid["jobs"][1:],
                ],
            },
            {
                **valid,
                "jobs": [
                    {**package_job, "status": "in_progress", "conclusion": None},
                    *valid["jobs"][1:],
                ],
            },
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(contract.ContractError):
                contract.select_exact_jobs(
                    pages,
                    definition=definition,
                    repository=REPOSITORY,
                    run=run,
                )

    def test_manifest_rejects_missing_extra_duplicate_and_reordered_batches(
        self,
    ) -> None:
        mutations = [
            lambda item: item["batches"].pop(),
            lambda item: item["batches"].append(copy.deepcopy(item["batches"][0])),
            lambda item: item["batches"].reverse(),
            lambda item: item["batches"][1].update(
                {
                    "run": {
                        **item["batches"][1]["run"],
                        "id": item["batches"][0]["run"]["id"],
                    }
                }
            ),
            lambda item: item["batches"][1].update(
                {
                    "artifact": {
                        **item["batches"][1]["artifact"],
                        "id": item["batches"][0]["artifact"]["id"],
                    }
                }
            ),
            lambda item: item["batches"][1].update(
                {"dispatch_nonce": item["batches"][0]["dispatch_nonce"]}
            ),
            lambda item: item["batches"][1]["jobs"][0].update(
                {"id": item["batches"][0]["jobs"][0]["id"]}
            ),
            lambda item: item["batches"][0]["jobs"][0].update(
                {"registration_job": "test-other"}
            ),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_manifest_rejected(mutation)

    def test_manifest_rejects_mixed_provenance_and_nonterminal_runs(self) -> None:
        mutations = [
            lambda item: item.update({"repository": "example/other"}),
            lambda item: item.update({"topology_sha256": "b" * 64}),
            lambda item: item["batches"][0]["run"].update({"head_sha": "b" * 40}),
            lambda item: item["batches"][0]["run"].update({"head_branch": "other"}),
            lambda item: item["batches"][0]["run"].update({"event": "push"}),
            lambda item: item["batches"][0]["run"].update(
                {"display_title": "another dispatch"}
            ),
            lambda item: item["batches"][0]["run"].update(
                {"workflow_path": ".github/workflows/other.yml"}
            ),
            lambda item: item["batches"][0]["run"].update({"attempt": 2}),
            lambda item: item["batches"][0]["run"].update(
                {"status": "in_progress", "conclusion": None}
            ),
            lambda item: item["batches"][0]["run"].update({"conclusion": "cancelled"}),
            lambda item: item["batches"][0]["artifact"].update({"expired": True}),
            lambda item: item["batches"][0]["artifact"].update(
                {"workflow_run_id": 999}
            ),
            lambda item: item["batches"][0]["artifact"].update({"digest": "bad"}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_manifest_rejected(mutation)

    def test_manifest_rejects_timestamps_outside_run_window(self) -> None:
        mutations = [
            lambda item: item["batches"][0]["run"].update(
                {"updated_at": "2026-08-03T12:06:00Z"}
            ),
            lambda item: item["batches"][0]["artifact"].update(
                {"created_at": "2026-08-03T11:59:59Z"}
            ),
            lambda item: item.update({"created_at": "2026-08-03 12:05:00Z"}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_manifest_rejected(mutation)

    def test_manifest_rejects_replayed_or_overbroad_launch_expectations(self) -> None:
        cases = []
        wrong_orchestration = self.fixture.expectations()
        wrong_orchestration["expected_orchestration_id"] = "orchestration-9999-1"
        cases.append(wrong_orchestration)

        wrong_nonces = self.fixture.expectations()
        wrong_nonces["expected_dispatch_nonces"] = [
            "f" * 64,
            wrong_nonces["expected_dispatch_nonces"][1],
        ]
        cases.append(wrong_nonces)

        stale_run = self.fixture.expectations()
        stale_run["expected_not_before"] = "2026-08-03T12:00:01Z"
        cases.append(stale_run)

        broad_window = self.fixture.expectations()
        broad_window["expected_not_before"] = "2026-08-01T12:00:00Z"
        cases.append(broad_window)

        for expectations in cases:
            with (
                self.subTest(expectations=expectations),
                self.assertRaises(contract.ContractError),
            ):
                contract.validate_manifest(
                    self.fixture.manifest,
                    topology=self.fixture.topology,
                    **expectations,
                )

    def test_manifest_json_rejects_duplicate_keys_nonfinite_and_deep_input(
        self,
    ) -> None:
        duplicate = b'{"schema":"one","schema":"two"}\n'
        nonfinite = b'{"value":NaN}\n'
        deep = ("[" * 40 + "0" + "]" * 40).encode()
        huge_integer = b'{"value":' + (b"9" * 10_000) + b"}\n"
        floating_point = b'{"value":1.5}\n'
        for raw in (duplicate, nonfinite, deep, huge_integer, floating_point):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(contract.ContractError):
                    contract.validate_manifest_text(
                        raw,
                        topology=self.fixture.topology,
                        **self.fixture.expectations(),
                    )
        with self.assertRaises(contract.ContractError):
            contract.validate_manifest_text(
                b"x" * (contract.MAX_MANIFEST_BYTES + 1),
                topology=self.fixture.topology,
                **self.fixture.expectations(),
            )

    def test_yaml_rejects_unhashable_keys_and_oversized_integers(self) -> None:
        malformed = (
            b"? [alpha, bravo]\n: value\n",
            b"value: " + (b"9" * 10_000) + b"\n",
        )
        for raw in malformed:
            with self.subTest(raw=raw[:30]), self.assertRaises(contract.ContractError):
                contract._yaml_mapping(raw, "adversarial workflow")

    def test_api_page_and_item_resource_limits_fail_closed(self) -> None:
        definition = self.fixture.topology[0]
        record = self.fixture.manifest["batches"][0]
        empty_page = {"total_count": 0, "workflow_runs": []}
        with mock.patch.object(contract, "MAX_API_PAGES", 1):
            with self.assertRaises(contract.ContractError):
                contract.select_exact_workflow_run(
                    [empty_page, empty_page],
                    definition=definition,
                    repository=REPOSITORY,
                    branch=BRANCH,
                    head_sha=HEAD_SHA,
                    orchestration_id=self.fixture.manifest["orchestration_id"],
                    dispatch_nonce=record["dispatch_nonce"],
                )
        duplicate = [self.fixture.artifact_api(1), self.fixture.artifact_api(1)]
        with mock.patch.object(contract, "MAX_API_ITEMS", 1):
            with self.assertRaises(contract.ContractError):
                contract.select_exact_artifact(
                    {"total_count": 2, "artifacts": duplicate},
                    definition=definition,
                    run=record["run"],
                )
            with self.assertRaises(contract.ContractError):
                contract.select_exact_jobs(
                    self.fixture.jobs_api(1),
                    definition=definition,
                    repository=REPOSITORY,
                    run=record["run"],
                )

    def test_cli_batch_assignments_are_explicit_complete_and_order_independent(
        self,
    ) -> None:
        first, second = self.fixture.expectations()["expected_dispatch_nonces"]
        self.assertEqual(
            contract._parse_expected_nonce_arguments(
                [f"2={second}", f"1={first}"], self.fixture.topology
            ),
            (first, second),
        )
        self.assertEqual(
            contract._parse_artifact_archive_arguments(
                ["2=/tmp/two.zip", "1=/tmp/one.zip"], self.fixture.topology
            ),
            (Path("/tmp/one.zip"), Path("/tmp/two.zip")),
        )
        invalid = (
            [f"1={first}"],
            [f"1={first}", f"1={second}"],
            [f"01={first}", f"2={second}"],
            [f"1={first}", f"3={second}"],
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(contract.ContractError):
                contract._parse_expected_nonce_arguments(values, self.fixture.topology)

    def test_complete_six_test_artifact_is_accepted(self) -> None:
        self.fixture.write_artifact(1)
        manifest = self.validated_manifest()
        proof = contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )
        self.assertEqual(proof["batch"], 1)
        self.assertEqual(proof["run_id"], 1001)
        self.assertEqual(len(proof["packages"]), 1)

    def test_honest_baseline_failure_is_valid_evidence(self) -> None:
        self.fixture.manifest["batches"][0]["run"]["conclusion"] = "failure"
        self.fixture.manifest["batches"][0]["jobs"][0]["conclusion"] = "failure"
        result = self.fixture.result(
            1,
            statuses=["passed", "passed", "failed", "passed", "passed", "skipped"],
            regression_status="skipped",
            regression_decision="baseline_failed",
            run_status="failure",
            badge_status="failing",
            core_failed=1,
        )
        self.fixture.write_artifact(1, result)
        manifest = self.validated_manifest()
        contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )

    def test_honest_test6_failure_is_valid_failing_evidence(self) -> None:
        self.fixture.manifest["batches"][0]["run"]["conclusion"] = "failure"
        self.fixture.manifest["batches"][0]["jobs"][0]["conclusion"] = "failure"
        result = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["failed"],
            regression_status="failed",
            regression_decision="next_regression_failed",
            run_status="failure",
            badge_status="failing",
        )
        self.fixture.write_artifact(1, result)
        manifest = self.validated_manifest()
        contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )

    def test_approved_test6_deferral_is_nonfailing_and_explicit(self) -> None:
        result = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["skipped"],
            regression_status="deferred",
            regression_decision="runtime_validation_not_automated",
        )
        self.fixture.write_artifact(1, result)
        manifest = self.validated_manifest()
        contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )

    def test_canonical_test6_not_applicable_is_nonfailing(self) -> None:
        result = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["skipped"],
            regression_status="not_applicable",
            regression_decision="no_newer_stable_available",
        )
        self.fixture.write_artifact(1, result)
        manifest = self.validated_manifest()
        contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )

    def test_package_contract_rejects_six_test_policy_violations(self) -> None:
        cases = []
        skipped_baseline = self.fixture.result(1)
        skipped_baseline["tests"]["details"][0]["status"] = "skipped"
        skipped_baseline["tests"].update({"passed": 5, "skipped": 1})
        cases.append(skipped_baseline)

        wrong_counts = self.fixture.result(1)
        wrong_counts["tests"]["passed"] = 5
        cases.append(wrong_counts)

        wrong_core = self.fixture.result(1)
        wrong_core["metadata"]["core_failed"] = 1
        cases.append(wrong_core)

        contradictory = self.fixture.result(1)
        contradictory["run"]["status"] = "failure"
        cases.append(contradictory)

        unsafe_defer = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["skipped"],
            regression_status="deferred",
            regression_decision="not_configured",
        )
        cases.append(unsafe_defer)

        passed_with_baseline_decision = self.fixture.result(
            1, regression_decision="baseline_failed"
        )
        cases.append(passed_with_baseline_decision)

        passed_without_decision = self.fixture.result(
            1, regression_decision="not_configured"
        )
        cases.append(passed_without_decision)

        failed_with_passing_decision = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["failed"],
            regression_status="failed",
            regression_decision="next_install_validated",
            run_status="failure",
            badge_status="failing",
        )
        cases.append(failed_with_passing_decision)

        failed_with_not_applicable_decision = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["failed"],
            regression_status="failed",
            regression_decision="no_newer_stable_available",
            run_status="failure",
            badge_status="failing",
        )
        cases.append(failed_with_not_applicable_decision)

        skipped_with_deferred_decision = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["skipped"],
            regression_status="skipped",
            regression_decision="runtime_validation_not_automated",
        )
        cases.append(skipped_with_deferred_decision)

        not_applicable_but_applicable = self.fixture.result(
            1,
            statuses=["passed"] * 5 + ["skipped"],
            regression_status="not_applicable",
            regression_decision="current_is_latest_stable",
        )
        not_applicable_but_applicable["metadata"]["regression_applicability"] = (
            "applicable"
        )
        cases.append(not_applicable_but_applicable)

        missing_detail_decision = self.fixture.result(1)
        missing_detail_decision["tests"]["details"][5].pop("decision")
        cases.append(missing_detail_decision)

        contradictory_detail_decision = self.fixture.result(1)
        contradictory_detail_decision["tests"]["details"][5]["decision"] = (
            "next_install_failed"
        )
        cases.append(contradictory_detail_decision)

        contradictory_detail_version = self.fixture.result(1)
        contradictory_detail_version["tests"]["details"][5]["current_version"] = "9.9.9"
        cases.append(contradictory_detail_version)

        baseline_with_failed_test6 = self.fixture.result(
            1,
            statuses=["failed", "passed", "passed", "passed", "passed", "failed"],
            regression_status="failed",
            regression_decision="baseline_failed",
            run_status="failure",
            badge_status="failing",
            core_failed=1,
        )
        cases.append(baseline_with_failed_test6)

        for result in cases:
            with self.subTest(case=result["metadata"]["regression_decision"]):
                fixture = ContractFixture()
                try:
                    fixture.write_artifact(1, result)
                    manifest = contract.validate_manifest(
                        fixture.manifest,
                        topology=fixture.topology,
                        **fixture.expectations(),
                    )
                    with self.assertRaises(contract.ContractError):
                        contract.validate_batch_artifact(
                            artifact_archive=fixture.archive_path(1),
                            manifest=manifest,
                            topology=fixture.topology,
                            batch=1,
                        )
                finally:
                    fixture.close()

    def test_regression_decision_policy_groups_are_disjoint(self) -> None:
        groups = contract._REGRESSION_DECISION_GROUPS
        self.assertEqual(
            sum(len(group) for group in groups),
            len(set().union(*groups)),
        )
        self.assertIn(
            "metadata_review_required", contract._DEFERRED_REGRESSION_DECISIONS
        )
        self.assertNotIn(
            "metadata_review_required", contract._FAILED_REGRESSION_DECISIONS
        )

    def test_package_contract_rejects_identity_and_provenance_mismatch(self) -> None:
        mutations = [
            lambda item: item["package"].update({"version": "unknown"}),
            lambda item: item["run"].update({"id": "999"}),
            lambda item: item["run"].update({"attempt": "2"}),
            lambda item: item["run"].update({"timestamp": "2026-08-03T13:00:00Z"}),
            lambda item: item["run"].update({"url": "https://example.com"}),
            lambda item: item["run"].update(
                {
                    "url": (
                        f"https://github.com/{REPOSITORY}/actions/runs/1001/"
                        "job/999999999"
                    )
                }
            ),
            lambda item: item["run"].update({"job_name": "test-other"}),
            lambda item: item["metadata"].update({"package_slug": "other"}),
            lambda item: item["metadata"].update({"dashboard_link": "/other"}),
            lambda item: item["metadata"].pop("regression_decision"),
            lambda item: item["tests"]["details"][0].update(
                {
                    "url": (
                        f"https://github.com/{REPOSITORY}/actions/runs/1001/"
                        "job/9999#step:5:1"
                    )
                }
            ),
        ]
        for mutation in mutations:
            result = self.fixture.result(1)
            mutation(result)
            with self.subTest(mutation=mutation):
                fixture = ContractFixture()
                try:
                    fixture.write_artifact(1, result)
                    manifest = contract.validate_manifest(
                        fixture.manifest,
                        topology=fixture.topology,
                        **fixture.expectations(),
                    )
                    with self.assertRaises(contract.ContractError):
                        contract.validate_batch_artifact(
                            artifact_archive=fixture.archive_path(1),
                            manifest=manifest,
                            topology=fixture.topology,
                            batch=1,
                        )
                finally:
                    fixture.close()

    def test_artifact_rejects_mutation_extra_missing_and_special_members(self) -> None:
        cases = ("mutated", "extra", "missing")
        for case in cases:
            fixture = ContractFixture()
            try:
                root = fixture.write_artifact(1)
                result = root / "alpha-test-results" / "alpha.json"
                if case == "mutated":
                    result.write_text("{}\n", encoding="utf-8")
                elif case == "extra":
                    (root / "extra.txt").write_text("extra", encoding="utf-8")
                elif case == "missing":
                    result.unlink()
                fixture.rebuild_archive(1, root)
                local_manifest = contract.validate_manifest(
                    fixture.manifest,
                    topology=fixture.topology,
                    **fixture.expectations(),
                )
                with self.subTest(case=case), self.assertRaises(contract.ContractError):
                    contract.validate_batch_artifact(
                        artifact_archive=fixture.archive_path(1),
                        manifest=local_manifest,
                        topology=fixture.topology,
                        batch=1,
                    )
            finally:
                fixture.close()

        malicious_modes = (
            ("symlink", stat.S_IFLNK | 0o777),
            ("fifo", stat.S_IFIFO | 0o600),
        )
        for case, mode in malicious_modes:
            fixture = ContractFixture()
            try:
                root = fixture.write_artifact(1)
                sentinel = (root / contract.BATCH_ATTESTATION_NAME).read_bytes()
                fixture.write_malicious_archive(
                    1,
                    [
                        (
                            contract.BATCH_ATTESTATION_NAME,
                            sentinel,
                            stat.S_IFREG | 0o600,
                        ),
                        ("alpha-test-results/", b"", stat.S_IFDIR | 0o700),
                        (
                            "alpha-test-results/alpha.json",
                            b"batch-attestation.json",
                            mode,
                        ),
                    ],
                )
                local_manifest = contract.validate_manifest(
                    fixture.manifest,
                    topology=fixture.topology,
                    **fixture.expectations(),
                )
                with self.subTest(case=case), self.assertRaises(contract.ContractError):
                    contract.validate_batch_artifact(
                        artifact_archive=fixture.archive_path(1),
                        manifest=local_manifest,
                        topology=fixture.topology,
                        batch=1,
                    )
            finally:
                fixture.close()

        fixture = ContractFixture()
        try:
            archive = fixture.write_malicious_archive(
                1, [("../escape.json", b"{}", stat.S_IFREG | 0o600)]
            )
            extraction_parent = fixture.root / "direct-extraction"
            destination = extraction_parent / "artifact"
            destination.mkdir(parents=True)
            with self.assertRaises(contract.ContractError):
                contract._extract_verified_archive(archive.read_bytes(), destination)
            self.assertFalse((extraction_parent / "escape.json").exists())
        finally:
            fixture.close()

        unsafe_paths = (
            ("alpha-test-results//alpha.json", b"{}", stat.S_IFREG | 0o600),
            ("payload/", b"hidden", stat.S_IFDIR | 0o700),
        )
        for name, data, mode in unsafe_paths:
            fixture = ContractFixture()
            try:
                fixture.write_malicious_archive(1, [(name, data, mode)])
                local_manifest = contract.validate_manifest(
                    fixture.manifest,
                    topology=fixture.topology,
                    **fixture.expectations(),
                )
                with self.subTest(name=name), self.assertRaises(contract.ContractError):
                    contract.validate_batch_artifact(
                        artifact_archive=fixture.archive_path(1),
                        manifest=local_manifest,
                        topology=fixture.topology,
                        batch=1,
                    )
            finally:
                fixture.close()

    def test_archive_directory_is_bounded_before_zipfile_parsing(self) -> None:
        entries = [
            (f"member-{index}.json", b"{}", stat.S_IFREG | 0o600)
            for index in range(contract.MAX_BATCH_ENTRIES + 1)
        ]
        archive = self.fixture.write_malicious_archive(1, entries)
        destination = self.fixture.root / "bounded-extraction"
        destination.mkdir()
        with mock.patch.object(
            contract.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZipFile must not parse an oversized directory"),
        ):
            with self.assertRaises(contract.ContractError):
                contract._extract_verified_archive(archive.read_bytes(), destination)

    def test_archive_rejects_eocd_parser_disagreement_before_zipfile(self) -> None:
        archive_path = self.fixture.archive_path(1)
        archive_path.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            archive.writestr("record.json", b"{}")
            archive.comment = b"ambiguous-PK\x05\x06-trailer"
        destination = self.fixture.root / "ambiguous-eocd"
        destination.mkdir()
        with mock.patch.object(
            contract.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZipFile must not select a different EOCD"),
        ):
            with self.assertRaises(contract.ContractError):
                contract._extract_verified_archive(
                    archive_path.read_bytes(), destination
                )

    def test_archive_rejects_invalid_utf8_name_as_contract_error(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("a", b"payload")
        raw = bytearray(buffer.getvalue())
        local = raw.index(b"PK\x03\x04")
        central = raw.index(b"PK\x01\x02")
        local_flags = struct.unpack_from("<H", raw, local + 6)[0]
        central_flags = struct.unpack_from("<H", raw, central + 8)[0]
        struct.pack_into("<H", raw, local + 6, local_flags | 0x800)
        struct.pack_into("<H", raw, central + 8, central_flags | 0x800)
        raw[local + 30] = 0xFF
        raw[central + 46] = 0xFF
        destination = self.fixture.root / "invalid-utf8"
        destination.mkdir()
        with self.assertRaises(contract.ContractError):
            contract._extract_verified_archive(bytes(raw), destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_archive_rejects_oversized_attestation_before_extraction(self) -> None:
        archive = self.fixture.write_malicious_archive(
            1,
            [
                (
                    contract.BATCH_ATTESTATION_NAME,
                    b"x" * (contract.MAX_BATCH_ATTESTATION_BYTES + 1),
                    stat.S_IFREG | 0o600,
                )
            ],
        )
        destination = self.fixture.root / "oversized-attestation"
        destination.mkdir()
        with self.assertRaises(contract.ContractError):
            contract._extract_verified_archive(archive.read_bytes(), destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_artifact_rejects_oversized_result_and_unexpected_empty_directory(
        self,
    ) -> None:
        root = self.fixture.write_artifact(1)
        (root / "unexpected").mkdir()
        self.fixture.rebuild_archive(1, root)
        manifest = self.validated_manifest()
        with self.assertRaises(contract.ContractError):
            contract.validate_batch_artifact(
                artifact_archive=self.fixture.archive_path(1),
                manifest=manifest,
                topology=self.fixture.topology,
                batch=1,
            )

        fixture = ContractFixture()
        try:
            fixture.write_artifact(1)
            local_manifest = contract.validate_manifest(
                fixture.manifest,
                topology=fixture.topology,
                **fixture.expectations(),
            )
            with mock.patch.object(contract, "MAX_RESULT_BYTES", 16):
                with self.assertRaises(contract.ContractError):
                    contract.validate_batch_artifact(
                        artifact_archive=fixture.archive_path(1),
                        manifest=local_manifest,
                        topology=fixture.topology,
                        batch=1,
                    )
        finally:
            fixture.close()

    def test_verified_archive_ignores_a_substituted_external_directory(self) -> None:
        root = self.fixture.write_artifact(1)
        manifest = self.validated_manifest()
        (root / "extra-after-archive.txt").write_text("substituted", encoding="utf-8")
        proof = contract.validate_batch_artifact(
            artifact_archive=self.fixture.archive_path(1),
            manifest=manifest,
            topology=self.fixture.topology,
            batch=1,
        )
        self.assertEqual(proof["batch"], 1)

    def test_artifact_rejects_archive_identity_and_conclusion_contradictions(
        self,
    ) -> None:
        self.fixture.write_artifact(1)
        manifest = self.validated_manifest()
        archive = self.fixture.archive_path(1)
        archive.write_bytes(b"tampered archive")
        with self.assertRaises(contract.ContractError):
            contract.validate_batch_artifact(
                artifact_archive=archive,
                manifest=manifest,
                topology=self.fixture.topology,
                batch=1,
            )

        fixture = ContractFixture()
        try:
            fixture.manifest["batches"][0]["run"]["conclusion"] = "failure"
            fixture.write_artifact(1)
            local_manifest = contract.validate_manifest(
                fixture.manifest,
                topology=fixture.topology,
                **fixture.expectations(),
            )
            with self.assertRaises(contract.ContractError):
                contract.validate_batch_artifact(
                    artifact_archive=fixture.archive_path(1),
                    manifest=local_manifest,
                    topology=fixture.topology,
                    batch=1,
                )
        finally:
            fixture.close()

    def test_aggregate_attestation_is_complete_ordered_and_byte_deterministic(
        self,
    ) -> None:
        for batch in (1, 2):
            self.fixture.write_artifact(batch)
        manifest = self.validated_manifest()
        archives = [self.fixture.archive_path(batch) for batch in (1, 2)]
        first = contract.build_aggregate_attestation(
            manifest=manifest,
            topology=self.fixture.topology,
            artifact_archives=archives,
        )
        second = contract.build_aggregate_attestation(
            manifest=copy.deepcopy(manifest),
            topology=self.fixture.topology,
            artifact_archives=archives,
        )
        self.assertEqual(
            contract.canonical_json(first), contract.canonical_json(second)
        )
        self.assertEqual(first["overall_status"], "success")
        with self.assertRaises(contract.ContractError):
            contract.build_aggregate_attestation(
                manifest=manifest,
                topology=self.fixture.topology,
                artifact_archives=list(reversed(archives)),
            )
        archives[0].write_bytes(b"forged archive")
        with self.assertRaises(contract.ContractError):
            contract.build_aggregate_attestation(
                manifest=manifest,
                topology=self.fixture.topology,
                artifact_archives=archives,
            )

    def test_aggregate_attestation_derives_honest_failure(self) -> None:
        self.fixture.manifest["batches"][0]["run"]["conclusion"] = "failure"
        self.fixture.manifest["batches"][0]["jobs"][0]["conclusion"] = "failure"
        failing = self.fixture.result(
            1,
            statuses=["failed", "passed", "passed", "passed", "passed", "skipped"],
            regression_status="skipped",
            regression_decision="baseline_failed",
            run_status="failure",
            badge_status="failing",
            core_failed=1,
        )
        self.fixture.write_artifact(1, failing)
        self.fixture.write_artifact(2)
        manifest = self.validated_manifest()
        aggregate = contract.build_aggregate_attestation(
            manifest=manifest,
            topology=self.fixture.topology,
            artifact_archives=[self.fixture.archive_path(batch) for batch in (1, 2)],
        )
        self.assertEqual(aggregate["overall_status"], "failure")


if __name__ == "__main__":
    unittest.main()
