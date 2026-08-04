"""Focused fail-closed tests for the dashboard package identity catalog."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from build_steps import validate_package_identity_catalog as validator_module
from build_steps.validate_package_identity_catalog import (
    CATALOG_REPOSITORY_PATH,
    CONTENT_ROOT,
    MAX_PACKAGE_BYTES,
    MAX_WORKFLOW_BYTES,
    CatalogValidationError,
    calculate_corpus_sha256,
    validate_catalog,
    validate_catalog_revision,
)


class CatalogFixture:
    """Build a small synthetic dashboard tree and its exact catalog."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: list[dict[str, Any]] = []
        self.path_digests: list[tuple[str, str | None]] = []
        (root / "config.toml").write_text(
            'baseURL = "/"\ntheme = "arm-design-system-hugo-theme"\n',
            encoding="utf-8",
        )
        (root / "config.cloudfront.toml").write_text(
            'baseURL = "https://example.com/"\n',
            encoding="utf-8",
        )
        theme = root / "themes" / "arm-design-system-hugo-theme"
        theme.mkdir(parents=True, exist_ok=True)
        for directory in ("archetypes", "layouts", "static"):
            mounted = theme / directory
            mounted.mkdir(exist_ok=True)
            (mounted / ".keep").write_text("\n", encoding="ascii")
        (theme / "theme.toml").write_text(
            'name = "Catalog test theme"\n',
            encoding="utf-8",
        )

    def add_package(
        self,
        slug: str,
        *,
        workflow_present: bool,
        pip_identities: tuple[str, ...] = (),
        npm_identities: tuple[str, ...] = (),
    ) -> None:
        content_path = f"{CONTENT_ROOT}/{slug}.md"
        page = self.root / content_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f"---\nname: {slug}\n"
            f"download_url: https://github.com/example/{slug}\n---\n",
            encoding="utf-8",
        )
        content_sha256 = _sha256(page.read_bytes())
        workflow_path = f".github/workflows/test-{slug}.yml"
        workflow_file = self.root / workflow_path
        if workflow_present:
            workflow_file.parent.mkdir(parents=True, exist_ok=True)
            workflow_file.write_text(
                f"name: Test {slug}\non:\n  workflow_call:\n",
                encoding="utf-8",
            )
            workflow_sha256: str | None = _sha256(workflow_file.read_bytes())
            workflow = {
                "path": workflow_path,
                "presence": "present",
                "sha256": workflow_sha256,
            }
        else:
            workflow_sha256 = None
            workflow = {
                "path": workflow_path,
                "presence": "absent",
                "sha256": None,
            }

        self.path_digests.extend(
            (
                (content_path, content_sha256),
                (workflow_path, workflow_sha256),
            )
        )
        self.records.append(
            {
                "slug": slug,
                "content_path": content_path,
                "content_sha256": content_sha256,
                "workflow": workflow,
                "registries": {
                    "pip": _dimension(
                        "pip",
                        content_path,
                        content_sha256,
                        pip_identities,
                    ),
                    "npm": _dimension(
                        "npm",
                        content_path,
                        content_sha256,
                        npm_identities,
                    ),
                },
            }
        )

    def payload(self) -> dict[str, Any]:
        records = sorted(self.records, key=lambda record: record["content_path"])
        return {
            "schema_version": "1.1",
            "corpus": {
                "content_root": CONTENT_ROOT,
                "entry_count": len(records),
                "corpus_sha256": calculate_corpus_sha256(self.path_digests),
            },
            "records": records,
        }

    def write(self, payload: dict[str, Any] | None = None) -> Path:
        catalog = self.root / CATALOG_REPOSITORY_PATH
        catalog.parent.mkdir(parents=True, exist_ok=True)
        _write_canonical(catalog, self.payload() if payload is None else payload)
        return catalog


def _write_valid_fixture(root: Path) -> CatalogFixture:
    fixture = CatalogFixture(root)
    fixture.add_package("alpha", workflow_present=True)
    fixture.add_package("beta", workflow_present=False)
    fixture.write()
    return fixture


def _commit_valid_fixture(root: Path) -> str:
    _write_valid_fixture(root)
    return _commit_existing_tree(root, "catalog fixture")


def _commit_existing_tree(root: Path, message: str) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "catalog-tests@example.com")
    _git(root, "config", "user.name", "Catalog tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class PackageIdentityCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def fixture(self) -> CatalogFixture:
        return _write_valid_fixture(self.root)

    def test_valid_exact_catalog_passes(self) -> None:
        self.fixture()

        self.assertEqual(validate_catalog(self.root), 2)

    def test_revision_validation_uses_an_immutable_commit_snapshot(self) -> None:
        revision = _commit_valid_fixture(self.root)
        page = self.root / CONTENT_ROOT / "alpha.md"
        page.write_text(page.read_text(encoding="utf-8") + "dirty\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogValidationError, "content_sha256 is stale"):
            validate_catalog(self.root)

        count, resolved = validate_catalog_revision(
            self.root,
            revision=revision,
        )

        self.assertEqual((count, resolved), (2, revision))

    def test_revision_validation_accepts_head_and_rejects_moving_names(self) -> None:
        revision = _commit_valid_fixture(self.root)

        self.assertEqual(
            validate_catalog_revision(self.root, revision="HEAD"),
            (2, revision),
        )
        with self.assertRaisesRegex(
            CatalogValidationError,
            "revision must be HEAD or a full lowercase Git object ID",
        ):
            validate_catalog_revision(self.root, revision="main")

    def test_revision_snapshot_is_bounded_and_rejects_links(self) -> None:
        _commit_valid_fixture(self.root)
        with (
            patch.object(validator_module, "MAX_REVISION_TREE_BYTES", 1),
            self.assertRaisesRegex(CatalogValidationError, "tree inspection exceeded"),
        ):
            validate_catalog_revision(self.root)

        with (
            patch.object(validator_module, "MAX_REVISION_SNAPSHOT_BYTES", 1),
            self.assertRaisesRegex(CatalogValidationError, "snapshot exceeds"),
        ):
            validate_catalog_revision(self.root)

        with (
            patch.object(validator_module, "MAX_REVISION_SNAPSHOT_ENTRIES", 1),
            self.assertRaisesRegex(CatalogValidationError, "invalid entry count"),
        ):
            validate_catalog_revision(self.root)

        workflow = self.root / ".github/workflows/test-alpha.yml"
        workflow.unlink()
        workflow.symlink_to("test-beta.yml")
        _git(self.root, "add", ".github/workflows/test-alpha.yml")
        _git(self.root, "commit", "-qm", "replace workflow with a link")
        with self.assertRaisesRegex(
            CatalogValidationError,
            "link or special file",
        ):
            validate_catalog_revision(self.root)

    def test_revision_snapshot_rejects_gitlinks(self) -> None:
        revision = _commit_valid_fixture(self.root)
        gitlink = f"{CONTENT_ROOT}/nested-package"
        _git(
            self.root,
            "update-index",
            "--add",
            "--cacheinfo",
            "160000",
            revision,
            gitlink,
        )
        _git(self.root, "commit", "-qm", "add package gitlink")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "link or special file",
        ):
            validate_catalog_revision(self.root)

    def test_committed_export_ignore_cannot_hide_an_uncataloged_page(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        payload["records"] = [
            record for record in payload["records"] if record["slug"] == "alpha"
        ]
        _refresh_corpus(payload)
        fixture.write(payload)
        (self.root / ".gitattributes").write_text(
            f"{CONTENT_ROOT}/beta.md export-ignore\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt committed export-ignore bypass")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "exactly one record per package page",
        ):
            validate_catalog_revision(self.root)

    def test_info_export_ignore_cannot_hide_an_uncataloged_page(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        payload["records"] = [
            record for record in payload["records"] if record["slug"] == "alpha"
        ]
        _refresh_corpus(payload)
        fixture.write(payload)
        _commit_existing_tree(self.root, "attempt info export-ignore bypass")
        info_attributes = self.root / ".git/info/attributes"
        info_attributes.write_text(
            f"{CONTENT_ROOT}/beta.md export-ignore\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "exactly one record per package page",
        ):
            validate_catalog_revision(self.root)

    def test_committed_export_subst_cannot_forge_reviewed_bytes(self) -> None:
        fixture = self.fixture()
        page = self.root / CONTENT_ROOT / "alpha.md"
        page.write_text(
            page.read_text(encoding="utf-8") + "author: $Format:%an$\n",
            encoding="utf-8",
        )
        transformed = page.read_bytes().replace(b"$Format:%an$", b"Catalog tests")
        payload = fixture.payload()
        _replace_record_content_digest(payload, "alpha", _sha256(transformed))
        fixture.write(payload)
        (self.root / ".gitattributes").write_text(
            f"{CONTENT_ROOT}/alpha.md export-subst\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt committed export-subst bypass")

        with self.assertRaisesRegex(CatalogValidationError, "content_sha256 is stale"):
            validate_catalog_revision(self.root)

    def test_info_export_subst_does_not_rewrite_valid_raw_bytes(self) -> None:
        fixture = self.fixture()
        page = self.root / CONTENT_ROOT / "alpha.md"
        page.write_text(
            page.read_text(encoding="utf-8") + "author: $Format:%an$\n",
            encoding="utf-8",
        )
        payload = fixture.payload()
        _replace_record_content_digest(payload, "alpha", _sha256(page.read_bytes()))
        fixture.write(payload)
        revision = _commit_existing_tree(self.root, "retain raw export-subst bytes")
        info_attributes = self.root / ".git/info/attributes"
        info_attributes.write_text(
            f"{CONTENT_ROOT}/alpha.md export-subst\n",
            encoding="utf-8",
        )

        self.assertEqual(
            validate_catalog_revision(self.root),
            (2, revision),
        )

    def test_revision_validation_rejects_custom_catalog_paths(self) -> None:
        _commit_valid_fixture(self.root)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "requires the canonical catalog path",
        ):
            validate_catalog_revision(
                self.root,
                catalog_relative_path="custom/catalog.json",
            )

    def test_blob_reader_initialization_failure_reaps_git_process(self) -> None:
        _commit_valid_fixture(self.root)
        original_popen = subprocess.Popen
        processes: list[subprocess.Popen[bytes]] = []

        def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        with (
            patch.object(
                validator_module._DeadlinePipeReader,
                "__init__",
                side_effect=RuntimeError("selector initialization failed"),
            ),
            patch.object(
                validator_module.subprocess, "Popen", side_effect=recording_popen
            ),
            self.assertRaisesRegex(RuntimeError, "selector initialization failed"),
        ):
            validate_catalog_revision(self.root)

        self.assertTrue(processes)
        self.assertIsNotNone(processes[-1].poll())

    def test_blob_reader_registration_failure_closes_selector(self) -> None:
        class FailingSelector:
            def __init__(self) -> None:
                self.closed = False

            def register(self, _stream: object, _events: int) -> None:
                raise RuntimeError("selector registration failed")

            def close(self) -> None:
                self.closed = True

        selector = FailingSelector()
        with (
            patch.object(
                validator_module.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            self.assertRaisesRegex(RuntimeError, "selector registration failed"),
        ):
            validator_module._DeadlinePipeReader(object())

        self.assertTrue(selector.closed)

    def test_bounded_process_timeout_terminates_descendants(self) -> None:
        child_pid_file = self.root / "child.pid"
        script = (
            "import pathlib, subprocess, sys, time; "
            "child=subprocess.Popen([sys.executable, '-c', 'import time; "
            "time.sleep(60)'], stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL); "
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid)); "
            "time.sleep(60)"
        )
        with (
            patch.object(validator_module, "_GIT_TIMEOUT_SECONDS", 0.2),
            self.assertRaisesRegex(CatalogValidationError, "timed out"),
        ):
            validator_module._run_bounded_process(
                [sys.executable, "-c", script],
                maximum_stdout_bytes=1024,
                context="descendant cleanup probe",
            )

        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            self.fail("timed-out descendant process remained alive")

    def test_bounded_process_success_terminates_residual_descendants(self) -> None:
        child_pid_file = self.root / "successful-child.pid"
        script = (
            "import pathlib, subprocess, sys; "
            "child=subprocess.Popen([sys.executable, '-c', 'import time; "
            "time.sleep(60)'], stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL); "
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid))"
        )
        validator_module._run_bounded_process(
            [sys.executable, "-c", script],
            maximum_stdout_bytes=1024,
            context="successful descendant cleanup probe",
        )

        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            self.fail("successful child left a residual descendant process")

    def test_clean_checkout_byte_transformations_are_rejected(self) -> None:
        cases = {
            "ident": "ident",
            "forced_crlf": "text eol=crlf",
        }
        for name, attributes in cases.items():
            with (
                self.subTest(case=name),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                fixture = _write_valid_fixture(root)
                page = root / CONTENT_ROOT / "alpha.md"
                if name == "ident":
                    page.write_text(
                        page.read_text(encoding="utf-8") + "$Id$\n",
                        encoding="utf-8",
                    )
                    payload = fixture.payload()
                    _replace_record_content_digest(
                        payload,
                        "alpha",
                        _sha256(page.read_bytes()),
                    )
                    fixture.write(payload)
                (root / ".gitattributes").write_text(
                    f"{CONTENT_ROOT}/alpha.md {attributes}\n",
                    encoding="utf-8",
                )
                _commit_existing_tree(root, f"attempt {name} checkout transform")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "clean checkout bytes differ from the reviewed Git blob",
                ):
                    validate_catalog_revision(root)

        with tempfile.TemporaryDirectory(dir="/tmp") as repository_directory:
            root = Path(repository_directory)
            _write_valid_fixture(root)
            _commit_existing_tree(root, "valid UTF-8 package corpus")
            (root / ".gitattributes").write_text(
                f"{CONTENT_ROOT}/alpha.md working-tree-encoding=UTF-16\n",
                encoding="utf-8",
            )
            _git(root, "add", ".gitattributes")
            _git(root, "commit", "-qm", "attempt checkout encoding transform")
            with self.assertRaisesRegex(
                CatalogValidationError,
                "clean checkout bytes differ from the reviewed Git blob",
            ):
                validate_catalog_revision(root)

    def test_external_checkout_filters_are_rejected(self) -> None:
        _write_valid_fixture(self.root)
        (self.root / ".gitattributes").write_text(
            f"{CONTENT_ROOT}/alpha.md filter=unreviewed-smudge\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt external checkout filter")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "checkout filters are forbidden",
        ):
            validate_catalog_revision(self.root)

    def test_hugo_alternate_content_sources_fail_closed(self) -> None:
        for case in ("module_mount", "content_dir", "theme_content"):
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                shadow = root / "shadow"
                shadow.mkdir()
                (shadow / "evil.md").write_text(
                    "---\ntitle: Evil\n---\n",
                    encoding="utf-8",
                )
                config = root / "config.toml"
                if case == "module_mount":
                    config.write_text(
                        config.read_text(encoding="utf-8")
                        + "\n[module]\n"
                        + '[[module.mounts]]\nsource = "content"\n'
                        + 'target = "content"\n'
                        + '[[module.mounts]]\nsource = "shadow"\n'
                        + f'target = "{CONTENT_ROOT}"\n',
                        encoding="utf-8",
                    )
                elif case == "content_dir":
                    config.write_text(
                        config.read_text(encoding="utf-8")
                        + '\ncontentDir = "shadow"\n',
                        encoding="utf-8",
                    )
                else:
                    theme_content = (
                        root / "themes" / "arm-design-system-hugo-theme" / CONTENT_ROOT
                    )
                    theme_content.mkdir(parents=True)
                    (theme_content / "evil.md").write_text(
                        "---\ntitle: Evil\n---\n",
                        encoding="utf-8",
                    )
                _commit_existing_tree(root, f"attempt {case} Hugo source")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "Hugo effective (?:content or resource mounts|module)",
                ):
                    validate_catalog_revision(root)

    def test_hugo_external_url_and_alias_routes_fail_closed(self) -> None:
        for case in ("url", "alias"):
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                external = root / "content" / "other" / "evil.md"
                external.parent.mkdir(parents=True)
                route_key = "url" if case == "url" else "aliases"
                route_value = (
                    "/linux/opensource_packages/evil/"
                    if case == "url"
                    else "[/linux/opensource_packages/evil/]"
                )
                external.write_text(
                    f"---\ntitle: Evil\n{route_key}: {route_value}\n---\n",
                    encoding="utf-8",
                )
                _commit_existing_tree(root, f"attempt external {case} route")

                expected = (
                    "uncataloged Hugo source claims a package route"
                    if case == "url"
                    else "Hugo aliases are forbidden"
                )
                with self.assertRaisesRegex(CatalogValidationError, expected):
                    validate_catalog_revision(root)

    def test_hugo_existing_route_aliases_fail_closed(self) -> None:
        _write_valid_fixture(self.root)
        external = self.root / "content" / "other" / "evil.md"
        external.parent.mkdir(parents=True)
        external.write_text(
            "---\ntitle: Evil\naliases: [/linux/opensource_packages/alpha/]\n---\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt existing package route alias")

        with self.assertRaisesRegex(
            CatalogValidationError, "Hugo aliases are forbidden"
        ):
            validate_catalog_revision(self.root)

    def test_hugo_content_adapters_are_rejected_before_execution(self) -> None:
        _write_valid_fixture(self.root)
        adapter = self.root / "content" / "_content.gotmpl"
        adapter.write_text(
            '{{ errorf "this adapter must never execute" }}\n',
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt content adapter execution")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "content adapters are forbidden",
        ):
            validate_catalog_revision(self.root)

    def test_hugo_theme_cannot_escape_the_reviewed_repository_path(self) -> None:
        _write_valid_fixture(self.root)
        config = self.root / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'theme = "arm-design-system-hugo-theme"',
                'theme = "../../../../etc"',
            ),
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt external theme path")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "reviewed in-repository theme",
        ):
            validate_catalog_revision(self.root)

    def test_hugo_themes_directory_overrides_are_case_insensitively_rejected(
        self,
    ) -> None:
        cases = (
            ("config.toml", 'themesdir = "/tmp/unreviewed"\n'),
            ("config.cloudfront.toml", 'themesDir = "/tmp/unreviewed"\n'),
        )
        for relative_path, addition in cases:
            with (
                self.subTest(relative_path=relative_path),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                config = root / relative_path
                config.write_text(
                    config.read_text(encoding="utf-8") + addition,
                    encoding="utf-8",
                )
                _commit_existing_tree(root, "attempt external themes directory")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "themesDir overrides are forbidden",
                ):
                    validate_catalog_revision(root)

    def test_hugo_case_insensitive_config_duplicates_are_rejected(self) -> None:
        _write_valid_fixture(self.root)
        config = self.root / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8") + 'Theme = "other"\n',
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt case-insensitive config duplicate")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "case-insensitive duplicate keys",
        ):
            validate_catalog_revision(self.root)

    def test_repository_hugo_security_overrides_are_rejected(self) -> None:
        _write_valid_fixture(self.root)
        config = self.root / "config.cloudfront.toml"
        config.write_text(
            config.read_text(encoding="utf-8") + "[security.http]\nurls = ['.*']\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt repository security override")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "security overrides are forbidden",
        ):
            validate_catalog_revision(self.root)

    def test_hugo_cache_overrides_cannot_write_outside_render_workspace(self) -> None:
        _write_valid_fixture(self.root)
        with tempfile.TemporaryDirectory(dir="/tmp") as external_directory:
            external_cache = Path(external_directory)
            config = self.root / "config.cloudfront.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "[Caches.Images]\n"
                + f"dir = {json.dumps(str(external_cache))}\n",
                encoding="utf-8",
            )
            image = self.root / "assets" / "probe.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(
                bytes.fromhex(
                    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415408d763f8cfc0f01f00050001ff89993d1d"
                    "0000000049454e44ae426082"
                )
            )
            layout = self.root / "layouts" / "_default" / "single.html"
            layout.parent.mkdir(parents=True)
            layout.write_text(
                '{{ with resources.Get "probe.png" }}'
                '{{ (.Resize "1x1").RelPermalink }}{{ end }}\n',
                encoding="utf-8",
            )
            _commit_existing_tree(self.root, "attempt external Hugo image cache")

            with self.assertRaisesRegex(
                CatalogValidationError,
                "cache and build-output overrides are forbidden",
            ):
                validate_catalog_revision(self.root)

            self.assertEqual(list(external_cache.iterdir()), [])

    def test_hugo_build_stats_output_overrides_are_rejected(self) -> None:
        _write_valid_fixture(self.root)
        config = self.root / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8") + "[BUILD.buildStats]\nenable = true\n",
            encoding="utf-8",
        )
        _commit_existing_tree(self.root, "attempt Hugo build stats output")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "cache and build-output overrides are forbidden",
        ):
            validate_catalog_revision(self.root)

    def test_production_template_failures_fail_closed(self) -> None:
        for layout_kind in ("project", "theme"):
            with (
                self.subTest(layout_kind=layout_kind),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                layouts_root = (
                    root / "layouts"
                    if layout_kind == "project"
                    else root / "themes" / "arm-design-system-hugo-theme" / "layouts"
                )
                layout = layouts_root / "_default" / "single.html"
                layout.parent.mkdir(parents=True, exist_ok=True)
                layout.write_text(
                    '{{ errorf "production template failure" }}\n',
                    encoding="utf-8",
                )
                _commit_existing_tree(root, "attempt failing production template")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "Hugo production-render failed",
                ):
                    validate_catalog_revision(root)

    def test_production_templates_cannot_publish_extra_package_files(self) -> None:
        for layout_kind in ("project", "theme"):
            with (
                self.subTest(layout_kind=layout_kind),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                layouts_root = (
                    root / "layouts"
                    if layout_kind == "project"
                    else root / "themes" / "arm-design-system-hugo-theme" / "layouts"
                )
                layout = layouts_root / "_default" / "single.html"
                layout.parent.mkdir(parents=True, exist_ok=True)
                layout.write_text(
                    '{{ (resources.FromString "linux/opensource_packages/alpha/'
                    'unreviewed.txt" "unreviewed").RelPermalink }}\n',
                    encoding="utf-8",
                )
                _commit_existing_tree(root, "attempt production resource publication")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "production Hugo templates unexpectedly publish",
                ):
                    validate_catalog_revision(root)

    def test_package_detail_layout_requires_an_explicit_contract_change(self) -> None:
        _write_valid_fixture(self.root)
        layout = self.root / "layouts" / "_default" / "single.html"
        layout.parent.mkdir(parents=True)
        layout.write_text("package detail page\n", encoding="utf-8")
        _commit_existing_tree(self.root, "attempt package detail-page activation")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "production Hugo templates unexpectedly publish",
        ):
            validate_catalog_revision(self.root)

    def test_production_render_denies_hugo_http_requests(self) -> None:
        _write_valid_fixture(self.root)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            layout = self.root / "layouts" / "_default" / "single.html"
            layout.parent.mkdir(parents=True)
            layout.write_text(
                "{{ $remote := resources.GetRemote "
                f'"http://127.0.0.1:{port}/must-not-connect"'
                " }}{{ $remote.RelPermalink }}\n",
                encoding="utf-8",
            )
            _commit_existing_tree(self.root, "attempt Hugo HTTP request")

            with self.assertRaisesRegex(
                CatalogValidationError,
                "Hugo production-render failed",
            ):
                validate_catalog_revision(self.root)

            listener.settimeout(0.1)
            with self.assertRaises(TimeoutError):
                listener.accept()

    def test_static_files_cannot_claim_protected_package_routes(self) -> None:
        for static_root in (
            Path("static"),
            Path("themes/arm-design-system-hugo-theme/static"),
        ):
            with (
                self.subTest(static_root=static_root),
                tempfile.TemporaryDirectory(dir="/tmp") as repository_directory,
            ):
                root = Path(repository_directory)
                _write_valid_fixture(root)
                collision = (
                    root
                    / static_root
                    / "linux"
                    / "opensource_packages"
                    / "alpha"
                    / "index.html"
                )
                collision.parent.mkdir(parents=True, exist_ok=True)
                collision.write_text("unreviewed static route\n", encoding="utf-8")
                _commit_existing_tree(root, "attempt static package route collision")

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "static files must not claim protected package routes",
                ):
                    validate_catalog_revision(root)

    def test_hugo_rendered_output_is_bounded_while_the_process_runs(self) -> None:
        _commit_valid_fixture(self.root)

        with (
            patch.object(validator_module, "MAX_RENDERED_FILES", 1),
            self.assertRaisesRegex(CatalogValidationError, "file-count limit"),
        ):
            validate_catalog_revision(self.root)

    def test_hugo_topology_validation_does_not_mutate_its_source(self) -> None:
        _write_valid_fixture(self.root)

        def source_state() -> tuple[tuple[str, ...], dict[str, str]]:
            directories = tuple(
                sorted(
                    path.relative_to(self.root).as_posix()
                    for path in self.root.rglob("*")
                    if path.is_dir()
                )
            )
            files = {
                path.relative_to(self.root).as_posix(): _sha256(path.read_bytes())
                for path in self.root.rglob("*")
                if path.is_file()
            }
            return directories, files

        before = source_state()
        with tempfile.TemporaryDirectory(dir="/tmp") as private_directory:
            private_root = Path(private_directory)
            hugo_binary = validator_module._resolve_hugo_binary(
                None,
                private_root=private_root,
            )
            validator_module._validate_hugo_topology(
                self.root,
                expected_package_count=2,
                hugo_binary=hugo_binary,
                private_root=private_root,
            )

        self.assertEqual(source_state(), before)

    def test_rendered_output_budget_rejects_oversized_files(self) -> None:
        output = self.root / "rendered"
        output.mkdir()
        (output / "oversized.html").write_bytes(b"xx")

        with self.assertRaisesRegex(CatalogValidationError, "oversized file"):
            validator_module._validate_output_directory_budget(
                output,
                context="test render",
                maximum_files=10,
                maximum_bytes=10,
                maximum_file_bytes=1,
            )

        with self.assertRaisesRegex(CatalogValidationError, "byte limit"):
            validator_module._validate_output_directory_budget(
                output,
                context="test render",
                maximum_files=10,
                maximum_bytes=1,
                maximum_file_bytes=10,
            )

    def test_missing_catalog_fails_closed(self) -> None:
        (self.root / CONTENT_ROOT).mkdir(parents=True)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "catalog is missing",
        ):
            validate_catalog(self.root)

    def test_only_the_root_content_index_is_exempt_from_catalog_coverage(self) -> None:
        self.fixture()
        root_index = self.root / CONTENT_ROOT / "_index.md"
        root_index.write_text("---\ntitle: Packages\n---\n", encoding="utf-8")

        self.assertEqual(validate_catalog(self.root), 2)

        ordinary_index = self.root / CONTENT_ROOT / "index.md"
        ordinary_index.write_text("---\ntitle: Published page\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(
            CatalogValidationError,
            "exactly one record per package page",
        ):
            validate_catalog(self.root)

    def test_noncanonical_hugo_content_paths_fail_closed(self) -> None:
        candidates = (
            ("package.MD", False),
            ("package.markdown", False),
            ("package.html", False),
            ("package/index.md", True),
        )
        for relative_path, nested in candidates:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    _write_valid_fixture(root)
                    candidate = root / CONTENT_ROOT / relative_path
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    candidate.write_text(
                        "---\ntitle: Uncataloged published page\n---\n",
                        encoding="utf-8",
                    )
                    error = "only top-level" if nested else "canonical top-level"
                    with self.assertRaisesRegex(CatalogValidationError, error):
                        validate_catalog(root)

    def test_duplicate_registry_identity_across_pages_is_rejected(self) -> None:
        fixture = CatalogFixture(self.root)
        fixture.add_package(
            "alpha",
            workflow_present=True,
            pip_identities=("shared-package",),
        )
        fixture.add_package(
            "beta",
            workflow_present=False,
            pip_identities=("shared-package",),
        )
        fixture.write()

        with self.assertRaisesRegex(
            CatalogValidationError,
            "registry identity pip:shared-package conflicts",
        ):
            validate_catalog(self.root)

    def test_non_normalized_registry_identity_is_rejected(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        pip_dimension = payload["records"][0]["registries"]["pip"]
        pip_dimension["status"] = "verified"
        pip_dimension["identities"] = ["Alpha_Package"]
        fixture.write(payload)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "must use pip normalization",
        ):
            validate_catalog(self.root)

    def test_stale_package_page_hash_is_rejected(self) -> None:
        self.fixture()
        page = self.root / CONTENT_ROOT / "alpha.md"
        page.write_text(
            page.read_text(encoding="utf-8") + "changed\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "content_sha256 is stale",
        ):
            validate_catalog(self.root)

    def test_stale_workflow_hash_is_rejected(self) -> None:
        self.fixture()
        workflow = self.root / ".github/workflows/test-alpha.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "# changed\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "workflow.sha256 is stale",
        ):
            validate_catalog(self.root)

    def test_oversized_package_page_is_rejected(self) -> None:
        self.fixture()
        page = self.root / CONTENT_ROOT / "alpha.md"
        page.write_bytes(b"x" * (MAX_PACKAGE_BYTES + 1))

        with self.assertRaisesRegex(
            CatalogValidationError,
            "package page .* size is outside the accepted bounds",
        ):
            validate_catalog(self.root)

    def test_oversized_package_workflow_is_rejected(self) -> None:
        self.fixture()
        workflow = self.root / ".github/workflows/test-alpha.yml"
        workflow.write_bytes(b"x" * (MAX_WORKFLOW_BYTES + 1))

        with self.assertRaisesRegex(
            CatalogValidationError,
            "package workflow .* size is outside the accepted bounds",
        ):
            validate_catalog(self.root)

    def test_symlinked_repository_root_is_rejected(self) -> None:
        self.fixture()
        with tempfile.TemporaryDirectory() as link_directory:
            repository_link = Path(link_directory) / "repository-link"
            repository_link.symlink_to(self.root, target_is_directory=True)

            with self.assertRaisesRegex(
                CatalogValidationError,
                "repository root must not be a symbolic link",
            ):
                validate_catalog(repository_link)

    def test_symlinked_ancestor_directories_are_rejected(self) -> None:
        cases = (
            (".github", ".github"),
            ("content/linux", "linux"),
            (".github/workflows", "workflows"),
        )
        for repository_path, external_name in cases:
            with self.subTest(repository_path=repository_path):
                with (
                    tempfile.TemporaryDirectory() as repository_directory,
                    tempfile.TemporaryDirectory() as external_directory,
                ):
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    original = root / repository_path
                    external = Path(external_directory) / external_name
                    original.rename(external)
                    original.symlink_to(external, target_is_directory=True)

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        r"symbolic(?:-| )link",
                    ):
                        validate_catalog(root)

    def test_symlinked_catalog_page_and_workflow_files_are_rejected(self) -> None:
        cases = (
            CATALOG_REPOSITORY_PATH,
            f"{CONTENT_ROOT}/alpha.md",
            ".github/workflows/test-alpha.yml",
        )
        for repository_path in cases:
            with self.subTest(repository_path=repository_path):
                with (
                    tempfile.TemporaryDirectory() as repository_directory,
                    tempfile.TemporaryDirectory() as external_directory,
                ):
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    original = root / repository_path
                    external = Path(external_directory) / original.name
                    original.rename(external)
                    original.symlink_to(external)

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        r"symbolic(?:-| )link",
                    ):
                        validate_catalog(root)

    def test_pathname_swap_during_descriptor_read_is_rejected(self) -> None:
        self.fixture()
        page = self.root / CONTENT_ROOT / "alpha.md"
        page_state = os.stat(page, follow_symlinks=False)
        original_read = os.read
        swapped = False

        with tempfile.TemporaryDirectory() as external_directory:
            replacement = Path(external_directory) / "alpha-replacement.md"
            replacement.write_bytes(page.read_bytes())

            def replace_path_then_read(file_fd: int, count: int) -> bytes:
                nonlocal swapped
                opened_state = os.fstat(file_fd)
                if (
                    not swapped
                    and opened_state.st_dev == page_state.st_dev
                    and opened_state.st_ino == page_state.st_ino
                ):
                    os.replace(replacement, page)
                    swapped = True
                return original_read(file_fd, count)

            with (
                patch(
                    "build_steps.validate_package_identity_catalog.os.read",
                    side_effect=replace_path_then_read,
                ),
                self.assertRaisesRegex(
                    CatalogValidationError,
                    "pathname was replaced while being read",
                ),
            ):
                validate_catalog(self.root)

        self.assertTrue(swapped)

    def test_post_read_file_replacements_fail_final_snapshot(self) -> None:
        protected_paths = (
            CATALOG_REPOSITORY_PATH,
            f"{CONTENT_ROOT}/alpha.md",
            ".github/workflows/test-alpha.yml",
        )
        original_validate_registries = validator_module._validate_registries
        for repository_path in protected_paths:
            with self.subTest(repository_path=repository_path):
                with (
                    tempfile.TemporaryDirectory() as repository_directory,
                    tempfile.TemporaryDirectory() as external_directory,
                ):
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    target = root / repository_path
                    replacement = Path(external_directory) / target.name
                    replacement.write_bytes(target.read_bytes())
                    replaced = False

                    def replace_after_semantic_check(
                        *args: object,
                        **kwargs: object,
                    ) -> None:
                        nonlocal replaced
                        original_validate_registries(*args, **kwargs)
                        if not replaced:
                            os.replace(replacement, target)
                            replaced = True

                    with (
                        patch.object(
                            validator_module,
                            "_validate_registries",
                            new=replace_after_semantic_check,
                        ),
                        self.assertRaisesRegex(
                            CatalogValidationError,
                            "protected file changed before validation completed",
                        ),
                    ):
                        validate_catalog(root)

                    self.assertTrue(replaced)

    def test_fifo_and_socket_catalog_candidates_fail_promptly(self) -> None:
        for candidate_kind in ("fifo", "socket"):
            with self.subTest(candidate_kind=candidate_kind):
                with tempfile.TemporaryDirectory(dir="/tmp") as repository_directory:
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    catalog = root / CATALOG_REPOSITORY_PATH
                    catalog.unlink()
                    socket_handle: socket.socket | None = None
                    if candidate_kind == "fifo":
                        os.mkfifo(catalog)
                    else:
                        socket_handle = socket.socket(
                            socket.AF_UNIX,
                            socket.SOCK_STREAM,
                        )
                        socket_handle.bind(str(catalog))

                    started = time.monotonic()
                    try:
                        with self.assertRaisesRegex(
                            CatalogValidationError,
                            r"catalog (?:is not a regular file|has a "
                            r"symbolic-link or unsafe pathname)",
                        ):
                            validate_catalog(root)
                    finally:
                        if socket_handle is not None:
                            socket_handle.close()
                    self.assertLess(time.monotonic() - started, 2.0)

    def test_device_candidate_fails_promptly(self) -> None:
        started = time.monotonic()
        with validator_module._open_repository_root(Path("/")) as root_fd:
            with self.assertRaisesRegex(
                CatalogValidationError,
                "device candidate is not a regular file",
            ):
                validator_module._read_repository_file(
                    root_fd,
                    "dev/null",
                    display_name="device candidate",
                    maximum_bytes=MAX_PACKAGE_BYTES,
                )
        self.assertLess(time.monotonic() - started, 2.0)

    def test_injected_fstat_failures_close_all_opened_descriptors(self) -> None:
        original_open = os.open
        original_fstat = os.fstat
        for failure_call in (1, 3, 5):
            with self.subTest(failure_call=failure_call):
                with tempfile.TemporaryDirectory() as repository_directory:
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    opened_fds: list[int] = []
                    fstat_calls = 0

                    def tracking_open(
                        *args: object,
                        **kwargs: object,
                    ) -> int:
                        file_fd = original_open(*args, **kwargs)
                        opened_fds.append(file_fd)
                        return file_fd

                    def injected_fstat(file_fd: int) -> os.stat_result:
                        nonlocal fstat_calls
                        fstat_calls += 1
                        if fstat_calls == failure_call:
                            raise OSError(
                                errno.EIO,
                                "injected fstat failure",
                            )
                        return original_fstat(file_fd)

                    with (
                        patch.object(
                            validator_module,
                            "_require_descriptor_platform",
                            return_value=None,
                        ),
                        patch.object(
                            validator_module.os,
                            "open",
                            side_effect=tracking_open,
                        ),
                        patch.object(
                            validator_module.os,
                            "fstat",
                            side_effect=injected_fstat,
                        ),
                        self.assertRaises(CatalogValidationError),
                    ):
                        validate_catalog(root)

                    self.assertTrue(opened_fds)
                    for file_fd in set(opened_fds):
                        with self.assertRaises(OSError) as raised:
                            original_fstat(file_fd)
                        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_hard_linked_protected_files_are_rejected(self) -> None:
        protected_paths = (
            CATALOG_REPOSITORY_PATH,
            f"{CONTENT_ROOT}/alpha.md",
            ".github/workflows/test-alpha.yml",
        )
        for repository_path in protected_paths:
            with self.subTest(repository_path=repository_path):
                with tempfile.TemporaryDirectory() as repository_directory:
                    root = Path(repository_directory)
                    _write_valid_fixture(root)
                    target = root / repository_path
                    os.link(target, root / f"hardlink-{target.name}")

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        "protected file must have exactly one hard link",
                    ):
                        validate_catalog(root)

    def test_latest_source_revision_is_rejected(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        evidence = payload["records"][0]["registries"]["pip"]["evidence"][0]
        evidence["source_revision"] = "latest"
        fixture.write(payload)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "immutable lowercase SHA-256 snapshot revision",
        ):
            validate_catalog(self.root)

    def test_moving_git_source_revisions_are_rejected(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        evidence = payload["records"][0]["registries"]["pip"]["evidence"][0]
        evidence["source_kind"] = "github_api"
        evidence["source_locator"] = "https://api.github.com/repos/example/alpha"
        for revision in (
            "main",
            "master",
            "HEAD",
            "branch",
            "tag",
            "refs/heads/main",
            "v1.2.3",
        ):
            with self.subTest(revision=revision):
                evidence["source_revision"] = revision
                fixture.write(payload)

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "immutable .* Git object ID",
                ):
                    validate_catalog(self.root)

    def test_version_label_source_revision_is_rejected(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        evidence = payload["records"][0]["registries"]["pip"]["evidence"][0]
        evidence["source_kind"] = "pypi_api"
        evidence["source_locator"] = "https://pypi.org/pypi/alpha/json"
        evidence["source_revision"] = "1.2.3"
        fixture.write(payload)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "immutable lowercase SHA-256 snapshot revision",
        ):
            validate_catalog(self.root)

    def test_all_zero_source_revisions_are_rejected(self) -> None:
        cases = (
            (
                "generated_workflow",
                ".github/workflows/test-alpha.yml",
                "0" * 40,
            ),
            (
                "github_api",
                "https://api.github.com/repos/example/alpha",
                "0" * 40,
            ),
            (
                "frontmatter_url",
                "https://github.com/example/alpha",
                "0" * 64,
            ),
        )
        for source_kind, source_locator, source_revision in cases:
            with self.subTest(source_kind=source_kind):
                with tempfile.TemporaryDirectory() as repository_directory:
                    root = Path(repository_directory)
                    fixture = _write_valid_fixture(root)
                    payload = fixture.payload()
                    evidence = payload["records"][0]["registries"]["pip"]["evidence"][0]
                    evidence["source_kind"] = source_kind
                    evidence["source_locator"] = source_locator
                    evidence["source_revision"] = source_revision
                    fixture.write(payload)

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        "source_revision must not be an all-zero object ID",
                    ):
                        validate_catalog(root)

    def test_new_package_page_without_catalog_record_is_rejected(self) -> None:
        self.fixture()
        new_page = self.root / CONTENT_ROOT / "gamma.md"
        new_page.write_text("---\nname: gamma\n---\n", encoding="utf-8")

        with self.assertRaisesRegex(
            CatalogValidationError,
            "exactly one record per package page",
        ):
            validate_catalog(self.root)

    def test_existing_workflow_declared_absent_is_rejected(self) -> None:
        fixture = self.fixture()
        payload = fixture.payload()
        workflow = payload["records"][0]["workflow"]
        workflow["presence"] = "absent"
        workflow["sha256"] = None
        fixture.write(payload)

        with self.assertRaisesRegex(
            CatalogValidationError,
            "declares an existing workflow as absent",
        ):
            validate_catalog(self.root)

    def test_orphan_package_workflow_is_rejected(self) -> None:
        self.fixture()
        orphan = self.root / ".github/workflows/test-orphan.yml"
        orphan.write_text(
            "name: Orphan package workflow\non: workflow_dispatch\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "orphan package workflows have no exact package page",
        ):
            validate_catalog(self.root)

    def test_known_control_workflows_are_not_package_orphans(self) -> None:
        self.fixture()
        workflows = self.root / ".github/workflows"
        for name in (
            "test-all-packages-batch1.yml",
            "test-all-packages-orchestrator.yml",
            "test-all-packages-summary.yml",
        ):
            (workflows / name).write_text(
                f"name: {name}\non: workflow_dispatch\n",
                encoding="utf-8",
            )

        self.assertEqual(validate_catalog(self.root), 2)

    def test_dashboard_control_workflow_slugs_are_reserved(self) -> None:
        for slug in (
            "all-packages-batch1",
            "all-packages-orchestrator",
            "all-packages-summary",
            "All-Packages-Summary",
        ):
            with self.subTest(slug=slug):
                with tempfile.TemporaryDirectory() as repository_directory:
                    root = Path(repository_directory)
                    fixture = CatalogFixture(root)
                    fixture.add_package(slug, workflow_present=False)
                    fixture.write()

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        "reserved for a dashboard control workflow",
                    ):
                        validate_catalog(root)

    def test_generated_workflow_evidence_must_match_record_binding(self) -> None:
        cases = (
            (".github/workflows/test-other.yml", None),
            (None, "f" * 64),
        )
        for source_locator, evidence_sha256 in cases:
            with self.subTest(
                source_locator=source_locator,
                evidence_sha256=evidence_sha256,
            ):
                with tempfile.TemporaryDirectory() as repository_directory:
                    root = Path(repository_directory)
                    fixture = _write_valid_fixture(root)
                    payload = fixture.payload()
                    record = payload["records"][0]
                    evidence = record["registries"]["pip"]["evidence"][0]
                    evidence.update(
                        {
                            "source_kind": "generated_workflow",
                            "source_locator": (
                                source_locator or record["workflow"]["path"]
                            ),
                            "source_revision": "a" * 40,
                            "evidence_sha256": (
                                evidence_sha256 or record["workflow"]["sha256"]
                            ),
                        }
                    )
                    fixture.write(payload)

                    with self.assertRaisesRegex(
                        CatalogValidationError,
                        "must match the record workflow path and SHA-256",
                    ):
                        validate_catalog(root)

    def test_evidence_timestamps_use_canonical_rfc3339_text(self) -> None:
        invalid_values = (
            "2025-01-01 00:00:00+00:00",
            "2025-01-01T00:00:00+0000",
            "2025-01-01T00:00:00.1234567+00:00",
        )
        for verified_at in invalid_values:
            with self.subTest(verified_at=verified_at):
                fixture = self.fixture()
                payload = fixture.payload()
                payload["records"][0]["registries"]["pip"]["evidence"][0][
                    "verified_at"
                ] = verified_at
                fixture.write(payload)

                with self.assertRaisesRegex(
                    CatalogValidationError,
                    "canonical RFC3339 timestamp text",
                ):
                    validate_catalog(self.root)

    def test_package_count_and_traversal_are_bounded(self) -> None:
        self.fixture()
        with (
            patch.object(validator_module, "MAX_PACKAGE_PAGES", 1),
            self.assertRaisesRegex(CatalogValidationError, "between 0 and 1"),
        ):
            validate_catalog(self.root)

        with (
            patch.object(validator_module, "MAX_DIRECTORY_ENTRIES", 1),
            self.assertRaisesRegex(CatalogValidationError, "traversal exceeds 1"),
        ):
            validate_catalog(self.root)

        (self.root / CONTENT_ROOT / "nested").mkdir()
        with self.assertRaisesRegex(CatalogValidationError, "only top-level"):
            validate_catalog(self.root)

    def test_duplicate_json_object_key_is_rejected(self) -> None:
        self.fixture()
        catalog = self.root / CATALOG_REPOSITORY_PATH
        original = catalog.read_text(encoding="utf-8")
        catalog.write_text(
            original.replace(
                "{\n",
                '{\n  "schema_version": "1.1",\n',
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "duplicate JSON object key: schema_version",
        ):
            validate_catalog(self.root)

    def test_non_canonical_json_is_rejected(self) -> None:
        fixture = self.fixture()
        catalog = self.root / CATALOG_REPOSITORY_PATH
        catalog.write_text(
            json.dumps(fixture.payload(), sort_keys=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CatalogValidationError,
            "catalog JSON must use sorted keys",
        ):
            validate_catalog(self.root)


def _dimension(
    registry_kind: str,
    content_path: str,
    content_sha256: str,
    identities: tuple[str, ...],
) -> dict[str, Any]:
    slug = Path(content_path).stem
    locator = f"https://github.com/example/{slug}"
    return {
        "status": "verified" if identities else "unknown",
        "exhaustive": False,
        "identities": list(identities),
        "evidence": [
            {
                "source_kind": "frontmatter_url",
                "source_locator": locator,
                "source_revision": content_sha256,
                "evidence_sha256": _sha256(locator.encode("utf-8")),
                "verified_by": "catalog-validator-test",
                "verified_at": "2025-01-01T00:00:00+00:00",
                "rationale": (
                    f"Synthetic {registry_kind} evidence for an isolated "
                    "validator test."
                ),
            }
        ],
    }


def _write_canonical(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _replace_record_content_digest(
    payload: dict[str, Any],
    slug: str,
    content_sha256: str,
) -> None:
    record = next(record for record in payload["records"] if record["slug"] == slug)
    record["content_sha256"] = content_sha256
    for dimension in record["registries"].values():
        for evidence in dimension["evidence"]:
            evidence["source_revision"] = content_sha256
    _refresh_corpus(payload)


def _refresh_corpus(payload: dict[str, Any]) -> None:
    path_digests: list[tuple[str, str | None]] = []
    for record in payload["records"]:
        path_digests.append((record["content_path"], record["content_sha256"]))
        workflow = record["workflow"]
        path_digests.append((workflow["path"], workflow["sha256"]))
    payload["corpus"]["entry_count"] = len(payload["records"])
    payload["corpus"]["corpus_sha256"] = calculate_corpus_sha256(path_digests)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    unittest.main()
