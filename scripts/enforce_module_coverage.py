from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce per-module coverage thresholds.")
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--minimum", type=float, required=True)
    args = parser.parse_args()

    coverage = json.loads(args.coverage_json.read_text())
    failures = []
    for filename, file_data in sorted(coverage["files"].items()):
        percent = file_data["summary"]["percent_covered"]
        if percent < args.minimum:
            failures.append((filename, percent))

    if not failures:
        return

    formatted = "\n".join(
        f"- {filename}: {percent:.2f}% < {args.minimum:.2f}%" for filename, percent in failures
    )
    raise SystemExit(f"Coverage below required per-module threshold:\n{formatted}")
