#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


STAGE_MS_KEYS = (
    "codeact_execution_stage_ms",
    "control_plane_exchange_stage_ms",
    "execution_log_capture_stage_ms",
    "executor_state_machine_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_bundle_write_stage_ms",
    "persist_core_reload_stage_ms",
    "persist_integrity_check_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "persist_semantic_manifest_reload_stage_ms",
    "persist_session_ledger_reload_stage_ms",
    "planner_runtime_stage_ms",
    "registry_query_stage_ms",
    "retriever_runtime_stage_ms",
    "runtime_commit_finalize_stage_ms",
    "runtime_data_plane_event_stage_ms",
    "runtime_driver_stage_ms",
    "runtime_non_executor_stage_ms",
    "runtime_post_executor_stage_ms",
    "runtime_replay_ledger_stage_ms",
    "runtime_signature_capture_stage_ms",
    "runtime_signature_materialize_stage_ms",
    "runtime_signature_stage_ms",
    "summarizer_runtime_stage_ms",
    "telemetry_emit_stage_ms",
    "telemetry_event_write_stage_ms",
    "telemetry_fact_write_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
)

ROLE_PROMPT_BYTE_KEYS = (
    "planner_prompt_bytes",
    "retriever_prompt_bytes",
    "executor_prompt_bytes",
    "summarizer_prompt_bytes",
)

ROLE_NAMES = ("planner", "retriever", "executor", "summarizer")

RETRY_AND_FALLBACK_KEYS = (
    "attempt_count",
    "replan_history_count",
    "runtime_fallback_count",
    "codeact_sandbox_fallback_count",
    "state_pool_fallback_count",
    "llm_call_count",
)


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return json.load(handle)


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    try:
        payload = _safe_read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _stage_from_path(root: Path, path: Path) -> str:
    rel = Path(_rel(root, path))
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "work":
        return parts[1]
    if len(parts) >= 3 and parts[0] == "artifacts" and parts[1] == "stages":
        return parts[2]
    return ""


def _host_path(path_text: str) -> Path | None:
    if not path_text:
        return None
    if path_text.startswith("/statebus/runs/"):
        return Path("/home/qcrs/statebus/runs") / path_text.removeprefix("/statebus/runs/")
    return Path(path_text)


def _walk_dicts(obj: Any, trail: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    found: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if isinstance(obj, dict):
        found.append((trail, obj))
        for key, value in obj.items():
            found.extend(_walk_dicts(value, (*trail, str(key))))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            found.extend(_walk_dicts(value, (*trail, str(idx))))
    return found


def _lane_from_trail(trail: tuple[str, ...]) -> str:
    if "statebus_report" in trail:
        return "statebus"
    if "external_report" in trail:
        return "external"
    if "text_report" in trail or "text-collaboration" in trail:
        return "text"
    if "structured_report" in trail or "structured-collaboration" in trail:
        return "structured"
    return "direct"


def _short_json(obj: Any, max_chars: int = 500) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def _pct(numerator: float, denominator: float, digits: int = 1) -> str:
    if denominator == 0:
        return "-"
    return f"{(numerator / denominator) * 100:.{digits}f}%"


def _first_num(metrics: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in metrics:
            return _num(metrics.get(key))
    return 0.0


def _sum_metric(cases: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for case in cases:
        metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
        total += _num(metrics.get(key))
    return total


def _component_metrics(metrics: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, float]:
    payload = payload or {}
    telemetry_ms = (
        _num(metrics.get("telemetry_emit_stage_ms"))
        + _num(metrics.get("telemetry_event_write_stage_ms"))
        + _num(metrics.get("telemetry_fact_write_stage_ms"))
    )
    workspace_ms = _num(metrics.get("workspace_input_stage_ms")) + _num(metrics.get("workspace_output_stage_ms"))
    runtime_ms = (
        _num(metrics.get("runtime_driver_stage_ms"))
        + _num(metrics.get("runtime_commit_finalize_stage_ms"))
        + _num(metrics.get("runtime_non_executor_stage_ms"))
        + _num(metrics.get("runtime_post_executor_stage_ms"))
        + _num(metrics.get("runtime_data_plane_event_stage_ms"))
        + _num(metrics.get("runtime_replay_ledger_stage_ms"))
        + _num(metrics.get("runtime_signature_stage_ms"))
    )
    return {
        "task_ms": _first_num(metrics, "task_ms", "end_to_end_ms"),
        "llm_ms": _first_num(metrics, "llm_wall_ms", "llm_ms"),
        "codeact_ms": _num(metrics.get("codeact_execution_stage_ms")),
        "persist_ms": _num(metrics.get("persist_and_reload_stage_ms")),
        "memfd_bytes": _num(metrics.get("memfd_bytes_transferred", payload.get("memfd_bytes_transferred"))),
        "memfd_count": _num(metrics.get("memfd_transfer_count", payload.get("memfd_transfer_count"))),
        "telemetry_ms": telemetry_ms,
        "workspace_ms": workspace_ms,
        "runtime_ms": runtime_ms,
        "control_plane_ms": _num(metrics.get("control_plane_exchange_stage_ms")),
    }


def _add_component_totals(target: dict[str, float], metrics: dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    for key, value in _component_metrics(metrics, payload).items():
        target[key] = target.get(key, 0.0) + value


def _render_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _telemetry_context(root: Path, path: Path) -> dict[str, str]:
    rel = Path(_rel(root, path))
    parts = rel.parts
    context = {"stage": _stage_from_path(root, path), "lane": "", "family": "", "task_id": "", "path": str(rel)}
    if "runtime" not in parts:
        return context
    runtime_idx = parts.index("runtime")
    after = parts[runtime_idx + 1 :]
    if len(after) >= 3 and after[-2] == "telemetry":
        context["task_id"] = after[-3]
        lane_parts = after[:-2]
        context["lane"] = "/".join(lane_parts)
        if lane_parts:
            if lane_parts[0] == "api":
                context["family"] = ""
            else:
                context["family"] = lane_parts[0]
    return context


def _extract_output_shape(path_text: str) -> dict[str, Any]:
    path = _host_path(path_text)
    if path is None or not path.exists():
        return {"path": path_text, "exists": False}
    payload = _read_json_or_empty(path)
    if not payload:
        return {"path": path_text, "exists": True, "json_object": False}
    return {
        "path": str(path),
        "exists": True,
        "json_object": True,
        "byte_size": path.stat().st_size,
        "top_level_key_count": len(payload),
        "top_level_keys": sorted(payload.keys()),
    }


def _planner_actions(result: dict[str, Any]) -> list[str]:
    plan = result.get("planner_plan_payload") if isinstance(result.get("planner_plan_payload"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    actions = []
    for step in steps:
        if isinstance(step, dict):
            action = str(step.get("action", ""))
            if action:
                actions.append(action)
    return actions


def _candidate_reports(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    reports: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    if isinstance(payload.get("statebus_report"), dict) and isinstance(payload.get("external_report"), dict):
        reports.append(("", payload, payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}))
    modes = payload.get("mode_reports")
    if isinstance(modes, list):
        for idx, mode in enumerate(modes):
            if not isinstance(mode, dict):
                continue
            if isinstance(mode.get("statebus_report"), dict) and isinstance(mode.get("external_report"), dict):
                meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
                reports.append((f"#mode_reports[{idx}]", mode, meta))
    return reports


def _iter_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    cases = report.get("cases")
    return [case for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []


def _aggregate_numbers(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, float]:
    totals = {key: 0.0 for key in keys}
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
        for key in keys:
            totals[key] += _num(metrics.get(key))
    return totals


def _stage_ms_items(metrics: dict[str, Any], *, min_value: float = 0.0) -> list[dict[str, Any]]:
    items = [
        {"metric": key, "ms": _num(metrics.get(key))}
        for key in STAGE_MS_KEYS
        if key in metrics and _num(metrics.get(key)) > min_value
    ]
    return sorted(items, key=lambda item: (-item["ms"], item["metric"]))


def _parse_jsonl_events(root: Path) -> dict[str, Any]:
    inventory = Counter()
    event_counts: dict[str, Counter[str]] = defaultdict(Counter)
    fact_counts: Counter[str] = Counter()
    stage_ms_by_stage: dict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    component_by_stage_lane: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    task_summary_case_rows: list[dict[str, Any]] = []
    task_summary_counts: Counter[str] = Counter()
    lifecycle: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    errors: list[str] = []

    for path in sorted(root.rglob("runtime_events.jsonl")):
        stage = _stage_from_path(root, path)
        inventory["runtime_events_jsonl"] += 1
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{_rel(root, path)}: {exc}")
            continue
        with handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                inventory["runtime_event_lines"] += 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{_rel(root, path)}:{line_no}: {exc}")
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("event_type", ""))
                event_counts[stage][event_type] += 1
                metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                if event_type == "TASK_SUMMARY_METRICS":
                    task_summary_counts[stage] += 1
                    for key in STAGE_MS_KEYS:
                        if key in metrics:
                            stage_ms_by_stage[stage][key] += _num(metrics.get(key))
                    for key in ("memfd_transfer_count", "memfd_bytes_transferred"):
                        if key in payload:
                            stage_ms_by_stage[stage][key] += _num(payload.get(key))
                    context = _telemetry_context(root, path)
                    component_key = (context["stage"], context["lane"])
                    _add_component_totals(component_by_stage_lane[component_key], metrics, payload)
                    components = _component_metrics(metrics, payload)
                    task_summary_case_rows.append(
                        {
                            **context,
                            "known_component_ms": sum(
                                components[key]
                                for key in (
                                    "codeact_ms",
                                    "persist_ms",
                                    "telemetry_ms",
                                    "workspace_ms",
                                    "runtime_ms",
                                    "control_plane_ms",
                                )
                            ),
                            **components,
                        }
                    )
                step_key = (
                    stage,
                    str(event.get("task_id", "")),
                    str(event.get("step_id", "")),
                    str(event.get("attempt_id", "")),
                )
                entry = lifecycle.setdefault(
                    step_key,
                    {
                        "stage": stage,
                        "task_id": step_key[1],
                        "step_id": step_key[2],
                        "attempt_id": step_key[3],
                        "role": str(event.get("role", "")),
                        "running_ns": None,
                        "completed_ns": None,
                    },
                )
                if event_type == "STEP_RUNNING":
                    entry["running_ns"] = int(event.get("event_ts_ns", 0) or 0)
                    entry["role"] = str(event.get("role", entry.get("role", "")))
                elif event_type == "STEP_COMPLETED":
                    entry["completed_ns"] = int(event.get("event_ts_ns", 0) or 0)
                    entry["role"] = str(event.get("role", entry.get("role", "")))

    for path in sorted(root.rglob("runtime_facts.jsonl")):
        inventory["runtime_facts_jsonl"] += 1
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{_rel(root, path)}: {exc}")
            continue
        with handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                inventory["runtime_fact_lines"] += 1
                try:
                    fact = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{_rel(root, path)}:{line_no}: {exc}")
                    continue
                if not isinstance(fact, dict):
                    continue
                fact_type = str(fact.get("fact_type") or fact.get("event_type") or fact.get("type") or "")
                fact_counts[fact_type] += 1

    lifecycle_by_stage_role: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in lifecycle.values():
        start = entry.get("running_ns")
        end = entry.get("completed_ns")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            continue
        key = (str(entry.get("stage", "")), str(entry.get("role", "")))
        item = lifecycle_by_stage_role.setdefault(
            key,
            {"stage": key[0], "role": key[1], "count": 0, "duration_ms_sum": 0.0, "duration_ms_max": 0.0},
        )
        duration_ms = (end - start) / 1_000_000.0
        item["count"] += 1
        item["duration_ms_sum"] += duration_ms
        item["duration_ms_max"] = max(float(item["duration_ms_max"]), duration_ms)

    return {
        "inventory": dict(inventory),
        "event_counts_by_stage": {stage: dict(counter) for stage, counter in event_counts.items()},
        "runtime_fact_type_counts_top": [
            {"type": key, "count": count} for key, count in fact_counts.most_common(20)
        ],
        "task_summary_counts_by_stage": dict(task_summary_counts),
        "task_summary_stage_ms_by_stage": {
            stage: dict(sorted(metrics.items()))
            for stage, metrics in stage_ms_by_stage.items()
        },
        "task_summary_component_by_stage_lane": sorted(
            [
                {"stage": stage, "lane": lane, **components}
                for (stage, lane), components in component_by_stage_lane.items()
            ],
            key=lambda item: (-float(item.get("persist_ms", 0.0)) - float(item.get("codeact_ms", 0.0)), item["stage"], item["lane"]),
        )[:80],
        "task_summary_case_rows_top": sorted(
            task_summary_case_rows,
            key=lambda item: (-float(item.get("known_component_ms", 0.0)), item.get("stage", ""), item.get("task_id", "")),
        )[:80],
        "task_summary_stage_ms_top": [
            {"stage": stage, **item}
            for stage, metrics in sorted(stage_ms_by_stage.items())
            for item in _stage_ms_items(metrics, min_value=0.0)[:12]
        ],
        "inferred_step_lifecycle_by_stage_role": sorted(
            lifecycle_by_stage_role.values(),
            key=lambda item: (-float(item["duration_ms_sum"]), item["stage"], item["role"]),
        )[:60],
        "errors": errors[:20],
    }


def _collect_reports(run_roots: list[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for root in run_roots:
        for path in sorted(root.rglob("*.json")):
            if "benchmark_reports" not in path.parts:
                continue
            payload = _read_json_or_empty(path)
            if not payload:
                continue
            reports.append(
                {
                    "run_id": root.name,
                    "root": root,
                    "path": path,
                    "stage": _stage_from_path(root, path),
                    "source": _rel(root, path),
                    "payload": payload,
                }
            )
    return reports


def _formal_external_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    selected: dict[str, Any] | None = None
    selected_source = ""
    selected_meta: dict[str, Any] = {}
    for item in reports:
        if "r01_07_formal_compare" not in item["source"]:
            continue
        for suffix, mode, wrapper_meta in _candidate_reports(item["payload"]):
            meta = wrapper_meta if isinstance(wrapper_meta, dict) else {}
            if meta.get("formal_compare_full_registry_coverage") is True:
                selected = mode
                selected_source = item["source"] + suffix
                selected_meta = meta
                break
        if selected is not None:
            break
    if selected is None:
        return {}

    statebus = selected.get("statebus_report", {})
    external = selected.get("external_report", {})
    sb_cases = _iter_cases(statebus)
    ex_cases = _iter_cases(external)
    ex_by_task = {case.get("task_id"): case for case in ex_cases}

    family_rows: dict[str, dict[str, Any]] = {}
    family_latency_rows: dict[str, dict[str, Any]] = {}
    failed_cases: list[dict[str, Any]] = []
    output_shapes: list[dict[str, Any]] = []
    output_key_freq: dict[str, Counter[str]] = {"statebus": Counter(), "external": Counter()}
    case_latency_rows: list[dict[str, Any]] = []
    case_completion_rows: list[dict[str, Any]] = []
    for sb in sb_cases:
        task_id = str(sb.get("task_id", ""))
        ex = ex_by_task.get(task_id, {})
        family = str(sb.get("task_family", ex.get("task_family", "")))
        row = family_rows.setdefault(
            family,
            {
                "family": family,
                "cases": 0,
                "statebus_quality_pass": 0,
                "external_quality_pass": 0,
                "statebus_prompt_tokens": 0.0,
                "external_prompt_tokens": 0.0,
                "statebus_completion_tokens": 0.0,
                "external_completion_tokens": 0.0,
                "statebus_total_tokens": 0.0,
                "external_total_tokens": 0.0,
                "statebus_output_key_count": 0.0,
                "external_output_key_count": 0.0,
            },
        )
        sb_metrics = sb.get("metrics") if isinstance(sb.get("metrics"), dict) else {}
        ex_metrics = ex.get("metrics") if isinstance(ex.get("metrics"), dict) else {}
        sb_q = sb.get("quality_floor") if isinstance(sb.get("quality_floor"), dict) else {}
        ex_q = ex.get("quality_floor") if isinstance(ex.get("quality_floor"), dict) else {}
        sb_components = _component_metrics(sb_metrics)
        ex_components = _component_metrics(ex_metrics)
        row["cases"] += 1
        row["statebus_quality_pass"] += 1 if sb_q.get("quality_floor_pass") is True else 0
        row["external_quality_pass"] += 1 if ex_q.get("quality_floor_pass") is True else 0
        row["statebus_prompt_tokens"] += _num(sb_metrics.get("prompt_tokens", sb_metrics.get("llm_prompt_tokens")))
        row["external_prompt_tokens"] += _num(ex_metrics.get("prompt_tokens"))
        row["statebus_completion_tokens"] += _num(
            sb_metrics.get("completion_tokens", sb_metrics.get("llm_completion_tokens"))
        )
        row["external_completion_tokens"] += _num(ex_metrics.get("completion_tokens"))
        row["statebus_total_tokens"] += _num(sb_metrics.get("llm_total_tokens"))
        row["external_total_tokens"] += _num(ex_metrics.get("llm_total_tokens"))

        latency_row = family_latency_rows.setdefault(
            family,
            {
                "family": family,
                "cases": 0,
                "task_ms_delta": 0.0,
                "llm_ms_delta": 0.0,
                "system_overhead_ms_delta": 0.0,
                "statebus_codeact_ms": 0.0,
                "statebus_persist_ms": 0.0,
                "statebus_memfd_bytes": 0.0,
                "statebus_telemetry_ms": 0.0,
                "statebus_workspace_ms": 0.0,
                "statebus_runtime_ms": 0.0,
                "prompt_tokens_delta": 0.0,
                "completion_tokens_delta": 0.0,
            },
        )
        latency_row["cases"] += 1
        latency_row["task_ms_delta"] += sb_components["task_ms"] - ex_components["task_ms"]
        latency_row["llm_ms_delta"] += sb_components["llm_ms"] - ex_components["llm_ms"]
        sb_overhead = sb_components["task_ms"] - sb_components["llm_ms"]
        ex_overhead = ex_components["task_ms"] - ex_components["llm_ms"]
        latency_row["system_overhead_ms_delta"] += sb_overhead - ex_overhead
        latency_row["statebus_codeact_ms"] += sb_components["codeact_ms"]
        latency_row["statebus_persist_ms"] += sb_components["persist_ms"]
        latency_row["statebus_memfd_bytes"] += sb_components["memfd_bytes"]
        latency_row["statebus_telemetry_ms"] += sb_components["telemetry_ms"]
        latency_row["statebus_workspace_ms"] += sb_components["workspace_ms"]
        latency_row["statebus_runtime_ms"] += sb_components["runtime_ms"]
        latency_row["prompt_tokens_delta"] += _num(sb_metrics.get("prompt_tokens")) - _num(ex_metrics.get("prompt_tokens"))
        latency_row["completion_tokens_delta"] += _num(sb_metrics.get("completion_tokens")) - _num(
            ex_metrics.get("completion_tokens")
        )

        case_latency_rows.append(
            {
                "task_id": task_id,
                "family": family,
                "statebus_task_ms": sb_components["task_ms"],
                "external_task_ms": ex_components["task_ms"],
                "task_ms_delta": sb_components["task_ms"] - ex_components["task_ms"],
                "statebus_llm_ms": sb_components["llm_ms"],
                "external_llm_ms": ex_components["llm_ms"],
                "llm_ms_delta": sb_components["llm_ms"] - ex_components["llm_ms"],
                "statebus_system_overhead_ms": sb_overhead,
                "external_system_overhead_ms": ex_overhead,
                "system_overhead_ms_delta": sb_overhead - ex_overhead,
                "statebus_codeact_ms": sb_components["codeact_ms"],
                "statebus_persist_ms": sb_components["persist_ms"],
                "statebus_memfd_bytes": sb_components["memfd_bytes"],
                "statebus_telemetry_ms": sb_components["telemetry_ms"],
                "statebus_runtime_ms": sb_components["runtime_ms"],
            }
        )
        case_completion_rows.append(
            {
                "task_id": task_id,
                "family": family,
                "statebus_prompt_tokens": _num(sb_metrics.get("prompt_tokens")),
                "external_prompt_tokens": _num(ex_metrics.get("prompt_tokens")),
                "prompt_tokens_delta": _num(sb_metrics.get("prompt_tokens")) - _num(ex_metrics.get("prompt_tokens")),
                "statebus_completion_tokens": _num(sb_metrics.get("completion_tokens")),
                "external_completion_tokens": _num(ex_metrics.get("completion_tokens")),
                "completion_tokens_delta": _num(sb_metrics.get("completion_tokens"))
                - _num(ex_metrics.get("completion_tokens")),
                "statebus_total_tokens": _num(sb_metrics.get("llm_total_tokens")),
                "external_total_tokens": _num(ex_metrics.get("llm_total_tokens")),
            }
        )

        sb_shape = _extract_output_shape(str(sb.get("output_artifact_path", "")))
        ex_shape = _extract_output_shape(str(ex.get("output_artifact_path", ""))) if isinstance(ex, dict) else {}
        row["statebus_output_key_count"] += _num(sb_shape.get("top_level_key_count"))
        row["external_output_key_count"] += _num(ex_shape.get("top_level_key_count"))
        for key in sb_shape.get("top_level_keys", []) if isinstance(sb_shape.get("top_level_keys"), list) else []:
            output_key_freq["statebus"][str(key)] += 1
        for key in ex_shape.get("top_level_keys", []) if isinstance(ex_shape.get("top_level_keys"), list) else []:
            output_key_freq["external"][str(key)] += 1
        output_shapes.append({"task_id": task_id, "family": family, "lane": "statebus", **sb_shape})
        if ex_shape:
            output_shapes.append({"task_id": task_id, "family": family, "lane": "external", **ex_shape})

        if ex_q.get("quality_floor_pass") is not True:
            failed_dims = []
            for dim in (
                "route_exact",
                "tool_exact",
                "metric_name_exact",
                "metric_value_exact",
                "selected_doc_hashes_exact",
                "summary_present",
            ):
                if dim in ex_metrics and _num(ex_metrics.get(dim)) == 0.0:
                    failed_dims.append(dim)
            failed_cases.append(
                {
                    "task_id": task_id,
                    "family": family,
                    "reason": ex_q.get("quality_floor_fail_reason", ""),
                    "failed_dimensions": failed_dims,
                    "external_prompt_tokens": _num(ex_metrics.get("prompt_tokens")),
                    "external_completion_tokens": _num(ex_metrics.get("completion_tokens")),
                }
            )

    role_prompt_byte_delta = {}
    sb_telemetry = statebus.get("telemetry_summary") if isinstance(statebus.get("telemetry_summary"), dict) else {}
    ex_telemetry = external.get("telemetry_summary") if isinstance(external.get("telemetry_summary"), dict) else {}
    for key in ROLE_PROMPT_BYTE_KEYS:
        role = key.removesuffix("_prompt_bytes")
        role_prompt_byte_delta[role] = {
            "statebus": _num(sb_telemetry.get(key)),
            "external": _num(ex_telemetry.get(key)),
            "delta": _num(sb_telemetry.get(key)) - _num(ex_telemetry.get(key)),
        }

    debug = selected.get("debug_metrics") if isinstance(selected.get("debug_metrics"), dict) else {}
    statebus_only_keys = sorted(set(output_key_freq["statebus"]) - set(output_key_freq["external"]))
    shared_keys = sorted(set(output_key_freq["statebus"]) & set(output_key_freq["external"]))
    retry_and_fallback = {
        "statebus": {key: _sum_metric(sb_cases, key) for key in RETRY_AND_FALLBACK_KEYS},
        "external": {key: _sum_metric(ex_cases, key) for key in RETRY_AND_FALLBACK_KEYS},
    }
    return {
        "source": selected_source,
        "metadata": selected_meta,
        "debug_metrics": debug,
        "token_delta_percentages": {
            "prompt_tokens_delta_pct_vs_external": _pct(_num(debug.get("prompt_tokens_delta")), _num(debug.get("external_prompt_tokens"))),
            "completion_tokens_delta_pct_vs_external": _pct(
                _num(debug.get("completion_tokens_delta")), _num(debug.get("external_completion_tokens"))
            ),
            "llm_total_tokens_delta_pct_vs_external": _pct(
                _num(debug.get("llm_total_tokens_delta")), _num(debug.get("external_llm_total_tokens"))
            ),
        },
        "statebus_stage_ms_top": _stage_ms_items(sb_telemetry)[:20],
        "statebus_stage_ms_total_known": sum(item["ms"] for item in _stage_ms_items(sb_telemetry)),
        "role_prompt_byte_delta": role_prompt_byte_delta,
        "family_token_and_output_shape": sorted(family_rows.values(), key=lambda row: row["family"]),
        "family_latency_decomposition": sorted(family_latency_rows.values(), key=lambda row: row["family"]),
        "case_latency_delta_top": sorted(
            case_latency_rows,
            key=lambda row: (-float(row["task_ms_delta"]), row["family"], row["task_id"]),
        )[:20],
        "case_completion_delta_top": sorted(
            case_completion_rows,
            key=lambda row: (-float(row["completion_tokens_delta"]), row["family"], row["task_id"]),
        )[:20],
        "retry_and_fallback_totals": retry_and_fallback,
        "output_key_frequency_by_lane": {
            lane: [{"key": key, "count": count} for key, count in counter.most_common()]
            for lane, counter in output_key_freq.items()
        },
        "schema_key_sets": {
            "statebus_only_keys": statebus_only_keys,
            "shared_keys": shared_keys,
        },
        "external_failed_cases": failed_cases,
        "output_shapes_sample": sorted(
            output_shapes,
            key=lambda row: (
                row.get("family", ""),
                row.get("task_id", ""),
                row.get("lane", ""),
            ),
        )[:80],
        "limits": [
            "formal artifacts expose total completion tokens but not reliable per-role completion-token split",
            "role-level completion inflation is inferred from total completion tokens, output shape, and strict JSON role code path",
        ],
    }


def _prompt_slice_summary(workspace: Path) -> dict[str, Any]:
    rows = []
    for path in sorted((workspace / "logs" / "prompt_slices").glob("*.prompt_slice.json")):
        payload = _read_json_or_empty(path)
        if not payload:
            continue
        rows.append(
            {
                "role": payload.get("role", path.name.split(".")[0]),
                "prompt_bytes": _num(payload.get("prompt_bytes")),
                "scaffolding": _num(payload.get("prompt_scaffolding_bytes")),
                "visible": _num(payload.get("total_prompt_visible_bytes")),
                "external_evidence_bytes": _num(payload.get("external_evidence_bytes")),
                "non_external_visible": _num(payload.get("non_external_prompt_visible_bytes")),
                "hydrated_bytes": _num(payload.get("hydrated_bytes")),
                "table_bytes": _num(payload.get("table_bytes")),
                "artifact_bytes": _num(payload.get("artifact_bytes")),
                "selected_stable_keys": payload.get("selected_stable_keys", []),
            }
        )
    return {"rows": rows, "total_prompt_bytes": sum(row["prompt_bytes"] for row in rows)}


def _workspace_sidecar_summary(workspace: Path) -> dict[str, Any]:
    result = _read_json_or_empty(workspace / "outputs" / "result.json")
    planner = _read_json_or_empty(workspace / "inputs" / "planner_handoff.json")
    canonical = _read_json_or_empty(workspace / "inputs" / "canonical_task_spec.json")
    retrieval_log = _read_json_or_empty(workspace / "inputs" / "retrieval_log.json")
    validators = []
    for path in sorted((workspace / "logs").glob("*validator*.json")):
        payload = _read_json_or_empty(path)
        if payload:
            validators.append({"source": str(path), **payload})
    prompt_summary = _prompt_slice_summary(workspace)
    return {
        "workspace": str(workspace),
        "exists": workspace.exists(),
        "result": {
            "action_contract": result.get("action_contract"),
            "route": result.get("route"),
            "tool_name": result.get("tool_name"),
            "intent_op": result.get("intent_op"),
            "trend_values": result.get("trend_values"),
            "trend_direction": result.get("trend_direction"),
            "selected_doc_hashes": result.get("selected_doc_hashes"),
            "summary_text": result.get("summary_text"),
            "planner_step_actions": _planner_actions(result),
            "top_level_key_count": len(result),
            "top_level_keys": sorted(result.keys()),
        },
        "planner_candidate_keys": (
            planner.get("retrieval_objective", {}).get("candidate_keys", [])
            if isinstance(planner.get("retrieval_objective"), dict)
            else []
        ),
        "planner_intent_op": (
            planner.get("retrieval_objective", {}).get("intent_op")
            if isinstance(planner.get("retrieval_objective"), dict)
            else None
        ),
        "planner_required_tools": (
            planner.get("retrieval_objective", {}).get("required_tools", [])
            if isinstance(planner.get("retrieval_objective"), dict)
            else []
        ),
        "canonical_task_family": canonical.get("task_family"),
        "canonical_intent_op": canonical.get("intent_op"),
        "canonical_required_tools": canonical.get("required_tools", []),
        "retrieval_log": {
            "query_text": retrieval_log.get("query_text"),
            "selected_doc_hashes": retrieval_log.get("selected_doc_hashes"),
            "full_corpus_bytes": retrieval_log.get("full_corpus_bytes"),
            "selected_evidence_bytes": retrieval_log.get("selected_evidence_bytes"),
        },
        "validator_reports": validators,
        "prompt_slices": prompt_summary,
    }


def _runtime_sidecar_summary(runtime_root: Path) -> dict[str, Any]:
    result = {
        "runtime_root": str(runtime_root),
        "rerank_selected_candidate_ids": [],
        "candidate_pool": {},
        "fact_coverage_validator": {},
        "deterministic_validator": {},
    }
    rerank_files = sorted((runtime_root / "sidecars" / "retrieval_rerank_results").glob("*.json"))
    if rerank_files:
        rerank = _read_json_or_empty(rerank_files[0])
        result["rerank_selected_candidate_ids"] = rerank.get("selected_candidate_ids", [])
        result["rerank_top_items"] = rerank.get("items", [])[:8]
    pool_files = sorted((runtime_root / "sidecars" / "retrieval_candidate_pools").glob("*.json"))
    if pool_files:
        pool = _read_json_or_empty(pool_files[0])
        result["candidate_pool"] = {
            "candidate_count": pool.get("candidate_count"),
            "bucket_counts": pool.get("bucket_counts", {}),
            "top_candidate_ids_by_bucket": pool.get("top_candidate_ids_by_bucket", {}),
            "candidate_audit_sample": pool.get("candidate_audit_sample", [])[:6],
        }
    for path in sorted((runtime_root / "sidecars" / "validator_reports").glob("*.json")):
        payload = _read_json_or_empty(path)
        scope = payload.get("validation_scope")
        if scope == "fact_coverage":
            result["fact_coverage_validator"] = payload
        elif scope == "deterministic":
            result["deterministic_validator"] = payload
    return result


def _route_miss_forensics(root: Path, task_id: str) -> dict[str, Any]:
    stage = "r01_06_formal_carrier_compare_api_local_memfd"
    base = root / "work" / stage
    structured_workspace = base / "workspaces" / "api" / "structured-collaboration" / task_id
    text_workspace = base / "workspaces" / "api" / "text-collaboration" / task_id
    structured_runtime = base / "runtime" / "api" / "structured-collaboration" / task_id
    text_runtime = base / "runtime" / "api" / "text-collaboration" / task_id

    report = {}
    for path in sorted((base / "runtime" / "benchmark_reports").glob("*.json")):
        payload = _read_json_or_empty(path)
        if not payload or "carrier-compare.json" not in path.name:
            continue
        modes = payload.get("mode_reports")
        mode = modes[0] if isinstance(modes, list) and modes and isinstance(modes[0], dict) else {}
        if not mode:
            continue
        for lane_name, report_key in (("structured", "statebus_report"), ("text", "external_report")):
            lane_report = mode.get(report_key) if isinstance(mode.get(report_key), dict) else {}
            case = next((item for item in _iter_cases(lane_report) if item.get("task_id") == task_id), {})
            if case:
                metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
                quality = case.get("quality_floor") if isinstance(case.get("quality_floor"), dict) else {}
                report[lane_name] = {
                    "quality_floor_pass": quality.get("quality_floor_pass"),
                    "quality_floor_fail_reason": quality.get("quality_floor_fail_reason", ""),
                    "route_exact": metrics.get("route_exact"),
                    "tool_exact": metrics.get("tool_exact"),
                    "metric_name_exact": metrics.get("metric_name_exact"),
                    "metric_value_exact": metrics.get("metric_value_exact"),
                    "selected_doc_hashes_exact": metrics.get("selected_doc_hashes_exact"),
                    "summary_present": metrics.get("summary_present"),
                    "prompt_tokens": metrics.get("prompt_tokens"),
                    "completion_tokens": metrics.get("completion_tokens"),
                    "llm_total_tokens": metrics.get("llm_total_tokens"),
                }
        break

    structured = _workspace_sidecar_summary(structured_workspace)
    text = _workspace_sidecar_summary(text_workspace)
    diagnosis = []
    structured_route = structured.get("result", {}).get("route")
    text_route = text.get("result", {}).get("route")
    if structured_route != text_route:
        diagnosis.append(f"structured route `{structured_route}` differs from text route `{text_route}`")
    candidate_keys = structured.get("planner_candidate_keys", [])
    if structured_route and candidate_keys and any(str(key).startswith(f"{structured_route}::") for key in candidate_keys):
        diagnosis.append("structured route exists in visible candidate keys, so this is a wrong visible-choice selection rather than hidden metadata leakage")
    if structured.get("result", {}).get("tool_name") == text.get("result", {}).get("tool_name"):
        diagnosis.append("tool selection matches; failure is route-level")
    if structured.get("result", {}).get("trend_values") == text.get("result", {}).get("trend_values"):
        diagnosis.append("computed trend values match; numeric execution is not the failing dimension")

    return {
        "stage": stage,
        "task_id": task_id,
        "carrier_report_case_metrics": report,
        "structured_workspace": structured,
        "text_workspace": text,
        "structured_runtime_sidecars": _runtime_sidecar_summary(structured_runtime),
        "text_runtime_sidecars": _runtime_sidecar_summary(text_runtime),
        "diagnosis": diagnosis,
    }


def _runtime_event_diagnostics(run_roots: list[Path]) -> dict[str, Any]:
    by_run = {root.name: _parse_jsonl_events(root) for root in run_roots}
    global_stage_ms: dict[str, float] = defaultdict(float)
    for run in by_run.values():
        for _stage, metrics in run.get("task_summary_stage_ms_by_stage", {}).items():
            for key, value in metrics.items():
                if key.endswith("_stage_ms") or key == "codeact_execution_stage_ms":
                    global_stage_ms[key] += _num(value)
    return {
        "by_run": by_run,
        "global_stage_ms_top": [
            {"metric": key, "ms": value}
            for key, value in sorted(global_stage_ms.items(), key=lambda item: (-item[1], item[0]))[:30]
        ],
    }


def analyze(run_roots: list[Path], target_task_id: str) -> dict[str, Any]:
    run_roots = [root.resolve() for root in run_roots]
    reports = _collect_reports(run_roots)
    base_root = next((root for root in run_roots if root.name == "sb2-gpu1-20260708_084458"), run_roots[0])
    return {
        "schema_version": "statebus.v2_diagnostic_artifact_mining.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_roots": [str(root) for root in run_roots],
        "runtime_event_diagnostics": _runtime_event_diagnostics(run_roots),
        "formal_external_diagnostics": _formal_external_diagnostics(reports),
        "route_miss_forensics": _route_miss_forensics(base_root, target_task_id),
        "notes": [
            "This diagnostic pass reuses existing artifacts only; it does not rerun experiments.",
            "runtime_events.jsonl lifecycle durations are useful for runtime event timing but are not a substitute for provider-reported LLM usage metrics.",
            "Per-role completion-token split is not currently persisted; total completion inflation is still visible in formal comparator reports.",
        ],
    }


def _render_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# 2026-07-08 diagnostic artifact mining",
        "",
        "本文由 `scripts/diagnose_v2_artifact_mining.py` 从既有 run artifacts 生成。它不是“全面抽取”的 headline 汇总，而是面向问题定位的诊断层：latency decomposition、route miss forensic、completion/schema inflation。",
        "",
        "## 覆盖",
        "",
    ]
    inv_rows = []
    for run_id, run in data["runtime_event_diagnostics"]["by_run"].items():
        inv = run.get("inventory", {})
        inv_rows.append(
            [
                run_id,
                inv.get("runtime_events_jsonl", 0),
                inv.get("runtime_event_lines", 0),
                inv.get("runtime_facts_jsonl", 0),
                inv.get("runtime_fact_lines", 0),
                len(run.get("event_counts_by_stage", {})),
                len(run.get("errors", [])),
            ]
        )
    lines.append(_render_table(["Run", "events files", "event lines", "facts files", "fact lines", "stages", "errors"], inv_rows))

    formal = data.get("formal_external_diagnostics", {})
    debug = formal.get("debug_metrics", {})
    lines.extend(["", "## Latency Decomposition", ""])
    lines.extend(
        [
            f"- formal external source: `{formal.get('source', '')}`",
            f"- task_ms_delta: `{_fmt(debug.get('task_ms_delta'))}`; llm_ms_delta: `{_fmt(debug.get('llm_ms_delta'))}`; system_overhead_ms_delta: `{_fmt(debug.get('system_overhead_ms_delta'))}`",
            f"- known StateBus stage-ms total from telemetry summary: `{_fmt(formal.get('statebus_stage_ms_total_known'))}`",
            "",
        ]
    )
    lines.append(
        _render_table(
            ["Formal delta", "Value", "Interpretation"],
            [
                ["task_ms_delta", _fmt(debug.get("task_ms_delta")), "StateBus slower end-to-end in this live run"],
                ["llm_ms_delta", _fmt(debug.get("llm_ms_delta")), "provider LLM wall time also higher"],
                ["system_overhead_ms_delta", _fmt(debug.get("system_overhead_ms_delta")), "non-LLM runtime overhead also higher"],
                ["codeact_execution_stage_ms", _fmt(debug.get("codeact_execution_stage_ms")), "StateBus-only executable artifact path"],
                ["prompt_tokens_delta", _fmt(debug.get("prompt_tokens_delta")), formal.get("token_delta_percentages", {}).get("prompt_tokens_delta_pct_vs_external", "")],
                ["completion_tokens_delta", _fmt(debug.get("completion_tokens_delta")), formal.get("token_delta_percentages", {}).get("completion_tokens_delta_pct_vs_external", "")],
                ["llm_total_tokens_delta", _fmt(debug.get("llm_total_tokens_delta")), formal.get("token_delta_percentages", {}).get("llm_total_tokens_delta_pct_vs_external", "")],
            ],
        )
    )
    lines.extend(["", "### Family-Level Latency Components", ""])
    lines.append(
        _render_table(
            [
                "Family",
                "Cases",
                "Task delta",
                "LLM delta",
                "Overhead delta",
                "CodeAct",
                "Persist",
                "Memfd bytes",
                "Telemetry",
                "Runtime",
            ],
            [
                [
                    row["family"],
                    row["cases"],
                    _fmt(row["task_ms_delta"]),
                    _fmt(row["llm_ms_delta"]),
                    _fmt(row["system_overhead_ms_delta"]),
                    _fmt(row["statebus_codeact_ms"]),
                    _fmt(row["statebus_persist_ms"]),
                    _fmt(row["statebus_memfd_bytes"]),
                    _fmt(row["statebus_telemetry_ms"]),
                    _fmt(row["statebus_runtime_ms"]),
                ]
                for row in formal.get("family_latency_decomposition", [])
            ],
        )
    )
    lines.extend(["", "### Slowest Formal Case Deltas", ""])
    lines.append(
        _render_table(
            ["Task", "Family", "Task delta", "LLM delta", "Overhead delta", "CodeAct", "Persist", "Runtime"],
            [
                [
                    row["task_id"],
                    row["family"],
                    _fmt(row["task_ms_delta"]),
                    _fmt(row["llm_ms_delta"]),
                    _fmt(row["system_overhead_ms_delta"]),
                    _fmt(row["statebus_codeact_ms"]),
                    _fmt(row["statebus_persist_ms"]),
                    _fmt(row["statebus_runtime_ms"]),
                ]
                for row in formal.get("case_latency_delta_top", [])[:10]
            ],
        )
    )
    lines.extend(["", "### StateBus Telemetry Summary Top", ""])
    lines.append(
        _render_table(
            ["StateBus stage metric", "ms"],
            [[item["metric"], _fmt(item["ms"])] for item in formal.get("statebus_stage_ms_top", [])[:15]],
        )
    )
    lines.extend(["", "### Runtime JSONL Stage Totals", ""])
    lines.append(
        _render_table(
            ["Metric", "ms"],
            [
                [item["metric"], _fmt(item["ms"])]
                for item in data["runtime_event_diagnostics"].get("global_stage_ms_top", [])[:18]
            ],
        )
    )
    lines.extend(["", "### Runtime JSONL Component Aggregates", ""])
    component_rows = []
    for run_id, run in data["runtime_event_diagnostics"]["by_run"].items():
        for row in run.get("task_summary_component_by_stage_lane", [])[:12]:
            component_rows.append(
                [
                    run_id,
                    row.get("stage", ""),
                    row.get("lane", ""),
                    _fmt(row.get("codeact_ms")),
                    _fmt(row.get("persist_ms")),
                    _fmt(row.get("memfd_bytes")),
                    _fmt(row.get("telemetry_ms")),
                    _fmt(row.get("workspace_ms")),
                    _fmt(row.get("runtime_ms")),
                ]
            )
    lines.append(
        _render_table(
            ["Run", "Stage", "Lane", "CodeAct", "Persist", "Memfd bytes", "Telemetry", "Workspace", "Runtime"],
            component_rows[:24],
        )
    )
    lines.extend(["", "### Runtime Event Lifecycle By Role", ""])
    lifecycle_rows = []
    for run_id, run in data["runtime_event_diagnostics"]["by_run"].items():
        for row in run.get("inferred_step_lifecycle_by_stage_role", [])[:12]:
            lifecycle_rows.append(
                [
                    run_id,
                    row.get("stage", ""),
                    row.get("role", ""),
                    row.get("count", 0),
                    _fmt(row.get("duration_ms_sum")),
                    _fmt(row.get("duration_ms_max")),
                ]
            )
    lines.append(_render_table(["Run", "Stage", "Role", "Count", "Sum ms", "Max ms"], lifecycle_rows[:24]))
    lines.extend(
        [
            "",
            "判断：本轮 latency 负结果不是单一原因。formal compare 的 LLM delta 和 system overhead delta 都为正；case/family 分解显示 CodeAct 是最大的 StateBus-only 显性成本，persist/reload、runtime driver、workspace IO、telemetry、memfd accounting 也是真实开销。JSONL lifecycle 只反映 runtime event 间隔，不能替代 provider LLM timing。",
            "",
        ]
    )

    lines.extend(["## Completion / Schema Inflation", ""])
    lines.append(
        _render_table(
            ["Token metric", "StateBus", "External", "Delta", "Delta vs external"],
            [
                [
                    "prompt_tokens",
                    _fmt(debug.get("statebus_prompt_tokens")),
                    _fmt(debug.get("external_prompt_tokens")),
                    _fmt(debug.get("prompt_tokens_delta")),
                    formal.get("token_delta_percentages", {}).get("prompt_tokens_delta_pct_vs_external", ""),
                ],
                [
                    "completion_tokens",
                    _fmt(debug.get("statebus_completion_tokens")),
                    _fmt(debug.get("external_completion_tokens")),
                    _fmt(debug.get("completion_tokens_delta")),
                    formal.get("token_delta_percentages", {}).get("completion_tokens_delta_pct_vs_external", ""),
                ],
                [
                    "llm_total_tokens",
                    _fmt(debug.get("statebus_llm_total_tokens")),
                    _fmt(debug.get("external_llm_total_tokens")),
                    _fmt(debug.get("llm_total_tokens_delta")),
                    formal.get("token_delta_percentages", {}).get("llm_total_tokens_delta_pct_vs_external", ""),
                ],
            ],
        )
    )
    lines.append("")
    family_rows = []
    for row in formal.get("family_token_and_output_shape", []):
        family_rows.append(
            [
                row["family"],
                f"{row['statebus_quality_pass']}/{row['cases']}",
                f"{row['external_quality_pass']}/{row['cases']}",
                _fmt(row["statebus_prompt_tokens"] - row["external_prompt_tokens"]),
                _fmt(row["statebus_completion_tokens"] - row["external_completion_tokens"]),
                _fmt(row["statebus_total_tokens"] - row["external_total_tokens"]),
                _fmt(row["statebus_output_key_count"] / row["cases"]),
                _fmt(row["external_output_key_count"] / row["cases"]),
            ]
        )
    lines.append(
        _render_table(
            [
                "Family",
                "SB quality",
                "External quality",
                "Prompt delta",
                "Completion delta",
                "Total delta",
                "SB avg keys",
                "External avg keys",
            ],
            family_rows,
        )
    )
    lines.extend(["", "### Largest Completion Deltas", ""])
    lines.append(
        _render_table(
            ["Task", "Family", "Prompt delta", "Completion delta", "SB completion", "External completion"],
            [
                [
                    row["task_id"],
                    row["family"],
                    _fmt(row["prompt_tokens_delta"]),
                    _fmt(row["completion_tokens_delta"]),
                    _fmt(row["statebus_completion_tokens"]),
                    _fmt(row["external_completion_tokens"]),
                ]
                for row in formal.get("case_completion_delta_top", [])[:10]
            ],
        )
    )
    role_rows = []
    for role, values in formal.get("role_prompt_byte_delta", {}).items():
        role_rows.append([role, _fmt(values.get("statebus")), _fmt(values.get("external")), _fmt(values.get("delta"))])
    lines.extend(["", "### Role Prompt Bytes", ""])
    lines.append(_render_table(["Role", "StateBus", "External", "Delta"], role_rows))
    retry = formal.get("retry_and_fallback_totals", {})
    retry_rows = []
    for key in RETRY_AND_FALLBACK_KEYS:
        retry_rows.append(
            [
                key,
                _fmt(retry.get("statebus", {}).get(key)),
                _fmt(retry.get("external", {}).get(key)),
                _fmt(_num(retry.get("statebus", {}).get(key)) - _num(retry.get("external", {}).get(key))),
            ]
        )
    lines.extend(["", "### Retry / Fallback Checks", ""])
    lines.append(_render_table(["Metric", "StateBus", "External", "Delta"], retry_rows))
    schema = formal.get("schema_key_sets", {})
    lines.extend(["", "### Schema Surface", ""])
    statebus_only = schema.get("statebus_only_keys", [])
    lines.append(
        _render_table(
            ["Item", "Value"],
            [
                ["StateBus-only top-level keys", ", ".join(statebus_only[:28])],
                ["Shared top-level keys", ", ".join(schema.get("shared_keys", [])[:20])],
            ],
        )
    )
    lines.extend(
        [
            "",
            "判断：completion token split 目前只有 total，不是 per-role。现有证据足以排除“重试导致 completion 膨胀”这一主因：LLM call count 没增加，fallback/replan 为 0 或不构成解释。更合理的解释是 StateBus 输出面更严格、更可审计，要求 route/tool/doc/value 之外保留 artifact、handoff、strategy、runtime hash、selected docs、summary 等字段；这让 completion 上升，但 prompt 与 total tokens 仍显著下降。",
            "",
        ]
    )

    forensic = data.get("route_miss_forensics", {})
    structured = forensic.get("structured_workspace", {})
    text = forensic.get("text_workspace", {})
    lines.extend(["## Route Miss Forensic", ""])
    lines.extend(
        [
            f"- stage: `{forensic.get('stage')}` task: `{forensic.get('task_id')}`",
            f"- structured route/tool: `{structured.get('result', {}).get('route')}` / `{structured.get('result', {}).get('tool_name')}`",
            f"- text route/tool: `{text.get('result', {}).get('route')}` / `{text.get('result', {}).get('tool_name')}`",
            f"- structured action_contract: `{structured.get('result', {}).get('action_contract')}`; text action_contract: `{text.get('result', {}).get('action_contract')}`",
            f"- structured trend values/direction: `{structured.get('result', {}).get('trend_values')}` / `{structured.get('result', {}).get('trend_direction')}`",
            f"- text trend values/direction: `{text.get('result', {}).get('trend_values')}` / `{text.get('result', {}).get('trend_direction')}`",
            "",
        ]
    )
    lines.append(
        _render_table(
            ["Lane", "Quality", "Route exact", "Tool exact", "Metric name", "Metric value", "Reason"],
            [
                [
                    lane,
                    metrics.get("quality_floor_pass"),
                    metrics.get("route_exact"),
                    metrics.get("tool_exact"),
                    metrics.get("metric_name_exact"),
                    metrics.get("metric_value_exact"),
                    metrics.get("quality_floor_fail_reason", ""),
                ]
                for lane, metrics in forensic.get("carrier_report_case_metrics", {}).items()
            ],
        )
    )
    lines.extend(["", "### Visible Candidate Keys", ""])
    lines.append(
        _render_table(
            ["Lane", "Candidate keys"],
            [
                ["structured", ", ".join(str(item) for item in structured.get("planner_candidate_keys", []))],
                ["text", ", ".join(str(item) for item in text.get("planner_candidate_keys", []))],
            ],
        )
    )
    lines.extend(["", "### Prompt Slice Comparison", ""])
    prompt_rows = []
    structured_prompts = {row.get("role"): row for row in structured.get("prompt_slices", {}).get("rows", [])}
    text_prompts = {row.get("role"): row for row in text.get("prompt_slices", {}).get("rows", [])}
    for role in ROLE_NAMES:
        sb = structured_prompts.get(role, {})
        tx = text_prompts.get(role, {})
        prompt_rows.append(
            [
                role,
                _fmt(sb.get("prompt_bytes")),
                _fmt(tx.get("prompt_bytes")),
                _fmt(_num(sb.get("prompt_bytes")) - _num(tx.get("prompt_bytes"))),
                _fmt(sb.get("scaffolding")),
                _fmt(tx.get("scaffolding")),
                _fmt(sb.get("visible")),
                _fmt(tx.get("visible")),
            ]
        )
    lines.append(
        _render_table(
            ["Role", "Structured prompt", "Text prompt", "Delta", "Structured scaffold", "Text scaffold", "Structured visible", "Text visible"],
            prompt_rows,
        )
    )
    lines.extend(["", "### Raw Output Shape", ""])
    lines.append(
        _render_table(
            ["Lane", "Top-level keys", "Planner step actions"],
            [
                [
                    "structured",
                    ", ".join(structured.get("result", {}).get("top_level_keys", [])),
                    ", ".join(structured.get("result", {}).get("planner_step_actions", [])),
                ],
                [
                    "text",
                    ", ".join(text.get("result", {}).get("top_level_keys", [])),
                    ", ".join(text.get("result", {}).get("planner_step_actions", [])),
                ],
            ],
        )
    )
    runtime = forensic.get("structured_runtime_sidecars", {})
    lines.extend(["", "### Structured Sidecar Evidence", ""])
    lines.append(
        _render_table(
            ["Item", "Value"],
            [
                ["rerank selected", ", ".join(runtime.get("rerank_selected_candidate_ids", []))],
                ["candidate buckets", _short_json(runtime.get("candidate_pool", {}).get("bucket_counts", {}), 300)],
                [
                    "fact validator",
                    _short_json(
                        {
                            "passed": runtime.get("fact_coverage_validator", {}).get("passed"),
                            "reason": runtime.get("fact_coverage_validator", {}).get("fail_reason"),
                            "details": runtime.get("fact_coverage_validator", {}).get("details"),
                        },
                        500,
                    ),
                ],
            ],
        )
    )
    if forensic.get("diagnosis"):
        lines.extend(["", "### Diagnosis", ""])
        for item in forensic["diagnosis"]:
            lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "修复方向：给 structured carrier 的 route selection/normalization 加 targeted regression。这个 case 的 tool/doc/value/trend 都对，失败集中在 route label 选择从 `compare_metric` 偏到 `generate_chart`。",
            "",
            "## Limits",
            "",
        ]
    )
    for item in data.get("notes", []):
        lines.append(f"- {item}")
    for item in formal.get("limits", []):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic mining for StateBus v2 run artifacts.")
    parser.add_argument("--run-root", action="append", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--target-task-id", default="formal-trend-002")
    args = parser.parse_args()

    data = analyze([Path(item) for item in args.run_root], args.target_task_id)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(_render_markdown(data), encoding="utf-8")


if __name__ == "__main__":
    main()
