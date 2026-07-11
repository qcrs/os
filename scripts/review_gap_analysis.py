#!/usr/bin/env python3
"""
Gap analysis script: extract data points NOT yet covered in plan documents.
Focus areas:
1. Per-role completion token distribution (infer from prompt slices)
2. External baseline prompt construction (check fairness of evidence sharing)
3. Route selection stability across families
4. Memory/replay actual reuse paths vs declared contracts
5. CodeAct latency isolation
"""
import json
import os
from pathlib import Path
from collections import defaultdict

BASE_RUN = Path("/home/qcrs/statebus/runs/sb2-gpu1-20260708_084458")
SUPPLEMENT_RUN = Path("/home/qcrs/statebus/runs/sb2-gpu1-health-20260708_110413")


def analyze_formal_compare_per_family_latency():
    """Extract per-family latency breakdown from formal compare."""
    compare_dir = BASE_RUN / "work/r01_07_formal_compare_api_local_memfd"
    report_pattern = "runtime/benchmark_reports/*cold-start-compare*.json"
    reports = list(compare_dir.glob(report_pattern))
    if not reports:
        print("[WARN] No formal compare report found")
        return {}
    report = json.loads(reports[0].read_text())
    results = {}
    for mode_report in report.get("mode_reports", []):
        if mode_report.get("role_path_mode") != "api":
            continue
        sb_cases = mode_report.get("statebus_report", {}).get("cases", [])
        ext_cases = mode_report.get("external_report", {}).get("cases", [])
        # Build per-family stats
        family_stats = defaultdict(lambda: {"sb_task_ms": 0, "ext_task_ms": 0, "count": 0,
                                            "sb_completion": 0, "ext_completion": 0,
                                            "sb_prompt": 0, "ext_prompt": 0})
        for case in sb_cases:
            fam = case.get("task_family", "unknown")
            metrics = case.get("metrics", {})
            family_stats[fam]["sb_task_ms"] += metrics.get("task_ms", 0)
            family_stats[fam]["sb_completion"] += metrics.get("completion_tokens", 0)
            family_stats[fam]["sb_prompt"] += metrics.get("prompt_tokens", 0)
            family_stats[fam]["count"] += 1
        for case in ext_cases:
            fam = case.get("task_family", "unknown")
            metrics = case.get("metrics", {})
            family_stats[fam]["ext_task_ms"] += metrics.get("end_to_end_ms", metrics.get("task_ms", 0))
            family_stats[fam]["ext_completion"] += metrics.get("completion_tokens", 0)
            family_stats[fam]["ext_prompt"] += metrics.get("prompt_tokens", 0)
        results = dict(family_stats)
    return results


def analyze_role_prompt_sizes():
    """Check StateBus vs external per-role prompt byte distribution in carrier compare."""
    carrier_dir = BASE_RUN / "work/r01_06_formal_carrier_compare_api_local_memfd"
    report_pattern = "runtime/benchmark_reports/*carrier*.json"
    reports = list(carrier_dir.glob(report_pattern))
    if not reports:
        # Try alternative pattern
        reports = list(carrier_dir.glob("runtime/benchmark_reports/*.json"))

    role_data = {}
    # Look at prompt slices to understand role distribution
    prompt_dir = carrier_dir / "runtime"
    for subdir in ("statebus", "external"):
        target = carrier_dir / "api" / subdir
        if not target.exists():
            target = carrier_dir / subdir
        if not target.exists():
            continue
        slices = list(target.rglob("*prompt_slice*.json"))
        for s in slices[:5]:  # Sample first 5
            try:
                data = json.loads(s.read_text())
                role = data.get("role", "unknown")
                key = f"{subdir}_{role}"
                if key not in role_data:
                    role_data[key] = {"count": 0, "total_bytes": 0}
                role_data[key]["count"] += 1
                role_data[key]["total_bytes"] += len(s.read_text())
            except Exception:
                pass
    return role_data


def analyze_continuous_reuse_depth():
    """Check continuous replay - how many rounds actually skip LLM calls."""
    continuous_dir = BASE_RUN / "work/r01_11_continuous_replay_api_local"
    report_pattern = "runtime/benchmark_reports/*continuous-replay*.json"
    reports = list(continuous_dir.glob(report_pattern))
    if not reports:
        print("[WARN] No continuous replay report found")
        return {}
    report = json.loads(reports[0].read_text())

    results = {}
    families = report.get("family_reports", [])
    for fam in families:
        fam_id = fam.get("family_id", "unknown")
        rounds = fam.get("rounds", [])
        skipped_rounds = []
        validated_rounds = []
        cold_rounds = []
        for r in rounds:
            round_num = r.get("round", 0)
            replay_class = r.get("replay_class", "cold_start")
            skipped = r.get("skipped_step_count", 0)
            if replay_class == "exact_replay":
                skipped_rounds.append(round_num)
            elif replay_class == "validated_replay":
                validated_rounds.append(round_num)
            else:
                cold_rounds.append(round_num)
        results[fam_id] = {
            "total_rounds": len(rounds),
            "exact_replay_rounds": skipped_rounds,
            "validated_replay_rounds": validated_rounds,
            "cold_start_rounds": cold_rounds,
        }
    return results


def analyze_codeact_timing_isolation():
    """Extract CodeAct stage timing to understand its contribution to latency."""
    # Read from telemetry
    telemetry_dir = BASE_RUN / "work/r01_07_formal_compare_api_local_memfd"
    events_pattern = "runtime/**/runtime_events.jsonl"
    codeact_events = []

    for events_file in telemetry_dir.rglob("runtime_events.jsonl"):
        try:
            for line in events_file.read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if "codeact" in str(event.get("stage", "")).lower():
                    codeact_events.append(event)
        except Exception:
            pass

    total_codeact_ms = sum(e.get("duration_ms", 0) for e in codeact_events)
    return {
        "codeact_event_count": len(codeact_events),
        "total_codeact_ms": total_codeact_ms,
    }


def analyze_external_baseline_evidence_access():
    """Check what evidence the external baseline actually sees."""
    compare_dir = BASE_RUN / "work/r01_07_formal_compare_api_local_memfd"
    ext_dir = compare_dir / "api" / "external"
    if not ext_dir.exists():
        # Try direct workspace path
        ext_candidates = list(compare_dir.rglob("external"))
        ext_dir = ext_candidates[0] if ext_candidates else None

    if not ext_dir or not ext_dir.exists():
        print("[WARN] External output dir not found")
        return {}

    # Find case output files
    case_files = list(ext_dir.rglob("*output*.json"))[:5]
    evidence_stats = {}
    for cf in case_files:
        try:
            data = json.loads(cf.read_text())
            task_id = data.get("task_id", cf.stem)
            evidence_stats[task_id] = {
                "has_evidence_summary": "evidence_summary" in data or "evidence" in str(data),
                "output_keys": list(data.keys())[:10],
            }
        except Exception:
            pass
    return evidence_stats


def analyze_formal_trend_002_route_detail():
    """Deep-dive into the formal-trend-002 route miss."""
    carrier_dir = BASE_RUN / "work/r01_06_formal_carrier_compare_api_local_memfd"

    # Find structured and text outputs for formal-trend-002
    results = {}
    for lane in ("structured", "text", "statebus"):
        lane_files = list(carrier_dir.rglob(f"*formal-trend-002*"))
        for f in lane_files:
            if f.suffix == ".json":
                try:
                    data = json.loads(f.read_text())
                    route = data.get("route", data.get("selected_route", ""))
                    tool = data.get("tool_name", data.get("selected_tool", ""))
                    if route or tool:
                        results[f"{f.parent.name}/{f.name}"] = {
                            "route": route,
                            "tool_name": tool,
                            "action_contract": data.get("action_contract", ""),
                        }
                except Exception:
                    pass
    return results


def check_kv_prefix_schedule_actual_vs_declared():
    """Verify KV prefix schedule hints match manifest declarations."""
    kv_dir = SUPPLEMENT_RUN / "work/s01_08_kv_prefix_demo_api_local"
    report_pattern = "runtime/benchmark_reports/*.json"
    reports = list(kv_dir.glob(report_pattern))

    if not reports:
        print("[WARN] No KV prefix demo report found")
        return {}

    results = {}
    for rp in reports[:2]:
        try:
            data = json.loads(rp.read_text())
            # Extract KV-specific metrics
            results[rp.name] = {
                "has_kv_metrics": any("kv" in k.lower() for k in data.keys()),
                "top_keys": list(data.keys())[:15],
            }
        except Exception:
            pass
    return results


def main():
    print("=" * 70)
    print("StateBus v2 Gap Analysis - Supplementary Data Collection")
    print("=" * 70)

    print("\n## 1. Per-Family Latency in Formal External Compare")
    family_latency = analyze_formal_compare_per_family_latency()
    if family_latency:
        print(f"| {'Family':<35} | {'SB ms':>8} | {'Ext ms':>8} | {'Delta':>8} | {'SB compl':>8} | {'Ext compl':>8} |")
        print(f"|{'-'*35}:|{'-'*8}:|{'-'*8}:|{'-'*8}:|{'-'*8}:|{'-'*8}:|")
        for fam, stats in sorted(family_latency.items()):
            delta = stats["sb_task_ms"] - stats["ext_task_ms"]
            print(f"| {fam:<35} | {stats['sb_task_ms']:>8.0f} | {stats['ext_task_ms']:>8.0f} | {delta:>+8.0f} | {stats['sb_completion']:>8.0f} | {stats['ext_completion']:>8.0f} |")
    else:
        print("  [No data - report structure may differ]")

    print("\n## 2. Continuous Replay Reuse Depth")
    reuse_depth = analyze_continuous_reuse_depth()
    for fam_id, data in reuse_depth.items():
        print(f"\n  Family: {fam_id}")
        print(f"    Total rounds: {data['total_rounds']}")
        print(f"    Exact replay rounds: {data['exact_replay_rounds']}")
        print(f"    Validated replay rounds: {data['validated_replay_rounds']}")
        print(f"    Cold start rounds: {data['cold_start_rounds']}")

    print("\n## 3. CodeAct Timing Isolation")
    codeact = analyze_codeact_timing_isolation()
    print(f"  Events: {codeact.get('codeact_event_count', 0)}")
    print(f"  Total ms: {codeact.get('total_codeact_ms', 0):.1f}")

    print("\n## 4. formal-trend-002 Route Detail")
    route_detail = analyze_formal_trend_002_route_detail()
    for path, info in route_detail.items():
        print(f"  {path}: route={info['route']} tool={info['tool_name']} action={info['action_contract']}")

    print("\n## 5. KV Prefix Schedule vs Declared")
    kv_check = check_kv_prefix_schedule_actual_vs_declared()
    for name, info in kv_check.items():
        print(f"  {name}: has_kv={info['has_kv_metrics']}, keys={info['top_keys'][:8]}")

    print("\n## 6. External Baseline Evidence Access")
    ext_evidence = analyze_external_baseline_evidence_access()
    for task_id, info in ext_evidence.items():
        print(f"  {task_id}: has_evidence={info['has_evidence_summary']}, keys={info['output_keys'][:6]}")

    print("\n" + "=" * 70)
    print("Analysis complete.")


if __name__ == "__main__":
    main()
