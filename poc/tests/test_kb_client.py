"""Offline behavior tests for latency, bounded admission and HTTP safety."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import httpx
import pytest

from poc.kb_client import KBClient

ENDPOINT = "https://kb.example.test/search"


def test_deadline_returns_while_slow_worker_keeps_its_slot_then_recovers():
    release = threading.Event()
    returned_from_transport = threading.Event()
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            release.wait()
            returned_from_transport.set()
        return httpx.Response(200, json={"results": []})

    client = KBClient(
        deadline=0.05, max_inflight=1, transport=httpx.MockTransport(handle)
    )
    try:
        started = time.monotonic()
        with pytest.raises(httpx.TimeoutException, match="deadline"):
            client.fetch(ENDPOINT, "vector databases", {})
        assert time.monotonic() - started < 0.75
        assert len(calls) == 1
        # A caller timeout must not release a still-running network worker.
        for _ in range(10):
            with pytest.raises(httpx.TimeoutException, match="capacity"):
                client.fetch(ENDPOINT, "another query", {})
        assert len(calls) == 1
        release.set()
        assert returned_from_transport.wait(1)
        expires = time.monotonic() + 1
        while True:
            try:
                assert client.fetch(ENDPOINT, "retry", {}) == {"results": []}
                break
            except httpx.TimeoutException:
                if time.monotonic() >= expires:
                    pytest.fail("Completed worker did not restore admission capacity")
                time.sleep(0.005)
        assert len(calls) == 2
    finally:
        release.set()
        client.close()


def test_concurrent_capacity_rejects_additional_work_without_queuing():
    release = threading.Event()
    both_started = threading.Event()
    lock = threading.Lock()
    started_count = 0

    def handle(_):
        nonlocal started_count
        with lock:
            started_count += 1
            if started_count == 2:
                both_started.set()
        release.wait()
        return httpx.Response(200, json={"results": []})

    client = KBClient(deadline=2, max_inflight=2, transport=httpx.MockTransport(handle))
    callers = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [callers.submit(client.fetch, ENDPOINT, str(i), {}) for i in range(2)]
        assert both_started.wait(1)
        for _ in range(20):
            with pytest.raises(httpx.TimeoutException, match="capacity"):
                client.fetch(ENDPOINT, "overflow", {})
        assert started_count == 2
        release.set()
        assert all(f.result(timeout=1) == {"results": []} for f in futures)
    finally:
        release.set()
        callers.shutdown(wait=True)
        client.close()


def test_http_errors_and_invalid_json_propagate_and_release_capacity():
    responses = iter(
        [
            httpx.Response(503, text="Unavailable"),
            httpx.Response(200, text="not-json"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"results": []}),
        ]
    )
    client = KBClient(
        max_inflight=1, transport=httpx.MockTransport(lambda _: next(responses))
    )
    try:
        for exception in (httpx.HTTPStatusError, ValueError, ValueError):
            with pytest.raises(exception):
                client.fetch(ENDPOINT, "search", {})
        assert client.fetch(ENDPOINT, "search", {}) == {"results": []}
    finally:
        client.close()


def test_network_failure_propagates_without_losing_admission_slot():
    attempts = 0

    def handle(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("controlled network failure")
        return httpx.Response(200, json={"results": []})

    client = KBClient(max_inflight=1, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(httpx.ConnectError):
            client.fetch(ENDPOINT, "query", {})
        assert client.fetch(ENDPOINT, "query", {}) == {"results": []}
    finally:
        client.close()


@pytest.mark.parametrize("claimed_length", [None, "1", "invalid", "-1"])
def test_streamed_size_limit_is_enforced_without_trusting_content_length(
    claimed_length,
):
    class Body(httpx.SyncByteStream):
        consumed = 0
        closed = False

        def __iter__(self):
            for _ in range(10):
                self.consumed += 1
                yield b"x" * 65_536

        def close(self):
            self.closed = True

    body = Body()
    headers = {} if claimed_length is None else {"content-length": claimed_length}
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers=headers, stream=body)
    )
    client = KBClient(max_response_bytes=70_000, transport=transport)
    try:
        with pytest.raises(ValueError, match="exceeds limit"):
            client.fetch(ENDPOINT, "query", {})
        assert body.consumed == 2
        assert body.closed
    finally:
        client.close()


def test_declared_oversized_body_is_rejected_before_reading():
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("Oversized declared body should not be read")
            yield b""

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, headers={"content-length": "2000001"}, stream=UnreadBody()
        )
    )
    client = KBClient(transport=transport)
    try:
        with pytest.raises(ValueError, match="exceeds limit"):
            client.fetch(ENDPOINT, "query", {})
    finally:
        client.close()


def test_success_preserves_query_headers_limit_and_disallows_redirects():
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            assert dict(request.url.params) == {"q": "message brokers", "k": "50"}
            assert request.headers["User-Agent"] == "test-agent"
            assert request.extensions["timeout"] == {
                "connect": 2.0,
                "read": 6.0,
                "write": 2.0,
                "pool": 2.0,
            }
            return httpx.Response(200, json={"results": [{"title": "RabbitMQ"}]})
        return httpx.Response(302, headers={"location": "https://elsewhere.example/"})

    client = KBClient(transport=httpx.MockTransport(handle))
    try:
        result = client.fetch(ENDPOINT, "message brokers", {"User-Agent": "test-agent"})
        assert result["results"][0]["title"] == "RabbitMQ"
        with pytest.raises(httpx.HTTPStatusError):
            client.fetch(ENDPOINT, "redirect", {})
        assert len(requests) == 2
    finally:
        client.close()


def test_slow_trickle_releases_worker_without_waiting_for_a_large_chunk():
    closed = threading.Event()

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(1000):
                time.sleep(0.005)
                yield b" "

        def close(self):
            closed.set()

    client = KBClient(
        deadline=0.02,
        max_inflight=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Trickle())),
    )
    try:
        with pytest.raises(httpx.TimeoutException):
            client.fetch(ENDPOINT, "query", {})
        assert closed.wait(0.5), (
            "Timed-out trickle must not hold its worker until 64 KB"
        )
    finally:
        client.close()
