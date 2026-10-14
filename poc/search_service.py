"""KB-led candidate discovery with current-catalog identity validation.

The proposed scoped API contract is opt-in and has not been validated against
an updated live provider. Natural-language queries pass through unchanged.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

import httpx

from .catalog import DOC_TYPE, PLATFORM, Catalog, ScopedContractError
from .kb_client import fetch_kb

KB_LIMIT = 50


class SearchService:
    def __init__(
        self, catalog: Catalog, transport=None, *, endpoint=None, scope_confirmed=False
    ):
        if type(scope_confirmed) is not bool:
            raise ValueError("scope_confirmed must be an explicit boolean")
        self.catalog = catalog
        self.transport = transport or fetch_kb
        self.endpoint = endpoint or os.getenv(
            "ARM_KB_SEARCH_URL", "https://knowledge.armdevtechapi.com/search"
        )
        self.scope_confirmed = scope_confirmed
        self.headers = {"User-Agent": "Arm-Ecosystem-Search/1.0"}
        token = os.getenv("ARM_KB_API_TOKEN")
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def retrieve(self, query, edition):
        if not self.scope_confirmed:
            raise ScopedContractError("Scoped provider contract is not confirmed")
        params = {"q": query, "k": KB_LIMIT, "doc_type": DOC_TYPE, "platform": PLATFORM}
        if edition is not None:
            params["edition"] = edition
        key = (self.endpoint, query, KB_LIMIT, DOC_TYPE, PLATFORM, edition)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                self.cache.move_to_end(key)
                return cached[1]
        response = self.transport(self.endpoint, params, dict(self.headers))
        if not isinstance(response, dict) or not isinstance(
            response.get("results"), list
        ):
            raise ScopedContractError("Missing scoped result list")
        hits = response["results"]
        if len(hits) > KB_LIMIT:
            raise ScopedContractError("Provider exceeded the requested result limit")
        # Validate every hit before admitting or caching any result, including
        # duplicates and hits a later local filter would otherwise remove.
        mapped = []
        omitted = 0
        seen = set()
        for hit in hits:
            packages = self.catalog.resolve_hit(hit, edition=edition)
            if not packages:
                omitted += 1
                continue
            package = packages[0]
            if package["id"] in seen:
                continue
            seen.add(package["id"])
            mapped.append(package)
        validated = (mapped, omitted)
        with self.lock:
            self.cache[key] = (time.monotonic(), validated)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        return validated

    def search(self, query, filters=None):
        supplied = filters or {}
        constraints = {
            "license": supplied.get("license", "all"),
            "category": supplied.get("category"),
            "tested_only": supplied.get("tested_only", False),
        }
        edition = {
            "all": None,
            "opensource": "open-source",
            "commercial": "commercial",
        }[constraints["license"]]
        base = {
            "query": query,
            "interpreted_query": query,
            "results": [],
            "constraints": constraints,
            "notices": [],
            "mode": "kb_scoped",
            "status": "no_matches",
            "total": 0,
            "catalog_count": len(self.catalog.packages),
        }

        def unavailable(notice):
            base.update(mode="kb_unavailable", status="unavailable")
            base["notices"].append(notice)
            return base

        if not self.scope_confirmed:
            return unavailable(
                "Knowledge-base search is unavailable: the scoped API contract has not "
                "been confirmed. Browse packages by name using the dashboard search."
            )
        if not query.strip():
            base["notices"].append("Enter a description to search the knowledge base.")
            return base
        try:
            mapped, omitted = self.retrieve(query, edition)
        except ScopedContractError:
            return unavailable(
                "Knowledge-base search is unavailable: the provider response did not "
                "satisfy the required dashboard, Linux, edition, and canonical URL contract. "
                "Browse packages by name using the dashboard search."
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return unavailable(
                "Knowledge-base search is temporarily unavailable. "
                "Browse packages by name using the dashboard search."
            )
        notices = base["notices"]
        notices.append(
            "Results cover up to the first 50 KB-ranked hits in the selected scope; "
            "they are not an exhaustive catalog search."
        )
        if omitted:
            notices.append(
                f"Omitted {omitted} KB hit(s) whose package identity is absent from the current catalog."
            )
        if constraints["category"] or constraints["tested_only"]:
            notices.append(
                "Category and recorded-test filters are applied locally to this bounded KB result set. "
                "Matching packages outside that set may not appear."
            )
        if constraints["tested_only"]:
            notices.append(
                "Recorded Linux Arm64 tests only. A recorded test does not guarantee every test passed; "
                "open the package to review the evidence."
            )
        for package in mapped:
            category = constraints["category"]
            if category and category.casefold() not in (
                package["category"].casefold(),
                package["parent_category"].casefold(),
            ):
                continue
            if constraints["tested_only"] and not package["has_recorded_tests"]:
                continue
            base["results"].append(
                {
                    "id": package["id"],
                    "title": package["title"],
                    "reason": package["description"],
                    "evidence_url": package["url"],
                    "match_source": "kb_scoped",
                    "category": package["category"],
                    "license": package["license"],
                    "has_recorded_tests": package["has_recorded_tests"],
                }
            )
        base["total"] = len(base["results"])
        base["status"] = "ok" if base["results"] else "no_matches"
        if not base["results"]:
            notices.append(
                "No matching current catalog packages were found in this KB result set."
            )
        return base
