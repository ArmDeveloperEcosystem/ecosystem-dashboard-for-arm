"""Focused tests for the advisory package identity review worksheet generator."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPOSITORY_ROOT / "build_steps/generate_package_identity_review_worksheet.py"
SPEC = importlib.util.spec_from_file_location(
    "package_identity_review_worksheet",
    GENERATOR_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load worksheet generator")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _write(root: Path, path: str, payload: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def _commit(root: Path) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "worksheet-tests@example.com")
    _git(root, "config", "user.name", "Worksheet tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic package corpus")
    return _git(root, "rev-parse", "HEAD")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


class PackageIdentityReviewWorksheetTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repository"
        self.root.mkdir()
        self.output = Path(temporary.name) / "output"

    def fixture(self) -> str:
        _write(
            self.root,
            "content/linux/opensource_packages/alpha.md",
            "---\nname: Alpha\ncategory: Tools\ndownload_url: https://pypi.org/project/Alpha_Pkg/\n"
            "optional_info:\n  homepage_url: https://github.com/example/alpha\n---\n",
        )
        _write(
            self.root,
            "content/linux/opensource_packages/beta.md",
            "---\nname: Beta\ndownload_url: https://www.npmjs.com/package/@scope/beta\n---\n",
        )
        _write(
            self.root,
            "content/linux/opensource_packages/broken.md",
            "---\nname: Broken\ndownload_url: https://pypi.org/project/must-not-be-trusted\nbad: [\n---\n",
        )
        _write(self.root, "content/linux/opensource_packages/_index.md", "---\ntitle: Index\n---\n")
        _write(self.root, ".github/workflows/test-alpha.yml", "name: Alpha\non: workflow_call\n")
        return _commit(self.root)

    def test_generates_complete_advisory_inventory_from_exact_commit(self) -> None:
        revision = self.fixture()

        manifest = generator.generate_worksheet(self.root, revision, self.output)

        inventory = _read_csv(self.output / "corpus-inventory.csv")
        decisions = _read_csv(self.output / "registry-decisions.csv")
        evidence = _read_csv(self.output / "evidence-ledger.csv")
        self.assertEqual([row["slug"] for row in inventory], ["alpha", "beta", "broken"])
        self.assertEqual(manifest["counts"]["package_pages"], 3)
        self.assertEqual(manifest["counts"]["present_workflows"], 1)
        self.assertEqual(manifest["counts"]["absent_workflows"], 2)
        self.assertEqual(len(decisions), 6)
        self.assertEqual(evidence, [])
        for row in decisions:
            self.assertEqual(row["base_commit"], revision)
            self.assertEqual(row["decision_status"], "unknown")
            self.assertEqual(row["exhaustive"], "false")
            self.assertEqual(row["approved_identities"], "")
            self.assertEqual(row["review_state"], "pending")
            self.assertEqual(row["review_notes"], "")

    def test_hints_are_structured_and_malformed_frontmatter_is_not_trusted(self) -> None:
        revision = self.fixture()
        generator.generate_worksheet(self.root, revision, self.output)

        inventory = {row["slug"]: row for row in _read_csv(self.output / "corpus-inventory.csv")}
        decisions = {
            (row["slug"], row["registry"]): row
            for row in _read_csv(self.output / "registry-decisions.csv")
        }
        self.assertEqual(
            json.loads(inventory["alpha"]["github_repository_hints"]),
            ["https://github.com/example/alpha"],
        )
        self.assertEqual(
            json.loads(decisions[("alpha", "pip")]["candidate_identity_hints"]),
            ["Alpha_Pkg"],
        )
        self.assertEqual(
            json.loads(
                decisions[("alpha", "pip")]["normalized_candidate_identity_hints"]
            ),
            ["alpha-pkg"],
        )
        self.assertEqual(
            json.loads(decisions[("beta", "npm")]["candidate_identity_hints"]),
            ["@scope/beta"],
        )
        self.assertEqual(inventory["broken"]["frontmatter_parse_status"], "yaml_error")
        self.assertEqual(
            json.loads(inventory["broken"]["data_quality_flags"]),
            ["frontmatter_yaml_error"],
        )
        self.assertEqual(
            json.loads(decisions[("broken", "pip")]["candidate_identity_hints"]),
            [],
        )

    def test_reads_committed_bytes_and_ignores_dirty_worktree(self) -> None:
        revision = self.fixture()
        committed = (self.root / "content/linux/opensource_packages/alpha.md").read_bytes()
        (self.root / "content/linux/opensource_packages/alpha.md").write_text(
            "---\nname: Dirty\ndownload_url: https://pypi.org/project/dirty/\n---\n",
            encoding="utf-8",
        )

        generator.generate_worksheet(self.root, revision, self.output)

        alpha = _read_csv(self.output / "corpus-inventory.csv")[0]
        self.assertEqual(alpha["display_name_hint"], "Alpha")
        self.assertEqual(alpha["content_sha256"], hashlib.sha256(committed).hexdigest())

    def test_output_is_byte_for_byte_deterministic_and_manifest_binds_csvs(self) -> None:
        revision = self.fixture()
        generator.generate_worksheet(self.root, revision, self.output)
        first = {path.name: path.read_bytes() for path in self.output.iterdir()}

        second_output = self.output.parent / "output-second"
        generator.generate_worksheet(self.root, revision, second_output)
        second = {path.name: path.read_bytes() for path in second_output.iterdir()}

        self.assertEqual(first, second)
        manifest = json.loads(second[generator.MANIFEST_NAME])
        for name in generator.OUTPUT_FILES:
            self.assertEqual(
                manifest["files"][name]["sha256"],
                hashlib.sha256(second[name]).hexdigest(),
            )

    def test_rejects_symbolic_or_abbreviated_revision(self) -> None:
        revision = self.fixture()
        for invalid in ("HEAD", "main", revision[:12], revision.upper()):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    generator.WorksheetGenerationError,
                    "exact full lowercase",
                ):
                    generator.generate_worksheet(self.root, invalid, self.output)

    def test_missing_yaml_dependency_fails_clearly(self) -> None:
        revision = self.fixture()
        with patch.object(generator, "yaml", None):
            with self.assertRaisesRegex(generator.WorksheetGenerationError, "PyYAML is required"):
                generator.generate_worksheet(self.root, revision, self.output)

    def test_nested_package_content_fails_closed(self) -> None:
        _write(
            self.root,
            "content/linux/opensource_packages/nested/package.md",
            "---\nname: Nested\n---\n",
        )
        revision = _commit(self.root)

        with self.assertRaisesRegex(
            generator.WorksheetGenerationError,
            "nested package content is not supported",
        ):
            generator.generate_worksheet(self.root, revision, self.output)

    def test_spreadsheet_formula_cells_are_neutralized(self) -> None:
        _write(
            self.root,
            "content/linux/opensource_packages/formula.md",
            "---\nname: '=HYPERLINK(\"https://example.com\")'\n"
            "category: '@unsafe'\n---\n",
        )
        revision = _commit(self.root)

        generator.generate_worksheet(self.root, revision, self.output)

        row = _read_csv(self.output / "corpus-inventory.csv")[0]
        self.assertEqual(row["display_name_hint"], "'=HYPERLINK(\"https://example.com\")")
        self.assertEqual(row["category_hint"], "'@unsafe")
        self.assertEqual(generator._spreadsheet_safe("\n=1+1"), "'\n=1+1")

    def test_yaml_aliases_and_duplicate_keys_are_not_trusted(self) -> None:
        alias_payload = b"---\nvalue: &anchor [one]\ncopy: *anchor\n---\n"
        duplicate_payload = b"---\nname: first\nname: second\n---\n"

        parsed, status, flags = generator._frontmatter(alias_payload)
        self.assertEqual((parsed, status, flags), ({}, "yaml_alias", ["frontmatter_yaml_alias"]))

        parsed, status, flags = generator._frontmatter(duplicate_payload)
        self.assertEqual((parsed, status, flags), ({}, "yaml_error", ["frontmatter_yaml_error"]))

        non_string_key = b"---\n1: value\n---\n"
        parsed, status, flags = generator._frontmatter(non_string_key)
        self.assertEqual((parsed, status, flags), ({}, "yaml_error", ["frontmatter_yaml_error"]))

    def test_orphan_package_workflow_fails_closed(self) -> None:
        _write(
            self.root,
            "content/linux/opensource_packages/alpha.md",
            "---\nname: Alpha\n---\n",
        )
        _write(self.root, ".github/workflows/test-orphan.yml", "name: Orphan\n")
        revision = _commit(self.root)

        with self.assertRaisesRegex(
            generator.WorksheetGenerationError,
            "workflow has no matching package page",
        ):
            generator.generate_worksheet(self.root, revision, self.output)

    def test_invalid_or_reserved_slug_fails_closed(self) -> None:
        for slug in ("bad:name", "all-packages-summary", "ALL-PACKAGES-SUMMARY"):
            with self.subTest(slug=slug):
                with tempfile.TemporaryDirectory() as temporary_name:
                    root = Path(temporary_name) / "repository"
                    root.mkdir()
                    output = Path(temporary_name) / "output"
                    _write(
                        root,
                        f"content/linux/opensource_packages/{slug}.md",
                        "---\nname: Invalid\n---\n",
                    )
                    revision = _commit(root)
                    with self.assertRaisesRegex(
                        generator.WorksheetGenerationError,
                        "invalid or reserved package slug",
                    ):
                        generator.generate_worksheet(root, revision, output)

    def test_invalid_normalized_candidate_is_isolated(self) -> None:
        _write(
            self.root,
            "content/linux/opensource_packages/invalid-hint.md",
            "---\nname: Invalid Hint\n"
            "download_url: https://pypi.org/project/bad%2Fname/\n---\n",
        )
        revision = _commit(self.root)

        generator.generate_worksheet(self.root, revision, self.output)

        decision = _read_csv(self.output / "registry-decisions.csv")[0]
        self.assertEqual(
            json.loads(decision["normalized_candidate_identity_hints"]),
            [],
        )
        self.assertEqual(
            json.loads(decision["invalid_candidate_identity_hints"]),
            ["bad/name"],
        )


if __name__ == "__main__":
    unittest.main()
