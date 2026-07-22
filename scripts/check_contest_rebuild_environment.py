#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.runtime.preflight import contest_environment_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline-only preflight for the StateBus contest-rebuild environment."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the complete machine-readable report",
    )
    args = parser.parse_args()

    report = contest_environment_preflight()
    payload = report.canonical_payload()
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2))
    else:
        print(f"contest environment: {'READY' if report.ok else 'NOT READY'}")
        for check in report.checks:
            print(f"[{'ok' if check.ok else 'fail'}] {check.name}: {check.detail}")
        print("deferred (not executed):")
        for check in report.deferred_checks:
            print(f"[deferred] {check.name}: {check.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
