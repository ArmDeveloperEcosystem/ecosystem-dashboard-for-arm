"""Authenticate persistent smoke failures before any model or code-writing job."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestration_contract import (
    ContractError, canonical_json, decode_json, validate_current_ref,
    validate_manifest, validate_repository, validate_run, validate_sha,
)
from exact_run_aggregation import (
    _prevalidate_zip_directory, discover_topology_at_commit, expected_job_name,
    validate_checkout_binding,
)
from smoke_recovery import GitHub, timestamp, validate_recovery_jobs

MAX_PACKAGES = 10
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024
MAX_LOG_EXCERPT = 12 * 1024
ORCHESTRATOR_PATH = ".github/workflows/test-all-packages-orchestrator.yml"
ORCHESTRATOR_JOB = "Trigger and Wait for All Batches"
EVIDENCE_STEP = "Preserve original failures and accepted run identities"


def positive(value, label):
    if type(value) is not int or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def read_json(path, maximum=MAX_JSON_BYTES):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ContractError("repair input is not a bounded regular file")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ContractError("repair input exceeds its size limit")
    return decode_json(raw)


def write_json(path, value):
    path = Path(path)
    raw = (canonical_json(value) + "\n").encode()
    if len(raw) > MAX_JSON_BYTES:
        raise ContractError("repair output exceeds its size limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def complete_jobs(pages):
    if not isinstance(pages, list) or not pages or any(
        not isinstance(page, dict) or not isinstance(page.get("jobs"), list) for page in pages
    ):
        raise ContractError("repair jobs inventory is malformed")
    jobs = [job for page in pages for job in page["jobs"]]
    if any(type(page.get("total_count")) is not int or page["total_count"] != len(jobs) for page in pages):
        raise ContractError("repair jobs inventory is incomplete")
    if any(not isinstance(job, dict) for job in jobs):
        raise ContractError("repair job record is malformed")
    ids = [positive(job.get("id"), "job ID") for job in jobs]
    if len(ids) != len(set(ids)):
        raise ContractError("repair jobs inventory contains duplicate identities")
    return jobs


def authenticate_parent(api, repository, sha, run_id, attempt):
    validate_repository(repository)
    validate_sha(sha)
    positive(run_id, "orchestrator run ID")
    positive(attempt, "orchestrator attempt")
    repo = api.api(f"repos/{repository}")
    if not isinstance(repo, dict) or repo.get("full_name") != repository or repo.get("private") is not False:
        raise ContractError("repair model handoff is restricted to the verified public repository")
    validate_current_ref(api.api(f"repos/{repository}/git/ref/heads/main"), expected_sha=sha, branch="main")
    run = api.api(f"repos/{repository}/actions/runs/{run_id}")
    expected = {"id": run_id, "head_sha": sha, "head_branch": "main", "path": ORCHESTRATOR_PATH}
    if not isinstance(run, dict) or any(run.get(key) != value for key, value in expected.items()):
        raise ContractError("repair parent does not match the main orchestrator")
    if type(run.get("id")) is not int or positive(run.get("run_attempt"), "parent attempt") < attempt:
        raise ContractError("repair parent attempt is invalid")
    if run.get("event") not in {"push", "schedule", "workflow_dispatch"} or any(
        not isinstance(run.get(key), dict) or run[key].get("full_name") != repository
        for key in ("repository", "head_repository")
    ):
        raise ContractError("repair parent event or repository is invalid")
    jobs = complete_jobs(api.api(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", pages=True))
    matches = [job for job in jobs if job.get("name") == ORCHESTRATOR_JOB]
    if len(matches) != 1:
        raise ContractError("repair requires exactly one completed orchestrator job")
    job = matches[0]
    if any(type(job.get(key)) is not int for key in ("run_id", "run_attempt")) or any(
        job.get(key) != value for key, value in {
            "run_id": run_id, "run_attempt": attempt, "head_sha": sha,
            "status": "completed", "conclusion": "failure",
            "html_url": f"https://github.com/{repository}/actions/runs/{run_id}/job/{job['id']}",
        }.items()
    ):
        raise ContractError("repair requires an exact failed orchestrator job, not a timeout or cancellation")
    steps = job.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        raise ContractError("orchestrator evidence steps are missing")
    upload = [step for step in steps if step.get("name") == EVIDENCE_STEP]
    if len(upload) != 1 or upload[0].get("status") != "completed" or upload[0].get("conclusion") != "success":
        raise ContractError("orchestrator evidence upload did not succeed")
    return job


def read_audit_archive(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 2 * 1024 * 1024:
        raise ContractError("orchestrator evidence archive exceeds its bound")
    _prevalidate_zip_directory(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 512:
                raise ContractError("orchestrator evidence archive inventory is invalid")
            names = set()
            selected = []
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                mode = entry.external_attr >> 16
                if name in names or path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
                    raise ContractError("orchestrator evidence archive has unsafe or duplicate paths")
                names.add(name)
                if entry.flag_bits & 1 or stat.S_ISLNK(mode):
                    raise ContractError("orchestrator evidence archive has unsupported entries")
                if name in {"recovery-audit.json", ".orchestration/recovery-audit.json"}:
                    selected.append(entry)
            if len(selected) != 1 or selected[0].file_size > MAX_JSON_BYTES or selected[0].is_dir():
                raise ContractError("orchestrator evidence has no unique bounded recovery audit")
            with archive.open(selected[0]) as stream:
                data = stream.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES or len(data) != selected[0].file_size:
                raise ContractError("orchestrator recovery audit size is invalid")
            return decode_json(data)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ContractError("orchestrator evidence archive is invalid") from exc


def download_audit(api, repository, sha, run_id, attempt, artifact_id, parent_job):
    positive(artifact_id, "orchestrator artifact ID")
    metadata = api.api(f"repos/{repository}/actions/artifacts/{artifact_id}")
    expected_name = f"smoke-orchestration-evidence-{run_id}-{attempt}"
    if not isinstance(metadata, dict) or metadata.get("expired") is not False or type(metadata.get("id")) is not int or any(
        metadata.get(key) != value for key, value in {"id": artifact_id, "name": expected_name, "expired": False}.items()
    ):
        raise ContractError("repair artifact identity is invalid")
    origin = metadata.get("workflow_run")
    if not isinstance(origin, dict) or type(origin.get("id")) is not int or any(
        origin.get(key) != value for key, value in {"id": run_id, "head_sha": sha, "head_branch": "main"}.items()
    ):
        raise ContractError("repair artifact belongs to another workflow run")
    size = positive(metadata.get("size_in_bytes"), "artifact size")
    digest = metadata.get("digest")
    if size > 2 * 1024 * 1024 or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ContractError("repair artifact has no bounded authenticated digest")
    if not timestamp(parent_job["started_at"]) <= timestamp(metadata.get("created_at")) <= timestamp(parent_job["completed_at"]):
        raise ContractError("repair artifact was not created during the producing job")
    raw = api.api(f"repos/{repository}/actions/artifacts/{artifact_id}/zip", raw=True)
    if len(raw) != size or f"sha256:{hashlib.sha256(raw).hexdigest()}" != digest:
        raise ContractError("repair artifact bytes do not match GitHub evidence")
    return read_audit_archive(raw)


def read_source(root, sha, relative):
    if not isinstance(relative, str) or not re.fullmatch(r"\.github/workflows/test-[A-Za-z0-9_.-]+\.yml", relative) or "test-all-packages" in relative:
        raise ContractError("repair target is not a package workflow")
    reference = f"{validate_sha(sha)}:{relative}"
    environment = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
    size = subprocess.run(["git", "-C", str(root), "cat-file", "-s", reference],
        check=True, capture_output=True, timeout=15, env=environment).stdout.strip()
    if not re.fullmatch(rb"[0-9]{1,6}", size) or not 0 < int(size) <= MAX_SOURCE_BYTES:
        raise ContractError("repair workflow source exceeds its bound")
    result = subprocess.run(
        ["git", "-C", str(root), "show", reference],
        check=True, capture_output=True, timeout=15,
        env=environment,
    )
    if len(result.stdout) != int(size):
        raise ContractError("repair workflow source exceeds its bound")
    return result.stdout.decode("utf-8")


def sanitize_log(raw):
    if not isinstance(raw, bytes):
        return "Log unavailable."
    text = raw.decode("utf-8", errors="replace")[-MAX_LOG_EXCERPT:]
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*", "[private-key material removed]", text)
    lines = []
    for line in text.splitlines():
        if re.search(r"authorization\s*:|(?:token|password|secret|api[_-]?key|access[_-]?key)\s*[=:]", line, re.I):
            lines.append("[credential-bearing diagnostic line removed]")
            continue
        line = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b", "[credential removed]", line)
        line = re.sub(r"https?://[^\s/]+:[^\s/]+@", "https://[credentials removed]@", line)
        line = re.sub(r"(https?://[^\s?#]+)\?[^\s]+", r"\1?[query removed]", line)
        lines.append("".join(c for c in line if c == "\t" or ord(c) >= 32))
    return "\n".join(lines)[-MAX_LOG_EXCERPT:]


def contexts_from_audit(audit, *, api, repository, sha, run_id, attempt, root, topology=None):
    validate_repository(repository)
    validate_sha(sha)
    orchestration_id = f"orchestration-{positive(run_id, 'run ID')}-{positive(attempt, 'attempt')}"
    if not isinstance(audit, dict) or audit.get("status") != "failed":
        raise ContractError("repair requires a failed recovery audit")
    manifest = validate_manifest(audit.get("original_manifest"), expected_sha=sha,
        expected_branch="main", expected_orchestration_id=orchestration_id)
    batches = audit.get("failed_batches")
    if batches is None:
        return []
    if not isinstance(batches, list) or not batches or any(type(batch) is not int for batch in batches) or batches != sorted(set(batches)):
        raise ContractError("persistent failed-batch inventory is invalid")
    definitions = topology or discover_topology_at_commit(root, sha)
    if len(definitions) != len(manifest["batches"]):
        raise ContractError("repair topology differs from the parent manifest")
    history, dispatches = audit.get("history"), audit.get("dispatches")
    if not isinstance(history, list) or not isinstance(dispatches, list) or any(not isinstance(item, dict) for item in history + dispatches):
        raise ContractError("repair audit history is malformed")
    seen_ids = {record["run_id"] for record in manifest["batches"]}
    seen_nonces = {record["dispatch_nonce"] for record in manifest["batches"]}
    contexts = []
    for batch in batches:
        if not 1 <= batch <= len(definitions):
            raise ContractError("repair batch is not registered")
        original = manifest["batches"][batch - 1]
        old = [item for item in history if item.get("batch") == batch and item.get("retry") == 0]
        new = [item for item in history if item.get("batch") == batch and item.get("retry") == 1]
        sent = [item for item in dispatches if item.get("batch") == batch]
        if len(old) != 1 or len(new) != 1 or len(sent) != 1:
            raise ContractError("repair requires a unique original and confirmation run")
        sent = sent[0]
        if any(type(item.get("retry")) is not int for item in (old[0], new[0], sent)):
            raise ContractError("repair retry identity must be an integer")
        if type(sent.get("run_attempt")) is not int:
            raise ContractError("repair confirmation attempt must be an integer")
        if any(sent.get(key) != value for key, value in {
            "retry": 1, "expected_sha": sha, "run_attempt": 1,
            "reason": "failed_batch_confirmation", "status": "registered",
        }.items()):
            raise ContractError("repair confirmation dispatch was not authorized")
        replacement = dict(original, run_id=positive(sent.get("run_id"), "confirmation run ID"), dispatch_nonce=sent.get("dispatch_nonce"))
        if replacement["run_id"] in seen_ids or replacement["dispatch_nonce"] in seen_nonces:
            raise ContractError("repair confirmation reused a previous identity")
        seen_ids.add(replacement["run_id"])
        seen_nonces.add(replacement["dispatch_nonce"])
        failed_in_each_run = []
        for record, entry in ((original, old[0]), (replacement, new[0])):
            if type(entry.get("run_id")) is not int or entry.get("run_id") != record["run_id"] or entry.get("classification") != "failed":
                raise ContractError("repair history does not identify two failed batch runs")
            run = api.api(f"repos/{repository}/actions/runs/{record['run_id']}")
            validate_run(run, batch=batch, orchestration_id=orchestration_id,
                dispatch_nonce=record["dispatch_nonce"], expected_sha=sha, branch="main",
                repository=repository, expected_run_id=record["run_id"], require_completed=True)
            if run.get("head_repository", {}).get("full_name") != repository or run.get("conclusion") != "failure":
                raise ContractError("repair batch is not a failed run from this repository")
            pages = api.api(f"repos/{repository}/actions/runs/{record['run_id']}/attempts/1/jobs?per_page=100", pages=True)
            failed_in_each_run.append(validate_recovery_jobs(
                pages, definition=definitions[batch - 1], run=run, repository=repository))
        original_failed_names = {job["name"] for job in failed_in_each_run[0]}
        for job in failed_in_each_run[1]:
            if job["name"] not in original_failed_names:
                continue
            registrations = [item for item in definitions[batch - 1].packages if expected_job_name(item) == job["name"]]
            if len(registrations) != 1:
                raise ContractError("repair failed job has no unique package registration")
            registration = registrations[0]
            steps = job.get("steps")
            if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
                raise ContractError("repair failed step inventory is missing")
            failed_steps = [step["name"] for step in steps if step.get("conclusion") == "failure" and isinstance(step.get("name"), str)]
            if not failed_steps:
                raise ContractError("repair job failure has no observed failing step")
            contexts.append({
                "repository": repository, "base_sha": sha, "orchestration_id": orchestration_id,
                "orchestrator_run_id": run_id, "orchestrator_run_attempt": attempt,
                "package_slug": registration.package_slug, "workflow_path": registration.workflow_path,
                "called_job": registration.called_job, "batch": batch,
                "initial_run_id": original["run_id"], "confirmation_run_id": replacement["run_id"],
                "confirmation_job_id": job["id"], "failed_steps": failed_steps,
                "source_text": read_source(root, sha, registration.workflow_path),
                "log_excerpt": "Log unavailable.",
            })
    if len(contexts) > MAX_PACKAGES:
        raise ContractError("persistent failures exceed the automatic repair incident limit; human triage required")
    if len({item["package_slug"] for item in contexts}) != len(contexts):
        raise ContractError("repair contains duplicate package registrations")
    for context in contexts:
        try:
            raw = api.api(f"repos/{repository}/actions/jobs/{context['confirmation_job_id']}/logs", raw=True, timeout=5)
            context["log_excerpt"] = sanitize_log(raw)
        except ContractError:
            pass
    validate_current_ref(api.api(f"repos/{repository}/git/ref/heads/main"), expected_sha=sha, branch="main")
    return contexts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_checkout_binding(Path.cwd(), args.base_sha)
        api = GitHub(time.monotonic() + 300)
        job = authenticate_parent(api, args.repository, args.base_sha, args.run_id, args.attempt)
        audit = download_audit(api, args.repository, args.base_sha, args.run_id, args.attempt, args.artifact_id, job)
        contexts = contexts_from_audit(audit, api=api, repository=args.repository, sha=args.base_sha,
            run_id=args.run_id, attempt=args.attempt, root=Path.cwd())
        write_json(args.output, {"schema_version": 1, "contexts": contexts})
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"eligible={'true' if contexts else 'false'}\n")
                stream.write("matrix=" + json.dumps({"include": [{"slug": item["package_slug"]} for item in contexts]}, separators=(",", ":")) + "\n")
        print(f"Authenticated {len(contexts)} package repair contexts; no model or write credentials used.")
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        print(f"Smoke repair evidence rejected: {type(exc).__name__}. No repair authorized.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
