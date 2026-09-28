#!/usr/bin/env python3
"""Print the compact result contract for one showcase output directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Show contest CodeAct DSL showcase results.")
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.result_dir / "summary.json").read_text(encoding="utf-8"))
    print((args.result_dir / "summary.md").read_text(encoding="utf-8"), end="")
    failures = [row for row in summary["rows"] if row["status"] == "failed"]
    if failures:
        print("\nFailures:")
        for row in failures:
            print(f"- {row['case_id']}: {row.get('reason') or 'unknown'}")
    print(json.dumps({key: summary[key] for key in ("mode", "fallback_enabled", "passed", "case_count", "dsl_passed", "dsl_total", "codeact_passed", "codeact_total", "overall_total")}, ensure_ascii=False, indent=2))
    return 0 if summary.get("mode") == "dry-run" or summary["passed"] == summary["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
