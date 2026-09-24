"""Role descriptions may paraphrase a need; extra capabilities still need facts.

Synthetic descriptions below are explicitly controlled inputs, not product claims.
The Memcached excerpt is unchanged public KB evidence captured during review.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from poc.catalog import Catalog
from poc.search_service import SearchService

ROOT = Path(__file__).resolve().parents[2]
MEMCACHED_EVIDENCE = {
    "title": "Deploy Memcached as a cache for MySQL and PostgreSQL on Arm based servers",
    "heading": "Who is this for?",
    "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/memcached_cache/#about-marker",
    "snippet": (
        "Document Title: Deploy Memcached as a cache for MySQL and PostgreSQL on Arm based servers\n"
        "Heading Path: About this Learning Path > Who is this for?\n\n"
        "This is an advanced topic for developers who want to use memcached as their in-memory key-value store."
    ),
}


def names(response):
    return {row["title"] for row in response["results"]}


@pytest.fixture
def catalog():
    return Catalog(ROOT / ".poc/public/poc-catalog.json")


@pytest.mark.parametrize(
    "context",
    ["for a web application", "for our web app", "for the web application"],
)
def test_cache_application_context_keeps_evidence_supported_matches(catalog, context):
    seen_queries = []

    def capture(query):
        seen_queries.append(query)
        return {"results": [MEMCACHED_EVIDENCE]}

    search = SearchService(catalog, transport=capture)
    response = search.search("I need an in-memory key value cache " + context)
    assert "Memcached" in names(response)
    # The KB receives the complete software request, not a shortened keyword list.
    assert context in seen_queries[0]
    assert all(row["id"] in catalog.by_id for row in response["results"])


@pytest.mark.parametrize(
    "description",
    [
        "to route incoming web traffic to backend services",
        "to forward HTTP requests to upstream servers",
        "to send client requests to backend applications",
        "for routing inbound traffic to our backend services",
    ],
)
def test_reverse_proxy_role_description_does_not_require_literal_wording(
    catalog, description
):
    response = SearchService(catalog, transport=lambda _: {"results": []}).search(
        "a reverse proxy " + description
    )
    assert names(response) == {"NGINX", "NGINX Plus", "Haproxy"}


@pytest.fixture
def controlled_catalog(catalog, tmp_path):
    def make(title, description):
        original = next(row for row in catalog.packages if row["title"] == title)
        package = deepcopy(original)
        package["description"] = description
        package.pop("_text", None)
        package.pop("_words", None)
        path = tmp_path / "controlled-description.json"
        path.write_text(json.dumps({"packages": [package]}))
        return Catalog(path)

    return make


@pytest.mark.parametrize(
    "extra",
    [
        "with encryption",
        "with TLS termination",
        "with packet capture",
        "with a web interface",
    ],
)
def test_application_context_does_not_erase_additional_cache_requirements(
    controlled_catalog, extra
):
    local = controlled_catalog(
        "Memcached", "Memcached is an in-memory key-value cache for application data."
    )
    response = SearchService(local, transport=lambda _: {"results": []}).search(
        "an in-memory key value cache for a web application " + extra
    )
    assert response["results"] == []
    assert response["notices"]


@pytest.mark.parametrize(
    "query",
    [
        "a reverse proxy to route incoming web traffic to backend services with encryption",
        "a reverse proxy to forward HTTP requests to upstream servers with packet capture",
        "a reverse proxy to route incoming HTTPS traffic to backend services",
        "a reverse proxy to forward encrypted web traffic to upstream servers",
        "a reverse proxy to route incoming web traffic to backend services with custom protocols",
    ],
)
def test_role_description_does_not_invent_additional_proxy_features(
    controlled_catalog, query
):
    local = controlled_catalog("NGINX", "NGINX is a reverse proxy and web server.")
    response = SearchService(local, transport=lambda _: {"results": []}).search(query)
    assert response["results"] == []
    assert response["notices"]


@pytest.mark.parametrize("collection_supported", [False, True])
def test_metrics_collection_and_querying_remain_evidence_requirements(
    controlled_catalog, collection_supported
):
    description = "VictoriaMetrics is a monitoring solution and time-series database."
    if collection_supported:
        description += (
            " VictoriaMetrics collects metrics and supports querying time-series data."
        )
    local = controlled_catalog("VictoriaMetrics", description)
    response = SearchService(local, transport=lambda _: {"results": []}).search(
        "software to collect and query time series metrics from my servers"
    )
    assert names(response) == ({"VictoriaMetrics"} if collection_supported else set())


@pytest.mark.parametrize("http_supported", [False, True])
def test_explicit_http_is_not_inferred_from_a_generic_proxy_role(
    controlled_catalog, http_supported
):
    description = "NGINX is a reverse proxy for TCP traffic."
    if http_supported:
        description += " NGINX also provides web serving."
    local = controlled_catalog("NGINX", description)
    response = SearchService(local, transport=lambda _: {"results": []}).search(
        "a reverse proxy to forward HTTP requests to upstream servers"
    )
    assert names(response) == ({"NGINX"} if http_supported else set())


def test_application_type_remains_meaningful_without_a_recognized_service_role(catalog):
    response = SearchService(catalog, transport=lambda _: {"results": []}).search(
        "a toolkit for a web application"
    )
    assert "Fast Light ToolKit (FLTK)" not in names(response)
