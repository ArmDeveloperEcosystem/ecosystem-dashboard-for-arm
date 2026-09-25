"""Bound caller latency and outstanding work for the synchronous KB API.

HTTPX phase timeouts do not bound total wall time: connection attempts can try
multiple DNS addresses. Callers stop waiting at the deadline, while a fixed
number of admitted workers finish or time out. A timed-out worker retains its
slot until it actually finishes, preventing an unbounded retry queue.
"""

from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx


class _RejectCookies(DefaultCookiePolicy):
    """Connection reuse must not carry provider session state between calls."""

    def set_ok(self, cookie, request):
        return False


class KBClient:
    """Bounded, reusable HTTP client; an optional transport supports offline tests."""

    def __init__(
        self,
        *,
        deadline: float = 8.0,
        max_inflight: int = 4,
        max_response_bytes: int = 2_000_000,
        transport: httpx.BaseTransport | None = None,
        trust_env: bool = True,
    ):
        if not math.isfinite(deadline) or deadline <= 0:
            raise ValueError("KB deadline must be a positive finite duration")
        if max_inflight < 1 or max_response_bytes < 1:
            raise ValueError("KB concurrency and response limits must be positive")
        self.deadline = deadline
        self.max_response_bytes = max_response_bytes
        self.transport = transport
        self.trust_env = trust_env
        self._max_inflight = max_inflight
        self._closed = False
        self._inflight = 0
        # add_done_callback can run immediately if a very fast request finished
        # before registration, so its completion handler needs a reentrant lock.
        self._lifecycle_lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._http: httpx.Client | None = None
        self._http_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_inflight, thread_name_prefix="arm-kb"
        )

    def fetch(self, endpoint: str, query: str, headers: dict[str, str]) -> dict:
        started = time.monotonic()
        with self._lifecycle_lock:
            if self._closed:
                raise httpx.ConnectError("Knowledge-base client is closed")
            if not self._slots.acquire(blocking=False):
                raise httpx.TimeoutException("Knowledge-base search is at capacity")
            self._inflight += 1
            try:
                future = self._executor.submit(
                    self._request, endpoint, query, dict(headers)
                )
            except BaseException:
                self._inflight -= 1
                self._slots.release()
                raise
            # Register before shutdown can observe this work. A caller timeout
            # must not release a slot while its network request is still running.
            future.add_done_callback(self._request_done)
        remaining = max(0.0, self.deadline - (time.monotonic() - started))
        try:
            return future.result(timeout=remaining)
        except FutureTimeout:
            # Cancellation only succeeds if the job has not started. A running
            # job keeps its slot until completion; it cannot grow the queue.
            future.cancel()
            raise httpx.TimeoutException(
                "Knowledge-base search exceeded its response deadline"
            ) from None

    def _request_done(self, _future) -> None:
        with self._lifecycle_lock:
            self._inflight -= 1
            self._slots.release()
            if self._closed and self._inflight == 0 and self._http is not None:
                self._http.close()

    def _http_client(self) -> httpx.Client:
        # Initialize in an admitted worker, never under the admission lock. TLS
        # setup is then covered by the caller deadline and unused default clients
        # do not inspect proxy/CA environment settings during module import.
        with self._http_lock:
            if self._http is None:
                self._http = httpx.Client(
                    timeout=httpx.Timeout(connect=2.0, read=6.0, write=2.0, pool=2.0),
                    limits=httpx.Limits(
                        max_connections=self._max_inflight,
                        max_keepalive_connections=self._max_inflight,
                    ),
                    follow_redirects=False,
                    trust_env=self.trust_env,
                    transport=self.transport,
                    cookies=CookieJar(policy=_RejectCookies()),
                )
            return self._http

    def _request(self, endpoint: str, query: str, headers: dict[str, str]) -> dict:
        worker_started = time.monotonic()
        # Headers remain request-local; never mutate defaults on the shared client.
        with self._http_client().stream(
            "GET", endpoint, params={"q": query, "k": 50}, headers=headers
        ) as response:
            response.raise_for_status()
            try:
                content_length = int(response.headers.get("content-length", "0"))
            except ValueError:
                content_length = 0
            if content_length > self.max_response_bytes:
                raise ValueError("KB response exceeds limit")
            body = bytearray()
            # Do not buffer up to a fixed chunk size: a slow trickle must be
            # checked against the worker deadline after each network chunk.
            for chunk in response.iter_bytes():
                if time.monotonic() - worker_started > self.deadline:
                    raise httpx.TimeoutException(
                        "Knowledge-base response stream exceeded deadline"
                    )
                if len(body) + len(chunk) > self.max_response_bytes:
                    raise ValueError("KB response exceeds limit")
                body.extend(chunk)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Invalid KB response")
        return payload

    def close(self, *, wait: bool = True) -> None:
        """Stop admission; close HTTP connections after admitted workers finish."""
        with self._lifecycle_lock:
            self._closed = True
            if self._inflight == 0 and self._http is not None:
                self._http.close()
        # Completion callbacks take the lifecycle lock. Never join workers (or
        # cancel pending futures, which also invokes callbacks) while holding it.
        self._executor.shutdown(wait=wait, cancel_futures=True)


_CLIENT = KBClient()


def fetch_kb(endpoint: str, query: str, headers: dict[str, str]) -> dict:
    """Fetch JSON with an eight-second caller deadline and four-work-item cap."""
    return _CLIENT.fetch(endpoint, query, headers)
