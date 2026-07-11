# StateBus v2 local API non-KV follow-up deep mining readout

- Generated at: `2026-07-09T12:25:50.424188+00:00`
- Scanned files: `124157`
- Stage rows: `56`; phase rows: `4`
- Stage stdout JSON: `48`
- Benchmark report JSON: `304`
- Telemetry JSON: `2373`
- Prompt slice JSON: `9492`
- JSON load errors: `2`

## Stage Failures
| Run | Stage/Phase | Required | Exit | Optional Fail | Required Fail | Categories |
| --- | --- | --- | --- | --- | --- | --- |
| core | lr01_14_formal_compare_latency_rerun_api_local_memfd | true | 1 | false | true | traceback,json_parse_failure,value_error,empty_output |
| followup | flagship_family_diag | false | 1 | true | false |  |
| followup | extras | false | 1 | true | false |  |
| extras | x17b_continuous_gridops_world_api_local | false | 1 | true | false | traceback,value_error,unsupported_family |

## Error Taxonomy
| Category | Count | Example Run | Example Stage | Example Path |
| --- | --- | --- | --- | --- |
| traceback | 6 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |
| value_error | 6 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |
| stdout_empty | 4 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |
| json_parse_failure | 3 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |
| empty_output | 3 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |
| optional_stage_fail | 3 | followup | flagship_family_diag |  |
| unsupported_family | 3 | extras | x17b_continuous_gridops_world_api_local | /home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x17b_continuous_gridops_world_api_local/console.log |
| validator_failed | 3 | core |  | artifacts/console.log |
| stage_fail | 2 | core |  | artifacts/console.log |
| required_stage_fail | 1 | core | lr01_14_formal_compare_latency_rerun_api_local_memfd | /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log |

## Claim Gates
| Run | Stage | Strict Equal | Quality Superiority | Formal Claim | Latency Claim | Restriction |
| --- | --- | --- | --- | --- | --- | --- |
| core | r01_07_formal_compare_api_local_memfd | false | true | true | 0 | formal_quality_superiority_external_compare |
| core | r01_06_formal_carrier_compare_api_local_memfd |  |  |  |  |  |
| core | lr03_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | 0 | external_compare_debug_only_until_strict_or_quality_gate_passes |
| core | r01_08_dev_compare_api_local_memfd | true | false | false | 0 | dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority |
| core | lr02_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | 0 | external_compare_debug_only_until_strict_or_quality_gate_passes |
| core | r01_07_formal_compare_api_local_memfd | false | true | true | false | formal_quality_superiority_external_compare |
| core | r01_07_formal_compare_api_local_memfd | 0 | 1 |  |  |  |
| core | r01_07_formal_compare_api_local_memfd |  |  |  |  | dev_fixed_answer_external_fairness_only_not_formal_financial_superiority |
| core | r01_06_formal_carrier_compare_api_local_memfd |  |  |  |  |  |
| core | lr03_14_formal_compare_latency_rerun_api_local_memfd | 0 | 0 |  |  |  |
| core | lr03_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | false | external_compare_debug_only_until_strict_or_quality_gate_passes |
| core | lr03_14_formal_compare_latency_rerun_api_local_memfd |  |  |  |  | dev_fixed_answer_external_fairness_only_not_formal_financial_superiority |
| core | r01_08_dev_compare_api_local_memfd | 1 | 0 |  |  |  |
| core | r01_08_dev_compare_api_local_memfd | true | false | false | false | dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority |
| core | r01_08_dev_compare_api_local_memfd |  |  |  |  | dev_fixed_answer_external_fairness_only_not_formal_financial_superiority |
| core | lr02_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | false | external_compare_debug_only_until_strict_or_quality_gate_passes |
| core | lr02_14_formal_compare_latency_rerun_api_local_memfd | 0 | 0 |  |  |  |
| core | lr02_14_formal_compare_latency_rerun_api_local_memfd |  |  |  |  | dev_fixed_answer_external_fairness_only_not_formal_financial_superiority |
| lr01 | lr01_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | 0 | external_compare_debug_only_until_strict_or_quality_gate_passes |
| lr01 | lr01_14_formal_compare_latency_rerun_api_local_memfd | false | false | false | false | external_compare_debug_only_until_strict_or_quality_gate_passes |
| lr01 | lr01_14_formal_compare_latency_rerun_api_local_memfd | 0 | 0 |  |  |  |
| lr01 | lr01_14_formal_compare_latency_rerun_api_local_memfd |  |  |  |  | dev_fixed_answer_external_fairness_only_not_formal_financial_superiority |
| extras | x25_formal_carrier_compare_api_local_memfd_benchmark_balanced |  |  |  |  |  |
| extras | x22_formal_carrier_compare_api_local_shared_memory |  |  |  |  |  |
| extras | x23_formal_compare_api_local_shared_memory | false | false | false | 0 | external_compare_debug_only_until_strict_or_quality_gate_passes |
| extras | x13_dev_compare_api_local_memfd | true | false | false | 0 | dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority |
| extras | x26_formal_compare_api_local_memfd_benchmark_balanced | false | false | false | 0 | external_compare_debug_only_until_strict_or_quality_gate_passes |
| extras | x25_formal_carrier_compare_api_local_memfd_benchmark_balanced |  |  |  |  |  |
| extras | x22_formal_carrier_compare_api_local_shared_memory |  |  |  |  |  |
| extras | x23_formal_compare_api_local_shared_memory | 0 | 0 |  |  |  |

## Flagship Stress
### Full follow-up flagship
| Family | Pass | Reasons | Quality | Replay | LLM Saved | Visible Saved |
| --- | --- | --- | --- | --- | --- | --- |
| csv_table_profile_v1 | true | [] | true | false | 7979 | 5295 |
| incident_diagnosis_v2 | false | ["quality_headline_not_eligible"] | false | false | 2614 | 3136 |
| csv_correlation_replay_v1 | true | [] | true | true | 7109 | 6 |
| cross_period_financial_v1 | false | ["no_extra_state_ref_prompt_saving_vs_t2"] | true | true | 0 | 0 |
| long_doc_metric_replay_v1 | false | ["quality_headline_not_eligible", "replay_headline_not_eligible", "no_extra_state_ref_prompt_saving_vs_t2"] | false | false | 0 | 0 |
| long_doc_table_v1 | false | ["no_extra_state_ref_prompt_saving_vs_t2"] | true | false | 0 | 0 |
### Isolated failed-family diagnostics
| Family | Pass | Reasons | Quality | Replay | LLM Saved | Visible Saved |
| --- | --- | --- | --- | --- | --- | --- |
| long_doc_metric_replay_v1 | true | [] | true | true | 10957 | 9434 |
| incident_diagnosis_v2 | false | ["quality_headline_not_eligible"] | false | false | 1931 | 2465 |
| cross_period_financial_v1 | false | ["no_extra_state_ref_prompt_saving_vs_t2"] | true | true | 0 | 0 |

## Cross-Run Comparisons
| Comparison | Finding |
| --- | --- |
| core_lr01_vs_followup_lr01 | hard external empty-output failure disappeared, but claim gates remain false |
| core_flagship_vs_followup_flagship_vs_diag | full follow-up flagship is 2/6 stress pass; isolated diag turns long_doc_metric_replay_v1 into a pass while incident and cross_period still fail different gates |
| extras_shared_memory_vs_memfd_benchmark_balanced | both backends complete formal 25-case paths; transport evidence differs by publish/transfer counters, not by quality headline |
