#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.runtime.kv_budget import estimate_kv_cache_footprint, format_gib, load_kv_cache_model_profile
from v2.utils import stable_json_dumps


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate model KV-cache footprint from local HF config.")
    parser.add_argument("model_path", type=Path)
    parser.add_argument("--prompt-tokens", type=int, default=8192)
    parser.add_argument("--max-output-tokens", type=int, default=0)
    parser.add_argument("--dtype-bytes", type=int, default=2, help="bf16/fp16=2, fp8=1")
    parser.add_argument("--target-dtype-bytes", type=int, default=1, help="target KV dtype for savings estimate")
    parser.add_argument("--usable-kv-cache-gib", type=float, default=0.0)
    args = parser.parse_args()

    profile = load_kv_cache_model_profile(args.model_path, dtype_bytes=args.dtype_bytes)
    estimate = estimate_kv_cache_footprint(
        profile,
        prompt_tokens=args.prompt_tokens,
        max_output_tokens=args.max_output_tokens,
        target_dtype_bytes=args.target_dtype_bytes,
        usable_kv_cache_bytes=int(args.usable_kv_cache_gib * 1024 * 1024 * 1024),
    )
    payload = estimate.canonical_payload()
    payload["human_readable"] = {
        "kv_bytes_per_token_kib": profile.kv_bytes_per_token / 1024.0,
        "prefill_kv_gib": format_gib(estimate.prefill_kv_bytes),
        "total_sequence_kv_gib": format_gib(estimate.total_sequence_kv_bytes),
        "target_dtype_total_sequence_kv_gib": format_gib(
            estimate.target_dtype_total_sequence_kv_bytes
        ),
        "target_dtype_savings_gib": format_gib(estimate.target_dtype_savings_bytes),
    }
    print(stable_json_dumps(payload))


if __name__ == "__main__":
    main()
