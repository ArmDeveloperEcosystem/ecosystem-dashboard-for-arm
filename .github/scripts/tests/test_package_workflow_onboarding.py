from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "package_workflow_supply_chain.py"
SPEC = importlib.util.spec_from_file_location("package_workflow_onboarding", SCRIPT)
assert SPEC and SPEC.loader
supply_chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supply_chain)

OLD = ".github/workflows/test-existing.yml"
ADDED = ".github/workflows/test-new-package.yml"
BATCH = ".github/workflows/test-all-packages-batch1.yml"


def transition_lock(previous: str, current: str) -> dict[str, object]:
    return {
        "hardened_workflow_sha256": current,
        "hardened_workflow_transition": {
            "from_sha256": previous,
            "to_sha256": current,
            "reason": "Reviewed package workflow onboarding.",
            "added_workflows": [ADDED],
        },
    }


class OnboardingDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = transition_lock("a" * 64, "b" * 64)

    def test_transition_is_optional(self) -> None:
        for lock in ({}, {"hardened_workflow_transition": None}):
            with self.subTest(lock=lock):
                self.assertIsNone(
                    supply_chain.validate_hardened_workflow_transition(lock)
                )

    def test_old_three_field_maintenance_transition_remains_valid(self) -> None:
        del self.lock["hardened_workflow_transition"]["added_workflows"]
        self.assertEqual(
            self.lock["hardened_workflow_transition"],
            supply_chain.validate_hardened_workflow_transition(self.lock),
        )

    def test_canonical_additions_preserve_the_reviewed_declaration(self) -> None:
        for additions in (
            [ADDED],
            [
                ".github/workflows/test-0.yml",
                ".github/workflows/test-alpha.yml",
                ".github/workflows/test-new_package-2.yml",
            ],
            [f".github/workflows/test-package-{index:02d}.yml" for index in range(45)],
        ):
            with self.subTest(count=len(additions)):
                self.lock["hardened_workflow_transition"]["added_workflows"] = additions
                before = copy.deepcopy(self.lock)
                self.assertEqual(
                    before["hardened_workflow_transition"],
                    supply_chain.validate_hardened_workflow_transition(self.lock),
                )
                self.assertEqual(before, self.lock)

    def test_malformed_addition_declarations_are_rejected(self) -> None:
        malformed = {
            "empty": [],
            "overbound": [
                f".github/workflows/test-package-{index:02d}.yml" for index in range(46)
            ],
            "duplicates": [ADDED, ADDED],
            "unsorted": [ADDED, OLD],
            "null": None,
            "string": ADDED,
            "tuple": (ADDED,),
            "mapping": {ADDED: True},
            "boolean": True,
            "number": 1,
            "null element": [None],
            "boolean element": [True],
            "number element": [1],
            "mapping element": [{}],
            "nested list": [[ADDED]],
            "mixed types": [ADDED, 1],
            "empty element": [""],
            "parent traversal": ["../" + ADDED],
            "internal traversal": [".github/workflows/test-../test-new.yml"],
            "dot segment": [".github/workflows/./test-new.yml"],
            "absolute": ["/" + ADDED],
            "relative alias": ["./" + ADDED],
            "double slash": [".github//workflows/test-new.yml"],
            "backslashes": [r".github\workflows\test-new.yml"],
            "wrong directory": [".github/scripts/test-new.yml"],
            "nested directory": [".github/workflows/test-dir/new.yml"],
            "wrong extension": [".github/workflows/test-new.yaml"],
            "uppercase": [".github/workflows/test-New.yml"],
            "non-ascii": [".github/workflows/test-caf\u00e9.yml"],
            "empty slug": [".github/workflows/test-.yml"],
            "leading punctuation": [".github/workflows/test-_new.yml"],
            "space": [".github/workflows/test-new package.yml"],
            "newline": [ADDED + "\n"],
            "nul": [ADDED + "\0"],
            "glob": [".github/workflows/test-*.yml"],
            "pathspec magic": [":(glob).github/workflows/test-*.yml"],
            "batch control": [BATCH],
            "summary control": [".github/workflows/test-all-packages-summary.yml"],
            "orchestrator control": [
                ".github/workflows/test-all-packages-orchestrator.yml"
            ],
            "reserved control prefix": [".github/workflows/test-all-packages-new.yml"],
            "foundation control": [
                ".github/workflows/exact-run-aggregation-foundation-ci.yml"
            ],
        }
        for label, additions in malformed.items():
            with self.subTest(case=label):
                lock = copy.deepcopy(self.lock)
                lock["hardened_workflow_transition"]["added_workflows"] = additions
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "additions are not canonical"
                ):
                    supply_chain.validate_hardened_workflow_transition(lock)

    def test_additions_do_not_relax_the_original_transition_fields(self) -> None:
        malformed = [[], "transition", {}]
        for field in ("from_sha256", "to_sha256", "reason"):
            transition = copy.deepcopy(self.lock["hardened_workflow_transition"])
            del transition[field]
            malformed.append(transition)
        for field, value in (
            ("from_sha256", "a" * 63),
            ("from_sha256", "A" * 64),
            ("from_sha256", 1),
            ("from_sha256", "b" * 64),
            ("to_sha256", "c" * 64),
            ("to_sha256", None),
            ("reason", ""),
            ("reason", " \n\t"),
            ("reason", "x" * 513),
            ("reason", True),
            ("unexpected", True),
        ):
            transition = copy.deepcopy(self.lock["hardened_workflow_transition"])
            transition[field] = value
            malformed.append(transition)
        for transition in malformed:
            with self.subTest(transition=transition):
                lock = copy.deepcopy(self.lock)
                lock["hardened_workflow_transition"] = transition
                with self.assertRaises(supply_chain.ContractError):
                    supply_chain.validate_hardened_workflow_transition(lock)


class OnboardingGitTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="package-onboarding-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Keep real Git subprocesses independent of the caller's repository/config.
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_COUNT="4",
            GIT_CONFIG_KEY_0="core.hooksPath",
            GIT_CONFIG_VALUE_0=os.devnull,
            GIT_CONFIG_KEY_1="core.attributesFile",
            GIT_CONFIG_VALUE_1=os.devnull,
            GIT_CONFIG_KEY_2="commit.gpgSign",
            GIT_CONFIG_VALUE_2="false",
            GIT_CONFIG_KEY_3="core.autocrlf",
            GIT_CONFIG_VALUE_3="false",
            GIT_AUTHOR_NAME="Onboarding Tests",
            GIT_AUTHOR_EMAIL="onboarding@example.invalid",
            GIT_COMMITTER_NAME="Onboarding Tests",
            GIT_COMMITTER_EMAIL="onboarding@example.invalid",
        )
        self.enterContext(mock.patch.dict(os.environ, environment, clear=True))
        self.git("init", "--quiet", "--object-format=sha1", "--template=")
        self.base_snapshot = {
            OLD: (
                b"name: Existing package\non: workflow_call\npermissions:\n"
                b"  contents: read\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
                b"    steps:\n      - run: echo existing\n"
            ),
            BATCH: (
                b"name: Package batch\non: workflow_dispatch\njobs:\n"
                b"  existing:\n    uses: ./.github/workflows/test-existing.yml\n"
            ),
        }
        self.base_commit = self.commit_snapshot(self.base_snapshot, "Reviewed base")
        self.base_digest = supply_chain.workflow_set_sha256(
            self.root, [self.root / name for name in self.base_snapshot]
        )
        self.current_snapshot = {
            **self.base_snapshot,
            ADDED: (
                b"name: New package\non: workflow_call\npermissions:\n"
                b"  contents: read\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
                b"    steps:\n      - run: echo new\n"
            ),
            BATCH: self.base_snapshot[BATCH]
            + b"  new:\n    uses: ./.github/workflows/test-new-package.yml\n",
        }
        self.current_commit = self.commit_snapshot(
            self.current_snapshot, "Reviewed package addition"
        )
        self.paths = [self.root / name for name in self.current_snapshot]
        self.current_digest = supply_chain.workflow_set_sha256(self.root, self.paths)
        self.lock = transition_lock(self.base_digest, self.current_digest)

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    def write(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def commit_snapshot(self, snapshot: dict[str, bytes], message: str) -> str:
        for name in (OLD, ADDED, BATCH):
            if name not in snapshot:
                (self.root / name).unlink(missing_ok=True)
        for name, content in snapshot.items():
            self.write(name, content)
        return self.commit(message)

    def authenticate(self, commit: str, lock: dict[str, object] | None = None) -> str:
        return supply_chain.validate_authenticated_base(
            self.root, self.paths, self.lock if lock is None else lock, commit
        )

    def test_pre_addition_base_matches_explicit_addition_and_previous_digest(self) -> None:
        self.assertTrue((self.root / ADDED).is_file())
        self.assertNotEqual(self.base_digest, self.current_digest)
        snapshot = supply_chain.source_snapshot(
            self.root, self.paths, self.base_commit, allowed_missing=[ADDED]
        )
        self.assertEqual(self.base_snapshot, snapshot)
        self.assertEqual(
            self.base_digest, supply_chain.workflow_snapshot_sha256(snapshot)
        )
        self.assertEqual(
            "declared_hardened_transition_source", self.authenticate(self.base_commit)
        )

    def test_post_addition_base_includes_existing_declared_addition(self) -> None:
        for additions in ((), (ADDED,)):
            with self.subTest(allowed_missing=additions):
                snapshot = supply_chain.source_snapshot(
                    self.root,
                    self.paths,
                    self.current_commit,
                    allowed_missing=additions,
                )
                self.assertEqual(self.current_snapshot, snapshot)
                self.assertEqual(self.current_snapshot[ADDED], snapshot[ADDED])
                self.assertEqual(
                    self.current_digest, supply_chain.workflow_snapshot_sha256(snapshot)
                )
        self.assertEqual(
            "current_hardened_snapshot", self.authenticate(self.current_commit)
        )

    def test_current_base_is_valid_without_a_transition(self) -> None:
        lock = {"hardened_workflow_sha256": self.current_digest}
        self.assertEqual(
            "current_hardened_snapshot", self.authenticate(self.current_commit, lock)
        )

    def test_missing_addition_requires_an_explicit_declaration(self) -> None:
        with self.assertRaisesRegex(supply_chain.ContractError, "missing workflows"):
            supply_chain.source_snapshot(self.root, self.paths, self.base_commit)
        for transition_present in (False, True):
            with self.subTest(transition_present=transition_present):
                lock = copy.deepcopy(self.lock)
                if transition_present:
                    del lock["hardened_workflow_transition"]["added_workflows"]
                else:
                    del lock["hardened_workflow_transition"]
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "could not read the authenticated"
                ):
                    self.authenticate(self.base_commit, lock)

    def test_declared_addition_must_belong_to_candidate_registration(self) -> None:
        paths = [path for path in self.paths if path != self.root / ADDED]
        for commit in (self.base_commit, self.current_commit):
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "not registered"
                ):
                    supply_chain.source_snapshot(
                        self.root, paths, commit, allowed_missing=[ADDED]
                    )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "could not read the authenticated"
                ) as error:
                    supply_chain.validate_authenticated_base(
                        self.root, paths, self.lock, commit
                    )
                self.assertIn("not registered", str(error.exception.__cause__))

    def test_addition_cannot_excuse_missing_old_workflow_or_batch(self) -> None:
        for missing in (OLD, BATCH):
            with self.subTest(missing=missing):
                snapshot = {
                    name: content
                    for name, content in self.current_snapshot.items()
                    if name != missing
                }
                commit = self.commit_snapshot(snapshot, "Unreviewed deletion")
                lock = transition_lock(
                    supply_chain.workflow_snapshot_sha256(snapshot), self.current_digest
                )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "missing workflows"
                ):
                    supply_chain.source_snapshot(
                        self.root, self.paths, commit, allowed_missing=[ADDED]
                    )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "could not read the authenticated"
                ):
                    self.authenticate(commit, lock)

    def test_changed_base_content_fails_both_reviewed_digests(self) -> None:
        for source in (self.base_snapshot, self.current_snapshot):
            for changed in source:
                with self.subTest(after_addition=ADDED in source, changed=changed):
                    snapshot = dict(source)
                    snapshot[changed] += b"# Unreviewed base change\n"
                    commit = self.commit_snapshot(snapshot, "Unreviewed base content")
                    with self.assertRaisesRegex(
                        supply_chain.ContractError,
                        "does not match the current or declared transition source",
                    ):
                        self.authenticate(commit)

    def test_wrong_previous_digest_cannot_authenticate_pre_addition_base(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["hardened_workflow_transition"]["from_sha256"] = "c" * 64
        with self.assertRaisesRegex(supply_chain.ContractError, "does not match"):
            self.authenticate(self.base_commit, lock)

    def test_wrong_current_digest_cannot_authenticate_post_addition_base(self) -> None:
        lock = transition_lock(self.base_digest, "c" * 64)
        with self.assertRaisesRegex(supply_chain.ContractError, "does not match"):
            self.authenticate(self.current_commit, lock)

    def test_current_base_still_validates_transition_target(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["hardened_workflow_transition"]["to_sha256"] = "c" * 64
        with self.assertRaisesRegex(
            supply_chain.ContractError, "transition is invalid"
        ):
            self.authenticate(self.current_commit, lock)

    def test_existing_addition_is_not_omitted_to_match_previous_digest(self) -> None:
        omitted = {
            name: value
            for name, value in self.current_snapshot.items()
            if name != ADDED
        }
        lock = transition_lock(supply_chain.workflow_snapshot_sha256(omitted), "c" * 64)
        with self.assertRaisesRegex(supply_chain.ContractError, "does not match"):
            self.authenticate(self.current_commit, lock)

    def test_existing_addition_cannot_be_hidden_with_export_ignore(self) -> None:
        for attributes in (
            f"{ADDED} export-ignore\n",
            ".github/workflows export-ignore\n",
        ):
            with self.subTest(attributes=attributes):
                self.write(".gitattributes", attributes.encode("utf-8"))
                commit = self.commit("Hide existing workflows from archive")
                self.assertIn(
                    ADDED, self.git("ls-tree", "-r", "--name-only", commit).splitlines()
                )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "reviewed source archive"
                ):
                    supply_chain.source_snapshot(
                        self.root, self.paths, commit, allowed_missing=[ADDED]
                    )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "could not read the authenticated"
                ):
                    self.authenticate(commit)

    def test_source_archive_rejects_export_ignore_without_an_allowance(self) -> None:
        self.write(".gitattributes", f"{OLD} export-ignore\n".encode("utf-8"))
        commit = self.commit("Hide an old workflow from archive")
        with self.assertRaisesRegex(supply_chain.ContractError, "missing workflows"):
            supply_chain.source_snapshot(self.root, self.paths, commit)

    def test_local_export_ignore_cannot_hide_an_existing_addition(self) -> None:
        self.write(".git/info/attributes", f"{ADDED} export-ignore\n".encode("utf-8"))
        with self.assertRaisesRegex(supply_chain.ContractError, "missing workflows"):
            supply_chain.source_snapshot(
                self.root, self.paths, self.current_commit, allowed_missing=[ADDED]
            )

    def test_snapshot_ignores_dirty_or_missing_worktree_files(self) -> None:
        self.write(OLD, b"uncommitted content\n")
        (self.root / ADDED).unlink()
        self.assertEqual(
            self.current_snapshot,
            supply_chain.source_snapshot(
                self.root, self.paths, self.current_commit, allowed_missing=[ADDED]
            ),
        )
        self.assertEqual(
            "current_hardened_snapshot", self.authenticate(self.current_commit)
        )

    def test_git_replacement_cannot_hide_an_existing_addition(self) -> None:
        self.git("replace", self.current_commit, self.base_commit)
        self.assertNotIn(
            ADDED,
            self.git("ls-tree", "-r", "--name-only", self.current_commit).splitlines(),
        )
        self.assertEqual(
            self.current_snapshot,
            supply_chain.source_snapshot(
                self.root, self.paths, self.current_commit, allowed_missing=[ADDED]
            ),
        )
        self.assertEqual(
            "current_hardened_snapshot", self.authenticate(self.current_commit)
        )

    def test_symlink_cannot_stand_in_for_a_declared_added_workflow(self) -> None:
        (self.root / ADDED).unlink()
        (self.root / ADDED).symlink_to(Path(OLD).name)
        commit = self.commit("Replace addition with symlink")
        with self.assertRaisesRegex(supply_chain.ContractError, "archive is malformed"):
            supply_chain.source_snapshot(
                self.root, self.paths, commit, allowed_missing=[ADDED]
            )

    def test_bad_or_zero_base_sha_is_rejected(self) -> None:
        for commit in (
            "",
            "HEAD",
            self.base_commit[:12],
            "a" * 39,
            "a" * 41,
            "A" * 40,
            "g" * 40,
            "0" * 40,
        ):
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "not a canonical SHA"
                ):
                    self.authenticate(commit)

    def test_nonexistent_base_sha_is_rejected_by_real_git(self) -> None:
        with self.assertRaisesRegex(
            supply_chain.ContractError, "could not read the authenticated"
        ) as error:
            self.authenticate("f" * 40)
        self.assertIsInstance(error.exception.__cause__, supply_chain.ContractError)
        self.assertIsInstance(
            error.exception.__cause__.__cause__, subprocess.CalledProcessError
        )

    def test_source_snapshot_rejects_unresolvable_revisions(self) -> None:
        for commit in ("not-a-real-revision", "f" * 40, "0" * 40):
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "could not read the reviewed"
                ):
                    supply_chain.source_snapshot(
                        self.root, self.paths, commit, allowed_missing=[ADDED]
                    )

    def test_three_field_maintenance_authenticates_old_and_new_snapshots(self) -> None:
        maintained = dict(self.current_snapshot)
        maintained[OLD] += b"# Reviewed maintenance\n"
        commit = self.commit_snapshot(maintained, "Reviewed maintenance")
        lock = transition_lock(
            self.current_digest, supply_chain.workflow_set_sha256(self.root, self.paths)
        )
        del lock["hardened_workflow_transition"]["added_workflows"]
        self.assertEqual(
            "declared_hardened_transition_source",
            self.authenticate(self.current_commit, lock),
        )
        self.assertEqual("current_hardened_snapshot", self.authenticate(commit, lock))

    def test_candidate_registration_count_is_reviewed_961_not_lock_driven(self) -> None:
        self.assertEqual(961, supply_chain.EXPECTED_WORKFLOWS)
        for batch in supply_chain.batch_paths(self.root):
            if not batch.exists():
                batch.write_text("jobs: {}\n", encoding="utf-8")
        self.write(
            ".github/scripts/" + supply_chain.LOCK_NAME,
            json.dumps({"registered_workflows": 2}).encode("utf-8"),
        )
        with self.assertRaisesRegex(
            supply_chain.ContractError, "expected 961 registrations, found 2"
        ):
            supply_chain.registered_workflows(self.root)

    def test_lock_cannot_choose_an_arbitrary_registration_count(self) -> None:
        for count in (0, 2, 960, 962, 1000, "961"):
            with self.subTest(count=count):
                self.write(
                    ".github/scripts/" + supply_chain.LOCK_NAME,
                    json.dumps(
                        {
                            "schema_version": 3,
                            "source_commit": supply_chain.SOURCE_COMMIT,
                            "registered_workflows": count,
                        }
                    ).encode("utf-8"),
                )
                with self.assertRaisesRegex(
                    supply_chain.ContractError, "workflow count is not canonical"
                ):
                    supply_chain.load_lock(self.root)


if __name__ == "__main__":
    unittest.main()
