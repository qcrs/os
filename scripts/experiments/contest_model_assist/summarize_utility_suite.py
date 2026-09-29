#!/usr/bin/env python3
"""Read-only summary for an immutable utility suite run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from statebus.benchmark.model_assist_utility.runner import summarize_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    payload = summarize_records(args.run_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
