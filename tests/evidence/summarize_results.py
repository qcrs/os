#!/usr/bin/env python3
"""Print a compact summary of the curated StateBus result evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
def _load(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def collect() -> dict[str, Any]:
    mainline = _load("mainline/results.json")
    mechanisms = _load("mechanisms/results.json")
    model_assist = _load("model-assist/metrics.json")
    overall = mainline["overall"]
    comparison = mainline["comparison"]

    return {
        "mainline": {
            "planned": overall["planned_count"],
            "started": overall["started_count"],
            "passed": overall["passed_count"],
            "quality_pass_rate": overall["quality_pass_rate"],
            "matched_pairs": comparison["matched_task_count"],
            "quality_matches": comparison["quality_matches"],
        },
        "mechanisms": {
            "planned": mechanisms["planned"],
            "started": mechanisms["started"],
            "passed": mechanisms["passed"],
            "status_counts": mechanisms["status_counts"],
        },
        "model_assist": {
            "status": model_assist["status"],
            "demo_completed": model_assist["demo_completed"],
            "standard_restored": model_assist["standard_restored"],
            "business_quality_passed": model_assist["business_quality_passed"],
            "slot_counts": model_assist["slot_counts"],
            "by_module": model_assist["by_module"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    result = collect()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    mainline = result["mainline"]
    mechanisms = result["mechanisms"]
    model_assist = result["model_assist"]
    print(
        "Mainline: "
        f"{mainline['passed']}/{mainline['planned']} passed, "
        f"{mainline['quality_matches']}/{mainline['matched_pairs']} matched quality pairs"
    )
    print(
        "Mechanisms: "
        f"{mechanisms['passed']}/{mechanisms['planned']} passed, "
        f"status_counts={mechanisms['status_counts']}"
    )
    module_counts = ", ".join(
        f"{name}={values['completed']} completed/{values['failed']} failed"
        for name, values in model_assist["by_module"].items()
    )
    print(
        "Model assist: "
        f"status={model_assist['status']}, {module_counts}, "
        f"business_quality_passed={model_assist['business_quality_passed']}"
    )


if __name__ == "__main__":
    main()
