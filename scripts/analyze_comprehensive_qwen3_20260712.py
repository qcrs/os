#!/usr/bin/env python3
"""Reconstruct the 2026-07-12 Qwen3-32B comprehensive experiment.

The original shell summary is incomplete, so this script reads the raw suite
payloads and nested benchmark reports directly. It is intentionally read-only
with respect to run artifacts and writes a compact JSON dataset plus a Markdown
analysis report under docs/improvement/.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_RUNS_ROOT = Path("/home/qcrs/statebus/runs")
DEFAULT_STAMP = "20260712_223614"
DEFAULT_OUTPUT_DIR = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706"
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def pct(delta: float, baseline: float) -> float | None:
    return round(delta / baseline * 100.0, 4) if baseline else None


def layer_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for layer in payload.get("layers", []):
        metrics = layer.get("telemetry_summary", {})
        aggregate = layer.get("aggregated_metrics", {})
        cases = layer.get("cases", [])
        rows.append(
            {
                "layer": layer.get("layer"),
                "case_count": aggregate.get("case_count", len(cases)),
                "quality_floor_pass_count": aggregate.get("quality_floor_pass_count"),
                "llm_prompt_tokens": metrics.get("llm_prompt_tokens"),
                "llm_completion_tokens": metrics.get("llm_completion_tokens"),
                "llm_total_tokens": metrics.get("llm_total_tokens"),
                "llm_wall_ms": metrics.get("llm_wall_ms"),
                "runtime_fallback_count": metrics.get("runtime_fallback_count"),
                "semantic_state_transfer_count": metrics.get("semantic_state_transfer_count"),
                "state_pool_shared_memory_mode_count": metrics.get(
                    "state_pool_shared_memory_mode_count"
                ),
                "logit_state_transfer_count": metrics.get("logit_state_transfer_count"),
                "logit_confidence_gate_trigger_count": metrics.get(
                    "logit_confidence_gate_trigger_count"
                ),
                "neural_prefix_shared_prefix_bytes": metrics.get(
                    "neural_prefix_shared_prefix_bytes"
                ),
                "neural_prefix_cache_hit_count_estimate": metrics.get(
                    "neural_prefix_cache_hit_count_estimate"
                ),
                "reuse_gain": metrics.get("reuse_gain"),
                "skipped_step_count": metrics.get("skipped_step_count"),
                "validated_replay_count": metrics.get("validated_replay_count"),
                "exact_replay_count": metrics.get("exact_replay_count"),
                "answer_restoration_replay_count": metrics.get(
                    "answer_restoration_replay_count"
                ),
                "history_reuse_gain": metrics.get("history_reuse_gain"),
                "history_step_reduction_count": metrics.get(
                    "history_step_reduction_count"
                ),
                "memory_match_count": metrics.get("memory_match_count"),
                "replay_class_distribution": layer.get("replay_class_distribution", {}),
            }
        )
    return rows


def collect_case_metrics(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage_name, payload in payloads.items():
        for layer in payload.get("layers", []):
            for case in layer.get("cases", []):
                metrics = case.get("metrics", {})
                rows.append(
                    {
                        "stage": stage_name,
                        "layer": layer.get("layer"),
                        "task_id": case.get("task_id"),
                        "task_family": case.get("task_family"),
                        "quality_floor_pass": bool(
                            case.get("quality_floor", {}).get("quality_floor_pass")
                        ),
                        "executor_completion_tokens": metrics.get(
                            "executor_completion_tokens"
                        ),
                        "logit_state_transfer_count": metrics.get(
                            "logit_state_transfer_count"
                        ),
                        "logit_peak_position": metrics.get("logit_peak_position"),
                        "logit_varentropy": metrics.get("logit_varentropy"),
                        "logit_top_gap": metrics.get("logit_top_gap"),
                        "logit_state_mean_entropy": metrics.get(
                            "logit_state_mean_entropy"
                        ),
                        "logit_confidence_gate_trigger_count": metrics.get(
                            "logit_confidence_gate_trigger_count"
                        ),
                        "neural_prefix_shared_prefix_bytes": metrics.get(
                            "neural_prefix_shared_prefix_bytes"
                        ),
                        "reuse_gain": metrics.get("reuse_gain"),
                        "skipped_step_count": metrics.get("skipped_step_count"),
                        "validated_replay_count": metrics.get(
                            "validated_replay_count"
                        ),
                    }
                )
    return rows


def numeric_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
    }


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / denominator


def summarize_logit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in rows if row.get("logit_state_transfer_count")]
    peak_offsets = []
    for row in usable:
        completion = row.get("executor_completion_tokens")
        peak = row.get("logit_peak_position")
        if isinstance(completion, (int, float)) and isinstance(peak, (int, float)):
            peak_offsets.append(completion - 1 - peak)
    varentropy = [float(row["logit_varentropy"]) for row in usable if row.get("logit_varentropy") is not None]
    top_gap = [float(row["logit_top_gap"]) for row in usable if row.get("logit_top_gap") is not None]
    prefix_bytes = [
        float(row["neural_prefix_shared_prefix_bytes"])
        for row in usable
        if row.get("neural_prefix_shared_prefix_bytes") is not None
    ]
    paired_varentropy = [
        (float(row["logit_varentropy"]), float(row["neural_prefix_shared_prefix_bytes"]))
        for row in usable
        if row.get("logit_varentropy") is not None
        and row.get("neural_prefix_shared_prefix_bytes") is not None
    ]
    return {
        "case_observation_count": len(usable),
        "quality_pass_count": sum(1 for row in usable if row["quality_floor_pass"]),
        "peak_is_last_count": sum(1 for offset in peak_offsets if offset == 0),
        "peak_before_last_count": sum(1 for offset in peak_offsets if offset > 0),
        "peak_offset_from_last_index": numeric_summary(peak_offsets),
        "varentropy": numeric_summary(varentropy),
        "top_gap": numeric_summary(top_gap),
        "shared_prefix_bytes": numeric_summary(prefix_bytes),
        "varentropy_vs_shared_prefix_bytes_pearson": pearson(
            [item[0] for item in paired_varentropy],
            [item[1] for item in paired_varentropy],
        ),
        "confidence_gate_trigger_count": sum(
            float(row.get("logit_confidence_gate_trigger_count") or 0) for row in usable
        ),
        "interpretation": (
            "Logit state and shared-prefix telemetry co-occur, but transfer_count is "
            "constant per completed case and cannot support a causal correlation claim."
        ),
    }


def baseline_failure_summary(compare_report: dict[str, Any]) -> dict[str, Any]:
    cases = compare_report["external_report"]["cases"]
    counter: Counter[str] = Counter()
    family_counter: dict[str, Counter[str]] = defaultdict(Counter)
    examples: list[dict[str, Any]] = []
    for case in cases:
        metrics = case.get("metrics", {})
        family = str(case.get("task_family"))
        for key in (
            "route_exact",
            "tool_exact",
            "selected_doc_hashes_exact",
            "summary_present",
            "metric_name_exact",
            "metric_value_exact",
            "admissible_match",
            "external_fairness_gate_pass",
        ):
            passed = bool(metrics.get(key))
            counter[f"{key}_pass" if passed else f"{key}_fail"] += 1
            family_counter[family][f"{key}_pass" if passed else f"{key}_fail"] += 1
        if len(examples) < 3:
            examples.append(
                {
                    "task_id": case.get("task_id"),
                    "task_family": family,
                    "quality_floor": case.get("quality_floor"),
                    "metrics": {
                        key: metrics.get(key)
                        for key in (
                            "route_exact",
                            "tool_exact",
                            "selected_doc_hashes_exact",
                            "summary_present",
                            "metric_name_exact",
                            "metric_value_exact",
                            "admissible_match",
                        )
                    },
                    "output_artifact_path": case.get("output_artifact_path"),
                }
            )
    return {
        "case_count": len(cases),
        "quality_floor_pass_count": compare_report["external_report"][
            "aggregated_metrics"
        ].get("quality_floor_pass_count"),
        "metric_counts": dict(sorted(counter.items())),
        "by_family": {
            family: dict(sorted(values.items()))
            for family, values in sorted(family_counter.items())
        },
        "examples": examples,
        "root_cause": (
            "The retriever prompt requests evidence_summary, metric_name, metric_value, "
            "and selected_doc_hashes, but the Track C response schema permits only "
            "candidate_key, route, and tool_name with additionalProperties=false. The "
            "model therefore cannot return the facts consumed by the scorer."
        ),
    }


def historical_summary(repo_root: Path) -> dict[str, Any]:
    path = repo_root / (
        "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/"
        "local_api_20260707_163354/summary.json"
    )
    payload = load_json(path)
    keys = payload["key_metrics"]
    formal = keys["r01_05_formal_api_local_memfd"]
    compare = keys["r01_06_formal_compare_api_local_memfd"]
    continuous = keys["r01_09_continuous_api_local"]
    replay = keys["r01_10_continuous_replay_api_local"]
    return {
        "source": str(path),
        "run_id": payload.get("run_id"),
        "model_identity": "not_preserved_in_archived_summary",
        "comparison_boundary": (
            "Historical numbers are path-level API evidence, not a controlled model-only "
            "comparison with Qwen3-32B."
        ),
        "formal_internal": formal,
        "formal_external_compare": compare,
        "continuous": continuous,
        "continuous_replay": replay,
        "v1_host_reference": {
            "reuse_gain": 0.17,
            "memory_hit_rate": 0.83,
            "skipped_step_count": 9,
            "source": "30_independent_audit_report_20260711.md",
        },
    }


def build_dataset(repo_root: Path, runs_root: Path, stamp: str) -> dict[str, Any]:
    paths = {
        "comprehensive": runs_root / f"comprehensive_qwen3_{stamp}",
        "s1": runs_root / f"s1-preflight-{stamp}" / "preflight.stdout.json",
        "s2": runs_root / f"s2-logit-verify-{stamp}" / "formal_suite.stdout.json",
        "s3": runs_root / f"s3-compare-qwen3-{stamp}" / "formal_suite.stdout.json",
        "s3_report": runs_root
        / f"s3-compare-qwen3-{stamp}"
        / "runtime/benchmark_reports"
        / f"s3-compare-qwen3-{stamp}-cold-start-compare-local_vllm.json",
        "s4": runs_root / f"s4-statebus-replay-{stamp}" / "stdout.json",
        "s5_csv": runs_root / f"s5-continuous-csv_table_profile-{stamp}" / "stdout.json",
        "s5_cross": runs_root
        / f"s5-continuous-cross_period_financial-{stamp}"
        / "stdout.json",
        "s6": runs_root / f"s6-formal-qwen3-e7-{stamp}" / "formal_suite.stdout.json",
    }
    missing = [str(path) for key, path in paths.items() if key != "comprehensive" and not path.exists()]
    if missing:
        raise FileNotFoundError("Missing experiment artifacts:\n" + "\n".join(missing))

    s1 = load_json(paths["s1"])
    s2 = load_json(paths["s2"])
    s3 = load_json(paths["s3"])
    s3_report = load_json(paths["s3_report"])
    s4 = load_json(paths["s4"])
    s5_csv = load_json(paths["s5_csv"])
    s5_cross = load_json(paths["s5_cross"])
    s6 = load_json(paths["s6"])
    suite_payloads = {
        "s2_logit": s2,
        "s3_compare_statebus": {"layers": [s3_report["statebus_report"]]},
        "s4_replay_attempt": s4,
        "s5_csv": s5_csv,
        "s5_cross": s5_cross,
        "s6_formal": s6,
    }
    case_rows = collect_case_metrics(suite_payloads)

    stage3_summary = s3["comparison_summary"]
    stage6_summary = s6["comparison_summary"]
    final_summary_path = paths["comprehensive"] / "final_summary.json"
    final_summary = load_json(final_summary_path)

    return {
        "schema_version": "statebus.qwen3_comprehensive_analysis.v1",
        "stamp": stamp,
        "source_paths": {key: str(value) for key, value in paths.items()},
        "stage_status": {
            "s0_health": "passed",
            "s1_preflight": "passed_but_not_schema_validation",
            "s2_logit": "passed",
            "s3_compare": "runner_completed_wrapper_jq_failed_comparison_invalid",
            "s4_replay": "runner_completed_but_replay_mode_not_applied",
            "s5_csv": "passed",
            "s5_cross": "passed",
            "s6_formal": "passed_internal_attribution_only",
        },
        "stage1": {
            "ok": s1.get("ok"),
            "checks": s1.get("checks"),
            "track_c_schema_exercised": False,
            "reason": "preflight only checks API/config, embedding dependency/model/device",
        },
        "stage2": {
            "layers": layer_rows(s2),
            "logit": summarize_logit(
                [row for row in case_rows if row["stage"] == "s2_logit"]
            ),
        },
        "stage3": {
            "comparison_valid": s3.get("fixed_answer_external_comparison_valid"),
            "invalid_reason": s3_report.get("invalid_reason"),
            "strict_equal_quality_comparison_valid": s3.get(
                "strict_equal_quality_comparison_valid"
            ),
            "quality_superiority_comparison_valid": s3.get(
                "quality_superiority_comparison_valid"
            ),
            "formal_external_claim_kind": s3.get("formal_external_claim_kind"),
            "formal_efficiency_superiority_claim_allowed": s3.get(
                "formal_efficiency_superiority_claim_allowed"
            ),
            "formal_quality_superiority_claim_allowed": s3.get(
                "formal_quality_superiority_claim_allowed"
            ),
            "case_count": stage3_summary.get("local_vllm_case_count"),
            "statebus_quality_pass_count": stage3_summary.get(
                "local_vllm_debug_statebus_quality_floor_pass_count"
            ),
            "external_quality_pass_count": stage3_summary.get(
                "local_vllm_debug_external_quality_floor_pass_count"
            ),
            "statebus_total_tokens": stage3_summary.get(
                "local_vllm_statebus_llm_total_tokens"
            ),
            "external_total_tokens": stage3_summary.get(
                "local_vllm_external_llm_total_tokens"
            ),
            "total_token_delta": stage3_summary.get("local_vllm_llm_total_tokens_delta"),
            "total_token_delta_percent": pct(
                stage3_summary.get("local_vllm_llm_total_tokens_delta", 0),
                stage3_summary.get("local_vllm_external_llm_total_tokens", 0),
            ),
            "prompt_token_delta": stage3_summary.get("local_vllm_prompt_tokens_delta"),
            "completion_token_delta": stage3_summary.get(
                "local_vllm_completion_tokens_delta"
            ),
            "fairness_manifest": s3_report.get("fairness_manifest"),
            "statebus_layers": layer_rows({"layers": [s3_report["statebus_report"]]}),
            "statebus_logit": summarize_logit(
                [row for row in case_rows if row["stage"] == "s3_compare_statebus"]
            ),
            "baseline_failures": baseline_failure_summary(s3_report),
        },
        "stage4": {
            "selected_case_count": s4.get("selected_case_count"),
            "family_count": s4.get("family_count"),
            "metadata": s4.get("metadata"),
            "comparison_summary": s4.get("comparison_summary"),
            "layers": layer_rows(s4),
            "auto_bootstrap_succeeded": False,
            "root_cause": (
                "live_runner formal-tier non-compare branch calls run_minimal_benchmark_suite "
                "before the suite=statebus branch and does not forward statebus_mode"
            ),
            "actual_vllm_gpu_prefix_cache_hit_rate": None,
            "actual_vllm_metric_reason": (
                "No per-stage /metrics snapshot was persisted; control-plane estimates are not "
                "a direct vLLM hit-rate measurement."
            ),
        },
        "stage5": {
            "family_count": 2,
            "families": {
                "csv_table_profile_v1": {
                    "comparison_summary": s5_csv.get("comparison_summary"),
                    "waterfall_metrics": s5_csv.get("waterfall_metrics"),
                    "metadata": s5_csv.get("metadata"),
                    "layers": layer_rows(s5_csv),
                },
                "cross_period_financial_v1": {
                    "comparison_summary": s5_cross.get("comparison_summary"),
                    "waterfall_metrics": s5_cross.get("waterfall_metrics"),
                    "metadata": s5_cross.get("metadata"),
                    "layers": layer_rows(s5_cross),
                },
            },
            "continuous_round_count": 20,
            "quality_pass_count": 20,
            "runtime_fallback_count": sum(
                int(row.get("runtime_fallback_count") or 0)
                for payload in (s5_csv, s5_cross)
                for row in layer_rows(payload)
                if row["layer"] == "L3"
            ),
            "statistical_repeat_count": 1,
        },
        "stage6": {
            "selected_case_count": s6.get("selected_case_count"),
            "available_case_count": s6.get("available_case_count"),
            "family_count": s6.get("family_count"),
            "families": s6.get("families"),
            "layers": layer_rows(s6),
            "comparison_summary": stage6_summary,
            "protocol_vs_text_token_delta_percent": pct(
                stage6_summary.get("protocol_vs_text_token_delta", 0),
                stage6_summary.get("text_L0_total_tokens", 0),
            ),
            "protocol_vs_text_prompt_token_delta_percent": pct(
                stage6_summary.get("protocol_vs_text_prompt_token_delta", 0),
                stage6_summary.get("text_L0_prompt_tokens", 0),
            ),
            "claim_boundary": s6.get("metadata", {}).get("ladder_claim_scope"),
            "formal_external_superiority_supported": False,
        },
        "logit_all_statebus_cases": summarize_logit(case_rows),
        "track_b": {
            "deployed": False,
            "evidence": "PrefixCacheFeedbackLoop is defined only in v2/runtime/prefix_feedback.py",
            "experiment_validation_required": True,
        },
        "historical": historical_summary(repo_root),
        "final_summary_bug": {
            "observed_payload": final_summary,
            "causes": [
                "STAMP, RESULTS_DIR, and HOST_RUNS_ROOT are shell variables but not exported",
                "Stage 3 compare fields are read from incorrect nested keys",
                "Stage 4 reuse fields are read from the top level instead of L3 telemetry",
                "Stage 6 layer quality fields are read from the layer top level instead of aggregated_metrics",
            ],
        },
        "case_metrics": case_rows,
    }


def markdown_report(data: dict[str, Any]) -> str:
    s3 = data["stage3"]
    s4_l3 = next(row for row in data["stage4"]["layers"] if row["layer"] == "L3")
    s6 = data["stage6"]
    s5_csv = data["stage5"]["families"]["csv_table_profile_v1"]
    s5_cross = data["stage5"]["families"]["cross_period_financial_v1"]
    csv_l3 = next(row for row in s5_csv["layers"] if row["layer"] == "L3")
    cross_l3 = next(row for row in s5_cross["layers"] if row["layer"] == "L3")
    historical = data["historical"]
    logit = data["logit_all_statebus_cases"]

    layer_table = "\n".join(
        f"| {row['layer']} | {int(row['case_count'])} | {int(row['quality_floor_pass_count'])} | "
        f"{int(row['llm_total_tokens'])} | {int(row['logit_state_transfer_count'])} | "
        f"{int(row['semantic_state_transfer_count'])} | {int(row['reuse_gain'])} |"
        for row in s6["layers"]
    )
    return f"""# Qwen3-32B 综合实验真值分析（2026-07-12）

## Executive Summary

本轮实验完成了 Qwen3-32B local vLLM 下的健康检查、2-case logit 链路、25-case external compare、两组 10-round continuous family，以及 25-case/5-family L0-L3 formal attribution。可直接成立的最强结果是：Stage 6 四层均为 25/25 quality pass，L3 相对 L0 减少 {abs(s6['comparison_summary']['protocol_vs_text_token_delta'])} total tokens（{abs(s6['protocol_vs_text_token_delta_percent']):.2f}%）和 {abs(s6['comparison_summary']['protocol_vs_text_prompt_token_delta'])} prompt tokens（{abs(s6['protocol_vs_text_prompt_token_delta_percent']):.2f}%）。但它仍是同一 StateBus 主线内部的 attribution ladder，不是外部 text baseline 的等质量 superiority 证据。

Stage 3 的 -{abs(s3['total_token_delta'])} tokens（{abs(s3['total_token_delta_percent']):.2f}%）不能作为公平效率结论：StateBus 25/25 通过，external baseline 0/25。根因不是 Qwen3-32B 完全不会抽取事实，而是 Track C schema 与 Retriever 输出契约冲突。schema 只允许 candidate/route/tool，禁止 metric/evidence/doc 字段；实际 25/25 route、tool、doc hash 和 summary 均正确，但 metric_name、metric_value、admissible_match 全部失败。因此 Track C 在本轮是负向回归，不是有效修复。

Stage 4 未产生 replay 证据。formal-tier 分支在 `suite=statebus` 逻辑之前返回，忽略了 `--statebus-mode replay-ready`；L3 的 reuse_gain、skipped_step_count、validated_replay_count 均为 0，metadata 也明确记录四层 seed 均为 false。Stage 5 则证明 local vLLM continuous runner 能稳定完成两个 family 共 20 rounds；其中 cross-period family 有 4 次 validated replay 和 4 个 skipped steps，csv family 只有 history-backed reuse，没有 replay skip。

Track A 已成功把 logit telemetry 带到所有 StateBus case：共有 {logit['case_observation_count']} 个 case-layer 观测，全部 quality pass，peak 从未落在最后 token，通常位于最后 token 前约 {logit['peak_offset_from_last_index']['median']:.0f} 个位置。varentropy 有非零区分度，但整体偏低，且 confidence gate 总触发数为 {int(logit['confidence_gate_trigger_count'])}；因此当前只证明“观测链路有效”，未证明决策质量提升。Track B 没有被任何 runner 导入或激活，必须另做预测值对实测 vLLM gauge 的校准实验。

## Stage 结果

| Stage | 状态 | 关键结论 |
| --- | --- | --- |
| S0 | 通过 | vLLM health 与 GPU 快照落盘；没有压力或 per-stage cache metric |
| S1 | 形式通过 | 4 项环境检查通过，但未调用 schema-constrained generation，不能验证 Track C |
| S2 | 通过 | 2 cases × 4 layers，logit transfer 8/8；peak 均非末位 |
| S3 | 数据生成成功，wrapper 失败 | live runner 完成；旧 jq 汇总因 `.layers` 为空报错；comparison 本身因 quality gate 无效 |
| S4 | 命令成功，目标失败 | 实际运行 cold-start formal ladder，未启用 replay-ready bootstrap |
| S5 | 通过 | 2 families、20 rounds、20/20 quality、0 runtime fallback |
| S6 | 通过 | 25 cases、5 families、L0-L3 各 25/25；内部 token attribution 成立 |

## Track A: Logit Peak-Scan

- Stage 2 的 peak position 为 33/37 等值，对应 executor completion 的倒数第二个 token 索引；8 个 layer-case 观测均避开最后 token。
- 全部实验汇总的 peak-before-last 为 {logit['peak_before_last_count']}/{logit['case_observation_count']}，peak-is-last 为 {logit['peak_is_last_count']}。
- varentropy 范围 {logit['varentropy']['min']:.6f} 到 {logit['varentropy']['max']:.6f}，均值 {logit['varentropy']['mean']:.6f}。它能区分受约束程度，但数值很小，尚无校准阈值。
- top-gap 范围 {logit['top_gap']['min']:.4f} 到 {logit['top_gap']['max']:.4f}。较大 gap 表示 peak token 仍较确定，不能仅凭“最大 entropy”认定存在真实语义歧义。
- S3/S4/S5/S6 的 StateBus 路径均有正的 `logit_state_transfer_count`；external baseline 不经过该链路。
- `logit_confidence_gate_trigger_count=0`，且没有旧算法 A/B 或关闭 logit 的质量对照。结论限定为 telemetry plumbing validated，不是 quality improvement validated。
- logit transfer 与 shared prefix bytes 在每个完成 case 中共同出现，但 transfer_count 基本恒为 1，统计方差为零，不能计算有意义的相关系数，也不能推导因果关系。

## Track B: Prefix Feedback

`PrefixCacheFeedbackLoop` 只存在于未跟踪文件 `v2/runtime/prefix_feedback.py`，仓库搜索未发现 runner/runtime/tests 的调用。所有本轮 artifact 也没有 `prefix_feedback_*` telemetry。Track B 状态为 implemented prototype / not deployed / not experimentally validated。

最低验证设计应在每个 stage 前后抓取 vLLM `/metrics`，记录预测 hit-rate、实际 `gpu_prefix_cache_hit_rate`、服务生命周期和请求数，再比较 feedback 开/关下的 reorder 决策、TTFT 与质量。当前不能使用累计 service gauge 反推某个 stage 的实际命中率。

## Track C 与 Stage 3 根因

Track C 的 `_build_baseline_selection_schema()` 使用 `additionalProperties=false`，required 仅为 `candidate_key/route/tool_name`。同一个 schema 被传给 Retriever 和 Executor，但 Retriever prompt 明确要求 `evidence_summary/metric_name/metric_value/selected_doc_hashes`。受约束解码会合法地删除这些字段，后续 scorer 读取到空字符串。

25 个 external case 的共同模式：

- route exact: 25/25
- tool exact: 25/25
- selected doc hashes exact: 25/25
- summary present: 25/25，且样例 summary 包含正确事实值
- metric_name exact: 0/25
- metric_value exact: 0/25
- admissible match / quality floor: 0/25
- external fairness hard gate: 25/25

因此 quality floor 并非“对 Qwen3-32B 过严”这一单一问题。它正确暴露了结构化事实字段缺失，但 `exact_match=25/25` 与 quality floor 0/25 同时出现也说明 legacy `exact_match` 语义过宽，容易误导。应分别为 Planner、Retriever、Executor、Summarizer 建 schema；Retriever schema 必须包含评分所需事实字段，Executor schema 必须与其 prompt/action contract 一致，并增加 schema-contract regression test。

让 `comparison_valid=true` 的必要条件：修复 role-specific schema 后重跑 25/5 compare；external 与 StateBus 都通过相同 quality floor；fairness gate 继续 25/25；只有 strict equal-quality 成立时，total/prompt token delta 才能进入 formal efficiency claim。

## G-01: Compare 公平性

Stage 3 覆盖了 25 cases / 5 families，fairness manifest 的 same tier、same role graph、same scorer、no contamination 均通过，因此“实验范围与角色公平性”比历史 8-case API compare 更完整。但结果质量不等价，`comparison_valid=false`、`strict_equal_quality_comparison_valid=false`、formal efficiency superiority 不允许。

Stage 6 没有 external baseline，所以不会遇到同一种 schema failure；它的 L0 与 L3 都在 StateBus runner 内完成并各 25/25。该结果只支持 internal attribution，不关闭 G-01 的 external same-task equal-quality gap。

## G-02: Replay Memory

Stage 4 的 L3 指标：reuse_gain={int(s4_l3['reuse_gain'])}、skipped_step_count={int(s4_l3['skipped_step_count'])}、validated_replay_count={int(s4_l3['validated_replay_count'])}、memory_match_count={int(s4_l3['memory_match_count'])}。`seed_replay_memory_by_layer` 四层均为 false，证明 auto-bootstrap 没有进入目标代码路径。

代码根因是 formal-tier non-compare 分支先调用 `run_minimal_benchmark_suite()` 并 return；后面的 `if args.suite == "statebus"` 永远不可达。修复需让 formal statebus suite 走 fixed-answer statebus runner，或为 minimal formal runner显式传入 replay-ready/history bootstrap contract，并新增 assertion：请求 replay-ready 时 L3 metadata 必须显示 history source，且至少一个 replay target 被观测。

本轮没有持久化任何 stage 前后 vLLM `/metrics` 快照，所以实际 GPU prefix cache hit rate不可恢复。`neural_prefix_cache_hit_count_estimate` 只能标为控制面推断，不能替代实测 gauge。

## G-03 / G-11: Multi-Family 与连续稳定性

| Family | Rounds | L3 quality | L3 total tokens | Replay / skip | History reuse | Headline scope |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| csv_table_profile_v1 | 10 | {int(csv_l3['quality_floor_pass_count'])}/10 | {int(csv_l3['llm_total_tokens'])} | 0 / 0 | gain {int(csv_l3['history_reuse_gain'])}, step reduction {int(csv_l3['history_step_reduction_count'])} | history-backed only |
| cross_period_financial_v1 | 10 | {int(cross_l3['quality_floor_pass_count'])}/10 | {int(cross_l3['llm_total_tokens'])} | {int(cross_l3['validated_replay_count'])} / {int(cross_l3['skipped_step_count'])} | gain {int(cross_l3['history_reuse_gain'])}, step reduction {int(cross_l3['history_step_reduction_count'])} | replay admissible |

两组 family 均完成，20/20 quality pass，L3 runtime fallback 为 0。cross-period 的目标 rounds 2/4/6/8 全部出现 validated replay，G-03 和“能连续跑 10 rounds”的 G-11 已显著补强。限制是每个 family 只跑一次，没有多 seed/repeat、误差线、服务重启隔离或 per-round vLLM gauge，因此只能 claim single-run continuous stability。

## Stage 6 Formal

| Layer | Cases | Quality pass | Total tokens | Logit transfer | Semantic transfer | Reuse gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{layer_table}

L3 vs L0：total tokens {s6['comparison_summary']['protocol_vs_text_token_delta']}（{s6['protocol_vs_text_token_delta_percent']:.2f}%），prompt tokens {s6['comparison_summary']['protocol_vs_text_prompt_token_delta']}（{s6['protocol_vs_text_prompt_token_delta_percent']:.2f}%），quality delta 0。L1 的 tokens 略高于 L0，主要收益来自 L2 semantic pruning，而 L2 与 L3 完全相同，进一步证明本轮没有 replay 增量。

Formal claim 边界：可以 claim Qwen3-32B 下 25-case/5-family internal attribution quality parity 和 token reduction；不能 claim external baseline efficiency superiority、真实 KV tensor handoff、Stage 6 replay gain 或 per-stage GPU cache hit-rate。

## 历史 API 对照

| Evidence | Scope | Quality | Token / reuse result | Interpretation |
| --- | --- | --- | --- | --- |
| API formal internal `r01_05`（归档未保留模型标识） | 25 cases / 5 families | 25/25 L3 | memfd 25 transfers, 247076 bytes | 完整 API formal 质量与 state transfer 证据 |
| API external compare `r01_06`（归档未保留模型标识） | 8 cases / 1 family | strict equal-quality valid | StateBus total-token delta +{historical['formal_external_compare']['api_llm_total_tokens_delta']} | 等质量但 total tokens 退步，claim=debug_only |
| Qwen3 Stage 3 | 25 cases / 5 families | 25/25 vs 0/25 | delta {s3['total_token_delta']} | token 方向更好但 baseline schema 失效，不可比较 |
| API continuous `r01_09` | 3 families / 30 rounds | completed | L3 reuse_gain {historical['continuous']['L3_reuse_gain']} | 多 family history reuse 更广 |
| API replay `r01_10` | 3 families / 30 rounds | replay targets 20/20 | 17 validated, 3 exact, reuse_gain {historical['continuous_replay']['L3_reuse_gain']} | replay 证据强于本轮 Stage 4 |
| Qwen3 Stage 5 | 2 families / 20 rounds | 20/20 | 4 validated replay, 4 skipped steps | local vLLM replay 正向进展，但覆盖更小 |

Qwen3 相对历史 API 路径的进步是 formal registry 覆盖从 external 8/1 扩展到 25/5、internal L0-L3 token reduction 明确、local vLLM continuous replay 首次出现正值。退步/未闭环之处是 external baseline schema 回归导致 0/25、Stage 4 formal replay flag 被吞、实际 prefix gauge 未采集，且没有统计 repeat。由于历史 summary 未归档 role model 名称，这不是严格的 Qwen3 vs DeepSeek 模型隔离实验，不能把差异全部归因于模型。

## Bug 与优化优先级

### P0

1. External baseline role schema contract mismatch：拆分 Retriever/Executor schema，恢复 metric/evidence/doc 字段，补 25-family-aware regression tests。
2. Stage 4 formal routing bug：保证 replay-ready 不被 minimal formal branch截获；runner 应在输出 metadata 中回显 effective statebus mode/history source。
3. Claim guard：当 external quality 为 0 或 strict equal-quality false 时，禁止把 token delta写入 headline；保留 quality-superiority 字段但明确它不是 efficiency comparison。

### P1

1. 综合脚本 summary：export `STAMP/RESULTS_DIR/HOST_RUNS_ROOT`，按真实 schema 读取；compare jq failure 应只影响 summary，不把成功的 live runner 标成 stage failure。
2. Stage 1 加一个真实 schema probe case，并验证评分所需字段，而不只是 environment preflight。
3. 每个 stage 前后采集 vLLM `/metrics`、请求计数和 service-lifetime id；clean-service 实验单独重启服务。
4. 持久化 `logit_sequence_length`、`decision_entropy` 和 per-role logit source，避免用 completion token 数近似判断 peak 是否末位。
5. 将 PrefixCacheFeedbackLoop 接入调度器和 telemetry，并增加 feedback on/off A/B。

### P2

1. 连续实验增加 3 seeds 或 3 clean repeats，输出 TTFT/token/replay 的均值、标准差和失败率。
2. 解释/修正 legacy `exact_match=25/25` 与 quality 0/25 的语义冲突。
3. 分离 dynamic pruning 的 token 收益、structured control 的 carrier 收益与 prefix cache 的 engine 收益，避免把 L0-L3 总 delta 全归因于 protocol。

## 仍缺实验

- 修复 schema 后的 Qwen3 full 25/5 external compare，目标 strict equal-quality + comparison_valid=true。
- 修复 formal routing 后的 replay-ready 25/5 run，要求 reuse_gain/skipped steps/validated replay 至少一项为正。
- Track B feedback on/off clean-service A/B，直接读取 vLLM gauge 与 TTFT。
- Track A peak-scan vs old last-token telemetry A/B；需要预注册阈值和真实 decision intervention，而非只记录字段。
- answer_restoration 端到端验证仍为 0，需要 replay 后答案等价性检查。
- mmap formal artifact、subprocess UDS formal 路径、openEuler VM smoke/pytest 仍未由本轮覆盖。
- 统计 repeat、错误条/置信区间和服务生命周期隔离仍缺失。

## 最终判定

Track A：链路有效，质量收益未验证。Track B：未部署。Track C：本轮构成 schema 回归。G-01：internal attribution 已补强，external公平效率未关闭。G-02：Stage 4 未关闭，根因是 runner routing。G-03：已通过两个 local-vLLM continuous family 补强。G-11：单次 10-round×2 family 稳定性成立，但无统计 repeat。Stage 6：formal internal claim 可用，external superiority claim 不可用。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--stamp", default=DEFAULT_STAMP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    data = build_dataset(repo_root, args.runs_root, args.stamp)
    json_path = output_dir / "40_qwen3_comprehensive_data_20260712.json"
    markdown_path = output_dir / "40_qwen3_comprehensive_analysis_20260712.md"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(markdown_report(data), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, indent=2))


if __name__ == "__main__":
    main()
