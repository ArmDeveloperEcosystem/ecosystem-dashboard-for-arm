"""Persistent bounded discovery, independent of public catalog publishing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
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


def normalize_candidate(value):
    source = value.get("source", "github").lower()
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
    text = Path(path).read_text(encoding="utf-8")
    document = (
        json.loads(text) if Path(path).suffix == ".json" else yaml.safe_load(text)
    )
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
    config_path, output_dir, catalog_path=None, *, http=None, now=None, reviewer=None
):
    """Collect one bounded run and return its JSON-serializable summary and paths.

    Injectable HTTP and reviewer objects support offline tests and optional AI.
    The public catalog is read only. State and outputs are internal local files.
    """
    config_path, output_dir = Path(config_path).resolve(), Path(output_dir).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    limits = {**DEFAULT_LIMITS, **config.get("limits", {})}
    for key, value in limits.items():
        if key != "oci_fallback" and (
            not isinstance(value, (int, float)) or value <= 0
        ):
            raise ValueError(f"limits.{key} must be positive")
    limits = {
        k: int(v) if k not in {"timeout_seconds", "max_seconds", "oci_fallback"} else v
        for k, v in limits.items()
    }
    refresh = {
        "supported": 168,
        "gap": 168,
        "unknown": 24,
        **config.get("refresh_hours", {}),
    }
    if any(not isinstance(x, (int, float)) or x < 0 for x in refresh.values()):
        raise ValueError("Refresh intervals must be nonnegative hours")
    now = now or utcnow()
    at, run_id = (
        timestamp(now),
        now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(config.get("state_path") or output_dir / "discovery.sqlite3")
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    db = open_state(state_path)
    # Expiring DB lease blocks concurrent crawls sharing state without holding a network transaction.
    lock_time = utcnow()
    db.execute("BEGIN IMMEDIATE")
    lock = db.execute("SELECT * FROM pipeline_lock WHERE id=1").fetchone()
    if lock and lock["expires_at"] > timestamp(lock_time):
        db.rollback()
        db.close()
        raise RuntimeError("A discovery run is already active for this state database")
    db.execute(
        "INSERT OR REPLACE INTO pipeline_lock VALUES (1,?,?)",
        (run_id, timestamp(lock_time + timedelta(seconds=limits["max_seconds"] + 120))),
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
    finally:
        db.execute("DELETE FROM pipeline_lock WHERE owner=?", (run_id,))
        db.commit()
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
    discovered, search_failures, search_skips = discover_github(
        http, config.get("discovery", {}), limits
    )
    failures.extend(search_failures)
    skipped.extend(search_skips)
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
            else "Selected seed candidate or retained investigation queue"
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
        if reviewer and result["evidence"]:
            try:
                result["ai_review"] = review_evidence(result, reviewer)
            except Exception as exc:
                result["ai_review"] = {
                    "status": "failed_validation",
                    "reason": str(exc)[:500],
                }
                failures.append(
                    {
                        "candidate_id": candidate["id"],
                        "source": "ai_review",
                        "reason": str(exc)[:500],
                    }
                )
        else:
            result["ai_review"] = {
                "status": "not_configured" if reviewer is None else "no_evidence"
            }
        next_check = timestamp(now + timedelta(hours=refresh[result["status"]]))
        result["next_check_at"] = next_check
        fingerprint = hashlib.sha256(
            json.dumps(
                {k: result[k] for k in ("status", "scope", "evidence")}, sort_keys=True
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
        "catalog_comparison": {"status": catalog_state, "identity_count": len(tracked)},
        "ai_review": {
            "status": "configured" if reviewer else "not_configured",
            "completed": sum(f["ai_review"]["status"] == "completed" for f in findings),
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
