"""Evidence trust checks, including Python/WHATWG parser disagreement regressions."""

from pathlib import Path

import pytest

from poc.catalog import ARM_HOSTS, Catalog, ScopedContractError, trusted_arm_url
from poc.search_service import SearchService

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = "/ecosystem-dashboard/linux/?package=redis"
UNTRUSTED_URLS = [
    "https://evil.example\\@developer.arm.com" + PACKAGE_PATH,
    "https://user@developer.arm.com" + PACKAGE_PATH,
    "https://user:password@developer.arm.com" + PACKAGE_PATH,
    "https://@developer.arm.com" + PACKAGE_PATH,
    "https://developer.arm.com@evil.example" + PACKAGE_PATH,
    "https://developer.arm.com.evil.example" + PACKAGE_PATH,
    "https://developer.arm.com." + PACKAGE_PATH,
    "https://%64eveloper.arm.com" + PACKAGE_PATH,
    "https://developer%2earm.com" + PACKAGE_PATH,
    "https://developer\u3002arm.com" + PACKAGE_PATH,
    "https://developer.arm.com:" + PACKAGE_PATH,
    "https://developer.arm.com:0443" + PACKAGE_PATH,
    "https://developer.arm.com:8443" + PACKAGE_PATH,
    "https://developer.arm.com:invalid" + PACKAGE_PATH,
    "https://developer.arm.com:65536" + PACKAGE_PATH,
    "https://developer.arm.com\\" + PACKAGE_PATH,
    "https://developer.arm.com\t" + PACKAGE_PATH,
    "https://devel\noper.arm.com" + PACKAGE_PATH,
    "https://developer.arm.com" + PACKAGE_PATH + "\r",
    "\x00https://developer.arm.com" + PACKAGE_PATH,
    " https://developer.arm.com" + PACKAGE_PATH,
    "https://developer.arm.com" + PACKAGE_PATH + "# ",
    "https://developer.arm.com" + PACKAGE_PATH + "#\x7f",
    "https://developer.arm.com" + PACKAGE_PATH + "#\x85",
    "https:developer.arm.com" + PACKAGE_PATH,
    "https:/developer.arm.com" + PACKAGE_PATH,
    "https:///developer.arm.com" + PACKAGE_PATH,
    "//developer.arm.com" + PACKAGE_PATH,
    "http://developer.arm.com" + PACKAGE_PATH,
    "https://evil.example" + PACKAGE_PATH,
    "https://[malformed" + PACKAGE_PATH,
    "javascript:alert(1)",
]
TRUSTED_URLS = [
    *("https://" + host + PACKAGE_PATH for host in sorted(ARM_HOSTS)),
    "HTTPS://DEVELOPER.ARM.COM" + PACKAGE_PATH,
    "https://developer.arm.com:443" + PACKAGE_PATH,
    "https://learn.arm.com/learning-paths/redis/?source=search#overview",
    "https://learn.arm.com/learning-paths/redis%20guide/?source=search#overview",
]


@pytest.fixture(scope="module")
def catalog():
    return Catalog(ROOT / ".poc/public/poc-catalog.json")


def redis_hit(url):
    return {
        "title": "Redis",
        "snippet": "Redis is a database, cache and message broker.",
        "url": url,
        "doc_type": "Ecosystem Dashboard",
        "platform": "linux",
        "edition": "open-source",
    }


@pytest.mark.parametrize("url", UNTRUSTED_URLS)
def test_untrusted_or_ambiguous_evidence_does_not_resolve(catalog, url):
    assert not trusted_arm_url(url)
    with pytest.raises(ScopedContractError):
        catalog.resolve_hit(redis_hit(url))


@pytest.mark.parametrize("url", TRUSTED_URLS)
def test_explicit_https_arm_evidence_remains_usable(catalog, url):
    assert trusted_arm_url(url)


def test_parser_disagreement_hit_fails_entire_scoped_response(catalog):
    hit = redis_hit(UNTRUSTED_URLS[0])
    service = SearchService(
        catalog, transport=lambda *_: {"results": [hit]}, scope_confirmed=True
    )
    result = service.search("Redis")
    assert result["results"] == []
    assert result["mode"] == "kb_unavailable"


def test_valid_hit_links_to_current_catalog_instead_of_provider_url(catalog):
    hit = redis_hit("https://arm.com/developer-hub/ecosystem-dashboard/?package=redis")
    service = SearchService(
        catalog, transport=lambda *_: {"results": [hit]}, scope_confirmed=True
    )
    result = service.search("Redis")
    redis = result["results"][0]
    assert redis["evidence_url"] == catalog.by_id[redis["id"]]["url"]
    assert redis["reason"] == catalog.by_id[redis["id"]]["description"]
