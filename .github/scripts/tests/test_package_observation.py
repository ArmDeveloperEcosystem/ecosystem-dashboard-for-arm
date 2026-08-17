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


class PackageObservationTests(unittest.TestCase):
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
