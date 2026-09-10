"""Exercise EDOT version binding and smoke-shell failure accounting."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.github/scripts'))
from package_observation_migration_audit import _step_emits_output


class EdotDotnetWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = yaml.safe_load((ROOT / '.github/workflows/test-edot-dotnet-sdk.yml').read_text())
        cls.steps = {step.get('id'): step for step in document['jobs']['test-edot-dotnet-sdk']['steps']}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='edot-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'TestApp' / 'obj').mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.output = self.root / 'output'
        self.report = {
            'version': 1,
            'projects': [{'frameworks': [{'framework': 'net8.0', 'topLevelPackages': [
                {'id': 'Elastic.OpenTelemetry', 'requestedVersion': '1.21.0', 'resolvedVersion': '1.21.0'}
            ]}]}],
        }
        self.assets = {
            'libraries': {'Elastic.OpenTelemetry/1.21.0': {'type': 'package'}},
            'targets': {'net8.0': {'Elastic.OpenTelemetry/1.21.0': {
                'type': 'package', 'runtime': {'lib/net8.0/Elastic.OpenTelemetry.dll': {}}
            }}},
        }
        dotnet = self.bin / 'dotnet'
        dotnet.write_text('''#!/bin/bash
set -eu
if [ "$1" = list ]; then
  test "$*" = 'list package --format json --output-version 1'
  printf '%s\n' "$FIXTURE_REPORT"
  exit "${FIXTURE_REPORT_RC:-0}"
elif [ "$1" = build ]; then
  exit "${FIXTURE_BUILD_RC:-0}"
elif [ "$1" = run ]; then
  printf '%s\n' "${FIXTURE_RUNTIME_OUTPUT:-EDOT tracing smoke passed: 1 validated activity}"
  exit "${FIXTURE_RUNTIME_RC:-0}"
fi
exit 99
''')
        dotnet.chmod(0o755)
        timeout = self.bin / 'timeout'
        timeout.write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
        timeout.chmod(0o755)

    def run_step(self, step, **env):
        self.output.write_text('')
        (self.root / 'TestApp' / 'obj' / 'project.assets.json').write_text(json.dumps(self.assets))
        result = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', self.steps[step]['run']],
            cwd=self.root, env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                                'GITHUB_OUTPUT': str(self.output),
                                'EXPECTED_EDOT_VERSION': '1.21.0',
                                'FIXTURE_REPORT': json.dumps(self.report), **env},
            capture_output=True, text=True, timeout=8,
        )
        fields = dict(line.split('=', 1) for line in self.output.read_text().splitlines())
        return result, fields

    def test_version_uses_resolved_structured_package_identity(self):
        result, fields = self.run_step('version')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({'version': '1.21.0'}, fields)
        self.assertNotEqual('Elastic.OpenTelemetry', fields['version'])

    def test_changed_core_outputs_remain_visible_to_the_real_auditor(self):
        for step in ('test2', 'test5'):
            for field in ('status', 'duration'):
                with self.subTest(step=step, field=field):
                    self.assertTrue(_step_emits_output(ROOT, self.steps[step], field))

    def test_version_rejects_missing_duplicate_wrong_and_placeholder_packages(self):
        base = copy.deepcopy(self.report)
        for mutation in ('missing', 'duplicate', 'wrong-id', 'placeholder', 'framework', 'schema'):
            with self.subTest(mutation=mutation):
                self.report = copy.deepcopy(base)
                framework = self.report['projects'][0]['frameworks'][0]
                package = framework['topLevelPackages'][0]
                if mutation == 'missing':
                    framework['topLevelPackages'] = []
                elif mutation == 'duplicate':
                    framework['topLevelPackages'].append(copy.deepcopy(package))
                elif mutation == 'wrong-id':
                    package['id'] = 'Elastic.OpenTelemetry.Extensions'
                elif mutation == 'placeholder':
                    package['resolvedVersion'] = 'Elastic.OpenTelemetry'
                elif mutation == 'framework':
                    framework['framework'] = 'net9.0'
                else:
                    self.report['version'] = 2
                result, fields = self.run_step('version')
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn('version', fields)

    def test_failed_or_malformed_package_report_never_emits_version(self):
        for env in ({'FIXTURE_REPORT_RC': '9'}, {'FIXTURE_REPORT': '{'}):
            with self.subTest(env=env):
                result, fields = self.run_step('version', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn('version', fields)

    def test_version_check_binds_restored_runtime_package(self):
        result, fields = self.run_step('test2')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', fields['status'])
        self.assertGreaterEqual(int(fields['duration']), 0)

    def test_restored_wrong_version_identity_or_missing_runtime_fails(self):
        original = copy.deepcopy(self.assets)
        for mutation in ('version', 'identity', 'runtime', 'framework', 'empty'):
            with self.subTest(mutation=mutation):
                self.assets = copy.deepcopy(original)
                if mutation == 'version':
                    self.assets['libraries'] = {'Elastic.OpenTelemetry/1.20.0': {'type': 'package'}}
                elif mutation == 'identity':
                    self.assets['libraries']['Elastic.OpenTelemetry/1.21.0']['type'] = 'project'
                elif mutation == 'runtime':
                    self.assets['targets']['net8.0']['Elastic.OpenTelemetry/1.21.0']['runtime'] = {}
                elif mutation == 'framework':
                    self.assets['targets'] = {'net9.0': {}}
                else:
                    self.assets = {}
                result, fields = self.run_step('test2')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', fields['status'])
                self.assertGreaterEqual(int(fields['duration']), 0)

    def test_runtime_executes_edot_and_checks_recorded_activity(self):
        result, fields = self.run_step('test5')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', fields['status'])
        code = (self.root / 'TestApp' / 'Program.cs').read_text()
        for required in ('WithElasticDefaults(options)', 'SkipOtlpExporter = true',
                         'SkipInstrumentationAssemblyScanning = true', 'span.Recorded',
                         'processor.Count != 1', 'activity.GetTagItem("smoke.answer")',
                         'Architecture.Arm64', 'AddProcessor(processor)'):
            self.assertIn(required, code)
        self.assertNotIn('Console.WriteLine("EDOT smoke test")', code)

    def test_build_failure_runtime_failure_and_old_placeholder_output_fail(self):
        for env in ({'FIXTURE_BUILD_RC': '1'}, {'FIXTURE_RUNTIME_RC': '7'},
                    {'FIXTURE_RUNTIME_OUTPUT': 'EDOT smoke test'}):
            with self.subTest(env=env):
                result, fields = self.run_step('test5', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', fields['status'])
                self.assertGreaterEqual(int(fields['duration']), 0)


if __name__ == '__main__':
    unittest.main()
