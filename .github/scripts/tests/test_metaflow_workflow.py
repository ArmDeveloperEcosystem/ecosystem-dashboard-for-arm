from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
JOB = yaml.safe_load((ROOT / '.github/workflows/test-metaflow.yml').read_text())['jobs']['test-metaflow']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class MetaflowWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='metaflow-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / '.venv-current/bin'
        self.bin.mkdir(parents=True)
        (self.bin / 'activate').write_text('export PATH="' + str(self.bin) + ':$PATH"\n')
        (self.bin / 'python').symlink_to(sys.executable)
        self.env = dict(os.environ, **JOB['env'], GITHUB_OUTPUT=str(self.root / 'outputs'))

    def run_step(self, step, values=None):
        values = values or {}
        def expression(match):
            terms = match[1].split('||')
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
        script = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS[step]['run'])
        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root, env=self.env, text=True, capture_output=True)
        return result, dict(line.split('=', 1) for line in output.read_text().splitlines())

    def test_import_failure_is_visible_and_cannot_fall_back_to_metadata(self):
        (self.root / 'metaflow.py').write_text('raise ModuleNotFoundError("No module named pkg_resources")\n')
        result, outputs = self.run_step('test5')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('pkg_resources', result.stderr)
        self.assertEqual('failed', outputs['status'])

    def test_public_api_requires_expected_version_and_symbols(self):
        for version, api in (('2.0.0', True), ('2.0.1', True), ('2.0.0', False)):
            with self.subTest(version=version, api=api):
                source = f'__version__ = {version!r}\n'
                if api:
                    source += 'FlowSpec = Parameter = step = lambda: None\n'
                (self.root / 'metaflow.py').write_text(source)
                result, outputs = self.run_step('test5')
                passed = version == '2.0.0' and api
                self.assertEqual(passed, result.returncode == 0, result.stderr)
                self.assertEqual('passed' if passed else 'failed', outputs['status'])
                for cached in (self.root / '__pycache__').glob('*'):
                    cached.unlink()

    def test_both_environments_supply_pkg_resources_and_candidate_import_is_required(self):
        for step in ('install', 'test6'):
            self.assertIn('"setuptools==80.9.0"', STEPS[step]['run'])
        self.assertIn("&& python -c 'from metaflow import FlowSpec, Parameter, step'", STEPS['test6']['run'])

    def test_candidate_rejects_failed_install_wrong_version_and_failed_import(self):
        (self.bin / 'python').unlink()
        (self.bin / 'python').write_text('''#!/bin/bash
set -euo pipefail
case "$*" in
  *textwrap*) echo 2.0.1 ;;
  *im.version*) echo "${CANDIDATE_VERSION:-2.0.1}" ;;
  *"from metaflow import"*) test "${IMPORT_FAIL:-0}" = 0 ;;
  "-m venv .venv-next") mkdir -p .venv-next/bin; touch .venv-next/bin/activate ;;
  "-m pip install metaflow==2.0.1") test "${INSTALL_FAIL:-0}" = 0 ;;
  "-m pip install --upgrade"*) ;;
  *) exit 2 ;;
esac
''')
        (self.bin / 'python').chmod(0o755)
        self.env['CURRENT_VERSION'] = '2.0.0'
        for install_fail, version, import_fail in (('0', '2.0.1', '0'), ('1', '2.0.1', '0'), ('0', '2.0.0', '0'), ('0', '2.0.1', '1')):
            with self.subTest(install_fail=install_fail, version=version, import_fail=import_fail):
                self.env.update(INSTALL_FAIL=install_fail, CANDIDATE_VERSION=version, IMPORT_FAIL=import_fail)
                result, outputs = self.run_step('test6')
                passed = install_fail == import_fail == '0' and version == '2.0.1'
                self.assertEqual(passed, result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual('passed' if passed else 'failed', outputs['status'])
                self.assertEqual('next_install_validated' if passed else 'next_install_failed', outputs['decision'])

    def test_summary_rejects_missing_core_or_candidate_results(self):
        values = {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'))}
        for index in (0, 5, 6):
            case = dict(values)
            if index:
                case[f'steps.test{index}.outputs.status'] = ''
                case[f'steps.test{index}.outcome'] = 'failure'
            result, outputs = self.run_step('summary', case)
            self.assertEqual(index == 0, result.returncode == 0)
            self.assertEqual('1' if index else '0', outputs['failed'])
            self.assertEqual('1' if index == 5 else '0', outputs['core_failed'])


if __name__ == '__main__':
    unittest.main()
