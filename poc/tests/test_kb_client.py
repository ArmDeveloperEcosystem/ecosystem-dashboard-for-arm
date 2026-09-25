"""Offline behavior tests for latency, bounded admission and HTTP safety."""

import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from poc.kb_client import KBClient

ENDPOINT = "https://kb.example.test/search"


def test_import_does_not_inspect_unused_default_client_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    monkeypatch.setenv("HTTPS_PROXY", "unsupported://proxy.invalid:9")
    imported = subprocess.run(
        [sys.executable, "-c", "import poc.kb_client"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


def test_real_http_connection_is_reused_without_cookies_or_stale_headers(
    monkeypatch, tmp_path
):
    # The runtime opts out of environment-controlled proxy and CA configuration.
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    monkeypatch.setenv("HTTP_PROXY", "unsupported://proxy.invalid:9")
    monkeypatch.setenv("HTTPS_PROXY", "unsupported://proxy.invalid:9")
    monkeypatch.setenv("NO_PROXY", "")
    requests = []

    class CountingServer(ThreadingHTTPServer):
        connections = 0

        def get_request(self):
            accepted = super().get_request()
            self.connections += 1
            return accepted

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            requests.append(dict(self.headers))
            body = b'{"results": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "provider-session=private; Path=/")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = CountingServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client = KBClient(max_inflight=1, trust_env=False)
    endpoint = f"http://127.0.0.1:{server.server_port}/search"
    try:
        for headers in (
            {"Authorization": "Bearer first", "X-Request-Only": "first"},
            {"Authorization": "Bearer second"},
            {},
        ):
            assert client.fetch(endpoint, "query", headers) == {"results": []}
        assert server.connections == 1
        assert [request.get("Authorization") for request in requests] == [
            "Bearer first",
            "Bearer second",
            None,
        ]
        assert [request.get("X-Request-Only") for request in requests] == [
            "first",
            None,
            None,
        ]
        assert all("Cookie" not in request for request in requests)
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)


def test_concurrent_requests_keep_authorization_headers_isolated():
    barrier = threading.Barrier(2)

    def handle(request):
        barrier.wait(timeout=1)
        token = request.url.params["q"]
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert "Cookie" not in request.headers
        return httpx.Response(
            200, json={"token": token}, headers={"Set-Cookie": f"session={token}"}
        )

    client = KBClient(max_inflight=2, transport=httpx.MockTransport(handle))
    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            futures = [
                callers.submit(
                    client.fetch, ENDPOINT, token, {"Authorization": f"Bearer {token}"}
                )
                for token in ("first", "second")
            ]
            assert [future.result(timeout=2) for future in futures] == [
                {"token": "first"},
                {"token": "second"},
            ]
    finally:
        client.close()


def test_slow_http_initialization_retains_deadline_and_admission_limit(monkeypatch):
    real_client = httpx.Client
    initialization_started = threading.Event()
    release = threading.Event()
    transport_closed = threading.Event()

    def initialize(**kwargs):
        initialization_started.set()
        assert release.wait(timeout=2)
        return real_client(**kwargs)

    class Transport(httpx.MockTransport):
        def close(self):
            transport_closed.set()

    monkeypatch.setattr(httpx, "Client", initialize)
    client = KBClient(
        deadline=0.03,
        max_inflight=1,
        transport=Transport(lambda _: httpx.Response(200, json={"results": []})),
    )
    try:
        started = time.monotonic()
        with pytest.raises(httpx.TimeoutException, match="deadline"):
            client.fetch(ENDPOINT, "first", {})
        assert time.monotonic() - started < 0.5
        assert initialization_started.is_set()
        with pytest.raises(httpx.TimeoutException, match="capacity"):
            client.fetch(ENDPOINT, "second", {})
        client.close(wait=False)
        assert not transport_closed.is_set()
        release.set()
        assert transport_closed.wait(timeout=1)
    finally:
        release.set()
        client.close()


@pytest.mark.parametrize("wait", [False, True])
def test_shutdown_closes_transport_once_after_running_request_finishes(wait):
    started = threading.Event()
    release = threading.Event()
    transport_closed = threading.Event()
    close_returned = threading.Event()

    class Transport(httpx.BaseTransport):
        close_count = 0

        def handle_request(self, _request):
            started.set()
            assert release.wait(timeout=2)
            assert not transport_closed.is_set()
            return httpx.Response(200, json={"results": []})

        def close(self):
            self.close_count += 1
            transport_closed.set()

    transport = Transport()
    client = KBClient(transport=transport)

    def close():
        client.close(wait=wait)
        close_returned.set()

    callers = ThreadPoolExecutor(max_workers=1)
    closer = threading.Thread(target=close, daemon=True)
    try:
        future = callers.submit(client.fetch, ENDPOINT, "query", {})
        assert started.wait(timeout=1)
        closer.start()
        if wait:
            assert not close_returned.wait(timeout=0.05)
        else:
            assert close_returned.wait(timeout=0.5)
        assert not transport_closed.is_set()
        with pytest.raises(httpx.ConnectError, match="closed"):
            client.fetch(ENDPOINT, "after shutdown", {})
        release.set()
        assert future.result(timeout=1) == {"results": []}
        assert close_returned.wait(timeout=1)
        assert transport_closed.wait(timeout=1)
        client.close()
        assert transport.close_count == 1
    finally:
        release.set()
        closer.join(timeout=1)
        callers.shutdown(wait=True)
        client.close()


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
    responses = iter(
        [
            httpx.Response(200, headers=headers, stream=body),
            httpx.Response(200, json={"results": []}),
        ]
    )
    client = KBClient(
        max_response_bytes=70_000,
        transport=httpx.MockTransport(lambda _: next(responses)),
    )
    try:
        with pytest.raises(ValueError, match="exceeds limit"):
            client.fetch(ENDPOINT, "query", {})
        assert body.consumed == 2
        assert body.closed
        assert client.fetch(ENDPOINT, "after oversized response", {}) == {"results": []}
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
