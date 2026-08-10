from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "package_workflow_supply_chain.py"
SPEC = importlib.util.spec_from_file_location("package_workflow_supply_chain", SCRIPT)
assert SPEC and SPEC.loader
supply_chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supply_chain)


class PackageWorkflowSupplyChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.workflows = supply_chain.registered_workflows(cls.root)
        cls.batches = supply_chain.batch_paths(cls.root)

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
            supply_chain.ContractError, "trusted pull-request base"
        ):
            supply_chain.validate_hardening(
                self.root, expected_source_commit="0" * 40
            )

    def test_foundation_check_is_bound_only_to_pull_request_base(self) -> None:
        workflow = (
            self.root
            / ".github/workflows/exact-run-aggregation-foundation-ci.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("inputs.reviewed_source_commit", workflow)
        self.assertIn(
            "REVIEWED_SOURCE_COMMIT: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn("git diff --quiet", workflow)
        self.assertIn("verify_action_lock_online.py", workflow)

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
                self.root, expected_source_commit=supply_chain.SOURCE_COMMIT
            ),
        )


if __name__ == "__main__":
    unittest.main()
