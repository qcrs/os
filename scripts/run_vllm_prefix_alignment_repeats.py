#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze_vllm_prefix_alignment_pair import analyze_pair  # noqa: E402
from scripts.probe_local_vllm_prefix_alignment import DEFAULT_EVIDENCE_FILE  # noqa: E402
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
    parser.add_argument(
        "--evidence-file",
        action="append",
        type=Path,
        default=None,
        help="repeatable evidence corpus path; repeat pairs rotate through supplied files",
    )
    parser.add_argument(
        "--clean-service-command",
        default="",
        help="optional user-supplied command run before each pair; the runner never assumes a Docker restart",
    )
    parser.add_argument("--clean-service-timeout-s", type=float, default=180.0)
    parser.add_argument("--service-ready-attempts", type=int, default=60)
    parser.add_argument("--service-ready-interval-s", type=float, default=2.0)
    return parser


def _repeat_salt(repeat_index: int) -> str:
    # Both modes receive byte-identical evidence/payload content within a pair.
    return f"r{repeat_index:02d}-a{repeat_index:06d}"


def _run_probe(
    args: argparse.Namespace,
    *,
    repeat_index: int,
    mode: str,
    evidence_file: Path,
    output: Path,
) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/probe_local_vllm_prefix_alignment.py"),
        "--mode",
        mode,
        "--run-salt",
        _repeat_salt(repeat_index),
        "--evidence-file",
        str(evidence_file),
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


def _fetch_service_health(health_url: str, *, timeout_s: float = 10.0) -> dict[str, object]:
    try:
        with urlopen(health_url, timeout=timeout_s) as response:  # nosec B310 - caller supplies local service endpoint.
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "error": "",
            }
    except Exception as exc:  # noqa: BLE001 - evidence must retain service readiness failures.
        return {"ok": False, "status_code": None, "error": f"{type(exc).__name__}: {exc}"}


def _service_baseline(metrics_url: str) -> dict[str, object]:
    try:
        with urlopen(metrics_url, timeout=10.0) as response:  # nosec B310 - caller supplies local service endpoint.
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "body_bytes": len(body.encode("utf-8")),
                "error": "",
            }
    except Exception as exc:  # noqa: BLE001 - evidence must retain service baseline failures.
        return {"ok": False, "status_code": None, "body_sha256": "", "body_bytes": 0, "error": f"{type(exc).__name__}: {exc}"}


def _prepare_clean_service(args: argparse.Namespace) -> dict[str, object]:
    baseline = _service_baseline(args.metrics_url)
    command = args.clean_service_command.strip()
    record: dict[str, object] = {
        "requested": bool(command),
        "command": command,
        "metrics_before_clean": baseline,
        "command_returncode": None,
        "command_stdout": "",
        "command_stderr": "",
        "ready": not command,
        "health_after_clean": _fetch_service_health(args.health_url),
        "ready_attempt_count": 0,
    }
    if not command:
        return record
    try:
        completed = subprocess.run(
            ["bash", "-lc", command],
            check=False,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=args.clean_service_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        record["command_returncode"] = None
        record["command_stderr"] = f"TimeoutExpired: {exc}"
        return record
    record["command_returncode"] = completed.returncode
    record["command_stdout"] = completed.stdout[-2000:]
    record["command_stderr"] = completed.stderr[-2000:]
    if completed.returncode != 0:
        return record
    for attempt in range(1, args.service_ready_attempts + 1):
        health = _fetch_service_health(args.health_url)
        record["health_after_clean"] = health
        record["ready_attempt_count"] = attempt
        if health["ok"]:
            record["ready"] = True
            return record
        if attempt < args.service_ready_attempts:
            time.sleep(args.service_ready_interval_s)
    return record


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


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
    clean_records = [dict(pair["clean_service"]) for pair in pairs]
    clean_service_requested = any(bool(record.get("requested")) for record in clean_records)
    clean_service_all_ready = all(
        (not bool(record.get("requested")))
        or (record.get("command_returncode") == 0 and bool(record.get("ready")))
        for record in clean_records
    )
    evidence_files = sorted({str(pair["evidence_file"]) for pair in pairs})
    all_completion_contracts_valid = all(
        int(run.get("completion_contract_valid_count", 0)) == int(run.get("request_count", -1))
        for run in [*shared_runs, *independent_runs]
    )
    ok = all_pair_gates_pass and both_orders_present and all_completion_contracts_valid and clean_service_all_ready
    return {
        "schema_version": "statebus.vllm_prefix_alignment_repeats.v2",
        "ok": ok,
        "claim_level": "serialized_alternating_order_repeated_mechanism_probe",
        "claim_boundary": (
            "engine-local vLLM block-query/block-hit counters and TTFT only; "
            "no hidden-state or KV tensor transfer; not an end-to-end workload speedup claim"
        ),
        "service_window": (
            "clean_service_between_pairs"
            if clean_service_requested
            else "continuous_service_between_pairs"
        ),
        "repeat_count": len(pairs),
        "orders": orders,
        "both_orders_present": both_orders_present,
        "all_pair_gates_pass": all_pair_gates_pass,
        "all_counter_deltas_valid": all_counter_deltas_valid,
        "counter_claim_allowed": all_counter_deltas_valid,
        "all_completion_contracts_valid": all_completion_contracts_valid,
        "evidence_files": evidence_files,
        "evidence_file_count": len(evidence_files),
        "clean_service_requested": clean_service_requested,
        "clean_service_all_ready": clean_service_all_ready,
        "shared": {
            "queries": shared_queries,
            "hits": shared_hits,
            "hit_rate": shared_hits / shared_queries if shared_queries else None,
            "warm_ttft_mean_ms": statistics.mean(shared_ttft),
            "warm_ttft_median_ms": statistics.median(shared_ttft),
            "warm_ttft_p95_ms": _percentile(shared_ttft, 0.95),
        },
        "independent": {
            "queries": independent_queries,
            "hits": independent_hits,
            "hit_rate": independent_hits / independent_queries if independent_queries else None,
            "warm_ttft_mean_ms": statistics.mean(independent_ttft),
            "warm_ttft_median_ms": statistics.median(independent_ttft),
            "warm_ttft_p95_ms": _percentile(independent_ttft, 0.95),
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
                "evidence_file": str(pair["evidence_file"]),
                "clean_service": pair["clean_service"],
            }
            for pair in pairs
        ],
    }


def main() -> int:
    args = _parser().parse_args()
    if args.repeats < 2:
        raise SystemExit("--repeats must be >= 2 to exercise both run orders")
    if args.service_ready_attempts < 1:
        raise SystemExit("--service-ready-attempts must be >= 1")
    evidence_files = tuple(args.evidence_file or [DEFAULT_EVIDENCE_FILE])
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
        evidence_file = evidence_files[(repeat_index - 1) % len(evidence_files)]
        clean_service = _prepare_clean_service(args)
        if clean_service["requested"] and not clean_service["ready"]:
            raise SystemExit(f"clean service did not become ready for repeat {repeat_index}: {clean_service}")
        for mode in modes:
            output_name = "shared.json" if mode == "shared_evidence_prefix" else "independent.json"
            _run_probe(
                args,
                repeat_index=repeat_index,
                mode=mode,
                evidence_file=evidence_file,
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
                "evidence_file": evidence_file,
                "clean_service": clean_service,
            }
        )
    summary = _aggregate(pairs)
    summary_path = args.output_root / "repeat_summary.json"
    summary_path.write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    print(summary_path)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
