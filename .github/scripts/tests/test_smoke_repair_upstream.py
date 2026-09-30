"""Adversarial fixtures mirrored with the independent public verifier."""

import copy
import hashlib
import io
import json
import signal
import socket
import threading
import unittest
from unittest.mock import MagicMock, patch

import yaml

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import smoke_repair_upstream as r

REPO = "example/widget"
SHA = hashlib.sha256(b"verified-arm-asset").hexdigest()
OLD_URL = (
    "https://github.com/example/widget/releases/download/v1.2.3/widget_1.2.3_linux_arm64.tar.gz"
)
NEW_NAME = "widget-1.2.4-linux-aarch64.tar.gz"
NEW_URL = "https://github.com/example/widget/releases/download/v1.2.4/" + NEW_NAME


def context(script=None):
    script = script or (
        "set -euo pipefail\n"
        'VERSION="1.2.3"\n'
        'URL="https://github.com/example/widget/releases/download/v${VERSION}/widget_${VERSION}_linux_arm64.tar.gz"\n'
        'curl -fsSL "$URL" -o /tmp/widget.tar.gz\n'
        "tar -xzf /tmp/widget.tar.gz -C /tmp\n"
        "./widget --version\n"
    )
    source = (
        "name: Widget\non: workflow_dispatch\njobs:\n  test:\n"
        "    runs-on: ubuntu-24.04-arm\n    steps:\n"
        "      - name: Install widget\n        id: install\n        run: |\n"
        + "".join("          " + line for line in script.splitlines(keepends=True))
        + "      - name: Test 1 - Actual operation\n        id: test1\n        run: |\n"
        "          widget check --strict\n"
        "      - name: Fail if any test failed\n        id: gate\n        run: exit 1\n"
    )
    return {
        "repository": "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
        "base_sha": "a" * 40,
        "package_slug": "widget",
        "workflow_path": ".github/workflows/test-widget.yml",
        "source_text": source,
    }


def release(ident=20, tag="v1.2.4"):
    url = "https://api.github.com/repos/" + REPO + "/releases/" + str(ident)
    return {
        "id": ident,
        "tag_name": tag,
        "url": url,
        "assets_url": url + "/assets",
        "html_url": "https://github.com/" + REPO + "/releases/tag/" + tag,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-01T01:00:00Z",
    }


def asset(ident=30, name=NEW_NAME, tag="v1.2.4"):
    return {
        "id": ident,
        "name": name,
        "state": "uploaded",
        "size": 18,
        "url": f"https://api.github.com/repos/{REPO}/releases/assets/{ident}",
        "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
        "digest": "sha256:" + SHA,
    }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.byte_calls = []
        self.asset = asset()
        self.original = release(10, "v1.2.3")
        self.new = release()
        self.data = {
            f"/repos/{REPO}": {
                "id": 77,
                "full_name": REPO,
                "private": False,
                "fork": False,
                "html_url": "https://github.com/" + REPO,
            },
            f"/repos/{REPO}/releases/tags/v1.2.3": self.original,
            f"/repos/{REPO}/releases?per_page=10&page=1": [self.new],
            f"/repos/{REPO}/releases/10": self.original,
            f"/repos/{REPO}/releases/20": self.new,
            f"/repos/{REPO}/releases/10/assets?per_page=100&page=1": [],
            f"/repos/{REPO}/releases/20/assets?per_page=100&page=1": [self.asset],
            f"/repos/{REPO}/releases/assets/30": self.asset,
        }

    def get_json(self, path):
        self.calls.append(path)
        if path not in self.data:
            raise AssertionError("unexpected API path: " + path)
        return copy.deepcopy(self.data[path])

    def asset_sha256(self, path, size):
        self.byte_calls.append((path, size))
        return SHA


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.context = context()
        self.client = FakeClient()

    def report(self):
        return r.research_downloads(self.context, client=self.client)

    def selected(self):
        row = self.report()["candidates"][0]
        return {
            "kind": "github_release_download",
            **{key: row[key] for key in ("step", "line", "research_id")},
        }

    def test_missing_asset_yields_a_source_bound_data_only_selection(self):
        report = self.report()
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["unsupported"], [])
        row = report["candidates"][0]
        self.assertEqual(
            set(row),
            {
                "step",
                "line",
                "repository_id",
                "release_id",
                "asset_id",
                "version",
                "sha256",
                "research_id",
            },
        )
        self.assertEqual(row["version"], "v1.2.4")
        self.assertEqual(row["repository_id"], 77)
        self.assertEqual(row["sha256"], SHA)
        self.assertRegex(row["research_id"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.client.byte_calls, [(f"/repos/{REPO}/releases/assets/30", 18)])
        self.assertNotIn("https://", json.dumps(report))
        self.assertNotIn("edit", row)

    def test_public_internal_golden_research_id(self):
        self.assertEqual(
            self.report()["candidates"][0]["research_id"],
            "6fade7538a636a2309b096c5ab12bf549d565c77f00a6031117b4739233ded1a",
        )

    def test_executable_prefix_overrides_are_unsupported(self):
        for prefix in (
            "source malicious.sh",
            ". malicious.sh",
            "eval 'echo bad'",
            "curl() { echo fake; }",
            "exec other-command",
        ):
            with self.subTest(prefix=prefix), self.assertRaises(r.ResearchError):
                r.research_downloads(
                    context(prefix + "\n" + f'curl -fsSL "{OLD_URL}" -o widget.tar.gz\n'),
                    client=self.client,
                )

    def test_multiple_downloads_in_one_block_need_coordinated_repair(self):
        script = f'curl -fsSL "{OLD_URL}" -o widget.tar.gz\n'
        with self.assertRaisesRegex(r.ResearchError, "coordinated repair"):
            r.research_downloads(context(script + script), client=self.client)

    def test_missing_digest_never_falls_back_to_untrusted_checksum_url(self):
        self.client.asset["digest"] = None
        self.client.asset["checksum_url"] = "https://private.invalid/secret"
        with self.assertRaises(r.ResearchError):
            self.report()
        self.assertTrue(all(path.startswith("/repos/example/widget") for path in self.client.calls))
        self.assertEqual(self.client.byte_calls, [])

    def test_resolve_researches_again_and_keeps_all_other_steps_verbatim(self):
        operation = self.selected()
        self.client.calls.clear()
        selected = r.resolve_download_operation(self.context, operation, client=self.client)
        self.assertIn(f"/repos/{REPO}", self.client.calls)
        edit = selected["edit"]
        original = self.context["source_text"]
        self.assertEqual(original.count(edit["old"]), 1)
        changed = original.replace(edit["old"], edit["new"], 1)
        before = yaml.safe_load(original)["jobs"]["test"]["steps"]
        after = yaml.safe_load(changed)["jobs"]["test"]["steps"]
        self.assertEqual(before[1:], after[1:])
        self.assertEqual(
            {k: v for k, v in before[0].items() if k != "run"},
            {k: v for k, v in after[0].items() if k != "run"},
        )
        self.assertIn('VERSION="1.2.4"', after[0]["run"])
        self.assertIn(NEW_URL, after[0]["run"])
        self.assertIn(SHA + "  /tmp/widget.tar.gz", after[0]["run"])
        self.assertIn("sha256sum --check - || exit 1", after[0]["run"])
        self.assertIn("tar -xzf /tmp/widget.tar.gz -C /tmp", after[0]["run"])

    def test_literal_url_upgrade_does_not_modify_unrelated_pin(self):
        self.context = context(
            f'OTHER_VERSION="1.2.3"\ncurl -fsSL "{OLD_URL}" -o /tmp/widget.tar.gz\n'
        )
        edit = r.resolve_download_operation(self.context, self.selected(), client=self.client)[
            "edit"
        ]
        self.assertIn('OTHER_VERSION="1.2.3"', edit["new"])

    def test_same_version_renamed_arm_asset(self):
        renamed = asset(name="widget-1.2.3-linux-aarch64.tar.gz", tag="v1.2.3")
        self.client.data[f"/repos/{REPO}/releases/10/assets?per_page=100&page=1"] = [renamed]
        self.client.data[f"/repos/{REPO}/releases/assets/30"] = renamed
        self.assertEqual(self.report()["candidates"][0]["version"], "v1.2.3")

    def test_literal_existing_checksum_changes_only_its_digest(self):
        self.context = context(
            f'curl -fsSL "{OLD_URL}" -o /tmp/widget.tar.gz\n'
            f'echo "{"0" * 64}  /tmp/widget.tar.gz" | sha256sum -c -\n'
            "tar -xzf /tmp/widget.tar.gz\n"
        )
        edit = r.resolve_download_operation(self.context, self.selected(), client=self.client)[
            "edit"
        ]
        self.assertIn(f'echo "{SHA}  /tmp/widget.tar.gz" | sha256sum -c -', edit["new"])
        self.assertNotIn("sha256sum --check", edit["new"])

    def test_wget_explicit_output_is_supported(self):
        self.context = context(f'wget -q -O /tmp/widget.tar.gz "{OLD_URL}"\n')
        self.assertEqual(len(self.report()["candidates"]), 1)

    def test_original_release_missing_uses_verified_same_minor_patch(self):
        self.client.data[f"/repos/{REPO}/releases/tags/v1.2.3"] = None
        self.assertEqual(len(self.report()["candidates"]), 1)

    def test_already_present_asset_does_not_trigger_upgrade(self):
        self.client.data[f"/repos/{REPO}/releases/10/assets?per_page=100&page=1"] = [
            asset(12, "widget_1.2.3_linux_arm64.tar.gz", "v1.2.3")
        ]
        self.assertEqual(self.report()["candidates"], [])
        self.assertEqual(self.report()["unsupported"], ["upstream_asset_present"])
        self.assertEqual(self.client.byte_calls, [])

    def test_prerelease_major_minor_and_downgrade_are_not_proposals(self):
        for tag in ("v2.0.0", "v1.3.0", "v1.2.2", "v1.2.5-rc1"):
            with self.subTest(tag=tag):
                self.client.data[f"/repos/{REPO}/releases?per_page=10&page=1"] = [release(tag=tag)]
                self.assertEqual(self.report()["candidates"], [])

    def test_missing_digest_and_changed_bytes_are_rejected(self):
        for digest in (None, "sha1:" + SHA, "sha256:" + "f" * 64):
            with self.subTest(digest=digest):
                self.client.asset["digest"] = digest
                with self.assertRaises(r.ResearchError):
                    self.report()

    def test_wrong_repository_identity_is_rejected(self):
        for field, value in (
            ("full_name", "attacker/widget"),
            ("id", True),
            ("private", True),
            ("fork", True),
            ("html_url", "https://github.com/attacker/widget"),
        ):
            with self.subTest(field=field):
                self.client = FakeClient()
                self.client.data[f"/repos/{REPO}"][field] = value
                with self.assertRaises(r.ResearchError):
                    self.report()

    def test_asset_source_or_identity_cannot_be_substituted(self):
        for field, value in (
            ("url", "https://evil.test/blob"),
            ("browser_download_url", "https://evil.test/widget.tar.gz"),
            ("id", True),
            ("size", 0),
            ("size", r.MAX_ASSET + 1),
            ("state", "new"),
        ):
            with self.subTest(field=field):
                self.client = FakeClient()
                self.client.asset[field] = value
                with self.assertRaises(r.ResearchError):
                    self.report()

    def test_wrong_platform_package_or_archive_type_is_unsupported(self):
        for name in (
            "widget-1.2.4-linux-amd64.tar.gz",
            "widget-1.2.4-darwin-arm64.tar.gz",
            "other-1.2.4-linux-arm64.tar.gz",
            "widget-1.2.4-linux-arm64.zip",
            "widget-1.2.4-linux-arm64-musl.tar.gz",
        ):
            with self.subTest(name=name):
                self.client = FakeClient()
                self.client.asset["name"] = name
                self.assertEqual(self.report()["candidates"], [])

    def test_ambiguous_assets_duplicate_releases_and_incomplete_pages_rejected(self):
        self.client.data[f"/repos/{REPO}/releases/20/assets?per_page=100&page=1"].append(
            asset(31, "widget_1.2.4_linux_arm64.tar.gz")
        )
        with self.assertRaises(r.ResearchError):
            self.report()
        self.client = FakeClient()
        self.client.data[f"/repos/{REPO}/releases?per_page=10&page=1"] *= 2
        with self.assertRaises(r.ResearchError):
            self.report()

    def test_asset_changed_between_listing_and_detail_is_rejected(self):
        self.client.data[f"/repos/{REPO}/releases/assets/30"] = {**self.client.asset, "size": 19}
        with self.assertRaises(r.ResearchError):
            self.report()

    def test_release_changed_between_listing_and_detail_is_rejected(self):
        self.client.data[f"/repos/{REPO}/releases/20"] = {**self.client.new, "draft": True}
        with self.assertRaises(r.ResearchError):
            self.report()

    def test_invalid_or_future_release_metadata_rejected(self):
        for field, value in (
            ("assets_url", "https://evil.test/"),
            ("url", "https://evil.test/"),
            ("html_url", "https://github.com/attacker/widget/releases/tag/v1.2.4"),
            ("published_at", "3026-01-01T00:00:00Z"),
            ("published_at", "2026-01-01"),
            ("id", False),
        ):
            with self.subTest(field=field):
                self.client = FakeClient()
                self.client.new[field] = value
                with self.assertRaises(r.ResearchError):
                    self.report()

    def test_source_and_base_binding_prevent_replay(self):
        operation = self.selected()
        for field, value in (
            ("base_sha", "b" * 40),
            ("source_text", self.context["source_text"] + "# changed\n"),
        ):
            with self.subTest(field=field):
                changed = {**self.context, field: value}
                with self.assertRaises(r.ResearchError):
                    r.resolve_download_operation(changed, operation, client=self.client)

    def test_forged_indexes_research_id_and_extra_fields_rejected(self):
        operation = self.selected()
        for field, value in (
            ("step", True),
            ("step", -1),
            ("line", 4096),
            ("research_id", "0" * 64),
            ("research_id", "x" * 64),
            ("url", "https://evil.test/"),
            ("diagnosis", "private text"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(r.ResearchError):
                    r.resolve_download_operation(
                        self.context, {**operation, field: value}, client=self.client
                    )

    def test_invalid_context_identity_rejected_before_network(self):
        for field, value in (
            ("repository", "attacker/widget"),
            ("base_sha", "not-sha"),
            ("package_slug", "../escape"),
            ("workflow_path", "other.yml"),
        ):
            with self.subTest(field=field):
                self.client.calls.clear()
                with self.assertRaises(r.ResearchError):
                    r.research_downloads({**self.context, field: value}, client=self.client)
                self.assertEqual(self.client.calls, [])

    def test_no_supported_download_is_not_recovered_execution_evidence(self):
        self.context = context("echo missing GitHub Actions artifacts; exit 1\n")
        report = self.report()
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["unsupported"], ["no_supported_download_site"])
        self.assertEqual(self.client.calls, [])

    def test_actions_artifact_is_never_treated_as_a_package_release(self):
        self.context = context(
            'curl -fsSL "https://api.github.com/repos/example/widget/actions/artifacts/9/zip" '
            "-o artifact.zip\n"
        )
        with self.assertRaises(r.ResearchError):
            self.report()
        self.assertEqual(self.client.calls, [])

    def test_dynamic_shell_credential_options_and_untrusted_origins_rejected(self):
        for script in (
            f'curl -fsSL "{OLD_URL}" -H "Authorization: Bearer secret" -o widget.tar.gz\n',
            f'curl -k -fsSL "{OLD_URL}" -o widget.tar.gz\n',
            f'curl -sSL "{OLD_URL}" -o widget.tar.gz\n',
            f'curl -fsSL "{OLD_URL}" | bash\n',
            f'if true; then\n  curl -fsSL "{OLD_URL}" -o widget.tar.gz\nfi\n',
            f'cat <<EOF\ncurl -fsSL "{OLD_URL}" -o widget.tar.gz\nEOF\n',
            'URL="$(printf x)"\ncurl -fsSL "$URL" -o widget.tar.gz\n',
            'curl -fsSL "https://127.0.0.1/latest" -o widget.tar.gz\n',
            'curl -fsSL "https://user:secret@github.com/example/widget/releases/download/'
            'v1.2.3/widget-linux-arm64" -o widget\n',
            f'curl -fsSL "{OLD_URL}" -o ../escape.tar.gz\n',
        ):
            with self.subTest(script=script):
                self.context = context(script)
                self.client.calls.clear()
                with self.assertRaises(r.ResearchError):
                    self.report()
                self.assertEqual(self.client.calls, [])

    def test_complex_checksums_and_checksum_bypass_are_not_rewritten(self):
        for suffix in (
            'echo "sha" | sha256sum -c -\n',
            f'echo "{"0" * 64}  /tmp/widget.tar.gz" | sha256sum -c - || true\n',
            "sha512sum --check checksum.txt\n",
        ):
            self.context = context(f'curl -fsSL "{OLD_URL}" -o /tmp/widget.tar.gz\n' + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(r.ResearchError):
                self.report()

    def test_test_step_never_becomes_download_repair_site(self):
        self.context["source_text"] = self.context["source_text"].replace(
            "id: install", "id: test1"
        )
        self.assertEqual(self.report()["candidates"], [])

    def test_aliases_and_duplicate_run_fields_rejected(self):
        for source in (
            self.context["source_text"].replace("run: |", "run: &script |", 1),
            self.context["source_text"].replace(
                "        run: |", "        run: exit 0\n        run: |", 1
            ),
        ):
            with self.subTest(source=source):
                with self.assertRaises(r.ResearchError):
                    r.research_downloads(
                        {**self.context, "source_text": source}, client=self.client
                    )

    def test_global_version_pin_requires_manual_upgrade(self):
        self.context = context(
            'curl -fsSL "https://github.com/example/widget/releases/download/v${VERSION}/'
            'widget_${VERSION}_linux_arm64.tar.gz" -o /tmp/widget.tar.gz\n'
        )
        self.context["source_text"] = self.context["source_text"].replace(
            "    steps:", '    env:\n      VERSION: "1.2.3"\n    steps:'
        )
        with self.assertRaisesRegex(r.ResearchError, "global or dynamic version"):
            self.report()

    def test_implicit_output_cannot_silently_rename_install_file(self):
        self.context = context(f'curl -fSL -O "{OLD_URL}"\n')
        with self.assertRaisesRegex(r.ResearchError, "implicit output"):
            self.report()

    def test_environment_export_and_reassignments_rejected(self):
        for script in (
            'echo "VERSION=1.2.3" >> "$GITHUB_ENV"\n'
            f'curl -fsSL "{OLD_URL}" -o /tmp/widget.tar.gz\n',
            f'VERSION=1.2.3\nVERSION=1.2.4\ncurl -fsSL "{OLD_URL}" -o /tmp/widget.tar.gz\n',
        ):
            self.context = context(script)
            with self.assertRaises(r.ResearchError):
                self.report()


class Response:
    def __init__(self, body=b'{"ok":true}', status=200, headers=None):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = list((headers or {}).items())

    def read(self, size):
        return self.body.read(size)

    def getheaders(self):
        return self.headers


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.context = context()
        self.client = FakeClient()
        default = patch.object(r, "_DEFAULT_SESSION", r.ResearchSession())
        default.start()
        self.addCleanup(default.stop)

    def selected(self):
        row = r.research_downloads(self.context)["candidates"][0]
        return {
            "kind": "github_release_download",
            **{key: row[key] for key in ("step", "line", "research_id")},
        }

    def test_compiler_and_readmission_share_one_verified_default_result(self):
        with patch.object(r, "GitHubReleases", return_value=self.client):
            operation = self.selected()
            for _ in range(30):
                selected = r.resolve_download_operation(self.context, operation)
                if hasattr(r, "verify_download_edit"):
                    self.assertTrue(
                        r.verify_download_edit(
                            self.context, selected["edit"], step=operation["step"]
                        )
                    )
                r.research_downloads(self.context)
        self.assertEqual(len(self.client.calls), 7)
        self.assertEqual(len(self.client.byte_calls), 1)

    def test_returned_mutations_cannot_change_cached_approval(self):
        with r.research_session(client=self.client):
            operation = self.selected()
            report = r.research_downloads(self.context)
            report["candidates"][0]["sha256"] = "0" * 64
            report["candidates"].clear()
            first = r.resolve_download_operation(self.context, operation)
            first["edit"]["new"] = "exit 0"
            first["research_id"] = "0" * 64
            second = r.resolve_download_operation(self.context, operation)
            self.assertIn(NEW_URL, second["edit"]["new"])
            self.assertEqual(second["sha256"], SHA)
            self.assertNotIn("_byte_identity", second)
            self.assertNotIn("_byte_identity", json.dumps(r.research_downloads(self.context)))
        self.assertEqual(len(self.client.byte_calls), 1)

    def test_explicit_refresh_refetches_metadata_but_not_verified_bytes(self):
        with r.research_session(client=self.client) as session:
            operation = self.selected()
            session.refresh()
            r.resolve_download_operation(self.context, operation)
            r.resolve_download_operation(self.context, operation, fresh=True)
        self.assertEqual(len(self.client.calls), 21)
        self.assertEqual(len(self.client.byte_calls), 1)

    def test_metadata_age_and_absolute_byte_lifetime_are_bounded(self):
        with patch.object(r.time, "monotonic", return_value=1000.0) as clock:
            with r.research_session(client=self.client):
                operation = self.selected()
                clock.return_value = 1000.0 + r.METADATA_SECONDS
                r.resolve_download_operation(self.context, operation)
                self.assertEqual(len(self.client.calls), 14)
                self.assertEqual(len(self.client.byte_calls), 1)
                clock.return_value = 1000.0 + r.CACHE_SECONDS
                r.resolve_download_operation(self.context, operation)
                self.assertEqual(len(self.client.byte_calls), 2)

    def test_source_base_run_and_repository_identities_are_separate(self):
        with r.research_session(client=self.client):
            operation = self.selected()
            for key, value in (
                ("source_text", self.context["source_text"] + "# new source\n"),
                ("base_sha", "b" * 40),
                ("orchestrator_run_id", 123),
                ("orchestrator_run_attempt", 2),
                ("request_nonce", "a" * 64),
            ):
                changed = {**self.context, key: value}
                report = r.research_downloads(changed)
                self.assertTrue(report["candidates"])
            self.assertEqual(len(self.client.byte_calls), 6)
            self.assertEqual(self.selected(), operation)
            before = len(self.client.calls)
            with self.assertRaises(r.ResearchError):
                r.research_downloads({**self.context, "repository": "evil/other"})
            self.assertEqual(len(self.client.calls), before)

    def test_job_process_and_session_boundaries_do_not_share_approval(self):
        with r.research_session(client=self.client):
            operation = self.selected()
            with patch.dict("os.environ", {"GITHUB_JOB": "different"}):
                r.resolve_download_operation(self.context, operation)
            with patch.object(r.os, "getpid", return_value=-1):
                r.resolve_download_operation(self.context, operation)
        with r.research_session(client=self.client):
            r.resolve_download_operation(self.context, operation)
        self.assertEqual(len(self.client.byte_calls), 4)

    def test_verified_identity_change_cannot_reuse_bytes_or_selection(self):
        with r.research_session(client=self.client) as session:
            operation = self.selected()
            self.client.data[f"/repos/{REPO}"]["id"] = 78
            session.refresh()
            with self.assertRaisesRegex(r.ResearchError, "stale, forged"):
                r.resolve_download_operation(self.context, operation)
            self.assertEqual(len(self.client.byte_calls), 2)

    def test_refresh_rejects_mutated_or_missing_provenance_and_evicts(self):
        mutations = [
            (f"/repos/{REPO}", "private", True),
            (f"/repos/{REPO}", "fork", True),
            (f"/repos/{REPO}", "full_name", "other/widget"),
            (f"/repos/{REPO}/releases/20", "draft", True),
            (f"/repos/{REPO}/releases/20", "prerelease", True),
            (f"/repos/{REPO}/releases/20", "assets_url", "https://evil.test"),
            (f"/repos/{REPO}/releases/assets/30", "digest", "sha256:" + "0" * 64),
            (f"/repos/{REPO}/releases/assets/30", "name", "widget-1.2.4-linux-amd64.tar.gz"),
            (f"/repos/{REPO}/releases/assets/30", "state", "deleted"),
        ]
        for path, key, value in mutations:
            with self.subTest(path=path, key=key):
                self.client = FakeClient()
                with r.research_session(client=self.client) as session:
                    operation = self.selected()
                    self.client.data[path][key] = value
                    session.refresh()
                    with self.assertRaises(r.ResearchError):
                        r.resolve_download_operation(self.context, operation)
                    self.assertFalse(session._entries)

    def test_asset_membership_and_size_change_require_fresh_verification(self):
        with r.research_session(client=self.client) as session:
            operation = self.selected()
            self.client.asset["size"] = 19
            session.refresh()
            r.resolve_download_operation(self.context, operation)
            self.assertEqual(self.client.byte_calls[-1][1], 19)
            self.assertEqual(len(self.client.byte_calls), 2)
            self.client.data[f"/repos/{REPO}/releases/20/assets?per_page=100&page=1"] = []
            session.refresh()
            with self.assertRaises(r.ResearchError):
                r.resolve_download_operation(self.context, operation)
            self.assertFalse(session._entries)

    def test_restored_original_asset_stops_speculative_patch_upgrade(self):
        with r.research_session(client=self.client) as session:
            operation = self.selected()
            self.client.data[f"/repos/{REPO}/releases/10/assets?per_page=100&page=1"] = [
                asset(12, "widget_1.2.3_linux_arm64.tar.gz", "v1.2.3")
            ]
            session.refresh()
            with self.assertRaises(r.ResearchError):
                r.resolve_download_operation(self.context, operation)
            self.assertFalse(session._entries)

    def test_failure_or_negative_research_is_never_cached(self):
        with r.research_session(client=self.client) as session:
            self.client.asset["digest"] = None
            with self.assertRaises(r.ResearchError):
                self.selected()
            self.assertFalse(session._entries)
            self.client.asset["digest"] = "sha256:" + SHA
            self.selected()
            self.assertEqual(len(self.client.byte_calls), 1)
        self.client = FakeClient()
        self.client.data[f"/repos/{REPO}/releases?per_page=10&page=1"] = []
        with r.research_session(client=self.client) as session:
            self.assertFalse(r.research_downloads(self.context)["candidates"])
            self.assertFalse(session._entries)
            self.client.data[f"/repos/{REPO}/releases?per_page=10&page=1"] = [self.client.new]
            self.assertTrue(r.research_downloads(self.context)["candidates"])

    def test_refresh_failure_cannot_fall_back_to_cached_bytes(self):
        with r.research_session(client=self.client) as session:
            operation = self.selected()
            session.refresh()
            with patch.object(self.client, "get_json", side_effect=r.ResearchError("unavailable")):
                with self.assertRaises(r.ResearchError):
                    r.resolve_download_operation(self.context, operation)
            self.assertFalse(session._entries)
            r.resolve_download_operation(self.context, operation)
            self.assertEqual(len(self.client.byte_calls), 2)

    def test_partial_research_results_are_not_cached(self):
        original = r._research

        def partial(*args, **kwargs):
            rows, _ = original(*args, **kwargs)
            return rows, ["no_supported_verified_arm_asset"]

        with r.research_session(client=self.client) as session:
            with patch.object(r, "_research", side_effect=partial):
                self.selected()
                self.selected()
            self.assertFalse(session._entries)
            self.assertEqual(len(self.client.byte_calls), 2)

    def test_cache_size_evicts_old_entries_and_never_retains_oversize_payload(self):
        with r.research_session(client=self.client) as session:
            self.selected()
            size = sum(len(entry.payload) for entry in session._entries.values())
            with patch.object(r, "MAX_CACHE_BYTES", size):
                r.research_downloads({**self.context, "base_sha": "b" * 40})
                self.assertLessEqual(
                    sum(len(entry.payload) for entry in session._entries.values()), size
                )
                self.assertEqual(len(session._entries), 1)

    def test_nested_sessions_restore_only_their_own_cache(self):
        second = FakeClient()
        with r.research_session(client=self.client):
            operation = self.selected()
            with r.research_session(client=second):
                r.resolve_download_operation(self.context, operation)
            r.resolve_download_operation(self.context, operation)
        self.assertEqual(len(self.client.byte_calls), 1)
        self.assertEqual(len(second.byte_calls), 1)

    def test_cache_count_size_and_lifecycle_are_bounded(self):
        with patch.object(r, "MAX_CACHE_ENTRIES", 1):
            with r.research_session(client=self.client) as session:
                operation = self.selected()
                r.research_downloads({**self.context, "base_sha": "b" * 40})
                self.assertEqual(len(session._entries), 1)
                r.resolve_download_operation(self.context, operation)
                self.assertEqual(len(self.client.byte_calls), 3)
            self.assertFalse(session._entries)
        with patch.object(r, "MAX_CACHE_BYTES", 1):
            with r.research_session(client=self.client) as session:
                self.selected()
                self.assertFalse(session._entries)

    def test_explicit_custom_clients_remain_independent_without_session(self):
        for _ in range(2):
            r.research_downloads(self.context, client=self.client)
        self.assertEqual(len(self.client.byte_calls), 2)

    def test_changed_selection_set_does_not_extend_reused_byte_lifetime(self):
        original = r._research

        def changed_selection(*args, **kwargs):
            rows, unsupported = original(*args, **kwargs)
            # Exercise cache lifetime when another fully verified selection was
            # added to this context; the existing asset bytes keep their age.
            other = {**rows[0], "research_id": "f" * 64, "_byte_identity": "e" * 64}
            return [*rows, other], unsupported

        with patch.object(r.time, "monotonic", return_value=1000.0) as clock:
            with r.research_session(client=self.client) as session:
                self.selected()
                clock.return_value = 1000.0 + r.CACHE_SECONDS - 1
                with patch.object(r, "_research", side_effect=changed_selection):
                    r.research_downloads(self.context, fresh=True)
                self.assertEqual(next(iter(session._entries.values())).created, 1000.0)
                clock.return_value += 1
                self.selected()
                self.assertEqual(len(self.client.byte_calls), 2)


class TransportTests(unittest.TestCase):
    def setUp(self):
        budget = patch.object(r, "_REQUEST_BUDGET", r._RequestBudget())
        budget.start()
        self.addCleanup(budget.stop)

    def response(self, response):
        connection = MagicMock()
        connection.getresponse.return_value = response
        return connection

    def test_only_explicit_github_metadata_credentials_are_accepted(self):
        for value in ("sk-model-secret", "eyJ.jwt.token", "ghp_legacy", "", "ghs_bad\nheader", 123):
            with self.subTest(value=value), self.assertRaises(r.ResearchError):
                r.GitHubReleases(metadata_token=value)
        for value in ("ghs_" + "a" * 36, "github_pat_" + "a" * 60):
            r.GitHubReleases(metadata_token=value)

    def test_github_token_is_only_sent_to_metadata_and_never_asset_or_cdn(self):
        token = "ghs_" + "a" * 36
        location = (
            "https://release-assets.githubusercontent.com/"
            "github-production-release-asset/77/id?sig=temporary"
        )
        metadata = self.response(Response())
        binary = self.response(Response(status=302, headers={"location": location}))
        cdn = self.response(Response(b"verified-arm-asset"))
        with patch.object(r, "_PinnedHTTPS", side_effect=[metadata, binary, cdn]):
            client = r.GitHubReleases(metadata_token=token)
            client.get_json("/repos/example/widget")
            self.assertEqual(
                client.asset_sha256("/repos/example/widget/releases/assets/30", 18), SHA
            )
        self.assertEqual(
            metadata.request.call_args.kwargs["headers"]["Authorization"], "Bearer " + token
        )
        for connection in (binary, cdn):
            self.assertNotIn("Authorization", connection.request.call_args.kwargs["headers"])
            self.assertNotIn(token, repr(connection.mock_calls))
        self.assertEqual(r._REQUEST_BUDGET.counts, {False: 1, True: 1})

    def test_authenticated_metadata_redirect_never_forwards_token(self):
        connection = self.response(
            Response(status=302, headers={"location": "https://evil.test/secret"})
        )
        with patch.object(r, "_PinnedHTTPS", return_value=connection) as constructor:
            with self.assertRaises(r.ResearchError):
                r.GitHubReleases(metadata_token="ghs_" + "a" * 36).get_json("/repos/example/widget")
        constructor.assert_called_once()
        connection.request.assert_called_once()

    def test_unauthenticated_budget_is_shared_across_new_clients(self):
        with patch.object(r, "UNAUTHENTICATED_REQUESTS", 2):
            connection = self.response(Response())
            with patch.object(r, "_PinnedHTTPS", return_value=connection) as constructor:
                for _ in range(2):
                    connection.getresponse.return_value = Response()
                    r.GitHubReleases().get_json("/repos/example/widget")
                with self.assertRaisesRegex(r.ResearchError, "quota exhausted"):
                    r.GitHubReleases().get_json("/repos/example/widget")
            self.assertEqual(constructor.call_count, 2)

    def test_metadata_authentication_does_not_bypass_binary_quota(self):
        r._REQUEST_BUDGET.counts[False] = r.UNAUTHENTICATED_REQUESTS
        connection = self.response(Response())
        with patch.object(r, "_PinnedHTTPS", return_value=connection) as constructor:
            client = r.GitHubReleases(metadata_token="ghs_" + "a" * 36)
            client.get_json("/repos/example/widget")
            with self.assertRaisesRegex(r.ResearchError, "quota exhausted"):
                client.asset_sha256("/repos/example/widget/releases/assets/30", 18)
        self.assertEqual(constructor.call_count, 1)

    def test_authenticated_budget_exhaustion_does_not_fall_back_to_anonymous(self):
        r._REQUEST_BUDGET.counts[True] = r.AUTHENTICATED_REQUESTS
        with patch.object(r, "_PinnedHTTPS") as constructor:
            with self.assertRaisesRegex(r.ResearchError, "quota exhausted"):
                r.GitHubReleases(metadata_token="ghs_" + "a" * 36).get_json("/repos/example/widget")
        constructor.assert_not_called()

    def test_server_quota_headers_stop_later_requests_without_retry(self):
        for status in (200, 403, 429):
            with self.subTest(status=status):
                r._REQUEST_BUDGET = r._RequestBudget()
                connection = self.response(
                    Response(
                        status=status,
                        headers={"x-ratelimit-remaining": "0", "retry-after": "7200"},
                    )
                )
                with patch.object(r, "_PinnedHTTPS", return_value=connection) as constructor:
                    if status == 200:
                        r.GitHubReleases().get_json("/repos/example/widget")
                    else:
                        with self.assertRaises(r.ResearchError):
                            r.GitHubReleases().get_json("/repos/example/widget")
                    with self.assertRaisesRegex(r.ResearchError, "quota exhausted"):
                        r.GitHubReleases().get_json("/repos/example/widget")
                self.assertEqual(constructor.call_count, 1)

    def test_budget_window_reset_never_shortens_server_cooldown(self):
        with patch.object(r.time, "monotonic", return_value=1000.0) as clock:
            budget = r._RequestBudget()
            budget.observe(False, 429, {"retry-after": "7200"})
            clock.return_value = 1000.0 + r.QUOTA_SECONDS
            with self.assertRaises(r.ResearchError):
                budget.take(False)
            clock.return_value = 8200.0
            budget.take(False)
            self.assertEqual(budget.counts[False], 1)

    def test_rate_limit_header_duplicates_fail_closed(self):
        response = Response()
        response.headers = [("x-ratelimit-remaining", "0"), ("X-RateLimit-Remaining", "50")]
        with patch.object(r, "_PinnedHTTPS", return_value=self.response(response)):
            with self.assertRaises(r.ResearchError):
                r.GitHubReleases().get_json("/repos/example/widget")

    def test_scoped_metadata_token_is_not_exported_or_retained_after_exit(self):
        client = FakeClient()
        token = "ghs_" + "a" * 36
        with patch.object(r, "GitHubReleases", return_value=client) as factory:
            with r.research_session(metadata_token=token) as session:
                report = r.research_downloads(context())
                self.assertNotIn(token, json.dumps(report))
            self.assertFalse(session._entries)
            self.assertIsNone(session._token)
            factory.assert_called_with(metadata_token=token)
        with self.assertRaises(r.ResearchError):
            with r.research_session(metadata_token=token, client=client):
                self.fail("ambiguous client accepted")

    def test_metadata_is_credential_free_and_has_no_environment_proxy(self):
        connection = self.response(Response())
        with (
            patch.object(r, "_PinnedHTTPS", return_value=connection),
            patch.dict(
                "os.environ", {"GH_TOKEN": "secret", "HTTPS_PROXY": "https://proxy.invalid:8080"}
            ),
        ):
            result = r.GitHubReleases().get_json("/repos/example/widget")
        self.assertEqual(result, {"ok": True})
        headers = connection.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("secret", repr(connection.mock_calls))
        self.assertEqual(connection.request.call_args.args, ("GET", "/repos/example/widget"))
        connection.close.assert_called_once()

    def test_metadata_redirect_and_rate_limit_are_not_followed_or_retried(self):
        for code in (301, 302, 307, 403, 429, 500):
            r._REQUEST_BUDGET = r._RequestBudget()
            connection = self.response(
                Response(status=code, headers={"location": "https://evil.test"})
            )
            with self.subTest(code=code), patch.object(r, "_PinnedHTTPS", return_value=connection):
                with self.assertRaises(r.ResearchError):
                    r.GitHubReleases().get_json("/repos/example/widget")
                self.assertEqual(connection.request.call_count, 1)

    def test_only_bounded_approved_api_paths_are_accepted(self):
        for path in (
            "/user",
            "/repos/example/widget/actions/artifacts/9",
            "/repos/example/widget/../../user",
            "/repos/example/widget?token=secret",
            "/repos/example/widget/releases?per_page=1000&page=1",
            "/repos/example/widget/releases/tags/%2e%2e",
        ):
            with self.subTest(path=path), patch.object(r, "_PinnedHTTPS") as connection:
                with self.assertRaises(r.ResearchError):
                    r.GitHubReleases().get_json(path)
                connection.assert_not_called()

    def test_binary_is_hashed_and_expected_size_checked(self):
        connection = self.response(
            Response(b"verified-arm-asset", headers={"content-length": "18"})
        )
        with patch.object(r, "_PinnedHTTPS", return_value=connection):
            self.assertEqual(
                r.GitHubReleases().asset_sha256("/repos/example/widget/releases/assets/30", 18), SHA
            )

    def test_binary_wrong_length_rejected(self):
        connection = self.response(Response(b"short", headers={"content-length": "20"}))
        with patch.object(r, "_PinnedHTTPS", return_value=connection):
            with self.assertRaises(r.ResearchError):
                r.GitHubReleases().asset_sha256("/repos/example/widget/releases/assets/30", 20)

    def test_one_approved_cdn_redirect_does_not_forward_credentials(self):
        location = "https://release-assets.githubusercontent.com/github-production-release-asset/77/id?sig=temporary"
        first = self.response(Response(status=302, headers={"location": location}))
        second = self.response(Response(b"verified-arm-asset"))
        with patch.object(r, "_PinnedHTTPS", side_effect=[first, second]) as constructor:
            result = r.GitHubReleases().asset_sha256("/repos/example/widget/releases/assets/30", 18)
        self.assertEqual(result, SHA)
        self.assertEqual(
            constructor.call_args_list[1].args, ("release-assets.githubusercontent.com",)
        )
        self.assertNotIn("Authorization", second.request.call_args.kwargs["headers"])

    def test_bad_redirect_destinations_are_rejected_before_connect(self):
        for location in (
            "http://release-assets.githubusercontent.com/github-production-release-asset/1",
            "https://evil.test/github-production-release-asset/1",
            "https://127.0.0.1/github-production-release-asset/1",
            "https://user:secret@release-assets.githubusercontent.com/github-production-release-asset/1",
            "https://release-assets.githubusercontent.com:443/github-production-release-asset/1",
            "https://release-assets.githubusercontent.com/unrelated",
            "https://release-assets.githubusercontent.com/github-production-release-asset/1#fragment",
        ):
            first = self.response(Response(status=302, headers={"location": location}))
            with (
                self.subTest(location=location),
                patch.object(r, "_PinnedHTTPS", return_value=first) as constructor,
            ):
                with self.assertRaises(r.ResearchError):
                    r.GitHubReleases().asset_sha256("/repos/example/widget/releases/assets/30", 18)
                self.assertEqual(constructor.call_count, 1)

    def test_second_redirect_is_not_followed(self):
        location = "https://release-assets.githubusercontent.com/github-production-release-asset/1"
        first = self.response(Response(status=302, headers={"location": location}))
        second = self.response(Response(status=302, headers={"location": location}))
        with patch.object(r, "_PinnedHTTPS", side_effect=[first, second]) as constructor:
            with self.assertRaises(r.ResearchError):
                r.GitHubReleases().asset_sha256("/repos/example/widget/releases/assets/30", 18)
            self.assertEqual(constructor.call_count, 2)

    def test_dns_private_mixed_and_reserved_answers_fail_before_socket(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "192.168.1.1",
            "100.64.0.1",
            "0.0.0.0",  # noqa: S104 - a rejected DNS answer, never a bind address
            "::1",
            "::ffff:127.0.0.1",
            "224.0.0.1",
        ):
            records = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.5", 443)),
                (
                    socket.AF_INET6 if ":" in address else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (address, 443),
                ),
            ]
            with (
                self.subTest(address=address),
                patch.object(r.socket, "getaddrinfo", return_value=records),
                patch.object(r.socket, "socket") as constructor,
            ):
                with self.assertRaises(r.ResearchError):
                    r._PinnedHTTPS("api.github.com").connect()
                constructor.assert_not_called()

    def test_dns_result_is_pinned_but_tls_uses_original_hostname(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.5", 443))]
        raw = MagicMock()
        tls = MagicMock()
        with (
            patch.object(r.socket, "getaddrinfo", return_value=records),
            patch.object(r.socket, "socket", return_value=raw),
            patch.object(r.ssl, "SSLContext", return_value=tls),
        ):
            r._PinnedHTTPS("api.github.com", timeout=15).connect()
        raw.connect.assert_called_once_with(("140.82.112.5", 443))
        tls.wrap_socket.assert_called_once_with(raw, server_hostname="api.github.com")

    def test_json_duplicate_keys_constants_and_oversize_rejected(self):
        for raw in (
            b'{"id":1,"id":2}',
            b'{"id":NaN}',
            b"[" * 2000,
            b" " * (r.MAX_JSON + 1),
            b"\xff",
        ):
            with self.subTest(size=len(raw)), self.assertRaises(r.ResearchError):
                r._json(raw)

    def test_budget_expiry_and_nested_deadlines_fail_closed(self):
        client = r.GitHubReleases()
        client.requests = r.MAX_REQUESTS
        with self.assertRaises(r.ResearchError):
            client.get_json("/repos/example/widget")
        client = r.GitHubReleases()
        client.expires = 0
        with self.assertRaises(r.ResearchError):
            client.get_json("/repos/example/widget")
        with patch.object(r.signal, "getitimer", return_value=(10.0, 0.0)):
            with self.assertRaises(r.ResearchError), r._deadline(10):
                self.fail("nested timer accepted")

    def test_deadline_interrupts_headers_and_is_restored(self):
        connection = self.response(Response())
        previous = signal.getsignal(signal.SIGALRM)

        def expire():
            signal.raise_signal(signal.SIGALRM)

        connection.getresponse.side_effect = expire
        with patch.object(r, "_PinnedHTTPS", return_value=connection):
            with self.assertRaisesRegex(r.ResearchError, "request failed"):
                r.GitHubReleases().get_json("/repos/example/widget")
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_transport_rejects_oversize_encoding_and_duplicate_security_headers(self):
        responses = [
            Response(headers={"content-length": str(r.MAX_JSON + 1)}),
            Response(headers={"content-encoding": "gzip"}),
            Response(headers={"content-length": "0"}),
            Response(headers={"content-length": "-1"}),
        ]
        duplicate = Response()
        duplicate.headers = [("content-length", "1"), ("Content-Length", "1")]
        responses.append(duplicate)
        for response in responses:
            with (
                self.subTest(headers=response.headers),
                patch.object(r, "_PinnedHTTPS", return_value=self.response(response)),
            ):
                with self.assertRaises(r.ResearchError):
                    r.GitHubReleases().get_json("/repos/example/widget")

    def test_tls_failure_closes_raw_socket(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.5", 443))]
        raw = MagicMock()
        tls = MagicMock()
        tls.wrap_socket.side_effect = OSError("private raw detail")
        with (
            patch.object(r.socket, "getaddrinfo", return_value=records),
            patch.object(r.socket, "socket", return_value=raw),
            patch.object(r.ssl, "SSLContext", return_value=tls),
        ):
            with self.assertRaises(OSError):
                r._PinnedHTTPS("api.github.com", timeout=15).connect()
        raw.close.assert_called_once()

    def test_transport_errors_never_return_response_or_credential_material(self):
        connection = self.response(Response())
        connection.getresponse.side_effect = OSError("https://private.invalid/token=secret")
        with patch.object(r, "_PinnedHTTPS", return_value=connection):
            with self.assertRaises(r.ResearchError) as error:
                r.GitHubReleases().get_json("/repos/example/widget")
        self.assertEqual(str(error.exception), "upstream request failed")
        self.assertIsNone(error.exception.__cause__)

    def test_worker_threads_cannot_omit_hard_deadline(self):
        errors = []

        def run():
            try:
                with r._deadline(10):
                    pass
            except r.ResearchError as error:
                errors.append(str(error))

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["research requires main-thread deadline enforcement"])

    def test_masked_deadline_is_rejected_before_network(self):
        with patch.object(r.signal, "pthread_sigmask", return_value={signal.SIGALRM}):
            with self.assertRaisesRegex(r.ResearchError, "signal is blocked"), r._deadline(10):
                self.fail("masked deadline accepted")

    def test_tls_context_ignores_keylog_environment_and_verifies_peer(self):
        with patch.dict("os.environ", {"SSLKEYLOGFILE": "/nonexistent/research-keys.log"}):
            connection = r._PinnedHTTPS("api.github.com")
        self.assertEqual(connection._tls.verify_mode, r.ssl.CERT_REQUIRED)
        self.assertTrue(connection._tls.check_hostname)
        self.assertIsNone(connection._tls.keylog_filename)


if __name__ == "__main__":
    unittest.main()
