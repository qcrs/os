"""Bounded Memory/State mechanism experiment runner for Contest design 40/41."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
import time

from statebus.benchmark.contest_dsl_mainline import (
    DEFAULT_PROVIDER_TIMEOUT_S,
    run_slot,
    write_json,
)
from statebus.benchmark.contest_dsl_metrics import collect_slot_metrics, read_events
from statebus.benchmark.contest_dsl_taskpack import (
    SIMPLE_PROFILE,
    generate_sealed,
    publish_required_files,
    task_contract,
)
from statebus.benchmark.semantic_holdout import (
    load_semantic_holdout_cases,
    run_semantic_state_ablation,
)

MEMORY_TASKS = {
    "finance": ("F01", "F02", "F06", "F07"),
    "service_ops": ("O01", "O02", "O06", "O07"),
}
STATE_TASKS = ("semantic-holdout-s1", "semantic-holdout-s5", "semantic-holdout-s4", "semantic-holdout-s8")
STATE_SMOKE_TASKS = (*STATE_TASKS, "semantic-holdout-s2")
VARIANTS = ("off", "on")


def _memory_selection(family: str, task_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    if family not in {"all", *MEMORY_TASKS}:
        raise ValueError(f"contest_memory_family_invalid:{family}")
    families = tuple(MEMORY_TASKS) if family == "all" else (family,)
    normalized = tuple(dict.fromkeys(task_ids))
    if not normalized:
        return {current: MEMORY_TASKS[current] for current in families}
    selected: dict[str, tuple[str, ...]] = {}
    for current in families:
        current_tasks = tuple(task_id for task_id in normalized if task_id in MEMORY_TASKS[current])
        if current_tasks:
            selected[current] = current_tasks
    unknown = [task_id for task_id in normalized if not any(task_id in tasks for tasks in MEMORY_TASKS.values())]
    outside = [
        task_id for task_id in normalized
        if family != "all" and task_id not in MEMORY_TASKS[family]
    ]
    if unknown or outside or not selected:
        invalid = ",".join(dict.fromkeys([*unknown, *outside]))
        raise ValueError(f"contest_memory_task_selection_invalid:{invalid}")
    return selected


def experiment_plan(
    *,
    mechanism: str = "all",
    family: str = "all",
    task_ids: tuple[str, ...] = (),
    case_ids: tuple[str, ...] = (),
    memory_variants: tuple[str, ...] = VARIANTS,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if mechanism in {"memory", "all"}:
        normalized_variants = tuple(dict.fromkeys(memory_variants))
        if not normalized_variants or any(variant not in VARIANTS for variant in normalized_variants):
            raise ValueError("contest_memory_variant_selection_invalid")
        for current_family, selected_tasks in _memory_selection(family, task_ids).items():
            for variant in normalized_variants:
                for task_id in selected_tasks:
                    rows.append({"experiment": "memory", "family": current_family, "task_id": task_id,
                                 "variant": variant, "order": MEMORY_TASKS[current_family].index(task_id) + 1})
    if mechanism in {"state", "all"}:
        selected = tuple(dict.fromkeys(case_ids)) or STATE_TASKS
        invalid = [task_id for task_id in selected if task_id not in STATE_SMOKE_TASKS]
        if invalid:
            raise ValueError(f"contest_state_case_selection_invalid:{','.join(invalid)}")
        for task_id in selected:
            for variant in VARIANTS:
                rows.append({"experiment": "state", "task_id": task_id, "variant": variant})
    keys = [(row["experiment"], row["task_id"], row["variant"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("contest_mechanism_plan_duplicate_slot")
    return rows


def run_offline_validation(output: Path, *, plan: list[dict[str, object]]) -> dict[str, object]:
    """Validate bounded wiring without provider or embedding execution."""

    validation_root = output / "offline-validation"
    validation_root.mkdir(parents=True, exist_ok=False)
    sealed_root = validation_root / "sealed"
    generate_sealed(sealed_root, profile=SIMPLE_PROFILE)
    memory_checks: list[dict[str, object]] = []
    memory_rows = [row for row in plan if row["experiment"] == "memory"]
    for task_id in dict.fromkeys(str(row["task_id"]) for row in memory_rows):
        task_root = validation_root / "published" / task_id
        published = publish_required_files(
            sealed_root, task_root, task_id, profile=SIMPLE_PROFILE,
        )
        contract = task_contract(task_id, profile=SIMPLE_PROFILE)
        relative = sorted(path.relative_to(task_root).as_posix() for path in published)
        expected = sorted(f"{contract.family}/{name}" for name in contract.required_files)
        memory_checks.append({
            "task_id": task_id,
            "required_history": list(contract.required_history),
            "required_files": list(contract.required_files),
            "published_files": relative,
            "only_required_files_published": relative == expected,
        })
    available_cases = {case.task_id for case in load_semantic_holdout_cases()}
    state_ids = list(dict.fromkeys(
        str(row["task_id"]) for row in plan if row["experiment"] == "state"
    ))
    state_checks = {
        "case_ids": state_ids,
        "modes": list(VARIANTS),
        "all_cases_registered": set(state_ids) <= available_cases,
        "consumer_off_not_requested": True,
    }
    isolation = [
        {
            "variant": variant,
            "transport": "typed",
            "semantic_state": "on",
            "memory": variant,
        }
        for variant in VARIANTS
        if any(row["experiment"] == "memory" and row["variant"] == variant for row in plan)
    ]
    checks = {
        "plan_unique": len(plan) == len({
            (row["experiment"], row["task_id"], row["variant"]) for row in plan
        }),
        "memory_publication_exact": all(
            bool(item["only_required_files_published"]) for item in memory_checks
        ),
        "memory_tasks_have_no_history_dependency": all(
            not item["required_history"] for item in memory_checks
        ),
        "memory_only_switches_memory": all(
            item["transport"] == "typed" and item["semantic_state"] == "on"
            for item in isolation
        ),
        "state_two_mode_selection_valid": bool(state_checks["all_cases_registered"]),
    }
    result = {
        "schema_version": "statebus.contest_mechanism_offline_validation.v1",
        "mode": "offline",
        "provider_requests_made": False,
        "embedding_loaded": False,
        "live_results_produced": False,
        "plan": plan,
        "memory": {"checks": memory_checks, "mechanism_configuration": isolation},
        "state": state_checks,
        "checks": checks,
        "ok": all(checks.values()),
    }
    write_json(validation_root / "offline-validation.json", result)
    return result


def _memory_details(slot_root: Path, metrics: dict[str, object], *, variant: str) -> dict[str, object]:
    events = read_events(slot_root / "memory-events.jsonl")
    queries = [event for event in events if event.get("event") == "query"]
    consumed = [event for event in events if event.get("event") == "consume" and event.get("consume_receipt")]
    sources = list(dict.fromkeys(str(event.get("source_task_id")) for event in consumed if event.get("source_task_id")))
    decisions = [decision for event in queries for decision in event.get("decisions", ()) if isinstance(decision, dict)]
    reason = None
    if variant == "off":
        reason = "memory_disabled_control"
    elif consumed:
        reason = "validated_replay_consumed" if any(event.get("replay_count") for event in consumed) else "memory_consumed_without_replay"
    elif queries and not any(int(event.get("candidate_count", 0) or 0) > 0 for event in queries):
        reason = "no-match"
    elif decisions:
        reason = ";".join(sorted({str(item.get("reason", item.get("verdict", "compatibility_not_approved"))) for item in decisions}))
    else:
        reason = "no_consumption_observed"
    rows_observed = (slot_root / "rows.json").is_file()
    input_lineage = slot_root / "input-lineage.json"
    return {
        "query_count": sum(int(event.get("query_count", 0) or 0) for event in queries),
        "candidate_hit_count": sum(int(int(event.get("candidate_count", 0) or 0) > 0) for event in queries),
        "actual_consumed": bool(consumed),
        "validated_replay": any(int(event.get("replay_count", 0) or 0) > 0 for event in consumed),
        "executor_requests": metrics.get("executor_request_count"),
        "method_source_task": sources[0] if len(sources) == 1 else sources or None,
        "compatibility_or_nonreuse_reason": reason,
        "current_input_execution_observed": bool(rows_observed and input_lineage.is_file()),
    }


def run_memory_chain(
    output: Path,
    *,
    family: str,
    variant: str,
    mode: str,
    task_ids: tuple[str, ...] | None = None,
    model: str = "qwen3-32b",
    base_url: str = "http://127.0.0.1:53334/v1",
    max_context: int = 8192,
    provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
    embedding_mode: str = "deterministic",
    embedding_model: Path | None = None,
    embedding_device: str | None = None,
    tokenizer_path: Path | None = None,
) -> dict[str, object]:
    if family not in MEMORY_TASKS:
        raise ValueError(f"contest_memory_family_invalid:{family}")
    if variant not in VARIANTS:
        raise ValueError(f"contest_memory_variant_invalid:{variant}")
    selected = task_ids or MEMORY_TASKS[family]
    if not selected or any(task_id not in MEMORY_TASKS[family] for task_id in selected):
        raise ValueError("contest_memory_task_selection_invalid")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    generate_sealed(output / "sealed", profile=SIMPLE_PROFILE)
    write_json(output / "manifest.json", {
        "schema_version": "statebus.contest_mechanism_memory.v1", "experiment": "memory",
        "family": family, "variant": variant, "mode": mode, "task_ids": list(selected),
        "memory_namespace": str(output / "memory"), "transport": "typed", "semantic_state": "on",
        "memory": variant, "memory_query_enabled": variant == "on",
    })
    ledger = []
    history: dict[str, object] = {}
    memory_root = output / "memory"
    for task_id in selected:
        slot_root = output / "slots" / task_id
        row = {"experiment": "memory", "family": family, "task_id": task_id, "variant": variant,
               "status": "running", "source_path": str(slot_root)}
        started = time.monotonic_ns()
        write_json(output / "ledger.json", [*ledger, row])
        try:
            published = publish_required_files(output / "sealed", output / "public", task_id, profile=SIMPLE_PROFILE)
            write_json(slot_root.parent / f"{task_id}-published-inputs.json", [str(path) for path in published])
            result = run_slot(
                slot_root, output / "public", task_id, history=history, variant="SB-FULL",
                mode=mode, model=model, base_url=base_url, max_context=max_context,
                provider_timeout_s=provider_timeout_s, embedding_mode=embedding_mode,
                embedding_model=embedding_model, embedding_device=embedding_device,
                tokenizer_path=tokenizer_path, profile=SIMPLE_PROFILE,
                memory_enabled=variant == "on", semantic_state_mode="on",
            )
            observed_rows = result.pop("rows")
            row.update(result)
            if row["status"] == "success":
                history[task_id] = observed_rows
        except Exception as exc:
            row.update(status="runtime_fail", returncode=1, quality=False, repair=None,
                       reason=f"{type(exc).__name__}:{exc}", failure_codes=[str(exc).split(":", 1)[0]])
            row["metrics"] = collect_slot_metrics(slot_root)
        row["e2e_ms"] = (time.monotonic_ns() - started) / 1e6
        metrics = row.get("metrics", {})
        row["memory"] = _memory_details(slot_root, metrics, variant=variant)
        row["memory_namespace"] = str(memory_root)
        ledger.append(row)
        write_json(slot_root / "task-row.json", row)
        write_json(output / "ledger.json", ledger)
    summary = {
        "schema_version": "statebus.contest_mechanism_memory_summary.v1",
        "experiment": "memory", "family": family, "variant": variant, "mode": mode,
        "planned": len(selected), "started": len(ledger),
        "passed": sum(row["status"] == "success" for row in ledger),
        "rows": ledger,
    }
    write_json(output / "summary.json", summary)
    return summary


def run_state(output: Path, *, case_ids: tuple[str, ...], embedding_model_path: str,
              embedding_device: str, tokenizer_path: str | None = None) -> dict[str, object]:
    return run_semantic_state_ablation(
        output_root=output, embedding_model_path=embedding_model_path,
        embedding_device=embedding_device, case_ids=case_ids or STATE_TASKS,
        modes=VARIANTS, tokenizer_path=tokenizer_path, run_name="ablation",
        # Keep Retriever candidate generation identical across both variants;
        # the mechanism experiment fixes only the Executor-side consumer
        # policy so StateRef selection is independently observable.
        executor_top_k=2, executor_budget_bytes=0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mechanism", choices=("memory", "state", "all"), default="all")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--family", choices=("all", "finance", "service_ops"), default="all")
    parser.add_argument("--memory-variant", choices=("off", "on", "all"), default="all")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--max-context", type=int, default=8192)
    parser.add_argument("--provider-timeout-s", type=float, default=DEFAULT_PROVIDER_TIMEOUT_S)
    parser.add_argument("--embedding-mode", choices=("deterministic", "local"), default="deterministic")
    parser.add_argument("--embedding-model", type=Path)
    parser.add_argument("--embedding-device")
    parser.add_argument("--tokenizer-path", type=Path)
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    memory_variants = VARIANTS if args.memory_variant == "all" else (args.memory_variant,)
    try:
        plan = experiment_plan(
            mechanism=args.mechanism,
            family=args.family,
            task_ids=tuple(args.task_id),
            case_ids=tuple(args.case_id),
            memory_variants=memory_variants,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({"executed": False, "configuration": vars(args), "plan": plan}, ensure_ascii=False, default=str, indent=2))
        return 0
    if any((args.output / name).exists() for name in ("memory", "state", "offline-validation")):
        parser.error(f"experiment output already exists below: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "live" and (args.embedding_mode != "local" or not args.embedding_model or not args.embedding_device):
        parser.error("live mode requires local embedding model/device")
    invoked_argv = [sys.executable, "-m", "statebus.benchmark.contest_mechanisms", *(sys.argv[1:] if argv is None else argv)]
    write_json(args.output / "manifest.json", {
        "schema_version": "statebus.contest_mechanism_batch.v1",
        "mode": args.mode,
        "mechanism": args.mechanism,
        "plan": plan,
        "configuration": vars(args),
        "argv": invoked_argv,
        "command": shlex.join(str(value) for value in invoked_argv),
        "host_output": os.environ.get("STATEBUS_CONTEST_HOST_OUTPUT", str(args.output)),
        "environment": {
            "host_model": args.model,
            "vllm_model_root": "/data/models/Qwen3-32B",
            "vllm_physical_gpu": 2,
            "api_base_url": args.base_url,
            "context_tokens": args.max_context,
            "container": os.environ.get("STATEBUS_CONTAINER_NAME", "statebus-runtime"),
            "container_source": "/workspace/statebus/os",
            "runtime_python": sys.executable,
            "embedding_model": str(args.embedding_model) if args.embedding_model else None,
            "embedding_physical_gpu": 1,
            "embedding_container_device": args.embedding_device,
            "os": "openEuler 24.03 LTS-SP3",
        },
        "formal_default_matrix": len(experiment_plan()) == 24,
    })
    if args.mode == "offline":
        return 0 if run_offline_validation(args.output, plan=plan)["ok"] else 1
    overall_ok = True
    if args.mechanism in {"memory", "all"}:
        for family, family_tasks in _memory_selection(args.family, tuple(args.task_id)).items():
            for variant in memory_variants:
                summary = run_memory_chain(
                    args.output / "memory" / family / variant,
                    family=family, variant=variant, mode=args.mode, task_ids=family_tasks,
                    model=args.model, base_url=args.base_url, max_context=args.max_context,
                    provider_timeout_s=args.provider_timeout_s, embedding_mode=args.embedding_mode,
                    embedding_model=args.embedding_model, embedding_device=args.embedding_device,
                    tokenizer_path=args.tokenizer_path,
                )
                overall_ok = overall_ok and summary["passed"] == summary["planned"]
    if args.mechanism in {"state", "all"}:
        summary = run_state(args.output / "state", case_ids=tuple(args.case_id),
                            embedding_model_path=str(args.embedding_model or ""),
                            embedding_device=str(args.embedding_device or ""),
                            tokenizer_path=str(args.tokenizer_path) if args.tokenizer_path else None)
        overall_ok = overall_ok and bool(summary["ok"])
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
