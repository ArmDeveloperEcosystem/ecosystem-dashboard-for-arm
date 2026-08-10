from __future__ import annotations

import copy
import importlib.util
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "package_workflow_supply_chain.py"
SPEC = importlib.util.spec_from_file_location("package_workflow_supply_chain", SCRIPT)
assert SPEC and SPEC.loader
supply_chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supply_chain)

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
    ".github/scripts/tests/test_package_workflow_supply_chain.py",
    ".github/scripts/tests/test_verify_action_lock_online.py",
    ".github/scripts/tests/test_exact_run_aggregation.py",
    ".github/scripts/tests/test_package_observation.py",
    ".github/scripts/tests/test_package_observation_migration_audit.py",
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
        self.assertEqual(3, lock["container_uses"])
        self.assertEqual(16, len(lock["actions"]))
        self.assertEqual(3, len(lock["containers"]))
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
            "db87133f5230f98fb16b0c53ff5c1dc05b714832ac4abaae54f3d344ecd201f1",
            result["workflow_sha256"],
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
                supply_chain.ContractError, "does not match the reviewed hardened"
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
        for path in self.batches:
            lines = path.read_text(encoding="utf-8").splitlines()
            supply_chain._validate_batch_permissions(path, lines)

    def test_every_container_is_digest_pinned(self) -> None:
        lock = supply_chain.load_lock(self.root)
        containers = supply_chain.container_lock_by_workflow(lock)
        self.assertEqual(3, len(containers))
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
                "container_uses": 3,
                "unique_original_refs": 16,
                "checkout_uses": 982,
                "permission_exceptions": 4,
                "topology_sha256": "c16f81d3e036e8fc378b634f1e54fc2fb16b960f89cde8ff430c68f6f7c7dd2e",
                "workflow_sha256": "db87133f5230f98fb16b0c53ff5c1dc05b714832ac4abaae54f3d344ecd201f1",
            },
            supply_chain.validate_hardening(
                self.root, expected_base_commit=supply_chain.SOURCE_COMMIT
            ),
        )


if __name__ == "__main__":
    unittest.main()
