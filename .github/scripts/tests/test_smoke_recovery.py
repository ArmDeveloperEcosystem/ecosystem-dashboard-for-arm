from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import yaml

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import exact_run_aggregation as exact  # noqa: E402
import orchestration_contract as contract  # noqa: E402
import smoke_recovery as recovery  # noqa: E402


REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
SHA = "a" * 40
OTHER_SHA = "b" * 40
EPOCH = 2_000_000_000
BRANCH = "main"
ORCHESTRATION = "orchestration-123456-1"
CREATED = "2026-09-11T12:00:00Z"
STARTED = "2026-09-11T12:01:00Z"
STEP_START = "2026-09-11T12:01:10Z"
STEP_END = "2026-09-11T12:01:20Z"
COMPLETED = "2026-09-11T12:03:00Z"
UPDATED = "2026-09-11T12:04:00Z"
DOWNLOAD = "https://downloads.example.org/package.tar.gz"
CURL_COMMAND = f"curl --fail --location {DOWNLOAD}"
DNS_ERROR = "curl: (6) Could not resolve host: downloads.example.org"
HTTP_ERROR = "curl: (22) The requested URL returned error: 503"
CONTRACT_ERRORS = (contract.ContractError, exact.ContractError)
REAL_RECOVERY = recovery.Recovery


def branch_ref(sha=SHA, branch=BRANCH):
    return {"ref": f"refs/heads/{branch}", "object": {"sha": sha, "type": "commit"}}


def initial_manifest():
    return contract.build_manifest(
        orchestration_id=ORCHESTRATION,
        expected_sha=SHA,
        branch=BRANCH,
        records=[
            {
                "batch": batch,
                "workflow": contract.expected_workflow(batch),
                "artifact": contract.expected_artifact(batch),
                "dispatch_nonce": f"{batch:064x}",
                "run_id": 10000 + batch,
                "run_attempt": 1,
            }
            for batch in range(1, contract.BATCH_COUNT + 1)
        ],
    )


def definition(batch):
    slug = f"package-{batch}"
    return exact.BatchDefinition(
        batch=batch,
        workflow_path=contract.expected_workflow_path(batch),
        workflow_name=contract.expected_workflow_name(batch),
        artifact_name=contract.expected_artifact(batch),
        packages=(exact.PackageRegistration(
            job=f"test-{slug}", called_job="test",
            workflow_path=f".github/workflows/test-{slug}.yml", package_slug=slug,
        ),),
        external_actions=(),
        local_actions=(),
    )


def run_payload(record, conclusion="success"):
    return {
        "id": record["run_id"],
        "run_attempt": 1,
        "name": contract.expected_workflow_name(record["batch"]),
        "path": contract.expected_workflow_path(record["batch"]),
        "display_title": contract.expected_run_name(
            record["batch"], ORCHESTRATION, record["dispatch_nonce"],
        ),
        "event": "workflow_dispatch",
        "head_branch": BRANCH,
        "head_sha": SHA,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "status": "completed",
        "conclusion": conclusion,
        "created_at": CREATED,
        "updated_at": UPDATED,
    }


def job_payload(record, *, summary=False, conclusion="success"):
    job_id = record["run_id"] * 10 + int(summary)
    return {
        "id": job_id,
        "run_id": record["run_id"],
        "run_attempt": 1,
        "head_sha": SHA,
        "name": "summary" if summary else exact.expected_job_name(definition(record["batch"]).packages[0]),
        "status": "completed",
        "conclusion": conclusion,
        "started_at": STARTED,
        "completed_at": COMPLETED,
        "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{record['run_id']}/job/{job_id}",
        "steps": [{
            "number": 1,
            "name": "Download and install package",
            "status": "completed",
            "conclusion": conclusion,
            "started_at": STEP_START,
            "completed_at": STEP_END,
        }],
    }


def log_bytes(*messages, command=None, exit_code=None):
    command = command or CURL_COMMAND
    if exit_code is None:
        terminal = re.match(r"curl: \((6|22)\) ", messages[-1]) if messages else None
        exit_code = int(terminal[1]) if terminal else 1
    lines = [f"##[group]Run {command}", command, "##[endgroup]"]
    lines.extend(messages)
    lines.append(f"##[error]Process completed with exit code {exit_code}.")
    return "".join(f"2026-09-11T12:01:15.{index:03d}Z {line}\n" for index, line in enumerate(lines)).encode()


class FakeClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if seconds <= 0:
            raise AssertionError("polling must have a positive backoff")
        self.sleeps.append(seconds)
        self.now += seconds
        if len(self.sleeps) > 250:
            raise AssertionError("unbounded recovery polling")


class RecoveryFixture:
    """All 22 records, but only one synthetic package per batch; no real Git/API."""

    def __init__(self):
        self.manifest = initial_manifest()
        self.definitions = tuple(definition(batch) for batch in range(1, 23))
        self.clock = FakeClock()
        self.runs, self.pages, self.logs = {}, {}, {}
        self.calls, self.posts, self.dispatched_records = [], [], []
        self.ref_count = self.registration_count = 0
        self.outcomes = {}
        self.ref_hook = self.run_hook = self.registration_hook = self.dispatch_hook = None
        self.ambiguous = False
        self.visible_after = 0
        self.never_register = False
        for record in self.manifest["batches"]:
            self.add_run(record)

    def add_run(self, record, outcome="success"):
        run_id = record["run_id"]
        conclusion = "success" if outcome == "success" else "failure"
        self.runs[run_id] = run_payload(record, conclusion)
        package = job_payload(record, conclusion=conclusion)
        self.pages[run_id] = [{"total_count": 2, "jobs": [package, job_payload(record, summary=True)]}]
        if outcome != "success":
            self.logs[package["id"]] = log_bytes(DNS_ERROR) if outcome == "transient" else log_bytes("fatal error: missing header")

    def fail(self, batch=1, outcome="transient"):
        self.add_run(self.manifest["batches"][batch - 1], outcome)

    def api(self, endpoint, *, payload=None, pages=False, raw=False):
        self.calls.append((endpoint, deepcopy(payload), pages, raw))
        prefix = f"repos/{REPOSITORY}/"
        if not endpoint.startswith(prefix):
            raise AssertionError(f"untrusted API endpoint: {endpoint}")
        path = endpoint[len(prefix):]
        if path == f"git/ref/heads/{BRANCH}":
            self.ref_count += 1
            if self.ref_hook:
                return deepcopy(self.ref_hook(self))
            return branch_ref()
        match = re.fullmatch(r"actions/workflows/test-all-packages-batch(\d+)\.yml/dispatches", path)
        if match:
            if payload is None or pages or raw:
                raise AssertionError("incorrect dispatch API flags")
            batch = int(match[1])
            self.posts.append((batch, deepcopy(payload)))
            nonce = payload["inputs"]["dispatch_nonce"]
            record = dict(self.manifest["batches"][batch - 1], run_id=20000 + len(self.posts), dispatch_nonce=nonce)
            choices = self.outcomes.get(batch, ["success"])
            prior = sum(item["batch"] == batch for item in self.dispatched_records)
            outcome = choices[min(prior, len(choices) - 1)]
            self.dispatched_records.append(record)
            self.add_run(record, outcome)
            if self.dispatch_hook:
                self.dispatch_hook(self, record)
            if self.ambiguous:
                raise contract.ContractError("ambiguous POST response")
            return None
        match = re.fullmatch(r"actions/workflows/test-all-packages-batch(\d+)\.yml/runs\?(.+)", path)
        if match:
            if not pages or raw or payload is not None:
                raise AssertionError("registration must retrieve every page")
            query = parse_qs(urlsplit(endpoint).query)
            if query != {"branch": [BRANCH], "head_sha": [SHA], "event": ["workflow_dispatch"], "per_page": ["100"]}:
                raise AssertionError(f"unbound registration query: {query}")
            self.registration_count += 1
            selected = [deepcopy(self.runs[item["run_id"]]) for item in self.dispatched_records if item["batch"] == int(match[1])]
            if self.never_register or self.registration_count <= self.visible_after:
                selected = []
            result = [{"total_count": len(selected), "workflow_runs": selected}]
            return self.registration_hook(result) if self.registration_hook else result
        match = re.fullmatch(r"actions/runs/(\d+)/attempts/1/jobs\?per_page=100", path)
        if match:
            if not pages or raw or payload is not None:
                raise AssertionError("jobs must use fully paginated attempt-1 endpoint")
            return deepcopy(self.pages[int(match[1])])
        match = re.fullmatch(r"actions/runs/(\d+)", path)
        if match:
            result = deepcopy(self.runs[int(match[1])])
            return self.run_hook(result) if self.run_hook else result
        match = re.fullmatch(r"actions/jobs/(\d+)/logs", path)
        if match:
            if not raw or pages or payload is not None:
                raise AssertionError("job log must be read as bytes from its validated ID")
            result = self.logs[int(match[1])]
            if isinstance(result, Exception):
                raise result
            return result
        raise AssertionError(f"unexpected API request: {endpoint}")


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.job = job_payload(initial_manifest()["batches"][0], conclusion="failure")

    def classify(self, raw, *, command=CURL_COMMAND):
        return recovery.classify_retryable_failure(raw, self.job, command=command)

    def test_terminal_remote_dns_failure(self):
        self.assertEqual(self.classify(log_bytes(DNS_ERROR)), "transient_download")

    def test_curl22_only_429_502_503_504(self):
        for code in (200, 400, 401, 403, 404, 408, 429, 500, 501, 502, 503, 504, 505):
            with self.subTest(code=code):
                expected = "transient_download" if code in {429, 502, 503, 504} else "unknown_failure"
                self.assertEqual(self.classify(log_bytes(f"curl: (22) The requested URL returned error: {code}")), expected)

    def test_network_noise_does_not_excuse_terminal_compiler_or_assertion_error(self):
        for terminal in ("fatal error: missing.h", "AssertionError: bad output", "undefined reference to main", "make: *** [all] Error 2", "error: build failed"):
            with self.subTest(terminal=terminal):
                self.assertEqual(self.classify(log_bytes(DNS_ERROR, "download recovered", terminal)), "unknown_failure")

    def test_hard_failures_before_terminal_network_message_are_not_retryable(self):
        for message in ("Permission denied", "certificate expired", "checksum mismatch", "hash mismatch", "signature verification failed", "No space left on device", "Out of memory", "Segmentation fault", "AssertionError: failed", "fatal error: compile failed"):
            with self.subTest(message=message):
                self.assertEqual(self.classify(log_bytes(message, HTTP_ERROR)), "unknown_failure")

    def test_generic_timeouts_and_unknown_errors_fail_closed(self):
        for message in ("curl: (28) Operation timed out after 3000 milliseconds", "The operation was canceled.", "Connection reset by peer", "command not found", "Process completed with exit code 1", "runner lost", "HTTP/1.1 503 Service Unavailable", "next_install_failed"):
            with self.subTest(message=message):
                self.assertEqual(self.classify(log_bytes(message)), "unknown_failure")

    def test_localservice_dns_and_address_failures_are_unknown(self):
        for host in ("localhost", "db", "127.0.0.1", "169.254.169.254", "service.local", "db.localhost", "api.internal", "::1"):
            with self.subTest(host=host):
                self.assertEqual(self.classify(log_bytes(f"curl: (6) Could not resolve host: {host}")), "unknown_failure")

    def test_local_service_http503_is_not_a_remote_download_failure(self):
        for host in ("localhost:8080", "127.0.0.1:8080", "[::1]:8080", "169.254.169.254"):
            with self.subTest(host=host):
                command = f"curl --fail http://{host}/health"
                self.assertEqual(self.classify(log_bytes(HTTP_ERROR, command=command)), "unknown_failure")

    def test_echoed_command_text_is_not_an_observed_error(self):
        raw = log_bytes("build unexpectedly exited", command=f"echo '{DNS_ERROR}'")
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_printf_output_cannot_impersonate_a_real_download_failure(self):
        raw = log_bytes(DNS_ERROR, command=f"printf '%s\\n' '{DNS_ERROR}'; exit 1")
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_succeeded_step_network_history_is_not_failed_step_evidence(self):
        raw = log_bytes(DNS_ERROR).replace(b"12:01:15.", b"12:00:15.")
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_later_step_network_error_is_not_failed_step_evidence(self):
        raw = log_bytes(DNS_ERROR).replace(b"12:01:15.", b"12:02:15.")
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_only_one_actual_failed_download_step_is_classifiable(self):
        for mutation in ("none", "multiple", "wrong_name", "incomplete", "reversed"):
            with self.subTest(mutation=mutation):
                job = deepcopy(self.job)
                if mutation == "none":
                    job["steps"][0]["conclusion"] = "success"
                elif mutation == "multiple":
                    job["steps"].append(deepcopy(job["steps"][0]))
                elif mutation == "wrong_name":
                    job["steps"][0]["name"] = "Compile package"
                elif mutation == "incomplete":
                    job["steps"][0].pop("completed_at")
                else:
                    job["steps"][0]["started_at"] = UPDATED
                self.assertEqual(recovery.classify_retryable_failure(log_bytes(DNS_ERROR), job, command=CURL_COMMAND), "unknown_failure")

    def test_malformed_non_utf8_and_oversized_logs_fail_closed(self):
        for raw in (None, "not bytes", b"", b"\xff", b"untimestamped " + DNS_ERROR.encode(), b"2026-09-11T12:01:15+00:00 " + DNS_ERROR.encode(), b"x" * (recovery.MAX_LOG_BYTES + 1)):
            with self.subTest(kind=type(raw).__name__, length=len(raw) if raw is not None else 0):
                self.assertEqual(self.classify(raw), "unknown_failure")

    def test_truncated_terminal_log_cannot_authorize_a_retry(self):
        raw = b"\n".join(log_bytes(DNS_ERROR).splitlines()[:-1]) + b"\n"
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_curl22_without_observed_public_download_url_is_unknown(self):
        self.assertEqual(self.classify(log_bytes(HTTP_ERROR, command="./install-package")), "unknown_failure")

    def test_private_or_internal_urls_override_remote_url_evidence(self):
        for host in ("10.0.0.1", "192.168.1.1", "172.16.0.1", "service.internal", "service.local", "db.localhost"):
            with self.subTest(host=host):
                self.assertEqual(self.classify(log_bytes(f"GET http://{host}/health", DNS_ERROR)), "unknown_failure")

    def test_malformed_step_metadata_is_unknown_not_an_unhandled_exception(self):
        for steps in (None, "not steps", [None], [{"conclusion": "failure", "name": None}], [{"conclusion": "failure", "name": "Download", "started_at": 123, "completed_at": STEP_END}]):
            with self.subTest(steps=steps):
                job = dict(self.job, steps=steps)
                self.assertEqual(recovery.classify_retryable_failure(log_bytes(DNS_ERROR), job, command=CURL_COMMAND), "unknown_failure")

    def test_ansi_color_does_not_hide_hard_failure(self):
        self.assertEqual(self.classify(log_bytes("\x1b[31mfatal error:\x1b[0m compilation failed", HTTP_ERROR)), "unknown_failure")

    def test_missing_or_wrong_typed_command_proof_is_not_inferred_from_logs(self):
        raw = log_bytes(DNS_ERROR)
        self.assertEqual(recovery.classify_retryable_failure(raw, self.job), "unknown_failure")
        for command in (None, "", {}, [CURL_COMMAND], CURL_COMMAND.encode()):
            with self.subTest(command=command):
                self.assertEqual(self.classify(raw, command=command), "unknown_failure")

    def test_command_must_be_one_read_only_curl_https_operation(self):
        commands = (
            f"{CURL_COMMAND}; ./configure", f"{CURL_COMMAND} && make", f"{CURL_COMMAND} || true",
            f"{CURL_COMMAND}\nprintf done", f"{CURL_COMMAND} | sh", f"{CURL_COMMAND} &",
            f"bash -c '{CURL_COMMAND}'", f"sudo {CURL_COMMAND}",
            "curl --fail $PACKAGE_URL", "curl --fail ${PACKAGE_URL}",
            "curl --fail $(cat url)", "curl --fail `cat url`", "./download-package.sh",
            f"printf '%s\\n' '{DOWNLOAD}' '{DNS_ERROR}'", f"echo '{HTTP_ERROR}'",
            "curl --fail http://downloads.example.org/package.tar.gz",
            f"curl --insecure {DOWNLOAD}", f"curl --upload-file secret {DOWNLOAD}",
            f"curl --request POST {DOWNLOAD}", f"curl --data secret {DOWNLOAD}",
            f"curl --config injected.cfg {DOWNLOAD}", f"curl {DOWNLOAD} {DOWNLOAD}",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.classify(log_bytes(DNS_ERROR, command=command), command=command), "unknown_failure")

    def test_log_command_must_match_authenticated_operation(self):
        for command in (f"curl --fail https://other.example.org/pkg", f"printf '%s\\n' '{DOWNLOAD}' '{DNS_ERROR}'", f"{CURL_COMMAND}; ./configure"):
            with self.subTest(command=command):
                self.assertEqual(self.classify(log_bytes(DNS_ERROR, command=command)), "unknown_failure")

    def test_dns_host_must_match_authenticated_download_host(self):
        self.assertEqual(self.classify(log_bytes("curl: (6) Could not resolve host: unrelated.example.org")), "unknown_failure")

    def test_output_filename_url_cannot_supply_a_trusted_dns_host(self):
        for executable in ("curl", "/usr/bin/curl"):
            for option in ("--output", "-o"):
                with self.subTest(executable=executable, option=option):
                    command = f"{executable} --fail {option} https://other.example.org/out {DOWNLOAD}"
                    raw = log_bytes("curl: (6) Could not resolve host: other.example.org", command=command)
                    self.assertEqual(self.classify(raw, command=command), "unknown_failure")

    def test_optional_utf8_bom_preserves_real_terminal_download_error(self):
        for message in (DNS_ERROR, HTTP_ERROR):
            with self.subTest(message=message):
                self.assertEqual(self.classify(b"\xef\xbb\xbf" + log_bytes(message)), "transient_download")

    def test_exit_marker_must_match_terminal_curl_error_code(self):
        for message, correct in ((DNS_ERROR, 6), (HTTP_ERROR, 22)):
            for code in (0, 1, 6, 22, 28, 127):
                if code == correct:
                    continue
                with self.subTest(message=message, code=code):
                    self.assertEqual(self.classify(log_bytes(message, exit_code=code)), "unknown_failure")

    def test_recovered_dns_then_silent_configure_failure_is_not_retryable(self):
        command = f"{CURL_COMMAND}\n./configure"
        raw = log_bytes(DNS_ERROR, command=command, exit_code=1)
        self.assertEqual(self.classify(raw, command=command), "unknown_failure")
        self.assertEqual(self.classify(raw), "unknown_failure")

    def test_printed_remote_url_and_error_do_not_authenticate_an_operation(self):
        command = f"printf '%s\\n' '{DOWNLOAD}' '{DNS_ERROR}'; exit 6"
        raw = log_bytes(DOWNLOAD, DNS_ERROR, command=command, exit_code=6)
        self.assertEqual(self.classify(raw, command=command), "unknown_failure")
        self.assertEqual(self.classify(raw, command=None), "unknown_failure")

    def test_conflicting_or_multiple_exit_markers_are_not_retryable(self):
        for code in (1, 6, 22):
            with self.subTest(code=code):
                raw = log_bytes(DNS_ERROR) + f"2026-09-11T12:01:16.001Z ##[error]Process completed with exit code {code}.\n".encode()
                self.assertEqual(self.classify(raw), "unknown_failure")


class JobInventoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RecoveryFixture()
        self.record = self.fixture.manifest["batches"][0]
        self.run = self.fixture.runs[self.record["run_id"]]
        self.pages = self.fixture.pages[self.record["run_id"]]

    def validate(self, pages=None):
        return recovery.validate_recovery_jobs(
            self.pages if pages is None else pages,
            definition=self.fixture.definitions[0], run=self.run, repository=REPOSITORY,
        )

    def test_complete_inventory_and_successful_collector(self):
        self.assertEqual(self.validate(), [])

    def test_valid_failure_returns_exact_job_not_collector(self):
        self.run["conclusion"] = "failure"
        self.pages[0]["jobs"][0]["conclusion"] = "failure"
        self.assertEqual(self.validate(), [self.pages[0]["jobs"][0]])

    def test_complete_two_page_inventory(self):
        jobs = self.pages[0]["jobs"]
        self.assertEqual(self.validate([{"total_count": 2, "jobs": [job]} for job in jobs]), [])

    def test_incomplete_duplicate_or_changing_pagination_is_rejected(self):
        jobs = self.pages[0]["jobs"]
        cases = [
            [],
            [{"total_count": 3, "jobs": jobs}],
            [{"total_count": 2, "jobs": jobs[:1]}],
            [{"total_count": 2, "jobs": jobs[:1]}, {"total_count": 3, "jobs": jobs[1:]}],
            [{"total_count": 4, "jobs": jobs}, {"total_count": 4, "jobs": jobs}],
            [{"total_count": 2, "jobs": None}],
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(CONTRACT_ERRORS):
                self.validate(pages)

    def test_missing_extra_duplicate_or_failing_collector_is_rejected(self):
        for variant in ("missing", "duplicate", "failed", "extra_job", "shared_id"):
            with self.subTest(variant=variant):
                pages = deepcopy(self.pages)
                jobs = pages[0]["jobs"]
                if variant == "missing":
                    jobs.pop()
                elif variant == "duplicate":
                    jobs.append(deepcopy(jobs[-1]))
                elif variant == "failed":
                    jobs[-1]["conclusion"] = "failure"
                elif variant == "extra_job":
                    jobs.append(dict(jobs[-1], id=99999, name="unexplained failed job", conclusion="failure"))
                else:
                    jobs[-1]["id"] = jobs[0]["id"]
                pages[0]["total_count"] = len(jobs)
                with self.assertRaises(CONTRACT_ERRORS):
                    self.validate(pages)

    def test_package_and_collector_provenance_states_and_timestamps(self):
        changes = {
            "id": (True, 0, -1, "100001"),
            "run_id": (99999, True),
            "run_attempt": (2, 0, True),
            "head_sha": (OTHER_SHA, None),
            "status": ("in_progress", "queued"),
            "conclusion": ("cancelled", "skipped", "timed_out", None),
            "html_url": ("https://evil.example/jobs/100001", f"https://github.com/other/repo/actions/runs/{self.run['id']}/job/100001"),
            "started_at": ("2026-09-10T12:00:00Z", UPDATED, None),
            "completed_at": ("2026-09-12T12:00:00Z", CREATED, None),
        }
        for index in (0, 1):
            for field, values in changes.items():
                for value in values:
                    with self.subTest(job=index, field=field, value=value):
                        pages = deepcopy(self.pages)
                        pages[0]["jobs"][index][field] = value
                        with self.assertRaises(CONTRACT_ERRORS):
                            self.validate(pages)

    def test_run_conclusion_must_match_complete_inventory(self):
        self.run["conclusion"] = "failure"
        with self.assertRaises(CONTRACT_ERRORS):
            self.validate()
        self.run["conclusion"] = "success"
        self.pages[0]["jobs"][0]["conclusion"] = "failure"
        with self.assertRaises(CONTRACT_ERRORS):
            self.validate()


class ManifestReplacementTests(unittest.TestCase):
    def setUp(self):
        self.manifest = initial_manifest()
        self.old = deepcopy(self.manifest["batches"][0])
        self.new = dict(self.old, run_id=20001, dispatch_nonce="f" * 64)
        self.ids = {record["run_id"] for record in self.manifest["batches"]}
        self.nonces = {record["dispatch_nonce"] for record in self.manifest["batches"]}

    def replace(self):
        return recovery.replace_manifest_record(
            self.manifest, old_record=self.old, replacement=self.new,
            seen_ids=self.ids, seen_nonces=self.nonces,
        )

    def test_fresh_replacement_preserves_other_21_and_original_input(self):
        before = deepcopy(self.manifest)
        result = self.replace()
        self.assertEqual(result["batches"][0], self.new)
        self.assertEqual(result["batches"][1:], before["batches"][1:])
        self.assertEqual(contract.validate_manifest(result, expected_sha=SHA), result)
        self.assertEqual(self.manifest, before)
        self.assertEqual(len(result["batches"]), 22)
        self.assertEqual(result["version"], 2)

    def test_entire_expected_old_record_must_match(self):
        for field, value in (("run_id", 29999), ("dispatch_nonce", "d" * 64), ("run_attempt", 2), ("artifact", "wrong"), ("workflow", "wrong.yml")):
            with self.subTest(field=field):
                old = deepcopy(self.old)
                old[field] = value
                with self.assertRaises(CONTRACT_ERRORS):
                    recovery.replace_manifest_record(self.manifest, old_record=old, replacement=self.new, seen_ids=self.ids, seen_nonces=self.nonces)

    def test_new_id_and_nonce_must_not_reuse_any_historical_attempt(self):
        for field, historical in (("run_id", 19999), ("dispatch_nonce", "e" * 64)):
            with self.subTest(field=field):
                ids, nonces = set(self.ids), set(self.nonces)
                (ids if field == "run_id" else nonces).add(historical)
                replacement = dict(self.new, **{field: historical})
                with self.assertRaises(CONTRACT_ERRORS):
                    recovery.replace_manifest_record(self.manifest, old_record=self.old, replacement=replacement, seen_ids=ids, seen_nonces=nonces)

    def test_wrong_batch_attempt_workflow_artifact_and_identity_rejected(self):
        for field, value in (("batch", 2), ("run_attempt", 2), ("run_attempt", True), ("workflow", "test-other.yml"), ("artifact", "batch2-test-results"), ("run_id", True), ("run_id", self.old["run_id"]), ("dispatch_nonce", self.old["dispatch_nonce"]), ("dispatch_nonce", "not-a-nonce")):
            with self.subTest(field=field, value=value):
                self.new = dict(self.old, run_id=20001, dispatch_nonce="f" * 64)
                self.new[field] = value
                with self.assertRaises(CONTRACT_ERRORS):
                    self.replace()


class RecoveryControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.audit_path = self.root / "audit.json"
        self.fixture = RecoveryFixture()
        self.topology = mock.patch.object(exact, "discover_topology_at_commit", return_value=self.fixture.definitions).start()
        self.addCleanup(mock.patch.stopall)
        self.trusted_command = mock.patch.object(recovery, "trusted_download_command", return_value=CURL_COMMAND).start()
        self.no_process = mock.patch.object(recovery.subprocess, "run", side_effect=AssertionError("unit tests may not run git, gh, or network commands")).start()

    def controller(self, *, deadline_epoch=None):
        return REAL_RECOVERY(
            self.fixture.manifest, REPOSITORY, self.root, self.audit_path,
            api=self.fixture, clock=self.fixture.clock, sleep=self.fixture.clock.sleep,
            deadline_epoch=deadline_epoch,
        )

    def audit(self):
        return json.loads(self.audit_path.read_text())

    def assert_final(self, result, changed=()):
        self.assertEqual(contract.validate_manifest(result, expected_sha=SHA, expected_branch=BRANCH, expected_orchestration_id=ORCHESTRATION), result)
        self.assertEqual(len(result["batches"]), 22)
        self.assertEqual(result["version"], 2)
        for before, after in zip(self.fixture.manifest["batches"], result["batches"]):
            with self.subTest(batch=after["batch"]):
                self.assertEqual(after["run_attempt"], 1)
                self.assertEqual(self.fixture.runs[after["run_id"]]["conclusion"], "success")
                if after["batch"] in changed:
                    self.assertNotEqual(before["run_id"], after["run_id"])
                    self.assertNotEqual(before["dispatch_nonce"], after["dispatch_nonce"])
                else:
                    self.assertEqual(after, before)
        audit = self.audit()
        self.assertEqual(audit["original_manifest"], self.fixture.manifest)
        self.assertEqual(audit["accepted_manifest"], result)
        self.assertEqual(audit["status"], "batches_passed_summary_pending")
        self.topology.assert_called_once_with(self.root, SHA)

    def test_baseline_all_green_checks_all_22_without_any_retry(self):
        result = self.controller().recover()
        self.assert_final(result)
        self.assertEqual(self.fixture.posts, [])
        self.assertEqual(self.fixture.clock.sleeps, [])
        self.assertEqual(len(self.audit()["history"]), 22)
        self.assertEqual(sum("/attempts/1/jobs?" in call[0] for call in self.fixture.calls), 22)
        self.trusted_command.assert_not_called()

    def test_fresh_retry_recovers_only_failed_batch(self):
        self.fixture.fail(6)
        result = self.controller().recover()
        self.assert_final(result, changed={6})
        self.assertEqual(len(self.fixture.posts), 1)
        batch, payload = self.fixture.posts[0]
        self.assertEqual(batch, 6)
        self.assertEqual(payload, contract.batch_dispatch_payload(batch=6, orchestration_id=ORCHESTRATION, dispatch_nonce=result["batches"][5]["dispatch_nonce"], expected_sha=SHA, branch=BRANCH))
        self.assertEqual([item["classification"] for item in self.audit()["history"] if item["batch"] == 6], ["transient_download", "success"])
        self.trusted_command.assert_called_once_with(self.root, SHA, self.fixture.definitions[5], self.fixture.pages[10006][0]["jobs"][0])

    def test_success_on_second_retry_accepts_only_last_successful_run(self):
        self.fixture.fail()
        self.fixture.outcomes[1] = ["transient", "success"]
        result = self.controller().recover()
        self.assert_final(result, changed={1})
        self.assertEqual(len(self.fixture.posts), 2)
        failed_retry, good_retry = self.fixture.dispatched_records
        self.assertEqual(result["batches"][0], good_retry)
        self.assertNotIn(failed_retry["run_id"], {item["run_id"] for item in result["batches"]})
        self.assertNotEqual(failed_retry["dispatch_nonce"], good_retry["dispatch_nonce"])
        self.assertEqual([entry["retry"] for entry in self.audit()["history"] if entry["batch"] == 1], [0, 1, 2])
        self.assertEqual(self.fixture.clock.sleeps, [60, 120])

    def test_entire_22_batch_recovery_produces_only_fresh_successful_records(self):
        for batch in range(1, 23):
            self.fixture.fail(batch)
            self.fixture.outcomes[batch] = ["transient", "success"] if batch % 2 == 0 else ["success"]
        result = self.controller().recover()
        self.assert_final(result, changed=set(range(1, 23)))
        self.assertEqual(len(self.fixture.posts), 33)
        self.assertEqual(len({item["dispatch_nonce"] for item in self.fixture.dispatched_records}), 33)
        self.assertEqual(len({item["run_id"] for item in self.fixture.dispatched_records}), 33)
        self.assertEqual(len(self.audit()["history"]), 55)

    def test_maximum_two_retries_and_never_accept_a_failed_replacement(self):
        self.fixture.fail()
        self.fixture.outcomes[1] = ["transient"]
        controller = self.controller()
        with self.assertRaises(CONTRACT_ERRORS):
            controller.recover()
        self.assertEqual(len(self.fixture.posts), 2)
        self.assertEqual(controller.manifest, self.fixture.manifest)
        self.assertNotEqual(self.audit()["status"], "batches_passed_summary_pending")

    def test_nontransient_failure_and_unavailable_logs_never_dispatch(self):
        for outcome in ("hard", "unavailable", "malicious", "oversized", "invalid_utf8"):
            with self.subTest(outcome=outcome):
                self.fixture = RecoveryFixture()
                self.fixture.fail(outcome="hard" if outcome == "hard" else "transient")
                job_id = self.fixture.manifest["batches"][0]["run_id"] * 10
                if outcome == "unavailable":
                    self.fixture.logs[job_id] = contract.ContractError("logs unavailable")
                elif outcome == "malicious":
                    self.fixture.logs[job_id] = log_bytes("fetch https://evil.example/jobs/999/logs", "fatal error: build failed")
                elif outcome == "oversized":
                    self.fixture.logs[job_id] = b"x" * (recovery.MAX_LOG_BYTES + 1)
                elif outcome == "invalid_utf8":
                    self.fixture.logs[job_id] = b"\xff"
                with self.assertRaises(CONTRACT_ERRORS):
                    self.controller().recover()
                self.assertEqual(self.fixture.posts, [])
                self.assertEqual(self.audit()["history"][0]["classification"], "repair_required")

    def test_only_validated_job_id_controls_log_endpoint(self):
        self.fixture.fail()
        job = self.fixture.pages[10001][0]["jobs"][0]
        job.update(url="https://evil.example/logs", logs_url="https://evil.example/logs")
        result = self.controller().recover()
        self.assert_final(result, changed={1})
        self.assertEqual([call[0] for call in self.fixture.calls if call[3]], [f"repos/{REPOSITORY}/actions/jobs/{job['id']}/logs"])

    def test_invalid_job_provenance_blocks_log_download_and_retry(self):
        self.fixture.fail()
        self.fixture.pages[10001][0]["jobs"][0]["html_url"] = "https://evil.example/logs"
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertFalse(any(call[3] for call in self.fixture.calls))
        self.assertEqual(self.fixture.posts, [])

    def test_baseline_run_identity_must_match_trusted_manifest(self):
        mutations = {
            "id": 99999, "head_sha": OTHER_SHA, "head_branch": "production",
            "repository": {"full_name": "other/repo"},
            "head_repository": {"full_name": "fork/repo"},
            "run_attempt": 2, "path": contract.expected_workflow_path(2),
            "display_title": contract.expected_run_name(1, ORCHESTRATION, "f" * 64),
            "event": "push", "status": "in_progress", "conclusion": "cancelled",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                self.fixture = RecoveryFixture()
                self.fixture.runs[10001][field] = value
                with self.assertRaises(CONTRACT_ERRORS):
                    self.controller().recover()
                self.assertEqual(self.fixture.posts, [])

    def test_main_movement_before_first_dispatch(self):
        self.fixture.fail()
        self.fixture.ref_hook = lambda api: branch_ref(OTHER_SHA if api.ref_count >= 2 else SHA)
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertEqual(self.fixture.posts, [])

    def test_main_movement_after_dispatch_never_accepts_replacement(self):
        self.fixture.fail()
        self.fixture.ref_hook = lambda api: branch_ref(OTHER_SHA if api.posts else SHA)
        controller = self.controller()
        with self.assertRaises(CONTRACT_ERRORS):
            controller.recover()
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertEqual(controller.manifest, self.fixture.manifest)

    def test_main_movement_after_registration_never_accepts_replacement(self):
        self.fixture.fail()
        self.fixture.ref_hook = lambda api: branch_ref(OTHER_SHA if api.registration_count else SHA)
        controller = self.controller()
        with self.assertRaises(CONTRACT_ERRORS):
            controller.recover()
        self.assertEqual(controller.manifest, self.fixture.manifest)
        self.assertEqual(len(self.fixture.posts), 1)

    def test_wrong_branch_reference_is_rejected_even_with_correct_sha(self):
        self.fixture.ref_hook = lambda api: branch_ref(branch="production")
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertEqual(self.fixture.posts, [])

    def test_reference_must_point_to_a_commit_not_a_tag_or_tree(self):
        for object_type in (None, "tag", "tree", "blob"):
            with self.subTest(object_type=object_type):
                self.fixture = RecoveryFixture()
                self.fixture.ref_hook = lambda api: {"ref": "refs/heads/main", "object": {"sha": SHA, "type": object_type}}
                with self.assertRaises(CONTRACT_ERRORS):
                    self.controller().recover()
                self.assertEqual(self.fixture.posts, [])

    def test_ambiguous_post_reconciles_one_nonce_without_redispatch(self):
        self.fixture.fail()
        self.fixture.ambiguous = True
        self.fixture.visible_after = 2
        result = self.controller().recover()
        self.assert_final(result, changed={1})
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertEqual(self.fixture.registration_count, 3)
        self.assertEqual(self.audit()["dispatches"][0]["dispatch_response"], "ambiguous")
        self.assertEqual(self.fixture.clock.sleeps, [60, 10, 10])

    def test_registration_timeout_is_bounded_at_18_polls_and_one_post(self):
        self.fixture.fail()
        self.fixture.ambiguous = True
        self.fixture.never_register = True
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertEqual(self.fixture.registration_count, 18)
        self.assertLessEqual(sum(self.fixture.clock.sleeps), 60 + 18 * 10)

    def test_duplicate_registration_across_pages_is_rejected(self):
        self.fixture.fail()
        self.fixture.registration_hook = lambda pages: [dict(pages[0], total_count=2), dict(deepcopy(pages[0]), total_count=2)]
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertEqual(len(self.fixture.posts), 1)

    def test_registration_incomplete_pagination_is_not_unique_evidence(self):
        self.fixture.fail()
        self.fixture.registration_hook = lambda pages: [dict(pages[0], total_count=2)]
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()

    def test_registration_reusing_an_original_run_id_is_rejected(self):
        self.fixture.fail()
        def reuse(pages):
            pages[0]["workflow_runs"][0]["id"] = 10022
            return pages
        self.fixture.registration_hook = reuse
        controller = self.controller()
        with self.assertRaises(CONTRACT_ERRORS):
            controller.recover()
        self.assertEqual(controller.manifest, self.fixture.manifest)

    def test_duplicate_pending_nonces_are_rejected_before_second_batch_dispatch(self):
        self.fixture.fail(1)
        self.fixture.fail(2)
        with mock.patch.object(recovery, "generate_dispatch_nonce", return_value="e" * 64):
            with self.assertRaises(CONTRACT_ERRORS):
                self.controller().recover()
        self.assertEqual(len(self.fixture.posts), 1)

    def test_cancellation_of_replacement_stops_recovery(self):
        self.fixture.fail()
        self.fixture.run_hook = lambda run: dict(run, conclusion="cancelled") if run["id"] > 20000 else run
        controller = self.controller()
        with self.assertRaises(CONTRACT_ERRORS):
            controller.recover()
        self.assertEqual(controller.manifest, self.fixture.manifest)

    def test_main_movement_on_final_check_prevents_success(self):
        self.fixture.ref_hook = lambda api: branch_ref(OTHER_SHA if sum("/attempts/1/jobs?" in call[0] for call in api.calls) == 22 else SHA)
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertNotEqual(self.audit()["status"], "batches_passed_summary_pending")

    def test_replacement_run_provenance_is_rechecked_after_registration(self):
        for field, value in (("head_sha", OTHER_SHA), ("head_branch", "production"), ("head_repository", {"full_name": "fork/repo"}), ("id", 29999), ("run_attempt", 2), ("display_title", contract.expected_run_name(1, ORCHESTRATION, "d" * 64))):
            with self.subTest(field=field):
                self.fixture = RecoveryFixture()
                self.fixture.fail()
                self.fixture.run_hook = lambda run, field=field, value=value: dict(run, **{field: value}) if run["id"] > 20000 else run
                controller = self.controller()
                with self.assertRaises(CONTRACT_ERRORS):
                    controller.recover()
                self.assertEqual(controller.manifest, self.fixture.manifest)
                self.assertEqual(len(self.fixture.posts), 1)

    def test_duplicate_generated_nonce_never_dispatches(self):
        self.fixture.fail()
        with mock.patch.object(recovery, "generate_dispatch_nonce", return_value=self.fixture.manifest["batches"][0]["dispatch_nonce"]):
            with self.assertRaises(CONTRACT_ERRORS):
                self.controller().recover()
        self.assertEqual(self.fixture.posts, [])

    def test_failed_first_retry_identity_cannot_be_reused_for_second_retry(self):
        self.fixture.fail()
        self.fixture.outcomes[1] = ["transient", "success"]
        with mock.patch.object(recovery, "generate_dispatch_nonce", return_value="e" * 64):
            with self.assertRaises(CONTRACT_ERRORS):
                self.controller().recover()
        self.assertEqual(len(self.fixture.posts), 1)

    def test_global_deadline_stops_waiting_run_without_accepting_it(self):
        self.fixture.fail()
        self.fixture.run_hook = lambda run: dict(run, status="in_progress", conclusion=None) if run["id"] > 20000 else run
        with mock.patch.object(recovery, "RECOVERY_SECONDS", 100):
            controller = self.controller()
            with self.assertRaises(CONTRACT_ERRORS):
                controller.recover()
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertEqual(controller.manifest, self.fixture.manifest)
        self.assertLessEqual(self.fixture.clock.now, 130)

    def test_optional_shared_deadline_preserves_90_minute_default(self):
        with mock.patch.object(recovery.time, "time") as wall_clock:
            controller = self.controller()
        self.assertEqual(controller.deadline, self.fixture.clock.now + 90 * 60)
        wall_clock.assert_not_called()

    def test_shared_deadline_requires_a_positive_literal_integer(self):
        for deadline in (True, False, 0, -1, str(EPOCH + 300), float(EPOCH + 300), float("inf"), float("nan")):
            with self.subTest(deadline=deadline), mock.patch.object(recovery.time, "time", return_value=EPOCH):
                with self.assertRaises(CONTRACT_ERRORS):
                    self.controller(deadline_epoch=deadline)
        self.assertEqual(self.fixture.calls, [])
        self.topology.assert_not_called()

    def test_controller_budget_is_minimum_of_90_minutes_and_remaining_epoch_time(self):
        self.fixture.clock.now = 123.5
        for seconds in (1, 30, 90 * 60, 4 * 60 * 60):
            with self.subTest(seconds=seconds), mock.patch.object(recovery.time, "time", return_value=EPOCH + 0.25):
                controller = self.controller(deadline_epoch=EPOCH + seconds)
                expected = min(90 * 60, seconds - 0.25)
                self.assertAlmostEqual(controller.deadline, 123.5 + expected)

    def test_elapsed_initial_batches_reduce_recovery_budget(self):
        with mock.patch.object(recovery.time, "time", return_value=EPOCH + 270 * 60):
            controller = self.controller(deadline_epoch=EPOCH + 285 * 60)
        self.assertEqual(controller.deadline, self.fixture.clock.now + 15 * 60)

    def test_already_expired_shared_deadline_rejects_before_any_api_or_topology(self):
        for deadline in (EPOCH - 1, EPOCH):
            with self.subTest(deadline=deadline), mock.patch.object(recovery.time, "time", return_value=EPOCH):
                with self.assertRaises(CONTRACT_ERRORS):
                    self.controller(deadline_epoch=deadline)
        self.assertEqual(self.fixture.calls, [])
        self.topology.assert_not_called()

    def test_shared_budget_exhausted_during_backoff_prevents_dispatch(self):
        self.fixture.fail()
        with mock.patch.object(recovery.time, "time", return_value=EPOCH):
            controller = self.controller(deadline_epoch=EPOCH + 30)
            with self.assertRaises(CONTRACT_ERRORS):
                controller.recover()
        self.assertEqual(self.fixture.posts, [])
        self.assertEqual(controller.manifest, self.fixture.manifest)
        self.assertNotEqual(self.audit()["status"], "batches_passed_summary_pending")

    def test_successful_recovery_within_shared_budget_preserves_exact_22_records(self):
        self.fixture.fail()
        with mock.patch.object(recovery.time, "time", return_value=EPOCH):
            controller = self.controller(deadline_epoch=EPOCH + 300)
            result = controller.recover()
        self.assert_final(result, changed={1})
        self.assertLess(self.fixture.clock.now, controller.deadline)
        self.assertEqual(len(self.fixture.posts), 1)

    def test_wall_clock_rollback_does_not_extend_established_monotonic_deadline(self):
        with mock.patch.object(recovery.time, "time", return_value=EPOCH) as wall_clock:
            controller = self.controller(deadline_epoch=EPOCH + 300)
            wall_clock.return_value = EPOCH - 60 * 60
            self.fixture.clock.now = 300
            with self.assertRaises(CONTRACT_ERRORS):
                controller.current()
        self.assertEqual(controller.deadline, 300)
        self.assertEqual(self.fixture.calls, [])

    def cli(self, *, trusted_sha=SHA, trusted_branch=BRANCH, trusted_orchestration=ORCHESTRATION, deadline_epoch=None):
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text(contract.canonical_json(self.fixture.manifest) + "\n")
        argv = ["--manifest", str(manifest_path), "--repository", REPOSITORY,
                "--expected-sha", trusted_sha, "--branch", trusted_branch,
                "--orchestration-id", trusted_orchestration, "--audit", str(self.audit_path)]
        if deadline_epoch is not None:
            argv.append(f"--deadline-epoch={deadline_epoch}")
        def factory(*args, **kwargs):
            return REAL_RECOVERY(*args, **kwargs, api=self.fixture, clock=self.fixture.clock, sleep=self.fixture.clock.sleep)
        with mock.patch.object(recovery, "Recovery", side_effect=factory) as constructor, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch("sys.stderr", new_callable=io.StringIO) as stderr, mock.patch.object(recovery.Path, "cwd", return_value=self.root):
            status = recovery.main(argv)
        return status, stdout.getvalue(), stderr.getvalue(), constructor

    def test_cli_writes_only_verified_replacement_manifest(self):
        self.fixture.fail()
        status, stdout, stderr, _ = self.cli()
        self.assertEqual(status, 0, stderr)
        result = json.loads((self.root / "manifest.json").read_text())
        self.assert_final(result, changed={1})
        self.assertIn("Global Summary", stdout)
        self.assertEqual(stderr, "")

    def test_cli_optional_deadline_is_forwarded_without_recomputing_it(self):
        for deadline in (None, EPOCH + 300):
            with self.subTest(deadline=deadline), mock.patch.object(recovery.time, "time", return_value=EPOCH):
                status, _, stderr, constructor = self.cli(deadline_epoch=deadline)
                self.assertEqual(status, 0, stderr)
                self.assertEqual(constructor.call_args.kwargs["deadline_epoch"], deadline)
        self.assertEqual(self.fixture.posts, [])

    def test_cli_invalid_or_expired_shared_deadline_never_writes_manifest(self):
        path = self.root / "manifest.json"
        original = contract.canonical_json(self.fixture.manifest) + "\n"
        path.write_text(original)
        for deadline in (0, -1, EPOCH - 1, EPOCH):
            with self.subTest(deadline=deadline), mock.patch.object(recovery.time, "time", return_value=EPOCH):
                status, stdout, stderr, _ = self.cli(deadline_epoch=deadline)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn("stopped", stderr)
                self.assertEqual(path.read_text(), original)
        self.assertEqual(self.fixture.calls, [])

    def test_cli_noninteger_deadline_is_rejected_by_argument_parser(self):
        for deadline in ("1.5", "true", "nan", "infinity"):
            with self.subTest(deadline=deadline), self.assertRaises(SystemExit) as error:
                self.cli(deadline_epoch=deadline)
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.fixture.calls, [])

    def test_cli_shared_budget_expiry_cannot_publish_partial_recovery(self):
        self.fixture.fail(1)
        self.fixture.fail(2)
        self.fixture.outcomes[2] = ["transient", "success"]
        path = self.root / "manifest.json"
        original = contract.canonical_json(self.fixture.manifest) + "\n"
        path.write_text(original)
        with mock.patch.object(recovery.time, "time", return_value=EPOCH):
            status, stdout, _, _ = self.cli(deadline_epoch=EPOCH + 90)
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(path.read_text(), original)
        self.assertEqual([batch for batch, _ in self.fixture.posts], [1, 2])
        self.assertEqual(self.audit()["status"], "failed")

    def test_cli_trusted_sha_branch_and_orchestration_are_not_inferred_from_input(self):
        for overrides in ({"trusted_sha": OTHER_SHA}, {"trusted_sha": "not-a-sha"}, {"trusted_branch": "production"}, {"trusted_orchestration": "orchestration-999999-1"}):
            with self.subTest(overrides=overrides):
                status, stdout, stderr, constructor = self.cli(**overrides)
                self.assertEqual(status, 1)
                self.assertIn("stopped", stderr)
                self.assertEqual(stdout, "")
                constructor.assert_not_called()
                self.assertEqual(self.fixture.calls, [])
                self.assertEqual(json.loads((self.root / "manifest.json").read_text()), self.fixture.manifest)

    def test_cli_failure_never_writes_a_partially_recovered_manifest(self):
        self.fixture.fail(1)
        self.fixture.fail(2, "hard")
        path = self.root / "manifest.json"
        original = contract.canonical_json(self.fixture.manifest) + "\n"
        path.write_text(original)
        status, stdout, stderr, _ = self.cli()
        self.assertEqual(status, 1)
        self.assertEqual(path.read_text(), original)
        self.assertEqual(stdout, "")
        self.assertIn("repair", stderr)
        self.assertEqual(self.audit()["status"], "failed")

    def test_cli_missing_trusted_sha_is_rejected_by_argument_parser(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
            recovery.main(["--manifest", str(self.root / "manifest.json"), "--repository", REPOSITORY, "--branch", BRANCH, "--orchestration-id", ORCHESTRATION, "--audit", str(self.audit_path)])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.fixture.calls, [])

    def test_cli_malformed_manifest_does_not_start_recovery(self):
        path = self.root / "manifest.json"
        for raw in ("not JSON", "{}", "[]"):
            with self.subTest(raw=raw):
                path.write_text(raw)
                status, _, _, constructor = self.cli()
                self.assertEqual(status, 1)
                constructor.assert_not_called()
                self.assertEqual(path.read_text(), raw)

    def test_cli_duplicate_keys_noncanonical_and_oversized_manifest_rejected(self):
        canonical = contract.canonical_json(self.fixture.manifest)
        duplicate_sha = canonical.replace('"expected_sha":', f'"expected_sha":"{OTHER_SHA}","expected_sha":', 1)
        path = self.root / "manifest.json"
        for raw in (duplicate_sha, json.dumps(self.fixture.manifest, indent=2), " " * (contract.MAX_MANIFEST_BYTES + 1)):
            with self.subTest(length=len(raw)):
                path.write_text(raw)
                status, _, _, constructor = self.cli()
                self.assertEqual(status, 1)
                constructor.assert_not_called()
                self.assertEqual(path.read_text(), raw)

    def test_cli_wrong_typed_log_response_fails_without_publishing_manifest(self):
        for raw in (None, {}, "curl: (6) Could not resolve host: downloads.example.org"):
            with self.subTest(raw=raw):
                self.fixture = RecoveryFixture()
                self.fixture.fail()
                self.fixture.logs[100010] = raw
                path = self.root / "manifest.json"
                original = contract.canonical_json(self.fixture.manifest) + "\n"
                path.write_text(original)
                status, _, _, _ = self.cli()
                self.assertEqual(status, 1)
                self.assertEqual(path.read_text(), original)
                self.assertEqual(self.fixture.posts, [])

    def test_cli_missing_untrusted_or_mismatched_command_never_dispatches(self):
        for command in (None, "", f"{CURL_COMMAND}; ./configure", "curl --fail https://unrelated.example.org/pkg", f"printf '%s\\n' '{DOWNLOAD}' '{DNS_ERROR}'"):
            with self.subTest(command=command):
                self.fixture = RecoveryFixture()
                self.fixture.fail()
                self.trusted_command.return_value = command
                path = self.root / "manifest.json"
                original = contract.canonical_json(self.fixture.manifest) + "\n"
                path.write_text(original)
                status, _, _, _ = self.cli()
                self.assertEqual(status, 1)
                self.assertEqual(self.fixture.posts, [])
                self.assertEqual(path.read_text(), original)

    def test_cli_command_authentication_failure_does_not_accept_manifest(self):
        self.fixture.fail()
        self.trusted_command.side_effect = contract.ContractError("immutable workflow blob unavailable")
        status, _, _, _ = self.cli()
        self.assertEqual(status, 1)
        self.assertEqual(self.fixture.posts, [])
        self.assertEqual(json.loads((self.root / "manifest.json").read_text()), self.fixture.manifest)

    def test_cli_output_filename_host_never_authorizes_retry_or_manifest_write(self):
        self.fixture.fail()
        command = f"curl --fail --output https://other.example.org/out {DOWNLOAD}"
        self.trusted_command.return_value = command
        self.fixture.logs[100010] = log_bytes(
            "curl: (6) Could not resolve host: other.example.org", command=command,
        )
        path = self.root / "manifest.json"
        original = contract.canonical_json(self.fixture.manifest) + "\n"
        path.write_text(original)
        status, stdout, _, _ = self.cli()
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(self.fixture.posts, [])
        self.assertEqual(path.read_text(), original)

    def test_downstream_calculate_summary_failure_does_not_retry_prior_download(self):
        self.fixture.fail()
        package = self.fixture.pages[10001][0]["jobs"][0]
        package["steps"].append(dict(package["steps"][0], number=2, name="Calculate Summary"))
        with self.assertRaises(CONTRACT_ERRORS):
            self.controller().recover()
        self.assertEqual(self.fixture.posts, [])


class WorkflowScopeTests(unittest.TestCase):
    def test_serialized_workflows_preserve_pending_jobs(self):
        for filename, job_id, group in (
            ("main.yml", "build_and_deploy_s3", "production-deployment"),
            ("test-all-packages-orchestrator.yml", "orchestrate-batches", "orchestrator"),
        ):
            with self.subTest(workflow=filename):
                workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / filename).read_text())
                self.assertNotIn("concurrency", workflow)
                for name, job in workflow["jobs"].items():
                    if name == job_id:
                        self.assertEqual(job["concurrency"], {
                            "group": group, "cancel-in-progress": False, "queue": "max",
                        })
                    else:
                        self.assertNotIn("concurrency", job)

    def test_late_old_scope_cannot_replace_latest_pending_deployment(self):
        workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / "main.yml").read_text())
        deployment = workflow["jobs"]["build_and_deploy_s3"]
        policy = deployment["concurrency"]
        # Model GitHub's queue admission order while an earlier job holds the lock.
        pending = [SHA]
        if policy.get("queue", "single") == "single":
            pending.clear()
        pending.append(OTHER_SHA)
        self.assertEqual(pending, [SHA, OTHER_SHA])
        guard = next(step["run"] for step in deployment["steps"]
                     if step.get("name") == "Require the reviewed commit to remain current")
        fake_git = 'git() { if [[ "$1" == "check-ref-format" ]]; then return 0; fi; printf "%s\\trefs/heads/main\\n" "$CURRENT_SHA"; }\n'
        statuses = []
        for sha in pending:
            result = subprocess.run(
                ["bash", "-c", fake_git + guard], capture_output=True, text=True,
                env={**recovery.os.environ, "BASE_BRANCH": "main", "EXPECTED_BASE_SHA": sha, "CURRENT_SHA": SHA},
                timeout=10,
            )
            statuses.append(result.returncode)
        self.assertEqual(statuses, [0, 1])

    def test_queue_lint_compatibility_is_narrow_and_schema_checked(self):
        workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / "exact-run-aggregation-foundation-ci.yml").read_text())
        lint = next(step for step in workflow["jobs"]["exact-run-contract"]["steps"] if step.get("name") == "Lint foundation workflow")
        command = lint["run"]
        self.assertEqual(lint["env"]["ACTIONLINT_VERSION"], "1.7.12")
        self.assertIn("! -name 'test-all-packages-orchestrator.yml'", command)
        self.assertEqual(command.count("-ignore"), 1)
        schema_check = "test_smoke_recovery.WorkflowScopeTests.test_serialized_workflows_preserve_pending_jobs"
        self.assertLess(command.index(schema_check), command.index("-ignore"))
        exempt = shlex.split(command[command.rindex('"$binary"'):].replace("\\\n", ""))
        self.assertEqual(exempt, ["$binary", "-shellcheck=", "-ignore",
            '^unexpected key "queue" for "concurrency" section\\. expected one of "cancel-in-progress", "group"$',
            ".github/workflows/main.yml", ".github/workflows/test-all-packages-orchestrator.yml"])

    def test_notification_retains_producing_attempt_on_partial_rerun(self):
        workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / "test-all-packages-orchestrator.yml").read_text())
        orchestration = workflow["jobs"]["orchestrate-batches"]
        self.assertEqual(orchestration["outputs"]["run_attempt"], "${{ steps.budget.outputs.run_attempt }}")
        budget = orchestration["steps"][0]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            subprocess.run(["bash", "-e", "-c", budget["run"]], check=True, timeout=10,
                           env={**recovery.os.environ, "GITHUB_RUN_ATTEMPT": "1", "GITHUB_OUTPUT": str(output)})
            self.assertEqual(dict(line.split("=", 1) for line in output.read_text().splitlines())["run_attempt"], "1")
        notifier = next(step for step in workflow["jobs"]["notify"]["steps"] if step.get("name") == "Notify the smoke-run owner")
        self.assertEqual(notifier["env"]["RUN_ATTEMPT"], "${{ github.run_attempt }}")
        self.assertEqual(notifier["env"]["ORCHESTRATION_ATTEMPT"], "${{ needs.orchestrate-batches.outputs.run_attempt || github.run_attempt }}")
        command = shlex.split(notifier["run"].replace("\\\n", ""))
        self.assertEqual(command[command.index("--orchestration-attempt") + 1], "$ORCHESTRATION_ATTEMPT")

    def test_recovery_helper_and_tests_trigger_existing_exact_ci(self):
        workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / "exact-run-aggregation-foundation-ci.yml").read_text())
        steps = workflow["jobs"]["exact-run-contract"]["steps"]
        scope = next(step for step in steps if step.get("id") == "scope")
        comparison = re.search(r"if git diff --quiet (.*?)\s*;\s*then", scope["run"], re.DOTALL)
        self.assertIsNotNone(comparison)
        tokens = shlex.split(comparison[1].replace("\\\n", ""))
        paths = tokens[tokens.index("--") + 1:]
        self.assertIn(".github/scripts/smoke_recovery.py", paths)
        self.assertIn(".github/scripts/tests/test_smoke_recovery.py", paths)
        runner = next(step for step in steps if step.get("name") == "Run adversarial contract tests")
        self.assertEqual(runner["if"], "steps.scope.outputs.relevant == 'true'")
        command = shlex.split(runner["run"])
        self.assertEqual(command[command.index("-s") + 1], ".github/scripts/tests")
        self.assertEqual(command[command.index("-p") + 1], "test_*.py")

    def test_orchestrator_shares_initial_budget_and_reserves_summary_and_upload_time(self):
        workflow = yaml.safe_load((SCRIPT_ROOT.parent / "workflows" / "test-all-packages-orchestrator.yml").read_text())
        job = workflow["jobs"]["orchestrate-batches"]
        steps = job["steps"]
        self.assertEqual(steps[0]["id"], "budget")
        self.assertRegex(steps[0]["run"], r"date \+%s")
        self.assertRegex(steps[0]["run"], r"\+\s*285\s*\*\s*60")
        self.assertIn("deadline_epoch=", steps[0]["run"])
        self.assertIn('"$GITHUB_OUTPUT"', steps[0]["run"])
        by_name = {step["name"]: step for step in steps}
        for name in ("Dispatch and capture exact batch runs", "Wait for captured batch runs", "Recover only verified transient download failures"):
            with self.subTest(step=name):
                step = by_name[name]
                self.assertEqual(step["env"]["DEADLINE_EPOCH"], "${{ steps.budget.outputs.deadline_epoch }}")
                self.assertIs(step.get("continue-on-error", False), False)
                if name != "Recover only verified transient download failures":
                    self.assertIn('"$(date +%s)" -lt "$DEADLINE_EPOCH"', step["run"])
                    self.assertIn("exit 1", step["run"])
        command = shlex.split(by_name["Recover only verified transient download failures"]["run"].replace("\\\n", ""))
        self.assertEqual(command[command.index("--deadline-epoch") + 1], "$DEADLINE_EPOCH")
        summary = by_name["Dispatch exact global summary"]
        upload = by_name["Preserve original failures and accepted run identities"]
        self.assertLessEqual(summary["timeout-minutes"], 65)
        self.assertLessEqual(upload["timeout-minutes"], 5)
        self.assertEqual(upload["if"], "always()")
        self.assertGreaterEqual(job["timeout-minutes"] - 285, 75)
        self.assertGreaterEqual(job["timeout-minutes"] - 285, summary["timeout-minutes"] + upload["timeout-minutes"])


class TrustedDownloadCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.definition = definition(1)
        self.job = job_payload(initial_manifest()["batches"][0], conclusion="failure")
        self.step = {"name": self.job["steps"][0]["name"], "run": CURL_COMMAND}
        self.workflow = {"jobs": {"test": {"steps": [self.step]}}}
        self.process = mock.patch.object(recovery.subprocess, "run").start()
        self.addCleanup(mock.patch.stopall)

    def resolve(self, *, raw=None, sha=SHA, topology=None, job=None):
        self.process.return_value = subprocess.CompletedProcess(
            ["git"], 0, stdout=raw if raw is not None else yaml.safe_dump(self.workflow).encode(), stderr=b"",
        )
        return recovery.trusted_download_command(
            self.root, sha, self.definition if topology is None else topology,
            self.job if job is None else job,
        )

    def test_reads_exact_sha_and_registered_workflow_blob_without_worktree_fallback(self):
        self.assertEqual(self.resolve(), CURL_COMMAND)
        self.process.assert_called_once()
        args, kwargs = self.process.call_args
        self.assertEqual(args[0], ["git", "-C", str(self.root), "show", f"{SHA}:{self.definition.packages[0].workflow_path}"])
        self.assertTrue(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertLessEqual(kwargs["timeout"], 20)

    def source_with_shell(self, scope, shell):
        document = deepcopy(self.workflow)
        if scope == "step":
            document["jobs"]["test"]["steps"][0]["shell"] = shell
        elif scope == "job":
            document["jobs"]["test"]["defaults"] = {"run": {"shell": shell}}
        elif scope == "workflow":
            document["defaults"] = {"run": {"shell": shell}}
        else:
            raise AssertionError(f"invalid fixture shell scope: {scope}")
        return yaml.safe_dump(document).encode()

    def assert_custom_shell_rejected(self, scope):
        for shell in (
            "./ci/download-wrapper {0}",
            "python3 {0}",
            "bash -c 'printf fake-error; exit 6' {0}",
            "${{ inputs.shell }}",
        ):
            with self.subTest(scope=scope, shell=shell):
                command = self.resolve(raw=self.source_with_shell(scope, shell))
                self.assertIsNone(command)
                self.assertEqual(
                    recovery.classify_retryable_failure(log_bytes(DNS_ERROR), self.job, command=command),
                    "unknown_failure",
                )

    def test_custom_step_shell_cannot_authenticate_a_curl_operation(self):
        self.assert_custom_shell_rejected("step")

    def test_custom_job_default_shell_cannot_authenticate_a_curl_operation(self):
        self.assert_custom_shell_rejected("job")

    def test_custom_workflow_default_shell_cannot_authenticate_a_curl_operation(self):
        self.assert_custom_shell_rejected("workflow")

    def test_default_bash_and_explicit_bash_shell_preserve_operation_proof(self):
        sources = {"default": yaml.safe_dump(self.workflow).encode()}
        sources.update({scope: self.source_with_shell(scope, "bash") for scope in ("step", "job", "workflow")})
        for scope, raw in sources.items():
            with self.subTest(scope=scope):
                command = self.resolve(raw=raw)
                self.assertEqual(command, CURL_COMMAND)
                self.assertEqual(
                    recovery.classify_retryable_failure(log_bytes(DNS_ERROR), self.job, command=command),
                    "transient_download",
                )

    def test_explicit_sh_is_a_supported_shell(self):
        for scope in ("step", "job", "workflow"):
            with self.subTest(scope=scope):
                self.assertEqual(self.resolve(raw=self.source_with_shell(scope, "sh")), CURL_COMMAND)

    def test_shell_resolution_uses_step_then_job_then_workflow_defaults(self):
        self.workflow["defaults"] = {"run": {"shell": "./workflow-wrapper {0}"}}
        self.workflow["jobs"]["test"]["defaults"] = {"run": {"shell": "./job-wrapper {0}"}}
        self.step["shell"] = "bash"
        self.assertEqual(self.resolve(), CURL_COMMAND)
        self.step.pop("shell")
        self.assertIsNone(self.resolve())
        self.workflow["jobs"]["test"]["defaults"]["run"]["shell"] = "bash"
        self.assertEqual(self.resolve(), CURL_COMMAND)
        self.workflow["jobs"]["test"].pop("defaults")
        self.assertIsNone(self.resolve())

    def test_uses_and_run_combination_cannot_authenticate_shell_operation(self):
        self.step["uses"] = "./ci/download-action"
        self.assertIsNone(self.resolve())

    def test_source_environment_cannot_replace_shell_or_curl_at_any_scope(self):
        overrides = {
            "BASH_ENV": "/tmp/curl-replacement.sh",
            "ENV": "/tmp/shell-startup.sh",
            "PATH": "/tmp/replacement-bin:/usr/bin",
            "LD_PRELOAD": "/tmp/replacement.so",
            "LD_LIBRARY_PATH": "/tmp/replacement-libraries",
            "LD_AUDIT": "/tmp/audit-replacement.so",
        }
        for scope in ("step", "job", "workflow"):
            for key, value in overrides.items():
                with self.subTest(scope=scope, key=key):
                    document = deepcopy(self.workflow)
                    target = {
                        "step": document["jobs"]["test"]["steps"][0],
                        "job": document["jobs"]["test"],
                        "workflow": document,
                    }[scope]
                    target["env"] = {key: value}
                    command = self.resolve(raw=yaml.safe_dump(document).encode())
                    self.assertIsNone(command)
                    self.assertEqual(
                        recovery.classify_retryable_failure(log_bytes(DNS_ERROR), self.job, command=command),
                        "unknown_failure",
                    )

    def test_dynamic_source_environment_cannot_hide_startup_overrides(self):
        for scope in ("step", "job", "workflow"):
            with self.subTest(scope=scope):
                document = deepcopy(self.workflow)
                target = {
                    "step": document["jobs"]["test"]["steps"][0],
                    "job": document["jobs"]["test"],
                    "workflow": document,
                }[scope]
                target["env"] = "${{ fromJSON(inputs.runtime_env) }}"
                self.assertIsNone(self.resolve(raw=yaml.safe_dump(document).encode()))

    def test_invalid_sha_never_uses_head_or_falls_back_to_worktree(self):
        for sha in ("main", "HEAD", "a" * 39, "a" * 41, "a" * 40 + ":other", "--output=somewhere"):
            with self.subTest(sha=sha):
                self.assertIsNone(self.resolve(sha=sha))
        self.process.assert_not_called()

    def test_unregistered_or_duplicate_package_job_never_reads_source(self):
        self.assertIsNone(self.resolve(job=dict(self.job, name="summary")))
        duplicate = replace(self.definition, packages=self.definition.packages * 2)
        self.assertIsNone(self.resolve(topology=duplicate))
        self.process.assert_not_called()

    def test_requires_exactly_one_failed_api_step(self):
        for steps in ([], None, "not steps", [dict(self.job["steps"][0], conclusion="success")], self.job["steps"] * 2):
            with self.subTest(steps=steps):
                self.assertIsNone(self.resolve(job=dict(self.job, steps=steps)))
        self.process.assert_not_called()

    def test_requires_exactly_one_matching_named_top_level_source_step(self):
        for steps in ([], [dict(self.step, name="Other download")], [deepcopy(self.step), deepcopy(self.step)], [{"uses": "./local-action", "name": self.step["name"]}], [{"name": "Wrapper", "steps": [self.step]}]):
            with self.subTest(steps=steps):
                self.workflow["jobs"]["test"]["steps"] = steps
                self.assertIsNone(self.resolve())

    def test_source_continue_on_error_must_be_literal_false_or_absent(self):
        for value in (True, "true", "false", "${{ inputs.allow_failure }}", 0, None):
            with self.subTest(value=value):
                self.step["continue-on-error"] = value
                self.assertIsNone(self.resolve())
        self.step["continue-on-error"] = False
        self.assertEqual(self.resolve(), CURL_COMMAND)

    def test_source_mixed_install_build_and_echo_scripts_do_not_authenticate(self):
        for command in (f"{CURL_COMMAND}\n./configure\nmake", f"echo '{DNS_ERROR}'", "./install.sh", None):
            with self.subTest(command=command):
                self.step["run"] = command
                self.assertIsNone(self.resolve())

    def test_wrong_called_job_does_not_select_an_unrelated_jobs_steps(self):
        self.workflow["jobs"]["unrelated"] = self.workflow["jobs"].pop("test")
        self.assertIsNone(self.resolve())

    def test_missing_malformed_duplicate_key_and_oversized_yaml_fail_closed(self):
        raws = (
            b"", b"[]", b"jobs: [invalid", b"\xff", b"jobs: {}\njobs: {}\n",
            b"jobs:\n  test:\n    steps: null\n", b"x" * (recovery.MAX_LOG_BYTES + 1),
        )
        for raw in raws:
            with self.subTest(length=len(raw)):
                self.assertIsNone(self.resolve(raw=raw))

    def test_git_blob_unavailable_never_returns_an_unverified_command(self):
        for error in (OSError("git unavailable"), subprocess.CalledProcessError(128, "git show"), subprocess.TimeoutExpired("git show", 20)):
            with self.subTest(error=error):
                self.process.side_effect = error
                self.assertIsNone(self.resolve())


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.clock = mock.patch.object(recovery.time, "monotonic", return_value=100).start()
        self.addCleanup(mock.patch.stopall)
        self.api = recovery.GitHub(200)

    def response(self, raw, status=0):
        def run(command, **kwargs):
            kwargs["stdout"].write(raw)
            return subprocess.CompletedProcess(command, status, stderr=b"fixture")
        return mock.patch.object(recovery.subprocess, "run", side_effect=run)

    def test_empty_dispatch_response_and_nonempty_issue_post_json(self):
        for raw, expected in ((b"", None), (b'{"number":1079}', {"number": 1079})):
            with self.subTest(raw=raw), self.response(raw) as process:
                self.assertEqual(self.api.api(f"repos/{REPOSITORY}/issues", payload={"title": "fixture"}), expected)
                command = process.call_args.args[0]
                self.assertEqual(command[-4:], ["--method", "POST", "--input", "-"])
                self.assertEqual(json.loads(process.call_args.kwargs["input"]), {"title": "fixture"})

    def test_paginated_response_uses_slurp_and_preserves_all_pages(self):
        raw = b'[{"jobs":[1],"total_count":2},{"jobs":[2],"total_count":2}]'
        with self.response(raw) as process:
            self.assertEqual(self.api.api("fixture", pages=True), json.loads(raw))
        self.assertEqual(process.call_args.args[0][-2:], ["--paginate", "--slurp"])

    def test_raw_log_read_returns_unmodified_bytes(self):
        raw = log_bytes(DNS_ERROR)
        with self.response(raw):
            self.assertEqual(self.api.api("fixture", raw=True), raw)

    def test_invalid_json_utf8_oversize_and_api_errors_fail_closed(self):
        for raw, status in ((b"not json", 0), (b"\xff", 0), (b"x" * (recovery.MAX_LOG_BYTES + 1), 0), (b"{}", 1)):
            with self.subTest(length=len(raw), status=status), self.response(raw, status), self.assertRaises(CONTRACT_ERRORS):
                self.api.api("fixture")

    def test_unavailable_process_and_timeout_are_contract_errors(self):
        for error in (OSError("gh unavailable"), subprocess.TimeoutExpired("gh", 60)):
            with self.subTest(error=error), mock.patch.object(recovery.subprocess, "run", side_effect=error), self.assertRaises(CONTRACT_ERRORS):
                self.api.api("fixture")

    def test_expired_deadline_does_not_start_process(self):
        self.clock.return_value = 201
        with mock.patch.object(recovery.subprocess, "run") as process, self.assertRaises(CONTRACT_ERRORS):
            self.api.api("fixture")
        process.assert_not_called()


class NotificationFixture:
    def __init__(self):
        self.run_id, self.attempt = 123456, 1
        self.orchestration_attempt = 1
        self.title = f"Arm64 smoke run {self.run_id}, attempt {self.attempt}"
        self.run = {
            "id": self.run_id, "run_attempt": self.attempt, "head_sha": SHA,
            "head_branch": BRANCH,
            "path": ".github/workflows/test-all-packages-orchestrator.yml",
            "event": "workflow_dispatch", "status": "in_progress", "conclusion": None,
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
            "created_at": CREATED, "updated_at": UPDATED,
        }
        self.job = {
            "id": 345678, "name": "Trigger and Wait for All Batches",
            "run_id": self.run_id, "run_attempt": 1, "head_sha": SHA,
            "status": "completed", "conclusion": "success",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{self.run_id}/job/345678",
            "started_at": STARTED, "completed_at": COMPLETED,
        }
        self.pages = [{"total_count": 1, "jobs": [self.job]}]
        self.search = {"total_count": 0, "incomplete_results": False, "items": []}
        self.calls, self.posts = [], []

    def api(self, endpoint, *, payload=None, pages=False, raw=False):
        self.calls.append((endpoint, deepcopy(payload), pages, raw))
        if endpoint == f"repos/{REPOSITORY}/actions/runs/{self.run_id}":
            return deepcopy(self.run)
        if endpoint == f"repos/{REPOSITORY}/actions/runs/{self.run_id}/attempts/{self.orchestration_attempt}/jobs?per_page=100":
            if not pages:
                raise AssertionError("notification jobs must be fully paginated")
            return deepcopy(self.pages)
        if endpoint.startswith("search/issues?"):
            query = parse_qs(urlsplit(endpoint).query)
            if "q" not in query or f"repo:{REPOSITORY}" not in query["q"][0]:
                raise AssertionError("notification lookup must be repository-scoped")
            return deepcopy(self.search)
        if endpoint == f"repos/{REPOSITORY}/issues":
            if payload is None:
                raise AssertionError("issue creation needs its payload")
            self.posts.append(deepcopy(payload))
            item = dict(payload, number=1079, user={"login": "github-actions[bot]"}, repository_url=f"https://api.github.com/repos/{REPOSITORY}")
            self.search = {"total_count": 1, "incomplete_results": False, "items": [item]}
            return deepcopy(item)
        raise AssertionError(f"unexpected notification request: {endpoint}")


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = NotificationFixture()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.summary = Path(temporary.name) / "summary.md"
        self.github = mock.patch.object(recovery, "GitHub", return_value=self.fixture).start()
        mock.patch.dict(recovery.os.environ, {"GITHUB_STEP_SUMMARY": str(self.summary)}).start()
        mock.patch.object(recovery.subprocess, "run", side_effect=AssertionError("notification tests must not access GitHub")).start()
        self.addCleanup(mock.patch.stopall)

    def invoke(self, **overrides):
        values = {
            "repository": REPOSITORY, "run-id": str(self.fixture.run_id),
            "run-attempt": str(self.fixture.attempt), "expected-sha": SHA,
            "orchestration-attempt": str(self.fixture.orchestration_attempt),
            "outcome": "success", "recipient": "test-reviewer",
        }
        values.update(overrides)
        argv = ["notify"] + [f"--{key}={value}" for key, value in values.items()]
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            status = recovery.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_rejected(self, **overrides):
        self.fixture.posts.clear()
        status, _, stderr = self.invoke(**overrides)
        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.fixture.posts, [])

    def test_verified_completed_orchestrator_can_notify_while_outer_run_in_progress(self):
        status, stdout, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        self.assertEqual(len(self.fixture.posts), 1)
        body = self.fixture.posts[0]["body"]
        self.assertIn("@test-reviewer", body)
        self.assertIn("All 22", body)
        self.assertIn("Global Summary", body)
        self.assertIn(SHA, body)
        self.assertIn("skips remain skips", body)
        self.assertIn("normal review", body)
        self.assertEqual(self.summary.read_text(), body)
        self.assertIn("Posted", stdout)

    def test_failure_summary_explicitly_does_not_claim_an_automatic_repair_pr(self):
        self.fixture.job["conclusion"] = "failure"
        status, _, stderr = self.invoke(outcome="failure")
        self.assertEqual(status, 0, stderr)
        body = self.fixture.posts[0]["body"]
        self.assertIn("not verified green", body)
        self.assertIn("reviewed repair PR", body)
        self.assertRegex(body.lower(), r"no automatic (?:repair |fix )?pr (?:was |has been )?created|no (?:repair )?pr (?:was |has been )?created automatically")

    def test_notification_only_rerun_reports_original_success(self):
        self.fixture.attempt = 2
        self.fixture.run["run_attempt"] = 2
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.fixture.posts[0]["title"], self.fixture.title)
        self.assertIn("Orchestration attempt: `1`", self.fixture.posts[0]["body"])
        endpoints = [call[0] for call in self.fixture.calls]
        self.assertIn(f"repos/{REPOSITORY}/actions/runs/{self.fixture.run_id}/attempts/1/jobs?per_page=100", endpoints)
        self.assertFalse(any("attempts/2/jobs" in endpoint for endpoint in endpoints))

    def test_notification_only_rerun_does_not_duplicate_original_report(self):
        self.assertEqual(self.invoke()[0], 0)
        for attempt in (2, 3):
            self.fixture.attempt = attempt
            self.fixture.run["run_attempt"] = attempt
            self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(len(self.fixture.posts), 1)

    def test_full_orchestration_rerun_reports_its_new_evidence(self):
        self.assertEqual(self.invoke()[0], 0)
        self.fixture.attempt = self.fixture.orchestration_attempt = 2
        self.fixture.run["run_attempt"] = self.fixture.job["run_attempt"] = 2
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        self.assertEqual(len(self.fixture.posts), 2)
        self.assertEqual(self.fixture.posts[-1]["title"], self.fixture.title.replace("attempt 1", "attempt 2"))

    def test_prior_attempt_must_still_match_sha_identity_and_outcome(self):
        self.fixture.attempt = 2
        self.fixture.run["run_attempt"] = 2
        original = deepcopy(self.fixture.job)
        for field, value in (("head_sha", OTHER_SHA), ("run_id", 999999), ("run_attempt", 2),
                             ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(field=field):
                self.fixture.job.clear()
                self.fixture.job.update(original)
                self.fixture.job[field] = value
                self.assert_rejected()

    def test_future_or_nonpositive_producing_attempt_rejected_before_api(self):
        for attempt in ("0", "-1", "2"):
            with self.subTest(attempt=attempt):
                self.assert_rejected(**{"orchestration-attempt": attempt})
        self.assertEqual(self.fixture.calls, [])

    def test_missing_or_duplicate_orchestrator_job_rejected(self):
        for jobs in ([], [dict(self.fixture.job, name="Some other job")], [self.fixture.job, deepcopy(self.fixture.job)]):
            with self.subTest(jobs=jobs):
                self.fixture.pages = [{"total_count": len(jobs), "jobs": jobs}]
                self.assert_rejected()

    def test_duplicate_orchestrator_job_across_pages_rejected(self):
        self.fixture.pages = [{"total_count": 2, "jobs": [self.fixture.job]}, {"total_count": 2, "jobs": [deepcopy(self.fixture.job)]}]
        self.assert_rejected()

    def test_other_notification_job_may_still_be_running(self):
        other = dict(self.fixture.job, id=345679, name="Notify smoke outcome", status="in_progress", conclusion=None)
        self.fixture.pages = [{"total_count": 2, "jobs": [self.fixture.job]}, {"total_count": 2, "jobs": [other]}]
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)

    def test_incomplete_and_inconsistent_jobs_pagination_rejected(self):
        for pages in ([], [{"total_count": 2, "jobs": [self.fixture.job]}], [{"total_count": 1, "jobs": [self.fixture.job]}, {"total_count": 2, "jobs": []}]):
            with self.subTest(pages=pages):
                self.fixture.pages = pages
                self.assert_rejected()

    def test_job_status_and_conclusion_must_exactly_match_requested_outcome(self):
        for conclusion, outcome in (("failure", "success"), ("success", "failure"), ("cancelled", "failure"), ("failure", "cancelled"), ("skipped", "failure"), (None, "failure"), ("neutral", "failure")):
            with self.subTest(conclusion=conclusion, outcome=outcome):
                self.fixture.job["conclusion"] = conclusion
                self.assert_rejected(outcome=outcome)
        self.fixture.job.update(status="in_progress", conclusion="success")
        self.assert_rejected()

    def test_valid_failure_and_cancellation_outcomes(self):
        for outcome in ("failure", "cancelled"):
            with self.subTest(outcome=outcome):
                self.fixture.job["conclusion"] = outcome
                status, _, stderr = self.invoke(outcome=outcome)
                self.assertEqual(status, 0, stderr)

    def test_wrong_run_identity_sha_branch_workflow_and_repository_rejected(self):
        changes = {
            "id": 999999, "run_attempt": 2, "head_sha": OTHER_SHA,
            "head_branch": "production", "path": ".github/workflows/test-all-packages-summary.yml",
            "repository": {"full_name": "other/repo"},
            "head_repository": {"full_name": "fork/repo"},
        }
        original = deepcopy(self.fixture.run)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.fixture.run = dict(original, **{field: value})
                self.assert_rejected()

    def test_substituted_job_identity_sha_url_and_attempt_rejected(self):
        original = deepcopy(self.fixture.job)
        for field, value in (("id", True), ("id", 0), ("run_id", 999999), ("run_attempt", 2), ("run_attempt", True), ("head_sha", OTHER_SHA), ("html_url", "https://evil.example/jobs/345678")):
            with self.subTest(field=field, value=value):
                self.fixture.job.clear()
                self.fixture.job.update(original)
                self.fixture.job[field] = value
                self.assert_rejected()

    def test_invalid_recipient_and_nonpositive_identity_rejected_without_api_calls(self):
        for recipient in ("", "@test-reviewer", "org/team", "first second", "first\n@second", "delivery[bot]", "-reviewer", "reviewer-", "a" * 40):
            with self.subTest(recipient=recipient):
                self.assert_rejected(recipient=recipient)
        for flag in ("run-id", "run-attempt", "orchestration-attempt"):
            for value in ("0", "-1"):
                with self.subTest(flag=flag, value=value):
                    self.assert_rejected(**{flag: value})
        self.assert_rejected(**{"expected-sha": "not-a-sha"})
        self.assertEqual(self.fixture.calls, [])

    def test_exact_run_attempt_issue_is_idempotent(self):
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(len(self.fixture.posts), 1)
        query = parse_qs(urlsplit([call[0] for call in self.fixture.calls if call[0].startswith("search/issues?")][-1]).query)["q"][0]
        self.assertIn(f"repo:{REPOSITORY}", query)
        self.assertIn("is:issue", query)
        self.assertIn("author:app/github-actions", query)
        self.assertIn(self.fixture.title, query)

    def test_other_attempt_or_author_cannot_suppress_report(self):
        for item in ({"title": self.fixture.title.replace("attempt 1", "attempt 2"), "user": {"login": "github-actions[bot]"}}, {"title": self.fixture.title, "user": {"login": "somebody-else"}}):
            with self.subTest(item=item):
                self.fixture.posts.clear()
                self.fixture.search = {"total_count": 1, "incomplete_results": False, "items": [item]}
                self.assertEqual(self.invoke()[0], 0)
                self.assertEqual(len(self.fixture.posts), 1)

    def test_incomplete_issue_lookup_does_not_create_duplicate_report(self):
        for search in ({"total_count": 1, "incomplete_results": True, "items": []}, {"total_count": 2, "incomplete_results": False, "items": []}):
            with self.subTest(search=search):
                self.fixture.search = search
                self.assert_rejected()

    def test_notification_cli_requires_trusted_sha(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
            recovery.main(["notify", "--repository", REPOSITORY, "--run-id", "123456", "--run-attempt", "1", "--orchestration-attempt", "1", "--outcome", "success", "--recipient", "test-reviewer"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.fixture.calls, [])

    def test_notification_cli_requires_producing_attempt(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
            recovery.main(["notify", "--repository", REPOSITORY, "--run-id", "123456", "--run-attempt", "1", "--expected-sha", SHA, "--outcome", "success", "--recipient", "test-reviewer"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.fixture.calls, [])


if __name__ == "__main__":
    unittest.main()
