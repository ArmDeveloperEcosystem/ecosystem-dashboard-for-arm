import pytest

from poc.discovery.evidence import (
    classify_assets,
    classify_platforms,
    manifest_platforms,
)
from poc.discovery.http import BoundedHTTP, CollectionError, github_pages
from poc.discovery.pipeline import review_evidence
from poc.discovery.sources import dockerhub_collect, github_collect


@pytest.mark.parametrize(
    "names,complete,status",
    [
        (["tool-linux-arm64.tar.gz"], True, "supported"),
        (["tool-aarch64-unknown-linux-gnu.tar.gz"], False, "supported"),
        (["tool-linux-amd64.tar.gz", "tool-darwin-arm64.tar.gz"], True, "gap"),
        (["tool-linux-amd64.tar.gz", "tool-windows-arm64.zip"], True, "gap"),
        (["tool-linux-armv7.tar.gz"], True, "gap"),
        (["tool-linux-armv8.tar.gz"], True, "unknown"),
        (["tool-linux-amd64.tar.gz"], False, "unknown"),
        (["tool-linux-amd64.tar.gz", "tool.tar.gz"], True, "unknown"),
        (["tool-darwin-arm64.tar.gz"], True, "unknown"),
        (["tool-linux-arm64.tar.gz.sha256"], True, "unknown"),
        ([], True, "unknown"),
    ],
)
def test_release_scope(names, complete, status):
    assert classify_assets([{"name": name} for name in names], complete)[0] == status


@pytest.mark.parametrize(
    "platforms,complete,status",
    [
        ([{"os": "linux", "architecture": "arm64"}], True, "supported"),
        ([{"os": "linux", "architecture": "amd64"}], True, "gap"),
        ([{"os": "darwin", "architecture": "arm64"}], True, "gap"),
        ([{"os": "windows", "architecture": "arm64"}], True, "gap"),
        ([{"os": "linux", "architecture": "arm", "variant": "v7"}], True, "gap"),
        (
            [{"os": "linux", "architecture": "amd64"}, {"architecture": "arm64"}],
            True,
            "unknown",
        ),
        ([{"os": "linux", "architecture": "amd64"}], False, "unknown"),
        ([{"os": "linux", "architecture": "newarchitecture"}], True, "unknown"),
        ([{"os": "unknown-linux", "architecture": "amd64"}], True, "unknown"),
        ([{"os": "Linux", "architecture": "AMD64"}], True, "gap"),
        ([], True, "unknown"),
    ],
)
def test_platform_scope(platforms, complete, status):
    assert classify_platforms(platforms, complete)[0] == status


def test_singlearch_requires_config_and_attestations_require_explicit_annotation():
    manifest = {"schemaVersion": 2, "config": {"digest": "sha256:abc"}, "layers": []}
    assert manifest_platforms(manifest) == ([], False)
    platforms, complete = manifest_platforms(
        manifest, {"os": "linux", "architecture": "arm64"}
    )
    assert classify_platforms(platforms, complete)[0] == "supported"
    index = {
        "manifests": [
            {"platform": {"os": "linux", "architecture": "amd64"}},
            {"platform": {"os": "unknown", "architecture": "unknown"}},
        ]
    }
    assert classify_platforms(*manifest_platforms(index))[0] == "unknown"
    index["manifests"][1]["annotations"] = {
        "vnd.docker.reference.type": "attestation-manifest"
    }
    assert classify_platforms(*manifest_platforms(index))[0] == "gap"


def test_unfinished_asset_upload_is_not_a_complete_distribution():
    assert (
        classify_assets(
            [{"name": "tool-linux-amd64.tar.gz", "state": "starter"}], True
        )[0]
        == "unknown"
    )


class Pages:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.rows[url]
        if isinstance(value, Exception):
            raise value
        return value


def test_asset_pagination_retains_late_arm64_and_page_failure_is_incomplete():
    first = "https://api.github.com/repos/org/tool/releases/1/assets"
    second = first + "?page=2"
    http = Pages(
        {
            first: (
                [{"name": "tool-linux-amd64.tar.gz"}],
                {"Link": f'<{second}>; rel="next"'},
            ),
            second: ([{"name": "tool-linux-arm64.tar.gz"}], {}),
        }
    )
    values, complete, errors = github_pages(http, first, 3)
    assert complete and not errors and len(http.calls) == 2
    assert classify_assets(values, complete)[0] == "supported"
    http.rows[second] = CollectionError("HTTP 403")
    values, complete, errors = github_pages(http, first, 3)
    assert not complete and errors
    assert classify_assets(values, complete)[0] == "unknown"


def test_pagination_cap_and_cycle_are_never_complete():
    url = "https://api.github.com/x"
    http = Pages(
        {url: ([{"name": "tool-linux-amd64.tar.gz"}], {"Link": f'<{url}>; rel="next"'})}
    )
    assert github_pages(http, url, 1)[1] is False
    assert "cycle" in github_pages(http, url, 3)[2][0].lower()


def test_no_arbitrary_hosts_or_http_and_request_cap():
    http = BoundedHTTP(
        {
            "max_requests": 1,
            "max_seconds": 10,
            "timeout_seconds": 1,
            "max_response_bytes": 1000,
        }
    )
    for url in (
        "http://api.github.com/x",
        "https://localhost/x",
        "https://api.github.com.evil.test/x",
        "https://user:password@api.github.com/x",
    ):
        with pytest.raises(CollectionError):
            http.get(url)
    http.requests_used = 1
    with pytest.raises(CollectionError, match="request limit"):
        http.get("https://api.github.com/x")


def test_ai_quote_validation_rejects_invented_url_or_quote():
    result = {
        "scope": "tag latest",
        "status": "gap",
        "evidence": [
            {"url": "https://example.com", "excerpt": "linux/amd64", "kind": "platform"}
        ],
    }
    valid = lambda value: {
        "note": "Review the exact tag.",
        "citations": [{"url": "https://example.com", "quote": "linux/amd64"}],
    }
    assert review_evidence(result, valid)["status"] == "completed"
    for quote, url in [
        ("linux/arm64", "https://example.com"),
        ("linux/amd64", "https://fake.example"),
    ]:
        with pytest.raises(ValueError):
            review_evidence(
                result,
                lambda value, url=url, quote=quote: {
                    "note": "invented",
                    "citations": [{"url": url, "quote": quote}],
                },
            )


def test_collector_follows_release_and_asset_pages_instead_of_embedded_assets():
    base = "https://api.github.com/repos/org/tool"
    releases2 = base + "/releases?page=2"
    assets = base + "/releases/2/assets"
    assets2 = assets + "?page=2"
    http = Pages(
        {
            base: ({"description": "test", "stargazers_count": 10}, {}),
            base + "/releases": (
                [{"id": 1, "tag_name": "preview", "prerelease": True}],
                {"Link": f'<{releases2}>; rel="next"'},
            ),
            releases2: (
                [
                    {
                        "id": 2,
                        "tag_name": "v1",
                        "assets": [{"name": "tool-linux-amd64.tar.gz"}],
                    }
                ],
                {},
            ),
            assets: (
                [{"name": "tool-linux-amd64.tar.gz"}],
                {"Link": f'<{assets2}>; rel="next"'},
            ),
            assets2: ([{"name": "tool-linux-arm64.tar.gz"}], {}),
            base + "/readme": CollectionError("HTTP 404"),
        }
    )
    result = github_collect(
        http,
        {"id": "github:org/tool", "name": "org/tool", "source": "github"},
        {"max_release_pages": 2, "max_asset_pages": 2},
    )
    assert result["status"] == "supported"
    assert result["metadata"]["asset_count"] == 2
    assert result["metadata"]["release_tag"] == "v1"
    assert result["failures"]  # Optional README failure does not erase proven artifact.


def test_docker_partial_metadata_never_becomes_gap():
    url = "https://hub.docker.com/v2/namespaces/org/repositories/tool/tags/v1"
    http = Pages(
        {
            url.rsplit("/tags/", 1)[0]: (
                {"name": "tool", "namespace": "org", "pull_count": 10},
                {},
            ),
            url: (
                {
                    "images": [
                        {"os": "linux", "architecture": "amd64"},
                        {"architecture": "arm64"},
                    ]
                },
                {},
            ),
        }
    )
    result = dockerhub_collect(
        http,
        {
            "id": "dockerhub:org/tool:v1",
            "name": "org/tool",
            "source": "dockerhub",
            "tag": "v1",
        },
        {"oci_fallback": False},
    )
    assert result["status"] == "unknown"


def test_ai_response_stream_enforces_total_deadline(monkeypatch):
    from poc.discovery import ai_review

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def iter_content(self, size):
            clock[0] = 20
            yield b'{"status":"completed"}'

    clock = [0]
    monkeypatch.setattr(ai_review.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ai_review.requests, "post", lambda *args, **kwargs: Response())
    reviewer = ai_review.OpenAIEvidenceReviewer(
        "configured-model", "test-key", max_seconds=5
    )
    with pytest.raises(ValueError, match="total time budget"):
        reviewer({"scope": "tag", "deterministic_status": "gap", "evidence": []})
