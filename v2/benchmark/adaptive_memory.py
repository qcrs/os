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
    _MEMORY_ACCOUNTING_COUNT_FIELDS,
    _aggregate_memory_consumption_accounting,
    _classify_failure,
    _failure_stage,
    _run_adaptive_case,
)
from v2.benchmark.minimal_runner import MinimalBenchmarkSample
from v2.benchmark.task_registry import load_registered_formal_samples
from v2.contracts import MemoryCounterfactualCallEvidence, ReplayClass
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


def _counterfactual_evidence_from_case(
    case: dict[str, object],
) -> dict[str, MemoryCounterfactualCallEvidence]:
    accounting = case.get("memory_consumption_accounting", {})
    if (
        not isinstance(accounting, dict)
        or int(accounting.get("actual_consumed_count", 0)) != 0
    ):
        return {}
    claim_reports = case.get("claim_validation_reports", {})
    citation_coverage_passed = bool(
        isinstance(claim_reports, dict)
        and claim_reports
        and all(
            isinstance(report, dict) and report.get("ok") is True
            for report in claim_reports.values()
        )
    )
    ledgers = case.get("code_generation_call_ledger_by_step", {})
    if not isinstance(ledgers, dict):
        return {}
    evidence_by_step: dict[str, MemoryCounterfactualCallEvidence] = {}
    for step_id, raw_ledger in sorted(ledgers.items()):
        if not isinstance(raw_ledger, dict):
            continue
        generation_count = int(raw_ledger.get("generation_call_count", 0))
        repair_count = int(raw_ledger.get("repair_call_count", 0))
        pairing_digest = str(raw_ledger.get("pairing_digest", ""))
        if generation_count + repair_count <= 0 or not pairing_digest:
            continue
        evidence = MemoryCounterfactualCallEvidence(
            pair_id=f"memory-pair:{case.get('task_id')}:{step_id}",
            task_id=str(case.get("task_id", "")),
            step_id=str(step_id),
            pairing_digest=pairing_digest,
            no_memory_generation_call_count=generation_count,
            no_memory_repair_call_count=repair_count,
            no_memory_quality_verified=bool(
                raw_ledger.get("quality_verified") and case.get("ok")
            ),
            no_memory_citation_coverage_passed=citation_coverage_passed,
            serialized_execution=True,
            lane_order="no_memory_then_memory",
        )
        evidence_by_step[str(step_id)] = evidence
    return evidence_by_step


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
    efficiency = summary.get("memory_efficiency_claim", {})
    lines = [
        "# Adaptive Memory Summary",
        "",
        f"- Overall: {'PASS' if summary['ok'] else 'FAIL'}",
        f"- Quality: {summary['quality_pass_count']}/{summary['case_count']}",
        f"- Queries: {funnel['query_count']}",
        f"- Candidates: {funnel['candidate_count']}",
        f"- Compatible matches: {funnel['compatible_match_count']}",
        f"- Recorded consumption rows: {funnel['recorded_consumption_count']}",
        f"- Receipt-backed actual consumption: {funnel['actual_consumed_count']}",
        f"- Behavioral effects: {funnel['behavioral_effect_count']}",
        f"- Rejected incompatible: {funnel['rejected_incompatible_count']}",
        f"- Skipped LLM calls: {funnel['skipped_llm_call_count']}",
        f"- Paired classification: {efficiency.get('classification', 'assist_style_recipe_reuse')}",
        f"- Efficiency claim eligible: {efficiency.get('eligible', False)}",
        "",
        "Only rendered/executed receipt rows count as actual consumption. LLM skips additionally require a matching serialized no-memory call ledger. The runtime-signature fixture remained visible in the raw candidate pool but was excluded from role inputs and consumption.",
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
    counterfactual_root = run_root / "counterfactual_no_memory"
    counterfactual_root.mkdir()
    memory_root = run_root / "family_memory"
    failures: list[dict[str, object]] = []
    case_summaries: list[dict[str, object]] = []
    counterfactual_summaries: list[dict[str, object]] = []
    sequence_index_by_task_id: dict[str, int] = {}
    counterfactual_sequence_index_by_task_id: dict[str, int] = {}
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
        counterfactual_evidence: dict[
            str, MemoryCounterfactualCallEvidence
        ] = {}
        try:
            counterfactual = _run_adaptive_case(
                case,
                case_root=counterfactual_root / f"{index:02d}-{case.task_id}",
                embedding_model_path=embedding_model_path,
                embedding_device=embedding_device,
                memory_store_root=memory_root,
                memory_policy="none",
                memory_commit_replay_class=ReplayClass.ASSIST,
                memory_tags=("adaptive-memory-counterfactual", "financial-report"),
                require_executor_model_role=True,
            )
            counterfactual_summaries.append(counterfactual)
            counterfactual_sequence_index_by_task_id[case.task_id] = index
            counterfactual_evidence = _counterfactual_evidence_from_case(
                counterfactual
            )
        except Exception as exc:
            stage = _failure_stage(str(exc))
            category = _classify_failure(str(exc), stage=stage)
            failures.append(LaneFailure(
                lane=f"adaptive-memory-counterfactual:{case.task_id}",
                error_type=type(exc).__name__,
                error=str(exc),
                category=category,
                stage=stage,
                task_id=case.task_id,
                error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
                system_gate_failed=category in _SYSTEM_FAILURE_CLASSES,
            ).canonical_payload())
            traceback.print_exc()
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
                memory_counterfactual_evidence_by_step=counterfactual_evidence,
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
    telemetry_memory_funnel = {
        output_key: int(sum(
            float(case.get("telemetry", {}).get(metric_key, 0.0))
            for case in case_summaries
        ))
        for output_key, metric_key in telemetry_keys.items()
    }
    memory_funnel = dict(telemetry_memory_funnel)
    memory_accounting = _aggregate_memory_consumption_accounting(case_summaries)
    memory_funnel.update({
        field: int(memory_accounting.get(field, 0) or 0)
        for field in _MEMORY_ACCOUNTING_COUNT_FIELDS
    })
    # Canonical reuse and skip headline counters come from receipt-backed
    # accounting.  Keep the raw telemetry projection separately for audit.
    memory_funnel["consumed_memory_count"] = memory_funnel["actual_consumed_count"]
    memory_funnel["skipped_step_count"] = memory_funnel[
        "skipped_generation_step_count"
    ]
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
    counterfactual_by_task = {
        str(case.get("task_id", "")): case
        for case in counterfactual_summaries
    }
    paired_case_summaries = []
    for memory_case in case_summaries:
        task_id = str(memory_case.get("task_id", ""))
        no_memory_case = counterfactual_by_task.get(task_id)
        if no_memory_case is None:
            continue
        no_memory_telemetry = no_memory_case.get("telemetry", {})
        memory_telemetry = memory_case.get("telemetry", {})
        no_memory_telemetry = (
            no_memory_telemetry if isinstance(no_memory_telemetry, dict) else {}
        )
        memory_telemetry = (
            memory_telemetry if isinstance(memory_telemetry, dict) else {}
        )
        paired_case_summaries.append({
            "task_id": task_id,
            "lane_order": "no_memory_then_memory",
            "pairing_digest_match": bool(
                set(no_memory_case.get("code_generation_pairing_digests", {}).values())
                & set(memory_case.get("code_generation_pairing_digests", {}).values())
            ),
            "no_memory_ok": bool(no_memory_case.get("ok")),
            "memory_ok": bool(memory_case.get("ok")),
            "no_memory_generation_call_count": int(
                no_memory_telemetry.get("llm_codeact_generation_count", 0)
            ),
            "memory_generation_call_count": int(
                memory_telemetry.get("llm_codeact_generation_count", 0)
            ),
            "no_memory_repair_call_count": int(
                no_memory_telemetry.get("llm_codeact_repair_count", 0)
            ),
            "memory_repair_call_count": int(
                memory_telemetry.get("llm_codeact_repair_count", 0)
            ),
            "verified_skipped_llm_call_count": int(
                memory_case.get("memory_consumption_accounting", {}).get(
                    "skipped_llm_call_count", 0
                )
            ),
            "no_memory_total_tokens": int(
                no_memory_case.get("usage", {}).get("total_tokens", 0)
            ),
            "memory_total_tokens": int(
                memory_case.get("usage", {}).get("total_tokens", 0)
            ),
            "no_memory_elapsed_ms": float(no_memory_case.get("elapsed_ms", 0.0)),
            "memory_elapsed_ms": float(memory_case.get("elapsed_ms", 0.0)),
        })
    efficiency_claim_eligible = bool(
        len(paired_case_summaries) == len(case_summaries) == 6
        and all(
            pair["no_memory_ok"]
            and pair["memory_ok"]
            and pair["pairing_digest_match"]
            for pair in paired_case_summaries
        )
        and sum(
            int(pair["verified_skipped_llm_call_count"])
            for pair in paired_case_summaries
        ) > 0
    )
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
        "memory_accounting_projection_consistent": bool(
            memory_accounting.get("projection_consistent", False)
        ),
        "paired_no_memory_quality_6_of_6": bool(
            len(counterfactual_summaries) == 6
            and all(case.get("ok") for case in counterfactual_summaries)
        ),
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
        "memory_telemetry_projection": telemetry_memory_funnel,
        "memory_consumption_accounting": memory_accounting,
        "paired_case_summaries": paired_case_summaries,
        "memory_efficiency_claim": {
            "eligible": efficiency_claim_eligible,
            "classification": (
                "verified_llm_call_avoidance"
                if efficiency_claim_eligible
                else "assist_style_recipe_reuse"
            ),
            "verified_skipped_llm_call_count": sum(
                int(pair["verified_skipped_llm_call_count"])
                for pair in paired_case_summaries
            ),
            "claim_boundary": (
                "A non-zero skip claim requires matched serialized no-memory call ledgers, equal quality/citation gates, and a successful no-repair replay."
            ),
        },
        "incompatible_fixture": fixture_audit,
        "negative_case_gates": negative_gates,
        "case_summaries": [
            {
                "task_id": case.get("task_id"),
                "ok": case.get("ok"),
                "selected_capability_ids": case.get("selected_capability_ids", []),
                "memory_commit_decision": case.get("memory_commit_decision", {}),
                "memory_consumption_count": len(case.get("memory_consumption_records", [])),
                "memory_consumption_accounting": case.get(
                    "memory_consumption_accounting", {}
                ),
                "summary_path": str(
                    case_root
                    / f"{sequence_index_by_task_id[str(case.get('task_id'))]:02d}-{case.get('task_id')}"
                    / "summary.json"
                ),
            }
            for case in case_summaries
        ],
        "counterfactual_case_summaries": [
            {
                "task_id": case.get("task_id"),
                "ok": case.get("ok"),
                "code_generation_pairing_digests": case.get(
                    "code_generation_pairing_digests", {}
                ),
                "code_generation_call_ledger_by_step": case.get(
                    "code_generation_call_ledger_by_step", {}
                ),
                "summary_path": str(
                    counterfactual_root
                    / f"{counterfactual_sequence_index_by_task_id[str(case.get('task_id'))]:02d}-{case.get('task_id')}"
                    / "summary.json"
                ),
            }
            for case in counterfactual_summaries
        ],
        "gates": gates,
        "failures": failures,
        "ok": all(gates.values()),
    }
    (run_root / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    _write_markdown(summary, run_root / "summary.md")
    return summary
