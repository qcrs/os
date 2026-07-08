# StateBus v2 local+api comprehensive statistics

- Mode: `role_path_mode=api`, `embedding_mode=local`
- Stage count: `14`
- Failed stage count: `1`
- Failed required stage count: `0`
- Activation script: `/usr/local/bin/activate_statebus_container.sh`
- Activation status: `success`
- Python executable: `/usr/bin/python3`

## Failed Required Stages
- none

## Key Metrics

### r01_04_preflight_api_local
- `preflight_ok`: `True`
- `embedding_model_path`: `/statebus/models/Qwen3-Embedding-0.6B`
- `embedding_device`: `cuda:0`
- `llm_config_source`: `/workspace/statebus/project/deploy/statebus_llm.yaml.local`

### r01_05_formal_api_local_memfd
- `suite_id`: `sb2-gpu1-20260708_084458-r01_05_formal_api_local_memfd-formal`
- `role_path_mode`: `api`
- `embedding_mode`: `local`
- `L3_case_count`: `25.0`
- `L3_quality_pass_count`: `25.0`
- `family_count`: `5`
- `state_pool_mode_requested`: `memfd`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `25.0`
- `memfd_publish_count`: `25.0`
- `memfd_bytes_transferred`: `247076.0`
- `semantic_state_transfer_count`: `25.0`
- `shared_memory_publish_count`: `0.0`
- `mmap_publish_count`: `0.0`
- `api_planner_call_count`: `25.0`
- `api_retriever_call_count`: `25.0`
- `api_executor_call_count`: `25.0`
- `api_summarizer_call_count`: `25.0`

### r01_06_formal_carrier_compare_api_local_memfd
- `formal_compare_scope_label`: `formal_registry_25case_5family_text_protocol_compare`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_registry_case_count`: `25`
- `formal_compare_full_registry_coverage`: `True`

### r01_07_formal_compare_api_local_memfd
- `fixed_answer_external_comparison_valid`: `False`
- `external_comparator_claim_scope`: `formal_registry_25case_5family_compare`
- `formal_compare_scope_label`: `formal_registry_25case_5family_compare`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_registry_case_count`: `25`
- `formal_compare_full_registry_coverage`: `True`
- `strict_equal_quality_comparison_valid`: `False`
- `quality_superiority_comparison_valid`: `True`
- `formal_quality_superiority_claim_allowed`: `True`
- `formal_efficiency_superiority_claim_allowed`: `False`
- `formal_external_claim_kind`: `quality_superiority`
- `formal_superiority_claim_allowed`: `True`
- `formal_efficiency_claim_allowed`: `False`
- `serialized_latency_superiority_claim_allowed`: `False`
- `timing_execution_contract`: `serialized_statebus_then_external_within_each_mode_v1`
- `comparator_token_split_schema`: `statebus.comparator.token_split.v1`
- `formal_headline_eligible`: `False`
- `api_comparison_valid`: `0.0`
- `api_strict_equal_quality_comparison_valid`: `0.0`
- `api_quality_superiority_comparison_valid`: `1.0`
- `api_llm_total_tokens_delta`: `-61155.0`
- `api_statebus_prompt_tokens`: `48754.0`
- `api_external_prompt_tokens`: `115734.0`
- `api_prompt_tokens_delta`: `-66980.0`
- `api_statebus_completion_tokens`: `13062.0`
- `api_external_completion_tokens`: `7237.0`
- `api_completion_tokens_delta`: `5825.0`
- `api_statebus_llm_total_tokens`: `61816.0`
- `api_external_llm_total_tokens`: `122971.0`
- `external_fairness_gate_coverage`: `True`
- `no_external_fairness_gate_failures`: `True`
- `external_fairness_gate_pass_count`: `25.0`
- `external_fairness_gate_failed_case_count`: `0.0`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `25.0`

### r01_08_dev_compare_api_local_memfd
- `fixed_answer_external_comparison_valid`: `True`
- `external_comparator_claim_scope`: `dev_fixed_answer_only`
- `formal_compare_scope_label`: `dev_fixed_answer_3case_compare`
- `formal_compare_case_count`: `3`
- `formal_compare_family_count`: `1`
- `formal_registry_case_count`: `25`
- `formal_compare_full_registry_coverage`: `False`
- `strict_equal_quality_comparison_valid`: `True`
- `quality_superiority_comparison_valid`: `False`
- `formal_quality_superiority_claim_allowed`: `False`
- `formal_efficiency_superiority_claim_allowed`: `False`
- `formal_external_claim_kind`: `none`
- `formal_superiority_claim_allowed`: `False`
- `formal_efficiency_claim_allowed`: `False`
- `serialized_latency_superiority_claim_allowed`: `False`
- `timing_execution_contract`: `serialized_statebus_then_external_within_each_mode_v1`
- `comparator_token_split_schema`: `statebus.comparator.token_split.v1`
- `formal_headline_eligible`: `False`
- `api_comparison_valid`: `1.0`
- `api_strict_equal_quality_comparison_valid`: `1.0`
- `api_quality_superiority_comparison_valid`: `0.0`
- `api_llm_total_tokens_delta`: `-1299.0`
- `api_statebus_prompt_tokens`: `3686.0`
- `api_external_prompt_tokens`: `5146.0`
- `api_prompt_tokens_delta`: `-1460.0`
- `api_statebus_completion_tokens`: `1183.0`
- `api_external_completion_tokens`: `1022.0`
- `api_completion_tokens_delta`: `161.0`
- `api_statebus_llm_total_tokens`: `4869.0`
- `api_external_llm_total_tokens`: `6168.0`
- `api_prompt_bytes_delta`: `-5969.0`
- `api_control_bytes_delta`: `-650.0`
- `api_task_ms_delta`: `10994.574713`
- `external_fairness_gate_coverage`: `True`
- `no_external_fairness_gate_failures`: `True`
- `external_fairness_gate_pass_count`: `3.0`
- `external_fairness_gate_failed_case_count`: `0.0`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `3.0`

### r01_10_continuous_api_local
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `L2_semantic_state_transfer_count`: `30.0`
- `L3_reuse_gain`: `9.0`

### r01_11_continuous_replay_api_local
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `replay_target_round_count`: `20.0`
- `replay_observed_round_count`: `19.0`
- `replay_missing_target_round_count`: `1.0`
- `validated_replay_count`: `18.0`
- `validated_downgraded_reuse_count`: `18.0`
- `exact_replay_count`: `2.0`
- `answer_restoration_replay_count`: `0.0`
- `L2_semantic_state_transfer_count`: `30.0`
- `L3_reuse_gain`: `20.0`

### r01_12_replay_negative_api_local
- `audit_pass`: `True`
- `case_count`: `7`


## Compare Case Structured Fields

### r01_07_formal_compare_api_local_memfd
- `benchmark-sample-1` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `revenue=120` legacy revenue `` qf `True`; statebus metric `revenue=120` qf `True`
- `benchmark-sample-7` pass `True` reason `compare_case_trace`; expected `operating_income=19`; external metric `operating_income=19` legacy revenue `` qf `True`; statebus metric `operating_income=19` qf `True`
- `benchmark-sample-2` pass `True` reason `compare_case_trace`; expected `revenue=132`; external metric `revenue=132` legacy revenue `` qf `True`; statebus metric `revenue=132` qf `True`
- `benchmark-sample-6` pass `True` reason `compare_case_trace`; expected `gross_margin=39`; external metric `gross_margin=39` legacy revenue `` qf `True`; statebus metric `gross_margin=39` qf `True`
- `benchmark-sample-3` pass `True` reason `compare_case_trace`; expected `revenue=145`; external metric `revenue=145` legacy revenue `` qf `True`; statebus metric `revenue=145` qf `True`
- `benchmark-sample-4` pass `True` reason `compare_case_trace`; expected `revenue=109`; external metric `revenue=109` legacy revenue `` qf `True`; statebus metric `revenue=109` qf `True`
- `benchmark-sample-8` pass `True` reason `compare_case_trace`; expected `gross_margin=31`; external metric `gross_margin=31` legacy revenue `` qf `True`; statebus metric `gross_margin=31` qf `True`
- `benchmark-sample-5` pass `True` reason `compare_case_trace`; expected `revenue=87`; external metric `revenue=87` legacy revenue `` qf `True`; statebus metric `revenue=87` qf `True`
- `formal-trend-003` pass `True` reason `compare_case_trace`; expected `revenue=22`; external metric `delta_value=22` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-trend-004` pass `True` reason `compare_case_trace`; expected `revenue=15`; external metric `delta_value=15` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-trend-001` pass `False` reason `quality_floor_failure`; expected `revenue=increasing`; external metric `trend_direction=upward` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-trend-005` pass `False` reason `quality_floor_failure`; expected `revenue=increasing`; external metric `acme_trend_direction=up` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-trend-002` pass `False` reason `quality_floor_failure`; expected `revenue=increasing`; external metric `trend_direction=up` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-join-004` pass `True` reason `compare_case_trace`; expected `revenue=increasing`; external metric `acme_trend_direction=increasing` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-join-005` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `acme_revenue_value=120` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-join-003` pass `True` reason `compare_case_trace`; expected `revenue=26`; external metric `gap_value=26` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-join-002` pass `True` reason `compare_case_trace`; expected `revenue=30`; external metric `gap_value=30` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-join-001` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `acme_revenue_value=120` legacy revenue `` qf `True`; statebus metric `None=None` qf `True`
- `formal-agg-002` pass `False` reason `quality_floor_failure`; expected `mean_cases=2081990`; external metric `mean_cases=2000000` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-agg-004` pass `False` reason `quality_floor_failure`; expected `monthly_avg_windspeed.month_1=7.17`; external metric `monthly_avg_windspeed.month_1=None` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-agg-003` pass `False` reason `quality_floor_failure`; expected `mean_windspeed=5.979`; external metric `mean_windspeed=7.78` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-agg-001` pass `False` reason `quality_floor_failure`; expected `percentage_cases_min=36.45`; external metric `percentage_cases_min=30.4` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-anomaly-001` pass `False` reason `quality_floor_failure`; expected `mean_no_of_deaths_with_outliers=10149.43`; external metric `mean_no_of_deaths_with_outliers=None` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-anomaly-002` pass `False` reason `quality_floor_failure`; expected `baro_outlier_count=111`; external metric `baro_outlier_count=0` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`
- `formal-anomaly-003` pass `False` reason `quality_floor_failure`; expected `mean_wind_post=5.76`; external metric `mean_wind_post=7.68` legacy revenue `` qf `False`; statebus metric `None=None` qf `True`

### r01_08_dev_compare_api_local_memfd
- `fixed-answer-auth-001` pass `True` reason `compare_case_trace`; expected `revenue=145`; external metric `revenue=145` legacy revenue `` qf `True`; statebus metric `revenue=145` qf `True`
- `fixed-answer-cache-001` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `revenue=120` legacy revenue `` qf `True`; statebus metric `revenue=120` qf `True`
- `fixed-answer-worker-001` pass `True` reason `compare_case_trace`; expected `revenue=132`; external metric `revenue=132` legacy revenue `` qf `True`; statebus metric `revenue=132` qf `True`


## Stage Log

- `00_env_probe` exit `0` required `1` duration `0s` artifact `-`
- `01_py_compile` exit `0` required `1` duration `0s` artifact `-`
- `02_pytest_full_v2` exit `0` required `1` duration `406s` artifact `-`
- `03_runtime_smoke` exit `0` required `1` duration `36s` artifact `-`
- `r01_04_preflight_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_04_preflight_api_local/stdout.json`
- `r01_05_formal_api_local_memfd` exit `0` required `1` duration `753s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_05_formal_api_local_memfd/stdout.json`
- `r01_06_formal_carrier_compare_api_local_memfd` exit `0` required `1` duration `392s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_06_formal_carrier_compare_api_local_memfd/stdout.json`
- `r01_07_formal_compare_api_local_memfd` exit `0` required `1` duration `329s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_07_formal_compare_api_local_memfd/stdout.json`
- `r01_08_dev_compare_api_local_memfd` exit `0` required `0` duration `45s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_08_dev_compare_api_local_memfd/stdout.json`
- `r01_09_carrier_compare_api_local_memfd` exit `0` required `0` duration `48s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_09_carrier_compare_api_local_memfd/stdout.json`
- `r01_10_continuous_api_local` exit `0` required `0` duration `961s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_10_continuous_api_local/stdout.json`
- `r01_11_continuous_replay_api_local` exit `0` required `0` duration `1031s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_11_continuous_replay_api_local/stdout.json`
- `r01_12_replay_negative_api_local` exit `0` required `1` duration `3s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_12_replay_negative_api_local/stdout.json`
- `r01_13_flagship_ablation_api_local` exit `1` required `0` duration `582s` artifact `/statebus/runs/sb2-gpu1-20260708_084458/artifacts/stages/r01_13_flagship_ablation_api_local/stdout.json`
