"""Ollama's historical API is version-bound, while genuine runtime failures stay red."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import package_observation_migration_audit as audit


class OllamaWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ollama-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load((ROOT / ".github/workflows/test-ollama.yml").read_text())["jobs"]["test-ollama"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.artifact, self.runtime = re.findall(r"^python3 - <<'PY'\n(.*?)^PY$", self.job["env"]["OLLAMA_SMOKE_COMMAND"], re.M | re.S)

    def run_step(self, name, values=None, **environment):
        values = values or {}
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = self.root / "output"
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(output), **environment},
                                capture_output=True, text=True, timeout=10)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def execute_runtime(self, expected="0.1.0", cli=None, root_body=b"Ollama is running", tags=None,
                        listing="NAME ID SIZE MODIFIED\n", api_version=None, missing_api=False, exited=None, offline=False,
                        unsupported_version=False, artifact_version=None):
        directory = self.root / f"runtime-{len(list(self.root.glob('runtime-*')))}"
        directory.mkdir()
        (directory / "artifact-proof.json").write_text(json.dumps({"release_tag": "v" + (artifact_version or expected)}))
        self.process = Mock(pid=12345678)
        self.process.poll.return_value = exited
        self.process.returncode = exited
        self.process.wait.return_value = 0
        self.urls = []
        def request(url, **_kwargs):
            self.urls.append(url)
            if offline:
                raise urllib.error.URLError("connection refused")
            if url.endswith("/api/version"):
                if missing_api:
                    raise urllib.error.HTTPError(url, 404, "not found", {}, None)
                body = json.dumps({"version": api_version or expected}).encode()
            elif url.endswith("/api/tags"):
                body = json.dumps(tags if tags is not None else {"models": None if expected == "0.1.0" else []}).encode()
            else:
                body = root_body
            response = io.BytesIO(body)
            response.status = 200
            return response
        def popen(_command, **kwargs):
            self.assertEqual("true", kwargs["env"]["OLLAMA_NO_CLOUD"])
            kwargs["stdout"].write("ollama server diagnostic fixture\n")
            kwargs["stdout"].flush()
            return self.process
        def cli_command(command, **_kwargs):
            if command[-1] == "--version" and unsupported_version:
                raise subprocess.CalledProcessError(1, command, output="Error: unknown flag: --version\n")
            return f"ollama version is {cli or expected}\n" if command[-1] == "--version" else listing
        self.printed = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, WORKDIR=str(directory), SMOKE_VERSION=expected,
                                           OLLAMA_BIN=str(directory / "ollama"), ASSET_URL=f"https://github.com/ollama/ollama/releases/download/v{expected}/ollama-linux-arm64"))
            stack.enter_context(patch("subprocess.Popen", side_effect=popen))
            stack.enter_context(patch("subprocess.check_output", side_effect=cli_command))
            stack.enter_context(patch("urllib.request.urlopen", side_effect=request))
            sockets = stack.enter_context(patch("socket.socket"))
            sockets.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 54321)
            stack.enter_context(patch("time.sleep"))
            self.kill = stack.enter_context(patch("os.killpg"))
            stack.enter_context(contextlib.redirect_stdout(self.printed))
            exec(compile(self.runtime, "ollama-runtime", "exec"), {})
        return json.loads((directory / "runtime-proof.json").read_text())

    def test_legacy_runtime_requires_cli_root_tags_and_list_not_modern_api(self):
        proof = self.execute_runtime(unsupported_version=True)
        self.assertEqual("0.1.0", proof["version"])
        self.assertEqual("official_release_asset_only; embedded_version_unavailable", proof["version_basis"])
        self.assertIsNone(proof["api_version"])
        self.assertTrue(any(url.endswith("/api/tags") for url in self.urls))
        self.assertFalse(any(url.endswith("/api/version") for url in self.urls))
        self.kill.assert_called_once()
        self.process.wait.assert_called_once()

    def test_modern_candidate_keeps_exact_api_version_assertion(self):
        proof = self.execute_runtime(expected="0.32.5")
        self.assertEqual({"version": "0.32.5"}, proof["api_version"])
        for arguments in ({"api_version": "0.1.0"}, {"missing_api": True}, {"tags": {"models": None}},
                          {"unsupported_version": True}, {"artifact_version": "0.1.0"}):
            with self.subTest(arguments=arguments), self.assertRaises((AssertionError, urllib.error.HTTPError)):
                self.execute_runtime(expected="0.32.5", **arguments)

    def test_release_asset_binding_rejects_wrong_tag_url_size_or_digest(self):
        data = b"release asset fixture"
        name = "ollama-linux-arm64"
        url = "https://github.com/ollama/ollama/releases/download/v0.33.3/" + name
        (self.root / name).write_bytes(data)
        for change in ({}, {"tag_name": "v0.2.0"}, {"draft": True}, {"prerelease": True},
                       {"browser_download_url": "https://example.invalid/binary"}, {"size": 1}, {"digest": "sha256:bad"}):
            with self.subTest(change=change):
                asset = {"id": 123, "name": name, "browser_download_url": url, "size": len(data),
                         "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                release = {"tag_name": "v0.33.3", "draft": False, "prerelease": False, "assets": [asset]}
                for key, value in change.items():
                    (release if key in release else asset)[key] = value
                (self.root / "release.json").write_text(json.dumps(release))
                with patch.dict(os.environ, WORKDIR=str(self.root), SMOKE_VERSION="0.33.3", ASSET=name, ASSET_URL=url), contextlib.redirect_stdout(io.StringIO()):
                    if change:
                        with self.assertRaises(AssertionError):
                            exec(compile(self.artifact, "ollama-artifact", "exec"), {})
                    else:
                        exec(compile(self.artifact, "ollama-artifact", "exec"), {})
                        self.assertEqual(hashlib.sha256(data).hexdigest(), json.loads((self.root / "artifact-proof.json").read_text())["sha256"])

    def baseline_artifact_fixture(self, name, data, publisher_digest=None):
        url = "https://github.com/ollama/ollama/releases/download/v0.1.0/" + name
        (self.root / name).write_bytes(data)
        asset = {"id": 127702158, "name": name, "browser_download_url": url,
                 "size": len(data), "digest": publisher_digest}
        (self.root / "release.json").write_text(json.dumps({"tag_name": "v0.1.0", "draft": False,
                                                           "prerelease": False, "assets": [asset]}))
        with patch.dict(os.environ, WORKDIR=str(self.root), SMOKE_VERSION="0.1.0", ASSET=name, ASSET_URL=url), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.artifact, "ollama-artifact", "exec"), {})

    def test_baseline_rejects_wrong_bytes_at_same_official_url_and_size(self):
        for data in (b"replacement A", b"replacement B"):
            for publisher_digest in (None, "sha256:" + hashlib.sha256(data).hexdigest()):
                with self.subTest(data=data, publisher_digest=publisher_digest):
                    with self.assertRaisesRegex(AssertionError, "differs from the reviewed bytes"):
                        self.baseline_artifact_fixture("ollama-linux-arm64", data, publisher_digest)
                    self.assertFalse((self.root / "artifact-proof.json").exists())

    def test_baseline_requires_raw_asset_name_and_exact_reviewed_hash(self):
        reviewed = "16cb9f8021f79cae616e0a34959d827972f6805a2cf6a36f55e66b37d5e4d572"
        # Only this unit fixture simulates the known hash; native replay hashes the actual ELF.
        with patch("hashlib.sha256") as hasher:
            hasher.return_value.hexdigest.return_value = reviewed
            with self.assertRaisesRegex(AssertionError, "ollama-linux-arm64.tgz"):
                self.baseline_artifact_fixture("ollama-linux-arm64.tgz", b"fixture")
            self.assertFalse((self.root / "artifact-proof.json").exists())
            self.baseline_artifact_fixture("ollama-linux-arm64", b"fixture")
            self.assertEqual(reviewed, json.loads((self.root / "artifact-proof.json").read_text())["sha256"])

    def test_wrong_cli_bad_http_shapes_and_dead_server_fail_with_cleanup(self):
        for arguments in ({"cli": "0.32.5"}, {"root_body": b"nonempty error"}, {"tags": {}},
                          {"tags": {"models": "bad"}}, {"listing": "server error\n"}, {"exited": 7}, {"offline": True}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AssertionError):
                    self.execute_runtime(**arguments)
                self.kill.assert_called_once()
                self.process.wait.assert_called_once()
                self.assertIn("ollama server diagnostic fixture", self.printed.getvalue())

    def test_baseline_runtime_failure_cannot_emit_pass(self):
        result, output = self.run_step("test5", OLLAMA_SMOKE_COMMAND="exit 31")
        self.assertEqual(31, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertIn("duration", output)

    def test_candidate_lookup_failure_or_missing_baseline_is_not_a_skip(self):
        binary = self.root / "bin"
        binary.mkdir()
        git = binary / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "$TAG_OUTPUT"\nexit "$GIT_EXIT"\n')
        git.chmod(0o755)
        for tags, exit_code, status in (("", "1", "failed"), ("", "0", "failed"),
                ("abc refs/tags/v0.32.5", "0", "failed"), ("abc refs/tags/v0.1.0", "0", "skipped")):
            with self.subTest(tags=tags, exit_code=exit_code):
                result, output = self.run_step("test6", PATH=str(binary) + os.pathsep + os.environ["PATH"],
                                               TAG_OUTPUT=tags, GIT_EXIT=exit_code, OLLAMA_SMOKE_COMMAND="exit 0")
                self.assertEqual(status, output["status"])
                self.assertEqual(status == "skipped", result.returncode == 0)

    def test_failed_candidate_cannot_claim_installed_version(self):
        binary = self.root / "bin"
        binary.mkdir()
        git = binary / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "abc refs/tags/v0.1.0" "def refs/tags/v0.32.5"\n')
        git.chmod(0o755)
        result, output = self.run_step("test6", PATH=str(binary) + os.pathsep + os.environ["PATH"], OLLAMA_SMOKE_COMMAND="exit 31")
        self.assertEqual(31, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertEqual("not_installed", output["next_installed_version"])

    def test_summary_requires_status_and_actual_outcome(self):
        for number in range(1, 7):
            for status, outcome in (("passed", "failure"), ("passed", "cancelled"), ("passed", ""), ("", "success"), ("skipped", "success")):
                values = self.statuses()
                values.update({f"steps.test{number}.outputs.status": status, f"steps.test{number}.outcome": outcome})
                result, output = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", output["failed"])
                self.assertEqual("1" if number <= 5 else "0", output["core_failed"])

    def test_audit_pairs_only_completed_candidate_decisions_with_their_status(self):
        self.assertEqual(
            (("limited_cpu_smoke_validated", "passed"), ("no_newer_stable_available", "skipped")),
            audit._step_literal_pairs(ROOT, self.steps["test6"]),
        )
        self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', self.steps["test6"]["run"])

    def test_only_proven_candidate_skip_and_named_outputs(self):
        result, output = self.run_step("summary", self.statuses())
        self.assertEqual((0, "6"), (result.returncode, output["passed"]))
        for outcome in ("success", "failure", "cancelled", ""):
            values = self.statuses()
            values.update({"steps.test6.outputs.status": "skipped", "steps.test6.outcome": outcome,
                           "steps.test6.outputs.decision": "no_newer_stable_available"})
            result, output = self.run_step("summary", values)
            self.assertEqual(outcome == "success", result.returncode == 0)
            self.assertEqual("1" if outcome == "success" else "0", output["skipped"])
        for number in range(1, 7):
            self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])
            self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])


if __name__ == "__main__":
    unittest.main()
