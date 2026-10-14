"""Scoped provider contract, ordering, cache isolation, and API behavior."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from poc.catalog import Catalog
from poc.runtime import RuntimeConfig
from poc.search_service import SearchService
from poc.server import create_app
from poc.tests.test_catalog_matching import hit, make_catalog, package

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def catalog(tmp_path):
    return make_catalog(
        tmp_path,
        [
            package(
                "redis",
                test_record={
                    "run": {
                        "runner": {"arch": "arm64", "os": "Ubuntu"},
                        "url": "https://ci.example/run",
                    },
                    "tests": {"details": ["failed"]},
                },
            ),
            package("weaviate"),
            package("weaviate", edition="commercial"),
            package("nginx", category="Web", parent_category="Servers"),
        ],
    )


def service_with(catalog, hits, **kwargs):
    return SearchService(
        catalog, transport=lambda *_: {"results": hits}, scope_confirmed=True, **kwargs
    )


def test_catalog_ids_match_unique_scoped_hugo_records():
    catalog = Catalog(ROOT / ".poc/public/poc-catalog.json")
    assert len(catalog.packages) > 1000
    assert len(catalog.by_id) == len(catalog.by_identity) == len(catalog.packages)
    assert all(p["id"].startswith("linux/") for p in catalog.packages)


def test_unconfirmed_contract_never_calls_provider_even_for_matching_name(catalog):
    def forbidden(*_):
        pytest.fail("Default-off scope must not call the provider")

    response = SearchService(catalog, transport=forbidden).search("Redis")
    assert response["mode"] == "kb_unavailable"
    assert response["status"] == "unavailable"
    assert response["results"] == []
    assert "not been confirmed" in " ".join(response["notices"])


@pytest.mark.parametrize(
    "filters,edition",
    [
        ({}, None),
        ({"license": "opensource"}, "open-source"),
        ({"license": "commercial"}, "commercial"),
    ],
)
def test_query_and_explicit_scope_are_sent_without_rewriting(catalog, filters, edition):
    calls = []
    query = "  Could you find open-source tools for packets, with NO guesses?  "

    def capture(endpoint, params, headers):
        calls.append((endpoint, params, headers))
        return {"results": []}

    response = SearchService(catalog, transport=capture, scope_confirmed=True).search(
        query, filters
    )
    assert len(calls) == 1
    expected = {
        "q": query,
        "k": 50,
        "doc_type": "Ecosystem Dashboard",
        "platform": "linux",
    }
    if edition:
        expected["edition"] = edition
    assert calls[0][1] == expected
    assert response["query"] == response["interpreted_query"] == query
    assert response["constraints"]["license"] == filters.get("license", "all")


def test_catalog_descriptions_and_titles_do_not_discover_independent_candidates(
    catalog,
):
    search = service_with(catalog, [])
    for query in (
        "Redis",
        "Current catalog description",
        "Databases",
        "only open-source ones",
    ):
        response = search.search(query)
        assert response["results"] == []
        assert response["mode"] == "kb_scoped"
        assert response["status"] == "no_matches"
        assert response["interpreted_query"] == query


def test_kb_rank_dedup_and_separate_editions_use_current_catalog_details(catalog):
    search = service_with(
        catalog,
        [
            hit(
                "weaviate",
                edition="commercial",
                title="Stale title",
                snippet="Invented claim",
            ),
            hit("nginx"),
            hit("weaviate", edition="commercial"),
            hit("weaviate"),
        ],
    )
    result = search.search("Redis")
    assert [p["id"] for p in result["results"]] == [
        "linux/commercial_packages/weaviate.md",
        "linux/opensource_packages/nginx.md",
        "linux/opensource_packages/weaviate.md",
    ]
    assert result["total"] == 3
    assert all(p["title"] == catalog.by_id[p["id"]]["title"] for p in result["results"])
    assert all(p["reason"] == "Current catalog description" for p in result["results"])
    assert all(p["match_source"] == "kb_scoped" for p in result["results"])


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"url": "https://developer.arm.com/ecosystem-dashboard/linux/?package=redis"},
        hit("redis", doc_type="Article"),
        hit("redis", platform="windows"),
        hit("redis", edition=None),
        hit("redis", edition=["open-source"]),
        hit("redis", url="https://evil.example/?package=redis"),
        hit("redis", url="https://learn.arm.com/learning-paths/redis/"),
        hit(
            "redis",
            url="https://developer.arm.com/ecosystem-dashboard/linux/?package=redis&package=nginx",
        ),
        None,
        7,
    ],
)
def test_any_contract_violation_rejects_entire_batch_and_does_not_cache(catalog, bad):
    calls = []
    responses = iter([{"results": [hit("redis"), bad]}, {"results": [hit("redis")]}])

    def provider(*args):
        calls.append(args)
        return next(responses)

    search = SearchService(catalog, transport=provider, scope_confirmed=True)
    failed = search.search("request")
    assert failed["results"] == []
    assert failed["mode"] == "kb_unavailable"
    assert "contract" in " ".join(failed["notices"])
    assert not search.cache
    assert search.search("request")["total"] == 1
    assert len(calls) == 2


def test_wrong_selected_edition_invalidates_response_before_local_filtering(catalog):
    response = service_with(
        catalog, [hit("weaviate"), hit("weaviate", edition="commercial")]
    ).search("request", {"license": "opensource", "category": "Other"})
    assert response["mode"] == "kb_unavailable"
    assert response["results"] == []


def test_unknown_identity_is_omitted_with_notice_without_title_guessing(catalog):
    result = service_with(
        catalog, [hit("deleted", title="Redis"), hit("nginx")]
    ).search("Redis")
    assert [p["title"] for p in result["results"]] == ["Nginx"]
    assert "Omitted 1 KB hit" in " ".join(result["notices"])


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"results": None},
        {"results": {}},
        {"results": [hit("redis")] * 51},
    ],
)
def test_invalid_provider_envelopes_are_unavailable(catalog, payload):
    search = SearchService(catalog, transport=lambda *_: payload, scope_confirmed=True)
    assert search.search("Redis")["mode"] == "kb_unavailable"
    assert not search.cache


def test_provider_outage_has_no_semantic_catalog_fallback_and_is_not_cached(catalog):
    calls = []

    def fail(*args):
        calls.append(args)
        raise httpx.TimeoutException("PRIVATE PROVIDER DETAILS")

    search = SearchService(catalog, transport=fail, scope_confirmed=True)
    for _ in range(2):
        result = search.search("Redis")
        assert result["results"] == []
        assert result["mode"] == "kb_unavailable"
        assert "PRIVATE" not in str(result)
    assert len(calls) == 2
    assert not search.cache


def test_filters_refine_only_retrieved_candidates_in_original_order(catalog):
    calls = []

    def provider(endpoint, params, _headers):
        calls.append(params)
        return {"results": [hit("nginx"), hit("redis"), hit("weaviate")]}

    search = SearchService(catalog, transport=provider, scope_confirmed=True)
    result = search.search("unaltered query", {"category": "Data", "tested_only": True})
    assert [p["title"] for p in result["results"]] == ["Redis"]
    assert "locally" in " ".join(result["notices"])
    assert "does not guarantee every test passed" in " ".join(result["notices"])
    empty = search.search("unaltered query", {"category": "Imaginary"})
    assert empty["results"] == []
    assert len(calls) == 1
    assert set(calls[0]) == {"q", "k", "doc_type", "platform"}


def test_valid_response_cache_separates_endpoint_query_scope_and_edition(catalog):
    calls = []

    def provider(endpoint, params, headers):
        calls.append((endpoint, dict(params)))
        return {
            "results": [hit("weaviate", edition=params.get("edition", "open-source"))]
        }

    search = SearchService(catalog, transport=provider, scope_confirmed=True)
    assert search.search("request")["total"] == 1
    assert search.search("request")["total"] == 1
    assert search.search("request", {"license": "opensource"})["total"] == 1
    assert (
        search.search("request", {"license": "commercial"})["results"][0]["license"]
        == "commercial"
    )
    search.endpoint = "https://other.example/search"
    search.search("request")
    search.search("Request")
    assert len(calls) == 5
    assert all(key[2:5] == (50, "Ecosystem Dashboard", "linux") for key in search.cache)


def test_cache_expires_and_empty_valid_responses_are_cached(catalog, monkeypatch):
    now = [1000]
    calls = []
    monkeypatch.setattr("poc.search_service.time.monotonic", lambda: now[0])

    def provider(*args):
        calls.append(args)
        return {"results": []}

    search = SearchService(catalog, transport=provider, scope_confirmed=True)
    search.search("request")
    search.search("request")
    assert len(calls) == 1
    now[0] += 301
    search.search("request")
    assert len(calls) == 2


def test_api_rejects_invalid_and_removed_context_fields(catalog):
    service = service_with(catalog, [hit("redis")])
    with TestClient(
        create_app(service=service, config=RuntimeConfig(serve_static=False)),
        base_url="http://127.0.0.1",
    ) as client:
        for body in (
            {"query": "x" * 501},
            {"query": "request", "filters": {"license": "bad"}},
            {"query": "request", "previous_query": "Redis"},
            {"query": "request", "filters_override": True},
        ):
            assert client.post("/api/search", json=body).status_code == 422
        assert (
            client.post(
                "/api/search",
                json={"query": "Redis"},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        result = client.post("/api/search", json={"query": "Redis"})
        assert result.status_code == 200
        assert result.json()["results"][0]["title"] == "Redis"


def test_api_unavailable_is_503_and_process_readiness_does_not_claim_kb_ready(catalog):
    app = create_app(
        service=SearchService(catalog), config=RuntimeConfig(serve_static=False)
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result = client.post("/api/search", json={"query": "Redis"})
        assert result.status_code == 503
        assert result.json()["mode"] == "kb_unavailable"
        assert result.json()["results"] == []
        ready = client.get("/api/ready").json()
        assert ready["status"] == "ready"
        assert ready["readiness_scope"] == "process_only"
        assert ready["scope_configured"] is False
        assert (
            client.get("/api/health").json()["rollout_status"]
            == "blocked_scope_unconfirmed"
        )
