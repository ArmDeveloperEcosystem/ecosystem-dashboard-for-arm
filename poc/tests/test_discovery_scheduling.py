"""Saved work must progress before bounded discovery spends shared resources."""

import base64
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from poc.discovery import __main__ as cli
from poc.discovery import pipeline
from poc.discovery.http import CollectionError

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Metadata:
    def __init__(self, rows=(), limit=50):
        self.rows = rows
        self.limit = limit
        self.requests_used = 0
        self.calls = []

    def get(self, url, **kwargs):
        if self.requests_used >= self.limit:
            raise CollectionError("Run request limit reached")
        self.requests_used += 1
        self.calls.append(url)
        if "/search/" in url:
            return {"items": list(self.rows)}, {}
        if "hub.docker.com" in url:
            if "/tags/" in url:
                return {"images": [{"os": "linux", "architecture": "arm64"}]}, {}
            return {"is_private": False}, {}
        if url.endswith("/releases"):
            return [], {}
        if url.endswith("/readme"):
            return {
                "encoding": "base64",
                "content": base64.b64encode(b"Linux project").decode(),
            }, {}
        return {"private": False, "visibility": "public"}, {}


def configure(path, **overrides):
    value = {
        "seeds": [
            {"source": "dockerhub", "name": "example/one"},
            {"source": "dockerhub", "name": "example/two"},
        ],
        "limits": {"oci_fallback": False},
        **overrides,
    }
    target = path / "config.yaml"
    target.write_text(yaml.safe_dump(value))
    return target


def test_two_request_reproduction_saved_candidate_precedes_empty_searches(tmp_path):
    cfg = configure(
        tmp_path, limits={"max_candidates": 1, "max_requests": 2, "oci_fallback": False}
    )
    first = pipeline.run_pipeline(
        cfg, tmp_path / "out", http=Metadata(limit=2), now=NOW
    )
    assert first["findings"][0]["candidate_id"] == "dockerhub:example/one:latest"
    data = yaml.safe_load(cfg.read_text())
    data["discovery"] = {"github_queries": ["topic:one", "topic:two"]}
    cfg.write_text(yaml.safe_dump(data))
    http = Metadata(limit=2)
    second = pipeline.run_pipeline(
        cfg, tmp_path / "out", http=http, now=NOW + timedelta(hours=1)
    )
    assert second["findings"][0]["candidate_id"] == "dockerhub:example/two:latest"
    assert len(http.calls) == 2 and all("hub.docker.com" in u for u in http.calls)
    assert second["scheduling"]["discovery_deferred"] is True
    assert second["counts"]["pending_investigation"] == 0
    assert second["outcome"] == "completed"
    assert second["current_errors"] == []


def test_backlog_rotates_discovery_gets_checkpoint_and_new_rows_persist(tmp_path):
    cfg = configure(
        tmp_path,
        seeds=[
            {"source": "dockerhub", "name": f"example/{name}"}
            for name in ("one", "two", "three")
        ],
        limits={"max_candidates": 1, "max_requests": 3, "oci_fallback": False},
        refresh_hours={"supported": 0},
        discovery={"github_queries": ["topic:test"]},
    )
    seen = []
    for day in range(3):
        http = Metadata(
            [{"full_name": "example/discovered", "stargazers_count": 100}], limit=3
        )
        summary = pipeline.run_pipeline(
            cfg, tmp_path / "out", http=http, now=NOW + timedelta(days=day)
        )
        seen.append(summary["findings"][0]["candidate_id"])
        assert len(http.calls) == 3 and "/search/" in http.calls[-1]
        assert summary["counts"]["investigated"] == 1
        assert summary["scheduling"]["status"] == "progress"
        assert summary["outcome"] == "completed"
    assert seen == [
        f"dockerhub:example/{name}:latest" for name in ("one", "two", "three")
    ]
    with sqlite3.connect(tmp_path / "out" / "discovery.sqlite3") as db:
        discovered = db.execute(
            "SELECT checked_at,investigation_count FROM candidates WHERE id='github:example/discovered'"
        ).fetchone()
        assert discovered == (None, 0)
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3


def test_fresh_bootstrap_six_seeds_then_two_discoveries_shared_budget(tmp_path):
    cfg = configure(
        tmp_path,
        seeds=[{"source": "dockerhub", "name": f"example/tool{i}"} for i in range(6)],
        discovery={"github_queries": ["topic:test"]},
    )
    http = Metadata(
        [
            {"full_name": "example/new-low", "stargazers_count": 50},
            {"full_name": "example/new-high", "stargazers_count": 100},
        ]
    )
    summary = pipeline.run_pipeline(cfg, tmp_path / "out", http=http, now=NOW)
    assert [f["candidate_id"] for f in summary["findings"]] == [
        *(f"dockerhub:example/tool{i}:latest" for i in range(6)),
        "github:example/new-high",
        "github:example/new-low",
    ]
    assert "/search/" in http.calls[2]
    assert summary["counts"]["investigated"] == 8
    assert summary["scheduling"]["due_at_start"] == 6
    assert summary["scheduling"]["due_total"] == 8
    assert summary["counts"]["requests"] == len(http.calls) == 19


@pytest.mark.parametrize("force", [False, True])
def test_checkpoint_not_repeated_with_force_zero_refresh_or_seed_aliases(
    tmp_path, force
):
    cfg = configure(
        tmp_path,
        seeds=[
            {"source": "github", "name": name}
            for name in ("OWNER/PROJECT.GIT", "owner/project", "owner/project.git")
        ],
        force_refresh=force,
        refresh_hours={"unknown": 0},
        discovery={"github_queries": ["topic:test"]},
    )
    for day in range(2):
        http = Metadata([{"full_name": "OWNER/PROJECT.GIT", "stargazers_count": 100}])
        summary = pipeline.run_pipeline(
            cfg, tmp_path / "out", http=http, now=NOW + timedelta(days=day)
        )
        assert summary["counts"]["investigated"] == 1
        assert summary["counts"]["queued_total"] == 1
        assert summary["findings"][0]["candidate_id"] == "github:owner/project"
        assert len(http.calls) == 4


def test_no_progress_is_degraded_and_preserves_due_fields_and_cli_health(
    tmp_path, monkeypatch, capsys
):
    cfg = configure(tmp_path)
    http = Metadata()
    http.started = time.monotonic() - 999
    summary = pipeline.run_pipeline(cfg, tmp_path / "out", http=http, now=NOW)
    assert http.calls == []
    assert summary["scheduling"]["status"] == "no_progress"
    assert summary["scheduling"]["deferred_due"] == 2
    assert summary["outcome"] == "degraded"
    assert summary["current_errors"][0]["source"] == "scheduler"
    with sqlite3.connect(tmp_path / "out" / "discovery.sqlite3") as db:
        assert (
            db.execute(
                "SELECT checked_at,investigation_count,next_check_at FROM candidates"
            ).fetchall()
            == [(None, 0, NOW.isoformat(timespec="seconds"))] * 2
        )
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **kw: summary)
    monkeypatch.setattr(sys, "argv", ["discovery", "--fail-on-errors"])
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["scheduling"]["status"] == "no_progress"


def test_discovery_only_exhaustion_keeps_new_scope_unchecked_and_degrades(tmp_path):
    cfg = configure(
        tmp_path,
        seeds=[],
        discovery={"github_queries": ["topic:test"]},
        limits={"max_requests": 1},
    )
    http = Metadata([{"full_name": "example/new", "stargazers_count": 100}], limit=1)
    summary = pipeline.run_pipeline(cfg, tmp_path / "out", http=http, now=NOW)
    assert summary["scheduling"]["status"] == "no_progress"
    assert summary["counts"]["pending_investigation"] == 1
    assert summary["counts"]["saved_observations"] == 0


def test_empty_and_not_due_are_healthy_no_work(tmp_path):
    cfg = configure(tmp_path)
    pipeline.run_pipeline(cfg, tmp_path / "out", http=Metadata(), now=NOW)
    result = pipeline.run_pipeline(
        cfg, tmp_path / "out", http=Metadata(), now=NOW + timedelta(hours=1)
    )
    assert result["scheduling"]["status"] == "no_work"
    assert result["current_errors"] == []
    assert result["counts"]["requests"] == 0
    empty_cfg = configure(tmp_path, seeds=[])
    empty = pipeline.run_pipeline(
        empty_cfg, tmp_path / "empty", http=Metadata(), now=NOW
    )
    assert (
        empty["scheduling"]["status"] == "no_work" and empty["outcome"] == "completed"
    )


def test_source_error_counts_as_attempt_and_remains_degraded(tmp_path):
    class Failed(Metadata):
        def get(self, url, **kwargs):
            self.requests_used += 1
            raise CollectionError("HTTP 429")

    result = pipeline.run_pipeline(
        configure(tmp_path), tmp_path / "out", http=Failed(), now=NOW
    )
    assert result["scheduling"]["status"] == "progress"
    assert result["scheduling"]["attempted"] == 2
    assert result["counts"]["unknown"] == 2
    assert result["outcome"] == "degraded"


def test_checkpoint_survives_discovery_crash_without_repeating_saved_check(tmp_path):
    class Crashing(Metadata):
        def get(self, url, **kwargs):
            if "/search/" in url:
                raise RuntimeError("Simulated process interruption after checkpoint")
            return super().get(url, **kwargs)

    cfg = configure(tmp_path, discovery={"github_queries": ["topic:test"]})
    with pytest.raises(RuntimeError, match="checkpoint"):
        pipeline.run_pipeline(cfg, tmp_path / "out", http=Crashing(), now=NOW)
    with sqlite3.connect(tmp_path / "out" / "discovery.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2
    recovered = pipeline.run_pipeline(
        cfg, tmp_path / "out", http=Metadata(), now=NOW + timedelta(hours=1)
    )
    assert [f["candidate_id"] for f in recovered["findings"]] == [
        "dockerhub:example/two:latest"
    ]
    assert recovered["counts"]["saved_observations"] == 2
