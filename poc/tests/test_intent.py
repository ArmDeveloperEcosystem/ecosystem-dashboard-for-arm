"""Query interpretation invariants, independent of catalog relevance/ranking."""

import pytest

from poc.intent import normal, parse_intent


@pytest.mark.parametrize(
    "query",
    [
        "vector databases",
        "What vector databases are available?",
        "What vector databases are available.",
        "I am looking for a vector database",
        "What are some vector databases?",
        "Help me find a vector database for my app",
        "Could you please help me find a vector database for our service?",
        "I'd like to find a vector database.",
        "Can you tell me which vector databases are available?",
        "Are there any vector databases I can use?",
        "  PLEASE   SHOW me VECTOR DATABASES!  ",
    ],
)
def test_framing_does_not_change_software_subject(query):
    intent = parse_intent(query)
    assert intent.subject == "vector database"
    assert not intent.refinement
    assert intent.clarification is None


@pytest.mark.parametrize(
    "need",
    [
        "SQL databases supporting geospatial indexes",
        "a queue so background workers can process jobs asynchronously",
        "locally hosted language models",
        "compression tools for my encrypted files",
        "monitoring tools for our production service",
    ],
)
def test_wrappers_preserve_meaningful_requirements(need):
    plain = parse_intent(need)
    framed = parse_intent(f"Could you help me find {need}?")
    assert framed.subject == plain.subject
    assert framed.constraints == plain.constraints


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("only open-source ones", {"license": "opensource", "tested_only": False}),
        ("Just commercial packages", {"license": "commercial", "tested_only": False}),
        ("Only ones with recorded Arm64 tests", {"license": "all", "tested_only": True}),
        ("with test evidence", {"license": "all", "tested_only": True}),
        ("only open source with recorded tests", {"license": "opensource", "tested_only": True}),
    ],
)
def test_only_supported_filter_followups_inherit_subject(query, expected):
    result = parse_intent(query, previous_query="What vector databases are available?")
    assert result.subject == "vector database"
    assert result.refinement
    assert result.clarification is None
    assert result.constraints == dict(expected, category=None)
    assert parse_intent(query).clarification


@pytest.mark.parametrize("query", ["Only web servers", "Just web servers", "Show only web servers"])
def test_new_subject_never_silently_inherits_previous_subject(query):
    result = parse_intent(query, previous_query="vector databases")
    assert result.subject == "web server"
    assert not result.refinement
    assert result.clarification is None


def test_explicit_sidebar_filters_override_query_filters():
    filters = {"license": "commercial", "tested_only": False, "category": "Data / Memory / State"}
    result = parse_intent(
        "open-source vector databases with recorded tests",
        filters=filters,
        filters_override=True,
    )
    assert result.subject == "vector database"
    assert result.constraints == filters
    assert filters == {"license": "commercial", "tested_only": False, "category": "Data / Memory / State"}


@pytest.mark.parametrize(
    "query",
    [
        "Open-source and commercial vector databases",
        "vector databases or message brokers",
        "vector databases with no recorded tests",
        "SQL databases without JSON support",
        "vector databases with Apache 2.0 licenses",
        "GPU accelerated vector databases",
        "databases recommended after 2024",
        "databases with passing tests",
        "non-commercial vector databases",
    ],
)
def test_unsupported_composition_or_constraints_explain_without_changing_filters(query):
    filters = {"license": "all", "tested_only": False, "category": None}
    result = parse_intent(query, filters=filters)
    assert result.clarification
    assert result.constraints == filters


@pytest.mark.parametrize("title", ["Commercial Example", "MIT License Tools", "NoSQL", "This or That", ".NET"])
def test_exact_real_package_names_are_not_interpreted_as_constraints(title):
    for query in [title, f"Show me {title}?", f"What is {title}?"]:
        result = parse_intent(query, package_titles=[title])
        assert result.subject == normal(title)
        assert result.exact_title
        assert result.clarification is None
        assert result.constraints["license"] == "all"


def test_test_execution_tools_are_not_confused_with_recorded_tests():
    result = parse_intent("tools to run tests")
    assert result.subject == "tools to run tests"
    assert not result.constraints["tested_only"]


def test_hyphenated_quality_adjectives_are_not_license_or_test_filters():
    result = parse_intent("battle-tested commercial-grade message brokers")
    assert result.subject == "battle-tested commercial-grade message broker"
    assert result.constraints["license"] == "all"
    assert not result.constraints["tested_only"]


def test_refinement_strips_previous_license_without_reapplying_it():
    result = parse_intent("only commercial ones", previous_query="open-source vector databases")
    assert result.subject == "vector database"
    assert result.constraints["license"] == "commercial"


def test_filter_refinement_keeps_explicit_sidebar_override():
    result = parse_intent(
        "only open-source ones",
        previous_query="vector databases",
        filters={"license": "commercial"},
        filters_override=True,
    )
    assert result.subject == "vector database"
    assert result.constraints["license"] == "commercial"


def test_empty_query_and_unknown_refinement_have_distinct_meanings():
    assert parse_intent("").subject == ""
    assert parse_intent("").clarification is None
    assert parse_intent("only those", previous_query="vector databases").clarification


def test_normalization_is_idempotent_and_preserves_technical_spelling():
    for query in ["Message BROKERS", "LOAD balancers", "open-source", "C++", ".NET", "S3-compatible"]:
        assert normal(normal(query)) == normal(query)
    assert normal("C++") == "c++"
    assert normal(".NET") == ".net"
