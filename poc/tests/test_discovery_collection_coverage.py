"""Regression coverage for bounded collection and honest artifact coverage."""

import time
from urllib.parse import parse_qs, urlparse

import pytest

from poc.discovery.http import CollectionError, github_pages
from poc.discovery.sources import discover_github, github_collect

SEARCH = "https://api.github.com/search/repositories"
BASE = "https://api.github.com/repos/org/tool"
ASSETS = BASE + "/releases/1/assets"
CANDIDATE = {"id": "github:org/tool", "source": "github", "name": "org/tool"}


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.pages.get(url, CollectionError("No fixture"))
        if isinstance(value, Exception):
            raise value
        return value


def limits(**values):
    return {
        "max_queries": 3,
        "max_discovered": 1000,
        "max_source_records": 250,
        "max_search_pages": 5,
        **values,
    }


def metrics(skips):
    return {item["metric"]: item["count"] for item in skips if item.get("metric")}


def test_deferred_tail_counts_only_eligible_unique_unseen_candidates():
    rows = [
        {"full_name": "org/first"},
        {"full_name": "org/second"},
        {"full_name": "org/third"},
        {"full_name": "org/known"},
        {"full_name": "ORG/THIRD"},
        {"full_name": "org/archived", "archived": True},
        {"full_name": "org/private", "private": True},
        {"full_name": "org/fork", "fork": True},
        {"full_name": "invalid"},
        None,
    ]
    http = Pages({SEARCH: ({"items": rows}, {})})
    found, errors, skips = discover_github(
        http,
        {"github_queries": ["database"]},
        limits(max_discovered=2),
        {"github:ORG/KNOWN.GIT"},
    )
    assert [item["name"] for item in found] == ["org/first", "org/second"]
    assert not errors
    assert metrics(skips) == {
        "source_records_fetched": 10,
        "source_records_examined": 10,
        "discovery_candidates_selected": 2,
    }
    deferred = [
        item for item in skips if item["reason"].startswith("Additional unseen")
    ]
    assert len(deferred) == 1 and deferred[0]["count"] == 1
    assert (
        next(item for item in skips if item["reason"].startswith("Known,"))["count"]
        == 7
    )


class SearchPages:
    """Honor requested page size while exposing a further full page."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        query = {key: value[0] for key, value in parse_qs(urlparse(url).query).items()}
        query.update(params or {})
        page = int(query.get("page", 1))
        size = int(query["per_page"])
        label = str(query.get("q", "first")).split()[0]
        self.calls.append((label, page, size))
        rows = [
            {"full_name": f"org/{label}{i}"}
            for i in range((page - 1) * size, page * size)
        ]
        return {"items": rows}, {
            "Link": f'<{SEARCH}?q={label}&page={page + 1}&per_page={size}>; rel="next"'
        }


@pytest.mark.parametrize(
    "cap,expected",
    [
        (150, [("first", 1, 100), ("second", 1, 50)]),
        (250, [("first", 1, 100), ("first", 2, 100), ("second", 1, 50)]),
    ],
)
def test_global_record_cap_preserves_page_offsets_across_queries(cap, expected):
    http = SearchPages()
    found, errors, skips = discover_github(
        http,
        {"github_queries": ["first", "second", "third"]},
        limits(max_source_records=cap),
    )
    assert http.calls == expected
    assert not errors
    assert len(found) == cap
    assert metrics(skips)["source_records_fetched"] == cap
    assert metrics(skips)["source_records_examined"] == cap
    assert len({item["name"] for item in found}) == cap


def test_one_query_can_underuse_remaining_allowance_without_offset_rewrite():
    http = SearchPages()
    found, errors, skips = discover_github(
        http,
        {"github_queries": ["first"]},
        limits(max_source_records=150),
    )
    assert http.calls == [("first", 1, 100)]
    assert len(found) == 100 and not errors
    assert metrics(skips)["source_records_fetched"] == 100


def test_expected_budget_deferral_between_search_pages_and_queries_is_not_a_failure():
    class LimitedSearch(SearchPages):
        def __init__(self):
            super().__init__()
            self.requests_used = 0
            self.started = time.monotonic()
            self.limits = {"max_requests": 1, "max_seconds": 30}

        def get(self, *args, **kwargs):
            assert self.requests_used < self.limits["max_requests"]
            self.requests_used += 1
            return super().get(*args, **kwargs)

    http = LimitedSearch()
    found, errors, skips = discover_github(
        http,
        {"github_queries": ["first", "second"]},
        limits(max_requests=1, max_seconds=30),
    )
    assert len(found) == 100 and http.requests_used == 1 and not errors
    assert any("request/time allowance exhausted" in item["reason"] for item in skips)
    assert metrics(skips)["source_records_fetched"] == 100


def test_configured_search_page_cap_is_coverage_deferral_not_collection_failure():
    http = SearchPages()
    found, errors, skips = discover_github(
        http, {"github_queries": ["first"]}, limits(max_search_pages=1)
    )
    assert len(found) == 100 and len(http.calls) == 1 and not errors
    assert any("not an exhaustive" in item["reason"] for item in skips)


def test_incomplete_search_marker_survives_local_record_budget_stop():
    http = Pages(
        {
            SEARCH: (
                {
                    "items": [{"full_name": f"org/p{i}"} for i in range(100)],
                    "incomplete_results": True,
                },
                {"Link": f'<{SEARCH}?page=2&per_page=100>; rel="next"'},
            )
        }
    )
    _, errors, _ = discover_github(
        http, {"github_queries": ["first"]}, limits(max_source_records=150)
    )
    assert len(http.calls) == 1
    assert any(
        item["reason"] == "GitHub search reports incomplete results" for item in errors
    )


def test_remote_oversized_page_is_accounted_and_reported_without_more_requests():
    http = Pages(
        {SEARCH: ({"items": [{"full_name": f"org/p{i}"} for i in range(6)]}, {})}
    )
    found, errors, skips = discover_github(
        http,
        {"github_queries": ["one", "two"]},
        limits(max_source_records=3),
    )
    assert len(found) == 3 and len(http.calls) == 1
    assert metrics(skips)["source_records_fetched"] == 6
    assert metrics(skips)["source_records_examined"] == 3
    assert any("exceeded its requested page size" in item["reason"] for item in errors)


def test_discovery_rejects_page_size_changes_but_release_pagination_is_unchanged():
    next_url = SEARCH + "?page=2&per_page=50"
    http = Pages({SEARCH: ({"items": []}, {"Link": f'<{next_url}>; rel="next"'})})
    rows, complete, errors = github_pages(
        http, SEARCH, 3, items_key="items", max_records=250
    )
    assert rows == [] and not complete and len(http.calls) == 1
    assert "fixed page size" in errors[0]

    next_assets = ASSETS + "?page=2"
    http = Pages(
        {
            ASSETS: (
                [{"name": "tool-linux-amd64.tgz"}],
                {"Link": f'<{next_assets}>; rel="next"'},
            ),
            next_assets: ([{"name": "tool-linux-arm64.tgz"}], {}),
        }
    )
    rows, complete, errors = github_pages(http, ASSETS, 2)
    assert complete and not errors and len(rows) == 2


def collect(assets, headers=None, release=None, max_asset_pages=1):
    http = Pages(
        {
            BASE: ({"full_name": "org/tool", "stargazers_count": 50}, {}),
            BASE + "/releases/latest": (release or {"id": 1, "tag_name": "v1"}, {}),
            ASSETS: (assets, headers or {}),
        }
    )
    result = github_collect(
        http, CANDIDATE, {"max_release_pages": 1, "max_asset_pages": max_asset_pages}
    )
    return result


def test_mixed_components_expose_inventory_without_inventing_gaps_or_review_flags():
    names = [
        "server-linux-arm64.tgz",
        "server-linux-amd64.tgz",
        "client-linux-amd64.tgz",
        "client-darwin-arm64.tgz",
        "SHA256SUMS",
    ]
    result = collect([{"name": name} for name in names])
    coverage = result["assessment_coverage"]
    assert result["status"] == "supported"
    assert coverage["supported_artifacts"] == [names[0]]
    assert [item["name"] for item in coverage["remaining_inventory"]] == names[1:]
    assert coverage["inventory_complete"] and not coverage["review_required"]
    assert coverage["review_reasons"] == []
    assert coverage["limitations"]  # Runtime/build caveats do not create review flags.
    assert coverage["evidence_urls"] == [ASSETS]
    assert "other components" in result["scope"]


def test_supported_artifact_with_incomplete_pages_retains_a_specific_review_question():
    result = collect(
        [{"name": "tool-linux-arm64.tgz"}], {"Link": f'<{ASSETS}?page=2>; rel="next"'}
    )
    coverage = result["assessment_coverage"]
    assert result["status"] == "supported"
    assert not coverage["inventory_complete"] and coverage["review_required"]
    assert coverage["review_reasons"] == [
        "The selected release's asset inventory is incomplete."
    ]
    assert coverage["evidence_urls"] == [ASSETS]


@pytest.mark.parametrize(
    "extra,assessment",
    [
        ({"name": "tool-universal.tgz"}, "ambiguous"),
        ({"name": "tool-linux-arm64-amd64.tgz"}, "ambiguous"),
        (None, "malformed"),
        ({"name": "tool-linux-arm64.tgz", "size": 0}, "malformed"),
    ],
)
def test_supported_result_keeps_ambiguous_or_malformed_companion_evidence_visible(
    extra, assessment
):
    result = collect([{"name": "tool-linux-arm64.tgz"}, extra])
    coverage = result["assessment_coverage"]
    assert result["status"] == "supported"
    assert coverage["inventory_complete"] and coverage["review_required"]
    assert coverage["remaining_inventory"][0]["assessment"] == assessment
    assert assessment in coverage["review_reasons"][0]
    if assessment == "malformed":
        assert coverage["remaining_inventory"][0]["raw_metadata"] == extra


def test_full_remaining_inventory_is_not_truncated_to_evidence_excerpt_length():
    names = [f"very-long-component-name-{i}-linux-amd64.tar.gz" for i in range(90)]
    result = collect(
        [{"name": "tool-linux-arm64.tgz"}, *[{"name": name} for name in names]]
    )
    coverage = result["assessment_coverage"]
    assert len(coverage["remaining_inventory"]) == 90
    assert coverage["remaining_inventory"][-1]["name"] == names[-1]
    assert not coverage["review_required"]


def test_gap_and_unknown_verdicts_remain_three_way_and_scoped():
    gap = collect([{"name": "tool-linux-amd64.tgz"}])
    assert gap["status"] == "gap"
    assert not gap["assessment_coverage"]["review_required"]
    unknown = collect([{"name": "tool.tar.gz"}])
    assert unknown["status"] == "unknown"
    assert unknown["assessment_coverage"]["review_required"]


def test_surrogate_release_tag_retains_original_and_uses_release_id_citation():
    result = collect(
        [{"name": "tool-linux-arm64.tgz"}], release={"id": 1, "tag_name": "v1\ud800"}
    )
    assert result["status"] == "supported"
    assert result["metadata"]["release_tag"] == "v1\ud800"
    assert (
        next(item for item in result["evidence"] if item["kind"] == "release_notes")[
            "url"
        ]
        == BASE + "/releases/1"
    )


@pytest.mark.parametrize(
    "response",
    [
        CollectionError("HTTP 404 latest release unavailable", status_code=404),
        ([None], {}),
        ({"id": 1, "tag_name": "preview", "prerelease": True}, {}),
    ],
)
def test_missing_latest_release_requires_review_without_inventing_artifact_coverage(response):
    http = Pages(
        {BASE: ({"full_name": "org/tool"}, {}), BASE + "/releases/latest": response, BASE + "/readme": ({"encoding": "base64", "content": ""}, {})}
    )
    result = github_collect(
        http, CANDIDATE, {"max_release_pages": 1, "max_asset_pages": 1}
    )
    coverage = result["assessment_coverage"]
    assert result["status"] == "unknown"
    assert coverage["kind"] == "github_latest_release"
    assert coverage["review_required"] and not coverage["inventory_complete"]
    assert coverage["remaining_inventory"] == []
    assert coverage["evidence_urls"] == [BASE + "/releases/latest"]
    assert bool(result["failures"]) is not (isinstance(response, CollectionError) and response.status_code == 404)


def test_selected_release_without_id_has_evidence_backed_review_reason():
    result = collect([], release={"tag_name": "v1"})
    assert result["status"] == "unknown"
    coverage = result["assessment_coverage"]
    assert coverage["review_required"] and not coverage["inventory_complete"]
    assert coverage["evidence_urls"] == [BASE + "/releases/latest"]
