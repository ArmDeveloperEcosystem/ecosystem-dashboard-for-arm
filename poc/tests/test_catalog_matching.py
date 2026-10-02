"""Composite identity mapping and current recorded-test checks, without NLP."""

import json

import pytest

from poc.catalog import Catalog, ScopedContractError

URL = "https://developer.arm.com/ecosystem-dashboard/linux/?package="


def package(slug, *, edition="open-source", identity=None, **fields):
    license = "opensource" if edition == "open-source" else "commercial"
    return {
        "id": identity or f"linux/{license}_packages/{slug}.md",
        "url_id": slug,
        "slug": slug,
        "url": "/linux/?package=" + slug,
        "platform": "linux",
        "edition": edition,
        "license": license,
        "title": slug.title(),
        "description": "Current catalog description",
        "category": "Databases",
        "parent_category": "Data",
        **fields,
    }


def make_catalog(tmp_path, packages):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"packages": packages}), encoding="utf-8")
    return Catalog(path)


def hit(slug, *, edition="open-source", **fields):
    return {
        "url": URL + slug,
        "doc_type": "Ecosystem Dashboard",
        "platform": "linux",
        "edition": edition,
        **fields,
    }


def test_same_slug_and_title_keep_edition_identity_objects(tmp_path):
    catalog = make_catalog(
        tmp_path,
        [
            package("weaviate", edition="commercial"),
            package("weaviate"),
        ],
    )
    for edition in ("open-source", "commercial"):
        result = catalog.resolve_hit(hit("weaviate", edition=edition))
        assert len(result) == 1
        assert result[0]["edition"] == edition
        assert result[0] is catalog.by_id[result[0]["id"]]


def test_canonical_identity_ignores_provider_title_heading_and_description(tmp_path):
    catalog = make_catalog(tmp_path, [package("redis"), package("go")])
    assert catalog.resolve_hit(
        hit("go", title="Redis", heading="Redis", snippet="Redis")
    ) == [catalog.packages[1]]
    assert catalog.resolve_hit(hit("deleted", title="Redis")) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://learn.arm.com/learning-paths/redis/",
        "https://developer.arm.com/ecosystem-dashboard/windows/?package=redis",
        "https://developer.arm.com/article?package=redis",
        "https://developer.arm.com/ecosystem-dashboard/linux;not-a-dashboard-path?package=redis",
        "https://developer.arm.com/ecosystem-dashboard/linux//?package=redis",
        "https://developer.arm.com/ecosystem-dashboard/linux/",
        URL + "redis&package=redis",
        URL + "&package=redis",
        URL,
        URL + "redis#details",
        URL + "red%0Ais",
        URL + "redis%2Fserver",
    ],
)
def test_article_wrong_platform_missing_or_ambiguous_urls_never_guess(tmp_path, url):
    catalog = make_catalog(tmp_path, [package("redis")])
    with pytest.raises(ScopedContractError):
        catalog.resolve_hit(hit("redis", url=url, title="Redis"))


@pytest.mark.parametrize(
    "origin,path",
    [
        ("https://developer.arm.com", "/ecosystem-dashboard/linux"),
        ("https://arm.com", "/developer-hub/ecosystem-dashboard"),
        ("https://www.arm.com", "/developer-hub/ecosystem-dashboard"),
    ],
)
@pytest.mark.parametrize("slash", ["", "/"])
def test_current_and_legacy_canonical_dashboard_paths(tmp_path, origin, path, slash):
    catalog = make_catalog(tmp_path, [package("redis")])
    assert (
        catalog.resolve_hit(hit("redis", url=origin + path + slash + "?package=redis"))
        == catalog.packages
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("doc_type", None),
        ("doc_type", "Article"),
        ("platform", None),
        ("platform", "windows"),
        ("edition", None),
        ("edition", "opensource"),
        ("edition", ["open-source"]),
    ],
)
def test_missing_or_wrong_scope_metadata_is_not_a_catalog_candidate(
    tmp_path, field, value
):
    catalog = make_catalog(tmp_path, [package("redis")])
    with pytest.raises(ScopedContractError):
        catalog.resolve_hit(hit("redis", **{field: value}))


def test_selected_edition_and_catalog_edition_must_both_agree(tmp_path):
    catalog = make_catalog(tmp_path, [package("redis")])
    with pytest.raises(ScopedContractError):
        catalog.resolve_hit(hit("redis"), edition="commercial")
    with pytest.raises(ScopedContractError):
        catalog.resolve_hit(hit("redis", edition="commercial"))


def test_duplicate_record_ids_and_ambiguous_composite_identity_fail_at_load(tmp_path):
    with pytest.raises(ValueError, match="Duplicate dashboard package identities"):
        make_catalog(
            tmp_path,
            [
                package("redis"),
                package("go", identity="linux/opensource_packages/redis.md"),
            ],
        )
    with pytest.raises(ValueError, match="Ambiguous dashboard"):
        make_catalog(
            tmp_path, [package("redis"), package("redis", identity="other-file")]
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", None),
        ("edition", None),
        ("license", "commercial"),
        ("url_id", "other"),
    ],
)
def test_catalog_scope_and_canonical_identity_are_required(tmp_path, field, value):
    with pytest.raises(ValueError):
        make_catalog(tmp_path, [package("redis", **{field: value})])


@pytest.mark.parametrize(
    "arch,os_name,run_url,details,expected",
    [
        ("arm64", "Ubuntu 24.04", "https://ci.example/run", ["success"], True),
        ("aarch64", "linux", "https://ci.example/run", ["failure"], True),
        ("x86_64", "Ubuntu", "https://ci.example/run", ["success"], False),
        ("arm64", "Windows", "https://ci.example/run", ["success"], False),
        ("arm64", "macOS", "https://ci.example/run", ["success"], False),
        ("arm64", "Ubuntu", "", ["success"], False),
        ("arm64", "Ubuntu", "https://ci.example/run", [], False),
    ],
)
def test_recorded_tests_require_arm_linux_run_and_details(
    tmp_path, arch, os_name, run_url, details, expected
):
    catalog = make_catalog(
        tmp_path,
        [
            package(
                "redis",
                test_record={
                    "run": {"runner": {"arch": arch, "os": os_name}, "url": run_url},
                    "tests": {"details": details},
                },
            )
        ],
    )
    assert catalog.packages[0]["has_recorded_tests"] is expected
