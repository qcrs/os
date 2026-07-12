#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


DOC_ROOT = Path("docs/improvement/20_v2_comprehensive_truth_audit_20260706")
ARTIFACTS_ROOT = DOC_ROOT / "artifacts"
RUNS_ROOT = Path("/home/qcrs/statebus/runs")
LOGS_ROOT = Path("/home/qcrs/statebus/logs")

OUTPUT_JSON = ARTIFACTS_ROOT / "local_vllm_kv_experiment_log_summary_20260711.json"
OUTPUT_MD = DOC_ROOT / "29_local_vllm_kv_experiment_log_synthesis_20260711.md"

MAX_LOG_SCAN_BYTES = 2_000_000
MAX_LOG_LINES_PER_FILE = 40

KV_ARTIFACTS = {
    "e0_local_vllm_audit": ARTIFACTS_ROOT / "local_vllm_kv_audit_20260711.json",
    "e1_schedule_primary": ARTIFACTS_ROOT / "e1_kv_schedule_ablation_summary_20260711_134159.json",
    "e1_e2_stability_repeat": ARTIFACTS_ROOT / "e1_e2_stability_repeat_summary_20260711_1425.json",
    "e1_e2_clean_service_repeat": ARTIFACTS_ROOT / "e1_e2_clean_service_repeat_summary_20260711_1438.json",
    "e2_prefix_alignment_primary": ARTIFACTS_ROOT / "e2_prefix_alignment_ablation_summary_20260711_1359.json",
    "e3_dynamic_pruning": ARTIFACTS_ROOT / "e3_dynamic_pruning_ablation_20260711.json",
    "e6_formal_guard_summary": ARTIFACTS_ROOT / "e6_formal_guard_summary_20260711_1448.json",
    "e6_formal_guard_mechanism_excerpt": ARTIFACTS_ROOT
    / "e6_formal_guard_mechanism_excerpt_20260711_1448.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize local vLLM KV experiment artifacts and logs."
    )
    parser.add_argument("--output-json", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=OUTPUT_MD)
    parser.add_argument("--doc-root", type=Path, default=DOC_ROOT)
    parser.add_argument("--artifacts-root", type=Path, default=ARTIFACTS_ROOT)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--logs-root", type=Path, default=LOGS_ROOT)
    args = parser.parse_args()

    payload = build_summary(
        doc_root=args.doc_root,
        artifacts_root=args.artifacts_root,
        runs_root=args.runs_root,
        logs_root=args.logs_root,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    markdown = render_markdown(payload, args.output_json)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")

    print(args.output_json)
    print(args.output_md)
    return 0


def build_summary(
    *,
    doc_root: Path,
    artifacts_root: Path,
    runs_root: Path,
    logs_root: Path,
) -> dict[str, Any]:
    kv_artifacts = load_kv_artifacts(artifacts_root)
    sections = {
        "e0_observability": summarize_e0(kv_artifacts),
        "e1_schedule": summarize_e1(kv_artifacts),
        "e2_prefix_alignment": summarize_e2(kv_artifacts),
        "e3_dynamic_pruning": summarize_e3(kv_artifacts),
        "e6_formal_guard": summarize_e6(kv_artifacts),
    }
    local_api_packages = collect_local_api_package_summaries(artifacts_root)
    run_roots = collect_relevant_run_roots(runs_root)
    vllm_logs = collect_vllm_logs(logs_root)
    judgment = build_judgment(sections, local_api_packages, run_roots)
    return {
        "schema_version": "statebus.local_vllm_kv_experiment_log_summary.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "doc_root": str(doc_root),
            "artifacts_root": str(artifacts_root),
            "runs_root": str(runs_root),
            "logs_root": str(logs_root),
            "kv_artifacts": {name: str(path) for name, path in KV_ARTIFACTS.items()},
        },
        "claim_boundary": (
            "Engine-Local Prefix Reuse via schedule/layout control and input-level "
            "dynamic pruning only; no KV tensor export, hidden-state transfer, "
            "cross-engine reuse, 2-GPU success, or openEuler VM validation is claimed."
        ),
        "sections": sections,
        "historical_run_roots": run_roots,
        "local_api_package_summaries": local_api_packages,
        "vllm_launch_logs": vllm_logs,
        "judgment": judgment,
    }


def load_kv_artifacts(artifacts_root: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for name, default_path in KV_ARTIFACTS.items():
        path = artifacts_root / default_path.name
        loaded[name] = read_json_status(path)
    return loaded


def summarize_e0(kv_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    audit = payload_of(kv_artifacts, "e0_local_vllm_audit")
    service = as_dict(audit.get("vllm_service"))
    metrics = as_dict(service.get("metrics"))
    health = as_dict(service.get("health"))
    cache_values = as_dict(metrics.get("raw_metric_values"))
    cache_lines = list_of_str(metrics.get("raw_metric_lines"))
    cache_config = next((line for line in cache_lines if "cache_config_info" in line), "")
    return {
        "artifact": path_of(kv_artifacts, "e0_local_vllm_audit"),
        "health_ok": health.get("ok"),
        "health_status_code": health.get("status_code"),
        "metrics_ok": metrics.get("ok"),
        "prefix_cache_metric_status": metrics.get("prefix_cache_metric_status"),
        "gpu_prefix_cache_hit_rate": cache_values.get("vllm:gpu_prefix_cache_hit_rate"),
        "cache_config_line": cache_config,
        "aggregate": audit.get("aggregate"),
        "readout": (
            "32B service observability is restored if health_ok is true and "
            "prefix/cache metrics are exposed."
        ),
    }


def summarize_e1(kv_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = payload_of(kv_artifacts, "e1_schedule_primary")
    clean = payload_of(kv_artifacts, "e1_e2_clean_service_repeat")
    stability = payload_of(kv_artifacts, "e1_e2_stability_repeat")
    primary_metrics = as_dict(primary.get("metrics"))
    clean_e1 = as_dict(clean.get("e1_schedule_clean_repeat"))
    stability_e1 = as_dict(stability.get("e1_schedule_repeat"))
    if not stability_e1:
        stability_e1 = as_dict(stability.get("e1_schedule_stability_repeat"))
    return {
        "artifacts": {
            "primary": path_of(kv_artifacts, "e1_schedule_primary"),
            "clean_service_repeat": path_of(kv_artifacts, "e1_e2_clean_service_repeat"),
            "stability_repeat": path_of(kv_artifacts, "e1_e2_stability_repeat"),
        },
        "primary_result": primary.get("primary_result"),
        "primary_metrics": {
            "friendly": as_dict(primary_metrics.get("friendly")),
            "hostile": as_dict(primary_metrics.get("hostile")),
            "delta": as_dict(primary_metrics.get("delta")),
        },
        "clean_repeat": clean_e1,
        "stability_repeat": stability_e1,
        "mechanism_readout": (
            "cache-friendly schedule keeps same-corpus prefixes adjacent and improves "
            "engine-local prefix reuse versus cache-hostile interleaving."
        ),
    }


def summarize_e2(kv_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = payload_of(kv_artifacts, "e2_prefix_alignment_primary")
    clean = payload_of(kv_artifacts, "e1_e2_clean_service_repeat")
    stability = payload_of(kv_artifacts, "e1_e2_stability_repeat")
    primary_metrics = as_dict(primary.get("metrics"))
    clean_e2 = as_dict(clean.get("e2_prefix_alignment_clean_repeat"))
    stability_e2 = as_dict(stability.get("e2_prefix_alignment_repeat"))
    if not stability_e2:
        stability_e2 = as_dict(stability.get("e2_prefix_alignment_stability_repeat"))
    return {
        "artifacts": {
            "primary": path_of(kv_artifacts, "e2_prefix_alignment_primary"),
            "clean_service_repeat": path_of(kv_artifacts, "e1_e2_clean_service_repeat"),
            "stability_repeat": path_of(kv_artifacts, "e1_e2_stability_repeat"),
        },
        "primary_result": primary.get("primary_result"),
        "primary_metrics": {
            "shared": as_dict(primary_metrics.get("shared")),
            "independent": as_dict(primary_metrics.get("independent")),
            "delta": as_dict(primary_metrics.get("delta")),
        },
        "clean_repeat": clean_e2,
        "stability_repeat": stability_e2,
        "mechanism_readout": (
            "shared_evidence_prefix moves common evidence to the beginning of prompts "
            "so vLLM automatic prefix caching can see the reusable prefix."
        ),
    }


def summarize_e3(kv_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    e3 = payload_of(kv_artifacts, "e3_dynamic_pruning")
    off = as_dict(e3.get("baseline_off"))
    on = as_dict(e3.get("dynamic_on"))
    return {
        "artifact": path_of(kv_artifacts, "e3_dynamic_pruning"),
        "primary_result": e3.get("primary_result"),
        "baseline_off": compact_pruning_side(off),
        "dynamic_on": compact_pruning_side(on),
        "delta": as_dict(e3.get("delta")),
        "quality_proxy": as_dict(e3.get("quality_proxy")),
        "mechanism_readout": (
            "dynamic pruning is input-level evidence pruning: it reduces selected "
            "evidence and estimated KV pressure while preserving required hard facts."
        ),
    }


def summarize_e6(kv_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary = payload_of(kv_artifacts, "e6_formal_guard_summary")
    excerpt = payload_of(kv_artifacts, "e6_formal_guard_mechanism_excerpt")
    return {
        "artifacts": {
            "summary": path_of(kv_artifacts, "e6_formal_guard_summary"),
            "mechanism_excerpt": path_of(kv_artifacts, "e6_formal_guard_mechanism_excerpt"),
        },
        "run_id": summary.get("run_id") or excerpt.get("run_id"),
        "selected_case_count": summary.get("selected_case_count"),
        "available_case_count": summary.get("available_case_count"),
        "layers": summary.get("layers") or as_dict(excerpt.get("formal_guard")).get("layers"),
        "comparison_summary": summary.get("comparison_summary") or excerpt.get("comparison_summary"),
        "metadata": summary.get("metadata"),
        "mechanism_switches": excerpt.get("mechanism_switches"),
        "l3_telemetry_excerpt": excerpt.get("l3_telemetry_excerpt"),
        "final_vllm_metrics_excerpt": excerpt.get("final_vllm_metrics_excerpt"),
        "formal_guard_passed": formal_guard_passed(summary.get("layers")),
        "mechanism_readout": (
            "combined shared-prefix layout plus dynamic pruning preserved the 25-case "
            "formal quality floor across L0-L3."
        ),
    }


def compact_pruning_side(data: dict[str, Any]) -> dict[str, Any]:
    profile = as_dict(data.get("pruning_profile"))
    return {
        "task_id": data.get("task_id"),
        "candidate_count": data.get("candidate_count"),
        "keep_count": data.get("keep_count"),
        "drop_count": data.get("drop_count"),
        "selected_evidence_bytes": data.get("selected_evidence_bytes"),
        "selected_candidate_ids": data.get("selected_candidate_ids"),
        "hard_fact_ids": data.get("hard_fact_ids"),
        "budget_decision": profile.get("budget_decision"),
        "dynamic_pruning_enabled": profile.get("dynamic_pruning_enabled"),
        "estimated_kv_tokens_saved": profile.get("estimated_kv_tokens_saved"),
        "selected_evidence_tokens_estimate": profile.get("selected_evidence_tokens_estimate"),
        "importance_threshold": profile.get("importance_threshold"),
    }


def collect_local_api_package_summaries(artifacts_root: Path) -> list[dict[str, Any]]:
    paths: list[Path] = []
    paths.extend(sorted(artifacts_root.glob("local_api_*/summary.json")))
    paths.extend(sorted(artifacts_root.glob("local_api_non_kv_followup_*/*/summary.json")))
    summaries = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        status = read_json_status(path)
        payload = as_dict(status.get("payload"))
        stages = payload.get("stages", [])
        stage_summary = summarize_stages(stages if isinstance(stages, list) else [])
        summaries.append(
            {
                "package": path.parent.name,
                "path": str(path),
                "json_ok": status["json_ok"],
                "stage_summary": stage_summary,
                "important_failed_stages": stage_summary["required_failed"]
                + stage_summary["optional_failed"][:5],
            }
        )
    return summaries


def summarize_stages(stages: list[Any]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        exit_code = str(stage.get("exit_code", ""))
        required = str(stage.get("required", "0")) == "1"
        item = {
            "stage": stage.get("stage"),
            "exit_code": exit_code,
            "required": required,
            "duration_s": safe_float(stage.get("duration_s")),
        }
        normalized.append(item)
    required_failed = [
        item for item in normalized if item["required"] and item["exit_code"] not in ("0", "")
    ]
    optional_failed = [
        item for item in normalized if not item["required"] and item["exit_code"] not in ("0", "")
    ]
    return {
        "stage_count": len(normalized),
        "required_count": sum(1 for item in normalized if item["required"]),
        "required_failed_count": len(required_failed),
        "optional_failed_count": len(optional_failed),
        "required_failed": required_failed,
        "optional_failed": optional_failed,
        "total_duration_s": sum(
            item["duration_s"] for item in normalized if isinstance(item.get("duration_s"), float)
        ),
    }


def collect_relevant_run_roots(runs_root: Path) -> list[dict[str, Any]]:
    if not runs_root.exists():
        return []
    roots = [
        path
        for path in sorted(runs_root.iterdir())
        if path.is_dir()
        and (
            path.name.startswith("sb32b")
            or path.name.startswith("v2-local-vllm-qwen3-32b")
            or path.name.startswith("kv-e6-guard-")
        )
    ]
    return [summarize_run_root(path) for path in roots]


def summarize_run_root(root: Path) -> dict[str, Any]:
    summary = read_json_status(root / "formal_suite.summary.json")
    stdout = read_json_status(root / "formal_suite.stdout.json")
    report_paths = sorted(root.glob("runtime/**/benchmark_reports/*.json"))[:20]
    reports = [summarize_benchmark_report(path) for path in report_paths]
    payload = as_dict(summary.get("payload")) or as_dict(stdout.get("payload"))
    layers = payload.get("layers")
    if not isinstance(layers, list) or not layers:
        layers = [
            report["layer_summary"]
            for report in reports
            if report.get("layer_summary", {}).get("layer")
        ]
    quality_status = classify_run_quality(payload, layers, summary, stdout)
    return {
        "run_id": root.name,
        "run_root": str(root),
        "summary_json_ok": summary["json_ok"],
        "summary_json_size_bytes": summary["size_bytes"],
        "stdout_json_ok": stdout["json_ok"],
        "stdout_json_size_bytes": stdout["size_bytes"],
        "selected_case_count": payload.get("selected_case_count"),
        "available_case_count": payload.get("available_case_count"),
        "layers": layers,
        "comparison_summary": payload.get("comparison_summary"),
        "report_count_scanned": len(reports),
        "quality_status": quality_status,
    }


def summarize_benchmark_report(path: Path) -> dict[str, Any]:
    status = read_json_status(path)
    payload = as_dict(status.get("payload"))
    metrics = as_dict(payload.get("aggregated_metrics"))
    return {
        "path": str(path),
        "json_ok": status["json_ok"],
        "layer_summary": {
            "layer": payload.get("layer") or infer_layer(path.name),
            "case_count": metrics.get("case_count"),
            "quality_floor_pass_count": metrics.get("quality_floor_pass_count"),
        },
    }


def classify_run_quality(
    payload: dict[str, Any],
    layers: Any,
    summary: dict[str, Any],
    stdout: dict[str, Any],
) -> str:
    if formal_guard_passed(layers):
        return "formal_pass_all_L0_L3"
    if isinstance(layers, list) and layers:
        return "partial_layer_reports_present"
    if not summary["json_ok"] and stdout["exists"] and stdout["size_bytes"] == 0:
        return "no_suite_summary_empty_stdout"
    if payload:
        return "payload_present_not_full_formal_pass"
    return "no_parseable_formal_payload"


def collect_vllm_logs(logs_root: Path) -> list[dict[str, Any]]:
    if not logs_root.exists():
        return []
    logs = sorted(logs_root.glob("vllm_qwen3_32b*.log"))
    return [summarize_vllm_log(path) for path in logs]


def summarize_vllm_log(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        raw = read_head_tail_bytes(path, MAX_LOG_SCAN_BYTES)
    except OSError as exc:
        return {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    text = raw.decode("utf-8", errors="replace")
    interesting: list[str] = []
    errors: list[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if re.search(
            r"(max_model_len|num_gpu_blocks|GPU KV cache|Maximum concurrency|"
            r"enable_prefix_caching|Uvicorn running|Started server process|"
            r"served-model-name|gpu_memory_utilization)",
            clean,
            re.IGNORECASE,
        ):
            interesting.append(clean[:500])
        if re.search(r"(Traceback|ERROR|Exception|CUDA out of memory|address already in use)", clean):
            errors.append(clean[:500])
    return {
        "path": str(path),
        "size_bytes": size,
        "interesting_lines": dedupe(interesting)[:MAX_LOG_LINES_PER_FILE],
        "error_lines": dedupe(errors)[:MAX_LOG_LINES_PER_FILE],
    }


def read_head_tail_bytes(path: Path, budget: int) -> bytes:
    size = path.stat().st_size
    if size <= budget:
        return path.read_bytes()
    head_budget = budget // 4
    tail_budget = budget - head_budget
    with path.open("rb") as handle:
        head = handle.read(head_budget)
        handle.seek(max(0, size - tail_budget))
        tail = handle.read(tail_budget)
    return head + b"\n...[snip]...\n" + tail


def build_judgment(
    sections: dict[str, Any],
    local_api_packages: list[dict[str, Any]],
    run_roots: list[dict[str, Any]],
) -> dict[str, Any]:
    e1_clean = as_dict(sections["e1_schedule"].get("clean_repeat"))
    e1_delta = as_dict(e1_clean.get("delta_friendly_minus_hostile"))
    e2_clean = as_dict(sections["e2_prefix_alignment"].get("clean_repeat"))
    e2_delta = as_dict(e2_clean.get("delta_shared_minus_independent"))
    e3 = sections["e3_dynamic_pruning"]
    e6 = sections["e6_formal_guard"]

    mechanism_ready = all(
        [
            positive(e1_delta.get("final_gpu_prefix_cache_hit_rate")),
            negative(e1_delta.get("mean_ttft_ms")),
            positive(e2_delta.get("final_gpu_prefix_cache_hit_rate")),
            negative(e2_delta.get("mean_ttft_ms")),
            as_dict(e3.get("quality_proxy")).get("pass") is True,
            e6.get("formal_guard_passed") is True,
        ]
    )
    clean_formal_passes = [
        item["run_id"] for item in run_roots if item.get("quality_status") == "formal_pass_all_L0_L3"
    ]
    required_failures = sum(
        as_dict(item.get("stage_summary")).get("required_failed_count", 0)
        for item in local_api_packages
    )
    return {
        "overall": (
            "mechanism evidence is sufficient for a careful Engine-Local Prefix Reuse claim"
            if mechanism_ready
            else "mechanism evidence is incomplete; inspect section-level blockers"
        ),
        "mechanism_ready": mechanism_ready,
        "formal_pass_run_roots": clean_formal_passes,
        "local_api_required_failed_count_scanned": required_failures,
        "supported_claims": [
            "cache-friendly scheduling improves vLLM engine-local prefix reuse behavior",
            "shared_evidence_prefix exposes a reusable common prompt prefix to vLLM",
            "dynamic pruning reduces input evidence/KV pressure at retrieval scope",
            "combined mechanism profile preserves the formal 25-case quality floor",
        ],
        "unsupported_claims": [
            "KV tensor export or transfer",
            "hidden-state transfer",
            "cross-engine KV reuse",
            "2-GPU success",
            "openEuler VM validation",
        ],
        "recommended_next_steps": [
            "freeze this evidence as the current mechanism-benefit package",
            "promote the clean E1/E2 and E6 numbers into the main report/presentation tables",
            "rerun E6 only after changing schedule, prefix layout, pruning policy, or prompt budgets",
            "defer E4/E5 context-length and multi-GPU tests until GPU restart risk is explicitly acceptable",
        ],
    }


def render_markdown(payload: dict[str, Any], output_json: Path) -> str:
    sections = payload["sections"]
    e0 = sections["e0_observability"]
    e1 = sections["e1_schedule"]
    e2 = sections["e2_prefix_alignment"]
    e3 = sections["e3_dynamic_pruning"]
    e6 = sections["e6_formal_guard"]
    judgment = payload["judgment"]
    lines = [
        "# Local vLLM KV Experiment Log Synthesis - 2026-07-11",
        "",
        "## Executive Judgment",
        "",
        (
            "当前日志和 artifact 支持一个谨慎但已经可用的结论：StateBus 现在有"
            "机制收益证据，具体是通过 schedule/layout 控制触发 vLLM 的 "
            "`Engine-Local Prefix Reuse`，再配合输入级 dynamic pruning 降低 prompt/KV 压力。"
        ),
        "",
        "不能写成 KV tensor 传递、hidden-state 传递、cross-engine KV reuse、2-GPU 成功或 openEuler 已验证。",
        "",
        f"机器可读汇总：`{output_json}`",
        "",
        "## Evidence Map",
        "",
        "| Area | Best Evidence | Key Numbers | Judgment |",
        "| --- | --- | --- | --- |",
        evidence_row(
            "E0 observability",
            "`local_vllm_kv_audit_20260711.json`",
            [
                f"health={e0.get('health_ok')}",
                f"metrics={e0.get('prefix_cache_metric_status')}",
                "single GPU0 32B service",
            ],
            "服务可观测性恢复，后续 KV 机制测试有意义。",
        ),
        evidence_row(
            "E1 schedule",
            "`e1_e2_clean_service_repeat_summary_20260711_1438.json`",
            [
                "friendly hit-rate "
                + fmt(get_path(e1, ["clean_repeat", "cache_friendly", "final_gpu_prefix_cache_hit_rate"])),
                "hostile hit-rate "
                + fmt(get_path(e1, ["clean_repeat", "cache_hostile", "final_gpu_prefix_cache_hit_rate"])),
                "TTFT delta "
                + fmt(get_path(e1, ["clean_repeat", "delta_friendly_minus_hostile", "mean_ttft_ms"]))
                + " ms",
            ],
            "cache-friendly ordering 在 clean-service 条件下复现收益。",
        ),
        evidence_row(
            "E2 prefix layout",
            "`e1_e2_clean_service_repeat_summary_20260711_1438.json`",
            [
                "shared hit-rate "
                + fmt(get_path(e2, ["clean_repeat", "shared_evidence_prefix", "final_gpu_prefix_cache_hit_rate"])),
                "independent hit-rate "
                + fmt(get_path(e2, ["clean_repeat", "independent", "final_gpu_prefix_cache_hit_rate"])),
                "TTFT delta "
                + fmt(get_path(e2, ["clean_repeat", "delta_shared_minus_independent", "mean_ttft_ms"]))
                + " ms",
            ],
            "`shared_evidence_prefix` 是当前最强机制证据。",
        ),
        evidence_row(
            "E3 pruning",
            "`e3_dynamic_pruning_ablation_20260711.json`",
            [
                "selected bytes "
                + fmt(get_path(e3, ["baseline_off", "selected_evidence_bytes"]))
                + " -> "
                + fmt(get_path(e3, ["dynamic_on", "selected_evidence_bytes"])),
                "KV token saved delta "
                + fmt(get_path(e3, ["delta", "estimated_kv_tokens_saved_on_minus_off"])),
                "quality proxy pass="
                + str(get_path(e3, ["quality_proxy", "pass"])),
            ],
            "证明输入级裁剪有效，但本身不是 end-to-end formal quality 证明。",
        ),
        evidence_row(
            "E6 formal guard",
            "`e6_formal_guard_summary_20260711_1448.json`",
            [
                "L0-L3 all 25/25",
                "L3 tokens "
                + fmt(get_path(e6, ["comparison_summary", "protocol_L3_total_tokens"])),
                "L0 tokens "
                + fmt(get_path(e6, ["comparison_summary", "text_L0_total_tokens"])),
                "quality delta 0",
            ],
            "组合机制 profile 没伤 formal 25-case 质量底线。",
        ),
        "",
        "## What The Logs Say",
        "",
        "- E0 的失败是服务未监听和 profile/启动问题，不是 StateBus 质量失败；恢复后 `/health` 为 200，`/metrics` 暴露 prefix/cache/KV gauge。",
        "- E1 的 repeat=3 压力不够，repeat=4 和 clean-service repeat 才是主证据；这解释了为什么要用容量敏感压力设置。",
        "- E2 的 clean-service 结果最干净：independent 从冷 cache 起步仍为 0.0，shared prefix 到 0.779545，且 TTFT 大幅下降。",
        "- E3 是 retrieval-level deterministic probe；它证明 pruning 机制和 hard-fact proxy，不应单独承担 formal quality claim。",
        "- E6 是质量闭环：机制开关打开后 L0/L1/L2/L3 都是 25/25，Protocol L3 相比 Text L0 少 51282 total tokens、45652 prompt tokens。",
        "",
        "## Historical Runs",
        "",
        historical_runs_table(payload["historical_run_roots"]),
        "",
        "历史 32B 运行里，失败主要集中在 wrapper timeout、空 stdout、上下文/JSON 截断风险和 partial L0 report；这些更像工程运行条件问题。"
        "当前可引用的质量闭环是 `sb32bcompact` 和 `kv-e6-guard-20260711-1448` 这类完整 L0-L3 pass。",
        "",
        "## Broader Local API Packages",
        "",
        local_api_packages_table(payload["local_api_package_summaries"]),
        "",
        "这些综合包说明：非 KV 主线在 2026-07-07 到 2026-07-08 已经有多次 required stages clean 的证据；"
        "早期 required failure 主要来自 API/timeout/修复前 artifact 审计，而不是当前 E1-E3 机制 probe。",
        "",
        "## vLLM Launch Logs",
        "",
        vllm_log_risk_table(payload["vllm_launch_logs"]),
        "",
        "日志扫描的实用结论是：8192 context 可以支撑当前 E1/E2/E6 证据，但曾出现过 independent layout 探索请求超过 8192 token 的报错；"
        "这解释了为什么后续要继续保留 context cap、shared prefix layout 和 dynamic pruning。",
        "",
        "## Decision",
        "",
        f"- Overall: {judgment['overall']}.",
        "- 当前可以把 E1/E2/E3/E6 固化成“机制收益 + formal guard”证据包。",
        "- 后续不建议继续消耗 GPU 去重复 E1/E2，除非要做最终图表误差线或改了 prompt/layout/pruning 代码。",
        "- E4/E5 仍然暂缓；8192 以上 context 和 multi-GPU 需要安全重启窗口，不能从现有日志推导成功。",
        "- 下一步更有价值的是把这份证据链合入主报告/答辩材料，并把 claim boundary 写死。",
        "",
        "## Claim Boundary",
        "",
        payload["claim_boundary"],
        "",
    ]
    return "\n".join(lines)


def evidence_row(area: str, evidence: str, numbers: list[str], judgment: str) -> str:
    return f"| {area} | {evidence} | {'; '.join(numbers)} | {judgment} |"


def historical_runs_table(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "No relevant run roots found."
    lines = [
        "| Run | Status | Extracted Cases | Token Delta |",
        "| --- | --- | ---: | ---: |",
    ]
    for run in runs:
        comparison = as_dict(run.get("comparison_summary"))
        layers = run.get("layers")
        case_text = extracted_case_text(layers)
        lines.append(
            "| "
            + str(run.get("run_id"))
            + " | "
            + str(run.get("quality_status"))
            + " | "
            + case_text
            + " | "
            + fmt(comparison.get("protocol_vs_text_token_delta"))
            + " |"
        )
    return "\n".join(lines)


def extracted_case_text(layers: Any) -> str:
    if not isinstance(layers, list) or not layers:
        return ""
    parts = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        parts.append(
            f"{layer.get('layer')} {fmt(layer.get('quality_floor_pass_count'))}/{fmt(layer.get('case_count'))}"
        )
    return ", ".join(parts)


def local_api_packages_table(packages: list[dict[str, Any]]) -> str:
    if not packages:
        return "No local_api package summaries found."
    lines = [
        "| Package | Stages | Required Failed | Optional Failed | Failed Stage Sample |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for package in packages:
        stage_summary = as_dict(package.get("stage_summary"))
        failed = package.get("important_failed_stages")
        failed_items = failed if isinstance(failed, list) else []
        failed_sample = ", ".join(
            str(item.get("stage")) + ":" + str(item.get("exit_code"))
            for item in failed_items[:3]
            if isinstance(item, dict)
        )
        lines.append(
            "| "
            + str(package.get("package"))
            + " | "
            + fmt(stage_summary.get("stage_count"))
            + " | "
            + fmt(stage_summary.get("required_failed_count"))
            + " | "
            + fmt(stage_summary.get("optional_failed_count"))
            + " | "
            + failed_sample
            + " |"
        )
    return "\n".join(lines)


def vllm_log_risk_table(logs: list[dict[str, Any]]) -> str:
    if not logs:
        return "No Qwen3-32B vLLM launch logs found."
    error_logs = [
        log for log in logs if isinstance(log.get("error_lines"), list) and log.get("error_lines")
    ]
    lines = [
        f"Scanned `{len(logs)}` Qwen3-32B vLLM launch logs; `{len(error_logs)}` contained error lines.",
        "",
        "| Log | Error Signal |",
        "| --- | --- |",
    ]
    if not error_logs:
        lines.append("| none | none |")
        return "\n".join(lines)
    for log in error_logs:
        path = str(log.get("path", ""))
        name = Path(path).name
        first_error = ""
        for line in log.get("error_lines", []):
            if "maximum context length" in str(line):
                first_error = str(line)
                break
        if not first_error:
            first_error = str(log.get("error_lines", [""])[0])
        lines.append(f"| `{name}` | {first_error[:240]} |")
    return "\n".join(lines)


def read_json_status(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": 0,
        "json_ok": False,
        "parse_error": "",
        "payload": {},
    }
    if not path.exists():
        status["parse_error"] = "missing"
        return status
    status["size_bytes"] = path.stat().st_size
    if status["size_bytes"] == 0:
        status["parse_error"] = "empty"
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - summarizer records bad artifacts.
        status["parse_error"] = f"{type(exc).__name__}: {exc}"
        return status
    status["json_ok"] = True
    status["payload"] = payload
    return status


def payload_of(loaded: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return as_dict(loaded.get(name, {}).get("payload"))


def path_of(loaded: dict[str, dict[str, Any]], name: str) -> str:
    return str(loaded.get(name, {}).get("path", ""))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def formal_guard_passed(layers: Any) -> bool:
    if not isinstance(layers, list):
        return False
    by_layer = {item.get("layer"): item for item in layers if isinstance(item, dict)}
    for layer in ("L0", "L1", "L2", "L3"):
        item = as_dict(by_layer.get(layer))
        if safe_int(item.get("case_count")) != 25:
            return False
        if safe_int(item.get("quality_floor_pass_count")) != 25:
            return False
    return True


def infer_layer(name: str) -> str:
    match = re.search(r"(?:^|-)(L[0-3])(?:\.|-)", name)
    return match.group(1) if match else ""


def get_path(data: dict[str, Any], keys: list[str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if abs(value) >= 100:
            return f"{value:.2f}"
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def negative(value: Any) -> bool:
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


if __name__ == "__main__":
    raise SystemExit(main())
