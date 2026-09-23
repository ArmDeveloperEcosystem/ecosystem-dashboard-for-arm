"""python -m poc.discovery --config CONFIG --output-dir DIRECTORY [--catalog JSON]"""

import argparse
import json

from .pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Internal bounded Linux Arm64 discovery. Reads metadata only; never publishes findings."
    )
    parser.add_argument("--config", default="poc/discovery/config.example.yaml")
    parser.add_argument("--output-dir", default=".poc/discovery")
    parser.add_argument(
        "--catalog",
        help="Optional read-only JSON/YAML catalog for repository URL identity comparison",
    )
    args = parser.parse_args()
    summary = run_pipeline(args.config, args.output_dir, args.catalog)
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "run_id",
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


if __name__ == "__main__":
    main()
