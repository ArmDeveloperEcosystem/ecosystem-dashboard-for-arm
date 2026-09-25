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
        title_patterns = []
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
            name = p["title"].strip()
            if len(name) >= 4:
                title_patterns.append(
                    (p, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I))
                )
        # Retain every row, including editions with the same display name.
        # Catalog-sized pattern sets can exceed re's shared cache, so keep the
        # compiled patterns for this catalog's lifetime instead of per hit.
        self._title_patterns = tuple(title_patterns)

    def resolve_hit(self, hit: dict) -> list[dict]:
        """Only trusted Arm evidence URLs; identities must exist in this catalog."""
        value = hit.get("url")
        # urllib strips some controls and treats backslashes differently from a
        # browser. Reject them before parsing so both agree on the destination.
        if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f-\x9f\\]", value):
            return []
        try:
            url = urlparse(value)
            hostname = url.hostname
        except ValueError:
            return []
        # Permit only literal approved hostnames and the standard HTTPS port.
        # Comparing the raw authority also rejects userinfo, encoded hostnames,
        # trailing dots, empty/noncanonical ports and Unicode host aliases.
        if (
            url.scheme != "https"
            or hostname not in ARM_HOSTS
            or url.netloc.lower() not in (hostname, hostname + ":443")
        ):
            return []
        package = parse_qs(url.query).get("package", [""])[0]
        if package:
            return self.by_url_id.get(package, [])
        # Articles propose candidates only. The search service must separately
        # validate evidence attribution, software roles and query requirements.
        title = str(hit.get("title") or "") + " " + str(hit.get("heading") or "")
        matched = []
        for p, pattern in self._title_patterns:
            if pattern.search(title):
                matched.append(p)
        return matched
