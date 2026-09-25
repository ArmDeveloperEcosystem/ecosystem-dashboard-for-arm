"""Retired demo scopes stay auditable without resurfacing as current opportunities."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from poc.discovery.pipeline import open_state, run_pipeline
from poc.tests.test_discovery_identity_memory import relabel_as_legacy
from poc.tests.test_discovery_scheduling import NOW, Metadata, configure

LEGACY = {"source": "dockerhub", "name": "library/mysql", "tag": "5.7"}
CURRENT = {"source": "dockerhub", "name": "library/mysql", "tag": "latest"}
RETIRED = {
    **LEGACY,
    "reason": "Legacy regression fixture; assess the current published image.",
}


class CurrentAndLegacyMetadata(Metadata):
    def get(self, url, **kwargs):
        result, headers = super().get(url, **kwargs)
        if "/tags/5.7" in url:
            result = {"images": [{"os": "linux", "architecture": "amd64"}]}
        return result, headers


def observations(path):
    with open_state(path) as db:
        return [
            tuple(row) for row in db.execute("SELECT * FROM observations ORDER BY id")
        ]


def test_existing_legacy_gap_retires_without_history_loss_or_unrelated_queue_loss(
    tmp_path,
):
    other = {"source": "dockerhub", "name": "example/other"}
    cfg = configure(tmp_path, seeds=[LEGACY, other])
    out = tmp_path / "out"
    old = run_pipeline(cfg, out, now=NOW, http=CurrentAndLegacyMetadata())
    legacy_finding = old["findings"][0]
    assert legacy_finding["status"] == "gap"
    original_observations = observations(out / "discovery.sqlite3")

    cfg = configure(
        tmp_path, seeds=[CURRENT], retired_candidates=[RETIRED], force_refresh=True
    )
    http = CurrentAndLegacyMetadata()
    upgraded = run_pipeline(cfg, out, now=NOW + timedelta(days=8), http=http)
    assert {f["candidate_id"] for f in upgraded["findings"]} == {
        "dockerhub:library/mysql:latest",
        "dockerhub:example/other:latest",
    }
    assert upgraded["counts"]["gap"] == 0
    assert upgraded["counts"]["supported"] == 2
    assert upgraded["counts"]["queued_total"] == 2
    assert upgraded["counts"]["stored_candidates"] == 3
    assert upgraded["counts"]["retired_candidates"] == 1
    assert upgraded["counts"]["retired_observations"] == 1
    assert upgraded["counts"]["saved_observations"] == 4
    assert all("/tags/5.7" not in url for url in http.calls)
    for key in ("retained_findings", "saved_history", "queue"):
        assert all(
            row["candidate_id"] != "dockerhub:library/mysql:5.7"
            for row in upgraded[key]
        )
    retired = upgraded["retired_candidates"][0]
    assert retired["finding"] == legacy_finding
    assert retired["reason"] == RETIRED["reason"]
    assert retired["finding"]["checked_at"] == old["generated_at"]
    assert observations(out / "discovery.sqlite3")[:2] == original_observations
    assert (
        json.loads(Path(upgraded["report_paths"]["json"]).read_text())[
            "retired_candidates"
        ]
        == upgraded["retired_candidates"]
    )


def test_retirement_survives_omitted_config_and_force_refresh_repeated_seed(tmp_path):
    out = tmp_path / "out"
    cfg = configure(tmp_path, seeds=[LEGACY])
    run_pipeline(cfg, out, now=NOW, http=CurrentAndLegacyMetadata())
    cfg = configure(tmp_path, seeds=[], retired_candidates=[RETIRED])
    retired = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    cfg = configure(tmp_path, seeds=[LEGACY], force_refresh=True)
    http = Metadata()
    result = run_pipeline(cfg, out, now=NOW + timedelta(days=100), http=http)
    assert http.calls == []
    assert (
        result["findings"]
        == result["retained_findings"]
        == result["saved_history"]
        == []
    )
    assert result["retired_candidates"] == retired["retired_candidates"]
    assert result["retirement_events"] == retired["retirement_events"]
    assert result["counts"]["queued_total"] == 0
    assert result["scheduling"]["status"] == "no_work"


def test_marker_only_retirement_is_not_a_finding_or_fake_investigation(tmp_path):
    cfg = configure(tmp_path, seeds=[CURRENT], retired_candidates=[RETIRED])
    out = tmp_path / "out"
    result = run_pipeline(cfg, out, now=NOW, http=Metadata())
    assert result["counts"]["supported"] == result["counts"]["investigated"] == 1
    assert (
        result["counts"]["stored_candidates"] == result["counts"]["queued_total"] == 1
    )
    assert result["counts"]["retired_candidates"] == 1
    assert result["counts"]["retired_observations"] == 0
    assert result["retired_candidates"][0]["finding"] is None
    assert result["counts"]["saved_observations"] == 1


def test_retiring_old_tag_does_not_hide_a_real_current_gap_for_same_image(tmp_path):
    class GapCurrentMetadata(CurrentAndLegacyMetadata):
        def get(self, url, **kwargs):
            result, headers = super().get(url, **kwargs)
            if "/tags/latest" in url:
                result = {"images": [{"os": "linux", "architecture": "amd64"}]}
            return result, headers

    cfg = configure(tmp_path, seeds=[LEGACY])
    out = tmp_path / "out"
    run_pipeline(cfg, out, now=NOW, http=CurrentAndLegacyMetadata())
    cfg = configure(tmp_path, seeds=[CURRENT], retired_candidates=[RETIRED])
    result = run_pipeline(
        cfg, out, now=NOW + timedelta(hours=1), http=GapCurrentMetadata()
    )
    assert result["counts"]["gap"] == 1
    assert result["counts"]["investigated"] == 1
    assert result["findings"][0]["candidate_id"] == "dockerhub:library/mysql:latest"
    assert result["findings"][0]["status"] == "gap"
    assert result["retired_candidates"][0]["finding"]["status"] == "gap"
    assert (
        result["retired_candidates"][0]["candidate_id"] == "dockerhub:library/mysql:5.7"
    )


def test_unchecked_retired_candidate_leaves_active_queue_without_deleting_row(tmp_path):
    cfg = configure(
        tmp_path,
        seeds=[CURRENT, LEGACY],
        limits={"max_candidates": 1, "oci_fallback": False},
    )
    out = tmp_path / "out"
    initial = run_pipeline(cfg, out, now=NOW, http=Metadata())
    assert initial["counts"]["pending_investigation"] == 1
    cfg = configure(tmp_path, seeds=[CURRENT], retired_candidates=[RETIRED])
    result = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    assert result["queue"] == []
    assert result["counts"]["pending_investigation"] == 0
    assert result["counts"]["stored_candidates"] == 2
    assert result["retired_candidates"][0]["finding"] is None
    with open_state(out / "discovery.sqlite3") as db:
        row = db.execute(
            "SELECT checked_at,investigation_count FROM candidates WHERE id=?",
            ("dockerhub:library/mysql:5.7",),
        ).fetchone()
        assert tuple(row) == (None, 0)


def test_explicit_reactivation_is_reversible_idempotent_and_respects_due_dates(
    tmp_path,
):
    cfg = configure(tmp_path, seeds=[LEGACY])
    out = tmp_path / "out"
    initial = run_pipeline(cfg, out, now=NOW, http=CurrentAndLegacyMetadata())
    cfg = configure(tmp_path, seeds=[], retired_candidates=[RETIRED])
    run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    reactivation = {
        **LEGACY,
        "reason": "Explicit historical regression investigation requested.",
    }
    cfg = configure(tmp_path, seeds=[], reactivated_candidates=[reactivation])
    activated = run_pipeline(cfg, out, now=NOW + timedelta(hours=2), http=Metadata())
    assert activated["retired_candidates"] == []
    assert activated["counts"]["investigated"] == 0
    assert activated["retained_findings"][0]["checked_at"] == initial["generated_at"]
    assert (
        activated["retained_findings"][0]["next_check_at"]
        == initial["findings"][0]["next_check_at"]
    )
    assert [e["action"] for e in activated["retirement_events"]] == [
        "reactivated",
        "retired",
    ]
    repeated = run_pipeline(cfg, out, now=NOW + timedelta(hours=3), http=Metadata())
    assert repeated["retirement_events"] == activated["retirement_events"]
    cfg = configure(
        tmp_path, seeds=[], reactivated_candidates=[reactivation], force_refresh=True
    )
    checked = run_pipeline(
        cfg, out, now=NOW + timedelta(hours=4), http=CurrentAndLegacyMetadata()
    )
    assert checked["counts"]["refreshed"] == 1
    assert checked["findings"][0]["investigation_count"] == 2
    cfg = configure(tmp_path, seeds=[], retired_candidates=[RETIRED])
    retired_again = run_pipeline(
        cfg, out, now=NOW + timedelta(hours=5), http=Metadata()
    )
    assert (
        retired_again["retired_candidates"][0]["retired_at"]
        == retired_again["generated_at"]
    )
    assert len(retired_again["retirement_events"]) == 3


def test_retirement_reason_update_preserves_first_retirement_and_raw_unicode(tmp_path):
    out = tmp_path / "out"
    cfg = configure(tmp_path, seeds=[], retired_candidates=[RETIRED])
    first = run_pipeline(cfg, out, now=NOW, http=Metadata())
    cfg = configure(
        tmp_path,
        seeds=[],
        retired_candidates=[{**RETIRED, "reason": "Updated \uffff explanation \ud800"}],
    )
    second = run_pipeline(cfg, out, now=NOW + timedelta(hours=1), http=Metadata())
    assert second["retired_candidates"][0]["retired_at"] == first["generated_at"]
    assert (
        second["retired_candidates"][0]["reason"] == "Updated \uffff explanation \ud800"
    )
    assert second["retirement_events"][0]["action"] == "retirement_reason_updated"
    repeated = run_pipeline(cfg, out, now=NOW + timedelta(hours=2), http=Metadata())
    assert repeated["retirement_events"] == second["retirement_events"]


def test_retired_alias_blocks_rediscovery_preserves_original_observation(tmp_path):
    cfg = configure(tmp_path, seeds=[{"source": "github", "name": "owner/project"}])
    out = tmp_path / "out"
    run_pipeline(cfg, out, now=NOW, http=Metadata())
    with open_state(out / "discovery.sqlite3") as db:
        relabel_as_legacy(
            db, "github:owner/project", "github:owner/project.git", "owner/project.git"
        )
    original = observations(out / "discovery.sqlite3")
    cfg = configure(
        tmp_path,
        seeds=[],
        retired_candidates=[
            {
                "source": "github",
                "name": "OWNER/PROJECT.GIT",
                "reason": "Superseded investigation scope.",
            }
        ],
        discovery={"github_queries": ["topic:test"]},
    )
    http = Metadata([{"full_name": "OWNER/PROJECT.GIT", "stargazers_count": 100}])
    result = run_pipeline(cfg, out, now=NOW + timedelta(days=8), http=http)
    assert len(http.calls) == 1 and "/search/" in http.calls[0]
    assert result["findings"] == result["retained_findings"] == result["queue"] == []
    assert result["counts"]["retired_observations"] == 1
    assert result["retired_candidates"][0]["candidate_id"] == "github:owner/project"
    assert observations(out / "discovery.sqlite3") == original


def test_retiring_unseen_scope_blocks_future_discovery_without_adding_candidate(
    tmp_path,
):
    cfg = configure(
        tmp_path,
        seeds=[],
        retired_candidates=[
            {
                "source": "github",
                "name": "owner/project",
                "reason": "Already investigated outside this queue.",
            }
        ],
        discovery={"github_queries": ["topic:test"]},
    )
    result = run_pipeline(
        cfg,
        tmp_path / "out",
        now=NOW,
        http=Metadata([{"full_name": "owner/project", "stargazers_count": 100}]),
    )
    assert result["counts"]["stored_candidates"] == 0
    assert result["counts"]["saved_observations"] == 0
    assert result["selection"]["source_candidates_selected"] == 0
    assert result["retired_candidates"][0]["finding"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"retired_candidates": None},
        {"reactivated_candidates": {}},
        {"retired_candidates": [None]},
        {"retired_candidates": [{**RETIRED, "unexpected": True}]},
        {"retired_candidates": [{**LEGACY, "reason": ""}]},
        {"retired_candidates": [{**LEGACY, "reason": " "}]},
        {"retired_candidates": [{**LEGACY, "reason": "x" * 1001}]},
        {"reactivated_candidates": [LEGACY]},
        {
            "retired_candidates": [
                {
                    "source": "dockerhub",
                    "name": "library/mysql",
                    "reason": "Exact tag missing.",
                }
            ]
        },
        {"retired_candidates": [{**RETIRED, "tag": 5.7}]},
        {"retired_candidates": [{**RETIRED, "tag": ""}]},
        {
            "retired_candidates": [
                {
                    "source": "github",
                    "name": "owner/project",
                    "tag": "latest",
                    "reason": "Invalid GitHub tag.",
                }
            ]
        },
        {"retired_candidates": [RETIRED, {**RETIRED, "name": "LIBRARY/MYSQL"}]},
        {"retired_candidates": [RETIRED], "reactivated_candidates": [RETIRED]},
        {"retired_candidates": [RETIRED] * 101},
        {"reactivated_candidates": [RETIRED] * 101},
    ],
)
def test_ambiguous_or_unbounded_policy_rejected_before_state_creation(
    tmp_path, overrides
):
    cfg = configure(tmp_path, **overrides)
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        run_pipeline(cfg, out, now=NOW, http=Metadata())
    assert not out.exists()
