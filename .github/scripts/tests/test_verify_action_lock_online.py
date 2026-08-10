from __future__ import annotations

import copy
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "verify_action_lock_online.py"
SPEC = importlib.util.spec_from_file_location("verify_action_lock_online", SCRIPT)
assert SPEC and SPEC.loader
online = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(online)


COMMIT = "1" * 40
TAG_OBJECT = "2" * 40
FILE_SHA = "3" * 40


def action_entry(ref_type: str = "lightweight_tag") -> dict[str, object]:
    requested_ref = "v1" if ref_type != "branch" else "stable"
    ref_object = TAG_OBJECT if ref_type == "annotated_tag" else COMMIT
    resolution_chain: list[dict[str, str]] = []
    if ref_type == "annotated_tag":
        resolution_chain.append(
            {
                "tag_object": TAG_OBJECT,
                "target_type": "commit",
                "target_sha": COMMIT,
            }
        )
    return {
        "original_ref": f"example/action@{requested_ref}",
        "occurrences": 1,
        "repository": "example/action",
        "repository_id": 1234,
        "action_path": "",
        "action_file": "action.yml",
        "requested_ref": requested_ref,
        "ref_type": ref_type,
        "resolved_commit": COMMIT,
        "resolution_chain": resolution_chain,
        "github_api_repository_confirmed": True,
        "github_api_commit_confirmed": True,
        "action_file_confirmed_at_commit": True,
        "git_ls_remote": {
            "ref_object": ref_object,
            "peeled_commit": COMMIT,
            "matches_github_api": True,
        },
        "github_commit_verification": {
            "verified": True,
            "reason": "valid",
            "signature_present": True,
            "payload_present": True,
        },
    }


def repository_payload() -> dict[str, object]:
    return {"id": 1234, "full_name": "example/action"}


def commit_payload(sha: str = COMMIT) -> dict[str, object]:
    return {
        "sha": sha,
        "commit": {
            "verification": {
                "verified": True,
                "reason": "valid",
                "signature": "signed",
                "payload": "payload",
            }
        },
    }


def contents_payload() -> dict[str, object]:
    return {"type": "file", "path": "action.yml", "sha": FILE_SHA}


class VerifyActionLockOnlineTests(unittest.TestCase):
    def verify(self, entry: dict[str, object], output: str) -> None:
        online.validate_live_action_evidence(
            entry,
            repository_payload(),
            commit_payload(),
            contents_payload(),
            output,
        )

    def test_accepts_matching_lightweight_tag_evidence(self) -> None:
        self.verify(action_entry(), f"{COMMIT}\trefs/tags/v1\n")

    def test_accepts_matching_branch_evidence(self) -> None:
        self.verify(action_entry("branch"), f"{COMMIT}\trefs/heads/stable\n")

    def test_branch_assertion_is_rejected_when_same_name_tag_exists(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "missing or ambiguous"):
            self.verify(
                action_entry("branch"),
                f"{COMMIT}\trefs/heads/stable\n{COMMIT}\trefs/tags/stable\n",
            )

    def test_tag_wins_when_same_name_branch_exists(self) -> None:
        self.verify(
            action_entry(),
            f"{COMMIT}\trefs/heads/v1\n{COMMIT}\trefs/tags/v1\n",
        )

    def test_accepts_peeled_annotated_tag_evidence(self) -> None:
        self.verify(
            action_entry("annotated_tag"),
            f"{TAG_OBJECT}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n",
        )

    def test_consistently_forged_zero_sha_record_is_rejected(self) -> None:
        entry = action_entry()
        entry["resolved_commit"] = "0" * 40
        entry["git_ls_remote"] = {
            "ref_object": "0" * 40,
            "peeled_commit": "0" * 40,
            "matches_github_api": True,
        }
        with self.assertRaisesRegex(online.OnlineEvidenceError, "not a Git object ID"):
            online.validate_live_action_evidence(
                entry,
                repository_payload(),
                commit_payload("0" * 40),
                contents_payload(),
                f"{'0' * 40}\trefs/tags/v1\n",
            )

    def test_repository_substitution_is_rejected(self) -> None:
        payload = repository_payload()
        payload["full_name"] = "attacker/action"
        with self.assertRaisesRegex(online.OnlineEvidenceError, "repository identity"):
            online.validate_live_action_evidence(
                action_entry(), payload, commit_payload(), contents_payload(),
                f"{COMMIT}\trefs/tags/v1\n",
            )

    def test_verification_mismatch_is_rejected(self) -> None:
        payload = commit_payload()
        verification = payload["commit"]["verification"]  # type: ignore[index]
        verification.update(  # type: ignore[union-attr]
            {"verified": False, "reason": "unsigned", "signature": None,
             "payload": None}
        )
        with self.assertRaisesRegex(online.OnlineEvidenceError, "verification"):
            online.validate_live_action_evidence(
                action_entry(), repository_payload(), payload, contents_payload(),
                f"{COMMIT}\trefs/tags/v1\n",
            )

    def test_missing_action_file_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "action file"):
            online.validate_live_action_evidence(
                action_entry(), repository_payload(), commit_payload(),
                {"message": "Not Found"}, f"{COMMIT}\trefs/tags/v1\n",
            )

    def test_mutable_ref_movement_is_rejected(self) -> None:
        moved = "4" * 40
        with self.assertRaisesRegex(online.OnlineEvidenceError, "ref object"):
            self.verify(action_entry(), f"{moved}\trefs/tags/v1\n")

    def test_annotated_tag_without_peeled_ref_is_rejected(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "missing or ambiguous"):
            self.verify(
                action_entry("annotated_tag"),
                f"{TAG_OBJECT}\trefs/tags/v1\n",
            )

    def test_malformed_ls_remote_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "malformed"):
            self.verify(action_entry(), "not-a-sha refs/tags/v1\n")

    def test_ref_query_uses_exact_head_tag_and_peeled_tag_names(self) -> None:
        self.assertEqual(
            ("refs/heads/v1", "refs/tags/v1", "refs/tags/v1^{}"),
            online.ref_query_names("v1"),
        )

    def test_missing_commit_verification_is_rejected(self) -> None:
        payload = copy.deepcopy(commit_payload())
        del payload["commit"]["verification"]  # type: ignore[index]
        with self.assertRaisesRegex(online.OnlineEvidenceError, "verification"):
            online.validate_live_action_evidence(
                action_entry(), repository_payload(), payload, contents_payload(),
                f"{COMMIT}\trefs/tags/v1\n",
            )

    @mock.patch.object(online.subprocess, "run")
    def test_command_runner_is_bounded_and_noninteractive(
        self, run: mock.Mock
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["git", "ls-remote"], 0, "evidence\n", ""
        )
        self.assertEqual("evidence\n", online.run_command(["git", "ls-remote"]))
        options = run.call_args.kwargs
        self.assertEqual(60, options["timeout"])
        self.assertEqual("0", options["env"]["GIT_TERMINAL_PROMPT"])
        self.assertTrue(options["capture_output"])

    @mock.patch.object(online.subprocess, "run")
    def test_command_timeout_fails_closed(self, run: mock.Mock) -> None:
        run.side_effect = subprocess.TimeoutExpired(["git", "ls-remote"], 60)
        with self.assertRaisesRegex(online.OnlineEvidenceError, "could not complete"):
            online.run_command(["git", "ls-remote"])


if __name__ == "__main__":
    unittest.main()
