"""Exercise result enforcement and download rejection; fixtures are not Arm evidence."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/test-bubblewrap.yml'
HELPER = ROOT / '.github/scripts/bubblewrap_smoke.sh'


class BubblewrapWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.document = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.document['jobs']['test-bubblewrap']
        self.steps = {step['id']: step for step in self.job['steps'] if 'id' in step}
        self.results = {
            'install': {'outcome': 'success', 'outputs': {'install_status': 'success'}},
            'version': {'outcome': 'success', 'outputs': {'version': '0.13.0'}},
            'cleanup': {'outcome': 'success', 'outputs': {}},
        }
        for number in range(1, 7):
            self.results[f'test{number}'] = {
                'outcome': 'success', 'outputs': {'status': 'passed', 'duration': '1'},
            }
        self.results['test6']['outputs']['decision'] = 'next_install_validated'

    def summary(self, results=None):
        with tempfile.TemporaryDirectory(prefix='bubblewrap-contract-') as directory:
            output = Path(directory) / 'output'
            summary = Path(directory) / 'summary'
            output.touch()
            process = subprocess.run(
                ['/bin/bash', '-e', '-o', 'pipefail', '-c', self.steps['summary']['run']],
                cwd=ROOT,
                env={**os.environ, 'STEP_RESULTS': json.dumps(results or self.results),
                     'GITHUB_OUTPUT': str(output), 'GITHUB_STEP_SUMMARY': str(summary)},
                capture_output=True, text=True, timeout=10,
            )
            pairs = [line.split('=', 1) for line in output.read_text().splitlines()]
            self.assertEqual(len(pairs), len(dict(pairs)), 'Duplicate result keys')
            return process, dict(pairs)

    def test_six_observed_passes_succeed(self):
        process, result = self.summary()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result['passed'], '6')
        self.assertEqual(result['overall_status'], 'success')

    def test_failed_step_cannot_claim_passed(self):
        self.results['test3']['outcome'] = 'failure'
        process, result = self.summary()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['core_failed'], '1')
        self.assertEqual(result['badge_status'], 'failing')

    def test_missing_test_result_fails(self):
        del self.results['test4']
        process, result = self.summary()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['core_failed'], '1')

    def test_unapproved_regression_decision_fails(self):
        self.results['test6']['outputs']['decision'] = 'pretend_upgrade_passed'
        process, result = self.summary()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['overall_status'], 'failure')

    def test_baseline_failure_prevents_successful_skip(self):
        self.results['test2']['outcome'] = 'failure'
        self.results['test2']['outputs']['status'] = 'failed'
        self.results['test6']['outputs'].update(status='skipped', decision='baseline_failed')
        process, result = self.summary()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((result['failed'], result['skipped']), ('1', '1'))

    def test_failed_version_or_install_is_not_passing(self):
        for step in ('version', 'install'):
            with self.subTest(step=step):
                results = copy.deepcopy(self.results)
                results[step]['outcome'] = 'failure'
                process, result = self.summary(results)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(result['badge_status'], 'failing')

    def test_failed_policy_restoration_is_not_passing(self):
        self.results['cleanup']['outcome'] = 'failure'
        process, result = self.summary()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['overall_status'], 'failure')
        self.assertEqual(result['badge_status'], 'failing')

    def test_no_version_fallback_is_invented(self):
        self.assertIn('test "$("$BWRAP_BINARY" --version)"', self.steps['version']['run'])
        self.assertNotIn('|| true', self.steps['version']['run'])

    def test_job_outputs_fail_closed_and_use_the_linux_dashboard_route(self):
        outputs = self.job['outputs']
        self.assertIn("|| 'not_installed'", outputs['package_version'])
        self.assertIn("|| 'failed'", outputs['regression_status'])
        self.assertIn("|| 'not_installed'", outputs['regression_current_version'])
        self.assertIn("|| 'not_checked'", outputs['regression_latest_version'])
        self.assertIn(
            'dashboard_link=/linux/opensource_packages/bubblewrap',
            self.steps['metadata']['run'],
        )

    def test_every_dispatched_probe_function_exists(self):
        source = HELPER.read_text()
        for mode in ('execution', 'readonly', 'namespaces'):
            self.assertIn(f'{mode}_probe() (', source)
        self.assertEqual(source.count("trap 'rm -rf -- \"$work\"' EXIT"), 3)

    def run_test6(self, release_json=None, curl_fails=False):
        with tempfile.TemporaryDirectory(prefix='bubblewrap-latest-') as directory:
            root = Path(directory)
            tools = root / 'bin'
            tools.mkdir()
            curl = tools / 'curl'
            curl.write_text('''#!/bin/sh
if test "${FIXTURE_CURL_FAIL:-0}" = 1; then exit 22; fi
output=
while test "$#" -gt 0; do
  if test "$1" = --output; then shift; output=$1; fi
  shift
done
test -n "$output"
printf '%s' "$FIXTURE_RELEASE_JSON" > "$output"
''')
            curl.chmod(0o755)
            output = root / 'output'
            output.touch()
            core_outcomes = {
                f'test{number}': {
                    'outcome': 'success',
                    'outputs': {'status': 'passed'},
                }
                for number in range(1, 6)
            }
            process = subprocess.run(
                ['/bin/bash', '-e', '-o', 'pipefail', '-c', self.steps['test6']['run']],
                cwd=ROOT,
                env={
                    **os.environ,
                    'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                    'CORE_OUTCOMES': json.dumps(core_outcomes),
                    'BASELINE_VERSION': '0.13.0',
                    'CANDIDATE_VERSION': '0.13.1',
                    'CANDIDATE_SHA256': '0' * 64,
                    'FIXTURE_CURL_FAIL': '1' if curl_fails else '0',
                    'FIXTURE_RELEASE_JSON': release_json or '',
                    'GH_TOKEN': 'fixture-token',
                    'GITHUB_OUTPUT': str(output),
                    'RUNNER_TEMP': str(root),
                },
                capture_output=True, text=True, timeout=10,
            )
            pairs = [line.split('=', 1) for line in output.read_text().splitlines()]
            self.assertEqual(len(pairs), len(dict(pairs)), 'Duplicate Test 6 output keys')
            return process, dict(pairs)

    def test_authoritative_latest_release_mismatch_is_deferred(self):
        process, result = self.run_test6(json.dumps({
            'tag_name': 'v0.13.2', 'draft': False, 'prerelease': False,
        }))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result['latest_version'], '0.13.2')
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['decision'], 'upgrade_candidate_available')
        self.assertEqual(result['next_installed_version'], 'not_installed')

    def test_latest_release_lookup_failure_fails_closed(self):
        process, result = self.run_test6(curl_fails=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['decision'], 'next_lookup_failed')

    def test_invalid_latest_release_metadata_fails_closed(self):
        process, result = self.run_test6(json.dumps({
            'tag_name': 'v0.13.2-rc1', 'draft': False, 'prerelease': True,
        }))
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['decision'], 'next_lookup_failed')

    def test_cleanup_restores_original_user_namespace_policy(self):
        with tempfile.TemporaryDirectory(prefix='bubblewrap-sysctl-') as directory:
            root = Path(directory)
            tools = root / 'bin'
            tools.mkdir()
            state = root / 'state'
            state.write_text('0\n')
            sysctl = tools / 'sysctl'
            sysctl.write_text('''#!/bin/sh
case "$1" in
  -n) cat "$SYSCTL_STATE" ;;
  -w) printf '%s\n' "${2#*=}" > "$SYSCTL_STATE"; printf '%s\n' "$2" ;;
  *) exit 2 ;;
esac
''')
            sysctl.chmod(0o755)
            sudo = tools / 'sudo'
            sudo.write_text('#!/bin/sh\nexec "$@"\n')
            sudo.chmod(0o755)
            process = subprocess.run(
                ['/bin/bash', '-e', '-o', 'pipefail', '-c', self.steps['cleanup']['run']],
                cwd=ROOT,
                env={
                    **os.environ,
                    'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                    'APPARMOR_USERNS_ORIGINAL': '1',
                    'SYSCTL_STATE': str(state),
                },
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(state.read_text(), '1\n')
        self.assertIn('APPARMOR_USERNS_ORIGINAL=', self.steps['install']['run'])

    def test_namespace_reads_must_succeed_and_show_distinct_namespaces(self):
        with tempfile.TemporaryDirectory(prefix='bubblewrap-namespace-fixture-') as directory:
            root = Path(directory)
            tools = root / 'bin'
            tools.mkdir()
            fixtures = {
                'uname': '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; *) exit 2;; esac\n',
                'timeout': '#!/bin/sh\nshift 2\nexec "$@"\n',
                'bwrap': '#!/bin/sh\nwhile test "$#" -gt 0; do\nif test "$1" = /bin/sh; then export INSIDE_SANDBOX=1; exec "$@"; fi\nshift\ndone\nexit 2\n',
                'readlink': '#!/bin/sh\nif test "${INSIDE_SANDBOX:-}" = 1; then\ncase "$FIXTURE_MODE" in failed) exit 1;; empty) exit 0;; distinct) echo "$1-distinct"; exit 0;; esac\nfi\nprintf "%s-host\\n" "$1"\n',
            }
            for name, content in fixtures.items():
                path = tools / name
                path.write_text(content)
                path.chmod(0o755)
            for mode in ('failed', 'empty', 'unchanged', 'distinct'):
                with self.subTest(mode=mode):
                    process = subprocess.run(
                        ['/bin/bash', str(HELPER), 'namespaces', str(tools / 'bwrap')],
                        env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                             'FIXTURE_MODE': mode, 'RUNNER_TEMP': str(root)},
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(process.returncode == 0, mode == 'distinct', process.stderr)
                    self.assertEqual(list(root.glob('bwrap-namespaces.*')), [])

    def test_bad_archive_hash_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory(prefix='bubblewrap-download-') as directory:
            root = Path(directory)
            tools = root / 'bin'
            tools.mkdir()
            uname = tools / 'uname'
            uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; *) exit 2;; esac\n')
            uname.chmod(0o755)
            curl = tools / 'curl'
            curl.write_text('#!/bin/sh\nwhile test "$#" -gt 0; do\nif test "$1" = --output; then shift; printf corrupt > "$1"; exit 0; fi\nshift\ndone\nexit 2\n')
            curl.chmod(0o755)
            sentinel = root / 'extraction-started'
            tar = tools / 'tar'
            tar.write_text('#!/bin/sh\nprintf started > "$EXTRACTION_SENTINEL"\nexit 97\n')
            tar.chmod(0o755)
            # Exercise ordering portably; macOS sha256sum lacks GNU --strict.
            checksum = tools / 'sha256sum'
            checksum.write_text('''#!/usr/bin/env python3
import hashlib
from pathlib import Path
import sys
assert sys.argv[1:] == ["--check", "--strict"]
expected, filename = sys.stdin.read().strip().split(None, 1)
valid = hashlib.sha256(Path(filename).read_bytes()).hexdigest() == expected
print(filename + (": OK" if valid else ": FAILED"))
sys.exit(0 if valid else 1)
''')
            checksum.chmod(0o755)
            process = subprocess.run(
                ['/bin/bash', str(HELPER), 'build', '0.13.0', 'a' * 64, str(root / 'release')],
                env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                     'EXTRACTION_SENTINEL': str(sentinel)},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('FAILED', process.stdout + process.stderr)
            self.assertFalse(sentinel.exists(), 'Unverified archive reached extraction')
            self.assertFalse((root / 'release/build').exists())


if __name__ == '__main__':
    unittest.main()
