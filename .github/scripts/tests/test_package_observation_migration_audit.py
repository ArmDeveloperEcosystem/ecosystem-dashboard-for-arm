from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import package_observation_migration_audit as audit  # noqa: E402


class PackageObservationMigrationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.report = audit.audit_repository(cls.root)

    def test_inventory_matches_the_registered_repository(self) -> None:
        self.assertEqual(
            {
                "batches": 22,
                "packages": 960,
                "custom_summary_workflows": 924,
                "emitter_workflows": 36,
                "shared_smoke_workflows": 13,
                "package_manager_workflows": 431,
            },
            self.report["totals"],
        )
        self.assertEqual(
            {"not_applicable_package_manager": 8, "not_configured": 952},
            self.report["fallback_counts"],
        )
        self.assertEqual(
            {
                "shared_smoke": 13,
                "emitter_only": 23,
                "generic_source": 97,
                "fully_custom": 827,
            },
            {
                key: len(value)
                for key, value in self.report["migration_cohorts"].items()
            },
        )
        cohort_members = [
            slug
            for cohort in self.report["migration_cohorts"].values()
            for slug in cohort
        ]
        self.assertEqual(960, len(cohort_members))
        self.assertEqual(960, len(set(cohort_members)))

    def test_structural_observation_inputs_are_present(self) -> None:
        remediation = self.report["remediation"]
        self.assertEqual({}, remediation["missing_test_steps"])
        self.assertEqual({}, remediation["missing_test_status"])
        self.assertEqual({}, remediation["invalid_test_names"])
        self.assertEqual([], remediation["missing_summary_step"])
        self.assertEqual([], remediation["unapproved_decision_tokens"])
        self.assertEqual([], remediation["emitter_contract_violations"])
        self.assertEqual([], remediation["emitter_slug_mismatch"])
        self.assertEqual([], remediation["shared_contract_violations"])
        self.assertEqual(
            [], remediation["shared_smoke_literal_pair_contradictions"]
        )
        self.assertEqual(
            {"test4": ["cobbler"]}, remediation["baseline_dynamic_skip"]
        )

    def test_remediation_counts_are_explicit_and_reproducible(self) -> None:
        remediation = self.report["remediation"]
        self.assertEqual(17, len(remediation["emitter_missing_slug"]))
        self.assertEqual(
            {"test4": 4, "test5": 35, "test6": 4},
            {
                key: len(value)
                for key, value in remediation["missing_test_duration"].items()
            },
        )
        self.assertEqual(
            {"test3": 1, "test4": 1, "test5": 2, "test6": 341},
            {
                key: len(value)
                for key, value in remediation[
                    "summary_missing_duration_reference"
                ].items()
            },
        )
        self.assertEqual(
            {"core_failed": 402, "duration": 3, "skipped": 726},
            {
                key: len(value)
                for key, value in remediation["missing_summary_outputs"].items()
            },
        )
        self.assertEqual(
            400,
            len(remediation["package_manager_missing_explicit_skip_counter"]),
        )
        self.assertEqual(79, len(remediation["package_manager_non_skipped_status"]))
        self.assertEqual(287, len(remediation["literal_pair_contradictions"]))
        self.assertEqual(21, len(remediation["no_literal_decision"]))
        self.assertEqual(
            326, len(remediation["package_manager_summary_omits_test6"])
        )
        self.assertEqual(8, len(remediation["unsafe_fallback_workflows"]))
        self.assertEqual(["freecad"], remediation["package_manager_missing_decision"])
        self.assertEqual(
            {"test1": 27, "test2": 34, "test3": 34, "test4": 27, "test5": 31},
            {
                key: len(value)
                for key, value in remediation["baseline_literal_skip"].items()
            },
        )
        baseline_skip_workflows = {
            slug
            for workflows in remediation["baseline_literal_skip"].values()
            for slug in workflows
        }
        self.assertEqual(37, len(baseline_skip_workflows))
        self.assertEqual(
            13, len(remediation["shared_smoke_baseline_skip_callers"])
        )
        self.assertEqual(
            97, len(remediation["generic_source_missing_baseline_facts"])
        )
        self.assertEqual(
            427, len(remediation["package_manager_missing_baseline_guard"])
        )
        self.assertEqual(
            960, len(remediation["missing_package_observation_output"])
        )
        self.assertEqual(
            960, len(remediation["missing_package_observation_step"])
        )
        self.assertEqual([], remediation["invalid_package_observation_contract"])
        self.assertEqual(
            [], remediation["invalid_package_observation_input_bindings"]
        )
        self.assertEqual(
            960,
            len(remediation["missing_workflow_call_observation_output"]),
        )
        self.assertEqual(
            [], remediation["invalid_workflow_call_observation_output"]
        )
        self.assertEqual(
            371,
            len(remediation["non_package_manager_missing_baseline_guard"]),
        )
        self.assertEqual(344, len(remediation["summary_omits_test6_status"]))
        self.assertEqual(
            952, len(remediation["unsafe_package_version_fallback"])
        )
        self.assertEqual(
            960, len(remediation["unsafe_regression_narrative_fallback"])
        )
        self.assertEqual(
            22, len(remediation["legacy_batch_collector_workflows"])
        )
        self.assertEqual(
            22, len(remediation["missing_strict_batch_collector"])
        )
        self.assertEqual([], remediation["invalid_strict_batch_collector"])
        self.assertEqual(
            [
                "native_arm64_shadow_validation",
                "supply_chain_lock_reseal_after_workflow_bytes_stabilize",
            ],
            self.report["required_activation_gates"],
        )
        self.assertEqual(10, len(self.report["audited_source_digests"]))
        self.assertTrue(
            all(
                len(digest) == 64
                for digest in self.report["audited_source_digests"].values()
            )
        )
        self.assertTrue(audit.report_has_findings(self.report))
        self.assertFalse(self.report["cutover_authorized"])
        self.assertFalse(audit.report_is_activation_ready(self.report))
        candidate = {**self.report, "cutover_authorized": True}
        with self.assertRaises(audit.AuditError):
            audit.report_is_activation_ready(candidate)


    def test_report_is_canonical_json_without_absolute_paths(self) -> None:
        encoded = audit.canonical_json(self.report)
        self.assertEqual(self.report, json.loads(encoded))
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn("/private/tmp/", encoded)
        digest = hashlib.sha256((encoded + "\n").encode("ascii")).hexdigest()
        self.assertEqual(
            "bc766884dd9ebe1920b81c916ea5734366d17aae559e9dc29ef75fc0fec434c5",
            digest,
        )

    def test_shell_output_detection_requires_a_real_github_output_write(self) -> None:
        step = {
            "run": """
                # echo "status=passed" >> "$GITHUB_OUTPUT"
                echo "status=passed"
                echo "duration=1" >> "$NOT_GITHUB_OUTPUT"
                echo prefix "note=not-a-record" >> "$GITHUB_OUTPUT"
                echo "status=failed" >> "$GITHUB_OUTPUT"
                echo "decision=$decision" >> "$GITHUB_OUTPUT"
            """
        }
        self.assertTrue(audit._step_emits_output(self.root, step, "status"))
        self.assertFalse(audit._step_emits_output(self.root, step, "duration"))
        self.assertFalse(audit._step_emits_output(self.root, step, "note"))
        self.assertEqual(
            ("failed",), audit._step_literal_outputs(self.root, step, "status")
        )
        self.assertEqual(
            (), audit._step_literal_outputs(self.root, step, "decision")
        )
        self.assertTrue(audit._step_has_dynamic_output(self.root, step, "decision"))

    def test_grouped_github_output_writes_are_traced(self) -> None:
        step = {
            "run": """
                {
                  echo "decision=not_applicable_package_manager"
                  echo "status=skipped"
                  echo "duration=0"
                } >> "$GITHUB_OUTPUT"
            """
        }
        self.assertEqual(
            ("not_applicable_package_manager",),
            audit._step_literal_outputs(self.root, step, "decision"),
        )
        self.assertTrue(audit._step_emits_output(self.root, step, "duration"))

    def test_uncalled_shell_function_outputs_are_not_counted(self) -> None:
        uncalled = {
            "run": """
                emit_result() {
                  echo "decision=next_install_failed" >> "$GITHUB_OUTPUT"
                  echo "status=failed" >> "$GITHUB_OUTPUT"
                }
                echo "duration=0" >> "$GITHUB_OUTPUT"
            """
        }
        self.assertFalse(audit._step_emits_output(self.root, uncalled, "status"))
        self.assertEqual((), audit._step_literal_pairs(self.root, uncalled))

        called = {"run": uncalled["run"] + "\nemit_result\n"}
        self.assertTrue(audit._step_emits_output(self.root, called, "status"))
        self.assertEqual(
            (("next_install_failed", "failed"),),
            audit._step_literal_pairs(self.root, called),
        )

    def test_decision_status_pairs_preserve_branch_correlation(self) -> None:
        step = {
            "run": """
                if condition; then
                  echo "decision=next_install_validated" >> "$GITHUB_OUTPUT"
                  echo "status=passed" >> "$GITHUB_OUTPUT"
                else
                  echo "decision=next_install_failed" >> "$GITHUB_OUTPUT"
                  echo "status=passed" >> "$GITHUB_OUTPUT"
                fi
                echo "decision=manual_review_needed" >> "$GITHUB_OUTPUT"
                echo "status=skipped" >> "$GITHUB_OUTPUT"
            """
        }
        self.assertEqual(
            (
                ("manual_review_needed", "skipped"),
                ("next_install_failed", "passed"),
                ("next_install_validated", "passed"),
            ),
            audit._step_literal_pairs(self.root, step),
        )

        status_first = {
            "run": """
                echo "status=passed" >> "$GITHUB_OUTPUT"
                echo "decision=next_install_failed" >> "$GITHUB_OUTPUT"
            """
        }
        self.assertEqual(
            (("next_install_failed", "passed"),),
            audit._step_literal_pairs(self.root, status_first),
        )

    def test_all_strict_placeholder_fallbacks_are_detected(self) -> None:
        for placeholder in ("", "unknown", "n/a", "na", "none", "null"):
            expression = f"${{{{ steps.version.outputs.version || '{placeholder}' }}}}"
            self.assertTrue(audit._has_placeholder_fallback(expression))
        for placeholder in (
            "",
            "Regression result unavailable.",
            "Regression comparison summary unavailable.",
            "No regression note recorded.",
        ):
            expression = f"${{{{ steps.test6.outputs.comparison || '{placeholder}' }}}}"
            self.assertTrue(
                audit._has_placeholder_fallback(expression, narrative=True)
            )

    def test_shared_smoke_variable_pairs_detect_mutated_status(self) -> None:
        source = """
            set_test() { true; }
            run_lane() {
              regression_decision=next_install_failed
              set_test 6 passed "$start"
            }
            run_lane
        """
        self.assertEqual(
            (("next_install_failed", "passed"),),
            audit._shell_variable_decision_status_pairs(
                source, "regression_decision", "test6_status"
            ),
        )

    def test_exact_observation_binding_requires_a_real_producer(self) -> None:
        steps = [
            {
                "id": "version",
                "run": 'echo "version=1.2.3" >> "$GITHUB_OUTPUT"',
            }
        ]
        self.assertTrue(
            audit._exact_step_output_is_produced(
                self.root,
                steps,
                "${{ steps.version.outputs.version }}",
                ("steps.version.outputs.version",),
            )
        )
        self.assertFalse(
            audit._exact_step_output_is_produced(
                self.root,
                steps,
                "${{ steps.version.outputs.version || 'unknown' }}",
                ("steps.version.outputs.version",),
            )
        )
        self.assertFalse(
            audit._exact_step_output_is_produced(
                self.root,
                steps,
                "${{ steps.version.outputs.status }}",
                ("steps.version.outputs.status",),
            )
        )
        self.assertFalse(
            audit._exact_step_output_is_produced(
                self.root,
                steps,
                "${{ steps.missing.outputs.version }}",
                ("steps.missing.outputs.version",),
            )
        )

    def test_local_action_declaration_must_trace_to_a_real_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action_dir = root / ".github" / "actions" / "sample"
            action_dir.mkdir(parents=True)
            action_path = action_dir / "action.yml"
            action_template = """\
name: Sample
outputs:
  status:
    value: ${{{{ steps.emit.outputs.status }}}}
runs:
  using: composite
  steps:
    - id: emit
      shell: bash
      run: {command}
"""
            action_path.write_text(
                action_template.format(command='echo "status=passed"'),
                encoding="utf-8",
            )
            caller = {"uses": "./.github/actions/sample"}
            self.assertFalse(audit._step_emits_output(root, caller, "status"))

            action_path.write_text(
                action_template.format(
                    command='echo "status=passed" >> "$GITHUB_OUTPUT"'
                ),
                encoding="utf-8",
            )
            self.assertTrue(audit._step_emits_output(root, caller, "status"))
            self.assertEqual(
                ("passed",),
                audit._step_literal_outputs(root, caller, "status"),
            )


if __name__ == "__main__":
    unittest.main()
