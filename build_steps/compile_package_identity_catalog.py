#!/usr/bin/env python3
"""Compile a fully reviewed worksheet bundle into the schema 1.1 catalog."""

from __future__ import annotations

import sys

_ISOLATED_MODE_ERROR = (
    "Python isolated mode (-I) is required; invoke this compiler with "
    "'python3 -I -B build_steps/compile_package_identity_catalog.py'"
)

if __name__ == "__main__" and not sys.flags.isolated:
    print(f"catalog compilation failed: {_ISOLATED_MODE_ERROR}", file=sys.stderr)
    raise SystemExit(1)

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any


CATALOG_PATH = ".github/package-identity-catalog.json"
CONTENT_ROOT = "content/linux/opensource_packages"
GENERATOR_NAME = "generate_package_identity_review_worksheet.py"
VALIDATOR_NAME = "validate_package_identity_catalog.py"
MANIFEST_NAME = "manifest.json"
MAX_REVIEW_FILE_BYTES = 25_000_000
MAX_EVIDENCE_ROWS = 64_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PIP_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NPM_NAME_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9._-]+|[a-z0-9][a-z0-9._-]*)$"
)

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
MUTABLE_DECISION_COLUMNS = {
    "decision_status",
    "exhaustive",
    "approved_identities",
    "review_state",
    "review_notes",
}
IMMUTABLE_DECISION_COLUMNS = tuple(
    column for column in DECISION_COLUMNS if column not in MUTABLE_DECISION_COLUMNS
)
REVIEW_STATUSES = {"verified", "not_applicable", "unknown", "ambiguous"}
REGISTRIES = ("pip", "npm")


class CatalogCompilationError(RuntimeError):
    """Raised when reviewed worksheet input cannot be trusted."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr.strip()
        raise CatalogCompilationError(
            f"command failed ({' '.join(arguments)}): {detail or error}"
        ) from error


def _read_bounded(path: Path, label: str) -> bytes:
    try:
        state = path.lstat()
    except OSError as error:
        raise CatalogCompilationError(f"{label} is missing: {path}") from error
    if path.is_symlink() or not path.is_file():
        raise CatalogCompilationError(f"{label} must be a regular file: {path}")
    if not 1 <= state.st_size <= MAX_REVIEW_FILE_BYTES:
        raise CatalogCompilationError(
            f"{label} must contain 1 to {MAX_REVIEW_FILE_BYTES} bytes"
        )
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise CatalogCompilationError(f"could not read {label}: {path}") from error
    if len(payload) != state.st_size:
        raise CatalogCompilationError(f"{label} changed while being read")
    return payload


def _load_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogCompilationError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise CatalogCompilationError(f"{label} must contain one JSON object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogCompilationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_csv(
    payload: bytes,
    columns: tuple[str, ...],
    label: str,
    *,
    maximum_rows: int,
) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CatalogCompilationError(f"{label} must be UTF-8") from error
    if "\x00" in text:
        raise CatalogCompilationError(f"{label} must not contain NUL bytes")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames != list(columns):
            raise CatalogCompilationError(
                f"{label} header must exactly match the reviewed worksheet contract"
            )
        rows = list(reader)
    except csv.Error as error:
        raise CatalogCompilationError(f"{label} is malformed CSV: {error}") from error
    if len(rows) > maximum_rows:
        raise CatalogCompilationError(f"{label} exceeds {maximum_rows} rows")
    for index, row in enumerate(rows, start=2):
        if None in row or set(row) != set(columns):
            raise CatalogCompilationError(f"{label} row {index} has unexpected columns")
        if any(value is None for value in row.values()):
            raise CatalogCompilationError(f"{label} row {index} is incomplete")
    return rows


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _require_committed_tool(repository: Path, relative_path: str) -> Path:
    path = repository / relative_path
    try:
        state = path.lstat()
    except OSError as error:
        raise CatalogCompilationError(f"required tool is missing: {relative_path}") from error
    if path.is_symlink() or not path.is_file() or state.st_size < 1:
        raise CatalogCompilationError(f"required tool must be a regular file: {relative_path}")
    committed_object = _run(
        ["git", "rev-parse", f"HEAD:{relative_path}"], cwd=repository
    ).stdout.strip()
    worktree_object = _run(
        ["git", "hash-object", "--", relative_path], cwd=repository
    ).stdout.strip()
    if worktree_object != committed_object:
        raise CatalogCompilationError(
            f"required tool differs from the exact base commit: {relative_path}"
        )
    return path


def _formula_neutralized(value: str) -> bool:
    if not value.startswith("'"):
        return False
    remainder = value[1:]
    stripped = remainder.lstrip(" \t\r\n")
    return bool(stripped) and (
        stripped.startswith(("=", "+", "-", "@"))
        or remainder[0] in {"\t", "\r", "\n"}
    )


def _require_review_text(value: str, context: str, *, maximum: int) -> str:
    if _formula_neutralized(value):
        raise CatalogCompilationError(
            f"{context} contains a spreadsheet-neutralized value; enter the literal reviewed value"
        )
    if "\x00" in value or "\n" in value or "\r" in value or len(value) > maximum:
        raise CatalogCompilationError(f"{context} must be bounded single-line text")
    return value


def _parse_identities(value: str, registry: str, context: str) -> list[str]:
    _require_review_text(value, context, maximum=4_000)
    try:
        identities = json.loads(value)
    except json.JSONDecodeError as error:
        raise CatalogCompilationError(
            f"{context} must be an explicit canonical JSON array"
        ) from error
    if not isinstance(identities, list) or any(
        not isinstance(identity, str) for identity in identities
    ):
        raise CatalogCompilationError(f"{context} must be an array of strings")
    if len(identities) > 16:
        raise CatalogCompilationError(f"{context} exceeds 16 identities")
    if value != json.dumps(identities, ensure_ascii=True, separators=(",", ":")):
        raise CatalogCompilationError(f"{context} must use canonical compact JSON")
    for identity in identities:
        pattern = _PIP_NAME_RE if registry == "pip" else _NPM_NAME_RE
        if not pattern.fullmatch(identity) or identity != identity.casefold():
            raise CatalogCompilationError(
                f"{context} contains a non-normalized {registry} identity"
            )
    if identities != sorted(set(identities)):
        raise CatalogCompilationError(f"{context} must be sorted and unique")
    return identities


def _verify_generator_manifest(
    worksheet_directory: Path,
    repository: Path,
) -> tuple[dict[str, Any], Path]:
    manifest_path = worksheet_directory / MANIFEST_NAME
    supplied_manifest_bytes = _read_bounded(manifest_path, "generator manifest")
    manifest = _load_json(supplied_manifest_bytes, "generator manifest")
    expected_top_keys = {
        "schema_version",
        "purpose",
        "base_commit",
        "content_root",
        "counts",
        "safety",
        "files",
    }
    if set(manifest) != expected_top_keys:
        raise CatalogCompilationError("generator manifest has unexpected fields")
    base_commit = manifest.get("base_commit")
    if not isinstance(base_commit, str) or not _FULL_COMMIT_RE.fullmatch(base_commit):
        raise CatalogCompilationError("generator manifest base_commit is invalid")
    head = _run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
    if head != base_commit:
        raise CatalogCompilationError(
            f"worksheet base commit {base_commit} does not match repository HEAD {head}"
        )

    temporary_root = Path(tempfile.mkdtemp(prefix="catalog-pristine-worksheet-"))
    pristine = temporary_root / "worksheet"
    generator = _require_committed_tool(
        repository, f"build_steps/{GENERATOR_NAME}"
    )
    try:
        _run(
            [
                sys.executable,
                "-I",
                "-B",
                str(generator),
                "--repository-root",
                str(repository),
                "--revision",
                base_commit,
                "--output-directory",
                str(pristine),
            ],
            cwd=repository,
        )
        pristine_manifest = _read_bounded(pristine / MANIFEST_NAME, "pristine manifest")
        if supplied_manifest_bytes != pristine_manifest:
            raise CatalogCompilationError(
                "generator manifest does not match a fresh deterministic generation"
            )
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != {
            "corpus-inventory.csv",
            "registry-decisions.csv",
            "evidence-ledger.csv",
        }:
            raise CatalogCompilationError("generator manifest file set is invalid")
        for name, metadata in files.items():
            pristine_payload = _read_bounded(pristine / name, f"pristine {name}")
            if not isinstance(metadata, dict) or set(metadata) != {"sha256", "bytes"}:
                raise CatalogCompilationError(f"manifest metadata is invalid for {name}")
            if metadata["sha256"] != _sha256(pristine_payload) or metadata["bytes"] != len(
                pristine_payload
            ):
                raise CatalogCompilationError(f"manifest hash or size is invalid for {name}")
        return manifest, pristine
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def _load_validator(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("catalog_compiler_validator", path)
    if spec is None or spec.loader is None:
        raise CatalogCompilationError("could not load the catalog validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_reviewed_decisions(
    reviewed_rows: list[dict[str, str]],
    pristine_rows: list[dict[str, str]],
    base_commit: str,
) -> dict[str, dict[str, Any]]:
    if len(reviewed_rows) != len(pristine_rows):
        raise CatalogCompilationError("registry decision row count changed after generation")
    decisions: dict[str, dict[str, Any]] = {}
    for index, (reviewed, pristine) in enumerate(
        zip(reviewed_rows, pristine_rows, strict=True), start=2
    ):
        for column in IMMUTABLE_DECISION_COLUMNS:
            if reviewed[column] != pristine[column]:
                raise CatalogCompilationError(
                    f"registry-decisions.csv row {index} changed immutable field {column}"
                )
        decision_id = reviewed["decision_id"]
        if decision_id in decisions:
            raise CatalogCompilationError(f"duplicate decision_id: {decision_id}")
        if reviewed["base_commit"] != base_commit:
            raise CatalogCompilationError(f"{decision_id} has the wrong base commit")
        registry = reviewed["registry"]
        if registry not in REGISTRIES or decision_id != f"{reviewed['slug']}:{registry}":
            raise CatalogCompilationError(f"invalid decision join: {decision_id}")
        status = _require_review_text(
            reviewed["decision_status"], f"{decision_id}.decision_status", maximum=32
        )
        if status not in REVIEW_STATUSES:
            raise CatalogCompilationError(f"{decision_id} has an unsupported status")
        exhaustive_text = _require_review_text(
            reviewed["exhaustive"], f"{decision_id}.exhaustive", maximum=5
        )
        if exhaustive_text not in {"true", "false"}:
            raise CatalogCompilationError(f"{decision_id}.exhaustive must be true or false")
        exhaustive = exhaustive_text == "true"
        review_state = _require_review_text(
            reviewed["review_state"], f"{decision_id}.review_state", maximum=32
        )
        if review_state != "reviewed":
            raise CatalogCompilationError(f"{decision_id} is not explicitly reviewed")
        identities = _parse_identities(
            reviewed["approved_identities"],
            registry,
            f"{decision_id}.approved_identities",
        )
        _require_review_text(
            reviewed["review_notes"], f"{decision_id}.review_notes", maximum=2_000
        )
        if status == "verified" and not identities:
            raise CatalogCompilationError(f"{decision_id} verified status needs an identity")
        if status in {"not_applicable", "unknown"} and identities:
            raise CatalogCompilationError(f"{decision_id} status cannot claim identities")
        if status == "not_applicable" and not exhaustive:
            raise CatalogCompilationError(f"{decision_id} not_applicable must be exhaustive")
        if status in {"unknown", "ambiguous"} and exhaustive:
            raise CatalogCompilationError(f"{decision_id} status cannot be exhaustive")
        decisions[decision_id] = {
            "slug": reviewed["slug"],
            "registry": registry,
            "status": status,
            "exhaustive": exhaustive,
            "identities": identities,
        }
    return decisions


def _validate_evidence(
    rows: list[dict[str, str]],
    decisions: Mapping[str, dict[str, Any]],
    base_commit: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    previous_key: tuple[str, str] | None = None
    for index, row in enumerate(rows, start=2):
        decision_id = row["decision_id"]
        decision = decisions.get(decision_id)
        if decision is None:
            raise CatalogCompilationError(
                f"evidence-ledger.csv row {index} has no matching decision"
            )
        if (
            row["base_commit"] != base_commit
            or row["slug"] != decision["slug"]
            or row["registry"] != decision["registry"]
        ):
            raise CatalogCompilationError(
                f"evidence-ledger.csv row {index} has an invalid row join"
            )
        evidence: dict[str, Any] = {}
        for field in (
            "source_kind",
            "source_locator",
            "source_revision",
            "evidence_sha256",
            "verified_by",
            "verified_at",
        ):
            evidence[field] = _require_review_text(
                row[field], f"evidence row {index}.{field}", maximum=2_000
            )
            if not evidence[field]:
                raise CatalogCompilationError(
                    f"evidence-ledger.csv row {index}.{field} is required"
                )
        rationale = _require_review_text(
            row["rationale"], f"evidence row {index}.rationale", maximum=2_000
        )
        evidence["rationale"] = rationale or None
        canonical = json.dumps(
            evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        key = (decision_id, canonical)
        if previous_key is not None and key < previous_key:
            raise CatalogCompilationError(
                "evidence-ledger.csv rows must be ordered by decision_id and canonical evidence"
            )
        if previous_key == key:
            raise CatalogCompilationError(f"duplicate evidence row for {decision_id}")
        previous_key = key
        grouped[decision_id].append(evidence)

    for decision_id, decision in decisions.items():
        evidence = grouped.get(decision_id, [])
        if not 1 <= len(evidence) <= 32:
            raise CatalogCompilationError(
                f"{decision_id} must contain 1 to 32 reviewed evidence rows"
            )
        kinds = {item["source_kind"] for item in evidence}
        rationales = [item["rationale"] for item in evidence if item["rationale"]]
        if decision["status"] in {"not_applicable", "unknown", "ambiguous"} and not rationales:
            raise CatalogCompilationError(f"{decision_id} requires an evidence rationale")
        required_kind = "pypi_api" if decision["registry"] == "pip" else "npm_api"
        if decision["exhaustive"] and required_kind not in kinds:
            raise CatalogCompilationError(
                f"{decision_id} exhaustive review requires {required_kind} evidence"
            )
    return grouped


def _calculate_corpus_sha256(inventory: list[dict[str, str]]) -> str:
    path_digests: list[tuple[str, str | None]] = []
    for row in inventory:
        path_digests.append((row["content_path"], row["content_sha256"]))
        workflow_digest = (
            row["workflow_sha256"] if row["workflow_presence"] == "present" else None
        )
        path_digests.append((row["workflow_path"], workflow_digest))
    digest = hashlib.sha256()
    for path, content_digest in sorted(path_digests, key=lambda item: item[0]):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        if content_digest is None:
            digest.update(b"absent")
        else:
            digest.update(b"sha256:")
            digest.update(content_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _catalog_payload(
    inventory: list[dict[str, str]],
    decisions: Mapping[str, dict[str, Any]],
    evidence: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for row in inventory:
        slug = row["slug"]
        content_path = row["content_path"]
        if content_path in seen_paths:
            raise CatalogCompilationError(f"duplicate inventory content path: {content_path}")
        seen_paths.add(content_path)
        dimensions: dict[str, Any] = {}
        for registry in REGISTRIES:
            decision_id = f"{slug}:{registry}"
            decision = decisions.get(decision_id)
            if decision is None:
                raise CatalogCompilationError(f"missing reviewed decision: {decision_id}")
            dimensions[registry] = {
                "status": decision["status"],
                "exhaustive": decision["exhaustive"],
                "identities": decision["identities"],
                "evidence": evidence[decision_id],
            }
        records.append(
            {
                "slug": slug,
                "content_path": content_path,
                "content_sha256": row["content_sha256"],
                "workflow": {
                    "path": row["workflow_path"],
                    "presence": row["workflow_presence"],
                    "sha256": row["workflow_sha256"] or None,
                },
                "registries": dimensions,
            }
        )
    if records != sorted(records, key=lambda record: record["content_path"]):
        raise CatalogCompilationError("inventory rows are not canonically ordered")
    if len(decisions) != len(records) * len(REGISTRIES):
        raise CatalogCompilationError("decision coverage is not exactly pip and npm per package")
    return {
        "schema_version": "1.1",
        "corpus": {
            "content_root": CONTENT_ROOT,
            "entry_count": len(records),
            "corpus_sha256": _calculate_corpus_sha256(inventory),
        },
        "records": records,
    }


def _validate_candidate(
    repository: Path,
    base_commit: str,
    catalog_bytes: bytes,
) -> None:
    validator_path = _require_committed_tool(
        repository, f"build_steps/{VALIDATOR_NAME}"
    )
    validator = _load_validator(validator_path)
    temporary_root = Path(tempfile.mkdtemp(prefix="catalog-compiler-validation-"))
    worktree = temporary_root / "worktree"
    added = False
    try:
        _run(
            ["git", "worktree", "add", "--detach", str(worktree), base_commit],
            cwd=repository,
        )
        added = True
        destination = worktree / CATALOG_PATH
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(catalog_bytes)
        try:
            validator.validate_catalog(worktree)
        except validator.CatalogValidationError as error:
            raise CatalogCompilationError(
                f"schema 1.1 validator rejected the compiled catalog: {error}"
            ) from error
    finally:
        if added:
            try:
                _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=repository)
            except CatalogCompilationError:
                pass
        shutil.rmtree(temporary_root, ignore_errors=True)


def compile_catalog(repository: Path, worksheet_directory: Path) -> Path:
    """Validate a reviewed bundle and atomically publish the canonical catalog."""
    repository = repository.resolve()
    worksheet_directory = worksheet_directory.resolve()
    if not (repository / ".git").exists():
        raise CatalogCompilationError("repository-root must be a Git worktree")
    manifest, pristine = _verify_generator_manifest(worksheet_directory, repository)
    pristine_root = pristine.parent
    try:
        base_commit = manifest["base_commit"]
        supplied_inventory = _read_bounded(
            worksheet_directory / "corpus-inventory.csv", "corpus inventory"
        )
        pristine_inventory = _read_bounded(
            pristine / "corpus-inventory.csv", "pristine corpus inventory"
        )
        if supplied_inventory != pristine_inventory:
            raise CatalogCompilationError(
                "corpus-inventory.csv must remain byte-identical to generator output"
            )
        inventory = _parse_csv(
            supplied_inventory,
            INVENTORY_COLUMNS,
            "corpus-inventory.csv",
            maximum_rows=10_000,
        )
        reviewed_decision_rows = _parse_csv(
            _read_bounded(
                worksheet_directory / "registry-decisions.csv", "registry decisions"
            ),
            DECISION_COLUMNS,
            "registry-decisions.csv",
            maximum_rows=20_000,
        )
        pristine_decision_rows = _parse_csv(
            _read_bounded(pristine / "registry-decisions.csv", "pristine decisions"),
            DECISION_COLUMNS,
            "pristine registry-decisions.csv",
            maximum_rows=20_000,
        )
        pristine_evidence = _parse_csv(
            _read_bounded(pristine / "evidence-ledger.csv", "pristine evidence"),
            EVIDENCE_COLUMNS,
            "pristine evidence-ledger.csv",
            maximum_rows=0,
        )
        if pristine_evidence:
            raise CatalogCompilationError("generator evidence template must start empty")
        reviewed_evidence_rows = _parse_csv(
            _read_bounded(
                worksheet_directory / "evidence-ledger.csv", "evidence ledger"
            ),
            EVIDENCE_COLUMNS,
            "evidence-ledger.csv",
            maximum_rows=MAX_EVIDENCE_ROWS,
        )
        if len(inventory) != manifest["counts"]["package_pages"]:
            raise CatalogCompilationError("manifest package count does not match inventory")
        decisions = _validate_reviewed_decisions(
            reviewed_decision_rows, pristine_decision_rows, base_commit
        )
        evidence = _validate_evidence(reviewed_evidence_rows, decisions, base_commit)
        payload = _catalog_payload(inventory, decisions, evidence)
        catalog_bytes = _canonical_json(payload)
        _validate_candidate(repository, base_commit, catalog_bytes)

        output = repository / CATALOG_PATH
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and (output.is_symlink() or not output.is_file()):
            raise CatalogCompilationError("catalog output path must be absent or a regular file")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".package-identity-catalog.", suffix=".json", dir=output.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(catalog_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, output)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        return output
    finally:
        shutil.rmtree(pristine_root, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="dashboard Git worktree",
    )
    parser.add_argument(
        "--worksheet-directory",
        required=True,
        type=Path,
        help="reviewed generator bundle containing manifest.json and all three CSVs",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        output = compile_catalog(options.repository_root, options.worksheet_directory)
    except CatalogCompilationError as error:
        print(f"catalog compilation failed: {error}", file=sys.stderr)
        return 1
    print(f"compiled reviewed schema 1.1 catalog at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
