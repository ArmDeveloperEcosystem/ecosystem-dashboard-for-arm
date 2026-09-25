"""Evidence trust checks, including Python/WHATWG parser disagreement regressions."""

import json
from pathlib import Path
import subprocess

import pytest

from poc.catalog import ARM_HOSTS, Catalog
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
    }


@pytest.mark.parametrize("url", UNTRUSTED_URLS)
def test_untrusted_or_ambiguous_evidence_does_not_resolve(catalog, url):
    assert catalog.resolve_hit(redis_hit(url)) == []


@pytest.mark.parametrize("url", TRUSTED_URLS)
def test_explicit_https_arm_evidence_remains_usable(catalog, url):
    assert "Redis" in {p["title"] for p in catalog.resolve_hit(redis_hit(url))}


def test_parser_disagreement_hit_keeps_catalog_only_evidence(catalog):
    hit = redis_hit(UNTRUSTED_URLS[0])
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    result = service.search("Redis")
    redis = next(p for p in result["results"] if p["title"] == "Redis")
    assert redis["match_source"] == "catalog_description"
    assert redis["evidence_url"] == catalog.by_id[redis["id"]]["url"]
    assert "knowledge-base evidence" not in redis["reason"]


def test_url_matrix_has_the_same_trust_decision_in_python_and_browser(catalog):
    # Exercise the production controller through the Node DOM fixture with the
    # same inputs as Python. URL parsing and mocked search never fetch evidence.
    urls = UNTRUSTED_URLS + TRUSTED_URLS
    completed = subprocess.run(
        ["node", str(ROOT / "poc/tests/ui_search.test.cjs"), "--evidence-url-matrix"],
        input=json.dumps(urls),
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    browser_results = json.loads(completed.stdout)
    assert len(browser_results) == len(urls)
    for url, browser in zip(urls, browser_results, strict=True):
        expected = url in TRUSTED_URLS
        assert bool(catalog.resolve_hit(redis_hit(url))) == expected, repr(url)
        assert all(result["accepted"] == expected for result in browser), repr(url)
        if expected:
            assert all(result["hostname"] in ARM_HOSTS for result in browser)
            assert all(result["protocol"] == "https:" for result in browser)
