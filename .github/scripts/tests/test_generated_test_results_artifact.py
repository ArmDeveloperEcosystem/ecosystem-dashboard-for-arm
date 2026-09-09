from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "generated_test_results_artifact.py"
SPEC = importlib.util.spec_from_file_location("generated_test_results_artifact", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
artifact = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = artifact
SPEC.loader.exec_module(artifact)


class GeneratedTestResultsArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git(self.repository, "init", "--initial-branch=main")
        self._git(self.repository, "config", "user.name", "Test Author")
        self._git(self.repository, "config", "user.email", "test@example.com")
        results = self.repository / "data/test-results"
        results.mkdir(parents=True)
        (self.repository / artifact.INDEX_PATH).write_text(
            '{"packages":["alpha","beta"]}\n', encoding="utf-8"
        )
        (results / "alpha.json").write_text('{"status":"old"}\n', encoding="utf-8")
        (results / "beta.json").write_text('{"status":"old"}\n', encoding="utf-8")
        self._git(self.repository, "add", ".")
        self._git(self.repository, "commit", "-m", "Initial generated data")
        self.base_sha = self._git(
            self.repository, "rev-parse", "HEAD"
        ).stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def _prepare_candidate(self) -> None:
        results = self.repository / "data/test-results"
        (self.repository / artifact.INDEX_PATH).write_text(
            '{"packages":["alpha","gamma"]}\n', encoding="utf-8"
        )
        (results / "alpha.json").write_text('{"status":"new"}\n', encoding="utf-8")
        (results / "beta.json").unlink()
        (results / "gamma.json").write_text(
            '{"status":"new"}\n', encoding="utf-8"
        )

    def _pack(self) -> tuple[Path, str]:
        output_directory = self.root / "artifact-source"
        output_directory.mkdir(exist_ok=True)
        output = output_directory / artifact.ARTIFACT_NAME
        digest = artifact.pack(self.repository, output, self.base_sha)
        return output, digest

    def _download_directory(self, source: Path) -> Path:
        directory = self.root / f"download-{len(list(self.root.glob('download-*')))}"
        directory.mkdir()
        shutil.copyfile(source, directory / artifact.ARTIFACT_NAME)
        return directory

    def _clone_base(self, name: str = "publication") -> Path:
        clone = self.root / name
        self._git(self.root, "clone", "--quiet", str(self.repository), str(clone))
        self._git(clone, "checkout", "--quiet", self.base_sha)
        return clone

    def test_pack_restore_and_reverify_exact_add_update_delete_set(self) -> None:
        self._prepare_candidate()
        output, digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)

        artifact.restore(publication, download, self.base_sha, digest)
        artifact.verify_restored(publication, download, self.base_sha, digest)

        self.assertEqual(
            (publication / artifact.INDEX_PATH).read_text(encoding="utf-8"),
            '{"packages":["alpha","gamma"]}\n',
        )
        self.assertFalse((publication / "data/test-results/beta.json").exists())
        self.assertEqual(
            (publication / "data/test-results/gamma.json").read_text(
                encoding="utf-8"
            ),
            '{"status":"new"}\n',
        )
        changed = self._git(
            publication, "diff", "--name-only", "--no-renames", "HEAD"
        ).stdout.splitlines()
        self.assertEqual(
            changed,
            [
                artifact.INDEX_PATH,
                "data/test-results/alpha.json",
                "data/test-results/beta.json",
            ],
        )
        untracked = self._git(
            publication, "ls-files", "--others", "--exclude-standard"
        ).stdout.splitlines()
        self.assertEqual(untracked, ["data/test-results/gamma.json"])

    def test_pack_is_deterministic(self) -> None:
        self._prepare_candidate()
        first, first_digest = self._pack()
        first_bytes = first.read_bytes()
        first.unlink()

        second_digest = artifact.pack(
            self.repository,
            first,
            self.base_sha,
        )

        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first_bytes, first.read_bytes())

    def test_pack_rejects_out_of_scope_worktree_change(self) -> None:
        self._prepare_candidate()
        (self.repository / "README.md").write_text("unexpected\n", encoding="utf-8")

        with self.assertRaisesRegex(artifact.ArtifactError, "outside the allowlist"):
            self._pack()

    def test_pack_rejects_unexpected_result_entry(self) -> None:
        self._prepare_candidate()
        (self.repository / "data/test-results/not-json.txt").write_text(
            "unexpected\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(artifact.ArtifactError, "outside the allowlist"):
            self._pack()

    def test_pack_rejects_missing_tracked_index(self) -> None:
        self._prepare_candidate()
        (self.repository / artifact.INDEX_PATH).unlink()

        with self.assertRaisesRegex(artifact.ArtifactError, "index is missing"):
            self._pack()

    def test_restore_rejects_wrong_generation_digest(self) -> None:
        self._prepare_candidate()
        output, _digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)

        with self.assertRaisesRegex(artifact.ArtifactError, "digest does not match"):
            artifact.restore(publication, download, self.base_sha, "f" * 64)

    def test_restore_rejects_artifact_bound_to_another_base(self) -> None:
        self._prepare_candidate()
        output, digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)

        payload = json.loads((download / artifact.ARTIFACT_NAME).read_text())
        payload["base_sha"] = "f" * 40
        raw = artifact._canonical_json(payload)
        (download / artifact.ARTIFACT_NAME).write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()

        with self.assertRaisesRegex(artifact.ArtifactError, "base SHA"):
            artifact.restore(publication, download, self.base_sha, digest)

    def test_restore_rejects_unsafe_or_noncanonical_file_manifest(self) -> None:
        self._prepare_candidate()
        output, _digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)
        payload = json.loads((download / artifact.ARTIFACT_NAME).read_text())
        payload["files"][1]["path"] = "data/test-results/../outside.json"
        raw = artifact._canonical_json(payload)
        (download / artifact.ARTIFACT_NAME).write_bytes(raw)

        with self.assertRaisesRegex(artifact.ArtifactError, "unsafe path"):
            artifact.restore(
                publication,
                download,
                self.base_sha,
                hashlib.sha256(raw).hexdigest(),
            )

    def test_restore_rejects_extra_downloaded_artifact_entry(self) -> None:
        self._prepare_candidate()
        output, digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)
        (download / "extra.txt").write_text("unexpected\n", encoding="utf-8")

        with self.assertRaisesRegex(artifact.ArtifactError, "unexpected contents"):
            artifact.restore(publication, download, self.base_sha, digest)

    def test_post_mint_reverification_rejects_byte_or_path_drift(self) -> None:
        self._prepare_candidate()
        output, digest = self._pack()
        publication = self._clone_base()
        download = self._download_directory(output)
        artifact.restore(publication, download, self.base_sha, digest)
        (publication / "data/test-results/alpha.json").write_text(
            '{"status":"tampered"}\n', encoding="utf-8"
        )

        with self.assertRaisesRegex(artifact.ArtifactError, "differ from the artifact"):
            artifact.verify_restored(publication, download, self.base_sha, digest)


if __name__ == "__main__":
    unittest.main()
