"""Exercise HTTP admission, lifecycle and deployment boundaries without live KB calls."""

import asyncio
import logging
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

from poc.runtime import RuntimeConfig
from poc.server import create_app
from poc.serve import trusted_proxies


class StubService:
    catalog = SimpleNamespace(packages=[{"id": "linux/example.md"}])
    endpoint = "https://kb.example/search"

    def search(self, *args):
        return {"status": "ok", "mode": "hybrid", "results": [], "total": 0}


def app_with(**kwargs):
    return create_app(
        service=StubService(), config=RuntimeConfig(serve_static=False, **kwargs)
    )


def raw_request(
    app, chunks, *, extra_headers=(), receive_delay=0, root_path="", path="/api/search"
):
    async def run():
        messages = []
        pending = iter(chunks)

        async def receive():
            if receive_delay:
                await asyncio.sleep(receive_delay)
            try:
                return next(pending)
            except StopIteration:
                return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": root_path,
                "server": ("127.0.0.1", 8765),
                "client": ("192.0.2.1", 4321),
                "headers": [
                    (b"host", b"127.0.0.1:8765"),
                    (b"content-type", b"application/json"),
                    *extra_headers,
                ],
            },
            receive,
            send,
        )
        start = next(m for m in messages if m["type"] == "http.response.start")
        return start["status"], dict(start["headers"]), messages

    return asyncio.run(run())


@pytest.mark.parametrize(
    "headers", [(), ((b"content-length", b"1"),), ((b"transfer-encoding", b"chunked"),)]
)
def test_stream_limit_is_real_not_only_a_content_length_check(headers):
    app = app_with(max_body_bytes=1024)
    chunks = [
        {"type": "http.request", "body": b"x" * 700, "more_body": True},
        {"type": "http.request", "body": b"x" * 400, "more_body": False},
    ]
    status, response_headers, _ = raw_request(app, chunks, extra_headers=headers)
    assert status == 413
    assert response_headers[b"cache-control"] == b"no-store"


@pytest.mark.parametrize("lengths", [[b"-1"], [b"abc"], [b"1", b"1"], [b"1", b"2"]])
def test_invalid_or_ambiguous_content_length_is_rejected(lengths):
    status, _, _ = raw_request(
        app_with(), [], extra_headers=[(b"content-length", value) for value in lengths]
    )
    assert status == 400


def test_body_timeout_releases_request_slot():
    app = app_with(body_timeout=0.01, max_inflight=1)
    assert raw_request(app, [], receive_delay=0.03)[0] == 408
    assert (
        raw_request(
            app,
            [
                {
                    "type": "http.request",
                    "body": b'{"query":"Prometheus"}',
                    "more_body": False,
                }
            ],
        )[0]
        == 200
    )


@pytest.mark.parametrize(
    "body",
    [
        b"[" * 1100 + b"]" * 1100,
        b'{"query":NaN}',
        b'{"query":Infinity}',
        b'{"query":1e999}',
        b'{"query":"\\ud800"}',
        b"\xff",
        b"{",
    ],
    ids=["deep", "nan", "infinity", "overflow", "surrogate", "encoding", "syntax"],
)
def test_deep_invalid_and_nonstandard_json_return_clean_client_error(body):
    assert (
        raw_request(
            app_with(), [{"type": "http.request", "body": body, "more_body": False}]
        )[0]
        == 400
    )


def test_proxy_path_prefix_keeps_api_limits_and_routes_working():
    body = b'{"query":"Prometheus"}'
    status, headers, _ = raw_request(
        app_with(),
        [{"type": "http.request", "body": body, "more_body": False}],
        root_path="/ecosystem-dashboard",
        path="/ecosystem-dashboard/api/search",
    )
    assert status == 200
    assert headers[b"cache-control"] == b"no-store"


def test_public_https_origin_and_host_are_explicit_not_forwarded_header_values():
    app = app_with(public_origin="https://dashboard.example")
    with TestClient(app, base_url="http://dashboard.example") as client:
        assert (
            client.post(
                "/api/search",
                json={"query": "test"},
                headers={"Origin": "https://dashboard.example"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/search",
                json={"query": "test"},
                headers={
                    "Origin": "https://evil.example",
                    "X-Forwarded-Host": "evil.example",
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/search",
                json={"query": "test"},
                headers={
                    "Host": "evil.example",
                    "X-Forwarded-Host": "dashboard.example",
                },
            ).status_code
            == 400
        )
        assert client.get("/api/docs").status_code == 404


def test_untrusted_forwarded_ips_do_not_bypass_rate_limit():
    app = app_with(requests_per_minute=2)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for i, expected in enumerate([200, 200, 429]):
            response = client.post(
                "/api/search",
                json={"query": "test"},
                headers={"X-Forwarded-For": f"198.51.100.{i}"},
            )
            assert response.status_code == expected
        assert response.headers["retry-after"] == "60"
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 200


def test_rate_state_is_bounded_without_evicting_active_client_limits():
    async def run():
        app = app_with(max_rate_clients=1)
        for ip, expected in [
            ("192.0.2.1", 200),
            ("192.0.2.2", 429),
            ("192.0.2.1", 200),
        ]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=(ip, 1)),
                base_url="http://127.0.0.1",
            ) as client:
                assert (
                    await client.post("/api/search", json={"query": "test"})
                ).status_code == expected

    asyncio.run(run())


def test_exhausted_request_admission_does_not_queue_more_work():
    entered = threading.Event()
    release = threading.Event()

    class BlockingService(StubService):
        def search(self, *args):
            entered.set()
            release.wait(3)
            return super().search(*args)

    async def run():
        app = create_app(
            service=BlockingService(),
            config=RuntimeConfig(serve_static=False, max_inflight=1),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            first = asyncio.create_task(
                client.post("/api/search", json={"query": "first"})
            )
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                excess = await client.post("/api/search", json={"query": "second"})
                assert excess.status_code == 503
                assert excess.headers["retry-after"] == "1"
            finally:
                release.set()
            assert (await first).status_code == 200
            assert (
                await client.post("/api/search", json={"query": "third"})
            ).status_code == 200

    asyncio.run(run())


def test_readiness_tracks_lifespan_and_logs_never_include_user_query(caplog):
    app = app_with()
    caplog.set_level(logging.INFO, logger="arm_search")
    assert not app.state.ready
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/ready").json()["status"] == "ready"
        assert (
            client.post("/api/search", json={"query": "PRIVATE_QUERY_TEXT"}).status_code
            == 200
        )
        assert "PRIVATE_QUERY_TEXT" not in caplog.text
        assert app.state.metrics["search_requests"] == 1
        assert app.state.metrics["search_status_200"] == 1
        assert "search_request status=200" in caplog.text
    assert not app.state.ready


def test_internal_exception_is_sanitized_in_response_and_logs(caplog):
    class BrokenService(StubService):
        def search(self, *args):
            raise RuntimeError("SECRET_TOKEN AND PRIVATE_QUERY_TEXT")

    app = create_app(service=BrokenService(), config=RuntimeConfig(serve_static=False))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/search", json={"query": "PRIVATE_QUERY_TEXT"})
        assert response.status_code == 503
        assert "SECRET_TOKEN" not in response.text + caplog.text
        assert "PRIVATE_QUERY_TEXT" not in response.text + caplog.text
        assert app.state.metrics["search_internal_errors"] == 1


def test_invalid_provider_output_is_sanitized_before_framework_serialization(caplog):
    class BrokenOutputService(StubService):
        def search(self, *args):
            return {
                "mode": "hybrid",
                "evidence_url": "https://learn.arm.com/PRIVATE_QUERY_TEXT/\ud800",
            }

    app = create_app(
        service=BrokenOutputService(), config=RuntimeConfig(serve_static=False)
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/search", json={"query": "test"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Search is temporarily unavailable."}
        assert "PRIVATE_QUERY_TEXT" not in response.text + caplog.text
        assert app.state.metrics["search_internal_errors"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_origin", "http://dashboard.example"),
        ("public_origin", "https://dashboard.example/path"),
        ("public_origin", "https://user:secret@dashboard.example"),
        ("public_origin", "https://*.example"),
        ("kb_url", "http://remote.example/search"),
        ("kb_url", "https://kb.example/search?token=secret"),
        ("kb_token", "secret\r\nInjected: value"),
        ("max_inflight", 0),
        ("max_body_bytes", 99999999),
        ("kb_deadline", float("inf")),
        ("body_timeout", float("nan")),
    ],
)
def test_invalid_runtime_configuration_fails_closed(field, value):
    with pytest.raises(ValueError):
        RuntimeConfig(**{field: value})


def test_api_rejects_unknown_fields_and_encoded_bodies():
    with TestClient(app_with(), base_url="http://127.0.0.1") as client:
        assert (
            client.post(
                "/api/search",
                json={"query": "test", "url": "https://elsewhere.example"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/search",
                json={"query": "test"},
                headers={"Content-Encoding": "gzip"},
            ).status_code
            == 415
        )
        assert client.post("/api/search", content="query=test").status_code == 415


def test_kb_client_is_owned_and_closed_by_app_lifecycle():
    app = create_app(config=RuntimeConfig(serve_static=False))
    owned = app.state.kb_client
    with TestClient(app, base_url="http://127.0.0.1"):
        assert not owned._closed
    assert owned._closed
    with pytest.raises(httpx.ConnectError, match="closed"):
        owned.fetch("https://kb.example/search", "test", {})


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "proxy.example"])
def test_proxy_trust_requires_explicit_address_boundaries(value):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        trusted_proxies(value)
    assert trusted_proxies("10.1.2.3/32, 127.0.0.1") == "10.1.2.3/32,127.0.0.1"
