"""Bounded, persistent main recovery reporting; never dispatch or authorize repair.

Run ``sync`` from trusted main code, with a complete local Git checkout and the
pinned exact-run parser dependencies. Serialize writers in one repository-wide
Actions concurrency group (cancel-in-progress: false). Read-only is the default;
--write requires contents/actions/pull-requests read and issues write. The issue is a bounded
display journal, NOT authority to pass tests or spend another proposal budget.
New incidents require --recipient (or SMOKE_NOTIFICATION_LOGIN) and assign that
human GitHub login without adding recipient-controlled text to the journal.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlencode
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exact_run_aggregation import discover_topology_at_commit
from orchestration_contract import (
    BATCH_COUNT, ContractError, MainAdvanced, canonical_json, decode_json,
    select_exact_summary_registration, validate_dispatch_nonce,
    validate_current_ref, validate_manifest, validate_repository, validate_run,
    validate_sha, validate_summary_run,
)
from smoke_recovery import GitHub, timestamp, validate_recovery_jobs
from smoke_repair_evidence import (
    EVIDENCE_STEP, ORCHESTRATOR_JOB, ORCHESTRATOR_PATH, complete_jobs,
    download_audit, positive,
)

TITLE = "Arm64 main smoke recovery"
MARKER = "<!-- arm64-main-recovery:v1 -->"
MAX_PAGES = 20
MAX_REQUESTS = 160
MAX_RUNS = 32
MAX_PRS = 64
MAX_BODY = 32000
SECONDS = 300
LOOKBACK_DAYS = 7
STUCK_SECONDS = 8 * 60 * 60
SCHEDULE_GRACE_SECONDS = 60 * 60
STATES = {"needs_investigation", "pending_manual_review", "awaiting_full_main", "verified_green"}
REASONS = {"full_main_failed", "repair_review_pending", "main_advanced", "verified_full_main",
           "weekly_validation_missing", "main_validation_stuck", "required_evidence_missing",
           "validation_in_progress"}
PARENT_STEPS = (
    "Bind exact orchestration context", "Dispatch and capture exact batch runs",
    "Wait for captured batch runs", "Confirm failed batches once with fresh exact runs",
    "Dispatch exact global summary", EVIDENCE_STEP,
)
SUMMARY_STEPS = (
    "Bind exact generated-data base", "Validate exact batch-run manifest",
    "Download exact batch artifacts", "Assemble candidate and previous-production staging sets",
    "Validate candidate exact job identities", "Promote validated candidate results into production data",
    "Generate global summary", "Revalidate exact publication base",
    "Package exact generated test-results artifact", "Upload exact generated test-results artifact",
)
ISSUE_FIELDS = """id number title body state updatedAt lastEditedAt
author { login } editor { login } repository { nameWithOwner }"""


def bot_login(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}\[bot\]", value):
        raise ContractError("an exact bot login is required")
    return value


def recipient_login(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value,
    ) or "--" in value:
        raise ContractError("configure SMOKE_NOTIFICATION_LOGIN as a human GitHub login")
    return value


class BoundedAPI:
    """Reuse the existing byte/time-bounded transport; paginate explicitly."""

    def __init__(self, api=None, *, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + SECONDS
        self.transport = api or GitHub(time.monotonic() + SECONDS)
        self.requests = 0

    def api(self, endpoint, *, payload=None, raw=False, **kwargs):
        if kwargs or self.clock() >= self.deadline or self.requests >= MAX_REQUESTS:
            raise ContractError("incident request or runtime budget exhausted")
        self.requests += 1
        return self.transport.api(endpoint, payload=payload, raw=raw,
                                  timeout=min(60, self.deadline - self.clock()))

    def inventory(self, endpoint, key=None):
        items, total = [], None
        for page in range(1, MAX_PAGES + 1):
            separator = "&" if "?" in endpoint else "?"
            response = self.api(f"{endpoint}{separator}per_page=100&page={page}")
            if key is None:
                batch = response
            else:
                if not isinstance(response, dict) or type(response.get("total_count")) is not int:
                    raise ContractError("incident inventory has no exact count")
                observed = response["total_count"]
                if not 0 <= observed <= 100 * MAX_PAGES or total is not None and total != observed:
                    raise ContractError("incident inventory count changed or exceeds limit")
                total = observed
                batch = response.get(key)
            if not isinstance(batch, list) or len(batch) > 100 or any(not isinstance(x, dict) for x in batch):
                raise ContractError("incident inventory is malformed")
            items.extend(batch)
            ids = [positive(item.get("id"), "inventory ID") for item in items]
            if len(ids) != len(set(ids)):
                raise ContractError("incident inventory contains duplicate identities")
            if key is not None and len(items) == total or key is None and len(batch) < 100:
                return items
            if len(batch) < 100:
                raise ContractError("incident inventory is incomplete")
        raise ContractError("incident pagination bound exhausted")


def _identity(run, repository, run_id, attempt, sha, path):
    expected = {"id": run_id, "run_attempt": attempt, "head_sha": sha,
                "head_branch": "main", "path": path}
    if not isinstance(run, dict) or any(run.get(k) != v for k, v in expected.items()):
        raise ContractError("run does not match exact main identity")
    positive(run.get("id"), "run ID")
    positive(run.get("run_attempt"), "run attempt")
    if any(not isinstance(run.get(k), dict) or run[k].get("full_name") != repository
           for k in ("repository", "head_repository")):
        raise ContractError("run belongs to a foreign repository")
    if timestamp(run.get("created_at")) > timestamp(run.get("updated_at")):
        raise ContractError("run timestamps are reversed")
    return run


def _jobs(api, repository, run_id, attempt):
    jobs = api.inventory(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    return complete_jobs([{"total_count": len(jobs), "jobs": jobs}])


def _job(job, run, repository):
    job_id = positive(job.get("id"), "job ID")
    for key in ("run_id", "run_attempt"):
        positive(job.get(key), key)
    expected = {"run_id": run["id"], "run_attempt": run["run_attempt"], "head_sha": run["head_sha"],
                "status": "completed",
                "html_url": f"https://github.com/{repository}/actions/runs/{run['id']}/job/{job_id}"}
    if any(job.get(k) != v for k, v in expected.items()):
        raise ContractError("job identity or completion differs from its exact run")
    if not timestamp(run["created_at"]) <= timestamp(job.get("started_at")) <= timestamp(job.get("completed_at")) <= timestamp(run["updated_at"]):
        raise ContractError("job timestamps lie outside its exact run")
    return job


def _named(jobs, name):
    matched = [job for job in jobs if job.get("name") == name]
    if len(matched) != 1:
        raise ContractError("required job is missing or ambiguous")
    return matched[0]


def _passed_steps(job, required):
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps or any(not isinstance(s, dict) for s in steps):
        raise ContractError("required job step evidence is missing")
    numbers = [positive(s.get("number"), "step number") for s in steps]
    if len(set(numbers)) != len(numbers):
        raise ContractError("duplicate job step identity")
    if any(s.get("conclusion") not in {"success", "skipped"} or s.get("status") != "completed" for s in steps):
        raise ContractError("a failed or incomplete step cannot establish green")
    for name in required:
        matched = [s for s in steps if s.get("name") == name]
        if len(matched) != 1 or matched[0].get("conclusion") != "success":
            raise ContractError("required verification step is missing, failed or skipped")


def authenticate_run(api, repository, run_id, attempt, sha):
    run = _identity(api.api(f"repos/{repository}/actions/runs/{run_id}"), repository,
                    run_id, attempt, sha, ORCHESTRATOR_PATH)
    if run.get("event") not in {"push", "schedule", "workflow_dispatch"}:
        raise ContractError("unsupported parent event")
    if run.get("status") != "completed":
        raise ContractError("parent is not ready for incident reporting")
    if run.get("conclusion") not in {"success", "failure", "cancelled", "timed_out", "startup_failure", "action_required"}:
        raise ContractError("parent completion state is invalid")
    jobs = _jobs(api, repository, run_id, attempt)
    parent = _job(_named(jobs, ORCHESTRATOR_JOB), run, repository)
    scope = _job(_named(jobs, "Check smoke change scope"), run, repository)
    if scope.get("conclusion") != "success":
        raise ContractError("smoke scope was not authenticated")
    _passed_steps(scope, ("Check out exact main commit", "Classify authenticated changes"))
    if parent.get("conclusion") not in {"success", "failure", "cancelled", "timed_out", "startup_failure"}:
        raise ContractError("parent has no completed smoke result")
    return run, parent


def require_current(api, repository, run):
    validate_current_ref(api.api(f"repos/{repository}/git/ref/heads/main"),
                         expected_sha=run["head_sha"], branch="main")
    query = urlencode({"branch": "main", "created": ">=" + run["created_at"]})
    runs = api.inventory(f"repos/{repository}/actions/workflows/test-all-packages-orchestrator.yml/runs?{query}", "workflow_runs")
    exact = [item for item in runs if item.get("id") == run["id"]]
    if len(exact) != 1 or exact[0].get("run_attempt") != run["run_attempt"]:
        raise ContractError("parent run was superseded by another attempt")
    for item in runs:
        if item.get("head_branch") != "main" or item.get("path") != ORCHESTRATOR_PATH:
            raise ContractError("main run inventory contains a foreign identity")
        if (timestamp(item.get("created_at")), positive(item.get("id"), "run ID")) > (timestamp(run["created_at"]), run["id"]):
            raise ContractError("a newer main orchestrator supersedes this run")


class _EvidenceReader:
    """Retain only the ZIP authenticated by the existing audit downloader."""

    def __init__(self, api):
        self.delegate, self.archive = api, None

    def api(self, endpoint, **options):
        result = self.delegate.api(endpoint, **options)
        if options.get("raw"):
            if self.archive is not None:
                raise ContractError("ambiguous orchestrator evidence download")
            self.archive = result
        return result


def _summary_reference(raw, manifest, repository):
    # download_audit already authenticates digest, size and the entire ZIP directory.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        def read(name, limit):
            selected = [entry for entry in archive.infolist()
                        if entry.filename in {name, ".orchestration/" + name}]
            if len(selected) != 1 or selected[0].is_dir() or selected[0].file_size > limit:
                raise ContractError("exact summary evidence member is missing or ambiguous")
            with archive.open(selected[0]) as stream:
                data = stream.read(limit + 1)
            if len(data) != selected[0].file_size or len(data) > limit:
                raise ContractError("summary evidence member exceeds its bound")
            return data

        nonce = validate_dispatch_nonce(read("summary-dispatch-nonce", 64).decode("ascii"))
        if decode_json(read("run-manifest.json", 65536)) != manifest:
            raise ContractError("summary dispatch manifest differs from accepted recovery")
        registration = decode_json(read("summary-registration.json", 2 * 1024 * 1024))
        run_id = select_exact_summary_registration(registration, manifest=manifest, dispatch_nonce=nonce,
                    expected_sha=manifest["expected_sha"], branch="main", repository=repository)
        positive(run_id, "registered summary run ID")
        recorded = decode_json(read("summary-run.json", 2 * 1024 * 1024))
        result = validate_summary_run(recorded, manifest=manifest, dispatch_nonce=nonce,
                    expected_sha=manifest["expected_sha"], branch="main", repository=repository,
                    expected_run_id=run_id, require_completed=True)
        if result["conclusion"] != "success":
            raise ContractError("captured Global Summary did not pass")
        return run_id, nonce


def verify_full_main(api, repository, run, parent, root):
    """Revalidate live exact jobs; delegate collector/result checks to summary gates.

    The authenticated successful orchestrator and Global Summary are trusted main
    code. Their required steps enforce the existing exact artifact/result contract;
    issue text, a model receipt or a package-only run is never substituted for them.
    """
    if parent.get("conclusion") != "success" or run.get("status") == "completed" and run.get("conclusion") != "success":
        raise ContractError("the full parent did not succeed")
    _passed_steps(parent, PARENT_STEPS)
    artifacts = api.inventory(f"repos/{repository}/actions/runs/{run['id']}/artifacts", "artifacts")
    name = f"smoke-orchestration-evidence-{run['id']}-{run['run_attempt']}"
    matches = [item for item in artifacts if item.get("name") == name]
    if len(matches) != 1:
        raise ContractError("no unique exact orchestrator artifact")
    reader = _EvidenceReader(api)
    audit = download_audit(reader, repository, run["head_sha"], run["id"], run["run_attempt"], matches[0]["id"], parent)
    if not isinstance(audit, dict) or audit.get("status") != "batches_passed_summary_pending":
        raise ContractError("audit does not establish completed batch recovery")
    orchestration = f"orchestration-{run['id']}-{run['run_attempt']}"
    manifest = validate_manifest(audit.get("accepted_manifest"), expected_orchestration_id=orchestration,
                                 expected_sha=run["head_sha"], expected_branch="main")
    summary_id, nonce = _summary_reference(reader.archive, manifest, repository)
    topology = discover_topology_at_commit(Path(root), run["head_sha"])
    if len(topology) != BATCH_COUNT:
        raise ContractError("the full batch topology is required")
    for record, definition in zip(manifest["batches"], topology):
        batch = api.api(f"repos/{repository}/actions/runs/{record['run_id']}")
        _identity(batch, repository, record["run_id"], 1, run["head_sha"], definition.workflow_path)
        validate_run(batch, batch=record["batch"], orchestration_id=orchestration,
                     dispatch_nonce=record["dispatch_nonce"], expected_sha=run["head_sha"], branch="main",
                     repository=repository, expected_run_id=record["run_id"], require_completed=True)
        if not timestamp(parent["started_at"]) <= timestamp(batch["created_at"]) <= timestamp(batch["updated_at"]) <= timestamp(parent["completed_at"]):
            raise ContractError("batch is not inside the producing orchestration")
        jobs = _jobs(api, repository, batch["id"], 1)
        failed = validate_recovery_jobs([{"total_count": len(jobs), "jobs": jobs}],
                                        definition=definition, run=batch, repository=repository)
        if failed or batch["conclusion"] != "success":
            raise ContractError("a required batch or package is not green")
        for job in jobs:
            _passed_steps(job, ())
    query = urlencode({"branch": "main", "head_sha": run["head_sha"], "event": "workflow_dispatch",
                       "created": ">=" + parent["started_at"]})
    summaries = api.inventory(f"repos/{repository}/actions/workflows/test-all-packages-summary.yml/runs?{query}", "workflow_runs")
    selected = select_exact_summary_registration([{"total_count": len(summaries), "workflow_runs": summaries}],
                manifest=manifest, dispatch_nonce=nonce, expected_sha=run["head_sha"], branch="main", repository=repository)
    if selected != summary_id:
        raise ContractError("live Global Summary differs from the captured exact registration")
    summary = api.api(f"repos/{repository}/actions/runs/{summary_id}")
    _identity(summary, repository, summary_id, 1, run["head_sha"], ".github/workflows/test-all-packages-summary.yml")
    validate_summary_run(summary, manifest=manifest, dispatch_nonce=nonce, expected_sha=run["head_sha"],
                         branch="main", repository=repository, expected_run_id=summary_id, require_completed=True)
    if summary["conclusion"] != "success" or not timestamp(parent["started_at"]) <= timestamp(summary["created_at"]) <= timestamp(summary["updated_at"]) <= timestamp(parent["completed_at"]):
        raise ContractError("Global Summary is not a successful child of this orchestration")
    jobs = _jobs(api, repository, summary["id"], 1)
    if len(jobs) != 2 or {job.get("name") for job in jobs} != {"Generate Global Summary", "Open generated test-results draft PR"}:
        raise ContractError("Global Summary required job inventory is incomplete")
    for job in jobs:
        _job(job, summary, repository)
        if job.get("conclusion") != "success":
            raise ContractError("a required Global Summary job did not pass")
        _passed_steps(job, SUMMARY_STEPS if job["name"] == "Generate Global Summary" else ("Open or update aggregated test-results review PR",))
    require_current(api, repository, run)
    return summary["id"]


def _run_record(run):
    return {"id": run["id"], "attempt": run["run_attempt"], "sha": run["head_sha"], "created_at": run["created_at"]}


def _record(value):
    if not isinstance(value, dict) or set(value) != {"id", "attempt", "sha", "created_at"}:
        raise ContractError("incident contains a malformed run record")
    positive(value["id"], "record ID")
    positive(value["attempt"], "record attempt")
    validate_sha(value["sha"])
    timestamp(value["created_at"])
    return value


def validate_journal_anchor(api, repository, record):
    historical = api.api(f"repos/{repository}/actions/runs/{record['id']}/attempts/{record['attempt']}")
    _identity(historical, repository, record["id"], record["attempt"], record["sha"], ORCHESTRATOR_PATH)
    if historical.get("created_at") != record["created_at"] or historical.get("event") not in {"push", "schedule", "workflow_dispatch"}:
        raise ContractError("incident journal anchor contradicts GitHub metadata")


def render(state):
    links = "".join(f"- Run: https://github.com/{state['repository']}/actions/runs/{run['id']}/attempts/{run['attempt']}\n"
                    for run in state["runs"])
    links += "".join(f"- Repair PR: https://github.com/{state['repository']}/pull/{number}\n" for number in state["pull_requests"])
    body = (f"{MARKER}\n# Main smoke recovery\n\n"
            "Only a fresh full-main verification can close this incident. PR review, merge, "
            "or a passing package alone is not fleet verification.\n\n"
            "Required jobs and exact summary checks must pass. Explicit optional test skips "
            "remain skips, not passes; unexecuted optional tests are not certified.\n\n"
            f"Status: `{state['status']}`\nReason: `{state['reason']}`\n\n"
            "Open repair PRs need human review; they may not cover every remaining failure.\n\n"
            + links + "\n"
            "```json\n" + canonical_json(state) + "\n```\n")
    if len(body.encode()) > MAX_BODY:
        raise ContractError("incident journal exceeds its bound")
    return body


def parse(body, repository):
    if not isinstance(body, str) or len(body.encode()) > MAX_BODY:
        raise ContractError("incident body is not bounded")
    match = re.search(r"\n```json\n([^\n]+)\n```\n$", body)
    if not match:
        raise ContractError("incident journal is missing")
    state = decode_json(match[1])
    if not isinstance(state, dict) or set(state) != {"schema", "repository", "status", "reason", "runs", "pull_requests"}:
        raise ContractError("incident state schema is invalid")
    if type(state["schema"]) is not int or state["schema"] != 1 or state["repository"] != repository or state["status"] not in STATES or state["reason"] not in REASONS:
        raise ContractError("incident state identity is invalid")
    runs, prs = state["runs"], state["pull_requests"]
    if not isinstance(runs, list) or len(runs) > MAX_RUNS or not runs and state["status"] == "verified_green":
        raise ContractError("incident run journal cannot substantiate its status")
    for run in runs:
        _record(run)
    keys = [(timestamp(r["created_at"]), r["id"], r["attempt"]) for r in runs]
    if keys != sorted(set(keys)):
        raise ContractError("incident journal is duplicated or reordered")
    if not isinstance(prs, list) or len(prs) > MAX_PRS or any(type(p) is not int or p <= 0 for p in prs) or prs != sorted(set(prs)) or prs and not runs:
        raise ContractError("incident PR journal is invalid")
    if render(state) != body:
        raise ContractError("incident body was modified outside the controller")
    return state


def issue_snapshot(api, repository, number, bot):
    owner, name = repository.split("/")
    query = "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){" + ISSUE_FIELDS + "}}}"
    response = api.api("graphql", payload={"query": query, "variables": {"owner": owner, "name": name, "number": number}})
    try:
        issue = response["data"]["repository"]["issue"]
        if response.get("errors") or issue["number"] != number or issue["repository"]["nameWithOwner"] != repository:
            raise ContractError("incident GraphQL identity differs from REST")
        if issue["author"]["login"] != bot or issue["title"] != TITLE or issue["state"] not in {"OPEN", "CLOSED"}:
            raise ContractError("incident is not the exact bot-owned issue")
        if issue["lastEditedAt"] is not None and (issue.get("editor") or {}).get("login") != bot:
            raise ContractError("incident was edited by a foreign identity")
        if not isinstance(issue["id"], str) or not re.fullmatch(r"[A-Za-z0-9_=-]{1,128}", issue["id"]):
            raise ContractError("incident node identity is malformed")
        timestamp(issue["updatedAt"])
        parse(issue["body"], repository)
        return issue
    except (KeyError, TypeError) as exc:
        raise ContractError("incident GraphQL evidence is incomplete") from exc


def find_issue(api, repository, bot):
    issues = api.inventory(f"repos/{repository}/issues?state=all&sort=created&direction=desc")
    matched = [item for item in issues if item.get("title") == TITLE or MARKER in (item.get("body") or "")]
    if len(matched) > 1:
        raise ContractError("multiple recovery issues are ambiguous")
    if not matched:
        return None
    item = matched[0]
    if "pull_request" in item or item.get("user", {}).get("login") != bot or item.get("user", {}).get("type") != "Bot":
        raise ContractError("recovery issue ownership is foreign")
    return issue_snapshot(api, repository, positive(item.get("number"), "issue number"), bot)


def repair_status(api, repository, state, repair_bot):
    if not repair_bot:
        if state["pull_requests"]:
            raise ContractError("repair bot identity is required for existing PRs")
        return [], False
    bot_login(repair_bot)
    prefixes = {f"automation/smoke-repair/{r['id']}-{r['attempt']}-": r for r in state["runs"]}
    pulls = api.inventory(f"repos/{repository}/pulls?state=all&base=main&sort=created&direction=desc")
    selected, pending = [], False
    for item in pulls:
        branch = (item.get("head") or {}).get("ref", "")
        matching = [prefix for prefix in prefixes if isinstance(branch, str) and branch.startswith(prefix)]
        if not matching and item.get("number") not in state["pull_requests"]:
            continue
        number = positive(item.get("number"), "repair PR")
        pull = api.api(f"repos/{repository}/pulls/{number}")
        if len(matching) != 1 or pull.get("number") != number or (pull.get("head") or {}).get("ref") != branch:
            raise ContractError("repair PR incident identity is ambiguous")
        repair_id = branch.removeprefix("automation/smoke-repair/")
        if not re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*-[a-z0-9][a-z0-9_-]{0,99}", repair_id):
            raise ContractError("repair branch identity is invalid")
        if pull.get("user", {}).get("login") != repair_bot or pull.get("user", {}).get("type") != "Bot":
            raise ContractError("repair PR is foreign-owned")
        for side in ("base", "head"):
            if (pull.get(side) or {}).get("repo", {}).get("full_name") != repository:
                raise ContractError("repair PR targets a foreign repository")
        if pull["base"].get("ref") != "main" or not (pull.get("body") or "").startswith(f"<!-- smoke-repair:{repair_id}:v1 -->\n"):
            raise ContractError("repair PR ownership marker does not match its branch")
        if pull.get("html_url") != f"https://github.com/{repository}/pull/{number}" or pull.get("state") not in {"open", "closed"}:
            raise ContractError("repair PR URL or state is invalid")
        validate_sha(pull["head"].get("sha"))
        selected.append(number)
        pending |= pull["state"] == "open"
    if len(selected) > MAX_PRS or not set(state["pull_requests"]).issubset(selected):
        raise ContractError("repair PR inventory is incomplete or exhausted")
    return sorted(selected), pending


def sync(*, repository, run_id, run_attempt, expected_sha, repository_root,
         bot="github-actions[bot]", repair_bot=None, recipient=None, write=False, api=None):
    repository = validate_repository(repository)
    validate_sha(expected_sha)
    positive(run_id, "run ID")
    positive(run_attempt, "run attempt")
    bot_login(bot)
    if recipient is not None:
        recipient_login(recipient)
    api = api if isinstance(api, BoundedAPI) else BoundedAPI(api)
    info = api.api(f"repos/{repository}")
    if not isinstance(info, dict) or info.get("full_name") != repository or info.get("private") is not False:
        raise ContractError("incident reporting is restricted to the public repository")
    run, parent = authenticate_run(api, repository, run_id, run_attempt, expected_sha)
    issue = find_issue(api, repository, bot)
    state = parse(issue["body"], repository) if issue else {"schema": 1, "repository": repository,
             "status": "needs_investigation", "reason": "full_main_failed", "runs": [], "pull_requests": []}
    record = _run_record(run)
    if state["runs"]:
        last = state["runs"][-1]
        validate_journal_anchor(api, repository, last)
        if (timestamp(record["created_at"]), run_id, run_attempt) < (timestamp(last["created_at"]), last["id"], last["attempt"]):
            return {"status": "stale_event_ignored", "issue": issue["number"], "written": False}
        if record["id"] == last["id"] and record["attempt"] == last["attempt"] and record != last:
            raise ContractError("journal run identity contradicts authenticated metadata")
        if issue["state"] == "CLOSED" and state["status"] == "verified_green" and record != last:
            # Start a new bounded episode; the prior issue revisions retain history.
            state["runs"], state["pull_requests"] = [], []
    if record not in state["runs"]:
        if len(state["runs"]) >= MAX_RUNS:
            raise ContractError("incident journal exhausted; human investigation required")
        state["runs"].append(record)
    summary_id = None
    try:
        require_current(api, repository, run)
    except MainAdvanced:
        state["status"] = "awaiting_full_main"
        state["reason"] = "main_advanced"
    else:
        if parent["conclusion"] == "success":
            summary_id = verify_full_main(api, repository, run, parent, repository_root)
            state["status"] = "verified_green"
            state["reason"] = "verified_full_main"
        else:
            state["status"] = "needs_investigation"
            state["reason"] = "full_main_failed"
    state["pull_requests"], pending = repair_status(api, repository, state, repair_bot)
    if pending and state["status"] == "needs_investigation":
        state["status"] = "pending_manual_review"
        state["reason"] = "repair_review_pending"
    if state["status"] == "verified_green":
        require_current(api, repository, run)
    target_state = "CLOSED" if state["status"] == "verified_green" else "OPEN"
    result = {"status": state["status"], "issue": issue["number"] if issue else None,
              "run_id": run_id, "run_attempt": run_attempt, "summary_run_id": summary_id, "written": False}
    if summary_id is not None:
        result["verification_scope"] = "required_package_jobs_and_exact_summary"
        result["optional_skips"] = "not_counted_as_passes"
    return _publish(api, repository, bot, issue, state, result, recipient=recipient, write=write,
                    before_write=lambda: _recheck(api, repository, run, parent, target_state))


def _recheck(api, repository, run, parent, target_state):
    fresh, fresh_parent = authenticate_run(api, repository, run["id"], run["run_attempt"], run["head_sha"])
    if fresh != run or fresh_parent != parent:
        raise ContractError("run evidence changed before publication")
    if target_state == "CLOSED":
        require_current(api, repository, fresh)


def _publish(api, repository, bot, issue, state, result, *, recipient, write, before_write):
    body = render(state)
    parse(body, repository)
    target_state = "CLOSED" if state["status"] == "verified_green" else "OPEN"
    if not write or issue is None and target_state == "CLOSED":
        return result
    if issue is not None and issue["body"] == body and issue["state"] == target_state:
        return result
    if issue is None:
        recipient = recipient_login(recipient)
    viewer = api.api("graphql", payload={"query": "query { viewer { login } }"})
    if not isinstance(viewer, dict) or viewer.get("errors") or ((viewer.get("data") or {}).get("viewer") or {}).get("login") != bot:
        raise ContractError("incident writes require the configured bot identity")
    if issue is None and api.api(f"repos/{repository}/assignees/{recipient}", raw=True) != b"":
        raise ContractError("incident recipient eligibility was not confirmed")
    # The workflow concurrency group is mandatory: GitHub issue writes have no CAS.
    if find_issue(api, repository, bot) != issue:
        raise ContractError("incident changed during validation; retry serialized update")
    before_write()
    if issue is None:
        response = api.api(f"repos/{repository}/issues", payload={"title": TITLE, "body": body, "assignees": [recipient]})
        number = positive(response.get("number") if isinstance(response, dict) else None, "created issue")
        assignees = response.get("assignees")
        if not isinstance(assignees, list) or len(assignees) != 1 or not isinstance(assignees[0], dict) or assignees[0].get("type") != "User" or not isinstance(assignees[0].get("login"), str) or assignees[0]["login"].lower() != recipient.lower():
            raise ContractError("created incident recipient assignment was not confirmed")
        result["assigned_to"] = recipient
    else:
        mutation = "mutation($input:UpdateIssueInput!){updateIssue(input:$input){issue{" + ISSUE_FIELDS + "}}}"
        response = api.api("graphql", payload={"query": mutation, "variables": {"input": {
            "id": issue["id"], "body": body, "state": target_state}}})
        if not isinstance(response, dict) or response.get("errors"):
            raise ContractError("incident update response was not successful")
        number = issue["number"]
    final = issue_snapshot(api, repository, number, bot)
    if final["body"] != body or final["state"] != target_state:
        raise ContractError("incident write was not independently confirmed")
    result.update(issue=number, written=True)
    return result


def watch(*, repository, repository_root, bot="github-actions[bot]", repair_bot=None,
          recipient=None, write=False, api=None, now=None):
    """Inspect at most seven days; missing/stuck runs are never silently green."""
    repository = validate_repository(repository)
    bot_login(bot)
    if recipient is not None:
        recipient_login(recipient)
    api = api if isinstance(api, BoundedAPI) else BoundedAPI(api)
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
        raise ContractError("watchdog requires a UTC clock")
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    endpoint = f"repos/{repository}/actions/workflows/test-all-packages-orchestrator.yml/runs?" + urlencode({"branch": "main", "created": ">=" + start})
    runs = api.inventory(endpoint, "workflow_runs")
    if len(runs) > 50:
        raise ContractError("watchdog recent-run inspection limit exceeded")
    # Saturday 03:00 UTC is the repository's Friday-evening weekly schedule.
    due = now.replace(hour=3, minute=0, second=0, microsecond=0) - timedelta(days=(now.weekday() - 5) % 7)
    if due > now:
        due -= timedelta(days=7)
    problem, candidate = "weekly_validation_missing", None
    for listed in sorted(runs, key=lambda r: (timestamp(r.get("created_at")), positive(r.get("id"), "run ID")), reverse=True):
        run_id, attempt, sha = positive(listed.get("id"), "run ID"), positive(listed.get("run_attempt"), "run attempt"), validate_sha(listed.get("head_sha"))
        run = _identity(api.api(f"repos/{repository}/actions/runs/{run_id}"), repository, run_id, attempt, sha, ORCHESTRATOR_PATH)
        if run.get("event") not in {"push", "schedule", "workflow_dispatch"} or not timestamp(start) <= timestamp(run["created_at"]) <= now:
            raise ContractError("watchdog run is outside the bounded main window")
        jobs = _jobs(api, repository, run_id, attempt)
        parents = [j for j in jobs if j.get("name") == ORCHESTRATOR_JOB]
        if len(parents) > 1:
            raise ContractError("watchdog parent job is ambiguous")
        if run.get("status") == "completed":
            if parents and parents[0].get("conclusion") == "skipped" and run.get("conclusion") == "success":
                continue  # A website-only push is deliberately not a smoke cycle.
            if timestamp(run["created_at"]) < due and (now - due).total_seconds() >= SCHEDULE_GRACE_SECONDS:
                break
            if not parents or parents[0].get("conclusion") == "skipped":
                problem, candidate = "required_evidence_missing", run
                break
            return sync(repository=repository, run_id=run_id, run_attempt=attempt, expected_sha=sha,
                        repository_root=repository_root, bot=bot, repair_bot=repair_bot, recipient=recipient,
                        write=write, api=api)
        if run.get("status") not in {"queued", "in_progress", "waiting", "pending", "requested"} or run.get("conclusion") is not None:
            raise ContractError("watchdog run has an invalid incomplete state")
        if (now - timestamp(run["created_at"])).total_seconds() < STUCK_SECONDS:
            problem, candidate = "validation_in_progress", run
        else:
            problem, candidate = "main_validation_stuck", run
        break
    if candidate is None and (now - due).total_seconds() < SCHEDULE_GRACE_SECONDS:
        return {"status": "weekly_schedule_grace", "issue": None, "written": False}
    info = api.api(f"repos/{repository}")
    if not isinstance(info, dict) or info.get("full_name") != repository or info.get("private") is not False:
        raise ContractError("watchdog requires the public repository")
    issue = find_issue(api, repository, bot)
    if issue is None and problem == "validation_in_progress":
        return {"status": "validation_in_progress", "issue": None, "run_id": candidate["id"], "written": False}
    state = parse(issue["body"], repository) if issue else {"schema": 1, "repository": repository,
             "status": "awaiting_full_main", "reason": problem, "runs": [], "pull_requests": []}
    if state["runs"]:
        validate_journal_anchor(api, repository, state["runs"][-1])
    if issue and issue["state"] == "CLOSED" and state["status"] == "verified_green":
        state["runs"], state["pull_requests"] = [], []
    state["status"] = "needs_investigation" if candidate and problem != "validation_in_progress" else "awaiting_full_main"
    state["reason"] = problem
    if candidate and _run_record(candidate) not in state["runs"]:
        state["runs"].append(_run_record(candidate))
    state["pull_requests"], _ = repair_status(api, repository, state, repair_bot)
    parse(render(state), repository)
    result = {"status": state["status"], "reason": problem,
              "issue": issue["number"] if issue else None, "written": False}

    def unchanged():
        if api.inventory(endpoint, "workflow_runs") != runs:
            raise ContractError("watchdog inventory changed before publication")

    return _publish(api, repository, bot, issue, state, result, recipient=recipient, write=write, before_write=unchanged)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "watch"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--expected-sha")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--bot-login", default="github-actions[bot]")
    parser.add_argument("--repair-bot-login", default=os.environ.get("SMOKE_REPAIR_APP_BOT_LOGIN"))
    parser.add_argument("--recipient", default=os.environ.get("SMOKE_NOTIFICATION_LOGIN"))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        options = dict(repository=args.repository, repository_root=args.repository_root,
                       bot=args.bot_login, repair_bot=args.repair_bot_login, recipient=args.recipient, write=args.write)
        if args.command == "sync":
            result = sync(**options, run_id=args.run_id, run_attempt=args.run_attempt, expected_sha=args.expected_sha)
        elif any(value is not None for value in (args.run_id, args.run_attempt, args.expected_sha)):
            raise ContractError("watch mode selects its own authenticated run")
        else:
            result = watch(**options)
        print(canonical_json(result))
        return 0
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError):
        # Never print upstream responses, model output, issue text or raw logs.
        print("Recovery incident not verified; no green conclusion authorized. Inspect trusted workflow evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
