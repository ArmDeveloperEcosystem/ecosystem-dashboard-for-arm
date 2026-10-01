"""Scheduler exit behavior and preflight must reflect the current run only."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

import pytest
import yaml

from poc.discovery import __main__ as cli
from poc.discovery.http import CollectionError
from poc.discovery.pipeline import run_pipeline


class FailedSource:
    requests_used = 0

    def get(self, *args, **kwargs):
        self.requests_used += 1
        raise CollectionError("HTTP 429 source quota exhausted")


@pytest.mark.parametrize("ai", [{"enabled": False}, {"enabled": True}])
def test_required_ai_fails_before_creating_state_or_collecting(
    tmp_path, monkeypatch, ai
):
    monkeypatch.delenv("ARM_DISCOVERY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ARM_DISCOVERY_MODEL", raising=False)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"ai_review": ai}))
    http = FailedSource()
    with pytest.raises(ValueError, match="AI review"):
        run_pipeline(config, tmp_path / "out", http=http, require_ai=True)
    assert http.requests_used == 0
    assert not (tmp_path / "out").exists()


def test_failed_current_source_has_degraded_outcome_and_published_reports(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("seeds:\n  - source: github\n    name: example/project\n")
    summary = run_pipeline(config, tmp_path / "out", http=FailedSource())
    assert summary["outcome"] == "degraded"
    assert summary["current_errors"][0]["source"] == "github"
    assert summary["findings"][0]["status"] == "unknown"
    assert all(Path(path).is_file() for path in summary["report_paths"].values())


def test_recovered_historical_failure_does_not_degrade_healthy_no_work_run(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("seeds: []\n")
    output = tmp_path / "out"
    run_pipeline(
        config,
        output,
        http=FailedSource(),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with sqlite3.connect(output / "discovery.sqlite3") as db:
        db.execute(
            "INSERT INTO runs(id,started_at,finished_at,summary) VALUES (?,?,?,?)",
            (
                "previous-failure",
                "2026-01-02",
                "2026-01-02",
                json.dumps({"status": "failed", "error": "Interrupted publication"}),
            ),
        )
    summary = run_pipeline(
        config,
        output,
        http=FailedSource(),
        now=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    assert summary["outcome"] == "completed"
    assert summary["current_errors"] == []
    assert any(error["source"] == "previous_run" for error in summary["failures"])


@pytest.mark.parametrize(
    "flags,errors,eligible,completed,expected",
    [
        ([], [{"source": "github"}], 0, 0, 0),
        (["--fail-on-errors"], [{"source": "github"}], 0, 0, 2),
        (["--fail-on-errors"], [], 0, 0, 0),
        (["--require-ai"], [], 2, 1, 2),
        (["--require-ai"], [], 2, 2, 0),
        (["--require-ai"], [], 0, 0, 0),
    ],
)
def test_cli_exit_after_reporting_matches_current_health(
    monkeypatch, capsys, flags, errors, eligible, completed, expected
):
    def run(*args, **kwargs):
        assert kwargs["require_ai"] is ("--require-ai" in flags)
        return {
            "run_id": "synthetic",
            "generated_at": "2026-09-24",
            "outcome": "degraded" if errors else "completed",
            "current_errors": errors,
            "counts": {},
            "report_paths": {},
            "state_path": "state",
            "ai_review": {"eligible": eligible, "completed": completed},
            "failures": [{"source": "previous_run", "reason": "Historical failure"}],
        }

    monkeypatch.setattr(cli, "run_pipeline", run)
    monkeypatch.setattr(sys, "argv", ["discovery", *flags])
    assert cli.main() == expected
    assert json.loads(capsys.readouterr().out)["run_id"] == "synthetic"


def test_word_retains_failed_ai_disclosure_on_historical_findings(tmp_path):
    from docx import Document
    from datetime import timedelta

    class PublicTag:
        requests_used = 0

        def get(self, url, **kwargs):
            self.requests_used += 1
            if "/tags/" in url:
                return {
                    "name": "v1",
                    "images": [{"os": "linux", "architecture": "arm64"}],
                }, {}
            return {"name": "tool", "namespace": "example", "is_private": False}, {}

    def unavailable(_):
        raise ValueError("Approved test provider unavailable")

    config = tmp_path / "config.yaml"
    config.write_text(
        "seeds:\n  - source: dockerhub\n    name: example/tool\n    tag: v1\n"
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    run_pipeline(
        config, tmp_path / "out", http=PublicTag(), now=now, reviewer=unavailable
    )
    summary = run_pipeline(
        config,
        tmp_path / "out",
        http=PublicTag(),
        now=now + timedelta(hours=1),
        reviewer=unavailable,
    )
    assert summary["counts"]["investigated"] == 0
    text = "\n".join(
        p.text for p in Document(summary["report_paths"]["docx"]).paragraphs
    )
    assert "AI interpretation: failed validation" in text
    assert "Approved test provider unavailable" in text
