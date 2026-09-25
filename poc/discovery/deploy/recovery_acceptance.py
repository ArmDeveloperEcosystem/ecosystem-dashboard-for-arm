"""Offline recovery drill on synthetic state; never operates on an existing state.

Run from the checkout with ``python -m poc.discovery.deploy.recovery_acceptance``.
This acceptance harness is deliberately excluded from the production image.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ..pipeline import run_pipeline, state_lock

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
DATABASE = "discovery.sqlite3"
LEGACY = {"source": "dockerhub", "name": "acceptance/legacy", "tag": "old"}
CURRENT = {"source": "dockerhub", "name": "acceptance/current", "tag": "latest"}
PENDING = {"source": "dockerhub", "name": "acceptance/pending", "tag": "latest"}
CRASH_EXIT = 73


class SyntheticMetadata:
    """Closed fixture transport: unexpected requests fail, never reach a network."""

    def __init__(self, crash=False):
        self.requests_used = 0
        self.calls = []
        self.crash = crash

    def get(self, url, **kwargs):
        self.requests_used += 1
        self.calls.append(url)
        if self.requests_used > 3:
            raise AssertionError("Recovery fixture exceeded its request bound")
        if url == "https://api.github.com/search/repositories" and self.crash:
            # The scheduler has committed a completed observation before its
            # discovery checkpoint. Simulate an actual unclean process exit.
            os._exit(CRASH_EXIT)
        for candidate in (LEGACY, CURRENT, PENDING):
            namespace, name = candidate["name"].split("/")
            base = (
                f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{name}"
            )
            if url.rstrip("/") == base:
                return {"is_private": False, "pull_count": 1}, {}
            if url.rstrip("/") == base + "/tags/" + candidate["tag"]:
                arch = "amd64" if candidate == LEGACY else "arm64"
                return {"images": [{"os": "linux", "architecture": arch}]}, {}
        raise AssertionError("Unexpected fixture request: " + url)


def rows(path):
    """Read every persisted business table without opening a writable connection."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise AssertionError("SQLite integrity check failed")
        tables = [
            item[0]
            for item in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for name in tables
        }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_fixture(source, destination):
    """Snapshot only this drill's small state using SQLite's consistent backup API.

    This is an acceptance helper, not a retention, encryption or host backup tool.
    An existing destination, symlink, or active pipeline fails closed.
    """
    if destination.exists():
        raise ValueError("Snapshot destination must not exist")
    database = source / DATABASE
    if (
        database.is_symlink()
        or not database.is_file()
        or database.stat().st_size > 10_000_000
    ):
        raise ValueError("Expected a regular fixture database")
    with state_lock(database):
        files = [source / "latest.json", *source.glob("*/opportunities.*")]
        if len(files) > 50 or any(
            path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000
            for path in files
        ):
            raise ValueError("Unexpected or oversized recovery fixture")
        destination.mkdir(mode=0o700)
        try:
            with (
                closing(
                    sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
                ) as src,
                closing(sqlite3.connect(destination / DATABASE)) as dst,
            ):
                src.backup(dst)
                # The standalone backup has all committed WAL data. Close
                # it in rollback-journal mode so no sidecar belongs to the
                # snapshot; pipeline startup restores its normal WAL mode.
                dst.execute("PRAGMA journal_mode=DELETE")
            if rows(database) != rows(destination / DATABASE):
                raise AssertionError("Snapshot lost SQLite rows")
            for path in files:
                target = destination / path.relative_to(source)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                target.chmod(0o600)
            (destination / DATABASE).chmod(0o600)
            manifest = {
                str(path.relative_to(destination)): digest(path)
                for path in destination.rglob("*")
                if path.is_file()
            }
            (destination / "snapshot-manifest.json").write_text(
                json.dumps(manifest, indent=2)
            )
            (destination / "snapshot-manifest.json").chmod(0o600)
            return manifest
        except BaseException:
            shutil.rmtree(destination)
            raise


def restore_fixture(snapshot, destination):
    """Restore a checksum-verified drill snapshot into a new private directory."""
    if destination.exists():
        raise ValueError("Restore destination must not exist")
    manifest = json.loads((snapshot / "snapshot-manifest.json").read_text())
    for relative, expected in manifest.items():
        path = snapshot / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or path.is_symlink()
            or not path.is_file()
            or digest(path) != expected
        ):
            raise ValueError("Snapshot file failed verification")
    if DATABASE not in manifest:
        raise ValueError("Snapshot database is missing")
    rows(snapshot / DATABASE)
    destination.mkdir(mode=0o700)
    try:
        for relative in manifest:
            target = destination / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(snapshot / relative, target)
            target.chmod(0o600)
    except BaseException:
        shutil.rmtree(destination)
        raise


def configure(root, name, **overrides):
    path = root / (name + ".yaml")
    config = {
        "seeds": [],
        "discovery": {"github_queries": []},
        "limits": {"max_candidates": 1, "max_requests": 3, "oci_fallback": False},
        "ai_review": {"enabled": False},
        **overrides,
    }
    # JSON is valid YAML, and keeps this harness independent of configuration
    # interpolation or shell quoting.
    path.write_text(json.dumps(config))
    return path


def crash_worker(root):
    config = configure(
        root,
        "crash",
        retired_candidates=[{**LEGACY, "reason": "Synthetic obsolete scope."}],
        discovery={"github_queries": ["topic:acceptance"]},
    )
    run_pipeline(
        config,
        root / "original",
        now=NOW + timedelta(hours=1),
        http=SyntheticMetadata(crash=True),
    )
    raise AssertionError("The interruption fixture did not exit")


def acceptance(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = configure(root, "initial", seeds=[LEGACY, CURRENT, PENDING])
    first = run_pipeline(config, root / "original", now=NOW, http=SyntheticMetadata())
    if (
        first["counts"]["saved_observations"] != 1
        or first["counts"]["pending_investigation"] != 2
    ):
        raise AssertionError("Initial fixture did not create history and backlog")
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "poc.discovery.deploy.recovery_acceptance",
            "--crash-worker",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if child.returncode != CRASH_EXIT:
        raise AssertionError(
            f"Expected unclean exit {CRASH_EXIT}; got {child.returncode}: {child.stderr}"
        )
    original = root / "original"
    wal_bytes = (original / (DATABASE + "-wal")).stat().st_size
    if wal_bytes == 0:
        raise AssertionError("Crash did not leave committed WAL data to recover")
    before = rows(original / DATABASE)
    if (
        len(before["observations"]) != 2
        or sum(row[2] is None for row in before["runs"]) != 1
    ):
        raise AssertionError(
            "Crash did not preserve its completed observation and unfinished run"
        )
    manifest = snapshot_fixture(original, root / "snapshot")
    restore_fixture(root / "snapshot", root / "restored")
    if rows(root / "restored" / DATABASE) != before:
        raise AssertionError("Restore changed saved state")
    config = configure(root, "continue")
    transport = SyntheticMetadata()
    resumed = run_pipeline(
        config, root / "restored", now=NOW + timedelta(hours=2), http=transport
    )
    after = rows(root / "restored" / DATABASE)
    if after["observations"][:2] != before["observations"]:
        raise AssertionError("Recovery changed immutable observations")
    if after["candidate_retirements"] != before["candidate_retirements"]:
        raise AssertionError("Recovery lost retirement memory")
    if (
        resumed["counts"]["investigated"] != 1
        or resumed["findings"][0]["name"] != PENDING["name"]
    ):
        raise AssertionError("Recovery failed to continue the pending queue")
    if resumed["counts"]["saved_observations"] != 3 or resumed["current_errors"]:
        raise AssertionError("Recovery did not complete a healthy bounded run")
    if not any(
        item["status"] == "interrupted" for item in resumed["previous_run_failures"]
    ):
        raise AssertionError("Unclean exit was not retained in the run audit")
    if rows(original / DATABASE) != before:
        raise AssertionError("Recovery modified the original state")
    for relative, expected in manifest.items():
        if relative != DATABASE and digest(original / relative) != expected:
            raise AssertionError("Original reports changed")
        if (
            relative not in (DATABASE, "latest.json")
            and digest(root / "restored" / relative) != expected
        ):
            raise AssertionError("Historical report bytes changed")
    latest = json.loads((root / "restored/latest.json").read_text())
    if latest["run_id"] != resumed["run_id"] or any(
        not Path(path).is_relative_to(root / "restored") or not Path(path).is_file()
        for path in latest["report_paths"].values()
    ):
        raise AssertionError("Recovery did not publish new local report references")
    result = {
        "acceptance": "passed",
        "scenario": "synthetic_offline_recovery",
        "backup_method": "sqlite3.Connection.backup",
        "unclean_process_exit": CRASH_EXIT,
        "wal_bytes_before_backup": wal_bytes,
        "observations_before": 2,
        "observations_after": 3,
        "retirement_preserved": True,
        "historical_reports_unchanged": True,
        "original_state_unchanged": True,
        "pending_work_resumed": True,
        "interrupted_run_audited": True,
        "new_report_paths_local": True,
        "live_source_requests": 0,
        "model_calls": 0,
        "actual_host_scheduler_backup_and_alert_acceptance": "still_required",
    }
    (root / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="New directory for synthetic private artifacts (required)",
    )
    parser.add_argument("--crash-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.crash_worker and args.work_dir is None:
        parser.error("--work-dir is required")
    os.umask(0o077)
    with ExitStack() as stack:
        for target in ("socket.create_connection", "requests.sessions.Session.request"):
            stack.enter_context(
                patch(
                    target,
                    side_effect=AssertionError("Network forbidden in recovery drill"),
                )
            )
        if args.crash_worker:
            crash_worker(args.crash_worker.resolve())
        else:
            print(json.dumps(acceptance(args.work_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
