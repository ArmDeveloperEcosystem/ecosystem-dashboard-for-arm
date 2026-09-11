"""Bounded fresh-dispatch recovery; never reinterpret failed tests as passes."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode, urlsplit

from orchestration_contract import (
    ContractError,
    batch_dispatch_payload,
    canonical_json,
    generate_dispatch_nonce,
    select_exact_registration,
    validate_manifest,
    validate_manifest_text,
    validate_repository,
    validate_run,
    validate_sha,
)

MAX_RETRIES = 2
MAX_LOG_BYTES = 2 * 1024 * 1024
RECOVERY_SECONDS = 90 * 60
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_HARD_FAILURE = re.compile(
    r"permission denied|unauthorized|forbidden|certificate|checksum|hash mismatch"
    r"|signature verification|no space left|out of memory|killed process"
    r"|segmentation fault|assertion|assert(?:ion)?error|fatal error:|undefined reference"
    r"|compilation (?:error|fail)|(?:^|\s)error:|connection refused.*(?:localhost|127\.0\.0\.1)",
    re.IGNORECASE,
)


def timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("API timestamp is not UTC")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("API timestamp is malformed") from exc


def download_tokens(command):
    """Accept only a single, explicit, read-only curl command, not a shell program."""
    if not isinstance(command, str) or any(char in command.strip() for char in ("\n", "\r", "$", "`")):
        return None
    try:
        lexer = shlex.shlex(command.strip(), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or tokens[0] not in {"curl", "/usr/bin/curl"}:
        return None
    urls = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"--fail", "--location", "--silent", "--show-error", "--tlsv1.2"} or re.fullmatch(r"-[fsSLO]+", token):
            index += 1
            continue
        if token in {"--output", "-o", "--connect-timeout", "--max-time", "--retry", "--retry-delay", "--proto"}:
            index += 1
            if index >= len(tokens) or tokens[index] in {";", "&&", "||", "|", "&", ">", "<", "(", ")"}:
                return None
            value = tokens[index]
            if token in {"--output", "-o"} and ("://" in value or re.fullmatch(r"[;&|<>()]+", value)):
                return None
            if token == "--proto" and value != "=https":
                return None
            if token not in {"--output", "-o", "--proto"} and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                return None
            index += 1
            continue
        try:
            url = urlsplit(token)
            host = url.hostname
            if url.scheme != "https" or not host or url.username or url.password:
                return None
            if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                return None
            try:
                if not ipaddress.ip_address(host).is_global:
                    return None
            except ValueError:
                if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", host):
                    return None
        except ValueError:
            return None
        urls.append(token)
        index += 1
    return tokens if len(urls) == 1 else None


def trusted_download_command(root, sha, definition, job):
    from exact_run_aggregation import _yaml_mapping, expected_job_name

    registrations = [item for item in definition.packages if expected_job_name(item) == job.get("name")]
    steps = job.get("steps", [])
    failed = [step for step in steps if isinstance(step, dict) and step.get("conclusion") == "failure"] if isinstance(steps, list) else []
    if len(registrations) != 1 or len(failed) != 1:
        return None
    registration = registrations[0]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{validate_sha(sha)}:{registration.workflow_path}"],
            check=True, capture_output=True, timeout=20,
            env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
        )
        if len(result.stdout) > MAX_LOG_BYTES:
            return None
        workflow = _yaml_mapping(result.stdout, "recovery package workflow")
        source_job = workflow["jobs"][registration.called_job]
        source_steps = source_job["steps"]
        matching = [step for step in source_steps if isinstance(step, dict) and step.get("name") == failed[0].get("name")]
        if len(matching) != 1 or matching[0].get("continue-on-error", False) is not False:
            return None
        shell = matching[0].get("shell", source_job.get("defaults", {}).get("run", {}).get(
            "shell", workflow.get("defaults", {}).get("run", {}).get("shell", "bash")
        ))
        if shell not in {"bash", "sh"} or "uses" in matching[0]:
            return None
        for source in (workflow, source_job, matching[0]):
            environment = source.get("env", {})
            if not isinstance(environment, dict) or any(
                key in {"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PATH"}
                or not isinstance(key, str) or key.startswith(("BASH_FUNC_", "LD_"))
                for key in environment
            ):
                return None
        command = matching[0].get("run")
        return command if download_tokens(command) else None
    except (AttributeError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return None


def classify_retryable_failure(raw: bytes, job: dict, *, command=None) -> str:
    """Require a terminal download error in the actual failed step, not old noise."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_LOG_BYTES:
        return "unknown_failure"
    expected_command = download_tokens(command)
    if expected_command is None:
        return "unknown_failure"
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return "unknown_failure"
    failed_steps = [step for step in steps if step.get("conclusion") == "failure"]
    if len(failed_steps) != 1:
        return "unknown_failure"
    step = failed_steps[0]
    if not isinstance(step.get("name"), str) or not re.search(r"\b(?:download|fetch|install)\b", step["name"], re.I):
        return "unknown_failure"
    try:
        start, end = timestamp(step["started_at"]), timestamp(step["completed_at"])
        text = raw.decode("utf-8-sig", errors="strict")
    except (KeyError, UnicodeError, ContractError):
        return "unknown_failure"
    if start > end:
        return "unknown_failure"
    lines = []
    remote_download = False
    exit_seen = False
    command_matches = False
    command_group = False
    for line in text.splitlines():
        prefix, separator, message = line.partition(" ")
        if not separator:
            return "unknown_failure"
        try:
            observed = timestamp(prefix)
        except ContractError:
            return "unknown_failure"
        if start <= observed < end + timedelta(seconds=1):
            for url in re.findall(r"https?://[^\s\"'<>]+", _ANSI.sub("", message)):
                try:
                    host = urlsplit(url).hostname
                except ValueError:
                    return "unknown_failure"
                if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                    return "unknown_failure"
                try:
                    if not ipaddress.ip_address(host).is_global:
                        return "unknown_failure"
                except ValueError:
                    if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", host):
                        return "unknown_failure"
                remote_download = True
        if message.startswith("##[group]Run "):
            command_group = True
            if start <= observed < end + timedelta(seconds=1):
                command_matches = download_tokens(message.removeprefix("##[group]Run ")) == expected_command
        elif message.startswith("##[endgroup]"):
            command_group = False
            continue
        if command_group or not start <= observed < end + timedelta(seconds=1):
            continue
        message = _ANSI.sub("", message).strip()
        exit_marker = re.fullmatch(r"##\[error\]Process completed with exit code ([1-9][0-9]*)\.", message)
        if exit_marker:
            if exit_seen:
                return "unknown_failure"
            exit_seen = int(exit_marker.group(1))
            continue
        if not message:
            continue
        lines.append(message)
    curl_http = r"curl: \(22\) The requested URL returned error: (?:429|502|503|504)"
    other_lines = [line for line in lines if not re.fullmatch(curl_http, line)]
    if not lines or not exit_seen or not command_matches or not remote_download or _HARD_FAILURE.search("\n".join(other_lines)):
        return "unknown_failure"
    # Generic timeouts and local-service connection failures are deliberately excluded.
    terminal = lines[-1]
    if exit_seen == 22 and re.fullmatch(curl_http, terminal):
        return "transient_download"
    match = re.fullmatch(r"curl: \(6\) Could not resolve host: ([A-Za-z0-9.-]+)", terminal)
    if match and exit_seen == 6:
        host = match.group(1).lower()
        download_hosts = {urlsplit(token).hostname for token in expected_command if token.startswith("https://")}
        if host in download_hosts and "." in host and not host.endswith((".local", ".localhost", ".internal")):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return "transient_download"
    return "unknown_failure"


def validate_recovery_jobs(pages, *, definition, run, repository):
    from exact_run_aggregation import select_exact_jobs

    normalized = select_exact_jobs(
        pages, definition=definition, repository=repository,
        run={"id": run["id"], "attempt": 1, "created_at": run["created_at"], "updated_at": run["updated_at"]},
    )
    jobs = [job for page in pages for job in page["jobs"]]
    summaries = [job for job in jobs if job.get("name") == "summary"]
    if len(summaries) != 1 or len(jobs) != len(normalized) + 1:
        raise ContractError("unexpected or missing batch job")
    if len({job["id"] for job in jobs}) != len(jobs):
        raise ContractError("duplicate batch job identity")
    for job in jobs:
        job_id = job.get("id")
        if type(job_id) is not int or job_id <= 0:
            raise ContractError("invalid batch job identity")
        if type(job.get("run_id")) is not int or type(job.get("run_attempt")) is not int:
            raise ContractError("invalid batch job run or attempt")
        expected = {
            "run_id": run["id"], "run_attempt": 1, "head_sha": run["head_sha"],
            "status": "completed",
            "html_url": f"https://github.com/{repository}/actions/runs/{run['id']}/job/{job_id}",
        }
        if any(job.get(key) != value for key, value in expected.items()):
            raise ContractError("batch job belongs to another run, commit, or attempt")
        if job.get("conclusion") not in {"success", "failure"}:
            raise ContractError("batch job has an unaccepted conclusion")
        if not timestamp(run["created_at"]) <= timestamp(job.get("started_at")) <= timestamp(job.get("completed_at")) <= timestamp(run["updated_at"]):
            raise ContractError("batch job lies outside its run window")
    if summaries[0]["conclusion"] != "success":
        raise ContractError("batch collector failed; retry is not authorized")
    failed = [job for job in jobs if job["conclusion"] == "failure"]
    if bool(failed) != (run["conclusion"] == "failure"):
        raise ContractError("run conclusion contradicts its complete job inventory")
    return failed


def replace_manifest_record(manifest, *, old_record, replacement, seen_ids, seen_nonces):
    result = validate_manifest(manifest)
    batch = old_record["batch"]
    if type(batch) is not int or not 1 <= batch <= len(result["batches"]):
        raise ContractError("recovery replacement has an invalid batch")
    if result["batches"][batch - 1] != old_record:
        raise ContractError("stale recovery replacement")
    if replacement["run_id"] in seen_ids or replacement["dispatch_nonce"] in seen_nonces:
        raise ContractError("recovery reused an earlier dispatch identity")
    if replacement["batch"] != batch:
        raise ContractError("recovery replacement targets another batch")
    result["batches"][batch - 1] = replacement
    return validate_manifest(result)


class GitHub:
    def __init__(self, deadline):
        self.deadline = deadline

    def api(self, endpoint, *, payload=None, pages=False, raw=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ContractError("recovery time budget exhausted")
        command = ["gh", "api", endpoint]
        if pages:
            command += ["--paginate", "--slurp"]
        if payload is not None:
            command += ["--method", "POST", "--input", "-"]
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(
                    command, input=None if payload is None else canonical_json(payload).encode(),
                    stdout=output, stderr=subprocess.PIPE, timeout=min(60, remaining),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ContractError("GitHub API response unavailable; no evidence inferred") from exc
            if result.returncode:
                raise ContractError("GitHub API request failed; no evidence inferred")
            output.seek(0)
            data = output.read(MAX_LOG_BYTES + 1)
        if len(data) > MAX_LOG_BYTES:
            raise ContractError("GitHub response exceeds recovery resource limit")
        if raw:
            return data
        if payload is not None and not data:
            return None
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ContractError("GitHub API response is not JSON") from exc


class Recovery:
    def __init__(self, manifest, repository, root, audit_path, *, api=None, clock=time.monotonic, sleep=time.sleep, deadline_epoch=None):
        self.manifest = validate_manifest(manifest)
        self.repository = validate_repository(repository)
        self.root, self.audit_path = Path(root), Path(audit_path)
        self.clock, self.sleep = clock, sleep
        budget = RECOVERY_SECONDS
        if deadline_epoch is not None:
            if type(deadline_epoch) is not int or deadline_epoch <= 0:
                raise ContractError("shared orchestration deadline is invalid")
            budget = min(budget, deadline_epoch - time.time())
            if budget <= 0:
                raise ContractError("shared orchestration time budget exhausted")
        self.deadline = clock() + budget
        self.github = api or GitHub(self.deadline)
        self.seen_ids = {record["run_id"] for record in self.manifest["batches"]}
        self.seen_nonces = {record["dispatch_nonce"] for record in self.manifest["batches"]}
        self.audit = {"original_manifest": deepcopy(self.manifest), "history": [], "status": "in_progress"}
        self.definitions = None

    def save(self):
        self.audit_path.write_text(json.dumps(self.audit, indent=2) + "\n")

    def current(self):
        if self.clock() >= self.deadline:
            raise ContractError("recovery time budget exhausted")
        payload = self.github.api(f"repos/{self.repository}/git/ref/heads/{self.manifest['branch']}")
        if payload.get("ref") != f"refs/heads/{self.manifest['branch']}" or payload.get("object", {}).get("sha") != self.manifest["expected_sha"] or payload.get("object", {}).get("type") != "commit":
            raise ContractError("branch advanced; start a new orchestration for the new commit")

    def check_run(self, record, *, completed):
        run = self.github.api(f"repos/{self.repository}/actions/runs/{record['run_id']}")
        validate_run(
            run, batch=record["batch"], orchestration_id=self.manifest["orchestration_id"],
            dispatch_nonce=record["dispatch_nonce"], expected_sha=self.manifest["expected_sha"],
            branch=self.manifest["branch"], repository=self.repository,
            expected_run_id=record["run_id"], require_completed=completed,
        )
        if run.get("head_repository", {}).get("full_name") != self.repository:
            raise ContractError("run head repository differs from orchestration repository")
        return run

    def inspect(self, record, retry):
        run = self.check_run(record, completed=True)
        pages = self.github.api(f"repos/{self.repository}/actions/runs/{record['run_id']}/attempts/1/jobs?per_page=100", pages=True)
        failed_jobs = validate_recovery_jobs(
            pages, definition=self.definitions[record["batch"] - 1], run=run, repository=self.repository,
        )
        entry = {"batch": record["batch"], "run_id": run["id"], "retry": retry,
                 "run": run, "jobs": pages, "classification": "success", "failures": []}
        self.audit["history"].append(entry)
        self.save()
        for job in failed_jobs:
            try:
                raw = self.github.api(f"repos/{self.repository}/actions/jobs/{job['id']}/logs", raw=True)
                command = trusted_download_command(self.root, self.manifest["expected_sha"], self.definitions[record["batch"] - 1], job)
                classification = classify_retryable_failure(raw, job, command=command)
                digest = hashlib.sha256(raw).hexdigest() if isinstance(raw, bytes) else None
            except ContractError:
                classification, digest = "logs_unavailable", None
            entry["failures"].append({"job_id": job["id"], "name": job["name"],
                                      "classification": classification, "log_sha256": digest})
        if failed_jobs:
            entry["classification"] = "transient_download" if all(
                failure["classification"] == "transient_download" for failure in entry["failures"]
            ) else "repair_required"
        self.save()
        return entry["classification"]

    def dispatch(self, record, retry):
        self.current()
        nonce = generate_dispatch_nonce()
        if nonce in self.seen_nonces or any(item["dispatch_nonce"] == nonce for item in self.audit.get("dispatches", [])):
            raise ContractError("recovery generated a duplicate dispatch nonce")
        replacement = dict(record, dispatch_nonce=nonce)
        pending = {"batch": record["batch"], "retry": retry, "dispatch_nonce": nonce, "status": "pending_registration"}
        self.audit.setdefault("dispatches", []).append(pending)
        self.save()
        payload = batch_dispatch_payload(
            batch=record["batch"], orchestration_id=self.manifest["orchestration_id"],
            dispatch_nonce=nonce, expected_sha=self.manifest["expected_sha"], branch=self.manifest["branch"],
        )
        try:
            self.github.api(f"repos/{self.repository}/actions/workflows/{record['workflow']}/dispatches", payload=payload)
        except ContractError:
            # An ambiguous POST is reconciled by nonce, never retried as another POST.
            pending["dispatch_response"] = "ambiguous"
            self.save()
        query = urlencode({"branch": self.manifest["branch"], "head_sha": self.manifest["expected_sha"], "event": "workflow_dispatch", "per_page": 100})
        endpoint = f"repos/{self.repository}/actions/workflows/{record['workflow']}/runs?{query}"
        for _ in range(18):
            self.current()
            runs = self.github.api(endpoint, pages=True)
            if not isinstance(runs, list) or not runs or any(not isinstance(page, dict) or not isinstance(page.get("workflow_runs"), list) for page in runs):
                raise ContractError("recovery registration pages are malformed")
            count = sum(len(page["workflow_runs"]) for page in runs)
            if any(type(page.get("total_count")) is not int or page["total_count"] != count for page in runs):
                raise ContractError("recovery registration pagination is incomplete")
            run_id = select_exact_registration(
                runs, batch=record["batch"], orchestration_id=self.manifest["orchestration_id"],
                dispatch_nonce=nonce, expected_sha=self.manifest["expected_sha"],
                branch=self.manifest["branch"], repository=self.repository,
            )
            if run_id is not None:
                if run_id in self.seen_ids or any(item.get("run_id") == run_id for item in self.audit.get("dispatches", [])):
                    raise ContractError("recovery reused a previous workflow run")
                replacement["run_id"] = run_id
                pending.update(status="registered", run_id=run_id)
                self.save()
                self.current()
                return replacement
            self.sleep(10)
        raise ContractError("fresh retry has no unique exact registration")

    def recover(self):
        from exact_run_aggregation import discover_topology_at_commit

        self.save()
        self.current()
        self.definitions = discover_topology_at_commit(self.root, self.manifest["expected_sha"])
        pending = []
        blocked = []
        for record in self.manifest["batches"]:
            state = self.inspect(record, 0)
            if state == "transient_download":
                pending.append(record)
            elif state != "success":
                blocked.append(record["batch"])
        for retry in range(1, MAX_RETRIES + 1):
            if not pending:
                break
            self.sleep(60 * retry)
            self.current()
            replacements = [(record, self.dispatch(record, retry)) for record in pending]
            pending = []
            for original, replacement in replacements:
                while True:
                    self.current()
                    run = self.check_run(replacement, completed=False)
                    if run["status"] == "completed":
                        break
                    self.sleep(30)
                state = self.inspect(replacement, retry)
                if state == "success":
                    self.manifest = replace_manifest_record(
                        self.manifest, old_record=self.manifest["batches"][original["batch"] - 1],
                        replacement=replacement, seen_ids=self.seen_ids, seen_nonces=self.seen_nonces,
                    )
                elif state == "transient_download" and retry < MAX_RETRIES:
                    pending.append(replacement)
                else:
                    blocked.append(original["batch"])
                self.seen_ids.add(replacement["run_id"])
                self.seen_nonces.add(replacement["dispatch_nonce"])
                self.audit["accepted_manifest"] = self.manifest
                self.save()
        if blocked:
            raise ContractError(f"batches require repair, not more retries: {sorted(blocked)}")
        self.current()
        self.audit["status"] = "batches_passed_summary_pending"
        self.audit["accepted_manifest"] = self.manifest
        self.save()
        return self.manifest


def notify(argv):
    parser = argparse.ArgumentParser(description="Report a verified orchestrator job outcome once.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--orchestration-attempt", required=True, type=int)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--outcome", choices=("success", "failure", "cancelled"), required=True)
    parser.add_argument("--recipient", required=True)
    args = parser.parse_args(argv)
    repository = validate_repository(args.repository)
    sha = validate_sha(args.expected_sha)
    if args.run_id <= 0 or args.run_attempt <= 0 or not 0 < args.orchestration_attempt <= args.run_attempt:
        raise ContractError("notification run identity is invalid")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", args.recipient):
        raise ContractError("configure SMOKE_NOTIFICATION_LOGIN as a human GitHub login")
    api = GitHub(time.monotonic() + 120)
    run = api.api(f"repos/{repository}/actions/runs/{args.run_id}")
    expected = {"id": args.run_id, "run_attempt": args.run_attempt, "head_sha": sha,
                "head_branch": "main", "path": ".github/workflows/test-all-packages-orchestrator.yml"}
    if any(run.get(key) != value for key, value in expected.items()) or any(run.get(key, {}).get("full_name") != repository for key in ("repository", "head_repository")):
        raise ContractError("notification does not match the exact main orchestration")
    if type(run.get("id")) is not int or type(run.get("run_attempt")) is not int or run.get("event") not in {"push", "schedule", "workflow_dispatch"}:
        raise ContractError("notification parent run identity or event is invalid")
    # A notification-only rerun retains the producing job's attempt through needs.
    pages = api.api(f"repos/{repository}/actions/runs/{args.run_id}/attempts/{args.orchestration_attempt}/jobs?per_page=100", pages=True)
    jobs = [job for page in pages for job in page["jobs"]]
    if not pages or any(page.get("total_count") != len(jobs) for page in pages):
        raise ContractError("notification jobs response is incomplete")
    matched = [job for job in jobs if job.get("name") == "Trigger and Wait for All Batches"]
    if len(matched) != 1:
        raise ContractError("notification has no unique orchestrator job")
    job = matched[0]
    if any(type(job.get(key)) is not int or job[key] <= 0 for key in ("id", "run_id", "run_attempt")):
        raise ContractError("notification job numeric identity is invalid")
    if job.get("run_id") != args.run_id or job.get("run_attempt") != args.orchestration_attempt or job.get("status") != "completed" or job.get("head_sha") != sha or job.get("html_url") != f"https://github.com/{repository}/actions/runs/{args.run_id}/job/{job['id']}":
        raise ContractError("notification job identity or completion is invalid")
    allowed = {"success": {"success"}, "failure": {"failure", "timed_out", "startup_failure"}, "cancelled": {"cancelled"}}
    if job.get("conclusion") not in allowed[args.outcome]:
        raise ContractError("notification contradicts the completed orchestrator job")
    title = f"Arm64 smoke run {args.run_id}, attempt {args.orchestration_attempt}"
    url = f"https://github.com/{repository}/actions/runs/{args.run_id}"
    if args.outcome == "success":
        result = "All 22 batch runs and exact Global Summary completed successfully."
        followup = "Explicit test skips remain skips. Generated results still need their normal review, merge and deployment."
    else:
        result = "Validation did not complete successfully; this run is not verified green."
        followup = "Check the run for the failing stage, exhausted retries, changed main commit, or pending delivery approval. A code fix requires a reviewed repair PR. No automatic repair PR was created."
    body = (f"@{args.recipient}\n\n{result}\n\n"
            f"- [Workflow run]({url})\n- Tested commit: `{sha}`\n"
            f"- Orchestration attempt: `{args.orchestration_attempt}`\n"
            f"- Original failures and any recovery attempts remain in the run's evidence artifact.\n\n{followup}\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(body)
    query = urlencode({"q": f'repo:{repository} is:issue author:app/github-actions "{title}" in:title'})
    existing = api.api(f"search/issues?{query}")
    if existing.get("incomplete_results") is not False or not isinstance(existing.get("items"), list) or type(existing.get("total_count")) is not int or existing["total_count"] != len(existing["items"]):
        raise ContractError("notification issue lookup is incomplete")
    if any(item.get("title") == title and item.get("user", {}).get("login") == "github-actions[bot]" for item in existing.get("items", [])):
        print("This exact run attempt has already been reported.")
        return 0
    api.api(f"repos/{repository}/issues", payload={"title": title, "body": body})
    print("Posted the smoke-run report and mentioned its configured recipient.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "notify":
        try:
            return notify(argv[1:])
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            print(f"Smoke notification stopped: {exc}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--orchestration-id", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--deadline-epoch", type=int)
    args = parser.parse_args(argv)
    recovery = None
    try:
        manifest = validate_manifest_text(
            args.manifest.read_text().rstrip("\n"), expected_sha=args.expected_sha,
            expected_branch=args.branch, repository=args.repository,
        )
        validate_manifest(manifest, expected_orchestration_id=args.orchestration_id)
        recovery = Recovery(manifest, args.repository, Path.cwd(), args.audit, deadline_epoch=args.deadline_epoch)
        accepted = recovery.recover()
        args.manifest.write_text(canonical_json(accepted) + "\n")
        print("All batch jobs passed; exact Global Summary validation is still required.")
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        if recovery is not None:
            recovery.audit.update(status="failed", error=str(exc))
            recovery.save()
        print(f"Smoke recovery stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
