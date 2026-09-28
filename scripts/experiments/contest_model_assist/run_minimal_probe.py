#!/usr/bin/env python3
"""Run the bounded Contest DSL model-assist wiring probe.

The command owns only the F01/O01 mechanism positions described by the
measurement proposal.  It never expands to the twelve-round mainline.  A
missing execution switch is intentionally a plan-only invocation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from statebus.benchmark.contest_dsl_mainline import run_slot
from statebus.benchmark.contest_dsl_metrics import collect_slot_metrics, read_events
from statebus.benchmark.contest_dsl_taskpack import (
    SIMPLE_PROFILE,
    generate_sealed,
    publish_required_files,
    task_contract,
)
from statebus.benchmark import contest_dsl_mainline
from statebus.benchmark import contest_model_assist
from statebus.integrations.vllm_kv import role_client as kv_role_client
from statebus.integrations.vllm_kv import middleware as kv_middleware
from statebus.integrations.vllm_kv import client as kv_client
from statebus.integrations.vllm_kv import tokenizer_client
from statebus.runtime import model_assist


PLAN_MATRIX: tuple[tuple[str, str, str, str], ...] = (
    ("standard", "finance", "F01", "logit"),
    ("standard", "finance", "F01", "apc"),
    ("standard", "service_ops", "O01", "apc"),
    ("standard", "service_ops", "O01", "logit"),
    ("kv", "finance", "F01", "kv_replay"),
    ("kv", "finance", "F01", "kv_continuation"),
    ("kv", "service_ops", "O01", "kv_continuation"),
    ("kv", "service_ops", "O01", "kv_replay"),
)
SOURCE_LABELS = ("candidate", "mainline")


@dataclass(frozen=True)
class ProbePosition:
    phase: str
    family: str
    task_id: str
    profile: str
    status: str = "not_started"
    slot_root: str | None = None
    error: str | None = None


def _source_paths() -> dict[str, str]:
    modules = {
        "statebus": __import__("statebus").__file__,
        "contest_dsl_mainline": contest_dsl_mainline.__file__,
        "contest_model_assist": contest_model_assist.__file__,
        "model_assist_policy": model_assist.__file__,
        "kv_role_client": kv_role_client.__file__,
        "kv_middleware": kv_middleware.__file__,
        "kv_client": kv_client.__file__,
        "tokenizer_client": tokenizer_client.__file__,
    }
    return {name: str(Path(path).resolve()) for name, path in modules.items()}


def _positions() -> list[ProbePosition]:
    return [ProbePosition(*item) for item in PLAN_MATRIX]


def _selected_positions(phase: str, family: str) -> list[ProbePosition]:
    return [
        position
        for position in _positions()
        if position.phase == phase and (family == "all" or position.family == family)
    ]


def _plan_payload(args: argparse.Namespace) -> dict[str, Any]:
    source_root = Path(__file__).resolve().parents[3]
    expected_roots = {
        "candidate": {"os-contest-dsl-model-assist-integration", "os"},
        "mainline": {"os"},
    }
    if source_root.name not in expected_roots[args.source_label]:
        raise SystemExit(
            f"source_label_mismatch:{args.source_label}:{source_root}"
        )
    source_paths = _source_paths()
    if any(Path(value).resolve().is_relative_to(source_root) is False for value in source_paths.values()):
        raise SystemExit(f"source_module_outside_checkout:{source_root}")
    try:
        branch = subprocess.run(
            ["git", "-C", str(source_root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(source_root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        branch = os.getenv("STATEBUS_SOURCE_BRANCH", "git_unavailable_in_runtime")
        head = os.getenv("STATEBUS_SOURCE_HEAD", "git_unavailable_in_runtime")
        dirty = os.getenv("STATEBUS_SOURCE_DIRTY", "unknown")
    positions = _positions()
    selected = {(item.phase, item.family, item.profile) for item in _selected_positions(args.phase, args.family)}
    for index, item in enumerate(positions):
        if (item.phase, item.family, item.profile) in selected:
            positions[index] = ProbePosition(
                item.phase, item.family, item.task_id, item.profile, status="selected"
            )
    return {
        "schema_version": "statebus.contest_model_assist_probe_plan.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_label": args.source_label,
        "source_root": str(source_root),
        "source_paths": source_paths,
        "source_identity": {"branch": branch, "head": head, "dirty": dirty},
        "kv_server_launcher": str(source_root / "scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh"),
        "phase": args.phase,
        "family": args.family,
        "selected_positions": [
            {**asdict(item), "status": "selected"}
            for item in _selected_positions(args.phase, args.family)
        ],
        "positions": [asdict(item) for item in positions],
        "configuration": {
            "variant": "SB-FULL",
            "mode": "live" if args.live else "dry-run" if args.dry_run else "plan-only",
            "profile": SIMPLE_PROFILE,
            "model": args.model,
            "base_url": args.base_url,
            "max_context": args.max_context,
            "provider_timeout_s": args.provider_timeout_s,
            "memory_enabled": False,
            "semantic_state_mode": "on",
            "codeact_fallback_enabled": False,
            "embedding_mode": "local",
            "embedding_model": str(args.embedding_model),
            "embedding_device": args.embedding_device,
            "tokenizer_path": str(args.tokenizer_path),
            "planned_generation_upper_bound_per_position": 3,
        },
        "output": str(args.output) if args.output else None,
        "executed": False,
    }


def _print_plan(args: argparse.Namespace) -> int:
    payload = _plan_payload(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _read_model_assist_events(slot_root: Path) -> list[dict[str, Any]]:
    path = slot_root / "model-assist.jsonl"
    if not path.is_file():
        return []
    return read_events(path)


def _slot_mechanism(slot_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "model_assist": _read_model_assist_events(slot_root),
        "engine_local_kv": None,
    }
    audit = slot_root / "engine-local-kv.json"
    if audit.is_file():
        result["engine_local_kv"] = json.loads(audit.read_text(encoding="utf-8"))
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_live(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"output_already_exists:{output}")
    if args.provider_timeout_s <= 0 or args.max_context <= 0:
        raise SystemExit("provider timeout and max context must be positive")
    output.mkdir(parents=True)
    plan = _plan_payload(args)
    plan["executed"] = True
    _write_json(output / "plan.json", plan)
    generate_sealed(output / "sealed", profile=SIMPLE_PROFILE)
    public = output / "public"
    selected = _selected_positions(args.phase, args.family)
    results: list[dict[str, Any]] = []
    stop_reason: str | None = None
    history: dict[str, list[dict[str, Any]]] = {}
    for index, position in enumerate(selected):
        row: dict[str, Any] = {
            "phase": position.phase,
            "family": position.family,
            "task_id": position.task_id,
            "profile": position.profile,
            "status": "not_started",
            "slot_root": str(output / "slots" / f"{position.task_id}-{position.profile}"),
        }
        if stop_reason:
            row["blocked_reason"] = stop_reason
            results.append(row)
            continue
        slot_root = Path(row["slot_root"])
        started_ns = time.monotonic_ns()
        try:
            publish_required_files(output / "sealed", public, position.task_id, profile=SIMPLE_PROFILE)
            # F01/O01 have no required history in the bounded probe.  Keep this
            # explicit so a future task cannot silently import prior answers.
            contract = task_contract(position.task_id, profile=SIMPLE_PROFILE)
            if contract.required_history:
                raise RuntimeError(f"unexpected_probe_history:{position.task_id}:{contract.required_history}")
            result = run_slot(
                slot_root,
                public,
                position.task_id,
                history=history,
                variant="SB-FULL",
                mode="live",
                profile=SIMPLE_PROFILE,
                model=args.model,
                base_url=args.base_url,
                max_context=args.max_context,
                embedding_mode="local",
                embedding_model=args.embedding_model,
                embedding_device=args.embedding_device,
                tokenizer_path=args.tokenizer_path,
                provider_timeout_s=args.provider_timeout_s,
                memory_enabled=False,
                semantic_state_mode="on",
                codeact_fallback_enabled=False,
                model_assist_profile=position.profile,
            )
            observed_rows = result.pop("rows", None)
            if result.get("status") == "success" and observed_rows is not None:
                history[position.task_id] = observed_rows
            row.update(result)
            row["mechanism"] = _slot_mechanism(slot_root)
            row["metrics"] = collect_slot_metrics(slot_root)
            if row.get("status") != "success":
                stop_reason = f"stop_after_{row.get('status', 'failure')}:{position.task_id}:{position.profile}"
        except Exception as exc:
            row.update(
                {
                    "status": "runtime_fail",
                    "returncode": 1,
                    "error": f"{type(exc).__name__}:{exc}",
                    "mechanism": _slot_mechanism(slot_root),
                    "metrics": collect_slot_metrics(slot_root),
                }
            )
            stop_reason = f"stop_after_runtime_fail:{position.task_id}:{position.profile}"
        row["e2e_ms"] = (time.monotonic_ns() - started_ns) / 1_000_000.0
        results.append(row)
        _write_json(output / "task_results.json", results)

    # Preserve the fixed plan's unselected positions in the batch result.
    selected_keys = {(item.phase, item.family, item.profile) for item in selected}
    for item in _positions():
        key = (item.phase, item.family, item.profile)
        if key not in selected_keys:
            results.append({**asdict(item), "status": "not_started", "reason": "outside_requested_phase_family"})
    _write_json(output / "task_results.json", results)
    summary = _summarize_payload(output)
    _write_json(output / "summary.json", summary)
    (output / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    return 0 if all(row.get("status") == "success" for row in results if row.get("status") != "not_started" and row.get("phase") == args.phase and (args.family == "all" or row.get("family") == args.family)) else 1


def _summarize_payload(batch_root: Path) -> dict[str, Any]:
    results_path = batch_root / "task_results.json"
    rows = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    started = [row for row in rows if row.get("status") not in {"not_started", "selected"}]
    mechanisms: dict[str, dict[str, int]] = {}
    for row in started:
        profile = str(row.get("profile", ""))
        bucket = mechanisms.setdefault(profile, {})
        status = str(row.get("status"))
        bucket[status] = bucket.get(status, 0) + 1
    return {
        "schema_version": "statebus.contest_model_assist_probe_summary.v1",
        "batch_root": str(batch_root.resolve()),
        "planned_count": len(rows),
        "started_count": len(started),
        "status_counts": {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in ("success", "runtime_fail", "quality_fail", "timeout", "blocked", "not_started")
        },
        "mechanism_status": mechanisms,
        "results": rows,
        "performance_claims": "not_reported",
    }


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Contest model-assist probe summary",
        "",
        f"- batch: `{summary['batch_root']}`",
        f"- started: `{summary['started_count']}` / planned `{summary['planned_count']}`",
        "- performance claims: not reported",
        "",
        "| phase | family | task | profile | status | slot |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary["results"]:
        lines.append(
            f"| {row.get('phase','')} | {row.get('family','')} | {row.get('task_id','')} | "
            f"{row.get('profile','')} | {row.get('status','')} | `{row.get('slot_root','')}` |"
        )
    return "\n".join(lines) + "\n"


def _summarize_only(path: Path) -> int:
    print(json.dumps(_summarize_payload(path.resolve()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("standard", "kv"), default="standard")
    parser.add_argument("--family", choices=("finance", "service_ops", "all"), default="finance")
    parser.add_argument("--source-label", choices=SOURCE_LABELS, default="candidate")
    parser.add_argument("--output", type=Path)
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--dry-run", action="store_true")
    execution.add_argument("--live", action="store_true")
    parser.add_argument("--summarize", type=Path)
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--max-context", type=int, default=8192)
    parser.add_argument("--provider-timeout-s", type=float, default=480.0)
    parser.add_argument("--embedding-model", type=Path, default=Path("/statebus/models/Qwen3-Embedding-0.6B"))
    parser.add_argument("--embedding-device", default="cuda:0")
    parser.add_argument("--tokenizer-path", type=Path, default=Path("/data/models/Qwen3-32B"))
    args = parser.parse_args(argv)
    if args.summarize is not None:
        return _summarize_only(args.summarize)
    if args.output is None:
        parser.error("--output is required for --dry-run, --live, or plan-only")
    if args.dry_run or not args.live:
        return _print_plan(args)
    return _run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
