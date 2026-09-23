"""Bounded, allowlisted metadata-only HTTP. Never downloads executable assets."""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests


class CollectionError(RuntimeError):
    pass


class BoundedHTTP:
    HOSTS = {
        "api.github.com",
        "hub.docker.com",
        "registry-1.docker.io",
        "auth.docker.io",
    }

    def __init__(self, limits: dict, session=None):
        self.session = session or requests.Session()
        self.limits = limits
        self.requests_used = 0
        self.started = time.monotonic()
        self.failures = []

    def get(self, url: str, *, params=None, headers=None) -> tuple[object, dict]:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise CollectionError("Rejected unapproved metadata URL")
        if self.requests_used >= self.limits["max_requests"]:
            raise CollectionError("Run request limit reached")
        if time.monotonic() - self.started >= self.limits["max_seconds"]:
            raise CollectionError("Run wall-clock limit reached")
        req_headers = {
            "User-Agent": "Arm-Ecosystem-Internal-PoC/1.0",
            "Accept": "application/json",
        }
        if parsed.hostname == "api.github.com":
            req_headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                req_headers["Authorization"] = "Bearer " + token
        req_headers.update(headers or {})
        self.requests_used += 1
        try:
            # Disallow automatic redirects so credentials cannot cross origins.
            remaining = self.limits["max_seconds"] - (time.monotonic() - self.started)
            timeout = max(0.1, min(self.limits["timeout_seconds"], remaining))
            with self.session.get(
                url,
                params=params,
                headers=req_headers,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise CollectionError(
                        f"HTTP {response.status_code} from {parsed.hostname}{parsed.path}"
                    )
                chunks, size = [], 0
                for part in response.iter_content(65536):
                    size += len(part)
                    if size > self.limits["max_response_bytes"]:
                        raise CollectionError(
                            "Metadata response exceeds configured byte limit"
                        )
                    if time.monotonic() - self.started >= self.limits["max_seconds"]:
                        raise CollectionError(
                            "Run wall-clock limit reached while reading metadata"
                        )
                    chunks.append(part)
                import json

                return json.loads(b"".join(chunks)), dict(response.headers)
        except (requests.RequestException, ValueError) as exc:
            # Never retain response bodies or Authorization headers in a failure.
            raise CollectionError(
                f"Metadata request failed for {parsed.hostname}{parsed.path}: {type(exc).__name__}"
            ) from exc


def github_pages(
    http,
    url,
    max_pages,
    *,
    params=None,
    items_key=None,
    stop_after=None,
    stop_when=None,
):
    """Follow GitHub Link pagination. Return items, completeness, and errors."""
    values, seen = [], set()
    next_url, first_params = url, {"per_page": 100, **(params or {})}
    for _ in range(max_pages):
        if next_url in seen:
            return values, False, ["Pagination cycle detected"]
        seen.add(next_url)
        try:
            data, headers = http.get(next_url, params=first_params)
        except CollectionError as exc:
            return values, False, [str(exc)]
        first_params = None
        page = data.get(items_key) if items_key and isinstance(data, dict) else data
        if not isinstance(page, list):
            return values, False, ["Unexpected paginated metadata shape"]
        values.extend(page)
        link = headers.get("Link", headers.get("link", ""))
        import re

        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not match:
            incomplete = isinstance(data, dict) and data.get(
                "incomplete_results", False
            )
            return (
                values,
                not incomplete,
                ["GitHub search reports incomplete results"] if incomplete else [],
            )
        next_url = match.group(1)
        if stop_when is not None and stop_when(values):
            return values, False, []
        if stop_after is not None and len(values) >= stop_after:
            return values, False, []
    return values, False, ["Pagination limit reached; inventory is incomplete"]
