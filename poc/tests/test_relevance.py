"""Behavioral regressions for evidence admission and package roles."""

from pathlib import Path
import pytest
from poc.catalog import Catalog
from poc.search_service import SearchService
from poc.relevance import has_positive, verified_attributes, stems


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


@pytest.mark.parametrize(
    "queries, required, forbidden",
    [
        (
            (
                "I am trying to find a toolkit for TLS connections.",
                "Can we get a toolkit for TLS connections?",
                "Could you find a TLS toolkit with QUIC?",
            ),
            {"OpenSSL"},
            {"curl", "Apache httpd", "MySQL"},
        ),
        (
            (
                "Please help us automate configuration management with playbooks.",
                "Configuration management automation with playbooks",
                "Tools for automating configuration management using playbooks",
            ),
            {"Ansible"},
            {"Terraform", "Red Hat Ansible Automation Platform"},
        ),
        (
            (
                "I would like a database built around nodes and relationships.",
                "A database for nodes and edges",
                "Please show graph databases",
            ),
            {"Neo4j", "JanusGraph"},
            {"MySQL", "Qdrant", "Sqoop"},
        ),
        (
            (
                "Is there a web server that deals with HTTPS automatically?",
                "Is there a web server with automatic HTTPS?",
                "Could I use a web server that automatically handles HTTPS?",
            ),
            {"Caddy"},
            {"NGINX", "MySQL", "Wordpress", "Gunicorn"},
        ),
        (
            (
                "Which open-source databases are meant for time-stamped measurements?",
                "Databases for timestamped measurements",
                "Open-source databases designed for time-stamped data",
            ),
            {"TimescaleDB", "InfluxDB"},
            {"Neo4j", "Qdrant", "Chroma"},
        ),
        (
            (
                "Could I get a tool to convert scans into text?",
                "Tools for converting scanned documents into text",
                "Please find a tool for converting scans to text",
            ),
            {"Tesseract"},
            {"Vector", "Agent", "Benchmark"},
        ),
        (
            (
                "Read and write geospatial data formats",
                "Libraries for reading and writing geospatial formats",
                "A library for reading and writing geospatial data formats",
            ),
            {"Geospatial Data Abstraction Library (GDAL)"},
            {"Apache Arrow", "Benchmark"},
        ),
        (
            (
                "Programs to make ZIP archives",
                "Programs to create ZIP archives",
                "ZIP file archivers",
            ),
            {"7-zip"},
            {"RoaringBitmap", "Vector", "Gzip"},
        ),
    ],
)
def test_reported_recall_misses_and_distinct_paraphrases(
    catalog, queries, required, forbidden
):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    for query in queries:
        response = service.search(query)
        actual = names(response)
        assert required <= actual, (query, response)
        assert not forbidden & actual, (query, response)
        if "open-source" in query.lower():
            assert all(p["license"] == "opensource" for p in response["results"])


@pytest.mark.parametrize(
    "query",
    [
        "TLS toolkit with lunar encryption",
        "Graph databases with lunar replication",
        "Archiving tools supporting unsupportedzip",
        "Automate configuration management with lunar playbooks",
        "Databases for time-stamped measurements with geospatial indexes",
        "Programs to make ZIP archives with lunar encryption",
    ],
)
def test_new_capability_vocabulary_preserves_unverified_requirements(catalog, query):
    response = SearchService(catalog, transport=lambda _: {"results": []}).search(query)
    assert not response["results"]
    assert response["notices"]


def test_inflections_are_consistent_under_concurrent_requests():
    from concurrent.futures import ThreadPoolExecutor

    forms = [
        ("write", "writing"),
        ("automate", "automation"),
        ("archive", "archives", "archiver"),
        ("scan", "scanned", "scanning"),
        ("connect", "connections"),
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(lambda terms: [stems(t) for t in terms], forms * 40))
    assert all(all(stem == batch[0] for stem in batch) for batch in batches)


@pytest.mark.parametrize("query", ["compilers", "Can you find a compiler?"])
def test_compiler_role_is_not_inferred_from_compilation_actions(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search(query))
    assert {"Clang", "GNU Toolchain (GCC)", "LLVM Flang"} <= actual
    assert not {"Apache Ant", "Gradle", "CUDA-GDB", "OpenEmbedded (Yocto)"} & actual


def test_library_role_plural_remains_distinct_from_toolkit(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    for query in ("TLS library", "TLS libraries"):
        actual = names(service.search(query))
        assert "GnuTLS" in actual
        assert "OpenSSL" not in actual  # Catalog identifies this as a toolkit.
    assert names(service.search("TLS toolkit")) == {"OpenSSL"}


@pytest.mark.parametrize(
    "description, expected",
    [
        ("A multi-model database.", False),
        ("A multi-model database with tenant metadata.", False),
        ("Not a multi-tenant database.", False),
        ("A multi-tenant database.", True),
        ("A multi tenant database.", True),
    ],
)
def test_compound_attributes_require_every_word_in_a_positive_phrase(
    description, expected
):
    assert (
        verified_attributes(description, [("multi-tenant", ("multi-tenant",))])
        is expected
    )


def test_partial_compound_kb_evidence_does_not_establish_multi_tenancy(catalog):
    hit = {
        "title": "Qdrant multi-model deployment",
        "snippet": "Qdrant is a multi-model vector database with tenant metadata.",
        "url": "https://learn.arm.com/example/qdrant/multi-model/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    assert "Qdrant" not in names(service.search("multi-tenant vector databases"))


@pytest.mark.parametrize(
    "query",
    [
        "I need a utility for live MySQL database backups.",
        "Tools for live backups of MySQL databases",
        "Live MySQL database backup tools",
        "Back up MySQL databases live",
    ],
)
def test_database_can_be_the_object_of_a_backup_request(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search(query))
    assert "Xtrabackup" in actual
    assert not {"MySQL", "Percona Server for MYSQL", "Keepalived"} & actual


def test_database_role_remains_required_when_backups_are_a_feature(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search("databases with enhanced backups"))
    assert "Percona Server for MYSQL" in actual
    assert "Xtrabackup" not in actual


def test_exact_short_package_name_does_not_admit_incidental_mentions(catalog):
    hit = {
        "title": "Cassandra with R",
        "snippet": "Cassandra can be queried from the R programming language.",
        "url": "https://learn.arm.com/example/cassandra/r/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    assert names(service.search("R")) == {"R"}
    assert names(service.search("Please find R")) == {"R"}
    editions = service.search("Weaviate")["results"]
    assert {p["id"] for p in editions} == {
        p["id"] for p in catalog.packages if p["title"] == "Weaviate"
    }


def test_redis_compatible_datastore_is_not_a_relational_database(catalog):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    assert "Dragonflydb (Dragonfly)" in names(service.search("in-memory data store"))
    assert "Dragonflydb (Dragonfly)" not in names(service.search("SQL databases"))


def test_open_firewall_protocol_does_not_establish_protocol_load_balancing(catalog):
    hit = {
        "title": "Install NGINX",
        "snippet": "Install NGINX. Allow HTTP traffic: sudo ufw allow 80/tcp.",
        "url": "https://learn.arm.com/example/nginx/install/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    actual = names(
        service.search("Find a load balancer for TCP and HTTP applications.")
    )
    assert "Haproxy" in actual
    assert "NGINX" not in actual


def test_scoped_protocol_load_balancing_evidence_is_admitted(catalog):
    hit = {
        "title": "NGINX TCP and HTTP load balancing",
        "snippet": "NGINX provides TCP and HTTP load balancing for application traffic.",
        "url": "https://learn.arm.com/example/nginx/load-balancing/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    actual = names(
        service.search("Find a load balancer for TCP and HTTP applications.")
    )
    assert {"Haproxy", "NGINX"} <= actual


@pytest.mark.parametrize(
    "statement",
    [
        "Encryption is not supported by RabbitMQ.",
        "Encryption support is unavailable in RabbitMQ.",
        "Encryption and compression are not supported by RabbitMQ.",
        "RabbitMQ doesn't support encryption.",
    ],
)
def test_support_negation_on_either_side_of_a_fact_is_not_positive_evidence(
    catalog, statement
):
    hit = {
        "title": "RabbitMQ security",
        "snippet": statement,
        "url": "https://learn.arm.com/example/rabbitmq/security/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    assert "RabbitMQ" not in names(service.search("encryption tools"))


def test_positive_occurrences_survive_other_negative_occurrences():
    assert has_positive(
        "Encryption was unavailable in old releases. The current release supports encryption.",
        ("encryption",),
    )
    assert has_positive(
        "It supports not only encryption but also authentication.", ("encryption",)
    )
    assert not verified_attributes(
        "Encrypted storage is unsupported.",
        [("encrypted storage", ("encrypted storage",))],
    )


@pytest.mark.parametrize(
    "query", ["Just web servers", "HTTP servers", "Can you find a web server?"]
)
def test_explicit_web_server_role_does_not_inherit_every_proxy(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search(query))
    assert {"Apache httpd", "NGINX", "Caddy"} <= actual
    assert "Haproxy" not in actual
    assert "Haproxy" in names(service.search("reverse proxy"))


@pytest.mark.parametrize(
    "query",
    [
        "What can distribute HTTP requests across several servers?",
        "A load balancer for HTTP applications",
        "A load balancer for TCP applications",
    ],
)
def test_combined_protocol_fact_can_satisfy_one_requested_protocol(catalog, query):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search(query))
    assert "Haproxy" in actual
    assert not {"MySQL", "WRK", "Gunicorn"} & actual


def test_combined_web_server_and_reverse_proxy_query_requires_both_capabilities(
    catalog,
):
    service = SearchService(catalog, transport=lambda _: {"results": []})
    actual = names(service.search("Reverse proxy web servers"))
    assert {"NGINX", "NGINX Plus"} <= actual
    assert not {"Haproxy", "Gunicorn", "WRK", "MySQL", "Caddy"} & actual
    assert "Haproxy" in names(service.search("reverse proxy"))
    assert "Gunicorn" not in names(service.search("reverse proxy"))


def test_web_server_can_gain_reverse_proxy_capability_from_its_own_evidence(catalog):
    hit = {
        "title": "Configure Caddy as a reverse proxy",
        "snippet": "Caddy's reverse proxy handles incoming requests to upstream application services.",
        "url": "https://learn.arm.com/example/caddy/proxy/",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    assert "Caddy" in names(service.search("Reverse proxy web servers"))
