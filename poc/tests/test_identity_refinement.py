"""Named package filters constrain the same catalog identities and editions."""

from pathlib import Path

import pytest

from poc.catalog import Catalog
from poc.intent import normal, parse_intent
from poc.search_service import SearchService


@pytest.fixture(scope="module")
def service():
    catalog = Catalog(
        Path(__file__).resolve().parents[2] / ".poc/public/poc-catalog.json"
    )
    return SearchService(catalog, transport=lambda _: {"results": []})


def ids(response):
    return {package["id"] for package in response["results"]}


@pytest.mark.parametrize(
    "query",
    [
        "only Redis",
        "just Redis",
        "Show only Redis",
        "Redis with recorded tests",
        "only open source Redis",
        "Redis open source with recorded Arm64 tests",
    ],
)
def test_named_wrappers_and_inline_filters_do_not_admit_related_packages(
    service, query
):
    expected = ids(service.search("Redis"))
    assert expected == {"linux/opensource_packages/redis.md"}
    assert ids(service.search(query)) == expected


@pytest.mark.parametrize(
    "query",
    [
        "with recorded tests",
        "only tests",
        "with test evidence",
        "only open source",
        "only open source with recorded Arm64 tests",
        "only commercial",
    ],
)
def test_filter_followups_retain_exact_identity(service, query):
    baseline = ids(service.search("Redis"))
    response = service.search(query, previous_query="Redis")
    assert ids(response) <= baseline
    assert ids(response) == (set() if query == "only commercial" else baseline)
    intent = parse_intent(query, previous_query="Redis", package_titles=["Redis"])
    assert intent.exact_title
    assert intent.refinement


@pytest.mark.parametrize(
    ("query", "previous_query"),
    [
        ("commercial Redis", None),
        ("only commercial", "Redis"),
        ("NGINX Plus with recorded tests", None),
        ("with recorded tests", "NGINX Plus"),
        ("open source Redis Enterprise", None),
        ("only open source", "Redis Enterprise"),
    ],
)
def test_unavailable_exact_edition_is_empty_instead_of_broadened(
    service, query, previous_query
):
    response = service.search(query, previous_query=previous_query)
    assert response["status"] == "no_matches"
    assert not response["results"]


@pytest.mark.parametrize("license", ["opensource", "commercial"])
def test_same_title_editions_keep_their_catalog_ids(service, license):
    expected = {f"linux/{license}_packages/weaviate.md"}
    wording = "open source" if license == "opensource" else "commercial"
    assert ids(service.search(f"only {wording}", previous_query="Weaviate")) == expected
    assert ids(service.search(f"{wording} Weaviate")) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Commercial Example",
        "MIT License Tools",
        "This or That",
        "Recorded Tests",
        ".NET",
    ],
)
@pytest.mark.parametrize("template", ["only {}", "just {}", "{} with recorded tests"])
def test_catalog_title_words_are_not_consumed_as_constraints(title, template):
    intent = parse_intent(template.format(title), package_titles=[title])
    assert intent.subject == normal(title)
    assert intent.exact_title
    assert intent.clarification is None
    assert intent.constraints["license"] == "all"
    assert intent.constraints["tested_only"] == template.endswith("with recorded tests")


def test_wrapped_title_still_starts_a_new_subject(service):
    assert ids(service.search("only Redis", previous_query="vector databases")) == ids(
        service.search("Redis")
    )
    intent = parse_intent(
        "Only web servers", previous_query="Redis", package_titles=["Redis"]
    )
    assert intent.subject == "web server"
    assert not intent.exact_title
    assert not intent.refinement


def test_exact_filters_keep_sidebar_precedence(service):
    response = service.search(
        "commercial Redis",
        filters={"license": "opensource"},
        filters_override=True,
    )
    assert ids(response) == ids(service.search("Redis"))
    assert response["constraints"]["license"] == "opensource"


def test_longer_title_wins_when_its_words_are_also_supported_filters():
    intent = parse_intent(
        "Commercial Example with recorded tests",
        package_titles=["Example", "Commercial Example"],
    )
    assert intent.subject == "commercial example"
    assert intent.exact_title
    assert intent.constraints["license"] == "all"
    assert intent.constraints["tested_only"]


@pytest.mark.parametrize("query", ["I need something fast", "something fast"])
def test_vague_performance_request_asks_for_a_software_need(service, query):
    response = service.search(query)
    assert response["results"] == []
    assert any("kind of software" in notice for notice in response["notices"])
    assert "retrieval_query" not in response


def test_vague_request_check_preserves_real_titles_and_capabilities():
    title = "Fast Light ToolKit"
    assert parse_intent(title, package_titles=[title]).exact_title
    assert parse_intent("fast in-memory cache").clarification is None
