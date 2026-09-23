"""Pure, bounded catalog rebinding; never authorization to publish a repair.

The caller must validate the complete exact-base catalog/tree and authenticate a
source-only anchor on that base, its exact candidate blob and regular Git modes,
the dedicated App bot, and the anchor's actual GitHub committer date. A commit ID
or bot-shaped string supplied here is NOT proof of any of those facts. The caller
retains historical evidence in Git, not in the new record as current evidence.

These functions do no I/O, clock reads, or candidate execution. Filesystem,
symlink, Git ancestry, timestamp freshness, full catalog/Hugo validation and
final candidate receipt checks belong to the caller. This is not a substitute
for the existing validator. Only its pure schema primitives and corpus digest
are reused; its evidence validator also reads the wall clock.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestration_contract import decode_json


_SPEC = importlib.util.spec_from_file_location(
    "smoke_repair_catalog_validator",
    Path(__file__).resolve().parents[2] / "build_steps/validate_package_identity_catalog.py",
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load trusted catalog validator")
catalog_validator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = catalog_validator
_SPEC.loader.exec_module(catalog_validator)

CatalogRebindingError = catalog_validator.CatalogValidationError
AUTOMATED_ADVISORY_RATIONALE = (
    "Automated verification binds these exact workflow bytes to the recorded "
    "immutable source-anchor commit. This advisory evidence does not establish "
    "a registry identity, exhaustive registry coverage, human approval, or a "
    "successful workflow execution."
)
_ADVISORY_RATIONALES = frozenset({
    "Exact repository bytes at the reviewed base commit are provided as advisory "
    "evidence; they do not establish a registry identity or exhaustive registry coverage.",
    "Exact workflow bytes at the recorded source revision are advisory evidence "
    "only; they do not establish a registry identity or exhaustive registry coverage.",
    "Exact workflow bytes at the committed smoke-test fix revision are advisory "
    "evidence only; they do not establish a registry identity or exhaustive registry coverage.",
    AUTOMATED_ADVISORY_RATIONALE,
})
_BOT_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?\[bot\]")


class ManualCatalogRebindingRequired(CatalogRebindingError):
    """The target's evidence is outside the mechanical advisory-only contract."""


@dataclass(frozen=True)
class CatalogRebindingPlan:
    record_index: int
    package_slug: str
    workflow_path: str
    original_sha256: str
    candidate_sha256: str
    candidate_corpus_sha256: str
    generated_evidence: tuple[tuple[str, int], ...]


def _object(value, keys, label):
    result = catalog_validator._require_dict(value, label)
    catalog_validator._require_exact_keys(result, keys, label)
    return result


def _text(value, label, maximum):
    if not isinstance(value, (str, bytes)):
        raise CatalogRebindingError(f"{label} must be UTF-8 text or bytes")
    try:
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if not 0 < len(raw) <= maximum or b"\x00" in raw:
            raise CatalogRebindingError(f"{label} is empty, oversized, or contains NUL")
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise CatalogRebindingError(f"{label} must be UTF-8") from exc


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _evidence_key(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _timestamp(value, label):
    value = catalog_validator._require_single_line(value, label, maximum=64)
    if not catalog_validator._RFC3339_TIMESTAMP_RE.fullmatch(value):
        raise CatalogRebindingError(f"{label} must be canonical RFC3339 timestamp text")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalogRebindingError(f"{label} is not a valid timestamp") from exc


def _commit(value, label):
    if (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
            or value == "0" * 40):
        raise CatalogRebindingError(f"{label} must be a nonzero immutable 40-character Git commit ID")
    return value


def _slug(value):
    if (not isinstance(value, str) or not catalog_validator._SLUG_RE.fullmatch(value)
            or ".." in value or value.casefold().startswith("all-packages")):
        raise CatalogRebindingError("unsafe or reserved package slug")
    return value


def _registries(record, owners):
    """Check payload shape/bindings without claiming historical revision verification."""
    registries = _object(record["registries"], {"pip", "npm"}, "registries")
    for kind, dimension in registries.items():
        _object(dimension, {"status", "exhaustive", "identities", "evidence"}, "registry dimension")
        status = catalog_validator._require_string(dimension["status"], "status", maximum=32)
        if status not in catalog_validator._DIMENSION_STATUSES:
            raise CatalogRebindingError("unsupported registry status")
        exhaustive = catalog_validator._require_bool(dimension["exhaustive"], "exhaustive")
        identities = catalog_validator._require_list(dimension["identities"], "identities")
        if len(identities) > 16:
            raise CatalogRebindingError("too many registry identities")
        for identity in identities:
            catalog_validator._require_string(identity, "registry identity", maximum=214)
            if catalog_validator._normalize_registry_identity(kind, identity) != identity:
                raise CatalogRebindingError("registry identity must be normalized")
            previous = owners.setdefault((kind, identity), record["slug"])
            if previous != record["slug"]:
                raise CatalogRebindingError("registry identity has multiple owners")
        if identities != sorted(set(identities)):
            raise CatalogRebindingError("registry identities must be sorted and unique")
        if ((status == "verified" and not identities)
                or (status in {"unknown", "not_applicable"} and identities)
                or (status in {"unknown", "ambiguous"} and exhaustive)
                or (status == "not_applicable" and not exhaustive)):
            raise CatalogRebindingError("registry decisions are inconsistent")
        evidence = catalog_validator._require_list(dimension["evidence"], "evidence")
        if not 1 <= len(evidence) <= 32:
            raise CatalogRebindingError("registry evidence must contain 1 to 32 entries")
        kinds, rationales, keys = set(), [], []
        for item in evidence:
            _object(item, {"source_kind", "source_locator", "source_revision", "evidence_sha256",
                           "verified_by", "verified_at", "rationale"}, "evidence")
            source_kind = catalog_validator._require_string(item["source_kind"], "source_kind", maximum=32)
            if source_kind not in catalog_validator._EVIDENCE_SOURCE_KINDS:
                raise CatalogRebindingError("unsupported evidence source_kind")
            for field, maximum in (("source_locator", 2000), ("source_revision", 256), ("verified_by", 256)):
                catalog_validator._require_single_line(item[field], field, maximum=maximum)
            _timestamp(item["verified_at"], "evidence.verified_at")
            digest = catalog_validator._require_sha256(item["evidence_sha256"], "evidence_sha256")
            if digest == "0" * 64 or item["source_revision"] in {"0" * 40, "0" * 64}:
                raise CatalogRebindingError("evidence must not use a zero digest or revision")
            if item["rationale"] is not None:
                rationales.append(catalog_validator._require_single_line(item["rationale"], "rationale", maximum=2000))
            if source_kind == "generated_workflow":
                _commit(item["source_revision"], "evidence.source_revision")
                if (record["workflow"]["presence"] != "present"
                        or item["source_locator"] != record["workflow"]["path"]
                        or digest != record["workflow"]["sha256"]):
                    raise CatalogRebindingError("generated evidence does not bind the original workflow")
            else:
                catalog_validator._validate_https_locator(
                    item["source_locator"], approved_hosts=catalog_validator._APPROVED_EVIDENCE_HOSTS[source_kind],
                    context="evidence.source_locator",
                )
                pattern = (catalog_validator._GIT_OBJECT_ID_RE if source_kind == "github_api"
                           else catalog_validator._SHA256_RE)
                if not pattern.fullmatch(item["source_revision"]):
                    raise CatalogRebindingError("evidence source_revision must be immutable")
            kinds.add(source_kind)
            keys.append(_evidence_key(item))
        if keys != sorted(set(keys)):
            raise CatalogRebindingError("evidence must be canonically sorted and unique")
        if status in {"unknown", "ambiguous", "not_applicable"} and not rationales:
            raise CatalogRebindingError("registry decision requires a rationale")
        if exhaustive and ("pypi_api" if kind == "pip" else "npm_api") not in kinds:
            raise CatalogRebindingError("exhaustive registry decision requires independent evidence")


def validate_catalog_rebinding(raw, *, package_slug, workflow_path, original_source,
                               candidate_source) -> CatalogRebindingPlan:
    """Validate payload bindings, not Git provenance, and return immutable plan data."""
    text = _text(raw, "catalog", catalog_validator.MAX_CATALOG_BYTES)
    try:
        payload = decode_json(text)
    except ValueError as exc:
        raise CatalogRebindingError("catalog is not unambiguous strict JSON") from exc
    _object(payload, {"schema_version", "corpus", "records"}, "catalog")
    if payload["schema_version"] != catalog_validator.SCHEMA_VERSION:
        raise CatalogRebindingError("unsupported catalog schema")
    if text != _canonical(payload):
        raise CatalogRebindingError("catalog must use canonical JSON formatting")
    slug = _slug(package_slug)
    catalog_validator._require_repository_path(workflow_path, "workflow_path", suffix=".yml")
    if workflow_path != f".github/workflows/test-{slug}.yml":
        raise CatalogRebindingError("target must use its canonical workflow path")
    original = _text(original_source, "original_source", catalog_validator.MAX_WORKFLOW_BYTES).encode("utf-8")
    candidate = _text(candidate_source, "candidate_source", catalog_validator.MAX_WORKFLOW_BYTES).encode("utf-8")
    if original == candidate:
        raise CatalogRebindingError("candidate_source must change the workflow")
    original_digest, candidate_digest = (hashlib.sha256(value).hexdigest() for value in (original, candidate))
    corpus = _object(payload["corpus"], {"content_root", "entry_count", "corpus_sha256"}, "corpus")
    records = catalog_validator._require_list(payload["records"], "records")
    count = catalog_validator._require_int(corpus["entry_count"], "entry_count")
    if (corpus["content_root"] != catalog_validator.CONTENT_ROOT
            or count != len(records) or not 1 <= count <= catalog_validator.MAX_PACKAGE_PAGES):
        raise CatalogRebindingError("catalog corpus inventory is invalid")
    catalog_validator._require_sha256(corpus["corpus_sha256"], "corpus_sha256")
    seen, paths, pairs, targets, owners = set(), [], [], [], {}
    for index, record in enumerate(records):
        _object(record, {"slug", "content_path", "content_sha256", "workflow", "registries"}, "record")
        identity = _slug(record["slug"])
        if identity.casefold() in seen:
            raise CatalogRebindingError("catalog package slugs must be unique, including case")
        seen.add(identity.casefold())
        if record["content_path"] != f"{catalog_validator.CONTENT_ROOT}/{identity}.md":
            raise CatalogRebindingError("record content_path must match the canonical package page")
        paths.append(record["content_path"])
        pairs.append((record["content_path"], catalog_validator._require_sha256(record["content_sha256"], "content_sha256")))
        workflow = _object(record["workflow"], {"path", "presence", "sha256"}, "workflow")
        if workflow["path"] != f".github/workflows/test-{identity}.yml":
            raise CatalogRebindingError("record workflow must use its canonical path")
        if workflow["presence"] == "present":
            catalog_validator._require_sha256(workflow["sha256"], "workflow.sha256")
        elif workflow["presence"] != "absent" or workflow["sha256"] is not None:
            raise CatalogRebindingError("invalid workflow presence or digest")
        pairs.append((workflow["path"], workflow["sha256"]))
        _registries(record, owners)
        if identity == slug:
            targets.append(index)
    if paths != sorted(paths) or len(targets) != 1:
        raise CatalogRebindingError("catalog records must be sorted with one exact target slug")
    index = targets[0]
    target = records[index]
    if target["workflow"]["presence"] != "present" or target["workflow"]["sha256"] != original_digest:
        raise CatalogRebindingError("catalog target does not bind original_source")
    if catalog_validator.calculate_corpus_sha256(pairs) != corpus["corpus_sha256"]:
        raise CatalogRebindingError("base catalog corpus digest is stale")
    generated = []
    for kind in ("pip", "npm"):
        dimension = target["registries"][kind]
        entries = [(kind, number) for number, item in enumerate(dimension["evidence"])
                   if item["source_kind"] == "generated_workflow"]
        if entries and (dimension["status"] != "unknown" or dimension["exhaustive"]
                        or dimension["identities"] or len(entries) != 1):
            raise ManualCatalogRebindingRequired("generated evidence with identity assertions or multiple entries requires manual review")
        for _, number in entries:
            if dimension["evidence"][number]["rationale"] not in _ADVISORY_RATIONALES:
                raise ManualCatalogRebindingRequired("unrecognized generated-workflow rationale requires manual review")
        generated.extend(entries)
    candidate_pairs = [(path, candidate_digest if path == workflow_path else digest) for path, digest in pairs]
    return CatalogRebindingPlan(index, slug, workflow_path, original_digest, candidate_digest,
                                catalog_validator.calculate_corpus_sha256(candidate_pairs), tuple(generated))


def rebind_catalog(raw, *, package_slug, workflow_path, original_source, candidate_source,
                   source_commit, verified_by, verified_at) -> str:
    """Render a validated rebind using caller-authenticated anchor provenance.

    The supplied time is the anchor's committer date, not a claim of human review
    or successful native execution. No existing reviewer is reattributed.
    """
    plan = validate_catalog_rebinding(
        raw, package_slug=package_slug, workflow_path=workflow_path,
        original_source=original_source, candidate_source=candidate_source,
    )
    _commit(source_commit, "source_commit")
    if not isinstance(verified_by, str) or not _BOT_RE.fullmatch(verified_by):
        raise CatalogRebindingError("verified_by must be a dedicated App bot login")
    timestamp = _timestamp(verified_at, "verified_at")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", verified_at):
        raise CatalogRebindingError("verified_at must be the anchor's UTC GitHub committer date")
    payload = decode_json(raw)
    target = payload["records"][plan.record_index]
    for kind, number in plan.generated_evidence:
        evidence = target["registries"][kind]["evidence"][number]
        if source_commit == evidence["source_revision"]:
            raise CatalogRebindingError("source_commit must replace the historical source revision")
        if timestamp < _timestamp(evidence["verified_at"], "historical verified_at"):
            raise CatalogRebindingError("verified_at must not precede historical evidence")
        evidence.update(source_revision=source_commit, evidence_sha256=plan.candidate_sha256,
                        verified_by=verified_by, verified_at=verified_at,
                        rationale=AUTOMATED_ADVISORY_RATIONALE)
    for kind in {kind for kind, _ in plan.generated_evidence}:
        target["registries"][kind]["evidence"].sort(key=_evidence_key)
    target["workflow"]["sha256"] = plan.candidate_sha256
    payload["corpus"]["corpus_sha256"] = plan.candidate_corpus_sha256
    result = _canonical(payload)
    if len(result.encode("utf-8")) > catalog_validator.MAX_CATALOG_BYTES:
        raise CatalogRebindingError("rebound catalog exceeds byte limit")
    return result
