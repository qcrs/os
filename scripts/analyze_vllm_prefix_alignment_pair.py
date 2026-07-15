#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2.utils import stable_json_dumps


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare one serialized shared-prefix/independent vLLM probe pair."
    )
    parser.add_argument("--shared", type=Path, required=True)
    parser.add_argument("--independent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def analyze_pair(shared: dict[str, object], independent: dict[str, object]) -> dict[str, object]:
    shared_summary = dict(shared.get("summary", {}))
    independent_summary = dict(independent.get("summary", {}))
    compatibility = {
        "model_equal": shared.get("model") == independent.get("model"),
        "evidence_file_equal": shared.get("evidence_file") == independent.get("evidence_file"),
        "evidence_sha256_equal": shared.get("evidence_sha256") == independent.get("evidence_sha256"),
        "evidence_repeat_equal": shared.get("evidence_repeat") == independent.get("evidence_repeat"),
        "evidence_bytes_equal": shared.get("evidence_bytes") == independent.get("evidence_bytes"),
        "run_salt_equal": shared.get("run_salt") == independent.get("run_salt"),
        "request_count_equal": shared_summary.get("request_count")
        == independent_summary.get("request_count"),
        "roles_equal": shared.get("roles") == independent.get("roles"),
        "generation_config_equal": (
            shared.get("max_tokens"),
            shared.get("temperature"),
            shared.get("response_format"),
        )
        == (
            independent.get("max_tokens"),
            independent.get("temperature"),
            independent.get("response_format"),
        ),
        "all_requests_ok": (
            shared_summary.get("request_count") == shared_summary.get("ok_count")
            and independent_summary.get("request_count") == independent_summary.get("ok_count")
        ),
        "all_completion_contracts_valid": (
            shared_summary.get("request_count")
            == shared_summary.get("completion_contract_valid_count")
            and independent_summary.get("request_count")
            == independent_summary.get("completion_contract_valid_count")
        ),
    }
    pair_valid = all(compatibility.values())
    shared_warm_ttft = float(shared_summary.get("warm_candidate_mean_ttft_ms", 0.0) or 0.0)
    independent_warm_ttft = float(
        independent_summary.get("warm_candidate_mean_ttft_ms", 0.0) or 0.0
    )
    shared_warm_latency = float(
        shared_summary.get("warm_candidate_mean_latency_ms", 0.0) or 0.0
    )
    independent_warm_latency = float(
        independent_summary.get("warm_candidate_mean_latency_ms", 0.0) or 0.0
    )
    counter_delta_available = (
        int(shared_summary.get("counter_delta_valid_request_count", 0) or 0) > 0
        and int(independent_summary.get("counter_delta_valid_request_count", 0) or 0) > 0
    )
    return {
        "schema_version": "statebus.vllm_prefix_alignment_pair_analysis.v1",
        "ok": pair_valid,
        "claim_level": "single_repeat_serialized_mechanism_probe",
        "claim_boundary": (
            "engine_local_prefix_layout_latency_observation_only; no hidden-state or KV tensor transfer; "
            "one pair cannot establish stable causal latency benefit"
        ),
        "compatibility": compatibility,
        "counter_delta_available": counter_delta_available,
        "counter_claim_allowed": counter_delta_available,
        "latency_observation": {
            "shared_warm_mean_ttft_ms": shared_warm_ttft,
            "independent_warm_mean_ttft_ms": independent_warm_ttft,
            "shared_minus_independent_warm_ttft_ms": shared_warm_ttft - independent_warm_ttft,
            "shared_warm_ttft_reduction_ratio_vs_independent": (
                (independent_warm_ttft - shared_warm_ttft) / independent_warm_ttft
                if independent_warm_ttft > 0.0
                else None
            ),
            "shared_warm_mean_latency_ms": shared_warm_latency,
            "independent_warm_mean_latency_ms": independent_warm_latency,
            "shared_minus_independent_warm_latency_ms": (
                shared_warm_latency - independent_warm_latency
            ),
            "shared_faster_in_this_pair": (
                pair_valid
                and shared_warm_ttft > 0.0
                and shared_warm_ttft < independent_warm_ttft
            ),
        },
        "required_next_evidence": [
            "alternating serialized repeat pairs with order randomization",
            "quality-equivalent responses",
            "exclusive or contamination-audited vLLM service window",
            "explicit query/hit counters or an engine version that exposes them",
        ],
    }


def main() -> int:
    args = _parser().parse_args()
    shared = json.loads(args.shared.read_text(encoding="utf-8"))
    independent = json.loads(args.independent.read_text(encoding="utf-8"))
    payload = analyze_pair(shared, independent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
