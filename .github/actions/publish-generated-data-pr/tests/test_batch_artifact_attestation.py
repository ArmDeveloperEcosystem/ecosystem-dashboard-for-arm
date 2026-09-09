from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from batch_artifact_attestation import (  # noqa: E402
    AttestationError,
    SENTINEL_NAME,
    canonical_json,
    create_attestation,
    load_registrations,
    verify_attestation,
)

BATCH = 1
REPOSITORY = "example/dashboard"
BRANCH = "main"
SHA = "a" * 40
ORCHESTRATION_ID = "orchestration-123456-1"
DISPATCH_NONCE = "b" * 64
RUN_ID = 123456
RUN_ATTEMPT = 1
ARTIFACT = "batch1-test-results"


class BatchArtifactAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workflow = self.root / "test-all-packages-batch1.yml"
        self.results = self.root / "test-results"
        self.workflow.write_text(
            """\
name: Batch 1
jobs:
  test-alpha:
    uses: ./.github/workflows/test-alpha.yml

  test-beta:
    uses: ./.github/workflows/test-beta.yml

  summary:
    needs: [test-alpha, test-beta]
""",
            encoding="utf-8",
        )
        self.results.mkdir()
        self.needs = {
            "test-alpha": {
                "result": "success",
                "outputs": {"package_slug": "alpha"},
            },
            "test-beta": {
                "result": "failure",
                "outputs": {"package_slug": "beta"},
            },
        }
        self._write_result("alpha", status="success")
        self._write_result("beta", status="failure")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_result(self, slug: str, *, status: str) -> Path:
        result_dir = self.results / f"{slug}-test-results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result = result_dir / f"{slug}.json"
        result.write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "package": {"name": slug.title(), "version": "1.0.0"},
                    "run": {
                        "id": str(RUN_ID),
                        "attempt": str(RUN_ATTEMPT),
                        "status": status,
                        "runner": {
                            "os": "ubuntu-24.04",
                            "arch": "arm64",
                        },
                    },
                    "tests": {
                        "passed": 6 if status == "success" else 5,
                        "failed": 0 if status == "success" else 1,
                        "skipped": 0,
                        "duration_seconds": 10,
                        "details": [],
                    },
                    "metadata": {
                        "package_slug": slug,
                        "batch_title": "Batch 1",
                        "badge_status": (
                            "passing" if status == "success" else "failing"
                        ),
                        "core_failed": 0 if status == "success" else 1,
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return result

    def _context(self) -> dict[str, object]:
        return {
            "results_root": self.results,
            "workflow_file": self.workflow,
            "batch": BATCH,
            "repository": REPOSITORY,
            "expected_branch": BRANCH,
            "current_branch": BRANCH,
            "expected_sha": SHA,
            "workflow_sha": SHA,
            "orchestration_id": ORCHESTRATION_ID,
            "dispatch_nonce": DISPATCH_NONCE,
            "run_id": RUN_ID,
            "run_attempt": RUN_ATTEMPT,
            "artifact_name": ARTIFACT,
        }

    def _create(self, *, count: int = 2) -> dict[str, object]:
        return create_attestation(
            **self._context(),
            collector_json_count=count,
            needs_json=json.dumps(self.needs),
        )

    def test_complete_artifact_attests_honest_package_failure(self) -> None:
        created = self._create()
        verified = verify_attestation(**self._context())
        self.assertEqual(verified, created)
        self.assertEqual(created["collector"], {"status": "success", "result_count": 2})
        self.assertEqual(
            [record["job"] for record in created["packages"]],
            ["test-alpha", "test-beta"],
        )
        sentinel = self.results / SENTINEL_NAME
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"),
            canonical_json(created) + "\n",
        )

    def test_failed_collector_count_cannot_write_attestation(self) -> None:
        with self.assertRaisesRegex(AttestationError, "collector_json_count"):
            self._create(count=1)
        self.assertFalse((self.results / SENTINEL_NAME).exists())

    def test_partial_or_structurally_invalid_artifact_is_rejected(self) -> None:
        with self.assertRaisesRegex(AttestationError, "sentinel"):
            verify_attestation(**self._context())

        (self.results / "beta-test-results" / "beta.json").unlink()
        with self.assertRaises(AttestationError):
            self._create()
        self.assertFalse((self.results / SENTINEL_NAME).exists())

        self._write_result("beta", status="failure")
        payload = json.loads(
            (self.results / "beta-test-results" / "beta.json").read_text(
                encoding="utf-8"
            )
        )
        del payload["metadata"]["package_slug"]
        (self.results / "beta-test-results" / "beta.json").write_text(
            json.dumps(payload) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(AttestationError):
            self._create()

    def test_duplicate_or_extra_result_is_rejected(self) -> None:
        duplicate_dir = self.results / "alpha-copy-test-results"
        duplicate_dir.mkdir()
        shutil.copy2(
            self.results / "alpha-test-results" / "alpha.json",
            duplicate_dir / "alpha-copy.json",
        )
        with self.assertRaisesRegex(AttestationError, "missing, extra, or duplicate"):
            self._create()
        self.assertFalse((self.results / SENTINEL_NAME).exists())

    def test_forged_sentinel_and_post_attestation_mutation_are_rejected(self) -> None:
        self._create()
        sentinel = self.results / SENTINEL_NAME
        forged = json.loads(sentinel.read_text(encoding="utf-8"))
        forged["dispatch_nonce"] = "c" * 64
        sentinel.write_text(canonical_json(forged) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(AttestationError, "dispatch_nonce"):
            verify_attestation(**self._context())

        sentinel.unlink()
        self._create()
        alpha = self.results / "alpha-test-results" / "alpha.json"
        alpha.write_text(alpha.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaises(AttestationError):
            verify_attestation(**self._context())

    def test_missing_duplicate_needs_and_wrong_run_context_fail_closed(self) -> None:
        missing = dict(self.needs)
        del missing["test-beta"]
        with self.assertRaisesRegex(AttestationError, "needs"):
            create_attestation(
                **self._context(),
                collector_json_count=2,
                needs_json=json.dumps(missing),
            )

        duplicate_slug = json.loads(json.dumps(self.needs))
        duplicate_slug["test-beta"]["outputs"]["package_slug"] = "alpha"
        with self.assertRaisesRegex(AttestationError, "multiple jobs"):
            create_attestation(
                **self._context(),
                collector_json_count=2,
                needs_json=json.dumps(duplicate_slug),
            )

        wrong_context = self._context()
        wrong_context["run_attempt"] = 2
        with self.assertRaisesRegex(AttestationError, "original"):
            verify_attestation(**wrong_context)


class RepositoryBatchAttestationContractTests(unittest.TestCase):
    def test_helper_parses_all_960_exact_wrapper_registrations(self) -> None:
        workflow_root = SCRIPT_ROOT.parents[1] / ".github/workflows"
        registrations = []
        counts = []
        for batch in range(1, 23):
            current = load_registrations(
                workflow_root / f"test-all-packages-batch{batch}.yml",
                batch=batch,
            )
            counts.append(len(current))
            registrations.extend(current)
        self.assertEqual(len(registrations), 960)
        self.assertEqual(len({workflow for _, workflow in registrations}), 960)
        self.assertLessEqual(max(counts), 45)


if __name__ == "__main__":
    unittest.main()
