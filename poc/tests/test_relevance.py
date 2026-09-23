"""Behavioral regressions for evidence admission and package roles."""

from pathlib import Path
import pytest
from poc.catalog import Catalog
from poc.search_service import SearchService
from poc.relevance import has_positive, verified_attributes


@pytest.fixture
def catalog():
    return Catalog(Path(__file__).resolve().parents[2] / ".poc/public/poc-catalog.json")


def names(response):
    return {p["title"] for p in response["results"]}


@pytest.mark.parametrize(
    "query",
    [
        "What vector databases are available?",
        "I am looking for a vector database",
        "What are some open-source vector databases for Arm Linux?",
        "Help me find a vector database for my app",
    ],
)
def test_question_phrasing_does_not_require_filler_catalog_facts(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    result = service.search(query)
    assert {"Qdrant", "Milvus", "Chroma", "Weaviate"} <= names(result)


@pytest.mark.parametrize("query", ["relational databases", "SQL databases"])
def test_database_role_and_occurrence_scoped_negation(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    result = names(service.search(query))
    assert {"Postgres", "MySQL", "TiDB", "SQLite"} <= result
    assert not {"Sqoop", "OpenCart", "OpenVVC", "Hbase", "BenchmarkSQL"} & result
    assert has_positive(
        "An SQL (relational) and JSON (non-relational) database", ("relational",)
    )
    assert not has_positive("A non-relational database", ("relational",))


def test_broad_database_query_excludes_dependency_and_data_transfer_roles(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    result = names(service.search("database"))
    assert {"Postgres", "MySQL", "Apache CouchDB"} <= result
    assert (
        not {
            "Sqoop",
            "OpenCart",
            "OpenVVC",
            "Hiredis",
            "Bytebase",
            "Minimap2",
            "HMMER",
            "New Relic",
        }
        & result
    )


def test_semantic_workload_order_and_kb_evidence_can_establish_relevance(catalog):
    query = "process jobs asynchronously using background workers"
    seen = []
    hit = {
        "title": "RabbitMQ application workloads",
        "heading": "Background workers",
        "snippet": "RabbitMQ lets background workers process jobs asynchronously using a durable queue.",
        "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/rabbitmq/workers/",
    }

    def retrieve(q):
        seen.append(q)
        return {"results": [hit]}

    local_only = SearchService(catalog, transport=lambda _: {"results": []})
    assert "RabbitMQ" not in names(local_only.search(query))
    service = SearchService(catalog, transport=retrieve)
    response = service.search(query)
    assert seen == [query]
    assert "RabbitMQ" in names(response)
    match = next(p for p in response["results"] if p["title"] == "RabbitMQ")
    assert match["match_source"] == "kb_and_catalog"
    assert match["evidence_url"] == hit["url"]


def test_heading_verb_does_not_establish_another_package_identity(catalog):
    hit = {
        "title": "RabbitMQ application workloads",
        "heading": "Bind queue to exchange",
        "snippet": "RabbitMQ is a message broker for asynchronous background workers.",
        "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/rabbitmq/workers/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    response = names(service.search("message broker"))
    assert "RabbitMQ" in response
    assert "BIND" not in response


@pytest.mark.parametrize(
    "query",
    [
        "geospatial SQL databases",
        "SQL databases supporting geospatial indexes",
        "vector databases with secure lunar replication",
    ],
)
def test_unverified_capability_qualifiers_are_not_discarded(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    response = service.search(query)
    assert not response["results"]
    assert response["notices"]


def test_file_compression_does_not_match_every_compressed_data_structure(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    result = names(service.search("Tools for compressing files"))
    assert {"Gzip", "7-zip", "Pigz"} <= result
    assert "RoaringBitmap" not in result


def test_json_document_storage_and_load_balancing(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    assert "Apache CouchDB" in names(
        service.search("A database to store JSON documents")
    )
    assert "Haproxy" in names(service.search("load balancers"))


@pytest.mark.parametrize(
    "query, expected, forbidden",
    [
        ("graph databases", {"Neo4j", "JanusGraph"}, {"MySQL", "SQLite", "InfluxDB"}),
        (
            "time series databases",
            {"InfluxDB", "TimescaleDB"},
            {"MySQL", "Neo4j", "Oracle Database"},
        ),
        ("Message brokers that implement MQTT", {"Mosquitto"}, {"Kafka", "Redis"}),
        (
            "Web servers that automatically handle HTTPS",
            {"Caddy"},
            {"Apache httpd", "Gunicorn"},
        ),
        ("lossless compression", {"Lz4", "Zstandard"}, {"RoaringBitmap", "KAEzip"}),
        ("Do you have a DNS server?", {"CoreDNS"}, {"Kube-Router", "Avahi"}),
    ],
)
def test_role_subtypes_and_features_are_constraints(
    catalog, query, expected, forbidden
):
    result = names(
        SearchService(catalog, transport=lambda _: {"results": []}).search(query)
    )
    assert expected <= result
    assert not forbidden & result


def test_inflection_matching_does_not_bypass_local_negation():
    assert not verified_attributes(
        "It is not encrypted.", [("encrypted", ("encrypted",))]
    )
    assert not verified_attributes(
        "Without encrypted storage.", [("encrypted", ("encrypted",))]
    )
    assert verified_attributes("It encrypts data.", [("encrypted", ("encrypted",))])


@pytest.mark.parametrize(
    "query, title, snippet, forbidden",
    [
        (
            "software that stores embeddings",
            "Build a vector search index",
            "Use FAISS to store embeddings in a vector database.",
            {"Vector"},
        ),
        (
            "software that stores embeddings",
            "Persistent AI agent memory",
            "The agent stores embeddings in a vector database.",
            {"Agent"},
        ),
        (
            "load balancers",
            "Terraform: implement a load balancer",
            "Terraform provisions a load balancer using cloud infrastructure.",
            {"Terraform"},
        ),
        (
            "web servers",
            "WordPress with MySQL",
            "Install an Apache web server alongside WordPress and MySQL.",
            {"Wordpress", "MySQL"},
        ),
        (
            "tools to serve language models locally",
            "Docker for local language models",
            "Use Docker to run the model serving application locally.",
            {"Docker"},
        ),
        (
            "in-memory cache",
            "MySQL with caching",
            "Cache results from MySQL in an in-memory cache.",
            {"MySQL"},
        ),
        (
            "extract text from scanned documents",
            "Add documents to a vector database",
            "Convert scanned documents and extract text before storing in a vector database.",
            {"Vector"},
        ),
    ],
)
def test_kb_articles_cannot_reassign_a_packages_role(
    catalog, query, title, snippet, forbidden
):
    hit = {
        "title": title,
        "snippet": snippet,
        "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/test/workload/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(query)
    )
    assert not forbidden & result


def test_longer_edition_name_does_not_supply_shorter_packages_features(catalog):
    hit = {
        "title": "NGINX Plus enterprise routing",
        "snippet": "NGINX Plus supports enterprise routing as a web server.",
        "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx-plus/routing/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(
            "web servers with enterprise routing"
        )
    )
    assert "NGINX Plus" in result
    assert "NGINX" not in result


def test_comparison_article_does_not_transfer_database_subtypes(catalog):
    hit = {
        "title": "Compare MySQL and Neo4j graph databases",
        "snippet": "MySQL is a relational database. Neo4j is a graph database for connected data.",
        "url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/databases/comparison/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(
            "graph databases"
        )
    )
    assert "Neo4j" in result
    assert "MySQL" not in result


@pytest.mark.parametrize(
    "query", ["Vector databases except Milvus", "I want something good for my project"]
)
def test_unclear_or_unverified_exclusion_does_not_return_confident_results(
    catalog, query
):
    result = SearchService(catalog, transport=lambda _: {"results": []}).search(query)
    assert not result["results"]
    assert result["notices"]


@pytest.mark.parametrize(
    "query", ["Just the open-source choices", "Only entries with recorded tests"]
)
def test_filter_only_paraphrases_preserve_previous_subject(catalog, query):
    result = SearchService(catalog, transport=lambda _: {"results": []}).search(
        query, previous_query="vector databases"
    )
    assert {"Qdrant", "Milvus"} <= names(result)
    assert result["interpreted_query"] == "vector database"


@pytest.mark.parametrize("query", ["encryption tools", "tools with encryption"])
def test_ungrouped_queries_reject_negative_kb_facts(catalog, query):
    hit = {
        "title": "RabbitMQ security",
        "snippet": "RabbitMQ has no encryption.",
        "url": "https://learn.arm.com/example/rabbitmq/security/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(query)
    )
    assert "RabbitMQ" not in result


def test_identically_named_editions_do_not_share_commercial_evidence(catalog):
    hit = {
        "title": "Weaviate Enterprise security",
        "snippet": "The commercial Weaviate Enterprise edition provides encryption.",
        "url": "https://learn.arm.com/example/weaviate-enterprise/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    assert "Weaviate" not in names(
        service.search("databases with encryption", {"license": "opensource"})
    )
    assert "Weaviate" in names(
        service.search("databases with encryption", {"license": "commercial"})
    )


@pytest.mark.parametrize("query", ["disk cache", "cache on disk"])
def test_meaningful_storage_medium_is_not_a_stopword(catalog, query):
    result = names(
        SearchService(catalog, transport=lambda _: {"results": []}).search(query)
    )
    assert "Bcache" in result
    assert not {"Memcached", "Redis"} & result


def test_toolkit_role_and_transfer_destination_remain_distinct(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    assert names(service.search("TLS toolkit")) == {"OpenSSL"}
    result = names(
        service.search("Software to move data between Hadoop and relational databases")
    )
    assert "Sqoop" in result
    assert not {"TiDB", "MySQL", "Postgres"} & result
    assert "Caddy" in names(service.search("web servers to serve HTTP"))
    assert "Apache CouchDB" in names(service.search("databases to store JSON"))


@pytest.mark.parametrize(
    "snippet",
    [
        "The NGINX deployment automatically mounts a ConfigMap. Download it from https://example.test/nginx.yaml .",
        "The NGINX deployment automatically mounts a ConfigMap. The documentation also discusses HTTPS.",
    ],
)
def test_urls_and_unrelated_automatic_actions_do_not_establish_automatic_https(
    catalog, snippet
):
    hit = {
        "title": "Deploy NGINX",
        "snippet": snippet,
        "url": "https://learn.arm.com/example/nginx/configuration/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(
            "web servers that automatically handle HTTPS"
        )
    )
    assert "Caddy" in result
    assert "NGINX" not in result


@pytest.mark.parametrize(
    "query, expected, forbidden",
    [
        ("I need live backups of MySQL", "Xtrabackup", "Percona Server for MYSQL"),
        ("network packet capture library", "Libpcap", "DPDK"),
    ],
)
def test_generic_requests_preserve_meaningful_qualifiers(
    catalog, query, expected, forbidden
):
    result = names(
        SearchService(catalog, transport=lambda _: {"results": []}).search(query)
    )
    assert expected in result
    assert forbidden not in result


def test_kb_generic_request_does_not_fill_a_missing_capture_fact_from_category(catalog):
    hit = {
        "title": "DPDK networking",
        "snippet": "DPDK provides libraries for fast network packet processing.",
        "url": "https://learn.arm.com/example/dpdk/networking/",
    }
    result = names(
        SearchService(catalog, transport=lambda _: {"results": [hit]}).search(
            "network packet capture library"
        )
    )
    assert "Libpcap" in result
    assert "DPDK" not in result
