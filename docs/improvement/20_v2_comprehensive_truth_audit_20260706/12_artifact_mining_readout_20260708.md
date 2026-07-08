# 2026-07-08 artifact mining 全量抽取分析

本文由 `scripts/analyze_v2_artifact_evidence.py` 从 run artifact 递归抽取生成。它不是替代原始 artifact，而是把 JSON report、case、prompt slice、telemetry 和代码 gate 汇总成可读证据索引。

## 输入与覆盖

| Run | json seen | json loaded | benchmark reports | prompt slices | telemetry files | load errors |
| --- | --- | --- | --- | --- | --- | --- |
| sb2-gpu1-20260708_084458 | 23928 | 23919 | 73 | 1976 | 494 | 9 |
| sb2-gpu1-health-20260708_110413 | 17642 | 17632 | 58 | 1456 | 364 | 10 |

## Stage 状态

| Run | Stage | Exit | Required | Kind | Duration s |
| --- | --- | --- | --- | --- | --- |
| sb2-gpu1-20260708_084458 | 00_env_probe | 0 | yes | text | 0 |
| sb2-gpu1-20260708_084458 | 01_py_compile | 0 | yes | text | 0 |
| sb2-gpu1-20260708_084458 | 02_pytest_full_v2 | 0 | yes | text | 406 |
| sb2-gpu1-20260708_084458 | 03_runtime_smoke | 0 | yes | text | 36 |
| sb2-gpu1-20260708_084458 | r01_04_preflight_api_local | 0 | yes | live_runner | 2 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | 0 | yes | live_runner | 753 |
| sb2-gpu1-20260708_084458 | r01_06_formal_carrier_compare_api_local_memfd | 0 | yes | live_runner | 392 |
| sb2-gpu1-20260708_084458 | r01_07_formal_compare_api_local_memfd | 0 | yes | live_runner | 329 |
| sb2-gpu1-20260708_084458 | r01_08_dev_compare_api_local_memfd | 0 | no | live_runner | 45 |
| sb2-gpu1-20260708_084458 | r01_09_carrier_compare_api_local_memfd | 0 | no | live_runner | 48 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | 0 | no | live_runner | 961 |
| sb2-gpu1-20260708_084458 | r01_11_continuous_replay_api_local | 0 | no | live_runner | 1031 |
| sb2-gpu1-20260708_084458 | r01_12_replay_negative_api_local | 0 | yes | live_runner | 3 |
| sb2-gpu1-20260708_084458 | r01_13_flagship_ablation_api_local | 1 | no | live_runner | 582 |
| sb2-gpu1-health-20260708_110413 | s01_00_base_run_snapshot | 0 | yes | json | 1 |
| sb2-gpu1-health-20260708_110413 | s01_00b_base_artifact_integrity_audit | 1 | yes | json | 0 |
| sb2-gpu1-health-20260708_110413 | s01_00c_base_claim_boundary_audit | 1 | yes | json | 0 |
| sb2-gpu1-health-20260708_110413 | s01_01_container_root_gpu_probe | 0 | yes | json | 2 |
| sb2-gpu1-health-20260708_110413 | s01_02_py_compile_health | 0 | yes | json | 0 |
| sb2-gpu1-health-20260708_110413 | s01_03_targeted_pytest_health | 0 | yes | json | 47 |
| sb2-gpu1-health-20260708_110413 | s01_04_kv_prefix_static_health | 0 | yes | json | 1 |
| sb2-gpu1-health-20260708_110413 | s01_05_import_probe | 0 | yes | json | 1 |
| sb2-gpu1-health-20260708_110413 | s01_06_codeact_bwrap_smoke | 0 | yes | json | 1 |
| sb2-gpu1-health-20260708_110413 | s01_07_codeact_acceptance_api | 0 | yes | codeact | 19 |
| sb2-gpu1-health-20260708_110413 | s01_08_kv_prefix_demo_api_local | 0 | yes | live_runner | 366 |
| sb2-gpu1-health-20260708_110413 | s01_09_vllm_prefix_metrics_probe_skipped | 0 | no | json | 0 |
| sb2-gpu1-health-20260708_110413 | s01_09b_vllm_prefix_alignment_probe_skipped | 0 | no | json | 0 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | 0 | yes | live_runner | 2364 |

## Formal external compare

- source: `work/r01_07_formal_compare_api_local_memfd/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_07_formal_compare_api_local_memfd-cold-start-compare.json#mode_reports[0]:api`
- scope: `formal_registry_25case_5family_compare`
- strict_equal_quality_comparison_valid: `False`
- quality_superiority_comparison_valid: `True`
- formal_external_claim_kind: `quality_superiority`
- serialized_latency_superiority_claim_allowed: `False`
- external fairness: coverage=`True` pass_count=`25.0` failed_case_count=`0.0`
- derived: prompt_reduction=`57.9%` total_reduction=`49.7%` completion_increase=`80.5%` quality_delta=`10`

| Metric | StateBus | External | Delta |
| --- | --- | --- | --- |
| prompt_tokens | 48754 | 115734 | -66980 |
| completion_tokens | 13062 | 7237 | 5825 |
| total_tokens | 61816 | 122971 | -61155 |
| task_ms | - | - | 73103.7 |
| llm_ms | - | - | 37201.9 |
| system_overhead_ms | - | - | 35901.8 |

### Family deltas

| Family | SB quality | External quality | Prompt delta | Completion delta | Total delta | External fail dimensions |
| --- | --- | --- | --- | --- | --- | --- |
| anomaly_detection_v1 | 3/3 | 0/3 | -26045 | 527 | -25518 | {'metric_value_exact': 3} |
| conditional_aggregation_v1 | 4/4 | 0/4 | -33048 | 745 | -32303 | {'metric_value_exact': 4} |
| cross_table_join_analysis_v1 | 5/5 | 5/5 | -2436 | 1194 | -1242 | {} |
| financial_report_analysis | 8/8 | 8/8 | -3090 | 1997 | -1093 | {} |
| multi_period_trend_analysis_v1 | 5/5 | 2/5 | -2361 | 1362 | -999 | {'metric_value_exact': 3} |

### External failed cases

| Task | Family | Reason | Failed dimensions | External total tokens |
| --- | --- | --- | --- | --- |
| formal-trend-001 | multi_period_trend_analysis_v1 | deterministic_checks_failed | metric_value_exact | 2631 |
| formal-trend-005 | multi_period_trend_analysis_v1 | deterministic_checks_failed | metric_value_exact | 2843 |
| formal-trend-002 | multi_period_trend_analysis_v1 | deterministic_checks_failed | metric_value_exact | 2654 |
| formal-agg-002 | conditional_aggregation_v1 | deterministic_checks_failed | metric_value_exact | 10082 |
| formal-agg-004 | conditional_aggregation_v1 | deterministic_checks_failed | metric_value_exact | 13163 |
| formal-agg-003 | conditional_aggregation_v1 | deterministic_checks_failed | metric_value_exact | 12833 |
| formal-agg-001 | conditional_aggregation_v1 | deterministic_checks_failed | metric_value_exact | 10157 |
| formal-anomaly-001 | anomaly_detection_v1 | deterministic_checks_failed | metric_value_exact | 10152 |
| formal-anomaly-002 | anomaly_detection_v1 | deterministic_checks_failed | metric_value_exact | 12749 |
| formal-anomaly-003 | anomaly_detection_v1 | deterministic_checks_failed | metric_value_exact | 12855 |

## Formal internal / layer waterfall

- source: `work/r01_05_formal_api_local_memfd/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_05_formal_api_local_memfd-formal-suite.json`
- L3 cases: `25.0` quality pass: `25.0`
- state pool used: `memfd` memfd transfers: `25.0` bytes: `247076.0`

| Layer | Quality | LLM prompt bytes | Visible bytes | Raw evidence bytes | Semantic transfers | memfd transfers | Reuse gain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| L0 | 25/25 | 254842 | 180106 | 173736 | 0 | 0 | 0 |
| L1 | 25/25 | 243692 | 180106 | 173736 | 0 | 0 | 0 |
| L2 | 25/25 | 139732 | 77304 | 70934 | 25 | 25 | 0 |
| L3 | 25/25 | 139732 | 77304 | 70934 | 25 | 25 | 0 |

## Continuous / replay summaries

| Stage | Source | Families | Rounds | Quality families | Replay families | Validated replay | Exact replay | L3 reuse gain | Missing targets |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r01_10_continuous_api_local | artifacts/stages/r01_10_continuous_api_local/stdout.json | 3 | 30 | 2 | 0 | 4 | 5 | 9 | 2 |
| r01_11_continuous_replay_api_local | artifacts/stages/r01_11_continuous_replay_api_local/stdout.json | 3 | 30 | 2 | 2 | 18 | 2 | 20 | 1 |
| r01_10_continuous_api_local | work/r01_10_continuous_api_local/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_10_continuous_api_local-continuous.json | 3 | 30 | 2 | 0 | 4 | 5 | 9 | 2 |
| r01_11_continuous_replay_api_local | work/r01_11_continuous_replay_api_local/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_11_continuous_replay_api_local-continuous-replay.json | 3 | 30 | 2 | 2 | 18 | 2 | 20 | 1 |
| s01_10_flagship_ablation_api_local | work/s01_10_flagship_ablation_api_local/runtime/flagship-ablation/continuous/benchmark_reports/sb2-gpu1-health-20260708_110413-s01_10_flagship_ablation_api_local-non-text-flagship-ablation-continuous.json | 3 | 30 | 3 | 1 | 2 | 7 | 9 | 0 |
| s01_10_flagship_ablation_api_local | work/s01_10_flagship_ablation_api_local/runtime/flagship-ablation/continuous-replay/benchmark_reports/sb2-gpu1-health-20260708_110413-s01_10_flagship_ablation_api_local-non-text-flagship-ablation-continuous-replay.json | 3 | 30 | 3 | 3 | 17 | 3 | 20 | 0 |

## Flagship non-text state stress

- source: `artifacts/stages/s01_10_flagship_ablation_api_local/stdout.json`
- stress pass: `5/6`; claimable families: `5`; diagnostic-only: `1`
- total_llm_prompt_saved_by_state_ref_bytes: `21325.0`
- total_prompt_visible_saved_by_state_ref_bytes: `7875.0`

| Family | Scope | Pass | LLM saved | Visible saved | Interpretation | Fail reasons |
| --- | --- | --- | --- | --- | --- | --- |
| csv_correlation_replay_v1 | non_text_state_claimable | True | 12980 | 7242 | non_text_state_transfer_has_extra_prompt_saving |  |
| long_doc_metric_replay_v1 | non_text_state_claimable | True | 3885 | 615 | non_text_state_transfer_has_extra_prompt_saving |  |
| long_doc_table_v1 | non_text_state_claimable | True | 941 | 18 | non_text_state_transfer_has_extra_prompt_saving |  |
| cross_period_financial_v1 | non_text_state_claimable | True | 1957 | 0 | non_text_state_transfer_has_scaffolding_saving |  |
| csv_table_profile_v1 | non_text_state_claimable | True | 1562 | 0 | non_text_state_transfer_has_scaffolding_saving |  |
| incident_diagnosis_v2 | diagnostic_only | False | 0 | 0 | semantic_selection_dominates_this_family | no_extra_state_ref_prompt_saving_vs_t2 |

## KV prefix / CodeAct supplement

- source: `artifacts/stages/s01_08_kv_prefix_demo_api_local/stdout.json`
- L3 quality: `10.0/10.0` reuse_gain=`6.0`
- corpus_prefix_reuse_count=`8.0` corpus_prefill_saved_estimate=`2144.0` engine_local_prefill_saved_estimate=`2680.0`
- replay_headline=`False` replay_gate_reason=`missing_target_replay_rounds`

- CodeAct source: `artifacts/stages/s01_07_codeact_acceptance_api/stdout.json`
- success: `5/5` target_met=`True` sandbox_required=`bwrap`

## Workspace-level prompt slice aggregate

| Stage | Role | Count | Prompt bytes | Scaffolding | Visible | External evidence | Non-external visible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s01_10_flagship_ablation_api_local | planner | 324 | 931045 | 178080 | 752965 | 742735 | 10230 |
| s01_10_flagship_ablation_api_local | retriever | 324 | 743459 | 263151 | 480308 | 411814 | 68494 |
| s01_10_flagship_ablation_api_local | summarizer | 324 | 739451 | 171514 | 567937 | 411814 | 156123 |
| s01_10_flagship_ablation_api_local | executor | 324 | 637638 | 263241 | 374397 | 305903 | 68494 |
| r01_11_continuous_replay_api_local | planner | 120 | 393449 | 69249 | 324200 | 324200 | 0 |
| r01_11_continuous_replay_api_local | retriever | 120 | 335252 | 103041 | 232211 | 204742 | 27469 |
| r01_10_continuous_api_local | planner | 120 | 334247 | 65259 | 268988 | 260804 | 8184 |
| r01_11_continuous_replay_api_local | summarizer | 120 | 331135 | 65442 | 265693 | 204742 | 60951 |
| s01_08_kv_prefix_demo_api_local | planner | 40 | 319103 | 22763 | 296340 | 296340 | 0 |
| r01_11_continuous_replay_api_local | executor | 120 | 292800 | 100493 | 192307 | 164838 | 27469 |
| r01_10_continuous_api_local | summarizer | 120 | 276267 | 64170 | 212097 | 160898 | 51199 |
| r01_10_continuous_api_local | retriever | 120 | 267115 | 87488 | 179627 | 160898 | 18729 |
| r01_10_continuous_api_local | executor | 120 | 237344 | 86092 | 151252 | 132523 | 18729 |
| r01_05_formal_api_local_memfd | planner | 100 | 225546 | 51810 | 173736 | 173736 | 0 |
| s01_08_kv_prefix_demo_api_local | summarizer | 40 | 216494 | 23171 | 193323 | 169590 | 23733 |
| s01_08_kv_prefix_demo_api_local | retriever | 40 | 212391 | 32100 | 180291 | 169590 | 10701 |
| r01_13_flagship_ablation_api_local | planner | 70 | 198271 | 37779 | 160492 | 152308 | 8184 |
| r01_05_formal_api_local_memfd | retriever | 100 | 192924 | 80104 | 112820 | 112820 | 0 |
| s01_08_kv_prefix_demo_api_local | executor | 40 | 190161 | 30690 | 159471 | 148770 | 10701 |
| r01_05_formal_api_local_memfd | summarizer | 100 | 189927 | 51627 | 138300 | 112820 | 25480 |
| r01_05_formal_api_local_memfd | executor | 100 | 169601 | 79637 | 89964 | 89964 | 0 |
| r01_13_flagship_ablation_api_local | retriever | 70 | 162114 | 63236 | 98878 | 93074 | 5804 |
| r01_13_flagship_ablation_api_local | summarizer | 70 | 151608 | 36302 | 115306 | 93074 | 22232 |
| r01_13_flagship_ablation_api_local | executor | 70 | 150289 | 64735 | 85554 | 79750 | 5804 |

## Code gate anchors

| Gate | Code | Pattern |
| --- | --- | --- |
| external fairness gate | `v2/benchmark/comparator_runner.py:116` | `def _fairness_manifest` |
| quality superiority gate | `v2/benchmark/comparator_runner.py:300` | `def _mode_quality_superiority_comparison_valid` |
| formal efficiency gate | `v2/benchmark/comparator_runner.py:260` | `def _mode_formal_efficiency_claim_allowed` |
| serialized latency gate | `v2/benchmark/comparator_runner.py:645` | `serialized_latency_superiority_claim_allowed` |
| fixed-answer quality floor | `v2/benchmark/scoring.py:69` | `quality_floor_pass=` |
| external pure text fairness | `v2/benchmark/external_text_baseline.py:116` | `def _fairness_gate` |
| json role completion | `v2/runtime/role_path.py:763` | `def _complete_json_role` |
| replay admissibility | `v2/benchmark/continuous_runner.py:359` | `eligible_for_replay_headline` |
| flagship non-text stress | `v2/benchmark/flagship_ablation.py:212` | `def _non_text_state_stress_summary` |
| kv reuse analysis | `v2/benchmark/kv_analysis.py:9` | `KV_ANALYSIS_SCHEMA_VERSION` |

## 综合判断

- 最强证据仍是 full-registry external compare 的 quality-superiority：StateBus 25/25，external 15/25，fairness gate 25/25。失败集中在 external `metric_value_exact=0`，说明收益核心是结构化数值投影和 artifact 可审计化。
- token 结论必须拆开读：prompt/total 明显下降，但 completion 明显上升。completion 上升来自严格 JSON role surface 和 `summary_json`/audit/replay 需要的结构字段。
- latency 不能 claim。抽取结果和代码 gate 都指向同一结论：`serialized_latency_superiority_claim_allowed=false`，且本轮 task/LLM/system overhead delta 都为正。
- replay 结论应以 validated replay 为主，exact replay 为较强子集；`long_doc_metric_replay_v1` round 7 是当前 replay-headline 缺口。
- non-text StateRef 有 family-level 正证据，但不是 universal：5 个 claimable families 通过，`incident_diagnosis_v2` 是诊断负例。
- KV prefix 当前只是 engine-local prefix identity/scheduling estimate；vLLM metrics/TTFT skipped，不能写真实 prefix-cache hit 或 KV tensor transfer。
