from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from summary_slug_policy import (  # noqa: E402
    DestinationRegistry,
    PackageCatalog,
    SlugPolicyError,
    validate_slug_syntax,
)


class SummarySlugPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name) / "repository"
        self.content_root = (
            self.repository / "content/linux/opensource_packages"
        )
        self.content_root.mkdir(parents=True)
        for slug in ("redis", "5G-RAL", "OpenH264", "Iguazio_Nuclio"):
            (self.content_root / f"{slug}.md").write_text(
                f"---\ntitle: {slug}\n---\n",
                encoding="utf-8",
            )
        self.stage = self.repository / ".summary-staging/candidate-test-results"
        self.stage.mkdir(parents=True)
        self.catalog = PackageCatalog.load(self.repository)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_actual_case_sensitive_slug_forms(self) -> None:
        for slug in ("redis", "5G-RAL", "OpenH264", "Iguazio_Nuclio"):
            with self.subTest(slug=slug):
                self.assertEqual(
                    self.catalog.require(slug, label="artifact package_slug"),
                    slug,
                )

    def test_rejects_traversal_absolute_encoded_and_control_slugs(self) -> None:
        malicious = (
            "../redis",
            "/tmp/redis",
            r"C:\redis",
            "redis/child",
            r"redis\child",
            "%2e%2e",
            "%2Ftmp%2Fredis",
            "redis..",
            "redis\nchild",
            "redis\x00child",
            ".",
            "..",
        )
        for slug in malicious:
            with self.subTest(slug=repr(slug)):
                with self.assertRaises(SlugPolicyError):
                    self.catalog.require(slug, label="artifact package_slug")

    def test_rejects_unknown_and_case_variant_slugs(self) -> None:
        for slug in ("unknown-package", "Redis", "openH264", "iguazio_nuclio"):
            with self.subTest(slug=slug):
                with self.assertRaises(SlugPolicyError):
                    self.catalog.require(slug, label="artifact package_slug")

    def test_rejects_duplicate_destination_claims(self) -> None:
        registry = DestinationRegistry(self.stage)
        first = registry.claim("redis", source_label="batch1/redis.json")
        self.assertEqual(first, self.stage / "redis.json")
        with self.assertRaisesRegex(SlugPolicyError, "duplicate package_slug"):
            registry.claim("redis", source_label="batch2/redis.json")

    def test_metadata_slug_is_required_to_be_exact_when_present(self) -> None:
        self.assertEqual(
            self.catalog.from_metadata(
                {},
                fallback_stem="redis",
                source_label="legacy.json",
            ),
            "redis",
        )
        for metadata in (
            {"package_slug": ""},
            {"package_slug": "Redis"},
            {"package_slug": ["redis"]},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(SlugPolicyError):
                    self.catalog.from_metadata(
                        metadata,
                        fallback_stem="redis",
                        source_label="artifact.json",
                    )

    def test_destination_is_resolved_inside_real_staging_root(self) -> None:
        destination = DestinationRegistry(self.stage).destination("OpenH264")
        self.assertEqual(destination, self.stage / "OpenH264.json")
        outside = self.repository / "outside"
        outside.mkdir()
        link = self.repository / "linked-stage"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SlugPolicyError):
            DestinationRegistry(link).destination("redis")

    def test_slug_length_is_bounded(self) -> None:
        self.assertEqual(
            validate_slug_syntax("a" * 100, label="slug"),
            "a" * 100,
        )
        with self.assertRaises(SlugPolicyError):
            validate_slug_syntax("a" * 101, label="slug")


class RepositorySlugContractTests(unittest.TestCase):
    def test_every_canonical_package_filename_satisfies_the_policy(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        catalog = PackageCatalog.load(repository)
        content_slugs = {
            path.stem
            for path in catalog.content_root.glob("*.md")
            if path.name != "_index.md"
        }
        self.assertEqual(catalog.slugs, frozenset(content_slugs))
        self.assertGreater(len(catalog.slugs), 900)

        for result_path in (repository / "data/test-results").glob("*.json"):
            self.assertIn(result_path.stem, catalog.slugs)


if __name__ == "__main__":
    unittest.main()
