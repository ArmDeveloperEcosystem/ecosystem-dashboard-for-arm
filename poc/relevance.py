"""Conservative relevance rules over catalog facts and mapped Arm KB evidence.

Capability vocabulary describes software roles, never package identities. KB passages
can establish a requested use case absent from a short catalog summary; retrieval
rank alone cannot establish relevance or a package's role.
"""

from __future__ import annotations
import re
import threading
from functools import lru_cache
from urllib.parse import urlparse, parse_qs
import snowballstemmer
from .catalog import words
from .intent import normal

# Reviewed vocabulary, not package lists. New capability groups require evaluation.
CAPABILITIES = {
    "vector search": (
        (
            "vector database",
            "vector search",
            "embedding",
            "embeddings",
            "similarity search",
            "semantic search",
            "rag",
        ),
        (
            "vector database",
            "vector search",
            "embedding",
            "similarity search",
            "data as vectors",
        ),
    ),
    "monitoring": (
        ("monitor", "monitoring", "metrics", "observability", "alerting", "telemetry"),
        ("monitoring", "monitor", "metrics", "observability", "alerting", "telemetry"),
    ),
    "software testing": (
        (
            "unit test",
            "unit tests",
            "unit testing",
            "unit-testing",
            "testing framework",
            "testing frameworks",
            "test framework",
            "test frameworks",
            "test automation framework",
            "testing tools",
            "test tools",
            "test runner",
            "test runners",
            "run tests",
            "running tests",
            "execute tests",
            "executing tests",
        ),
        (
            "testing framework",
            "test framework",
            "test automation framework",
            "test runner",
            "testing tool",
            "test tool",
            "test execution",
        ),
    ),
    "model serving": (
        (
            "llm",
            "inference",
            "serve language models",
            "serving models",
            "run language models",
            "large language model",
            "model serving",
            "language model",
        ),
        ("inference", "model serving", "llm", "large language model"),
    ),
    "message streaming": (
        (
            "message broker",
            "message queue",
            "stream events",
            "event streaming",
            "pub/sub",
        ),
        (
            "message broker",
            "messaging broker",
            "message queue",
            "messaging middleware",
            "event streaming",
            "messaging and streaming",
            "messaging platform",
            "streaming data platform",
            "pub/sub",
        ),
    ),
    "cache": (
        ("cache", "caching", "in-memory store"),
        ("cache", "caching", "in-memory data store"),
    ),
    "relational database": (
        (
            "relational database",
            "relational sql database",
            "sql database",
            "relational data",
        ),
        ("relational", "sql database"),
    ),
    "web serving": (
        ("web server", "http server", "serve web pages"),
        ("web server", "http server", "web serving"),
    ),
    "reverse proxy": (
        ("reverse proxy", "reverse proxying"),
        (
            "reverse proxy",
            "reverse proxying",
            "proxy for tcp and http",
        ),
    ),
    "object storage": (
        ("object storage", "s3 compatible", "s3-compatible"),
        ("object storage", "s3-compatible", "s3 compatible"),
    ),
    "container orchestration": (
        ("container orchestration", "manage containers", "orchestrate containers"),
        (
            "container orchestration",
            "automating deployment, scaling, and management of containerized applications",
            "container orchestration platform",
            "orchestration engine",
            "kubernetes service",
            "kubernetes distribution",
            "kubernetes control plane",
            "containerization platform",
            "openshift container platform",
        ),
    ),
    "document database": (
        (
            "document database",
            "json document",
            "store json",
            "storing json",
            "document-oriented database",
        ),
        (
            "document-oriented",
            "document oriented",
            "json document",
            "json for storage",
            "json (non-relational)",
            "including document",
        ),
    ),
    "load balancing": (
        (
            "load balancer",
            "load balancing",
            "balance traffic",
            "distribute traffic",
            "spread requests",
            "distribute http requests",
            "distribute requests",
        ),
        ("load balancer", "load balancing", "spreads requests"),
    ),
    "compression": (
        (
            "compression",
            "compress",
            "compressing",
            "compress files",
            "reduce file size",
            "shrink files",
        ),
        ("compression", "compresses", "compress and decompress"),
    ),
    "database": (
        ("database", "data store", "datastore"),
        (
            "database",
            "data warehouse",
            "data store",
            "datastore",
            "data structure store",
        ),
    ),
    "DNS serving": (
        ("dns server", "domain name server"),
        ("dns server", "dns forwarding", "domain name server"),
    ),
    "TLS": (
        ("tls", "tls connection", "tls connections", "tls protocol", "tls protocols"),
        ("tls", "transport layer security"),
    ),
    "time-series data": (
        (
            "time series",
            "time-series",
            "time-stamped measurements",
            "time stamped measurements",
            "timestamped measurements",
            "time-stamped data",
            "timestamped data",
        ),
        ("time-series", "time series", "time-stamped", "timestamped"),
    ),
    "graph database": (
        ("graph database", "nodes and relationships", "nodes and edges"),
        ("graph database", "graph-based database", "graph based database"),
    ),
    "file archiving": (
        ("file archive", "file archives", "file archiver", "archives", "archiving"),
        ("file archiver", "archiving utility", "archive utility", "archiving tool"),
    ),
}
STOP = words(
    "a an the i me we us my our want need looking find show discover suggest recommend software packages package tools tool solutions solution for to of on in with that which and or are is can do please linux arm arm64 aarch64 server servers open source opensource commercial only ones those works work supports support use used using help could would you as provide provides designed run running available about it all"
)


def transfer_request(query):
    return re.search(
        r"\b(?:move|transfer|copy|migrate|import|export)\b.*?\b(?:between|from|into|to)\b",
        normal(query),
    )


def transfer_role(package):
    text = package["description"]
    patterns = r"\b(?:mov(?:e|ing)|transfer(?:ring)?|migrat\w*|copy\w*|export\w*|import\w*)\b[^.;]{0,65}\bdata\b|\bdata (?:transfer|integration|migration|pipeline)\b"
    return any(
        has_positive(text, (match.group(),))
        for match in re.finditer(patterns, text, re.I)
    )


def backup_request(query):
    """A database can be the object of a backup request rather than the role."""
    text = normal(query)
    head = re.split(r"\b(?:with|that|supporting|supports|requiring|featuring)\b", text)[
        0
    ]
    return bool(
        re.search(r"\b(?:backups?|back(?:ing)? up)\b", head)
        and not re.search(r"\bdatabase\s+(?:for|to)\b", head)
    )


def backup_role(package):
    text = package["description"]
    patterns = (
        r"\b(?:utility|tool|software|application|service)\b[^.;]{0,80}\bbackups?\b",
        r"\bbackup\s+(?:utility|tool|software|application|service)\b",
    )
    return any(
        has_positive(text, (match.group(),))
        for pattern in patterns
        for match in re.finditer(pattern, text, re.I)
    )


def capability_groups(query):
    text = normal(query)
    if backup_request(text):
        return []
    # In a transfer request the database/storage name can be a destination,
    # rather than the role of the software being sought.
    transfer = transfer_request(text)
    if transfer:
        text = text[: transfer.end()].rsplit(" ", 1)[0]
    groups = [
        name
        for name, (triggers, _) in CAPABILITIES.items()
        if any(
            re.search(r"(?<!\w)" + re.escape(normal(t)) + r"(?!\w)", text)
            for t in triggers
        )
    ]
    # A database/broker *for metrics* need not itself be a monitoring tool.
    # The workload remains an independently checked attribute below.
    if (
        monitoring_workload(text)
        and "monitoring" in groups
        and not re.search(r"\b(?:monitor(?:ing)?|observability|alerting)\b", text)
    ):
        groups.remove("monitoring")
    if "database" in groups and any(
        g in groups
        for g in (
            "vector search",
            "relational database",
            "document database",
            "graph database",
        )
    ):
        groups.remove("database")
    if re.search(r"\bqueue\b", text) and re.search(
        r"\b(worker|workers|background|jobs|asynchronous|asynchronously)\b", text
    ):
        groups.append("message streaming")
    return list(dict.fromkeys(groups))


# Grammatical scaffolding affects neither admission nor mandatory attributes.
STOP |= words(
    "what some am there any app application applications service services so get suitable options option possible know tell names listed existing currently available kind kinds types type something looking like use case cases task tasks"
)

STOP |= words(
    "should trying way let good project toward towards team through across several systems system send implement implements implementing handle handles handling store stores storing saved save into programs program utility utilities requiring featuring supporting"
)


_stemmer_local = threading.local()


@lru_cache(maxsize=16384)
def _stem_word(word):
    # Snowball stemmers retain mutable algorithm state. Each request thread must
    # have its own instance; only immutable stem results are shared by the cache.
    if not hasattr(_stemmer_local, "english"):
        _stemmer_local.english = snowballstemmer.stemmer("english")
    return _stemmer_local.english.stemWord(word)


@lru_cache(maxsize=8192)
def stems(value):
    """Normalize English word forms without altering catalog package identities."""
    return frozenset(_stem_word(word) for word in words(normal(value)))


def positive_occurrences(text, phrase):
    """Associate negation with each occurrence, not every mention in the document."""
    text = normal(text)
    pattern = r"(?<!\w)" + re.escape(normal(phrase)) + r"(?!\w)"
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 55) : match.start()]
        suffix = text[match.end() : match.end() + 100]
        before = re.search(
            r"(?:\bnon[- ]|\b(?:no|not(?! only\b)|without|cannot|can't|doesn't|isn't|aren't)\s+(?:\w+\s+){0,2})$",
            prefix,
        )
        after = re.search(
            r"^\s*(?:(?:,|and|or)\s+\w+\s*){0,2}"
            r"(?:(?:support|capability|functionality)\s+)?"
            r"(?:(?:is|are|was|were|remains?)\s+)?"
            r"(?:(?:currently|explicitly)\s+)?"
            r"(?:unsupported|unavailable|missing|absent|disabled|"
            r"not\s+(?:(?:currently|yet)\s+)?(?:supported|available|provided|implemented|enabled))\b",
            suffix,
        )
        if not before and not after:
            yield match


def has_positive(text, phrases):
    return any(any(positive_occurrences(text, phrase)) for phrase in phrases)


def database_role(package):
    """A database role must be asserted, rather than merely used or benchmarked."""
    text = normal(package["description"])
    # Role nouns in the first proposition prevent secondary destinations/dependencies
    # from turning transfer tools, stores, connectors and benchmarks into databases.
    if re.search(
        r"\b(?:benchmark(?:ing)?|online store|connector|database client|database driver|data manipulation|data transfer|move .* data between)\b",
        text[:220],
    ):
        return False
    pattern = r"\b(?:is|are|provides|implements|offers|delivers|as)\b([^.;]{0,170}?)\b(?:database|datastore|data warehouse|data store|data structure store)\b"
    for match in re.finditer(pattern, text):
        prefix = match.group(1)
        # SQLite is a library implementing a database engine; a client library is
        # different. Managed database products remain discoverable as databases.
        implements_engine = "implements" in prefix or match.group().startswith(
            "implements"
        )
        managed_database = bool(
            re.search(r"\b(?:managed solution|replacement) for\b", prefix)
        )
        incidental = re.search(
            r"\b(?:tool|toolset|application|agent|library|connections|interact|interaction|query|queries|schema|using|uses|between|connects|for|types of|align)\b",
            prefix,
        )
        if not incidental or implements_engine or managed_database:
            return True
    return False


_ASSERTION_VERBS = (
    r"is|are|provides|implements|offers|delivers|supports|stores?|ingests?|"
    r"processes|routes?|collects?|handles?|publishes|streams?|transports?|transmits?"
)
_NEW_SUBJECT_CLAUSE = re.compile(
    r"\b(?:and|while|whereas|although|but)\s+"
    r"(?!(?:" + _ASSERTION_VERBS + r"|also|it|they)\b)"
    r"(?:[\w'-]+\s+){1,5}(?:" + _ASSERTION_VERBS + r")\b"
)


def package_assertions(package, text):
    """Affirmative clauses whose subject is this package, not a dependency.

    Catalog identity and article attribution alone cannot turn instructions to
    run a package's tests into a claim that it supplies a testing framework.
    Keep the grammatical owner for the bounded role/workload checks below.
    """
    name = re.escape(normal(package["title"]))
    assertion = re.compile(
        r"(?<!\w)(?:the\s+)?"
        + name
        + r"(?:\s+(?:enterprise|community|professional)(?:\s+edition)?)?"
        r"\s+(?:" + _ASSERTION_VERBS + r")\b[^.;\n]*"
    )
    for match in assertion.finditer(normal(text)):
        # "Package is X and Other is Y" establishes X only for this package.
        # Coordinated noun roles ("a database and a monitoring solution") and
        # predicates with the same subject ("and stores metrics") stay intact.
        yield _NEW_SUBJECT_CLAUSE.split(match.group(), maxsplit=1)[0]


_INCIDENTAL_ROLE = re.compile(
    r"\b(?:uses?|used(?! for\b)|using|depends?|dependencies|requires?|requiring|similar|"
    r"like|via|integrates?|integration|adapter|connector|client for|"
    r"while|whereas|although|but(?! also\b)|"
    r"not(?! only\b)|no|without)\b"
)
_TESTING_ROLE = (
    r"\b(?:(?:unit[- ]|build and )?test(?:ing)?(?: automation)? "
    r"(?:framework|runner|tool|library)|framework for (?:unit[- ])?testing)\b"
)
_MONITORING_ROLE = (
    r"\b(?:monitoring|observability) "
    r"(?:solution|platform|tool|agent|system|suite|framework)\b"
)


def asserted_role(package, text, pattern):
    for assertion in package_assertions(package, text):
        for role in re.finditer(pattern, assertion):
            if _INCIDENTAL_ROLE.search(assertion[: role.start()]):
                continue
            if has_positive(assertion, (role.group(),)):
                return True
    return False


def testing_role(package, text):
    return asserted_role(package, text, _TESTING_ROLE) or unit_testing_evidence(
        package, text
    )


def unit_testing_evidence(package, text):
    """Unit testing must be provided, rather than performed on the package."""
    for assertion in package_assertions(package, text):
        if re.search(
            r"\b(?:own|internal|its)\s+(?:unit[- ]tests?|test suite)\b", assertion
        ):
            continue
        patterns = (
            r"\bunit[- ]test(?:ing)? (?:framework|runner|tool|library)\b",
            r"\b(?:for|supports?|enables?|provides|used for)\b[^.;]{0,70}"
            r"\b(?:writing|running|executing|write|run|execute)\b[^.;]{0,30}\bunit[- ]tests?\b",
            r"\b(?:supports?|provides|implements|offers|enables?) "
            r"(?:unit[- ]testing|unit[- ]test (?:execution|automation))\b",
        )
        if any(
            not _INCIDENTAL_ROLE.search(assertion[: match.start()])
            and not _INCIDENTAL_ROLE.search(match.group())
            and has_positive(assertion, (match.group(),))
            for pattern in patterns
            for match in re.finditer(pattern, assertion)
        ):
            return True
    return False


def monitoring_role(package, text):
    return asserted_role(package, text, _MONITORING_ROLE) or asserted_role(
        package,
        text,
        r"\b(?:provides|offers|implements|delivers) (?:built-in |integrated )?"
        r"(?:monitoring|observability)\b",
    )


def monitoring_workload(subject):
    """Recognize a bounded primary-role + metrics/telemetry workload clause."""
    text = normal(subject)
    match = re.search(
        r"\b(?:for|(?:to )?(?:store|storing|process|processing|route|routing|"
        r"collect|collecting|ingest|ingesting))\s+"
        r"(?:(?:application|infrastructure|sensor)\s+)?(metrics|telemetry)\b",
        text,
    )
    if not match:
        return None
    head = text[: match.start()]
    # Extraction is independent of role composition. Adding "with monitoring"
    # must retain this workload obligation as well as the monitoring role.
    if any(
        re.search(r"(?<!\w)" + re.escape(normal(trigger)) + r"(?!\w)", head)
        for group in ("database", "message streaming", "time-series data")
        for trigger in CAPABILITIES[group][0]
    ):
        return match.group(1)
    return None


def workload_evidence(package, text, workload):
    if re.search(
        r"\b" + re.escape(workload) + r"\b", normal(text)
    ) and not has_positive(text, (workload,)):
        return False
    # Only the package's own catalog role facts establish this inference. A KB
    # article about monitoring a different database cannot supply either role.
    catalog_facts = ". ".join(package_assertions(package, package["description"]))
    if (
        workload == "metrics"
        and monitoring_role(package, catalog_facts)
        and has_positive(catalog_facts, CAPABILITIES["time-series data"][1])
    ):
        return True
    pattern = (
        r"\b(?:stores?|storing|ingests?|ingesting|process(?:es|ing)?|routes?|routing|"
        r"collects?|collecting|handles?|handling|publishes|publishing|streams?|"
        r"streaming|transports?|transporting|transmits?|transmitting|supports?|supporting)\b"
        r"[^.;]{0,70}\b" + re.escape(workload) + r"\b"
    )
    for assertion in package_assertions(package, text):
        for match in re.finditer(pattern, assertion):
            prefix = assertion[: match.start()].strip()
            # The predicate must belong to this package, or continue its own
            # relative/coordinated clause. A later named subject such as
            # "while another product stores telemetry" cannot supply evidence.
            owner = r"(?:the\s+)?" + re.escape(normal(package["title"]))
            owner += r"(?:\s+(?:enterprise|community|professional)(?:\s+edition)?)?"
            owned = bool(re.fullmatch(owner, prefix)) or bool(
                re.search(
                    r"\b(?:that|which|and|for|by)\s+(?:(?:also|directly|can)\s+)?$",
                    prefix + " ",
                )
            )
            if not owned or _INCIDENTAL_ROLE.search(prefix):
                continue
            if _INCIDENTAL_ROLE.search(match.group()):
                continue
            if re.search(r"\b(?:own|internal|its)\b", match.group()):
                continue
            if has_positive(assertion, (workload,)) and has_positive(
                assertion, (match.group(),)
            ):
                return True
    return False


def role_allowed(package, group):
    text = normal(package["description"])
    opening = text[:180]
    if group in (
        "database",
        "relational database",
        "document database",
        "graph database",
    ):
        return database_role(package)
    if group == "vector search":
        return has_positive(text, CAPABILITIES[group][1])
    if group == "object storage":
        return has_positive(
            text, ("object storage", "storage platform", "storage system")
        ) and not any(
            t in opening
            for t in ("command-line tool", "command line tool", "client", "sdk")
        )
    if group == "container orchestration":
        return package["category"] in (
            "Containers and Orchestration",
            "Platform / Infrastructure",
        )
    if group == "monitoring":
        return package["category"] in (
            "Observability",
            "Monitoring/Observability",
        ) or monitoring_role(package, text)
    if group == "software testing":
        return testing_role(package, text)
    if group in ("web serving", "load balancing", "reverse proxy"):
        roles = CAPABILITIES[group][1]
        if group == "reverse proxy":
            # A catalog web server can gain a verified reverse-proxy feature
            # from its own KB passage. A deployment article cannot make an
            # unrelated application into either of these software roles.
            roles += CAPABILITIES["web serving"][1]
        return has_positive(text, roles) and not any(
            t in opening
            for t in ("benchmark", "memory allocator", "client library", "testing tool")
        )
    if group == "message streaming":
        return (
            has_positive(text, CAPABILITIES[group][1])
            or package["category"] == "Messaging/Comms"
        ) and not any(
            t in opening for t in ("library", "client for", "connector", "benchmark")
        )
    if group == "compression":
        return package["category"] == "Compression" or bool(
            re.search(
                r"\b(?:compression (?:tool|utility|algorithm|library)|compress(?:es| and decompress) (?:data|files)|compressor)\b",
                text,
            )
        )
    if group == "file archiving":
        return has_positive(text, CAPABILITIES[group][1])
    if group in ("cache", "model serving", "DNS serving"):
        return has_positive(text, CAPABILITIES[group][1])
    return True


def covered_groups(package, text, groups):
    return [
        g
        for g in groups
        if role_allowed(package, g)
        and (
            testing_role(package, text)
            if g == "software testing"
            else has_positive(text, CAPABILITIES[g][1])
        )
    ]


def requested_attributes(subject, groups):
    """Keep explicit capability qualifiers instead of treating every query word as one.

    Unknown qualifiers are checked against evidence; inability to establish them
    yields no match and a clarification. Conversational wrappers are not facts.
    """
    attributes = []
    if "software testing" in groups and re.search(r"\bunit[- ]test", subject):
        attributes.append(
            ("unit testing role", ("unit test", "unit tests", "unit testing"))
        )
    workload = monitoring_workload(subject)
    if workload:
        attributes.append((workload + " workload", (workload,)))
    if "load balancing" in groups:
        protocols = [
            p for p in ("tcp", "http") if re.search(r"\b" + p + r"\b", subject)
        ]
        for protocol in protocols:
            # Opening a TCP firewall port in a deployment guide is not evidence
            # of TCP load balancing. Protocols must be tied to the requested role.
            phrases = (
                f"{protocol} load balancing",
                f"{protocol} load balancer",
                f"{protocol} proxy",
                f"load balancing {protocol}",
                f"load balancing for {protocol}",
                f"load balancer for {protocol}",
                f"proxy for {protocol}",
                f"proxying {protocol}",
                f"balancing {protocol} traffic",
            )
            # Evidence of a combined TCP-and-HTTP capability also proves an
            # HTTP-only or TCP-only request; query wording need not list both.
            for pair in ("tcp and http", "http and tcp"):
                phrases += (
                    f"proxy for {pair}",
                    f"load balancing for {pair}",
                    f"{pair} load balancer",
                    f"{pair} load balancing",
                )
            attributes.append((f"{protocol.upper()} load balancing", phrases))
    if re.search(r"\bautomatic(?:ally)?\b", subject) and re.search(
        r"\bhttps\b", subject
    ):
        # This is one compound feature, not two words allowed anywhere in an
        # article (for example automatic mounts plus an unrelated HTTPS link).
        attributes.append(
            (
                "automatic HTTPS",
                (
                    "automatic https",
                    "automatically handles https",
                    "automatically enables https",
                    "automatically configures https",
                    "https is automatically enabled",
                ),
            )
        )
    if "monitoring" in groups and re.search(r"\balert(?:s|ing)?\b", subject):
        attributes.append(("alerting", ("alerting", "alerts", "alert")))
    if "vector search" in groups and re.search(
        r"\b(?:store|stores|storing)\b", subject
    ):
        attributes.append(
            (
                "embedding storage",
                (
                    "database",
                    "vector storage",
                    "vector index",
                    "stores vectors",
                    "stores embeddings",
                ),
            )
        )
    if re.search(r"\b(?:locally|local|(?:my|our) own machine)\b", subject):
        attributes.append(
            (
                "local execution",
                (
                    "locally",
                    "local execution",
                    "local machine",
                    "on your machine",
                    "on my own machine",
                    "on our own machine",
                ),
            )
        )
    if re.search(r"\bin[- ]memory\b", subject):
        attributes.append(
            (
                "in-memory",
                ("in-memory", "in memory", "memory cache", "caching data in memory"),
            )
        )
    if re.search(r"\bjson\b", subject):
        attributes.append(("JSON", ("json",)))
    if "compression" in groups and re.search(r"\bfiles?\b", subject):
        attributes.append(
            (
                "file compression",
                (
                    "file compression",
                    "file archiver",
                    "compression tool",
                    "compress files",
                    "compress and decompress files",
                ),
            )
        )
    if "message streaming" in groups and re.search(
        r"\b(?:background|workers?|jobs|asynchronously)\b", subject
    ):
        attributes.append(
            (
                "background job processing",
                (
                    "background worker",
                    "task queue",
                    "job queue",
                    "process jobs",
                    "asynchronously",
                ),
            )
        )
    for feature in (
        "geospatial",
        "encrypted",
        "encryption",
        "persistent",
        "durable",
        "quantized",
        "offline",
        "distributed",
        "multi-tenant",
    ):
        if re.search(r"(?<!\w)" + re.escape(feature) + r"(?!\w)", subject):
            attributes.append((feature, (feature,)))
    # A requested sub-feature is not established simply by the parent capability.
    vocabulary = set(STOP) | words(
        "recorded verified tests tested test evidence storing stored data database databases server servers tools building build capable capability"
    )
    for group in groups:
        vocabulary |= words(" ".join(CAPABILITIES[group][0]))
    for clause in re.split(
        r"\b(?:with|supporting|supports|requiring|featuring)\b", subject
    )[1:]:
        for term in words(clause) - vocabulary:
            if term not in {"json", "local", "locally", "memory"}:
                attributes.append((term, (term,)))
    return attributes


def verified_attributes(text, attributes, package=None):
    for label, phrases in attributes:
        if label == "unit testing role":
            matched = bool(package) and unit_testing_evidence(package, text)
        elif label in ("metrics workload", "telemetry workload"):
            matched = bool(package) and workload_evidence(package, text, phrases[0])
        else:
            matched = has_positive(text, phrases) or (
                len(phrases) == 1 and positive_inflected_phrase(text, phrases[0])
            )
        if not matched:
            return False
    return True


def positive_inflected_phrase(text, phrase):
    """All words of a compound fact must occur together, with positive scope."""
    expected = tuple(
        _stem_word(w.group()) for w in re.finditer(r"[a-z0-9+#]+", normal(phrase))
    )
    if not expected:
        return False
    if len(expected) == 1:
        return expected[0] in positive_stems(text)
    normalized = normal(text)
    tokens = list(re.finditer(r"[a-z0-9+#]+", normalized))
    for start in range(len(tokens) - len(expected) + 1):
        window = tokens[start : start + len(expected)]
        if tuple(_stem_word(t.group()) for t in window) != expected:
            continue
        if any(
            not re.fullmatch(r"[\s-]+", normalized[left.end() : right.start()])
            for left, right in zip(window, window[1:])
        ):
            continue
        if has_positive(
            normalized, (normalized[window[0].start() : window[-1].end()],)
        ):
            return True
    return False


@lru_cache(maxsize=4096)
def positive_stems(text):
    """Inflection coverage cannot turn a negated occurrence into positive evidence."""
    return frozenset(
        stem
        for term in words(text)
        if has_positive(text, (term,))
        for stem in stems(term)
    )


def remaining_concepts(subject, groups, attributes):
    """Keep role specializations and workload context after recognizing a role.

    A generic role match cannot erase 'graph', 'time series' or 'MQTT'. Evidence
    coverage handles inflections; explicit sub-features remain mandatory.
    """
    if "compression" in groups:
        subject = re.sub(r"\bto save (?:disk|storage) space\b", "", subject)
    consumed = set()
    for group in groups:
        consumed |= stems(" ".join(CAPABILITIES[group][0]))
    for _, phrases in attributes:
        consumed |= stems(" ".join(phrases))
    return query_terms(subject) - consumed


def verifies_concepts(text, concepts, *, require_all=False):
    if not concepts:
        return True
    overlap = concepts & positive_stems(text)
    required = (
        len(concepts)
        if require_all
        else (
            len(concepts) if len(concepts) <= 3 else max(3, round(len(concepts) * 0.75))
        )
    )
    return len(overlap) >= required


def query_terms(subject):
    # parse_intent already consumes explicit recorded-test filters. Remaining
    # test words describe requested software, and must retain their meaning.
    return stems(" ".join(words(subject) - STOP))


ROLE_NOUNS = {
    "library": ("library", "libraries"),
    "toolkit": ("toolkit", "toolkits"),
    "driver": ("driver", "drivers"),
    "compiler": ("compiler", "compilers"),
    "web server": (
        "web server",
        "web servers",
        "http server",
        "http servers",
        "web serving",
    ),
}


@lru_cache(maxsize=2048)
def catalog_roles(text):
    """Software role nouns are more precise than general inflection matches.

    A build tool can compile programs without being a compiler. Snowball is
    useful for feature wording, but must not make this role distinction disappear.
    """
    return frozenset(
        role for role, forms in ROLE_NOUNS.items() if has_positive(text, forms)
    )


def requested_catalog_roles(subject):
    """A specific role noun in the request's head must describe the package."""
    head = re.split(r"\b(?:with|that|supporting|supports|requiring)\b", subject)[0]
    return catalog_roles(head)


def kb_evidence(
    package,
    hit,
    ambiguous_name=False,
    shadowed_name=False,
    related_names=(),
    ambiguous_edition=False,
):
    """Reject generic, multi-project or mismatched article identity as role evidence.

    The catalog resolver already validates the Arm URL and real package identity.
    Only evidence associated with this named package is passed to relevance rules.
    """

    # A link's transport scheme is navigation syntax, not evidence that the
    # package implements HTTPS. Keep the original URL separately for citation.
    def facts(value):
        return re.sub(r"\bhttps?://[^\s<>\]\)]+", "", str(value or ""), flags=re.I)

    title = facts(hit.get("title"))
    snippet = facts(str(hit.get("snippet") or "")[:6000])
    scope = normal(title + " " + snippet[:1500])
    commercial = bool(
        re.search(
            r"\b(?:commercial|proprietary)\b|\b(?:paid|enterprise|professional) (?:edition|version|plan)\b|(?<!\w)"
            + re.escape(normal(package["title"]))
            + r" enterprise\b",
            scope,
        )
    )
    community = bool(re.search(r"\b(?:open source|community edition)\b", scope))
    # Identical display names do not make an edition-specific feature common to
    # every catalog record. Unspecified edition evidence is insufficient to add it.
    if package["license"] == "opensource" and commercial:
        return ""
    if ambiguous_edition and (
        (not commercial and not community) or (commercial and community)
    ):
        return ""
    if ambiguous_edition and package["license"] == "commercial" and community:
        return ""
    if shadowed_name:
        return ""
    url = urlparse(str(hit.get("url") or ""))
    direct = parse_qs(url.query).get("package", [""])[0] == package.get("url_id")
    resources = (package.get("metadata", {}).get("optional_info") or {}).get(
        "getting_started_resources"
    ) or {}
    curated = resources.get("arm_content")
    curated_urls = [curated] if isinstance(curated, str) else []
    same_resource = any(
        url._replace(fragment="").geturl().rstrip("/")
        == str(value).split("#")[0].rstrip("/")
        for value in curated_urls
    )
    if ambiguous_name and not (direct or same_resource):
        return ""
    if related_names and not direct:
        # A comparison/deployment article may name several valid packages. Only
        # sentences explicitly about this package establish its extra features.
        own = r"(?<!\w)" + re.escape(package["title"]) + r"(?!\w)"
        others = [r"(?<!\w)" + re.escape(name) + r"(?!\w)" for name in related_names]
        return " ".join(
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+|\n", snippet)
            if re.search(own, sentence, re.I)
            and not any(re.search(pattern, sentence, re.I) for pattern in others)
        )
    if re.search(r"(?<!\w)" + re.escape(package["title"]) + r"(?!\w)", title, re.I):
        return title + " " + facts(hit.get("heading")) + " " + snippet
    return ""
