"""Current discovery examples retain exact evidence without manufacturing gaps."""

import base64
from pathlib import Path

import pytest
import yaml

from poc.discovery.http import CollectionError
from poc.discovery.pipeline import normalize_candidate
from poc.discovery.sources import dockerhub_collect, github_collect

ROOT = Path(__file__).resolve().parents[2]
MYSQL = "https://hub.docker.com/v2/namespaces/library/repositories/mysql"


class MySQLMetadata:
    """Explicit test fixtures; these do not assert live registry contents."""

    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url == MYSQL:
            return {"name": "mysql", "namespace": "library", "is_private": False}, {}
        if url == MYSQL + "/tags/latest":
            return {
                "name": "latest",
                "digest": "sha256:" + "a" * 64,
                "images": [
                    {"os": "linux", "architecture": "amd64"},
                    {"os": "linux", "architecture": "arm64", "variant": "v8"},
                ],
            }, {}
        if url == MYSQL + "/tags/5.7":
            return {
                "name": "5.7",
                "digest": "sha256:" + "b" * 64,
                "images": [{"os": "linux", "architecture": "amd64"}],
            }, {}
        raise AssertionError(f"Unexpected endpoint: {url}")


def test_example_checks_current_mysql_without_forcing_a_gap():
    config = yaml.safe_load((ROOT / "poc/discovery/config.example.yaml").read_text())
    seeds = [seed for seed in config["seeds"] if seed["name"] == "library/mysql"]
    assert len(seeds) == 1
    candidate = normalize_candidate(seeds[0])
    assert candidate["tag"] == "latest"
    http = MySQLMetadata()
    result = dockerhub_collect(http, candidate, {"oci_fallback": False})
    assert result["status"] == "supported"
    assert result["candidate_id"] == "dockerhub:library/mysql:latest"
    assert result["metadata"]["digest"] == "sha256:" + "a" * 64
    assert result["metadata"]["tag"] == "latest"
    assert "library/mysql:latest" in result["scope"]
    assert MYSQL + "/tags/5.7" not in http.calls


def test_legacy_mysql_is_only_a_scoped_regression_fixture():
    candidate = normalize_candidate(
        {"source": "dockerhub", "name": "library/mysql", "tag": "5.7"}
    )
    result = dockerhub_collect(MySQLMetadata(), candidate, {"oci_fallback": False})
    assert result["status"] == "gap"
    assert result["candidate_id"] == "dockerhub:library/mysql:5.7"
    assert "library/mysql:5.7" in result["scope"]
    assert "exact tag" in result["scope"]
    assert result["metadata"]["digest"] == "sha256:" + "b" * 64


GITHUB = "https://api.github.com/repos/example/tool"


class LatestReleaseMetadata:
    def __init__(self, latest=None, assets=None):
        self.latest = (
            {"id": 22, "tag_name": "v2", "published_at": "2026-09-20T10:00:00Z"}
            if latest is None
            else latest
        )
        self.assets = (
            [{"name": "tool-linux-arm64.tar.gz"}] if assets is None else assets
        )
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url == GITHUB:
            return {
                "full_name": "example/tool",
                "private": False,
                "default_branch": "main",
            }, {}
        if url == GITHUB + "/releases/latest":
            if isinstance(self.latest, Exception):
                raise self.latest
            return self.latest, {}
        if url == GITHUB + "/releases/22/assets":
            return self.assets, {}
        if url == GITHUB + "/readme":
            return {
                "encoding": "base64",
                "content": base64.b64encode(
                    b"Linux Arm64 source build instructions"
                ).decode(),
                "sha": "a" * 40,
            }, {}
        # An old release is intentionally available but must not be consulted.
        if url == GITHUB + "/releases":
            return [{"id": 1, "tag_name": "v1"}], {}
        if url == GITHUB + "/releases/1/assets":
            return [{"name": "tool-linux-amd64.tar.gz"}], {}
        raise AssertionError(f"Unexpected endpoint: {url}")


def collect_latest(http):
    return github_collect(
        http,
        normalize_candidate({"source": "github", "name": "example/tool"}),
        {"max_asset_pages": 1},
    )


def test_default_repository_selection_uses_latest_endpoint_not_legacy_list_order():
    http = LatestReleaseMetadata()
    result = collect_latest(http)
    assert result["status"] == "supported"
    assert result["metadata"]["release_selection"] == "github_latest_release"
    assert result["metadata"]["release_tag"] == "v2"
    assert result["metadata"]["release_id"] == 22
    assert result["metadata"]["release_published_at"] == "2026-09-20T10:00:00Z"
    assert GITHUB + "/releases" not in http.calls
    assert GITHUB + "/releases/1/assets" not in http.calls
    assert "maintenance" in result["metadata"]["release_selection_limitations"]


def test_actual_current_distribution_gap_is_still_reported():
    http = LatestReleaseMetadata(assets=[{"name": "tool-linux-amd64.tar.gz"}])
    result = collect_latest(http)
    assert result["status"] == "gap"
    assert "release v2" in result["scope"]
    assert "latest published full release" in result["scope"]


@pytest.mark.parametrize(
    "latest",
    [
        CollectionError("HTTP 404", status_code=404),
        [],
        {"id": 22, "tag_name": "v3-preview", "prerelease": True},
        {"id": 22, "tag_name": "v2", "draft": True},
        {"id": 22, "tag_name": ""},
    ],
)
def test_missing_or_invalid_latest_stays_unknown_without_historical_fallback(latest):
    http = LatestReleaseMetadata(latest=latest)
    result = collect_latest(http)
    assert result["status"] == "unknown"
    assert result["assessment_coverage"]["review_required"]
    assert result["assessment_coverage"]["inventory_complete"] is False
    assert any(e["kind"] == "official_readme" for e in result["evidence"])
    if isinstance(latest, CollectionError) and latest.status_code == 404:
        assert not result["failures"]
        assert result["metadata"]["latest_release_response_status"] == 404
    else:
        assert result["failures"]
    assert GITHUB + "/releases" not in http.calls
    assert not any(url.endswith("/assets") for url in http.calls)


@pytest.mark.parametrize(
    "failure",
    [
        CollectionError("HTTP 404 text without a typed status"),
        CollectionError("Forbidden", status_code=403),
        CollectionError("Rate limited", status_code=429),
        CollectionError("Server failure", status_code=500),
        CollectionError("Network failure"),
    ],
)
def test_only_typed_latest_404_is_expected_absence(failure):
    result = collect_latest(LatestReleaseMetadata(latest=failure))
    assert result["status"] == "unknown"
    assert result["failures"]
    assert "latest_release_response_status" not in result["metadata"]


@pytest.mark.parametrize(
    "field,value", [("draft", []), ("prerelease", 0), ("draft", "false")]
)
def test_malformed_publication_flags_do_not_prove_current_release_support(field, value):
    result = collect_latest(
        LatestReleaseMetadata(latest={"id": 22, "tag_name": "v2", field: value})
    )
    assert result["status"] == "unknown"
    assert any("malformed" in failure for failure in result["failures"])


def test_expected_latest_absence_does_not_swallow_another_endpoint_404():
    class MissingReadme(LatestReleaseMetadata):
        def get(self, url, **kwargs):
            if url.endswith("/readme"):
                raise CollectionError("README missing", status_code=404)
            return super().get(url, **kwargs)

    result = collect_latest(
        MissingReadme(latest=CollectionError("No full release", status_code=404))
    )
    assert result["status"] == "unknown"
    assert len(result["failures"]) == 1
    assert "README" in result["failures"][0]


def test_http_failures_expose_status_without_response_body_or_credentials():
    from poc.discovery.http import BoundedHTTP

    class Response:
        status_code = 404

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    http = BoundedHTTP(
        {"max_requests": 2, "max_seconds": 30, "timeout_seconds": 1}, session=Session()
    )
    with pytest.raises(CollectionError) as failure:
        http.get(GITHUB + "/releases/latest")
    assert failure.value.status_code == 404
    assert (
        str(failure.value)
        == "HTTP 404 from api.github.com/repos/example/tool/releases/latest"
    )
