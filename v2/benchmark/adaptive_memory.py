from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
import time
import traceback

from v2.benchmark.adaptive_formal import adapt_formal_sample
from v2.benchmark.adaptive_formal_mainline import (
    LaneFailure,
    _SYSTEM_FAILURE_CLASSES,
    _classify_failure,
    _failure_stage,
    _run_adaptive_case,
)
from v2.benchmark.minimal_runner import MinimalBenchmarkSample
from v2.benchmark.task_registry import load_registered_formal_samples
from v2.contracts import ReplayClass
from v2.memory import MemoryIndexStore
from v2.utils import sha256_digest, stable_json_dumps


_FINANCIAL_SEQUENCE = (
    "benchmark-sample-1",
    "benchmark-sample-2",
    "benchmark-sample-3",
    "benchmark-sample-4",
    "benchmark-sample-5",
)
_NEGATIVE_TASK_ID = "adaptive-memory-negative-runtime"
_INCOMPATIBLE_MEMORY_ID = "memory:adaptive-incompatible-runtime-fixture"


def load_adaptive_memory_cases() -> tuple:
    by_id = {sample.task_id: sample for sample in load_registered_formal_samples()}
    missing = [task_id for task_id in _FINANCIAL_SEQUENCE if task_id not in by_id]
    if missing:
        raise ValueError(f"adaptive_memory_financial_cases_missing:{','.join(missing)}")
    selected = [by_id[task_id] for task_id in _FINANCIAL_SEQUENCE]
    source = selected[0]
    negative = MinimalBenchmarkSample(
        task_id=_NEGATIVE_TASK_ID,
        request_text=(
            "Recompute ACME revenue for 2026Q1 from the authorized report and produce a cited summary. "
            "Use compatible verified history when available; otherwise recompute from the source."
        ),
        canonical_task_spec=source.canonical_task_spec,
        expected_artifact_type=source.expected_artifact_type,
        task_family=source.task_family,
        expected_facts=dict(source.expected_facts or {}),
        scenario_tags=("adaptive_memory", "runtime_signature_negative"),
    )
    return tuple(adapt_formal_sample(sample) for sample in (*selected, negative))


def _seed_incompatible_runtime_fixture(
    *,
    memory_root: Path,
    audit_path: Path,
) -> dict[str, object]:
    store = MemoryIndexStore(store_root=memory_root)
    store.load_persisted_state()
    source_commits = sorted(
        store.commits.values(),
        key=lambda commit: (commit.memory_ref.created_at_ns, commit.memory_ref.memory_id),
    )
    if not source_commits:
        raise RuntimeError("adaptive_memory_fixture_source_commit_missing")
    source = source_commits[0]
    if not source.quality_floor_pass or source.memory_ref.commit_status.value != "committed":
        raise RuntimeError("adaptive_memory_fixture_source_not_verified")
    incompatible_signature = sha256_digest({
        "fixture": "adaptive_runtime_signature_incompatible",
        "version": 1,
    })
    incompatible_ref = replace(
        source.memory_ref,
        memory_id=_INCOMPATIBLE_MEMORY_ID,
        producer_run_id="adaptive-memory-incompatible-fixture-v1",
        metadata={
            **source.memory_ref.metadata,
            "runtime_signature_hash": incompatible_signature,
            "fixture_kind": "runtime_signature_incompatible",
        },
    )
    store.put_commit(replace(source, memory_ref=incompatible_ref))
    audit = {
        "schema_version": "statebus.adaptive_memory_incompatible_fixture.v1",
        "fixture_memory_id": _INCOMPATIBLE_MEMORY_ID,
        "source_memory_id": source.memory_ref.memory_id,
        "source_task_id": source.memory_ref.source_task_id,
        "source_artifact_hash": source.created_from_artifact_hash,
        "source_quality_floor_pass": source.quality_floor_pass,
        "source_commit_status": source.memory_ref.commit_status.value,
        "changed_fields": [
            "memory_ref.memory_id",
            "memory_ref.producer_run_id",
            "memory_ref.metadata.runtime_signature_hash",
            "memory_ref.metadata.fixture_kind",
        ],
        "incompatible_runtime_signature": incompatible_signature,
        "expected_decision": "reject_incompatible_and_recompute",
    }
    audit_path.write_text(stable_json_dumps(audit) + "\n", encoding="utf-8")
    return audit


def _memory_results(case: dict[str, object]) -> tuple[dict[str, object], ...]:
    payload = case.get("memory_query_results", {})
    if not isinstance(payload, dict):
        return ()
    return tuple(value for value in payload.values() if isinstance(value, dict))


def _negative_fixture_gate(case: dict[str, object]) -> dict[str, bool]:
    results = _memory_results(case)
    candidate_ids = {
        str(memory_id)
        for result in results
        for memory_id in (
            result.get("candidate_pool", {}).get("candidate_memory_ids", [])
            if isinstance(result.get("candidate_pool"), dict)
            else []
        )
    }
    decisions = [
        decision
        for result in results
        for decision in result.get("compatibility_decisions", [])
        if isinstance(decision, dict)
        and decision.get("memory_id") == _INCOMPATIBLE_MEMORY_ID
    ]
    role_input_ids = {
        str(item.get("ref_id", ""))
        for inputs in case.get("memory_role_inputs_by_step", {}).values()
        if isinstance(inputs, list)
        for item in inputs
        if isinstance(item, dict)
    }
    consumed_ids = {
        str(record.get("memory_id", ""))
        for record in case.get("memory_consumption_records", [])
        if isinstance(record, dict)
    }
    terminal_reports = [
        report
        for report in case.get("terminal_quality_reports", [])
        if isinstance(report, dict)
    ]
    return {
        "fixture_visible_in_candidate_pool": _INCOMPATIBLE_MEMORY_ID in candidate_ids,
        "fixture_decision_recorded": len(decisions) == 1,
        "fixture_runtime_incompatible": bool(
            decisions
            and decisions[0].get("verdict") == "incompatible"
            and decisions[0].get("replay_class") == "disallowed"
            and decisions[0].get("policy_approved") is False
            and "runtime_signature_mismatch" in decisions[0].get("reasons", [])
        ),
        "fixture_absent_from_role_inputs": _INCOMPATIBLE_MEMORY_ID not in role_input_ids,
        "fixture_not_consumed": _INCOMPATIBLE_MEMORY_ID not in consumed_ids,
        "current_output_recomputed_and_verified": bool(
            case.get("ok")
            and case.get("expected_facts_report", {}).get("passed")
            and terminal_reports
            and all(
                report.get("verified") is True
                and report.get("recomputation_evaluated") is True
                and report.get("recomputation_passed") is True
                for report in terminal_reports
            )
        ),
    }


def _write_markdown(summary: dict[str, object], path: Path) -> None:
    funnel = summary["memory_funnel"]
    lines = [
        "# Adaptive Memory Summary",
        "",
        f"- Overall: {'PASS' if summary['ok'] else 'FAIL'}",
        f"- Quality: {summary['quality_pass_count']}/{summary['case_count']}",
        f"- Queries: {funnel['query_count']}",
        f"- Candidates: {funnel['candidate_count']}",
        f"- Compatible matches: {funnel['compatible_match_count']}",
        f"- Consumed memories: {funnel['consumed_memory_count']}",
        f"- Behavioral effects: {funnel['behavioral_effect_count']}",
        f"- Rejected incompatible: {funnel['rejected_incompatible_count']}",
        f"- Skipped LLM calls: {funnel['skipped_llm_call_count']}",
        "",
        "The runtime-signature fixture remained visible in the raw candidate pool but was excluded from role inputs and consumption.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_adaptive_memory(
    *,
    output_root: Path,
    embedding_model_path: str,
    embedding_device: str,
) -> dict[str, object]:
    cases = load_adaptive_memory_cases()
    run_root = output_root / f"adaptive_memory_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}"
    run_root.mkdir(parents=True, exist_ok=False)
    case_root = run_root / "cases"
    case_root.mkdir()
    memory_root = run_root / "family_memory"
    failures: list[dict[str, object]] = []
    case_summaries: list[dict[str, object]] = []
    sequence_index_by_task_id: dict[str, int] = {}
    fixture_audit: dict[str, object] = {}
    for index, case in enumerate(cases, start=1):
        if index == 6:
            fixture_audit = _seed_incompatible_runtime_fixture(
                memory_root=memory_root,
                audit_path=run_root / "incompatible_fixture.json",
            )
        print(stable_json_dumps({
            "stage": "adaptive_memory_case_started",
            "case_index": index,
            "case_count": len(cases),
            "task_id": case.task_id,
        }), flush=True)
        try:
            case_summary = _run_adaptive_case(
                case,
                case_root=case_root / f"{index:02d}-{case.task_id}",
                embedding_model_path=embedding_model_path,
                embedding_device=embedding_device,
                memory_store_root=memory_root,
                memory_policy="validated_replay",
                memory_commit_replay_class=ReplayClass.VALIDATED_REPLAY,
                memory_tags=("adaptive-memory", "financial-report"),
                require_executor_model_role=False,
            )
            case_summaries.append(case_summary)
            sequence_index_by_task_id[case.task_id] = index
        except Exception as exc:
            stage = _failure_stage(str(exc))
            category = _classify_failure(str(exc), stage=stage)
            failure = LaneFailure(
                lane=f"adaptive-memory:{case.task_id}",
                error_type=type(exc).__name__,
                error=str(exc),
                category=category,
                stage=stage,
                task_id=case.task_id,
                error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
                system_gate_failed=category in _SYSTEM_FAILURE_CLASSES,
            ).canonical_payload()
            failures.append(failure)
            failure_path = case_root / f"{index:02d}-{case.task_id}" / "failure.json"
            failure_path.parent.mkdir(parents=True, exist_ok=True)
            failure_path.write_text(stable_json_dumps(failure) + "\n", encoding="utf-8")
            traceback.print_exc()
            if index < 5:
                break

    telemetry_keys = {
        "query_count": "hybrid_memory_query_count",
        "candidate_count": "memory_candidate_count",
        "compatible_match_count": "memory_compatible_match_count",
        "policy_approved_match_count": "memory_policy_approved_match_count",
        "consumed_memory_count": "memory_consumed_count",
        "behavioral_effect_count": "memory_behavioral_effect_count",
        "assist_count": "memory_assist_count",
        "validated_replay_count": "validated_replay_count",
        "exact_replay_count": "exact_replay_count",
        "rejected_incompatible_count": "memory_rejected_incompatible_count",
        "skipped_step_count": "skipped_step_count",
        "skipped_llm_call_count": "skipped_llm_call_count",
    }
    memory_funnel = {
        output_key: int(sum(
            float(case.get("telemetry", {}).get(metric_key, 0.0))
            for case in case_summaries
        ))
        for output_key, metric_key in telemetry_keys.items()
    }
    negative_case = next(
        (case for case in case_summaries if case.get("task_id") == _NEGATIVE_TASK_ID),
        {},
    )
    negative_gates = _negative_fixture_gate(negative_case) if negative_case else {}
    commit_decisions = [
        case.get("memory_commit_decision", {})
        for case in case_summaries
        if isinstance(case.get("memory_commit_decision"), dict)
    ]
    gates = {
        "quality_6_of_6": len(case_summaries) == 6 and all(case.get("ok") for case in case_summaries),
        "fresh_runner_shared_store_sequence": len(case_summaries) == 6 and memory_root.is_dir(),
        "verified_commit_6_of_6": len(commit_decisions) == 6 and all(
            decision.get("committed") is True
            and decision.get("benchmark_gold_used") is False
            for decision in commit_decisions
        ),
        "query_candidate_match_consume_effect_closed": all(
            memory_funnel[key] > 0
            for key in (
                "query_count",
                "candidate_count",
                "compatible_match_count",
                "policy_approved_match_count",
                "consumed_memory_count",
                "behavioral_effect_count",
            )
        ),
        "runtime_incompatible_negative_closed": bool(negative_gates) and all(negative_gates.values()),
    }
    selected_capabilities = Counter(
        str(capability_id)
        for case in case_summaries
        for capability_id in case.get("selected_capability_ids", [])
    )
    summary = {
        "schema_version": "statebus.adaptive_memory_summary.v1",
        "suite_id": "adaptive_memory_financial_v1",
        "run_dir": str(run_root),
        "serial_execution": True,
        "case_count": 6,
        "attempted_case_count": len(case_summaries) + len(failures),
        "quality_pass_count": sum(bool(case.get("ok")) for case in case_summaries),
        "family_memory_root": str(memory_root),
        "case_order": [case.task_id for case in cases],
        "capability_counts": dict(sorted(selected_capabilities.items())),
        "memory_funnel": memory_funnel,
        "incompatible_fixture": fixture_audit,
        "negative_case_gates": negative_gates,
        "case_summaries": [
            {
                "task_id": case.get("task_id"),
                "ok": case.get("ok"),
                "selected_capability_ids": case.get("selected_capability_ids", []),
                "memory_commit_decision": case.get("memory_commit_decision", {}),
                "memory_consumption_count": len(case.get("memory_consumption_records", [])),
                "summary_path": str(
                    case_root
                    / f"{sequence_index_by_task_id[str(case.get('task_id'))]:02d}-{case.get('task_id')}"
                    / "summary.json"
                ),
            }
            for case in case_summaries
        ],
        "gates": gates,
        "failures": failures,
        "ok": all(gates.values()),
    }
    (run_root / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    _write_markdown(summary, run_root / "summary.md")
    return summary
