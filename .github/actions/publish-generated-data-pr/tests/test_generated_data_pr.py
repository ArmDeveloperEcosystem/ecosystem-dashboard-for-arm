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
            "user": {"login": config.expected_pr_author_login},
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


class PublisherConfigurationTests(unittest.TestCase):
    def test_environment_defaults_to_builtin_token_and_actions_bot(self) -> None:
        config = Config.from_environment(_valid_environment())

        self.assertEqual(config.credential_source, "github-token")
        self.assertEqual(config.expected_pr_author_login, "github-actions[bot]")

    def test_environment_accepts_github_app_installation_identity(self) -> None:
        environment = _valid_environment()
        environment.update(
            {
                "GENERATED_DATA_CREDENTIAL_SOURCE": "github-app",
                "GENERATED_DATA_EXPECTED_PR_AUTHOR_LOGIN": (
                    "arm-ecosystem-publisher[bot]"
                ),
            }
        )

        config = Config.from_environment(environment)

        self.assertEqual(config.credential_source, "github-app")
        self.assertEqual(
            config.expected_pr_author_login,
            "arm-ecosystem-publisher[bot]",
        )

    def test_rejects_malformed_expected_author_logins(self) -> None:
        malformed = (
            "",
            " github-actions[bot]",
            "github-actions[bot] ",
            "-publisher[bot]",
            "publisher-[bot]",
            "publisher bot",
            "owner/publisher[bot]",
            "publisher[admin]",
            f"{'a' * 101}[bot]",
        )
        for author_login in malformed:
            with self.subTest(author_login=author_login):
                environment = _valid_environment()
                environment["GENERATED_DATA_EXPECTED_PR_AUTHOR_LOGIN"] = author_login
                with self.assertRaisesRegex(PublishError, "author login is malformed"):
                    Config.from_environment(environment)

    def test_rejects_malformed_credential_sources(self) -> None:
        for credential_source in (
            "",
            "github-token ",
            "GITHUB-TOKEN",
            "github_app",
            "installation-token",
            "personal-access-token",
        ):
            with self.subTest(credential_source=credential_source):
                environment = _valid_environment()
                environment["GENERATED_DATA_CREDENTIAL_SOURCE"] = credential_source
                with self.assertRaisesRegex(PublishError, "credential source must be"):
                    Config.from_environment(environment)

    def test_rejects_author_and_credential_source_mismatches(self) -> None:
        mismatches = (
            ("github-token", "arm-ecosystem-publisher[bot]", "requires github-actions"),
            ("github-app", "release-manager", "requires a GitHub App bot"),
            ("github-app", "github-actions[bot]", "installed App bot author"),
        )
        for credential_source, author_login, error in mismatches:
            with self.subTest(
                credential_source=credential_source,
                author_login=author_login,
            ):
                environment = _valid_environment()
                environment.update(
                    {
                        "GENERATED_DATA_CREDENTIAL_SOURCE": credential_source,
                        "GENERATED_DATA_EXPECTED_PR_AUTHOR_LOGIN": author_login,
                    }
                )
                with self.assertRaisesRegex(PublishError, error):
                    Config.from_environment(environment)


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

    def test_default_pr_body_describes_builtin_token_without_activation(self) -> None:
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
        self.assertIn("GitHub Actions built-in `GITHUB_TOKEN`", body)
        self.assertIn("Expected PR author: `github-actions[bot]`", body)
        self.assertIn("may suppress recursive workflow starts", body)
        self.assertIn("does not mint credentials, change repository rules", body)

    def test_app_pr_body_describes_only_app_installation_credentials(self) -> None:
        worktree = self._clone("app-credential-guidance")
        (worktree / "data/generated.yml").write_text(
            "value: proposed\n",
            encoding="utf-8",
        )
        config = self._config(
            credential_source="github-app",
            expected_pr_author_login="arm-ecosystem-publisher[bot]",
        )

        publish_generated_data(
            config,
            repository_root=worktree,
            github=self.github,
        )

        body = self.github.pull_requests[0]["body"]
        self.assertIn("short-lived GitHub App installation token", body)
        self.assertIn(
            "Expected PR author: `arm-ecosystem-publisher[bot]`",
            body,
        )
        self.assertIn("App-authored pull-request events", body)
        self.assertNotIn("GITHUB_TOKEN", body)
        self.assertNotIn("fine-grained PAT", body)

    def test_app_author_ownership_comparison_is_case_insensitive(self) -> None:
        config = self._config(
            credential_source="github-app",
            expected_pr_author_login="Arm-Ecosystem-Publisher[bot]",
        )
        first = self._clone("app-author-first")
        (first / "data/generated.yml").write_text(
            "value: proposed\n",
            encoding="utf-8",
        )
        created = publish_generated_data(
            config,
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["user"]["login"] = (
            "arm-ecosystem-publisher[bot]"
        )

        second = self._clone("app-author-second")
        (second / "data/generated.yml").write_text(
            "value: proposed\n",
            encoding="utf-8",
        )
        unchanged = publish_generated_data(
            config,
            repository_root=second,
            github=self.github,
        )

        self.assertEqual(created.status, "created")
        self.assertEqual(unchanged.status, "unchanged")

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

    def test_rejects_wrong_app_bot_actor(self) -> None:
        config = self._config(
            credential_source="github-app",
            expected_pr_author_login="arm-ecosystem-publisher[bot]",
        )
        first = self._clone("first-app-pr-author")
        (first / "data/generated.yml").write_text(
            "value: proposed\n",
            encoding="utf-8",
        )
        publish_generated_data(
            config,
            repository_root=first,
            github=self.github,
        )
        self.github.pull_requests[0]["user"]["login"] = "other-app[bot]"

        next_run = self._clone("next-app-pr-author")
        (next_run / "data/generated.yml").write_text(
            "value: changed\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PublishError, "wrong author"):
            publish_generated_data(
                config,
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

        worktree = self._clone("required-deleted")
        (worktree / "data/generated.yml").unlink()

        with self.assertRaisesRegex(PublishError, "file is missing"):
            publish_generated_data(
                self._config(
                    required_tracked_paths=("data/generated.yml",),
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


class FoundationContractTests(unittest.TestCase):
    def test_action_exposes_validated_credential_metadata_inputs(self) -> None:
        action = (ACTION_ROOT / "action.yml").read_text(encoding="utf-8")

        self.assertIn("expected-pr-author-login:", action)
        self.assertIn("default: github-actions[bot]", action)
        self.assertIn("credential-source:", action)
        self.assertIn("default: github-token", action)
        self.assertIn("GENERATED_DATA_EXPECTED_PR_AUTHOR_LOGIN:", action)
        self.assertIn("GENERATED_DATA_CREDENTIAL_SOURCE:", action)

    def test_foundation_ci_is_read_only_and_sha_pins_external_actions(self) -> None:
        repository = ACTION_ROOT.parents[2]
        workflow = (
            repository
            / ".github/workflows/generated-data-publisher-foundation-ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("runs-on: ubuntu-24.04-arm", workflow)
        self.assertIn("python3 -m unittest discover", workflow)
        self.assertIn("actionlint_", workflow)
        self.assertIn("_linux_arm64.tar.gz", workflow)
        self.assertIn(
            "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
            workflow,
        )
        self.assertIn("sha256sum --check --strict", workflow)
        for line in workflow.splitlines():
            if "uses:" not in line:
                continue
            reference = line.split("uses:", maxsplit=1)[1].strip()
            _, separator, revision = reference.rpartition("@")
            self.assertEqual(separator, "@")
            self.assertRegex(revision, r"^[0-9a-f]{40}$")

    def test_readme_declares_dormant_least_privilege_foundation(self) -> None:
        readme = (ACTION_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("No existing", readme)
        self.assertIn("production workflow invokes it", readme)
        self.assertIn("does not change repository", readme)
        self.assertIn("Generation and publication should be separate jobs", readme)
        self.assertIn("contents: read", readme)
        self.assertIn("short-lived credential", readme)
        self.assertIn("does not activate", readme)


def _valid_environment() -> dict[str, str]:
    return {
        "GENERATED_DATA_PRODUCER": "test-producer",
        "GENERATED_DATA_BASE_BRANCH": "main",
        "GENERATED_DATA_EXPECTED_BASE_SHA": "a" * 40,
        "GENERATED_DATA_HEAD_BRANCH": (
            "automation/generated-data/test-producer/main"
        ),
        "GENERATED_DATA_TITLE": "Update generated test data",
        "GENERATED_DATA_COMMIT_MESSAGE": "Update generated test data",
        "GENERATED_DATA_PATHS": "data/generated.yml",
        "GENERATED_DATA_REQUIRED_TRACKED_PATHS": "data/generated.yml",
        "GITHUB_REPOSITORY": "example/dashboard",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_RUN_ID": "1",
        "GITHUB_REF_NAME": "main",
    }


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
