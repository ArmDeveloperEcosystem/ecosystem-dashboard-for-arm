#!/usr/bin/env python3
"""Route an authenticated, complete Git diff without GitHub path-filter limits."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

# Keep the trusted sibling import available for isolated Python invocations.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestration_contract import decode_json

SHA_RE = re.compile(r"[0-9a-f]{40}")
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
SMOKE_WORKFLOW_RE = re.compile(r"\.github/workflows/test-[A-Za-z0-9_.-]+\.yml")
SMOKE_WORKFLOW_TEST_RE = re.compile(
    r"\.github/scripts/tests/test_[A-Za-z0-9_]+_workflows?\.py"
)

# Runtime imports and local actions used by the package/batch/summary workflows.
# Keep website data and the package identity catalog out of this execution set.
SMOKE_SCRIPTS = frozenset({
    ".github/scripts/batch_artifact_attestation.py",
    ".github/scripts/download-with-fallback.sh",
    ".github/scripts/exact_run_aggregation.py",
    ".github/scripts/generated_test_results_artifact.py",
    ".github/scripts/orchestration_contract.py",
    ".github/scripts/package_observation.py",
    ".github/scripts/package_result_policy.py",
    ".github/scripts/promote_package_results.py",
    ".github/scripts/smoke_recovery.py",
    ".github/scripts/smoke_repair_evidence.py",
    ".github/scripts/smoke_repair_model.py",
    ".github/scripts/smoke_repair_native.py",
    ".github/scripts/smoke_repair_pipeline.py",
    ".github/scripts/smoke_repair_policy.py",
    ".github/scripts/smoke_repair_publisher.py",
    ".github/scripts/summary_slug_policy.py",
})
SMOKE_ACTIONS = frozenset({
    "apt-bootstrap",
    "collect-batch-observations",
    "collect-batch-results",
    "collect-batch-results-v2",
    "derive-package-source-expectations",
    "emit-package-observation",
    "emit-package-result",
    "generic-source-regression-check",
    "publish-generated-data-pr",
    "run-missing-package-smoke",
    "write-package-job-summary",
})
ROUTING_SCRIPT = ".github/scripts/ci_change_scope.py"
ROUTING_TEST = ".github/scripts/tests/test_ci_change_scope.py"
SMOKE_SUPPORT = frozenset({
    ".github/workflows/smoke-repair.yml",
    ".github/workflows/smoke-repair-package.yml",
    ".github/scripts/package_observation_migration_audit.py",
    ".github/scripts/package_workflow_supply_chain.py",
    ".github/scripts/package_workflow_action_lock.json",
    ".github/scripts/verify_action_lock_online.py",
    ".github/scripts/requirements-exact-run.txt",
    ".github/scripts/prefetch-heavy-baselines.sh",
    ".github/scripts/tests/test_active_collector_failure_evidence.py",
    ".github/scripts/tests/test_source_only_candidate_reporting.py",
    ".github/scripts/tests/test_vidgear_summary.py",
    ".github/scripts/tests/test_smoke_repair_integration.py",
})


class ScopeError(ValueError):
    """The requested comparison cannot safely determine routing."""


class _DeploymentHistoryChanged(ScopeError):
    """Valid API responses no longer describe one deployment snapshot."""


def read_api_response(command: list[str], *, environment: dict, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        assert process.stdout is not None
        chunks = []
        size = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ScopeError("deployment receipt API request timed out")
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_API_RESPONSE_BYTES - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_API_RESPONSE_BYTES:
                        raise ScopeError("deployment receipt API response exceeds byte limit")
                    chunks.append(chunk)
            if process.wait(timeout=max(0, deadline - time.monotonic())):
                raise ScopeError("deployment receipt API request failed; refusing to infer deployment state")
        except BaseException:
            process.kill()
            process.wait()
            raise
    return b"".join(chunks)


class GitHubReadAPI:
    """Bounded, authenticated reads of this repository's deployment evidence."""

    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
            raise ScopeError("GITHUB_REPOSITORY is missing or malformed")
        if not os.environ.get("GH_TOKEN"):
            raise ScopeError("authenticated deployment receipt lookup requires GH_TOKEN")
        self.prefix = f"repos/{repository}/actions/"
        self.requests = 0
        self.deadline = time.monotonic() + 120

    def __call__(self, endpoint: str) -> dict:
        if not endpoint.startswith(self.prefix) or any(c in endpoint for c in (":", "#", "..")):
            raise ScopeError("deployment receipt API endpoint is outside this repository")
        remaining = self.deadline - time.monotonic()
        if self.requests >= 128 or remaining <= 0:
            raise ScopeError("deployment receipt API read budget exhausted")
        self.requests += 1
        try:
            raw = read_api_response(
                ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint],
                environment={**os.environ, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"},
                timeout=min(15, remaining),
            )
        except subprocess.TimeoutExpired as exc:
            raise ScopeError("deployment receipt API request timed out") from exc
        try:
            document = decode_json(raw)
        except (ValueError, UnicodeError) as exc:
            raise ScopeError("deployment receipt API returned invalid JSON") from exc
        if not isinstance(document, dict):
            raise ScopeError("deployment receipt API returned an invalid document")
        return document


def positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def validate_deployment_run(run: dict, repository: str, workflow_id: int, *, require_success=True) -> None:
    if (
        not isinstance(run, dict)
        or not positive_id(run.get("id"))
        or not positive_id(run.get("run_attempt"))
        or not positive_id(run.get("run_number"))
        or not positive_id(run.get("workflow_id"))
        or run.get("workflow_id") != workflow_id
        or run.get("path") != ".github/workflows/main.yml"
        or run.get("head_branch") != "main"
        or run.get("event") not in {"push", "workflow_dispatch"}
        or not (
            (run.get("status") == "completed" and run.get("conclusion") in {
                "success", "failure", "cancelled", "timed_out", "action_required",
                "neutral", "skipped", "stale", "startup_failure",
            })
            or (run.get("status") in {"queued", "in_progress", "waiting", "pending", "requested"}
                and run.get("conclusion") is None)
        )
        or (require_success and (run.get("status"), run.get("conclusion")) != ("completed", "success"))
        or not isinstance(run.get("head_sha"), str)
        or not SHA_RE.fullmatch(run["head_sha"])
        or run["head_sha"] == "0" * 40
        or any(
            not isinstance(run.get(key), dict)
            or run[key].get("full_name") != repository
            for key in ("repository", "head_repository")
        )
    ):
        raise ScopeError("deployment run identity or successful completion is invalid")


def deployment_job_succeeded(jobs: list, run: dict) -> bool:
    repository = run["repository"]["full_name"]
    api_root = f"https://api.github.com/repos/{repository}/actions"
    run_url = f"{api_root}/runs/{run['id']}"
    ids = set()
    for job in jobs:
        if (
            not isinstance(job, dict) or not positive_id(job.get("id"))
            or not positive_id(job.get("run_id")) or not positive_id(job.get("run_attempt"))
            or job["id"] in ids or job.get("run_id") != run["id"]
            or job.get("run_attempt") != run["run_attempt"]
            or job.get("head_sha") != run["head_sha"]
            or job.get("status") != "completed"
            or job.get("url") != f"{api_root}/jobs/{job['id']}"
            or job.get("run_url") != run_url
            or job.get("html_url") != f"https://github.com/{repository}/actions/runs/{run['id']}/job/{job['id']}"
        ):
            raise ScopeError("deployment jobs do not bind to the exact successful run attempt")
        ids.add(job["id"])
    candidates = [job for job in jobs if job.get("name") == "Build and deploy reviewed main"]
    if not candidates:
        return False
    if len(candidates) != 1:
        raise ScopeError("duplicate deployment jobs cannot establish a receipt")
    job = candidates[0]
    if job.get("conclusion") == "skipped":
        return False
    if job.get("conclusion") != "success" or not isinstance(job.get("steps"), list):
        raise ScopeError("successful workflow has invalid deployment job evidence")
    for name in (
        "Require reviewed generated site data",
        "Require the reviewed commit to remain current",
        "Deploy to S3",
    ):
        steps = [step for step in job["steps"] if isinstance(step, dict) and step.get("name") == name]
        if len(steps) != 1:
            raise ScopeError(f"deployment receipt requires exactly one {name!r} step")
        if steps[0].get("status") != "completed" or steps[0].get("conclusion") != "success":
            return False
    return True


def latest_deployment_receipt(repository: str, api, *, current_run=None) -> dict:
    # Restart all evidence reads, but share the caller's API deadline/request budget.
    for attempt in range(3):
        try:
            return _deployment_receipt_snapshot(repository, api, current_run=current_run)
        except _DeploymentHistoryChanged as exc:
            if attempt == 2:
                raise ScopeError("deployment history did not stabilize after 3 lookup attempts") from exc


def _deployment_receipt_snapshot(repository: str, api, *, current_run=None) -> dict:
    prefix = f"repos/{repository}/actions"
    workflow = api(f"{prefix}/workflows/main.yml")
    workflow_id = workflow.get("id")
    if not positive_id(workflow_id) or workflow.get("path") != ".github/workflows/main.yml":
        raise ScopeError("main deployment workflow identity is invalid")
    identity_keys = ("id", "run_attempt", "head_sha", "run_number", "event")
    seen = {}
    previous_number = None
    total = None
    if current_run is not None and (
        not isinstance(current_run, tuple) or len(current_run) != 3 or not positive_id(current_run[0])
        or not positive_id(current_run[1]) or not isinstance(current_run[2], str)
        or not SHA_RE.fullmatch(current_run[2]) or current_run[2] == "0" * 40
    ):
        raise ScopeError("current deployment activation identity is invalid")
    requires_catch_up = current_run is not None and current_run[1] > 1
    # Inspect all statuses: newer unsuccessful executions may have changed S3.
    for page in range(1, 6):
        document = api(f"{prefix}/workflows/main.yml/runs?branch=main&per_page=50&page={page}")
        count = document.get("total_count")
        runs = document.get("workflow_runs")
        if type(count) is not int or count < 0 or not isinstance(runs, list):
            raise ScopeError("deployment run listing is incomplete")
        if len(runs) != min(50, max(0, count - len(seen))):
            raise ScopeError("deployment run listing is truncated")
        history_changed = total is not None and count != total
        page_seen = {}
        page_previous_number = None
        for listed in runs:
            validate_deployment_run(listed, repository, workflow_id, require_success=False)
            number = listed["run_number"]
            identity = tuple(listed[key] for key in identity_keys)
            if (
                listed["id"] in page_seen
                or (page_previous_number is not None and number >= page_previous_number)
            ):
                raise ScopeError("deployment history has duplicate or unordered runs")
            if listed["id"] in seen and seen[listed["id"]] != identity:
                raise ScopeError("deployment history has contradictory run identities")
            if listed["id"] in seen or (previous_number is not None and number >= previous_number):
                history_changed = True
            page_seen[listed["id"]] = identity
            page_previous_number = number
            if current_run is not None and listed["id"] == current_run[0]:
                if (listed["run_attempt"], listed["head_sha"]) != current_run[1:]:
                    raise ScopeError("listed activation contradicts the current run identity")
                if listed["status"] == "completed":
                    raise ScopeError("current activation cannot already be completed")
        if history_changed:
            raise _DeploymentHistoryChanged("deployment history changed during pagination")
        total = count
        seen.update(page_seen)
        previous_number = page_previous_number
        for listed in runs:
            if current_run is not None and listed["id"] == current_run[0]:
                # This activation cannot write S3, but a previous attempt may have.
                requires_catch_up = requires_catch_up or current_run[1] > 1
                continue
            endpoint = f"{prefix}/runs/{listed['id']}/attempts/{listed['run_attempt']}"
            run = api(endpoint)
            validate_deployment_run(run, repository, workflow_id, require_success=False)
            if any(run[key] != listed[key] for key in identity_keys):
                raise ScopeError("deployment attempt contradicts the listed run")
            if any(run.get(key) != listed.get(key) for key in ("status", "conclusion")):
                raise _DeploymentHistoryChanged("deployment attempt state changed after listing")
            if (run["status"], run["conclusion"]) != ("completed", "success"):
                # A failed/cancelled/live deployment may have partially written S3.
                # Never infer clean storage solely from a later content reversion.
                requires_catch_up = True
                continue
            job_document = api(f"{endpoint}/jobs?per_page=100&page=1")
            jobs = job_document.get("jobs")
            if (
                not isinstance(jobs, list) or not jobs or len(jobs) > 100
                or type(job_document.get("total_count")) is not int
                or job_document["total_count"] != len(jobs)
            ):
                raise ScopeError("attempt-specific deployment jobs are incomplete")
            if deployment_job_succeeded(jobs, run):
                receipt = {"run_id": run["id"], "run_attempt": run["run_attempt"], "sha": run["head_sha"]}
                if requires_catch_up:
                    receipt["requires_catch_up"] = True
                return receipt
            if not any(job.get("name") == "Build and deploy reviewed main" and job.get("conclusion") == "skipped" for job in jobs):
                requires_catch_up = True
        if len(seen) == total:
            break
    raise ScopeError(
        "No verified S3 deployment receipt within bounded history. "
        "Use an approved, enabled manual main deployment to establish a reviewed baseline."
    )


def classify_paths(paths: Iterable[str]) -> dict[str, bool]:
    smoke = False
    dashboard = False
    for path in paths:
        parts = path.split("/")
        if not path or any(part in {"", ".", ".."} for part in parts):
            raise ScopeError("Git returned an invalid repository-relative path")
        is_action = (
            len(parts) >= 4
            and parts[:2] == [".github", "actions"]
            and parts[2] in SMOKE_ACTIONS
        )
        tested_script = (
            ".github/scripts/" + parts[-1].removeprefix("test_")
            if path.startswith(".github/scripts/tests/test_")
            and len(parts) == 4
            else ""
        )
        is_router = path in {ROUTING_SCRIPT, ROUTING_TEST}
        is_smoke = bool(SMOKE_WORKFLOW_RE.fullmatch(path)) or (
            path in SMOKE_SCRIPTS
            or path in SMOKE_SUPPORT
            or tested_script in SMOKE_SCRIPTS | SMOKE_SUPPORT
            or bool(SMOKE_WORKFLOW_TEST_RE.fullmatch(path))
            or is_action
            or is_router
        )
        smoke = smoke or is_smoke
        # Unknown changes build conservatively; the shared router affects both.
        dashboard = dashboard or not is_smoke or is_router
    return {"smoke": smoke, "dashboard": dashboard}


def git(*arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
        check=False,
    )
    if result.returncode:
        raise ScopeError(
            f"Git {' '.join(arguments[:2])} failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def validate_commit(sha: str) -> None:
    if not SHA_RE.fullmatch(sha) or sha == "0" * 40:
        raise ScopeError("base and head must be nonzero, full lowercase commit SHAs")
    if git("cat-file", "-t", sha).strip() != b"commit":
        raise ScopeError("base and head must identify commits, not tags or trees")
    if git("rev-parse", "--verify", f"{sha}^{{commit}}").strip() != sha.encode():
        raise ScopeError("Git did not resolve the exact requested commit")


def changed_paths(base: str, head: str) -> list[str]:
    validate_commit(base)
    validate_commit(head)
    git("merge-base", "--is-ancestor", base, head)
    raw = git(
        "diff", "--name-only", "--no-renames", "--no-ext-diff", "--no-textconv",
        "--no-relative", "--ignore-submodules=none", "-z", base, head, "--",
    )
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise ScopeError("Git returned an incomplete NUL-delimited diff")
    return [os.fsdecode(path) for path in raw[:-1].split(b"\0")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--deployed-baseline", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        scope = classify_paths(changed_paths(arguments.base, arguments.head))
        result = dict(scope)
        if arguments.deployed_baseline:
            repository = os.environ.get("GITHUB_REPOSITORY", "")
            identity = [os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")]
            if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in identity):
                raise ScopeError("deployed-baseline routing requires the current GitHub run ID and attempt")
            receipt = latest_deployment_receipt(
                repository, GitHubReadAPI(repository),
                current_run=(int(identity[0]), int(identity[1]), arguments.head),
            )
            outstanding = classify_paths(changed_paths(receipt["sha"], arguments.head))["dashboard"]
            scope["dashboard"] = outstanding or receipt.get("requires_catch_up", False)
            result = {**scope, "deployment_receipt": receipt}
        if arguments.github_output is not None:
            with arguments.github_output.open("a", encoding="utf-8") as output:
                for name, value in scope.items():
                    output.write(f"{name}={str(value).lower()}\n")
    except (OSError, ScopeError) as exc:
        print(f"Cannot determine CI scope: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
