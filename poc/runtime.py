"""Validated service configuration. Defaults remain safe for local development."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeConfig:
    site_dir: Path = ROOT / ".poc/public"
    public_origin: str | None = None
    serve_static: bool = True
    docs_enabled: bool = False
    max_body_bytes: int = 8192
    body_timeout: float = 5.0
    max_inflight: int = 8
    requests_per_minute: int = 60
    max_rate_clients: int = 4096
    kb_url: str = "https://knowledge.armdevtechapi.com/search"
    kb_token: str | None = field(default=None, repr=False)
    kb_deadline: float = 8.0
    kb_max_inflight: int = 4

    def __post_init__(self):
        object.__setattr__(self, "site_dir", Path(self.site_dir).resolve())
        for name, low, high in (
            ("max_body_bytes", 1024, 65536),
            ("max_inflight", 1, 64),
            ("requests_per_minute", 1, 10000),
            ("max_rate_clients", 1, 100000),
            ("kb_max_inflight", 1, 16),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        for name, high in (("body_timeout", 30), ("kb_deadline", 30)):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= high:
                raise ValueError(
                    f"{name} must be a positive duration of at most {high}s"
                )
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
                or "*" in parsed.netloc
            ):
                raise ValueError(
                    "ARM_SEARCH_PUBLIC_ORIGIN must be an HTTPS origin without a path"
                )
            # Accessing port also rejects malformed port strings.
            parsed.port
            object.__setattr__(self, "public_origin", self.public_origin.rstrip("/"))
        kb = urlsplit(self.kb_url)
        if (
            kb.scheme not in ("http", "https")
            or not kb.hostname
            or kb.username
            or kb.password
            or kb.query
            or kb.fragment
        ):
            raise ValueError(
                "ARM_KB_SEARCH_URL must be an HTTP(S) endpoint without credentials/query"
            )
        if kb.scheme != "https" and kb.hostname not in (
            "127.0.0.1",
            "localhost",
            "::1",
        ):
            raise ValueError("Non-loopback KB endpoints require HTTPS")
        if self.kb_token and any(c in self.kb_token for c in "\r\n"):
            raise ValueError("ARM_KB_API_TOKEN must not contain newlines")

    @property
    def allowed_hosts(self):
        if self.public_origin:
            return [urlsplit(self.public_origin).hostname]
        return ["localhost", "127.0.0.1", "[::1]"]

    @classmethod
    def from_env(cls):
        def flag(name, default):
            raw = os.environ.get(name)
            if raw is None:
                return default
            if raw not in ("true", "false"):
                raise ValueError(f"{name} must be true or false")
            return raw == "true"

        return cls(
            site_dir=Path(os.getenv("ARM_SEARCH_SITE_DIR", str(ROOT / ".poc/public"))),
            public_origin=os.getenv("ARM_SEARCH_PUBLIC_ORIGIN") or None,
            serve_static=flag("ARM_SEARCH_SERVE_STATIC", True),
            docs_enabled=flag(
                "ARM_SEARCH_DOCS_ENABLED",
                not bool(os.getenv("ARM_SEARCH_PUBLIC_ORIGIN")),
            ),
            max_body_bytes=int(os.getenv("ARM_SEARCH_MAX_BODY_BYTES", "8192")),
            body_timeout=float(os.getenv("ARM_SEARCH_BODY_TIMEOUT", "5")),
            max_inflight=int(os.getenv("ARM_SEARCH_MAX_INFLIGHT", "8")),
            requests_per_minute=int(os.getenv("ARM_SEARCH_REQUESTS_PER_MINUTE", "60")),
            max_rate_clients=int(os.getenv("ARM_SEARCH_MAX_RATE_CLIENTS", "4096")),
            kb_url=os.getenv(
                "ARM_KB_SEARCH_URL", "https://knowledge.armdevtechapi.com/search"
            ),
            kb_token=os.getenv("ARM_KB_API_TOKEN") or None,
            kb_deadline=float(os.getenv("ARM_SEARCH_KB_DEADLINE", "8")),
            kb_max_inflight=int(os.getenv("ARM_SEARCH_KB_MAX_INFLIGHT", "4")),
        )
