"""Independent bounded acceptance cases for the internal opportunity report.

All source responses and AI reviews are controlled fixtures. These tests verify
evidence boundaries and durable reporting, not live-provider or runtime support.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest
import yaml

from poc.discovery import report
from poc.discovery.http import CollectionError
from poc.discovery.pipeline import run_pipeline


START = datetime(2026, 9, 24, tzinfo=timezone.utc)
REPOSITORY = "https://api.github.com/repos/example/tool"
ASSETS = REPOSITORY + "/releases/17/assets"


def write_config(path, seeds):
    path.write_text(
        yaml.safe_dump({"seeds": seeds, "limits": {"oci_fallback": False}}),
        encoding="utf-8",
    )
    return path


def image_seed(tag):
    return {"source": "dockerhub", "name": "sample/tool", "tag": tag}


class RegistryMetadata:
    def __init__(self, platforms_by_tag):
        self.platforms_by_tag = platforms_by_tag
        self.requests_used = 0

    def get(self, url, **kwargs):
        self.requests_used += 1
        if "/tags/" in url:
            tag = url.rsplit("/", 1)[1]
            return {
                "images": self.platforms_by_tag[tag],
                "last_updated": "2026-09-23T00:00:00Z",
            }, {}
        # Optional repository popularity must not affect architecture verdicts.
        return {"pull_count": 12, "star_count": 3}, {}


class RepositoryMetadata:
    def __init__(self, link, visibility=None):
        self.link = link
        self.visibility = (
            {"private": False, "visibility": "public"}
            if visibility is None
            else visibility
        )
        self.requests_used = 0
        self.urls = []

    def get(self, url, **kwargs):
        self.requests_used += 1
        self.urls.append(url)
        if url == REPOSITORY:
            return {"stargazers_count": 25, **self.visibility}, {}
        if url == REPOSITORY + "/releases/latest":
            return {"id": 17, "tag_name": "v1", "draft": False, "prerelease": False}, {}
        if url == ASSETS:
            return [{"name": "tool-linux-amd64.tar.gz", "state": "uploaded"}], {
                "Link": self.link
            }
        if url == ASSETS + "?page=2":
            return [{"name": "tool-linux-arm64.tar.gz", "state": "uploaded"}], {}
        if url == REPOSITORY + "/readme":
            return {"encoding": "base64", "content": ""}, {}
        raise AssertionError(f"Unplanned source request: {url}")


@pytest.mark.parametrize(
    "parameters",
    ['rel="next"', "rel=next", 'type="application/json"; rel="next"'],
)
def test_late_arm64_asset_is_not_misreported_as_a_gap(tmp_path, parameters):
    config = write_config(
        tmp_path / "config.yaml", [{"source": "github", "name": "example/tool"}]
    )
    http = RepositoryMetadata(f"<{ASSETS}?page=2>; {parameters}")
    summary = run_pipeline(config, tmp_path / "out", now=START, http=http)
    finding = summary["findings"][0]
    assert finding["status"] == "supported"
    assert finding["metadata"]["asset_inventory_complete"] is True
    assert ASSETS + "?page=2" in http.urls
    assert "tool-linux-arm64.tar.gz" in finding["scope"]


def test_unparseable_next_page_is_incomplete_evidence(tmp_path):
    config = write_config(
        tmp_path / "config.yaml", [{"source": "github", "name": "example/tool"}]
    )
    # A page link with no relation cannot establish whether more assets exist.
    http = RepositoryMetadata(f'<{ASSETS}?page=2>; title="more assets"')
    summary = run_pipeline(config, tmp_path / "out", now=START, http=http)
    finding = summary["findings"][0]
    assert finding["status"] == "unknown"
    assert finding["metadata"]["asset_inventory_complete"] is False
    assert finding["failures"]


@pytest.mark.parametrize("visibility", ["private", "internal"])
def test_nonpublic_repository_is_not_collected_or_sent_to_ai(tmp_path, visibility):
    config = write_config(
        tmp_path / "config.yaml", [{"source": "github", "name": "example/tool"}]
    )
    http = RepositoryMetadata("", {"private": True, "visibility": visibility})
    reviews = []

    def reviewer(evidence):
        reviews.append(evidence)
        raise AssertionError("Nonpublic source evidence must not reach an AI reviewer")

    summary = run_pipeline(
        config, tmp_path / "out", now=START, http=http, reviewer=reviewer
    )
    finding = summary["findings"][0]
    assert finding["status"] == "unknown"
    assert finding["evidence"] == []
    assert http.urls == [REPOSITORY]
    assert not reviews
    assert summary["failures"]


def test_cataloged_image_tags_keep_independent_distribution_verdicts(tmp_path):
    config = write_config(tmp_path / "config.yaml", [image_seed("old"), image_seed("new")])
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"packages": [{"download_url": "https://hub.docker.com/r/sample/tool"}]}),
        encoding="utf-8",
    )
    http = RegistryMetadata(
        {
            "old": [{"os": "linux", "architecture": "amd64"}],
            "new": [{"os": "linux", "architecture": "arm64"}],
        }
    )
    summary = run_pipeline(config, tmp_path / "out", catalog, now=START, http=http)
    findings = {finding["metadata"]["tag"]: finding for finding in summary["findings"]}
    assert findings["old"]["status"] == "gap"
    assert findings["new"]["status"] == "supported"
    assert all(finding["catalog_tracked"] is True for finding in findings.values())
    assert findings["old"]["candidate_id"] != findings["new"]["candidate_id"]
    assert all(f"sample/tool:{tag}" in finding["scope"] for tag, finding in findings.items())


@pytest.mark.parametrize("bad_citation", ["url", "quote"])
@pytest.mark.parametrize("architecture,expected", [("amd64", "gap"), ("unknown", "unknown")])
def test_invalid_ai_citations_cannot_override_or_contaminate_the_report(
    tmp_path, bad_citation, architecture, expected
):
    config = write_config(tmp_path / "config.yaml", [image_seed("v1")])
    http = RegistryMetadata({"v1": [{"os": "linux", "architecture": architecture}]})

    def reviewer(evidence):
        assert evidence["deterministic_status"] == expected
        source = evidence["evidence"][0]
        return {
            "status": "supported",
            "note": "UNVERIFIED-OVERRIDE-NOTE",
            "citations": [{
                "url": "https://invented.example/evidence" if bad_citation == "url" else source["url"],
                "quote": "linux/arm64" if bad_citation == "quote" else source["excerpt"],
            }],
        }

    summary = run_pipeline(config, tmp_path / "out", now=START, http=http, reviewer=reviewer)
    finding = summary["findings"][0]
    assert finding["status"] == expected
    assert finding["ai_review"]["status"] == "failed_validation"
    assert "note" not in finding["ai_review"]
    assert any(issue["source"] == "ai_review" for issue in summary["failures"])
    exported = Path(summary["report_paths"]["json"]).read_text(encoding="utf-8")
    assert "UNVERIFIED-OVERRIDE-NOTE" not in exported
    assert json.loads(exported)["findings"][0]["status"] == expected


def test_failed_report_preserves_latest_and_committed_observations(tmp_path, monkeypatch):
    output = tmp_path / "out"
    config = write_config(tmp_path / "config.yaml", [image_seed("old")])
    initial = run_pipeline(
        config,
        output,
        now=START,
        http=RegistryMetadata({"old": [{"os": "linux", "architecture": "arm64"}]}),
    )
    latest_before = (output / "latest.json").read_bytes()
    artifacts_before = {path: Path(path).read_bytes() for path in initial["report_paths"].values()}
    write_config(config, [image_seed("new")])
    partial_reports = []

    def fail_report(summary):
        partial = Path(summary["report_paths"]["json"])
        partial.write_text(json.dumps({"run_id": summary["run_id"], "partial": True}))
        partial_reports.append(partial)
        raise OSError("acceptance report writer failure")

    with monkeypatch.context() as patch:
        patch.setattr(report, "write_reports", fail_report)
        with pytest.raises(OSError, match="acceptance report writer failure"):
            run_pipeline(
                config,
                output,
                now=START + timedelta(hours=1),
                http=RegistryMetadata({"new": [{"os": "linux", "architecture": "amd64"}]}),
            )

    assert partial_reports and json.loads(partial_reports[0].read_text())["partial"] is True
    assert (output / "latest.json").read_bytes() == latest_before
    assert all(Path(path).read_bytes() == content for path, content in artifacts_before.items())
    with sqlite3.connect(initial["state_path"]) as state:
        state.row_factory = sqlite3.Row
        failed = state.execute("SELECT * FROM runs WHERE id != ?", (initial["run_id"],)).fetchone()
        assert failed["finished_at"] is not None
        failure = json.loads(failed["summary"])
        assert failure["status"] == "failed"
        assert "acceptance report writer failure" in failure["error"]
        stored = {
            row["candidate_id"]: json.loads(row["result"])
            for row in state.execute("SELECT candidate_id,result FROM observations")
        }
        assert len(stored) == 2

    # Successful retry proves the failure also releases the state lock. Neither
    # already-committed observation needs collecting again before it is due.
    http = RegistryMetadata({})
    recovered = run_pipeline(config, output, now=START + timedelta(hours=2), http=http)
    assert http.requests_used == 0
    assert recovered["counts"]["investigated"] == 0
    assert recovered["counts"]["saved_observations"] == 2
    assert len(recovered["retained_findings"]) == 2
    for finding in recovered["retained_findings"]:
        assert finding == {**stored[finding["candidate_id"]], "historical": True}
    assert any(
        "acceptance report writer failure" in issue["reason"]
        for issue in recovered["failures"]
    )
    assert json.loads((output / "latest.json").read_text())["run_id"] == recovered["run_id"]


class DiscoveryMetadata:
    def __init__(self, rows):
        self.rows = rows
        self.requests_used = 0

    def get(self, url, **kwargs):
        self.requests_used += 1
        if url == "https://api.github.com/search/repositories":
            return {"items": self.rows, "incomplete_results": False}, {}
        if url.endswith("/releases/latest"):
            raise CollectionError("HTTP 404 latest release unavailable", status_code=404)
        assert url.startswith("https://api.github.com/repos/example/")
        return {"private": False, "visibility": "public", "stargazers_count": 5}, {}


def test_current_seeds_do_not_consume_new_discovery_allowance(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "seeds": [{"source": "github", "name": "example/seed"}],
        "discovery": {"github_queries": ["topic:demo"]},
        "limits": {"max_discovered": 1},
    }))
    http = DiscoveryMetadata([
        {"full_name": "example/seed", "stargazers_count": 100},
        {"full_name": "example/new", "stargazers_count": 50},
    ])
    summary = run_pipeline(config, tmp_path / "out", now=START, http=http)
    assert {finding["candidate_id"] for finding in summary["findings"]} == {
        "github:example/seed", "github:example/new"
    }


def test_malformed_popularity_cannot_abort_unrelated_investigations(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "discovery": {"github_queries": ["topic:demo"]},
    }))
    http = DiscoveryMetadata([
        {"full_name": "example/bad-count", "stargazers_count": "not-an-integer"},
        {"full_name": "example/valid", "stargazers_count": 50},
    ])
    summary = run_pipeline(config, tmp_path / "out", now=START, http=http)
    assert summary["status"] == "completed"
    assert "github:example/valid" in {
        finding["candidate_id"] for finding in summary["findings"]
    }
