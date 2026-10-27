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

    def test_no_version_fallback_is_invented(self):
        self.assertIn('test "$("$BWRAP_BINARY" --version)"', self.steps['version']['run'])
        self.assertNotIn('|| true', self.steps['version']['run'])

    def test_every_dispatched_probe_function_exists(self):
        source = HELPER.read_text()
        for mode in ('execution', 'readonly', 'namespaces'):
            self.assertIn(f'{mode}_probe() {{', source)

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
            process = subprocess.run(
                ['/bin/bash', str(HELPER), 'build', '0.13.0', 'a' * 64, str(root / 'release')],
                env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH']},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse((root / 'release/build').exists())


if __name__ == '__main__':
    unittest.main()
