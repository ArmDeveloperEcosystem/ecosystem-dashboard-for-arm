"""Synthetic HTTP integration, not a live KB semantic-quality evaluation.

Every search crosses two real loopback HTTP connections: the public FastAPI
boundary and its production KBClient talking to a scripted HTTP provider.
"""

import json
import socket
import threading
import time
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn

from poc.evaluation.fixture_kb import (
    DEFAULT_CATALOG,
    MILVUS,
    QDRANT,
    WEAVIATE_COMMERCIAL,
    WEAVIATE_OPEN_SOURCE,
    FixtureKB,
    FixtureReply,
)
from poc.runtime import RuntimeConfig
from poc.server import create_app

QUERY = "Find vector databases for Arm Linux"
RANKED_UNIQUE_IDS = [MILVUS, WEAVIATE_COMMERCIAL, QDRANT, WEAVIATE_OPEN_SOURCE]


@contextmanager
def running_api(provider, **settings):
    config = RuntimeConfig(
        kb_url=provider.endpoint,
        serve_static=False,
        requests_per_minute=1000,
        **{"kb_scope_confirmed": True, "kb_deadline": 1, **settings},
    )
    app = create_app(catalog_path=DEFAULT_CATALOG, config=config)
    # Bind once and pass the open listener to uvicorn, avoiding a port-selection
    # race. Both the application and provider are restricted to loopback.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]),
        daemon=True,
    )
    thread.start()
    try:
        expires = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= expires:
                raise AssertionError("Loopback application did not start")
            time.sleep(0.005)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            trust_env=False,
            timeout=3,
        ) as client:
            assert client.get("/api/ready").status_code == 200
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "Loopback application failed to shut down"
        assert app.state.kb_client._closed


@pytest.fixture
def provider():
    with FixtureKB() as fixture:
        yield fixture


@pytest.fixture
def api(provider):
    with running_api(provider) as client:
        yield client


def search(client, query=QUERY, filters=None):
    body = {"query": query}
    if filters is not None:
        body["filters"] = filters
    return client.post("/api/search", json=body)


def ids(response):
    return [row["id"] for row in response.json()["results"]]


def assert_unavailable(response):
    assert response.status_code == 503, response.text
    result = response.json()
    assert result["status"] == "unavailable"
    assert result["mode"] == "kb_unavailable"
    assert result["results"] == []
    assert result["notices"]


def test_real_http_scoping_preserves_rank_unique_editions_and_current_details(
    api, provider
):
    response = search(api)
    assert response.status_code == 200, response.text
    assert ids(response) == RANKED_UNIQUE_IDS
    result = response.json()
    assert result["status"] == "ok"
    assert result["mode"] == "kb_scoped"
    for row in result["results"]:
        current = provider.by_id[row["id"]]
        assert row["title"] == current["title"]
        assert current["description"] in row["reason"]
        assert row["license"] == current["license"]
        assert row["match_source"] == "kb_scoped"
        assert "SYNTHETIC FIXTURE" not in row["reason"]
    assert provider.requests == [
        {
            "q": [QUERY],
            "k": ["50"],
            "doc_type": ["Ecosystem Dashboard"],
            "platform": ["linux"],
        }
    ]


def test_http_query_is_preserved_without_keyword_or_capability_rewriting(api, provider):
    provider.reply = lambda _: FixtureReply({"results": [provider.hit(QDRANT)]})
    query = "Can I find databases for embeddings & C++ / café?"
    response = search(api, query)
    assert response.status_code == 200
    assert ids(response) == [QDRANT]
    assert provider.requests[0]["q"] == [query]


def test_unknown_identity_is_omitted_with_notice_without_inventing_a_row(api, provider):
    unknown = provider.hit(QDRANT)
    unknown["url"] = (
        "https://developer.arm.com/ecosystem-dashboard/linux/?package=not-in-current-catalog"
    )
    provider.reply = lambda _: FixtureReply(
        {
            "results": [provider.hit(MILVUS), unknown, provider.hit(QDRANT)],
        }
    )
    response = search(api)
    assert response.status_code == 200
    assert ids(response) == [MILVUS, QDRANT]
    assert response.json()["notices"]


def test_only_unknown_identity_is_an_explained_empty_result(api, provider):
    unknown = provider.hit(QDRANT)
    unknown["url"] = (
        "https://developer.arm.com/ecosystem-dashboard/linux/?package=not-in-current-catalog"
    )
    provider.reply = lambda _: FixtureReply({"results": [unknown]})
    response = search(api)
    assert response.status_code == 200
    assert response.json()["status"] == "no_matches"
    assert ids(response) == []
    assert response.json()["notices"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doc_type", None),
        ("platform", None),
        ("edition", None),
        ("doc_type", "Learning Paths"),
        ("platform", "windows"),
        ("edition", "opensource"),
        ("edition", ["open-source"]),
        ("url", None),
        ("url", "https://learn.arm.com/learning-paths/qdrant/?package=qdrant"),
        (
            "url",
            "https://developer.arm.com/ecosystem-dashboard/windows/?package=qdrant",
        ),
        ("url", "https://evil.example/ecosystem-dashboard/linux/?package=qdrant"),
        (
            "url",
            "https://developer.arm.com/ecosystem-dashboard/linux/?package=qdrant&package=milvus",
        ),
    ],
)
def test_invalid_provider_scope_rejects_whole_response_without_partial_rows(
    api, provider, field, value
):
    invalid = provider.hit(QDRANT)
    if value is None:
        invalid.pop(field)
    else:
        invalid[field] = value
    provider.reply = lambda _: FixtureReply(
        {
            "results": [provider.hit(MILVUS), invalid],
        }
    )
    assert_unavailable(search(api))
    assert len(provider.requests) == 1


def test_provider_cannot_return_commercial_edition_into_open_source_scope(
    api, provider
):
    provider.reply = lambda _: FixtureReply(
        {
            "results": [provider.hit(WEAVIATE_COMMERCIAL)],
        }
    )
    assert_unavailable(search(api, "Weaviate", {"license": "opensource"}))
    assert provider.requests[0]["edition"] == ["open-source"]


def test_valid_empty_provider_does_not_fall_back_to_known_catalog_name(api, provider):
    provider.reply = lambda _: FixtureReply()
    response = search(api, "Redis")
    assert response.status_code == 200
    assert response.json()["status"] == "no_matches"
    assert response.json()["mode"] == "kb_scoped"
    assert ids(response) == []


def test_edition_scope_and_original_query_have_separate_http_cache_entries(
    api, provider
):
    combinations = [
        ("Weaviate", {}, [WEAVIATE_COMMERCIAL, WEAVIATE_OPEN_SOURCE]),
        ("Weaviate", {"license": "opensource"}, [WEAVIATE_OPEN_SOURCE]),
        ("Weaviate", {"license": "commercial"}, [WEAVIATE_COMMERCIAL]),
        ("Redis", {}, ["linux/opensource_packages/redis.md"]),
    ]
    for _ in range(2):
        for query, filters, expected in combinations:
            response = search(api, query, filters)
            assert response.status_code == 200
            assert ids(response) == expected
    assert len(provider.requests) == 4
    assert [r.get("edition") for r in provider.requests] == [
        None,
        ["open-source"],
        ["commercial"],
        None,
    ]


def test_local_category_and_recorded_tests_only_narrow_cached_provider_results(
    api, provider
):
    assert ids(search(api)) == RANKED_UNIQUE_IDS
    categorized = search(api, filters={"category": "RAG / Vector Search"})
    assert categorized.status_code == 200
    assert ids(categorized) == [MILVUS, QDRANT]
    assert categorized.json()["notices"]
    tested = search(api, filters={"tested_only": True})
    assert tested.status_code == 200
    assert ids(tested) == [MILVUS, QDRANT, WEAVIATE_OPEN_SOURCE]
    assert tested.json()["notices"]
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "reply",
    [
        FixtureReply({"error": "Synthetic unavailable"}, status=503),
        FixtureReply(raw_body=b"{invalid JSON"),
        FixtureReply({"results": None}),
        FixtureReply({"results": ["not-a-hit"]}),
        FixtureReply({"unexpected": []}),
    ],
    ids=[
        "http_error",
        "invalid_json",
        "null_results",
        "non_object_hit",
        "missing_results",
    ],
)
def test_provider_failure_is_not_cached_and_next_request_can_recover(
    api, provider, reply
):
    provider.reply = lambda _: reply
    assert_unavailable(search(api))
    provider.reply = provider.default_reply
    recovered = search(api)
    assert recovered.status_code == 200, recovered.text
    assert ids(recovered) == RANKED_UNIQUE_IDS
    assert len(provider.requests) == 2


def test_deadline_keeps_slow_http_worker_bounded_then_recovers(provider):
    entered = threading.Event()
    release = threading.Event()

    def reply(_params):
        entered.set()
        assert release.wait(timeout=3)
        return FixtureReply({"results": [provider.hit(QDRANT)]})

    provider.reply = reply
    with running_api(provider, kb_deadline=0.08, kb_max_inflight=1) as client:
        try:
            started = time.monotonic()
            assert_unavailable(search(client))
            assert time.monotonic() - started < 0.75
            assert entered.is_set()
            assert_unavailable(search(client, "another request while worker is busy"))
            assert len(provider.requests) == 1
        finally:
            provider.reply = provider.default_reply
            release.set()
        expires = time.monotonic() + 2
        while True:
            response = search(client)
            if response.status_code == 200:
                break
            assert time.monotonic() < expires, response.text
            time.sleep(0.01)
        assert ids(response) == RANKED_UNIQUE_IDS
        assert len(provider.requests) == 2


def test_unconfirmed_scope_fails_closed_without_contacting_provider(provider):
    with running_api(provider, kb_scope_confirmed=False) as client:
        assert_unavailable(search(client))
        assert_unavailable(search(client, "Redis"))
    assert provider.requests == []


def test_runtime_scope_confirmation_is_an_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("ARM_KB_SCOPE_CONFIRMED", raising=False)
    assert RuntimeConfig.from_env().kb_scope_confirmed is False
    monkeypatch.setenv("ARM_KB_SCOPE_CONFIRMED", "true")
    assert RuntimeConfig.from_env().kb_scope_confirmed is True
    monkeypatch.setenv("ARM_KB_SCOPE_CONFIRMED", "yes")
    with pytest.raises(ValueError, match="ARM_KB_SCOPE_CONFIRMED"):
        RuntimeConfig.from_env()


@pytest.mark.parametrize(
    ("identity", "url_id"),
    [
        ("linux/commercial_packages/star-ccm.md", "siemens-simcenter-star-ccm+"),
        ("linux/opensource_packages/xerces.md", "xerces-c++"),
    ],
)
def test_encoded_plus_slugs_resolve_to_current_rows_over_http(
    api, provider, identity, url_id
):
    assert provider.by_id[identity]["url_id"] == url_id
    hit = provider.hit(identity)
    assert "%2B" in hit["url"]
    provider.reply = lambda _: FixtureReply({"results": [hit]})
    response = search(api, "Synthetic plus-sign package lookup")
    assert response.status_code == 200, response.text
    assert ids(response) == [identity]


def test_every_built_dashboard_row_and_url_share_the_exported_identity():
    class Rows(HTMLParser):
        def __init__(self):
            super().__init__()
            self.identities = {}

        def handle_starttag(self, _tag, attributes):
            row = dict(attributes)
            if row.get("data-catalog-id"):
                identity = row["data-catalog-id"]
                assert identity not in self.identities
                self.identities[identity] = row.get("data-title-urlized")

    catalog = json.loads(DEFAULT_CATALOG.read_text())["packages"]
    parser = Rows()
    parser.feed((DEFAULT_CATALOG.parent / "linux/index.html").read_text())
    assert len(catalog) > 1000
    assert parser.identities == {row["id"]: row["url_id"] for row in catalog}
    for row in catalog:
        assert parse_qs(urlsplit(row["url"]).query)["package"] == [row["url_id"]]
