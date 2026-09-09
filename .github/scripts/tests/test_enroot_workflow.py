from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
JOB = yaml.safe_load((ROOT / '.github/workflows/test-enroot.yml').read_text())['jobs']['test-enroot']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class EnrootWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='enroot-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.root / 'baseline-src').mkdir()
        self.env = dict(os.environ, **JOB['env'], RUNNER_TEMP=str(self.root), GITHUB_OUTPUT=str(self.root / 'outputs'))
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        self.stub('uname', 'echo "${TEST_ARCH:-aarch64}"')
        self.stub('timeout', 'shift; exec "$@"')
        self.stub('file', 'echo "${TEST_ELF:-ELF 64-bit ARM aarch64}"')
        self.stub('git', '''
case "$1" in
  clone) test "${FAIL_STAGE:-}" != clone; mkdir -p next-src; touch next-src/README.md ;;
  describe)
    if [ "$SOURCE_DIR" = next-src ]; then version=4.2.1; else version=2.1.0; fi
    echo "${TEST_TAG:-v$version}" ;;
  rev-parse) echo source-commit ;;
  config) exit 0 ;;
  submodule)
    if [ "$2" = update ]; then test "${FAIL_STAGE:-}" != fetch; fi
    if [ "$2" = foreach ]; then test "${FAIL_STAGE:-}" != pin; fi ;;
  *) exit 1 ;;
esac
''')
        self.stub('make', '''
test "${FAIL_STAGE:-}" != build
test "$1" = -j2
PREFIX="${2#DESTDIR=}"
test "$3" = prefix=/usr
test "$4" = install
mkdir -p "$PREFIX/usr/bin"
cp "$MOCK_BINARY" "$PREFIX/usr/bin/enroot"
touch "$PREFIX/usr/bin/enroot-mount"
''')
        self.stub('mock-enroot', '''
if [ "$SOURCE_DIR" = next-src ]; then version=4.2.1; else version=2.1.0; fi
case "$1" in
  version) test "${FAIL_STAGE:-}" != version; echo "${MOCK_VERSION:-$version}" ;;
  list)
    test "${FAIL_STAGE:-}" != list
    test -d "$ENROOT_DATA_PATH"
    test -d "$XDG_RUNTIME_DIR"
    if [ "${NONEMPTY_LIST:-0}" = 1 ]; then echo unexpected-container; fi ;;
  *) exit 1 ;;
esac
''')
        self.env['MOCK_BINARY'] = str(self.bin / 'mock-enroot')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -euo pipefail\n' + body + '\n')
        path.chmod(0o755)

    def run_script(self, script, **env):
        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root, env=dict(self.env, **env), capture_output=True, text=True)
        return result, dict(line.split('=', 1) for line in output.read_text().splitlines() if '=' in line)

    def run_step(self, step, values=None, **env):
        values = values or {}
        def expression(match):
            terms = match[1].split('||')
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
        return self.run_script(re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS[step]['run']), **env)

    def run_candidate(self, overrides=None, **env):
        action = yaml.safe_load((ROOT / '.github/actions/generic-source-regression-check/action.yml').read_text())
        inputs = {key: value.get('default', '') for key, value in action['inputs'].items()}
        inputs.update(STEPS['test6']['with'])
        inputs.update(baseline_version='2.1.0', github_repo=JOB['env']['GITHUB_REPO'], lane_kind=JOB['env']['LANE_KIND'])
        inputs.update(overrides or {})
        def render(value):
            return re.sub(r'\$\{\{\s*inputs\.(\w+)\s*\}\}', lambda match: inputs[match[1]], value)
        step = action['runs']['steps'][0]
        return self.run_script(render(step['run']), **{**{key: render(value) for key, value in step['env'].items()}, **env})

    def test_preserves_pinned_dependencies_and_adds_bootstrap_tools(self):
        apt = next(step for step in JOB['steps'] if step.get('uses', '').endswith('apt-bootstrap'))
        self.assertTrue({'autoconf', 'automake', 'libtool'} <= set(apt['with']['packages'].split()))
        script = JOB['env']['ENROOT_SMOKE']
        self.assertIn('https://git.hadrons.org/git/libbsd.git', script)
        self.assertIn('git submodule update --init', script)
        self.assertIn('git submodule foreach \'test "$(git rev-parse HEAD)" = "$sha1"\'', script)
        self.assertNotIn('VERSION=', script)
        self.assertNotIn('defer_on_limited_cpu_probe_failure', STEPS['test6']['with'])

    def test_baseline_dependencies_build_and_cli_failures(self):
        for stage in ('fetch', 'pin', 'build', 'version', 'list', ''):
            with self.subTest(stage=stage):
                result, outputs = self.run_step('test5', {'steps.install.outputs.install_mode': 'github_source'}, FAIL_STAGE=stage)
                self.assertEqual(not stage, result.returncode == 0, result.stderr)
                self.assertEqual('failed' if stage else 'passed', outputs['status'])

    def test_rejects_wrong_architecture_tag_runtime_and_list(self):
        for env in ({'TEST_ARCH': 'x86_64'}, {'TEST_ELF': 'ELF x86-64'}, {'TEST_TAG': 'v2.0.0'}, {'MOCK_VERSION': '2.1.01'}, {'NONEMPTY_LIST': '1'}):
            with self.subTest(env=env):
                result, outputs = self.run_step('test5', {'steps.install.outputs.install_mode': 'github_source'}, **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_candidate_failure_propagates_through_real_composite_and_summary(self):
        for env in ({'FAIL_STAGE': 'fetch'}, {'FAIL_STAGE': 'pin'}, {'FAIL_STAGE': 'build'}, {'FAIL_STAGE': 'list'}, {'MOCK_VERSION': '2.1.0'}, {'MOCK_VERSION': '4.2.0'}, {}):
            with self.subTest(env=env):
                result, outputs = self.run_candidate(**env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('failed' if env else 'passed', outputs['status'])
                self.assertEqual('limited_cpu_smoke_failed' if env else 'limited_cpu_smoke_validated', outputs['decision'])
                self.assertEqual('limited_cpu_probe_failed' if env else '4.2.1', outputs['next_installed_version'])
                self.assertEqual('2.1.0', outputs['current_version'])
                values = self.success_values()
                values['steps.test6.outputs.status'] = outputs['status']
                summary, counts = self.run_step('summary', values)
                self.assertEqual(not env, summary.returncode == 0)
                self.assertEqual('1' if env else '0', counts['failed'])
                self.assertEqual('0', counts['core_failed'])

    def test_candidate_rejects_wrong_tag_and_version_binding(self):
        for inputs, env in (({'candidate_tag_override': 'v2.1.0'}, {}), ({'next_version_override': '4.2.2'}, {}), ({}, {'TEST_TAG': 'v2.1.0'})):
            with self.subTest(inputs=inputs, env=env):
                _, outputs = self.run_candidate(inputs, **env)
                self.assertEqual('failed', outputs['status'])

    def success_values(self):
        return {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'), ('outputs.duration', '1'))}

    def test_summary_requires_six_actual_successes_and_never_hides_skips(self):
        result, counts = self.run_step('summary', self.success_values())
        self.assertEqual(0, result.returncode)
        self.assertEqual(('6', '0', '0', '6'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'duration')))
        for i in range(1, 7):
            for status, outcome in (('', 'failure'), ('skipped', 'success'), ('passed', 'failure'), ('failed', 'success')):
                with self.subTest(test=i, status=status, outcome=outcome):
                    values = self.success_values()
                    values.update({f'steps.test{i}.outputs.status': status, f'steps.test{i}.outcome': outcome})
                    result, counts = self.run_step('summary', values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(('5', '1', '0', '1' if i < 6 else '0', 'failure'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'core_failed', 'overall_status')))


if __name__ == '__main__':
    unittest.main()
