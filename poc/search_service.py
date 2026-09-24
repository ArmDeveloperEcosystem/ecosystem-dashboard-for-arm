"""KB-first search, catalog identity validation, and transparent catalog reranking.

No language model determines package existence or support. Catalog identities and
software roles remain authoritative; scoped KB evidence can establish use cases.
"""

from __future__ import annotations
import os
import re
import time
import threading
from collections import OrderedDict, Counter
import httpx
from .catalog import Catalog, words
from .kb_client import fetch_kb

from .intent import normal, parse_intent
from .relevance import (
    capability_groups,
    covered_groups,
    requested_attributes,
    verified_attributes,
    query_terms,
    stems,
    kb_evidence,
    database_role,
    remaining_concepts,
    verifies_concepts,
    role_allowed,
    requested_catalog_roles,
    catalog_roles,
    transfer_request,
    transfer_role,
    backup_request,
    backup_role,
)


class SearchService:
    def __init__(self, catalog: Catalog, transport=None):
        self.catalog = catalog
        self.transport = transport
        self.endpoint = os.getenv(
            "ARM_KB_SEARCH_URL", "https://knowledge.armdevtechapi.com/search"
        )
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.word_frequency = Counter()
        self.title_licenses = {}
        for package in catalog.packages:
            self.word_frequency.update(package["_words"])
            self.title_licenses.setdefault(normal(package["title"]), set()).add(
                package["license"]
            )

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
            response = fetch_kb(self.endpoint, query, headers)
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
        intent = parse_intent(
            query,
            previous_query=previous_query,
            filters=filters,
            filters_override=filters_override,
            package_titles=(p["title"] for p in self.catalog.packages),
        )
        constraints = intent.constraints
        subject = intent.subject
        notices = []
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
        if intent.clarification:
            notices.append(intent.clarification)
            return base
        if not normal(query):
            base.update(status="ok", mode="catalog", total=len(self.catalog.packages))
            return base
        groups = capability_groups(subject)
        terms = query_terms(subject)
        attributes = requested_attributes(subject, groups)
        concepts = remaining_concepts(subject, groups, attributes)
        required_roles = requested_catalog_roles(subject)
        transfer = bool(transfer_request(subject))
        backup = backup_request(subject)
        if not terms and not groups:
            notices.append(
                "Describe a capability, for example “databases for storing embeddings”."
            )
            return base
        # Preserve the user's semantic relationships, including workload context.
        # Sorting words or replacing the query with aliases loses that information.
        base["retrieval_query"] = subject
        kb_ok = True
        try:
            hits = self.retrieve(subject)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            hits = []
            kb_ok = False
            notices.append(
                "Knowledge-base search is unavailable. Showing matches from recorded catalog descriptions."
            )
        candidates = {}
        for position, hit in enumerate(hits):
            resolved = self.catalog.resolve_hit(hit)
            for package in resolved:
                # A longer edition name in an article must not supply feature
                # evidence for a shorter differently scoped catalog identity.
                name = normal(package["title"])
                shadowed = any(
                    name != normal(other["title"])
                    and re.search(
                        r"(?<!\w)" + re.escape(name) + r"(?!\w)", normal(other["title"])
                    )
                    for other in resolved
                )
                peers = [
                    other["title"]
                    for other in resolved
                    if other["id"] != package["id"]
                    and normal(other["title"]) != name
                    and not re.search(
                        r"(?<!\w)" + re.escape(normal(other["title"])) + r"(?!\w)", name
                    )
                    and (
                        not groups
                        or all(role_allowed(other, group) for group in groups)
                    )
                ]
                candidates.setdefault(package["id"], []).append(
                    (position, hit, shadowed, peers)
                )
        ranked = []
        for package in self.catalog.packages:
            if (
                constraints["license"] != "all"
                and package["license"] != constraints["license"]
            ):
                continue
            category = constraints["category"]
            if category and normal(category) not in (
                normal(package["category"]),
                normal(package["parent_category"]),
            ):
                continue
            if constraints["tested_only"] and not package["has_recorded_tests"]:
                continue
            name = normal(package["title"])
            exact = subject == name
            if intent.exact_title and not exact:
                continue
            text = normal(package["description"])
            if not exact and not required_roles <= catalog_roles(
                package["description"]
            ):
                continue
            if transfer and not exact and not transfer_role(package):
                continue
            if backup and not exact and not backup_role(package):
                continue
            catalog_groups = covered_groups(package, text, groups)
            overlap = terms & stems(package["_text"])
            # Capability intent and explicit sub-features are separate. Ordinary
            # question/filler words do not become mandatory catalog claims.
            # Without a recognized role, dropping a remaining concept can change
            # the request (packet processing is not packet capture).
            catalog_match = verified_attributes(text, attributes, package) and (
                len(catalog_groups) == len(groups) and verifies_concepts(text, concepts)
                if groups
                else bool(terms) and verifies_concepts(text, concepts, require_all=True)
            )
            best_kb = None
            kb_groups = []
            ambiguous = len(words(name)) == 1 and self.word_frequency[name] >= 6
            for position, hit, shadowed, peers in candidates.get(package["id"], []):
                passage = kb_evidence(
                    package,
                    hit,
                    ambiguous,
                    shadowed,
                    peers,
                    len(self.title_licenses[name]) > 1,
                )
                if not passage:
                    continue
                evidence = text + " " + passage
                matched = covered_groups(package, evidence, groups)
                evidence_match = verified_attributes(
                    evidence, attributes, package
                ) and (
                    len(matched) == len(groups)
                    and verifies_concepts(evidence, concepts)
                    if groups
                    else bool(terms)
                    and verifies_concepts(evidence, concepts, require_all=True)
                )
                if evidence_match:
                    best_kb = (position, hit, passage)
                    kb_groups = matched
                    break
            if not exact and not catalog_match and not best_kb:
                continue
            # A plain database request remains a role request, even when KB evidence
            # describes another product's database dependency.
            if (
                bool(stems("database") & terms)
                and not transfer
                and not backup
                and not exact
                and not database_role(package)
            ):
                continue
            group_matches = catalog_groups if catalog_match else kb_groups
            score = (100 if exact else 0) + 8 * len(group_matches) + 3 * len(overlap)
            if best_kb:
                score += 12 / (1 + best_kb[0])
                source = "kb_and_catalog"
                evidence_url = best_kb[1]["url"]
                reason = (
                    "Matched Arm knowledge-base evidence; package identity verified in this catalog. "
                    + str(package["description"])[:210]
                )
            else:
                source = "catalog_description"
                evidence_url = package["url"]
                reason = (
                    "Matches " + ", ".join(group_matches) + ". "
                    if group_matches
                    else "Matches the recorded package description. "
                ) + str(package["description"])[:210]
            ranked.append(
                (
                    score,
                    {
                        "id": package["id"],
                        "title": package["title"],
                        "reason": reason,
                        "evidence_url": evidence_url,
                        "match_source": source,
                        "category": package["category"],
                        "license": package["license"],
                        "has_recorded_tests": package["has_recorded_tests"],
                    },
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]["title"].lower()))
        base["results"] = [item for _, item in ranked[:50]]
        base["total"] = len(base["results"])
        base["mode"] = "hybrid" if kb_ok else "catalog_fallback"
        base["status"] = "ok" if ranked else ("no_matches" if kb_ok else "unavailable")
        base["retrieval"] = {
            "kb_hits": len(hits),
            "mapped_packages": len(candidates),
            "capabilities": groups,
            "returned_limit": 50,
            "evidence_admitted": sum(
                p["match_source"] == "kb_and_catalog" for _, p in ranked[:50]
            ),
        }
        if constraints["tested_only"]:
            notices.append(
                "Recorded Linux Arm64 tests only. A recorded test is not a guarantee that every test passed; expand the package to review the evidence."
            )
        if not ranked and (attributes or concepts):
            # Search stems are internal matching keys, not words a visitor can
            # meaningfully refine (for example "writing" becomes "write").
            concept_labels = {term for term in words(subject) if stems(term) & concepts}
            notices.append(
                "The available evidence does not verify the requested attributes: "
                + ", ".join(
                    sorted(set(label for label, _ in attributes) | concept_labels)
                )
                + ". Try a broader capability or clarify the requirement."
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
