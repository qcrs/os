#!/usr/bin/env python3
"""Collect compact, citation-friendly results from the final Contest39 runs.

The collector reads existing run artifacts only.  It does not execute the
mainchain, copy raw logs, or invent unobserved transport metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable


JSON = dict[str, Any]


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[JSON]:
    if not path.is_file():
        return []
    rows: list[JSON] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def numeric_sum(rows: Iterable[JSON], key: str) -> int | float:
    total: int | float = 0
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += value
    return total


def compact_plan(plan: JSON) -> JSON:
    steps = []
    for step in plan.get("steps", []) if isinstance(plan, dict) else []:
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "step_id": step.get("step_id"),
                "role": step.get("role"),
                "capability_id": step.get("capability_id"),
                "depends_on": step.get("depends_on", []),
                "input_ref_ids": step.get("input_ref_ids", []),
                "input_ref_kinds": step.get("input_ref_kinds", []),
                "output_contract_version": step.get("output_contract_version"),
            }
        )
    return {
        "proposal_id": plan.get("proposal_id"),
        "steps": steps,
        "final_output_contract_version": plan.get("final_output_contract_version"),
    }


def compact_provider(rows: list[JSON], metrics: JSON) -> JSON:
    requests = []
    for row in rows:
        nested = row.get("provider_events") if isinstance(row.get("provider_events"), list) else []
        candidates = nested if nested else ([row] if row.get("event") == "provider_request" else [])
        for request in candidates:
            if not isinstance(request, dict) or request.get("event") != "provider_request":
                continue
            requests.append(
                {
                    "role": request.get("role"),
                    "model": request.get("model"),
                    "status": request.get("status"),
                    "attempt": request.get("attempt"),
                    "retry_kind": request.get("retry_kind"),
                    "finish_reason": request.get("finish_reason"),
                    "prompt_tokens": request.get("response_prompt_tokens"),
                    "completion_tokens": request.get("response_completion_tokens"),
                    "total_tokens": request.get("response_total_tokens"),
                }
            )
    return {
        "request_count": metrics.get("provider_request_count"),
        "observed_request_count": metrics.get("provider_observed_request_count"),
        "prompt_tokens": metrics.get("provider_prompt_tokens"),
        "completion_tokens": metrics.get("provider_completion_tokens"),
        "total_tokens": metrics.get("provider_total_tokens"),
        "planner_request_count": metrics.get("planner_request_count"),
        "retriever_request_count": metrics.get("retriever_request_count"),
        "executor_request_count": metrics.get("executor_request_count"),
        "summarizer_request_count": metrics.get("summarizer_request_count"),
        "executor_generation_count": metrics.get("executor_generation_count"),
        "executor_repair_count": metrics.get("executor_repair_count"),
        "requests": requests,
    }


def compact_communication(rows: list[JSON]) -> JSON:
    sends = [row for row in rows if row.get("event") == "send"]
    event_counts = Counter(str(row.get("event")) for row in rows if row.get("event"))
    carrier_counts = Counter(str(row.get("carrier")) for row in sends if row.get("carrier"))
    edge_map: dict[tuple[Any, ...], JSON] = {}
    for row in sends:
        key = (row.get("sender"), row.get("receiver"), row.get("step"), row.get("carrier"))
        edge = edge_map.setdefault(
            key,
            {
                "sender": row.get("sender"),
                "receiver": row.get("receiver"),
                "step": row.get("step"),
                "carrier": row.get("carrier"),
                "message_count": 0,
                "text_chars": 0,
                "text_tokens": 0,
                "text_bytes": 0,
            },
        )
        edge["message_count"] += 1
        for source, target in (
            ("handoff_text_chars", "text_chars"),
            ("handoff_text_tokens", "text_tokens"),
            ("handoff_text_bytes", "text_bytes"),
        ):
            value = row.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                edge[target] += value
    return {
        "message_count": len(sends),
        "event_counts": dict(sorted(event_counts.items())),
        "carrier_counts": dict(sorted(carrier_counts.items())),
        "text_chars": numeric_sum(sends, "handoff_text_chars"),
        "text_tokens": numeric_sum(sends, "handoff_text_tokens"),
        "text_bytes": numeric_sum(sends, "handoff_text_bytes"),
        "edges": list(edge_map.values()),
    }


def compact_state(rows: list[JSON], variant: str) -> JSON:
    if variant == "P-TEXT" or not rows:
        return {"status": "not_applicable", "reason": "p-text_state_disabled"}
    events = Counter(str(row.get("event")) for row in rows if row.get("event"))
    consumes = [row for row in rows if row.get("event") == "consume"]
    releases = [row for row in rows if row.get("event") == "release"]
    effects = Counter(str(row.get("downstream_effect")) for row in consumes if row.get("downstream_effect"))
    return {
        "status": "observed",
        "event_counts": dict(sorted(events.items())),
        "publish_count": events.get("publish", 0),
        "transfer_count": events.get("transfer", 0),
        "consume_count": events.get("consume", 0),
        "release_count": events.get("release", 0),
        "payload_bytes": numeric_sum(rows, "payload_bytes"),
        "read_bytes": numeric_sum(consumes, "read_bytes"),
        "selected_evidence_bytes": numeric_sum(consumes, "selected_evidence_bytes"),
        "downstream_effect_counts": dict(sorted(effects.items())),
        "physical_reclaimed_count": sum(1 for row in releases if row.get("physical_reclaimed") is True),
        "released_bytes": numeric_sum(releases, "released_bytes"),
    }


def compact_memory(rows: list[JSON], variant: str) -> JSON:
    if variant == "P-TEXT":
        return {"status": "not_applicable", "reason": "p-text_memory_disabled"}
    queries = [row for row in rows if row.get("event") == "query"]
    consumes = [row for row in rows if row.get("event") == "consume"]
    effects = Counter(str(row.get("downstream_effect")) for row in consumes if row.get("downstream_effect"))
    replay_classes = Counter(str(row.get("replay_class")) for row in consumes if row.get("replay_class"))
    compatibility = Counter(str(row.get("compatibility_verdict")) for row in consumes if row.get("compatibility_verdict"))
    cross_agent = sum(
        1
        for row in consumes
        if row.get("actual_consumption")
        and row.get("source_agent")
        and row.get("consumer_agent")
        and row.get("source_agent") != row.get("consumer_agent")
    )
    return {
        "status": "observed",
        "query_count": sum(int(row.get("query_count") or 0) for row in queries),
        "queries_with_candidate": sum(1 for row in queries if (row.get("candidate_count") or 0) > 0),
        "candidate_count": numeric_sum(queries, "candidate_count"),
        "actual_consumption": int(any(row.get("actual_consumption") for row in consumes)),
        "consumption_event_count": numeric_sum(consumes, "actual_consumption"),
        "replay_count": numeric_sum(consumes, "replay_count"),
        "cross_agent_consumption": cross_agent,
        "skipped_executor_generation": numeric_sum(consumes, "skipped_executor_generation"),
        "artifact_read_bytes": numeric_sum(consumes, "artifact_read_bytes"),
        "downstream_effect_counts": dict(sorted(effects.items())),
        "replay_class_counts": dict(sorted(replay_classes.items())),
        "compatibility_counts": dict(sorted(compatibility.items())),
    }


def compact_repair(rows: list[JSON], repair_count: int) -> JSON:
    modes = sorted({str(row.get("normalization_mode")) for row in rows if row.get("normalization_mode")})
    reasons = sorted({str(row.get("normalization_reason")) for row in rows if row.get("normalization_reason")})
    violations = sorted({str(row.get("provider_protocol_violation")) for row in rows if row.get("provider_protocol_violation")})
    return {
        "count": repair_count,
        "normalization_modes": modes,
        "normalization_reasons": reasons,
        "provider_protocol_violations": violations,
    }


def compact_codeact(rows: list[JSON]) -> JSON:
    """Project the optional DSL-to-CodeAct switch without copying raw logs."""
    if not rows:
        return {
            "status": "not_observed",
            "fallback_enabled": None,
            "fallback_attempted": None,
            "dsl_execute_attempts": None,
            "python_attempts": None,
            "completed_python_attempts": None,
        }
    enabled = any(row.get("fallback_enabled") is True for row in rows)
    attempted = any(row.get("fallback_attempted") is True for row in rows)
    return {
        "status": "observed",
        "fallback_enabled": enabled,
        "fallback_attempted": attempted,
        "dsl_execute_attempts": max(
            (int(row.get("dsl_execute_attempts") or 0) for row in rows),
            default=0,
        ),
        "python_attempts": sum(int(row.get("python_attempts") or 0) for row in rows),
        "completed_python_attempts": sum(
            1 for row in rows if str(row.get("final_result", "")).lower() == "completed"
        ),
    }


def source_files(slot: Path, run_root: Path, family: str, task_id: str) -> JSON:
    names = [
        "task-row.json",
        "manifest.json",
        "plan.json",
        "handoffs.jsonl",
        "provider.jsonl",
        "state-events.jsonl",
        "memory-events.jsonl",
        "generation-events.jsonl",
        "repair-events.jsonl",
        "scorer.json",
        "runtime-evidence.json",
    ]
    return {
        "run_root": str(run_root),
        "slot": str(Path(family) / "slots" / task_id),
        "files": [str(Path(family) / "slots" / task_id / name) for name in names if (slot / name).is_file()],
    }


def collect_run(run_root: Path, expected_variant: str) -> list[JSON]:
    records: list[JSON] = []
    for family in ("finance", "service_ops"):
        family_root = run_root / family
        ledger = read_json(family_root / "ledger.json", [])
        if not isinstance(ledger, list):
            continue
        for row in ledger:
            if not isinstance(row, dict):
                continue
            task_id = str(row.get("task_id"))
            slot = family_root / "slots" / task_id
            variant = row.get("variant") or expected_variant
            manifest = read_json(slot / "manifest.json", {}) or {}
            plan = read_json(slot / "plan.json", {}) or {}
            metrics = row.get("metrics", {}) or {}
            handoffs = read_jsonl(slot / "handoffs.jsonl")
            provider = read_jsonl(slot / "provider.jsonl")
            state = read_jsonl(slot / "state-events.jsonl")
            memory = read_jsonl(slot / "memory-events.jsonl")
            repair = read_jsonl(slot / "repair-events.jsonl")
            codeact = read_jsonl(slot / "codeact-events.jsonl")
            records.append(
                {
                    "variant": variant,
                    "family": family,
                    "round": row.get("round"),
                    "task_id": task_id,
                    "task_profile": row.get("task_profile"),
                    "status": row.get("status"),
                    "quality": row.get("quality"),
                    "business_quality": row.get("business_quality"),
                    "repair": row.get("repair", 0),
                    "e2e_ms": row.get("e2e_ms"),
                    "failure_codes": row.get("failure_codes", []),
                    "scorer_errors": row.get("scorer_errors", []),
                    "mechanism_gate_passed": row.get("mechanism_gate_passed"),
                    "roles": {
                        "planner": manifest.get("planner"),
                        "retriever": manifest.get("retriever"),
                    },
                    "plan": compact_plan(plan),
                    "provider": compact_provider(provider, metrics),
                    "communication": compact_communication(handoffs),
                    "state": compact_state(state, variant),
                    "memory": compact_memory(memory, variant),
                    "repair_detail": compact_repair(repair, int(row.get("repair") or 0)),
                    "codeact": compact_codeact(codeact),
                    "source": source_files(slot, run_root, family, task_id),
                }
            )
    return sorted(records, key=lambda row: (row["variant"], row["family"], row["round"], row["task_id"]))


def add_totals(target: JSON, records: list[JSON]) -> None:
    target.update(
        {
            "planned_count": len(records),
            "started_count": sum(1 for row in records if row["status"] not in {"blocked", "not_started"}),
            "passed_count": sum(1 for row in records if row["status"] == "success" and row["quality"] is True),
            "business_quality_passed_count": sum(1 for row in records if row["business_quality"] is True),
            "status_counts": dict(sorted(Counter(row["status"] for row in records).items())),
            "quality_pass_rate": (
                sum(1 for row in records if row["quality"] is True) / len(records) if records else None
            ),
            "e2e_ms_total": sum(float(row["e2e_ms"] or 0) for row in records),
            "e2e_ms_mean": (
                sum(float(row["e2e_ms"] or 0) for row in records) / len(records) if records else None
            ),
        }
    )


def aggregate_group(records: list[JSON]) -> JSON:
    summary: JSON = {}
    add_totals(summary, records)
    provider = summary["provider"] = {
        "request_count": sum((row["provider"].get("request_count") or 0) for row in records),
        "prompt_tokens": sum((row["provider"].get("prompt_tokens") or 0) for row in records),
        "completion_tokens": sum((row["provider"].get("completion_tokens") or 0) for row in records),
        "total_tokens": sum((row["provider"].get("total_tokens") or 0) for row in records),
        "planner_request_count": sum((row["provider"].get("planner_request_count") or 0) for row in records),
        "retriever_request_count": sum((row["provider"].get("retriever_request_count") or 0) for row in records),
        "executor_request_count": sum((row["provider"].get("executor_request_count") or 0) for row in records),
        "summarizer_request_count": sum((row["provider"].get("summarizer_request_count") or 0) for row in records),
        "executor_generation_count": sum((row["provider"].get("executor_generation_count") or 0) for row in records),
        "executor_repair_count": sum((row["provider"].get("executor_repair_count") or 0) for row in records),
    }
    communication = summary["communication"] = {
        "message_count": sum(row["communication"].get("message_count", 0) for row in records),
        "text_chars": sum(row["communication"].get("text_chars", 0) for row in records),
        "text_tokens": sum(row["communication"].get("text_tokens", 0) for row in records),
        "text_bytes": sum(row["communication"].get("text_bytes", 0) for row in records),
        "carrier_counts": dict(
            sorted(sum_counters((row["communication"].get("carrier_counts", {}) for row in records)).items())
        ),
    }
    state_records = [row["state"] for row in records if row["state"].get("status") == "observed"]
    if state_records:
        state = summary["state"] = {
            "status": "observed",
            "publish_count": sum(row.get("publish_count", 0) for row in state_records),
            "transfer_count": sum(row.get("transfer_count", 0) for row in state_records),
            "consume_count": sum(row.get("consume_count", 0) for row in state_records),
            "release_count": sum(row.get("release_count", 0) for row in state_records),
            "payload_bytes": sum(row.get("payload_bytes", 0) for row in state_records),
            "read_bytes": sum(row.get("read_bytes", 0) for row in state_records),
            "selected_evidence_bytes": sum(row.get("selected_evidence_bytes", 0) for row in state_records),
            "downstream_effect_counts": dict(
                sorted(sum_counters((row.get("downstream_effect_counts", {}) for row in state_records)).items())
            ),
            "physical_reclaimed_count": sum(row.get("physical_reclaimed_count", 0) for row in state_records),
            "released_bytes": sum(row.get("released_bytes", 0) for row in state_records),
        }
    else:
        summary["state"] = {"status": "not_applicable", "reason": "p-text_state_disabled"}
    memory_records = [row["memory"] for row in records if row["memory"].get("status") == "observed"]
    if memory_records:
        summary["memory"] = {
            "status": "observed",
            "query_count": sum(row.get("query_count", 0) for row in memory_records),
            "queries_with_candidate": sum(row.get("queries_with_candidate", 0) for row in memory_records),
            "candidate_count": sum(row.get("candidate_count", 0) for row in memory_records),
            "actual_consumption": sum(row.get("actual_consumption", 0) for row in memory_records),
            "consumption_event_count": sum(row.get("consumption_event_count", 0) for row in memory_records),
            "replay_count": sum(row.get("replay_count", 0) for row in memory_records),
            "cross_agent_consumption": sum(row.get("cross_agent_consumption", 0) for row in memory_records),
            "skipped_executor_generation": sum(row.get("skipped_executor_generation", 0) for row in memory_records),
            "artifact_read_bytes": sum(row.get("artifact_read_bytes", 0) for row in memory_records),
            "downstream_effect_counts": dict(
                sorted(sum_counters((row.get("downstream_effect_counts", {}) for row in memory_records)).items())
            ),
            "replay_class_counts": dict(
                sorted(sum_counters((row.get("replay_class_counts", {}) for row in memory_records)).items())
            ),
            "compatibility_counts": dict(
                sorted(sum_counters((row.get("compatibility_counts", {}) for row in memory_records)).items())
            ),
        }
    else:
        summary["memory"] = {"status": "not_applicable", "reason": "p-text_memory_disabled"}
    repairs = sum((row["repair_detail"].get("count") or 0) for row in records)
    summary["repair"] = {
        "count": repairs,
        "normalization_modes": sorted(
            {mode for row in records for mode in row["repair_detail"].get("normalization_modes", [])}
        ),
        "normalization_reasons": sorted(
            {reason for row in records for reason in row["repair_detail"].get("normalization_reasons", [])}
        ),
    }
    codeact_records = [row["codeact"] for row in records if row["codeact"].get("status") == "observed"]
    summary["codeact"] = {
        "status": "observed" if codeact_records else "not_observed",
        "fallback_enabled_slots": sum(1 for row in codeact_records if row.get("fallback_enabled")),
        "fallback_attempted_slots": sum(1 for row in codeact_records if row.get("fallback_attempted")),
        "python_attempts": sum(int(row.get("python_attempts") or 0) for row in codeact_records),
        "completed_python_attempts": sum(
            int(row.get("completed_python_attempts") or 0) for row in codeact_records
        ),
    }
    return summary


def sum_counters(counters: Iterable[dict[str, Any]]) -> Counter:
    result: Counter = Counter()
    for counter in counters:
        result.update({key: value for key, value in counter.items() if isinstance(value, (int, float))})
    return result


def comparison(records: list[JSON]) -> JSON:
    groups: dict[tuple[str, str], dict[str, JSON]] = defaultdict(dict)
    for row in records:
        groups[(row["family"], row["task_id"])][row["variant"]] = row
    pairs = []
    for (family, task_id), variants in sorted(groups.items()):
        sb = variants.get("SB-FULL")
        pt = variants.get("P-TEXT")
        if not sb or not pt:
            continue
        sb_tokens = sb["provider"].get("total_tokens")
        pt_tokens = pt["provider"].get("total_tokens")
        pairs.append(
            {
                "family": family,
                "task_id": task_id,
                "quality_match": sb.get("quality") == pt.get("quality"),
                "sb_provider_total_tokens": sb_tokens,
                "ptext_provider_total_tokens": pt_tokens,
                "ptext_minus_sb_provider_tokens": (pt_tokens - sb_tokens) if isinstance(pt_tokens, (int, float)) and isinstance(sb_tokens, (int, float)) else None,
                "sb_provider_requests": sb["provider"].get("request_count"),
                "ptext_provider_requests": pt["provider"].get("request_count"),
                "ptext_minus_sb_provider_requests": (pt["provider"].get("request_count") or 0) - (sb["provider"].get("request_count") or 0),
                "sb_e2e_ms": sb.get("e2e_ms"),
                "ptext_e2e_ms": pt.get("e2e_ms"),
                "ptext_minus_sb_e2e_ms": (pt.get("e2e_ms") or 0) - (sb.get("e2e_ms") or 0),
            }
        )
    return {
        "matched_task_count": len(pairs),
        "quality_matches": sum(1 for pair in pairs if pair["quality_match"]),
        "provider_token_delta_total_ptext_minus_sb": sum(
            pair["ptext_minus_sb_provider_tokens"] or 0 for pair in pairs
        ),
        "provider_request_delta_total_ptext_minus_sb": sum(
            pair["ptext_minus_sb_provider_requests"] or 0 for pair in pairs
        ),
        "pairs": pairs,
    }


CSV_FIELDS = [
    "variant",
    "family",
    "round",
    "task_id",
    "task_profile",
    "status",
    "quality",
    "business_quality",
    "repair",
    "e2e_ms",
    "provider_requests",
    "provider_prompt_tokens",
    "provider_completion_tokens",
    "provider_total_tokens",
    "planner_requests",
    "retriever_requests",
    "executor_requests",
    "summarizer_requests",
    "communication_messages",
    "communication_text_chars",
    "communication_text_tokens",
    "state_status",
    "state_publish_count",
    "state_transfer_count",
    "state_consume_count",
    "state_release_count",
    "state_payload_bytes",
    "state_read_bytes",
    "state_selected_evidence_bytes",
    "memory_status",
    "memory_query_count",
    "memory_queries_with_candidate",
    "memory_candidate_count",
    "memory_actual_consumption",
    "memory_consumption_event_count",
    "memory_replay_count",
    "memory_cross_agent_consumption",
    "memory_skipped_executor_generation",
    "codeact_status",
    "codeact_fallback_enabled",
    "codeact_fallback_attempted",
    "codeact_dsl_execute_attempts",
    "codeact_python_attempts",
    "codeact_completed_python_attempts",
    "repair_reasons",
    "failure_codes",
    "scorer_errors",
    "source_slot",
]


def csv_row(record: JSON) -> dict[str, Any]:
    provider = record["provider"]
    communication = record["communication"]
    state = record["state"]
    memory = record["memory"]
    codeact = record["codeact"]
    return {
        "variant": record["variant"],
        "family": record["family"],
        "round": record["round"],
        "task_id": record["task_id"],
        "task_profile": record["task_profile"],
        "status": record["status"],
        "quality": record["quality"],
        "business_quality": record["business_quality"],
        "repair": record["repair"],
        "e2e_ms": record["e2e_ms"],
        "provider_requests": provider.get("request_count"),
        "provider_prompt_tokens": provider.get("prompt_tokens"),
        "provider_completion_tokens": provider.get("completion_tokens"),
        "provider_total_tokens": provider.get("total_tokens"),
        "planner_requests": provider.get("planner_request_count"),
        "retriever_requests": provider.get("retriever_request_count"),
        "executor_requests": provider.get("executor_request_count"),
        "summarizer_requests": provider.get("summarizer_request_count"),
        "communication_messages": communication.get("message_count"),
        "communication_text_chars": communication.get("text_chars"),
        "communication_text_tokens": communication.get("text_tokens"),
        "state_status": state.get("status"),
        "state_publish_count": state.get("publish_count"),
        "state_transfer_count": state.get("transfer_count"),
        "state_consume_count": state.get("consume_count"),
        "state_release_count": state.get("release_count"),
        "state_payload_bytes": state.get("payload_bytes"),
        "state_read_bytes": state.get("read_bytes"),
        "state_selected_evidence_bytes": state.get("selected_evidence_bytes"),
        "memory_status": memory.get("status"),
        "memory_query_count": memory.get("query_count"),
        "memory_queries_with_candidate": memory.get("queries_with_candidate"),
        "memory_candidate_count": memory.get("candidate_count"),
        "memory_actual_consumption": memory.get("actual_consumption"),
        "memory_consumption_event_count": memory.get("consumption_event_count"),
        "memory_replay_count": memory.get("replay_count"),
        "memory_cross_agent_consumption": memory.get("cross_agent_consumption"),
        "memory_skipped_executor_generation": memory.get("skipped_executor_generation"),
        "codeact_status": codeact.get("status"),
        "codeact_fallback_enabled": codeact.get("fallback_enabled"),
        "codeact_fallback_attempted": codeact.get("fallback_attempted"),
        "codeact_dsl_execute_attempts": codeact.get("dsl_execute_attempts"),
        "codeact_python_attempts": codeact.get("python_attempts"),
        "codeact_completed_python_attempts": codeact.get("completed_python_attempts"),
        "repair_reasons": ";".join(record["repair_detail"].get("normalization_reasons", [])),
        "failure_codes": json.dumps(record.get("failure_codes", []), ensure_ascii=False),
        "scorer_errors": json.dumps(record.get("scorer_errors", []), ensure_ascii=False),
        "source_slot": record["source"]["slot"],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_summary(summary: JSON) -> str:
    lines = [
        "# Contest39 Mainchain Results",
        "",
        f"Collection date: {summary['collection_date']}.",
        "",
        "This package summarizes the final 48-task Contest39 mainchain runs. The raw `runs/` directories are unchanged; `task_results.jsonl` is the detailed per-task source for analysis and citation.",
        "",
        "## Overall",
        "",
        f"- Tasks: {summary['overall']['planned_count']} planned, {summary['overall']['passed_count']} passed.",
        f"- Quality pass rate: {summary['overall']['quality_pass_rate']:.3f}.",
        f"- Matched SB-FULL/P-TEXT task pairs: {summary['comparison']['matched_task_count']}; quality matches: {summary['comparison']['quality_matches']}.",
        "",
        "## Variant and Family",
        "",
        "| Variant | Family | Passed | Provider requests | Provider tokens | Mean e2e ms | Repairs | State read bytes | Memory actual/replay |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, group in summary["groups"].items():
        variant, family = key.split("/", 1)
        lines.append(
            f"| {variant} | {family} | {group['passed_count']}/{group['planned_count']} | "
            f"{group['provider']['request_count']} | {group['provider']['total_tokens']} | "
            f"{group['e2e_ms_mean']:.1f} | {group['repair']['count']} | "
            f"{group['state'].get('read_bytes', '-')} | "
            f"{group['memory'].get('actual_consumption', '-')}/{group['memory'].get('replay_count', '-')} |"
        )
    lines.extend(
        [
            "",
            "## Matched Comparison",
            "",
            "| Family | P-TEXT tokens | SB-FULL tokens | P-TEXT - SB-FULL | P-TEXT requests | SB-FULL requests |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for family in ("finance", "service_ops"):
        group = summary["groups"]
        pt = group[f"P-TEXT/{family}"]["provider"]
        sb = group[f"SB-FULL/{family}"]["provider"]
        lines.append(
            f"| {family} | {pt['total_tokens']} | {sb['total_tokens']} | "
            f"{pt['total_tokens'] - sb['total_tokens']} | {pt['request_count']} | {sb['request_count']} |"
        )
    lines.extend(
        [
            "",
            "## Observed Boundaries",
            "",
            "- SB-FULL state metrics are observed for publish/transfer/consume/release, logical payload/read bytes, selected evidence bytes, downstream effects, and physical reclamation.",
            "- P-TEXT state and memory are marked `not_applicable` because those mechanisms are disabled in that variant.",
            "- Provider tokens are model-provider usage, not inter-agent communication tokens.",
            "- `wire_bytes`, `typed_bytes`, object-boundary serialization bytes, and counterfactual avoided provider tokens are not collected or inferred.",
            "- State downstream effects in this run are reported as observed event values; they are not by themselves a causal business-benefit claim.",
            "",
            "## Files",
            "",
            "- `task_results.jsonl`: one compact record per task.",
            "- `task_results.csv`: flattened analysis index.",
            "- `summary.json`: machine-readable aggregate and matched comparison.",
            "- `manifest.json`: collection inputs and scope.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sb-run", type=Path, required=True, help="SB-FULL run root")
    parser.add_argument("--ptext-run", type=Path, required=True, help="P-TEXT run root")
    parser.add_argument("--output", type=Path, required=True, help="Derived result directory")
    args = parser.parse_args()

    args.sb_run = args.sb_run.resolve()
    args.ptext_run = args.ptext_run.resolve()
    args.output = args.output.resolve()

    sb_records = collect_run(args.sb_run, "SB-FULL")
    ptext_records = collect_run(args.ptext_run, "P-TEXT")
    records = sb_records + ptext_records
    if len(records) != 48:
        raise SystemExit(f"expected 48 task records, collected {len(records)}")

    args.output.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output / "task_results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    with (args.output / "task_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_row(record) for record in records)

    groups = {
        f"{variant}/{family}": aggregate_group(
            [row for row in records if row["variant"] == variant and row["family"] == family]
        )
        for variant in ("SB-FULL", "P-TEXT")
        for family in ("finance", "service_ops")
    }
    collection_date = date.today().isoformat()
    summary = {
        "schema_version": "contest39.mainchain.results.v1",
        "collection_date": collection_date,
        "record_count": len(records),
        "overall": aggregate_group(records),
        "groups": groups,
        "comparison": comparison(records),
        "limitations": [
            "wire_bytes not observed for these in-process handoffs",
            "typed_bytes and object-boundary serialized bytes not measured for SB-FULL",
            "counterfactual avoided provider tokens not measured",
            "provider tokens are not inter-agent communication tokens",
        ],
    }
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "manifest.json",
        {
            "schema_version": "contest39.mainchain.collection_manifest.v1",
            "collection_date": collection_date,
            "sources": {"SB-FULL": str(args.sb_run), "P-TEXT": str(args.ptext_run)},
            "records": len(records),
            "families": ["finance", "service_ops"],
            "variants": ["SB-FULL", "P-TEXT"],
            "raw_runs_modified": False,
            "files": [
                "README.md",
                "manifest.json",
                "task_results.jsonl",
                "task_results.csv",
                "summary.json",
                "summary.md",
            ],
        },
    )
    (args.output / "summary.md").write_text(markdown_summary(summary), encoding="utf-8")
    (args.output / "README.md").write_text(
        """# Contest39 Mainchain Result Package

This derived package contains compact evidence from the final 48-task Contest39 mainchain runs.

- `task_results.jsonl` is the canonical per-task record.
- `task_results.csv` is a flattened index for analysis and citation.
- `summary.json` and `summary.md` contain aggregate results and matched SB-FULL/P-TEXT comparisons.
- `manifest.json` records the two input run roots and collection scope.

The collector does not copy raw logs and does not infer `wire_bytes`, `typed_bytes`, object-boundary serialization bytes, or counterfactual avoided provider tokens.
""",
        encoding="utf-8",
    )
    print(f"collected {len(records)} tasks into {args.output}")


if __name__ == "__main__":
    main()
