#!/usr/bin/env python3
"""Collect bounded registry evidence for explicit worksheet candidates."""

from __future__ import annotations

import sys

_ISOLATED_MODE_ERROR = (
    "Python isolated mode (-I) is required; invoke this collector with "
    "'python3 -I -B build_steps/collect_registry_evidence.py'"
)

if __name__ == "__main__" and not sys.flags.isolated:
    print(f"registry evidence collection failed: {_ISOLATED_MODE_ERROR}", file=sys.stderr)
    raise SystemExit(1)

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


MANIFEST_NAME = "manifest.json"
WORKSHEET_FILES = (
    "corpus-inventory.csv",
    "registry-decisions.csv",
    "evidence-ledger.csv",
)
OUTPUT_FILES = (
    "collected-evidence.csv",
    "proposed-decisions.csv",
    "collector-manifest.json",
)
MAX_INPUT_BYTES = 25_000_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_ROWS = 20_000
MAX_CANDIDATES = 200
MAX_JSON_NODES = 200_000
MAX_JSON_DEPTH = 32
DEFAULT_TIMEOUT_SECONDS = 10.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PIP_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NPM_NAME_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9._-]+|[a-z0-9][a-z0-9._-]*)$"
)

INVENTORY_COLUMNS = (
    "base_commit", "slug", "content_path", "content_sha256", "workflow_path",
    "workflow_presence", "workflow_sha256", "frontmatter_parse_status",
    "display_name_hint", "category_hint", "download_url_hint",
    "homepage_url_hint", "official_docs_url_hint", "github_repository_hints",
    "direct_pypi_identity_hints", "direct_npm_identity_hints", "data_quality_flags",
)
DECISION_COLUMNS = (
    "base_commit", "decision_id", "slug", "registry", "candidate_identity_hints",
    "normalized_candidate_identity_hints", "invalid_candidate_identity_hints",
    "candidate_source_fields", "candidate_source_urls", "decision_status",
    "exhaustive", "approved_identities", "review_state", "review_notes",
)
EVIDENCE_COLUMNS = (
    "base_commit", "decision_id", "slug", "registry", "source_kind",
    "source_locator", "source_revision", "evidence_sha256", "rationale",
    "verified_by", "verified_at",
)
PROPOSAL_COLUMNS = (
    "base_commit", "decision_id", "slug", "registry", "candidate_identity",
    "proposed_status", "proposed_exhaustive", "proposed_approved_identities",
    "evidence_sha256", "review_required", "proposal_notes",
)


class EvidenceCollectionError(RuntimeError):
    """Raised when evidence cannot be collected within the trust boundary."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceCollectionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                EvidenceCollectionError(f"{label} contains non-finite number {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvidenceCollectionError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise EvidenceCollectionError(f"{label} must contain one JSON object")
    _bound_json(value, label)
    return value


def _bound_json(value: Any, label: str) -> None:
    nodes = 0
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise EvidenceCollectionError(f"{label} exceeds JSON complexity limits")
        if isinstance(item, dict):
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and len(item) > MAX_RESPONSE_BYTES:
            raise EvidenceCollectionError(f"{label} contains an oversized JSON string")


def _read_regular(path: Path, label: str) -> bytes:
    try:
        state = path.lstat()
    except OSError as error:
        raise EvidenceCollectionError(f"{label} is missing: {path}") from error
    if path.is_symlink() or not path.is_file():
        raise EvidenceCollectionError(f"{label} must be a regular file")
    if not 1 <= state.st_size <= MAX_INPUT_BYTES:
        raise EvidenceCollectionError(f"{label} exceeds its size limit")
    payload = path.read_bytes()
    if len(payload) != state.st_size:
        raise EvidenceCollectionError(f"{label} changed while being read")
    return payload


def _parse_csv(payload: bytes, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceCollectionError(f"{label} must be UTF-8") from error
    if "\x00" in text:
        raise EvidenceCollectionError(f"{label} must not contain NUL bytes")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != columns:
        raise EvidenceCollectionError(f"{label} has an unexpected header")
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise EvidenceCollectionError(f"{label} has too many rows")
    if any(None in row for row in rows):
        raise EvidenceCollectionError(f"{label} contains an over-wide row")
    return rows


def _json_string_list(value: str, context: str) -> list[str]:
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise EvidenceCollectionError(f"{context} is not valid JSON") from error
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise EvidenceCollectionError(f"{context} must be a JSON string array")
    if parsed != sorted(set(parsed)):
        raise EvidenceCollectionError(f"{context} must be sorted and unique")
    return parsed


def load_worksheet(directory: Path) -> tuple[str, dict[str, dict[str, str]]]:
    manifest_payload = _read_regular(directory / MANIFEST_NAME, "worksheet manifest")
    manifest = _load_json(manifest_payload, "worksheet manifest")
    if manifest.get("schema_version") != "1.0" or manifest.get("purpose") != "advisory_package_identity_review":
        raise EvidenceCollectionError("worksheet manifest has an unsupported contract")
    base_commit = manifest.get("base_commit")
    if not isinstance(base_commit, str) or not _COMMIT_RE.fullmatch(base_commit):
        raise EvidenceCollectionError("worksheet manifest has an invalid base commit")
    file_contract = manifest.get("files")
    if not isinstance(file_contract, dict) or set(file_contract) != set(WORKSHEET_FILES):
        raise EvidenceCollectionError("worksheet manifest file set is invalid")

    payloads: dict[str, bytes] = {}
    for name in WORKSHEET_FILES:
        payload = _read_regular(directory / name, name)
        entry = file_contract.get(name)
        if not isinstance(entry, dict) or set(entry) != {"bytes", "sha256"}:
            raise EvidenceCollectionError(f"worksheet manifest entry is invalid: {name}")
        if entry["bytes"] != len(payload) or entry["sha256"] != _sha256(payload):
            raise EvidenceCollectionError(f"worksheet file does not match manifest: {name}")
        payloads[name] = payload

    inventory = _parse_csv(payloads["corpus-inventory.csv"], INVENTORY_COLUMNS, "corpus-inventory.csv")
    decisions = _parse_csv(payloads["registry-decisions.csv"], DECISION_COLUMNS, "registry-decisions.csv")
    evidence = _parse_csv(payloads["evidence-ledger.csv"], EVIDENCE_COLUMNS, "evidence-ledger.csv")
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or (
        counts.get("package_pages") != len(inventory)
        or counts.get("registry_decisions") != len(decisions)
        or counts.get("evidence_rows") != len(evidence)
    ):
        raise EvidenceCollectionError("worksheet manifest row counts do not match its CSV files")
    safety = manifest.get("safety")
    if not isinstance(safety, dict) or (
        safety.get("advisory_only") is not True
        or safety.get("hints_are_evidence") is not False
        or safety.get("approved_identities_prefilled") is not False
    ):
        raise EvidenceCollectionError("worksheet manifest safety declarations are invalid")
    slugs = {row["slug"] for row in inventory}
    if len(slugs) != len(inventory) or any(row["base_commit"] != base_commit for row in inventory):
        raise EvidenceCollectionError("inventory rows are not uniquely bound to the base commit")

    indexed: dict[str, dict[str, str]] = {}
    for row in decisions:
        decision_id = row["decision_id"]
        registry = row["registry"]
        if (
            registry not in {"pip", "npm"}
            or row["slug"] not in slugs
            or decision_id != f"{row['slug']}:{registry}"
            or row["base_commit"] != base_commit
            or decision_id in indexed
        ):
            raise EvidenceCollectionError(f"invalid decision row join: {decision_id}")
        _json_string_list(row["normalized_candidate_identity_hints"], f"{decision_id} normalized hints")
        indexed[decision_id] = row
    if len(indexed) != 2 * len(inventory):
        raise EvidenceCollectionError("worksheet must contain exactly two decisions per package")
    return base_commit, indexed


def _normalize_candidate(registry: str, value: str) -> str:
    if registry == "pip":
        normalized = re.sub(r"[-_.]+", "-", value).lower()
        pattern = _PIP_NAME_RE
    else:
        normalized = value.lower()
        pattern = _NPM_NAME_RE
    if value != normalized or not pattern.fullmatch(value):
        raise EvidenceCollectionError(f"candidate is not a normalized {registry} identity: {value}")
    return normalized


def parse_candidate_specs(specifications: list[str], decisions: Mapping[str, dict[str, str]]) -> list[tuple[dict[str, str], str]]:
    if not specifications:
        raise EvidenceCollectionError("at least one explicit --candidate is required")
    if len(specifications) > MAX_CANDIDATES:
        raise EvidenceCollectionError(f"no more than {MAX_CANDIDATES} candidates may be requested")
    selected: list[tuple[dict[str, str], str]] = []
    seen: set[tuple[str, str]] = set()
    for specification in specifications:
        decision_id, separator, candidate = specification.partition("=")
        row = decisions.get(decision_id)
        if not separator or row is None or not candidate:
            raise EvidenceCollectionError(f"invalid candidate specification: {specification}")
        _normalize_candidate(row["registry"], candidate)
        hints = _json_string_list(
            row["normalized_candidate_identity_hints"],
            f"{decision_id} normalized hints",
        )
        if candidate not in hints:
            raise EvidenceCollectionError(
                f"candidate is not an explicit normalized worksheet hint: {decision_id}={candidate}"
            )
        key = (decision_id, candidate)
        if key in seen:
            raise EvidenceCollectionError(f"duplicate candidate specification: {specification}")
        seen.add(key)
        selected.append((row, candidate))
    return sorted(selected, key=lambda item: (item[0]["decision_id"], item[1]))


def registry_endpoint(registry: str, candidate: str) -> str:
    if registry == "pip":
        encoded = urllib.parse.quote(candidate, safe="")
        return f"https://pypi.org/pypi/{encoded}/json"
    encoded = urllib.parse.quote(candidate, safe="")
    return f"https://registry.npmjs.org/{encoded}/latest"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def fetch_registry_json(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    allowed = (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and parsed.query == ""
        and parsed.fragment == ""
        and (
            (parsed.hostname == "pypi.org" and re.fullmatch(r"/pypi/[^/]+/json", parsed.path))
            or (parsed.hostname == "registry.npmjs.org" and re.fullmatch(r"/[^/]+/latest", parsed.path))
        )
    )
    if not allowed:
        raise EvidenceCollectionError(f"registry endpoint is outside the allowlist: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "arm-dashboard-registry-evidence-collector/1",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200 or response.geturl() != url:
                raise EvidenceCollectionError("registry response status or final URL is invalid")
            media_type = response.headers.get_content_type().lower()
            if media_type not in {"application/json", "application/vnd.npm.install-v1+json"}:
                raise EvidenceCollectionError(f"registry returned disallowed content type: {media_type}")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise EvidenceCollectionError("compressed registry responses are not accepted")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError as error:
                    raise EvidenceCollectionError("registry returned an invalid Content-Length") from error
                if not 1 <= declared_size <= MAX_RESPONSE_BYTES:
                    raise EvidenceCollectionError("registry response exceeds its size limit")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except EvidenceCollectionError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
        raise EvidenceCollectionError(f"registry request failed for {url}: {error}") from error
    if not 1 <= len(payload) <= MAX_RESPONSE_BYTES:
        raise EvidenceCollectionError("registry response exceeds its size limit")
    return payload


def _canonical_snapshot(payload: bytes, registry: str, candidate: str) -> bytes:
    document = _load_json(payload, f"{registry} registry response")
    if registry == "pip":
        info = document.get("info")
        observed = info.get("name") if isinstance(info, dict) else None
        if not isinstance(observed, str) or re.sub(r"[-_.]+", "-", observed).lower() != candidate:
            raise EvidenceCollectionError("PyPI response identity does not match the candidate")
    else:
        observed = document.get("name")
        if not isinstance(observed, str) or observed.lower() != candidate:
            raise EvidenceCollectionError("npm response identity does not match the candidate")
    return (json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _csv_bytes(columns: tuple[str, ...], rows: list[Mapping[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def collect(
    worksheet_directory: Path,
    output_directory: Path,
    candidate_specs: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[[str, float], bytes] = fetch_registry_json,
) -> dict[str, Any]:
    if output_directory.exists() or output_directory.is_symlink():
        raise EvidenceCollectionError("output directory must not already exist")
    if not 0.1 <= timeout <= 30.0:
        raise EvidenceCollectionError("timeout must be between 0.1 and 30 seconds")
    base_commit, decisions = load_worksheet(worksheet_directory)
    selected = parse_candidate_specs(candidate_specs, decisions)

    temporary_parent = output_directory.parent
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=temporary_parent))
    try:
        snapshots = temporary / "snapshots"
        snapshots.mkdir(mode=0o700)
        evidence_rows: list[dict[str, str]] = []
        proposal_rows: list[dict[str, str]] = []
        snapshot_entries: list[dict[str, str]] = []
        for decision, candidate in selected:
            registry = decision["registry"]
            endpoint = registry_endpoint(registry, candidate)
            canonical = _canonical_snapshot(fetcher(endpoint, timeout), registry, candidate)
            digest = _sha256(canonical)
            snapshot_name = f"{digest}.json"
            snapshot_path = snapshots / snapshot_name
            if snapshot_path.exists() and snapshot_path.read_bytes() != canonical:
                raise EvidenceCollectionError("snapshot digest collision")
            snapshot_path.write_bytes(canonical)
            rationale = (
                f"Collector observed registry metadata whose declared package name normalizes "
                f"to explicit worksheet candidate {candidate}; human review is still required."
            )
            evidence_rows.append({
                "base_commit": base_commit,
                "decision_id": decision["decision_id"],
                "slug": decision["slug"],
                "registry": registry,
                "source_kind": "pypi_api" if registry == "pip" else "npm_api",
                "source_locator": endpoint,
                "source_revision": digest,
                "evidence_sha256": digest,
                "rationale": rationale,
                "verified_by": "",
                "verified_at": "",
            })
            proposal_rows.append({
                "base_commit": base_commit,
                "decision_id": decision["decision_id"],
                "slug": decision["slug"],
                "registry": registry,
                "candidate_identity": candidate,
                "proposed_status": "unknown",
                "proposed_exhaustive": "false",
                "proposed_approved_identities": "",
                "evidence_sha256": digest,
                "review_required": "true",
                "proposal_notes": "Registry name match only; this is not approval or exhaustive coverage.",
            })
            snapshot_entries.append({
                "decision_id": decision["decision_id"],
                "candidate_identity": candidate,
                "source_locator": endpoint,
                "path": f"snapshots/{snapshot_name}",
                "sha256": digest,
            })

        evidence_payload = _csv_bytes(EVIDENCE_COLUMNS, evidence_rows)
        proposal_payload = _csv_bytes(PROPOSAL_COLUMNS, proposal_rows)
        (temporary / "collected-evidence.csv").write_bytes(evidence_payload)
        (temporary / "proposed-decisions.csv").write_bytes(proposal_payload)
        manifest = {
            "schema_version": "1.0",
            "purpose": "bounded_registry_evidence_collection",
            "base_commit": base_commit,
            "worksheet_manifest_sha256": _sha256(_read_regular(worksheet_directory / MANIFEST_NAME, "worksheet manifest")),
            "safety": {
                "ai_used": False,
                "credentials_used": False,
                "proxies_used": False,
                "human_review_required": True,
                "proposed_status": "unknown",
                "proposed_exhaustive": False,
                "not_applicable_inferred": False,
            },
            "files": {
                "collected-evidence.csv": {"bytes": len(evidence_payload), "sha256": _sha256(evidence_payload)},
                "proposed-decisions.csv": {"bytes": len(proposal_payload), "sha256": _sha256(proposal_payload)},
            },
            "snapshots": snapshot_entries,
        }
        manifest_payload = (json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (temporary / "collector-manifest.json").write_bytes(manifest_payload)
        os.replace(temporary, output_directory)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet-directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="DECISION_ID=NORMALIZED_IDENTITY",
        help="explicit normalized worksheet hint to query; repeat for additional candidates",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    arguments = parser.parse_args()
    try:
        manifest = collect(
            arguments.worksheet_directory,
            arguments.output_directory,
            arguments.candidate,
            timeout=arguments.timeout_seconds,
        )
    except EvidenceCollectionError as error:
        print(f"registry evidence collection failed: {error}", file=sys.stderr)
        return 1
    print(
        f"collected {len(manifest['snapshots'])} bounded registry snapshots for "
        f"{manifest['base_commit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
