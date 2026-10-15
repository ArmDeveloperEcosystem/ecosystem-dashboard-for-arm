#!/usr/bin/env python3
"""Generate an advisory package-identity review worksheet from an exact commit."""

from __future__ import annotations

import sys

_ISOLATED_MODE_ERROR = (
    "Python isolated mode (-I) is required; invoke this generator with "
    "'python3 -I -B build_steps/generate_package_identity_review_worksheet.py'"
)

if __name__ == "__main__" and not sys.flags.isolated:
    print(f"worksheet generation failed: {_ISOLATED_MODE_ERROR}", file=sys.stderr)
    raise SystemExit(1)

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by dependency test
    yaml = None


CONTENT_ROOT = "content/linux/opensource_packages"
WORKFLOW_ROOT = ".github/workflows"
OUTPUT_FILES = (
    "corpus-inventory.csv",
    "registry-decisions.csv",
    "evidence-ledger.csv",
)
MANIFEST_NAME = "manifest.json"
MAX_PACKAGE_PAGES = 10_000
MAX_PROTECTED_BLOB_BYTES = 2_000_000
_FULL_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_PACKAGE_WORKFLOW_RE = re.compile(
    r"^\.github/workflows/test-[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.yml$"
)
_CONTROL_WORKFLOW_RE = re.compile(
    r"^\.github/workflows/test-all-packages-(?:batch[1-9][0-9]*|orchestrator|summary)\.yml$"
)
_CONTROL_SLUG_RE = re.compile(
    r"^all-packages-(?:batch[1-9][0-9]*|orchestrator|summary)$"
)
_PIP_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NPM_NAME_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9._-]+|[a-z0-9][a-z0-9._-]*)$"
)
_TREE_ENTRY_RE = re.compile(
    rb"^([0-7]{6}) (blob|tree|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)$"
)
_URL_RE = re.compile(r"https://[^\s<>\]\[(){}\"']+")

INVENTORY_COLUMNS = (
    "base_commit",
    "slug",
    "content_path",
    "content_sha256",
    "workflow_path",
    "workflow_presence",
    "workflow_sha256",
    "frontmatter_parse_status",
    "display_name_hint",
    "category_hint",
    "download_url_hint",
    "homepage_url_hint",
    "official_docs_url_hint",
    "github_repository_hints",
    "direct_pypi_identity_hints",
    "direct_npm_identity_hints",
    "data_quality_flags",
)

DECISION_COLUMNS = (
    "base_commit",
    "decision_id",
    "slug",
    "registry",
    "candidate_identity_hints",
    "normalized_candidate_identity_hints",
    "invalid_candidate_identity_hints",
    "candidate_source_fields",
    "candidate_source_urls",
    "decision_status",
    "exhaustive",
    "approved_identities",
    "review_state",
    "review_notes",
)

EVIDENCE_COLUMNS = (
    "base_commit",
    "decision_id",
    "slug",
    "registry",
    "source_kind",
    "source_locator",
    "source_revision",
    "evidence_sha256",
    "rationale",
    "verified_by",
    "verified_at",
)


class WorksheetGenerationError(RuntimeError):
    """Raised when the advisory worksheet cannot be generated safely."""


def _git_environment() -> dict[str, str]:
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    return environment


def _run_git(
    repository: Path,
    arguments: list[str],
    *,
    binary: bool = False,
) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary,
            env=_git_environment(),
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            stderr = error.stderr
            detail = (
                stderr.decode("utf-8", "replace")
                if isinstance(stderr, bytes)
                else stderr
            )
        raise WorksheetGenerationError(
            f"Git command failed ({' '.join(arguments)}): {detail.strip() or error}"
        ) from error
    return result.stdout


def resolve_exact_commit(repository: Path, revision: str) -> str:
    """Require and resolve a full immutable commit object ID."""
    if not _FULL_COMMIT_RE.fullmatch(revision):
        raise WorksheetGenerationError(
            "--revision must be an exact full lowercase Git commit ID; symbolic names and abbreviations are not accepted"
        )
    resolved = str(
        _run_git(repository, ["rev-parse", "--verify", f"{revision}^{{commit}}"])
    ).strip()
    if resolved != revision:
        raise WorksheetGenerationError(
            f"revision resolved to {resolved}, not the requested exact commit {revision}"
        )
    return resolved


def _revision_tree(repository: Path, revision: str) -> dict[str, tuple[str, str]]:
    raw = _run_git(
        repository,
        [
            "-c",
            "core.quotePath=false",
            "ls-tree",
            "-rz",
            "--full-tree",
            revision,
            "--",
            CONTENT_ROOT,
            WORKFLOW_ROOT,
        ],
        binary=True,
    )
    assert isinstance(raw, bytes)
    entries: dict[str, tuple[str, str]] = {}
    for raw_entry in raw.split(b"\0"):
        if not raw_entry:
            continue
        match = _TREE_ENTRY_RE.fullmatch(raw_entry)
        if match is None:
            raise WorksheetGenerationError("Git returned an unrecognized tree entry")
        mode, object_type, object_id, raw_path = match.groups()
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorksheetGenerationError("package paths must be valid UTF-8") from error
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise WorksheetGenerationError(f"protected path is not a regular Git file: {path}")
        entries[path] = (object_id.decode("ascii"), mode.decode("ascii"))
    return entries


def _read_blob(repository: Path, object_id: str) -> bytes:
    raw_size = str(_run_git(repository, ["cat-file", "-s", object_id])).strip()
    try:
        size = int(raw_size)
    except ValueError as error:
        raise WorksheetGenerationError(
            f"Git returned an invalid blob size for {object_id}: {raw_size}"
        ) from error
    if not 1 <= size <= MAX_PROTECTED_BLOB_BYTES:
        raise WorksheetGenerationError(
            f"protected blob {object_id} must contain 1 to "
            f"{MAX_PROTECTED_BLOB_BYTES} bytes"
        )
    payload = _run_git(repository, ["cat-file", "blob", object_id], binary=True)
    assert isinstance(payload, bytes)
    if len(payload) != size:
        raise WorksheetGenerationError(
            f"protected blob {object_id} changed size while being read"
        )
    return payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _csv_bytes(columns: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=columns,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _spreadsheet_safe(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8")


def _spreadsheet_safe(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    stripped = value.lstrip(" \t\r\n")
    if stripped.startswith(("=", "+", "-", "@")) or value[0] in {"\t", "\r", "\n"}:
        return f"'{value}"
    return value


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _nested(mapping: Mapping[str, Any], *path: str) -> str:
    value: Any = mapping
    for component in path:
        if not isinstance(value, Mapping):
            return ""
        value = value.get(component)
    return _scalar(value)


def _walk_scalars(
    value: Any,
    path: str = "",
    *,
    depth: int = 0,
) -> Iterable[tuple[str, str]]:
    if depth > 32:
        raise WorksheetGenerationError("frontmatter nesting exceeds 32 levels")
    if isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            component = str(key)
            child_path = f"{path}.{component}" if path else component
            yield from _walk_scalars(value[key], child_path, depth=depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_scalars(child, f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, (str, int, float, bool)):
        yield path, str(value)


def _frontmatter(payload: bytes) -> tuple[dict[str, Any], str, list[str]]:
    if yaml is None:
        raise WorksheetGenerationError(
            "PyYAML is required for structured frontmatter parsing; install the 'PyYAML' dependency"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {}, "invalid_utf8", ["invalid_utf8"]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing", ["frontmatter_missing"]
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        return {}, "unterminated", ["frontmatter_unterminated"]
    source = "\n".join(lines[1:closing_index])
    try:
        for event in yaml.parse(source, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.events.AliasEvent):
                return {}, "yaml_alias", ["frontmatter_yaml_alias"]
        parsed = yaml.load(source, Loader=_unique_key_safe_loader())
    except (yaml.YAMLError, RecursionError):
        return {}, "yaml_error", ["frontmatter_yaml_error"]
    if not isinstance(parsed, Mapping):
        return {}, "non_mapping", ["frontmatter_not_mapping"]
    normalized = {str(key): value for key, value in parsed.items()}
    return normalized, "parsed", []


def _unique_key_safe_loader() -> type[Any]:
    class UniqueKeySafeLoader(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
            mapping: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str):
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        "mapping keys must be strings",
                        key_node.start_mark,
                    )
                try:
                    duplicate = key in mapping
                except TypeError as error:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        "found an unhashable key",
                        key_node.start_mark,
                    ) from error
                if duplicate:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                    )
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    return UniqueKeySafeLoader


def _extract_urls(frontmatter: Mapping[str, Any]) -> list[tuple[str, str]]:
    urls: set[tuple[str, str]] = set()
    for field, scalar in _walk_scalars(frontmatter):
        for match in _URL_RE.findall(scalar):
            urls.add((field, match.rstrip(".,;:")))
    return sorted(urls)


def _registry_hints(
    urls: list[tuple[str, str]], registry: str
) -> tuple[list[str], list[str], list[str]]:
    identities: set[str] = set()
    fields: set[str] = set()
    source_urls: set[str] = set()
    for field, url in urls:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        identity = ""
        if registry == "pip" and host in {"pypi.org", "www.pypi.org"}:
            if len(parts) >= 2 and parts[0].lower() in {"project", "pypi"}:
                identity = parts[1]
        elif registry == "npm" and host in {"npmjs.com", "www.npmjs.com"}:
            if len(parts) >= 2 and parts[0] == "package":
                identity = (
                    "/".join(parts[1:3])
                    if parts[1].startswith("@") and len(parts) >= 3
                    else parts[1]
                )
        if identity:
            identities.add(identity)
            fields.add(field)
            source_urls.add(url)
    return sorted(identities), sorted(fields), sorted(source_urls)


def _github_hints(urls: list[tuple[str, str]]) -> list[str]:
    repositories: set[str] = set()
    for _, url in urls:
        parsed = urlsplit(url)
        if (parsed.hostname or "").lower() not in {"github.com", "www.github.com"}:
            continue
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            repositories.add(f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}")
    return sorted(repositories)


def _join(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def _normalize_hint(registry: str, identity: str) -> str | None:
    if registry == "pip":
        normalized = re.sub(r"[-_.]+", "-", identity).casefold()
        return normalized if len(normalized) <= 214 and _PIP_NAME_RE.fullmatch(normalized) else None
    normalized = identity.casefold()
    package_component = normalized.rsplit("/", maxsplit=1)[-1]
    if (
        len(normalized) > 214
        or package_component in {".", ".."}
        or not _NPM_NAME_RE.fullmatch(normalized)
    ):
        return None
    return normalized


def _page_paths(entries: Mapping[str, tuple[str, str]]) -> list[str]:
    prefix = f"{CONTENT_ROOT}/"
    pages: list[str] = []
    for path in entries:
        if not path.startswith(prefix):
            continue
        relative_path = path[len(prefix) :]
        if "/" in relative_path:
            raise WorksheetGenerationError(
                f"nested package content is not supported: {path}"
            )
        if not relative_path.endswith(".md"):
            raise WorksheetGenerationError(
                f"unexpected package content file type: {path}"
            )
        if relative_path != "_index.md":
            pages.append(path)
    if len(pages) > MAX_PACKAGE_PAGES:
        raise WorksheetGenerationError(
            f"package corpus exceeds {MAX_PACKAGE_PAGES} pages"
        )
    return sorted(pages)


def _validate_catalog_compatible_paths(
    entries: Mapping[str, tuple[str, str]], pages: list[str]
) -> None:
    slugs: set[str] = set()
    folded_slugs: set[str] = set()
    expected_workflows: set[str] = set()
    for path in pages:
        slug = Path(path).stem
        if not _SLUG_RE.fullmatch(slug) or _CONTROL_SLUG_RE.fullmatch(slug.casefold()):
            raise WorksheetGenerationError(f"invalid or reserved package slug: {slug}")
        if slug.casefold() in folded_slugs:
            raise WorksheetGenerationError(
                f"case-insensitive package slug collision: {slug}"
            )
        slugs.add(slug)
        folded_slugs.add(slug.casefold())
        expected_workflows.add(f"{WORKFLOW_ROOT}/test-{slug}.yml")

    for path in entries:
        if not _PACKAGE_WORKFLOW_RE.fullmatch(path):
            continue
        if _CONTROL_WORKFLOW_RE.fullmatch(path):
            continue
        if path not in expected_workflows:
            raise WorksheetGenerationError(
                f"package workflow has no matching package page: {path}"
            )


def generate_worksheet(
    repository: Path,
    revision: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Generate deterministic advisory files and return the manifest payload."""
    if yaml is None:
        raise WorksheetGenerationError(
            "PyYAML is required for structured frontmatter parsing; install the 'PyYAML' dependency"
        )
    repository = repository.resolve()
    if not (repository / ".git").exists():
        raise WorksheetGenerationError(f"repository root is not a Git worktree: {repository}")
    exact_commit = resolve_exact_commit(repository, revision)
    entries = _revision_tree(repository, exact_commit)
    pages = _page_paths(entries)
    if not pages:
        raise WorksheetGenerationError(f"no package pages found at {CONTENT_ROOT} in {exact_commit}")
    _validate_catalog_compatible_paths(entries, pages)

    inventory_rows: list[dict[str, str]] = []
    decision_rows: list[dict[str, str]] = []
    present_workflows = 0
    malformed_frontmatter = 0
    for content_path in pages:
        slug = Path(content_path).stem
        content_oid, _ = entries[content_path]
        content = _read_blob(repository, content_oid)
        workflow_path = f"{WORKFLOW_ROOT}/test-{slug}.yml"
        workflow_entry = entries.get(workflow_path)
        if workflow_entry is None:
            workflow_presence = "absent"
            workflow_sha256 = ""
        else:
            workflow_presence = "present"
            workflow_sha256 = _sha256(_read_blob(repository, workflow_entry[0]))
            present_workflows += 1

        parsed, parse_status, flags = _frontmatter(content)
        if parse_status != "parsed":
            malformed_frontmatter += 1
        urls = _extract_urls(parsed)
        pip_hints, pip_fields, pip_urls = _registry_hints(urls, "pip")
        npm_hints, npm_fields, npm_urls = _registry_hints(urls, "npm")
        github_hints = _github_hints(urls)
        inventory_rows.append(
            {
                "base_commit": exact_commit,
                "slug": slug,
                "content_path": content_path,
                "content_sha256": _sha256(content),
                "workflow_path": workflow_path,
                "workflow_presence": workflow_presence,
                "workflow_sha256": workflow_sha256,
                "frontmatter_parse_status": parse_status,
                "display_name_hint": _nested(parsed, "name"),
                "category_hint": _nested(parsed, "category"),
                "download_url_hint": _nested(parsed, "download_url"),
                "homepage_url_hint": _nested(parsed, "optional_info", "homepage_url"),
                "official_docs_url_hint": _nested(
                    parsed, "optional_info", "getting_started_resources", "official_docs"
                ),
                "github_repository_hints": _join(github_hints),
                "direct_pypi_identity_hints": _join(pip_hints),
                "direct_npm_identity_hints": _join(npm_hints),
                "data_quality_flags": _join(sorted(flags)),
            }
        )
        for registry, hints, fields, source_urls in (
            ("pip", pip_hints, pip_fields, pip_urls),
            ("npm", npm_hints, npm_fields, npm_urls),
        ):
            normalized_hints = {
                normalized
                for hint in hints
                if (normalized := _normalize_hint(registry, hint)) is not None
            }
            invalid_hints = {
                hint for hint in hints if _normalize_hint(registry, hint) is None
            }
            decision_rows.append(
                {
                    "base_commit": exact_commit,
                    "decision_id": f"{slug}:{registry}",
                    "slug": slug,
                    "registry": registry,
                    "candidate_identity_hints": _join(hints),
                    "normalized_candidate_identity_hints": _join(sorted(normalized_hints)),
                    "invalid_candidate_identity_hints": _join(sorted(invalid_hints)),
                    "candidate_source_fields": _join(fields),
                    "candidate_source_urls": _join(source_urls),
                    "decision_status": "unknown",
                    "exhaustive": "false",
                    "approved_identities": "",
                    "review_state": "pending",
                    "review_notes": "",
                }
            )

    file_payloads = {
        OUTPUT_FILES[0]: _csv_bytes(INVENTORY_COLUMNS, inventory_rows),
        OUTPUT_FILES[1]: _csv_bytes(DECISION_COLUMNS, decision_rows),
        OUTPUT_FILES[2]: _csv_bytes(EVIDENCE_COLUMNS, []),
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "purpose": "advisory_package_identity_review",
        "base_commit": exact_commit,
        "content_root": CONTENT_ROOT,
        "counts": {
            "package_pages": len(inventory_rows),
            "present_workflows": present_workflows,
            "absent_workflows": len(inventory_rows) - present_workflows,
            "registry_decisions": len(decision_rows),
            "evidence_rows": 0,
            "malformed_frontmatter_pages": malformed_frontmatter,
        },
        "safety": {
            "advisory_only": True,
            "decision_status": "unknown",
            "exhaustive": False,
            "approved_identities_prefilled": False,
            "reviewer_metadata_prefilled": False,
            "hints_are_evidence": False,
        },
        "files": {
            name: {"sha256": _sha256(payload), "bytes": len(payload)}
            for name, payload in sorted(file_payloads.items())
        },
    }
    manifest_payload = _canonical_json(manifest)

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        raise WorksheetGenerationError(
            f"output directory already exists; choose a new path: {output_directory}"
        )
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.",
            dir=output_directory.parent,
        )
    )
    try:
        for name, payload in file_payloads.items():
            (temporary / name).write_bytes(payload)
        (temporary / MANIFEST_NAME).write_bytes(manifest_payload)
        os.replace(temporary, output_directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="dashboard Git worktree (default: repository containing this script)",
    )
    parser.add_argument(
        "--revision",
        required=True,
        help="exact full lowercase commit ID to inventory",
    )
    parser.add_argument(
        "--output-directory",
        required=True,
        type=Path,
        help="directory for deterministic advisory CSV and manifest files",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        manifest = generate_worksheet(
            options.repository_root,
            options.revision,
            options.output_directory.resolve(),
        )
    except WorksheetGenerationError as error:
        print(f"worksheet generation failed: {error}", file=sys.stderr)
        return 1
    print(
        "generated advisory worksheet for "
        f"{manifest['counts']['package_pages']} packages at {manifest['base_commit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
