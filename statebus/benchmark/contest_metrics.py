"""Durable metrics shared by the typed and text contest callers.

Logical callback payloads are measured at invocation; they are not physical
wire traffic. Tokenization is local, without chat-template/special tokens.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
import os
from pathlib import Path

from statebus.benchmark.request_journal import append_event, summarize_journal
from statebus.utils import stable_json_dumps


@lru_cache(maxsize=2)
def _tokenizer(path: str):
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(Path(path) / "tokenizer.json"))


def record_handoff(path, sender, receiver, *, text=None, payload=None, scope):
    serialized = text if text is not None else stable_json_dumps(payload)
    tokenizer_path = os.getenv("STATEBUS_VLLM_TOKENIZER_PATH", "/data/models/Qwen3-32B")
    available = (Path(tokenizer_path) / "tokenizer.json").is_file()
    event = {
        "sender": sender, "receiver": receiver, "scope": scope,
        "carrier": "utf8_text" if text is not None else "typed_payload_projection",
        "text": serialized, "characters": len(serialized), "utf8_bytes": len(serialized.encode("utf-8")),
        "tokens": len(_tokenizer(tokenizer_path).encode(serialized, add_special_tokens=False).ids) if available else None,
        "tokenizer_path": tokenizer_path, "tokenization": "local_no_special_tokens" if available else "missing_local_tokenizer",
    }
    if payload is not None:
        event["payload"] = payload
    append_event(path, event)


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def handoff_measurement(root):
    entries = read_events(root / "handoffs.jsonl") + read_events(root / "execution" / "handoffs.jsonl")
    edges = {}
    for entry in entries:
        edge = entry["sender"] + "->" + entry["receiver"]
        edges.setdefault(edge, []).append(entry)
    def totals(items):
        return {"messages": len(items), "characters": sum(e["characters"] for e in items),
                "utf8_bytes": sum(e["utf8_bytes"] for e in items),
                "tokens": sum(e["tokens"] for e in items) if all(e.get("tokens") is not None for e in items) else None}
    total = totals(entries)
    return {"observed_callback_messages": total["messages"], "observed_callback_characters": total["characters"],
            "observed_callback_utf8_bytes": total["utf8_bytes"], "tokens": total["tokens"],
            "edges": {edge: totals(items) for edge, items in edges.items()},
            "tokenization": "local_no_special_tokens" if total["tokens"] is not None else "missing_local_tokenizer",
            "scope": "actual_callback_payload_projections_including_retries; see per-edge counts",
            "complete_agent_handoff_bytes": None, "matched_receiver_comparison": False,
            "reason": "Typed callbacks and text handoffs are observable logical boundaries, not exhaustive wire traffic or B2 matched receivers."}


def unified_metrics(summary, root, *, status=None):
    provider = summarize_journal(root / "provider.jsonl")
    handoff = handoff_measurement(root)
    events = read_events(root / "execution" / "metric-events.jsonl")
    repairs = Counter(e["kind"] for e in events if e["event"] == "repair_requested")
    provider_events = [p for e in read_events(root / "provider.jsonl") if e["event"] == "finished" for p in e["provider_events"]]
    provider_timeouts = sum("timeout" in str(e.get("error_type", "")).lower() or "timeout" in str(e.get("status", "")).lower() for e in provider_events)
    # Text attempts are durable even when the worker fails before result.json.
    text_attempts = read_events(root / "execution" / "tool-events.jsonl")
    tool_timeouts = sum(e.get("timeout", False) for e in summary.get("execution_records", []))
    tool_timeouts += sum(e.get("returncode") == 124 for e in text_attempts)
    return {
        "handoff_message_count": handoff["observed_callback_messages"],
        "handoff_text_characters": handoff["observed_callback_characters"],
        "handoff_utf8_bytes": handoff["observed_callback_utf8_bytes"], "handoff_tokens": handoff["tokens"],
        "handoff_edges": handoff["edges"], "handoff_scope": handoff["scope"],
        "provider_request_count": provider["provider_request_count"],
        "provider_observed_request_count": provider["observed_provider_request_count"],
        **{f"provider_{key}": value for key, value in provider["usage"].items()},
        "provider_observed_usage_partial": provider["observed_usage_partial"],
        "provider_usage_missing_reason": provider["usage_missing_reason"],
        **{f"{role}_request_count": count for role, count in provider["roles"].items()},
        "repairs": {kind: repairs[kind] for kind in ("policy", "runtime", "quality", "report")},
        "repairs_by_role": {role: sum(e.get("role") == role for e in events if e["event"] == "repair_requested")
                            for role in ("planner", "executor", "summarizer")},
        "timeout_count": provider_timeouts + tool_timeouts + int(status == "timeout"),
        "timeout_scope": "observed_provider_and_tool_and_outer_watchdog_events; not unique_tasks; typed attempts unavailable before runtime summary are not inferred",
    }


def aggregate_metrics(ledger):
    attempted = [row for row in ledger if row["status"] in {"success", "failed", "timeout"}]
    def observed_sum(key):
        values = [row["metrics"].get(key) for row in attempted]
        return sum(values) if all(value is not None for value in values) else None
    return {"attempted_count": len(attempted),
            **{key: observed_sum(key) for key in (
                "provider_request_count", "provider_observed_request_count", "provider_prompt_tokens", "provider_completion_tokens",
                "provider_total_tokens", "handoff_message_count", "handoff_text_characters", "handoff_utf8_bytes", "handoff_tokens", "timeout_count")},
            "repairs": {kind: sum(row["metrics"]["repairs"][kind] for row in attempted) for kind in ("policy", "runtime", "quality", "report")},
            "includes_failed_attempts": True, "missing_values_are_not_zero": True}
