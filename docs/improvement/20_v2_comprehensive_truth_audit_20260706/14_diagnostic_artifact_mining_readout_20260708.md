# 2026-07-08 diagnostic artifact mining

本文由 `scripts/diagnose_v2_artifact_mining.py` 从既有 run artifacts 生成。它不是“全面抽取”的 headline 汇总，而是面向问题定位的诊断层：latency decomposition、route miss forensic、completion/schema inflation。

## 覆盖

| Run | events files | event lines | facts files | fact lines | stages | errors |
| --- | --- | --- | --- | --- | --- | --- |
| sb2-gpu1-20260708_084458 | 494 | 14791 | 494 | 11776 | 8 | 0 |
| sb2-gpu1-health-20260708_110413 | 364 | 10788 | 364 | 8604 | 2 | 0 |

## Latency Decomposition

- formal external source: `work/r01_07_formal_compare_api_local_memfd/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_07_formal_compare_api_local_memfd-cold-start-compare.json#mode_reports[0]`
- task_ms_delta: `73103.7`; llm_ms_delta: `37201.9`; system_overhead_ms_delta: `35901.8`
- known StateBus stage-ms total from telemetry summary: `26138.7`

| Formal delta | Value | Interpretation |
| --- | --- | --- |
| task_ms_delta | 73103.7 | StateBus slower end-to-end in this live run |
| llm_ms_delta | 37201.9 | provider LLM wall time also higher |
| system_overhead_ms_delta | 35901.8 | non-LLM runtime overhead also higher |
| codeact_execution_stage_ms | 22389.2 | StateBus-only executable artifact path |
| prompt_tokens_delta | -66980 | -57.9% |
| completion_tokens_delta | 5825 | 80.5% |
| llm_total_tokens_delta | -61155 | -49.7% |

### Family-Level Latency Components

| Family | Cases | Task delta | LLM delta | Overhead delta | CodeAct | Persist | Memfd bytes | Telemetry | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| anomaly_detection_v1 | 3 | 7267.3 | 3254.4 | 4012.9 | 2752.2 | 96.9 | 29691 | 10.9 | 210.5 |
| conditional_aggregation_v1 | 4 | 13319.2 | 7633.5 | 5685.7 | 3683.1 | 107.4 | 39596 | 13.5 | 214.4 |
| cross_table_join_analysis_v1 | 5 | 12422.4 | 6552.1 | 5870.4 | 4390.5 | 143.5 | 49372 | 45.7 | 338.4 |
| financial_report_analysis | 8 | 24841.4 | 10584.0 | 14257.4 | 7194.3 | 225.1 | 79025 | 48.5 | 522.3 |
| multi_period_trend_analysis_v1 | 5 | 15253.4 | 9177.8 | 6075.5 | 4369.2 | 165.6 | 49392 | 60.7 | 384.7 |

### Slowest Formal Case Deltas

| Task | Family | Task delta | LLM delta | Overhead delta | CodeAct | Persist | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- |
| benchmark-sample-1 | financial_report_analysis | 8803.6 | 2751.4 | 6052.2 | 902.9 | 26.9 | 54.1 |
| formal-agg-004 | conditional_aggregation_v1 | 3912.7 | 2457.1 | 1455.6 | 997.8 | 26.8 | 53.1 |
| formal-agg-002 | conditional_aggregation_v1 | 3807.7 | 2464.2 | 1343.5 | 884.9 | 27.2 | 56.1 |
| formal-trend-001 | multi_period_trend_analysis_v1 | 3553.9 | 2365.9 | 1188.0 | 899.5 | 25.9 | 67.3 |
| formal-trend-002 | multi_period_trend_analysis_v1 | 3534.8 | 2246.9 | 1287.9 | 873.6 | 26.3 | 68.1 |
| formal-join-001 | cross_table_join_analysis_v1 | 3482.0 | 2264.9 | 1217.1 | 905.8 | 25.3 | 66.5 |
| formal-anomaly-001 | anomaly_detection_v1 | 3432.4 | 2160.9 | 1271.5 | 881.6 | 30.0 | 55.6 |
| benchmark-sample-7 | financial_report_analysis | 3416.2 | 2140.7 | 1275.6 | 941.8 | 44.7 | 104.2 |
| formal-join-004 | cross_table_join_analysis_v1 | 3189.1 | 2023.5 | 1165.6 | 873.2 | 27.9 | 68.7 |
| formal-trend-004 | multi_period_trend_analysis_v1 | 3084.8 | 1913.2 | 1171.6 | 859.7 | 29.4 | 70.9 |

### StateBus Telemetry Summary Top

| StateBus stage metric | ms |
| --- | --- |
| codeact_execution_stage_ms | 22389.2 |
| runtime_driver_stage_ms | 1378.6 |
| persist_and_reload_stage_ms | 738.5 |
| persist_bundle_write_stage_ms | 524.8 |
| control_plane_exchange_stage_ms | 160.4 |
| persist_core_reload_stage_ms | 136.9 |
| workspace_input_stage_ms | 109.3 |
| runtime_commit_finalize_stage_ms | 93.3 |
| telemetry_emit_stage_ms | 91.2 |
| telemetry_event_write_stage_ms | 72.9 |
| runtime_non_executor_stage_ms | 63.1 |
| persist_integrity_check_stage_ms | 53.1 |
| runtime_data_plane_event_stage_ms | 47.0 |
| runtime_signature_stage_ms | 39.2 |
| planner_runtime_stage_ms | 32.3 |

### Runtime JSONL Stage Totals

| Metric | ms |
| --- | --- |
| persist_and_reload_stage_ms | 24461.5 |
| persist_bundle_write_stage_ms | 16644.6 |
| persist_core_reload_stage_ms | 4723.4 |
| runtime_commit_finalize_stage_ms | 4049.3 |
| control_plane_exchange_stage_ms | 3273.8 |
| persist_integrity_check_stage_ms | 1817.6 |
| runtime_non_executor_stage_ms | 1804.5 |
| runtime_data_plane_event_stage_ms | 1191.4 |
| runtime_post_executor_stage_ms | 1131.3 |
| planner_runtime_stage_ms | 907.9 |
| runtime_replay_ledger_stage_ms | 862.0 |
| persist_session_ledger_reload_stage_ms | 575.3 |
| retriever_runtime_stage_ms | 521.9 |
| executor_state_machine_stage_ms | 486.3 |
| persist_retrieval_verification_stage_ms | 454.7 |
| summarizer_runtime_stage_ms | 374.7 |
| persist_semantic_manifest_reload_stage_ms | 77.8 |
| registry_query_stage_ms | 0 |

### Runtime JSONL Component Aggregates

| Run | Stage | Lane | CodeAct | Persist | Memfd bytes | Telemetry | Workspace | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sb2-gpu1-20260708_084458 | r01_07_formal_compare_api_local_memfd | api/statebus/formal-trend-005 | 0 | 58.3 | 9867 | 0 | 0 | 22.8 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | csv_table_profile/L2/csv-profile-010 | 0 | 54.9 | 0 | 0 | 0 | 11.9 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | L1/benchmark-sample-8 | 0 | 51.2 | 0 | 0 | 0 | 13.3 |
| sb2-gpu1-20260708_084458 | r01_11_continuous_replay_api_local | long_doc_metric_replay/L0/replay-longdoc-006 | 0 | 50.8 | 0 | 0 | 0 | 19.6 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | L1/benchmark-sample-5 | 0 | 50.1 | 0 | 0 | 0 | 12.5 |
| sb2-gpu1-20260708_084458 | r01_13_flagship_ablation_api_local | flagship-ablation/continuous/csv_table_profile/L1/csv-profile-006 | 0 | 49.5 | 0 | 0 | 0 | 17.9 |
| sb2-gpu1-20260708_084458 | r01_13_flagship_ablation_api_local | flagship-ablation/fixed-ladder/L0/fixed-answer-worker-001 | 0 | 49.4 | 0 | 0 | 0 | 14.8 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | long_doc_table/L0/longdoc-008 | 0 | 49.2 | 0 | 0 | 0 | 10.5 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | long_doc_table/L1/longdoc-009 | 0 | 48.9 | 0 | 0 | 0 | 10.3 |
| sb2-gpu1-20260708_084458 | r01_08_dev_compare_api_local_memfd | api/statebus/fixed-answer-auth-001 | 0 | 48.2 | 9889 | 0 | 0 | 15.2 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | L0/formal-trend-005 | 0 | 48.2 | 0 | 0 | 0 | 18.9 |
| sb2-gpu1-20260708_084458 | r01_11_continuous_replay_api_local | cross_period_financial/L3/cross-period-008 | 0 | 48.1 | 0 | 0 | 0 | 23.0 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-text-semantic-selection/csv_table_profile_v1/csv-profile-001 | 0 | 66.6 | 0 | 0 | 0 | 11.9 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay-text-semantic-selection/csv_correlation_replay_v1/replay-csv-007 | 0 | 66.2 | 0 | 0 | 0 | 17.3 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L3/replay-longdoc-006 | 0 | 63.8 | 0 | 0 | 0 | 22.2 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/cross_period_financial/L2/cross-period-010 | 0 | 58.2 | 0 | 0 | 0 | 10.7 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-text-semantic-selection/incident_diagnosis_v2/incident-010 | 0 | 52.5 | 0 | 0 | 0 | 10.1 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L1/replay-longdoc-003 | 0 | 50.8 | 0 | 0 | 0 | 10.9 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L1/replay-longdoc-006 | 0 | 50.5 | 0 | 0 | 0 | 23.9 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L3/replay-longdoc-003 | 0 | 49.6 | 0 | 0 | 0 | 14.3 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L3/replay-longdoc-002 | 0 | 48.4 | 0 | 0 | 0 | 17.2 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/csv_correlation_replay/L2/replay-csv-007 | 0 | 48.1 | 0 | 0 | 0 | 16.5 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L0/replay-longdoc-002 | 0 | 47.9 | 0 | 0 | 0 | 20.4 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | flagship-ablation/continuous-replay/long_doc_metric_replay/L0/replay-longdoc-008 | 0 | 47.5 | 0 | 0 | 0 | 10.8 |

### Runtime Event Lifecycle By Role

| Run | Stage | Role | Count | Sum ms | Max ms |
| --- | --- | --- | --- | --- | --- |
| sb2-gpu1-20260708_084458 | r01_07_formal_compare_api_local_memfd | planner | 25 | 10.8 | 8.7 |
| sb2-gpu1-20260708_084458 | r01_07_formal_compare_api_local_memfd | executor | 25 | 7.6 | 1.0 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | executor | 30 | 7.6 | 0.5 |
| sb2-gpu1-20260708_084458 | r01_11_continuous_replay_api_local | executor | 30 | 7.2 | 0.4 |
| sb2-gpu1-20260708_084458 | r01_06_formal_carrier_compare_api_local_memfd | executor | 25 | 7.1 | 0.6 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | executor | 25 | 6.9 | 0.6 |
| sb2-gpu1-20260708_084458 | r01_13_flagship_ablation_api_local | executor | 19 | 4.9 | 0.4 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | planner | 30 | 2.5 | 0.2 |
| sb2-gpu1-20260708_084458 | r01_07_formal_compare_api_local_memfd | retriever | 25 | 2.4 | 0.5 |
| sb2-gpu1-20260708_084458 | r01_11_continuous_replay_api_local | planner | 30 | 2.4 | 0.1 |
| sb2-gpu1-20260708_084458 | r01_05_formal_api_local_memfd | planner | 25 | 2.3 | 0.1 |
| sb2-gpu1-20260708_084458 | r01_10_continuous_api_local | retriever | 30 | 2.3 | 0.1 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | executor | 63 | 16.0 | 0.5 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | planner | 63 | 5.3 | 0.2 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | retriever | 63 | 5.0 | 0.2 |
| sb2-gpu1-health-20260708_110413 | s01_10_flagship_ablation_api_local | summarizer | 63 | 4.4 | 0.4 |
| sb2-gpu1-health-20260708_110413 | s01_08_kv_prefix_demo_api_local | executor | 10 | 2.7 | 0.4 |
| sb2-gpu1-health-20260708_110413 | s01_08_kv_prefix_demo_api_local | planner | 10 | 0.9 | 0.1 |
| sb2-gpu1-health-20260708_110413 | s01_08_kv_prefix_demo_api_local | retriever | 10 | 0.9 | 0.1 |
| sb2-gpu1-health-20260708_110413 | s01_08_kv_prefix_demo_api_local | summarizer | 10 | 0.6 | 0.1 |

判断：本轮 latency 负结果不是单一原因。formal compare 的 LLM delta 和 system overhead delta 都为正；case/family 分解显示 CodeAct 是最大的 StateBus-only 显性成本，persist/reload、runtime driver、workspace IO、telemetry、memfd accounting 也是真实开销。JSONL lifecycle 只反映 runtime event 间隔，不能替代 provider LLM timing。

## Completion / Schema Inflation

| Token metric | StateBus | External | Delta | Delta vs external |
| --- | --- | --- | --- | --- |
| prompt_tokens | 48754 | 115734 | -66980 | -57.9% |
| completion_tokens | 13062 | 7237 | 5825 | 80.5% |
| llm_total_tokens | 61816 | 122971 | -61155 | -49.7% |

| Family | SB quality | External quality | Prompt delta | Completion delta | Total delta | SB avg keys | External avg keys |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anomaly_detection_v1 | 3/3 | 0/3 | -26045 | 527 | -25518 | 25.3 | 9 |
| conditional_aggregation_v1 | 4/4 | 0/4 | -33048 | 745 | -32303 | 25 | 9 |
| cross_table_join_analysis_v1 | 5/5 | 5/5 | -2436 | 1194 | -1242 | 25.2 | 9 |
| financial_report_analysis | 8/8 | 8/8 | -3090 | 1997 | -1093 | 20 | 9 |
| multi_period_trend_analysis_v1 | 5/5 | 2/5 | -2361 | 1362 | -999 | 24.4 | 9 |

### Largest Completion Deltas

| Task | Family | Prompt delta | Completion delta | SB completion | External completion |
| --- | --- | --- | --- | --- | --- |
| formal-agg-004 | conditional_aggregation_v1 | -9870 | 341 | 634 | 293 |
| formal-join-001 | cross_table_join_analysis_v1 | -480 | 333 | 641 | 308 |
| formal-trend-001 | multi_period_trend_analysis_v1 | -476 | 333 | 637 | 304 |
| formal-agg-002 | conditional_aggregation_v1 | -6610 | 324 | 660 | 336 |
| formal-join-002 | cross_table_join_analysis_v1 | -469 | 307 | 637 | 330 |
| formal-trend-004 | multi_period_trend_analysis_v1 | -476 | 300 | 587 | 287 |
| formal-anomaly-001 | anomaly_detection_v1 | -6771 | 299 | 588 | 289 |
| benchmark-sample-8 | financial_report_analysis | -391 | 297 | 523 | 226 |
| formal-join-003 | cross_table_join_analysis_v1 | -463 | 279 | 567 | 288 |
| benchmark-sample-5 | financial_report_analysis | -363 | 271 | 513 | 242 |

### Role Prompt Bytes

| Role | StateBus | External | Delta |
| --- | --- | --- | --- |
| planner | 56058 | 49832 | 6226 |
| retriever | 31757 | 179217 | -147460 |
| executor | 19652 | 40217 | -20565 |
| summarizer | 32265 | 21241 | 11024 |

### Retry / Fallback Checks

| Metric | StateBus | External | Delta |
| --- | --- | --- | --- |
| attempt_count | 25 | 0 | 25 |
| replan_history_count | 0 | 0 | 0 |
| runtime_fallback_count | 0 | 0 | 0 |
| codeact_sandbox_fallback_count | 0 | 0 | 0 |
| state_pool_fallback_count | 0 | 0 | 0 |
| llm_call_count | 100 | 100 | 0 |

### Schema Surface

| Item | Value |
| --- | --- |
| StateBus-only top-level keys | acme_revenue_value, acme_trend_direction, acme_trend_values, action_contract, baro_outlier_count, beta_revenue_value, beta_trend_direction, beta_trend_values, cleaned_table_ref, codeact_action_count, codeact_plan_hash, codeact_stage_count, consumed_artifact_refs, consumed_strategy_refs, csv_path, csv_source_path, dataset_id, delta_pct, delta_value, document_path, document_source_path, downgraded_execution_goal, evidence_pack_hash, execution_goal, gap_value, groupby_artifact_ref, intent_op, max_deaths_country |
| Shared top-level keys | metric_name, metric_value, revenue_value, route, selected_doc_hashes, summary_text, supporting_doc_ids, task_id, tool_name |

判断：completion token split 目前只有 total，不是 per-role。现有证据足以排除“重试导致 completion 膨胀”这一主因：LLM call count 没增加，fallback/replan 为 0 或不构成解释。更合理的解释是 StateBus 输出面更严格、更可审计，要求 route/tool/doc/value 之外保留 artifact、handoff、strategy、runtime hash、selected docs、summary 等字段；这让 completion 上升，但 prompt 与 total tokens 仍显著下降。

## Route Miss Forensic

- stage: `r01_06_formal_carrier_compare_api_local_memfd` task: `formal-trend-002`
- structured route/tool: `generate_chart` / `table_retriever`
- text route/tool: `compare_metric` / `table_retriever`
- structured action_contract: `generate_chart`; text action_contract: `materialize_validated_artifact`
- structured trend values/direction: `72,79,87` / `increasing`
- text trend values/direction: `72,79,87` / `increasing`

| Lane | Quality | Route exact | Tool exact | Metric name | Metric value | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| structured | False | 0.0 | 1.0 | 1.0 | 1.0 | fact_coverage_failed |
| text | True | 1.0 | 1.0 | 1.0 | 1.0 |  |

### Visible Candidate Keys

| Lane | Candidate keys |
| --- | --- |
| structured | compare_metric::table_retriever, summarize_risk::semantic_retriever, generate_chart::table_retriever |
| text | compare_metric::table_retriever, summarize_risk::semantic_retriever, generate_chart::table_retriever |

### Prompt Slice Comparison

| Role | Structured prompt | Text prompt | Delta | Structured scaffold | Text scaffold | Structured visible | Text visible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| planner | 1944 | 2000 | -56 | 530 | 586 | 1414 | 1414 |
| retriever | 2162 | 2276 | -114 | 748 | 862 | 1414 | 1414 |
| executor | 2096 | 2291 | -195 | 682 | 877 | 1414 | 1414 |
| summarizer | 2261 | 2248 | 13 | 542 | 529 | 1719 | 1719 |

### Raw Output Shape

| Lane | Top-level keys | Planner step actions |
| --- | --- | --- |
| structured | action_contract, consumed_artifact_refs, consumed_strategy_refs, dataset_id, document_path, document_source_path, downgraded_execution_goal, evidence_pack_hash, execution_goal, intent_op, planner_plan_payload, produced_artifact_refs, produced_strategy_refs, query_text, retrieval_log_hash, route, selected_doc_hashes, summary_text, supporting_doc_ids, task_family, task_id, tool_name, trend_direction, trend_values |  |
| text | action_contract, consumed_artifact_refs, consumed_strategy_refs, dataset_id, document_path, document_source_path, downgraded_execution_goal, evidence_pack_hash, execution_goal, intent_op, planner_plan_payload, produced_artifact_refs, produced_strategy_refs, query_text, retrieval_log_hash, route, selected_doc_hashes, summary_text, supporting_doc_ids, task_family, task_id, tool_name, trend_direction, trend_values | retrieve_table, compute_trend, generate_summary |

### Structured Sidecar Evidence

| Item | Value |
| --- | --- |
| rerank selected | ctx-section-1, ctx-section-2, ctx-section-5, fact-revenue-1, fact-revenue-2, fact-revenue-3, hint-1, hint-2 |
| candidate buckets | {"hard_fact": 3, "lexical_hint": 2, "semantic_context": 3} |
| fact validator | {"details": {"expected_facts": {"metric_name": "trend_direction", "metric_value": "increasing", "trend_direction": "increasing"}, "replay_class": "disallowed"}, "passed": false, "reason": "fact_coverage_failed"} |

### Diagnosis

- structured route `generate_chart` differs from text route `compare_metric`
- structured route exists in visible candidate keys, so this is a wrong visible-choice selection rather than hidden metadata leakage
- tool selection matches; failure is route-level
- computed trend values match; numeric execution is not the failing dimension

修复方向：给 structured carrier 的 route selection/normalization 加 targeted regression。这个 case 的 tool/doc/value/trend 都对，失败集中在 route label 选择从 `compare_metric` 偏到 `generate_chart`。

## Limits

- This diagnostic pass reuses existing artifacts only; it does not rerun experiments.
- runtime_events.jsonl lifecycle durations are useful for runtime event timing but are not a substitute for provider-reported LLM usage metrics.
- Per-role completion-token split is not currently persisted; total completion inflation is still visible in formal comparator reports.
- formal artifacts expose total completion tokens but not reliable per-role completion-token split
- role-level completion inflation is inferred from total completion tokens, output shape, and strict JSON role code path
