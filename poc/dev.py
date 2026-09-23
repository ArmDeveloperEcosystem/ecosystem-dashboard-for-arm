"""Build the existing Hugo site with opt-in PoC features and serve on loopback."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if not args.no_build:
        if not shutil.which("hugo"):
            raise SystemExit(
                "Install Hugo extended (CI uses 0.130.0) and run this command again."
            )
        subprocess.run(
            [
                "hugo",
                "--config",
                "config.toml,poc/config.local.toml",
                "--baseURL",
                f"http://127.0.0.1:{args.port}/",
                "--destination",
                ".poc/public",
            ],
            check=True,
        )
    from .server import create_app
    import uvicorn

    print(
        f"\nDashboard: http://127.0.0.1:{args.port}/linux/\nInternal report: http://127.0.0.1:{args.port}/internal/opportunities\n",
        flush=True,
    )
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
