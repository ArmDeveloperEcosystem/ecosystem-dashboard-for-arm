from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import exact_run_aggregation as exact  # noqa: E402
import package_observation as observation  # noqa: E402
import package_result_policy as result_policy  # noqa: E402


class PackageObservationTests(unittest.TestCase):
    def test_maven_networked_build_transient_failures_are_explicit(self) -> None:
        transient_logs = (
            (
                "[ERROR] Failed to execute goal example:plugin:goal on project alpha: "
                "Could not resolve dependencies\n"
                "[ERROR] Could not transfer artifact example:dep:jar:1.0: "
                "status code: 503\n"
                "[ERROR] -> [Help 1]"
            ),
            (
                "[ERROR] Failed to read artifact descriptor for example:dep:jar:1.0\n"
                "[ERROR] Could not transfer artifact example:dep:pom:1.0: "
                "Connection reset\n"
                "[ERROR] Re-run Maven using the -X switch"
            ),
            (
                "\x1b[31m[ERROR]\x1b[0m Could not collect dependencies: "
                "java.net.UnknownHostException: repo.maven.apache.org\n"
                "[ERROR] -> [Help 1]"
            ),
        )
        for log in transient_logs:
            with self.subTest(log=log):
                self.assertEqual(
                    "transient_infrastructure",
                    result_policy.classify_maven_networked_build_failure(
                        log, return_code=1
                    ),
                )

    def test_maven_networked_build_mixed_or_permanent_failures_stay_red(self) -> None:
        package_failures = (
            ("Connection reset\nCould not find artifact com.example:missing:jar:1.0", 1),
            ("Repository returned status code: 503\nstatus code: 404", 1),
            ("Connection reset\nCOMPILATION ERROR: cannot find symbol", 1),
            (
                (
                    "Connection reset\n"
                    "[ERROR] Failed to execute goal example:plugin:goal\n"
                    "[ERROR] Unexpected package build defect"
                ),
                1,
            ),
            (
                (
                    "Repository returned status code: 503\n"
                    "[ERROR] Failed to execute goal example:plugin:goal"
                ),
                1,
            ),
            (
                (
                    "Connection reset\n"
                    "\x1b[31m[ERROR]\x1b[0m Unexpected package build defect"
                ),
                1,
            ),
            (
                (
                    "[ERROR] Failed to execute goal example:custom-goal:run: "
                    "unrelated endpoint returned status code: 503"
                ),
                1,
            ),
            ("[ERROR] Could not transfer artifact: Connection reset", 124),
            ("[ERROR] Could not transfer artifact: Connection reset", 125),
            ("[ERROR] Could not transfer artifact: Connection reset", 137),
            ("[ERROR] Could not transfer artifact: Connection reset", 0),
            ("PKIX path building failed", 1),
            ("No space left on device", 1),
            ("java.lang.OutOfMemoryError", 1),
            ("Command timed out after 600 seconds", 1),
            (b"contains-nul\x00data", 1),
            ("Non-resolvable parent POM", 1),
            ("COMPILATION ERROR: cannot find symbol", 1),
            ("", 1),
            (b"not-utf8-\xff", 1),
        )
        for log, return_code in package_failures:
            with self.subTest(log=log, return_code=return_code):
                self.assertEqual(
                    "package_failure",
                    result_policy.classify_maven_networked_build_failure(
                        log, return_code=return_code
                    ),
                )

    def test_non_failing_regression_cannot_erase_unproven_failures(self) -> None:
        result_policy.validate_aggregate_failure_counts(
            failed=0, core_failed=0, non_failing_regression=True
        )
        result_policy.validate_aggregate_failure_counts(
            failed=2, core_failed=2, non_failing_regression=True
        )
        result_policy.validate_aggregate_failure_counts(
            failed=1, core_failed=0, non_failing_regression=False
        )
        contradictory = (
            {"failed": 1, "core_failed": 0, "non_failing_regression": True},
            {"failed": 2, "core_failed": 1, "non_failing_regression": True},
            {"failed": 0, "core_failed": 1, "non_failing_regression": False},
            {"failed": -1, "core_failed": 0, "non_failing_regression": False},
            {"failed": True, "core_failed": 0, "non_failing_regression": False},
        )
        for values in contradictory:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    result_policy.validate_aggregate_failure_counts(**values)

    @staticmethod
    def _six_details(
        statuses: list[str], decision: str = "next_install_validated"
    ) -> list[dict[str, object]]:
        details = []
        for ordinal, status in enumerate(statuses, start=1):
            detail: dict[str, object] = {
                "name": f"Test {ordinal} - Evidence check",
                "status": status,
                "duration_seconds": ordinal,
            }
            if ordinal == 6:
                detail["decision"] = decision
            details.append(detail)
        return details

    def test_six_test_result_accepts_only_coherent_lanes(self) -> None:
        cases = (
            (["passed"] * 6, 6, 0, 0, 0, "next_install_validated", "success"),
            (
                ["passed"] * 5 + ["failed"],
                5,
                1,
                0,
                0,
                "next_install_failed",
                "failure",
            ),
            (
                ["passed"] * 5 + ["skipped"],
                5,
                0,
                1,
                0,
                "runtime_validation_infrastructure_failure",
                "success",
            ),
            (
                ["failed"] + ["passed"] * 4 + ["skipped"],
                4,
                1,
                1,
                1,
                "baseline_failed",
                "failure",
            ),
        )
        for statuses, passed, failed, skipped, core_failed, decision, expected in cases:
            with self.subTest(decision=decision):
                self.assertEqual(
                    expected,
                    result_policy.validate_six_test_result(
                        details=self._six_details(statuses, decision),
                        passed=passed,
                        failed=failed,
                        skipped=skipped,
                        core_failed=core_failed,
                        decision=decision,
                    ),
                )

    def test_six_test_result_rejects_counter_and_policy_contradictions(self) -> None:
        deferred = self._six_details(
            ["passed"] * 5 + ["skipped"],
            "runtime_validation_infrastructure_failure",
        )
        contradictions = (
            (deferred, 5, 1, 0, 0, "runtime_validation_infrastructure_failure"),
            (deferred, 5, 0, 1, 1, "runtime_validation_infrastructure_failure"),
            (
                self._six_details(["passed"] * 5 + ["failed"]),
                5,
                1,
                0,
                0,
                "runtime_validation_infrastructure_failure",
            ),
            (
                self._six_details(
                    ["failed"] + ["passed"] * 5,
                    "next_install_validated",
                ),
                5,
                1,
                0,
                1,
                "next_install_validated",
            ),
        )
        for details, passed, failed, skipped, core_failed, decision in contradictions:
            with self.subTest(decision=decision):
                with self.assertRaises(ValueError):
                    result_policy.validate_six_test_result(
                        details=details,
                        passed=passed,
                        failed=failed,
                        skipped=skipped,
                        core_failed=core_failed,
                        decision=decision,
                    )

    def test_six_test_result_rejects_missing_duplicate_or_extra_details(self) -> None:
        valid = self._six_details(["passed"] * 6)
        malformed = (
            valid[:5],
            valid + [dict(valid[-1])],
            [*valid[:4], valid[5], valid[5]],
        )
        for details in malformed:
            with self.subTest(detail_count=len(details)):
                with self.assertRaises(ValueError):
                    result_policy.validate_six_test_result(
                        details=details,
                        passed=6,
                        failed=0,
                        skipped=0,
                        core_failed=0,
                        decision="next_install_validated",
                    )

    def _publishable_result(
        self, statuses: list[str], decision: str, core_failed: int
    ) -> dict[str, object]:
        semantic = result_policy.expected_regression_metadata(
            decision=decision, core_failed=core_failed
        )
        counts = {
            status: statuses.count(status)
            for status in ("passed", "failed", "skipped")
        }
        return {
            "run": {"status": semantic["run_status"]},
            "tests": {
                **counts,
                "details": self._six_details(statuses, decision),
            },
            "metadata": {
                "core_failed": core_failed,
                "badge_status": (
                    "passing"
                    if semantic["run_status"] == "success"
                    else "failing"
                ),
                "regression_status": semantic["status"],
                "regression_decision": decision,
                "regression_applicability": semantic["applicability"],
                "regression_reason": semantic["reason"],
            },
        }

    def test_publishable_result_accepts_explicit_semantic_lanes(self) -> None:
        cases = (
            (["passed"] * 6, "next_install_validated", 0, "success"),
            (
                ["passed"] * 5 + ["failed"],
                "next_install_failed",
                0,
                "failure",
            ),
            (
                ["passed"] * 5 + ["skipped"],
                "runtime_validation_infrastructure_failure",
                0,
                "success",
            ),
            (
                ["failed"] + ["passed"] * 4 + ["skipped"],
                "baseline_failed",
                1,
                "failure",
            ),
        )
        for statuses, decision, core_failed, expected in cases:
            with self.subTest(decision=decision):
                payload = self._publishable_result(
                    statuses, decision, core_failed
                )
                self.assertEqual(
                    expected,
                    result_policy.validate_publishable_result(payload),
                )

    def test_publishable_result_rejects_untrusted_repairs_and_metadata(self) -> None:
        base = self._publishable_result(
            ["passed"] * 5 + ["skipped"],
            "runtime_validation_infrastructure_failure",
            0,
        )
        adversarial = []
        malformed_counter = copy.deepcopy(base)
        malformed_counter["tests"]["failed"] = "0"
        adversarial.append(malformed_counter)
        wrong_semantic_status = copy.deepcopy(base)
        wrong_semantic_status["metadata"]["regression_status"] = "skipped"
        adversarial.append(wrong_semantic_status)
        wrong_applicability = copy.deepcopy(base)
        wrong_applicability["metadata"]["regression_applicability"] = "not_applicable"
        adversarial.append(wrong_applicability)
        wrong_reason = copy.deepcopy(base)
        wrong_reason["metadata"]["regression_reason"] = "validated"
        adversarial.append(wrong_reason)
        wrong_run = copy.deepcopy(base)
        wrong_run["run"]["status"] = "failure"
        adversarial.append(wrong_run)
        wrong_badge = copy.deepcopy(base)
        wrong_badge["metadata"]["badge_status"] = "failing"
        adversarial.append(wrong_badge)
        misplaced_decision = copy.deepcopy(base)
        misplaced_decision["tests"]["details"][0]["decision"] = (
            "runtime_validation_infrastructure_failure"
        )
        adversarial.append(misplaced_decision)
        mismatched_decision = copy.deepcopy(base)
        mismatched_decision["tests"]["details"][5]["decision"] = (
            "next_install_validated"
        )
        adversarial.append(mismatched_decision)

        for payload in adversarial:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    result_policy.validate_publishable_result(payload)

    def test_infrastructure_decision_normalizes_to_deferred(self) -> None:
        payload = self._build(lane="deferred")
        payload["regression"]["decision"] = (
            "runtime_validation_infrastructure_failure"
        )
        payload["regression"]["reason"] = (
            "runtime_validation_infrastructure_failure"
        )
        normalized = observation.validate_observation(payload)
        self.assertEqual("deferred", normalized["regression"]["status"])
        self.assertEqual("success", normalized["outcome"]["run_status"])

    def _build(self, *, lane: str = "passed") -> dict[str, object]:
        statuses = ["passed"] * 6
        decision = "next_install_validated"
        run_status = "success"
        badge_status = "passing"
        core_failed = 0
        if lane == "failed":
            statuses[5] = "failed"
            decision = "next_install_failed"
            run_status = "failure"
            badge_status = "failing"
        elif lane == "deferred":
            statuses[5] = "skipped"
            decision = "runtime_validation_not_automated"
        elif lane == "not_applicable":
            statuses[5] = "skipped"
            decision = "current_is_latest_stable"
        elif lane == "baseline_failed":
            statuses[0] = "failed"
            statuses[5] = "skipped"
            decision = "baseline_failed"
            run_status = "failure"
            badge_status = "failing"
            core_failed = 1
        details = [
            {
                "name": f"Test {ordinal} - Evidence check",
                "status": status,
                "duration_seconds": ordinal,
            }
            for ordinal, status in enumerate(statuses, start=1)
        ]
        counts = {
            status: statuses.count(status) for status in ("passed", "failed", "skipped")
        }
        return observation.build_observation(
            package_slug="alpha",
            package_name="Alpha",
            package_version="1.2.3",
            run_status=run_status,
            badge_status=badge_status,
            core_failed=core_failed,
            tests_passed=counts["passed"],
            tests_failed=counts["failed"],
            tests_skipped=counts["skipped"],
            duration_seconds=sum(range(1, 7)),
            test_details=details,
            regression_decision=decision,
            regression_current_version="1.2.3",
            regression_latest_version="1.3.0",
            regression_next_installed_version=(
                "1.3.0" if lane == "passed" else "not_installed"
            ),
            regression_result="Arm64 regression validation produced an explicit result.",
            regression_comparison=(
                "The baseline and candidate evidence were compared explicitly on Arm64."
            ),
        )

    def test_passed_observation_is_canonical_and_deterministic(self) -> None:
        payload = self._build()
        self.assertEqual("Alpha", payload["package"]["name"])
        self.assertEqual("passed", payload["regression"]["status"])
        self.assertEqual("validated", payload["regression"]["reason"])
        self.assertEqual("success", payload["outcome"]["run_status"])
        encoded = observation.canonical_json(payload)
        self.assertEqual(payload, observation.validate_observation(json.loads(encoded)))
        self.assertNotIn("run_id", encoded)
        self.assertNotIn("job_url", encoded)

    def test_approved_deferred_lane_is_success_with_raw_skip(self) -> None:
        payload = self._build(lane="deferred")
        self.assertEqual("deferred", payload["regression"]["status"])
        self.assertEqual("applicable", payload["regression"]["applicability"])
        self.assertEqual("skipped", payload["tests"]["details"][5]["status"])
        self.assertEqual({"passed": 5, "failed": 0, "skipped": 1}, {
            key: payload["tests"][key] for key in ("passed", "failed", "skipped")
        })

    def test_approved_not_applicable_lane_is_success_with_raw_skip(self) -> None:
        payload = self._build(lane="not_applicable")
        self.assertEqual("not_applicable", payload["regression"]["status"])
        self.assertEqual("not_applicable", payload["regression"]["applicability"])
        self.assertEqual("passing", payload["outcome"]["badge_status"])

    def test_failed_regression_fails_observation(self) -> None:
        payload = self._build(lane="failed")
        self.assertEqual("failed", payload["regression"]["status"])
        self.assertEqual("failure", payload["outcome"]["run_status"])
        self.assertEqual("failing", payload["outcome"]["badge_status"])

    def test_baseline_failure_requires_explicit_baseline_decision(self) -> None:
        payload = self._build(lane="baseline_failed")
        self.assertEqual("skipped", payload["regression"]["status"])
        self.assertEqual(1, payload["outcome"]["core_failed"])
        self.assertEqual("failure", payload["outcome"]["run_status"])

    def test_unknown_decision_is_rejected(self) -> None:
        payload = self._build()
        payload["regression"]["decision"] = "looks_good"
        with self.assertRaisesRegex(observation.ObservationError, "unapproved"):
            observation.validate_observation(payload)

    def test_status_decision_contradiction_is_rejected(self) -> None:
        payload = self._build(lane="deferred")
        payload["tests"]["details"][5]["status"] = "passed"
        payload["tests"]["passed"] = 6
        payload["tests"]["skipped"] = 0
        with self.assertRaisesRegex(observation.ObservationError, "contradicts"):
            observation.validate_observation(payload)

    def test_counter_repair_is_forbidden(self) -> None:
        payload = self._build()
        payload["tests"]["passed"] = 5
        payload["tests"]["skipped"] = 1
        with self.assertRaisesRegex(observation.ObservationError, "counters"):
            observation.validate_observation(payload)

    def test_duration_repair_is_forbidden(self) -> None:
        payload = self._build()
        payload["tests"]["duration_seconds"] = 0
        with self.assertRaisesRegex(observation.ObservationError, "duration"):
            observation.validate_observation(payload)

    def test_baseline_skip_is_rejected(self) -> None:
        payload = self._build()
        payload["tests"]["details"][0]["status"] = "skipped"
        payload["tests"]["passed"] = 5
        payload["tests"]["skipped"] = 1
        with self.assertRaisesRegex(observation.ObservationError, "unsupported"):
            observation.validate_observation(payload)

    def test_core_failure_count_must_match_baseline_details(self) -> None:
        payload = self._build()
        payload["outcome"]["core_failed"] = 1
        with self.assertRaisesRegex(observation.ObservationError, "core_failed"):
            observation.validate_observation(payload)

    def test_success_cannot_hide_failed_evidence(self) -> None:
        payload = self._build(lane="failed")
        payload["outcome"]["run_status"] = "success"
        payload["outcome"]["badge_status"] = "passing"
        with self.assertRaisesRegex(observation.ObservationError, "outcome contradicts"):
            observation.validate_observation(payload)

    def test_placeholder_package_version_is_rejected(self) -> None:
        payload = self._build()
        payload["package"]["version"] = "unknown"
        payload["regression"]["current_version"] = "unknown"
        with self.assertRaisesRegex(observation.ObservationError, "placeholder"):
            observation.validate_observation(payload)

    def test_noncanonical_dashboard_route_is_rejected(self) -> None:
        payload = self._build()
        payload["package"]["dashboard_link"] = "/opensource_packages/alpha"
        with self.assertRaisesRegex(observation.ObservationError, "canonical route"):
            observation.validate_observation(payload)

    def test_noncanonical_test_label_is_rejected(self) -> None:
        payload = self._build()
        payload["tests"]["details"][2]["name"] = "Architecture check"
        with self.assertRaisesRegex(observation.ObservationError, "is not Test 3"):
            observation.validate_observation(payload)

    def test_non_nfc_text_is_rejected(self) -> None:
        payload = self._build()
        payload["package"]["name"] = "Cafe\u0301"
        with self.assertRaisesRegex(observation.ObservationError, "NFC"):
            observation.validate_observation(payload)

    def test_current_version_must_equal_baseline_version(self) -> None:
        payload = self._build()
        payload["regression"]["current_version"] = "1.2.2"
        with self.assertRaisesRegex(observation.ObservationError, "current_version"):
            observation.validate_observation(payload)

    def test_placeholder_narrative_is_rejected(self) -> None:
        payload = self._build()
        payload["regression"]["comparison"] = (
            "Regression comparison summary unavailable."
        )
        with self.assertRaisesRegex(observation.ObservationError, "actual validation"):
            observation.validate_observation(payload)

    def test_extra_fields_are_rejected(self) -> None:
        payload = self._build()
        payload["producer_run_id"] = "123"
        with self.assertRaisesRegex(observation.ObservationError, "unexpected keys"):
            observation.validate_observation(payload)

    def test_boolean_schema_version_is_rejected(self) -> None:
        payload = self._build()
        payload["version"] = True
        with self.assertRaisesRegex(observation.ObservationError, "version"):
            observation.validate_observation(payload)

    def test_boolean_test_ordinal_is_rejected(self) -> None:
        payload = self._build()
        payload["tests"]["details"][0]["ordinal"] = True
        with self.assertRaisesRegex(observation.ObservationError, "ordinals"):
            observation.validate_observation(payload)

    def test_canonical_parser_rejects_duplicate_keys(self) -> None:
        raw = observation.canonical_json(self._build())
        duplicate = raw.replace(
            '"schema":"arm-dashboard-package-observation",',
            '"schema":"arm-dashboard-package-observation",'
            '"schema":"arm-dashboard-package-observation",',
            1,
        )
        with self.assertRaisesRegex(observation.ObservationError, "duplicate key"):
            observation.parse_canonical_observation(duplicate)

    def test_canonical_parser_rejects_normalizable_numeric_strings(self) -> None:
        raw = observation.canonical_json(self._build())
        noncanonical = raw.replace('"duration_seconds":1', '"duration_seconds":"1"', 1)
        with self.assertRaisesRegex(observation.ObservationError, "canonical compact"):
            observation.parse_canonical_observation(noncanonical)

    def test_trusted_binding_satisfies_exact_result_validator(self) -> None:
        payload = self._build(lane="deferred")
        timestamp = "2026-08-10T12:02:00Z"
        bound = observation.bind_trusted_job(
            observation.canonical_json(payload),
            repository="ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
            batch_number=1,
            run_id=123,
            run_attempt=1,
            job_id=456,
            job_name="test-alpha / test-alpha",
            timestamp=timestamp,
        )
        registration = exact.PackageRegistration(
            job="test-alpha",
            called_job="test-alpha",
            workflow_path=".github/workflows/test-alpha.yml",
            package_slug="alpha",
        )
        normalized = exact.validate_package_result(
            bound,
            registration=registration,
            repository="ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
            batch=1,
            run={
                "id": 123,
                "attempt": 1,
                "created_at": "2026-08-10T12:00:00Z",
                "updated_at": "2026-08-10T12:05:00Z",
            },
            job={
                "id": 456,
                "name": "test-alpha / test-alpha",
                "html_url": (
                    "https://github.com/ArmDeveloperEcosystem/"
                    "ecosystem-dashboard-for-arm/actions/runs/123/job/456"
                ),
                "started_at": "2026-08-10T12:01:00Z",
                "completed_at": "2026-08-10T12:04:00Z",
                "conclusion": "success",
            },
        )
        self.assertEqual(bound, normalized)
        self.assertEqual(
            payload["regression"]["result"],
            bound["tests"]["details"][5]["regression_result"],
        )

    def test_trusted_binding_rejects_noncanonical_timestamp(self) -> None:
        with self.assertRaisesRegex(observation.ObservationError, "canonical RFC3339"):
            observation.bind_trusted_job(
                observation.canonical_json(self._build()),
                repository="ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
                batch_number=1,
                run_id=123,
                run_attempt=1,
                job_id=456,
                job_name="test-alpha / test-alpha",
                timestamp="2026-08-10T12:02Z",
            )

    def test_cli_rejects_noncanonical_json_file(self) -> None:
        payload = self._build()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "observation.json"
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(2, observation.main(["validate", "--input", str(path)]))

    def test_cli_rejects_oversized_file_before_json_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "observation.json"
            path.write_text("x" * (observation.MAX_OBSERVATION_BYTES + 2))
            self.assertEqual(2, observation.main(["validate", "--input", str(path)]))

    def test_validate_does_not_mutate_input(self) -> None:
        payload = self._build()
        original = copy.deepcopy(payload)
        observation.validate_observation(payload)
        self.assertEqual(original, payload)

    def test_composite_action_forwards_every_required_fact_without_defaults(self) -> None:
        action_path = (
            SCRIPT_ROOT.parent / "actions" / "emit-package-observation" / "action.yml"
        )
        action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
        expected_inputs = {
            "package_slug",
            "package_name",
            "package_version",
            "run_status",
            "badge_status",
            "core_failed",
            "tests_passed",
            "tests_failed",
            "tests_skipped",
            "duration_seconds",
            "regression_decision",
            "regression_current_version",
            "regression_latest_version",
            "regression_next_installed_version",
            "regression_result",
            "regression_comparison",
        }
        for ordinal in range(1, 7):
            expected_inputs.update(
                {
                    f"test{ordinal}_name",
                    f"test{ordinal}_status",
                    f"test{ordinal}_duration",
                }
            )
        self.assertEqual(expected_inputs, set(action["inputs"]))
        for definition in action["inputs"].values():
            self.assertIs(definition["required"], True)
            self.assertNotIn("default", definition)

        step = action["runs"]["steps"][0]
        expected_environment = {
            key.upper(): f"${{{{ inputs.{key} }}}}" for key in expected_inputs
        }
        self.assertEqual(expected_environment, step["env"])
        self.assertIn("package_observation.py", step["run"])
        self.assertIn("--github-output \"${GITHUB_OUTPUT}\"", step["run"])

    def test_emit_cli_writes_exact_file_and_one_line_github_output(self) -> None:
        payload = self._build(lane="deferred")
        environment = {
            "PACKAGE_SLUG": payload["package"]["slug"],
            "PACKAGE_NAME": payload["package"]["name"],
            "PACKAGE_VERSION": payload["package"]["version"],
            "RUN_STATUS": payload["outcome"]["run_status"],
            "BADGE_STATUS": payload["outcome"]["badge_status"],
            "CORE_FAILED": str(payload["outcome"]["core_failed"]),
            "TESTS_PASSED": str(payload["tests"]["passed"]),
            "TESTS_FAILED": str(payload["tests"]["failed"]),
            "TESTS_SKIPPED": str(payload["tests"]["skipped"]),
            "DURATION_SECONDS": str(payload["tests"]["duration_seconds"]),
            "REGRESSION_DECISION": payload["regression"]["decision"],
            "REGRESSION_CURRENT_VERSION": payload["regression"]["current_version"],
            "REGRESSION_LATEST_VERSION": payload["regression"]["latest_version"],
            "REGRESSION_NEXT_INSTALLED_VERSION": payload["regression"][
                "next_installed_version"
            ],
            "REGRESSION_RESULT": payload["regression"]["result"],
            "REGRESSION_COMPARISON": payload["regression"]["comparison"],
        }
        for detail in payload["tests"]["details"]:
            ordinal = detail["ordinal"]
            environment[f"TEST{ordinal}_NAME"] = detail["name"]
            environment[f"TEST{ordinal}_STATUS"] = detail["status"]
            environment[f"TEST{ordinal}_DURATION"] = str(
                detail["duration_seconds"]
            )

        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "package-observation.json"
            github_output = Path(temporary) / "github-output"
            with mock.patch.dict(os.environ, environment, clear=True):
                exit_code = observation.main(
                    [
                        "emit",
                        "--output",
                        str(result_path),
                        "--github-output",
                        str(github_output),
                    ]
                )
            self.assertEqual(0, exit_code)
            encoded = observation.canonical_json(payload)
            self.assertEqual(encoded + "\n", result_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    f"package_observation_json={encoded}",
                    f"result_path={result_path}",
                ],
                github_output.read_text(encoding="utf-8").splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
