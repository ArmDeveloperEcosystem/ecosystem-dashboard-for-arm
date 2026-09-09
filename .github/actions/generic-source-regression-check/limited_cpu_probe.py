#!/usr/bin/env python3

import compileall
import os
import sys
from pathlib import Path


def main() -> int:
    source_root = Path(sys.argv[1] if len(sys.argv) > 1 else "next-src").resolve()
    slug = os.environ.get("PACKAGE_SLUG", "").strip()

    targets = {
        "catboost": [
            source_root / "catboost" / "python-package" / "catboost",
        ],
        "dify": [
            source_root / "api",
        ],
        "feast": [
            source_root / "sdk" / "python" / "feast",
        ],
        "gdsfactory": [
            source_root / "gdsfactory",
        ],
        "myhdl": [
            source_root / "myhdl",
        ],
        "prophet": [
            source_root / "python" / "prophet",
            source_root / "python_shim" / "fbprophet",
        ],
        "shap": [
            source_root / "shap",
        ],
        "tabpfn-time-series": [
            source_root / "tabpfn_time_series",
        ],
        "tabPFN": [
            source_root / "src" / "tabpfn",
        ],
        "veriloggen": [
            source_root / "veriloggen",
        ],
        "vidgear": [
            source_root / "vidgear",
        ],
    }

    probe_targets = targets.get(slug, [])
    if not probe_targets:
        print(f"No limited CPU probe is configured for package slug: {slug}", file=sys.stderr)
        return 1

    for target in probe_targets:
        if not target.exists():
            continue
        if target.is_dir():
            ok = compileall.compile_dir(str(target), quiet=1)
        else:
            ok = compileall.compile_file(str(target), quiet=1)
        if ok:
            print(f"limited-cpu-proof-ok: {slug} -> {target}")
            return 0
        print(f"limited-cpu-proof-failed: {slug} -> {target}", file=sys.stderr)
        return 1

    print(
        f"Probe target was not found for {slug}. Checked: "
        + ", ".join(str(target) for target in probe_targets),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
