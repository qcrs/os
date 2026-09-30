#!/usr/bin/env python3
"""Build the versioned, read-only Contest39 observatory replay bundle.

The input is an existing run and the evidence collection.  This script never
starts a task, reads arbitrary paths supplied by a caller, or copies payload
blobs.  It is intentionally deterministic so a bundle can be regenerated and
compared byte-for-byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SB = PROJECT_ROOT / "runs" / "contest39-sbfull-all-20260927_101009-1987732"
DEFAULT_PT = PROJECT_ROOT / "runs" / "contest39-ptext-all-20260927_101009-1987732"
EVIDENCE_ROOT = PROJECT_ROOT / "tests" / "evidence" / "mainline"
DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "statebus" / "studio" / "data" / "observatory" / "contest39-20260927"
TASKS = [f"F{index:02d}" for index in range(1, 13)]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(value: Any) -> Any:
    """Drop machine-local paths while retaining useful evidence fields."""
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items() if key not in {"mmap_path", "socket_path", "workspace_root_id"}}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str) and (value.startswith("/") or value.startswith("file://")):
        return value.rsplit("/", 1)[-1]
    return value


def _source_ref(task_id: str, filename: str, line: int | None = None, pointer: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": f"finance/slots/{task_id}/{filename}"}
    if line is not None:
        result["line"] = line
    if pointer:
        result["json_pointer"] = pointer
    return result


def _kind(event: str) -> str:
    names = {
        "ADAPTIVE_PLAN_APPROVED": "runtime.plan.approved",
        "STEP_DISPATCHED": "runtime.capability.grant",
        "STEP_RUNNING": "runtime.step.running",
        "STEP_COMPLETED": "runtime.step.completed",
        "STEP_SKIPPED": "runtime.step.skipped",
        "STATE_PUBLISHED": "state.publish",
        "STATE_RESOLVED": "state.resolve",
        "STATE_CONSUMED": "state.consume",
        "STATE_RELEASED": "state.release",
        "MEMORY_COMMIT_VERIFIED": "memory.commit.verified",
        "MEMORY_QUERY": "memory.query",
        "MEMORY_CONSUMED": "memory.consume",
        "ARTIFACT_VALIDATED": "artifact.validated",
        "QUALITY_GATE_PASSED": "quality.gate.passed",
    }
    return names.get(event, event.lower().replace("_", "."))


def _object_ids(payload: dict[str, Any], source: dict[str, Any]) -> list[str]:
    keys = ("ref_id", "memory_id", "artifact_ref_id", "grant_id", "query_id", "consume_receipt", "message_id", "approved_plan_hash")
    values = [payload.get(key) for key in keys] + [source.get(key) for key in keys]
    return [str(value) for value in values if value]


def _event(task_id: str, order: int, kind: str, actor: str, source: dict[str, Any], *, timestamp: int | None = None, payload: dict[str, Any] | None = None, object_ids: list[str] | None = None, time_basis: str = "causal_order") -> dict[str, Any]:
    return {
        "id": f"{task_id}:{source['path'].split('/')[-1]}:{source.get('line', order)}",
        "kind": kind,
        "order": order,
        "event_ts_ns": timestamp,
        "time_basis": time_basis,
        "actor": actor or "runtime",
        "object_ids": object_ids or [],
        "source_ref": source,
        "payload": _safe(payload or {}),
    }


def _state_object(task_id: str, state_rows: list[dict[str, Any]], metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    publish = next((row for row in state_rows if row.get("event") == "publish"), None)
    if not publish:
        return None
    consume = next((row for row in state_rows if row.get("event") == "consume"), {})
    descriptor = (consume.get("receipt") or {}).get("descriptor_identity") or {}
    ref_id = str(publish.get("ref") or "")
    return {
        "id": ref_id,
        "object_type": "SemanticStateRef",
        "label": "SemanticState",
        "summary": "Retriever 发布的跨进程语义矩阵引用",
        "fields": {
            "ref_id": ref_id,
            "state_type": publish.get("state_type"),
            "storage_kind": publish.get("storage_kind") or descriptor.get("storage_kind", "mmap_file"),
            "shape": descriptor.get("shape", [5, 1024]),
            "dtype": descriptor.get("dtype", "float32"),
            "size_bytes": publish.get("payload_bytes") or descriptor.get("size_bytes"),
            "producer_pid": publish.get("producer_pid"),
            "consumer_pid": consume.get("consumer_pid"),
            "wire_bytes": None,
            "wire_bytes_missing_reason": "cross_process_ref_resolution_not_a_payload_copy",
            "blob_hash": publish.get("hash") or descriptor.get("blob_hash"),
            "behavioral_effect": consume.get("behavioral_effect", "no_effect"),
        },
    }


def _task_bundle(sb_root: Path, task_id: str) -> dict[str, Any]:
    slot = sb_root / "finance" / "slots" / task_id
    task_row = _json(slot / "task-row.json")
    contract = _json(slot / "manifest.json").get("contract", {})
    report = _json(slot / "report.json")
    claim_set = next(iter(report.values()))
    rows = json.loads((slot / "rows.json").read_text(encoding="utf-8"))
    if contract.get("task_id") != task_id or claim_set.get("task_id") != task_id or not isinstance(rows, list):
        raise ValueError(f"{task_id} input/output records do not match the replay task")
    runtime_rows = _jsonl(slot / "runtime" / "telemetry" / "runtime_events.jsonl")
    state_rows = _jsonl(slot / "state-events.jsonl")
    memory_rows = _jsonl(slot / "memory-events.jsonl")
    handoff_rows = _jsonl(slot / "handoffs.jsonl")
    runtime_evidence = _json(slot / "runtime-evidence.json") if (slot / "runtime-evidence.json").is_file() else {}

    events: list[dict[str, Any]] = []
    raw_evidence: list[dict[str, Any]] = []
    order = 0
    for line, row in enumerate(runtime_rows, 1):
        event_type = str(row.get("event_type", ""))
        if event_type not in {"ADAPTIVE_PLAN_APPROVED", "STEP_DISPATCHED", "STEP_RUNNING", "STEP_COMPLETED", "STEP_SKIPPED", "STATE_PUBLISHED", "STATE_RESOLVED", "STATE_CONSUMED", "STATE_RELEASED", "MEMORY_COMMIT_VERIFIED", "ARTIFACT_VALIDATED", "QUALITY_GATE_PASSED"}:
            continue
        order += 1
        source = _source_ref(task_id, "runtime/telemetry/runtime_events.jsonl", line)
        item = _event(task_id, order, _kind(event_type), str(row.get("role", "")), source, timestamp=row.get("event_ts_ns"), payload=row.get("payload") or {}, object_ids=_object_ids(row.get("payload") or {}, row), time_basis="runtime_timestamp")
        events.append(item)
        if event_type in {"ADAPTIVE_PLAN_APPROVED", "STATE_PUBLISHED", "STATE_RESOLVED", "STATE_CONSUMED", "MEMORY_COMMIT_VERIFIED", "STATE_RELEASED"}:
            raw_evidence.append({"source_ref": source, "event_type": event_type, "fields": _safe({"event_id": row.get("event_id"), "payload": row.get("payload"), "metrics": row.get("metrics")})})

    for filename, event_rows, event_key in (("state-events.jsonl", state_rows, "event"), ("memory-events.jsonl", memory_rows, "event")):
        for line, row in enumerate(event_rows, 1):
            order += 1
            source = _source_ref(task_id, filename, line)
            kind = _kind(f"{event_key}_{row.get(event_key, 'unknown')}")
            actor = str(row.get("consumer_agent") or row.get("consumer") or ("retriever" if row.get(event_key) in {"publish", "query"} else "runtime"))
            ids = _object_ids(row, row.get("receipt") or {})
            events.append(_event(task_id, order, kind, actor, source, payload=row, object_ids=ids))
            if row.get(event_key) in {"query", "consume", "publish", "release"}:
                raw_evidence.append({"source_ref": source, "event_type": f"{event_key}.{row.get(event_key)}", "fields": _safe(row)})

    for line, row in enumerate(handoff_rows, 1):
        if row.get("event") != "consume":
            continue
        order += 1
        source = _source_ref(task_id, "handoffs.jsonl", line)
        events.append(_event(task_id, order, "handoff.consume", str(row.get("receiver", "")), source, timestamp=row.get("timestamp_ns"), payload=row, object_ids=[str(row.get("message_id"))] if row.get("message_id") else [], time_basis="runtime_timestamp"))

    commit = next((row for row in runtime_rows if row.get("event_type") == "MEMORY_COMMIT_VERIFIED"), {})
    commit_payload = commit.get("payload") or {}
    memory_consumes = [row for row in memory_rows if row.get("event") == "consume"]
    query = next((row for row in memory_rows if row.get("event") == "query"), {})
    objects: list[dict[str, Any]] = []
    state = _state_object(task_id, state_rows, None)
    if state:
        objects.append(state)
    # The story follows the object actually consumed in this task.  A task can
    # also commit a new Memory at the end; that commit is evidence, not the
    # replay source shown in the Memory view.
    consumed = memory_consumes[0] if memory_consumes else {}
    artifact_id = str(consumed.get("artifact_ref_id") or commit_payload.get("artifact_ref_id") or "")
    memory_id = str(consumed.get("memory_ref") or commit_payload.get("memory_id") or "")
    verdict_decision = next((decision for decision in query.get("decisions", []) if decision.get("memory_id") == memory_id), {})
    if artifact_id:
        objects.append({"id": artifact_id, "object_type": "ExecutionArtifactRef", "label": "Verified Artifact", "summary": "通过质量门并可进入 Memory 的结构化产物", "fields": {"artifact_ref_id": artifact_id, "artifact_hash": commit_payload.get("artifact_hash"), "quality_report_hash": commit_payload.get("quality_report_hash"), "source_ref": _source_ref(task_id, "runtime/telemetry/runtime_events.jsonl")}})
    if memory_id:
        objects.append({"id": memory_id, "object_type": "MemoryRef", "label": "Memory", "summary": "跨任务可复用的 verified artifact 引用", "fields": {"memory_id": memory_id, "artifact_ref_id": artifact_id, "verdict": verdict_decision.get("verdict"), "replay_class": verdict_decision.get("replay_class"), "candidate_count": query.get("candidate_count", 0), "source_task_id": next((value.split(":", 2)[1] for value in [memory_id] if value.count(":") >= 2), None)}})
    if query:
        objects.append({"id": str(query.get("query_id")), "object_type": "MemoryQuery/Verdict", "label": "Memory Query", "summary": f"{query.get('candidate_count', 0)} 个候选，按合同判定", "fields": _safe(query)})
    for index, consume in enumerate(memory_consumes, 1):
        receipt_id = str(consume.get("consume_receipt") or f"{task_id}:memory-consume:{index}")
        objects.append({"id": receipt_id, "object_type": "Receipt", "label": "Consume receipt", "summary": f"{consume.get('consumer_agent', 'consumer')} 实际消费", "fields": _safe(consume)})
    grants = [row.get("payload", {}).get("grant_hash") for row in runtime_rows if row.get("event_type") == "STEP_DISPATCHED" and row.get("payload", {}).get("grant_hash")]
    for grant in grants:
        objects.append({"id": str(grant), "object_type": "CapabilityGrant", "label": "Capability grant", "summary": "Runtime 授权门", "fields": {"grant_hash": grant}})

    edges: list[dict[str, Any]] = []
    if artifact_id and memory_id:
        edges.append({"from": artifact_id, "to": memory_id, "kind": "verified_commit", "label": "verified commit"})
    if memory_id and query.get("query_id"):
        edges.append({"from": memory_id, "to": str(query["query_id"]), "kind": "candidate", "label": "candidate / verdict"})
    for consume in memory_consumes:
        receipt = str(consume.get("consume_receipt") or "")
        if receipt and memory_id:
            edges.append({"from": memory_id, "to": receipt, "kind": "actual_consumption", "label": str(consume.get("replay_class") or "consume")})
    if state:
        edges.extend([{"from": state["id"], "to": f"artifact:{task_id}", "kind": "state_to_evidence", "label": "selected evidence"}])

    run_id = str((runtime_rows[0].get("trace_id") if runtime_rows else "") or task_row.get("task_id") or task_id)
    return {
        "task_id": task_id,
        "family": "finance",
        "variant": "SB-FULL",
        "run_id": run_id,
        "status": task_row.get("status", "success"),
        "round": task_row.get("round"),
        "metrics": _safe(task_row.get("metrics", {})),
        "task_contract": {
            "method": contract.get("method"),
            "periods": contract.get("periods", []),
            "required_history": contract.get("required_history", []),
            "instructions": contract.get("instructions", ""),
            "input_schemas": contract.get("input_schemas", {}),
            "output_schema": contract.get("output_schema", {}),
            "source_ref": _source_ref(task_id, "manifest.json", pointer="/contract"),
        },
        "delivery": {
            "rows": _safe(rows),
            "rows_source_ref": _source_ref(task_id, "rows.json"),
            "claim_set": _safe(claim_set),
            "report_source_ref": _source_ref(task_id, "report.json"),
            "quality_passed": task_row.get("quality"),
            "business_quality_passed": task_row.get("business_quality"),
            "mechanism_gate_passed": task_row.get("mechanism_gate_passed"),
            "quality_source_ref": _source_ref(task_id, "task-row.json"),
        },
        "events": events,
        "objects": objects,
        "edges": edges,
        "raw_evidence": raw_evidence[:80],
        "source_ref": _source_ref(task_id, "task-row.json"),
    }


def _evidence_payload() -> dict[str, Any]:
    results = _json(EVIDENCE_ROOT / "results.json")
    with (EVIDENCE_ROOT / "tasks.csv").open(encoding="utf-8", newline="") as handle:
        tasks = list(csv.DictReader(handle))
    return {"collection": "contest39-20260927", "results": results, "tasks": tasks}


def build(sb_root: Path, ptext_root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    task_dir = output / "tasks"
    task_dir.mkdir(exist_ok=True)
    for task_id in TASKS:
        payload = _task_bundle(sb_root, task_id)
        (task_dir / f"{task_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence = _evidence_payload()
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_files: list[dict[str, Any]] = []
    for root, prefix in ((sb_root, "SB-FULL"), (ptext_root, "P-TEXT"), (EVIDENCE_ROOT, "evidence")):
        candidates: Iterable[Path] = root.rglob("*")
        for path in sorted(candidates):
            if not path.is_file() or path.suffix in {".sqlite3", ".bin", ".npy", ".npz"}:
                continue
            relative = path.relative_to(root)
            if prefix != "evidence" and not (str(relative).startswith("finance/slots/") and path.name in {"task-row.json", "state-events.jsonl", "memory-events.jsonl", "handoffs.jsonl", "runtime_events.jsonl", "runtime-evidence.json", "manifest.json", "rows.json", "report.json"}):
                continue
            source_files.append({"variant": prefix, "path": str(relative), "sha256": _sha256(path)})
    manifest = {
        "schema": "statebus.observatory.replay.v1",
        "collection": "contest39-20260927",
        "collection_date": "2026-09-27",
        "generator_version": "observatory-bundle-v1",
        "run_ids": {"SB-FULL": sb_root.name, "P-TEXT": ptext_root.name},
        "task_ids": TASKS,
        "families": ["finance"],
        "source_files": source_files,
        "constraints": {"offline": True, "payload_blobs_included": False, "wire_bytes": "unmeasured"},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sb-full", type=Path, default=DEFAULT_SB)
    parser.add_argument("--p-text", type=Path, default=DEFAULT_PT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.sb_full, args.p_text, args.output)


if __name__ == "__main__":
    main()
