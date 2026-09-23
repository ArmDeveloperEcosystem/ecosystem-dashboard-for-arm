"""Authoritative package identities exported by the same Hugo template as the UI."""

from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ARM_HOSTS = {"arm.com", "www.arm.com", "developer.arm.com", "learn.arm.com"}


def words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", value.lower()))


class Catalog:
    def __init__(self, path: Path):
        payload = json.loads(path.read_text())
        self.packages = payload["packages"]
        self.by_id = {p["id"]: p for p in self.packages}
        if len(self.by_id) != len(self.packages):
            raise ValueError(
                "Duplicate dashboard package identities: resolve before serving search"
            )
        self.by_url_id = {}
        self.by_slug = {}
        for p in self.packages:
            self.by_url_id.setdefault(p.get("url_id", p["id"]), []).append(p)
            self.by_slug.setdefault(p["slug"], []).append(p)
            p["_text"] = " ".join(
                str(p.get(k, "")) for k in ("title", "description", "category")
            ).lower()
            p["_words"] = words(p["_text"])
            record = p.get("test_record") or {}
            runner = (record.get("run") or {}).get("runner") or {}
            os_name = str(runner.get("os", "")).lower()
            p["has_recorded_tests"] = (
                runner.get("arch") in ("arm64", "aarch64")
                and any(
                    x in os_name
                    for x in (
                        "linux",
                        "ubuntu",
                        "debian",
                        "rhel",
                        "centos",
                        "fedora",
                        "amazon",
                        "alpine",
                        "suse",
                    )
                )
                and bool((record.get("run") or {}).get("url"))
                and bool((record.get("tests") or {}).get("details"))
            )

    def resolve_hit(self, hit: dict) -> list[dict]:
        """Only trusted Arm evidence URLs; identities must exist in this catalog."""
        try:
            url = urlparse(str(hit.get("url") or ""))
            hostname = url.hostname
        except ValueError:
            return []
        if url.scheme != "https" or hostname not in ARM_HOSTS:
            return []
        package = parse_qs(url.query).get("package", [""])[0]
        if package:
            return self.by_url_id.get(package, [])
        # Articles may propose candidates; relevance and facts still come from the catalog.
        title = str(hit.get("title") or "") + " " + str(hit.get("heading") or "")
        matched = []
        for p in self.packages:
            name = p["title"].strip()
            if len(name) >= 4 and re.search(
                r"(?<!\w)" + re.escape(name) + r"(?!\w)", title, re.I
            ):
                matched.append(p)
        return matched
