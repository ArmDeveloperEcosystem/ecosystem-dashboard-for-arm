"""Acceptance evidence must include real fresh work, not a successful empty batch."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from poc.discovery.deploy.verify_acceptance import assess, main

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


@pytest.fixture
def acceptance_report():
    at = NOW.isoformat()
    url = "https://hub.docker.com/v2/repositories/example/tool/tags/latest"
    return {
        "run_id": "controlled-acceptance-fixture",
        "status": "completed",
        "outcome": "completed",
        "current_errors": [],
        "generated_at": at,
        "counts": {"investigated": 1, "supported": 1, "gap": 0, "unknown": 0},
        "findings": [
            {
                "candidate_id": "dockerhub:example/tool:latest",
                "status": "supported",
                "scope": "Current image, advertised platform only",
                "checked_at": at,
                "evidence": [
                    {
                        "kind": "dockerhub_tag_platforms",
                        "url": url,
                        "excerpt": "linux/arm64",
                    }
                ],
                "ai_review": {
                    "status": "completed",
                    "note": "Advertised platform only; runtime remains untested.",
                    "citations": [{"url": url, "quote": "linux/arm64"}],
                },
            }
        ],
        "ai_review": {
            "status": "configured",
            "requested": True,
            "eligible": 1,
            "completed": 1,
        },
    }


def test_nonempty_cited_run_passes_consistency_without_promising_a_gap(
    acceptance_report,
):
    assert assess(acceptance_report, now=NOW) == []
    assert acceptance_report["counts"]["gap"] == 0


def test_history_and_retirement_do_not_substitute_for_fresh_work(acceptance_report):
    prior = copy.deepcopy(acceptance_report["findings"])
    acceptance_report.update(
        findings=[], retained_findings=prior, retired_candidates=[{"finding": prior[0]}]
    )
    acceptance_report["counts"] = dict.fromkeys(
        ("investigated", "supported", "gap", "unknown"), 0
    )
    acceptance_report["ai_review"].update(eligible=0, completed=0)
    errors = assess(acceptance_report, now=NOW)
    assert any("Insufficient current findings" in error for error in errors)
    assert any("No evidence-bearing" in error for error in errors)


def test_metadata_only_requires_explicit_mode_and_does_not_prove_ai(acceptance_report):
    acceptance_report["findings"][0]["ai_review"] = {"status": "not_configured"}
    acceptance_report["ai_review"] = {
        "status": "not_configured",
        "requested": False,
        "eligible": 1,
        "completed": 0,
    }
    assert assess(acceptance_report, mode="metadata", now=NOW) == []
    assert assess(acceptance_report, now=NOW)


@pytest.mark.parametrize("delta", [timedelta(hours=25), timedelta(seconds=-1)])
def test_old_or_future_observation_cannot_pass_acceptance(acceptance_report, delta):
    acceptance_report["generated_at"] = (NOW - delta).isoformat()
    assert any("age limit" in error for error in assess(acceptance_report, now=NOW))


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "degraded"),
        ("status", "interrupted"),
        ("current_errors", [{"reason": "Source failed"}]),
        ("current_errors", None),
        ("run_id", None),
        ("counts", {}),
        ("findings", None),
        ("generated_at", "2026-09-25T00:00:00"),
    ],
)
def test_unhealthy_or_malformed_run_rejected(acceptance_report, field, value):
    acceptance_report[field] = value
    assert assess(acceptance_report, now=NOW)


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_quote",
        "bad_url",
        "empty_note",
        "missing_review",
        "bad_evidence",
        "unsupported_without_evidence",
        "old_date",
        "historical",
        "duplicate",
        "bad_count",
        "bool_count",
        "too_few",
        "phantom_ai",
    ],
)
def test_false_acceptance_evidence_rejected(acceptance_report, mutation):
    report = acceptance_report
    finding = report["findings"][0]
    if mutation == "bad_quote":
        finding["ai_review"]["citations"][0]["quote"] = "invented support"
    elif mutation == "bad_url":
        finding["ai_review"]["citations"][0]["url"] = "https://example.org/uncollected"
    elif mutation == "empty_note":
        finding["ai_review"]["note"] = ""
    elif mutation == "missing_review":
        finding["ai_review"] = {"status": "budget_exhausted"}
    elif mutation == "bad_evidence":
        finding["evidence"] = [None]
    elif mutation == "unsupported_without_evidence":
        finding["evidence"] = []
    elif mutation == "old_date":
        finding["checked_at"] = (NOW - timedelta(days=1)).isoformat()
    elif mutation == "historical":
        finding["historical"] = True
    elif mutation == "duplicate":
        report["findings"].append(copy.deepcopy(finding))
    elif mutation == "bad_count":
        report["ai_review"]["completed"] = 0
    elif mutation == "bool_count":
        report["counts"]["investigated"] = True
    elif mutation == "too_few":
        assert assess(report, minimum_findings=8, now=NOW)
        return
    elif mutation == "phantom_ai":
        finding["status"] = "unknown"
        finding["evidence"] = []
        report["counts"].update(unknown=1, supported=0)
        report["ai_review"]["eligible"] = 0
    assert assess(report, now=NOW)


def test_cli_is_read_only_and_never_claims_production_or_live_provider_approval(
    tmp_path, acceptance_report, capsys
):
    now = datetime.now(timezone.utc).isoformat()
    acceptance_report["generated_at"] = now
    acceptance_report["findings"][0]["checked_at"] = now
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps(acceptance_report))
    before = path.read_bytes()
    assert main([str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["automated_result"] == "pass"
    assert result["production_approval"] == "not_established"
    assert "live-call provenance" in result["limitations"]
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_unreadable_report_has_no_false_success(tmp_path, capsys):
    assert main([str(tmp_path / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().out)["automated_result"] == "fail"


@pytest.mark.parametrize("content", ["[]", "{", "null"])
def test_cli_malformed_input_is_reported(tmp_path, capsys, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    assert main([str(path)]) in (1, 2)
    assert (
        json.loads(capsys.readouterr().out)["production_approval"] == "not_established"
    )
