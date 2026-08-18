from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "package_workflow_supply_chain.py"
SPEC = importlib.util.spec_from_file_location("package_workflow_supply_chain", SCRIPT)
assert SPEC and SPEC.loader
supply_chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supply_chain)
sys.path.insert(0, str(SCRIPT.parent))
import promote_package_results as promoter  # noqa: E402

FOUNDATION_WORKFLOW = ".github/workflows/exact-run-aggregation-foundation-ci.yml"
SCOPE_GUARD = "if: steps.scope.outputs.relevant == 'true'"
RELEVANT_PATHS = (
    ".github/scripts/download-with-fallback.sh",
    ".github/scripts/package_workflow_action_lock.json",
    ".github/scripts/verify_action_lock_online.py",
    ".github/scripts/package_workflow_supply_chain.py",
    ".github/scripts/exact_run_aggregation.py",
    ".github/scripts/package_result_policy.py",
    ".github/scripts/package_observation.py",
    ".github/scripts/package_observation_migration_audit.py",
    ".github/scripts/promote_package_results.py",
    ".github/scripts/tests/test_package_workflow_supply_chain.py",
    ".github/scripts/tests/test_verify_action_lock_online.py",
    ".github/scripts/tests/test_exact_run_aggregation.py",
    ".github/scripts/tests/test_package_observation.py",
    ".github/scripts/tests/test_package_observation_migration_audit.py",
    ".github/scripts/tests/test_promote_package_results.py",
    ".github/scripts/README-exact-run-aggregation.md",
    ".github/scripts/README-package-observation.md",
    ".github/scripts/requirements-exact-run.txt",
    ".github/actions/**",
    FOUNDATION_WORKFLOW,
    ".github/workflows/test-*.yml",
)


class PackageWorkflowSupplyChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.workflows = supply_chain.registered_workflows(cls.root)
        cls.batches = supply_chain.batch_paths(cls.root)

    def foundation_workflow(self) -> str:
        return (self.root / FOUNDATION_WORKFLOW).read_text(encoding="utf-8")

    def test_xebium_uses_networked_warmup_then_offline_rebuild(self) -> None:
        workflow = (
            self.root / ".github/workflows/test-xebium.yml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^          for ATTEMPT in 1 2 3; do\n(.*?)^          done$",
            workflow,
        )
        self.assertIsNotNone(match)
        retry_body = match.group(1)
        self.assertIn("clean package", retry_body)
        self.assertIn('rm -rf "$WARMUP_DIR"', retry_body)
        self.assertIn(
            'git -C "$NEXT_REPO_DIR" archive --format=tar "$LATEST_COMMIT"',
            retry_body,
        )
        self.assertIn('-v "$WARMUP_DIR:/work"', retry_body)
        self.assertIn('tee "$WARMUP_LOG"', retry_body)
        self.assertNotIn("--network none", retry_body)
        self.assertNotIn('tee "$BUILD_LOG"', retry_body)
        self.assertIn(
            "from package_result_policy import "
            "classify_maven_networked_build_failure",
            retry_body,
        )
        self.assertIn('WARMUP_PIPE_STATUS=("${PIPESTATUS[@]}")', retry_body)
        self.assertIn('WARMUP_TEE_EXIT="${WARMUP_PIPE_STATUS[1]}"', retry_body)
        self.assertIn("return_code=int(sys.argv[2])", retry_body)
        self.assertIn('if [ "$WARMUP_TEE_EXIT" -ne 0 ]', retry_body)
        warmup_index = workflow.index(
            'clean package 2>&1 | tee "$WARMUP_LOG"'
        )
        isolated_container_index = workflow.index(
            "sudo docker run --rm --pull=never --network none"
        )
        offline_build_index = workflow.index("mvn -o -q", isolated_container_index)
        self.assertLess(warmup_index, isolated_container_index)
        self.assertLess(isolated_container_index, offline_build_index)
        clean_source = workflow[warmup_index:isolated_container_index]
        self.assertIn(
            'git -C "$NEXT_REPO_DIR" archive --format=tar "$LATEST_COMMIT"',
            clean_source,
        )
        self.assertIn('test ! -e "$OFFLINE_DIR/.git"', clean_source)
        self.assertIn('-v "$OFFLINE_DIR:/work"', workflow[isolated_container_index:])
        self.assertNotIn('-v "$NEXT_REPO_DIR:/work"', workflow)
        self.assertNotIn('reset --hard', clean_source)
        self.assertNotIn('clean -ffdx', clean_source)
        self.assertIn(
            "-DskipTests clean package",
            workflow[offline_build_index:],
        )
        self.assertIn('tee "$BUILD_LOG"', workflow[offline_build_index:])
        self.assertNotIn("dependency:go-offline", workflow)
        self.assertNotIn('grep -Eiq ', workflow)
        self.assertIn(
            'XEBIUM_BASELINE_COMMIT: "209f4b2b854b9a2ddf66f6ac4625ce167d5c9968"',
            workflow,
        )
        self.assertIn(
            "maven@sha256:"
            "0537e78bbba084ec350fcaa0dedef6efa34440e4e464bbb284f0f1e47043f629",
            workflow,
        )
        self.assertIn("# original: maven:3.9-eclipse-temurin-8", workflow)
        self.assertEqual(
            3, workflow.count('"$PINNED_CONTAINER_IMAGE_MAVEN"')
        )
        self.assertEqual(
            3,
            workflow.count("timeout --signal=TERM --kill-after=30s 10m"),
        )
        self.assertIn('echo "latest_commit=$LATEST_COMMIT"', workflow)
        self.assertIn(
            'git -C "$NEXT_REPO_DIR" fetch --no-tags --depth=1 '
            'origin "$LATEST_COMMIT"',
            workflow,
        )
        self.assertIn('git init --bare "$NEXT_REPO_DIR"', workflow)
        self.assertNotIn("git clone --depth 1 --branch", workflow)
        self.assertNotRegex(workflow, r"jar tf [^\n]+\|")
        self.assertNotRegex(workflow, r"unzip -p [^\n]+\|")
        self.assertEqual(4, workflow.count("unzip -Z1 "))
        metadata_branch = workflow[
            workflow.index('echo "decision=metadata_review_required"') :
            workflow.index('echo "decision=next_install_validated"')
        ]
        self.assertIn('echo "status=skipped"', metadata_branch)
        self.assertIn('STATUS="skipped"', metadata_branch)

    def test_infrastructure_deferral_is_wired_through_publishers(self) -> None:
        decision = "runtime_validation_infrastructure_failure"
        collector = (
            self.root / ".github/actions/collect-batch-results-v2/action.yml"
        ).read_text(encoding="utf-8")
        active_collector = (
            self.root / ".github/actions/collect-batch-results/action.yml"
        ).read_text(encoding="utf-8")
        promoter = (
            self.root / ".github/scripts/promote_package_results.py"
        ).read_text(encoding="utf-8")
        result_policy = (
            self.root / ".github/scripts/package_result_policy.py"
        ).read_text(encoding="utf-8")
        summary = (
            self.root / ".github/workflows/test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")


        self.assertIn(f'"{decision}",', collector)
        self.assertIn(f'if decision == "{decision}":', collector)
        self.assertIn(
            "Next-version validation deferred after a transient "
            "infrastructure failure",
            collector,
        )
        self.assertNotIn("if job_failed and not failed_detail_exists:", collector)
        self.assertNotIn('"name": "Workflow Finalization"', collector)
        self.assertIn("validate_six_test_result(", collector)
        self.assertIn("validate_publishable_result(result_payload)", collector)
        self.assertIn("strict_output_int(", collector)
        self.assertIn("job conclusion contradicts six-test evidence", collector)
        self.assertIn("def validate_persisted_result(", promoter)
        self.assertIn("validate_publishable_result(payload)", promoter)
        self.assertIn("expected_slug=slug", promoter)
        self.assertIn("expected_repository=repository", promoter)
        self.assertIn('publication_role="candidate"', promoter)
        self.assertIn('publication_role="previous"', promoter)
        self.assertIn('validation_policy="strict"', promoter)
        self.assertIn(
            'stage_root / "trusted-registrations.json"', promoter
        )
        self.assertIn("previous_registrations", promoter)
        self.assertIn(
            "previous row lacks an API-verified historical registration",
            promoter,
        )
        self.assertIn(
            "run.status does not match the trusted GitHub job conclusion",
            promoter,
        )
        self.assertIn("trusted GitHub job window", promoter)
        self.assertIn(
            'allow_legacy_missing_decision=validation_policy == "compatibility"',
            promoter,
        )
        self.assertNotIn("published_with_warning", promoter)
        self.assertIn('"state": "retained_previous"', promoter)
        self.assertIn('"state": "blocked_no_previous"', promoter)
        self.assertIn('"state": "blocked_invalid_previous"', promoter)
        self.assertIn("if blocked_count:", promoter)
        self.assertNotIn("safe_single_regression_skip", collector)
        self.assertNotIn("safe_package_manager_skip", collector)
        self.assertNotIn("extract_summary_statuses_from_log", collector)
        self.assertNotIn("fetch_job_log", collector)
        self.assertNotIn("extract_summary_statuses_from_log", active_collector)
        self.assertNotIn("fetch_job_log", active_collector)
        self.assertNotIn("apply_summary_log_statuses", active_collector)
        self.assertNotIn("mark_core_details_failed", active_collector)
        self.assertNotIn("use_detail_counts", active_collector)
        self.assertNotIn("Workflow Finalization", active_collector)
        self.assertIn(
            "required package_slug and run_status outputs are missing",
            collector,
        )
        self.assertIn('"regression_status"', active_collector)
        self.assertIn('"regression_decision"', active_collector)
        self.assertIn(
            "from package_result_policy import expected_regression_metadata",
            active_collector,
        )
        self.assertIn(
            "regression_semantic = expected_regression_metadata(",
            active_collector,
        )
        self.assertIn(
            "python3 .github/scripts/promote_package_results.py",
            summary,
        )
        self.assertIn("--validation-policy compatibility", summary)
        self.assertIn('--repository "$GITHUB_REPOSITORY"', summary)
        self.assertIn(
            '".summary-staging/trusted-registrations.json"', summary
        )
        self.assertIn('"version": 2', summary)
        self.assertIn(
            '"previous_registrations": previous_registrations', summary
        )
        self.assertIn(
            'str(run.get("event") or "") != "workflow_dispatch"',
            summary,
        )
        self.assertIn("TRUSTED_PUBLICATION_BRANCH: main", summary)
        self.assertIn(
            'str(run.get("head_branch") or "")',
            summary,
        )
        self.assertIn(
            'f"{commit_sha}...{trusted_publication_branch}"',
            summary,
        )
        self.assertIn('"ubuntu-24.04-arm" in labels', summary)
        self.assertIn('"self-hosted" not in labels', summary)
        self.assertIn("runner_group_id == 0", summary)
        self.assertIn(
            'runner_group_name == "GitHub Actions"', summary
        )
        self.assertIn(
            'str(job.get("head_sha") or "") == run_head_sha',
            summary,
        )
        self.assertIn(
            'previous_resolution_state == "central_exact"', summary
        )
        self.assertIn(
            "callee_job_name = next(iter(reusable_jobs))", summary
        )
        self.assertIn(
            'expected_api_job_name = f"{job_name} / {callee_job_name}"',
            summary,
        )
        self.assertIn(
            "trusted_job_identity_mismatch:", summary
        )
        self.assertIn(
            "object_pairs_hook=reject_duplicate_keys", summary
        )
        self.assertIn(
            "target_path.write_bytes(source_bytes)", summary
        )
        self.assertNotIn(
            'metadata["package_slug"] = canonical', summary
        )
        self.assertNotIn("def resolve_job_url(", summary)
        self.assertNotIn("def normalize_runner(", summary)
        self.assertIn(
            "Prior rows retained for blocked candidates",
            summary,
        )
        self.assertNotIn("def normalize_payload_status", summary)
        self.assertNotIn("failed = max(0, failed - 1)", summary)
        self.assertNotIn("published_with_warning", summary)
        self.assertNotIn("Candidate rows published with warnings", summary)
        self.assertEqual(
            1, summary.count("promote_package_results.py")
        )
        self.assertIn(
            "cp .summary-staging/publish-index.json",
            summary,
        )
        self.assertNotIn("validate_publishable_result", active_collector)
        self.assertIn(f'"{decision}",', result_policy)
        self.assertIn("def expected_regression_metadata(", result_policy)
        for batch_path in self.batches:
            batch = batch_path.read_text(encoding="utf-8")
            self.assertIn(
                "uses: ./.github/actions/collect-batch-results", batch
            )
            self.assertNotIn("collect-batch-results-v2", batch)

    def test_embedded_python_blocks_compile(self) -> None:
        workflows = (
            (".github/actions/collect-batch-results/action.yml", 1),
            (".github/actions/collect-batch-results-v2/action.yml", 1),
            (".github/workflows/test-all-packages-summary.yml", 2),
        )

        def runs(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "run" and isinstance(child, str):
                        yield child
                    yield from runs(child)
            elif isinstance(value, list):
                for child in value:
                    yield from runs(child)

        marker = "python3 - <<'PY'\n"
        delimiter = "\nPY\n"
        for relative_path, expected_count in workflows:
            workflow = yaml.safe_load(
                (self.root / relative_path).read_text(encoding="utf-8")
            )
            blocks = []
            for run_script in runs(workflow):
                cursor = 0
                while True:
                    marker_index = run_script.find(marker, cursor)
                    if marker_index < 0:
                        break
                    body_start = marker_index + len(marker)
                    body_end = run_script.find(delimiter, body_start)
                    self.assertGreaterEqual(
                        body_end, 0, f"{relative_path}: unterminated heredoc"
                    )
                    body = run_script[body_start:body_end]
                    compile(body, f"{relative_path}:embedded-python", "exec")
                    blocks.append(body)
                    cursor = body_end + len(delimiter)
            self.assertEqual(expected_count, len(blocks), relative_path)

    def test_summary_registration_rejects_branch_and_runner_substitution(
        self,
    ) -> None:
        workflow = yaml.safe_load(
            (
                self.root / ".github/workflows/test-all-packages-summary.yml"
            ).read_text(encoding="utf-8")
        )
        steps = workflow["jobs"]["global-summary"]["steps"]
        assemble = next(
            step
            for step in steps
            if step.get("name")
            == "Assemble candidate and previous-production staging sets"
        )
        marker = "python3 - <<'PY'\n"
        python_source = assemble["run"].split(marker, 1)[1].rsplit(
            "\nPY", 1
        )[0]
        parsed = ast.parse(python_source)
        functions = {
            node.name: node
            for node in parsed.body
            if isinstance(node, ast.FunctionDef)
        }
        selected = ast.Module(
            body=[
                functions["is_trusted_publication_commit"],
                functions["resolve_expected_job"],
            ],
            type_ignores=[],
        )
        ast.fix_missing_locations(selected)

        repository = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
        run_id = "123"
        attempt = "1"
        head_sha = "a" * 40
        workflow_name = "test-all-packages-batch4.yml"
        caller_name = "test-alpha"
        callee_name = "test-alpha"
        job_url = (
            f"https://github.com/{repository}/actions/runs/{run_id}/job/456"
        )
        run = {
            "id": 123,
            "run_attempt": 1,
            "status": "completed",
            "event": "workflow_dispatch",
            "repository": {"full_name": repository},
            "head_repository": {"full_name": repository},
            "path": f".github/workflows/{workflow_name}",
            "head_branch": "main",
            "head_sha": head_sha,
        }
        job = {
            "run_id": 123,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-08-18T04:00:00Z",
            "completed_at": "2026-08-18T04:01:00Z",
            "head_sha": head_sha,
            "name": f"{caller_name} / {callee_name}",
            "html_url": job_url,
            "labels": ["ubuntu-24.04-arm"],
            "runner_group_id": 0,
            "runner_group_name": "GitHub Actions",
        }
        namespace = {
            "json": json,
            "os": os,
            "re": re,
            "subprocess": mock.Mock(),
            "ancestry_cache": {},
            "gh_token": "test-token",
            "github_repository": repository,
            "github_server": "https://github.com",
            "trusted_publication_branch": "main",
            "terminal_job_conclusions": {"success", "failure"},
        }
        exec(compile(selected, "<summary-provenance>", "exec"), namespace)

        compare = namespace["subprocess"].check_output
        compare.return_value = json.dumps(
            {
                "status": "ahead",
                "merge_base_commit": {"sha": head_sha},
            }
        )
        self.assertTrue(namespace["is_trusted_publication_commit"](head_sha))
        namespace["ancestry_cache"].clear()
        compare.return_value = json.dumps(
            {
                "status": "diverged",
                "merge_base_commit": {"sha": "b" * 40},
            }
        )
        self.assertFalse(namespace["is_trusted_publication_commit"](head_sha))

        def resolve(
            *,
            head_branch: str = "main",
            trusted_ancestry: bool = True,
            labels: list[str] | None = None,
            runner_group_id: int | None = 0,
            runner_group_name: str | None = "GitHub Actions",
        ):
            candidate_run = copy.deepcopy(run)
            candidate_run["head_branch"] = head_branch
            candidate_job = copy.deepcopy(job)
            if labels is not None:
                candidate_job["labels"] = labels
            if runner_group_id is None:
                candidate_job.pop("runner_group_id", None)
            else:
                candidate_job["runner_group_id"] = runner_group_id
            if runner_group_name is None:
                candidate_job.pop("runner_group_name", None)
            else:
                candidate_job["runner_group_name"] = runner_group_name
            fetch_jobs = mock.Mock(return_value=[candidate_job])
            namespace["fetch_run"] = mock.Mock(return_value=candidate_run)
            namespace["fetch_jobs"] = fetch_jobs
            namespace["is_trusted_publication_commit"] = mock.Mock(
                return_value=trusted_ancestry
            )
            result = namespace["resolve_expected_job"](
                run_id,
                attempt,
                workflow_name,
                caller_name,
                callee_name,
            )
            return result, fetch_jobs

        result, fetch_jobs = resolve(head_branch="prod-smoke-final")
        self.assertEqual("batch_run_fallback", result[-1])
        fetch_jobs.assert_not_called()

        result, fetch_jobs = resolve(trusted_ancestry=False)
        self.assertEqual("batch_run_fallback", result[-1])
        fetch_jobs.assert_not_called()

        result, _ = resolve(labels=["self-hosted", "ubuntu-24.04-arm"])
        self.assertEqual("batch_run_fallback", result[-1])

        result, _ = resolve(
            labels=["ubuntu-24.04-arm"],
            runner_group_id=9,
            runner_group_name="Internal",
        )
        self.assertEqual("batch_run_fallback", result[-1])

        result, _ = resolve(
            labels=["ubuntu-24.04-arm"],
            runner_group_id=None,
            runner_group_name=None,
        )
        self.assertEqual("batch_run_fallback", result[-1])

        result, _ = resolve(
            labels=["ubuntu-24.04-arm"],
            runner_group_id=0,
            runner_group_name="Internal",
        )
        self.assertEqual("batch_run_fallback", result[-1])

        result, _ = resolve(labels=["ubuntu-24.04-arm"])
        self.assertEqual("central_exact", result[-1])
        self.assertEqual(job_url, result[0])

    def test_active_collector_emits_one_strict_publishable_candidate(self) -> None:
        action = yaml.safe_load(
            (
                self.root / ".github/actions/collect-batch-results/action.yml"
            ).read_text(encoding="utf-8")
        )
        run_script = action["runs"]["steps"][0]["run"]
        marker = "python3 - <<'PY'\n"
        python_source = run_script.split(marker, 1)[1].rsplit("\nPY", 1)[0]

        needs = {
            "test-alpha": {
                "result": "success",
                "outputs": {
                    "contract_version": "2.0",
                    "package_slug": "alpha",
                    "package_name": "Alpha",
                    "package_version": "1.0.0",
                    "run_status": "success",
                    "tests_passed": "6",
                    "tests_failed": "0",
                    "tests_skipped": "0",
                    "core_failed": "0",
                    "duration_seconds": "6",
                    "timestamp": "2026-08-18T04:00:00Z",
                    "dashboard_link": "/linux/opensource_packages/alpha",
                    "job_name": "test-alpha",
                    "regression_policy": "applicable",
                    "regression_status": "passed",
                    "regression_decision": "next_install_validated",
                    "regression_current_version": "1.0.0",
                    "regression_latest_version": "1.1.0",
                    "regression_next_installed_version": "1.1.0",
                    "regression_result": (
                        "Next version installed successfully on Arm64"
                    ),
                    "regression_comparison": (
                        "Version 1.1.0 passed the same bounded checks."
                    ),
                },
            }
        }
        job_url = (
            "https://github.com/example/project/actions/runs/123/job/456"
        )
        steps = []
        for ordinal in range(1, 7):
            steps.append(
                {
                    "name": (
                        f"Test {ordinal} - Regression Validation"
                        if ordinal == 6
                        else f"Test {ordinal} - Baseline"
                    ),
                    "number": ordinal,
                    "conclusion": "success",
                    "started_at": f"2026-08-18T04:00:0{ordinal - 1}Z",
                    "completed_at": f"2026-08-18T04:00:0{ordinal}Z",
                }
            )
        jobs = {
            "jobs": [
                {
                    "id": 456,
                    "name": "test-alpha / test-alpha",
                    "html_url": job_url,
                    "conclusion": "success",
                    "steps": steps,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github" / "scripts").symlink_to(
                self.root / ".github" / "scripts",
                target_is_directory=True,
            )
            output_path = root / "github-output"
            summary_path = root / "github-summary"
            environment = {
                **os.environ,
                "NEEDS_JSON": json.dumps(needs),
                "BATCH_NUMBER": "1",
                "BATCH_TITLE": "Batch 1",
                "GH_TOKEN": "",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "example/project",
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "RUN_JOBS_JSON": json.dumps(jobs),
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_STEP_SUMMARY": str(summary_path),
            }
            subprocess.run(
                [sys.executable, "-c", python_source],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(
                (
                    root
                    / "test-results"
                    / "alpha-test-results"
                    / "alpha.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual("passed", payload["metadata"]["regression_status"])
        self.assertEqual(
            "applicable", payload["metadata"]["regression_applicability"]
        )
        self.assertEqual("validated", payload["metadata"]["regression_reason"])
        promoter.validate_persisted_result(
            payload,
            expected_slug="alpha",
            expected_repository="example/project",
            expected_registration={
                "batch_title": "Batch 1",
                "workflow_path": (
                    ".github/workflows/test-all-packages-batch1.yml"
                ),
                "run_id": "123",
                "run_attempt": "1",
                "job_name": "test-alpha / test-alpha",
                "job_url": job_url,
                "job_conclusion": "success",
                "job_started_at": payload["run"]["timestamp"],
                "job_completed_at": payload["run"]["timestamp"],
                "resolution_status": "central_exact",
            },
            publication_role="candidate",
            validation_policy="strict",
        )

    def assert_foundation_workflow_contract(self, workflow: str) -> None:

        trigger, separator, remainder = workflow.partition("\npermissions:\n")
        self.assertTrue(separator, "top-level permissions must follow the trigger")
        _, on_separator, events = trigger.partition("\non:\n")
        self.assertTrue(on_separator, "workflow must have an event trigger")
        self.assertEqual("  pull_request:", events)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"\binputs\.")
        base_assignments = re.findall(
            r"(?m)^\s+AUTHENTICATED_BASE_COMMIT: (.+)$", workflow
        )
        self.assertEqual(3, len(base_assignments))
        self.assertTrue(
            all(
                value == "${{ github.event.pull_request.base.sha }}"
                for value in base_assignments
            )
        )

        steps = re.findall(
            r"(?ms)^      - name: ([^\n]+)\n(.*?)(?=^      - name: |\Z)",
            remainder,
        )
        self.assertGreaterEqual(len(steps), 3)
        self.assertEqual(
            [
                "Check out candidate without persisted credentials",
                "Detect exact-run scope from authenticated PR base",
            ],
            [name for name, _ in steps[:2]],
        )

        checkout = steps[0][1]
        scope = steps[1][1]
        self.assertNotIn("\n        if:", checkout)
        self.assertNotIn("\n        if:", scope)
        self.assertIn("        id: scope\n", scope)
        self.assertIn(
            "AUTHENTICATED_BASE_COMMIT: "
            "${{ github.event.pull_request.base.sha }}",
            scope,
        )
        self.assertNotIn("github.event.inputs", scope)
        self.assertNotIn("github.sha", scope)
        self.assertIn("git fetch --no-tags --depth=1 origin", scope)
        self.assertIn(
            'git diff --quiet "$AUTHENTICATED_BASE_COMMIT" HEAD', scope
        )
        self.assertIn("diff_status=$?", scope)
        self.assertIn('if [[ "$diff_status" -ne 1 ]]', scope)
        self.assertIn('exit "$diff_status"', scope)
        self.assertEqual(1, scope.count("'relevant=false'"))
        self.assertEqual(1, scope.count("'relevant=true'"))
        _, diff_separator, diff_tail = scope.partition(
            'if git diff --quiet "$AUTHENTICATED_BASE_COMMIT" HEAD -- \\\n'
        )
        self.assertTrue(diff_separator, "scope must diff the authenticated base")
        path_block, then_separator, _ = diff_tail.partition("; then")
        self.assertTrue(then_separator, "scope diff must have an explicit result branch")
        diff_paths = tuple(
            line.strip().removesuffix("\\").strip().strip("'")
            for line in path_block.splitlines()
        )
        self.assertEqual(RELEVANT_PATHS, diff_paths)

        step_map = dict(steps)
        source_fetch = step_map.get("Fetch reviewed package workflow source")
        self.assertIsNotNone(source_fetch)
        assert source_fetch is not None
        self.assertIn(
            f"REVIEWED_SOURCE_COMMIT: {supply_chain.SOURCE_COMMIT}",
            source_fetch,
        )
        self.assertIn(
            'git fetch --no-tags --depth=1 origin "$REVIEWED_SOURCE_COMMIT"',
            source_fetch,
        )
        step_names = [name for name, _ in steps]
        self.assertLess(
            step_names.index("Fetch reviewed package workflow source"),
            step_names.index("Run adversarial contract tests"),
        )

        presence = step_map.get("Confirm migration audit sources are present")
        self.assertIsNotNone(presence)
        assert presence is not None
        for source in (
            ".github/scripts/package_observation_migration_audit.py",
            ".github/scripts/tests/test_package_observation_migration_audit.py",
        ):
            self.assertIn(source, presence)
        self.assertIn('test -f "$source"', presence)
        self.assertIn('test ! -L "$source"', presence)

        for name, body in steps[2:]:
            self.assertEqual(
                1,
                body.count(f"        {SCOPE_GUARD}\n"),
                f"{name!r} must use the exact fail-closed scope guard",
            )

    def test_registration_is_exact(self) -> None:
        relative = [path.relative_to(self.root).as_posix() for path in self.workflows]
        self.assertEqual(960, len(relative))
        self.assertEqual(960, len(set(relative)))
        self.assertTrue(all(path.is_file() for path in self.workflows))
        self.assertFalse(
            any("test-all-packages-" in Path(path).name for path in relative)
        )

    def test_inventory_has_no_unresolved_reference(self) -> None:
        lock = supply_chain.load_lock(self.root)
        self.assertEqual([], lock["unresolved_references"])
        self.assertEqual(supply_chain.SOURCE_COMMIT, lock["source_commit"])
        self.assertEqual(1130, lock["external_uses"])
        self.assertEqual(4, lock["container_uses"])
        self.assertEqual(15, len(lock["actions"]))
        self.assertRegex(
            lock["migration_parent_workflow_sha256"],
            r"^[0-9a-f]{64}$",
        )
        transition = lock["hardened_workflow_transition"]
        self.assertEqual(
            "8e29c5376045fdc6cb2a5b4ecfd4f16a4b22aef88db6aa8d820300034cf1ec6e",
            transition["from_sha256"],
        )
        self.assertEqual(
            lock["hardened_workflow_sha256"],
            transition["to_sha256"],
        )
        self.assertTrue(transition["reason"].strip())
        self.assertEqual(4, len(lock["containers"]))
        for entry in lock["actions"]:
            self.assertTrue(entry["github_api_repository_confirmed"])
            self.assertTrue(entry["github_api_commit_confirmed"])
            self.assertTrue(entry["action_file_confirmed_at_commit"])
            self.assertTrue(entry["git_ls_remote"]["matches_github_api"])
            self.assertRegex(entry["resolved_commit"], r"^[0-9a-f]{40}$")
            verification = entry["github_commit_verification"]
            self.assertIn(verification["verified"], (True, False))
            self.assertIsInstance(verification["reason"], str)
        for entry in lock["containers"]:
            self.assertTrue(entry["linux_arm64_confirmed"])
            self.assertRegex(entry["resolved_digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(entry["arm64_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_action_identity_substitution_is_rejected(self) -> None:
        lock = supply_chain.load_lock(self.root)
        entry = copy.deepcopy(lock["actions"][0])
        entry["repository"] = "attacker/substituted-action"
        with self.assertRaisesRegex(
            supply_chain.ContractError, "identity evidence contradicts"
        ):
            supply_chain.validate_action_lock_entry(entry)

    def test_container_repository_substitution_is_rejected(self) -> None:
        lock = supply_chain.load_lock(self.root)
        entry = copy.deepcopy(lock["containers"][0])
        entry["repository"] = "attacker/substituted-image"
        entry["resolved_ref"] = (
            f"{entry['repository']}@{entry['resolved_digest']}"
        )
        with self.assertRaisesRegex(
            supply_chain.ContractError, "invalid container lock entry"
        ):
            supply_chain.validate_container_lock_entry(entry)

    def test_stale_reviewed_base_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            supply_chain.ContractError, "authenticated pull-request base"
        ):
            supply_chain.validate_hardening(
                self.root, expected_base_commit="0" * 40
            )

    def test_legitimate_advanced_hardened_base_is_accepted(self) -> None:
        head = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        self.assertNotEqual(supply_chain.SOURCE_COMMIT, head)
        result = supply_chain.validate_hardening(
            self.root, expected_base_commit=head
        )
        self.assertEqual(
            "4b856e18e35d49acef2ab571b49f8ff60ec4f4c0eaf4ce3182563d7738d05300",
            result["workflow_sha256"],
        )

    def test_malformed_hardened_transitions_are_rejected(self) -> None:
        base_lock = supply_chain.load_lock(self.root)
        current = base_lock["hardened_workflow_sha256"]
        valid_from = "a" * 64
        adversarial = (
            {},
            {"from_sha256": valid_from, "to_sha256": current},
            {
                "from_sha256": valid_from,
                "to_sha256": "b" * 64,
                "reason": "Target does not match the candidate digest.",
            },
            {
                "from_sha256": current,
                "to_sha256": current,
                "reason": "A no-op transition is not valid.",
            },
            {
                "from_sha256": valid_from,
                "to_sha256": current,
                "reason": "   ",
            },
            {
                "from_sha256": valid_from,
                "to_sha256": current,
                "reason": "x" * 513,
            },
        )
        for transition in adversarial:
            with self.subTest(transition=transition):
                lock = copy.deepcopy(base_lock)
                lock["hardened_workflow_transition"] = transition
                with self.assertRaises(supply_chain.ContractError):
                    supply_chain.validate_hardened_workflow_transition(lock)

    def test_declared_hardened_transition_source_is_accepted(self) -> None:
        lock = copy.deepcopy(supply_chain.load_lock(self.root))
        paths = [*self.workflows, *self.batches]
        snapshot = {"synthetic-reviewed-workflows": b"prior reviewed snapshot"}
        transition_source = supply_chain.workflow_snapshot_sha256(snapshot)
        lock["hardened_workflow_transition"] = {
            "from_sha256": transition_source,
            "to_sha256": lock["hardened_workflow_sha256"],
            "reason": "Exercise the explicit reviewed maintenance transition.",
        }
        with mock.patch.object(
            supply_chain, "source_snapshot", return_value=snapshot
        ):
            self.assertEqual(
                "declared_hardened_transition_source",
                supply_chain.validate_authenticated_base(
                    self.root, paths, lock, "f" * 40
                ),
            )

    def test_modified_advanced_base_snapshot_is_rejected(self) -> None:
        lock = supply_chain.load_lock(self.root)
        paths = [*self.workflows, *self.batches]
        snapshot = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in paths
        }
        first = min(snapshot)
        snapshot[first] += b"\n"
        with mock.patch.object(
            supply_chain, "source_snapshot", return_value=snapshot
        ):
            with self.assertRaisesRegex(
                supply_chain.ContractError,
                "does not match the current or declared transition source",
            ):
                supply_chain.validate_authenticated_base(
                    self.root, paths, lock, "f" * 40
                )

    def test_foundation_check_has_an_always_on_pull_request_trigger(self) -> None:
        workflow = self.foundation_workflow()
        self.assert_foundation_workflow_contract(workflow)

        filtered = workflow.replace(
            "  pull_request:\n",
            "  pull_request:\n    paths:\n      - '.github/scripts/**'\n",
            1,
        )
        with self.assertRaises(AssertionError):
            self.assert_foundation_workflow_contract(filtered)

    def test_foundation_check_rejects_dispatch_or_input_fallback(self) -> None:
        workflow = self.foundation_workflow()
        self.assert_foundation_workflow_contract(workflow)

        dispatch = workflow.replace(
            "  pull_request:\n", "  pull_request:\n  workflow_dispatch:\n", 1
        )
        fallback = workflow.replace(
            "${{ github.event.pull_request.base.sha }}",
            "${{ github.event.pull_request.base.sha "
            "|| inputs.reviewed_source_commit }}",
            1,
        )
        for adversarial_workflow in (dispatch, fallback):
            with self.subTest(workflow=adversarial_workflow):
                with self.assertRaises(AssertionError):
                    self.assert_foundation_workflow_contract(adversarial_workflow)

    def test_foundation_expensive_steps_require_exact_scope_guard(self) -> None:
        workflow = self.foundation_workflow()
        self.assert_foundation_workflow_contract(workflow)

        unguarded = workflow.replace(f"        {SCOPE_GUARD}\n", "", 1)
        weakened = workflow.replace(
            f"        {SCOPE_GUARD}\n", "        if: always()\n", 1
        )
        for adversarial_workflow in (unguarded, weakened):
            with self.subTest(workflow=adversarial_workflow):
                with self.assertRaises(AssertionError):
                    self.assert_foundation_workflow_contract(adversarial_workflow)

    def test_publisher_ci_fetches_reviewed_source_before_full_suite(self) -> None:
        workflow = (
            self.root
            / ".github/workflows/generated-data-publisher-foundation-ci.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            1, workflow.count("      - name: Fetch reviewed package workflow source")
        )
        self.assertIn(
            f"REVIEWED_SOURCE_COMMIT: {supply_chain.SOURCE_COMMIT}",
            workflow,
        )
        self.assertIn(
            'git fetch --no-tags --depth=1 origin "$REVIEWED_SOURCE_COMMIT"',
            workflow,
        )
        self.assertLess(
            workflow.index("      - name: Fetch reviewed package workflow source"),
            workflow.index("      - name: Run generated site data artifact tests"),
        )
        self.assertIn("          fetch-depth: 2\n", workflow)
        self.assertIn("          persist-credentials: false\n", workflow)
        self.assertNotIn("          fetch-depth: 0\n", workflow)


    def test_every_external_use_is_immutable(self) -> None:
        external = 0
        for path in [*self.workflows, *self.batches]:
            for _, match in supply_chain.iter_uses(path):
                spec = match.group("spec")
                if spec.startswith("./"):
                    continue
                external += 1
                if spec.startswith("docker://"):
                    self.assertRegex(spec, r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
                    continue
                _, _, _, ref = supply_chain.split_github_action(spec)
                self.assertRegex(ref, r"^[0-9a-f]{40}$")
        self.assertEqual(1130, external)

    def test_every_checkout_disables_persisted_credentials(self) -> None:
        checkouts = 0
        for path in [*self.workflows, *self.batches]:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            for index, line in enumerate(lines):
                match = supply_chain.USES_RE.match(line)
                if not match:
                    continue
                spec = match.group("spec")
                if spec.startswith(("./", "docker://")):
                    continue
                _, owner_repo, _, _ = supply_chain.split_github_action(spec)
                if owner_repo.lower() != "actions/checkout":
                    continue
                checkouts += 1
                self.assertTrue(
                    supply_chain._checkout_has_disabled_credentials(
                        lines, index, match
                    ),
                    path.relative_to(self.root).as_posix(),
                )
        self.assertEqual(982, checkouts)

    def test_permissions_are_read_only(self) -> None:
        exceptions = supply_chain.permission_exceptions(
            supply_chain.load_lock(self.root)
        )
        for path in self.workflows:
            lines = path.read_text(encoding="utf-8").splitlines()
            supply_chain._validate_permissions(self.root, path, lines, exceptions)
            for index, line in enumerate(lines):
                if not line.lstrip().startswith("permissions:"):
                    continue
                values = supply_chain._permission_values(lines, index)
                self.assertTrue(
                    all(value.endswith(": read") for value in values),
                    path.relative_to(self.root).as_posix(),
                )
        forwarded: set[str] = set()
        for path in self.batches:
            lines = path.read_text(encoding="utf-8").splitlines()
            forwarded.update(
                supply_chain._validate_batch_permissions(
                    self.root,
                    path,
                    lines,
                    exceptions,
                )
            )
        self.assertEqual(set(exceptions), forwarded)

        permissioned_batch = self.root / ".github/workflows/test-all-packages-batch21.yml"
        unsafe = permissioned_batch.read_text(encoding="utf-8").replace(
            "      packages: read\n",
            "      packages: write\n",
            1,
        )
        with self.assertRaises(supply_chain.ContractError):
            supply_chain._validate_batch_permissions(
                self.root,
                permissioned_batch,
                unsafe.splitlines(),
                exceptions,
            )

    def test_every_container_is_digest_pinned(self) -> None:
        lock = supply_chain.load_lock(self.root)
        containers = supply_chain.container_lock_by_workflow(lock)
        self.assertEqual(4, len(containers))
        for relative, entry in containers.items():
            text = (self.root / relative).read_text(encoding="utf-8")
            self.assertIn(entry["resolved_ref"], text)
            self.assertIn(f"# original: {entry['original_ref']}", text)

    def test_complete_offline_contract(self) -> None:
        self.assertEqual(
            {
                "registered_workflows": 960,
                "batch_workflows": 22,
                "external_uses": 1130,
                "container_uses": 4,
                "unique_original_refs": 15,
                "checkout_uses": 982,
                "permission_exceptions": 4,
                "topology_sha256": "dd3b2c7547600d99769b0f8aabf4ca8057334a3ab70e473de59af21750adb69b",
                "workflow_sha256": "4b856e18e35d49acef2ab571b49f8ff60ec4f4c0eaf4ce3182563d7738d05300",
            },
            supply_chain.validate_hardening(
                self.root,
                expected_base_commit=subprocess.run(
                    ["git", "-C", str(self.root), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip(),
            ),
        )


if __name__ == "__main__":
    unittest.main()
