"""Independent regressions for public-source credentials and model input limits."""

import json

import pytest
import requests

from poc.discovery.ai_review import OpenAIEvidenceReviewer
from poc.discovery.http import BoundedHTTP
from poc.discovery.pipeline import DEFAULT_LIMITS


@pytest.fixture
def prepared_requests(monkeypatch, tmp_path):
    """Exercise requests' real preparation/auth path without opening a socket."""
    netrc = tmp_path / "netrc"
    netrc.write_text(
        "\n".join(
            f"machine {host} login unrelated-user password unrelated-password"
            for host in ("api.github.com", "hub.docker.com", "api.openai.com")
        )
        + "\n"
    )
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("GITHUB_TOKEN", "dedicated-github-canary")
    captured = []

    def send(session, request, **kwargs):
        captured.append(request)
        body = {}
        if request.url == "https://api.openai.com/v1/responses":
            body = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "note": "Human review required.",
                                        "citations": [
                                            {
                                                "url": "https://github.com/org/project",
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
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = json.dumps(body).encode()
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.sessions.Session, "send", send)
    return captured


def public_evidence():
    return {
        "scope": "org/project release v1 published Linux binaries",
        "deterministic_status": "supported",
        "evidence": [
            {
                "url": "https://github.com/org/project",
                "kind": "release_artifact",
                "excerpt": "linux/arm64",
            }
        ],
    }


def test_public_source_requests_do_not_inherit_unrelated_netrc(prepared_requests):
    client = BoundedHTTP(DEFAULT_LIMITS)
    client.get("https://hub.docker.com/v2/namespaces/org/repositories/project")
    client.get("https://api.github.com/repos/org/project")

    assert "Authorization" not in prepared_requests[0].headers
    assert prepared_requests[1].headers["Authorization"] == (
        "Bearer dedicated-github-canary"
    )


def test_model_request_uses_only_dedicated_auth_under_netrc(prepared_requests):
    reviewer = OpenAIEvidenceReviewer("approved-test-model", "dedicated-model-canary")
    reviewer(public_evidence())

    assert prepared_requests[0].headers["Authorization"] == (
        "Bearer dedicated-model-canary"
    )


def test_large_public_scope_cannot_bypass_model_input_bound(prepared_requests):
    value = public_evidence()
    value["scope"] += "; tool-linux-arm64.tar.gz" * 10_000
    value["evidence"] = [
        {
            **value["evidence"][0],
            "excerpt": "linux/arm64 " * 10_000,
        }
        for _ in range(12)
    ]
    reviewer = OpenAIEvidenceReviewer("approved-test-model", "dedicated-model-canary")
    reviewer(value)

    request = prepared_requests[0]
    assert len(request.body) <= 64 * 1024
    payload = json.loads(request.body)
    submitted = json.loads(payload["input"][1]["content"])
    assert len(submitted["evidence"]) <= 8

    def discloses_truncation(item):
        if isinstance(item, dict):
            return any(
                ("truncat" in key.lower() and bool(child))
                or discloses_truncation(child)
                for key, child in item.items()
            )
        if isinstance(item, list):
            return any(discloses_truncation(child) for child in item)
        return isinstance(item, str) and "truncated" in item.lower()

    assert discloses_truncation(submitted)
