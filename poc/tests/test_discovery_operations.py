"""Operational behavior without live source or model access."""

import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
import yaml

from poc.discovery.pipeline import (
    catalog_identities,
    run_pipeline,
    state_lock,
    validate_config,
)
from poc.discovery.serve import Runner, create_server
from poc.discovery.ai_review import configured_reviewer, OpenAIEvidenceReviewer


@pytest.mark.parametrize(
    "config",
    [
        [],
        {"limtis": {}},
        {"limits": {"max_candiates": 1}},
        {"limits": {"max_candidates": 0.5}},
        {"limits": {"max_candidates": True}},
        {"limits": {"max_seconds": float("nan")}},
        {"limits": {"oci_fallback": "false"}},
        {"refresh_hours": {"unknown": float("inf")}},
        {"force_refresh": "false"},
        {"discovery": {"github_queries": "topic:database"}},
        {"discovery": {"min_stars": -1}},
        {"seeds": "repo"},
        {"ai_review": {"enabled": "false"}},
        {"ai_review": {"max_calls": 0.5}},
    ],
)
def test_invalid_config_rejected_before_io(config):
    with pytest.raises(ValueError):
        validate_config(config)


def test_catalog_reads_linux_source_files(tmp_path):
    directory = tmp_path / "opensource_packages"
    directory.mkdir()
    (directory / "example.md").write_text(
        "---\nname: Example\noptional_info:\n  docs: https://github.com/org/repo/releases\n---\nBody"
    )
    assert catalog_identities(tmp_path) == {"github:org/repo"}


def test_state_lock_blocks_second_run_and_releases(tmp_path):
    path = tmp_path / "state.sqlite3"
    with state_lock(path):
        with pytest.raises(RuntimeError, match="already active"):
            with state_lock(path):
                pytest.fail("Second run should not acquire the lock")
    with state_lock(path):
        pass


def test_ai_uses_dedicated_credentials_only(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-ide-token")
    monkeypatch.setenv("OPENAI_MODEL", "unrelated-model")
    monkeypatch.delenv("ARM_DISCOVERY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ARM_DISCOVERY_MODEL", raising=False)
    reviewer, error = configured_reviewer({"ai_review": {"enabled": True}})
    assert reviewer is None and "dedicated" in error
    monkeypatch.setenv("ARM_DISCOVERY_OPENAI_API_KEY", "configured-test-token")
    monkeypatch.setenv("ARM_DISCOVERY_MODEL", "configured-test-model")
    reviewer, error = configured_reviewer({"ai_review": {"enabled": True}})
    assert error is None and reviewer.model == "configured-test-model"
    assert reviewer.api_key == "configured-test-token"


def test_ai_provider_request_is_bounded_public_evidence(monkeypatch):
    seen = {}

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            yield json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "note": "Advisory",
                                            "citations": [
                                                {
                                                    "url": "https://github.com/a/b",
                                                    "quote": "linux/arm64",
                                                }
                                            ],
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ).encode()

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("poc.discovery.ai_review.requests.post", post)
    reviewer = OpenAIEvidenceReviewer("test-model", "secret", max_calls=1)
    result = reviewer(
        {
            "scope": "selected tag",
            "deterministic_status": "supported",
            "evidence": [
                {
                    "url": "https://github.com/a/b",
                    "kind": "metadata",
                    "excerpt": "linux/arm64",
                    "private_field": "DO NOT SEND",
                }
            ],
        }
    )
    assert result["note"] == "Advisory"
    assert seen["json"]["store"] is False and seen["allow_redirects"] is False
    assert "DO NOT SEND" not in json.dumps(seen["json"])
    with pytest.raises(ValueError, match="budget"):
        reviewer({})


@pytest.fixture
def local_server(tmp_path):
    started, finish = threading.Event(), threading.Event()

    def pipeline(*args):
        started.set()
        assert finish.wait(5)

    runner = Runner("config", tmp_path, None, pipeline)
    server = create_server("config", tmp_path, None, port=0, runner=runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, runner, started
    finish.set()
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_local_http_run_download_and_origin_boundaries(local_server, tmp_path):
    server, runner, started = local_server
    base = f"http://127.0.0.1:{server.server_port}"
    with urlopen(base + "/") as r:
        assert b"Find the next enablement opportunity" in r.read()
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    with urlopen(base + "/api/state") as r:
        state = json.load(r)
        assert state["summary"] is None
    for headers in (
        {},
        {"Origin": "https://unrelated.example", "X-CSRF-Token": runner.token},
        {"Origin": base, "X-CSRF-Token": "wrong"},
    ):
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/run", method="POST", headers=headers))
        assert error.value.code == 403
    headers = {"Origin": base, "X-CSRF-Token": runner.token}
    with urlopen(Request(base + "/api/run", method="POST", headers=headers)) as r:
        assert r.status == 202
    assert started.wait(1)
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/api/run", method="POST", headers=headers))
    assert error.value.code == 409
    outside = tmp_path.parent / "outside-secret.json"
    outside.write_text("not served")
    (tmp_path / "latest.json").write_text(
        json.dumps({"report_paths": {"json": str(outside)}})
    )
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/download/json")
    assert error.value.code == 404
    report = tmp_path / "report.json"
    report.write_text('{"run_id":"example"}')
    (tmp_path / "latest.json").write_text(
        json.dumps({"report_paths": {"json": str(report)}})
    )
    with urlopen(base + "/download/json") as r:
        assert json.load(r)["run_id"] == "example"
        assert "attachment" in r.headers["Content-Disposition"]
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/", headers={"Host": "unrelated.example"}))
    assert error.value.code == 403


def test_empty_run_still_produces_reviewable_report(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"seeds": []}))
    summary = run_pipeline(config, tmp_path / "out")
    assert summary["counts"]["investigated"] == summary["counts"]["requests"] == 0
    assert all(Path(path).is_file() for path in summary["report_paths"].values())
