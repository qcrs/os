from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _gate_audit(case_root: Path) -> dict[str, Any]:
    paths = tuple(case_root.glob("workspaces/**/logs/logit_gate.json"))
    return _load_json(paths[0]) if len(paths) == 1 else {}


def _case_row(
    *,
    root: Path,
    mode: str,
    task_id: str,
    exit_code: int,
) -> dict[str, Any]:
    case_root = root / mode / task_id
    runner = _load_json(case_root / "runner.stdout.json")
    cases = runner.get("cases", [])
    case = cases[0] if isinstance(cases, list) and cases and isinstance(cases[0], dict) else {}
    metrics = case.get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    quality = case.get("quality_floor", {})
    quality = quality if isinstance(quality, dict) else {}
    gate = _gate_audit(case_root)
    attempts = gate.get("attempts", [])
    attempts = attempts if isinstance(attempts, list) else []
    receipts = [
        item.get("gate_receipt", {})
        for item in attempts
        if isinstance(item, dict) and isinstance(item.get("gate_receipt"), dict)
    ]
    return {
        "mode": mode,
        "task_id": task_id,
        "exit_code": exit_code,
        "quality_floor_pass": bool(quality.get("quality_floor_pass", False)),
        "task_ms": float(metrics.get("task_ms", 0.0)),
        "llm_total_tokens": float(metrics.get("llm_total_tokens", 0.0)),
        "executor_call_count": int(metrics.get("executor_call_count", 0)),
        "logit_extraction_available_count": int(
            metrics.get("logit_extraction_available_count", 0)
        ),
        "logit_state_transfer_count": int(metrics.get("logit_state_transfer_count", 0)),
        "logit_state_release_count": int(metrics.get("logit_state_release_count", 0)),
        "retry_triggered": bool(gate.get("retry_triggered", False)),
        "final_status": str(gate.get("final_status", "off" if mode == "off" else "missing")),
        "failure_reason": str(gate.get("failure_reason", "")),
        "gate_actions": [str(receipt.get("action", "")) for receipt in receipts],
        "top_margins": [float(receipt.get("top_margin", 0.0)) for receipt in receipts],
        "producer_pids": [int(receipt.get("producer_pid", 0)) for receipt in receipts],
        "consumer_pids": [int(receipt.get("consumer_pid", 0)) for receipt in receipts],
        "state_bytes": [
            int(item.get("state_bytes", 0))
            for item in attempts
            if isinstance(item, dict)
        ],
    }


def summarize(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    status_path = root / "status.tsv"
    for line in status_path.read_text(encoding="utf-8").splitlines()[1:]:
        mode, task_id, exit_text = line.split("\t")
        rows.append(
            _case_row(
                root=root,
                mode=mode,
                task_id=task_id,
                exit_code=int(exit_text),
            )
        )
    retry_rows = [row for row in rows if row["mode"] == "retry_once"]
    summary = {
        "schema_version": "statebus.logit_retry_gate_experiment.v1",
        "experiment_root": str(root),
        "case_count": len(rows),
        "successful_case_count": sum(row["exit_code"] == 0 for row in rows),
        "quality_pass_count": sum(row["quality_floor_pass"] for row in rows),
        "retry_mode_case_count": len(retry_rows),
        "cross_pid_transfer_case_count": sum(
            row["logit_state_transfer_count"] > 0 for row in retry_rows
        ),
        "released_case_count": sum(
            row["logit_state_release_count"] > 0 for row in retry_rows
        ),
        "retry_triggered_case_count": sum(row["retry_triggered"] for row in retry_rows),
        "fail_closed_case_count": sum(
            row["final_status"] == "fail_closed" for row in retry_rows
        ),
        "rows": rows,
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# StateBus Logit Retry Gate Experiment",
        "",
        "This is a bounded diagnostic experiment and does not update formal benchmark evidence.",
        "",
        "| mode | task | exit | quality | final status | actions | margins | cross-PID | released | task ms |",
        "|---|---|---:|---:|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {mode} | {task_id} | {exit_code} | {quality} | {status} | {actions} | {margins} | {transfer} | {release} | {task_ms:.3f} |".format(
                mode=row["mode"],
                task_id=row["task_id"],
                exit_code=row["exit_code"],
                quality=int(row["quality_floor_pass"]),
                status=row["final_status"],
                actions=",".join(row["gate_actions"]) or "-",
                margins=",".join(f"{value:.6f}" for value in row["top_margins"]) or "-",
                transfer=row["logit_state_transfer_count"],
                release=row["logit_state_release_count"],
                task_ms=row["task_ms"],
            )
        )
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_root", type=Path)
    args = parser.parse_args()
    summary = summarize(args.experiment_root)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
