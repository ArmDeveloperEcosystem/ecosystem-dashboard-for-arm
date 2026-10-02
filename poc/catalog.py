"""Current dashboard identities and strict scoped-KB URL mapping."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ARM_HOSTS = {"arm.com", "www.arm.com", "developer.arm.com", "learn.arm.com"}
EDITIONS = {"open-source": "opensource", "commercial": "commercial"}
DOC_TYPE = "Ecosystem Dashboard"
PLATFORM = "linux"


class ScopedContractError(ValueError):
    """The provider did not satisfy the proposed scoped response contract."""


def trusted_arm_url(value: str) -> bool:
    """Keep Python and browser URL trust decisions aligned before parsing scope."""
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f-\x9f\\]", value):
        return False
    try:
        value.encode("utf-8")
        url = urlparse(value)
        hostname = url.hostname
    except (ValueError, UnicodeError):
        return False
    return (
        url.scheme == "https"
        and hostname in ARM_HOSTS
        and url.netloc.lower() in (hostname, hostname + ":443")
    )


def package_parameter(value: str) -> str:
    """A canonical package identity has exactly one nonempty package parameter."""
    try:
        packages = parse_qs(urlparse(value).query, keep_blank_values=True).get(
            "package", []
        )
    except ValueError as exc:
        raise ScopedContractError("Invalid dashboard package URL") from exc
    if (
        len(packages) != 1
        or not packages[0]
        or re.search(r"[\s\x00-\x1f\x7f-\x9f\\/]", packages[0])
    ):
        raise ScopedContractError("Missing or ambiguous dashboard package identity")
    return packages[0]


class Catalog:
    def __init__(self, path: Path):
        payload = json.loads(path.read_text())
        self.packages = payload["packages"]
        self.by_id = {p["id"]: p for p in self.packages}
        if len(self.by_id) != len(self.packages):
            raise ValueError(
                "Duplicate dashboard package identities: resolve before serving search"
            )
        self.by_identity = {}
        self.by_url_id = {}
        for package in self.packages:
            if (
                package.get("platform") != PLATFORM
                or package.get("edition") not in EDITIONS
                or package.get("license") != EDITIONS[package["edition"]]
            ):
                raise ValueError(
                    "Catalog package has missing or invalid platform/edition"
                )
            url_id = package_parameter(package["url"])
            if package.get("url_id") != url_id:
                raise ValueError("Catalog URL and canonical package identity disagree")
            key = (url_id, package["platform"], package["edition"])
            if key in self.by_identity:
                raise ValueError("Ambiguous dashboard URL/platform/edition identity")
            self.by_identity[key] = package
            self.by_url_id.setdefault(url_id, []).append(package)
            record = package.get("test_record") or {}
            runner = (record.get("run") or {}).get("runner") or {}
            os_name = str(runner.get("os", "")).lower()
            package["has_recorded_tests"] = (
                runner.get("arch") in ("arm64", "aarch64")
                and any(
                    name in os_name
                    for name in (
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

    def resolve_hit(self, hit: dict, *, edition: str | None = None) -> list[dict]:
        """Resolve only canonical URL + platform + edition; never guess from text.

        Unknown URL identities can be omitted. Scope, trust, or ambiguity errors
        invalidate the full provider response so valid-looking partial results
        cannot hide an unscoped or malformed provider contract.
        """
        if (
            not isinstance(hit, dict)
            or hit.get("doc_type") != DOC_TYPE
            or hit.get("platform") != PLATFORM
            or not isinstance(hit.get("edition"), str)
            or hit["edition"] not in EDITIONS
            or (edition is not None and hit["edition"] != edition)
        ):
            raise ScopedContractError("Missing or incorrect dashboard scope metadata")
        value = hit.get("url")
        if not trusted_arm_url(value):
            raise ScopedContractError("Untrusted dashboard URL")
        url = urlparse(value)
        path = url.path.removesuffix("/")
        current = (
            url.hostname == "developer.arm.com" and path == "/ecosystem-dashboard/linux"
        )
        legacy = (
            url.hostname in ("arm.com", "www.arm.com")
            and path == "/developer-hub/ecosystem-dashboard"
        )
        if not (current or legacy) or url.params or url.fragment:
            raise ScopedContractError("URL is not a canonical Linux dashboard package")
        url_id = package_parameter(value)
        key = (url_id, hit["platform"], hit["edition"])
        package = self.by_identity.get(key)
        if package is None and url_id in self.by_url_id:
            raise ScopedContractError("KB edition disagrees with the current catalog")
        return [package] if package else []
