"""Collector boundary cases: uncertain metadata must never invent support/gaps."""

from datetime import datetime

import pytest

from poc.discovery.evidence import (
    classify_assets,
    classify_platforms,
    manifest_platforms,
)
from poc.discovery.http import BoundedHTTP, CollectionError, github_pages
from poc.discovery.sources import (
    _github_link,
    discover_github,
    dockerhub_collect,
    github_collect,
)


class Metadata:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.pages.get(url, CollectionError("No fixture for metadata endpoint"))
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("entry", [None, "linux-arm64", [], 12])
def test_malformed_asset_prevents_negative_inventory_claim(entry):
    status, _ = classify_assets([{"name": "tool-linux-amd64.tar.gz"}, entry], True)
    assert status == "unknown"


@pytest.mark.parametrize(
    "name",
    [
        "tool-linux-arm64.html",
        "tool-linux-arm64.md",
        "tool-linux-arm64.tar.gz.minisig",
        "tool-linux-arm64.intoto.jsonl",
        "tool-linux-arm64.pdf",
        "tool-linux-arm64.yaml",
        "tool-linux-arm64-amd64.zip",
        "tool-linux-windows-arm64.zip",
    ],
)
def test_nonbinary_or_contradictory_names_do_not_prove_support(name):
    assert classify_assets([{"name": name}], True)[0] == "unknown"


def test_zero_byte_advertised_asset_is_not_distribution_evidence():
    assert (
        classify_assets([{"name": "tool-linux-arm64.tgz", "size": 0}], True)[0]
        == "unknown"
    )


def test_text_mime_type_does_not_prove_binary_distribution():
    assert (
        classify_assets(
            [{"name": "tool-linux-arm64", "content_type": "text/html"}], True
        )[0]
        == "unknown"
    )


@pytest.mark.parametrize("media_type", ["application/vnd.unknown.artifact", [], {}])
def test_unknown_oci_media_types_never_prove_runtime_support(media_type):
    descriptor = {
        "platform": {"os": "linux", "architecture": "arm64"},
        "mediaType": media_type,
    }
    assert (
        classify_platforms(*manifest_platforms({"manifests": [descriptor]}))[0]
        == "unknown"
    )
    assert manifest_platforms(
        {
            "mediaType": media_type,
            "manifests": [{"platform": {"os": "linux", "architecture": "arm64"}}],
        }
    ) == ([], False)


@pytest.mark.parametrize(
    "entry", [None, "linux/arm64", [], 12, {"platform": "linux/arm64"}]
)
def test_malformed_oci_descriptor_cannot_complete_amd64_only_inventory(entry):
    index = {
        "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}, entry]
    }
    assert classify_platforms(*manifest_platforms(index))[0] == "unknown"


def test_oci_artifacts_are_not_runtime_arm64_support():
    index = {
        "manifests": [
            {"platform": {"os": "linux", "architecture": "amd64"}},
            {
                "platform": {"os": "linux", "architecture": "arm64"},
                "artifactType": "application/spdx+json",
            },
        ]
    }
    assert classify_platforms(*manifest_platforms(index))[0] == "gap"
    index["artifactType"] = "application/spdx+json"
    assert classify_platforms(*manifest_platforms(index))[0] == "unknown"
    artifact = {"config": {"mediaType": "application/vnd.oci.empty.v1+json"}}
    assert (
        classify_platforms(
            *manifest_platforms(artifact, {"os": "linux", "architecture": "arm64"})
        )[0]
        == "unknown"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com:garbage/x",
        "https://api.github.com:0443/x",
        "https://evil.example\\@api.github.com/x",
        "https://api.github.com./x",
        "https://%61pi.github.com/x",
        "https://api.github.com/x\n",
        "https://api.github.com/x#fragment",
        "https://[api.github.com/x",
    ],
)
def test_ambiguous_http_authorities_rejected_before_any_request(url):
    client = BoundedHTTP(
        {
            "max_requests": 1,
            "max_seconds": 10,
            "timeout_seconds": 1,
            "max_response_bytes": 1000,
        }
    )
    with pytest.raises(CollectionError, match="unapproved"):
        client.get(url)
    assert client.requests_used == 0


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/releases/v1",
        "https://evil.example\\@github.com/org/tool/releases/v1",
        "https://github.com/other/tool/releases/v1",
        "https://github.com/org/tool/../../other/tool/releases/v1",
        "https://github.com/org/tool/%2e%2e/%2e%2e/other/tool",
        "https://user@github.com/org/tool/releases/v1",
        "javascript:alert(1)",
        None,
        [],
    ],
)
def test_repository_citations_fall_back_when_url_not_official(value):
    assert _github_link(value, "org/tool", "safe-fallback") == "safe-fallback"


@pytest.mark.parametrize(
    "link",
    [
        "<https://api.github.com/repos/org/tool/releases/1/assets?page=2>; rel=next",
        '<https://api.github.com/repos/org/tool/releases/1/assets?page=2>; type="application/json"; rel="next"',
        '<https://api.github.com/repos/org/tool/releases/1/assets?page=2>; rel="next alternate"',
    ],
)
def test_pagination_link_parameters_do_not_hide_arm64_second_page(link):
    first = "https://api.github.com/repos/org/tool/releases/1/assets"
    second = first + "?page=2"
    client = Metadata(
        {
            first: ([{"name": "tool-linux-amd64.tgz"}], {"Link": link}),
            second: ([{"name": "tool-linux-arm64.tgz"}], {}),
        }
    )
    assets, complete, errors = github_pages(client, first, 2)
    assert complete and not errors
    assert classify_assets(assets, complete)[0] == "supported"
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "link",
    [
        '<https://hub.docker.com/next>; rel="next"',
        '<https://api.github.com/repos/different/repository>; rel="next"',
        '<https://api.github.com./assets>; rel="next"',
        "<https://api.github.com/assets?page=2>; broken=1",
        "broken header",
    ],
)
def test_invalid_pagination_never_proves_absence(link):
    url = "https://api.github.com/assets"
    client = Metadata({url: ([{"name": "tool-linux-amd64.tgz"}], {"Link": link})})
    assets, complete, errors = github_pages(client, url, 2)
    assert not complete and errors
    assert classify_assets(assets, complete)[0] == "unknown"
    assert len(client.calls) == 1


def test_incomplete_search_flag_survives_later_complete_page():
    url = "https://api.github.com/search/repositories"
    next_url = url + "?page=2"
    client = Metadata(
        {
            url: (
                {"items": [{"full_name": "org/one"}], "incomplete_results": True},
                {"Link": f'<{next_url}>; rel="next"'},
            ),
            next_url: (
                {"items": [{"full_name": "org/two"}], "incomplete_results": False},
                {},
            ),
        }
    )
    values, complete, errors = github_pages(client, url, 2, items_key="items")
    assert len(values) == 2 and not complete
    assert errors == ["GitHub search reports incomplete results"]


def test_github_verified_numeric_repository_pagination_alias_is_followed():
    first = "https://api.github.com/repos/org/tool/releases/1/assets"
    canonical = "/repositories/1234/releases/1/assets"
    second = "https://api.github.com" + canonical + "?page=2"
    client = Metadata(
        {
            first: (
                [{"name": "tool-linux-amd64.tgz"}],
                {"Link": f'<{second}>; rel="next"'},
            ),
            second: ([{"name": "tool-linux-arm64.tgz"}], {}),
        }
    )
    assets, complete, errors = github_pages(
        client, first, 2, alternate_paths=[canonical]
    )
    assert complete and not errors
    assert classify_assets(assets, complete)[0] == "supported"


def test_new_discovery_skips_known_top_projects_and_keeps_bounded_star_order():
    url = "https://api.github.com/search/repositories"
    client = Metadata(
        {
            url: (
                {
                    "items": [
                        {"full_name": "org/known", "stargazers_count": 1000},
                        {"full_name": "org/next", "stargazers_count": 900},
                        {"full_name": "ORG/NEXT", "stargazers_count": 900},
                        {"full_name": "org/new", "stargazers_count": 800},
                        {"full_name": "org/later", "stargazers_count": 700},
                    ]
                },
                {},
            )
        }
    )
    limits = {
        "max_queries": 1,
        "max_discovered": 2,
        "max_search_pages": 2,
        "max_source_records": 5,
    }
    found, failures, skips = discover_github(
        client,
        {"github_queries": ["topic:database"]},
        limits,
        known_ids={"github:org/known"},
    )
    assert [f["name"] for f in found] == ["org/next", "org/new"]
    assert [f["discovery_rank"] for f in found] == [2, 4]
    assert [f["discovery_stars"] for f in found] == [900, 800]
    assert not failures
    assert next(s for s in skips if s.get("informational"))["count"] == 5
    assert any("deferred" in s["reason"] for s in skips)
    assert "is:public" in client.calls[0][1]["params"]["q"]


def test_known_records_do_not_allow_discovery_to_exceed_source_scan_limit():
    url = "https://api.github.com/search/repositories"
    client = Metadata(
        {url: ({"items": [{"full_name": f"org/p{i}"} for i in range(6)]}, {})}
    )
    found, _, skips = discover_github(
        client,
        {"github_queries": ["one", "two"]},
        {
            "max_queries": 2,
            "max_discovered": 2,
            "max_search_pages": 1,
            "max_source_records": 3,
        },
        known_ids={f"github:org/p{i}" for i in range(3)},
    )
    assert found == []
    assert len(client.calls) == 1
    assert next(s for s in skips if s.get("informational"))["count"] == 3
    assert any("Source-record limit" in s["reason"] for s in skips)


def test_discovery_excludes_private_archived_forks_and_malformed_rows():
    url = "https://api.github.com/search/repositories"
    client = Metadata(
        {
            url: (
                {
                    "items": [
                        None,
                        {"full_name": "org/private", "private": True},
                        {"full_name": "org/archived", "archived": True},
                        {"full_name": "org/fork", "fork": True},
                        {"full_name": "org/public", "private": False},
                    ]
                },
                {},
            )
        }
    )
    found, _, _ = discover_github(
        client,
        {"github_queries": ["database"]},
        {"max_queries": 1, "max_discovered": 3, "max_search_pages": 1},
    )
    assert [f["name"] for f in found] == ["org/public"]


def test_docker_popularity_is_dated_optional_and_does_not_change_status():
    base = "https://hub.docker.com/v2/namespaces/library/repositories/tool"
    client = Metadata(
        {
            base + "/tags/v1": (
                {"images": [{"os": "linux", "architecture": "arm64"}]},
                {},
            ),
            base: (
                {
                    "namespace": "library",
                    "name": "tool",
                    "pull_count": 1200,
                    "star_count": 10,
                },
                {},
            ),
        }
    )
    candidate = {
        "id": "dockerhub:library/tool:v1",
        "name": "library/tool",
        "tag": "v1",
        "source": "dockerhub",
    }
    result = dockerhub_collect(client, candidate, {"oci_fallback": False})
    assert result["status"] == "supported"
    assert result["popularity_signals"][0]["value"] == 1200
    assert "cumulative" in result["popularity_signals"][0]["period"]
    assert datetime.fromisoformat(result["popularity_signals"][0]["observed_at"]).tzinfo
    assert result["metadata"]["publisher_recognition"] == "Docker Official Image"
    client.pages[base] = CollectionError("Rate limited")
    result = dockerhub_collect(client, candidate, {"oci_fallback": False})
    assert result["status"] == "supported"
    assert result["popularity_signals"][0]["value"] is None
    assert "Rate limited" in result["failures"][0]


@pytest.mark.parametrize(
    "bad_images",
    [
        [None],
        ["arm64"],
        [{"os": [], "architecture": "arm64"}],
        [{"os": "linux", "architecture": {}}],
    ],
)
def test_bad_docker_tag_shapes_remain_unknown(bad_images):
    url = "https://hub.docker.com/v2/namespaces/org/repositories/tool/tags/v1"
    client = Metadata({url: ({"images": bad_images}, {})})
    result = dockerhub_collect(
        client,
        {
            "id": "dockerhub:org/tool:v1",
            "name": "org/tool",
            "tag": "v1",
            "source": "dockerhub",
        },
        {"oci_fallback": False},
    )
    assert result["status"] == "unknown"


def test_missing_release_id_keeps_unknown_and_repository_popularity():
    base = "https://api.github.com/repos/org/tool"
    client = Metadata(
        {
            base: ({"stargazers_count": 200}, {}),
            base + "/releases": ([{"tag_name": "v1"}], {}),
        }
    )
    result = github_collect(
        client,
        {"id": "github:org/tool", "name": "org/tool", "source": "github"},
        {"max_release_pages": 1, "max_asset_pages": 1},
    )
    assert result["status"] == "unknown" and result["failures"]
    assert result["popularity_signals"][0]["value"] == 200


class StreamResponse:
    def __init__(self, chunks, status=200):
        self.chunks, self.status_code = chunks, status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, size):
        yield from self.chunks


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.parametrize(
    "response,expected",
    [
        (StreamResponse([b'{"too":"large"}']), "byte limit"),
        (StreamResponse([b"not-json"]), "JSONDecodeError"),
        (StreamResponse([], status=302), "HTTP 302"),
        (StreamResponse([], status=429), "HTTP 429"),
    ],
)
def test_bounded_http_errors_do_not_include_body_and_never_follow_redirects(
    response, expected
):
    session = Session(response)
    client = BoundedHTTP(
        {
            "max_requests": 1,
            "max_seconds": 10,
            "timeout_seconds": 1,
            "max_response_bytes": 10,
        },
        session=session,
    )
    with pytest.raises(CollectionError, match=expected):
        client.get("https://api.github.com/repos/org/tool")
    assert client.requests_used == 1
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["stream"] is True


def test_github_token_never_crosses_to_docker(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-secret")
    session = Session(StreamResponse([b"{}"]))
    client = BoundedHTTP(
        {
            "max_requests": 2,
            "max_seconds": 10,
            "timeout_seconds": 1,
            "max_response_bytes": 10,
        },
        session=session,
    )
    client.get("https://api.github.com/repos/org/tool")
    client.get("https://hub.docker.com/v2/namespaces/library/repositories/tool")
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer test-secret"
    assert "Authorization" not in session.calls[1][1]["headers"]
