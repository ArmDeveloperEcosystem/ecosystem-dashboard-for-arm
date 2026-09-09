"""Exercise the two source-build workflows' real scripts with failing fixtures."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
SLUGS = ("opennow", "playit")
SHA2_CHECKSUM = "55deaec60f81eefe3cce0dc50bda92d6d8e88f2a27df7c5033b42afeb1ed2676"


def job(slug):
    path = ROOT / ".github/workflows" / f"test-{slug}.yml"
    return next(iter(yaml.safe_load(path.read_text())["jobs"].values()))


def step(slug, ident):
    return next(item for item in job(slug)["steps"] if item.get("id") == ident)


def render(script, values):
    def replace(match):
        for part in match[1].split("||"):
            part = part.strip()
            value = part[1:-1] if part.startswith("'") else values.get(part, "")
            if value:
                return value
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)


def fixture(root, slug):
    source = root / "baseline-src"
    source.mkdir()
    if slug == "opennow":
        (source / "package.json").write_text(json.dumps({
            "name": "opennow", "version": "0.0.21", "scripts": {"build": "tsc && vite build"}}))
        (source / "bun.lock").write_text("frozen fixture\n")
        (source / "src-tauri").mkdir()
        (source / "src-tauri/tauri.conf.json").write_text('{"version":"0.0.21"}')
        (source / "src-tauri/Cargo.toml").write_text('[package]\nname="opennow"\nversion="0.0.21"\n')
    else:
        for package in ("agent_cli", "agent_common"):
            (source / "packages" / package).mkdir(parents=True)
        (source / "packages/agent_cli/Cargo.toml").write_text('[package]\nname="agent"\nversion="0.9.1"\n')
        (source / "packages/agent_common/Cargo.toml").write_text(
            '[dependencies]\nsha2 = { verion = "0.10.2", optional = true }\n')
        (source / "Cargo.lock").write_text(
            'version=3\n[[package]]\nname="sha2"\nversion="0.10.2"\n'
            f'checksum="{SHA2_CHECKSUM}"\n')
    return source


class OpenNowPlayitWorkflowTests(unittest.TestCase):
    def run_script(self, script, slug, mode="ok", stubs=None, alter=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root, slug)
            if alter:
                alter(source)
            binary = root / "bin"
            binary.mkdir()
            for name, body in (stubs or {}).items():
                path = binary / name
                path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
                path.chmod(0o755)
            output = root / "output"
            output.touch()
            env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}", MODE=mode,
                       GITHUB_OUTPUT=str(output), FIXTURE_ROOT=str(root),
                       BASELINE_VERSION="0.0.21" if slug == "opennow" else "0.9.1")
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=20)
            fields = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
            return result, fields

    def summary(self, slug, overrides=None):
        values = {}
        for number in range(1, 7):
            values[f"steps.test{number}.outputs.status"] = "passed"
            values[f"steps.test{number}.outcome"] = "success"
            values[f"steps.test{number}.outputs.duration"] = "1"
        values.update(overrides or {})
        return self.run_script(render(step(slug, "summary")["run"], values), slug)

    def test_summary_all_pass(self):
        for slug in SLUGS:
            result, fields = self.summary(slug)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((fields["passed"], fields["failed"], fields["duration"]), ("6", "0", "6"))

    def test_summary_missing_failed_or_skipped_core_fails(self):
        for slug in SLUGS:
            for number in range(1, 6):
                for status in ("", "failed", "skipped"):
                    result, fields = self.summary(slug, {f"steps.test{number}.outputs.status": status})
                    self.assertNotEqual(result.returncode, 0, (slug, number, status))
                    self.assertEqual((fields["core_failed"], fields["skipped"]), ("1", "0"))

    def test_passed_output_never_overrides_bad_outcome(self):
        for slug in SLUGS:
            for number in range(1, 7):
                for outcome in ("failure", "cancelled", "skipped", ""):
                    result, fields = self.summary(slug, {f"steps.test{number}.outcome": outcome})
                    self.assertNotEqual(result.returncode, 0, (slug, number, outcome))
                    self.assertEqual(fields["failed"], "1")

    def test_only_successful_no_newer_regression_skip_is_approved(self):
        for slug in SLUGS:
            for decision, outcome, valid in (("no_newer_stable_available", "success", True),
                                             ("no_newer_stable_available", "failure", False),
                                             ("runtime_validation_not_automated", "success", False),
                                             ("not_applicable_package_manager", "success", False)):
                result, fields = self.summary(slug, {"steps.test6.outputs.status": "skipped",
                    "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
                self.assertEqual(result.returncode == 0, valid)
                self.assertEqual(fields["skipped"], "1" if valid else "0")

    def test_baseline_outputs_are_explicit(self):
        for slug in SLUGS:
            for number in range(1, 6):
                script = step(slug, f"test{number}")["run"]
                self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', script.splitlines()[:5])
                self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', script.splitlines()[:6])
                self.assertIn('echo "status=passed" >> "$GITHUB_OUTPUT"', script)
                self.assertIn('echo "duration=$((END_TIME - START_TIME))" >> "$GITHUB_OUTPUT"', script)

    def test_exact_tag_install_has_no_default_branch_fallback(self):
        for slug in SLUGS:
            script = step(slug, "install")["run"]
            self.assertIn('RESOLVED_TAG="v$BASELINE_VERSION"', script)
            self.assertIn('describe --tags --exact-match', script)
            self.assertNotIn("default_branch", script)
            self.assertNotIn("|| true", script)

    def test_versions_come_from_agreeing_source_manifests(self):
        for slug in SLUGS:
            result, fields = self.run_script(step(slug, "version")["run"], slug)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fields["version"], job(slug)["env"]["BASELINE_VERSION"])
        paths = ("package.json", "src-tauri/tauri.conf.json", "src-tauri/Cargo.toml")
        for path in paths:
            def alter(source):
                target = source / path
                target.write_text(target.read_text().replace("0.0.21", "9.9.9"))
            result, fields = self.run_script(step("opennow", "version")["run"], "opennow", alter=alter)
            self.assertNotEqual(result.returncode, 0, path)
            self.assertNotIn("version", fields)
        def alter_playit(source):
            path = source / "packages/agent_cli/Cargo.toml"
            path.write_text(path.read_text().replace("0.9.1", "9.9.9"))
        result, fields = self.run_script(step("playit", "version")["run"], "playit", alter=alter_playit)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("version", fields)

    def opennow_build(self, mode):
        stubs = {
            "curl": 'test "$6" = https://github.com/oven-sh/bun/releases/download/bun-v1.4.2/bun-linux-aarch64.zip\n',
            "sha256sum": 'read -r digest path\ntest "$digest" = 54328bbc2d9c8e0c9f892c544d66c57a83b84139e34909e5ee81758f1ac8fda7\ntest "$MODE" != wrong_digest\n',
            "unzip": 'mkdir -p "$4/bun-linux-aarch64"\ncp "$FIXTURE_ROOT/bin/bun" "$4/bun-linux-aarch64/bun"\n',
            "file": 'echo "ELF 64-bit LSB executable, ARM aarch64"\n',
            "git": 'test "$MODE" != changed_source\n',
            "timeout": 'shift\nexec "$@"\n',
            "bun": '''case "$1" in
  --version) if [ "$MODE" = wrong_version ]; then echo 1.4.3; else echo 1.4.2; fi;;
  install) test "$*" = 'install --frozen-lockfile --ignore-scripts'; test "$MODE" != install_failure;;
  run)
    test "$*" = 'run --bun build'
    test "$TAURI_ENV_PLATFORM" = linux
    test -z "${TAURI_ENV_DEBUG+x}"
    test "$MODE" != build_failure
    mkdir -p dist/assets
    if [ "$MODE" != missing_html ]; then echo html > dist/index.html; fi
    if [ "$MODE" != missing_js ]; then echo javascript > dist/assets/main.js; fi
    ;;
  *) exit 1;;
esac
''',
        }
        script = render(step("opennow", "test5")["run"], {"steps.install.outputs.install_mode": "github_source"})
        return self.run_script(script, "opennow", mode, stubs)

    def test_opennow_frozen_production_build(self):
        result, fields = self.opennow_build("ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")

    def test_opennow_failures_and_missing_artifacts_never_pass(self):
        for mode in ("wrong_digest", "wrong_version", "install_failure", "build_failure", "missing_html", "missing_js", "changed_source"):
            result, fields = self.opennow_build(mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(fields["status"], "failed")

    def playit_build(self, mode="ok", alter=None):
        stubs = {
            "file": 'if [ "$MODE" = wrong_arch ]; then echo "ELF 64-bit x86-64"; else echo "ELF 64-bit ARM aarch64"; fi\n',
            "git": 'test "$MODE" != changed_lock\n',
            "rustc": "echo rustc\n",
            "timeout": 'shift\nexec "$@"\n',
            "agent": '''case "$1" in
  --help) test "$MODE" != help_failure; echo '--config-file';;
  --version) if [ "$MODE" = wrong_version ]; then echo 'agent 9.9.9'; else echo 'agent 0.9.1'; fi;;
  *) exit 99;;
esac
''',
            "cargo": '''case "$1" in
  --version) echo cargo;;
  metadata) test "$*" = 'metadata --locked --format-version 1 --no-deps';;
  build)
    test "$*" = 'build --locked --workspace --bins -j 2'
    test "$MODE" != build_failure
    mkdir -p target/debug
    cp "$FIXTURE_ROOT/bin/agent" target/debug/agent
    ;;
  test)
    test "$*" = 'test --locked --offline -p playit-agent-common --test arm_invalid_secret -j 2'
    grep -Fq 'config.valid_secret_key()' packages/agent_common/tests/arm_invalid_secret.rs
    test "$MODE" != invalid_token_accepted
    ;;
  *) exit 99;;
esac
''',
        }
        script = render(step("playit", "test5")["run"], {"steps.install.outputs.install_mode": "github_source"})
        return self.run_script(script, "playit", mode, stubs, alter)

    def test_playit_locked_build_and_real_offline_validator_contract(self):
        result, fields = self.playit_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")

    def test_playit_compile_elf_cli_lock_and_token_failures_are_not_green(self):
        for mode in ("build_failure", "wrong_arch", "help_failure", "wrong_version", "changed_lock", "invalid_token_accepted"):
            result, fields = self.playit_build(mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(fields["status"], "failed")

    def test_playit_spelling_repair_refuses_different_dependency_or_lock(self):
        for relative, old, new in (("packages/agent_common/Cargo.toml", "0.10.2", "0.10.3"),
                                   ("packages/agent_common/Cargo.toml", "verion", "version"),
                                   ("Cargo.lock", "0.10.2", "0.10.3"),
                                   ("Cargo.lock", SHA2_CHECKSUM, "0" * 64)):
            def alter(source):
                path = source / relative
                path.write_text(path.read_text().replace(old, new))
            result, fields = self.playit_build(alter=alter)
            self.assertNotEqual(result.returncode, 0, relative)
            self.assertEqual(fields["status"], "failed")

    def test_regression_preserves_mandatory_builds_and_real_architecture(self):
        opennow = step("opennow", "test6")["with"]["limited_cpu_probe"]
        self.assertIn("npm run typecheck", opennow)
        self.assertIn("npm run build", opennow)
        self.assertNotIn("--if-present", opennow)
        self.assertEqual(step("opennow", "test6")["with"]["defer_on_limited_cpu_probe_failure"], "false")
        playit = step("playit", "test6")["with"]["limited_cpu_probe"]
        self.assertIn("cargo build --locked --workspace --bins -j 2", playit)
        self.assertIn("ELF 64-bit.*ARM aarch64", playit)
        self.assertIn('"$BIN" --help', playit)
        self.assertIn('--secret_path "$PWD/playit-unused-secret" version', playit)
        self.assertIn('test "$(cat playit-next-version.txt)" = 0.17.1', playit)
        self.assertNotIn('"$BIN" --version', playit)
        self.assertNotIn("||", playit)

    def test_opennow_source_build_never_publishes_an_installed_runtime_version(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/test-opennow.yml").read_text())
        published = job("opennow")["outputs"]
        summary = next(item["with"] for item in job("opennow")["steps"]
                       if item.get("uses") == "./.github/actions/write-package-job-summary")
        trigger = workflow.get("on", workflow.get(True))
        self.assertEqual(trigger["workflow_call"]["outputs"]["regression_next_installed_version"]["value"],
                         "${{ jobs.test-opennow.outputs.regression_next_installed_version }}")
        for raw_version in ("1.3.5", "0.3.4", "", "unknown"):
            values = {"steps.test6.outputs.next_installed_version": raw_version,
                      "steps.test6.outputs.latest_version": "1.3.5"}
            for binding in (published, summary):
                self.assertEqual(render(binding["regression_next_installed_version"], values), "not_installed")
                self.assertEqual(render(binding["regression_latest_version"], values), "1.3.5")
        description = step("opennow", "test6")["with"]["limited_cpu_description"]
        self.assertIn("frontend typecheck and production build", description)
        self.assertIn("no versioned OpenNOW runtime was installed or launched", description)
        self.assertEqual(render(job("playit")["outputs"]["regression_next_installed_version"],
                                {"steps.test6.outputs.next_installed_version": "0.17.1"}), "0.17.1")

    def test_playit_next_version_subcommand_must_succeed_and_match(self):
        probe = step("playit", "test6")["with"]["limited_cpu_probe"]
        script = probe[probe.index("env -u PLAYIT_SECRET"):]
        script = 'BIN="$FIXTURE_ROOT/bin/agent"\n' + script
        stubs = {"agent": '''test "$1" = --stdout
test "$2" = --secret_path
test "$4" = version
test -z "${PLAYIT_SECRET+x}"
test -z "${PLAYIT_SECRET_PATH+x}"
if [ "$MODE" = failed ]; then echo 0.17.1; exit 1; fi
if [ "$MODE" = wrong ]; then echo 0.17.2; else echo 0.17.1; fi
'''}
        for mode in ("ok", "failed", "wrong"):
            result, _ = self.run_script(script, "playit", mode, stubs)
            self.assertEqual(result.returncode == 0, mode == "ok", (mode, result.stderr))


if __name__ == "__main__":
    unittest.main()
