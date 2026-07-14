#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze_vllm_prefix_alignment_pair import analyze_pair  # noqa: E402
from v2.utils import stable_json_dumps  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run alternating serialized vLLM shared/independent prefix probes."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--health-url", default="http://127.0.0.1:53334/health")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:53334/metrics")
    parser.add_argument("--model", default="qwen3-32b")
    return parser


def _mode_salt(repeat_index: int, mode: str) -> str:
    mode_code = "shared" if mode == "shared_evidence_prefix" else "indep0"
    return f"r{repeat_index:02d}-{mode_code}-a{repeat_index:06d}"


def _run_probe(args, *, repeat_index: int, mode: str, output: Path) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/probe_local_vllm_prefix_alignment.py"),
        "--mode",
        mode,
        "--run-salt",
        _mode_salt(repeat_index, mode),
        "--max-tokens",
        str(args.max_tokens),
        "--base-url",
        args.base_url,
        "--health-url",
        args.health_url,
        "--metrics-url",
        args.metrics_url,
        "--model",
        args.model,
        "--output-json",
        str(output),
    ]
    subprocess.run(command, check=True, cwd=REPO_ROOT, capture_output=True, text=True)


def _aggregate(pairs: list[dict[str, object]]) -> dict[str, object]:
    shared_runs = [dict(pair["shared"]["summary"]) for pair in pairs]
    independent_runs = [dict(pair["independent"]["summary"]) for pair in pairs]
    shared_queries = sum(float(run["counter_delta_queries"]) for run in shared_runs)
    shared_hits = sum(float(run["counter_delta_hits"]) for run in shared_runs)
    independent_queries = sum(float(run["counter_delta_queries"]) for run in independent_runs)
    independent_hits = sum(float(run["counter_delta_hits"]) for run in independent_runs)
    shared_ttft = [float(run["warm_candidate_mean_ttft_ms"]) for run in shared_runs]
    independent_ttft = [
        float(run["warm_candidate_mean_ttft_ms"]) for run in independent_runs
    ]
    pair_differences = [left - right for left, right in zip(shared_ttft, independent_ttft)]
    orders = [str(pair["order"]) for pair in pairs]
    pair_reports = [dict(pair["analysis"]) for pair in pairs]
    all_pair_gates_pass = bool(pair_reports) and all(
        bool(report.get("ok")) for report in pair_reports
    )
    both_orders_present = {"shared_first", "independent_first"}.issubset(set(orders))
    all_counter_deltas_valid = all(
        int(run.get("counter_delta_valid_request_count", 0))
        == int(run.get("request_count", -1))
        for run in [*shared_runs, *independent_runs]
    )
    ok = all_pair_gates_pass and both_orders_present and all_counter_deltas_valid
    return {
        "schema_version": "statebus.vllm_prefix_alignment_repeats.v1",
        "ok": ok,
        "claim_level": "serialized_alternating_order_repeated_mechanism_probe",
        "claim_boundary": (
            "engine-local vLLM block-query/block-hit counters and TTFT only; "
            "no hidden-state or KV tensor transfer; not an end-to-end workload speedup claim"
        ),
        "repeat_count": len(pairs),
        "orders": orders,
        "both_orders_present": both_orders_present,
        "all_pair_gates_pass": all_pair_gates_pass,
        "all_counter_deltas_valid": all_counter_deltas_valid,
        "shared": {
            "queries": shared_queries,
            "hits": shared_hits,
            "hit_rate": shared_hits / shared_queries if shared_queries else None,
            "warm_ttft_mean_ms": statistics.mean(shared_ttft),
            "warm_ttft_median_ms": statistics.median(shared_ttft),
        },
        "independent": {
            "queries": independent_queries,
            "hits": independent_hits,
            "hit_rate": independent_hits / independent_queries if independent_queries else None,
            "warm_ttft_mean_ms": statistics.mean(independent_ttft),
            "warm_ttft_median_ms": statistics.median(independent_ttft),
        },
        "paired_ttft": {
            "shared_minus_independent_mean_ms": statistics.mean(pair_differences),
            "shared_minus_independent_median_ms": statistics.median(pair_differences),
            "shared_faster_pair_count": sum(value < 0.0 for value in pair_differences),
        },
        "pairs": [
            {
                "repeat_index": pair["repeat_index"],
                "order": pair["order"],
                "analysis_path": pair["analysis_path"],
            }
            for pair in pairs
        ],
    }


def main() -> int:
    args = _parser().parse_args()
    if args.repeats < 2:
        raise SystemExit("--repeats must be >= 2 to exercise both run orders")
    args.output_root.mkdir(parents=True, exist_ok=True)
    pairs: list[dict[str, object]] = []
    for repeat_index in range(1, args.repeats + 1):
        repeat_root = args.output_root / f"repeat{repeat_index:02d}"
        repeat_root.mkdir(parents=True, exist_ok=True)
        modes = (
            ("shared_evidence_prefix", "independent")
            if repeat_index % 2
            else ("independent", "shared_evidence_prefix")
        )
        for mode in modes:
            output_name = "shared.json" if mode == "shared_evidence_prefix" else "independent.json"
            _run_probe(
                args,
                repeat_index=repeat_index,
                mode=mode,
                output=repeat_root / output_name,
            )
        shared = json.loads((repeat_root / "shared.json").read_text(encoding="utf-8"))
        independent = json.loads(
            (repeat_root / "independent.json").read_text(encoding="utf-8")
        )
        analysis = analyze_pair(shared, independent)
        analysis_path = repeat_root / "pair_summary.json"
        analysis_path.write_text(stable_json_dumps(analysis) + "\n", encoding="utf-8")
        pairs.append(
            {
                "repeat_index": repeat_index,
                "order": "shared_first" if modes[0] == "shared_evidence_prefix" else "independent_first",
                "shared": shared,
                "independent": independent,
                "analysis": analysis,
                "analysis_path": str(analysis_path),
            }
        )
    summary = _aggregate(pairs)
    summary_path = args.output_root / "repeat_summary.json"
    summary_path.write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    print(summary_path)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

