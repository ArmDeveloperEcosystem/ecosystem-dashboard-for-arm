from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from poc.catalog import Catalog
from poc.search_service import SearchService
from poc.server import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def catalog():
    return Catalog(ROOT / ".poc/public/poc-catalog.json")


@pytest.fixture
def service(catalog):
    return SearchService(catalog, transport=lambda _: {"results": []})


def names(result):
    return {p["title"] for p in result["results"]}


def test_catalog_ids_match_unique_hugo_records(catalog):
    assert len(catalog.packages) > 1000
    assert len(catalog.by_id) == len(catalog.packages)
    assert all(p["id"].startswith("linux/") for p in catalog.packages)


def test_capability_paraphrase_discovers_real_packages(service):
    r = service.search("databases for storing embeddings", {"license": "opensource"})
    assert {"Qdrant", "Milvus", "Chroma", "Weaviate"} <= names(r)
    assert not {"AvxToNeon", "FreeType", "ThirdAI Platform"} & names(r)
    assert all(p["id"] in service.catalog.by_id for p in r["results"])


def test_fake_stale_untrusted_hits_never_create_records(catalog):
    hits = [
        {
            "url": "https://developer.arm.com/ecosystem-dashboard/linux/?package=made-up-db",
            "title": "Qdrant",
        },
        {"url": "https://evil.example/?package=qdrant", "title": "Qdrant"},
        {"url": "javascript:alert(1)", "title": "Qdrant"},
    ]
    assert all(not catalog.resolve_hit(h) for h in hits)


def test_duplicate_display_names_preserve_editions(service):
    r = service.search("Weaviate", {"license": "opensource"})
    assert r["results"]
    assert all(p["license"] == "opensource" for p in r["results"])
    assert r["results"][0]["id"] == "linux/opensource_packages/weaviate.md"


def test_tests_filter_checks_linux_and_architecture(catalog):
    s = SearchService(catalog, transport=lambda _: {"results": []})
    r = s.search("vector databases with recorded Arm64 tests")
    assert r["constraints"]["tested_only"]
    assert all(catalog.by_id[p["id"]]["has_recorded_tests"] for p in r["results"])
    assert all(p["license"] == "opensource" for p in r["results"])


def test_followup_keeps_subject_and_filters(service):
    r = service.search("only open-source ones", previous_query="vector databases")
    assert r["interpreted_query"] == "vector database"
    assert r["constraints"]["license"] == "opensource"
    assert {"Qdrant", "Milvus"} <= names(r)


def test_explicit_sidebar_filter_wins(service):
    r = service.search(
        "open-source vector databases", {"license": "commercial"}, filters_override=True
    )
    assert r["constraints"]["license"] == "commercial"
    assert all(p["license"] == "commercial" for p in r["results"])


def test_unknown_constraints_do_not_silently_pass(service):
    for q in [
        "fastest vector database",
        "databases certified on Arm",
        "databases recommended after 2024",
    ]:
        r = service.search(q)
        assert r["results"] == []
        assert r["notices"]


def test_no_match_empty_and_contextless_followup(service):
    assert not service.search("quantum teleportation hyperdrive")["results"]
    assert service.search("")["status"] == "ok"
    assert not service.search("only open-source ones")["results"]


def test_outage_returns_labelled_catalog_fallback(catalog):
    def fail(_):
        raise httpx.ConnectError("unreachable")

    s = SearchService(catalog, transport=fail)
    r = s.search("vector databases")
    assert r["mode"] == "catalog_fallback"
    assert "Qdrant" in names(r)
    assert any("unavailable" in x for x in r["notices"])


def test_malformed_response_is_safe_fallback(catalog):
    s = SearchService(catalog, transport=lambda _: {"results": None})
    assert s.search("Prometheus")["mode"] == "catalog_fallback"


def test_api_validation_and_local_boundary(service):
    app = create_app(service=service)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/search", json={"query": "x" * 501}).status_code == 422
        assert (
            client.post(
                "/api/search",
                json={"query": "Prometheus", "filters": {"license": "bad"}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/search",
                json={"query": "Prometheus"},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        result = client.post("/api/search", json={"query": "Prometheus"})
        assert result.status_code == 200
        assert result.json()["results"][0]["title"] == "Prometheus"


def test_reviewed_adversarial_queries(service):
    for q in [
        "vector databases with no recorded tests",
        "vector databases with Apache 2.0 licenses",
        "SQL databases supporting geospatial indexes",
    ]:
        result = service.search(q)
        assert not result["results"]
        assert result["notices"]
    assert not {"Qdrant", "Milvus", "Chroma", "Vector"} & names(
        service.search("vector graphics tools")
    )
    assert not {
        "CRI-O",
        "Calico",
        "Qualys Container Security",
        "NVIDIA Container Toolkit",
    } & names(service.search("container orchestration"))
    assert "Kubernetes" in names(service.search("container orchestration"))
    assert not {"MySQL", "Bcache", "NGINX Plus", "Harness CI", "Apache Arrow"} & names(
        service.search("in-memory cache")
    )
    assert names(service.search("tools to serve language models locally")) == {"Ollama"}


def test_malformed_kb_url_is_rejected(catalog):
    assert catalog.resolve_hit({"url": "https://[malformed", "title": "Qdrant"}) == []


def test_malformed_content_length_returns_400(service):
    with TestClient(
        create_app(service=service),
        base_url="http://127.0.0.1:8765",
    ) as c:
        assert (
            c.post(
                "/api/search", content="{}", headers={"Content-Length": "wat"}
            ).status_code
            == 400
        )


def test_package_names_containing_license_words_remain_searchable(service):
    assert "Apache Kafka" in names(service.search("Apache Kafka")) or "Kafka" in names(
        service.search("Kafka")
    )
    actual = next(
        p for p in service.catalog.packages if p["title"].startswith("Apache ")
    )
    assert actual["title"] in names(service.search(actual["title"]))


@pytest.mark.parametrize(
    "query",
    [
        "Message broker",
        "Message brokers",
        "Message queue",
        "Message queues",
        "Stream events with a message broker",
    ],
)
def test_message_service_role_excludes_video_and_client_libraries(service, query):
    result = names(service.search(query))
    assert {"RabbitMQ", "Redis", "Kafka"} <= result
    assert (
        not {
            "Restreamer",
            "Simple Real-time Server (SRS)",
            "MediaMTX",
            "Owncast",
            "Libopus",
            "Sunshine",
            "ACL",
        }
        & result
    )


def test_incidental_capability_mentions_do_not_claim_package_roles(service):
    result = names(service.search("Web servers"))
    assert {"Apache httpd", "Caddy", "NGINX"} <= result
    assert not {"WRK", "Jemalloc"} & result
    result = names(service.search("Monitoring and alerting tools"))
    assert "Prometheus" in result
    assert not {"Cloud Hypervisor", "Harness CI", "Ubuntu Pro"} & result
