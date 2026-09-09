from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "generated_site_data_artifact.py"
SPEC = importlib.util.spec_from_file_location("generated_site_data_artifact", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
artifact = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = artifact
SPEC.loader.exec_module(artifact)


class GeneratedSiteDataArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--initial-branch=main")
        self._git("config", "user.name", "Artifact Test")
        self._git("config", "user.email", "artifact@example.invalid")
        for index, relative in enumerate(artifact.ALLOWLIST):
            path = self.repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"original-{index}\n", encoding="utf-8")
        (self.repository / "README.md").write_text("dashboard\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-m", "base")
        self.base_sha = self._git("rev-parse", "HEAD").strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _change_allowlisted_files(self) -> dict[str, bytes]:
        expected: dict[str, bytes] = {}
        for index, relative in enumerate(artifact.ALLOWLIST):
            data = f"generated-{index}\n".encode()
            (self.repository / relative).write_bytes(data)
            expected[relative] = data
        return expected

    def _pack(self, directory_name: str = "artifact") -> tuple[Path, str]:
        directory = self.root / directory_name
        directory.mkdir()
        archive = directory / artifact.ARCHIVE_NAME
        digest = artifact.pack(self.repository, archive, self.base_sha)
        return directory, digest

    def _pack_changed_and_reset(self) -> tuple[Path, str, dict[str, bytes]]:
        expected = self._change_allowlisted_files()
        directory, digest = self._pack()
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        return directory, digest, expected

    def _archive_members(self, directory: Path) -> list[tuple[zipfile.ZipInfo, bytes]]:
        with zipfile.ZipFile(directory / artifact.ARCHIVE_NAME, "r") as archive:
            return [(info, archive.read(info.filename)) for info in archive.infolist()]

    def _replace_archive(
        self,
        directory: Path,
        members: list[tuple[zipfile.ZipInfo, bytes]],
    ) -> str:
        archive_path = directory / artifact.ARCHIVE_NAME
        archive_path.unlink()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(
                archive_path, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for info, data in members:
                    archive.writestr(info, data)
        return hashlib.sha256(archive_path.read_bytes()).hexdigest()

    def _replace_manifest(
        self,
        directory: Path,
        transform,
        *,
        canonical: bool = True,
    ) -> str:
        members = self._archive_members(directory)
        original = json.loads(members[0][1])
        changed = transform(original)
        if isinstance(changed, bytes):
            raw = changed
        elif canonical:
            raw = artifact._canonical_json(changed)
        else:
            raw = json.dumps(changed, indent=2).encode()
        members[0] = (members[0][0], raw)
        return self._replace_archive(directory, members)

    def test_pack_is_deterministic_and_manifest_binds_every_file(self) -> None:
        self._change_allowlisted_files()
        first_directory, first_digest = self._pack("first")
        second_directory, second_digest = self._pack("second")

        first = (first_directory / artifact.ARCHIVE_NAME).read_bytes()
        second = (second_directory / artifact.ARCHIVE_NAME).read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(first_digest, second_digest)
        with zipfile.ZipFile(first_directory / artifact.ARCHIVE_NAME) as archive:
            manifest = json.loads(archive.read(artifact.MANIFEST_NAME))
            self.assertEqual(manifest["base_sha"], self.base_sha)
            self.assertEqual(
                tuple(item["path"] for item in manifest["files"]), artifact.ALLOWLIST
            )
            for item in manifest["files"]:
                payload = archive.read(f"{artifact.PAYLOAD_PREFIX}{item['path']}")
                self.assertEqual(item["size"], len(payload))
                self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())

    def test_pack_accepts_an_unchanged_allowlist(self) -> None:
        directory, digest = self._pack()
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertTrue((directory / artifact.ARCHIVE_NAME).is_file())

    def test_pack_accepts_normal_umask_permission_differences(self) -> None:
        os.chmod(self.repository / artifact.ALLOWLIST[0], 0o664)

        directory, digest = self._pack()

        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertTrue((directory / artifact.ARCHIVE_NAME).is_file())

    def test_pack_rejects_executable_mode_drift(self) -> None:
        path = self.repository / artifact.ALLOWLIST[0]
        os.chmod(path, 0o755)

        with self.assertRaisesRegex(artifact.ArtifactError, "executable mode differs"):
            self._pack("mode-755")

    def test_rejects_special_mode_bits(self) -> None:
        for special_mode in (stat.S_ISUID, stat.S_ISGID, stat.S_ISVTX):
            with self.subTest(mode=oct(special_mode)):
                with self.assertRaisesRegex(
                    artifact.ArtifactError, "unsafe special mode bits"
                ):
                    artifact._validate_regular_mode(
                        stat.S_IFREG | special_mode | 0o644,
                        0o644,
                        artifact.ALLOWLIST[0],
                    )

    def test_pack_rejects_wrong_base_sha(self) -> None:
        directory = self.root / "artifact"
        directory.mkdir()
        with self.assertRaisesRegex(artifact.ArtifactError, "HEAD does not match"):
            artifact.pack(self.repository, directory / artifact.ARCHIVE_NAME, "f" * 40)

    def test_pack_rejects_change_outside_allowlist(self) -> None:
        (self.repository / "README.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(artifact.ArtifactError, "outside the allowlist"):
            self._pack()

    def test_pack_rejects_untracked_files(self) -> None:
        (self.repository / "unexpected.txt").write_text(
            "unexpected\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(artifact.ArtifactError, "untracked paths"):
            self._pack()

    def test_pack_rejects_ignored_files(self) -> None:
        exclude = self.repository / ".git/info/exclude"
        exclude.write_text("generated.cache\n", encoding="utf-8")
        (self.repository / "generated.cache").write_text(
            "ignored but unexpected\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(artifact.ArtifactError, "including ignored paths"):
            self._pack()

    def test_pack_rejects_staged_changes(self) -> None:
        path = self.repository / artifact.ALLOWLIST[0]
        path.write_text("staged\n", encoding="utf-8")
        self._git("add", artifact.ALLOWLIST[0])
        with self.assertRaisesRegex(artifact.ArtifactError, "staged changes"):
            self._pack()

    def test_pack_rejects_missing_required_file(self) -> None:
        (self.repository / artifact.ALLOWLIST[0]).unlink()
        with self.assertRaisesRegex(artifact.ArtifactError, "missing"):
            self._pack()

    def test_pack_rejects_untracked_required_file(self) -> None:
        relative = artifact.ALLOWLIST[0]
        self._git("rm", "--cached", relative)
        with self.assertRaisesRegex(artifact.ArtifactError, "staged changes"):
            self._pack()
        with self.assertRaisesRegex(artifact.ArtifactError, "not uniquely tracked"):
            artifact._tracked_regular_mode(self.repository, relative)

    def test_pack_rejects_required_symlink(self) -> None:
        relative = artifact.ALLOWLIST[0]
        path = self.repository / relative
        path.unlink()
        path.symlink_to(self.repository / "README.md")
        with self.assertRaisesRegex(artifact.ArtifactError, "not a regular file"):
            self._pack()

    def test_pack_rejects_required_directory(self) -> None:
        path = self.repository / artifact.ALLOWLIST[0]
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(artifact.ArtifactError, "not a regular file"):
            self._pack()

    def test_pack_rejects_hard_linked_required_file(self) -> None:
        path = self.repository / artifact.ALLOWLIST[0]
        os.link(path, self.root / "hard-linked-generated-data.yml")

        with self.assertRaisesRegex(artifact.ArtifactError, "exactly one hard link"):
            self._pack()

    def test_pack_rejects_parent_symlink(self) -> None:
        data = self.repository / "data"
        moved = self.repository / "real-data"
        data.rename(moved)
        data.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "parent is not a real directory"
        ):
            self._pack()

    def test_pack_rejects_source_mutation_during_archive_creation(self) -> None:
        self._change_allowlisted_files()
        original_write = artifact._write_archive

        def mutating_write(path, manifest, snapshots):
            original_write(path, manifest, snapshots)
            (self.repository / artifact.ALLOWLIST[0]).write_text(
                "raced\n", encoding="utf-8"
            )

        directory = self.root / "artifact"
        directory.mkdir()
        output = directory / artifact.ARCHIVE_NAME
        with patch.object(artifact, "_write_archive", side_effect=mutating_write):
            with self.assertRaisesRegex(artifact.ArtifactError, "mutated during"):
                artifact.pack(self.repository, output, self.base_sha)
        self.assertFalse(output.exists())

    def test_pack_rejects_existing_or_misnamed_output(self) -> None:
        directory = self.root / "artifact"
        directory.mkdir()
        with self.assertRaisesRegex(artifact.ArtifactError, "must be named"):
            artifact.pack(self.repository, directory / "wrong.zip", self.base_sha)
        output = directory / artifact.ARCHIVE_NAME
        output.write_bytes(b"existing")
        with self.assertRaisesRegex(artifact.ArtifactError, "must not already exist"):
            artifact.pack(self.repository, output, self.base_sha)

    def test_pack_rejects_missing_or_symlinked_output_parent(self) -> None:
        with self.assertRaisesRegex(artifact.ArtifactError, "could not be inspected"):
            artifact.pack(
                self.repository,
                self.root / "missing" / artifact.ARCHIVE_NAME,
                self.base_sha,
            )
        real_parent = self.root / "real-artifact-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-artifact-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(artifact.ArtifactError, "must not be a symlink"):
            artifact.pack(
                self.repository,
                linked_parent / artifact.ARCHIVE_NAME,
                self.base_sha,
            )

    def test_restore_replaces_only_allowlisted_files(self) -> None:
        directory, digest, expected = self._pack_changed_and_reset()
        readme_before = (self.repository / "README.md").read_bytes()

        artifact.restore(self.repository, directory, self.base_sha, digest)

        for relative, data in expected.items():
            self.assertEqual((self.repository / relative).read_bytes(), data)
        self.assertEqual((self.repository / "README.md").read_bytes(), readme_before)
        changed = set(self._git("diff", "--name-only", "HEAD").splitlines())
        self.assertEqual(changed, set(artifact.ALLOWLIST))

    def test_restore_rejects_wrong_archive_digest(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        with self.assertRaisesRegex(artifact.ArtifactError, "digest does not match"):
            artifact.restore(self.repository, directory, self.base_sha, "0" * 64)

    def test_restore_rejects_wrong_checkout_base(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        (self.repository / "later.txt").write_text("later\n", encoding="utf-8")
        self._git("add", "later.txt")
        self._git("commit", "-m", "later")
        with self.assertRaisesRegex(artifact.ArtifactError, "HEAD does not match"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_dirty_or_untracked_publication_checkout(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        (self.repository / "README.md").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(artifact.ArtifactError, "not clean"):
            artifact.restore(self.repository, directory, self.base_sha, digest)
        self._git("restore", "README.md")
        (self.repository / "untracked.txt").write_text("x\n", encoding="utf-8")
        with self.assertRaisesRegex(artifact.ArtifactError, "untracked"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_extra_or_symlinked_downloads(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        (directory / "extra.txt").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(
            artifact.ArtifactError, "only the expected archive"
        ):
            artifact.restore(self.repository, directory, self.base_sha, digest)
        (directory / "extra.txt").unlink()
        archive_path = directory / artifact.ARCHIVE_NAME
        real_path = self.root / "real.zip"
        archive_path.rename(real_path)
        archive_path.symlink_to(real_path)
        with self.assertRaisesRegex(artifact.ArtifactError, "regular file"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_symlinked_artifact_directory(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        linked = self.root / "linked-artifact"
        linked.symlink_to(directory, target_is_directory=True)
        with self.assertRaisesRegex(artifact.ArtifactError, "must not be a symlink"):
            artifact.restore(self.repository, linked, self.base_sha, digest)

    def test_restore_rejects_malformed_and_noncanonical_json(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        malformed_digest = self._replace_manifest(directory, lambda _: b"{not-json}\n")
        with self.assertRaisesRegex(artifact.ArtifactError, "safe UTF-8 JSON"):
            artifact.restore(
                self.repository, directory, self.base_sha, malformed_digest
            )

        directory, _digest = self._pack("artifact-two")
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        noncanonical_digest = self._replace_manifest(
            directory, lambda value: value, canonical=False
        )
        with self.assertRaisesRegex(artifact.ArtifactError, "canonical JSON"):
            artifact.restore(
                self.repository, directory, self.base_sha, noncanonical_digest
            )

    def test_restore_rejects_duplicate_json_keys(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        members = self._archive_members(directory)
        original = members[0][1].decode().strip()
        duplicate = (
            original.replace(
                '"schema":',
                f'"schema":"{artifact.SCHEMA}","schema":',
                1,
            ).encode()
            + b"\n"
        )
        members[0] = (members[0][0], duplicate)
        digest = self._replace_archive(directory, members)
        with self.assertRaisesRegex(artifact.ArtifactError, "duplicate key"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_wrong_manifest_base(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        digest = self._replace_manifest(
            directory,
            lambda value: {**value, "base_sha": "f" * 40},
        )
        with self.assertRaisesRegex(artifact.ArtifactError, "base SHA"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_duplicate_manifest_entries(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()

        def duplicate(value):
            value["files"][1] = dict(value["files"][0])
            return value

        digest = self._replace_manifest(directory, duplicate)
        with self.assertRaisesRegex(artifact.ArtifactError, "duplicate file entry"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_manifest_path_traversal(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()

        def traverse(value):
            value["files"][0]["path"] = "../category_data.yml"
            return value

        digest = self._replace_manifest(directory, traverse)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "unsafe or unapproved path"
        ):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_manifest_digest_and_size_mismatch(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()

        def wrong_digest(value):
            value["files"][0]["sha256"] = "0" * 64
            return value

        digest = self._replace_manifest(directory, wrong_digest)
        with self.assertRaisesRegex(artifact.ArtifactError, "digest does not match"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        self._change_allowlisted_files()
        directory, _digest = self._pack("artifact-size")
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)

        def wrong_size(value):
            value["files"][0]["size"] += 1
            return value

        digest = self._replace_manifest(directory, wrong_size)
        with self.assertRaisesRegex(artifact.ArtifactError, "size does not match"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_missing_extra_or_out_of_order_members(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        members = self._archive_members(directory)
        missing_digest = self._replace_archive(directory, members[:-1])
        with self.assertRaisesRegex(
            artifact.ArtifactError, "missing, extra, or out of order"
        ):
            artifact.restore(self.repository, directory, self.base_sha, missing_digest)

        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        self._change_allowlisted_files()
        directory, _digest = self._pack("artifact-extra")
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        members = self._archive_members(directory)
        members.append((artifact._zip_info("payload/extra.yml"), b"extra"))
        extra_digest = self._replace_archive(directory, members)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "missing, extra, or out of order"
        ):
            artifact.restore(self.repository, directory, self.base_sha, extra_digest)

    def test_restore_rejects_archive_path_traversal_and_duplicate_names(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        members = self._archive_members(directory)
        traversal = [
            (artifact._zip_info("../manifest.json"), members[0][1]),
            *members[1:],
        ]
        digest = self._replace_archive(directory, traversal)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "missing, extra, or out of order"
        ):
            artifact.restore(self.repository, directory, self.base_sha, digest)

        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        self._change_allowlisted_files()
        directory, _digest = self._pack("artifact-duplicate")
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        members = self._archive_members(directory)
        members.append(members[-1])
        digest = self._replace_archive(directory, members)
        with self.assertRaisesRegex(artifact.ArtifactError, "duplicate member names"):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rejects_symlink_and_nonregular_archive_members(self) -> None:
        directory, _digest, _expected = self._pack_changed_and_reset()
        members = self._archive_members(directory)
        symlink = artifact._zip_info(members[1][0].filename)
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        members[1] = (symlink, members[1][1])
        digest = self._replace_archive(directory, members)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "not a canonical regular file"
        ):
            artifact.restore(self.repository, directory, self.base_sha, digest)

        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        self._change_allowlisted_files()
        directory, _digest = self._pack("artifact-directory-member")
        self._git("restore", "--source=HEAD", "--worktree", "--", *artifact.ALLOWLIST)
        members = self._archive_members(directory)
        directory_info = artifact._zip_info(members[1][0].filename)
        directory_info.external_attr = (stat.S_IFDIR | 0o755) << 16
        members[1] = (directory_info, members[1][1])
        digest = self._replace_archive(directory, members)
        with self.assertRaisesRegex(
            artifact.ArtifactError, "not a canonical regular file"
        ):
            artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_detects_destination_mutation_before_replacement(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        original_stage = artifact._stage_payloads

        def mutating_stage(repository, payloads):
            staged = original_stage(repository, payloads)
            (repository / artifact.ALLOWLIST[1]).write_text("raced\n", encoding="utf-8")
            return staged

        with patch.object(artifact, "_stage_payloads", side_effect=mutating_stage):
            with self.assertRaisesRegex(artifact.ArtifactError, "mutated during"):
                artifact.restore(self.repository, directory, self.base_sha, digest)

    def test_restore_rolls_back_if_a_destination_mutates_mid_restore(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        originals = {
            relative: (self.repository / relative).read_bytes()
            for relative in artifact.ALLOWLIST
        }
        real_replace = os.replace
        raced = False

        def racing_replace(source, destination):
            nonlocal raced
            real_replace(source, destination)
            if not raced and ".generated-" in str(source):
                raced = True
                (self.repository / artifact.ALLOWLIST[1]).write_text(
                    "raced\n", encoding="utf-8"
                )

        with patch.object(artifact.os, "replace", side_effect=racing_replace):
            with self.assertRaisesRegex(artifact.ArtifactError, "mutated during"):
                artifact.restore(self.repository, directory, self.base_sha, digest)
        for relative, original in originals.items():
            self.assertEqual((self.repository / relative).read_bytes(), original)

    def test_post_restore_verification_detects_any_intervening_change(self) -> None:
        directory, digest, _expected = self._pack_changed_and_reset()
        artifact.restore(self.repository, directory, self.base_sha, digest)
        artifact.verify_restored(self.repository, directory, self.base_sha, digest)

        (self.repository / artifact.ALLOWLIST[0]).write_text(
            "changed after credential minting\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(artifact.ArtifactError, "differ from the reviewed"):
            artifact.verify_restored(self.repository, directory, self.base_sha, digest)

    def test_cli_fails_closed_without_a_valid_command(self) -> None:
        completed = subprocess.run(
            ["python3", str(SCRIPT), "pack", "--repository", str(self.repository)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
