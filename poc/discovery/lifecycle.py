"""Explicit, reversible investigation retirement without deleting evidence."""

from __future__ import annotations

import json

from .text import json_dumps

MAX_LIFECYCLE_ENTRIES = 100


def lifecycle_directives(config, normalize):
    """Reject ambiguous policy changes before opening or modifying saved state."""
    directives = {}
    for key in ("retired_candidates", "reactivated_candidates"):
        entries = config.get(key, [])
        if not isinstance(entries, list) or len(entries) > MAX_LIFECYCLE_ENTRIES:
            raise ValueError(
                f"{key} must be a list of at most {MAX_LIFECYCLE_ENTRIES} entries"
            )
        normalized = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {
                "source",
                "name",
                "tag",
                "reason",
            }:
                raise ValueError(
                    f"{key} entries allow source, name, tag and reason only"
                )
            if not isinstance(entry.get("source"), str) or not isinstance(
                entry.get("name"), str
            ):
                raise ValueError(f"{key} entries require source and name strings")  # noqa: TRY004 - configuration API uses ValueError
            source = entry["source"].lower()
            if source == "dockerhub" and not isinstance(entry.get("tag"), str):
                raise ValueError(
                    f"{key} Docker Hub entries require an explicit tag string"
                )
            if source == "github" and "tag" in entry:
                raise ValueError(f"{key} GitHub entries do not accept a tag")
            reason = entry.get("reason")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
                raise ValueError(
                    f"{key} entries require a nonempty reason up to 1000 characters"
                )
            candidate = normalize(entry)
            if candidate["id"] in normalized:
                raise ValueError(
                    f"{key} contains duplicate normalized candidate identities"
                )
            normalized[candidate["id"]] = candidate
        directives[key] = normalized
    if (
        directives["retired_candidates"].keys()
        & directives["reactivated_candidates"].keys()
    ):
        raise ValueError(
            "A candidate cannot be retired and reactivated in the same configuration"
        )
    return directives


def apply_lifecycle(db, directives, at):
    """Persist explicit changes; omitting a directive never resurrects saved work."""
    for key, action in (
        ("retired_candidates", "retired"),
        ("reactivated_candidates", "reactivated"),
    ):
        for identity, candidate in directives[key].items():
            event_action = action
            previous = db.execute(
                "SELECT * FROM candidate_retirements WHERE candidate_id=?", (identity,)
            ).fetchone()
            if action == "reactivated":
                if previous is None or previous["reactivated_at"] is not None:
                    continue
                db.execute(
                    "UPDATE candidate_retirements SET reactivated_at=? WHERE candidate_id=?",
                    (at, identity),
                )
            else:
                if previous is not None and previous["reactivated_at"] is None:
                    if json.loads(previous["payload"]) == candidate:
                        continue
                    # Keep the original retirement time when its explanation is amended.
                    db.execute(
                        "UPDATE candidate_retirements SET payload=? WHERE candidate_id=?",
                        (json_dumps(candidate), identity),
                    )
                    event_action = "retirement_reason_updated"
                else:
                    db.execute(
                        "INSERT INTO candidate_retirements(candidate_id,payload,retired_at,reactivated_at) VALUES (?,?,?,NULL) ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload,retired_at=excluded.retired_at,reactivated_at=NULL",
                        (identity, json_dumps(candidate), at),
                    )
            db.execute(
                "INSERT INTO candidate_retirement_events(candidate_id,action,changed_at,reason) VALUES (?,?,?,?)",
                (
                    identity,
                    event_action,
                    at,
                    json_dumps(candidate["reason"]),
                ),
            )
    db.commit()
    return {
        row[0]
        for row in db.execute(
            "SELECT candidate_id FROM candidate_retirements WHERE reactivated_at IS NULL"
        )
    }


def retirement_snapshot(db):
    """Return separately labelled evidence; a marker alone is never a finding."""
    retired = []
    for row in db.execute(
        "SELECT r.*,c.last_result FROM candidate_retirements r LEFT JOIN candidates c ON c.id=r.candidate_id WHERE r.reactivated_at IS NULL ORDER BY r.candidate_id"
    ):
        candidate = json.loads(row["payload"])
        retired.append(
            {
                **{
                    key: candidate[key]
                    for key in ("source", "name", "tag", "reason")
                    if key in candidate
                },
                "candidate_id": row["candidate_id"],
                "retired_at": row["retired_at"],
                "finding": json.loads(row["last_result"])
                if row["last_result"] is not None
                else None,
            }
        )
    events = [
        {**dict(row), "reason": json.loads(row["reason"])}
        for row in db.execute(
            "SELECT candidate_id,action,changed_at,reason FROM candidate_retirement_events ORDER BY id DESC LIMIT 100"
        )
    ]
    return retired, events
