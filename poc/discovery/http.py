"""Bounded, allowlisted metadata-only HTTP. Never downloads executable assets."""

from __future__ import annotations

import os
import re
import time
from urllib.parse import parse_qs, urlparse

import requests


class CollectionError(RuntimeError):
    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class HeaderOnlyAuth(requests.auth.AuthBase):
    """Use only explicit headers; never inherit credentials from a local netrc."""

    def __call__(self, request):
        return request


class BoundedHTTP:
    HOSTS = frozenset(
        {
            "api.github.com",
            "hub.docker.com",
            "registry-1.docker.io",
            "auth.docker.io",
        }
    )

    def __init__(self, limits: dict, session=None):
        self.session = session or requests.Session()
        self.limits = limits
        self.requests_used = 0
        self.started = time.monotonic()
        self.failures = []

    def get(self, url: str, *, params=None, headers=None) -> tuple[object, dict]:
        # Validate the literal authority before requests parses it. In
        # particular, backslashes, userinfo and malformed ports are not URLs
        # whose authority we are willing to reinterpret.
        try:
            if not isinstance(url, str) or re.search(r"[\x00-\x20\x7f\\]", url):
                raise ValueError("Ambiguous URL")
            parsed = urlparse(url)
            approved_authorities = self.HOSTS | {host + ":443" for host in self.HOSTS}
            valid = (
                parsed.scheme == "https"
                and parsed.netloc.lower() in approved_authorities
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
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
                auth=HeaderOnlyAuth(),
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise CollectionError(
                        f"HTTP {response.status_code} from {parsed.hostname}{parsed.path}",
                        status_code=response.status_code,
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
    alternate_paths=(),
    max_records=None,
):
    """Follow GitHub Link pagination. Return items, completeness, and errors.

    Discovery can impose a fetched-record allowance. Keep its page size fixed
    within a query and stop before a further full page would exceed that
    allowance. Release and asset pagination retain their completeness rules.
    """
    values, seen, incomplete_seen = [], set(), False
    origin = urlparse(url)
    approved_paths = {origin.path, *alternate_paths}
    next_url, first_params = url, {"per_page": 100, **(params or {})}
    page_size = first_params["per_page"]
    for _ in range(max_pages):
        if (
            max_records is not None
            and hasattr(http, "limits")
            and (
                getattr(http, "requests_used", 0) >= http.limits["max_requests"]
                or time.monotonic() - getattr(http, "started", time.monotonic())
                >= http.limits["max_seconds"]
            )
        ):
            return (
                values,
                False,
                ["GitHub search reports incomplete results"] if incomplete_seen else [],
            )
        if max_records is not None and len(values) + page_size > max_records:
            return (
                values,
                False,
                ["GitHub search reports incomplete results"] if incomplete_seen else [],
            )
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
        incomplete_seen = incomplete_seen or (
            isinstance(data, dict) and bool(data.get("incomplete_results", False))
        )
        values.extend(page)
        if max_records is not None and len(page) > page_size:
            # A remote endpoint can violate per_page. Account for what it
            # actually returned, stop immediately, and surface the violation.
            return values, False, ["Search response exceeded its requested page size"]
        link = headers.get("Link", headers.get("link", ""))
        if not isinstance(link, str):
            return values, False, ["Unexpected pagination header shape"]
        # Link parameters are unordered, and rel may be quoted or unquoted.
        # A malformed non-empty header cannot establish an exhaustive list.
        links = requests.utils.parse_header_links(link) if link else []
        if link and (
            not links
            or any(not item.get("url") or not item.get("rel") for item in links)
            or any(not re.match(r"\s*<", part) for part in re.split(r",\s*(?=<)", link))
        ):
            return (
                values,
                False,
                ["Malformed pagination header; inventory is incomplete"],
            )
        following = [
            item["url"] for item in links if "next" in item.get("rel", "").split()
        ]
        if len(following) > 1:
            return values, False, ["Multiple next-page links; inventory is incomplete"]
        if not following:
            return (
                values,
                not incomplete_seen,
                ["GitHub search reports incomplete results"] if incomplete_seen else [],
            )
        next_url = following[0]
        if (stop_when is not None and stop_when(values)) or (
            stop_after is not None and len(values) >= stop_after
        ):
            return (
                values,
                False,
                ["GitHub search reports incomplete results"] if incomplete_seen else [],
            )
        try:
            target = urlparse(next_url)
            safe_next = (
                not re.search(r"[\x00-\x20\x7f\\]", next_url)
                and target.scheme == "https"
                and target.netloc == origin.netloc
                and target.path in approved_paths
                and not target.fragment
            )
        except ValueError:
            safe_next = False
        if not safe_next:
            return (
                values,
                False,
                ["Rejected pagination URL outside the original metadata endpoint"],
            )
        if max_records is not None:
            next_page_sizes = parse_qs(target.query, keep_blank_values=True).get(
                "per_page"
            )
            if next_page_sizes is not None and next_page_sizes != [str(page_size)]:
                return values, False, ["Search pagination changed its fixed page size"]
            if next_page_sizes is None:
                first_params = {"per_page": page_size}
    if max_records is not None:
        return (
            values,
            False,
            ["GitHub search reports incomplete results"] if incomplete_seen else [],
        )
    return values, False, ["Pagination limit reached; inventory is incomplete"]
