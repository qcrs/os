"""Stage 2 mechanism runner for the contest measurement contract.

The runner owns the stage ledger and task plans.  Existing Runtime, Memory,
semantic-state, sandbox, validator and citation implementations remain the
execution authorities; this module only composes them and records evidence.

It has two explicit modes:

* ``--dry-run`` / ``--offline`` build and audit the plan without a model call.
* live mode runs only the requested mechanism and selected smoke slots.  A
  full Stage 2 campaign is opt-in and never implied by ``--stage 3``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any, Iterable, Mapping

from statebus.benchmark.stage2_contract import public_case_projection, validate_public_case
from statebus.benchmark.contest_stage1_taskpack import FAMILIES, PERIODS
from statebus.utils import stable_json_dumps

SCHEMA_VERSION = "statebus.contest_stage2_mechanism.v1"
PLAN_SCHEMA_VERSION = "statebus.contest_stage2_task_plan.v1"
RAW_SCHEMA_VERSION = "statebus.contest_stage2_raw.v1"
FORMAL_MECHANISMS = ("memory", "state", "communication", "codeact", "cross-agent")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{time.time_ns()}")
    temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json_dumps(payload) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_digest(root: Path) -> str:
    """Hash source inputs only; generated runs must not alter source identity."""
    entries: list[str] = []
    source_roots = (root / "statebus", root / "scripts", root / "deploy")
    for source_root in source_roots:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            entries.append(f"{_sha256_file(path)}  {relative.as_posix()}\n")
    return hashlib.sha256("".join(entries).encode("utf-8")).hexdigest()


def _stage1_summary(stage1_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(stage1_root.glob("stage1/*/acceptance.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({"path": str(path), "status": "invalid", "error": f"{type(exc).__name__}:{exc}"})
            continue
        rows.append({
            "path": str(path),
            "variant": payload.get("variant"),
            "ok": payload.get("ok"),
            "formal_headline_eligible": payload.get("formal_headline_eligible"),
            "semantic_review_required": payload.get("semantic_review_required"),
            "effective_configuration_hash": payload.get("effective_configuration_hash"),
            "report_contract_version": payload.get("report_contract_version"),
        })
    return {
        "root": str(stage1_root),
        "exists": stage1_root.is_dir(),
        "acceptance_files": rows,
        "acceptance_count": len(rows),
        "source_digest": (stage1_root / "source-digest.txt").read_text(encoding="utf-8").strip()
        if (stage1_root / "source-digest.txt").is_file() else None,
    }


def _slot(
    mechanism: str,
    task_id: str,
    *,
    chain_id: str = "",
    round_index: int = 1,
    variant: str = "",
    mode: str = "",
    boundary: str = "",
    status: str = "planned",
    smoke: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "slot_id": f"{mechanism}:{task_id}:{variant or mode or round_index}",
        "mechanism": mechanism,
        "task_id": task_id,
        "chain_id": chain_id,
        "round": round_index,
        "variant": variant,
        "mode": mode,
        "expected_boundary": boundary,
        "status": status,
        "smoke_selected": smoke,
        "notes": notes,
        "denominator_class": "started_task",
    }


def memory_plan(*, smoke: bool) -> list[dict[str, Any]]:
    chains = (
        ("finance", ("F01", "F02", "F06")),
        ("service_ops", ("O01", "O02", "O06")),
    )
    variants = ("none", "validated_replay")
    rows: list[dict[str, Any]] = []
    for chain, tasks in chains:
        for variant in variants:
            for index, task_id in enumerate(tasks, 1):
                selected = (chain == "finance" and task_id in {"F01", "F02"}) if smoke else True
                boundary = {
                    1: "producer_inclusive_first_generation",
                    2: "current_input_recomputed_and_replay_decision",
                    3: "semantic_or_method_compatibility_change",
                }[index]
                rows.append(_slot(
                    "memory", task_id, chain_id=chain, round_index=index,
                    variant=variant, boundary=boundary, smoke=selected,
                    notes="Producer cost stays in the chain denominator; blocked successors remain planned.",
                ))
    return rows


def state_plan(*, smoke: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    task_ids = ("semantic-holdout-s1", "semantic-holdout-s3")
    modes = ("off", "on", "consumer_off")
    for task_id in task_ids:
        for mode in modes:
            rows.append(_slot(
                "state", task_id, chain_id=task_id, variant=mode,
                mode=mode, boundary=("active_downstream_selection" if task_id.endswith("s1") else "inactive_negative_control"),
                smoke=(task_id.endswith("s1") if smoke else True),
                notes="Inactive s3 is excluded from active benefit denominators.",
            ))
    return rows


def communication_plan(*, smoke: bool) -> list[dict[str, Any]]:
    tasks = ("F01", "F02")
    carriers = ("text", "typed")
    return [
        _slot(
            "communication", task_id, chain_id="finance", round_index=index,
            variant=carrier, mode=carrier,
            boundary="same_receiver_same_public_input",
            smoke=(task_id == "F01" if smoke else True),
            notes="Typed path must be consumed by a receiver; carrier-only microbench is supporting evidence.",
        )
        for index, task_id in enumerate(tasks, 1)
        for carrier in carriers
    ]


def codeact_plan(*, smoke: bool) -> list[dict[str, Any]]:
    # Candidate slots are explicit even when no legal off path is registered.
    return [
        _slot(
            "codeact", task_id, chain_id="finance", round_index=index,
            variant=policy, mode=policy,
            boundary="same_output_contract_same_validator",
            status="not_applicable", smoke=(smoke and index == 1),
            notes="Requires a legal common non-CodeAct route; route denial is not a failure row.",
        )
        for index, task_id in enumerate(("F01", "F02"), 1)
        for policy in ("on", "off")
    ]


def cross_agent_plan(*, smoke: bool) -> list[dict[str, Any]]:
    return [_slot(
        "cross-agent", "F10", chain_id="finance", round_index=10,
        variant="producer_executor_to_consumer_summarizer",
        boundary="source_agent_distinct_from_consumer_agent",
        status="blocked", smoke=smoke,
        notes="Must have MemoryRef, Grant, receipt, current-input recompute and source artifact chain.",
    )]


def build_plan(mechanism: str, *, smoke: bool) -> list[dict[str, Any]]:
    if mechanism == "all":
        rows: list[dict[str, Any]] = []
        for name in FORMAL_MECHANISMS:
            rows.extend(build_plan(name, smoke=smoke))
        return rows
    if mechanism == "memory":
        return memory_plan(smoke=smoke)
    if mechanism == "state":
        return state_plan(smoke=smoke)
    if mechanism == "communication":
        return communication_plan(smoke=smoke)
    if mechanism == "codeact":
        return codeact_plan(smoke=smoke)
    if mechanism == "cross-agent":
        return cross_agent_plan(smoke=smoke)
    raise ValueError(f"unknown_mechanism:{mechanism}")


def _selected_rows(plan: Iterable[Mapping[str, Any]], *, smoke: bool) -> list[dict[str, Any]]:
    rows = [dict(item) for item in plan if not smoke or item.get("smoke_selected")]
    return rows


def _public_case_audit() -> dict[str, Any]:
    """Exercise the public projection against a minimal public-only object.

    Stage 2 taskpack inputs are supplied by the existing Stage 1 publisher at
    live time.  This audit protects the runner itself from embedding scorer or
    oracle metadata in its communication/task manifest.
    """
    sample = type("Sample", (), {})()
    spec = type("Spec", (), {})()
    spec.arguments = {"csv_path": "finance/actual_2026-01.csv", "expected": {"revenue": 1}}
    spec.task_family = "continuous_csv_table_analysis"
    spec.intent_op = "finance_monthly_review"
    spec.required_outputs = ("per_entity_metrics", "source_locator")
    sample.task_id = "F01"
    sample.task_family = spec.task_family
    sample.dataset_id = "stage1-finance-2026-01"
    sample.dataset_version = "synthetic-dev-v1"
    sample.dataset_split = "development"
    sample.request_text = "Review the published current input."
    sample.canonical_task_spec = spec
    projected = public_case_projection(sample)
    errors = validate_public_case(projected)
    return {
        "status": "passed" if not errors else "failed",
        "errors": list(errors),
        "case": projected,
        "gold_fields_removed": "expected" not in stable_json_dumps(projected),
    }


def _offline_communication_contract(root: Path, plan: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in _selected_rows(plan, smoke=False):
        payload = {
            "task_id": item["task_id"],
            "metric_name": "public_metric",
            "rows": [{"row_id": "public-row-1", "value": "observed"}],
            "source_locator": "public/source#section",
        }
        started = time.perf_counter_ns()
        if item["variant"] == "text":
            encoded = stable_json_dumps(payload)
            decoded = json.loads(encoded)
            text_chars = len(encoded)
            typed_bytes = None
            control_bytes = 0
            wire_bytes = len(encoded.encode("utf-8"))
        else:
            encoded_bytes = stable_json_dumps(payload).encode("utf-8")
            decoded = json.loads(encoded_bytes.decode("utf-8"))
            text_chars = 0
            typed_bytes = len(encoded_bytes)
            control_bytes = len(stable_json_dumps({"schema": "stage2.typed.v1"}).encode("utf-8"))
            wire_bytes = typed_bytes + control_bytes
        elapsed = (time.perf_counter_ns() - started) / 1e6
        rows.append({
            "slot_id": item["slot_id"], "task_id": item["task_id"], "variant": item["variant"],
            "receiver_consumed": decoded == payload, "message_count": 1,
            "handoff_text_chars": text_chars, "handoff_text_tokens": None,
            "typed_frame_bytes": typed_bytes, "control_frame_bytes": control_bytes,
            "wire_bytes": wire_bytes, "encode_decode_ms": elapsed,
            "provider_usage": {"status": "not_applicable", "reason": "offline_contract"},
            "quality": {"status": "not_scored", "reason": "no_provider_task_execution"},
            "terminal_class": "success" if decoded == payload else "runtime_fail",
            "status": "success" if decoded == payload else "failed",
            "claim_scope": "offline_receiver_contract_only",
        })
    write_json(root / "communication" / "offline" / "rows.json", rows)
    return {
        "status": "passed" if all(row["receiver_consumed"] for row in rows) else "failed",
        "rows": rows,
        "claim_scope": "offline_receiver_contract_only",
        "task_level_live_equivalent": False,
    }


def _offline_codeact_contract(plan: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [{
        "slot_id": item["slot_id"], "task_id": item["task_id"], "variant": item["variant"],
        "status": "not_applicable", "terminal_class": "unsupported",
        "reason": "no_validated_legal_common_route", "blocking": False,
    } for item in plan]
    return {"status": "not_applicable", "blocking": False, "rows": rows,
            "claim_scope": "no_codeact_causal_comparison"}


def _offline_cross_agent_contract(plan: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [{
        "slot_id": item["slot_id"], "task_id": item["task_id"],
        "status": "blocked", "terminal_class": "unsupported",
        "source_agent": "executor", "consumer_agent": "summarizer",
        "source_agent_distinct": True,
        "memory_ref": None, "grant": None, "consumption_receipt": None,
        "reason": "live_cross_agent_caller_not_closed",
    } for item in plan]
    return {"status": "blocked", "blocking": True, "rows": rows,
            "claim_scope": "cross_agent_memory_not_demonstrated"}


def _offline_state_contract() -> dict[str, Any]:
    from statebus.benchmark.semantic_holdout import load_semantic_holdout_cases
    cases = load_semantic_holdout_cases()
    shapes = Counter(str(case.sample.scenario_tags[0]) for case in cases)
    expected = Counter({"narrative_only": 3, "table_only": 3, "mixed_narrative_table": 2})
    return {
        "status": "passed" if len(cases) == 8 and shapes == expected else "failed",
        "case_count": len(cases), "input_shapes": dict(shapes),
        "formal_selection": ["semantic-holdout-s1", "semantic-holdout-s3"],
        "variant_order": ["off", "on", "consumer_off"],
        "claim_scope": "fixture_and_selection_contract_only",
    }


def _offline_memory_contract(root: Path) -> dict[str, Any]:
    from statebus.benchmark.memory_ablation import run_memory_ablation
    result_root = root / "memory" / "offline-contract"
    result = run_memory_ablation(output_root=result_root, rounds_per_family=3)
    return {
        "status": "passed" if result.get("ok") else "failed",
        "result_root": str(result_root), "result": result,
        "claim_scope": "deterministic_runtime_contract_only",
        "formal_live_equivalent": False,
    }


def _is_real_failure(detail: Mapping[str, Any]) -> bool:
    return _component_status(detail) in {"failed", "environment_fail"}


def run_offline_contracts(
    root: Path,
    mechanism: str,
    plan: list[dict[str, Any]],
    *,
    stop_on_failure: bool = False,
) -> dict[str, Any]:
    components: dict[str, Any] = {}
    runners: list[tuple[str, Any]] = []
    if mechanism in {"memory", "all"}:
        runners.append(("memory", lambda: _offline_memory_contract(root)))
    if mechanism in {"state", "all"}:
        runners.append(("state", _offline_state_contract))
    if mechanism in {"communication", "all"}:
        runners.append(("communication", lambda: _offline_communication_contract(
            root, [x for x in plan if x["mechanism"] == "communication"])))
    if mechanism in {"codeact", "all"}:
        runners.append(("codeact", lambda: _offline_codeact_contract(
            [x for x in plan if x["mechanism"] == "codeact"])))
    if mechanism in {"cross-agent", "all"}:
        runners.append(("cross-agent", lambda: _offline_cross_agent_contract(
            [x for x in plan if x["mechanism"] == "cross-agent"])))
    for name, runner in runners:
        try:
            components[name] = runner()
        except Exception as exc:
            components[name] = {"status": "failed", "error": f"{type(exc).__name__}:{exc}"}
        if stop_on_failure and _is_real_failure(components[name]):
            break
    if not stop_on_failure or not any(_is_real_failure(value) for value in components.values()):
        components["public_projection"] = _public_case_audit()
    return components


def _run_stage1_memory_smoke(
    root: Path, *, embedding_model_path: str, embedding_device: str, smoke: bool = True,
    stop_on_failure: bool = False,
) -> dict[str, Any]:
    """Compose the same public worker for both Memory variants and retain every slot."""
    from statebus.benchmark import contest_stage1
    slots = _selected_rows(memory_plan(smoke=smoke), smoke=smoke)
    rows = [{**slot, "status": "not_started", "ok": False, "provider": None,
             "elapsed_ms": None} for slot in slots]
    results: list[dict[str, Any]] = []
    for policy in ("none", "validated_replay"):
        output = root / "memory" / "live" / policy
        args = argparse.Namespace(
            output_root=output, dry_run=False, plan_output=None, profile="SB-FULL",
            family="finance" if smoke else "all", sb_memory_policy=policy,
            chain_tasks=("F01", "F02") if smoke else ("F01", "F02", "F06", "O01", "O02", "O06"),
            block_failed_chain=True, stop_on_failure=stop_on_failure,
            embedding_model_path=embedding_model_path, embedding_device=embedding_device,
            worker=False, task=None,
        )
        started = time.monotonic_ns()
        try:
            code = contest_stage1.run(args)
            result = {
                "variant": policy, "returncode": int(code), "status": "success" if code == 0 else "failed",
                "output_root": str(output), "elapsed_ms": (time.monotonic_ns() - started) / 1e6,
            }
        except Exception as exc:
            result = {
                "variant": policy, "returncode": None, "status": "environment_fail",
                "output_root": str(output), "elapsed_ms": (time.monotonic_ns() - started) / 1e6,
                "error": f"{type(exc).__name__}:{exc}", "traceback": traceback.format_exc(),
            }
        results.append(result)
        ledger_path = output / "ledger.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.is_file() else []
        by_task = {entry["task_id"]: entry for entry in ledger}
        for row in rows:
            if row["variant"] != policy or row["task_id"] not in by_task:
                continue
            entry = by_task[row["task_id"]]
            row.update(entry)
            row["variant"] = policy
            result_path = Path(entry["result_path"]) if entry.get("result_path") else None
            task_result = json.loads(result_path.read_text()) if result_path and result_path.is_file() else {}
            row.update({
                "source_artifact_hash": task_result.get("source_artifact_hash"),
                "execution_output_artifact_hash": task_result.get("execution_output_artifact_hash"),
                "memory_query_results": task_result.get("memory_query_results"),
                "memory_consumption_records": task_result.get("memory_consumption_records"),
                "memory_commit_decision": task_result.get("memory_commit_decision"),
                "external_score_passed": task_result.get("external_score_passed"),
            })
        if stop_on_failure and result["status"] != "success":
            break
    started_count = sum(row["status"] not in {"not_started", "blocked_by_prior_failure"} for row in rows)
    passed_count = sum(bool(row["ok"]) for row in rows)
    return {
        "status": "passed" if len(results) == 2 and all(r["status"] == "success" for r in results)
                  and passed_count == len(rows) else "failed",
        "variants": results, "rows": rows,
        "claim_scope": "live_f01_f02_memory_pair" if smoke else "live_two_public_memory_chains",
        "formal_required_executions": 12, "planned_executions": len(rows),
        "started_executions": started_count, "passed_executions": passed_count,
        "smoke_executions": started_count if smoke else 0,
    }


def _run_state_smoke(
    root: Path, *, embedding_model_path: str, embedding_device: str, smoke: bool = True,
) -> dict[str, Any]:
    from statebus.benchmark.semantic_holdout import run_semantic_state_ablation
    selected_cases = ("semantic-holdout-s1",) if smoke else ("semantic-holdout-s1", "semantic-holdout-s3")
    try:
        result = run_semantic_state_ablation(
            output_root=root / "state" / "live",
            embedding_model_path=embedding_model_path,
            embedding_device=embedding_device,
            case_ids=selected_cases,
        )
        slots = {(row["task_id"], row["variant"]): row for row in state_plan(smoke=smoke)}
        rows = [
            {**slots[(row["task_id"], row["variant"])], **row,
             "status": "success" if row.get("ok") else "failed"}
            for row in result.get("rows", [])
        ]
        return {
            "status": "passed" if result.get("ok") else "failed",
            "result": result, "rows": rows,
            "claim_scope": (
                "live_semantic_state_s1_three_variant_pair"
                if smoke else "live_semantic_state_s1_s3_three_variant_pairs"
            ),
            "formal_required_executions": 6,
            "smoke_executions": 3 if smoke else 6,
        }
    except Exception as exc:
        return {"status": "environment_fail", "error": f"{type(exc).__name__}:{exc}",
                "traceback": traceback.format_exc(), "claim_scope": "live_semantic_state_s1_three_variant_pair"}


def _run_communication_smoke(root: Path, stage1_root: Path, plan: list[dict[str, Any]]) -> dict[str, Any]:
    # Stage 1 has real measured callbacks, but not a matched text/typed
    # receiver.  Keep that boundary explicit instead of promoting carrier data
    # to a task-level causal result.
    source_rows = []
    for path in sorted(stage1_root.glob("stage1/*/summary.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_rows.extend(summary.get("ledger", []))
    available = [row for row in source_rows if row.get("task_id") == "F01"]
    return {
        "status": "diagnostic_only" if available else "not_started",
        "source_stage1_rows": len(available),
        "planned_smoke_slots": len([row for row in plan if row.get("smoke_selected")]),
        "claim_scope": "stage1_callback_observation_no_matched_text_typed_receiver",
        "task_level_live_equivalent": False,
        "reason": "matched_task_level_adapter_not_closed",
    }


def _run_codeact_smoke(plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "not_applicable", "blocking": False,
        "rows": _offline_codeact_contract(plan)["rows"],
        "claim_scope": "no_codeact_causal_comparison",
    }


def _run_cross_agent_smoke(plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "blocked", "blocking": True,
        "rows": _offline_cross_agent_contract(plan)["rows"],
        "claim_scope": "cross_agent_memory_not_demonstrated",
    }


def run_live_components(
    root: Path,
    stage1_root: Path,
    mechanism: str,
    plan: list[dict[str, Any]],
    *,
    embedding_model_path: str,
    embedding_device: str,
    smoke: bool = True,
    stop_on_failure: bool = False,
) -> dict[str, Any]:
    components: dict[str, Any] = {}
    runners: list[tuple[str, Any]] = []
    if mechanism in {"memory", "all"}:
        runners.append(("memory", lambda: _run_stage1_memory_smoke(
            root, embedding_model_path=embedding_model_path, embedding_device=embedding_device, smoke=smoke,
            stop_on_failure=stop_on_failure)))
    if mechanism in {"state", "all"}:
        runners.append(("state", lambda: _run_state_smoke(
            root, embedding_model_path=embedding_model_path, embedding_device=embedding_device, smoke=smoke)))
    if mechanism in {"communication", "all"}:
        runners.append(("communication", lambda: _run_communication_smoke(
            root, stage1_root, [x for x in plan if x["mechanism"] == "communication"])))
    if mechanism in {"codeact", "all"}:
        runners.append(("codeact", lambda: _run_codeact_smoke(
            [x for x in plan if x["mechanism"] == "codeact"])))
    if mechanism in {"cross-agent", "all"}:
        runners.append(("cross-agent", lambda: _run_cross_agent_smoke(
            [x for x in plan if x["mechanism"] == "cross-agent"])))
    for name, runner in runners:
        components[name] = runner()
        if stop_on_failure and _is_real_failure(components[name]):
            break
    for row in plan:
        if smoke and not row.get("smoke_selected"):
            continue
        detail = components.get(row["mechanism"], {})
        observations = {item["slot_id"]: item for item in detail.get("rows", [])}
        observed = observations.get(row["slot_id"])
        # A component-level diagnostic or failure does not prove a task ran.
        row["status"] = observed["status"] if observed else "not_started"
    return components


def _component_status(component: Mapping[str, Any]) -> str:
    return str(component.get("status", "unknown"))


def build_acceptance(*, mechanism: str, smoke: bool, plan: list[dict[str, Any]], components: Mapping[str, Any], stage1: Mapping[str, Any], preflight: Mapping[str, Any] | None, live: bool) -> dict[str, Any]:
    statuses = {name: _component_status(value) for name, value in components.items()}
    blocking = [name for name, value in components.items() if value.get("blocking")]
    failed = [name for name, status in statuses.items() if status in {"failed", "environment_fail"}]
    formal_ready = (
        not smoke and live and not blocking and not failed
        and all(statuses.get(name) in {"passed", "diagnostic_only", "not_applicable"} for name in statuses)
        and statuses.get("memory") == "passed"
        and statuses.get("state") == "passed"
        and statuses.get("communication") == "passed"
        and statuses.get("cross-agent") == "passed"
    )
    return {
        "schema_version": "statebus.contest_stage2_acceptance.v1",
        "mechanism": mechanism,
        "run_mode": "live_smoke" if live and smoke else "live_campaign" if live else "offline_contract",
        "ok": not failed and not (live and blocking),
        "formal_stage2_ready": bool(formal_ready),
        "smoke_passed": bool(
            live and smoke and not failed and not blocking
            and any(statuses.get(name) == "passed" for name in FORMAL_MECHANISMS)
            and all(statuses.get(name) in {"passed", "not_applicable"}
                    for name in FORMAL_MECHANISMS if name in statuses)
        ),
        "semantic_review_required": True,
        "not_started": [row["slot_id"] for row in plan if row.get("status") == "not_started" or (row.get("status") == "planned" and (not smoke or not row.get("smoke_selected")))],
        "blocked": blocking + [row["slot_id"] for row in plan if row.get("status") == "blocked"],
        "not_applicable": [row["slot_id"] for row in plan if row.get("status") == "not_applicable"] + [name for name, status in statuses.items() if status == "not_applicable"],
        "components": statuses,
        "component_details": dict(components),
        "planned_count": len(plan),
        "selected_count": sum(bool(row.get("smoke_selected")) for row in plan) if smoke else len(plan),
        "stage1_context": stage1,
        "preflight": preflight or {"status": "not_run"},
        "claim_scope": "stage2_mechanism_evidence_only",
        "formal_campaign_executed": bool(live and not smoke),
        "stage3_allowed": bool(formal_ready),
    }


def run_stage2(
    *, output_root: Path, stage1_root: Path, mechanism: str, smoke: bool,
    offline: bool, stop_on_failure: bool, profile: str, embedding_model_path: str,
    embedding_device: str, preflight: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if output_root.exists():
        if not output_root.is_dir():
            raise FileExistsError(f"stage2_output_root_not_directory:{output_root}")
        allowed_bootstrap = {"source-digest.txt", "preflight.log", "preflight.json", "stage2.log"}
        unexpected = [path.name for path in output_root.iterdir() if path.name not in allowed_bootstrap]
        if unexpected:
            raise FileExistsError(f"stage2_output_root_not_empty:{output_root}:{','.join(sorted(unexpected))}")
    else:
        output_root.mkdir(parents=True, exist_ok=False)
    if not stage1_root.is_dir():
        raise FileNotFoundError(f"stage1_root_missing:{stage1_root}")
    plan = build_plan(mechanism, smoke=smoke)
    stage1 = _stage1_summary(stage1_root)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "stage": 2, "mechanism": mechanism, "profile": profile,
        "smoke": smoke, "offline": offline, "stop_on_failure": stop_on_failure,
        "stage1_root": str(stage1_root), "output_root": str(output_root),
        "model": os.getenv("STATEBUS_LOCAL_VLLM_MODEL", "qwen3-32b"),
        "embedding_model_path": embedding_model_path, "embedding_device": embedding_device,
        "formal_counts": {name: len(build_plan(name, smoke=False)) for name in FORMAL_MECHANISMS},
        "planned_count": len(plan), "selected_count": sum(bool(row.get("smoke_selected")) for row in plan) if smoke else len(plan),
        "denominator_rules": {
            "success_rate": "passed_tasks / all_started_tasks",
            "memory_hit_rate": "candidate_or_query_hits / all_memory_queries",
            "memory_actual_reuse_rate": "actual_consumption / all_memory_queries",
            "state_benefit": "active_eligible_pairs_only",
            "missing_metrics": "missing_with_reason_never_zero_filled",
        },
        "source_classes": {
            "architecture": "os source and contracts",
            "runtime": "this run output and preflight",
            "historical": "stage1_root only",
        },
    }
    write_json(output_root / "manifest.json", manifest)
    write_json(output_root / "effective-config.json", {
        "profile": profile, "embedding_model_path": embedding_model_path,
        "embedding_device": embedding_device, "runtime_python": sys.executable,
        "service_gpu": os.getenv("STATEBUS_G6B2_SERVICE_PHYSICAL_GPU", ""),
        "embedding_gpu": os.getenv("STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU", ""),
    })
    write_json(output_root / "preflight.json", preflight or {"status": "not_run", "reason": "offline_contract"})
    (output_root / "source-digest.txt").write_text(source_digest(Path(__file__).resolve().parents[2]) + "\n", encoding="utf-8")
    write_json(output_root / "task-plan.json", {"schema_version": PLAN_SCHEMA_VERSION, "slots": plan})
    write_json(output_root / "stage1-context.json", stage1)

    offline_components = run_offline_contracts(
        output_root, mechanism, plan, stop_on_failure=stop_on_failure)
    live = not offline
    components = dict(offline_components)
    if live:
        offline_failed = any(_is_real_failure(detail) for detail in offline_components.values())
        live_components = {} if stop_on_failure and offline_failed else run_live_components(
            output_root, stage1_root, mechanism, plan,
            embedding_model_path=embedding_model_path,
            embedding_device=embedding_device,
            smoke=smoke, stop_on_failure=stop_on_failure,
        )
        components = {}
        for name in dict.fromkeys(row["mechanism"] for row in plan):
            contract = offline_components.get(name)
            if name in live_components:
                detail = dict(live_components[name])
                detail["evidence_scope"] = (
                    "diagnostic" if detail["status"] in {"diagnostic_only", "not_applicable", "blocked"}
                    else "live"
                )
                if contract is not None:
                    detail["offline_contract"] = contract
            elif contract is not None and _is_real_failure(contract):
                detail = {**contract, "evidence_scope": "offline_contract"}
            else:
                detail = {"status": "not_started", "evidence_scope": "not_started",
                          "reason": "stopped_after_offline_failure" if offline_failed else "live_component_not_started"}
                if contract is not None:
                    detail["offline_contract"] = contract
            components[name] = detail
        if "public_projection" in offline_components:
            components["public_projection"] = {
                **offline_components["public_projection"], "evidence_scope": "offline_contract"}
        if stop_on_failure and offline_failed:
            for row in plan:
                if not smoke or row.get("smoke_selected"):
                    row["status"] = "not_started"
    write_json(output_root / "task-plan.json", {"schema_version": PLAN_SCHEMA_VERSION, "slots": plan})
    raw_rows: list[dict[str, Any]] = []
    for name, detail in components.items():
        if not isinstance(detail, Mapping):
            continue
        for row in detail.get("rows", []):
            raw_rows.append({
                "schema_version": RAW_SCHEMA_VERSION,
                "mechanism": name,
                "evidence_scope": detail.get("evidence_scope", "offline_contract"),
                **row,
            })
        offline_detail = detail.get("offline_contract")
        if isinstance(offline_detail, Mapping):
            for row in offline_detail.get("rows", []):
                raw_rows.append({
                    "schema_version": RAW_SCHEMA_VERSION,
                    "mechanism": name,
                    "evidence_scope": "offline_contract",
                    **row,
                })
    write_json(output_root / "raw_rows.json", raw_rows)
    write_json(output_root / "telemetry.json", {
        "schema_version": "statebus.contest_stage2_telemetry.v1",
        "component_status": {name: _component_status(value) for name, value in components.items()},
        "raw_row_count": len(raw_rows), "missing_usage_fields": [],
        "missing_wire_fields": [row["slot_id"] for row in raw_rows if row.get("wire_bytes") is None],
    })
    acceptance = build_acceptance(
        mechanism=mechanism, smoke=smoke, plan=plan, components=components,
        stage1=stage1, preflight=preflight, live=live,
    )
    failures = []
    for name, value in components.items():
        if value.get("status") not in {"failed", "environment_fail", "blocked"}:
            continue
        task_failures = [row for row in value.get("rows", [])
                         if row.get("status") in {"failed", "environment_fail", "timeout"}]
        for row in task_failures or [value]:
            failures.append({"mechanism": name, **{
                key: row.get(key) for key in (
                    "task_id", "variant", "status", "error", "reason", "failure_path", "log_path",
                )
            }})
    write_json(output_root / "acceptance.json", acceptance)
    write_json(output_root / "phase-summary.json", {
        "schema_version": "statebus.contest_stage2_phase_summary.v1",
        "mechanism": mechanism, "run_mode": acceptance["run_mode"],
        "component_status": acceptance["components"], "planned_count": len(plan),
        "selected_count": acceptance["selected_count"], "raw_row_count": len(raw_rows),
        "formal_stage2_ready": acceptance["formal_stage2_ready"],
        "stage3_allowed": acceptance["stage3_allowed"],
    })
    write_json(output_root / "failures.json", {"schema_version": "statebus.contest_stage2_failures.v1", "rows": failures})
    write_json(output_root / "results.json", {"acceptance": acceptance, "components": components})
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stage1-root", type=Path, required=True)
    parser.add_argument("--mechanism", choices=("all", *FORMAL_MECHANISMS), default="all")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--profile", default=os.getenv("STATEBUS_VLLM_PROFILE", "qwen3-32b-gpu2-u050"))
    parser.add_argument("--embedding-model-path", default=os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"))
    parser.add_argument("--embedding-device", default=os.getenv("STATEBUS_EMBED_DEVICE", "cuda:0"))
    parser.add_argument("--preflight-json", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = build_plan(args.mechanism, smoke=args.smoke)
    if args.dry_run:
        print(stable_json_dumps({
            "schema_version": SCHEMA_VERSION, "stage": 2,
            "mechanism": args.mechanism, "smoke": args.smoke,
            "offline": args.offline, "stage1_root": str(args.stage1_root),
            "planned_count": len(plan),
            "selected_count": sum(bool(row.get("smoke_selected")) for row in plan) if args.smoke else len(plan),
            "formal_counts": {name: len(build_plan(name, smoke=False)) for name in FORMAL_MECHANISMS},
            "slots": plan,
        }))
        return
    preflight = None
    if args.preflight_json and args.preflight_json.is_file():
        preflight = json.loads(args.preflight_json.read_text(encoding="utf-8"))
    result = run_stage2(
        output_root=args.output_root, stage1_root=args.stage1_root,
        mechanism=args.mechanism, smoke=args.smoke, offline=args.offline,
        stop_on_failure=args.stop_on_failure, profile=args.profile,
        embedding_model_path=args.embedding_model_path, embedding_device=args.embedding_device,
        preflight=preflight,
    )
    print(stable_json_dumps(result))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
