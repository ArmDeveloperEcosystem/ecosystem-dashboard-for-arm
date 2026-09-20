"""Execute Rav1e workflow/reporting with offline fixtures, not a native encoder."""

import io
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-rav1e.yml"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_result_policy as policy  # noqa: E402
import package_observation_migration_audit as audit  # noqa: E402


class Rav1eSmokeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text())
        cls.job = cls.workflow["jobs"]["test-rav1e"]
        cls.steps = {s["id"]: s for s in cls.job["steps"] if "id" in s}
        cls.action = yaml.safe_load(
            (ROOT / ".github/actions/generic-source-regression-check/action.yml").read_text()
        )
        collector = yaml.safe_load(
            (ROOT / ".github/actions/collect-batch-results/action.yml").read_text()
        )
        cls.collector = collector["runs"]["steps"][0]["run"].split(
            "python3 - <<'PY'\n", 1
        )[1].rsplit("\nPY", 1)[0]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rav1e-smoke-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.output = self.root / "output"
        self.env = {
            **os.environ, **self.job["env"], "GH_TOKEN": "offline-fixture-token",
            "GITHUB_TOKEN": "another-offline-fixture-token",
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "GITHUB_OUTPUT": str(self.output), "FIXTURE_ROOT": str(self.root),
            "TMPDIR": str(self.root), "RUNNER_TEMP": str(self.root), "FIXTURE_FAILURE": "",
            "FIXTURE_RELEASE_TAG": "v0.8.1",
        }
        self.tool("curl", '''
            import json, os, pathlib, shutil, sys
            args = sys.argv[1:]
            url = next(x for x in args if x.startswith("https://"))
            output = pathlib.Path(args[args.index("-o") + 1])
            root = pathlib.Path(os.environ["FIXTURE_ROOT"])
            failure = os.environ["FIXTURE_FAILURE"]
            api = url.startswith("https://api.github.com/repos/xiph/rav1e/releases/")
            authorized = "Authorization: Bearer offline-fixture-token" in args
            with (root / "requests.jsonl").open("a") as stream:
                stream.write(json.dumps({"url": url, "authorized": authorized}) + "\\n")
            if api:
                assert authorized, "Metadata request must authenticate"
                assert args[args.index("--connect-timeout") + 1] == "10"
                assert args[args.index("--max-time") + 1] == "60"
                if failure == "metadata":
                    print("curl: (22) HTTP 403 fixture", file=sys.stderr)
                    sys.exit(22)
                if failure == "malformed":
                    output.write_text("<html>not release metadata</html>")
                else:
                    assets = [] if failure == "missing_asset" else [{
                        "name": "rav1e-0.8.1-linux-aarch64.tar.gz",
                        "browser_download_url": "https://github.com/xiph/rav1e/releases/download/v0.8.1/rav1e-0.8.1-linux-aarch64.tar.gz",
                    }]
                    output.write_text(json.dumps({"tag_name": os.environ["FIXTURE_RELEASE_TAG"], "assets": assets}))
            else:
                assert not authorized, "Do not forward the API token to asset downloads"
                assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
                assert args[args.index("--connect-timeout") + 1] == "10"
                assert args[args.index("--max-time") + 1] == "180"
                assert args[args.index("--proto") + 1] == "=https"
                assert args[args.index("--proto-redir") + 1] == "=https"
                assert url == "https://github.com/xiph/rav1e/releases/download/v0.8.1/rav1e-0.8.1-linux-aarch64.tar.gz"
                if failure == "download":
                    sys.exit(22)
                if failure == "archive":
                    output.write_text("invalid tarball")
                else:
                    shutil.copyfile(root / "fixture.tar.gz", output)
        ''')
        self.tool("git", '''
            import pathlib, sys
            assert sys.argv[1:] == ["clone", "--depth", "1", "--branch", "v0.8.1", "https://github.com/xiph/rav1e.git", "next-src"]
            pathlib.Path("next-src").mkdir()
            pathlib.Path("next-src/README.md").write_text("offline source fixture")
        ''')
        self.tool("timeout", '''
            import json, os, pathlib, subprocess, sys
            args = sys.argv[1:]
            assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
            assert args[0] == "--kill-after=5s"
            mode = args[3]
            assert args[1] == ("90s" if mode == "--limit" else "30s")
            root = pathlib.Path(os.environ["FIXTURE_ROOT"])
            with (root / "timers.jsonl").open("a") as stream:
                stream.write(json.dumps({"mode": mode, "seconds": args[1]}) + "\\n")
            failure = os.environ["FIXTURE_FAILURE"]
            timed_mode = "encode" if mode == "--limit" else mode.removeprefix("--")
            deadline = 0.1 if failure == timed_mode + "_timeout" else float(args[1][:-1])
            try:
                process = subprocess.run(args[2:], timeout=deadline)
                sys.exit(process.returncode)
            except subprocess.TimeoutExpired:
                sys.exit(124)
        ''')
        encoder = f"#!{sys.executable}\n" + textwrap.dedent('''
            import os, pathlib, struct, sys, time
            assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
            args = sys.argv[1:]
            failure = os.environ["FIXTURE_FAILURE"]
            if args in (["--version"], ["--help"]):
                if failure == args[0][2:]:
                    sys.exit(7)
                if failure == args[0][2:] + "_timeout":
                    time.sleep(5)
                if failure == args[0][2:] + "_empty":
                    sys.exit(0)
                if failure == args[0][2:] + "_wrong":
                    print("unrelated encoder 99.99.99")
                elif failure == "version_near_match" and args == ["--version"]:
                    print("rav1e 0.8.10 (v0.8.10) (release)")
                elif failure == "help_incomplete" and args == ["--help"]:
                    print("Usage: rav1e [OPTIONS] <INPUT>\\n--limit")
                elif args == ["--version"]:
                    print("rav1e 0.8.1 (v0.8.1) (release)\\nrustc 1.87.0 (17067e9ac 2025-05-09) aarch64-unknown-linux-musl\\nCompiled CPU Features: neon")
                else:
                    print("Usage: rav1e [OPTIONS] <INPUT>\\n--limit --speed --quantizer --output")
            else:
                assert args[:6] == ["--limit", "1", "--speed", "10", "--quantizer", "255"]
                assert args[6] == "-o"
                data = pathlib.Path(args[8]).read_bytes()
                header = b"YUV4MPEG2 W16 H16 F1:1 Ip A1:1 C420jpeg\\nFRAME\\n"
                assert data == header + bytes([128]) * 384
                target = pathlib.Path(args[7])
                if failure == "encode_timeout":
                    time.sleep(5)
                if failure == "no_output":
                    sys.exit(0)
                magic = b"JUNK" if failure == "wrong_format" else b"DKIF"
                codec = b"VP90" if failure == "wrong_codec" else b"AV01"
                width = 32 if failure == "wrong_size" else 16
                count = 2 if failure == "wrong_count" else 0
                header_size = 33 if failure == "wrong_header_size" else 32
                rate = 0 if failure == "wrong_rate" else 1
                header = struct.pack("<4sHH4sHHIIII", magic, 0, header_size, codec, width, 16, rate, 1, count, 0)
                payload = b"structural fixture only, not a decoded AV1 claim"
                length = 0 if failure == "zero_frame" else len(payload)
                timestamp = 1 if failure == "wrong_timestamp" else 0
                frame = struct.pack("<IQ", length, timestamp) + payload
                output = header + frame
                if failure == "truncated_header":
                    output = header[:16]
                elif failure == "truncated_frame":
                    output = output[:-1]
                elif failure == "extra_frame":
                    output += frame
                elif failure == "junk":
                    output = b"not an IVF bitstream"
                elif failure == "empty":
                    output = b""
                elif failure == "oversized":
                    output = b"x" * (1024 * 1024 + 1)
                target.write_bytes(output)
                if failure == "encode":
                    sys.exit(9)
                print("offline encoder fixture consumed one 16x16 frame")
        ''')
        with tarfile.open(self.root / "fixture.tar.gz", "w:gz") as archive:
            info = tarfile.TarInfo("rav1e")
            info.mode = 0o755
            info.size = len(encoder.encode())
            archive.addfile(info, io.BytesIO(encoder.encode()))
        process, _, _ = self.run_script(self.steps["runtime_probe"]["run"])
        self.assertEqual(0, process.returncode, process.stderr)

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
        path.chmod(0o755)

    def render(self, script, values):
        def expression(match):
            for part in match[1].split("||"):
                part = part.strip()
                value = part[1:-1] if part.startswith("'") else values.get(part)
                if value:
                    return str(value)
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def run_script(self, script, values=None, **env):
        self.output.write_text("")
        process = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(script, values or {})],
            cwd=self.root, env={**self.env, **env}, capture_output=True, text=True, timeout=20,
        )
        lines = self.output.read_text().splitlines()
        outputs = dict(line.split("=", 1) for line in lines)
        return process, outputs, lines

    def run_probe(self, number, failure=""):
        if number == 5:
            return self.run_script(self.steps["test5"]["run"], FIXTURE_FAILURE=failure)
        inputs = {key: spec.get("default", "") for key, spec in self.action["inputs"].items()}
        inputs.update(self.steps["test6"]["with"])
        inputs["baseline_version"] = "0.3.2"
        inputs["github_repo"] = "xiph/rav1e"
        inputs["lane_kind"] = self.job["env"]["LANE_KIND"]
        return self.run_script(
            self.action["runs"]["steps"][0]["run"],
            {f"inputs.{key}": value for key, value in inputs.items()},
            INPUT_LIMITED_CPU_PROBE=inputs["limited_cpu_probe"],
            INPUT_LIMITED_CPU_DESCRIPTION=inputs["limited_cpu_description"],
            INPUT_DEFER_ON_LIMITED_CPU_PROBE_FAILURE="false", FIXTURE_FAILURE=failure,
        )

    def summarize(self, statuses=None, outcomes=None):
        statuses = statuses or ["passed"] * 6
        outcomes = outcomes or ["success"] * 6
        values = {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", statuses[i - 1]),
            (f"steps.test{i}.outcome", outcomes[i - 1]),
            (f"steps.test{i}.outputs.duration", str(i)),
        )}
        return self.run_script(self.steps["summary"]["run"], values)

    def collect(self, summary, statuses, conclusions, *, decision=None, old_skip=False):
        outputs = {
            "contract_version": "2.0", "package_slug": "rav1e", "package_name": "Rav1e",
            "package_version": "0.3.2", "job_name": "test-rav1e",
            "run_status": summary["overall_status"], "badge_status": summary["badge_status"],
            "tests_passed": summary["passed"], "tests_failed": summary["failed"],
            "tests_skipped": "1" if old_skip else summary["skipped"],
            "core_failed": summary["core_failed"], "regression_status": statuses[5],
            "regression_decision": decision or (
                "limited_cpu_smoke_validated" if statuses[5] == "passed" else "limited_cpu_smoke_failed"
            ),
            "regression_policy": "applicable", "regression_current_version": "0.3.2",
            "regression_latest_version": "0.8.1", "regression_next_installed_version": (
                "0.8.1" if statuses[5] == "passed" else "limited_cpu_probe_failed"
            ),
        }
        failed = summary["overall_status"] == "failure"
        job = {
            "id": 456, "name": "test-rav1e / test-rav1e",
            "html_url": "https://github.com/example/project/actions/runs/123/job/456",
            "conclusion": "failure" if failed else "success",
            "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i,
                       "conclusion": conclusions[i - 1]} for i in range(1, 7)],
        }
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            env = {**self.env, "GH_TOKEN": "", "BATCH_NUMBER": "20", "BATCH_TITLE": "Batch 20",
                   "NEEDS_JSON": json.dumps({"test-rav1e": {"result": job["conclusion"], "outputs": outputs}}),
                   "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                   "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                   "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_OUTPUT": str(root / "output"), "GITHUB_STEP_SUMMARY": str(root / "summary")}
            process = subprocess.run([sys.executable, "-B", "-c", self.collector], cwd=root,
                                     env=env, capture_output=True, text=True, timeout=20)
            path = root / "test-results/rav1e-test-results/rav1e.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def test_scope_pins_and_failure_visibility(self):
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual("0.3.2", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("v0.8.1", self.steps["test6"]["with"]["candidate_tag_override"])
        for i in range(1, 7):
            self.assertEqual("always()", self.steps[f"test{i}"]["if"])
            self.assertNotIn("continue-on-error", self.steps[f"test{i}"])
        for i in (5, 6):
            self.assertEqual("${{ github.token }}", self.steps[f"test{i}"]["env"]["GH_TOKEN"])
        self.assertNotIn("defer_on_limited_cpu_probe_failure", self.steps["test6"]["with"])

    def test_both_probe_bodies_execute_positive_fixture(self):
        for i in (5, 6):
            with self.subTest(probe=i):
                process, outputs, lines = self.run_probe(i)
                self.assertEqual(0, process.returncode, process.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertEqual(1, sum(line.startswith("status=") for line in lines))
                self.assertEqual(1, sum(line.startswith("duration=") for line in lines))
                self.assertIn("offline encoder fixture consumed one 16x16 frame", process.stdout)
                self.assertIn("Verified rav1e 0.8.1: AV01 IVF 16x16, one complete frame", process.stdout)
                if i == 6:
                    self.assertEqual("limited_cpu_smoke_validated", outputs["decision"])
        requests = [json.loads(line) for line in (self.root / "requests.jsonl").read_text().splitlines()]
        self.assertEqual([True, False, True, False], [r["authorized"] for r in requests])
        self.assertTrue(requests[0]["url"].endswith("/releases/latest"))
        self.assertTrue(requests[2]["url"].endswith("/releases/tags/v0.8.1"))
        timers = [json.loads(line) for line in (self.root / "timers.jsonl").read_text().splitlines()]
        self.assertEqual(["30s", "30s", "90s"] * 2, [entry["seconds"] for entry in timers])

    def test_all_acquisition_and_cli_errors_emit_failure_not_skip(self):
        for i in (5, 6):
            for failure in ("metadata", "malformed", "missing_asset", "download", "archive",
                            "version", "help", "encode", "empty"):
                with self.subTest(probe=i, failure=failure):
                    process, outputs, lines = self.run_probe(i, failure)
                    self.assertEqual("failed", outputs["status"])
                    self.assertRegex(outputs["duration"], r"^\d+$")
                    self.assertEqual(1, sum(line.startswith("status=") for line in lines))
                    if i == 5:
                        self.assertNotEqual(0, process.returncode)
                    else:
                        self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])
                        self.assertEqual("limited_cpu_probe_failed", outputs["next_installed_version"])

    def test_zero_exit_false_outputs_are_not_successful_smokes(self):
        for number in (5, 6):
            for failure in ("version_empty", "version_wrong", "version_near_match", "help_empty", "help_wrong", "help_incomplete", "no_output",
                            "junk", "wrong_format", "wrong_codec", "wrong_size", "wrong_count", "wrong_rate",
                            "wrong_header_size", "wrong_timestamp", "truncated_header", "truncated_frame",
                            "extra_frame", "zero_frame", "oversized"):
                with self.subTest(probe=number, failure=failure):
                    process, outputs, _ = self.run_probe(number, failure)
                    self.assertEqual("failed", outputs["status"])
                    if number == 5:
                        self.assertNotEqual(0, process.returncode)
                    else:
                        self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])
                        self.assertNotEqual("0.8.1", outputs["next_installed_version"])

    def test_runtime_timeouts_propagate_as_failure_not_deferred(self):
        for number in (5, 6):
            for failure in ("version_timeout", "help_timeout", "encode_timeout"):
                with self.subTest(probe=number, failure=failure):
                    _, outputs, _ = self.run_probe(number, failure)
                    self.assertEqual("failed", outputs["status"])
                    if number == 6:
                        self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])

    def test_old_valid_output_cannot_rescue_no_output_encode(self):
        for number in (5, 6):
            with self.subTest(probe=number):
                _, outputs, _ = self.run_probe(number)
                self.assertEqual("passed", outputs["status"])
                path = self.root / ("smoke.ivf" if number == 5 else "smoke-next.ivf")
                self.assertTrue(path.is_file())
                _, outputs, _ = self.run_probe(number, "no_output")
                self.assertEqual("failed", outputs["status"])
                self.assertFalse(path.exists())

    def test_selected_release_tag_binds_the_observed_cli_version(self):
        for number in (5, 6):
            for tag in ("v0.8.2", "", "not-a-version"):
                with self.subTest(probe=number, tag=tag):
                    self.env["FIXTURE_RELEASE_TAG"] = tag
                    _, outputs, _ = self.run_probe(number)
                    self.assertEqual("failed", outputs["status"])

    def test_runtime_help_and_ivf_claims_exclude_baseline_runtime_and_decoding(self):
        self.assertIn("source/metadata-only", self.steps["test5"]["run"])
        description = self.steps["test6"]["with"]["limited_cpu_description"]
        self.assertIn("Baseline 0.3.2 remains source/metadata-only", description)
        self.assertIn("Decode, throughput, quality and long-form encoding are not validated", description)

    def test_missing_workflow_token_fails_before_any_request(self):
        for i in (5, 6):
            with self.subTest(probe=i):
                self.env["GH_TOKEN"] = ""
                _, outputs, _ = self.run_probe(i)
                self.assertEqual("failed", outputs["status"])
                self.assertFalse((self.root / "requests.jsonl").exists())

    def test_all_64_pass_fail_combinations_match_active_collector(self):
        for failures in itertools.product((False, True), repeat=6):
            with self.subTest(failures=failures):
                statuses = ["failed" if bad else "passed" for bad in failures]
                outcomes = ["failure" if bad else "success" for bad in failures[:5]] + ["success"]
                process, summary, _ = self.summarize(statuses, outcomes)
                self.assertEqual(sum(failures) == 0, process.returncode == 0)
                self.assertEqual(str(sum(failures)), summary["failed"])
                self.assertEqual(str(6 - sum(failures)), summary["passed"])
                self.assertEqual(str(sum(failures[:5])), summary["core_failed"])
                self.assertEqual("0", summary["skipped"])
                self.assertEqual("21", summary["duration"])
                self.assertEqual("failing" if any(failures[:5]) else "passing", summary["badge_status"])
                collected, payload = self.collect(summary, statuses, outcomes)
                self.assertEqual(0, collected.returncode, collected.stderr)
                self.assertEqual(statuses, [d["status"] for d in payload["tests"]["details"]])
                if any(failures[:5]):
                    with self.assertRaisesRegex(ValueError, "baseline failures require an approved baseline decision"):
                        policy.validate_publishable_result(payload)
                else:
                    self.assertEqual(summary["overall_status"], policy.validate_publishable_result(payload))
                for key in ("passed", "failed", "skipped"):
                    self.assertEqual(int(summary[key]), payload["tests"][key])

    def test_missing_or_contradictory_outputs_never_become_pass_or_skip(self):
        for i in range(6):
            for status, outcome in (("", "failure"), ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped"), ("passed", ""), ("skipped", "success"),
                                    ("", "success"), ("unknown", "success")):
                with self.subTest(i=i, status=status, outcome=outcome):
                    statuses, outcomes = ["passed"] * 6, ["success"] * 6
                    statuses[i], outcomes[i] = status, outcome
                    process, outputs, _ = self.summarize(statuses, outcomes)
                    self.assertNotEqual(0, process.returncode)
                    self.assertEqual(("5", "1", "0"), tuple(outputs[k] for k in ("passed", "failed", "skipped")))
                    self.assertEqual("failed", outputs[f"test{i + 1}_status"])

    def test_historical_403_pair_is_two_failures_and_no_skips(self):
        statuses, outcomes = ["passed"] * 4 + ["", "failed"], ["success"] * 4 + ["failure", "success"]
        process, summary, _ = self.summarize(statuses, outcomes)
        self.assertNotEqual(0, process.returncode)
        self.assertEqual(("4", "2", "0", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
        collected, payload = self.collect(summary, statuses, outcomes)
        self.assertEqual(0, collected.returncode, collected.stderr)
        with self.assertRaisesRegex(ValueError, "baseline failures require an approved baseline decision"):
            policy.validate_publishable_result(payload)
        self.assertEqual(["failed", "failed"], [d["status"] for d in payload["tests"]["details"][4:]])

    def test_collector_still_rejects_historical_skip_and_masked_core_failure(self):
        _, passing, _ = self.summarize()
        process, payload = self.collect(passing, ["passed"] * 6, ["success"] * 6, old_skip=True)
        self.assertNotEqual(0, process.returncode)
        self.assertIn("emitted skipped count contradicts test details", process.stderr)
        self.assertIsNone(payload)
        statuses = ["passed"] * 4 + ["failed", "passed"]
        _, failed, _ = self.summarize(statuses)
        process, payload = self.collect(failed, statuses, ["success"] * 6)
        self.assertNotEqual(0, process.returncode)
        self.assertIn("emitted failure counts contradict test details", process.stderr)
        self.assertIsNone(payload)

    def test_job_summary_uses_normalized_statuses(self):
        summary = next(s for s in self.job["steps"] if s["name"] == "Create test summary")
        for i in range(1, 7):
            self.assertEqual("${{ steps.summary.outputs.test%d_status || 'failed' }}" % i,
                             summary["with"][f"test{i}_status"])

    def test_terminal_probe_outputs_remain_auditor_visible(self):
        for field in ("status", "duration"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["test5"], field))


if __name__ == "__main__":
    unittest.main()
