"""Exercise the actual VPP tag lookup without network or package execution."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-vpp.yml"
TOKEN = "synthetic-vpp-test-token"
URL = "https://api.github.com/repos/FDio/vpp/tags?per_page=20"


class VppVersionLookupTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.job = self.workflow["jobs"]["test-vpp"]
        self.step = next(step for step in self.job["steps"] if step.get("id") == "version")
        self.program = self.step["run"].split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]

    def execute(self):
        namespace = {}
        exec(compile(self.program, "workflow:vpp-version", "exec"), namespace)
        return namespace

    def test_authenticated_lookup_preserves_stable_tag_selection(self):
        response = io.BytesIO(json.dumps([
            {"name": "v26.10-rc1"}, {"name": "v26.06"}, {"name": "v26.02"},
        ]).encode())
        output = io.StringIO()
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), \
                patch("urllib.request.OpenerDirector.open", return_value=response) as request, \
                contextlib.redirect_stdout(output):
            self.execute()
        argument = request.call_args.args[0]
        self.assertEqual(argument.full_url, URL)
        self.assertEqual(argument.get_method(), "GET")
        self.assertEqual(argument.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(argument.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(request.call_args.kwargs, {"timeout": 20})
        self.assertEqual(request.call_count, 1)
        self.assertEqual(output.getvalue(), "26.06-release\n")
        self.assertNotIn(TOKEN, output.getvalue())

    def test_http_failure_is_not_converted_to_success(self):
        failure = urllib.error.HTTPError(URL, 403, "rate limit exceeded", {}, None)
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), \
                patch("urllib.request.OpenerDirector.open", side_effect=failure) as request, \
                self.assertRaises(urllib.error.HTTPError):
            self.execute()
        self.assertEqual(request.call_count, 1)

    def test_missing_token_does_not_make_anonymous_request(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch("urllib.request.OpenerDirector.open") as request, self.assertRaises(KeyError):
            self.execute()
        request.assert_not_called()

    def test_malformed_response_still_fails(self):
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), \
                patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(b"not JSON")), \
                self.assertRaises(json.JSONDecodeError):
            self.execute()

    def test_no_stable_tag_preserves_unknown_result(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), \
                patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(b'[{"name":"v26.10-rc1"}]')), \
                contextlib.redirect_stdout(output):
            self.execute()
        self.assertEqual(output.getvalue(), "unknown\n")

    def test_authenticated_redirects_are_rejected_before_followup_request(self):
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), \
                patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(b"[]")), \
                contextlib.redirect_stdout(io.StringIO()):
            namespace = self.execute()
        opener = namespace["opener"]
        handler = next(item for item in opener.handlers
                       if isinstance(item, namespace["NoRedirects"]))
        for target in ("https://other.example/tags", "http://api.github.com/tags", URL):
            with self.subTest(target=target), patch.object(opener, "open") as followup, \
                    self.assertRaises(urllib.error.HTTPError):
                handler.http_error_302(namespace["req"], io.BytesIO(), 302, "Found",
                                       {"location": target})
            followup.assert_not_called()

    def test_version_step_keeps_lookup_token_out_of_package_process(self):
        with tempfile.TemporaryDirectory(prefix="vpp-token-test-") as temporary:
            root = Path(temporary)
            binaries = {
                "vpp": '#!/bin/sh\n[ "${GH_TOKEN+x}" != x ] || exit 97\nprintf "vpp v26.06-release\\n"\n',
                "python3": '#!/bin/sh\n[ "$GH_TOKEN" = "' + TOKEN
                           + '" ] || exit 98\ncat >/dev/null\nprintf "26.06-release\\n"\n',
            }
            for name, content in binaries.items():
                executable = root / name
                executable.write_text(content)
                executable.chmod(0o755)
            output = root / "output"
            result = subprocess.run(
                ["bash", "-c", self.step["run"]], capture_output=True, text=True, timeout=10,
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                     "GH_TOKEN": TOKEN, "GITHUB_OUTPUT": str(output)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "version=26.06-release\nlatest=26.06-release\n")
            self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_token_is_limited_to_version_step_with_read_only_permissions(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.step["env"], {"GH_TOKEN": "${{ github.token }}"})
        self.assertNotIn("GH_TOKEN", self.job.get("env", {}))
        self.assertEqual([step.get("id") for step in self.job["steps"]
                          if "GH_TOKEN" in step.get("env", {})], ["version"])
        self.assertNotIn("continue-on-error", self.step)
        self.assertTrue(self.step["run"].startswith("set -euo pipefail\n"))


if __name__ == "__main__":
    unittest.main()
