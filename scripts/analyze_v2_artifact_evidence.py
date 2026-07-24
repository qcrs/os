#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


NUMBER_KEYS = {
    "case_count",
    "quality_floor_pass_count",
    "prompt_tokens",
    "completion_tokens",
    "llm_total_tokens",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_prompt_bytes",
    "prompt_bytes",
    "prompt_scaffolding_bytes",
    "prompt_scaffolding_bytes_total",
    "prompt_visible_bytes",
    "prompt_visible_total_bytes",
    "non_external_prompt_visible_bytes",
    "raw_evidence_bytes_seen_by_llm",
    "selected_evidence_bytes",
    "full_corpus_bytes",
    "external_evidence_bytes",
    "control_bytes",
    "message_count",
    "control_message_count",
    "task_ms",
    "end_to_end_ms",
    "llm_ms",
    "llm_wall_ms",
    "system_overhead_ms_delta",
    "task_ms_delta",
    "llm_ms_delta",
    "net_llm_ms_delta",
    "semantic_state_transfer_count",
    "semantic_state_ref_count",
    "memfd_transfer_count",
    "memfd_publish_count",
    "memfd_bytes_transferred",
    "shared_memory_publish_count",
    "mmap_publish_count",
    "reuse_gain",
    "history_reuse_gain",
    "history_step_reduction_count",
    "history_artifact_reuse_count",
    "artifact_reuse_count",
    "validated_replay_count",
    "validated_downgraded_reuse_count",
    "exact_replay_count",
    "answer_restoration_replay_count",
    "skipped_step_count",
    "route_exact",
    "tool_exact",
    "metric_name_exact",
    "metric_value_exact",
    "selected_doc_hashes_exact",
    "summary_present",
    "external_fairness_gate_pass",
    "external_fairness_gate_failed",
    "external_fairness_gate_failed_check_count",
    "codeact_execution_stage_ms",
    "persist_and_reload_stage_ms",
    "runtime_driver_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "telemetry_emit_stage_ms",
    "kv_corpus_level_prefill_saved_tokens_estimate",
    "kv_corpus_prefix_hash_reuse_count",
    "kv_corpus_prefix_hash_unique_count",
    "kv_engine_local_prefill_saved_tokens_estimate",
    "kv_engine_local_prefix_cache_hit_count_estimate",
    "kv_engine_local_prefix_cache_query_count_estimate",
    "kv_evidence_prefix_hash_reuse_count",
    "kv_evidence_prefix_hash_unique_count",
    "neural_prefix_prefill_saved_tokens_estimate",
    "neural_prefix_cache_hit_count_estimate",
    "neural_prefix_cache_query_count_estimate",
}


CODE_PATTERNS = {
    "external fairness gate": ("v2/benchmark/comparator_runner.py", "def _fairness_manifest"),
    "quality superiority gate": ("v2/benchmark/comparator_runner.py", "def _mode_quality_superiority_comparison_valid"),
    "formal efficiency gate": ("v2/benchmark/comparator_runner.py", "def _mode_formal_efficiency_claim_allowed"),
    "serialized latency gate": ("v2/benchmark/comparator_runner.py", "serialized_latency_superiority_claim_allowed"),
    "fixed-answer quality floor": ("v2/benchmark/scoring.py", "quality_floor_pass="),
    "external pure text fairness": ("v2/benchmark/external_text_baseline.py", "def _fairness_gate"),
    "json role completion": ("v2/runtime/role_path.py", "def _complete_json_role"),
    "replay admissibility": ("v2/benchmark/continuous_runner.py", "eligible_for_replay_headline"),
    "flagship non-text stress": ("v2/benchmark/flagship_ablation.py", "def _non_text_state_stress_summary"),
    "kv reuse analysis": ("v2/benchmark/kv_analysis.py", "KV_ANALYSIS_SCHEMA_VERSION"),
}


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _safe_read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return json.load(handle)


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


def _parse_status(root: Path) -> list[dict[str, Any]]:
    status_path = root / "artifacts" / "status.tsv"
    if not status_path.exists():
        return []
    with status_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return [
            {
                "stage": row.get("stage", ""),
                "exit_code": int(row.get("exit_code", "0") or 0),
                "required": row.get("required", "0") == "1",
                "kind": row.get("kind", ""),
                "duration_s": int(row.get("duration_s", "0") or 0),
                "artifact": row.get("artifact", ""),
            }
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def _code_refs(repo_root: Path) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for label, (relative, pattern) in CODE_PATTERNS.items():
        path = repo_root / relative
        line_no = None
        if path.exists():
            for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if pattern in line:
                    line_no = idx
                    break
        refs[label] = {
            "path": relative,
            "pattern": pattern,
            "line": line_no,
        }
    return refs


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


def _case_rows(
    *,
    run_id: str,
    root: Path,
    source: Path,
    trail: tuple[str, ...],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    cases = report.get("cases")
    if not isinstance(cases, list):
        return []
    rows: list[dict[str, Any]] = []
    lane = _lane_from_trail(trail)
    for case in cases:
        if not isinstance(case, dict):
            continue
        metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
        q = case.get("quality_floor") if isinstance(case.get("quality_floor"), dict) else {}
        row_metrics = {
            key: _num(metrics.get(key))
            for key in sorted(NUMBER_KEYS)
            if key in metrics
        }
        rows.append(
            {
                "run_id": run_id,
                "stage": _stage_from_path(root, source),
                "source": _rel(root, source),
                "context": ".".join(trail[-4:]),
                "lane": lane,
                "suite_id": report.get("suite_id", ""),
                "report_task_family": report.get("task_family", ""),
                "layer": report.get("layer", ""),
                "task_id": case.get("task_id", ""),
                "task_family": case.get("task_family", report.get("task_family", "")),
                "quality_floor_pass": _bool(q.get("quality_floor_pass")),
                "quality_floor_fail_reason": q.get("quality_floor_fail_reason", ""),
                "replay_class": case.get("replay_class", ""),
                "metrics": row_metrics,
            }
        )
    return rows


def _aggregate_cases_by_family(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cases:
        key = (row.get("lane", ""), row.get("task_family") or row.get("report_task_family") or "")
        item = grouped.setdefault(
            key,
            {
                "lane": key[0],
                "family": key[1],
                "cases": 0,
                "quality_pass": 0,
                "fail_reasons": Counter(),
                "metrics": defaultdict(float),
            },
        )
        item["cases"] += 1
        if row.get("quality_floor_pass"):
            item["quality_pass"] += 1
        elif row.get("quality_floor_fail_reason"):
            item["fail_reasons"][row["quality_floor_fail_reason"]] += 1
        for metric, value in row.get("metrics", {}).items():
            item["metrics"][metric] += _num(value)
    rendered: list[dict[str, Any]] = []
    for item in grouped.values():
        rendered.append(
            {
                "lane": item["lane"],
                "family": item["family"],
                "cases": item["cases"],
                "quality_pass": item["quality_pass"],
                "fail_reasons": dict(item["fail_reasons"]),
                "metrics": dict(sorted(item["metrics"].items())),
            }
        )
    return sorted(rendered, key=lambda x: (str(x["lane"]), str(x["family"])))


def _aggregate_prompt_slices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    keys = [
        "prompt_bytes",
        "prompt_scaffolding_bytes",
        "total_prompt_visible_bytes",
        "hydrated_bytes",
        "table_bytes",
        "memory_bytes",
        "artifact_bytes",
        "external_evidence_bytes",
        "non_external_prompt_visible_bytes",
    ]
    for row in rows:
        key = (row["run_id"], row["stage"], row["role"])
        item = grouped.setdefault(
            key,
            {
                "run_id": key[0],
                "stage": key[1],
                "role": key[2],
                "count": 0,
                **{metric: 0.0 for metric in keys},
            },
        )
        item["count"] += 1
        for metric in keys:
            item[metric] += _num(row.get(metric))
    return sorted(grouped.values(), key=lambda x: (-x["prompt_bytes"], x["run_id"], x["stage"], x["role"]))


def _external_compare_summary(payload: dict[str, Any], source: str) -> dict[str, Any]:
    statebus = payload.get("statebus_report") if isinstance(payload.get("statebus_report"), dict) else {}
    external = payload.get("external_report") if isinstance(payload.get("external_report"), dict) else {}
    sb_cases = statebus.get("cases") if isinstance(statebus.get("cases"), list) else []
    ex_cases = external.get("cases") if isinstance(external.get("cases"), list) else []
    ex_by_task = {case.get("task_id"): case for case in ex_cases if isinstance(case, dict)}
    family: dict[str, dict[str, Any]] = {}
    failed_cases: list[dict[str, Any]] = []
    for sb in sb_cases:
        if not isinstance(sb, dict):
            continue
        task_id = sb.get("task_id")
        ex = ex_by_task.get(task_id, {})
        fam = str(sb.get("task_family", ex.get("task_family", "")))
        item = family.setdefault(
            fam,
            {
                "family": fam,
                "cases": 0,
                "statebus_quality_pass": 0,
                "external_quality_pass": 0,
                "prompt_delta": 0.0,
                "completion_delta": 0.0,
                "total_delta": 0.0,
                "task_ms_delta": 0.0,
                "external_fail_dimensions": Counter(),
            },
        )
        sb_metrics = sb.get("metrics") if isinstance(sb.get("metrics"), dict) else {}
        ex_metrics = ex.get("metrics") if isinstance(ex.get("metrics"), dict) else {}
        sb_q = sb.get("quality_floor") if isinstance(sb.get("quality_floor"), dict) else {}
        ex_q = ex.get("quality_floor") if isinstance(ex.get("quality_floor"), dict) else {}
        item["cases"] += 1
        item["statebus_quality_pass"] += 1 if _bool(sb_q.get("quality_floor_pass")) else 0
        ex_pass = _bool(ex_q.get("quality_floor_pass"))
        item["external_quality_pass"] += 1 if ex_pass else 0
        item["prompt_delta"] += _num(sb_metrics.get("prompt_tokens", sb_metrics.get("llm_prompt_tokens"))) - _num(
            ex_metrics.get("prompt_tokens")
        )
        item["completion_delta"] += _num(
            sb_metrics.get("completion_tokens", sb_metrics.get("llm_completion_tokens"))
        ) - _num(ex_metrics.get("completion_tokens"))
        item["total_delta"] += _num(sb_metrics.get("llm_total_tokens")) - _num(ex_metrics.get("llm_total_tokens"))
        item["task_ms_delta"] += _num(sb_metrics.get("task_ms")) - _num(
            ex_metrics.get("end_to_end_ms", ex_metrics.get("task_ms"))
        )
        if not ex_pass:
            dims = []
            for dim in (
                "route_exact",
                "tool_exact",
                "metric_name_exact",
                "metric_value_exact",
                "selected_doc_hashes_exact",
                "summary_present",
            ):
                if dim in ex_metrics and _num(ex_metrics.get(dim)) == 0.0:
                    dims.append(dim)
                    item["external_fail_dimensions"][dim] += 1
            failed_cases.append(
                {
                    "task_id": task_id,
                    "family": fam,
                    "fail_reason": ex_q.get("quality_floor_fail_reason", ""),
                    "failed_dimensions": dims,
                    "external_prompt_tokens": _num(ex_metrics.get("prompt_tokens")),
                    "external_completion_tokens": _num(ex_metrics.get("completion_tokens")),
                    "external_total_tokens": _num(ex_metrics.get("llm_total_tokens")),
                }
            )
    comp = payload.get("comparison_summary", {})
    dbg = (payload.get("mode_reports") or [{}])[0].get("debug_metrics", {}) if isinstance(payload.get("mode_reports"), list) else payload.get("debug_metrics", {})
    sb_prompt = _num(comp.get("api_statebus_prompt_tokens", comp.get("statebus_prompt_tokens", dbg.get("statebus_prompt_tokens"))))
    ex_prompt = _num(comp.get("api_external_prompt_tokens", comp.get("external_prompt_tokens", dbg.get("external_prompt_tokens"))))
    sb_completion = _num(
        comp.get("api_statebus_completion_tokens", comp.get("statebus_completion_tokens", dbg.get("statebus_completion_tokens")))
    )
    ex_completion = _num(
        comp.get("api_external_completion_tokens", comp.get("external_completion_tokens", dbg.get("external_completion_tokens")))
    )
    sb_total = _num(comp.get("api_statebus_llm_total_tokens", comp.get("statebus_llm_total_tokens", dbg.get("statebus_llm_total_tokens"))))
    ex_total = _num(comp.get("api_external_llm_total_tokens", comp.get("external_llm_total_tokens", dbg.get("external_llm_total_tokens"))))
    sb_quality = _num(dbg.get("statebus_quality_floor_pass_count"))
    ex_quality = _num(dbg.get("external_quality_floor_pass_count"))
    return {
        "source": source,
        "metadata": payload.get("metadata", {}),
        "comparison_summary": comp,
        "debug_metrics": dbg,
        "fairness_manifest": (payload.get("mode_reports") or [{}])[0].get("fairness_manifest", {})
        if isinstance(payload.get("mode_reports"), list)
        else payload.get("fairness_manifest", {}),
        "derived": {
            "statebus_prompt_tokens": sb_prompt,
            "external_prompt_tokens": ex_prompt,
            "prompt_token_reduction_ratio": (ex_prompt - sb_prompt) / ex_prompt if ex_prompt else None,
            "statebus_completion_tokens": sb_completion,
            "external_completion_tokens": ex_completion,
            "completion_token_increase_ratio": (sb_completion - ex_completion) / ex_completion if ex_completion else None,
            "statebus_total_tokens": sb_total,
            "external_total_tokens": ex_total,
            "total_token_reduction_ratio": (ex_total - sb_total) / ex_total if ex_total else None,
            "statebus_quality_pass_count": sb_quality,
            "external_quality_pass_count": ex_quality,
            "quality_pass_delta": sb_quality - ex_quality,
        },
        "family_deltas": [
            {
                **{k: v for k, v in item.items() if k != "external_fail_dimensions"},
                "external_fail_dimensions": dict(item["external_fail_dimensions"]),
            }
            for item in sorted(family.values(), key=lambda x: x["family"])
        ],
        "external_failed_cases": failed_cases,
    }


def _external_compare_candidate_payloads(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload.get("statebus_report"), dict) and isinstance(payload.get("external_report"), dict):
        candidates.append(("", payload))
    mode_reports = payload.get("mode_reports")
    if isinstance(mode_reports, list):
        for idx, mode in enumerate(mode_reports):
            if not isinstance(mode, dict):
                continue
            if not isinstance(mode.get("statebus_report"), dict) or not isinstance(mode.get("external_report"), dict):
                continue
            merged = dict(mode)
            if isinstance(payload.get("metadata"), dict) and not isinstance(merged.get("metadata"), dict):
                merged["metadata"] = payload["metadata"]
            if isinstance(payload.get("comparison_summary"), dict):
                merged["wrapper_comparison_summary"] = payload["comparison_summary"]
            suffix = f"#mode_reports[{idx}]"
            role_path_mode = mode.get("role_path_mode")
            if role_path_mode:
                suffix += f":{role_path_mode}"
            candidates.append((suffix, merged))
    return candidates


def _render_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
    rendered = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        rendered.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(rendered)


def _fmt_num(value: Any, digits: int = 1) -> str:
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


def _render_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# 2026-07-08 artifact mining 全量抽取分析",
        "",
        "本文由 `scripts/analyze_v2_artifact_evidence.py` 从 run artifact 递归抽取生成。它不是替代原始 artifact，而是把 JSON report、case、prompt slice、telemetry 和代码 gate 汇总成可读证据索引。",
        "",
        "## 输入与覆盖",
        "",
    ]
    inv_rows = []
    for run_id, run in data["runs"].items():
        inv = run["inventory"]
        inv_rows.append(
            [
                run_id,
                inv.get("json_seen", 0),
                inv.get("json_loaded", 0),
                inv.get("benchmark_reports", 0),
                inv.get("prompt_slices", 0),
                inv.get("telemetry_files", 0),
                inv.get("load_errors", 0),
            ]
        )
    lines.append(
        _render_table(
            ["Run", "json seen", "json loaded", "benchmark reports", "prompt slices", "telemetry files", "load errors"],
            inv_rows,
        )
    )
    lines.extend(["", "## Stage 状态", ""])
    stage_rows = []
    for run_id, run in data["runs"].items():
        for stage in run["stages"]:
            stage_rows.append(
                [
                    run_id,
                    stage["stage"],
                    stage["exit_code"],
                    "yes" if stage["required"] else "no",
                    stage["kind"],
                    stage["duration_s"],
                ]
            )
    lines.append(_render_table(["Run", "Stage", "Exit", "Required", "Kind", "Duration s"], stage_rows))

    ext = data["analysis"].get("formal_external_compare", {})
    lines.extend(["", "## Formal external compare", ""])
    if ext:
        meta = ext.get("metadata", {})
        comp = ext.get("comparison_summary", {})
        dbg = ext.get("debug_metrics", {})
        fair = ext.get("fairness_manifest", {})
        derived = ext.get("derived", {})
        lines.extend(
            [
                f"- source: `{ext.get('source', '')}`",
                f"- scope: `{meta.get('formal_compare_scope_label', meta.get('external_comparator_claim_scope', ''))}`",
                f"- strict_equal_quality_comparison_valid: `{meta.get('strict_equal_quality_comparison_valid')}`",
                f"- quality_superiority_comparison_valid: `{meta.get('quality_superiority_comparison_valid')}`",
                f"- formal_external_claim_kind: `{meta.get('formal_external_claim_kind')}`",
                f"- serialized_latency_superiority_claim_allowed: `{meta.get('serialized_latency_superiority_claim_allowed')}`",
                f"- external fairness: coverage=`{fair.get('external_fairness_gate_coverage')}` pass_count=`{fair.get('external_fairness_gate_pass_count')}` failed_case_count=`{fair.get('external_fairness_gate_failed_case_count')}`",
                f"- derived: prompt_reduction=`{_fmt_num(_num(derived.get('prompt_token_reduction_ratio')) * 100, 1)}%` total_reduction=`{_fmt_num(_num(derived.get('total_token_reduction_ratio')) * 100, 1)}%` completion_increase=`{_fmt_num(_num(derived.get('completion_token_increase_ratio')) * 100, 1)}%` quality_delta=`{_fmt_num(derived.get('quality_pass_delta'))}`",
                "",
            ]
        )
        token_rows = [
            ["prompt_tokens", _fmt_num(comp.get("api_statebus_prompt_tokens", dbg.get("statebus_prompt_tokens"))), _fmt_num(comp.get("api_external_prompt_tokens", dbg.get("external_prompt_tokens"))), _fmt_num(comp.get("api_prompt_tokens_delta", dbg.get("prompt_tokens_delta")))],
            ["completion_tokens", _fmt_num(comp.get("api_statebus_completion_tokens", dbg.get("statebus_completion_tokens"))), _fmt_num(comp.get("api_external_completion_tokens", dbg.get("external_completion_tokens"))), _fmt_num(comp.get("api_completion_tokens_delta", dbg.get("completion_tokens_delta")))],
            ["total_tokens", _fmt_num(comp.get("api_statebus_llm_total_tokens", dbg.get("statebus_llm_total_tokens"))), _fmt_num(comp.get("api_external_llm_total_tokens", dbg.get("external_llm_total_tokens"))), _fmt_num(comp.get("api_llm_total_tokens_delta", dbg.get("llm_total_tokens_delta")))],
            ["task_ms", "-", "-", _fmt_num(dbg.get("task_ms_delta"))],
            ["llm_ms", "-", "-", _fmt_num(dbg.get("llm_ms_delta"))],
            ["system_overhead_ms", "-", "-", _fmt_num(dbg.get("system_overhead_ms_delta"))],
        ]
        lines.append(_render_table(["Metric", "StateBus", "External", "Delta"], token_rows))
        lines.extend(["", "### Family deltas", ""])
        family_rows = []
        for row in ext.get("family_deltas", []):
            family_rows.append(
                [
                    row["family"],
                    f"{row['statebus_quality_pass']}/{row['cases']}",
                    f"{row['external_quality_pass']}/{row['cases']}",
                    _fmt_num(row["prompt_delta"]),
                    _fmt_num(row["completion_delta"]),
                    _fmt_num(row["total_delta"]),
                    row.get("external_fail_dimensions", {}),
                ]
            )
        lines.append(_render_table(["Family", "SB quality", "External quality", "Prompt delta", "Completion delta", "Total delta", "External fail dimensions"], family_rows))
        failed = ext.get("external_failed_cases", [])
        if failed:
            lines.extend(["", "### External failed cases", ""])
            lines.append(
                _render_table(
                    ["Task", "Family", "Reason", "Failed dimensions", "External total tokens"],
                    [
                        [
                            item["task_id"],
                            item["family"],
                            item["fail_reason"],
                            ",".join(item["failed_dimensions"]),
                            _fmt_num(item["external_total_tokens"]),
                        ]
                        for item in failed
                    ],
                )
            )

    formal = data["analysis"].get("formal_internal", {})
    lines.extend(["", "## Formal internal / layer waterfall", ""])
    if formal:
        lines.extend(
            [
                f"- source: `{formal.get('source', '')}`",
                f"- L3 cases: `{formal.get('L3_case_count')}` quality pass: `{formal.get('L3_quality_pass_count')}`",
                f"- state pool used: `{formal.get('state_pool_mode_used')}` memfd transfers: `{formal.get('memfd_transfer_count')}` bytes: `{formal.get('memfd_bytes_transferred')}`",
                "",
            ]
        )
        layer_rows = []
        for layer in formal.get("layers", []):
            metrics = layer.get("telemetry_summary", {})
            agg = layer.get("aggregated_metrics", {})
            layer_rows.append(
                [
                    layer.get("layer"),
                    f"{_fmt_num(agg.get('quality_floor_pass_count'))}/{_fmt_num(agg.get('case_count'))}",
                    _fmt_num(metrics.get("llm_prompt_bytes")),
                    _fmt_num(metrics.get("prompt_visible_total_bytes")),
                    _fmt_num(metrics.get("raw_evidence_bytes_seen_by_llm")),
                    _fmt_num(metrics.get("semantic_state_transfer_count")),
                    _fmt_num(metrics.get("memfd_transfer_count")),
                    _fmt_num(metrics.get("reuse_gain")),
                ]
            )
        lines.append(_render_table(["Layer", "Quality", "LLM prompt bytes", "Visible bytes", "Raw evidence bytes", "Semantic transfers", "memfd transfers", "Reuse gain"], layer_rows))

    lines.extend(["", "## Continuous / replay summaries", ""])
    cont_rows = []
    for item in data["analysis"].get("continuous_collections", []):
        s = item.get("collection_summary", {})
        cont_rows.append(
            [
                item.get("stage", ""),
                item.get("source", ""),
                _fmt_num(s.get("family_count")),
                _fmt_num(s.get("continuous_round_count")),
                _fmt_num(s.get("quality_headline_eligible_family_count")),
                _fmt_num(s.get("replay_headline_eligible_family_count")),
                _fmt_num(s.get("validated_replay_count")),
                _fmt_num(s.get("exact_replay_count")),
                _fmt_num(s.get("L3_reuse_gain")),
                _fmt_num(s.get("replay_missing_target_round_count")),
            ]
        )
    lines.append(_render_table(["Stage", "Source", "Families", "Rounds", "Quality families", "Replay families", "Validated replay", "Exact replay", "L3 reuse gain", "Missing targets"], cont_rows))

    lines.extend(["", "## Flagship non-text state stress", ""])
    flag = data["analysis"].get("flagship_stress", {})
    if flag:
        lines.extend(
            [
                f"- source: `{flag.get('source', '')}`",
                f"- stress pass: `{flag.get('stress_pass_family_count')}/{flag.get('stress_family_count')}`; claimable families: `{flag.get('claimable_non_text_state_family_count')}`; diagnostic-only: `{flag.get('diagnostic_only_family_count')}`",
                f"- total_llm_prompt_saved_by_state_ref_bytes: `{flag.get('total_llm_prompt_saved_by_state_ref_bytes')}`",
                f"- total_prompt_visible_saved_by_state_ref_bytes: `{flag.get('total_prompt_visible_saved_by_state_ref_bytes')}`",
                "",
            ]
        )
        lines.append(
            _render_table(
                ["Family", "Scope", "Pass", "LLM saved", "Visible saved", "Interpretation", "Fail reasons"],
                [
                    [
                        fam.get("family_id"),
                        fam.get("family_claim_scope"),
                        fam.get("stress_pass"),
                        _fmt_num(fam.get("llm_prompt_saved_by_state_ref_bytes")),
                        _fmt_num(fam.get("prompt_visible_saved_by_state_ref_bytes")),
                        fam.get("interpretation"),
                        ",".join(fam.get("stress_fail_reasons", [])),
                    ]
                    for fam in flag.get("families", [])
                ],
            )
        )

    lines.extend(["", "## KV prefix / CodeAct supplement", ""])
    kv = data["analysis"].get("kv_prefix", {})
    if kv:
        lines.extend(
            [
                f"- source: `{kv.get('source', '')}`",
                f"- L3 quality: `{kv.get('L3_quality_pass_count')}/{kv.get('L3_case_count')}` reuse_gain=`{kv.get('L3_reuse_gain')}`",
                f"- corpus_prefix_reuse_count=`{kv.get('L3_kv_corpus_prefix_hash_reuse_count')}` corpus_prefill_saved_estimate=`{kv.get('L3_kv_corpus_level_prefill_saved_tokens_estimate')}` engine_local_prefill_saved_estimate=`{kv.get('L3_kv_engine_local_prefill_saved_tokens_estimate')}`",
                f"- replay_headline=`{kv.get('eligible_for_replay_headline')}` replay_gate_reason=`{kv.get('replay_gate_reason')}`",
                "",
            ]
        )
    codeact = data["analysis"].get("codeact", {})
    if codeact:
        lines.extend(
            [
                f"- CodeAct source: `{codeact.get('source', '')}`",
                f"- success: `{codeact.get('success_count')}/{codeact.get('total_runs')}` target_met=`{codeact.get('target_met')}` sandbox_required=`{codeact.get('sandbox_backend_required')}`",
                "",
            ]
        )

    lines.extend(["## Workspace-level prompt slice aggregate", ""])
    prompt_rows = []
    for row in data["analysis"].get("prompt_slice_aggregate", [])[:24]:
        prompt_rows.append(
            [
                row["stage"],
                row["role"],
                row["count"],
                _fmt_num(row["prompt_bytes"]),
                _fmt_num(row["prompt_scaffolding_bytes"]),
                _fmt_num(row["total_prompt_visible_bytes"]),
                _fmt_num(row["external_evidence_bytes"]),
                _fmt_num(row["non_external_prompt_visible_bytes"]),
            ]
        )
    lines.append(_render_table(["Stage", "Role", "Count", "Prompt bytes", "Scaffolding", "Visible", "External evidence", "Non-external visible"], prompt_rows))

    lines.extend(["", "## Code gate anchors", ""])
    ref_rows = []
    for label, ref in data.get("code_refs", {}).items():
        line = ref.get("line")
        path = ref.get("path")
        ref_rows.append([label, f"`{path}:{line}`" if line else f"`{path}`", f"`{ref.get('pattern')}`"])
    lines.append(_render_table(["Gate", "Code", "Pattern"], ref_rows))

    lines.extend(
        [
            "",
            "## 综合判断",
            "",
            "- 最强证据仍是 full-registry external compare 的 quality-superiority：StateBus 25/25，external 15/25，fairness gate 25/25。失败集中在 external `metric_value_exact=0`，说明收益核心是结构化数值投影和 artifact 可审计化。",
            "- token 结论必须拆开读：prompt/total 明显下降，但 completion 明显上升。completion 上升来自严格 JSON role surface 和 `summary_json`/audit/replay 需要的结构字段。",
            "- latency 不能 claim。抽取结果和代码 gate 都指向同一结论：`serialized_latency_superiority_claim_allowed=false`，且本轮 task/LLM/system overhead delta 都为正。",
            "- replay 结论应以 validated replay 为主，exact replay 为较强子集；`long_doc_metric_replay_v1` round 7 是当前 replay-headline 缺口。",
            "- non-text StateRef 有 family-level 正证据，但不是 universal：5 个 claimable families 通过，`incident_diagnosis_v2` 是诊断负例。",
            "- KV prefix 当前只是 engine-local prefix identity/scheduling estimate；vLLM metrics/TTFT skipped，不能写真实 prefix-cache hit 或 KV tensor transfer。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def analyze_runs(run_roots: list[Path], repo_root: Path) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "statebus.v2_artifact_mining.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runs": {},
        "analysis": {},
        "code_refs": _code_refs(repo_root),
    }

    all_case_rows: list[dict[str, Any]] = []
    prompt_rows: list[dict[str, Any]] = []
    continuous_collections: list[dict[str, Any]] = []
    compare_reports: list[dict[str, Any]] = []
    external_compare_candidates: list[tuple[Path, str, dict[str, Any]]] = []
    formal_candidates: list[tuple[Path, Path, dict[str, Any]]] = []
    flagship_candidates: list[tuple[Path, Path, dict[str, Any]]] = []
    kv_candidates: list[tuple[Path, Path, dict[str, Any]]] = []
    codeact_candidates: list[tuple[Path, Path, dict[str, Any]]] = []

    for root in run_roots:
        root = root.resolve()
        run_id = root.name
        inventory = Counter()
        load_errors: list[str] = []
        run_json_summaries: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*.json")):
            inventory["json_seen"] += 1
            if "benchmark_reports" in path.parts:
                inventory["benchmark_reports"] += 1
            if "prompt_slices" in path.parts:
                inventory["prompt_slices"] += 1
            if path.name == "telemetry.json":
                inventory["telemetry_files"] += 1
            if path.name == "hydration_audit.json":
                inventory["hydration_audits"] += 1
            try:
                payload = _safe_read_json(path)
            except Exception as exc:  # pragma: no cover - diagnostic script
                load_errors.append(f"{_rel(root, path)}: {exc}")
                continue
            inventory["json_loaded"] += 1
            stage = _stage_from_path(root, path)
            rel = _rel(root, path)
            if path.name == "stdout.json" and "artifacts" in path.parts and "stages" in path.parts:
                run_json_summaries.append({"stage": stage, "source": rel, "keys": sorted(payload.keys()) if isinstance(payload, dict) else []})
            if "prompt_slices" in path.parts and isinstance(payload, dict):
                prompt_rows.append(
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "source": rel,
                        "role": str(payload.get("role", "")),
                        **{
                            key: _num(payload.get(key))
                            for key in (
                                "prompt_bytes",
                                "prompt_scaffolding_bytes",
                                "total_prompt_visible_bytes",
                                "hydrated_bytes",
                                "table_bytes",
                                "memory_bytes",
                                "artifact_bytes",
                                "external_evidence_bytes",
                                "non_external_prompt_visible_bytes",
                            )
                        },
                    }
                )
            if path.name == "telemetry.json" and isinstance(payload, list):
                event_counter = Counter(
                    str(item.get("event_type", ""))
                    for item in payload
                    if isinstance(item, dict)
                )
                data["runs"].setdefault(run_id, {}).setdefault("telemetry_event_counts", Counter()).update(event_counter)
            if isinstance(payload, dict):
                for suffix, candidate in _external_compare_candidate_payloads(payload):
                    external_compare_candidates.append((root, _rel(root, path) + suffix, candidate))
                if "layers" in payload and "formal-suite" in str(path):
                    formal_candidates.append((root, path, payload))
                if "collection_summary" in payload:
                    continuous_collections.append(
                        {
                            "run_id": run_id,
                            "stage": stage,
                            "source": rel,
                            "task_family": payload.get("task_family", ""),
                            "headline_scope": payload.get("headline_scope", ""),
                            "collection_summary": payload.get("collection_summary", {}),
                            "admissibility_summary": payload.get("admissibility_summary", {}),
                        }
                    )
                if "comparison_summary" in payload:
                    compare_reports.append(
                        {
                            "run_id": run_id,
                            "stage": stage,
                            "source": rel,
                            "metadata": payload.get("metadata", {}),
                            "comparison_summary": payload.get("comparison_summary", {}),
                        }
                    )
                if "non_text_state_stress_summary" in payload:
                    flagship_candidates.append((root, path, payload))
                if "L3_kv_corpus_prefix_hash_reuse_count" in payload or payload.get("task_family") == "kv_prefix_reuse_v1":
                    kv_candidates.append((root, path, payload))
                if payload.get("schema_version") == "statebus.local_api_codeact_acceptance_supplement.v1":
                    codeact_candidates.append((root, path, payload))
                for trail, item in _walk_dicts(payload):
                    all_case_rows.extend(_case_rows(run_id=run_id, root=root, source=path, trail=trail, report=item))
        current = data["runs"].setdefault(run_id, {})
        current.update(
            {
                "root": str(root),
                "stages": _parse_status(root),
                "stdout_json_summaries": run_json_summaries,
                "inventory": {
                    **dict(inventory),
                    "load_errors": len(load_errors),
                },
                "load_errors": load_errors[:20],
            }
        )
        if isinstance(current.get("telemetry_event_counts"), Counter):
            current["telemetry_event_counts"] = dict(current["telemetry_event_counts"])

    # Target the current source-of-truth reports first, then fall back by metadata.
    formal_external = None
    for root, source, payload in external_compare_candidates:
        meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        if meta.get("formal_compare_full_registry_coverage") is True and "r01_07_formal_compare" in source:
            formal_external = _external_compare_summary(payload, source)
            break
    if formal_external is None:
        for root, source, payload in external_compare_candidates:
            meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
            if meta.get("formal_compare_full_registry_coverage") is True:
                formal_external = _external_compare_summary(payload, source)
                break

    formal_internal = {}
    for root, path, payload in formal_candidates:
        if "r01_05_formal_api_local_memfd" in str(path):
            formal_internal = {
                "source": _rel(root, path),
                "L3_case_count": payload.get("L3_case_count"),
                "L3_quality_pass_count": payload.get("L3_quality_pass_count"),
                "state_pool_mode_used": payload.get("state_pool_mode_used"),
                "memfd_transfer_count": payload.get("memfd_transfer_count"),
                "memfd_publish_count": payload.get("memfd_publish_count"),
                "memfd_bytes_transferred": payload.get("memfd_bytes_transferred"),
                "comparison_summary": payload.get("comparison_summary", {}),
                "waterfall_metrics": payload.get("waterfall_metrics", {}),
                "layers": payload.get("layers", []),
            }
            break

    flagship = {}
    for root, path, payload in flagship_candidates:
        if "s01_10_flagship_ablation_api_local" in str(path) and path.name == "stdout.json":
            stress = dict(payload.get("non_text_state_stress_summary", {}))
            stress["source"] = _rel(root, path)
            flagship = stress
            break
    if not flagship and flagship_candidates:
        root, path, payload = flagship_candidates[-1]
        stress = dict(payload.get("non_text_state_stress_summary", {}))
        stress["source"] = _rel(root, path)
        flagship = stress

    kv = {}
    for root, path, payload in kv_candidates:
        if "s01_08_kv_prefix_demo_api_local" in str(path) and path.name == "stdout.json":
            kv = {
                "source": _rel(root, path),
                "task_family": payload.get("task_family"),
                "L3_case_count": payload.get("L3_case_count"),
                "L3_quality_pass_count": payload.get("L3_quality_pass_count"),
                "L3_reuse_gain": (payload.get("waterfall_metrics") or {}).get("L3_reuse_gain"),
                "L3_kv_corpus_prefix_hash_reuse_count": (payload.get("waterfall_metrics") or {}).get(
                    "L3_kv_corpus_prefix_hash_reuse_count"
                ),
                "L3_kv_corpus_level_prefill_saved_tokens_estimate": (payload.get("waterfall_metrics") or {}).get(
                    "L3_kv_corpus_level_prefill_saved_tokens_estimate"
                ),
                "L3_kv_engine_local_prefill_saved_tokens_estimate": (payload.get("waterfall_metrics") or {}).get(
                    "L3_kv_engine_local_prefill_saved_tokens_estimate"
                ),
                "eligible_for_quality_headline": payload.get("eligible_for_quality_headline"),
                "eligible_for_replay_headline": payload.get("eligible_for_replay_headline"),
                "replay_gate_reason": payload.get("replay_gate_reason"),
                "replay_admissibility_audit": payload.get("replay_admissibility_audit", {}),
            }
            break

    codeact = {}
    if codeact_candidates:
        root, path, payload = codeact_candidates[-1]
        codeact = {
            "source": _rel(root, path),
            "success_count": payload.get("success_count"),
            "total_runs": payload.get("total_runs"),
            "target_met": payload.get("target_met"),
            "target_success_count": payload.get("target_success_count"),
            "sandbox_backend_required": payload.get("sandbox_backend_required"),
            "runs": [
                {
                    "run": item.get("run"),
                    "ok": item.get("ok"),
                    "generated_by": item.get("generated_by"),
                    "generation_fallback_used": item.get("generation_fallback_used"),
                    "ast_policy_pass": item.get("ast_policy_pass"),
                    "sandbox_backend": item.get("sandbox_backend"),
                }
                for item in payload.get("runs", [])
                if isinstance(item, dict)
            ],
        }

    data["analysis"].update(
        {
            "formal_external_compare": formal_external or {},
            "formal_internal": formal_internal,
            "continuous_collections": continuous_collections,
            "compare_reports": compare_reports,
            "case_rows_count": len(all_case_rows),
            "case_family_aggregate": _aggregate_cases_by_family(all_case_rows),
            "prompt_slice_count": len(prompt_rows),
            "prompt_slice_aggregate": _aggregate_prompt_slices(prompt_rows),
            "flagship_stress": flagship,
            "kv_prefix": kv,
            "codeact": codeact,
        }
    )
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine StateBus v2 local+api run artifacts.")
    parser.add_argument("--run-root", action="append", required=True, help="Run root to scan. Can be passed multiple times.")
    parser.add_argument("--output-json", required=True, help="Path for machine-readable JSON summary.")
    parser.add_argument("--output-md", required=True, help="Path for markdown readout.")
    parser.add_argument("--repo-root", default=".", help="Repository root for code references.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    run_roots = [Path(item).resolve() for item in args.run_root]
    data = analyze_runs(run_roots, repo_root)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(_render_markdown(data), encoding="utf-8")


if __name__ == "__main__":
    main()
