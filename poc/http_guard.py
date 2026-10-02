"""ASGI admission and streaming limits; no raw query, client or token logging."""

from __future__ import annotations

import asyncio
from collections import Counter
import json
import logging
import math
import time

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

LOGGER = logging.getLogger("arm_search.requests")


class SearchBoundary:
    def __init__(self, app, config, metrics):
        self.app = app
        self.config = config
        self.metrics = metrics
        self.inflight = 0
        self.clients = {}

    def admit_client(self, client):
        now = time.monotonic()
        # State is bounded even if every request has a different source IP.
        self.clients = {k: v for k, v in self.clients.items() if now - v[0] < 60}
        previous = self.clients.get(client)
        if previous is None:
            if len(self.clients) >= self.config.max_rate_clients:
                return False
            self.clients[client] = (now, 1)
            return True
        start, count = previous
        if count >= self.config.requests_per_minute:
            return False
        self.clients[client] = (start, count + 1)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        root_path = scope.get("root_path", "").rstrip("/")
        if root_path and (path == root_path or path.startswith(root_path + "/")):
            path = path[len(root_path) :] or "/"
        is_api = path.startswith("/api/")
        is_search = path == "/api/search" and scope["method"] == "POST"
        started = time.monotonic()
        status = 500

        async def safe_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                if is_api:
                    headers = list(message.get("headers", []))
                    headers.extend(
                        [
                            (b"cache-control", b"no-store"),
                            (b"x-content-type-options", b"nosniff"),
                        ]
                    )
                    message = {**message, "headers": headers}
            await send(message)

        async def reject(code, detail):
            self.metrics[f"rejected_{code}"] += 1
            headers = {"Retry-After": "60"} if code == 429 else {}
            if code == 503:
                headers["Retry-After"] = "1"
            await JSONResponse({"detail": detail}, status_code=code, headers=headers)(
                scope, receive, safe_send
            )

        if not is_search:
            return await self.app(scope, receive, safe_send)
        admitted = False
        try:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            expected = self.config.public_origin or (
                scope["scheme"] + "://" + headers.get("host", "")
            )
            if origin and origin.rstrip("/") != expected:
                return await reject(403, "Cross-origin requests are not allowed.")
            if headers.get("sec-fetch-site") == "cross-site":
                return await reject(403, "Cross-origin requests are not allowed.")
            lengths = headers.getlist("content-length")
            try:
                if len(lengths) > 1:
                    raise ValueError
                length = int(lengths[0]) if lengths else 0
                if length < 0:
                    raise ValueError
            except ValueError:
                return await reject(400, "Invalid Content-Length.")
            if length > self.config.max_body_bytes:
                return await reject(413, "Request too large.")
            if headers.get("content-encoding", "identity").lower() != "identity":
                return await reject(415, "Compressed request bodies are not supported.")
            if (
                headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                return await reject(415, "Content-Type must be application/json.")
            client = (scope.get("client") or ("unknown", 0))[0]
            if not self.admit_client(client):
                return await reject(
                    429, "Search rate limit reached. Please retry later."
                )
            if self.inflight >= self.config.max_inflight:
                return await reject(503, "Search is at capacity. Please retry shortly.")
            self.inflight += 1
            admitted = True
            body = bytearray()
            try:
                async with asyncio.timeout(self.config.body_timeout):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > self.config.max_body_bytes:
                            return await reject(413, "Request too large.")
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "Request body timed out.")
            try:

                def invalid_constant(_):
                    raise ValueError("Non-standard JSON constant")

                parsed = json.loads(body, parse_constant=invalid_constant)
                pending = [(parsed, 0)]
                while pending:
                    value, depth = pending.pop()
                    if depth > 16:
                        raise ValueError("JSON nesting exceeds limit")
                    if isinstance(value, dict):
                        pending.extend(
                            (part, depth + 1) for pair in value.items() for part in pair
                        )
                    elif isinstance(value, list):
                        pending.extend((part, depth + 1) for part in value)
                    elif isinstance(value, str):
                        value.encode("utf-8")
                    elif isinstance(value, float) and not math.isfinite(value):
                        raise ValueError("JSON number is not finite")
            except (ValueError, UnicodeError, RecursionError):
                return await reject(400, "Invalid JSON body.")
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            await self.app(scope, bounded_receive, safe_send)
        finally:
            if admitted:
                self.inflight -= 1
            elapsed = round((time.monotonic() - started) * 1000)
            self.metrics["search_requests"] += 1
            self.metrics[f"search_status_{status}"] += 1
            self.metrics["search_duration_ms"] += elapsed
            LOGGER.info("search_request status=%s duration_ms=%s", status, elapsed)


def new_metrics():
    return Counter()
