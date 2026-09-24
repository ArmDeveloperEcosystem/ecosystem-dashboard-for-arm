"""Reviewed GitHub release research; no model URL, credentials, or source execution.

Wire v2 operation: {kind: "github_release_download", step, line, research_id}.
Both sides independently derive the same source-bound ID. Research never repairs
Actions artifacts: missing run evidence requires a fresh authenticated execution.

Integration: research_downloads(context) returns bounded data for model selection.
resolve_download_operation(context, op) independently verifies and returns one
exact literal-run-block edit plus typed provenance. The caller must still apply
its whole-workflow policy, immutable-source checks and native Arm validation.
Do not admit arbitrary edits merely because a research ID exists.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import shlex
import signal
import socket
import ssl
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

import yaml

MAX_SOURCE = 128 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_ASSET = 128 * 1024 * 1024
MAX_REQUESTS = 40
MAX_CANDIDATES = 4
CACHE_SECONDS = 300
METADATA_SECONDS = 30
MAX_CACHE_ENTRIES = 32
MAX_CACHE_BYTES = 8 * 1024 * 1024
UNAUTHENTICATED_REQUESTS = 45
AUTHENTICATED_REQUESTS = 512
QUOTA_SECONDS = 3600
DEADLINE_SECONDS = 180
SOCKET_SECONDS = 15
_API = "https://api.github.com"
_REPO = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
_VERSION = re.compile(r"v?(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
_DOWNLOAD = re.compile(r"https://github\.com/(" + _REPO + r")/releases/download/([^/]+)/([^/]+)")
_VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]{0,63})(#v)?\}|\$([A-Z][A-Z0-9_]{0,63})")
_ASSIGN = re.compile(r"([A-Z][A-Z0-9_]{0,63})=(.*)")
_PATH = re.compile(r"(?:/tmp/)?[A-Za-z0-9][A-Za-z0-9._-]{0,150}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ID_KEYS = {"kind", "step", "line", "research_id"}


class ResearchError(ValueError):
    """Fixed diagnostics only; never include remote bodies, URLs or exception text."""


def _require(condition: bool, message: str = "upstream evidence is invalid") -> None:
    if not condition:
        raise ResearchError(message)


def _positive(value: Any) -> int:
    _require(type(value) is int and 0 < value < 10**19)
    return int(value)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _scope() -> tuple[Any, ...]:
    return (os.getpid(),) + tuple(
        os.environ.get(key, "")
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_SHA")
    )


class _RequestBudget:
    """Process-wide conservative ceiling, including newly constructed clients."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.started = time.monotonic()
        self.counts = {False: 0, True: 0}
        self.blocked_until = {False: 0.0, True: 0.0}

    def take(self, authenticated: bool) -> None:
        now = time.monotonic()
        if self.pid != os.getpid():
            self.pid = os.getpid()
            self.started = now
            self.counts = {False: 0, True: 0}
            self.blocked_until = {False: 0.0, True: 0.0}
        elif now - self.started >= QUOTA_SECONDS:
            self.started = now
            self.counts = {False: 0, True: 0}
        maximum = AUTHENTICATED_REQUESTS if authenticated else UNAUTHENTICATED_REQUESTS
        _require(
            now >= self.blocked_until[authenticated] and self.counts[authenticated] < maximum,
            "upstream API quota exhausted; defer research",
        )
        self.counts[authenticated] += 1

    def observe(self, authenticated: bool, status: int, headers: dict[str, str]) -> None:
        if status not in {403, 429} and headers.get("x-ratelimit-remaining") != "0":
            return
        # No automatic retries. A bounded future invocation may try again after
        # the server's reset; never sleep inside admission or rotate credentials.
        delay = float(QUOTA_SECONDS)
        reset = headers.get("x-ratelimit-reset", "")
        retry = headers.get("retry-after", "")
        if reset.isascii() and reset.isdigit() and len(reset) <= 12:
            delay = max(delay, int(reset) - time.time())
        if retry.isascii() and retry.isdigit() and len(retry) <= 8:
            delay = max(delay, float(retry))
        self.blocked_until[authenticated] = max(
            self.blocked_until[authenticated], time.monotonic() + delay
        )


_REQUEST_BUDGET = _RequestBudget()


def _version(value: Any) -> tuple[int, int, int]:
    _require(
        type(value) is str and _VERSION.fullmatch(value) is not None, "unsupported release version"
    )
    major, minor, patch = value.removeprefix("v").split(".")
    return int(major), int(minor), int(patch)


def _json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    try:
        _require(0 < len(raw) <= MAX_JSON)
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: _require(False))
    except (ValueError, UnicodeError, RecursionError):
        raise ResearchError("upstream JSON is invalid") from None


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    _require(
        threading.current_thread() is threading.main_thread(),
        "research requires main-thread deadline enforcement",
    )
    _require(hasattr(signal, "setitimer"), "research requires POSIX deadline enforcement")
    _require(
        not hasattr(signal, "pthread_sigmask")
        or signal.SIGALRM not in signal.pthread_sigmask(signal.SIG_BLOCK, []),
        "research deadline signal is blocked",
    )
    previous = signal.getsignal(signal.SIGALRM)
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    _require(remaining == 0 and interval == 0, "nested research deadlines are unsupported")

    def expired(_signum: int, _frame: Any) -> None:
        raise ResearchError("upstream research deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _url(value: str, *, cdn: bool = False) -> tuple[str, str]:
    _require(type(value) is str and len(value) <= 8192)
    _require(all(33 <= ord(char) <= 126 and char not in '\\"<>' for char in value))
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ResearchError("upstream URL is invalid") from None
    hosts = (
        {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        if cdn
        else {"api.github.com"}
    )
    _require(parts.scheme == "https" and parts.netloc in hosts and not parts.fragment)
    _require(not parts.username and not parts.password)
    if cdn:
        _require(parts.path.startswith("/github-production-release-asset"))
    else:
        endpoint = r"/repos/" + _REPO
        detail = (
            endpoint
            + r"(?:/releases/(?:tags/v?[0-9]+[.][0-9]+[.][0-9]+|assets/[1-9][0-9]*|[1-9][0-9]*))?"
        )
        listing = endpoint + r"/releases(?:/[1-9][0-9]*/assets)?"
        _require(
            bool(re.fullmatch(detail, parts.path))
            and not parts.query
            or bool(re.fullmatch(listing, parts.path))
            and bool(re.fullmatch(r"per_page=(?:10|100)&page=[1-3]", parts.query))
        )
        _require("%" not in parts.path and ".." not in parts.path.split("/"))
    return parts.netloc, parts.path + ("?" + parts.query if parts.query else "")


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, *, timeout: int = SOCKET_SECONDS) -> None:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        tls.load_default_certs()
        self._tls = tls
        super().__init__(host, timeout=timeout, context=tls)

    def connect(self) -> None:
        # Resolve once, reject mixed public/private answers, then connect to that
        # exact IP while authenticating the original hostname with TLS.
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        _require(bool(addresses), "upstream DNS unavailable")
        for family, _kind, _protocol, _canonical_name, address in addresses:
            _require(family in {socket.AF_INET, socket.AF_INET6})
            ip = ipaddress.ip_address(address[0])
            _require(
                ip.is_global and not ip.is_multicast and not ip.is_reserved,
                "upstream DNS is not public",
            )
        family, kind, protocol, _, address = addresses[0]
        raw = socket.socket(family, kind, protocol)
        try:
            raw.settimeout(self.timeout)
            raw.connect(address)
            self.sock = self._tls.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class GitHubReleases:
    """No-proxy transport; optional explicit read-only GitHub metadata token.

    Signed CDN query strings are used transiently and never returned or logged.
    Inject a fake client implementing get_json/asset_sha256 for offline tests;
    do not inject the repository's authenticated GitHub client.
    The caller must supply a read-only GitHub App/fine-grained token, never a
    model credential. No credentials are read from environment variables.
    Binary API and CDN requests remain unauthenticated.
    """

    def __init__(self, *, metadata_token: str | None = None) -> None:
        _require(
            metadata_token is None
            or type(metadata_token) is str
            and re.fullmatch(r"(?:ghs_|github_pat_)[A-Za-z0-9_]{20,240}", metadata_token)
            is not None,
            "expected an explicit read-only GitHub metadata token",
        )
        self._metadata_token = metadata_token
        self.expires = time.monotonic() + DEADLINE_SECONDS
        self.requests = 0

    def _request(
        self, url: str, *, binary: bool, cdn: bool = False
    ) -> tuple[int, dict[str, str], bytes | str]:
        host, path = _url(url, cdn=cdn)
        self.requests += 1
        _require(self.requests <= MAX_REQUESTS, "upstream request budget exhausted")
        _require(time.monotonic() < self.expires, "upstream research deadline exceeded")
        authenticated = not binary and not cdn and self._metadata_token is not None
        if not cdn:
            _REQUEST_BUDGET.take(authenticated)
        request_headers = {
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "User-Agent": "dashboard-reviewed-upstream-research",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept-Encoding": "identity",
        }
        if authenticated:
            _require(host == "api.github.com")
            request_headers["Authorization"] = "Bearer " + str(self._metadata_token)
        connection = _PinnedHTTPS(host, timeout=SOCKET_SECONDS)
        try:
            with _deadline(self.expires - time.monotonic()):
                connection.request(
                    "GET",
                    path,
                    headers=request_headers,
                )
                response = connection.getresponse()
                headers: dict[str, str] = {}
                for key, value in response.getheaders():
                    name = key.lower()
                    _require(
                        name not in headers
                        or name
                        not in {
                            "location",
                            "content-length",
                            "content-encoding",
                            "x-ratelimit-remaining",
                            "x-ratelimit-reset",
                            "retry-after",
                        }
                    )
                    headers[name] = value
                _require(headers.get("content-encoding", "identity") == "identity")
                if not cdn:
                    _REQUEST_BUDGET.observe(authenticated, response.status, headers)
                if response.status != 200:
                    return response.status, headers, b""
                limit = MAX_ASSET if binary else MAX_JSON
                length = headers.get("content-length")
                _require(
                    length is None
                    or length.isascii()
                    and length.isdigit()
                    and 0 < int(length) <= limit
                )
                hasher = hashlib.sha256()
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(65536, limit + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    _require(total <= limit, "upstream response exceeds size budget")
                    hasher.update(chunk)
                    if not binary:
                        chunks.append(chunk)
                _require(total > 0 and (length is None or int(length) == total))
                headers["verified-size"] = str(total)
                return response.status, headers, hasher.hexdigest() if binary else b"".join(chunks)
        except (OSError, http.client.HTTPException, ValueError):
            raise ResearchError("upstream request failed") from None
        finally:
            connection.close()

    def get_json(self, path: str) -> Any:
        _require(type(path) is str and path.startswith("/repos/"))
        status, _, body = self._request(_API + path, binary=False)
        if status == 404:
            return None
        _require(
            status == 200 and type(body) is bytes, "upstream metadata unavailable or redirected"
        )
        return _json(body)  # type: ignore[arg-type]

    def asset_sha256(self, path: str, size: int) -> str:
        _require(bool(re.fullmatch(r"/repos/" + _REPO + r"/releases/assets/[1-9][0-9]*", path)))
        _require(type(size) is int and 0 < size <= MAX_ASSET)
        status, headers, body = self._request(_API + path, binary=True)
        if status == 302:
            status, headers, body = self._request(
                headers.get("location", ""), binary=True, cdn=True
            )
        _require(
            status == 200
            and type(body) is str
            and _SHA.fullmatch(body) is not None
            and headers.get("verified-size") == str(size),
            "upstream asset could not be verified",
        )
        return str(body)


@dataclass(frozen=True)
class _Site:
    step: int
    line: int
    scalar: yaml.ScalarNode
    script: str
    lines: tuple[str, ...]
    url: str
    repository: str
    tag: str
    name: str
    output: str
    url_word: str
    assignment: tuple[int, str, str] | None
    checksum_line: int | None


def _field(node: yaml.Node, name: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    entries = [
        value for key, value in node.value if isinstance(key, yaml.ScalarNode) and key.value == name
    ]
    _require(len(entries) <= 1, "duplicate workflow fields")
    return entries[0] if entries else None


def _scalar(node: yaml.Node | None) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _tree(source: str) -> yaml.Node:
    try:
        events = list(yaml.parse(source))
        _require(
            len(events) < 16384
            and not any(
                isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None)
                for event in events
            ),
            "workflow aliases are unsupported",
        )
        node = yaml.compose(source)
        _require(node is not None)
        return cast(yaml.Node, node)
    except (yaml.YAMLError, RecursionError):
        raise ResearchError("workflow YAML is invalid") from None


def _environment(node: yaml.Node) -> dict[str, str]:
    env = _field(node, "env")
    if env is None:
        return {}
    _require(isinstance(env, yaml.MappingNode), "dynamic workflow environment")
    env = cast(yaml.MappingNode, env)
    result: dict[str, str] = {}
    for key, value in env.value:
        _require(isinstance(key, yaml.ScalarNode) and isinstance(value, yaml.ScalarNode))
        _require(key.value not in result, "duplicate environment field")
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key.value) and not any(
            token in value.value for token in ("$", "`", "\n", "\r")
        ):
            result[key.value] = value.value
    return result


def _expand(text: str, values: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match[1] or match[3]
        _require(name in values, "dynamic download variable")
        value = values[name]
        return value.removeprefix("v") if match[2] else value

    result = _VARIABLE.sub(substitute, text)
    _require(
        not any(token in result for token in ("$", "`", "\n", "\r")), "dynamic download expression"
    )
    return result


def _words(line: str) -> list[str]:
    _require(not any(token in line for token in ("`", "$(", "\\", "\r")), "dynamic download shell")
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        raise ResearchError("ambiguous download shell") from None


def _download(words: list[str], values: dict[str, str]) -> tuple[str, str]:
    _require(bool(words) and words[0] in {"curl", "/usr/bin/curl", "wget", "/usr/bin/wget"})
    curl = words[0].endswith("curl")
    urls: list[str] = []
    output: str | None = None
    remote_name = False
    fail = not curl
    index = 1
    while index < len(words):
        word = words[index]
        if curl and (
            word in {"--fail", "--location", "--silent", "--show-error"}
            or re.fullmatch(r"-[fsSL]+", word)
        ):
            fail = fail or word == "--fail" or word.startswith("-") and "f" in word
        elif not curl and word in {"-q", "--quiet", "-nv", "--no-verbose"}:
            pass
        elif curl and word in {"-O", "--remote-name"}:
            remote_name = True
        elif word in ({"-o", "--output"} if curl else {"-O", "--output-document"}):
            index += 1
            _require(index < len(words) and output is None)
            output = _expand(words[index], values)
        elif curl and word in {
            "--retry",
            "--retry-delay",
            "--retry-max-time",
            "--max-time",
            "--connect-timeout",
        }:
            index += 1
            _require(index < len(words) and bool(re.fullmatch(r"[1-9][0-9]{0,2}", words[index])))
        else:
            urls.append(_expand(word, values))
        index += 1
    _require(fail and len(urls) == 1 and not (remote_name and output))
    match = _DOWNLOAD.fullmatch(urls[0])
    _require(match is not None, "unsupported upstream download source")
    match = cast(re.Match[str], match)
    output = output or match[3]
    _require(
        _PATH.fullmatch(output) is not None and ".." not in output,
        "dynamic or unsafe download destination",
    )
    return urls[0], output


def _checksum(lines: tuple[str, ...], download_line: int, output: str) -> int | None:
    matches = []
    for index, line in enumerate(lines):
        if re.search(r"sha(?:256|512)sum|shasum|openssl\s+dgst|CHECKSUM|SHA256", line, re.I):
            # Accept only the common immediately-following literal sha256 check.
            pattern = (
                r"\s*echo [\"']([0-9a-f]{64})  "
                + re.escape(output)
                + r"[\"'] \| sha256sum (?:-c|--check) -\n?"
            )
            _require(
                index == download_line + 1 and re.fullmatch(pattern, line) is not None,
                "unsupported existing checksum contract",
            )
            matches.append(index)
    _require(len(matches) <= 1)
    return matches[0] if matches else None


def _sites(context: dict[str, Any]) -> list[_Site]:
    source = context.get("source_text")
    _require(
        type(source) is str
        and 0 < len(source.encode("utf-8")) <= MAX_SOURCE
        and "\r" not in source
        and "\x00" not in source
    )
    _require(
        type(context.get("package_slug")) is str
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", context["package_slug"]))
    )
    _require(
        context.get("workflow_path") == f".github/workflows/test-{context['package_slug']}.yml"
    )
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", context.get("base_sha", ""))))
    _require(context.get("repository") == "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm")
    tree = _tree(str(source))
    jobs = _field(tree, "jobs")
    _require(
        isinstance(jobs, yaml.MappingNode) and len(jobs.value) == 1,
        "research requires one package job",
    )
    jobs = cast(yaml.MappingNode, jobs)
    job = jobs.value[0][1]
    steps = _field(job, "steps")
    _require(isinstance(steps, yaml.SequenceNode) and len(steps.value) <= 256)
    steps = cast(yaml.SequenceNode, steps)
    global_values = {**_environment(tree), **_environment(job)}
    result = []
    for step_index, step in enumerate(steps.value):
        identifier = _scalar(_field(step, "id")) or ""
        name = _scalar(_field(step, "name")) or ""
        if (
            identifier.startswith("test")
            or re.search(r"metadata|summary|report|version", name, re.I)
            or not (
                identifier in {"install", "setup"} or re.match(r"(?:install|setup)\b", name, re.I)
            )
        ):
            continue
        scalar = _field(step, "run")
        if not isinstance(scalar, yaml.ScalarNode) or scalar.style != "|":
            continue
        lines = tuple(scalar.value.splitlines(keepends=True))
        values = {**global_values, **_environment(step)}
        assignments: dict[str, tuple[int, str]] = {}
        dependencies: dict[str, set[str]] = {}
        safe_prefix = True
        for index, line in enumerate(lines):
            stripped = line.strip()
            if (
                stripped.endswith("\\")
                or "`" in line
                or "<<" in line
                or re.match(
                    r"(?:if|for|while|until|case|function|select|eval|source|alias|exec|return|exit)\b"
                    r"|[{}()]|[A-Za-z_][A-Za-z0-9_]*\s*\(\)|\.\s",
                    stripped,
                )
            ):
                safe_prefix = False
            assignment = _ASSIGN.fullmatch(stripped)
            if assignment:
                try:
                    words = _words(stripped)
                    _require(len(words) == 1)
                    variable, raw = words[0].split("=", 1)
                    value = _expand(raw, values)
                    _require(variable not in assignments, "reassigned download variable")
                    direct = {item[1] or item[3] for item in _VARIABLE.finditer(raw)}
                    dependencies[variable] = direct | set().union(
                        *(dependencies.get(item, set()) for item in direct)
                    )
                    assignments[variable] = (index, raw)
                    values[variable] = value
                except ResearchError:
                    values.pop(assignment[1], None)
                    safe_prefix = False
                continue
            if not re.match(r"(?:/usr/bin/)?(?:curl|wget)\s", stripped):
                continue
            _require(safe_prefix, "conditional or dynamic download requires review")
            download_words = _words(stripped)
            url, output = _download(download_words, values)
            url_words = [word for word in download_words[1:] if _expand(word, values) == url]
            _require(len(url_words) == 1)
            direct = {item[1] or item[3] for item in _VARIABLE.finditer(url_words[0])}
            used = direct | set().union(*(dependencies.get(item, set()) for item in direct))
            match = _DOWNLOAD.fullmatch(url)
            match = cast(re.Match[str], match)
            _version(match[2])
            _require(_NAME.fullmatch(match[3]) is not None)
            local_version = [
                (number, variable, raw)
                for variable, (number, raw) in assignments.items()
                if variable in used
                and _VERSION.fullmatch(raw)
                and _version(raw) == _version(match[2])
            ]
            _require(len(local_version) <= 1, "ambiguous install version")
            _require(
                not any("GITHUB_ENV" in item for item in lines), "cross-step install variables"
            )
            result.append(
                _Site(
                    step_index,
                    index,
                    scalar,
                    scalar.value,
                    lines,
                    url,
                    match[1],
                    match[2],
                    match[3],
                    output,
                    url_words[0],
                    local_version[0] if local_version else None,
                    _checksum(lines, index, output),
                )
            )
    _require(len(result) <= 4, "too many download sites")
    _require(
        len({site.step for site in result}) == len(result),
        "multiple downloads in one setup block require coordinated repair",
    )
    return result


def _family(name: str, tag: str) -> str:
    _require(_NAME.fullmatch(name) is not None)
    lowered = name.lower()
    _require(bool(re.search(r"(?:^|[-_.])linux(?:[-_.]|$)", lowered)))
    _require(
        bool(re.search(r"(?:^|[-_.])(?:arm64|aarch64)(?:[-_.]|$)", lowered)),
        "asset is not explicitly Linux Arm64",
    )
    _require(
        not re.search(
            r"(?:^|[-_.])(?:amd64|x86|x86_64|i686|darwin|windows|win32|armv7)(?:[-_.]|$)", lowered
        )
    )
    suffix = next(
        (
            ext
            for ext in (".tar.gz", ".tar.xz", ".tgz", ".zip", ".gz", ".deb", ".rpm")
            if lowered.endswith(ext)
        ),
        "",
    )
    stem = lowered[: -len(suffix)] if suffix else lowered
    numeric = tag.removeprefix("v")
    stem = re.sub(r"(?<![a-z0-9])v?" + re.escape(numeric) + r"(?![a-z0-9])", "", stem)
    tokens = [token for token in re.split(r"[-_.]+", stem) if token]
    tokens = ["arm64" if component == "aarch64" else component for component in tokens]
    _require(
        any(token not in {"linux", "arm64", "gnu", "musl", "static"} for token in tokens),
        "asset lacks package identity",
    )
    return "-".join(tokens) + suffix


def _release(value: Any, repository: str) -> dict[str, Any]:
    _require(type(value) is dict)
    ident = _positive(value.get("id"))
    tag = value.get("tag_name")
    _version(tag)
    prefix = f"{_API}/repos/{repository}/releases/{ident}"
    _require(
        value.get("url") == prefix
        and value.get("assets_url") == prefix + "/assets"
        and value.get("html_url") == f"https://github.com/{repository}/releases/tag/{tag}"
        and value.get("draft") is False
        and value.get("prerelease") is False
    )
    published = value.get("published_at")
    try:
        _require(type(published) is str)
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        _require(date.tzinfo is not None and date <= datetime.now(UTC))
    except (ValueError, TypeError):
        raise ResearchError("release publication is invalid") from None
    return dict(value)


def _assets(client: Any, repository: str, release_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 4):
        value = client.get_json(
            f"/repos/{repository}/releases/{release_id}/assets?per_page=100&page={page}"
        )
        _require(type(value) is list and len(value) <= 100)
        for asset in value:
            _require(type(asset) is dict)
            _positive(asset.get("id"))
            _require(type(asset.get("name")) is str)
            rows.append(asset)
        if len(value) < 100:
            _require(
                len({item["id"] for item in rows}) == len(rows)
                and len({item["name"] for item in rows}) == len(rows),
                "ambiguous release assets",
            )
            return rows
    raise ResearchError("release assets exceed inventory budget")


def _replacement(site: _Site, tag: str, url: str, checksum: str) -> str:
    lines = list(site.lines)
    if _version(tag) != _version(site.tag):
        _require(
            _version(tag)[:2] == _version(site.tag)[:2] and _version(tag) > _version(site.tag),
            "unsupported release upgrade",
        )
        # Only an install-local literal may move. Global pins, other package
        # sources and Test 1-6 version expectations are never rewritten.
        if site.assignment:
            index, name, value = site.assignment
            new_value = tag if value.startswith("v") else tag.removeprefix("v")
            original = lines[index]
            _require(original.count(value) == 1)
            lines[index] = original.replace(value, new_value, 1)
        else:
            _require(
                site.url in lines[site.line], "global or dynamic version pin requires manual repair"
            )
    original = lines[site.line]
    words = _words(original.strip())
    # Replace only the URL word (possibly a literal variable reference); shlex
    # locates it semantically, and the source span must be unique.
    _require(original.count(site.url_word) == 1, "ambiguous download URL span")
    replacement = original.replace(site.url_word, url, 1)
    # Preserve remote-name output only when the new filename is identical.
    if not any(word in {"-o", "--output", "--output-document"} for word in words):
        if words[0].endswith("curl") or "-O" not in words:
            _require(
                url.rsplit("/", 1)[1] == site.output, "renamed implicit output requires review"
            )
    lines[site.line] = replacement
    if site.checksum_line is not None:
        lines[site.checksum_line] = re.sub(
            r"[0-9a-f]{64}", checksum, lines[site.checksum_line], count=1
        )
    else:
        indent = original[: len(original) - len(original.lstrip())]
        _require(original.endswith("\n"), "download requires a complete line")
        lines.insert(
            site.line + 1,
            indent + f"echo '{checksum}  {site.output}' | sha256sum --check - || exit 1\n",
        )
    return "".join(lines)


def _verified(
    client: Any,
    context: dict[str, Any],
    site: _Site,
    repo_id: int,
    release: dict[str, Any],
    asset: dict[str, Any],
    verified_bytes: dict[str, str],
) -> dict[str, Any]:
    asset_id = _positive(asset.get("id"))
    tag = release["tag_name"]
    name = asset.get("name")
    _require(
        type(name) is str and _family(name, tag) == _family(site.name, site.tag),
        "asset package or platform changed",
    )
    url = f"https://github.com/{site.repository}/releases/download/{tag}/{name}"
    path = f"/repos/{site.repository}/releases/assets/{asset_id}"
    digest = asset.get("digest")
    size = asset.get("size")
    _require(
        asset.get("url") == _API + path
        and asset.get("browser_download_url") == url
        and asset.get("state") == "uploaded"
        and type(size) is int
        and 0 < size <= MAX_ASSET
        and type(digest) is str
        and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None,
        "asset lacks verified integrity provenance",
    )
    _require(client.get_json(path) == asset, "release asset changed during research")
    checksum = str(digest).removeprefix("sha256:")
    proof = {
        "repository": site.repository,
        "repository_id": repo_id,
        "release": {
            key: release[key]
            for key in (
                "id",
                "tag_name",
                "url",
                "assets_url",
                "html_url",
                "draft",
                "prerelease",
                "published_at",
            )
        },
        "asset": {
            key: asset[key]
            for key in ("id", "name", "url", "browser_download_url", "state", "size", "digest")
        },
    }
    byte_identity = _digest(proof)
    verified_digest = verified_bytes.get(byte_identity)
    if verified_digest is None:
        verified_digest = client.asset_sha256(path, size)
    _require(verified_digest == checksum, "download differs from release digest")
    new_script = _replacement(site, tag, url, checksum)
    _require(new_script != site.script)
    binding = {
        "schema_version": 2,
        "repository": context["repository"],
        "base_sha": context["base_sha"],
        "workflow_path": context["workflow_path"],
        "package_slug": context["package_slug"],
        "source_sha256": hashlib.sha256(context["source_text"].encode()).hexdigest(),
        "step": site.step,
        "line": site.line,
        "upstream_repository": site.repository,
        "repository_id": repo_id,
        "release_id": release["id"],
        "asset_id": asset_id,
        "version": tag,
        "sha256": checksum,
        "old_url": site.url,
        "new_url": url,
        "new_script_sha256": hashlib.sha256(new_script.encode()).hexdigest(),
    }
    source = context["source_text"]
    old = source[site.scalar.start_mark.index : site.scalar.end_mark.index]
    header, separator, _ = old.partition("\n")
    _require(bool(separator) and bool(re.fullmatch(r"\|[-+]? *", header)))
    nonempty = [line for line in old.splitlines()[1:] if line.strip()]
    indent = min(len(line) - len(line.lstrip(" ")) for line in nonempty)
    new = (
        header
        + "\n"
        + "".join(
            " " * indent + line if line.strip() else line
            for line in new_script.splitlines(keepends=True)
        )
    )
    return {
        **{
            key: binding[key]
            for key in (
                "step",
                "line",
                "repository_id",
                "release_id",
                "asset_id",
                "version",
                "sha256",
            )
        },
        "research_id": _digest(binding),
        "edit": {"path": context["workflow_path"], "old": old, "new": new},
        "_byte_identity": byte_identity,
    }


def _research(
    context: dict[str, Any], client: Any, *, verified_bytes: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    sites = _sites(context)
    candidates: list[dict[str, Any]] = []
    unsupported: set[str] = set()
    for site in sites:
        _family(site.name, site.tag)
        repo = client.get_json(f"/repos/{site.repository}")
        _require(
            type(repo) is dict
            and repo.get("full_name") == site.repository
            and repo.get("private") is False
            and repo.get("fork") is False
            and repo.get("html_url") == f"https://github.com/{site.repository}",
            "upstream repository identity changed",
        )
        repo_id = _positive(repo.get("id"))
        original = client.get_json(f"/repos/{site.repository}/releases/tags/{site.tag}")
        releases: list[dict[str, Any]] = []
        original_assets: list[dict[str, Any]] = []
        if original is not None:
            original = _release(original, site.repository)
            _require(original["tag_name"] == site.tag)
            existing = _assets(client, site.repository, original["id"])
            original_assets = existing
            if any(asset["name"] == site.name for asset in existing):
                unsupported.add("upstream_asset_present")
                continue
            releases.append(original)
        recent = client.get_json(f"/repos/{site.repository}/releases?per_page=10&page=1")
        _require(type(recent) is list and len(recent) <= 10)
        seen: set[int] = set()
        for item in recent:
            _require(type(item) is dict)
            ident = _positive(item.get("id"))
            _require(ident not in seen, "duplicate release identity")
            seen.add(ident)
            if item.get("draft") is not False or item.get("prerelease") is not False:
                continue
            try:
                version = _version(item.get("tag_name"))
            except ResearchError:
                continue
            if version[:2] == _version(site.tag)[:2] and version > _version(site.tag):
                releases.append(_release(item, site.repository))
        releases.sort(
            key=lambda row: (
                _version(row["tag_name"]) != _version(site.tag),
                tuple(-part for part in _version(row["tag_name"])),
            )
        )
        found = False
        for release in releases:
            if release == original:
                inventory = original_assets
            else:
                live = client.get_json(f"/repos/{site.repository}/releases/{release['id']}")
                _require(live == release, "release changed during research")
                inventory = _assets(client, site.repository, release["id"])
            matches = []
            for asset in inventory:
                try:
                    if _family(asset["name"], release["tag_name"]) == _family(site.name, site.tag):
                        matches.append(asset)
                except ResearchError:
                    continue
            _require(len(matches) <= 1, "ambiguous matching Arm assets")
            if matches:
                candidates.append(
                    _verified(
                        client, context, site, repo_id, release, matches[0], verified_bytes or {}
                    )
                )
                found = True
                break
        if not found:
            unsupported.add("no_supported_verified_arm_asset")
    if not sites:
        unsupported.add("no_supported_download_site")
    _require(len(candidates) <= MAX_CANDIDATES)
    return candidates, sorted(unsupported)


@dataclass(frozen=True)
class _VerifiedEntry:
    created: float
    checked: float
    generation: int
    payload: bytes


class ResearchSession:
    """Bounded in-memory verified evidence, never a cross-job approval.

    refresh() marks the next use of each entry for live metadata discovery.
    Only unchanged repository/release/asset identities and digests may reuse
    verified bytes. No HTTP metadata, failed or partial research is cached.
    """

    def __init__(self, *, metadata_token: str | None = None, client: Any = None) -> None:
        _require(client is None or metadata_token is None, "ambiguous research client")
        if metadata_token is not None:
            GitHubReleases(metadata_token=metadata_token)  # Validate without network access.
        self._token = metadata_token
        self._client = client
        self._scope = _scope()
        self._generation = 0
        self._entries: OrderedDict[tuple[str, str], _VerifiedEntry] = OrderedDict()

    def clear(self) -> None:
        self._entries.clear()

    def refresh(self) -> None:
        """Begin a new admission boundary; re-fetch metadata before reuse."""
        self._generation += 1

    def _transport(self) -> Any:
        if self._client is not None:
            return self._client
        return GitHubReleases(metadata_token=self._token) if self._token else GitHubReleases()

    def lookup(self, context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        _require(
            threading.current_thread() is threading.main_thread(),
            "research requires main-thread deadline enforcement",
        )
        _sites(context)
        try:
            encoded_context = _canonical(context)
            _require(len(encoded_context) <= 1024 * 1024, "research context exceeds size budget")
        except (TypeError, ValueError, RecursionError):
            raise ResearchError("research context is invalid") from None
        context_id = hashlib.sha256(encoded_context).hexdigest()
        current_scope = _scope()
        if current_scope != self._scope:
            self.clear()
            self._scope = current_scope
        now = time.monotonic()
        for key, value in list(self._entries.items()):
            if now - value.created >= CACHE_SECONDS:
                del self._entries[key]
        match = next((key for key in self._entries if key[0] == context_id), None)
        previous: _VerifiedEntry | None = None
        verified_bytes: dict[str, str] = {}
        if match is not None:
            previous = self._entries.pop(match)
            candidates, unsupported = json.loads(previous.payload)
            if (
                previous.generation == self._generation
                and now - previous.checked < METADATA_SECONDS
            ):
                self._entries[match] = previous
                return candidates, unsupported
            verified_bytes = {row["_byte_identity"]: row["sha256"] for row in candidates}
        # Evicted before refetch: a failed refresh must never fall back to stale
        # evidence. Discovery revalidates ownership, membership and integrity.
        candidates, unsupported = _research(
            context, self._transport(), verified_bytes=verified_bytes
        )
        if candidates and not unsupported:
            payload = _canonical((candidates, unsupported))
            if len(payload) <= MAX_CACHE_BYTES:
                identity = _digest(
                    [(row["research_id"], row["_byte_identity"]) for row in candidates]
                )
                key = (context_id, identity)
                reused_bytes = any(row["_byte_identity"] in verified_bytes for row in candidates)
                created = previous.created if previous and reused_bytes else time.monotonic()
                self._entries[key] = _VerifiedEntry(
                    created, time.monotonic(), self._generation, payload
                )
                while (
                    len(self._entries) > MAX_CACHE_ENTRIES
                    or sum(len(entry.payload) for entry in self._entries.values()) > MAX_CACHE_BYTES
                ):
                    self._entries.popitem(last=False)
        return candidates, unsupported


_DEFAULT_SESSION = ResearchSession()
_ACTIVE_SESSION: ContextVar[ResearchSession | None] = ContextVar("upstream_research", default=None)


@contextmanager
def research_session(
    *, metadata_token: str | None = None, client: Any = None
) -> Iterator[ResearchSession]:
    """One intake/admission stage. A new session never imports another's cache.

    Call session.refresh() before a later publication/admission boundary.
    Supply only the public read-only App credential, before model-token access.
    The session and credential are never serialized into research/model data.
    """
    session = ResearchSession(metadata_token=metadata_token, client=client)
    token = _ACTIVE_SESSION.set(session)
    try:
        yield session
    finally:
        session.clear()
        session._token = None
        _ACTIVE_SESSION.reset(token)


def _cached_research(
    context: dict[str, Any], client: Any, *, fresh: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    # Explicit fake/custom clients retain independent research semantics unless
    # deliberately installed in a scoped session.
    if client is not None:
        return _research(context, client)
    session = _ACTIVE_SESSION.get() or _DEFAULT_SESSION
    if fresh:
        session.refresh()
    return session.lookup(context)


def research_downloads(
    context: dict[str, Any], *, client: Any = None, fresh: bool = False
) -> dict[str, Any]:
    """Return only source-bound IDs and finite/validated public facts, never prose.

    context MUST be independently authenticated to the reviewed dashboard base.
    A supplied catalog is not an authority for release ownership: its existing
    workflow identity is advisory. The authenticated source download is the
    repository anchor; no repository is inferred from logs, prompts or search.
    """
    candidates, unsupported = _cached_research(context, client, fresh=fresh)
    return {
        "schema_version": 2,
        "source_sha256": hashlib.sha256(context["source_text"].encode()).hexdigest(),
        "candidates": [
            {key: value for key, value in row.items() if key not in {"edit", "_byte_identity"}}
            for row in candidates
        ],
        "unsupported": unsupported,
    }


def validate_download_operation(operation: Any) -> dict[str, Any]:
    _require(
        type(operation) is dict
        and set(operation) == _ID_KEYS
        and operation.get("kind") == "github_release_download",
        "invalid download operation",
    )
    for key, maximum in (("step", 255), ("line", 4095)):
        _require(
            type(operation[key]) is int and 0 <= operation[key] <= maximum,
            "invalid download operation index",
        )
    _require(
        type(operation["research_id"]) is str
        and _SHA.fullmatch(operation["research_id"]) is not None,
        "invalid research ID",
    )
    return dict(operation)


def resolve_download_operation(
    context: dict[str, Any], operation: Any, *, client: Any = None, fresh: bool = False
) -> dict[str, Any]:
    """Independently verify upstream; return exactly one compiler-generated edit.

    Parent policy must authorize this exact old/new edit only in the referenced
    setup step, preserve every other step/gate, and still require native tests.
    Fresh verified process-local evidence is reusable for at most 30 seconds;
    fresh=True or session.refresh() rechecks metadata at an admission boundary.
    """
    operation = validate_download_operation(operation)
    candidates, _ = _cached_research(context, client, fresh=fresh)
    matches = [
        row
        for row in candidates
        if all(row[key] == operation[key] for key in ("step", "line", "research_id"))
    ]
    _require(len(matches) == 1, "research selection is stale, forged or unsupported")
    return {key: value for key, value in matches[0].items() if key != "_byte_identity"}


def verify_download_edit(
    context: dict[str, Any], edit: Any, *, step: int, client: Any = None
) -> bool:
    """Independently authorize one complete, reconstructed setup-block edit."""
    if (
        type(edit) is not dict
        or set(edit) != {"path", "old", "new"}
        or edit.get("path") != context.get("workflow_path")
        or any(type(edit.get(key)) is not str for key in ("old", "new"))
        or "github.com/" not in edit["old"]
        or "/releases/download/" not in edit["old"]
    ):
        return False
    candidates, _ = _cached_research(context, client, fresh=False)
    return bool(sum(row["step"] == step and row["edit"] == edit for row in candidates) == 1)
