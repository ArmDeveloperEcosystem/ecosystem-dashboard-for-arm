"""Admit a data-only repair callback without giving the public repo model access."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.parse import urlencode
import zipfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestration_contract import ContractError, decode_json, validate_current_ref, validate_sha
from exact_run_aggregation import _UniqueSafeLoader, _prevalidate_zip_directory, validate_checkout_binding
from smoke_recovery import GitHub, timestamp
from smoke_repair_evidence import (
    authenticate_parent, complete_jobs, contexts_from_audit, download_audit,
    positive, read_json, write_json,
)
from smoke_repair_pipeline import admit, select_context
from smoke_repair_policy import APT_BUILD_DEPENDENCIES, PYTHON_BUILD_DEPENDENCIES

REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
WORKFLOW = ".github/workflows/smoke-repair-receive.yml"
EVENT = "smoke-repair-proposal"
MAX_AGE = 72 * 60 * 60
MAX_ARCHIVE = 2 * 1024 * 1024
PAYLOAD_KEYS = {
    "schema_version", "repository", "base_sha", "orchestrator_run_id",
    "orchestrator_attempt", "context_artifact_id", "package_slug",
    "context_sha256", "operations",
}
VARIABLES = {"MAKEFLAGS", "CMAKE_BUILD_PARALLEL_LEVEL", "CARGO_BUILD_JOBS", "GOMAXPROCS"}
PREPARE_JOBS = {
    "Authenticate exhausted smoke confirmations",
    "Prepare authenticated repair requests / Authenticate exhausted smoke confirmations",
}


def context_digest(context):
    raw = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError("repair operation has an invalid integer")
    return value


def validate_operations(operations):
    if type(operations) is not list or not 1 <= len(operations) <= 12:
        raise ContractError("repair requires a bounded nonempty operation list")
    for op in operations:
        if type(op) is not dict or type(op.get("kind")) is not str:
            raise ContractError("repair operation is malformed")
        integer(op.get("step"), 0, 255)
        kind = op["kind"]
        if kind in {"prepend_apt", "prepend_pip"}:
            if set(op) != {"kind", "step", "packages"}:
                raise ContractError("dependency operation has unexpected fields")
            packages = op["packages"]
            allowed = APT_BUILD_DEPENDENCIES if kind == "prepend_apt" else PYTHON_BUILD_DEPENDENCIES
            if (type(packages) is not list or not 1 <= len(packages) <= 8
                    or any(type(p) is not str or p not in allowed for p in packages)
                    or len(set(packages)) != len(packages)):
                raise ContractError("dependency operation is outside the reviewed allowlist")
        elif kind == "prepend_parallelism":
            if set(op) != {"kind", "step", "variable", "count"}:
                raise ContractError("parallelism operation has unexpected fields")
            if type(op["variable"]) is not str or op["variable"] not in VARIABLES:
                raise ContractError("parallelism variable is not approved")
            integer(op["count"], 1, 4)
        elif kind == "curl_retry":
            if set(op) != {"kind", "step", "line", "retries", "delay", "seconds"}:
                raise ContractError("retry operation has unexpected fields")
            integer(op["line"], 0, 4095)
            integer(op["retries"], 1, 5)
            integer(op["delay"], 1, 10)
            if type(op["seconds"]) is not int or op["seconds"] not in {30, 60, 90, 120}:
                raise ContractError("retry operation exceeds the time budget")
        else:
            raise ContractError("unsupported repair operation")
    if len({json.dumps(op, sort_keys=True, separators=(",", ":")) for op in operations}) != len(operations):
        raise ContractError("repair operations are duplicated")
    return operations


def compile_proposal(context, operations):
    """Compile fixed enums/integers; never accept a model-authored shell string."""
    validate_operations(operations)
    source = context["source_text"]
    if "\r" in source:
        raise ContractError("non-LF source requires manual repair")
    tree = yaml.compose(source, Loader=_UniqueSafeLoader)

    def field(node, key):
        if not isinstance(node, yaml.MappingNode):
            raise ContractError("repair workflow mapping is invalid")
        matches = [v for k, v in node.value if k.value == key]
        if len(matches) != 1:
            raise ContractError("repair workflow field is ambiguous")
        return matches[0]

    jobs = field(tree, "jobs")
    if not isinstance(jobs, yaml.MappingNode) or len(jobs.value) != 1:
        raise ContractError("repair requires one package job")
    steps = field(jobs.value[0][1], "steps")
    if not isinstance(steps, yaml.SequenceNode):
        raise ContractError("repair steps are invalid")
    grouped = {}
    for operation in operations:
        grouped.setdefault(operation["step"], []).append(operation)
    edits = []
    for index, items in sorted(grouped.items()):
        if index >= len(steps.value):
            raise ContractError("repair step is outside the source")
        scalar = field(steps.value[index], "run")
        if not isinstance(scalar, yaml.ScalarNode) or scalar.style != "|":
            raise ContractError("only literal block scripts support automatic operations")
        original = source[scalar.start_mark.index:scalar.end_mark.index]
        lines = original.splitlines(keepends=True)
        if not lines or not re.fullmatch(r"\|[-+]?[ \t]*\n", lines[0]):
            raise ContractError("ambiguous script header requires manual repair")
        nonempty = [line for line in lines[1:] if line.strip()]
        if not nonempty:
            raise ContractError("repair script is empty")
        indent = min(len(line) - len(line.lstrip(" ")) for line in nonempty)
        if indent == 0:
            raise ContractError("repair script indentation is invalid")
        prefixes = []
        changed_lines = set()
        logical = scalar.value.splitlines()
        for op in items:
            if op["kind"] == "prepend_apt":
                prefixes.append("sudo apt-get install -y " + " ".join(sorted(op["packages"])))
            elif op["kind"] == "prepend_pip":
                prefixes.append("python3 -m pip install " + " ".join(sorted(op["packages"])))
            elif op["kind"] == "prepend_parallelism":
                value = f'"-j{op["count"]}"' if op["variable"] == "MAKEFLAGS" else str(op["count"])
                prefixes.append(f'export {op["variable"]}={value}')
            else:
                number = op["line"]
                if number in changed_lines or number >= len(logical) or number + 1 >= len(lines):
                    raise ContractError("retry line is ambiguous or outside the source")
                changed_lines.add(number)
                raw = lines[number + 1]
                if (not raw.endswith("\n") or raw[indent:].rstrip("\n") != logical[number]
                        or not logical[number].lstrip().startswith("curl ")):
                    raise ContractError("retry line does not identify a standalone curl command")
                lines[number + 1] = raw[:-1] + (
                    f' --retry {op["retries"]} --retry-delay {op["delay"]}'
                    f' --retry-max-time {op["seconds"]}\n'
                )
        replacement = lines[0] + "".join(" " * indent + line + "\n" for line in prefixes) + "".join(lines[1:])
        if source.count(original) != 1 or original == replacement:
            raise ContractError("repair script anchor is not unique or unchanged")
        edits.append({"path": context["workflow_path"], "old": original, "new": replacement})
    proposal = {"diagnosis": "Bounded prerequisite, resource, or download repair for unchanged tests.",
                "edits": edits, "unresolved_reason": ""}
    admit(context, proposal)
    return proposal


def validate_event(event, environment):
    if not isinstance(event, dict) or event.get("action") != EVENT:
        raise ContractError("unexpected repair callback event")
    expected = {
        "GITHUB_EVENT_NAME": "repository_dispatch", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main", "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW}@refs/heads/main",
        "SMOKE_REPAIR_ENABLED": "true",
    }
    if any(environment.get(key) != value for key, value in expected.items()):
        raise ContractError("repair callback is not enabled on trusted main")
    sha = validate_sha(environment.get("GITHUB_SHA"))
    if environment.get("GITHUB_WORKFLOW_SHA") != sha:
        raise ContractError("repair workflow source differs from main")
    login = environment.get("SMOKE_REPAIR_BRIDGE_BOT_LOGIN", "")
    ident = environment.get("SMOKE_REPAIR_BRIDGE_BOT_ID", "")
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,98}\[bot\]", login)
            or not re.fullmatch(r"[1-9][0-9]{0,18}", ident)):
        raise ContractError("repair bridge identity is not configured")
    sender = event.get("sender")
    if (type(sender) is not dict or sender.get("type") != "Bot"
            or sender.get("login") != login or type(sender.get("id")) is not int
            or sender["id"] != int(ident) or environment.get("GITHUB_ACTOR") != login
            or environment.get("GITHUB_ACTOR_ID") != ident):
        raise ContractError("repair callback sender is not the configured App")
    repo = event.get("repository")
    if (type(repo) is not dict or repo.get("full_name") != REPOSITORY
            or repo.get("private") is not False or repo.get("default_branch") != "main"
            or str(positive(repo.get("id"), "repository ID")) != environment.get("GITHUB_REPOSITORY_ID")):
        raise ContractError("repair callback repository is invalid")
    payload = event.get("client_payload")
    if type(payload) is not dict or set(payload) != PAYLOAD_KEYS:
        raise ContractError("repair callback fields are invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ContractError("repair callback schema is unsupported")
    if payload["repository"] != REPOSITORY or payload["base_sha"] != sha:
        raise ContractError("repair callback is stale or from another repository")
    for key in ("orchestrator_run_id", "orchestrator_attempt", "context_artifact_id"):
        integer(payload[key], 1, 10**19 - 1)
    if not isinstance(payload["package_slug"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", payload["package_slug"]):
        raise ContractError("repair callback package is invalid")
    if not isinstance(payload["context_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["context_sha256"]):
        raise ContractError("repair context digest is invalid")
    validate_operations(payload["operations"])
    return payload


def artifact_inventory(api, run_id):
    pages = api.api(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100", pages=True)
    if type(pages) is not list or not pages or any(type(p) is not dict or type(p.get("artifacts")) is not list for p in pages):
        raise ContractError("repair artifact inventory is invalid")
    items = [item for page in pages for item in page["artifacts"]]
    if len(items) > 512 or any(type(p.get("total_count")) is not int or p["total_count"] != len(items) for p in pages):
        raise ContractError("repair artifact inventory is incomplete")
    ids = [positive(item.get("id"), "artifact ID") for item in items if type(item) is dict]
    if len(ids) != len(items) or len(ids) != len(set(ids)):
        raise ContractError("repair artifacts contain ambiguous identities")
    return items


def context_archive(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ARCHIVE:
        raise ContractError("repair context archive is oversized")
    _prevalidate_zip_directory(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ContractError("repair context archive must contain one file")
            entry = entries[0]
            if (entry.filename != "contexts.json" or entry.is_dir() or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16) or not 0 < entry.file_size <= MAX_ARCHIVE):
                raise ContractError("repair context archive has an unsafe entry")
            with archive.open(entry) as stream:
                data = stream.read(MAX_ARCHIVE + 1)
            if len(data) != entry.file_size:
                raise ContractError("repair context archive size is invalid")
            return decode_json(data)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ContractError("repair context archive is invalid") from exc


def assert_current_failure(read, context, *, now=None):
    """A newer run, even at the same SHA, invalidates an older repair request."""
    now = time.time() if now is None else now
    run_id = positive(context["orchestrator_run_id"], "failure run ID")
    attempt = positive(context["orchestrator_run_attempt"], "failure attempt")
    sha = validate_sha(context["base_sha"])
    if context.get("repository") != REPOSITORY:
        raise ContractError("repair failure repository is invalid")
    run = read(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    expected = {"id": run_id, "run_attempt": attempt, "head_sha": sha,
                "head_branch": "main", "path": ".github/workflows/test-all-packages-orchestrator.yml",
                "status": "completed", "conclusion": "failure"}
    if type(run) is not dict or any(run.get(key) != val for key, val in expected.items()):
        raise ContractError("repair failure is no longer current and failed")
    for field in ("id", "run_attempt", "run_number"):
        positive(run.get(field), field)
    if (run.get("event") not in {"push", "schedule", "workflow_dispatch"}
            or any(type(run.get(key)) is not dict or run[key].get("full_name") != REPOSITORY
                   for key in ("repository", "head_repository"))
            or not 0 <= now - timestamp(run.get("created_at")).timestamp() <= MAX_AGE):
        raise ContractError("repair failure provenance or freshness is invalid")
    query = urlencode({"branch": "main", "head_sha": sha, "per_page": 100})
    identity = {key: run[key] for key in (*expected, "run_number", "event", "created_at",
                                         "repository", "head_repository")}
    found = set()
    expected_count = None
    for page in range(1, 11):
        rows = read(f"repos/{REPOSITORY}/actions/workflows/test-all-packages-orchestrator.yml/runs?{query}&page={page}")
        if (type(rows) is not dict or type(rows.get("total_count")) is not int
                or not 1 <= rows["total_count"] < 1000 or type(rows.get("workflow_runs")) is not list
                or len(rows["workflow_runs"]) > 100):
            raise ContractError("repair supersession inventory is incomplete")
        if expected_count is not None and rows["total_count"] != expected_count:
            raise ContractError("repair supersession inventory changed")
        expected_count = rows["total_count"]
        for item in rows["workflow_runs"]:
            if type(item) is not dict:
                raise ContractError("repair supersession run is malformed")
            ident = positive(item.get("id"), "supersession run ID")
            number = positive(item.get("run_number"), "supersession run number")
            if (ident in found or item.get("head_sha") != sha or item.get("head_branch") != "main"
                    or item.get("path") != expected["path"]
                    or number > run["run_number"] or (number == run["run_number"] and ident != run_id)):
                raise ContractError("repair failure has been superseded or inventory is ambiguous")
            if ident == run_id:
                positive(item.get("run_attempt"), "supersession attempt")
                if any(item.get(key) != value for key, value in identity.items()):
                    raise ContractError("repair failure changed during supersession validation")
            found.add(ident)
        if len(found) == expected_count:
            if run_id not in found:
                raise ContractError("repair failure is absent from complete inventory")
            fresh = read(f"repos/{REPOSITORY}/actions/runs/{run_id}")
            if type(fresh) is not dict or any(fresh.get(key) != value for key, value in identity.items()):
                raise ContractError("repair failure changed after supersession validation")
            positive(fresh.get("run_attempt"), "latest failure attempt")
            return
        if len(found) > expected_count or len(rows["workflow_runs"]) != 100:
            raise ContractError("repair supersession inventory is incomplete")
    raise ContractError("repair supersession inventory exceeds the read budget")


def authenticate_context(payload, api, root, *, now):
    run_id, attempt = payload["orchestrator_run_id"], payload["orchestrator_attempt"]
    sha, slug = payload["base_sha"], payload["package_slug"]
    parent_job = authenticate_parent(api, REPOSITORY, sha, run_id, attempt)
    run = api.api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if (run.get("run_attempt") != attempt or run.get("status") != "completed"
            or run.get("conclusion") != "failure" or not 0 <= now - timestamp(run.get("created_at")).timestamp() <= MAX_AGE):
        raise ContractError("repair failure is stale, superseded, or incomplete")
    jobs = complete_jobs(api.api(f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", pages=True))
    prepare = [job for job in jobs if job.get("name") in PREPARE_JOBS]
    if (len(prepare) != 1 or any(type(prepare[0].get(key)) is not int for key in ("run_id", "run_attempt"))
            or any(prepare[0].get(key) != val for key, val in {
        "run_id": run_id, "run_attempt": attempt, "head_sha": sha, "status": "completed", "conclusion": "success",
    }.items())):
        raise ContractError("repair context producer was not successful on this exact run")
    items = artifact_inventory(api, run_id)
    name = f"smoke-repair-context-{run_id}-{attempt}"
    contexts = [item for item in items if item.get("name") == name]
    if len(contexts) != 1 or contexts[0]["id"] != payload["context_artifact_id"]:
        raise ContractError("repair context artifact is not uniquely registered")
    metadata = contexts[0]
    origin = metadata.get("workflow_run")
    size = positive(metadata.get("size_in_bytes"), "artifact size")
    if (metadata.get("expired") is not False or size > MAX_ARCHIVE or type(origin) is not dict
            or type(origin.get("id")) is not int
            or any(origin.get(key) != val for key, val in {"id": run_id, "head_sha": sha, "head_branch": "main"}.items())
            or not timestamp(prepare[0]["started_at"]) <= timestamp(metadata.get("created_at")) <= timestamp(prepare[0]["completed_at"])):
        raise ContractError("repair context artifact provenance is invalid")
    raw = api.api(f"repos/{REPOSITORY}/actions/artifacts/{metadata['id']}/zip", raw=True)
    if len(raw) != size or metadata.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ContractError("repair context artifact digest differs")
    context = select_context(context_archive(raw), slug, REPOSITORY, sha, root)
    if context_digest(context) != payload["context_sha256"]:
        raise ContractError("repair proposal is bound to another context")
    assert_current_failure(api.api, context, now=now)
    audit_matches = [item for item in items if item.get("name") == f"smoke-orchestration-evidence-{run_id}-{attempt}"]
    if len(audit_matches) != 1:
        raise ContractError("repair original evidence artifact is ambiguous")
    audit = download_audit(api, REPOSITORY, sha, run_id, attempt, audit_matches[0]["id"], parent_job)
    verified = contexts_from_audit(audit, api=api, repository=REPOSITORY, sha=sha, run_id=run_id, attempt=attempt, root=root)
    matching = [item for item in verified if item["package_slug"] == slug]
    if len(matching) != 1 or {k: v for k, v in matching[0].items() if k != "log_excerpt"} != {
        k: v for k, v in context.items() if k != "log_excerpt"
    }:
        raise ContractError("repair context no longer matches verified persistent failures")
    branch = f"automation/smoke-repair/{run_id}-{attempt}-{slug}"
    refs = api.api(f"repos/{REPOSITORY}/git/matching-refs/heads/{branch}")
    pulls = api.api(f"repos/{REPOSITORY}/pulls?state=all&head=ArmDeveloperEcosystem:{branch}&per_page=100")
    if (type(refs) is not list or any(type(ref) is not dict or type(ref.get("ref")) is not str for ref in refs)
            or type(pulls) is not list or any(ref["ref"] == f"refs/heads/{branch}" for ref in refs) or pulls):
        raise ContractError("repair incident was already staged or published")
    validate_current_ref(api.api(f"repos/{REPOSITORY}/git/ref/heads/main"), expected_sha=sha, branch="main")
    return context


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = validate_event(read_json(args.event, maximum=128 * 1024), os.environ)
        validate_checkout_binding(Path.cwd(), payload["base_sha"])
        context = authenticate_context(payload, GitHub(time.monotonic() + 300), Path.cwd(), now=time.time())
        proposal = compile_proposal(context, payload["operations"])
        output = args.output_directory.resolve(strict=True)
        if output.is_relative_to(Path.cwd().resolve()):
            raise ContractError("repair admission output must be outside the checkout")
        write_json(output / "context.json", context)
        write_json(output / "proposal.json", proposal)
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(f"base_sha={payload['base_sha']}\npackage_slug={payload['package_slug']}\n")
        print("Authenticated bounded repair proposal; package validation and human review remain required.")
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError, yaml.YAMLError):
        print("Repair callback rejected; no candidate or successful repair is inferred.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
