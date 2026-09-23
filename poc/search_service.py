"""KB-first search, catalog identity validation, and transparent catalog reranking.

No language model determines package existence or support. Capability aliases only
expand query vocabulary; package membership is always established by catalog text.
"""

from __future__ import annotations
import os
import re
import time
import threading
from collections import OrderedDict
import httpx
from .catalog import Catalog, words

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
    "model serving": (
        (
            "llm",
            "inference",
            "serve language models",
            "serving models",
            "run language models",
            "large language model",
            "model serving",
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
        ("web server", "http server", "reverse proxy", "serve web pages"),
        (
            "web server",
            "http server",
            "reverse proxy",
            "web serving",
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
}
STOP = words(
    "a an the i me we us my our want need looking find show discover suggest recommend software packages package tools tool solutions solution for to of on in with that which and or are is can do please linux arm arm64 aarch64 server servers open source opensource commercial only ones those works work supports support use used using help could would you as provide provides designed run running available about it all"
)


def normal(value):
    text = re.sub(
        r"\s+", " ", value.lower().replace("open-source", "open source")
    ).strip()
    for plural, singular in [
        ("databases", "database"),
        ("servers", "server"),
        ("models", "model"),
        ("embeddings", "embedding"),
        ("brokers", "broker"),
        ("queues", "queue"),
    ]:
        text = re.sub(r"\b" + plural + r"\b", singular, text)
    return text


def capability_groups(query):
    text = normal(query)
    return [
        name
        for name, (triggers, _) in CAPABILITIES.items()
        if any(
            re.search(r"(?<!\w)" + re.escape(normal(t)) + r"(?!\w)", text)
            for t in triggers
        )
    ]


class SearchService:
    def __init__(self, catalog: Catalog, transport=None):
        self.catalog = catalog
        self.transport = transport
        self.endpoint = os.getenv(
            "ARM_KB_SEARCH_URL", "https://knowledge.armdevtechapi.com/search"
        )
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def retrieve(self, query):
        with self.lock:
            cached = self.cache.get(query)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
        if self.transport:
            response = self.transport(query)
        else:
            headers = {"User-Agent": "Arm-Ecosystem-Search-PoC/1.0"}
            token = os.getenv("ARM_KB_API_TOKEN")
            if token:
                headers["Authorization"] = "Bearer " + token
            with httpx.Client(
                timeout=12, follow_redirects=False, trust_env=True
            ) as client:
                r = client.get(
                    self.endpoint, params={"q": query, "k": 50}, headers=headers
                )
                r.raise_for_status()
                if len(r.content) > 2_000_000:
                    raise ValueError("KB response exceeds limit")
                response = r.json()
        if not isinstance(response, dict) or not isinstance(
            response.get("results"), list
        ):
            raise ValueError("Invalid KB response")
        hits = [x for x in response["results"][:100] if isinstance(x, dict)]
        with self.lock:
            self.cache[query] = (time.monotonic(), hits)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        return hits

    def search(self, query, filters=None, previous_query=None, filters_override=False):
        filters = dict(filters or {})
        constraints = {
            "license": filters.get("license", "all"),
            "category": filters.get("category"),
            "tested_only": bool(filters.get("tested_only", False)),
        }
        if constraints["category"] in ("", "All", "all"):
            constraints["category"] = None
        notices = []
        original_constraints = constraints.copy()
        q = normal(query)
        refinement = bool(re.match(r"^(only|just|show only|filter|and only)\b", q))
        subject = normal(previous_query) if refinement and previous_query else q
        if not filters_override and ("open source" in q or "opensource" in q):
            constraints["license"] = "opensource"
        if not filters_override and re.search(r"\bcommercial\b", q):
            constraints["license"] = "commercial"
        if not filters_override and re.search(
            r"\b(tested|tests|test records|test evidence)\b", q
        ):
            constraints["tested_only"] = True
        # Do not imply support for constraints that this PoC cannot establish.
        unsupported = re.search(
            r"\b(fastest|cheapest|best performance|tco|apache (?:license|2(?:\.0)?)|mit license|gpl|bsd license|permissive|license|licenses|licensing|gpu|cuda|version|versions|privacy|production ready|production-ready|certified|guarantee|after 20\d\d|before 20\d\d|since 20\d\d|not|no|never|untested|excluding|without)\b",
            q,
        )
        base = {
            "query": query,
            "interpreted_query": subject,
            "results": [],
            "constraints": constraints,
            "notices": notices,
            "mode": "hybrid",
            "status": "no_matches",
            "total": 0,
            "catalog_count": len(self.catalog.packages),
        }
        if unsupported and not any(
            q == normal(p["title"]) for p in self.catalog.packages
        ):
            base["constraints"] = original_constraints
            notices.append(
                "This search cannot verify that constraint from the catalog. Try a software capability, license type, category or recorded-test filter."
            )
            return base
        if refinement and not previous_query:
            notices.append(
                "Start with the kind of software you need, then refine the results."
            )
            return base
        if not q:
            base.update(status="ok", mode="catalog", total=len(self.catalog.packages))
            return base
        groups = capability_groups(subject)
        # Strip platform/license boilerplate before semantic retrieval; it otherwise dominates hits.
        tokens = (
            words(subject)
            - STOP
            - words("recorded verified tests tested test evidence ones")
        )
        if not tokens and not groups:
            notices.append(
                "Describe a capability, for example “databases for storing embeddings”."
            )
            return base
        retrieval_query = " ".join(groups) if groups else " ".join(sorted(tokens))
        base["retrieval_query"] = retrieval_query
        group_vocabulary = set()
        for group in groups:
            group_vocabulary.update(words(normal(" ".join(CAPABILITIES[group][0]))))
        residual = (
            tokens
            - group_vocabulary
            - words(
                "store storing stored data database databases server servers tool tools build building describe need capable capability scalable scale large efficient efficiently high performance"
            )
        )
        kb_ok = True
        try:
            hits = self.retrieve(retrieval_query)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            hits = []
            kb_ok = False
            notices.append(
                "Knowledge-base search is unavailable. Showing matches from recorded catalog descriptions."
            )
        candidates = {}
        for position, hit in enumerate(hits):
            for p in self.catalog.resolve_hit(hit):
                candidates.setdefault(p["id"], (position, hit))
        ranked = []
        for p in self.catalog.packages:
            if (
                constraints["license"] != "all"
                and p["license"] != constraints["license"]
            ):
                continue
            category = constraints["category"]
            if category and normal(category) not in (
                normal(p["category"]),
                normal(p["parent_category"]),
            ):
                continue
            if constraints["tested_only"] and not p["has_recorded_tests"]:
                continue
            name = normal(p["title"])
            exact = q == name or subject == name
            name_match = bool(
                len(name) > 2
                and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", subject)
            )
            text = normal(p["description"])
            group_matches = [
                g
                for g in groups
                if any(
                    re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text)
                    and not re.search(
                        r"(?:\bno|\bnot|\bwithout|\bnon)\W+(?:\w+\W+){0,2}"
                        + re.escape(term),
                        text,
                    )
                    for term in CAPABILITIES[g][1]
                )
            ]
            if "database" in words(subject) and not exact and not name_match:
                if not any(
                    term in text
                    for term in ("database", "data warehouse", "data store")
                ):
                    continue
                if any(
                    term in text[:150]
                    for term in (
                        "benchmark",
                        "driver",
                        "connector",
                        "client",
                        "text-to-sql",
                        "library",
                        "extension",
                    )
                ):
                    continue
            # Named capabilities are constraints: unrelated KB hits cannot populate results.
            if (
                "object storage" in groups
                and any(
                    term in text[:140]
                    for term in (
                        "command-line tool",
                        "command line tool",
                        "client",
                        "sdk",
                    )
                )
                and not exact
            ):
                continue
            if (
                "cache" in groups
                and "memory" in tokens
                and not any(
                    t in text for t in ("in-memory", "in memory", "memory cache")
                )
                and not exact
            ):
                continue
            if (
                "container orchestration" in groups
                and p["category"]
                not in ("Containers and Orchestration", "Platform / Infrastructure")
                and not exact
            ):
                continue
            # A capability mentioned as a client/dependency is not the package's role.
            # Categories provide a conservative role boundary for the pilot.
            if (
                "monitoring" in groups
                and p["category"] not in ("Observability", "Monitoring/Observability")
                and not exact
            ):
                continue
            if (
                "web serving" in groups
                and any(
                    t in text[:160]
                    for t in (
                        "benchmark",
                        "memory allocator",
                        "client library",
                        "testing tool",
                    )
                )
                and not exact
            ):
                continue
            if (
                "message streaming" in groups
                and any(
                    t in text[:160]
                    for t in ("library", "client for", "connector", "benchmark")
                )
                and not exact
            ):
                continue
            if (
                groups
                and residual
                and not all(
                    any(
                        w == term or (len(term) > 4 and w.startswith(term))
                        for w in p["_words"]
                    )
                    for term in residual
                )
                and not exact
            ):
                continue
            if groups and len(group_matches) != len(groups) and not exact:
                continue
            overlap = tokens & p["_words"]
            relevant = bool(
                exact or group_matches or (tokens and len(overlap) == len(tokens))
            )
            if not relevant:
                continue
            kb = candidates.get(p["id"])
            score = (
                (100 if exact else 0)
                + (30 if name_match else 0)
                + 8 * len(group_matches)
                + 3 * len(overlap)
                + (6 / (1 + kb[0]) if kb else 0)
            )
            for g in group_matches:
                score += sum(3 for term in CAPABILITIES[g][1] if term in text[:150])
            if kb:
                reason = (
                    "Knowledge-base match, verified against this catalog entry. "
                    + str(p["description"])[:210]
                )
                source = "kb_and_catalog"
                evidence = kb[1]["url"]
            else:
                reason = (
                    "Matches " + ", ".join(group_matches) + ". "
                    if group_matches
                    else "Matches the recorded package description. "
                ) + str(p["description"])[:210]
                source = "catalog_description"
                evidence = p["url"]
            ranked.append(
                (
                    score,
                    {
                        "id": p["id"],
                        "title": p["title"],
                        "reason": reason,
                        "evidence_url": evidence,
                        "match_source": source,
                        "category": p["category"],
                        "license": p["license"],
                        "has_recorded_tests": p["has_recorded_tests"],
                    },
                )
            )
        ranked.sort(key=lambda x: (-x[0], x[1]["title"].lower()))
        base["results"] = [item for _, item in ranked[:50]]
        base["total"] = len(base["results"])
        base["mode"] = "hybrid" if kb_ok else "catalog_fallback"
        base["status"] = "ok" if ranked else ("no_matches" if kb_ok else "unavailable")
        base["retrieval"] = {
            "kb_hits": len(hits),
            "mapped_packages": len(candidates),
            "capabilities": groups,
            "returned_limit": 50,
        }
        if constraints["tested_only"]:
            notices.append(
                "Recorded Linux Arm64 tests only. A recorded test is not a guarantee that every test passed; expand the package to review the evidence."
            )
        if not ranked and residual:
            notices.append(
                "No matching catalog description verifies all requested terms: "
                + ", ".join(sorted(residual))
                + "."
            )
        if not ranked:
            notices.append(
                "No catalog packages matched the requested capability and filters. Try another description or clear a filter."
            )
        if len(ranked) > 50:
            notices.append(
                "Showing the first 50 matches. Refine your search to narrow the results."
            )
        return base
