from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
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
CONTAINER_DIGEST = "sha256:" + "a" * 64
ARM64_DIGEST = "sha256:" + "b" * 64
AMD64_DIGEST = "sha256:" + "c" * 64


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


def annotated_tag_payload() -> dict[str, object]:
    return {
        "sha": TAG_OBJECT,
        "tag": "v1",
        "object": {"type": "commit", "sha": COMMIT},
    }


def container_entry() -> dict[str, object]:
    return {
        "workflow": ".github/workflows/test-example.yml",
        "original_ref": "example:1",
        "repository": "example",
        "resolved_ref": f"example@{CONTAINER_DIGEST}",
        "resolved_digest": CONTAINER_DIGEST,
        "arm64_digest": ARM64_DIGEST,
        "media_type": "application/vnd.oci.image.index.v1+json",
        "linux_arm64_confirmed": True,
        "observed_at_utc": "2026-08-18T02:18:20Z",
        "arm64_runtime_validation": {
            "method": "Pull exact digest on aarch64",
            "result": "passed",
        },
    }


def container_manifest_payload(
    arm64_digest: str = ARM64_DIGEST,
) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "digest": AMD64_DIGEST,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            {
                "digest": arm64_digest,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "platform": {
                    "os": "linux",
                    "architecture": "arm64",
                    "variant": "v8",
                },
            },
        ],
    }


def single_manifest_evidence(oci: bool = False):
    entry = container_entry()
    entry.update(
        media_type=("application/vnd.oci.image.manifest.v1+json" if oci
                    else "application/vnd.docker.distribution.manifest.v2+json"),
        config_digest="sha256:" + "d" * 64,
    )
    manifest = {
        "schemaVersion": 2,
        "mediaType": entry["media_type"],
        "config": {
            "mediaType": ("application/vnd.oci.image.config.v1+json" if oci
                          else "application/vnd.docker.container.image.v1+json"),
            "digest": entry["config_digest"], "size": 200,
        },
        "layers": [{"digest": "sha256:" + "e" * 64, "size": 100}],
    }
    raw = json.dumps(manifest, separators=(",", ":"))
    digest = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    entry.update(resolved_ref=f"example@{digest}", resolved_digest=digest, arm64_digest=digest)
    config = {"architecture": "arm64", "os": "linux", "variant": "v8",
              "rootfs": {"type": "layers", "diff_ids": ["sha256:" + "f" * 64]}}
    return entry, manifest, config, raw


class AuthenticatedBaseLockTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / online.LOCK_RELATIVE_PATH
        self.path.parent.mkdir(parents=True)
        self.candidate = json.loads(
            (SCRIPT.parent / online.supply_chain.LOCK_NAME).read_text()
        )
        entry = action_entry("branch")
        entry["occurrences"] = 1131
        self.candidate["actions"] = [entry]
        self.base = copy.deepcopy(self.candidate)
        self.base["registered_workflows"] = 960
        self.base["external_uses"] = 1130
        self.base["actions"][0]["occurrences"] = 1130
        self.base_commit = "a" * 40
        self.base_type = "commit\n"
        self.base_raw = None
        self.drift = True
        self.commands = []
        self.api_overrides = {}
        patcher = mock.patch.object(online, "verify_live_container")
        self.containers = patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, command):
        self.commands.append(list(command))
        if command[0] == "git" and "cat-file" in command:
            return self.base_type
        if command[0] == "git" and "show" in command:
            return json.dumps(self.base) if self.base_raw is None else self.base_raw
        if command[:2] == ["git", "ls-remote"]:
            entry = next(
                entry for entry in self.candidate["actions"]
                if command[-3] == f"refs/heads/{entry['requested_ref']}"
            )
            ref = "heads" if entry["ref_type"] == "branch" else "tags"
            commit = "9" * 40 if self.drift else entry["git_ls_remote"]["ref_object"]
            result = f"{commit}\trefs/{ref}/{entry['requested_ref']}\n"
            if entry["ref_type"] == "annotated_tag":
                result += f"{COMMIT}\trefs/tags/{entry['requested_ref']}^{{}}\n"
            return result
        if command[:2] == ["gh", "api"]:
            endpoint = command[2]
            if endpoint in self.api_overrides:
                return json.dumps(self.api_overrides[endpoint])
            entry = self.candidate["actions"][0]
            if endpoint == f"repos/{entry['repository']}":
                return json.dumps({"id": entry["repository_id"], "full_name": entry["repository"]})
            if "/commits/" in endpoint:
                payload = commit_payload(entry["resolved_commit"])
                payload["commit"]["verification"]["reason"] = (
                    entry["github_commit_verification"]["reason"]
                )
                return json.dumps(payload)
            if "/contents/" in endpoint:
                return json.dumps({**contents_payload(), "path": entry["action_file"]})
            if "/git/tags/" in endpoint:
                return json.dumps(annotated_tag_payload())
        raise AssertionError(f"unexpected command: {command}")

    def verify(self, **kwargs):
        self.path.write_text(json.dumps(self.candidate))
        return online.verify_lock(self.path, self.runner, **kwargs)

    def mutable_calls(self):
        return [command for command in self.commands if command[:2] == ["git", "ls-remote"]]

    def test_unchanged_pin_allows_occurrence_change_and_moving_ref(self) -> None:
        self.assertEqual((1, 10), self.verify(expected_base_commit=self.base_commit))
        self.assertEqual([], self.mutable_calls())
        git = ["git", "--no-replace-objects", "-C", str(self.root)]
        self.assertEqual([
            [*git, "cat-file", "-t", self.base_commit],
            [*git, "show", f"{self.base_commit}:{online.LOCK_RELATIVE_PATH}"],
        ], self.commands[:2])
        self.assertEqual([
            ["gh", "api", "repos/example/action"],
            ["gh", "api", f"repos/example/action/commits/{COMMIT}"],
            ["gh", "api", f"repos/example/action/contents/action.yml?ref={COMMIT}"],
        ], self.commands[2:])
        self.assertEqual(10, self.containers.call_count)

    def test_no_base_keeps_full_live_ref_verification(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "live ref object contradicts"):
            self.verify()
        self.assertEqual(1, len(self.mutable_calls()))
        self.assertFalse(any("show" in command for command in self.commands))
        self.drift = False
        self.assertEqual((1, 10), self.verify())

    def test_authenticated_base_may_predate_a_reviewed_container_addition(self) -> None:
        self.base["containers"].pop()
        self.base["container_uses"] = len(self.base["containers"])
        expected = online.supply_chain.EXPECTED_CONTAINER_USES
        self.assertEqual((1, expected), self.verify(expected_base_commit=self.base_commit))
        self.assertEqual(expected, self.containers.call_count)
        self.assertEqual(
            [mock.call(entry, self.runner) for entry in self.candidate["containers"]],
            self.containers.call_args_list,
        )

    def test_new_container_live_verification_failure_cannot_be_inherited_from_base(self) -> None:
        self.base["containers"].pop()
        self.base["container_uses"] = len(self.base["containers"])
        added = self.candidate["containers"][-1]

        def verify_container(entry, runner):
            if entry == added:
                raise online.OnlineEvidenceError("new container digest mismatch")

        self.containers.side_effect = verify_container
        with self.assertRaisesRegex(online.OnlineEvidenceError, "new container digest mismatch"):
            self.verify(expected_base_commit=self.base_commit)
        self.containers.assert_called_with(added, self.runner)

    def test_older_inventory_is_never_accepted_as_the_candidate(self) -> None:
        self.candidate["containers"].pop()
        self.candidate["container_uses"] = len(self.candidate["containers"])
        with self.assertRaisesRegex(online.OnlineEvidenceError, "invalid container inventory"):
            self.verify(expected_base_commit=self.base_commit)
        self.assertEqual([], self.commands)

    def test_base_inventory_still_requires_matching_count_and_valid_entries(self) -> None:
        original = copy.deepcopy(self.base)
        for mutation in (
            lambda lock: lock.update(container_uses=0),
            lambda lock: lock.update(container_uses=True),
            lambda lock: lock["containers"][0].update(linux_arm64_confirmed=False),
            lambda lock: lock["containers"][0].update(unreviewed=True),
        ):
            with self.subTest(mutation=mutation):
                self.base = copy.deepcopy(original)
                mutation(self.base)
                with self.assertRaises(online.OnlineEvidenceError):
                    self.verify(expected_base_commit=self.base_commit)
        self.assertFalse(any(command[0] == "gh" for command in self.commands))

    def test_new_pin_requires_live_ref_confirmation(self) -> None:
        entry = action_entry()
        entry["occurrences"] = 1131
        self.candidate["actions"] = [entry]
        with self.assertRaisesRegex(online.OnlineEvidenceError, "live ref object contradicts"):
            self.verify(expected_base_commit=self.base_commit)
        self.assertEqual(1, len(self.mutable_calls()))
        self.drift = False
        self.assertEqual((1, 10), self.verify(expected_base_commit=self.base_commit))

    def test_same_ref_changed_commit_requires_full_live_verification(self) -> None:
        entry = self.candidate["actions"][0]
        entry["resolved_commit"] = "4" * 40
        entry["git_ls_remote"].update(ref_object="4" * 40, peeled_commit="4" * 40)
        with self.assertRaisesRegex(online.OnlineEvidenceError, "live ref object contradicts"):
            self.verify(expected_base_commit=self.base_commit)
        self.assertEqual(1, len(self.mutable_calls()))

    def test_same_pin_changed_evidence_does_not_receive_an_exemption(self) -> None:
        self.candidate["actions"][0]["github_commit_verification"]["reason"] = "different-reason"
        with self.assertRaisesRegex(online.OnlineEvidenceError, "live ref object contradicts"):
            self.verify(expected_base_commit=self.base_commit)
        self.assertEqual(1, len(self.mutable_calls()))

    def test_same_pin_changed_repository_identity_does_not_receive_an_exemption(self) -> None:
        self.candidate["actions"][0]["repository_id"] = 5678
        with self.assertRaisesRegex(online.OnlineEvidenceError, "live ref object contradicts"):
            self.verify(expected_base_commit=self.base_commit)
        self.assertEqual(1, len(self.mutable_calls()))

    def test_reviewed_annotated_tag_does_not_requery_mutable_resolution(self) -> None:
        entry = action_entry("annotated_tag")
        entry["occurrences"] = 1131
        self.candidate["actions"] = [entry]
        self.base = copy.deepcopy(self.candidate)
        self.assertEqual((1, 10), self.verify(expected_base_commit=self.base_commit))
        self.assertEqual([], self.mutable_calls())
        self.assertFalse(any("/git/tags/" in command[-1] for command in self.commands))

    def test_new_annotated_tag_still_requires_tag_object_evidence(self) -> None:
        entry = action_entry("annotated_tag")
        entry["occurrences"] = 1131
        self.candidate["actions"] = [entry]
        self.drift = False
        self.assertEqual((1, 10), self.verify(expected_base_commit=self.base_commit))
        self.assertEqual(1, len(self.mutable_calls()))
        self.assertIn(["gh", "api", f"repos/example/action/git/tags/{TAG_OBJECT}"], self.commands)

    def test_unchanged_pin_still_rejects_invalid_immutable_live_evidence(self) -> None:
        cases = (
            ("repos/example/action", {"id": 999, "full_name": "example/action"}),
            (f"repos/example/action/commits/{COMMIT}", commit_payload("5" * 40)),
            (f"repos/example/action/commits/{COMMIT}", {"sha": COMMIT, "commit": {}}),
            (f"repos/example/action/contents/action.yml?ref={COMMIT}", {"type": "dir"}),
        )
        for endpoint, payload in cases:
            with self.subTest(endpoint=endpoint, payload=payload):
                self.api_overrides = {endpoint: payload}
                with self.assertRaises(online.OnlineEvidenceError):
                    self.verify(expected_base_commit=self.base_commit)
        self.assertEqual([], self.mutable_calls())

    def test_malformed_base_identity_is_rejected_without_git_or_network(self) -> None:
        for base in ("", "HEAD", "a" * 39, "A" * 40, "0" * 40, "a" * 40 + ":path"):
            with self.subTest(base=base):
                with self.assertRaisesRegex(online.OnlineEvidenceError, "nonzero full commit SHA"):
                    self.verify(expected_base_commit=base)
        self.assertEqual([], self.commands)

    def test_base_must_be_a_commit_object(self) -> None:
        for kind in ("tree\n", "blob\n", "tag\n", ""):
            with self.subTest(kind=kind):
                self.base_type = kind
                with self.assertRaisesRegex(online.OnlineEvidenceError, "not a commit object"):
                    self.verify(expected_base_commit=self.base_commit)
        self.assertFalse(any(command[0] == "gh" for command in self.commands))

    def test_missing_base_or_base_lock_fails_closed(self) -> None:
        for failing_operation in ("cat-file", "show"):
            with self.subTest(operation=failing_operation):
                def runner(command):
                    if failing_operation in command:
                        raise online.OnlineEvidenceError("missing authenticated Git object")
                    return self.runner(command)
                self.path.write_text(json.dumps(self.candidate))
                with self.assertRaisesRegex(online.OnlineEvidenceError, "missing authenticated"):
                    online.verify_lock(self.path, runner, expected_base_commit=self.base_commit)

    def test_noncanonical_candidate_path_cannot_select_another_base_lock(self) -> None:
        path = self.root / "elsewhere.json"
        path.write_text(json.dumps(self.candidate))
        with self.assertRaisesRegex(online.OnlineEvidenceError, "canonical repository lock path"):
            online.verify_lock(path, self.runner, expected_base_commit=self.base_commit)
        self.assertEqual([], self.commands)

    def test_malformed_duplicate_and_nonfinite_base_json_are_rejected(self) -> None:
        for raw in ("", "not JSON", "[]", '{"actions": [], "actions": []}', '{"schema_version": NaN}'):
            with self.subTest(raw=raw):
                self.base_raw = raw
                with self.assertRaises(online.OnlineEvidenceError):
                    self.verify(expected_base_commit=self.base_commit)
        self.assertFalse(any(command[0] == "gh" for command in self.commands))

    def test_both_locks_are_validated_before_any_network_call(self) -> None:
        mutations = (
            lambda lock: lock.update(schema_version=2),
            lambda lock: lock.update(schema_version=True),
            lambda lock: lock.update(source_commit="a" * 40),
            lambda lock: lock.update(external_uses=1),
            lambda lock: lock.update(registered_workflows=True),
            lambda lock: lock.update(unresolved_references=["unreviewed"]),
            lambda lock: lock.update(hardened_topology_sha256="bad"),
            lambda lock: lock["actions"].append(copy.deepcopy(lock["actions"][0])),
            lambda lock: lock["actions"][0].update(skip_live_verification=True),
            lambda lock: lock["actions"][0].update(occurrences=True),
            lambda lock: lock["actions"][0].update(action_file_confirmed_at_commit=False),
            lambda lock: lock["containers"].pop(),
            lambda lock: lock["containers"].__setitem__(1, copy.deepcopy(lock["containers"][0])),
        )
        for target in ("candidate", "base"):
            original = copy.deepcopy(getattr(self, target))
            for mutation in mutations:
                with self.subTest(target=target, mutation=mutation):
                    setattr(self, target, copy.deepcopy(original))
                    mutation(getattr(self, target))
                    with self.assertRaises(online.OnlineEvidenceError):
                        self.verify(expected_base_commit=self.base_commit)
            setattr(self, target, original)
        self.assertFalse(any(command[0] == "gh" for command in self.commands))

    def test_cli_passes_base_explicitly_and_defaults_to_full_verification(self) -> None:
        for arguments, base in (([], None), (["--expected-base-commit", self.base_commit], self.base_commit)):
            with self.subTest(arguments=arguments), mock.patch.object(
                online.sys, "argv", [str(SCRIPT), "--lock", str(self.path), *arguments]
            ), mock.patch.object(online, "verify_lock", return_value=(1, 10)) as verify, mock.patch("builtins.print"):
                self.assertEqual(0, online.main())
                verify.assert_called_once_with(self.path, expected_base_commit=base)


class VerifyActionLockOnlineTests(unittest.TestCase):
    def verify(self, entry: dict[str, object], output: str) -> None:
        tag = annotated_tag_payload() if entry["ref_type"] == "annotated_tag" else None
        online.validate_live_action_evidence(
            entry,
            repository_payload(),
            commit_payload(),
            contents_payload(),
            output,
            tag,
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

    def test_annotated_tag_without_tag_object_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(online.OnlineEvidenceError, "annotated-tag"):
            online.validate_live_action_evidence(
                action_entry("annotated_tag"),
                repository_payload(),
                commit_payload(),
                contents_payload(),
                f"{TAG_OBJECT}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n",
            )

    def test_nested_annotated_tag_cannot_masquerade_as_direct(self) -> None:
        nested = annotated_tag_payload()
        nested["object"] = {"type": "tag", "sha": "4" * 40}
        with self.assertRaisesRegex(online.OnlineEvidenceError, "tag chain"):
            online.validate_live_action_evidence(
                action_entry("annotated_tag"),
                repository_payload(),
                commit_payload(),
                contents_payload(),
                f"{TAG_OBJECT}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n",
                nested,
            )

    def test_annotated_tag_name_and_object_are_bound(self) -> None:
        wrong_name = annotated_tag_payload()
        wrong_name["tag"] = "other"
        with self.assertRaisesRegex(online.OnlineEvidenceError, "tag chain"):
            online.validate_live_action_evidence(
                action_entry("annotated_tag"),
                repository_payload(),
                commit_payload(),
                contents_payload(),
                f"{TAG_OBJECT}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n",
                wrong_name,
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

    def test_accepts_matching_linux_arm64_container_evidence(self) -> None:
        online.validate_live_container_evidence(
            container_entry(), container_manifest_payload()
        )

    def test_accepts_matching_docker_manifest_list_evidence(self) -> None:
        entry = container_entry()
        payload = container_manifest_payload()
        entry["media_type"] = "application/vnd.docker.distribution.manifest.list.v2+json"
        payload["mediaType"] = entry["media_type"]
        for manifest in payload["manifests"]:
            manifest["mediaType"] = "application/vnd.docker.distribution.manifest.v2+json"
        online.validate_live_container_evidence(entry, payload)
        for digest in ("sha256:" + "0" * 64, "not-a-digest"):
            with self.subTest(digest=digest):
                mutated = copy.deepcopy(payload)
                mutated["manifests"][1]["digest"] = digest
                with self.assertRaises(online.OnlineEvidenceError):
                    online.validate_live_container_evidence(entry, mutated)

    def test_single_image_and_unknown_media_types_are_not_indexes(self) -> None:
        for media_type in (
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.oci.image.manifest.v1+json",
            "application/json", "", None,
        ):
            with self.subTest(media_type=media_type):
                entry = container_entry()
                payload = container_manifest_payload()
                entry["media_type"] = media_type
                payload["mediaType"] = media_type
                with self.assertRaises(online.OnlineEvidenceError):
                    online.validate_live_container_evidence(entry, payload)

    def test_container_media_type_mismatch_is_rejected(self) -> None:
        payload = container_manifest_payload()
        payload["mediaType"] = (
            "application/vnd.docker.distribution.manifest.list.v2+json"
        )
        with self.assertRaisesRegex(online.OnlineEvidenceError, "media type"):
            online.validate_live_container_evidence(container_entry(), payload)

    def test_direct_manifest_requires_its_config_and_matching_manifest_digest(self):
        for oci in (False, True):
            entry, manifest, config, _ = single_manifest_evidence(oci)
            online.validate_live_container_evidence(entry, manifest, config)
            for mutation in (lambda item: item.pop("config_digest"),
                             lambda item: item.update(config_digest="not-a-digest"),
                             lambda item: item.update(arm64_digest=ARM64_DIGEST),
                             lambda item: item.update(media_type=[])):
                changed = copy.deepcopy(entry)
                mutation(changed)
                with self.assertRaises(online.OnlineEvidenceError):
                    online.validate_live_container_evidence(changed, manifest, config)
            with self.assertRaises(online.OnlineEvidenceError):
                online.validate_live_container_evidence(entry, manifest)

    def test_direct_manifest_rejects_wrong_or_missing_linux_arm64_config(self):
        entry, manifest, config, _ = single_manifest_evidence()
        for key, value in (("architecture", "amd64"), ("architecture", None),
                           ("os", "windows"), ("os", None), ("variant", "v9")):
            changed = copy.deepcopy(config)
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(online.OnlineEvidenceError):
                online.validate_live_container_evidence(entry, manifest, changed)

    def test_direct_manifest_rejects_config_descriptor_and_index_substitution(self):
        entry, manifest, config, _ = single_manifest_evidence()
        mutations = (
            lambda item: item.update(schemaVersion=1),
            lambda item: item.update(manifests=[]),
            lambda item: item.update(config=None),
            lambda item: item["config"].update(digest="sha256:" + "0" * 64),
            lambda item: item["config"].update(mediaType="application/json"),
            lambda item: item["config"].update(size=0),
            lambda item: item["config"].update(size=True),
        )
        for mutation in mutations:
            changed = copy.deepcopy(manifest)
            mutation(changed)
            with self.assertRaises(online.OnlineEvidenceError):
                online.validate_live_container_evidence(entry, changed, config)

    def test_direct_manifest_rejects_incomplete_or_malformed_filesystem_evidence(self):
        entry, manifest, config, _ = single_manifest_evidence()
        for layers in (None, [], [None], [{"digest": "bad", "size": 10}],
                       [{"digest": "sha256:" + "e" * 64, "size": False}]):
            changed = copy.deepcopy(manifest)
            changed["layers"] = layers
            with self.assertRaises(online.OnlineEvidenceError):
                online.validate_live_container_evidence(entry, changed, config)
        for rootfs in (None, {}, {"type": "layers", "diff_ids": []},
                       {"type": "layers", "diff_ids": ["bad"]},
                       {"type": "other", "diff_ids": ["sha256:" + "f" * 64]}):
            changed = copy.deepcopy(config)
            changed["rootfs"] = rootfs
            with self.assertRaises(online.OnlineEvidenceError):
                online.validate_live_container_evidence(entry, manifest, changed)

    def test_direct_manifest_online_commands_bind_config_to_exact_pinned_reference(self):
        entry, _, config, raw = single_manifest_evidence()
        for suffix in ("", "\n"):
            calls = []
            def runner(command):
                calls.append(command)
                return raw + suffix if command[-1] == "--raw" else json.dumps(config)
            online.verify_live_container(entry, runner)
            self.assertEqual([
                ["docker", "buildx", "imagetools", "inspect", entry["resolved_ref"], "--raw"],
                ["docker", "buildx", "imagetools", "inspect", entry["resolved_ref"],
                 "--format", "{{json .Image}}"],
            ], calls)

    def test_direct_manifest_online_rejects_raw_digest_mismatch_before_config_lookup(self):
        entry, manifest, _, _ = single_manifest_evidence()
        manifest["config"]["digest"] = "sha256:" + "0" * 64
        calls = []
        def runner(command):
            calls.append(command)
            return json.dumps(manifest)
        with self.assertRaisesRegex(online.OnlineEvidenceError, "pinned digest"):
            online.verify_live_container(entry, runner)
        self.assertEqual(1, len(calls))

    def test_direct_manifest_online_missing_malformed_or_failed_config_is_rejected(self):
        entry, _, _, raw = single_manifest_evidence()
        for config_result in ("null", "[]", "{", "{}"):
            def runner(command):
                return raw if command[-1] == "--raw" else config_result
            with self.subTest(config_result=config_result), self.assertRaises(online.OnlineEvidenceError):
                online.verify_live_container(entry, runner)
        def failed_runner(command):
            if command[-1] == "--raw":
                return raw
            raise online.OnlineEvidenceError("config fetch failed")
        with self.assertRaisesRegex(online.OnlineEvidenceError, "config fetch failed"):
            online.verify_live_container(entry, failed_runner)

    def test_missing_or_wrong_arm64_container_digest_is_rejected(self) -> None:
        missing = container_manifest_payload()
        missing_manifests = missing["manifests"]
        assert isinstance(missing_manifests, list)
        missing["manifests"] = [missing_manifests[0]]
        cases = (
            container_manifest_payload("sha256:" + "d" * 64),
            missing,
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    online.OnlineEvidenceError, "Arm64 manifest contradicts"
                ):
                    online.validate_live_container_evidence(
                        container_entry(), payload
                    )

    def test_duplicate_or_malformed_arm64_container_evidence_is_rejected(self) -> None:
        duplicate = container_manifest_payload()
        duplicate_manifests = duplicate["manifests"]
        assert isinstance(duplicate_manifests, list)
        duplicate_manifests.append(copy.deepcopy(duplicate_manifests[1]))

        malformed = container_manifest_payload()
        malformed_manifests = malformed["manifests"]
        assert isinstance(malformed_manifests, list)
        malformed_platform = malformed_manifests[1]["platform"]
        assert isinstance(malformed_platform, dict)
        malformed_platform["variant"] = "v9"

        for payload in (duplicate, malformed):
            with self.subTest(payload=payload):
                with self.assertRaises(online.OnlineEvidenceError):
                    online.validate_live_container_evidence(
                        container_entry(), payload
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
