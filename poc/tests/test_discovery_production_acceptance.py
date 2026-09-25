"""Independent production-review regressions and actual crash recovery.

No live service, source code, binary or model is executed by these tests.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest
import yaml

from poc.discovery.evidence import classify_assets
from poc.discovery.http import BoundedHTTP, CollectionError
from poc.discovery.pipeline import run_pipeline
from poc.discovery.sources import dockerhub_collect


ROOT = Path(__file__).resolve().parents[2]
BASE = "https://hub.docker.com/v2/namespaces/org/repositories/tool"
CANDIDATE = {
    "id": "dockerhub:org/tool:v1",
    "source": "dockerhub",
    "name": "org/tool",
    "tag": "v1",
}
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Metadata:
    def __init__(self, repository=None, architecture="arm64"):
        self.repository = (
            {"name": "tool", "namespace": "org", "is_private": False}
            if repository is None
            else repository
        )
        self.architecture = architecture
        self.requests_used = 0

    def get(self, url, **kwargs):
        self.requests_used += 1
        if "/tags/" in url:
            return {
                "name": "v1",
                "images": [{"os": "linux", "architecture": self.architecture}],
            }, {}
        if isinstance(self.repository, Exception):
            raise self.repository
        return self.repository, {}


def write_config(tmp_path, **extra):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"seeds": [CANDIDATE], "limits": {"oci_fallback": False}, **extra}
        )
    )
    return path


@pytest.mark.parametrize(
    "repository",
    [
        {"is_private": True, "namespace": "org", "name": "tool"},
        {"is_private": False, "namespace": "other", "name": "tool"},
        {"is_private": False, "namespace": "org", "name": "other"},
    ],
)
def test_explicit_repository_rejection_cannot_publish_supported_scope(repository):
    result = dockerhub_collect(Metadata(repository), CANDIDATE, {"oci_fallback": False})
    assert result["status"] == "unknown", (
        "Identity/public-source policy failure must invalidate the otherwise positive finding"
    )
    assert result["failures"]


def test_optional_repository_transport_failure_retains_positive_tag_evidence():
    result = dockerhub_collect(
        Metadata(CollectionError("HTTP 429")), CANDIDATE, {"oci_fallback": False}
    )
    assert result["status"] == "supported"
    assert any("429" in error for error in result["failures"])


@pytest.mark.parametrize("size", [0, -1, False, "0", None, 3.14])
def test_invalid_binary_size_cannot_prove_distribution_gap(size):
    asset = {"name": "tool-linux-amd64.tar.gz", "state": "uploaded", "size": size}
    assert classify_assets([asset], True)[0] == "unknown"


@pytest.mark.parametrize("size", [-1, True, "0", None, 3.14])
def test_invalid_binary_size_cannot_prove_arm64_distribution(size):
    asset = {"name": "tool-linux-arm64.tar.gz", "state": "uploaded", "size": size}
    assert classify_assets([asset], True)[0] == "unknown"


@pytest.mark.parametrize(
    "architecture,expected", [("arm64", "supported"), ("amd64", "gap")]
)
def test_invalid_ai_review_retains_deterministic_status_and_report(
    tmp_path, architecture, expected
):
    def invalid_reviewer(value):
        return {
            "note": "Invented evidence",
            "citations": [
                {
                    "url": value["evidence"][0]["url"],
                    "quote": "this was never collected",
                }
            ],
        }

    report = run_pipeline(
        write_config(tmp_path),
        tmp_path / "out",
        http=Metadata(architecture=architecture),
        now=NOW,
        reviewer=invalid_reviewer,
    )
    finding = report["findings"][0]
    assert finding["status"] == expected
    assert finding["ai_review"]["status"] == "failed_validation"
    assert any(error["source"] == "ai_review" for error in report["failures"])
    published = json.loads((tmp_path / "out" / "latest.json").read_text())
    assert published["findings"][0]["status"] == expected
    assert all(Path(path).is_file() for path in published["report_paths"].values())


def test_failed_ai_review_is_not_retried_for_not_due_source(tmp_path):
    calls = []

    def unavailable(value):
        calls.append(value["scope"])
        raise ValueError("Configured provider unavailable")

    config = write_config(tmp_path)
    first = run_pipeline(
        config, tmp_path / "out", http=Metadata(), now=NOW, reviewer=unavailable
    )
    second_http = Metadata()
    second = run_pipeline(
        config,
        tmp_path / "out",
        http=second_http,
        now=NOW + timedelta(hours=1),
        reviewer=unavailable,
    )
    assert len(calls) == 1
    assert first["findings"][0]["status"] == "supported"
    assert second["counts"]["investigated"] == 0 and second_http.requests_used == 0
    assert second["retained_findings"][0]["ai_review"]["status"] == "failed_validation"


class Response:
    status_code = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, size):
        yield b'{"ok":true}'


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()


def test_request_budget_is_shared_across_all_source_hosts():
    session = Session()
    http = BoundedHTTP(
        {
            "max_requests": 2,
            "max_seconds": 30,
            "timeout_seconds": 2,
            "max_response_bytes": 1024,
        },
        session=session,
    )
    http.get("https://api.github.com/repos/org/tool")
    http.get("https://hub.docker.com/v2/namespaces/org/repositories/tool/tags/v1")
    with pytest.raises(CollectionError, match="request limit"):
        http.get("https://auth.docker.io/token")
    assert len(session.calls) == http.requests_used == 2


def test_source_deadline_excludes_later_requests(monkeypatch):
    clock = [0]
    monkeypatch.setattr("poc.discovery.http.time.monotonic", lambda: clock[0])
    session = Session()
    http = BoundedHTTP(
        {
            "max_requests": 10,
            "max_seconds": 30,
            "timeout_seconds": 2,
            "max_response_bytes": 1024,
        },
        session=session,
    )
    http.get("https://api.github.com/repos/org/tool")
    clock[0] = 31
    with pytest.raises(CollectionError, match="wall-clock"):
        http.get("https://auth.docker.io/token")
    assert len(session.calls) == 1


def test_process_death_after_observation_commit_recovers_without_rechecking(tmp_path):
    config = write_config(tmp_path)
    output = tmp_path / "out"
    child = textwrap.dedent("""
        import os, sys
        from datetime import datetime, timezone
        import poc.discovery.report
        from poc.discovery.pipeline import run_pipeline
        class Metadata:
            requests_used = 0
            def get(self, url, **kwargs):
                self.requests_used += 1
                if '/tags/' in url:
                    return {'name':'v1','images':[{'os':'linux','architecture':'amd64'}]}, {}
                return {'name':'tool','namespace':'org','is_private':False}, {}
        def terminate_after_observation(summary):
            os._exit(76)
        poc.discovery.report.write_reports = terminate_after_observation
        run_pipeline(sys.argv[1], sys.argv[2], http=Metadata(), now=datetime(2026,9,24,tzinfo=timezone.utc))
    """)
    process = subprocess.run(
        [sys.executable, "-c", child, str(config), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 76, process.stderr
    assert not (output / "latest.json").exists()
    with sqlite3.connect(output / "discovery.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert db.execute("SELECT finished_at FROM runs").fetchone()[0] is None
    http = Metadata()
    recovered = run_pipeline(config, output, now=NOW + timedelta(hours=1), http=http)
    assert http.requests_used == 0
    assert recovered["counts"]["investigated"] == 0
    assert recovered["counts"]["saved_observations"] == 1
    assert recovered["retained_findings"][0]["status"] == "gap"
    assert recovered["retained_findings"][0]["investigation_count"] == 1
    assert recovered["previous_run_failures"][0]["status"] == "interrupted"
    assert all(Path(path).is_file() for path in recovered["report_paths"].values())


def test_changed_tag_refresh_preserves_prior_observation_and_scoped_identity(tmp_path):
    config = write_config(tmp_path)
    output = tmp_path / "out"
    first = run_pipeline(config, output, now=NOW, http=Metadata(architecture="amd64"))
    second = run_pipeline(
        config, output, now=NOW + timedelta(days=8), http=Metadata(architecture="arm64")
    )
    finding = second["findings"][0]
    assert first["findings"][0]["status"] == "gap"
    assert finding["status"] == "supported" and finding["previous_status"] == "gap"
    assert (
        finding["candidate_id"] == CANDIDATE["id"]
        and finding["evidence_changed"] is True
    )
    with sqlite3.connect(output / "discovery.sqlite3") as db:
        assert db.execute("SELECT status FROM observations ORDER BY id").fetchall() == [
            ("gap",),
            ("supported",),
        ]


def test_ai_budget_counts_active_calls_not_collection_or_idle_time(monkeypatch):
    from poc.discovery.ai_review import OpenAIEvidenceReviewer

    clock = [0.0]
    monkeypatch.setattr("poc.discovery.ai_review.time.monotonic", lambda: clock[0])

    class ProviderResponse(Response):
        def iter_content(self, size):
            clock[0] += 1
            yield json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"note": "Advisory", "citations": []}
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ).encode()

    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return ProviderResponse()

    monkeypatch.setattr("poc.discovery.ai_review.requests.post", post)
    reviewer = OpenAIEvidenceReviewer(
        "test-model", "test-key", max_calls=2, max_seconds=5
    )
    input_value = {
        "scope": "selected tag",
        "deterministic_status": "unknown",
        "evidence": [],
    }
    clock[0] = 1000  # Metadata collection before any model call.
    assert reviewer(input_value)["note"] == "Advisory"
    clock[0] += 1000  # Work between calls does not consume model processing budget.
    assert reviewer(input_value)["note"] == "Advisory"
    assert len(calls) == 2
    with pytest.raises(ValueError, match="budget"):
        reviewer(input_value)


def test_ai_active_read_time_accumulates_across_calls(monkeypatch):
    from poc.discovery.ai_review import OpenAIEvidenceReviewer

    clock = [0.0]
    monkeypatch.setattr("poc.discovery.ai_review.time.monotonic", lambda: clock[0])

    class ProviderResponse(Response):
        def iter_content(self, size):
            clock[0] += 3
            yield json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"note":"Advisory","citations":[]}',
                                }
                            ],
                        }
                    ],
                }
            ).encode()

    monkeypatch.setattr(
        "poc.discovery.ai_review.requests.post",
        lambda *args, **kwargs: ProviderResponse(),
    )
    reviewer = OpenAIEvidenceReviewer(
        "test-model", "test-key", max_calls=3, max_seconds=5
    )
    value = {"scope": "selected tag", "deterministic_status": "unknown", "evidence": []}
    assert reviewer(value)["note"] == "Advisory"
    clock[0] += 1000
    with pytest.raises(ValueError, match="budget"):
        reviewer(value)


def test_source_collection_finishes_before_ai_and_saved_reviews_match_report(tmp_path):
    candidates = [CANDIDATE, {**CANDIDATE, "id": "dockerhub:org/tool:v2", "tag": "v2"}]

    class TwoTags(Metadata):
        def get(self, url, **kwargs):
            value, headers = super().get(url, **kwargs)
            if "/tags/" in url:
                value["name"] = url.rsplit("/", 1)[-1]
            return value, headers

    http = TwoTags()
    observed_counts = []

    def reviewer(value):
        observed_counts.append(http.requests_used)
        evidence = value["evidence"][0]
        return {
            "note": "Review the selected tag.",
            "citations": [{"url": evidence["url"], "quote": evidence["excerpt"]}],
        }

    output = tmp_path / "out"
    summary = run_pipeline(
        write_config(tmp_path, seeds=candidates),
        output,
        http=http,
        now=NOW,
        reviewer=reviewer,
    )
    assert observed_counts == [4, 4], (
        "Model latency must not displace the second candidate's source investigation"
    )
    assert summary["ai_review"]["completed"] == 2
    with sqlite3.connect(output / "discovery.sqlite3") as db:
        stored = [
            json.loads(row[0])
            for row in db.execute("SELECT result FROM observations ORDER BY id")
        ]
    assert [finding["ai_review"] for finding in stored] == [
        finding["ai_review"] for finding in summary["findings"]
    ]


@pytest.mark.parametrize(
    "release", [CollectionError("HTTP 404 latest release unavailable", status_code=404), {"id": 123, "tag_name": "v1-preview", "prerelease": True}]
)
def test_no_valid_latest_release_still_collects_repository_readme_without_promoting_support(
    release,
):
    import base64
    from poc.discovery.sources import github_collect

    base = "https://api.github.com/repos/org/tool"
    sha = "1" * 40
    statement = "Linux Arm64 users may build from source."
    calls = []

    class Repository:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            if url == base:
                return {
                    "id": 55,
                    "full_name": "org/tool",
                    "private": False,
                    "default_branch": "main",
                }, {}
            if url == base + "/releases/latest":
                if isinstance(release, Exception):
                    raise release
                return release, {}
            if url == base + "/readme":
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(statement.encode()).decode(),
                    "sha": sha,
                    "git_url": base + "/git/blobs/" + sha,
                    "html_url": "https://github.com/org/tool/blob/main/README.md",
                }, {}
            raise CollectionError("Unexpected metadata URL")

    finding = github_collect(
        Repository(),
        {"id": "github:org/tool", "source": "github", "name": "org/tool"},
        {"max_release_pages": 1, "max_asset_pages": 1},
    )
    assert finding["status"] == "unknown"
    readme_call = next(call for call in calls if call[0] == base + "/readme")
    assert readme_call[1]["params"]["ref"] == "main"
    excerpt = next(e for e in finding["evidence"] if statement in e["excerpt"])
    assert sha in json.dumps(excerpt), (
        "Content identity must be retained for the mutable default branch"
    )
    assert (
        "default" in json.dumps(excerpt).lower()
        or "repository" in json.dumps(excerpt).lower()
    )


def test_missing_repository_readme_remains_unknown_with_visible_collection_failure():
    from poc.discovery.sources import github_collect

    base = "https://api.github.com/repos/org/tool"

    class Repository:
        def get(self, url, **kwargs):
            if url == base:
                return {
                    "full_name": "org/tool",
                    "private": False,
                    "default_branch": "main",
                }, {}
            if url == base + "/releases/latest":
                raise CollectionError("HTTP 404 latest release unavailable", status_code=404)
            raise CollectionError("HTTP 404 repository README unavailable")

    finding = github_collect(
        Repository(),
        {"id": "github:org/tool", "source": "github", "name": "org/tool"},
        {"max_release_pages": 1, "max_asset_pages": 1},
    )
    assert finding["status"] == "unknown"
    assert any("README" in reason for reason in finding["failures"])


def test_custom_configuration_scope_cannot_reach_public_evidence_reviewer(tmp_path):
    base = "https://api.github.com/repos/org/tool"
    seen = []

    class Repository:
        requests_used = 0

        def get(self, url, **kwargs):
            self.requests_used += 1
            if url == base:
                return {"full_name": "org/tool", "private": False}, {}
            if url == base + "/releases/latest":
                return {"tag_name": "v1", "id": "invalid-release-id"}, {}
            raise CollectionError("Optional README unavailable")

    def reviewer(value):
        seen.append(json.dumps(value))
        evidence = value["evidence"][0]
        return {
            "note": "Evidence is incomplete.",
            "citations": [{"url": evidence["url"], "quote": evidence["excerpt"]}],
        }

    config = write_config(
        tmp_path,
        seeds=[
            {
                "source": "github",
                "name": "org/tool",
                "scope": "INTERNAL_PRIVATE_CONTEXT_NOT_FOR_MODEL",
            }
        ],
    )
    report = run_pipeline(
        config, tmp_path / "out", http=Repository(), reviewer=reviewer, now=NOW
    )
    assert report["findings"][0]["status"] == "unknown"
    assert seen and all(
        "INTERNAL_PRIVATE_CONTEXT_NOT_FOR_MODEL" not in item for item in seen
    )


def test_unchanged_readme_refreshed_date_does_not_claim_changed_evidence(
    tmp_path, monkeypatch
):
    import base64

    clock = [NOW]

    class ObservedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr("poc.discovery.sources.datetime", ObservedTime)
    base = "https://api.github.com/repos/org/tool"

    class Repository:
        requests_used = 0

        def get(self, url, **kwargs):
            self.requests_used += 1
            if url == base:
                return {
                    "full_name": "org/tool",
                    "private": False,
                    "default_branch": "main",
                }, {}
            if url == base + "/releases/latest":
                raise CollectionError("HTTP 404 latest release unavailable", status_code=404)
            if url == base + "/readme":
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(
                        b"Linux Arm64 source instructions."
                    ).decode(),
                    "sha": "1" * 40,
                }, {}
            raise CollectionError("Unexpected URL")

    config = write_config(tmp_path, seeds=[{"source": "github", "name": "org/tool"}])
    first = run_pipeline(config, tmp_path / "out", http=Repository(), now=NOW)
    clock[0] = NOW + timedelta(days=2)
    second = run_pipeline(config, tmp_path / "out", http=Repository(), now=clock[0])
    first_readme = next(
        e for e in first["findings"][0]["evidence"] if e["kind"] == "official_readme"
    )
    second_readme = next(
        e for e in second["findings"][0]["evidence"] if e["kind"] == "official_readme"
    )
    assert first_readme["collected_at"] != second_readme["collected_at"]
    assert first_readme["blob_sha"] == second_readme["blob_sha"]
    assert second["findings"][0]["evidence_changed"] is False
    assert second["findings"][0]["investigation_count"] == 2
