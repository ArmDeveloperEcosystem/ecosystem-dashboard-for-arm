"""Bounded query interpretation for catalog-grounded package discovery.

This module removes conversational framing, not software requirements. It never
infers package facts. Filter-only follow-ups may inherit a previous subject;
queries that name new software remain new searches. Unsupported constraints and
ambiguous composition are returned for clarification before retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


@dataclass(frozen=True)
class QueryIntent:
    subject: str
    constraints: dict
    clarification: str | None = None
    refinement: bool = False
    exact_title: bool = False


def normal(value: str) -> str:
    """Normalize surface spelling without broadly stemming package identities."""
    text = re.sub(r"\s+", " ", value.lower().replace("’", "'")).strip()
    text = re.sub(r"\bopen-source\b", "open source", text)
    for plural, singular in (
        ("databases", "database"),
        ("documents", "document"),
        ("servers", "server"),
        ("models", "model"),
        ("embeddings", "embedding"),
        ("brokers", "broker"),
        ("queues", "queue"),
        ("balancers", "balancer"),
    ):
        text = re.sub(r"\b" + plural + r"\b", singular, text)
    return text


# Anchored phrases remove how a visitor asks, preserving what they ask for.
# In particular, meaningful adjectives and workloads are not global stopwords.
_PREFIXES = tuple(
    re.compile(pattern)
    for pattern in (
        r"^please\s+",
        r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?",
        r"^(?:can|could|may)\s+(?:i|we)\s+(?:please\s+)?(?:get|find|use|have)\s+",
        r"^(?:help|assist)\s+(?:me|us)\s+(?:to\s+)?",
        r"^tell\s+(?:me|us)\s+(?:about\s+)?",
        r"^(?:i am|we are|i'm|we're|our team is)\s+(?:looking|searching)\s+for\s+",
        r"^(?:i am|we are|i'm|we're)\s+trying\s+to\s+",
        r"^point\s+(?:me|us)\s+(?:toward|towards|to)\s+",
        r"^(?:i'd|we'd)\s+like\s+(?:to\s+)?",
        r"^(?:i|we)\s+(?:want|need|would like|'d like)\s+(?:to\s+)?",
        r"^(?:find|discover|recommend|suggest|show|list|give)\s+(?:(?:me|us)\s+)?",
        r"^(?:what|which)\s+(?:(?:are|is)\s+)?(?:(?:some|the)\s+)?",
        r"^(?:are|is)\s+there\s+(?:(?:any|some)\s+)?",
        r"^do\s+you\s+(?:have|know(?:\s+of)?)\s+(?:any\s+)?",
        r"^(?:a|an|some|any)\s+",
    )
)
_SUFFIXES = tuple(
    re.compile(pattern)
    for pattern in (
        r"\s+(?:please|thanks)$",
        r"\s+(?:are|is)\s+available(?:\s+(?:here|in the dashboard))?$",
        r"\s+(?:that\s+)?(?:i|we)\s+(?:can|could)\s+use$",
        r"\s+for\s+(?:my|our)\s+(?:app|application|service|project|workload)$",
    )
)


def _framing(value: str) -> str:
    text = normal(value).rstrip(" ?!.")
    # Repeat because wrappers compose: "Could you please help me find ...?".
    for _ in range(8):
        previous = text
        for pattern in _PREFIXES:
            text = pattern.sub("", text).strip()
        for pattern in _SUFFIXES:
            text = pattern.sub("", text).strip()
        if text == previous:
            break
    # These phrases describe the relationship to a requested capability, not an
    # additional capability. Preserve the object (e.g. "built for geospatial
    # analysis" still requires geospatial analysis).
    text = re.sub(
        r"\b(?:built|meant|intended|designed)\s+(?:around|for|to)\b", "", text
    )
    text = re.sub(r"\bdeals?\s+with\b", "with", text)
    text = re.sub(r"\bback(?:ing)?\s+up\b", "backup", text)
    text = re.sub(
        r"^(?:programs?|tools?|utilities|software)\s+to\s+(?:make|create)\s+", "", text
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


_UNSUPPORTED = re.compile(
    r"\b(?:fastest|cheapest|best performance|tco|"
    r"apache (?:license|2(?:\.0)?)|mit license|gpl|bsd license|permissive|"
    r"license|licenses|licensing|gpu|cuda|version|versions|privacy|"
    r"production ready|production-ready|certified|guarantee|guaranteed|"
    r"after 20\d\d|before 20\d\d|since 20\d\d|"
    r"not|no|never|untested|excluding|except|omit|omitting|without|"
    r"non[- ]commercial|non[- ]open[- ]source|"
    r"passing tests|passed tests|tests pass|all tests pass)\b"
)
_LICENSE = re.compile(r"(?<![\w-])(?:open source|opensource|commercial)(?![\w-])")
_RECORDED_TESTS = re.compile(
    r"(?<![\w-])(?:"
    r"(?:with|having)\s+(?:recorded\s+)?(?:arm64\s+|arm\s+|aarch64\s+)?tests|"
    r"recorded\s+(?:arm64\s+|arm\s+|aarch64\s+)?(?:test records|test evidence|tests)|"
    r"test records|test evidence|tested(?:\s+on\s+(?:arm64|arm|aarch64))?"
    r")(?![\w-])"
)
# A remainder made only of these words has no new software subject. This is
# deliberately used only after a recognized filter, never as global stopwords.
_FILTER_REMAINDER = re.compile(
    r"\b(?:and|only|just|show|filter|to|by|with|having|ones|those|these|"
    r"the|a|an|all|packages|package|software|tools|tool|results|result|choices|choice|entries|entry|"
    r"please|linux|arm64|aarch64|arm)\b"
)


def _named_filter_subject(subject: str, titles: set[str]) -> tuple[str | None, str]:
    """Separate a catalog title only when all other wording is supported filters.

    Match the longest title first so an edition or a title containing words like
    ``Commercial`` keeps its full identity. Its own words are never filters.
    """
    for title in sorted(titles, key=lambda value: (-len(value), value)):
        if not title or title not in subject:
            continue
        match = re.search(r"(?<![\w-])" + re.escape(title) + r"(?![\w-])", subject)
        if not match:
            continue
        outside = subject[: match.start()] + " " + subject[match.end() :]
        if not (_LICENSE.search(outside) or _RECORDED_TESTS.search(outside)):
            continue
        remainder = _LICENSE.sub("", _RECORDED_TESTS.sub("", outside))
        if not _FILTER_REMAINDER.sub("", remainder).strip(" ,:;.!?"):
            return title, outside.strip()
    return None, subject


def parse_intent(
    query: str,
    previous_query: str | None = None,
    filters: Mapping | None = None,
    filters_override: bool = False,
    package_titles: Iterable[str] = (),
) -> QueryIntent:
    """Interpret only supported intent, retaining explicit sidebar precedence.

    A clarification leaves all supplied filters unchanged. Exact catalog names
    bypass vocabulary-based constraint interpretation (for example a package
    whose genuine name contains ``Commercial`` or ``License``).
    """
    original = {
        "license": (filters or {}).get("license", "all"),
        "category": (filters or {}).get("category"),
        "tested_only": bool((filters or {}).get("tested_only", False)),
    }
    if original["category"] in ("", "All", "all"):
        original["category"] = None
    titles = {normal(title) for title in package_titles}
    raw_query = normal(query)
    q = raw_query.rstrip(" ?!.")
    subject = _framing(q)
    if raw_query in titles:
        return QueryIntent(raw_query, original, exact_title=True)
    if q in titles or subject in titles:
        return QueryIntent(q if q in titles else subject, original, exact_title=True)
    if not q:
        return QueryIntent("", original)

    # These wrappers introduce a new subject, including exact catalog names.
    # Check before interpreting words inside a genuine title as constraints.
    subject = re.sub(r"^(?:and\s+)?(?:only|just)\s+", "", subject)
    subject = re.sub(r"^filter\s+(?:to|by)\s+", "", subject)
    subject = re.sub(r"^(?:ones|those|these)\s+(?:with|having)\s+", "", subject)
    if subject in titles:
        return QueryIntent(subject, original, exact_title=True)
    named_subject, subject = _named_filter_subject(subject, titles)

    if _UNSUPPORTED.search(subject if named_subject else q):
        return QueryIntent(
            subject,
            original,
            "This search cannot verify that constraint from the catalog. Try a "
            "software capability, open-source/commercial filter, category or "
            "recorded-test filter.",
        )
    licenses = set(_LICENSE.findall(subject))
    if "commercial" in licenses and licenses & {"open source", "opensource"}:
        return QueryIntent(
            subject,
            original,
            "Choose open-source or commercial, or remove the license wording "
            "and use All to search both. Combining license choices in a sentence "
            "is not supported by this PoC.",
        )
    if re.search(r"\bor\b", subject):
        return QueryIntent(
            subject,
            original,
            "Search one software need at a time. OR combinations are not "
            "supported by this PoC; try each alternative separately.",
        )

    constraints = original.copy()
    has_tests = bool(_RECORDED_TESTS.search(subject))
    # A standalone "tests" is accepted as the recorded-test filter, but phrases
    # like "tools to run tests" remain software requests, not test-record claims.
    filter_only_tests = bool(
        re.fullmatch(r"(?:only |just |and only )?(?:ones with )?tests", subject)
    )
    has_tests |= filter_only_tests
    has_filter = bool(licenses or has_tests)
    if not filters_override:
        if licenses & {"open source", "opensource"}:
            constraints["license"] = "opensource"
        elif "commercial" in licenses:
            constraints["license"] = "commercial"
        if has_tests:
            constraints["tested_only"] = True

    subject = _LICENSE.sub("", subject)
    subject = _RECORDED_TESTS.sub("", subject)
    if filter_only_tests:
        subject = re.sub(r"\btests\b", "", subject)
    subject = re.sub(r"\s+", " ", subject).strip()
    if named_subject:
        return QueryIntent(named_subject, constraints, exact_title=True)
    remainder = _FILTER_REMAINDER.sub("", subject).strip(" ,:;.!?")
    if has_filter and not remainder:
        if not previous_query:
            return QueryIntent(
                subject,
                original,
                "Start with the kind of software you need, then refine the results.",
            )
        previous = parse_intent(
            previous_query,
            filters=constraints,
            filters_override=True,
            package_titles=titles,
        )
        if previous.clarification or not previous.subject:
            return QueryIntent(
                subject,
                original,
                "Start with the kind of software you need, then refine the results.",
            )
        return QueryIntent(
            previous.subject,
            constraints,
            refinement=True,
            exact_title=previous.exact_title,
        )

    # A leading "only" is not sufficient to inherit old intent. This also makes
    # "Only web servers" after vector databases a new web-server search.
    subject = re.sub(r"^(?:and\s+)?(?:only|just)\s+", "", subject)
    subject = re.sub(r"^filter\s+(?:to|by)\s+", "", subject)
    subject = re.sub(r"^(?:ones|those|these)\s+(?:with|having)\s+", "", subject)
    subject = subject.strip(" ,:;!?")
    subject = re.sub(r"(?:\s+(?:with|and|having))+$", "", subject)
    if subject == "something fast" or re.fullmatch(
        r"(?:only|just|those|these|ones|results|packages|software)?", subject
    ):
        return QueryIntent(
            subject,
            original,
            "Describe the kind of software you need, or refine an existing "
            "search by open-source/commercial or recorded tests.",
        )
    return QueryIntent(subject, constraints, exact_title=subject in titles)
