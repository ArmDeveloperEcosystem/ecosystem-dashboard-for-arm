"""python -m poc.discovery --config CONFIG --output-dir DIRECTORY [--catalog JSON]"""

import argparse
import json
import sys
import sqlite3

import yaml

from .pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Internal bounded Linux Arm64 discovery. Reads metadata only; never publishes findings."
    )
    parser.add_argument("--config", default="poc/discovery/config.example.yaml")
    parser.add_argument("--output-dir", default=".poc/discovery")
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Exit 2 after publishing reports if this run had collection or AI errors",
    )
    parser.add_argument(
        "--require-ai",
        action="store_true",
        help="Require configured AI before collection, and completed AI for every eligible new finding",
    )
    parser.add_argument(
        "--catalog",
        default="content/linux",
        help="Read-only Linux catalog directory or JSON/YAML snapshot (default content/linux)",
    )
    args = parser.parse_args()
    try:
        summary = run_pipeline(
            args.config, args.output_dir, args.catalog, require_ai=args.require_ai
        )
    except (OSError, ValueError, RuntimeError, yaml.YAMLError, sqlite3.Error) as exc:
        print(f"Discovery run failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "run_id",
                    "outcome",
                    "current_errors",
                    "generated_at",
                    "counts",
                    "ai_review",
                    "report_paths",
                    "state_path",
                )
            },
            indent=2,
        )
    )
    if args.fail_on_errors and summary["current_errors"]:
        return 2
    if (
        args.require_ai
        and summary["ai_review"]["completed"] < summary["ai_review"]["eligible"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
