from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.benchmark.comparator_runner import compare_fixed_answer_with_external
from v2.benchmark.external_text_baseline import (
    _build_execution_artifact_text,
    _executor_prompt,
    _load_execution_context,
    _planner_prompt,
    _retriever_prompt,
    _summarizer_prompt,
)
from v2.benchmark.fixed_answer_runner import (
    FixedAnswerSample,
    load_fixed_answer_family,
    run_fixed_answer_internal_carrier_compare_suite,
)
from v2.utils import stable_json_dumps


def _default_dev_family_dir() -> Path:
    return Path("v2/benchmark/samples/fixed_answer_family")


def _default_workspace_root() -> Path:
    return Path(os.getenv("STATEBUS_WORKDIR", "/tmp")) / "v2-live" / "workspaces"


def _default_runtime_root() -> Path:
    return Path(os.getenv("STATEBUS_RUNS_DIR", "/tmp")) / "v2-live" / "runtime"


def _default_socket_path() -> Path:
    return _default_runtime_root().parent / "control.sock"


def _default_output_root() -> Path:
    return Path(os.getenv("STATEBUS_RUNS_DIR", "/tmp")) / "v2-diagnostics"


def _default_host_runs_root() -> Path:
    return REPO_ROOT.parent / "runs"


def _default_host_work_root() -> Path:
    return REPO_ROOT.parent / "work"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return []
    return [json.loads(line) for line in lines]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _timestamp_label() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _bundle_dir(output_root: Path, suite_id: str) -> Path:
    return output_root / f"{suite_id}-{_timestamp_label()}"


def _metric(case_or_report: dict[str, Any], key: str) -> float:
    metrics = case_or_report.get("metrics", {})
    if key in metrics:
        return float(metrics[key])
    telemetry_summary = case_or_report.get("telemetry_summary", {})
    if key in telemetry_summary:
        return float(telemetry_summary[key])
    aggregated_metrics = case_or_report.get("aggregated_metrics", {})
    if key in aggregated_metrics:
        return float(aggregated_metrics[key])
    return 0.0


def _is_internal_carrier_compare(suite_payload: dict[str, Any]) -> bool:
    mode_reports = suite_payload.get("mode_reports", [])
    if not mode_reports:
        return False
    fairness_manifest = mode_reports[0].get("fairness_manifest", {})
    return fairness_manifest.get("comparison_contract") == "same_mainline_internal_text_vs_structured_carrier"


def _resolve_mounted_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.exists():
        return path
    run_root = Path(os.getenv("STATEBUS_RUNS_DIR", str(_default_host_runs_root())))
    work_root = Path(os.getenv("STATEBUS_WORKDIR", str(_default_host_work_root())))
    mappings = {
        Path("/statebus/runs"): run_root,
        Path("/statebus/work"): work_root,
    }
    for source_root, target_root in mappings.items():
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue
        candidate = target_root / relative
        if candidate.exists():
            return candidate
    return path


def _statebus_runtime_case_root(mode_payload: dict[str, Any], task_id: str) -> Path:
    report_path = _resolve_mounted_path(str(mode_payload["statebus_report"]["report_path"]))
    return report_path.parent.parent / task_id


def _role_call_count(case_payload: dict[str, Any], role: str) -> float:
    return _metric(case_payload, f"{role}_call_count")


def _count_true_flags(values: list[bool]) -> int:
    return sum(1 for value in values if value)


def _build_fairness_diagnostics(suite_payload: dict[str, Any]) -> dict[str, Any]:
    mode_results: list[dict[str, Any]] = []
    invalid_modes = 0
    for mode_payload in suite_payload.get("mode_reports", []):
        fairness_manifest = dict(mode_payload.get("fairness_manifest", {}))
        statebus_report = dict(mode_payload.get("statebus_report", {}))
        external_report = dict(mode_payload.get("external_report", {}))
        statebus_summary = statebus_report.get("telemetry_summary", {})
        external_summary = external_report.get("telemetry_summary", {})
        statebus_role_count = _count_true_flags(
            [_role_call_count({"telemetry_summary": statebus_summary}, role) > 0.0 for role in ("planner", "retriever", "executor", "summarizer")]
        )
        external_role_count = _count_true_flags(
            [_role_call_count({"telemetry_summary": external_summary}, role) > 0.0 for role in ("planner", "retriever", "executor", "summarizer")]
        )
        gate_checks = [
            {
                "gate": "object_parity_gate",
                "passed": bool(fairness_manifest.get("same_task_family")) and bool(fairness_manifest.get("same_tier")),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:705-720",
                "code_ref": "v2/benchmark/comparator_runner.py:89-96",
                "details": {
                    "same_task_family": fairness_manifest.get("same_task_family"),
                    "same_tier": fairness_manifest.get("same_tier"),
                },
            },
            {
                "gate": "role_graph_gate",
                "passed": bool(fairness_manifest.get("same_role_graph")) and statebus_role_count == 4 and external_role_count == 4,
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:705-720",
                "code_ref": "v2/benchmark/comparator_runner.py:90-103",
                "details": {
                    "same_role_graph": fairness_manifest.get("same_role_graph"),
                    "statebus_role_count": statebus_role_count,
                    "external_role_count": external_role_count,
                },
            },
            {
                "gate": "scoring_contract_gate",
                "passed": bool(fairness_manifest.get("same_scoring_contract")) and bool(
                    fairness_manifest.get("same_quality_floor_contract")
                ),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:716-730",
                "code_ref": "v2/benchmark/comparator_runner.py:91-94",
                "details": {
                    "same_scoring_contract": fairness_manifest.get("same_scoring_contract"),
                    "same_quality_floor_contract": fairness_manifest.get("same_quality_floor_contract"),
                },
            },
            {
                "gate": "oracle_leakage_gate",
                "passed": bool(fairness_manifest.get("no_external_contamination")) and not bool(
                    fairness_manifest.get("external_uses_internal_helpers")
                ),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:718-720",
                "code_ref": "v2/benchmark/comparator_runner.py:96-110",
                "details": {
                    "no_external_contamination": fairness_manifest.get("no_external_contamination"),
                    "external_uses_internal_helpers": fairness_manifest.get("external_uses_internal_helpers"),
                },
            },
            {
                "gate": "role_metric_presence_gate",
                "passed": bool(fairness_manifest.get("role_metric_presence_gate")),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:724-730",
                "code_ref": "v2/benchmark/comparator_runner.py:110-127",
                "details": {
                    "role_metric_presence_gate": fairness_manifest.get("role_metric_presence_gate"),
                },
            },
            {
                "gate": "repeat_policy_gate",
                "passed": bool(fairness_manifest.get("same_history_policy")),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:717-720",
                "code_ref": "v2/benchmark/comparator_runner.py:104-127",
                "details": {
                    "same_history_policy": fairness_manifest.get("same_history_policy"),
                    "statebus_mode": fairness_manifest.get("statebus_mode"),
                },
            },
            {
                "gate": "formal_eligibility_gate",
                "passed": bool(fairness_manifest.get("external_formal_eligible")),
                "contract_ref": "docs/planning/statebus_4_role_comparator_contract_20260620.md:698-704",
                "code_ref": "v2/benchmark/external_text_baseline.py:151-170",
                "details": {
                    "external_formal_eligible": fairness_manifest.get("external_formal_eligible"),
                    "claim_restriction": fairness_manifest.get("claim_restriction"),
                },
            },
        ]
        failed_gates = [gate["gate"] for gate in gate_checks if not gate["passed"]]
        comparison_valid = bool(mode_payload.get("comparison_valid"))
        if not comparison_valid:
            invalid_modes += 1
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "comparison_valid": comparison_valid,
                "invalid_reason": mode_payload.get("invalid_reason", ""),
                "missing_reason": mode_payload.get("missing_reason", ""),
                "claim_level": mode_payload.get("claim_level", ""),
                "pass_hard_gate": fairness_manifest.get("pass_hard_gate", False),
                "failed_gates": failed_gates,
                "gate_checks": gate_checks,
                "fairness_manifest": fairness_manifest,
                "debug_metrics": dict(mode_payload.get("debug_metrics", {})),
                "headline_metrics": dict(mode_payload.get("headline_metrics", {})),
                "conclusion": (
                    "external_comparator_admissible"
                    if comparison_valid
                    else "debug_only_fairness_fail_closed"
                    if mode_payload.get("invalid_reason") == "fairness_gate_failed"
                    else "quality_floor_failed"
                    if mode_payload.get("invalid_reason") == "quality_floor_gate_failed"
                    else "not_formal_for_other_reason"
                ),
            }
        )
    benchmark_tier = str(suite_payload.get("benchmark_tier", ""))
    if invalid_modes == 0 and mode_results:
        suite_verdict = "formal_valid" if benchmark_tier == "formal" else "dev_fixed_answer_valid"
    else:
        invalid_reasons = {str(result["invalid_reason"]) for result in mode_results if result["invalid_reason"]}
        fairness_failed = any(
            result["invalid_reason"] == "fairness_gate_failed" or bool(result["failed_gates"])
            for result in mode_results
        )
        if fairness_failed:
            suite_verdict = "formal_invalid_debug_only"
        elif "quality_floor_gate_failed" in invalid_reasons:
            suite_verdict = (
                "formal_quality_floor_invalid"
                if benchmark_tier == "formal"
                else "dev_fixed_answer_quality_invalid"
            )
        elif any(result["missing_reason"] for result in mode_results):
            suite_verdict = "external_compare_missing"
        else:
            suite_verdict = "external_compare_invalid"
    contract_problem = _fairness_contract_problem(mode_results, suite_verdict)
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "benchmark_tier": benchmark_tier,
        "claim_level": suite_payload.get("claim_level", ""),
        "suite_verdict": suite_verdict,
        "contract_problem": contract_problem,
        "mode_results": mode_results,
        "summary": {
            "mode_count": len(mode_results),
            "valid_mode_count": sum(1 for result in mode_results if result["comparison_valid"]),
            "fairness_failed_mode_count": sum(
                1 for result in mode_results if result["invalid_reason"] == "fairness_gate_failed"
            ),
            "quality_floor_failed_mode_count": sum(
                1 for result in mode_results if result["invalid_reason"] == "quality_floor_gate_failed"
            ),
        },
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md:1452-1508",
            "docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md:214-279",
            "docs/planning/statebus_4_role_comparator_contract_20260620.md:684-760",
            "docs/planning/benchmark_quality_floor_contract.md:21-28",
        ],
    }


def _fairness_contract_problem(mode_results: list[dict[str, Any]], suite_verdict: str) -> str:
    if suite_verdict in {"formal_valid", "dev_fixed_answer_valid"}:
        return "none"
    if any(
        result.get("invalid_reason") == "fairness_gate_failed" or bool(result.get("failed_gates"))
        for result in mode_results
    ):
        return "fairness_gate_fail_closed_blocks_comparator_claim"
    if any(result.get("invalid_reason") == "quality_floor_gate_failed" for result in mode_results):
        return "quality_floor_gate_failed_blocks_comparator_claim"
    if any(result.get("missing_reason") for result in mode_results):
        return "missing_mode_blocks_comparator_claim"
    return "invalid_mode_blocks_comparator_claim"


def _external_prompt_rows(
    *,
    samples: list[FixedAnswerSample],
    mode_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    statebus_cases = {
        case["task_id"]: case for case in mode_payload.get("statebus_report", {}).get("cases", [])
    }
    external_cases = {
        case["task_id"]: case for case in mode_payload.get("external_report", {}).get("cases", [])
    }
    rows: list[dict[str, Any]] = []
    for sample in samples:
        if sample.task_id not in statebus_cases or sample.task_id not in external_cases:
            continue
        context = _load_execution_context(sample)
        planner_payload = {"route": sample.expected_route, "tool_name": sample.expected_tool_name}
        artifact_text = _build_execution_artifact_text(
            context=context,
            route=sample.expected_route,
            tool_name=sample.expected_tool_name,
        )
        planner_prompt = _planner_prompt(sample=sample, context=context)
        retriever_prompt = _retriever_prompt(sample=sample, context=context, planner_payload=planner_payload)
        # Use a compact evidence_summary for executor/summarizer (they don't see full corpus).
        _evidence_summary = f"Evidence for {sample.task_id}: revenue={context.revenue_value} docs={','.join(context.public_doc_hashes)}"
        executor_prompt = _executor_prompt(
            sample=sample,
            context=context,
            route=sample.expected_route,
            tool_name=sample.expected_tool_name,
            evidence_summary=_evidence_summary,
        )
        summarizer_prompt = _summarizer_prompt(
            sample=sample,
            context=context,
            route=sample.expected_route,
            tool_name=sample.expected_tool_name,
            execution_artifact_text=artifact_text,
            evidence_summary=_evidence_summary,
        )
        public_evidence_bytes = len(context.public_evidence_text.encode("utf-8"))
        planner_has_full_evidence = context.public_evidence_text in planner_prompt
        retriever_has_full_evidence = context.public_evidence_text in retriever_prompt
        executor_has_full_evidence = context.public_evidence_text in executor_prompt
        summarizer_has_full_evidence = context.public_evidence_text in summarizer_prompt
        evidence_role_count = _count_true_flags(
            [
                planner_has_full_evidence,
                retriever_has_full_evidence,
                executor_has_full_evidence,
                summarizer_has_full_evidence,
            ]
        )
        statebus_metrics = statebus_cases[sample.task_id]["metrics"]
        external_metrics = external_cases[sample.task_id]["metrics"]
        rows.append(
            {
                "task_id": sample.task_id,
                "public_evidence_bytes": public_evidence_bytes,
                "public_doc_hash_count": len(context.public_doc_hashes),
                "route_candidate_count": len(context.route_candidates),
                "external_roles_with_full_evidence_text": evidence_role_count,
                "external_repeated_public_evidence_bytes": public_evidence_bytes * evidence_role_count,
                "planner_prompt_bytes": len(planner_prompt.encode("utf-8")),
                "retriever_prompt_bytes": len(retriever_prompt.encode("utf-8")),
                "executor_prompt_bytes": len(executor_prompt.encode("utf-8")),
                "summarizer_prompt_bytes": len(summarizer_prompt.encode("utf-8")),
                "external_prompt_bytes_reported": float(external_metrics.get("prompt_bytes", 0.0)),
                "external_text_bytes_reported": float(external_metrics.get("text_bytes", 0.0)),
                "statebus_prompt_bytes_reported": float(statebus_metrics.get("llm_prompt_bytes", 0.0)),
                "statebus_raw_evidence_bytes_seen_by_llm": float(
                    statebus_metrics.get("raw_evidence_bytes_seen_by_llm", 0.0)
                ),
                "statebus_planner_hydrated_bytes": float(statebus_metrics.get("planner_hydrated_bytes", 0.0)),
                "statebus_retriever_hydrated_bytes": float(statebus_metrics.get("retriever_hydrated_bytes", 0.0)),
                "statebus_executor_hydrated_bytes": float(statebus_metrics.get("executor_hydrated_bytes", 0.0)),
                "statebus_summarizer_hydrated_bytes": float(statebus_metrics.get("summarizer_hydrated_bytes", 0.0)),
                "statebus_planner_text_bytes": float(statebus_metrics.get("planner_text_bytes", 0.0)),
                "statebus_retriever_text_bytes": float(statebus_metrics.get("retriever_text_bytes", 0.0)),
                "statebus_executor_text_bytes": float(statebus_metrics.get("executor_text_bytes", 0.0)),
                "statebus_summarizer_text_bytes": float(statebus_metrics.get("summarizer_text_bytes", 0.0)),
                "statebus_planner_table_bytes": float(statebus_metrics.get("planner_table_bytes", 0.0)),
                "statebus_retriever_table_bytes": float(statebus_metrics.get("retriever_table_bytes", 0.0)),
                "statebus_executor_table_bytes": float(statebus_metrics.get("executor_table_bytes", 0.0)),
                "statebus_summarizer_table_bytes": float(statebus_metrics.get("summarizer_table_bytes", 0.0)),
                "statebus_memory_bytes_total": float(
                    statebus_metrics.get("planner_memory_bytes", 0.0)
                    + statebus_metrics.get("retriever_memory_bytes", 0.0)
                    + statebus_metrics.get("executor_memory_bytes", 0.0)
                    + statebus_metrics.get("summarizer_memory_bytes", 0.0)
                ),
            }
        )
    return rows


def _build_text_lane_diagnostics(
    suite_payload: dict[str, Any],
    *,
    family_dir: Path,
) -> dict[str, Any]:
    samples = load_fixed_answer_family(family_dir)
    mode_results: list[dict[str, Any]] = []
    for mode_payload in suite_payload.get("mode_reports", []):
        rows = _external_prompt_rows(samples=samples, mode_payload=mode_payload)
        external_report = mode_payload.get("external_report", {})
        statebus_report = mode_payload.get("statebus_report", {})
        external_profile = external_report.get("profile", {})
        statebus_profile = statebus_report.get("profile", {})
        debug_reasonable_checks = {
            "same_task_family": external_report.get("task_family") == statebus_report.get("task_family"),
            "same_role_graph": external_report.get("metadata", {}).get("role_graph")
            == statebus_report.get("metadata", {}).get("role_graph"),
            "same_scoring_contract": external_report.get("metadata", {}).get("scoring_contract")
            == statebus_report.get("metadata", {}).get("scoring_contract"),
            "same_quality_floor_contract": external_report.get("metadata", {}).get("quality_floor_contract")
            == statebus_report.get("metadata", {}).get("quality_floor_contract"),
            "same_llm_call_count": mode_payload.get("debug_metrics", {}).get("llm_call_count_delta", 1.0) == 0.0,
            "same_exact_match": mode_payload.get("debug_metrics", {}).get("exact_match_delta", 1.0) == 0.0,
        }
        external_public_broadcast_bytes = sum(row["external_repeated_public_evidence_bytes"] for row in rows)
        statebus_raw_evidence_bytes = sum(row["statebus_raw_evidence_bytes_seen_by_llm"] for row in rows)
        formal_blockers = [
            "dev_fixed_answer_scope_not_formal_financial_family",
            "external_profile_disables_structured_control_semantic_pruning_replay",
            "external_repeats_full_public_evidence_text_across_all_roles",
            "statebus_lane_carries_workspace_artifact_telemetry_replay_obligations_not_shared_by_external",
        ]
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "verdict": "reasonable_for_debug_not_formal",
                "debug_reasonable_checks": debug_reasonable_checks,
                "debug_reasonable_check_count": sum(1 for value in debug_reasonable_checks.values() if value),
                "formal_blockers": formal_blockers,
                "external_profile": external_profile,
                "statebus_profile": statebus_profile,
                "external_prompt_construction": {
                    "public_evidence_text_broadcast_to_roles": ["planner", "retriever", "executor", "summarizer"],
                    "structured_control_enabled": external_profile.get("structured_control_enabled"),
                    "semantic_pruning_enabled": external_profile.get("semantic_pruning_enabled"),
                    "replay_enabled": external_profile.get("replay_enabled"),
                },
                "statebus_runtime_obligations": {
                    "structured_control_enabled": statebus_profile.get("structured_control_enabled"),
                    "semantic_pruning_enabled": statebus_profile.get("semantic_pruning_enabled"),
                    "replay_enabled": statebus_profile.get("replay_enabled"),
                },
                "suite_metrics": {
                    "external_public_broadcast_bytes": external_public_broadcast_bytes,
                    "statebus_raw_evidence_bytes_seen_by_llm": statebus_raw_evidence_bytes,
                    "prompt_bytes_delta": float(mode_payload.get("debug_metrics", {}).get("prompt_bytes_delta", 0.0)),
                },
                "sample_rows": rows,
            }
        )
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "suite_verdict": "reasonable_for_debug_not_formal",
        "mode_results": mode_results,
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md:121-134",
            "docs/planning/semantic_provenance_and_hydration_contract.md:260-345",
            "docs/planning/statebus_4_role_comparator_contract_20260620.md:705-720",
            "v2/benchmark/external_text_baseline.py:26-34",
            "v2/benchmark/external_text_baseline.py:214-354",
            "v2/runtime/smoke.py:1493-1566",
        ],
    }


def _event_type_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        counts[str(event.get("event_type", ""))] += 1
    return dict(sorted(counts.items()))


def _role_event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        role = str(event.get("role", "")).strip()
        if role:
            counts[role] += 1
    return dict(sorted(counts.items()))


def _build_runtime_diagnostics(suite_payload: dict[str, Any]) -> dict[str, Any]:
    mode_results: list[dict[str, Any]] = []
    for mode_payload in suite_payload.get("mode_reports", []):
        statebus_cases = {
            case["task_id"]: case for case in mode_payload.get("statebus_report", {}).get("cases", [])
        }
        external_cases = {
            case["task_id"]: case for case in mode_payload.get("external_report", {}).get("cases", [])
        }
        case_rows: list[dict[str, Any]] = []
        aggregate_event_counts: Counter[str] = Counter()
        aggregate_role_counts: Counter[str] = Counter()
        total_statebus_non_llm_ms = 0.0
        total_external_non_llm_ms = 0.0
        total_task_delta_ms = 0.0
        total_llm_delta_ms = 0.0
        for task_id, statebus_case in statebus_cases.items():
            external_case = external_cases.get(task_id)
            if external_case is None:
                continue
            statebus_metrics = statebus_case.get("metrics", {})
            external_metrics = external_case.get("metrics", {})
            statebus_task_ms = float(statebus_metrics.get("task_ms", 0.0))
            statebus_llm_ms = float(statebus_metrics.get("llm_wall_ms", 0.0))
            statebus_non_llm_ms = max(statebus_task_ms - statebus_llm_ms, 0.0)
            external_task_ms = float(external_metrics.get("end_to_end_ms", external_metrics.get("task_ms", 0.0)))
            external_llm_ms = float(external_metrics.get("llm_ms", 0.0))
            external_non_llm_ms = max(external_task_ms - external_llm_ms, 0.0)
            total_statebus_non_llm_ms += statebus_non_llm_ms
            total_external_non_llm_ms += external_non_llm_ms
            total_task_delta_ms += statebus_task_ms - external_task_ms
            total_llm_delta_ms += statebus_llm_ms - external_llm_ms
            case_runtime_root = _statebus_runtime_case_root(mode_payload, task_id)
            event_path = case_runtime_root / "telemetry" / "runtime_events.jsonl"
            fact_path = case_runtime_root / "telemetry" / "runtime_facts.jsonl"
            events = _read_jsonl(event_path)
            facts = _read_jsonl(fact_path)
            event_counts = _event_type_counts(events)
            role_counts = _role_event_counts(events)
            aggregate_event_counts.update(event_counts)
            aggregate_role_counts.update(role_counts)
            statebus_bucket_sum = round(
                sum(
                    float(statebus_metrics.get(key, 0.0))
                    for key in (
                        "workspace_input_stage_ms",
                        "runtime_signature_stage_ms",
                        "codeact_execution_stage_ms",
                        "execution_log_capture_stage_ms",
                        "workspace_output_stage_ms",
                        "runtime_non_executor_stage_ms",
                        "runtime_data_plane_event_stage_ms",
                        "control_plane_exchange_stage_ms",
                        "executor_state_machine_stage_ms",
                        "runtime_commit_finalize_stage_ms",
                        "runtime_post_executor_stage_ms",
                        "runtime_replay_ledger_stage_ms",
                        "persist_and_reload_stage_ms",
                        "registry_query_stage_ms",
                    )
                ),
                6,
            )
            driver_bucket_sum = round(
                sum(
                    float(statebus_metrics.get(key, 0.0))
                    for key in (
                        "runtime_non_executor_stage_ms",
                        "runtime_data_plane_event_stage_ms",
                        "control_plane_exchange_stage_ms",
                        "executor_state_machine_stage_ms",
                        "runtime_commit_finalize_stage_ms",
                        "runtime_post_executor_stage_ms",
                        "runtime_replay_ledger_stage_ms",
                        "persist_and_reload_stage_ms",
                        "registry_query_stage_ms",
                    )
                ),
                6,
            )
            case_rows.append(
                {
                    "task_id": task_id,
                    "statebus_task_ms": round(statebus_task_ms, 6),
                    "statebus_llm_ms": round(statebus_llm_ms, 6),
                    "statebus_non_llm_ms": round(statebus_non_llm_ms, 6),
                    "external_task_ms": round(external_task_ms, 6),
                    "external_llm_ms": round(external_llm_ms, 6),
                    "external_non_llm_ms": round(external_non_llm_ms, 6),
                    "task_ms_delta": round(statebus_task_ms - external_task_ms, 6),
                    "llm_ms_delta": round(statebus_llm_ms - external_llm_ms, 6),
                    "non_llm_ms_delta": round(statebus_non_llm_ms - external_non_llm_ms, 6),
                    "non_llm_delta_share_of_task_delta": round(
                        0.0
                        if statebus_task_ms == external_task_ms
                        else (statebus_non_llm_ms - external_non_llm_ms) / (statebus_task_ms - external_task_ms),
                        6,
                    ),
                    "statebus_prompt_bytes": round(float(statebus_metrics.get("llm_prompt_bytes", 0.0)), 3),
                    "external_prompt_bytes": round(float(external_metrics.get("prompt_bytes", 0.0)), 3),
                    "statebus_raw_evidence_bytes_seen_by_llm": round(
                        float(statebus_metrics.get("raw_evidence_bytes_seen_by_llm", 0.0)),
                        3,
                    ),
                    "statebus_workspace_files": int(statebus_metrics.get("workspace_files", 0.0)),
                    "statebus_telemetry_event_count": int(statebus_case.get("telemetry_event_count", 0)),
                    "runtime_event_log_present": event_path.exists(),
                    "runtime_fact_log_present": fact_path.exists(),
                    "runtime_event_line_count": len(events),
                    "runtime_fact_line_count": len(facts),
                    "artifact_count": int(statebus_metrics.get("artifact_count", 0.0)),
                    "validator_report_count": int(statebus_metrics.get("validator_report_count", 0.0)),
                    "memory_commit_count": int(statebus_metrics.get("memory_commit_count", 0.0)),
                    "replay_ledger_entry_count": int(statebus_metrics.get("replay_ledger_entry_count", 0.0)),
                    "retrieval_log_count": int(statebus_metrics.get("retrieval_log_count", 0.0)),
                    "codeact_plan_stage_count": int(statebus_metrics.get("codeact_plan_stage_count", 0.0)),
                    "codeact_plan_action_count": int(statebus_metrics.get("codeact_plan_action_count", 0.0)),
                    "workspace_input_stage_ms": round(float(statebus_metrics.get("workspace_input_stage_ms", 0.0)), 6),
                    "workspace_output_stage_ms": round(float(statebus_metrics.get("workspace_output_stage_ms", 0.0)), 6),
                    "execution_log_capture_stage_ms": round(
                        float(statebus_metrics.get("execution_log_capture_stage_ms", 0.0)),
                        6,
                    ),
                    "codeact_execution_stage_ms": round(
                        float(statebus_metrics.get("codeact_execution_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_driver_stage_ms": round(float(statebus_metrics.get("runtime_driver_stage_ms", 0.0)), 6),
                    "planner_runtime_stage_ms": round(float(statebus_metrics.get("planner_runtime_stage_ms", 0.0)), 6),
                    "retriever_runtime_stage_ms": round(
                        float(statebus_metrics.get("retriever_runtime_stage_ms", 0.0)),
                        6,
                    ),
                    "summarizer_runtime_stage_ms": round(
                        float(statebus_metrics.get("summarizer_runtime_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_non_executor_stage_ms": round(
                        float(statebus_metrics.get("runtime_non_executor_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_data_plane_event_stage_ms": round(
                        float(statebus_metrics.get("runtime_data_plane_event_stage_ms", 0.0)),
                        6,
                    ),
                    "control_plane_exchange_stage_ms": round(
                        float(statebus_metrics.get("control_plane_exchange_stage_ms", 0.0)),
                        6,
                    ),
                    "executor_state_machine_stage_ms": round(
                        float(statebus_metrics.get("executor_state_machine_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_commit_finalize_stage_ms": round(
                        float(statebus_metrics.get("runtime_commit_finalize_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_post_executor_stage_ms": round(
                        float(statebus_metrics.get("runtime_post_executor_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_replay_ledger_stage_ms": round(
                        float(statebus_metrics.get("runtime_replay_ledger_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_signature_stage_ms": round(
                        float(statebus_metrics.get("runtime_signature_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_signature_capture_stage_ms": round(
                        float(statebus_metrics.get("runtime_signature_capture_stage_ms", 0.0)),
                        6,
                    ),
                    "runtime_signature_materialize_stage_ms": round(
                        float(statebus_metrics.get("runtime_signature_materialize_stage_ms", 0.0)),
                        6,
                    ),
                    "persist_and_reload_stage_ms": round(
                        float(statebus_metrics.get("persist_and_reload_stage_ms", 0.0)),
                        6,
                    ),
                    "registry_query_stage_ms": round(float(statebus_metrics.get("registry_query_stage_ms", 0.0)), 6),
                    "telemetry_emit_stage_ms": round(float(statebus_metrics.get("telemetry_emit_stage_ms", 0.0)), 6),
                    "telemetry_event_write_stage_ms": round(
                        float(statebus_metrics.get("telemetry_event_write_stage_ms", 0.0)),
                        6,
                    ),
                    "telemetry_fact_write_stage_ms": round(
                        float(statebus_metrics.get("telemetry_fact_write_stage_ms", 0.0)),
                        6,
                    ),
                    "telemetry_event_write_count": int(statebus_metrics.get("telemetry_event_write_count", 0.0)),
                    "telemetry_fact_write_count": int(statebus_metrics.get("telemetry_fact_write_count", 0.0)),
                    "telemetry_log_handle_open_count": int(
                        statebus_metrics.get("telemetry_log_handle_open_count", 0.0)
                    ),
                    "observed_bucket_sum_stage_ms": statebus_bucket_sum,
                    "estimated_unbucketed_non_llm_ms": round(statebus_non_llm_ms - statebus_bucket_sum, 6),
                    "driver_bucket_sum_stage_ms": driver_bucket_sum,
                    "estimated_unbucketed_within_driver_stage_ms": round(
                        float(statebus_metrics.get("runtime_driver_stage_ms", 0.0)) - driver_bucket_sum,
                        6,
                    ),
                    "workspace_input_direct_write_count": int(
                        statebus_metrics.get("workspace_input_direct_write_count", 0.0)
                    ),
                    "workspace_input_bundle_write_count": int(
                        statebus_metrics.get("workspace_input_bundle_write_count", 0.0)
                    ),
                    "workspace_input_bundle_reused_count": int(
                        statebus_metrics.get("workspace_input_bundle_reused_count", 0.0)
                    ),
                    "workspace_output_bundle_write_count": int(
                        statebus_metrics.get("workspace_output_bundle_write_count", 0.0)
                    ),
                    "workspace_output_bundle_reused_count": int(
                        statebus_metrics.get("workspace_output_bundle_reused_count", 0.0)
                    ),
                    "event_type_counts": event_counts,
                    "role_event_counts": role_counts,
                }
            )
        non_llm_delta = total_statebus_non_llm_ms - total_external_non_llm_ms
        aggregate_bucket_totals = {
            "workspace_input_stage_ms_total": round(
                sum(row["workspace_input_stage_ms"] for row in case_rows),
                6,
            ),
            "workspace_output_stage_ms_total": round(
                sum(row["workspace_output_stage_ms"] for row in case_rows),
                6,
            ),
            "codeact_execution_stage_ms_total": round(
                sum(row["codeact_execution_stage_ms"] for row in case_rows),
                6,
            ),
            "execution_log_capture_stage_ms_total": round(
                sum(row["execution_log_capture_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_driver_stage_ms_total": round(
                sum(row["runtime_driver_stage_ms"] for row in case_rows),
                6,
            ),
            "planner_runtime_stage_ms_total": round(
                sum(row["planner_runtime_stage_ms"] for row in case_rows),
                6,
            ),
            "retriever_runtime_stage_ms_total": round(
                sum(row["retriever_runtime_stage_ms"] for row in case_rows),
                6,
            ),
            "summarizer_runtime_stage_ms_total": round(
                sum(row["summarizer_runtime_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_non_executor_stage_ms_total": round(
                sum(row["runtime_non_executor_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_data_plane_event_stage_ms_total": round(
                sum(row["runtime_data_plane_event_stage_ms"] for row in case_rows),
                6,
            ),
            "control_plane_exchange_stage_ms_total": round(
                sum(row["control_plane_exchange_stage_ms"] for row in case_rows),
                6,
            ),
            "executor_state_machine_stage_ms_total": round(
                sum(row["executor_state_machine_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_commit_finalize_stage_ms_total": round(
                sum(row["runtime_commit_finalize_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_post_executor_stage_ms_total": round(
                sum(row["runtime_post_executor_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_replay_ledger_stage_ms_total": round(
                sum(row["runtime_replay_ledger_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_signature_stage_ms_total": round(
                sum(row["runtime_signature_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_signature_capture_stage_ms_total": round(
                sum(row["runtime_signature_capture_stage_ms"] for row in case_rows),
                6,
            ),
            "runtime_signature_materialize_stage_ms_total": round(
                sum(row["runtime_signature_materialize_stage_ms"] for row in case_rows),
                6,
            ),
            "persist_and_reload_stage_ms_total": round(
                sum(row["persist_and_reload_stage_ms"] for row in case_rows),
                6,
            ),
            "registry_query_stage_ms_total": round(
                sum(row["registry_query_stage_ms"] for row in case_rows),
                6,
            ),
            "observed_bucket_sum_stage_ms_total": round(
                sum(row["observed_bucket_sum_stage_ms"] for row in case_rows),
                6,
            ),
            "estimated_unbucketed_non_llm_ms_total": round(
                sum(row["estimated_unbucketed_non_llm_ms"] for row in case_rows),
                6,
            ),
            "driver_bucket_sum_stage_ms_total": round(
                sum(row["driver_bucket_sum_stage_ms"] for row in case_rows),
                6,
            ),
            "estimated_unbucketed_within_driver_stage_ms_total": round(
                sum(row["estimated_unbucketed_within_driver_stage_ms"] for row in case_rows),
                6,
            ),
        }
        cross_cutting_observation_totals = {
            "telemetry_emit_stage_ms_total": round(
                sum(row["telemetry_emit_stage_ms"] for row in case_rows),
                6,
            ),
            "telemetry_event_write_stage_ms_total": round(
                sum(row["telemetry_event_write_stage_ms"] for row in case_rows),
                6,
            ),
            "telemetry_fact_write_stage_ms_total": round(
                sum(row["telemetry_fact_write_stage_ms"] for row in case_rows),
                6,
            ),
            "telemetry_event_write_count_total": int(
                sum(row["telemetry_event_write_count"] for row in case_rows)
            ),
            "telemetry_fact_write_count_total": int(
                sum(row["telemetry_fact_write_count"] for row in case_rows)
            ),
            "telemetry_log_handle_open_count_total": int(
                sum(row["telemetry_log_handle_open_count"] for row in case_rows)
            ),
        }
        suite_summary = {
            "statebus_non_llm_ms_total": round(total_statebus_non_llm_ms, 6),
            "external_non_llm_ms_total": round(total_external_non_llm_ms, 6),
            "non_llm_ms_delta_total": round(non_llm_delta, 6),
            "task_ms_delta_total": round(total_task_delta_ms, 6),
            "llm_ms_delta_total": round(total_llm_delta_ms, 6),
            "non_llm_delta_share_of_task_delta": round(
                0.0 if total_task_delta_ms == 0.0 else non_llm_delta / total_task_delta_ms,
                6,
            ),
            "dominant_gap": (
                "runtime_non_llm_overhead"
                if total_task_delta_ms > 0.0 and non_llm_delta > total_llm_delta_ms
                else "llm_or_mixed_gap"
            ),
            "aggregate_event_type_counts": dict(sorted(aggregate_event_counts.items())),
            "aggregate_role_event_counts": dict(sorted(aggregate_role_counts.items())),
            "aggregate_bucket_totals": aggregate_bucket_totals,
            "cross_cutting_observation_totals": cross_cutting_observation_totals,
        }
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "suite_summary": suite_summary,
                "case_rows": case_rows,
            }
        )
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "suite_verdict": "runtime_non_llm_overhead_dominates" if mode_results else "no_data",
        "mode_results": mode_results,
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/runtime_state_machine_contract.md:35-125",
            "docs/planning/telemetry_event_contract.md:22-134",
            "docs/planning/semantic_provenance_and_hydration_contract.md:260-345",
            "v2/runtime/smoke.py:1493-1605",
        ],
    }


def _build_experiment_plan(
    bundle_dir: Path,
    *,
    output_root: Path,
    family_dir: Path,
    compare_kind: str,
) -> dict[str, Any]:
    runs_dir = Path(os.getenv("STATEBUS_RUNS_DIR", "/statebus/runs"))
    if compare_kind == "carrier":
        return {
            "output_bundle_dir": str(bundle_dir),
            "recommended_experiments": [
                {
                    "experiment_id": "C1-rerun-carrier-compare",
                    "goal": "Regenerate deterministic cold-start same-mainline carrier compare and write a fresh diagnostics bundle.",
                    "command": (
                        "python3 scripts/v2_diagnostics/compare_diagnostics.py "
                        "--compare-kind carrier "
                        "--suite-id statebus-v2-diagnostics-carrier-compare "
                        f"--family-dir {family_dir} "
                        "--role-path-mode deterministic "
                        "--embedding-mode deterministic "
                        "--statebus-mode cold-start "
                        f"--output-root {output_root}"
                    ),
                    "expected_signal": "same_mainline carrier-only prompt/runtime deltas with no external fairness blocker",
                },
                {
                    "experiment_id": "C2-lane-local-runs",
                    "goal": "Inspect text-only and structured-only mainline suites separately before attributing carrier deltas.",
                    "commands": [
                        "python3 -m v2.benchmark.live_runner --suite statebus --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic --statebus-mode cold-start",
                        "python3 -m v2.benchmark.live_runner --suite carrier-compare --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic --statebus-mode cold-start",
                    ],
                    "expected_signal": "layer-local plus carrier-local telemetry with same mainline ownership",
                },
                {
                    "experiment_id": "C3-formal-family-check",
                    "goal": "Use the formal financial family to inspect whether the same accounting assumptions remain honest on formal tasks.",
                    "command": "python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic",
                    "expected_signal": "formal family evidence separated from dev carrier-only compare",
                },
            ],
        }
    return {
        "output_bundle_dir": str(bundle_dir),
        "recommended_experiments": [
            {
                "experiment_id": "E1-current-compare-fairness-audit",
                "goal": "Verify whether the current dev fixed-answer compare is admissible under the external fairness gate.",
                "command": (
                    "python3 scripts/v2_diagnostics/compare_diagnostics.py "
                    f"--compare-suite-report {runs_dir / 'v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json'} "
                    f"--output-root {output_root}"
                ),
                "expected_signal": "dev_fixed_answer_valid when the fairness gate passes; not a formal superiority claim",
            },
            {
                "experiment_id": "E2-rerun-dev-compare-and-analyze",
                "goal": "Regenerate deterministic cold-start compare and immediately write a new diagnostics bundle.",
                "command": (
                    "python3 scripts/v2_diagnostics/compare_diagnostics.py "
                    f"--family-dir {family_dir} "
                    "--role-path-mode deterministic "
                    "--embedding-mode deterministic "
                    "--statebus-mode cold-start "
                    f"--output-root {output_root}"
                ),
                "expected_signal": "fresh compare report plus fairness/text/runtime diagnostics in one bundle",
            },
            {
                "experiment_id": "E3-lane-local-runs",
                "goal": "Inspect StateBus-only and external-only lanes separately before attributing compare deltas.",
                "commands": [
                    "python3 -m v2.benchmark.live_runner --suite statebus --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic --statebus-mode cold-start",
                    "python3 -m v2.benchmark.live_runner --suite external --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic",
                ],
                "expected_signal": "lane-local telemetry without fairness narrative",
            },
            {
                "experiment_id": "E4-formal-family-check",
                "goal": "Use the formal financial family to inspect L0-L3 and non-text evidence accounting independent of external compare fairness.",
                "command": "python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic",
                "expected_signal": "formal family evidence that should be read separately from dev fixed-answer compare",
            },
        ],
    }


def _build_internal_carrier_fairness_diagnostics(suite_payload: dict[str, Any]) -> dict[str, Any]:
    mode_results: list[dict[str, Any]] = []
    for mode_payload in suite_payload.get("mode_reports", []):
        fairness_manifest = dict(mode_payload.get("fairness_manifest", {}))
        gate_checks = [
            {"gate": "same_task_family", "passed": bool(fairness_manifest.get("same_task_family"))},
            {"gate": "same_role_graph", "passed": bool(fairness_manifest.get("same_role_graph"))},
            {"gate": "same_scoring_contract", "passed": bool(fairness_manifest.get("same_scoring_contract"))},
            {"gate": "same_quality_floor_contract", "passed": bool(fairness_manifest.get("same_quality_floor_contract"))},
            {"gate": "same_role_path_mode", "passed": bool(fairness_manifest.get("same_role_path_mode"))},
            {"gate": "same_embedding_mode", "passed": bool(fairness_manifest.get("same_embedding_mode"))},
            {"gate": "same_statebus_mode", "passed": bool(fairness_manifest.get("same_statebus_mode"))},
            {"gate": "same_semantic_pruning", "passed": bool(fairness_manifest.get("same_semantic_pruning"))},
            {"gate": "same_replay_policy", "passed": bool(fairness_manifest.get("same_replay_policy"))},
            {"gate": "same_four_role_counts", "passed": bool(fairness_manifest.get("same_four_role_counts"))},
            {"gate": "text_handoff_mode", "passed": fairness_manifest.get("text_handoff_mode") == "text_collaboration"},
            {
                "gate": "structured_handoff_mode",
                "passed": fairness_manifest.get("structured_handoff_mode") == "structured_collaboration",
            },
        ]
        failed_gates = [gate["gate"] for gate in gate_checks if not gate["passed"]]
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "comparison_valid": bool(mode_payload.get("comparison_valid", False)),
                "invalid_reason": str(mode_payload.get("invalid_reason", "")),
                "conclusion": (
                    "internal_carrier_single_variable_valid"
                    if not failed_gates and bool(mode_payload.get("comparison_valid", False))
                    else "internal_carrier_gate_failed"
                ),
                "failed_gates": failed_gates,
                "gate_checks": gate_checks,
                "fairness_manifest": fairness_manifest,
                "debug_metrics": dict(mode_payload.get("debug_metrics", {})),
            }
        )
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "suite_verdict": (
            "internal_carrier_single_variable_valid"
            if mode_results and all(not mode["failed_gates"] for mode in mode_results)
            else "internal_carrier_gate_failed"
        ),
        "mode_results": mode_results,
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md:148-163",
            "docs/planning/statebus_4_role_comparator_contract_20260620.md:44-58",
        ],
    }


def _build_internal_carrier_text_diagnostics(suite_payload: dict[str, Any]) -> dict[str, Any]:
    mode_results: list[dict[str, Any]] = []
    for mode_payload in suite_payload.get("mode_reports", []):
        text_report = mode_payload.get("external_report", {})
        structured_report = mode_payload.get("statebus_report", {})
        text_summary = text_report.get("telemetry_summary", {})
        structured_summary = structured_report.get("telemetry_summary", {})
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "verdict": "same_mainline_carrier_only",
                "text_handoff_mode": text_report.get("metadata", {}).get("handoff_mode", ""),
                "structured_handoff_mode": structured_report.get("metadata", {}).get("handoff_mode", ""),
                "suite_metrics": {
                    "text_prompt_visible_total_bytes": float(text_summary.get("prompt_visible_total_bytes", 0.0)),
                    "structured_prompt_visible_total_bytes": float(
                        structured_summary.get("prompt_visible_total_bytes", 0.0)
                    ),
                    "text_non_external_prompt_visible_bytes": float(
                        text_summary.get("non_external_prompt_visible_bytes", 0.0)
                    ),
                    "structured_non_external_prompt_visible_bytes": float(
                        structured_summary.get("non_external_prompt_visible_bytes", 0.0)
                    ),
                    "text_prompt_scaffolding_bytes_total": float(
                        text_summary.get("prompt_scaffolding_bytes_total", 0.0)
                    ),
                    "structured_prompt_scaffolding_bytes_total": float(
                        structured_summary.get("prompt_scaffolding_bytes_total", 0.0)
                    ),
                },
                "debug_metrics": dict(mode_payload.get("debug_metrics", {})),
            }
        )
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "suite_verdict": "same_mainline_carrier_only",
        "mode_results": mode_results,
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/semantic_provenance_and_hydration_contract.md:274-347",
            "v2/runtime/smoke.py:248-271",
        ],
    }


def _build_internal_carrier_runtime_diagnostics(suite_payload: dict[str, Any]) -> dict[str, Any]:
    mode_results: list[dict[str, Any]] = []
    for mode_payload in suite_payload.get("mode_reports", []):
        text_report = mode_payload.get("external_report", {})
        structured_report = mode_payload.get("statebus_report", {})
        text_summary = text_report.get("telemetry_summary", {})
        structured_summary = structured_report.get("telemetry_summary", {})
        task_ms_delta = float(structured_summary.get("task_ms", 0.0) - text_summary.get("task_ms", 0.0))
        llm_ms_delta = float(structured_summary.get("llm_wall_ms", 0.0) - text_summary.get("llm_wall_ms", 0.0))
        non_llm_delta = task_ms_delta - llm_ms_delta
        mode_results.append(
            {
                "role_path_mode": mode_payload.get("role_path_mode", ""),
                "suite_summary": {
                    "task_ms_delta": task_ms_delta,
                    "llm_ms_delta": llm_ms_delta,
                    "non_llm_ms_delta": non_llm_delta,
                    "text_control_bytes": float(text_summary.get("control_bytes", 0.0)),
                    "structured_control_bytes": float(structured_summary.get("control_bytes", 0.0)),
                    "text_runtime_driver_stage_ms": float(text_summary.get("runtime_driver_stage_ms", 0.0)),
                    "structured_runtime_driver_stage_ms": float(
                        structured_summary.get("runtime_driver_stage_ms", 0.0)
                    ),
                },
                "debug_metrics": dict(mode_payload.get("debug_metrics", {})),
            }
        )
    return {
        "suite_id": suite_payload.get("suite_id", ""),
        "task_family": suite_payload.get("task_family", ""),
        "suite_verdict": "carrier_runtime_delta_profiled" if mode_results else "no_data",
        "mode_results": mode_results,
        "authority_refs": [
            "docs/reference/题目.md",
            "docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md:165-185",
            "docs/planning/telemetry_event_contract.md:22-134",
        ],
    }


def _build_markdown_summary(
    *,
    compare_suite_report_path: Path,
    fairness: dict[str, Any],
    text_lane: dict[str, Any],
    runtime: dict[str, Any],
    experiment_plan: dict[str, Any],
) -> str:
    internal_carrier = fairness.get("suite_verdict") == "internal_carrier_single_variable_valid"
    fairness_rows = []
    for mode in fairness.get("mode_results", []):
        fairness_rows.append(
            f"| {mode['role_path_mode']} | {mode['conclusion']} | {','.join(mode['failed_gates']) or '-'} | {mode['invalid_reason'] or '-'} |"
        )
    runtime_rows = []
    for mode in runtime.get("mode_results", []):
        summary = mode["suite_summary"]
        if internal_carrier:
            runtime_rows.append(
                f"| {mode['role_path_mode']} | {summary['task_ms_delta']:.3f} | {summary['llm_ms_delta']:.3f} | {summary['non_llm_ms_delta']:.3f} | {summary['structured_control_bytes']:.3f} | {summary['text_control_bytes']:.3f} | carrier_runtime_delta_profiled |"
            )
        else:
            runtime_rows.append(
                f"| {mode['role_path_mode']} | {summary['task_ms_delta_total']:.3f} | {summary['llm_ms_delta_total']:.3f} | {summary['non_llm_ms_delta_total']:.3f} | {summary['aggregate_bucket_totals']['observed_bucket_sum_stage_ms_total']:.3f} | {summary['aggregate_bucket_totals']['estimated_unbucketed_non_llm_ms_total']:.3f} | {summary['dominant_gap']} |"
            )
    runtime_detail_lines = []
    for mode in runtime.get("mode_results", []):
        summary = mode["suite_summary"]
        if internal_carrier:
            runtime_detail_lines.extend(
                [
                    f"- `{mode['role_path_mode']}` structured_runtime_driver_stage_ms: `{summary['structured_runtime_driver_stage_ms']:.3f}`",
                    f"- `{mode['role_path_mode']}` text_runtime_driver_stage_ms: `{summary['text_runtime_driver_stage_ms']:.3f}`",
                    f"- `{mode['role_path_mode']}` structured_control_bytes: `{summary['structured_control_bytes']:.3f}`",
                    f"- `{mode['role_path_mode']}` text_control_bytes: `{summary['text_control_bytes']:.3f}`",
                ]
            )
        else:
            buckets = summary["aggregate_bucket_totals"]
            cross_cutting = summary["cross_cutting_observation_totals"]
            runtime_detail_lines.extend(
                [
                    f"- `{mode['role_path_mode']}` driver_bucket_sum_stage_ms_total: `{buckets['driver_bucket_sum_stage_ms_total']:.3f}`",
                    f"- `{mode['role_path_mode']}` estimated_unbucketed_within_driver_stage_ms_total: `{buckets['estimated_unbucketed_within_driver_stage_ms_total']:.3f}`",
                    f"- `{mode['role_path_mode']}` telemetry_emit_stage_ms_total: `{cross_cutting['telemetry_emit_stage_ms_total']:.3f}`",
                    f"- `{mode['role_path_mode']}` telemetry_event_write_count_total: `{cross_cutting['telemetry_event_write_count_total']}`",
                    f"- `{mode['role_path_mode']}` telemetry_fact_write_count_total: `{cross_cutting['telemetry_fact_write_count_total']}`",
                ]
            )
    text_rows = []
    for mode in text_lane.get("mode_results", []):
        metrics = mode["suite_metrics"]
        if internal_carrier:
            text_rows.append(
                f"| {mode['role_path_mode']} | {metrics['text_prompt_visible_total_bytes']:.0f} | {metrics['structured_prompt_visible_total_bytes']:.0f} | {metrics['structured_prompt_scaffolding_bytes_total'] - metrics['text_prompt_scaffolding_bytes_total']:.0f} | {mode['verdict']} |"
            )
        else:
            text_rows.append(
                f"| {mode['role_path_mode']} | {metrics['external_public_broadcast_bytes']:.0f} | {metrics['statebus_raw_evidence_bytes_seen_by_llm']:.0f} | {metrics['prompt_bytes_delta']:.0f} | {mode['verdict']} |"
            )
    experiments = experiment_plan.get("recommended_experiments", [])
    experiment_lines = []
    for item in experiments:
        experiment_lines.append(f"- `{item['experiment_id']}`: {item['goal']}")
        if "command" in item:
            experiment_lines.append(f"  command: `{item['command']}`")
        else:
            for command in item.get("commands", []):
                experiment_lines.append(f"  command: `{command}`")
    return "\n".join(
        [
            "# Compare Diagnostics",
            "",
            f"- compare_suite_report: `{compare_suite_report_path}`",
            f"- fairness_suite_verdict: `{fairness['suite_verdict']}`",
            f"- text_lane_suite_verdict: `{text_lane['suite_verdict']}`",
            f"- runtime_suite_verdict: `{runtime['suite_verdict']}`",
            "",
            "## Fairness",
            "",
            "| Mode | Conclusion | Failed Gates | Invalid Reason |",
            "| --- | --- | --- | --- |",
            *fairness_rows,
            "",
            "## Text Lane",
            "",
            (
                "| Mode | text_prompt_visible_total_bytes | structured_prompt_visible_total_bytes | prompt_scaffolding_delta | Verdict |"
                if internal_carrier
                else "| Mode | external_public_broadcast_bytes | statebus_raw_evidence_bytes_seen_by_llm | prompt_bytes_delta | Verdict |"
            ),
            "| --- | ---: | ---: | ---: | --- |",
            *text_rows,
            "",
            "## Runtime",
            "",
            (
                "| Mode | task_ms_delta | llm_ms_delta | non_llm_ms_delta | structured_control_bytes | text_control_bytes | Dominant Gap |"
                if internal_carrier
                else "| Mode | task_ms_delta_total | llm_ms_delta_total | non_llm_ms_delta_total | observed_bucket_sum_stage_ms_total | estimated_unbucketed_non_llm_ms_total | Dominant Gap |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            *runtime_rows,
            "",
            *runtime_detail_lines,
            "",
            "## Recommended Experiments",
            "",
            *experiment_lines,
            "",
        ]
    )


def _copy_source_reports(bundle_dir: Path, suite_payload: dict[str, Any]) -> None:
    _write_json(bundle_dir / "compare_suite_report.json", suite_payload)
    for mode_payload in suite_payload.get("mode_reports", []):
        role_path_mode = str(mode_payload.get("role_path_mode", "unknown"))
        _write_json(bundle_dir / f"mode-{role_path_mode}-report.json", mode_payload)
        _write_json(bundle_dir / f"mode-{role_path_mode}-statebus-family-report.json", mode_payload["statebus_report"])
        _write_json(bundle_dir / f"mode-{role_path_mode}-external-family-report.json", mode_payload["external_report"])


def build_compare_diagnostics_bundle(
    *,
    compare_suite_report_path: Path,
    output_root: Path,
    family_dir: Path,
) -> Path:
    suite_payload = _read_json(compare_suite_report_path)
    bundle_dir = _bundle_dir(output_root, suite_payload.get("suite_id", "compare-diagnostics"))
    bundle_dir.mkdir(parents=True, exist_ok=True)

    compare_kind = "carrier" if _is_internal_carrier_compare(suite_payload) else "external"
    if compare_kind == "carrier":
        fairness = _build_internal_carrier_fairness_diagnostics(suite_payload)
        text_lane = _build_internal_carrier_text_diagnostics(suite_payload)
        runtime = _build_internal_carrier_runtime_diagnostics(suite_payload)
    else:
        fairness = _build_fairness_diagnostics(suite_payload)
        text_lane = _build_text_lane_diagnostics(suite_payload, family_dir=family_dir)
        runtime = _build_runtime_diagnostics(suite_payload)
    experiment_plan = _build_experiment_plan(
        bundle_dir,
        output_root=output_root,
        family_dir=family_dir,
        compare_kind=compare_kind,
    )
    summary = {
        "compare_suite_report_path": str(compare_suite_report_path),
        "bundle_dir": str(bundle_dir),
        "fairness": fairness,
        "text_lane": text_lane,
        "runtime": runtime,
        "experiment_plan": experiment_plan,
    }

    _copy_source_reports(bundle_dir, suite_payload)
    _write_json(bundle_dir / "fairness_diagnostics.json", fairness)
    _write_json(bundle_dir / "text_lane_diagnostics.json", text_lane)
    _write_json(bundle_dir / "runtime_bottleneck_diagnostics.json", runtime)
    _write_json(bundle_dir / "experiment_plan.json", experiment_plan)
    _write_json(bundle_dir / "summary.json", summary)

    case_rows: list[dict[str, Any]] = []
    if compare_kind != "carrier":
        for mode in runtime.get("mode_results", []):
            for case_row in mode.get("case_rows", []):
                case_rows.append(
                    {
                        "role_path_mode": mode["role_path_mode"],
                        "task_id": case_row["task_id"],
                        "statebus_task_ms": case_row["statebus_task_ms"],
                        "statebus_llm_ms": case_row["statebus_llm_ms"],
                        "statebus_non_llm_ms": case_row["statebus_non_llm_ms"],
                        "external_task_ms": case_row["external_task_ms"],
                        "external_llm_ms": case_row["external_llm_ms"],
                        "external_non_llm_ms": case_row["external_non_llm_ms"],
                        "task_ms_delta": case_row["task_ms_delta"],
                        "llm_ms_delta": case_row["llm_ms_delta"],
                        "non_llm_ms_delta": case_row["non_llm_ms_delta"],
                        "statebus_workspace_files": case_row["statebus_workspace_files"],
                        "statebus_telemetry_event_count": case_row["statebus_telemetry_event_count"],
                        "artifact_count": case_row["artifact_count"],
                        "validator_report_count": case_row["validator_report_count"],
                        "memory_commit_count": case_row["memory_commit_count"],
                        "replay_ledger_entry_count": case_row["replay_ledger_entry_count"],
                        "retrieval_log_count": case_row["retrieval_log_count"],
                        "codeact_plan_stage_count": case_row["codeact_plan_stage_count"],
                        "codeact_plan_action_count": case_row["codeact_plan_action_count"],
                        "codeact_execution_stage_ms": case_row["codeact_execution_stage_ms"],
                        "runtime_driver_stage_ms": case_row["runtime_driver_stage_ms"],
                        "runtime_non_executor_stage_ms": case_row["runtime_non_executor_stage_ms"],
                        "runtime_data_plane_event_stage_ms": case_row["runtime_data_plane_event_stage_ms"],
                        "control_plane_exchange_stage_ms": case_row["control_plane_exchange_stage_ms"],
                        "executor_state_machine_stage_ms": case_row["executor_state_machine_stage_ms"],
                        "runtime_commit_finalize_stage_ms": case_row["runtime_commit_finalize_stage_ms"],
                        "runtime_post_executor_stage_ms": case_row["runtime_post_executor_stage_ms"],
                        "runtime_replay_ledger_stage_ms": case_row["runtime_replay_ledger_stage_ms"],
                        "persist_and_reload_stage_ms": case_row["persist_and_reload_stage_ms"],
                        "observed_bucket_sum_stage_ms": case_row["observed_bucket_sum_stage_ms"],
                        "estimated_unbucketed_non_llm_ms": case_row["estimated_unbucketed_non_llm_ms"],
                        "estimated_unbucketed_within_driver_stage_ms": case_row[
                            "estimated_unbucketed_within_driver_stage_ms"
                        ],
                        "telemetry_emit_stage_ms": case_row["telemetry_emit_stage_ms"],
                        "telemetry_event_write_count": case_row["telemetry_event_write_count"],
                        "telemetry_fact_write_count": case_row["telemetry_fact_write_count"],
                    }
                )
    _write_csv(bundle_dir / "case_matrix.csv", case_rows)
    _write_markdown(
        bundle_dir / "summary.md",
        _build_markdown_summary(
            compare_suite_report_path=compare_suite_report_path,
            fairness=fairness,
            text_lane=text_lane,
            runtime=runtime,
            experiment_plan=experiment_plan,
        ),
    )
    return bundle_dir


def _run_compare_suite_from_args(args: argparse.Namespace) -> Path:
    samples = load_fixed_answer_family(args.family_dir)
    if args.compare_kind == "carrier":
        report = run_fixed_answer_internal_carrier_compare_suite(
            samples=samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=args.suite_id,
            role_path_modes=(args.role_path_mode,),
            embedding_mode=args.embedding_mode,
            statebus_mode=args.statebus_mode,
            benchmark_tier="dev",
            claim_level="prototype",
        )
    else:
        report = compare_fixed_answer_with_external(
            samples=samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=args.suite_id,
            role_path_modes=(args.role_path_mode,),
            embedding_mode=args.embedding_mode,
            statebus_mode=args.statebus_mode,
            seed_replay_memory=args.seed_replay_memory,
            benchmark_tier="dev",
            claim_level="prototype",
        )
    return Path(report.report_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or analyze StateBus v2 compare diagnostics and write a mounted diagnostics bundle."
    )
    parser.add_argument(
        "--compare-suite-report",
        type=Path,
        default=None,
        help="existing compare suite report json; when omitted, a fresh dev compare suite is executed first",
    )
    parser.add_argument(
        "--compare-kind",
        choices=("external", "carrier"),
        default="external",
        help="fresh-run compare family: external text comparator or same-mainline internal carrier compare",
    )
    parser.add_argument(
        "--family-dir",
        type=Path,
        default=_default_dev_family_dir(),
        help="fixed-answer family directory for prompt-surface inspection and optional fresh compare runs",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="workspace root used only when a fresh compare suite is executed",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=_default_runtime_root(),
        help="runtime root used only when a fresh compare suite is executed",
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=_default_socket_path(),
        help="control socket path used only when a fresh compare suite is executed",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_default_output_root(),
        help="mounted diagnostics output root",
    )
    parser.add_argument(
        "--suite-id",
        default="statebus-v2-diagnostics-cold-start-compare",
        help="suite id used only when a fresh compare suite is executed",
    )
    parser.add_argument(
        "--role-path-mode",
        default="deterministic",
        choices=("deterministic", "api"),
        help="role path mode for a fresh compare suite",
    )
    parser.add_argument(
        "--embedding-mode",
        default="deterministic",
        choices=("deterministic", "local"),
        help="embedding mode for a fresh compare suite",
    )
    parser.add_argument(
        "--statebus-mode",
        default="cold-start",
        choices=("cold-start", "replay-ready"),
        help="StateBus mode for a fresh compare suite",
    )
    parser.add_argument(
        "--seed-replay-memory",
        action="store_true",
        help="dev-only synthetic replay seed for a fresh compare suite",
    )
    return parser


def main(argv: list[str] | None = None) -> Path:
    parser = _build_parser()
    args = parser.parse_args(argv)
    compare_suite_report_path = args.compare_suite_report
    if compare_suite_report_path is None:
        compare_suite_report_path = _run_compare_suite_from_args(args)
    bundle_dir = build_compare_diagnostics_bundle(
        compare_suite_report_path=compare_suite_report_path,
        output_root=args.output_root,
        family_dir=args.family_dir,
    )
    print(
        stable_json_dumps(
            {
                "bundle_dir": str(bundle_dir),
                "compare_suite_report_path": str(compare_suite_report_path),
                "summary_json": str(bundle_dir / "summary.json"),
                "summary_markdown": str(bundle_dir / "summary.md"),
            }
        )
    )
    return bundle_dir


if __name__ == "__main__":
    main()
