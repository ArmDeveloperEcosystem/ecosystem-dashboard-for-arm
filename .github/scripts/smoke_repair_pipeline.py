"""Glue for isolated repair proposal, admission, and owner reporting jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestration_contract import ContractError, validate_repository, validate_sha
from exact_run_aggregation import _yaml_mapping, validate_checkout_binding
from smoke_recovery import GitHub
from smoke_repair_evidence import positive, read_json, read_source, write_json

MODEL_FIELDS = {"repository", "base_sha", "orchestration_id", "package_slug", "workflow_path", "source_text", "failed_steps", "log_excerpt"}


def select_context(bundle, slug, repository, sha, root):
    validate_repository(repository)
    validate_sha(sha)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", slug):
        raise ContractError("repair package slug is invalid")
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "contexts"} or type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise ContractError("repair context bundle is invalid")
    if not isinstance(bundle["contexts"], list) or any(not isinstance(item, dict) for item in bundle["contexts"]):
        raise ContractError("repair context inventory is invalid")
    contexts = [item for item in bundle["contexts"] if item.get("package_slug") == slug]
    if len(contexts) != 1:
        raise ContractError("repair package has no unique authenticated context")
    context = contexts[0]
    if context.get("repository") != repository or context.get("base_sha") != sha:
        raise ContractError("repair context repository or base differs from this job")
    validate_checkout_binding(root, sha)
    if read_source(root, sha, context["workflow_path"]) != context["source_text"]:
        raise ContractError("repair source differs from its trusted base")
    from smoke_repair_policy import derive_contract
    from smoke_repair_native import derive_native_contract
    derive_contract(context["source_text"], context["called_job"])
    derive_native_contract(context["source_text"].encode(), repository=repository, base_sha=sha,
        workflow_path=context["workflow_path"], package_slug=slug, called_job=context["called_job"],
        source_digest=hashlib.sha256(context["source_text"].encode()).hexdigest())
    return context


def model_context(context):
    from smoke_repair_policy import policy_description
    output = {key: context[key] for key in MODEL_FIELDS}
    output["validation_feedback"] = (
        "Enforced repair policy (including frozen final gates): " + policy_description()
    )
    return output


def admit(context, proposal):
    from smoke_repair_policy import validate_proposal
    from smoke_repair_native import derive_native_contract
    result = validate_proposal(context, proposal)
    source = result["candidate_source"]
    workflow = _yaml_mapping(source.encode(), "admitted repair workflow")
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                # Syntax-only validation never executes model-proposed commands.
                subprocess.run(["bash", "--noprofile", "--norc", "-n"], input=step["run"].encode(),
                    check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    contract = derive_native_contract(context["source_text"].encode(), repository=context["repository"],
        base_sha=context["base_sha"], workflow_path=context["workflow_path"], package_slug=context["package_slug"],
        source_digest=hashlib.sha256(source.encode()).hexdigest(), called_job=context["called_job"])
    if result["contract"] != {
        "expected_job_name": contract["job_name"],
        "mandatory_step_names": contract["mandatory_steps"],
        "final_gate_step_name": contract["gate_step"],
    }:
        raise ContractError("policy and native test contracts disagree")
    return source, contract


def report(repository, run_id, attempt, slug, recipient, results, api, *, pull_request_url=""):
    validate_repository(repository)
    positive(run_id, "report run ID")
    positive(attempt, "report attempt")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", slug):
        raise ContractError("report package is invalid")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", recipient):
        raise ContractError("report recipient is invalid")
    if not isinstance(results, dict) or set(results) - {"prepare", "propose", "stage", "native", "publish"}:
        raise ContractError("repair job results are invalid")
    if not results or any(value not in {"success", "failure", "cancelled", "skipped"} for value in results.values()):
        raise ContractError("repair job result is not terminal")
    if results.get("publish") == "success" and (
        any(results.get(key) != "success" for key in ("propose", "stage", "native"))
        or results.get("prepare", "success") != "success"
    ):
        raise ContractError("successful publication contradicts its required repair stages")
    if pull_request_url and (results.get("publish") != "success" or not re.fullmatch(
        rf"https://github\.com/{re.escape(repository)}/pull/[1-9][0-9]*", pull_request_url
    )):
        raise ContractError("repair PR link is not a successful publisher output for this repository")
    title = f"Arm64 smoke repair {run_id}, attempt {attempt}: {slug}"
    url = f"https://github.com/{repository}/actions/runs/{run_id}"
    lines = [f"@{recipient}", "", f"[Repair workflow and evidence]({url})", ""]
    lines += [f"- {key}: `{value}`" for key, value in results.items()]
    if results.get("publish") == "success":
        lines += ["", "The repair publisher completed. Review its linked draft PR and required checks.",
            "This does not make the original main run green. A human must review and merge the fix; the new main must pass its own full orchestrator cycle."]
        if pull_request_url:
            lines += ["", f"[Verified repair draft]({pull_request_url})"]
    else:
        lines += ["", "No successfully published repair is claimed. Check the failed or skipped stage for unsupported changes, unavailable configuration, stale main, or validation failure. Human investigation remains necessary."]
    lines += ["", "No automatic approval, merge, production write, or weakening of a failed result is authorized."]
    body = "\n".join(lines) + "\n"
    query = urlencode({"q": f'repo:{repository} is:issue author:app/github-actions "{title}" in:title'})
    found = api.api(f"search/issues?{query}")
    if not isinstance(found, dict) or found.get("incomplete_results") is not False or not isinstance(found.get("items"), list) or type(found.get("total_count")) is not int or found["total_count"] != len(found["items"]):
        raise ContractError("repair report lookup is incomplete")
    if any(not isinstance(item, dict) or not isinstance(item.get("user"), dict)
           or not isinstance(item["user"].get("login"), str) or not isinstance(item.get("title"), str)
           for item in found["items"]):
        raise ContractError("repair report lookup contains malformed issue metadata")
    matches = [item for item in found["items"] if isinstance(item, dict) and item.get("title") == title and item.get("user", {}).get("login") == "github-actions[bot]"]
    if len(matches) > 1:
        raise ContractError("repair report identity is ambiguous")
    if not matches:
        api.api(f"repos/{repository}/issues", payload={"title": title, "body": body})
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    for flag in ("bundle", "output", "model-output"):
        select.add_argument(f"--{flag}", required=True, type=Path)
    for flag in ("slug", "repository", "base-sha"):
        select.add_argument(f"--{flag}", required=True)
    preflight = commands.add_parser("admit")
    for flag in ("context", "proposal", "source-output", "contract-output"):
        preflight.add_argument(f"--{flag}", required=True, type=Path)
    notify = commands.add_parser("report")
    for flag in ("repository", "slug", "recipient"):
        notify.add_argument(f"--{flag}", required=True)
    for flag in ("run-id", "attempt"):
        notify.add_argument(f"--{flag}", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            context = select_context(read_json(args.bundle), args.slug, args.repository, args.base_sha, Path.cwd())
            write_json(args.output, context)
            write_json(args.model_output, model_context(context))
        elif args.command == "admit":
            source, contract = admit(read_json(args.context), read_json(args.proposal))
            descriptor = os.open(args.source_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(source)
            write_json(args.contract_output, contract)
        else:
            from orchestration_contract import decode_json
            report(args.repository, args.run_id, args.attempt, args.slug, args.recipient,
                decode_json(os.environ.get("SMOKE_REPAIR_JOB_RESULTS", "")), GitHub(time.monotonic() + 120),
                pull_request_url=os.environ.get("SMOKE_REPAIR_PR_URL", ""))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Smoke repair pipeline stopped: {type(exc).__name__}; no successful repair inferred.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
