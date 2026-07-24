#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPARE_PATHS = (
    "v2/runtime/smoke.py",
    "v2/runtime/role_path.py",
    "v2/benchmark/live_runner.py",
    "v2/benchmark/comparator_runner.py",
    "scripts/run_v2_full_qwen3_container.sh",
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={REPO_ROOT}", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _feature_snapshot(text: str) -> dict[str, bool]:
    return {
        "task_local_prefix_counter_delta": "counter_delta" in text or "record_live" in text,
        "subprocess_transport": "subprocess" in text and "transport" in text,
        "route_hint_audit_switch": "STATEBUS_ROUTE_HINTS_ENABLED" in text,
        "formal_claim_first_pass": 'claim_level="first_pass"' in text or "claim_level=(" in text,
        "task_metrics_persistence": "task_metrics.json" in text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a read-only current-vs-tag StateBus v2 audit.")
    parser.add_argument("--tag", default="v2-non-kv-baseline-20260710")
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()

    current_commit = _git("rev-parse", "HEAD")
    tag_commit = _git("rev-list", "-n", "1", args.tag)
    rows = []
    for path in COMPARE_PATHS:
        current_text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace") if (REPO_ROOT / path).exists() else ""
        try:
            tagged_text = _git("show", f"{args.tag}:{path}")
            tag_exists = True
        except subprocess.CalledProcessError:
            tagged_text = ""
            tag_exists = False
        rows.append(
            {
                "path": path,
                "tag_exists": tag_exists,
                "current_line_count": len(current_text.splitlines()),
                "tag_line_count": len(tagged_text.splitlines()),
                "current_features": _feature_snapshot(current_text),
                "tag_features": _feature_snapshot(tagged_text),
                "diff_numstat": _git("diff", "--numstat", f"{args.tag}..HEAD", "--", path).strip(),
            }
        )
    payload = {
        "schema_version": "statebus.v2_tag_baseline_audit.v1",
        "tag": args.tag,
        "tag_commit": tag_commit,
        "current_commit": current_commit,
        "comparison_mode": "read_only_git_show_and_numstat",
        "claim_boundary": (
            "implementation/reference audit only; it does not rerun the historical tag API "
            "under a different dependency or model environment"
        ),
        "files": rows,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
