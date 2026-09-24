"""Persistent bounded discovery, independent of public catalog publishing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

import yaml

from .http import BoundedHTTP, CollectionError
from .sources import discover_github, dockerhub_collect, github_collect, unknown

DEFAULT_LIMITS = {
    "max_candidates": 8,
    "max_discovered": 2,
    "max_source_records": 40,
    "max_queries": 2,
    "max_requests": 50,
    "max_seconds": 180,
    "timeout_seconds": 15,
    "max_response_bytes": 2_000_000,
    "max_search_pages": 1,
    "max_release_pages": 2,
    "max_asset_pages": 4,
    "max_seed_candidates": 100,
    "oci_fallback": True,
}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    return value.isoformat(timespec="seconds")


def valid_stars(value):
    """Missing/unusable popularity sorts after measured positive values."""
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else -1
    )


def normalize_candidate(value):
    if not isinstance(value, dict):
        raise ValueError("Each candidate must be a mapping")
    source = str(value.get("source", "github")).lower()
    name = str(value.get("name", "")).strip().strip("/")
    if source not in {"github", "dockerhub"} or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name
    ):
        raise ValueError(
            "Candidates require source github/dockerhub and an owner/name identifier"
        )
    name = name.removesuffix(".git").lower() if source == "github" else name.lower()
    tag = str(value.get("tag", "latest"))
    if source == "dockerhub" and not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag
    ):
        raise ValueError("Invalid Docker Hub tag")
    identity = f"{source}:{name}" + (":" + tag if source == "dockerhub" else "")
    return {
        **value,
        "id": identity,
        "name": name,
        "source": source,
        **({"tag": tag} if source == "dockerhub" else {}),
    }


def open_state(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS candidates (
          id TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL, next_check_at TEXT NOT NULL, checked_at TEXT,
          investigation_count INTEGER NOT NULL DEFAULT 0, last_status TEXT,
          last_result TEXT, last_fingerprint TEXT
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, summary TEXT
        );
        CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
          checked_at TEXT NOT NULL, status TEXT NOT NULL, scope TEXT NOT NULL,
          fingerprint TEXT NOT NULL, result TEXT NOT NULL,
          UNIQUE(run_id, candidate_id)
        );
        CREATE INDEX IF NOT EXISTS due_candidates ON candidates(next_check_at);
        CREATE TABLE IF NOT EXISTS pipeline_lock (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires_at TEXT NOT NULL);
    """)
    return db


def catalog_identities(path):
    """Match official repository URLs only; catalog membership is not support proof."""
    if path is None:
        return set()
    path = Path(path)
    if path.is_dir():
        # Read the actual Linux Hugo catalog, without requiring PoC1 or a build.
        files = sorted(path.glob("*_packages/*.md"))
        if not files:
            raise ValueError("Catalog directory contains no Linux package records")
        document = []
        for file in files:
            text = file.read_text(encoding="utf-8")
            if text.startswith("---\n"):
                document.append(yaml.safe_load(text.split("---", 2)[1]))
    else:
        text = path.read_text(encoding="utf-8")
        document = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    identities = set()

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in {"github_repo", "github_repository"}
                    and isinstance(child, str)
                    and re.fullmatch(r"[\w.-]+/[\w.-]+", child)
                ):
                    identities.add("github:" + child.lower().removesuffix(".git"))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            for owner, name in re.findall(
                r"https?://github\.com/([\w.-]+)/([\w.-]+)", value
            ):
                identities.add(
                    "github:" + owner.lower() + "/" + name.lower().removesuffix(".git")
                )
            for name in re.findall(
                r"https?://hub\.docker\.com/r/([\w.-]+/[\w.-]+)", value
            ):
                identities.add("dockerhub:" + name.lower())
            for name in re.findall(r"https?://hub\.docker\.com/_/([\w.-]+)", value):
                identities.add("dockerhub:library/" + name.lower())

    visit(document)
    return identities


@contextmanager
def state_lock(path):
    """OS releases this lock even after a crash; no lease can expire mid-run."""
    with Path(str(path) + ".lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "A discovery run is already active for this state database"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    allowed = {
        "seeds",
        "discovery",
        "limits",
        "refresh_hours",
        "force_refresh",
        "ai_review",
        "catalog_path",
        "state_path",
    }
    if set(config) - allowed:
        raise ValueError(
            "Unknown configuration keys: " + ", ".join(sorted(set(config) - allowed))
        )
    for name in ("limits", "refresh_hours", "discovery", "ai_review"):
        if name in config and not isinstance(config[name], dict):
            raise ValueError(f"{name} must be a mapping")
    if not isinstance(config.get("seeds", []), list):
        raise ValueError("seeds must be a list")
    if not isinstance(config.get("force_refresh", False), bool):
        raise ValueError("force_refresh must be true or false")
    extra_limits = set(config.get("limits", {})) - set(DEFAULT_LIMITS)
    if extra_limits:
        raise ValueError("Unknown limit keys: " + ", ".join(sorted(extra_limits)))
    limits = {**DEFAULT_LIMITS, **config.get("limits", {})}
    for key, value in limits.items():
        if key == "oci_fallback":
            if not isinstance(value, bool):
                raise ValueError("limits.oci_fallback must be true or false")
        elif (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            or (
                key not in {"timeout_seconds", "max_seconds"}
                and not isinstance(value, int)
            )
        ):
            raise ValueError(
                f"limits.{key} must be a positive finite "
                + ("number" if key in {"timeout_seconds", "max_seconds"} else "integer")
            )
    refresh = {
        "supported": 168,
        "gap": 168,
        "unknown": 24,
        **config.get("refresh_hours", {}),
    }
    if set(refresh) != {"supported", "gap", "unknown"}:
        raise ValueError("refresh_hours allows supported, gap and unknown only")
    if any(
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or not math.isfinite(x)
        or x < 0
        for x in refresh.values()
    ):
        raise ValueError("Refresh intervals must be nonnegative finite hours")
    discovery = config.get("discovery", {})
    if set(discovery) - {"github_queries", "min_stars"}:
        raise ValueError("Unknown discovery configuration key")
    queries = discovery.get("github_queries", [])
    if not isinstance(queries, list) or any(
        not isinstance(q, str) or not q.strip() or len(q) > 256 for q in queries
    ):
        raise ValueError(
            "github_queries must be a list of nonempty strings (up to 256 characters)"
        )
    stars = discovery.get("min_stars", 500)
    if isinstance(stars, bool) or not isinstance(stars, int) or stars < 0:
        raise ValueError("min_stars must be a nonnegative integer")
    ai = config.get("ai_review", {})
    if set(ai) - {
        "enabled",
        "provider",
        "model",
        "max_calls",
        "max_seconds",
        "timeout_seconds",
        "max_output_tokens",
    }:
        raise ValueError("Unknown ai_review configuration key")
    if "model" in ai and (not isinstance(ai["model"], str) or not ai["model"].strip()):
        raise ValueError("ai_review.model must be a nonempty model identifier")
    if not isinstance(ai.get("enabled", False), bool):
        raise ValueError("ai_review.enabled must be true or false")
    for key, default in (
        ("max_calls", 4),
        ("max_seconds", 120),
        ("timeout_seconds", 30),
        ("max_output_tokens", 1500),
    ):
        value = ai.get(key, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"ai_review.{key} must be positive and finite")
        if key in {"max_calls", "max_output_tokens"} and not isinstance(value, int):
            raise ValueError(f"ai_review.{key} must be an integer")
    return limits, refresh


def review_evidence(result, reviewer):
    """Advisory review only; exact quotes and known source URLs must validate."""
    review = reviewer(
        {
            "scope": result["scope"],
            "deterministic_status": result["status"],
            "evidence": result["evidence"],
        }
    )
    if (
        not isinstance(review, dict)
        or not isinstance(review.get("citations"), list)
        or not review["citations"]
    ):
        raise ValueError("AI review requires citations with exact evidence quotes")
    for citation in review["citations"]:
        if (
            not isinstance(citation, dict)
            or not citation.get("quote")
            or not any(
                citation.get("url") == e["url"] and citation["quote"] in e["excerpt"]
                for e in result["evidence"]
            )
        ):
            raise ValueError(
                "AI review cited a URL or quotation absent from collected evidence"
            )
    note = review.get("note")
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise ValueError(
            "AI review note must be a nonempty string of at most 2000 characters"
        )
    return {
        "status": "completed",
        "note": note,
        "citations": review["citations"],
        "authority": "Advisory interpretation; classification remains deterministic and human review is required.",
    }


def run_pipeline(
    config_path,
    output_dir,
    catalog_path=None,
    *,
    http=None,
    now=None,
    reviewer=None,
    require_ai=False,
):
    """Collect one bounded run and return its JSON-serializable summary and paths.

    Injectable HTTP and reviewer objects support offline tests and optional AI.
    The public catalog is read only. State and outputs are internal local files.
    """
    config_path, output_dir = Path(config_path).resolve(), Path(output_dir).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = {} if config is None else config
    limits, refresh = validate_config(config)
    if require_ai and reviewer is None:
        from .ai_review import configured_reviewer

        reviewer, error = configured_reviewer(config)
        if reviewer is None:
            raise ValueError(
                error or "AI review is required but disabled in the configuration"
            )
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError("Observation time must include a timezone")
    now = now.astimezone(timezone.utc)
    at, run_id = (
        timestamp(now),
        now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(config.get("state_path") or output_dir / "discovery.sqlite3")
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(state_path):
        db = open_state(state_path)
        # A killed process cannot retain an OS lock. Recover its unfinished audit row.
        db.execute(
            "UPDATE runs SET finished_at=?,summary=? WHERE finished_at IS NULL",
            (
                at,
                json.dumps(
                    {
                        "status": "interrupted",
                        "error": "Previous process ended before publishing a complete report; saved observations are retained.",
                    }
                ),
            ),
        )
        db.execute("INSERT INTO runs(id,started_at) VALUES (?,?)", (run_id, at))
        db.commit()
        try:
            return _run(
                config,
                config_path,
                output_dir,
                catalog_path,
                limits,
                refresh,
                now,
                at,
                run_id,
                state_path,
                db,
                http or BoundedHTTP(limits),
                reviewer,
            )
        except Exception as exc:
            db.rollback()
            db.execute(
                "UPDATE runs SET finished_at=?,summary=? WHERE id=?",
                (
                    timestamp(utcnow()),
                    json.dumps(
                        {
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                            "run_id": run_id,
                            "observations_retained": True,
                        }
                    ),
                    run_id,
                ),
            )
            db.commit()
            raise
        finally:
            db.close()


def _run(
    config,
    config_path,
    output_dir,
    catalog_path,
    limits,
    refresh,
    now,
    at,
    run_id,
    state_path,
    db,
    http,
    reviewer,
):
    started = time.monotonic()
    failures, skipped = [], []
    if reviewer is None:
        from .ai_review import configured_reviewer

        reviewer, ai_configuration_error = configured_reviewer(config)
        if ai_configuration_error:
            failures.append({"source": "ai_review", "reason": ai_configuration_error})
    configured_catalog = (
        Path(catalog_path).resolve() if catalog_path else config.get("catalog_path")
    )
    if configured_catalog and not Path(configured_catalog).is_absolute():
        configured_catalog = config_path.parent / configured_catalog
    try:
        tracked = catalog_identities(configured_catalog)
        catalog_state = "loaded" if configured_catalog else "not_configured"
    except (OSError, ValueError, yaml.YAMLError) as exc:
        tracked, catalog_state = set(), "unavailable"
        failures.append({"source": "catalog", "reason": str(exc)})
    known_ids = {row[0] for row in db.execute("SELECT id FROM candidates")}
    # Current seeds already have a reserved place in this run's queue, even on
    # the first invocation. Do not spend a discovery slot on them again.
    for seed in config.get("seeds", [])[: limits["max_seed_candidates"]]:
        try:
            known_ids.add(normalize_candidate(seed)["id"])
        except (ValueError, AttributeError):
            pass
    discovered, search_failures, search_skips = discover_github(
        http, config.get("discovery", {}), limits, known_ids=known_ids
    )
    failures.extend(search_failures)
    source_records_examined = sum(
        s.get("count", 0) for s in search_skips if s.get("informational")
    )
    skipped.extend(s for s in search_skips if not s.get("informational"))
    seeds = config.get("seeds", [])
    if len(seeds) > limits["max_seed_candidates"]:
        skipped.append(
            {
                "reason": "Seed queue insertion capped",
                "count": len(seeds) - limits["max_seed_candidates"],
            }
        )
    for raw in seeds[: limits["max_seed_candidates"]] + discovered:
        try:
            candidate = normalize_candidate(raw)
        except (ValueError, AttributeError) as exc:
            skipped.append({"candidate": str(raw), "reason": str(exc)})
            continue
        db.execute(
            "INSERT INTO candidates(id,payload,first_seen,last_seen,next_check_at) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen",
            (candidate["id"], json.dumps(candidate), at, at, at),
        )
    db.commit()
    force = bool(config.get("force_refresh", False))
    all_candidates = db.execute(
        "SELECT * FROM candidates ORDER BY next_check_at,first_seen,id"
    ).fetchall()
    due = [row for row in all_candidates if force or row["next_check_at"] <= at]
    # Older queued work first; within a batch use explicit seed order, then
    # GitHub star order. Never add incompatible pull/star units together.
    seed_priority = {}
    for i, seed in enumerate(seeds):
        try:
            seed_priority[normalize_candidate(seed)["id"]] = i
        except (ValueError, AttributeError):
            pass
    due.sort(
        key=lambda row: (
            row["next_check_at"],
            row["first_seen"],
            0 if row["id"] in seed_priority else 1,
            seed_priority.get(row["id"], 0),
            -valid_stars(json.loads(row["payload"]).get("discovery_stars")),
            row["id"],
        )
    )
    for row in all_candidates:
        if not force and row["next_check_at"] > at:
            skipped.append(
                {
                    "candidate_id": row["id"],
                    "reason": "Not due for refresh",
                    "next_check_at": row["next_check_at"],
                    "last_status": row["last_status"],
                }
            )
    findings = []
    for row in due[: limits["max_candidates"]]:
        if (
            time.monotonic() - started >= limits["max_seconds"]
            or http.requests_used >= limits["max_requests"]
        ):
            skipped.append(
                {
                    "candidate_id": row["id"],
                    "reason": "Run time or request limit reached; queued for next run",
                }
            )
            continue
        candidate = json.loads(row["payload"])
        try:
            collector = (
                github_collect if candidate["source"] == "github" else dockerhub_collect
            )
            result = collector(http, candidate, limits)
        except (
            CollectionError,
            KeyError,
            TypeError,
            AttributeError,
            ValueError,
        ) as exc:
            result = unknown(
                candidate,
                "Authoritative evidence collection was incomplete; support remains unknown.",
                [str(exc)],
            )
        identity = f"{candidate['source']}:{candidate['name']}"
        result.update(
            checked_at=at,
            catalog_tracked=(identity in tracked)
            if catalog_state == "loaded"
            else None,
            investigated_before=bool(row["investigation_count"]),
            investigation_count=row["investigation_count"] + 1,
            first_seen=row["first_seen"],
            previous_status=row["last_status"],
        )
        result["selection_reason"] = (
            ("GitHub discovery query: " + candidate["discovery_query"])
            if candidate.get("discovery_query")
            else candidate.get(
                "selection_reason",
                "Selected seed candidate or retained investigation queue",
            )
        )
        result["recommended_action"] = {
            "supported": "No gap action for this exact distribution scope. Refresh evidence on schedule; runtime validation remains separate.",
            "gap": "Human review: confirm whether the scoped missing Linux Arm64 distribution is an enablement priority and check existing internal ownership.",
            "unknown": "Investigate missing or ambiguous authoritative evidence before deciding whether an enablement gap exists.",
        }[result["status"]]
        if result["investigated_before"]:
            result["recommended_action"] += (
                " Continue the existing investigation history; do not open a duplicate investigation."
            )
        if result["catalog_tracked"]:
            result["recommended_action"] += (
                " The project is already cataloged; assess the distribution-specific finding independently."
            )
        # Save deterministic observations before invoking the optional model. A crash
        # leaves a truthful pending marker instead of losing the collected evidence.
        result["ai_review"] = {
            "status": "pending"
            if reviewer and result["evidence"]
            else ("not_configured" if reviewer is None else "no_evidence")
        }
        next_check = timestamp(now + timedelta(hours=refresh[result["status"]]))
        result["next_check_at"] = next_check
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "status": result["status"],
                    "scope": result["scope"],
                    "evidence": [
                        {
                            key: value
                            for key, value in e.items()
                            if key != "collected_at"
                        }
                        for e in result["evidence"]
                        if e.get("kind")
                        not in {"repository_metadata", "dockerhub_repository_metadata"}
                    ],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        result["evidence_changed"] = fingerprint != row["last_fingerprint"]
        serialized = json.dumps(result, ensure_ascii=False)
        db.execute(
            "INSERT INTO observations(run_id,candidate_id,checked_at,status,scope,fingerprint,result) VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                candidate["id"],
                at,
                result["status"],
                result["scope"],
                fingerprint,
                serialized,
            ),
        )
        db.execute(
            "UPDATE candidates SET checked_at=?,next_check_at=?,investigation_count=investigation_count+1,last_status=?,last_result=?,last_fingerprint=? WHERE id=?",
            (
                at,
                next_check,
                result["status"],
                serialized,
                fingerprint,
                candidate["id"],
            ),
        )
        db.commit()
        findings.append(result)
        failures.extend(
            {
                "candidate_id": candidate["id"],
                "source": candidate["source"],
                "reason": error,
            }
            for error in result["failures"]
        )
    for row in due[limits["max_candidates"] :]:
        skipped.append(
            {
                "candidate_id": row["id"],
                "reason": "Run candidate limit reached; saved queue retained",
            }
        )
    # Model latency has its own budget and cannot displace source collection.
    for result in findings:
        if result["ai_review"]["status"] != "pending":
            continue
        try:
            result["ai_review"] = review_evidence(result, reviewer)
        except Exception as exc:
            result["ai_review"] = {
                "status": "failed_validation",
                "reason": str(exc)[:500],
            }
            failures.append(
                {
                    "candidate_id": result["candidate_id"],
                    "source": "ai_review",
                    "reason": str(exc)[:500],
                }
            )
        serialized = json.dumps(result, ensure_ascii=False)
        db.execute(
            "UPDATE observations SET result=? WHERE run_id=? AND candidate_id=?",
            (serialized, run_id, result["candidate_id"]),
        )
        db.execute(
            "UPDATE candidates SET last_result=? WHERE id=?",
            (serialized, result["candidate_id"]),
        )
        db.commit()
    current_errors = list(failures)
    saved = db.execute(
        "SELECT id,last_result,next_check_at,investigation_count FROM candidates WHERE last_result IS NOT NULL ORDER BY id"
    ).fetchall()
    saved_results = [json.loads(row["last_result"]) for row in saved]
    investigated_ids = {f["candidate_id"] for f in findings}
    retained_findings = [
        {**result, "historical": True}
        for result in saved_results
        if result["candidate_id"] not in investigated_ids
    ]
    history = []
    for result in saved_results:
        preferred_evidence = sorted(
            result["evidence"],
            key=lambda evidence: {
                "oci_manifest": 0,
                "release_asset_inventory": 1,
                "dockerhub_tag_platforms": 2,
                "release_artifact": 3,
            }.get(evidence["kind"], 9),
        )
        history.append(
            {
                **{
                    key: result[key]
                    for key in (
                        "candidate_id",
                        "status",
                        "checked_at",
                        "scope",
                        "next_check_at",
                        "investigation_count",
                    )
                },
                "evidence_url": preferred_evidence[0]["url"]
                if preferred_evidence
                else None,
            }
        )
    queue = [
        {
            "candidate_id": row["id"],
            "name": json.loads(row["payload"])["name"],
            "source": json.loads(row["payload"])["source"],
            "selection_reason": json.loads(row["payload"]).get(
                "selection_reason", "Selected seed or bounded discovery query"
            ),
            "next_check_at": row["next_check_at"],
        }
        for row in db.execute(
            "SELECT * FROM candidates WHERE last_result IS NULL ORDER BY first_seen,id"
        )
    ]
    previous_run_failures = [
        {
            "run_id": row["id"],
            "started_at": row["started_at"],
            **json.loads(row["summary"]),
        }
        for row in db.execute(
            "SELECT * FROM runs WHERE summary IS NOT NULL ORDER BY started_at DESC LIMIT 20"
        )
        if json.loads(row["summary"]).get("status") in {"failed", "interrupted"}
    ]
    for failed_run in previous_run_failures:
        failures.append(
            {
                "source": "previous_run",
                "reason": f"Run {failed_run['run_id']}: {failed_run.get('error', 'interrupted')}; retained observations are available.",
            }
        )
    counts = {
        status: sum(f["status"] == status for f in findings)
        for status in ("supported", "gap", "unknown")
    }
    counts.update(
        investigated=len(findings),
        newly_investigated=sum(not f["investigated_before"] for f in findings),
        refreshed=sum(f["investigated_before"] for f in findings),
        catalog_tracked=sum(f["catalog_tracked"] is True for f in findings),
        queued_total=len(all_candidates),
        pending_investigation=len(queue),
        due_at_start=len(due),
        skipped=len(skipped),
        failures=len(failures),
        requests=http.requests_used,
        saved_observations=db.execute("SELECT COUNT(*) FROM observations").fetchone()[
            0
        ],
    )
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str((run_dir / "opportunities.json").resolve()),
        "docx": str((run_dir / "opportunities.docx").resolve()),
        "csv": str((run_dir / "opportunities.csv").resolve()),
    }
    summary = {
        "schema_version": 1,
        "status": "completed",
        "outcome": "degraded" if current_errors else "completed",
        "current_errors": current_errors,
        "run_id": run_id,
        "generated_at": at,
        "finished_at": timestamp(utcnow()),
        "counts": counts,
        "findings": findings,
        "failures": failures,
        "skipped": skipped,
        "limits": limits,
        "refresh_hours": refresh,
        "state_path": str(state_path.resolve()),
        "report_paths": paths,
        "saved_history": history,
        "queue": queue,
        "previous_run_failures": previous_run_failures,
        "catalog_comparison": {"status": catalog_state, "identity_count": len(tracked)},
        "ai_review": {
            "status": "configured" if reviewer else "not_configured",
            "completed": sum(f["ai_review"]["status"] == "completed" for f in findings),
            "eligible": sum(bool(f["evidence"]) for f in findings),
            "failed": sum(
                f["ai_review"]["status"] == "failed_validation" for f in findings
            ),
            "requested": bool(config.get("ai_review", {}).get("enabled"))
            or reviewer is not None,
            "disclosure": "AI review is advisory and quote-validated; deterministic metadata rules determine status."
            if reviewer
            else "No AI reviewer is configured. This run uses deterministic metadata verification only; AI-assisted interpretation remains an optional integration.",
        },
        "scope": "Selected GitHub releases and exact Docker Hub tags; metadata inspection only; no downloaded code is executed.",
        "limitations": [
            "A support-gap finding applies only to the inspected release artifact set or container tag, not all versions or source-build compatibility.",
            "Filename evidence verifies an advertised Linux Arm64 distribution, not binary contents, installation, security, or runtime compatibility.",
            "Unknown results are not unsupported. API errors, rate limits, missing metadata, ambiguous names and pagination caps are retained.",
            "Repository search is a bounded sample ranked by stars and configured topics. Seeds may include projects already present in the public catalog.",
            "Catalog URL matching is secondary and may miss aliases; no catalog match does not prove an untracked project.",
            "Docker Hub tags can move; timestamps and available digests are retained. No images are run or layers downloaded.",
            "Internal only: no public catalog changes, external publication, or maintainer contact.",
        ],
    }
    summary["selection"] = {
        "seeds": [
            {k: item[k] for k in ("source", "name", "tag") if k in item}
            for item in config.get("seeds", [])
            if isinstance(item, dict)
        ],
        "github_queries": config.get("discovery", {}).get("github_queries", []),
        "minimum_stars": config.get("discovery", {}).get("min_stars", 500),
        "source_records_examined": source_records_examined,
        "priority_policy": "Oldest due work first; configured seeds in order, then newly discovered repositories by GitHub stars. Pulls and stars are not combined.",
        "repository_release_selection": "First non-draft, non-prerelease in GitHub API order, within configured pagination limits",
        "registry_selection": "Configured exact Docker Hub image/tag seeds",
        "retained_queue_policy": "Previously queued candidates remain eligible until investigated or not due; changing seeds does not delete history",
    }
    summary["retained_findings"] = retained_findings
    from .report import write_reports

    write_reports(summary)
    latest = output_dir / "latest.json"
    temp = output_dir / f".latest-{run_id}.json"
    temp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(latest)
    db.execute(
        "UPDATE runs SET finished_at=?,summary=? WHERE id=?",
        (summary["finished_at"], json.dumps(summary), run_id),
    )
    db.commit()
    return summary
