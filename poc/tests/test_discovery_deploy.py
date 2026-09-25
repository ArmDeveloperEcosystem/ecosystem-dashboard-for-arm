"""Production entrypoint permissions and scheduler cleanup behavior."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "poc/discovery/deploy"
CID = "a" * 64


def test_batch_entrypoint_creates_private_reports_and_state(tmp_path):
    config = tmp_path / "empty.yaml"
    config.write_text("seeds: []\ndiscovery: {github_queries: []}\n")
    output = tmp_path / "state"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "poc.discovery.deploy.run",
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--catalog",
            str(ROOT / "content/linux"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    summary = json.loads(result.stdout)
    assert summary["counts"]["investigated"] == 0
    assert summary["counts"]["requests"] == 0
    assert output.stat().st_mode & 0o077 == 0
    for path in output.rglob("*"):
        assert path.stat().st_mode & 0o077 == 0, path
    for path in summary["report_paths"].values():
        assert Path(path).is_file()
    assert Path(summary["state_path"]).is_file()


@pytest.mark.parametrize(
    ("scenario", "expected_code", "expected_calls"),
    [
        ("removed", 0, 1),
        ("running", 0, 2),
        ("race", 0, 3),
        ("daemon_error", 9, 1),
        ("remove_failed", 1, 3),
    ],
)
def test_service_cleanup_is_idempotent_and_reports_real_failures(
    tmp_path, scenario, expected_code, expected_calls
):
    # A process-level fake exercises the actual POSIX cleanup script; it never
    # connects to a daemon or stops a user's container.
    fake_docker = tmp_path / "docker"
    log = tmp_path / "calls.json"
    fake_docker.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        "p=pathlib.Path(os.environ['CALL_LOG'])\n"
        "calls=json.loads(p.read_text()) if p.exists() else []\n"
        "calls.append(sys.argv[1:]);p.write_text(json.dumps(calls))\n"
        "scenario=os.environ['SCENARIO']\n"
        "if scenario=='daemon_error': sys.exit(9)\n"
        "if sys.argv[2]=='ls':\n"
        " if scenario in ('running','remove_failed') or (scenario=='race' and len(calls)==1): print('a'*64)\n"
        "elif scenario in ('race','remove_failed'): sys.exit(1)\n"
    )
    fake_docker.chmod(0o700)
    cidfile = tmp_path / "container.id"
    cidfile.write_text(CID)
    result = subprocess.run(
        ["/bin/sh", str(DEPLOY / "stop-container.sh"), str(cidfile)],
        env={
            **os.environ,
            "DOCKER_BIN": str(fake_docker),
            "CALL_LOG": str(log),
            "SCENARIO": scenario,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected_code
    calls = json.loads(log.read_text())
    assert len(calls) == expected_calls
    assert all(CID in " ".join(call) for call in calls)


@pytest.mark.parametrize("value", ["", "bad;id", "abc", "../container", "f" * 65])
def test_service_cleanup_never_executes_malformed_container_id(tmp_path, value):
    cidfile = tmp_path / "container.id"
    cidfile.write_text(value)
    result = subprocess.run(
        ["/bin/sh", str(DEPLOY / "stop-container.sh"), str(cidfile)],
        env={**os.environ, "DOCKER_BIN": "/missing/must-not-run"},
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (0 if not value else 1)
