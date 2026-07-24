#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.contracts import CanonicalTaskSpec  # noqa: E402
from v2.retrieval import RetrieverFanoutPipeline  # noqa: E402
from v2.retrieval.models import RetrievalBundle  # noqa: E402
from v2.retrieval.pruning import DynamicPruningConfig  # noqa: E402
from v2.utils import stable_json_dumps  # noqa: E402


DEFAULT_OUTPUT = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/"
    "e3_dynamic_pruning_ablation_20260711.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe dynamic evidence pruning on/off.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--available-kv-cache-bytes", type=int, default=20_000)
    parser.add_argument("--kv-bytes-per-token", type=int, default=256)
    parser.add_argument("--base-threshold", type=float, default=0.6)
    parser.add_argument("--capacity-buffer", type=float, default=0.2)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
    )
    baseline = _run_pipeline(
        task_id="e3-dynamic-pruning-off",
        spec=spec,
        top_k=args.top_k,
        dynamic_config=DynamicPruningConfig(enabled=False),
    )
    enabled = _run_pipeline(
        task_id="e3-dynamic-pruning-on",
        spec=spec,
        top_k=args.top_k,
        dynamic_config=DynamicPruningConfig(
            enabled=True,
            available_kv_cache_bytes=args.available_kv_cache_bytes,
            kv_bytes_per_token=args.kv_bytes_per_token,
            base_threshold=args.base_threshold,
            capacity_buffer=args.capacity_buffer,
            min_keep_semantic_contexts=1,
            min_keep_lexical_hints=0,
        ),
    )

    baseline_payload = _bundle_payload(baseline)
    enabled_payload = _bundle_payload(enabled)
    quality_proxy = _quality_proxy(baseline=baseline, enabled=enabled)
    payload = {
        "schema_version": "statebus.e3_dynamic_pruning_ablation.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": (
            "input_level_evidence_pruning_only_no_model_internal_kv_tensor_pruning; "
            "deterministic retrieval-level mechanism probe not formal guard"
        ),
        "task_spec": spec.canonical_payload(),
        "controls": {
            "embedding_mode": "deterministic",
            "top_k": args.top_k,
            "available_kv_cache_bytes_on": args.available_kv_cache_bytes,
            "kv_bytes_per_token_on": args.kv_bytes_per_token,
            "base_threshold_on": args.base_threshold,
            "capacity_buffer_on": args.capacity_buffer,
        },
        "baseline_off": baseline_payload,
        "dynamic_on": enabled_payload,
        "delta": {
            "selected_evidence_bytes_on_minus_off": (
                enabled_payload["selected_evidence_bytes"] - baseline_payload["selected_evidence_bytes"]
            ),
            "selected_evidence_tokens_on_minus_off": (
                enabled_payload["pruning_profile"]["selected_evidence_tokens_estimate"]
                - baseline_payload["pruning_profile"]["selected_evidence_tokens_estimate"]
            ),
            "estimated_kv_tokens_saved_on_minus_off": (
                enabled_payload["pruning_profile"]["estimated_kv_tokens_saved"]
                - baseline_payload["pruning_profile"]["estimated_kv_tokens_saved"]
            ),
            "dropped_candidate_count_on_minus_off": (
                enabled_payload["drop_count"] - baseline_payload["drop_count"]
            ),
        },
        "quality_proxy": quality_proxy,
        "primary_result": _primary_result(quality_proxy=quality_proxy, enabled=enabled_payload, baseline=baseline_payload),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    print(args.output_json)
    return 0


def _run_pipeline(
    *,
    task_id: str,
    spec: CanonicalTaskSpec,
    top_k: int,
    dynamic_config: DynamicPruningConfig,
) -> RetrievalBundle:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic", top_k=top_k)
    pipeline.dynamic_pruning_config = dynamic_config
    return pipeline.run(task_id=task_id, spec=spec)


def _bundle_payload(bundle: RetrievalBundle) -> dict[str, Any]:
    profile = bundle.pruning_profile.canonical_payload()
    hints = profile["pruning_hints"]
    keep_count = sum(1 for hint in hints if hint["keep_in_budget"])
    drop_count = len(hints) - keep_count
    return {
        "task_id": bundle.task_id,
        "selected_doc_hashes": list(bundle.selected_doc_hashes),
        "full_corpus_bytes": bundle.full_corpus_bytes,
        "selected_evidence_bytes": bundle.selected_evidence_bytes,
        "candidate_count": len(bundle.candidate_pool.candidates),
        "selected_candidate_ids": list(bundle.pruning_profile.selected_candidate_ids),
        "hard_fact_ids": [item.item_id for item in bundle.evidence_pack.hard_facts],
        "semantic_context_ids": [item.item_id for item in bundle.evidence_pack.semantic_contexts],
        "lexical_hint_ids": [item.item_id for item in bundle.evidence_pack.lexical_hints],
        "structured_evidence_ids": [item.item_id for item in bundle.evidence_pack.structured_evidence],
        "keep_count": keep_count,
        "drop_count": drop_count,
        "dynamic_drop_ids": [
            hint["candidate_id"]
            for hint in hints
            if hint["pruning_class"] == "dynamic_budget_drop"
        ],
        "pruning_profile": profile,
    }


def _quality_proxy(*, baseline: RetrievalBundle, enabled: RetrievalBundle) -> dict[str, Any]:
    baseline_hard_facts = [item.item_id for item in baseline.evidence_pack.hard_facts]
    enabled_hard_facts = [item.item_id for item in enabled.evidence_pack.hard_facts]
    baseline_structured = [item.item_id for item in baseline.evidence_pack.structured_evidence]
    enabled_structured = [item.item_id for item in enabled.evidence_pack.structured_evidence]
    return {
        "proxy_name": "hard_fact_and_structured_evidence_preservation",
        "pass": bool(baseline_hard_facts)
        and baseline_hard_facts == enabled_hard_facts
        and baseline_structured == enabled_structured,
        "baseline_hard_fact_ids": baseline_hard_facts,
        "enabled_hard_fact_ids": enabled_hard_facts,
        "baseline_structured_evidence_ids": baseline_structured,
        "enabled_structured_evidence_ids": enabled_structured,
        "note": "retrieval-level proxy; formal quality floor still requires benchmark guard",
    }


def _primary_result(*, quality_proxy: dict[str, Any], enabled: dict[str, Any], baseline: dict[str, Any]) -> str:
    if not quality_proxy["pass"]:
        return "dynamic_pruning_reduces_context_but_quality_proxy_failed"
    if enabled["drop_count"] <= baseline["drop_count"]:
        return "dynamic_pruning_quality_proxy_passed_but_no_additional_drop"
    if enabled["pruning_profile"]["estimated_kv_tokens_saved"] <= baseline["pruning_profile"]["estimated_kv_tokens_saved"]:
        return "dynamic_pruning_quality_proxy_passed_but_no_estimated_kv_gain"
    return "dynamic_pruning_reduces_prompt_kv_pressure_with_quality_proxy_preserved"


if __name__ == "__main__":
    raise SystemExit(main())
