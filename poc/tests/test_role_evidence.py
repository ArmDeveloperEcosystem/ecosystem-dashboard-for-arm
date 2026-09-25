"""Search regressions for software roles, workload evidence, and test filters.

Controlled descriptions and KB passages below are synthetic claims, not statements
about the named products. Their IDs, editions, URLs, and test records originate in
the dashboard catalog; each temporary Catalog rebuilds its own derived fields.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from poc.catalog import Catalog
from poc.search_service import SearchService


ROOT = Path(__file__).resolve().parents[2]

# Captured provider evidence from the 23 September 2026 independent review.
# Only the fields consumed by SearchService are retained; no live KB is needed.
CAPTURED_VECTORSCAN = {
    "title": "Run Vectorscan on Arm",
    "heading": "Run Vectorscan unit tests",
    "snippet": (
        "Document Title: Run Vectorscan on Arm\n"
        "Heading Path: Determine if your processor has SVE > Run Vectorscan unit tests\n\n"
        "Run a check to validate that Vectorscan is built and running correctly:\n\n"
        "```\nls bin && ./bin/unit-hyperscan\n```\n\n"
        "All the unit tests should run successfully. At the end of execution you will see output similar to:\n\n"
        "```\n[----------] Global test environment tear-down\n"
        "[==========] 3746 tests from 33 test cases ran. (197558 ms total)\n"
        "[ PASSED ] 3746 tests.\n```\n\n"
        "You have successfully built and run Vectorscan."
    ),
    "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/vectorscan/install/#run-vectorscan-unit-tests",
}
CAPTURED_METRICS = {
    "title": "Deploy a live sensor dashboard with TimescaleDB and Grafana on Google Cloud C4A",
    "heading": "Who is this for?",
    "snippet": (
        "Document Title: Deploy a live sensor dashboard with TimescaleDB and Grafana on Google Cloud C4A\n"
        "Heading Path: About this Learning Path > Who is this for?\n\n"
        "This is an introductory topic for DevOps engineers, database engineers, and software developers "
        "who want to deploy and operate TimescaleDB on SUSE Linux Enterprise Server (SLES) Arm64, "
        "ingest live time-series sensor data, and visualize it in Grafana."
    ),
    "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/timescaledb-on-gcp/#about-marker",
}


@pytest.fixture
def catalog():
    return Catalog(ROOT / ".poc/public/poc-catalog.json")


def names(response):
    return {row["title"] for row in response["results"]}


def service(catalog, hits=()):
    return SearchService(catalog, transport=lambda _: {"results": list(hits)})


@pytest.fixture
def synthetic_catalog(catalog, tmp_path):
    """Keep dashboard identities while replacing only explicitly named facts."""

    def make(*variants):
        packages = []
        for title, changes in variants:
            license_name = changes.get("license", "opensource")
            original = next(
                p
                for p in catalog.packages
                if p["title"] == title and p["license"] == license_name
            )
            package = deepcopy(original)
            package.update(changes)
            package.pop("_text", None)
            package.pop("_words", None)
            packages.append(package)
        path = tmp_path / "synthetic-role-evidence.json"
        path.write_text(json.dumps({"packages": packages}))
        return Catalog(path)

    return make


@pytest.mark.parametrize(
    "query",
    [
        "Tools to run unit tests",
        "unit testing frameworks",
        "Could you please help me find tools to run unit tests?",
    ],
)
@pytest.mark.parametrize(
    "hits", [(), (CAPTURED_VECTORSCAN,)], ids=["catalog", "captured-kb"]
)
def test_real_unit_testing_results_all_supply_the_requested_role(catalog, query, hits):
    response = service(catalog, hits).search(query)
    # The current catalog has one affirmative unit-testing framework. Assert the
    # whole result set so fixing Benchmark cannot leave another own-tests match.
    assert names(response) == {"Junit5"}
    assert response["constraints"]["tested_only"] is False
    assert all(row["id"] in catalog.by_id for row in response["results"])


def test_generic_testing_request_is_new_software_intent(catalog):
    response = service(catalog, [CAPTURED_VECTORSCAN]).search(
        "tools to run tests", previous_query="vector databases"
    )
    assert {"Junit5", "Robot Framework"} <= names(response)
    assert not {"Benchmark", "Vectorscan", "Qdrant", "Milvus"} & names(response)
    assert response["constraints"]["tested_only"] is False
    assert response["interpreted_query"] == "tools to run tests"


@pytest.mark.parametrize(
    "description, generic, unit",
    [
        ("Benchmark is a framework for writing and running unit tests.", True, True),
        ("Benchmark provides a unit test runner.", True, True),
        ("Benchmark is a browser testing framework.", True, False),
        ("Benchmark runs its own unit tests to validate its build.", False, False),
        (
            "Benchmark uses the Junit5 unit testing framework to test its implementation.",
            False,
            False,
        ),
        ("Benchmark measures code performance, similar to unit tests.", False, False),
        ("Benchmark is not a unit testing framework or test runner.", False, False),
    ],
    ids=[
        "framework",
        "runner",
        "different-testing-kind",
        "own-tests",
        "dependency",
        "comparison",
        "negated",
    ],
)
def test_synthetic_catalog_claims_distinguish_testing_role_and_specialization(
    synthetic_catalog, description, generic, unit
):
    local = synthetic_catalog(("Benchmark", {"description": description}))
    search = service(local)
    assert names(search.search("tools to run tests")) == (
        {"Benchmark"} if generic else set()
    )
    assert names(search.search("tools to run unit tests")) == (
        {"Benchmark"} if unit else set()
    )


@pytest.mark.parametrize(
    "snippet, expected",
    [
        ("Benchmark provides a runner for writing and running unit tests.", True),
        (
            "Run Benchmark's own unit tests to check that Benchmark was built correctly.",
            False,
        ),
        (
            "Benchmark uses the Junit5 unit testing framework to validate its implementation.",
            False,
        ),
        ("Benchmark runs browser tests, which are similar to unit tests.", False),
        ("Benchmark has no unit testing capability.", False),
    ],
    ids=["affirmative-function", "own-tests", "dependency", "comparison", "negated"],
)
def test_synthetic_kb_must_attribute_unit_testing_to_the_package(
    synthetic_catalog, snippet, expected
):
    local = synthetic_catalog(
        ("Benchmark", {"description": "Benchmark is a testing framework."})
    )
    hit = {
        "title": "Benchmark testing capabilities",
        "snippet": snippet,
        "url": "https://developer.arm.com" + local.packages[0]["url"],
    }
    response = service(local, [hit]).search("tools to run unit tests")
    assert names(response) == ({"Benchmark"} if expected else set())
    if expected:
        assert response["results"][0]["match_source"] == "kb_and_catalog"


@pytest.mark.parametrize("followup", [None, "With tests", "With recorded tests"])
def test_testing_role_survives_recorded_test_filters(synthetic_catalog, followup):
    local = synthetic_catalog(
        ("Junit5", {"test_record": None}),
        ("Benchmark", {"description": "Benchmark is a unit testing framework."}),
    )
    assert not local.by_id["linux/opensource_packages/Junit5.md"]["has_recorded_tests"]
    search = service(local)
    query = followup or "unit testing frameworks with recorded Arm64 tests"
    response = search.search(
        query, previous_query="unit testing frameworks" if followup else None
    )
    assert names(response) == {"Benchmark"}
    assert response["constraints"]["tested_only"] is True
    assert all(row["has_recorded_tests"] for row in response["results"])
    if followup:
        contextless = search.search(followup)
        assert not contextless["results"]
        assert contextless["notices"]


def test_sidebar_override_keeps_testing_role_but_can_disable_recorded_filter(
    synthetic_catalog,
):
    local = synthetic_catalog(("Junit5", {"test_record": None}))
    response = service(local).search(
        "unit testing frameworks with recorded Arm64 tests",
        filters={"tested_only": False},
        filters_override=True,
    )
    assert response["constraints"]["tested_only"] is False
    assert names(response) == {"Junit5"}


@pytest.mark.parametrize(
    "query",
    [
        "unit testing frameworks with passing tests",
        "unit testing frameworks except Junit5",
    ],
)
def test_unsupported_test_requirements_still_clarify(catalog, query):
    response = service(catalog).search(query)
    assert not response["results"]
    assert response["notices"]


def test_exact_titles_keep_precedence_over_testing_words(catalog, synthetic_catalog):
    search = service(catalog)
    for title in ("Junit5", "Benchmark", "Vectorscan"):
        assert names(search.search(title)) == {title}
    # Controlled display-title variation retains a real ID and edition.
    local = synthetic_catalog(("Benchmark", {"title": "Benchmark Tests"}))
    response = service(local).search("Show me Benchmark Tests?")
    assert names(response) == {"Benchmark Tests"}
    assert response["results"][0]["id"] == "linux/opensource_packages/benchmark.md"
    assert response["constraints"]["tested_only"] is False


@pytest.mark.parametrize(
    "hits", [(), (CAPTURED_METRICS,)], ids=["catalog", "captured-kb"]
)
def test_real_metrics_database_can_establish_role_across_categories(catalog, hits):
    response = service(catalog, hits).search("A time-series database for metrics")
    assert "VictoriaMetrics" in names(response)
    match = next(
        row for row in response["results"] if row["title"] == "VictoriaMetrics"
    )
    assert match["category"] == "Database"
    assert match["match_source"] == "catalog_description"
    assert response["constraints"]["category"] is None


def test_monitoring_requests_retain_monitoring_role_checks(catalog):
    response = service(catalog).search("Monitoring tools")
    assert "Prometheus" in names(response)
    assert not {"Cloud Hypervisor", "BenchmarkSQL"} & names(response)


@pytest.mark.parametrize("source", ["catalog", "kb"])
@pytest.mark.parametrize(
    "title, base_description, query, positive, incidental, negated",
    [
        (
            "RabbitMQ",
            "RabbitMQ is a message broker.",
            "message broker for telemetry",
            "RabbitMQ supports telemetry workloads by routing telemetry messages.",
            "Prometheus monitors RabbitMQ and collects telemetry about its performance.",
            "RabbitMQ has no support for telemetry workloads.",
        ),
        (
            "Cassandra",
            "Cassandra is a time-series database.",
            "a time-series database for metrics",
            "Cassandra stores metrics from applications.",
            "Use Prometheus to monitor Cassandra and collect metrics about its performance.",
            "Cassandra does not store metrics.",
        ),
    ],
    ids=["broker-telemetry", "database-metrics"],
)
def test_synthetic_workload_is_required_and_does_not_impose_monitoring_category(
    synthetic_catalog,
    source,
    title,
    base_description,
    query,
    positive,
    incidental,
    negated,
):
    for extra, expected in [
        ("", False),
        (positive, True),
        (incidental, False),
        (negated, False),
    ]:
        description = base_description + (" " + extra if source == "catalog" else "")
        local = synthetic_catalog((title, {"description": description}))
        hits = (
            []
            if source == "catalog"
            else [
                {
                    "title": title + " workload guide",
                    "snippet": base_description + " " + extra,
                    "url": "https://developer.arm.com" + local.packages[0]["url"],
                }
            ]
        )
        search = service(local, hits)
        response = search.search(query)
        assert names(response) == ({title} if expected else set()), (
            source,
            extra,
            response,
        )
        assert response["constraints"]["category"] is None
        # Handling a workload does not itself establish an additional role.
        assert not search.search(query + " with monitoring")["results"]


@pytest.mark.parametrize("source", ["catalog", "kb"])
@pytest.mark.parametrize(
    "has_workload, has_monitoring",
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["neither", "workload-only", "monitoring-only", "both"],
)
def test_synthetic_conjunction_requires_both_workload_and_monitoring(
    synthetic_catalog, source, has_workload, has_monitoring
):
    description = "RabbitMQ is a message broker."
    if has_monitoring:
        description += " RabbitMQ is a monitoring solution."
    workload = "RabbitMQ routes telemetry messages." if has_workload else ""
    if source == "catalog":
        description += " " + workload
    local = synthetic_catalog(("RabbitMQ", {"description": description}))
    # The catalog establishes software roles; scoped KB evidence may add the
    # workload. A monitoring role alone cannot consume the telemetry requirement.
    hits = (
        []
        if source == "catalog"
        else [
            {
                "title": "RabbitMQ workload guide",
                "snippet": workload,
                "url": "https://developer.arm.com" + local.packages[0]["url"],
            }
        ]
    )
    response = service(local, hits).search(
        "message broker for telemetry with monitoring"
    )
    expected = {"RabbitMQ"} if has_workload and has_monitoring else set()
    assert names(response) == expected


@pytest.mark.parametrize("source", ["catalog", "kb"])
def test_synthetic_workload_negation_inside_support_clause(synthetic_catalog, source):
    for claim in (
        "RabbitMQ supports no telemetry.",
        "RabbitMQ supports metrics but not telemetry.",
    ):
        description = "RabbitMQ is a message broker."
        if source == "catalog":
            description += " " + claim
        local = synthetic_catalog(("RabbitMQ", {"description": description}))
        hits = (
            []
            if source == "catalog"
            else [
                {
                    "title": "RabbitMQ workload guide",
                    "snippet": claim,
                    "url": "https://developer.arm.com" + local.packages[0]["url"],
                }
            ]
        )
        response = service(local, hits).search("message broker for telemetry")
        assert not response["results"], (source, claim, response)


@pytest.mark.parametrize("source", ["catalog", "kb"])
@pytest.mark.parametrize(
    "claim, expected",
    [
        ("RabbitMQ is a message broker that processes telemetry data.", True),
        ("RabbitMQ is a message broker, while Kafka processes telemetry data.", False),
        ("RabbitMQ is a message broker and Kafka processes telemetry data.", False),
    ],
    ids=["same-subject", "different-subject-while", "different-subject-and"],
)
def test_synthetic_workload_predicate_belongs_to_the_requested_package(
    synthetic_catalog, source, claim, expected
):
    description = claim if source == "catalog" else "RabbitMQ is a message broker."
    local = synthetic_catalog(("RabbitMQ", {"description": description}))
    hits = (
        []
        if source == "catalog"
        else [
            {
                "title": "RabbitMQ workload guide",
                "snippet": claim,
                "url": "https://developer.arm.com" + local.packages[0]["url"],
            }
        ]
    )
    response = service(local, hits).search("message broker for telemetry")
    assert names(response) == ({"RabbitMQ"} if expected else set())


@pytest.mark.parametrize("source", ["catalog", "kb"])
def test_another_products_monitoring_role_cannot_establish_metrics_database_workload(
    catalog, synthetic_catalog, source
):
    claim = (
        "MySQL is a relational database and Prometheus is a monitoring solution "
        "for time-series metrics."
    )
    if source == "catalog":
        local = synthetic_catalog(
            ("MySQL", {"description": claim}), ("VictoriaMetrics", {})
        )
        hits = []
    else:
        local = catalog
        hits = [
            {
                "title": "MySQL and monitoring workloads",
                "snippet": claim,
                "url": "https://learn.arm.com/example/mysql/monitoring/",
            }
        ]
    response = service(local, hits).search("A time-series database for metrics")
    assert "MySQL" not in names(response)
    assert "VictoriaMetrics" in names(response)


@pytest.mark.parametrize(
    "description, expected",
    [
        (
            "Cassandra is a time-series database and a monitoring solution for metrics.",
            True,
        ),
        (
            "Cassandra is a time-series database. A guide explains how to monitor Cassandra with Prometheus.",
            False,
        ),
        ("Cassandra is a time-series database, not a monitoring solution.", False),
    ],
    ids=["affirmative-role", "operational-guide", "negated-role"],
)
def test_synthetic_cross_category_monitoring_needs_an_affirmative_role(
    synthetic_catalog, description, expected
):
    local = synthetic_catalog(
        ("Cassandra", {"description": description, "category": "Database"})
    )
    search = service(local)
    for query in ("monitoring tools", "databases with monitoring"):
        assert names(search.search(query)) == ({"Cassandra"} if expected else set())


def test_synthetic_testing_kb_preserves_edition_attribution(synthetic_catalog):
    description = "Weaviate is a testing framework."
    local = synthetic_catalog(
        ("Weaviate", {"license": "opensource", "description": description}),
        ("Weaviate", {"license": "commercial", "description": description}),
    )
    hit = {
        "title": "Weaviate Enterprise testing",
        "snippet": "The commercial Weaviate Enterprise edition provides a framework for running unit tests.",
        "url": "https://learn.arm.com/example/weaviate-enterprise/testing/",
    }
    search = service(local, [hit])
    assert not search.search("unit testing frameworks", {"license": "opensource"})[
        "results"
    ]
    response = search.search("unit testing frameworks", {"license": "commercial"})
    assert names(response) == {"Weaviate"}
    assert all(row["license"] == "commercial" for row in response["results"])
