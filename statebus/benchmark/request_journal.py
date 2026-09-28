"""Opt-in, durable provider-boundary audit for live benchmark callers.

A started event survives caller failure/timeout. Usage is server-observed or null;
this journal never equates provider prompts with inter-agent communication.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid


def append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class JournalClient:
    def __init__(self, delegate, path: Path):
        self.delegate, self.path = delegate, path

    @property
    def request_events(self):
        return self.delegate.request_events

    def describe(self):
        return self.delegate.describe()

    async def complete(self, messages, *, purpose, **kwargs):
        call_id = str(uuid.uuid4())
        start = time.monotonic_ns()
        offset = len(self.delegate.request_events)
        append_event(self.path, {
            "call_id": call_id, "event": "started", "role": purpose, "start_ns": start,
            "pid": os.getpid(),
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "response_schema": kwargs.get("response_schema"),
        })
        result = None
        try:
            result = await self.delegate.complete(messages, purpose=purpose, **kwargs)
            return result
        finally:
            events = self.delegate.request_events[offset:]
            append_event(self.path, {
                "call_id": call_id, "event": "finished", "role": purpose,
                "start_ns": start, "end_ns": time.monotonic_ns(), "provider_events": events,
                "status": "response_received" if result is not None else "error",
                "raw_response": result.text if result is not None else None,
                "model": result.model if result is not None else None,
                "finish_reason": result.finish_reason if result is not None else None,
            })


def with_optional_request_journal(client):
    path = os.getenv("STATEBUS_PROVIDER_JOURNAL")
    return JournalClient(client, Path(path)) if path else client


def summarize_journal(path: Path) -> dict:
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    started = {e["call_id"]: e for e in events if e["event"] == "started"}
    finished = {e["call_id"]: e for e in events if e["event"] == "finished"}
    provider = [p for e in finished.values() for p in e["provider_events"]]
    unresolved = sorted(set(started) - set(finished))
    usage = {}
    observed_usage = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [event.get("response_" + name) for event in provider]
        usage[name] = sum(values) if values and all(v is not None for v in values) and not unresolved else None
        observed_usage[name] = sum(v for v in values if v is not None) if any(v is not None for v in values) else None
    return {
        "call_count": len(started), "provider_request_count": len(provider) if not unresolved else None,
        "observed_provider_request_count": len(provider), "unresolved_call_ids": unresolved,
        "usage": usage, "usage_missing_reason": "failed_or_unsettled_request_usage" if any(v is None for v in usage.values()) else "",
        "observed_usage_partial": observed_usage,
        "roles": {role: sum(e["role"] == role for e in started.values()) for role in ("planner", "retriever", "executor", "summarizer")},
    }
