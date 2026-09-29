"""Five evidence tables for the frozen DSL slot ledger.

Public API: ``collect_slot_metrics(slot_root)``, ``aggregate_slots(ledger)``,
``build_tables(ledger)``, ``write_reports(output_root, ledger)``.
Ledger rows identify chain_id/family/variant/round/task_id/status and slot_root.
Optional precollected ``metrics`` override metrics read from that slot's
provider.jsonl. Handoffs are in handoffs.jsonl. Mechanism evidence is stored in
state-events.jsonl, memory-events.jsonl and codeact-events.jsonl, or supplied
explicitly as state_rows/memory_rows/codeact_rows on a slot. No mechanism or
zero-cost observation is inferred from a variant name.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from typing import Any, Iterable

from statebus.benchmark.request_journal import summarize_journal


STATUSES = {"running", "success", "quality_fail", "runtime_fail", "timeout", "blocked", "not_started"}
STARTED = {"running", "success", "quality_fail", "runtime_fail", "timeout"}
IDENTITY = ("chain_id", "family", "variant", "round", "task_id")
PROVIDER_FIELDS = ("provider_request_count", "provider_prompt_tokens", "provider_completion_tokens", "provider_total_tokens")
COLUMNS = {
    "product": (*IDENTITY, "task_profile", "mode", "status", "returncode", "quality", "business_quality", "mechanism_gate_passed", "repair", *PROVIDER_FIELDS,
                "provider_observed_request_count", "provider_usage_missing_reason", "e2e_ms", "blocked_reason",
                "failure_codes", "scorer_errors"),
    "communication": (*IDENTITY, "status", "sender", "receiver", "step", "message_id", "carrier",
                      "message_count", "received_count", "consumed_count", "error_count", "handoff_text_chars",
                      "handoff_text_tokens", "handoff_tokens_missing_reason", "handoff_text_bytes", "typed_bytes",
                      "control_bytes", "serialized_bytes", "wire_bytes", "wire_missing_reason", "serialize_ms",
                      "parse_ms", "decode_ms", "hydrate_ms", "hydrate_bytes", "object_copy_ms", "receiver_ms",
                      *PROVIDER_FIELDS, "provider_metric_scope", "missing_reason"),
    "state": (*IDENTITY, "status", "event", "state_type", "publish_count", "transfer_count", "consume_count",
              "release_count", "object_id", "ref", "schema", "hash", "payload_bytes", "read_bytes", "hydrate_bytes",
              "generation_ms", "consume_ms", "consumer", "downstream_effect", "activity", "missing_reason"),
    "memory": (*IDENTITY, "status", "event", "query_id", "query_count", "candidate_count", "queries_with_candidate",
               "hit_rate", "actual_reuse_rate", "policy_approved", "compatibility_approved", "grant_id", "memory_ref",
               "source_agent", "consumer_agent", "hydrate_count", "hydrate_bytes", "actual_consumption", "consume_receipt",
               "replay_count", "skipped_executor_generation", "avoided_tokens", "input_recomputed", "quality_parity",
               "quality_passed", "downstream_effect", "rejection_reason", "producer_inclusive_cost", "replay_latency_ms",
               "missing_reason"),
    "codeact": (*IDENTITY, "status", "first_attempt", "final_result", "repair", "sandbox", "artifact", "validator",
                "citation", *PROVIDER_FIELDS, "generation_ms", "execution_ms", "validation_ms", "e2e_ms", "failure_class",
                "missing_reason"),
}


def read_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sum_known(values: Iterable[Any]) -> int | float | None:
    values = list(values)
    return sum(values) if values and all(value is not None for value in values) else None


def collect_slot_metrics(slot_root: Path) -> dict:
    """Read provider observations, preserving incomplete and missing usage."""
    path = Path(slot_root) / "provider.jsonl"
    if not path.is_file():
        return {**dict.fromkeys(PROVIDER_FIELDS), "provider_observed_request_count": None,
                "provider_usage_missing_reason": "provider_journal_not_created"}
    provider = summarize_journal(path)
    return {"provider_request_count": provider["provider_request_count"],
            "provider_observed_request_count": provider["observed_provider_request_count"],
            **{f"provider_{name}": value for name, value in provider["usage"].items()},
            "provider_usage_missing_reason": provider["usage_missing_reason"] or None,
            "provider_observed_usage_partial": provider["observed_usage_partial"],
            "provider_unresolved_call_ids": provider["unresolved_call_ids"],
            **{f"{role}_request_count": count for role, count in provider["roles"].items()}}


def _identity(row: dict) -> dict:
    return {key: row.get(key) for key in IDENTITY}


def _root(row: dict) -> Path | None:
    value = row.get("slot_root")
    return Path(value) if value else None


def _metrics(row: dict) -> dict:
    root = _root(row)
    return {**(collect_slot_metrics(root) if root else {}), **row.get("metrics", {})}


def validate_ledger(ledger: list[dict]) -> None:
    keys = [(row["chain_id"], row["task_id"]) for row in ledger]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate task slots in the frozen ledger")
    for row in ledger:
        if row["status"] not in STATUSES:
            raise ValueError(f"unknown slot status: {row['status']}")


def aggregate_slots(ledger: list[dict]) -> dict:
    """Keep blocked and not_started visible with explicit denominators.

    'started' means actual execution began. 'accountable' includes blocked
    slots: a failed prior task cannot improve the chain's success rate by
    preventing downstream execution. Planned rates additionally include the
    explicitly not_started slots, without labelling those slots as failures.
    """
    validate_ledger(ledger)
    counts = Counter(row["status"] for row in ledger)
    started = [row for row in ledger if row["status"] in STARTED]
    passed = counts["success"]
    quality_count = sum(row.get("quality") is True for row in started)
    quality_observed = all("quality" in row for row in started)
    accountable = len(started) + counts["blocked"]
    metric_rows = [_metrics(row) for row in started]
    return {"planned_count": len(ledger), "started_count": len(started), "blocked_count": counts["blocked"],
            "not_started_count": counts["not_started"], "passed_count": passed,
            "status_counts": {status: counts[status] for status in sorted(STATUSES)},
            "business_quality_passed_count": quality_count if quality_observed else None,
            "quality_pass_rate": quality_count / len(started) if started and quality_observed else None,
            "success_rate": passed / accountable if accountable else None,
            "success_rate_denominator": "started_plus_blocked",
            "success_rate_started": passed / len(started) if started else None,
            "success_rate_planned": passed / len(ledger) if ledger else None,
            **{key: _sum_known(row.get(key) for row in metric_rows) for key in PROVIDER_FIELDS},
            "observed_provider_usage_partial": {
                key: sum(row[key] for row in metric_rows if row.get(key) is not None)
                if any(row.get(key) is not None for row in metric_rows) else None for key in PROVIDER_FIELDS},
            "e2e_ms": _sum_known(row.get("e2e_ms") for row in started),
            "missing_values_are_not_zero": True,
            "all_frozen_slots_retained": True}


def _unobserved(row: dict, reason: str) -> dict:
    return {**_identity(row), "status": "not_observed", "missing_reason": reason}


def _communication_rows(row: dict, metrics: dict) -> list[dict]:
    root = _root(row)
    events = read_events(root / "handoffs.jsonl") if root else []
    messages = defaultdict(list)
    for event in events:
        messages[event["message_id"]].append(event)
    result = []
    for message_id, trace in messages.items():
        merged = {}
        for event in trace:
            merged.update(event)
        kinds = Counter(event["event"] for event in trace)
        result.append({**_identity(row), **merged, "message_id": message_id,
                       "status": "error" if kinds["error"] else "consumed" if kinds["consume"] else "unsettled",
                       "message_count": kinds["send"], "received_count": kinds["receive"],
                       "consumed_count": kinds["consume"], "error_count": kinds["error"],
                       **{key: metrics.get(key) for key in PROVIDER_FIELDS},
                       "provider_metric_scope": "slot_total_repeated_for_context_do_not_sum_across_edges"})
    return result or [_unobserved(row, "no_handoff_events")]


def _mechanism_rows(row: dict, name: str) -> list[dict]:
    """Project actual event fields only; variant names grant no evidence."""
    supplied = row.get(f"{name}_rows")
    root = _root(row)
    events = supplied if supplied is not None else read_events(root / f"{name}-events.jsonl") if root else []
    result = []
    for event in events:
        item = {**_identity(row), "status": "observed", **event}
        if name == "state":
            for operation in ("publish", "transfer", "consume", "release"):
                item.setdefault(f"{operation}_count", int(event.get("event") == operation))
        result.append(item)
    return result or [_unobserved(row, f"no_{name}_events")]


def memory_totals(rows: list[dict]) -> dict:
    """Summarize query-based Memory evidence, never treating a hit as use.

    Query records carry candidate_count. Actual consumption requires a
    distinct consume event with the same query_id and an explicit receipt.
    Other evidence remains in the raw rows, including rejection and no-effect.
    """
    observed = [row for row in rows if row.get("status") != "not_observed"]
    queries = {(row.get("chain_id"), row.get("task_id"), row["query_id"]): row
               for row in observed if row.get("event") == "query" and row.get("query_id") is not None}
    if not queries:
        return {"query_count": 0 if observed else None, "queries_with_candidate": None,
                "actual_consumption": None, "hit_rate": None, "actual_reuse_rate": None,
                "missing_reason": "no_memory_queries_observed"}
    # Candidate observations may follow the query in the durable journal.
    candidates = {key: value.get("candidate_count") for key, value in queries.items()}
    consumed = set()
    for row in observed:
        key = (row.get("chain_id"), row.get("task_id"), row.get("query_id"))
        if key not in queries:
            continue
        if row.get("candidate_count") is not None:
            candidates[key] = row["candidate_count"]
        if row.get("event") == "consume" and row.get("consume_receipt"):
            consumed.add(key)
    hits = sum(value > 0 for value in candidates.values()) if all(value is not None for value in candidates.values()) else None
    return {"query_count": len(queries), "queries_with_candidate": hits,
            "actual_consumption": len(consumed), "hit_rate": hits / len(queries) if hits is not None else None,
            "actual_reuse_rate": len(consumed) / len(queries),
            "missing_reason": "unsettled_candidate_lookup" if hits is None else None}


def build_tables(ledger: list[dict]) -> dict[str, list[dict]]:
    validate_ledger(ledger)
    tables = {name: [] for name in COLUMNS}
    for row in ledger:
        metrics = _metrics(row)
        tables["product"].append({**_identity(row), **{key: row.get(key) for key in
                ("task_profile", "mode", "status", "returncode", "quality", "business_quality", "mechanism_gate_passed", "repair", "e2e_ms", "blocked_reason", "failure_codes", "scorer_errors")}, **metrics})
        tables["communication"].extend(_communication_rows(row, metrics))
        for name in ("state", "memory", "codeact"):
            tables[name].extend(_mechanism_rows(row, name))
    return tables


def _cell(value: Any, *, markdown: bool = False) -> str:
    if value is None:
        return "missing"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list, bool)) else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>") if markdown else text


def write_reports(output_root: Path, ledger: list[dict]) -> dict:
    """Write five JSON/CSV/Markdown tables plus denominator-aware summary.

    JSON preserves null; CSV and Markdown show 'missing'. Caller owns the
    output directory's lifecycle and must choose a new experiment root.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    tables = build_tables(ledger)
    paths = {}
    for name, rows in tables.items():
        # Preserve observed extension fields in all three formats.
        columns = list(COLUMNS[name])
        columns.extend(sorted({key for row in rows for key in row} - set(columns)))
        normalized = [{key: row.get(key) for key in columns} for row in rows]
        json_path, csv_path, md_path = (output_root / f"{name}.{extension}" for extension in ("json", "csv", "md"))
        json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows({key: _cell(value) for key, value in row.items()} for row in normalized)
        md = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        md.extend("| " + " | ".join(_cell(row[key], markdown=True) for key in columns) + " |" for row in normalized)
        md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
        paths[name] = {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}
    by_chain = defaultdict(list)
    for row in ledger:
        by_chain[row["chain_id"]].append(row)
    summary = {"aggregate": aggregate_slots(ledger),
               "chains": {key: aggregate_slots(rows) for key, rows in by_chain.items()},
               "memory": memory_totals(tables["memory"]), "tables": paths,
               "producer_inclusive_cost": {"scope": "all started slots including producer generation, repair and consumers; not a reuse-only subtotal",
                   "by_chain": {key: {field: aggregate_slots(rows)[field] for field in (*PROVIDER_FIELDS, "e2e_ms")}
                                for key, rows in by_chain.items()}},
               "claim_boundary": "product comparison only; causal mechanism claims require matched receiver/input/scorer evidence"}
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
