from __future__ import annotations

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
        self.assertEqual(1086, lock["external_uses"])
        self.assertEqual(13, len(lock["actions"]))
        for entry in lock["actions"]:
            self.assertTrue(entry["github_api_repository_confirmed"])
            self.assertTrue(entry["github_api_commit_confirmed"])
            self.assertTrue(entry["action_file_confirmed_at_commit"])
            self.assertTrue(entry["git_ls_remote"]["matches_github_api"])
            self.assertRegex(entry["resolved_commit"], r"^[0-9a-f]{40}$")
            verification = entry["github_commit_verification"]
            self.assertIn(verification["verified"], (True, False))
            self.assertIsInstance(verification["reason"], str)

    def test_every_external_use_is_immutable(self) -> None:
        external = 0
        for path in self.workflows:
            for _, match in supply_chain.iter_uses(path):
                spec = match.group("spec")
                if spec.startswith("./"):
                    continue
                external += 1
                if spec.startswith("docker://"):
                    self.assertRegex(
                        spec, r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$"
                    )
                    continue
                _, _, _, ref = supply_chain.split_github_action(spec)
                self.assertRegex(ref, r"^[0-9a-f]{40}$")
        self.assertEqual(1086, external)

    def test_every_checkout_disables_persisted_credentials(self) -> None:
        checkouts = 0
        for path in self.workflows:
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
        self.assertEqual(960, checkouts)

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

    def test_complete_offline_contract(self) -> None:
        self.assertEqual(
            {
                "registered_workflows": 960,
                "external_uses": 1086,
                "unique_original_refs": 13,
                "checkout_uses": 960,
                "permission_exceptions": 4,
            },
            supply_chain.validate_hardening(self.root),
        )


if __name__ == "__main__":
    unittest.main()
