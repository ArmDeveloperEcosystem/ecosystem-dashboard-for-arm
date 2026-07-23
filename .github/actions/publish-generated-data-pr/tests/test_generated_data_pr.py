from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Mapping
from unittest.mock import patch

ACTION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACTION_ROOT))

import generated_data_pr as publisher  # noqa: E402
from generated_data_pr import (  # noqa: E402
    Config,
    GhClient,
    PublishError,
    publish_generated_data,
)

EXPECTED_BATCH_COUNT = 22


class FakeGitHub:
    def __init__(self) -> None:
        self.pull_requests: list[dict[str, Any]] = []
        self.auth_calls = 0
        self.list_calls = 0
        self.on_setup_git_auth: Callable[[], None] | None = None
        self.on_close: Callable[[dict[str, Any]], None] | None = None
        self.on_list: Callable[[int, list[dict[str, Any]]], None] | None = None

    def setup_git_auth(self) -> None:
        self.auth_calls += 1
        if self.on_setup_git_auth is not None:
            self.on_setup_git_auth()

    def list_open_pull_requests(self, config: Config) -> list[dict[str, Any]]:
        self.list_calls += 1
        if self.on_list is not None:
            self.on_list(self.list_calls, self.pull_requests)
        return [
            copy.deepcopy(pull_request)
            for pull_request in self.pull_requests
            if pull_request["state"] == "open"
            and pull_request["head"]["ref"] == config.head_branch
        ]

    def create_pull_request(
        self,
        config: Config,
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        pull_request = self._payload(
            config,
            number=len(self.pull_requests) + 1,
            body=body,
            head_sha=head_sha,
        )
        self.pull_requests.append(pull_request)
        return pull_request

    def update_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        stored = self.pull_requests[int(pull_request["number"]) - 1]
        stored["title"] = config.title
        stored["body"] = body
        stored["head"]["sha"] = head_sha
        return stored

    def close_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        del config
        stored = self.pull_requests[int(pull_request["number"]) - 1]
        stored["state"] = "closed"
        response = copy.deepcopy(stored)
        if self.on_close is not None:
            self.on_close(stored)
        return response

    @staticmethod
    def _payload(
        config: Config,
        *,
        number: int,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        return {
            "number": number,
            "html_url": f"https://github.com/{config.repository}/pull/{number}",
            "state": "open",
            "draft": True,
            "title": config.title,
            "body": body,
            "user": {"login": "github-actions[bot]"},
            "base": {
                "ref": config.base_branch,
                "sha": config.expected_base_sha,
                "repo": {"full_name": config.repository},
            },
            "head": {
                "ref": config.head_branch,
                "sha": head_sha,
                "repo": {"full_name": config.repository},
            },
        }


class GeneratedDataPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"
        _git(self.root, "init", "--bare", str(self.origin))
        _git(self.root, "init", "--initial-branch=main", str(self.seed))
        _git(self.seed, "config", "user.name", "Test Author")
        _git(self.seed, "config", "user.email", "test@example.com")
        (self.seed / "data").mkdir()
        (self.seed / "data/generated.yml").write_text("value: old\n", encoding="utf-8")
        (self.seed / "unrelated.txt").write_text("base\n", encoding="utf-8")
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "Initial base")
        _git(self.seed, "remote", "add", "origin", str(self.origin))
        _git(self.seed, "push", "--set-upstream", "origin", "main")
        self.base_sha = _git(self.seed, "rev-parse", "HEAD").stdout.strip()
        self.github = FakeGitHub()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reuses_one_branch_and_one_pr_across_reruns(self) -> None:
        first = self._clone("first")
        (first / "data/generated.yml").write_text("value: one\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )

        second = self._clone("second")
        (second / "data/generated.yml").write_text("value: one\n", encoding="utf-8")
        unchanged = publish_generated_data(
            self._config(),
            repository_root=second,
            github=self.github,
        )

        third = self._clone("third")
        (third / "data/generated.yml").write_text("value: two\n", encoding="utf-8")
        updated = publish_generated_data(
            self._config(),
            repository_root=third,
            github=self.github,
        )

        self.assertEqual(created.status, "created")
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(updated.status, "updated")
        self.assertEqual(len(self.github.pull_requests), 1)
        self.assertNotEqual(created.head_sha, updated.head_sha)
        self.assertEqual(self.github.pull_requests[0]["head"]["sha"], updated.head_sha)
        self.assertEqual(self.github.auth_calls, 2)

    def test_closes_only_owned_open_pr_when_diff_disappears(self) -> None:
        first = self._clone("first-close")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )

        clean = self._clone("clean")
        result = publish_generated_data(
            self._config(),
            repository_root=clean,
            github=self.github,
        )

        self.assertEqual(result.status, "closed_stale")
        self.assertEqual(self.github.pull_requests[0]["state"], "closed")

    def test_pr_body_documents_no_deploy_and_external_activation_blockers(self) -> None:
        worktree = self._clone("approval-guidance")
        (worktree / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=worktree,
            github=self.github,
        )

        pull_request = self.github.pull_requests[0]
        body = pull_request["body"]
        self.assertEqual(pull_request["user"]["login"], "github-actions[bot]")
        self.assertIn("will not deploy", body)
        self.assertIn("clean rerun", body)
        self.assertIn("`GITHUB_TOKEN`", body)
        self.assertIn("required approving reviews", body)
        self.assertIn("required checks", body)
        self.assertIn("administrators", body)
        self.assertIn("protected production", body)
        self.assertIn("must not be merged or activated", body)
        self.assertIn("Approve workflows to run", body)
        self.assertIn("GitHub App or fine-grained PAT", body)
        self.assertIn("optional only", body)
        self.assertIn("does not change repository rules", body)

    def test_refuses_to_overwrite_a_manual_remote_head(self) -> None:
        first = self._clone("first-owned")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )

        manual = self.root / "manual"
        _git(
            self.root,
            "clone",
            "--branch",
            self._config().head_branch,
            str(self.origin),
            str(manual),
        )
        _git(manual, "config", "user.name", "Human")
        _git(manual, "config", "user.email", "human@example.com")
        (manual / "data/generated.yml").write_text("value: human\n", encoding="utf-8")
        _git(manual, "add", "data/generated.yml")
        _git(manual, "commit", "-m", "Human branch edit")
        _git(manual, "push", "origin", self._config().head_branch)

        next_run = self._clone("next-run")
        (next_run / "data/generated.yml").write_text("value: next\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "head does not match its remote branch"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

    def test_force_with_lease_race_preserves_the_competing_remote_head(self) -> None:
        worktree = self._clone("lease-race")
        (worktree / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        raced_sha: list[str] = []

        def create_competing_head() -> None:
            racer = self.root / "lease-racer"
            _git(
                self.root,
                "clone",
                "--branch",
                "main",
                str(self.origin),
                str(racer),
            )
            _git(racer, "config", "user.name", "Concurrent Writer")
            _git(racer, "config", "user.email", "race@example.com")
            _git(racer, "switch", "--create", self._config().head_branch)
            (racer / "data/generated.yml").write_text("value: raced\n", encoding="utf-8")
            _git(racer, "add", "data/generated.yml")
            _git(racer, "commit", "-m", "Concurrent branch creation")
            raced_sha.append(_git(racer, "rev-parse", "HEAD").stdout.strip())
            _git(
                racer,
                "push",
                "origin",
                f"HEAD:refs/heads/{self._config().head_branch}",
            )

        self.github.on_setup_git_auth = create_competing_head

        with self.assertRaises(PublishError):
            publish_generated_data(
                self._config(),
                repository_root=worktree,
                github=self.github,
            )

        self.assertEqual(self._remote_head_sha(), raced_sha[0])
        self.assertEqual(self.github.pull_requests, [])

    def test_stale_pr_closure_race_fails_closed(self) -> None:
        first = self._clone("first-close-race")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.on_close = lambda pull_request: pull_request.update(state="open")

        clean = self._clone("clean-close-race")
        with patch.object(publisher.time, "sleep", return_value=None):
            with self.assertRaisesRegex(PublishError, "closure was not stable"):
                publish_generated_data(
                    self._config(),
                    repository_root=clean,
                    github=self.github,
                )

        self.assertEqual(self.github.pull_requests[0]["state"], "open")
        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_stale_pr_snapshot_change_blocks_closure(self) -> None:
        first = self._clone("first-close-snapshot")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        mutation_call = self.github.list_calls + 2

        def mutate_head_snapshot(
            call_number: int,
            pull_requests: list[dict[str, Any]],
        ) -> None:
            if call_number == mutation_call:
                pull_requests[0]["head"]["sha"] = "e" * 40

        self.github.on_list = mutate_head_snapshot
        clean = self._clone("clean-close-snapshot")
        with self.assertRaisesRegex(PublishError, "ownership snapshot changed"):
            publish_generated_data(
                self._config(),
                repository_root=clean,
                github=self.github,
            )

        self.assertEqual(self.github.pull_requests[0]["state"], "open")
        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_stale_pr_body_edit_blocks_closure(self) -> None:
        first = self._clone("first-close-body")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        mutation_call = self.github.list_calls + 2

        def mutate_body_snapshot(
            call_number: int,
            pull_requests: list[dict[str, Any]],
        ) -> None:
            if call_number == mutation_call:
                pull_requests[0]["body"] += "\nHuman review note.\n"

        self.github.on_list = mutate_body_snapshot
        clean = self._clone("clean-close-body")
        with self.assertRaisesRegex(PublishError, "ownership snapshot changed"):
            publish_generated_data(
                self._config(),
                repository_root=clean,
                github=self.github,
            )

        self.assertEqual(self.github.pull_requests[0]["state"], "open")
        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_refuses_to_rewrite_a_pr_that_has_left_draft_review(self) -> None:
        first = self._clone("first-draft")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["draft"] = False

        next_run = self._clone("next-draft")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "after it leaves draft review"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

        remote_sha = _git(
            self.root,
            "ls-remote",
            str(self.origin),
            f"refs/heads/{self._config().head_branch}",
        ).stdout.split()[0]
        self.assertEqual(remote_sha, created.head_sha)

    def test_rejects_a_pr_not_bound_to_the_reviewed_base(self) -> None:
        first = self._clone("first-pr-base")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["base"]["sha"] = "f" * 40

        next_run = self._clone("next-pr-base")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "exact reviewed base SHA"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

    def test_retargeted_pr_blocks_branch_update(self) -> None:
        first = self._clone("first-retarget")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["base"]["ref"] = "production"

        next_run = self._clone("next-retarget")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "retargeted"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_wrong_pr_repository_blocks_branch_update(self) -> None:
        first = self._clone("first-wrong-pr-repo")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["head"]["repo"]["full_name"] = "example/fork"

        next_run = self._clone("next-wrong-pr-repo")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "head branch or repository"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_wrong_pr_base_repository_blocks_branch_update(self) -> None:
        first = self._clone("first-wrong-pr-base-repo")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        created = publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["base"]["repo"]["full_name"] = "example/other"

        next_run = self._clone("next-wrong-pr-base-repo")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "retargeted"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

        self.assertEqual(self._remote_head_sha(), created.head_sha)

    def test_rejects_a_pr_with_the_wrong_author(self) -> None:
        first = self._clone("first-pr-author")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["user"]["login"] = "human-reviewer"

        next_run = self._clone("next-pr-author")
        (next_run / "data/generated.yml").write_text("value: changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "wrong author"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

    def test_rejects_forged_ownership_trailers_and_control_character_paths(self) -> None:
        first = self._clone("first-forged")
        (first / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        publish_generated_data(
            self._config(),
            repository_root=first,
            github=self.github,
        )

        forged = self.root / "forged"
        _git(
            self.root,
            "clone",
            "--branch",
            self._config().head_branch,
            str(self.origin),
            str(forged),
        )
        _git(forged, "config", "user.name", "Human")
        _git(forged, "config", "user.email", "human@example.com")
        (forged / "unrelated.txt").write_text("forged\n", encoding="utf-8")
        _git(forged, "add", "unrelated.txt")
        _git(
            forged,
            "commit",
            "-m",
            "Forged automation update",
            "-m",
            (
                "Generated-Data-Producer: test-producer\n"
                "Generated-Data-Branch: automation/generated-data/test-producer/main\n"
                "Generated-Data-Base-Branch: main\n"
                f"Generated-Data-Base-SHA: {self.base_sha}"
            ),
        )
        _git(forged, "push", "origin", self._config().head_branch)
        self.github.pull_requests[0]["state"] = "closed"

        next_run = self._clone("next-forged")
        (next_run / "data/generated.yml").write_text("value: next\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "not one generated commit"):
            publish_generated_data(
                self._config(),
                repository_root=next_run,
                github=self.github,
            )

        with self.assertRaisesRegex(PublishError, "unsafe"):
            self._config(paths=("data/results/\n",))

    def test_rejects_stale_base_and_preexisting_index_changes(self) -> None:
        stale = self._clone("stale")
        (self.seed / "unrelated.txt").write_text("new base\n", encoding="utf-8")
        _git(self.seed, "add", "unrelated.txt")
        _git(self.seed, "commit", "-m", "Advance base")
        _git(self.seed, "push", "origin", "main")
        (stale / "data/generated.yml").write_text("value: stale\n", encoding="utf-8")

        with self.assertRaisesRegex(PublishError, "base branch changed"):
            publish_generated_data(
                self._config(),
                repository_root=stale,
                github=self.github,
            )

        indexed = self._clone("indexed")
        (indexed / "unrelated.txt").write_text("indexed\n", encoding="utf-8")
        _git(indexed, "add", "unrelated.txt")
        with self.assertRaisesRegex(PublishError, "initially empty Git index"):
            publish_generated_data(
                self._config(expected_base_sha=_git(indexed, "rev-parse", "HEAD").stdout.strip()),
                repository_root=indexed,
                github=self.github,
            )

    def test_rejects_unexpected_dirty_and_untracked_paths(self) -> None:
        dirty = self._clone("unexpected-dirty")
        (dirty / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        (dirty / "unrelated.txt").write_text("unexpected\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "outside the generated-data allowlist"):
            publish_generated_data(
                self._config(),
                repository_root=dirty,
                github=self.github,
            )

        untracked = self._clone("unexpected-untracked")
        (untracked / "data/generated.yml").write_text("value: proposed\n", encoding="utf-8")
        (untracked / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "outside the generated-data allowlist"):
            publish_generated_data(
                self._config(),
                repository_root=untracked,
                github=self.github,
            )

        self.assertIsNone(self._remote_head_sha())

    def test_allows_new_regular_files_only_inside_an_allowlisted_directory(self) -> None:
        worktree = self._clone("allowlisted-new-file")
        results = worktree / "data/results"
        results.mkdir()
        (results / "new.json").write_text('{"status":"passing"}\n', encoding="utf-8")

        result = publish_generated_data(
            self._config(
                paths=("data/results/",),
                required_tracked_paths=(),
            ),
            repository_root=worktree,
            github=self.github,
        )

        self.assertEqual(result.status, "created")
        changed = _git(
            worktree,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            result.head_sha,
        ).stdout.splitlines()
        self.assertEqual(changed, ["data/results/new.json"])

    def test_required_generated_file_must_remain_tracked(self) -> None:
        worktree = self._clone("required-untracked")
        (worktree / "data/required.yml").write_text(
            "value: untracked\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PublishError, "not tracked exactly once"):
            publish_generated_data(
                self._config(
                    paths=("data/required.yml",),
                    required_tracked_paths=("data/required.yml",),
                ),
                repository_root=worktree,
                github=self.github,
            )

    def test_rejects_symlink_output_and_unsafe_configuration(self) -> None:
        worktree = self._clone("symlink")
        generated = worktree / "data/generated.yml"
        generated.unlink()
        generated.symlink_to(worktree / "unrelated.txt")
        with self.assertRaisesRegex(PublishError, "symlink|regular file"):
            publish_generated_data(
                self._config(),
                repository_root=worktree,
                github=self.github,
            )

        with self.assertRaisesRegex(PublishError, "producer namespace"):
            self._config(head_branch="automation/generated-data/other/main")

        wrong_origin = self._clone("wrong-origin")
        _git(
            wrong_origin,
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/other-repository.git",
        )
        with self.assertRaisesRegex(PublishError, "origin does not match"):
            publish_generated_data(
                self._config(),
                repository_root=wrong_origin,
                github=self.github,
            )

    def _clone(self, name: str) -> Path:
        destination = self.root / name
        _git(
            self.root,
            "clone",
            "--branch",
            "main",
            str(self.origin),
            str(destination),
        )
        canonical_origin = "https://github.com/example/dashboard.git"
        _git(
            destination,
            "config",
            f"url.{self.origin.resolve().as_uri()}.insteadOf",
            canonical_origin,
        )
        _git(destination, "remote", "set-url", "origin", canonical_origin)
        return destination

    def _remote_head_sha(self) -> str | None:
        completed = _git(
            self.root,
            "ls-remote",
            str(self.origin),
            f"refs/heads/{self._config().head_branch}",
        )
        output = completed.stdout.strip()
        return output.split()[0] if output else None

    def _config(self, **overrides: object) -> Config:
        values: dict[str, object] = {
            "producer": "test-producer",
            "base_branch": "main",
            "expected_base_sha": self.base_sha,
            "head_branch": "automation/generated-data/test-producer/main",
            "title": "Update generated test data",
            "commit_message": "Update generated test data",
            "paths": ("data/generated.yml",),
            "required_tracked_paths": ("data/generated.yml",),
            "repository": "example/dashboard",
            "server_url": "https://github.com",
            "run_url": "https://github.com/example/dashboard/actions/runs/1",
            "output_path": None,
        }
        values.update(overrides)
        config = Config(**values)  # type: ignore[arg-type]
        config.validate()
        return config


class GitHubApiContractTests(unittest.TestCase):
    def test_open_pr_discovery_is_paginated_and_independent_of_base(self) -> None:
        first_page = [{"number": number} for number in range(1, 101)]
        second_page = [{"number": 101}]
        responses = [
            subprocess.CompletedProcess(
                args=["gh"],
                returncode=0,
                stdout=publisher.json.dumps(first_page),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["gh"],
                returncode=0,
                stdout=publisher.json.dumps(second_page),
                stderr="",
            ),
        ]
        config = Config(
            producer="test-producer",
            base_branch="main",
            expected_base_sha="a" * 40,
            head_branch="automation/generated-data/test-producer/main",
            title="Update generated test data",
            commit_message="Update generated test data",
            paths=("data/generated.yml",),
            required_tracked_paths=("data/generated.yml",),
            repository="example/dashboard",
            server_url="https://github.com",
            run_url="https://github.com/example/dashboard/actions/runs/1",
            output_path=None,
        )

        with patch.object(publisher.subprocess, "run", side_effect=responses) as run:
            pull_requests = GhClient().list_open_pull_requests(config)

        self.assertEqual(len(pull_requests), 101)
        self.assertEqual(run.call_count, 2)
        endpoints = [call.args[0][-1] for call in run.call_args_list]
        self.assertTrue(all("head=example%3Aautomation%2Fgenerated-data" in item for item in endpoints))
        self.assertTrue(all("base=" not in item for item in endpoints))
        self.assertIn("page=1", endpoints[0])
        self.assertIn("page=2", endpoints[1])


class WorkflowContractTests(unittest.TestCase):
    def test_migrated_workflows_use_review_action_without_direct_pushes(self) -> None:
        checkout_sha = "11d5960a326750d5838078e36cf38b85af677262"
        hugo_sha = "2752ce1d29631191ea3f27c23495fa06139a5b78"
        repository = ACTION_ROOT.parents[2]
        main = (repository / ".github/workflows/main.yml").read_text(encoding="utf-8")
        summary = (
            repository / ".github/workflows/test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")

        for workflow in (main, summary):
            self.assertIn("./.github/actions/publish-generated-data-pr", workflow)
            self.assertIn("pull-requests: write", workflow)
            self.assertIn("GH_TOKEN: ${{ github.token }}", workflow)
            self.assertNotIn("git push", workflow)
            self.assertIn(f"actions/checkout@{checkout_sha}", workflow)
            self.assertNotIn("actions/checkout@v", workflow)

        self.assertIn("data/category_data_windows.yml", main)
        self.assertIn("hugo deploy --force", main)
        self.assertIn(f"peaceiris/actions-hugo@{hugo_sha}", main)
        self.assertNotIn("peaceiris/actions-hugo@v", main)
        self.assertIn("EXPECTED_REF: refs/heads/main", main)
        self.assertIn('[[ "$GITHUB_REF" == "$EXPECTED_REF" ]]', main)
        self.assertIn("id: generated_data_review", main)
        self.assertIn("producer: site-preprocessing", main)
        self.assertLess(
            main.index("Open or update preprocessing data review PR"),
            main.index("- name: Build"),
        )
        self.assertLess(
            main.index('[[ "$actual_base_sha" == "$EXPECTED_BASE_SHA" ]]'),
            main.index("hugo deploy --force"),
        )
        deploy_gate = (
            "if: steps.generated_data_review.outputs.status == 'no_changes'"
        )
        self.assertEqual(main.count(deploy_gate), 2)
        for blocked_status in ("created", "updated", "unchanged", "closed_stale"):
            self.assertNotIn(
                f"steps.generated_data_review.outputs.status == '{blocked_status}'",
                main,
            )
        concurrency_contract = (
            "concurrency:\n"
            "  group: ${{ github.repository }}-production-deployment\n"
            "  cancel-in-progress: false"
        )
        self.assertIn(concurrency_contract, main)
        self.assertLess(main.index("concurrency:"), main.index("jobs:"))
        build_job_start = main.index("  build_and_review:")
        deploy_job_start = main.index("  deploy_production:")
        build_job = main[build_job_start:deploy_job_start]
        deploy_job = main[deploy_job_start:]
        self.assertIn("needs: build_and_review", deploy_job)
        self.assertIn("needs.build_and_review.result == 'success'", deploy_job)
        self.assertIn(
            "needs.build_and_review.outputs.generated_data_status == 'no_changes'",
            deploy_job,
        )
        self.assertIn(
            "needs.build_and_review.outputs.current_base == 'true'",
            deploy_job,
        )
        self.assertIn("environment:\n      name: production", deploy_job)
        self.assertIn(
            "ref: ${{ needs.build_and_review.outputs.reviewed_sha }}",
            deploy_job,
        )
        self.assertNotIn("secrets.AWS_", build_job)
        self.assertEqual(deploy_job.count("secrets.AWS_"), 2)
        self.assertLess(
            deploy_job.index('[[ "$remote_sha" == "$EXPECTED_SHA" ]]'),
            deploy_job.index("hugo deploy --force"),
        )

        action_start = main.index("uses: ./.github/actions/publish-generated-data-pr")
        action_end = main.index("- name: Build")
        preprocessing_action = main[action_start:action_end]
        generated_files = (
            "data/category_data.yml",
            "data/category_data_windows.yml",
            "data/recently_added_packages.yaml",
        )
        self.assertIn("paths: |", preprocessing_action)
        self.assertIn("required-tracked-paths: |", preprocessing_action)
        for path in generated_files:
            self.assertEqual(preprocessing_action.count(path), 2)

        self.assertIn("data/test-results/", summary)
        self.assertIn("data/test-results-index.json", summary)
        self.assertIn("batch${i}-test-results", summary)
        self.assertIn("DOWNLOAD_FAILURES=$((DOWNLOAD_FAILURES + 1))", summary)
        self.assertIn(
            "Refusing publication because one or more batch downloads failed",
            summary,
        )
        self.assertIn("GITHUB_STEP_SUMMARY", summary)
        self.assertIn("ref: ${{ github.sha }}", summary)
        self.assertNotIn("ref: ${{ inputs.expected_sha }}", summary)
        self.assertNotIn("ref: ${{ github.ref }}", summary)
        self.assertIn(
            "required-tracked-paths: data/test-results-index.json",
            summary,
        )
        self.assertLess(
            summary.index("Remove generated-data scratch paths"),
            summary.index("Open or update aggregated test-results review PR"),
        )
        self.assertEqual(summary.count("if: always()"), 1)
        self.assertIn(
            "if: steps.assemble.outcome == 'success' && "
            "steps.assemble.outputs.json_count != '0'",
            summary,
        )
        self.assertIn(
            "if: steps.normalize.outcome == 'success' && "
            "steps.assemble.outputs.json_count != '0'",
            summary,
        )
        publisher_start = summary.index(
            "- name: Open or update aggregated test-results review PR"
        )
        publisher_step = summary[publisher_start:]
        for required_outcome in (
            "steps.download.outcome == 'success'",
            "steps.assemble.outcome == 'success'",
            "steps.normalize.outcome == 'success'",
            "steps.promote.outcome == 'success'",
            "steps.publication_base.outcome == 'success'",
        ):
            self.assertIn(required_outcome, publisher_step)
        self.assertIn("success()", publisher_step)
        self.assertNotIn("always()", publisher_step)
        assembly_start = summary.index(
            "- name: Assemble candidate and previous-production staging sets"
        )
        normalize_start = summary.index("- name: Validate candidate exact job URLs")
        assembly_step = summary[assembly_start:normalize_start]
        self.assertIn("PackageCatalog.load(Path.cwd())", assembly_step)
        self.assertIn("catalog.from_metadata(", assembly_step)
        self.assertIn("destinations.claim(", assembly_step)
        self.assertIn("candidate_destinations.destination(slug)", assembly_step)
        self.assertNotIn("package_map.get(", assembly_step)
        self.assertLess(
            assembly_step.index("catalog.from_metadata("),
            assembly_step.index("destinations.claim("),
        )
        for scratch_path in (
            "downloaded-results",
            ".orchestration",
            ".summary-package-map.json",
            ".summary-staging",
            "test-results",
        ):
            self.assertIn(scratch_path, summary)

        documentation = (
            repository / ".github/actions/publish-generated-data-pr/README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("required approving reviews", documentation)
        self.assertIn("required checks", documentation)
        self.assertIn("administrators", documentation)
        self.assertIn("protected production environment", documentation)
        self.assertIn("Do not merge or activate", documentation)
        self.assertIn("Approve workflows to run", documentation)
        self.assertIn("optional only", documentation)
        self.assertIn("Workflow permissions", documentation)
        self.assertIn("write access remains an", documentation)
        self.assertIn("owner-setting activation blocker", documentation)

    def test_batch_count_contract_is_ready_for_parent_integration(self) -> None:
        repository = ACTION_ROOT.parents[2]
        workflow_root = repository / ".github/workflows"
        batch_numbers = sorted(
            int(path.stem.removeprefix("test-all-packages-batch"))
            for path in workflow_root.glob("test-all-packages-batch*.yml")
        )
        self.assertEqual(
            batch_numbers,
            list(range(1, EXPECTED_BATCH_COUNT + 1)),
            "The workflow inventory and orchestration range must stay aligned.",
        )

        orchestrator = (
            workflow_root / "test-all-packages-orchestrator.yml"
        ).read_text(encoding="utf-8")
        summary = (
            workflow_root / "test-all-packages-summary.yml"
        ).read_text(encoding="utf-8")
        loop = f"for i in {{1..{EXPECTED_BATCH_COUNT}}}; do"
        self.assertEqual(orchestrator.count(loop), 2)
        self.assertEqual(summary.count(loop), 1)


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed


if __name__ == "__main__":
    unittest.main()
