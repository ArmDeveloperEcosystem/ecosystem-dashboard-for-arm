"""Offline acceptance of the production image's default batch command.

Uses isolated disposable Docker volumes and synthetic empty input. No real source
or model requests are possible, and no generated report contents are printed.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import uuid


INSPECT_STATE = r"""
import importlib.util,json,os,pathlib,platform,sqlite3
assert os.getuid()==10001
assert platform.machine()=='aarch64'
assert os.statvfs('/').f_flag & os.ST_RDONLY
status=pathlib.Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\t1' in status
assert 'CapEff:\t0000000000000000' in status
assert importlib.util.find_spec('pytest') is None
assert importlib.util.find_spec('pip') is None
assert importlib.util.find_spec('ensurepip') is None
assert not list(pathlib.Path('/usr/local/bin').glob('pip*'))
assert importlib.util.find_spec('poc.discovery.serve') is None
assert not pathlib.Path('/app/.git').exists()
assert not pathlib.Path('/app/poc/tests').exists()
pathlib.Path('/tmp/writable').write_text('ok')
files=[p for p in pathlib.Path('/state').rglob('*') if p.is_file()]
assert all(not p.stat().st_mode & 0o077 for p in files)
conn=sqlite3.connect('/state/discovery.sqlite3')
runs=conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
assert runs==2,runs
assert len(list(pathlib.Path('/state').glob('*/opportunities.docx')))==2
assert len(list(pathlib.Path('/state').glob('*/opportunities.csv')))==2
assert len(list(pathlib.Path('/state').glob('*/opportunities.json')))==2
latest=json.loads(pathlib.Path('/state/latest.json').read_text())
assert latest['counts']['investigated']==0
assert latest['counts']['requests']==0
assert latest['catalog_comparison']['identity_count']==0
assert latest['ai_review']['completed']==0
print(json.dumps({'uid':os.getuid(),'architecture':platform.machine(),
 'persistent_runs':runs,'private_output_files':len(files),'default_command':True,
 'readonly_root':True,'tmpfs_writable':True,'capabilities_dropped':True,
 'no_new_privileges':True,'network':'none','source_requests':0,'model_calls':0,
 'packaged_web_server':False,'packaged_test_dependencies':False,
 'packaged_installer':False,'bundled_installer':False}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--context", help="Optional explicit Docker context")
    args = parser.parse_args()
    docker = ["docker"] + (["--context", args.context] if args.context else [])
    suffix = uuid.uuid4().hex
    volume = "arm64-opportunity-smoke-" + suffix
    names = []

    def run(command):
        result = subprocess.run(
            docker + command, capture_output=True, text=True, timeout=90
        )
        if result.returncode:
            raise RuntimeError(
                f"Offline image check failed ({result.returncode}): {result.stderr}"
            )
        return result.stdout

    try:
        run(["volume", "create", volume])
        with tempfile.TemporaryDirectory(prefix="arm64-opportunity-smoke-") as folder:
            root = Path(folder)
            config = root / "config.yaml"
            config.write_text(
                "seeds: []\ndiscovery: {github_queries: []}\n"
                "ai_review: {enabled: false}\n"
            )
            config.chmod(0o644)
            catalog = root / "empty-catalog"
            catalog.mkdir(mode=0o755)
            # Replace /app/content with an empty YAML snapshot at its default
            # catalog path. A truly empty catalog directory is invalid input;
            # [] is a valid snapshot containing no real package records.
            (catalog / "linux").write_text("[]\n")
            base = [
                "run", "--rm", "--pull=never", "--init", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--pids-limit=128", "--memory=1g", "--cpus=2", "--network=none",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777",
                "--mount", f"type=volume,source={volume},target=/state",
                "--mount", f"type=bind,source={config},target=/config/config.yaml,readonly",
                "--mount", f"type=bind,source={catalog},target=/app/content,readonly",
            ]
            for index in range(2):
                name = f"{volume}-run-{index}"
                names.append(name)
                # No CLI override: exercise the packaged operational defaults.
                result = json.loads(run(base + ["--name", name, args.image]))
                assert result["counts"]["investigated"] == 0
                assert result["counts"]["requests"] == 0
            name = volume + "-inspect"
            names.append(name)
            print(run(base + ["--name", name, "--entrypoint", "python",
                              args.image, "-c", INSPECT_STATE]).strip())
    finally:
        # A subprocess timeout can leave a running container. Remove only this
        # invocation's unique names before discarding its disposable volume.
        for name in names:
            subprocess.run(docker + ["container", "rm", "-f", name],
                           capture_output=True, timeout=30)
        subprocess.run(docker + ["volume", "rm", volume],
                       capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
