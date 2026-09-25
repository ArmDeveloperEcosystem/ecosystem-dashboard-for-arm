"""Regression coverage for catalog-owned, reusable article-title matchers."""

import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from poc.catalog import ARM_HOSTS, Catalog


ARTICLE_URL = "https://learn.arm.com/learning-paths/software/example/"


def package(title, identity, **fields):
    return {"id": identity, "slug": identity, "title": title, **fields}


def make_catalog(tmp_path, packages):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"packages": packages}), encoding="utf-8")
    return Catalog(path)


@pytest.mark.parametrize(
    ("name", "title", "heading", "matches"),
    [
        ("Redis", "Using REDIS on Arm", "", True),
        ("  Redis\t", "Redis", "", True),
        ("Redis", "RedisGraph", "", False),
        ("Redis", "preRedis", "", False),
        ("Redis", "_Redis", "", False),
        ("Redis", "Redis_", "", False),
        ("Redis", "πRedis", "", False),
        ("Redis", "Redis٣", "", False),
        ("Redis", "(Redis)-server", "", True),
        ("Redis", "An unrelated title", "Redis guide", True),
        ("Redis", "An in-memory cache", "", False),
        (".NET", "Using .net on Arm", "", True),
        (".NET", "Using XNET on Arm", "", False),
        (".NET", "x.NET", "", False),
        (".NET", ".NET8", "", False),
        ("C++", "C++", "", False),
        ("Go", "Go", "", False),
        ("C#", "C#", "", False),
        ("   Go   ", "Go", "", False),
        ("", "anything", "", False),
        ("C++17", "C++17 guide", "", True),
        ("C++17", "C17 guide", "", False),
        ("Kit++", "Kit++++", "", True),
        ("Kit++", "Kit++extension", "", False),
        ("foo[1]", "foo[1]", "", True),
        ("foo[1]", "foo1", "", False),
        ("lib(a)", "lib(a)", "", True),
        ("lib(a)", "liba", "", False),
        ("a|b?", "a|b?", "", True),
        ("a|b?", "a", "", False),
        (r"a\bc", r"a\bc", "", True),
        ("^tool$", "^tool$", "", True),
        ("Kilo", "KILO", "", True),
        ("Iris", "ırİs", "", True),
        ("Cafe", "Café", "", False),
        ("Straße", "STRASSE", "", False),
        ("Two Words", "Two", "Words", True),
        ("Two Words", "Two  Words", "", False),
        ("Two Words", "Two\nWords", "", False),
        ("line\nbreak", "line\nbreak", "", True),
    ],
)
def test_article_matching_preserves_literal_names_and_boundaries(
    tmp_path, name, title, heading, matches
):
    catalog = make_catalog(tmp_path, [package(name, "example")])
    actual = catalog.resolve_hit(
        {"url": ARTICLE_URL, "title": title, "heading": heading}
    )
    assert actual == (catalog.packages if matches else [])


def test_duplicate_names_keep_edition_identity_objects_and_catalog_order(tmp_path):
    catalog = make_catalog(
        tmp_path,
        [
            package("Weaviate", "commercial/weaviate", url_id="weaviate"),
            package("Redis", "opensource/redis", url_id="redis"),
            package("Weaviate", "opensource/weaviate", url_id="weaviate"),
        ],
    )
    actual = catalog.resolve_hit(
        {"url": ARTICLE_URL, "title": "Weaviate with Redis"}
    )
    assert [p["id"] for p in actual] == [p["id"] for p in catalog.packages]
    assert all(p is original for p, original in zip(actual, catalog.packages))

    direct = catalog.resolve_hit(
        {"url": ARTICLE_URL + "?package=weaviate", "title": "Redis"}
    )
    assert [p["id"] for p in direct] == [
        "commercial/weaviate",
        "opensource/weaviate",
    ]
    assert all(p is catalog.by_id[p["id"]] for p in direct)
    assert catalog.resolve_hit(
        {"url": ARTICLE_URL + "?package=unknown", "title": "Weaviate"}
    ) == []


def test_short_names_remain_resolvable_by_explicit_identity(tmp_path):
    catalog = make_catalog(tmp_path, [package("Go", "go")])
    assert catalog.resolve_hit({"url": ARTICLE_URL + "?package=go"}) == (
        catalog.packages
    )


def test_duplicate_ids_are_rejected_before_article_matching(tmp_path):
    with pytest.raises(ValueError, match="Duplicate dashboard package identities"):
        make_catalog(
            tmp_path,
            [package("First name", "same-id"), package("Second name", "same-id")],
        )


def test_catalog_instances_do_not_share_matching_rows(tmp_path):
    first = make_catalog(tmp_path, [package("Shared name", "first-edition")])
    second = make_catalog(tmp_path, [package("Shared name", "second-edition")])
    hit = {"url": ARTICLE_URL, "title": "Shared name"}
    assert first.resolve_hit(hit) == first.packages
    assert second.resolve_hit(hit) == second.packages
    assert first.resolve_hit(hit)[0] is first.by_id["first-edition"]
    assert second.resolve_hit(hit)[0] is second.by_id["second-edition"]


def legacy_resolve_hit(catalog, hit):
    """Frozen pre-optimization resolver, including URL and identity precedence."""
    value = hit.get("url")
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f-\x9f\\]", value):
        return []
    try:
        url = urlparse(value)
        hostname = url.hostname
    except ValueError:
        return []
    if (
        url.scheme != "https"
        or hostname not in ARM_HOSTS
        or url.netloc.lower() not in (hostname, hostname + ":443")
    ):
        return []
    identity = parse_qs(url.query).get("package", [""])[0]
    if identity:
        return catalog.by_url_id.get(identity, [])
    title = str(hit.get("title") or "") + " " + str(hit.get("heading") or "")
    matched = []
    for row in catalog.packages:
        name = row["title"].strip()
        if len(name) >= 4 and re.search(
            r"(?<!\w)" + re.escape(name) + r"(?!\w)", title, re.I
        ):
            matched.append(row)
    return matched


def test_large_catalog_matches_the_complete_legacy_resolver(tmp_path):
    # Distinct names exceed Python's regex cache, as the deployed catalog does.
    packages = [
        package(f"Package-{index:04d} [C++]", f"package-{index}")
        for index in range(1200)
    ]
    packages.extend(
        [
            package(".NET", "dotnet"),
            package("Redis", "redis-oss", url_id="redis"),
            package("Redis", "redis-commercial", url_id="redis"),
            package("Go", "go"),
            package("Two Words", "two-words"),
            package("Kilo", "kilo"),
            package("Iris", "iris"),
            package("a|b?", "metacharacters"),
        ]
    )
    catalog = make_catalog(tmp_path, packages)
    hits = []
    for index in (0, 1, 255, 256, 511, 512, 767, 768, 1023, 1199):
        name = packages[index]["title"]
        hits.extend(
            [
                {"url": ARTICLE_URL, "title": f"({name.lower()}) with Redis"},
                {"url": ARTICLE_URL, "title": "Arm", "heading": name.upper()},
                {"url": ARTICLE_URL, "title": f"_{name} {name}suffix"},
            ]
        )
    hits.extend(
        [
            {"url": ARTICLE_URL},
            {"url": ARTICLE_URL, "title": None, "heading": 0},
            {"url": ARTICLE_URL, "title": ["Redis", ".NET"]},
            {"url": ARTICLE_URL, "title": "Two", "heading": "Words"},
            {"url": ARTICLE_URL, "title": "KILO ırİs a|b? Go"},
            {"url": ARTICLE_URL, "title": "Redis_ πRedis Redis٣"},
        ]
    )
    hits.extend(
        {"url": url, "title": "Redis .NET Package-0000 [C++]"}
        for url in (
            ARTICLE_URL + "?package=redis",
            ARTICLE_URL + "?package=go",
            ARTICLE_URL + "?package=unknown",
            ARTICLE_URL + "?package=package-1199&package=redis",
            ARTICLE_URL + "?package=&package=redis",
            ARTICLE_URL + "?package=",
            ARTICLE_URL + "?package=%72edis",
            "HTTPS://DEVELOPER.ARM.COM:443/article",
            "https://evil.example/article",
            "https://user@developer.arm.com/article",
            "https://developer.arm.com:0443/article",
            "https://developer.arm.com./article",
            "https://evil.example\\@developer.arm.com/article",
            "https://[malformed",
            "https://learn.arm.com/\tarticle",
            None,
            123,
        )
    )
    for hit in hits:
        expected = legacy_resolve_hit(catalog, hit)
        actual = catalog.resolve_hit(hit)
        assert [row["id"] for row in actual] == [row["id"] for row in expected], hit
        assert all(row is original for row, original in zip(actual, expected)), hit
