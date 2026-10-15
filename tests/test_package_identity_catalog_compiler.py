"""Focused fail-closed tests for reviewed worksheet catalog compilation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPILER_PATH = REPOSITORY_ROOT / "build_steps/compile_package_identity_catalog.py"
GENERATOR_PATH = REPOSITORY_ROOT / "build_steps/generate_package_identity_review_worksheet.py"
VALIDATOR_PATH = REPOSITORY_ROOT / "build_steps/validate_package_identity_catalog.py"

_COMPILER_SPEC = importlib.util.spec_from_file_location(
    "package_identity_catalog_compiler", COMPILER_PATH
)
if _COMPILER_SPEC is None or _COMPILER_SPEC.loader is None:
    raise RuntimeError("could not load the package identity catalog compiler")
compiler = importlib.util.module_from_spec(_COMPILER_SPEC)
sys.modules[_COMPILER_SPEC.name] = compiler
_COMPILER_SPEC.loader.exec_module(compiler)

CatalogCompilationError = compiler.CatalogCompilationError
compile_catalog = compiler.compile_catalog


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return reader.fieldnames, list(reader)


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class CompilerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        shutil.copytree(
            REPOSITORY_ROOT / "build_steps",
            root / "build_steps",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        content = root / "content/linux/opensource_packages"
        workflows = root / ".github/workflows"
        content.mkdir(parents=True)
        workflows.mkdir(parents=True)
        (content / "alpha.md").write_text(
            "---\nname: Alpha\ndownload_url: https://pypi.org/project/alpha/\n---\n",
            encoding="utf-8",
        )
        (content / "beta.md").write_text(
            "---\nname: Beta\ndownload_url: https://github.com/example/beta\n---\n",
            encoding="utf-8",
        )
        (workflows / "test-alpha.yml").write_text(
            "name: Test alpha\non:\n  workflow_call:\n",
            encoding="utf-8",
        )
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "compiler-tests@example.com")
        _git(root, "config", "user.name", "Compiler tests")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "compiler fixture")
        self.revision = _git(root, "rev-parse", "HEAD")
        self.worksheet = root.parent / "worksheet"
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(GENERATOR_PATH),
                "--repository-root",
                str(root),
                "--revision",
                self.revision,
                "--output-directory",
                str(self.worksheet),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def complete_review(self) -> None:
        decision_path = self.worksheet / "registry-decisions.csv"
        columns, decisions = _read_csv(decision_path)
        evidence_rows: list[dict[str, str]] = []
        for decision in decisions:
            slug = decision["slug"]
            registry = decision["registry"]
            decision["decision_status"] = "verified"
            decision["exhaustive"] = "true"
            decision["approved_identities"] = json.dumps(
                [slug], separators=(",", ":")
            )
            decision["review_state"] = "reviewed"
            decision["review_notes"] = "Registry response and project ownership reviewed."
            if registry == "pip":
                source_kind = "pypi_api"
                locator = f"https://pypi.org/pypi/{slug}/json"
            else:
                source_kind = "npm_api"
                locator = f"https://registry.npmjs.org/{slug}"
            snapshot = json.dumps(
                {"name": slug, "registry": registry},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest = _sha256(snapshot)
            evidence_rows.append(
                {
                    "base_commit": self.revision,
                    "decision_id": decision["decision_id"],
                    "slug": slug,
                    "registry": registry,
                    "source_kind": source_kind,
                    "source_locator": locator,
                    "source_revision": digest,
                    "evidence_sha256": digest,
                    "rationale": "Registry snapshot and ownership were reviewed.",
                    "verified_by": "qualified-reviewer",
                    "verified_at": "2026-01-01T00:00:00+00:00",
                }
            )
        _write_csv(decision_path, columns, decisions)
        evidence_rows.sort(
            key=lambda row: (
                row["decision_id"],
                json.dumps(
                    {
                        key: (value or None if key == "rationale" else value)
                        for key, value in row.items()
                        if key
                        not in {"base_commit", "decision_id", "slug", "registry"}
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        _write_csv(
            self.worksheet / "evidence-ledger.csv",
            list(compiler.EVIDENCE_COLUMNS),
            evidence_rows,
        )


class PackageIdentityCatalogCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.fixture = CompilerFixture(self.root)

    def assert_no_catalog(self) -> None:
        self.assertFalse((self.root / compiler.CATALOG_PATH).exists())

    def test_complete_review_round_trips_through_schema_validator(self) -> None:
        self.fixture.complete_review()

        output = compile_catalog(self.root, self.fixture.worksheet)

        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["corpus"]["entry_count"], 2)
        self.assertEqual(len(payload["records"]), 2)
        validator_spec = importlib.util.spec_from_file_location(
            "compiler_test_validator", VALIDATOR_PATH
        )
        assert validator_spec is not None and validator_spec.loader is not None
        validator = importlib.util.module_from_spec(validator_spec)
        sys.modules[validator_spec.name] = validator
        validator_spec.loader.exec_module(validator)
        self.assertEqual(validator.validate_catalog(self.root), 2)

    def test_unreviewed_generator_bundle_is_rejected_without_output(self) -> None:
        with self.assertRaisesRegex(CatalogCompilationError, "explicitly reviewed"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_changed_inventory_is_rejected_without_output(self) -> None:
        self.fixture.complete_review()
        inventory = self.fixture.worksheet / "corpus-inventory.csv"
        inventory.write_text(
            inventory.read_text(encoding="utf-8").replace("alpha.md", "other.md", 1),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalogCompilationError, "byte-identical"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_changed_immutable_decision_field_is_rejected(self) -> None:
        self.fixture.complete_review()
        path = self.fixture.worksheet / "registry-decisions.csv"
        columns, rows = _read_csv(path)
        rows[0]["candidate_source_urls"] = "[]"
        _write_csv(path, columns, rows)

        with self.assertRaisesRegex(CatalogCompilationError, "immutable field"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_formula_neutralized_reviewer_identity_is_rejected(self) -> None:
        self.fixture.complete_review()
        path = self.fixture.worksheet / "evidence-ledger.csv"
        columns, rows = _read_csv(path)
        rows[0]["verified_by"] = "'@reviewer"
        _write_csv(path, columns, rows)

        with self.assertRaisesRegex(CatalogCompilationError, "spreadsheet-neutralized"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_missing_evidence_join_is_rejected(self) -> None:
        self.fixture.complete_review()
        path = self.fixture.worksheet / "evidence-ledger.csv"
        columns, rows = _read_csv(path)
        rows.pop()
        _write_csv(path, columns, rows)

        with self.assertRaisesRegex(CatalogCompilationError, "1 to 32 reviewed evidence"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_validator_incompatible_evidence_is_rejected_before_output(self) -> None:
        self.fixture.complete_review()
        path = self.fixture.worksheet / "evidence-ledger.csv"
        columns, rows = _read_csv(path)
        rows[0]["evidence_sha256"] = "0" * 64
        _write_csv(path, columns, rows)

        with self.assertRaisesRegex(
            CatalogCompilationError, "schema 1.1 validator rejected"
        ):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_noncanonical_approved_identity_array_is_rejected(self) -> None:
        self.fixture.complete_review()
        path = self.fixture.worksheet / "registry-decisions.csv"
        columns, rows = _read_csv(path)
        rows[0]["approved_identities"] = '[ "alpha" ]'
        _write_csv(path, columns, rows)

        with self.assertRaisesRegex(CatalogCompilationError, "canonical compact JSON"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_manifest_from_another_generation_is_rejected(self) -> None:
        self.fixture.complete_review()
        manifest = self.fixture.worksheet / "manifest.json"
        payload: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
        payload["purpose"] = "modified"
        manifest.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(CatalogCompilationError, "fresh deterministic generation"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()

    def test_modified_generator_is_not_trusted(self) -> None:
        self.fixture.complete_review()
        generator = self.root / "build_steps" / GENERATOR_PATH.name
        generator.write_text(
            generator.read_text(encoding="utf-8") + "\n# unreviewed change\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalogCompilationError, "differs from the exact base"):
            compile_catalog(self.root, self.fixture.worksheet)

        self.assert_no_catalog()


if __name__ == "__main__":
    unittest.main()
