from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import yaml

from poc.discovery.pipeline import run_pipeline, catalog_identities
from poc.discovery.http import CollectionError


class FakeHTTP:
    def __init__(self, failure=False):
        self.requests_used = 0
        self.failure = failure

    def get(self, url, **kwargs):
        self.requests_used += 1
        if self.failure:
            raise CollectionError("HTTP 429 from hub.docker.com")
        return {
            "images": [
                {"os": "linux", "architecture": "amd64", "digest": "sha256:123"}
            ],
            "last_updated": "2026-09-01T00:00:00Z",
        }, {}


def config(tmp_path, **overrides):
    value = {
        "seeds": [{"source": "dockerhub", "name": "sample/tool", "tag": "v1"}],
        "limits": {"oci_fallback": False},
        **overrides,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(value))
    return path


def test_memory_refresh_and_catalog_are_orthogonal(tmp_path):
    path = config(tmp_path)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "id": "tool",
                        "metadata": {
                            "download_url": "https://hub.docker.com/r/sample/tool"
                        },
                    }
                ]
            }
        )
    )
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    first = run_pipeline(path, tmp_path / "output", catalog, now=now, http=FakeHTTP())
    f = first["findings"][0]
    assert f["status"] == "gap" and f["catalog_tracked"] is True
    assert f["investigated_before"] is False
    assert first["ai_review"]["status"] == "not_configured"
    assert all(Path(p).exists() for p in first["report_paths"].values())
    second_http = FakeHTTP()
    second = run_pipeline(
        path,
        tmp_path / "output",
        catalog,
        now=now + timedelta(hours=1),
        http=second_http,
    )
    assert second_http.requests_used == 0
    assert second["counts"]["investigated"] == 0
    assert second["counts"]["saved_observations"] == 1
    assert second["saved_history"][0]["status"] == "gap"
    assert second["retained_findings"][0]["historical"] is True
    assert second["retained_findings"][0]["checked_at"] == f["checked_at"]
    assert second["retained_findings"][0]["evidence"] == f["evidence"]
    third = run_pipeline(
        path, tmp_path / "output", catalog, now=now + timedelta(days=8), http=FakeHTTP()
    )
    assert third["findings"][0]["investigated_before"] is True
    assert third["findings"][0]["evidence_changed"] is False
    assert third["counts"]["newly_investigated"] == 0
    assert third["counts"]["saved_observations"] == 2
    assert "duplicate" in third["findings"][0]["recommended_action"]
    assert third["retained_findings"] == []


def test_repeat_run_retains_all_eight_prior_findings_without_new_counts(tmp_path):
    seeds = [{"source": "dockerhub", "name": f"sample/tool{i}"} for i in range(8)]
    path = config(tmp_path, seeds=seeds)
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    first = run_pipeline(path, tmp_path / "out", now=now, http=FakeHTTP())
    second = run_pipeline(
        path, tmp_path / "out", now=now + timedelta(hours=1), http=FakeHTTP()
    )
    assert len(first["findings"]) == 8
    assert second["findings"] == []
    assert len(second["retained_findings"]) == 8
    assert all(
        f["historical"] is True and f["checked_at"] == first["generated_at"]
        for f in second["retained_findings"]
    )
    assert (
        second["counts"]["investigated"]
        == second["counts"]["newly_investigated"]
        == second["counts"]["refreshed"]
        == second["counts"]["gap"]
        == 0
    )
    assert second["counts"]["saved_observations"] == 8
    assert all(h["evidence_url"] for h in second["saved_history"])


def test_failure_persists_unknown_then_recovers(tmp_path):
    path = config(tmp_path)
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    first = run_pipeline(path, tmp_path / "out", now=now, http=FakeHTTP(failure=True))
    assert first["findings"][0]["status"] == "unknown"
    assert first["failures"] and first["findings"][0]["catalog_tracked"] is None
    second = run_pipeline(
        path, tmp_path / "out", now=now + timedelta(days=2), http=FakeHTTP()
    )
    assert second["findings"][0]["status"] == "gap"
    assert second["findings"][0]["previous_status"] == "unknown"


def test_run_limit_retains_queued_candidates(tmp_path):
    seeds = [{"source": "dockerhub", "name": f"sample/tool{i}"} for i in range(3)]
    path = config(
        tmp_path, seeds=seeds, limits={"max_candidates": 1, "oci_fallback": False}
    )
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    first = run_pipeline(path, tmp_path / "out", now=now, http=FakeHTTP())
    assert first["counts"]["investigated"] == 1
    assert first["counts"]["queued_total"] == 3
    assert sum("candidate limit" in skip["reason"] for skip in first["skipped"]) == 2
    second = run_pipeline(
        path, tmp_path / "out", now=now + timedelta(hours=1), http=FakeHTTP()
    )
    assert second["findings"][0]["candidate_id"] != first["findings"][0]["candidate_id"]
    assert second["counts"]["saved_observations"] == 2


def test_ai_note_cannot_override_classification(tmp_path):
    def reviewer(value):
        ev = value["evidence"][0]
        return {
            "note": "Review this distribution.",
            "status": "supported",
            "citations": [{"url": ev["url"], "quote": "linux/amd64"}],
        }

    result = run_pipeline(
        config(tmp_path), tmp_path / "out", http=FakeHTTP(), reviewer=reviewer
    )
    assert result["findings"][0]["status"] == "gap"
    assert result["findings"][0]["ai_review"]["status"] == "completed"


def test_catalog_uses_repository_urls_not_names(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "title": "org/project",
                        "slug": "project",
                        "metadata": {
                            "download_url": "https://github.com/Real/Project.git/releases"
                        },
                    }
                ]
            }
        )
    )
    assert catalog_identities(path) == {"github:real/project"}


def test_requested_ai_without_credentials_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    result = run_pipeline(
        config(tmp_path, ai_review={"enabled": True}), tmp_path / "out", http=FakeHTTP()
    )
    assert result["ai_review"]["status"] == "not_configured"
    assert any(f["source"] == "ai_review" for f in result["failures"])
