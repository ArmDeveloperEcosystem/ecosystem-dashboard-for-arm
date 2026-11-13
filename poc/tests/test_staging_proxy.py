"""Exercise the staging proxy against the real API with controlled search results."""

import json
import shutil
import socket
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from poc.runtime import RuntimeConfig
from poc.server import create_app

ORIGIN = "https://d1jmgdpytvgwdc.cloudfront.net"
SEARCH = "/dashboard-search/api/search"


def test_staging_build_connects_root_ui_to_its_matching_api_catalog(tmp_path):
    hugo = shutil.which("hugo")
    if not hugo:
        pytest.skip("Hugo is required; the CI job installs the pinned version")
    site = tmp_path / "site"
    subprocess.run(
        [hugo, "--minify", "--config", "config.toml,poc/deploy/config.staging.toml",
         "--destination", str(site)],
        cwd=Path(__file__).parents[2], capture_output=True, check=True, timeout=30,
    )

    class Endpoints(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            if "data-endpoint" in dict(attrs):
                self.values.append(dict(attrs)["data-endpoint"])

    parser = Endpoints()
    parser.feed((site / "linux/index.html").read_text())
    assert parser.values == ["/api/search"]
    catalog = site / "poc-catalog.json"
    count = len(json.loads(catalog.read_text())["packages"])
    assert count > 0
    app = create_app(
        catalog_path=catalog,
        config=RuntimeConfig(public_origin=ORIGIN, serve_static=False),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/ready").json()["catalog_count"] == count
        assert client.get("/api/docs").status_code == 404
        response = client.post("/api/search", json={"query": "vector databases"})
        assert response.status_code == 503  # Explicit scope validation is still required.
        assert response.json()["mode"] == "kb_unavailable"


@pytest.fixture
def proxy(tmp_path):
    nginx = shutil.which("nginx")
    if not nginx:
        pytest.skip("nginx is required; the Ubuntu CI job installs it")

    class Evidence:
        catalog = SimpleNamespace(packages=[{"id": "linux/example.md"}])
        endpoint = "https://kb.example/search"

        def search(self, query, filters):
            return {"mode": "kb_scoped", "results": self.catalog.packages, "total": 1}

    app = create_app(
        service=Evidence(),
        config=RuntimeConfig(public_origin=ORIGIN, serve_static=False),
    )
    listener = socket.socket()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    process = None
    try:
        listener.bind(("127.0.0.1", 0))
        api_port = listener.getsockname()[1]
        thread.start()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            proxy_port = reservation.getsockname()[1]
        fragment = (Path(__file__).parents[1] / "deploy/nginx.staging.conf.example").read_text()
        fragment = fragment.replace("listen 8081", f"listen 127.0.0.1:{proxy_port}")
        fragment = fragment.replace("127.0.0.1:8080", f"127.0.0.1:{api_port}")
        config = tmp_path / "nginx.conf"
        config.write_text(
            f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log warn;\n"
            f"events {{}}\nhttp {{\nclient_body_temp_path {tmp_path}/body;\n"
            f"proxy_temp_path {tmp_path}/proxy;\n{fragment}\n}}\n"
        )
        command = [nginx, "-p", str(tmp_path), "-c", str(config)]
        subprocess.run([*command, "-t"], check=True, capture_output=True, timeout=5)
        process = subprocess.Popen(
            [*command, "-g", "daemon off;"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with httpx.Client(
            base_url=f"http://127.0.0.1:{proxy_port}", timeout=3, trust_env=False,
        ) as client:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("nginx exited: " + (tmp_path / "error.log").read_text())
                try:
                    if client.get("/dashboard-search/api/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("staging proxy/API did not become ready")
            yield client
    finally:
        try:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            server.should_exit = True
            if thread.ident is not None:
                thread.join(timeout=5)
            listener.close()
        assert not thread.is_alive(), "API did not stop cleanly"


def test_origin_host_and_private_health_are_rewritten_correctly(proxy):
    response = proxy.post(
        SEARCH, json={"query": "example"},
        headers={"Host": "backend.example", "Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["results"] == [{"id": "linux/example.md"}]
    assert "no-store" in response.headers["cache-control"]
    response = proxy.get("/dashboard-search/api/ready", headers={"Host": "10.0.0.8"})
    assert response.status_code == 200
    assert response.json()["readiness_scope"] == "process_only"


@pytest.mark.parametrize("path", ["/api/search", "/api/docs", "/api/ready", "/"])
def test_other_paths_are_not_forwarded(proxy, path):
    assert proxy.get(path).status_code == 404


def test_wrong_origin_method_and_body_are_rejected(proxy):
    assert proxy.get(SEARCH).status_code == 403
    assert proxy.post(
        SEARCH, json={"query": "example"}, headers={"Origin": "https://other.example"},
    ).status_code == 403
    assert proxy.post(
        SEARCH, content=b"x" * 9000, headers={"Origin": ORIGIN},
    ).status_code == 413
    assert proxy.post(
        SEARCH, content="{}", headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
    ).status_code == 415
