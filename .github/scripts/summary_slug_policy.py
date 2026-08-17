"""Fail-closed package-slug and staging-path policy for summary assembly."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

_SLUG_RE = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_CANONICAL_CONTENT_PARTS = ("content", "linux", "opensource_packages")
# The repository defines no filename alias map; exact content-page stems are identities.


class SlugPolicyError(ValueError):
    """A package identity or staging destination violates the repository contract."""


def validate_slug_syntax(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise SlugPolicyError(
            f"{label} must be a 1..100 character canonical slug using only "
            "ASCII letters, digits, hyphens, and underscores"
        )
    return value


@dataclass(frozen=True)
class PackageCatalog:
    """Exact package-page identities from the one canonical content directory."""

    content_root: Path
    slugs: frozenset[str]
    casefold_index: Mapping[str, tuple[str, ...]]

    @classmethod
    def load(cls, repository_root: Path) -> PackageCatalog:
        repository = repository_root.resolve(strict=True)
        if not repository.is_dir():
            raise SlugPolicyError("repository root is not a directory")

        content_root = repository.joinpath(*_CANONICAL_CONTENT_PARTS)
        _require_real_directory_tree(repository, content_root)
        resolved_content_root = content_root.resolve(strict=True)
        _require_contained(repository, resolved_content_root, "canonical content root")

        slugs: set[str] = set()
        folded: dict[str, list[str]] = {}
        for content_path in sorted(content_root.glob("*.md")):
            if content_path.name == "_index.md":
                continue
            metadata = content_path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise SlugPolicyError(
                    f"canonical package entry must be a regular file: {content_path}"
                )
            slug = validate_slug_syntax(
                content_path.stem,
                label=f"canonical package filename {content_path.name!r}",
            )
            resolved_entry = content_path.resolve(strict=True)
            _require_contained(
                resolved_content_root,
                resolved_entry,
                f"canonical package entry {content_path.name!r}",
            )
            if slug in slugs:
                raise SlugPolicyError(f"duplicate canonical package entry: {slug}")
            slugs.add(slug)
            folded.setdefault(slug.casefold(), []).append(slug)

        ambiguous = {
            key: tuple(sorted(values))
            for key, values in folded.items()
            if len(values) != 1
        }
        if ambiguous:
            raise SlugPolicyError(
                f"case-ambiguous canonical package entries are not allowed: {ambiguous!r}"
            )
        if not slugs:
            raise SlugPolicyError("canonical package catalog is empty")

        return cls(
            content_root=resolved_content_root,
            slugs=frozenset(slugs),
            casefold_index={
                key: tuple(values)
                for key, values in folded.items()
            },
        )

    def require(self, value: object, *, label: str) -> str:
        slug = validate_slug_syntax(value, label=label)
        matches = self.casefold_index.get(slug.casefold(), ())
        if slug in self.slugs and matches == (slug,):
            return slug
        if matches:
            raise SlugPolicyError(
                f"{label} is not exact canonical case; expected {matches[0]!r}"
            )
        raise SlugPolicyError(
            f"{label} does not map to exactly one canonical package page: {slug!r}"
        )

    def from_metadata(
        self,
        metadata: object,
        *,
        fallback_stem: str,
        source_label: str,
    ) -> str:
        if not isinstance(metadata, dict):
            raise SlugPolicyError(f"{source_label} metadata must be an object")
        if "package_slug" in metadata:
            return self.require(
                metadata["package_slug"],
                label=f"{source_label} package_slug",
            )
        return self.require(
            fallback_stem,
            label=f"{source_label} filename fallback",
        )


@dataclass
class DestinationRegistry:
    """Allocate each canonical destination once and prove root containment."""

    root: Path
    claims: dict[str, str] = field(default_factory=dict)

    def destination(self, slug: str) -> Path:
        validate_slug_syntax(slug, label="destination package slug")
        root = self.root.resolve(strict=True)
        if self.root.is_symlink() or not root.is_dir():
            raise SlugPolicyError("staging destination root must be a real directory")
        destination = self.root / f"{slug}.json"
        resolved_destination = destination.resolve(strict=False)
        _require_contained(root, resolved_destination, "staging destination")
        if destination.is_symlink():
            raise SlugPolicyError(
                f"staging destination must not be a symlink: {destination}"
            )
        return destination

    def claim(self, slug: str, *, source_label: str) -> Path:
        destination = self.destination(slug)
        previous = self.claims.get(slug)
        if previous is not None:
            raise SlugPolicyError(
                f"duplicate package_slug {slug!r} from {previous!r} and {source_label!r}"
            )
        self.claims[slug] = source_label
        return destination


def _require_real_directory_tree(repository: Path, target: Path) -> None:
    current = repository
    for part in target.relative_to(repository).parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise SlugPolicyError(
                f"canonical content directory is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SlugPolicyError(
                f"canonical content path must contain only real directories: {current}"
            )


def _require_contained(root: Path, candidate: Path, label: str) -> None:
    try:
        common = Path(os.path.commonpath((str(root), str(candidate))))
    except ValueError as exc:
        raise SlugPolicyError(f"{label} is outside its allowed root") from exc
    if common != root:
        raise SlugPolicyError(f"{label} is outside its allowed root")
