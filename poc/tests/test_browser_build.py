"""Verify the real Hugo output for the opt-in browser transport."""

import json
import shutil
import subprocess
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


class SearchHTML(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.search = []
        self.rows = {}
        self.scripts = []
        self.feed(path.read_text())

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "data-conversational-search" in attrs:
            self.search.append(attrs)
        if attrs.get("data-catalog-id"):
            assert attrs["data-catalog-id"] not in self.rows
            self.rows[attrs["data-catalog-id"]] = attrs
        if tag == "script" and "js/eco-dashboard/" in attrs.get("src", ""):
            self.scripts.append(urlsplit(attrs["src"]).path.rsplit("/", 1)[-1])


def test_browser_build_maps_exact_catalog_and_loads_adapter_before_controller(tmp_path):
    hugo = shutil.which("hugo")
    if not hugo:
        pytest.skip("Hugo is required; CI installs the pinned version")
    site = tmp_path / "browser"
    subprocess.run(
        [hugo, "--minify", "--config",
         "config.toml,poc/config.local.toml,poc/config.browser.toml",
         "--destination", str(site)],
        cwd=ROOT, capture_output=True, check=True, timeout=30,
    )
    linux = SearchHTML(site / "linux/index.html")
    assert len(linux.search) == 1
    assert linux.search[0]["data-transport"] == "browser"
    assert linux.search[0]["data-endpoint"] == "https://knowledge.armdevtechapi.com/search"
    packages = json.loads((site / "poc-catalog.json").read_text())["packages"]
    assert len(packages) > 1000
    assert set(linux.rows) == {package["id"] for package in packages}
    for package in packages:
        row = linux.rows[package["id"]]
        assert row["data-woa"] == "true"
        assert row["data-title-urlized"] == package["url_id"]
        assert row["data-kb-edition"] == package["edition"]
        assert row["data-kb-description"] == package["description"]
    source = ROOT / "themes/arm-design-system-hugo-theme/static/js/eco-dashboard"
    expected = []
    for name in ("browser-kb-search", "conversational-search"):
        content = (source / f"{name}.js").read_bytes()
        filename = f"{name}.{sha256(content).hexdigest()}.js"
        expected.append(filename)
        assert (site / "js/eco-dashboard" / filename).read_bytes() == content
    assert linux.scripts.index(expected[0]) < linux.scripts.index(expected[1])
    windows = SearchHTML(site / "windows/index.html")
    assert not windows.search
    assert not any("browser-kb-search" in name for name in windows.scripts)


def test_normal_site_build_keeps_browser_search_disabled(tmp_path):
    hugo = shutil.which("hugo")
    if not hugo:
        pytest.skip("Hugo is required; CI installs the pinned version")
    subprocess.run(
        [hugo, "--minify", "--config", "config.toml", "--destination", str(tmp_path)],
        cwd=ROOT, capture_output=True, check=True, timeout=30,
    )
    linux = SearchHTML(tmp_path / "linux/index.html")
    assert not linux.search
    assert not linux.rows
    assert not any("browser-kb-search" in name for name in linux.scripts)
