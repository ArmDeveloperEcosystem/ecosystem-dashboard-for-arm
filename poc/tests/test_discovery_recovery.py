"""Offline operational drill and failure boundaries for saved-state recovery."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from poc.discovery.deploy.recovery_acceptance import (
    DATABASE,
    restore_fixture,
    rows,
    snapshot_fixture,
)
from poc.discovery.pipeline import state_lock

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def drill(tmp_path_factory):
    root = tmp_path_factory.mktemp("recovery") / "new-state"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "poc.discovery.deploy.recovery_acceptance",
            "--work-dir",
            str(root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    return root, json.loads(run.stdout)


def test_unclean_exit_snapshot_restore_and_pending_work_continuation(drill):
    root, result = drill
    assert result["acceptance"] == "passed"
    assert result["unclean_process_exit"] == 73
    assert result["wal_bytes_before_backup"] > 0
    assert result["observations_before"] == 2 and result["observations_after"] == 3
    assert result["pending_work_resumed"] and result["retirement_preserved"]
    assert result["interrupted_run_audited"] and result["new_report_paths_local"]
    assert result["live_source_requests"] == result["model_calls"] == 0
    before, after = (
        rows(root / "original" / DATABASE),
        rows(root / "restored" / DATABASE),
    )
    assert after["observations"][:2] == before["observations"]
    assert after["candidate_retirements"] == before["candidate_retirements"]
    assert json.loads(after["runs"][1][3])["status"] == "interrupted"
    assert before["runs"][1][2] is None
    assert not list((root / "snapshot").glob("*-wal"))
    assert not list((root / "snapshot").glob("*-shm"))
    assert all(not path.stat().st_mode & 0o077 for path in root.rglob("*"))


def test_snapshot_refuses_active_state_without_creating_destination(drill, tmp_path):
    root, _ = drill
    target = tmp_path / "backup"
    with (
        state_lock(root / "original" / DATABASE),
        pytest.raises(RuntimeError, match="already active"),
    ):
        snapshot_fixture(root / "original", target)
    assert not target.exists()


def test_restore_refuses_existing_directory_and_corruption(drill, tmp_path):
    root, _ = drill
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_text("keep")
    with pytest.raises(ValueError, match="must not exist"):
        restore_fixture(root / "snapshot", target)
    assert (target / "keep").read_text() == "keep"
    broken = tmp_path / "corrupt"
    shutil.copytree(root / "snapshot", broken)
    (broken / "latest.json").write_text("changed")
    with pytest.raises(ValueError, match="verification"):
        restore_fixture(broken, tmp_path / "must-not-be-created")
    assert not (tmp_path / "must-not-be-created").exists()


def test_restore_rejects_manifest_escape_before_writing(tmp_path):
    snapshot = tmp_path / "bad-snapshot"
    snapshot.mkdir()
    (snapshot / "snapshot-manifest.json").write_text(
        json.dumps({"../secret": "ignored"})
    )
    with pytest.raises(ValueError, match="verification"):
        restore_fixture(snapshot, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_drill_refuses_existing_output_without_changing_files(tmp_path):
    (tmp_path / "keep").write_text("keep")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "poc.discovery.deploy.recovery_acceptance",
            "--work-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert run.returncode != 0
    assert list(tmp_path.iterdir()) == [tmp_path / "keep"]
    assert (tmp_path / "keep").read_text() == "keep"
