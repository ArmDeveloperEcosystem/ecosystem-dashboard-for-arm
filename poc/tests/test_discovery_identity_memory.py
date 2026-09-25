"""Legacy .GIT aliases collapse active work while preserving dated observations."""

import json
from datetime import timedelta

import pytest

from poc.discovery.pipeline import (
    normalize_candidate,
    open_state,
    reconcile_candidate_aliases,
    run_pipeline,
)
from poc.tests.test_discovery_scheduling import NOW, Metadata, configure


@pytest.mark.parametrize(
    "name", ["OWNER/PROJECT.GIT", "owner/project.git", "Owner/Project"]
)
def test_github_aliases_have_one_canonical_identity(name):
    assert (
        normalize_candidate({"source": "github", "name": name})["id"]
        == "github:owner/project"
    )


@pytest.mark.parametrize("name", ["owner/.git", "owner/.GIT"])
def test_suffix_removal_cannot_produce_empty_repository(name):
    with pytest.raises(ValueError, match="nonempty"):
        normalize_candidate({"source": "github", "name": name})


def insert_unchecked(db, identity, name, *, first, due):
    db.execute(
        "INSERT INTO candidates(id,payload,first_seen,last_seen,next_check_at) VALUES (?,?,?,?,?)",
        (
            identity,
            json.dumps({"source": "github", "name": name, "id": identity}),
            first,
            first,
            due,
        ),
    )
    db.commit()


def relabel_as_legacy(db, old_id, alias_id, alias_name):
    """Build an actual pre-fix state without calling the corrected normalizer."""
    row = db.execute(
        "SELECT payload,last_result FROM candidates WHERE id=?", (old_id,)
    ).fetchone()
    payload = json.loads(row["payload"])
    payload.update(id=alias_id, name=alias_name)
    result = json.loads(row["last_result"])
    result.update(candidate_id=alias_id, name=alias_name)
    db.execute(
        "UPDATE candidates SET id=?,payload=?,last_result=? WHERE id=?",
        (alias_id, json.dumps(payload), json.dumps(result), old_id),
    )
    for obs in db.execute(
        "SELECT id,result FROM observations WHERE candidate_id=?", (old_id,)
    ).fetchall():
        value = json.loads(obs["result"])
        value.update(candidate_id=alias_id, name=alias_name)
        db.execute(
            "UPDATE observations SET candidate_id=?,result=? WHERE id=?",
            (alias_id, json.dumps(value), obs["id"]),
        )
    db.commit()


def test_unchecked_legacy_alias_is_admitted_once_and_mapping_survives_seed_upsert(
    tmp_path,
):
    out = tmp_path / "out"
    out.mkdir()
    with open_state(out / "discovery.sqlite3") as db:
        insert_unchecked(
            db,
            "github:owner/project.git",
            "owner/project.git",
            first="2026-09-01T00:00:00+00:00",
            due="2026-09-01T00:00:00+00:00",
        )
    cfg = configure(tmp_path, seeds=[{"source": "github", "name": "OWNER/PROJECT.GIT"}])
    first = run_pipeline(cfg, out, now=NOW, http=Metadata())
    assert first["counts"]["queued_total"] == 1
    assert first["counts"]["investigated"] == 1
    assert first["findings"][0]["first_seen"] == "2026-09-01T00:00:00+00:00"
    assert first["identity_aliases"] == [
        {"alias_id": "github:owner/project.git", "canonical_id": "github:owner/project"}
    ]
    second = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    assert second["identity_aliases"] == first["identity_aliases"]
    assert second["counts"]["investigated"] == 0
    assert len(second["retained_findings"]) == 1


def test_checked_alias_only_retains_original_observation_and_scheduling(tmp_path):
    cfg = configure(tmp_path, seeds=[{"source": "github", "name": "owner/project"}])
    out = tmp_path / "out"
    run_pipeline(cfg, out, now=NOW, http=Metadata())
    with open_state(out / "discovery.sqlite3") as db:
        relabel_as_legacy(
            db, "github:owner/project", "github:owner/project.git", "owner/project.git"
        )
        original = [tuple(row) for row in db.execute("SELECT * FROM observations")]
        old = dict(db.execute("SELECT * FROM candidates").fetchone())
    result = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    assert result["counts"]["investigated"] == 0
    assert result["retained_findings"][0]["candidate_id"] == "github:owner/project"
    assert result["retained_findings"][0]["historical_candidate_ids"] == [
        "github:owner/project.git"
    ]
    with open_state(out / "discovery.sqlite3") as db:
        assert [
            tuple(row) for row in db.execute("SELECT * FROM observations")
        ] == original
        canonical = dict(db.execute("SELECT * FROM candidates").fetchone())
        for key in ("first_seen", "checked_at", "next_check_at", "investigation_count"):
            assert canonical[key] == old[key]


def test_alias_collision_same_run_observations_unchanged_latest_evidence_and_due_preserved(
    tmp_path,
):
    cfg = configure(
        tmp_path,
        seeds=[
            {"source": "github", "name": name}
            for name in ("owner/project", "owner/other")
        ],
    )
    out = tmp_path / "out"
    run_pipeline(cfg, out, now=NOW, http=Metadata())
    with open_state(out / "discovery.sqlite3") as db:
        relabel_as_legacy(
            db, "github:owner/other", "github:owner/project.git", "owner/project.git"
        )
        db.execute(
            "UPDATE candidates SET next_check_at=?,last_seen=? WHERE id=?",
            (
                "2026-09-25T00:00:00+00:00",
                "2026-09-24T01:00:00+00:00",
                "github:owner/project.git",
            ),
        )
        db.execute(
            "UPDATE candidates SET next_check_at=?,first_seen=? WHERE id=?",
            (
                "2026-09-27T00:00:00+00:00",
                "2026-09-20T00:00:00+00:00",
                "github:owner/project",
            ),
        )
        db.commit()
        originals = [
            tuple(row) for row in db.execute("SELECT * FROM observations ORDER BY id")
        ]
        reconcile_candidate_aliases(db)
        once = [tuple(row) for row in db.execute("SELECT * FROM candidates")]
        reconcile_candidate_aliases(db)
        assert [tuple(row) for row in db.execute("SELECT * FROM candidates")] == once
        assert [
            tuple(row) for row in db.execute("SELECT * FROM observations ORDER BY id")
        ] == originals
        canonical = dict(db.execute("SELECT * FROM candidates").fetchone())
        assert canonical["investigation_count"] == 2
        assert canonical["next_check_at"] == "2026-09-25T00:00:00+00:00"
        assert canonical["first_seen"] == "2026-09-20T00:00:00+00:00"
        assert canonical["last_seen"] == "2026-09-24T01:00:00+00:00"
        assert json.loads(canonical["last_result"])["scope"].startswith(
            "owner/other:"
        )  # Preserve exact evidence scope, never relabel it.
    cfg = configure(tmp_path, seeds=[{"source": "github", "name": "OWNER/PROJECT.GIT"}])
    no_work = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    assert len(no_work["retained_findings"]) == len(no_work["saved_history"]) == 1
    assert no_work["counts"]["saved_observations"] == 2
    refreshed = run_pipeline(cfg, out, now=NOW + timedelta(days=2), http=Metadata())
    assert refreshed["counts"]["investigated"] == 1
    assert refreshed["findings"][0]["investigation_count"] == 3
    with open_state(out / "discovery.sqlite3") as db:
        assert [
            tuple(row)
            for row in db.execute("SELECT * FROM observations ORDER BY id LIMIT 2")
        ] == originals
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3


def test_alias_merge_prefers_newest_actual_observation_not_support_status(tmp_path):
    db = open_state(tmp_path / "state.sqlite3")
    insert_unchecked(
        db,
        "github:owner/project",
        "owner/project",
        first="2026-01-01",
        due="2026-02-01",
    )
    insert_unchecked(
        db,
        "github:owner/project.git",
        "owner/project.git",
        first="2026-01-02",
        due="2026-02-02",
    )
    for identity, status, checked in (
        ("github:owner/project", "supported", "2026-01-03"),
        ("github:owner/project.git", "unknown", "2026-01-04"),
    ):
        result = {
            "candidate_id": identity,
            "status": status,
            "scope": identity,
            "checked_at": checked,
        }
        db.execute(
            "UPDATE candidates SET checked_at=?,last_status=?,last_result=?,investigation_count=1 WHERE id=?",
            (checked, status, json.dumps(result), identity),
        )
    db.commit()
    reconcile_candidate_aliases(db)
    row = db.execute("SELECT * FROM candidates").fetchone()
    assert row["last_status"] == "unknown"
    assert json.loads(row["last_result"])["checked_at"] == "2026-01-04"
    db.close()


@pytest.mark.parametrize("checked", [False, True])
def test_invalid_legacy_identity_is_quarantined_without_poisoning_reports(
    tmp_path, monkeypatch, checked
):
    """Recreate the old suffix-before-lowercase admission, then upgrade its state."""
    from poc.discovery import pipeline
    from poc.discovery.http import CollectionError
    import time

    def legacy_normalize(value):
        # This is the historical normalization sequence that admitted owner/.GIT.
        name = value["name"].removesuffix(".git").lower()
        return {**value, "name": name, "id": "github:" + name}

    class MissingRepository(Metadata):
        def get(self, url, **kwargs):
            self.requests_used += 1
            self.calls.append(url)
            raise CollectionError("HTTP 404 from api.github.com/repos/owner/.git")

    cfg = configure(tmp_path, seeds=[{"source": "github", "name": "owner/.GIT"}])
    out = tmp_path / "out"
    old_http = MissingRepository()
    if not checked:
        old_http.started = time.monotonic() - 999
    with monkeypatch.context() as legacy:
        legacy.setattr(pipeline, "normalize_candidate", legacy_normalize)
        old = run_pipeline(cfg, out, now=NOW, http=old_http)
    assert old["counts"]["saved_observations"] == int(checked)
    with open_state(out / "discovery.sqlite3") as db:
        legacy_row = tuple(db.execute("SELECT * FROM candidates").fetchone())
        observations = [
            tuple(row) for row in db.execute("SELECT * FROM observations ORDER BY id")
        ]

    # Keep a currently invalid spelling in configuration too: it remains rejected
    # while valid new work and the legacy checked history can be published.
    cfg = configure(
        tmp_path,
        seeds=[
            {"source": "github", "name": "owner/.GIT"},
            {"source": "dockerhub", "name": "example/valid"},
        ],
    )
    valid_http = Metadata()
    upgraded = run_pipeline(cfg, out, now=NOW + timedelta(days=2), http=valid_http)
    assert [f["candidate_id"] for f in upgraded["findings"]] == [
        "dockerhub:example/valid:latest"
    ]
    assert all("owner/.git" not in url for url in valid_http.calls)
    assert upgraded["counts"]["stored_candidates"] == 2
    assert upgraded["counts"]["queued_total"] == 1
    assert upgraded["counts"]["quarantined_candidates"] == 1
    assert upgraded["counts"]["pending_investigation"] == 0
    assert upgraded["counts"]["saved_observations"] == int(checked) + 1
    assert upgraded["scheduling"]["due_total"] == 1
    assert upgraded["outcome"] == "degraded"
    assert upgraded["quarantined_candidates"][0]["candidate_id"] == "github:owner/.git"
    assert any(
        item["source"] == "identity_review" for item in upgraded["current_errors"]
    )
    assert any("nonempty" in skip["reason"] for skip in upgraded["skipped"])
    if checked:
        assert upgraded["retained_findings"][0]["candidate_id"] == "github:owner/.git"
    with open_state(out / "discovery.sqlite3") as db:
        assert (
            tuple(
                db.execute(
                    "SELECT * FROM candidates WHERE id='github:owner/.git'"
                ).fetchone()
            )
            == legacy_row
        )
        assert [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM observations ORDER BY id LIMIT ?", (len(observations),)
            )
        ] == observations

    # Removing its configuration seed does not hide the saved-state diagnostic,
    # and force-refresh never re-admits a quarantined identity.
    cfg = configure(tmp_path, seeds=[], force_refresh=True)
    repeated_http = Metadata()
    repeated = run_pipeline(cfg, out, now=NOW + timedelta(days=3), http=repeated_http)
    assert repeated["counts"]["investigated"] == 1
    assert all("owner/.git" not in url for url in repeated_http.calls)
    cfg = configure(tmp_path, seeds=[])
    no_work = run_pipeline(
        cfg, out, now=NOW + timedelta(days=3, hours=1), http=Metadata()
    )
    assert no_work["scheduling"]["status"] == "no_work"
    assert no_work["outcome"] == "degraded"
    assert no_work["quarantined_candidates"] == repeated["quarantined_candidates"]
    assert any(
        error["source"] == "identity_review" for error in no_work["current_errors"]
    )
    from pathlib import Path

    assert all(Path(path).exists() for path in no_work["report_paths"].values())
