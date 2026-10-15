from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
JOB = yaml.safe_load((ROOT / '.github/workflows/test-kasmvnc.yml').read_text())['jobs']['test-kasmvnc']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class KasmVNCWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kasmvnc-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, **JOB['env'], RESOLVED_TAG='v0.9.3-beta', GITHUB_OUTPUT=str(self.root / 'outputs'), RUNNER_TEMP=str(self.root))
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        for filename in ('README.md', 'BUILDING.txt', 'CMakeLists.txt'):
            (self.root / filename).write_text('KasmVNC\n')
        for directory in ('unix', 'common', 'tests'):
            (self.root / directory).mkdir()
        self.stub('curl', 'echo release')
        # Real jq consumes its input; an early-exiting stub races curl under pipefail.
        self.stub('jq', 'cat >/dev/null\necho https://example.invalid/kasmvnc.deb')
        self.stub('dpkg-deb', '''
case "$3" in
  Architecture) echo "${TEST_ARCH:-arm64}" ;;
  Version) echo "${TEST_VERSION:-0.9.3~beta-1}" ;;
  Package) printf 'Package: kasmvncserver\nVersion: 0.9.3~beta-1\nArchitecture: arm64\n' ;;
  *) exit 2 ;;
esac
''')

    def stub(self, name, body):
        target = self.bin / name
        target.write_text('#!/bin/bash\nset -euo pipefail\n' + body + '\n')
        target.chmod(0o755)

    def run_script(self, script, **env):
        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        def isolate(value):
            # Redirect fixed workflow paths into this test's private filesystem.
            return value.replace('/tmp/kasmvnc-', str(self.root / 'kasmvnc-')).replace('"/usr/bin/', '"' + str(self.root / 'installed') + '/')
        script = isolate(script)
        if 'INPUT_LIMITED_CPU_PROBE' in env:
            env['INPUT_LIMITED_CPU_PROBE'] = isolate(env['INPUT_LIMITED_CPU_PROBE'])
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root, env=dict(self.env, **env), text=True, capture_output=True)
        return result, dict(line.split('=', 1) for line in output.read_text().splitlines())

    def prepare_candidate(self):
        self.env['FIXTURE_ROOT'] = str(self.root)
        payload = self.root / 'payload'
        payload.mkdir()
        server = payload / 'Xkasmvnc'
        server.write_text('''#!/bin/bash
printf '%s\\n' "$0" > "$FIXTURE_ROOT/invoked-binary"
echo "Xvnc KasmVNC ${REPORTED_VERSION-1.4.0.663b6d6a0bdd4638bff981c75a522056aaaa1c2e} - built fixture"
exit "${VERSION_EXIT:-0}"
''')
        server.chmod(0o755)
        helper = payload / 'kasmvncserver'
        helper.write_text('#!/bin/bash\necho "usage: kasmvncserver [:<number>]"\nexit "${TEST_HELP_EXIT:-2}"\n')
        helper.chmod(0o755)
        self.stub('uname', 'echo aarch64')
        self.stub('timeout', 'shift; exec "$@"')
        self.stub('git', 'mkdir -p next-src; echo KasmVNC > next-src/README.md')
        self.stub('file', 'echo "$1: ELF 64-bit executable, ARM aarch64"')
        self.stub('dpkg-deb', '''
if [ "$1" = -x ]; then
  mkdir -p "$3/usr/bin"
  cp "$FIXTURE_ROOT/payload/"* "$3/usr/bin/"
elif [ "$#" -gt 3 ]; then
  printf 'Package: kasmvncserver\nVersion: %s\nArchitecture: arm64\n' "${TEST_DEB_VERSION:-1.4.0-1}"
else
  case "$3" in
    Package) echo kasmvncserver ;;
    Architecture) echo arm64 ;;
    Version) echo "${TEST_DEB_VERSION:-1.4.0-1}" ;;
    *) exit 2 ;;
  esac
fi
''')
        self.stub('sudo', '''
touch "$FIXTURE_ROOT/install-invoked"
mkdir -p "$FIXTURE_ROOT/installed"
cp "$FIXTURE_ROOT/payload/"* "$FIXTURE_ROOT/installed/"
if [ "${STALE_INSTALLED_RUNTIME:-0}" = 1 ]; then
  printf '#!/bin/bash\necho "Xvnc KasmVNC 1.3.3 - built older"\n' > "$FIXTURE_ROOT/installed/Xkasmvnc"
fi
''')
        self.stub('dpkg-query', '''
if [ "$1" = -L ]; then
  if [ "${UNOWNED_EXECUTABLE:-0}" = 0 ]; then echo "$FIXTURE_ROOT/installed/Xkasmvnc"; fi
  echo "$FIXTURE_ROOT/installed/kasmvncserver"
else
  case "$2" in
    '-f=${Status}') echo 'install ok installed' ;;
    '-f=${Architecture}') echo arm64 ;;
    '-f=${Version}') echo "${TEST_INSTALLED_VERSION:-1.4.0-1}" ;;
    *) exit 2 ;;
  esac
fi
''')

    def run_candidate(self, **env):
        action = yaml.safe_load((ROOT / '.github/actions/generic-source-regression-check/action.yml').read_text())
        values = {key: value.get('default', '') for key, value in action['inputs'].items()}
        values.update(STEPS['test6']['with'])
        values.update(baseline_version=JOB['env']['BASELINE_VERSION'], github_repo=JOB['env']['GITHUB_REPO'], lane_kind=JOB['env']['LANE_KIND'])
        composite = action['runs']['steps'][0]
        def render(value):
            return re.sub(r'\$\{\{\s*inputs\.(\w+)\s*\}\}', lambda match: values[match[1]], value)
        env = {**{key: render(value) for key, value in composite['env'].items()}, **env}
        return self.run_script(render(composite['run']), **env)

    def assert_candidate_failure(self, **env):
        result, outputs = self.run_candidate(**env)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('failed', outputs['status'], result.stdout + result.stderr)
        self.assertEqual('limited_cpu_smoke_failed', outputs['decision'])
        self.assertEqual('limited_cpu_probe_failed', outputs['next_installed_version'])
        values = {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'))}
        values['steps.test6.outputs.status'] = outputs['status']
        def expression(match):
            terms = match[1].split('||')
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
        summary, counts = self.run_script(re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS['summary']['run']))
        self.assertNotEqual(0, summary.returncode)
        self.assertEqual(('5', '1', '0'), tuple(counts[key] for key in ('passed', 'failed', 'core_failed')))

    def test_candidate_rejects_older_package_and_runtime_before_install(self):
        self.prepare_candidate()
        self.assert_candidate_failure(TEST_DEB_VERSION='1.3.3-1', TEST_INSTALLED_VERSION='1.3.3-1', REPORTED_VERSION='1.3.3')
        self.assertFalse((self.root / 'install-invoked').exists())

    def test_candidate_rejects_candidate_metadata_with_older_runtime(self):
        self.prepare_candidate()
        self.assert_candidate_failure(STALE_INSTALLED_RUNTIME='1')
        self.assertFalse((self.root / 'invoked-binary').exists())
        self.assert_candidate_failure(REPORTED_VERSION='1.3.3')
        self.assertTrue((self.root / 'invoked-binary').exists())

    def test_candidate_binds_installed_version_and_allows_debian_revisions(self):
        self.prepare_candidate()
        for version in ('1.4.0-1', '1.4.0-2', '1:1.4.0-1'):
            with self.subTest(version=version):
                result, outputs = self.run_candidate(TEST_DEB_VERSION=version, TEST_INSTALLED_VERSION=version)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('passed', outputs['status'], result.stdout + result.stderr)
                self.assertEqual('1.4.0', outputs['next_installed_version'])
        self.assert_candidate_failure(TEST_INSTALLED_VERSION='1.3.3-1')
        self.assert_candidate_failure(TEST_DEB_VERSION='1.4.0~beta-1')

    def test_candidate_rejects_wrong_banner_and_failed_version_or_help_commands(self):
        self.prepare_candidate()
        for version in ('1.4.01', '1.4.0-beta', '1.4.0.bad', ''):
            with self.subTest(version=version):
                self.assert_candidate_failure(REPORTED_VERSION=version)
        for code in ('1', '124'):
            with self.subTest(exit_code=code):
                self.assert_candidate_failure(VERSION_EXIT=code)
                self.assert_candidate_failure(TEST_HELP_EXIT=code)

    def test_candidate_invokes_owned_payload_paths_despite_path_shadow(self):
        self.prepare_candidate()
        self.stub('Xkasmvnc', 'touch "$FIXTURE_ROOT/shadow-invoked"; echo "Xvnc KasmVNC 1.3.3 - built older"')
        result, outputs = self.run_candidate()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', outputs['status'], result.stdout + result.stderr)
        self.assertEqual(str(self.root / 'installed/Xkasmvnc'), (self.root / 'invoked-binary').read_text().strip())
        self.assertFalse((self.root / 'shadow-invoked').exists())
        self.assert_candidate_failure(UNOWNED_EXECUTABLE='1')

    def test_baseline_source_layout_and_missing_build_instructions(self):
        result, _ = self.run_script(JOB['env']['TEST1_COMMAND'])
        self.assertEqual(0, result.returncode, result.stderr)
        (self.root / 'BUILDING.txt').unlink()
        result, _ = self.run_script(JOB['env']['TEST1_COMMAND'])
        self.assertNotEqual(0, result.returncode)

    def test_release_parser_fixture_consumes_the_producer_stream(self):
        result, _ = self.run_script(
            "python3 -c 'import sys; sys.stdout.write(\"release\\n\" * 32768)' | jq -r ignored"
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('https://example.invalid/kasmvnc.deb', result.stdout.strip())

    def test_source_checks_reject_wrong_tag_and_missing_tests(self):
        result, _ = self.run_script(JOB['env']['TEST1_COMMAND'], RESOLVED_TAG='v1.4.0')
        self.assertNotEqual(0, result.returncode)
        result, _ = self.run_script(JOB['env']['TEST3_COMMAND'])
        self.assertEqual(0, result.returncode, result.stderr)
        (self.root / 'tests').rmdir()
        result, _ = self.run_script(JOB['env']['TEST3_COMMAND'])
        self.assertNotEqual(0, result.returncode)

    def test_package_fields_accept_labeled_report_but_reject_wrong_arch_or_version(self):
        probe = JOB['env']['TEST5_COMMAND'].split('dpkg-deb -x', 1)[0]
        for arch, version in (('arm64', '0.9.3~beta-1'), ('amd64', '0.9.3~beta-1'), ('arm64', '1.4.0-1')):
            with self.subTest(arch=arch, version=version):
                result, _ = self.run_script(probe, TEST_ARCH=arch, TEST_VERSION=version)
                self.assertEqual(arch == 'arm64' and version == '0.9.3~beta-1', result.returncode == 0, result.stderr)

    def test_summary_counts_original_missing_core_outputs_as_failures(self):
        values = {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'))}
        for failed in ((), (1, 3, 5), (6,)):
            case = dict(values)
            for i in failed:
                case[f'steps.test{i}.outputs.status'] = '' if i in (1, 3) else 'failed'
                case[f'steps.test{i}.outcome'] = 'failure'
            def expression(match):
                terms = match[1].split('||')
                return case.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
            script = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS['summary']['run'])
            result, outputs = self.run_script(script)
            self.assertEqual(not failed, result.returncode == 0)
            self.assertEqual(str(len(failed)), outputs['failed'])
            self.assertEqual(str(len([i for i in failed if i <= 5])), outputs['core_failed'])
            self.assertEqual('0', outputs['skipped'])

    def test_runtime_requires_live_server_display_and_rfb_greeting(self):
        self.stub('Xkasmvnc', '''
case " $* " in *" -noWebsocket "*) ;; *) exit 2 ;; esac
if [ "${SERVER_FAIL:-0}" = 1 ]; then exit 1; fi
exec /bin/sleep 30
''')
        self.stub('xdpyinfo', 'test "${DISPLAY_FAIL:-0}" = 0; echo dimensions')
        self.stub('python3', 'test "${PROTOCOL_FAIL:-0}" = 0')
        self.stub('seq', 'echo 1 2')
        self.stub('sleep', '/bin/sleep 0.05')
        runtime = JOB['env']['TEST5_COMMAND'].split('DISPLAY_NUM=29', 1)[1]
        script = 'DISPLAY_NUM=29\n' + runtime
        for failure in ('SERVER_FAIL', 'DISPLAY_FAIL', 'PROTOCOL_FAIL', ''):
            with self.subTest(failure=failure):
                env = {'XKASM': str(self.bin / 'Xkasmvnc'), 'ASSET_URL': 'fixture'}
                if failure:
                    env[failure] = '1'
                if failure == 'SERVER_FAIL':
                    env['DISPLAY_FAIL'] = '1'
                result, outputs = self.run_script(script, **env)
                self.assertEqual(not failure, result.returncode == 0, result.stderr)
                self.assertEqual(not failure, 'note' in outputs)


if __name__ == '__main__':
    unittest.main()
