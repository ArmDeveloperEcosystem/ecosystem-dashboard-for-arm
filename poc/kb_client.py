"""Bound caller latency and outstanding work for the synchronous KB API.

HTTPX phase timeouts do not bound total wall time: connection attempts can try
multiple DNS addresses. Callers stop waiting at the deadline, while a fixed
number of admitted workers finish or time out. A timed-out worker retains its
slot until it actually finishes, preventing an unbounded retry queue.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import math
import threading
import time

import httpx


class KBClient:
    """Small bounded HTTP client; an optional transport supports offline tests."""

    def __init__(
        self,
        *,
        deadline: float = 8.0,
        max_inflight: int = 4,
        max_response_bytes: int = 2_000_000,
        transport: httpx.BaseTransport | None = None,
    ):
        if not math.isfinite(deadline) or deadline <= 0:
            raise ValueError("KB deadline must be a positive finite duration")
        if max_inflight < 1 or max_response_bytes < 1:
            raise ValueError("KB concurrency and response limits must be positive")
        self.deadline = deadline
        self.max_response_bytes = max_response_bytes
        self.transport = transport
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._executor = ThreadPoolExecutor(
            max_workers=max_inflight, thread_name_prefix="arm-kb"
        )

    def fetch(self, endpoint: str, query: str, headers: dict[str, str]) -> dict:
        started = time.monotonic()
        if not self._slots.acquire(blocking=False):
            raise httpx.TimeoutException("Knowledge-base search is at capacity")
        try:
            future = self._executor.submit(self._request, endpoint, query, dict(headers))
        except BaseException:
            self._slots.release()
            raise
        # Releasing on the caller's timeout would admit more work while its
        # previous network request is still running. Release only on completion.
        future.add_done_callback(lambda _: self._slots.release())
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

    def _request(self, endpoint: str, query: str, headers: dict[str, str]) -> dict:
        timeout = httpx.Timeout(connect=2.0, read=6.0, write=2.0, pool=2.0)
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=True,
            transport=self.transport,
        ) as client:
            with client.stream(
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
                for chunk in response.iter_bytes(chunk_size=65_536):
                    if len(body) + len(chunk) > self.max_response_bytes:
                        raise ValueError("KB response exceeds limit")
                    body.extend(chunk)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Invalid KB response")
        return payload

    def close(self) -> None:
        """Finish admitted requests and release the worker pool (used by tests)."""
        self._executor.shutdown(wait=True, cancel_futures=True)


_CLIENT = KBClient()


def fetch_kb(endpoint: str, query: str, headers: dict[str, str]) -> dict:
    """Fetch JSON with an eight-second caller deadline and four-work-item cap."""
    return _CLIENT.fetch(endpoint, query, headers)
