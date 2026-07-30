#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.contracts import CanonicalTaskSpec
from v2.runtime.smoke import SmokeLayerConfig, run_smoke
from v2.utils import sha256_digest


DEFAULT_DOCUMENT = (
    REPO_ROOT
    / "v2/benchmark/samples/engine_local_kv_continuation/compiled_parents/kv-fin-4k-nova.txt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one serialized full-mainline full-replay/KV-continuation A/B pair."
    )
    parser.add_argument("--mode", choices=("ab", "full_replay", "continuation"), default="ab")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--parent-tokens", type=int, default=4096)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = datetime.now(timezone.utc).strftime("mainline-ab-%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (
        Path(os.getenv("STATEBUS_RUN_ROOT", REPO_ROOT / "runs"))
        / "engine_local_kv_mainline"
        / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _configure_environment(args)
    modes = ("full_replay", "continuation") if args.mode == "ab" else (args.mode,)
    records = [_run_lane(mode, output_dir=output_dir, document=args.document) for mode in modes]
    summary = _summarize(run_id=run_id, output_dir=output_dir, records=records)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"run_id={run_id}")
    print(f"output_dir={output_dir}")
    for record in records:
        print(
            f"{record['mode']}: wall_ms={record['mainline_wall_ms']:.3f} "
            f"ttft_ms={record['consumer_ttft_ms']:.3f} "
            f"computed={record['computed_prefill_tokens']} "
            f"inherited={record['inherited_kv_tokens']} "
            f"quality={record['quality_floor_pass']}"
        )
    comparison = summary.get("comparison", {})
    if comparison:
        print(
            "comparison: "
            f"ttft_reduction={comparison['consumer_ttft_reduction']:.4f} "
            f"computed_reduction={comparison['computed_prefill_reduction']:.4f} "
            f"mainline_wall_reduction={comparison['mainline_wall_reduction']:.4f} "
            f"consumer_output_equal={comparison['consumer_output_token_digest_equal']}"
        )
    return 0 if all(record["quality_floor_pass"] for record in records) else 2


def _configure_environment(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    defaults = {
        "STATEBUS_LLM_MODE": "local_vllm",
        "STATEBUS_LLM_BASE_URL": f"{base_url}/v1",
        "STATEBUS_LLM_DEFAULT_MODEL": args.model,
        "STATEBUS_LLM_REQUEST_MAX_ATTEMPTS": "1",
        "STATEBUS_LLM_TIMEOUT_S": "300",
        "STATEBUS_LLM_PLANNER_MAX_TOKENS": "512",
        "STATEBUS_LLM_RETRIEVER_MAX_TOKENS": "96",
        "STATEBUS_LLM_PLANNER_MAX_CONTEXT_TOKENS": "8192",
        "STATEBUS_LLM_RETRIEVER_MAX_CONTEXT_TOKENS": "8192",
        "STATEBUS_KV_API_BASE_URL": base_url,
        "STATEBUS_ENGINE_LOCAL_KV_MODEL": args.model,
        "STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS": str(args.parent_tokens),
        "STATEBUS_PREFIX_ALIGNMENT_MODE": "shared_evidence_prefix",
        "STATEBUS_ROUTE_HINTS_ENABLED": "1",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _run_lane(mode: str, *, output_dir: Path, document: Path) -> dict[str, object]:
    os.environ["STATEBUS_ENGINE_LOCAL_KV_MODE"] = mode
    lane_root = output_dir / mode
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="extract_metric_series_generic",
        target_entities=("Nova Retail Logistics",),
        time_scope="2026Q1-2026Q3",
        required_outputs=(
            "metric_series_ref",
            "metric_name",
            "value_q1",
            "value_q2",
            "value_q3",
        ),
        required_tools=("table_retriever",),
        arguments={
            "dataset_id": "nova_retail_ops_2026",
            "document_path": str(document.resolve()),
            "metric": "revenue_musd",
            "quarters": ["2026Q1", "2026Q2", "2026Q3"],
        },
    )
    started_ns = time.perf_counter_ns()
    result = run_smoke(
        workspace_root=lane_root / "workspace",
        runtime_root=lane_root / "runtime",
        socket_path=lane_root / "runtime.sock",
        request_text=(
            "Analyze the Nova operating report and extract revenue_musd for "
            "2026Q1, 2026Q2, and 2026Q3 through the complete StateBus role chain."
        ),
        canonical_task_spec=spec,
        task_id="kv-mainline-nova-4k",
        layer_config=SmokeLayerConfig(
            role_path_mode="local_vllm",
            embedding_mode="deterministic",
            semantic_pruning_enabled=False,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={
            "metric_name": "revenue_musd",
            "value_q1": "142",
            "value_q2": "156",
            "value_q3": "169",
        },
    )
    mainline_wall_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    audit_path = lane_root / "runtime" / "engine_local_kv_mainline.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    producer = audit["producer_calls"][-1]
    consumer = audit["consumer_calls"][-1]
    producer_telemetry = dict(producer.get("telemetry") or {})
    consumer_telemetry = dict(consumer.get("telemetry") or {})
    output_payload = json.loads(Path(result.output_artifact_path).read_text(encoding="utf-8"))
    record = {
        "mode": mode,
        "mainline_wall_ms": mainline_wall_ms,
        "runtime_root": result.runtime_root,
        "output_artifact_path": result.output_artifact_path,
        "output_artifact_hash": result.output_artifact_hash,
        "output_payload_digest": sha256_digest(output_payload),
        "quality_floor": asdict(result.quality_floor),
        "quality_floor_pass": result.quality_floor.quality_floor_pass,
        "session_state": result.session_state,
        "workflow_step_count": result.workflow_step_count,
        "completed_workflow_step_count": result.completed_workflow_step_count,
        "attempt_count": result.attempt_count,
        "consumer_lane": consumer["lane"],
        "parent_tokens": consumer["parent_tokens"],
        "suffix_tokens": consumer["suffix_tokens"],
        "logical_prompt_tokens": consumer["logical_prompt_tokens"],
        "computed_prefill_tokens": int(consumer_telemetry.get("computed_prefill_tokens", 0)),
        "inherited_kv_tokens": int(consumer_telemetry.get("inherited_kv_tokens", 0)),
        "consumer_ttft_ms": float(consumer["client_ttft_ms"]),
        "consumer_wall_ms": float(consumer["client_wall_ms"]),
        "consumer_request_bytes": int(consumer["api_request_bytes"]),
        "consumer_output_token_digest": consumer["output_token_digest"],
        "consumer_output_text_digest": consumer["output_text_digest"],
        "producer_output_token_digest": producer["output_token_digest"],
        "producer_logical_token_digest": producer["logical_token_digest"],
        "consumer_logical_token_digest": consumer["logical_token_digest"],
        "kv_store_ms": float(producer_telemetry.get("kv_store_ms", 0.0)),
        "kv_load_ms": float(consumer_telemetry.get("kv_load_ms", 0.0)),
        "kv_bytes_actual": int(consumer_telemetry.get("kv_bytes_actual", 0)),
        "connector_load_count": int(consumer_telemetry.get("connector_load_count", 0)),
        "capture_count": int(audit["capture_count"]),
        "load_count": int(audit["load_count"]),
        "fallback_count": int(audit["fallback_count"]),
        "release_calls": list(audit["release_calls"]),
        "audit_path": str(audit_path),
    }
    (lane_root / "record.json").write_text(
        json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def _summarize(
    *,
    run_id: str,
    output_dir: Path,
    records: list[dict[str, object]],
) -> dict[str, object]:
    summary: dict[str, object] = {
        "schema_version": "statebus.engine_local_kv_mainline_ab.v1",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "serialized": True,
        "repeat_count": 1,
        "records": records,
    }
    if len(records) != 2:
        return summary
    by_mode = {str(record["mode"]): record for record in records}
    baseline = by_mode["full_replay"]
    continuation = by_mode["continuation"]
    summary["comparison"] = {
        "consumer_ttft_reduction": _reduction(
            float(baseline["consumer_ttft_ms"]), float(continuation["consumer_ttft_ms"])
        ),
        "consumer_wall_reduction": _reduction(
            float(baseline["consumer_wall_ms"]), float(continuation["consumer_wall_ms"])
        ),
        "computed_prefill_reduction": _reduction(
            float(baseline["computed_prefill_tokens"]),
            float(continuation["computed_prefill_tokens"]),
        ),
        "consumer_request_bytes_reduction": _reduction(
            float(baseline["consumer_request_bytes"]),
            float(continuation["consumer_request_bytes"]),
        ),
        "mainline_wall_reduction": _reduction(
            float(baseline["mainline_wall_ms"]), float(continuation["mainline_wall_ms"])
        ),
        "producer_logical_token_digest_equal": (
            baseline["producer_logical_token_digest"]
            == continuation["producer_logical_token_digest"]
        ),
        "consumer_logical_token_digest_equal": (
            baseline["consumer_logical_token_digest"]
            == continuation["consumer_logical_token_digest"]
        ),
        "producer_output_token_digest_equal": (
            baseline["producer_output_token_digest"]
            == continuation["producer_output_token_digest"]
        ),
        "consumer_output_token_digest_equal": (
            baseline["consumer_output_token_digest"]
            == continuation["consumer_output_token_digest"]
        ),
        "output_artifact_hash_equal": (
            baseline["output_artifact_hash"] == continuation["output_artifact_hash"]
        ),
        "quality_floor_equal": baseline["quality_floor"] == continuation["quality_floor"],
    }
    return summary


def _reduction(baseline: float, candidate: float) -> float:
    return 0.0 if baseline <= 0 else (baseline - candidate) / baseline


if __name__ == "__main__":
    raise SystemExit(main())
