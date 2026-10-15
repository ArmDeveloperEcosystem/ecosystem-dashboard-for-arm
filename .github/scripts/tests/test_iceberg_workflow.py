from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[3]
JOB = yaml.safe_load((ROOT / '.github/workflows/test-iceberg.yml').read_text())['jobs']['test-iceberg']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class IcebergWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='iceberg-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.root / 'baseline-src').mkdir()
        self.env = dict(os.environ, **JOB['env'], RUNNER_TEMP=str(self.root), GITHUB_OUTPUT=str(self.root / 'outputs'))
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        self.stub('uname', 'echo "${TEST_ARCH:-aarch64}"')
        self.stub('timeout', 'shift; exec "$@"')
        self.stub('mvn', 'test "${FAIL_STAGE:-}" != resolve; echo dependencies > classpath.txt')
        self.stub('javac', 'test "${FAIL_STAGE:-}" != compile')
        self.stub('java', 'test "${FAIL_STAGE:-}" != runtime')
        self.stub('git', '''
test "$1" = clone
test "${FAIL_STAGE:-}" != clone
mkdir -p next-src/core
echo Iceberg > next-src/README.md
touch next-src/build.gradle
if [ "${OMIT_SETTINGS:-0}" = 0 ]; then
  echo "include 'iceberg-core'" > next-src/settings.gradle
fi
''')

    def stub(self, name, body):
        target = self.bin / name
        target.write_text('#!/bin/bash\nset -euo pipefail\n' + body + '\n')
        target.chmod(0o755)

    def run_step(self, step, values=None, **env):
        values = values or {}
        def expression(match):
            terms = match[1].split('||')
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
        script = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS[step]['run'])
        return self.run_script(script, **env)

    def run_script(self, script, **env):
        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root, env=dict(self.env, **env), text=True, capture_output=True)
        return result, dict(line.split('=', 1) for line in output.read_text().splitlines())

    def run_candidate(self, inputs=None, **env):
        action = yaml.safe_load((ROOT / '.github/actions/generic-source-regression-check/action.yml').read_text())
        values = {key: value.get('default', '') for key, value in action['inputs'].items()}
        values.update(STEPS['test6']['with'])
        values.update(baseline_version=JOB['env']['BASELINE_VERSION'], github_repo=JOB['env']['GITHUB_REPO'], lane_kind=JOB['env']['LANE_KIND'])
        values.update(inputs or {})
        composite = action['runs']['steps'][0]
        def render(value):
            return re.sub(r'\$\{\{\s*inputs\.(\w+)\s*\}\}', lambda match: values[match[1]], value)
        env = {**{key: render(value) for key, value in composite['env'].items()}, **env}
        return self.run_script(render(composite['run']), **env)

    def test_smoke_propagates_dependency_compile_and_runtime_failures(self):
        for stage in ('resolve', 'compile', 'runtime', ''):
            with self.subTest(stage=stage):
                result, outputs = self.run_step('test5', {'steps.install.outputs.install_mode': 'github_source'}, FAIL_STAGE=stage)
                self.assertEqual(not stage, result.returncode == 0, result.stderr)
                self.assertEqual('failed' if stage else 'passed', outputs['status'])
                self.assertFalse(list(self.root.glob('iceberg-smoke.*')))

    def test_smoke_rejects_non_arm_host(self):
        result, outputs = self.run_step('test5', TEST_ARCH='x86_64')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('failed', outputs['status'])

    def test_candidate_failure_propagates_through_composite_and_summary(self):
        for stage in ('resolve', 'compile', 'runtime', ''):
            with self.subTest(stage=stage):
                result, outputs = self.run_candidate(FAIL_STAGE=stage)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('failed' if stage else 'passed', outputs['status'])
                self.assertEqual('limited_cpu_smoke_failed' if stage else 'limited_cpu_smoke_validated', outputs['decision'])
                self.assertEqual('limited_cpu_probe_failed' if stage else '1.10.1', outputs['next_installed_version'])
                self.assertFalse(list(self.root.glob('iceberg-smoke.*')))
                values = {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'))}
                values['steps.test6.outputs.status'] = outputs['status']
                summary, counts = self.run_step('summary', values)
                self.assertEqual(not stage, summary.returncode == 0)
                self.assertEqual('1' if stage else '0', counts['failed'])
                self.assertEqual('0', counts['core_failed'])

    def test_candidate_version_is_bound_to_maven_and_runtime_without_changing_baseline(self):
        self.stub('mvn', 'cp pom.xml "$SMOKE_POM"; echo dependencies > classpath.txt')
        self.stub('java', 'printf "%s\\n" "$@" > "$JAVA_ARGS"')
        result, outputs = self.run_candidate(SMOKE_POM=str(self.root / 'candidate-pom.xml'), JAVA_ARGS=str(self.root / 'java-args'))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', outputs['status'])
        pom = ET.parse(self.root / 'candidate-pom.xml')
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        dependencies = {item.find('m:artifactId', ns).text: item.find('m:version', ns).text for item in pom.findall('m:dependencies/m:dependency', ns)}
        self.assertEqual('1.10.1', dependencies['iceberg-core'])
        self.assertEqual(['IcebergSmoke', '1.10.1'], (self.root / 'java-args').read_text().splitlines()[-2:])
        self.assertEqual('1.1.0', outputs['current_version'])
        self.assertEqual('1.1.0', self.env['BASELINE_VERSION'])

    def test_candidate_rejects_wrong_tag_and_missing_source_evidence(self):
        for inputs, env in (({'candidate_tag_override': 'apache-iceberg-1.1.0'}, {}), ({}, {'OMIT_SETTINGS': '1'})):
            with self.subTest(inputs=inputs, env=env):
                result, outputs = self.run_candidate(inputs, **env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('failed', outputs['status'])
                self.assertEqual('limited_cpu_smoke_failed', outputs['decision'])

    def test_summary_fails_closed_and_preserves_six_test_contract(self):
        values = {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outputs.duration', '1'), ('outcome', 'success'))}
        result, outputs = self.run_step('summary', values)
        self.assertEqual(0, result.returncode)
        self.assertEqual(('6', '0', '0', '6'), tuple(outputs[key] for key in ('passed', 'failed', 'core_failed', 'duration')))
        for status, outcome in (('', 'failure'), ('skipped', 'skipped'), ('passed', 'failure'), ('failed', 'success')):
            with self.subTest(status=status, outcome=outcome):
                result, outputs = self.run_step('summary', dict(values, **{'steps.test5.outputs.status': status, 'steps.test5.outcome': outcome}))
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(('5', '1', '1', 'failure'), tuple(outputs[key] for key in ('passed', 'failed', 'core_failed', 'overall_status')))
        result, outputs = self.run_step('summary', dict(values, **{'steps.test6.outputs.status': 'failed'}))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('0', outputs['core_failed'])


if __name__ == '__main__':
    unittest.main()
