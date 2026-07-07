# StateBus v2 local+api comprehensive statistics

- Mode: `role_path_mode=api`, `embedding_mode=local`
- Stage count: `12`
- Failed stage count: `0`
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
- `llm_config_source`: `env`

### r01_05_formal_api_local_memfd
- `suite_id`: `v2-local-api-20260707_091807-r01_05_formal_api_local_memfd-formal`
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

### r01_06_formal_compare_api_local_memfd
- `fixed_answer_external_comparison_valid`: `True`
- `external_comparator_claim_scope`: `formal_financial_family_8case_compare`
- `formal_compare_scope_label`: `formal_financial_family_8case_compare`
- `formal_compare_case_count`: `8`
- `formal_compare_family_count`: `1`
- `formal_registry_case_count`: `25`
- `formal_compare_full_registry_coverage`: `False`
- `strict_equal_quality_comparison_valid`: `True`
- `quality_superiority_comparison_valid`: `False`
- `formal_quality_superiority_claim_allowed`: `False`
- `formal_efficiency_superiority_claim_allowed`: `False`
- `formal_external_claim_kind`: `debug_only`
- `formal_superiority_claim_allowed`: `False`
- `formal_efficiency_claim_allowed`: `False`
- `formal_headline_eligible`: `True`
- `api_comparison_valid`: `1.0`
- `api_strict_equal_quality_comparison_valid`: `1.0`
- `api_quality_superiority_comparison_valid`: `0.0`
- `api_llm_total_tokens_delta`: `6165.0`
- `api_prompt_bytes_delta`: `-12965.0`
- `api_control_bytes_delta`: `577.0`
- `api_task_ms_delta`: `106135.486703`
- `external_fairness_gate_coverage`: `True`
- `no_external_fairness_gate_failures`: `True`
- `external_fairness_gate_pass_count`: `8.0`
- `external_fairness_gate_failed_case_count`: `0.0`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `8.0`

### r01_07_dev_compare_api_local_memfd
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
- `formal_headline_eligible`: `False`
- `api_comparison_valid`: `1.0`
- `api_strict_equal_quality_comparison_valid`: `1.0`
- `api_quality_superiority_comparison_valid`: `0.0`
- `api_llm_total_tokens_delta`: `2345.0`
- `api_prompt_bytes_delta`: `-5659.0`
- `api_control_bytes_delta`: `-514.0`
- `api_task_ms_delta`: `33266.867113`
- `external_fairness_gate_coverage`: `True`
- `no_external_fairness_gate_failures`: `True`
- `external_fairness_gate_pass_count`: `3.0`
- `external_fairness_gate_failed_case_count`: `0.0`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `3.0`

### r01_09_continuous_api_local
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `L2_semantic_state_transfer_count`: `30.0`
- `L3_reuse_gain`: `9.0`

### r01_10_continuous_replay_api_local
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `replay_target_round_count`: `20.0`
- `replay_observed_round_count`: `20.0`
- `replay_missing_target_round_count`: `0.0`
- `validated_replay_count`: `17.0`
- `validated_downgraded_reuse_count`: `17.0`
- `exact_replay_count`: `3.0`
- `answer_restoration_replay_count`: `0.0`
- `L2_semantic_state_transfer_count`: `30.0`
- `L3_reuse_gain`: `20.0`

### r01_11_replay_negative_api_local
- `audit_pass`: `True`
- `case_count`: `7`


## Compare Case Structured Fields

### r01_06_formal_compare_api_local_memfd
- `benchmark-sample-1` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `revenue=120` legacy revenue `` qf `True`; statebus metric `revenue=120` qf `True`
- `benchmark-sample-7` pass `True` reason `compare_case_trace`; expected `operating_income=19`; external metric `operating_income=19` legacy revenue `` qf `True`; statebus metric `operating_income=19` qf `True`
- `benchmark-sample-2` pass `True` reason `compare_case_trace`; expected `revenue=132`; external metric `revenue=132` legacy revenue `` qf `True`; statebus metric `revenue=132` qf `True`
- `benchmark-sample-6` pass `True` reason `compare_case_trace`; expected `gross_margin=39`; external metric `gross_margin=39` legacy revenue `` qf `True`; statebus metric `gross_margin=39` qf `True`
- `benchmark-sample-3` pass `True` reason `compare_case_trace`; expected `revenue=145`; external metric `revenue=145` legacy revenue `145` qf `True`; statebus metric `revenue=145` qf `True`
- `benchmark-sample-4` pass `True` reason `compare_case_trace`; expected `revenue=109`; external metric `revenue=109` legacy revenue `109` qf `True`; statebus metric `revenue=109` qf `True`
- `benchmark-sample-8` pass `True` reason `compare_case_trace`; expected `gross_margin=31`; external metric `gross_margin=31` legacy revenue `` qf `True`; statebus metric `gross_margin=31` qf `True`
- `benchmark-sample-5` pass `True` reason `compare_case_trace`; expected `revenue=87`; external metric `revenue=87` legacy revenue `` qf `True`; statebus metric `revenue=87` qf `True`

### r01_07_dev_compare_api_local_memfd
- `fixed-answer-auth-001` pass `True` reason `compare_case_trace`; expected `revenue=145`; external metric `revenue=145` legacy revenue `` qf `True`; statebus metric `revenue=145` qf `True`
- `fixed-answer-cache-001` pass `True` reason `compare_case_trace`; expected `revenue=120`; external metric `revenue=120` legacy revenue `` qf `True`; statebus metric `revenue=120` qf `True`
- `fixed-answer-worker-001` pass `True` reason `compare_case_trace`; expected `revenue=132`; external metric `revenue=132` legacy revenue `` qf `True`; statebus metric `revenue=132` qf `True`


## Stage Log

- `00_env_probe` exit `0` required `1` duration `0s` artifact `-`
- `01_py_compile` exit `0` required `1` duration `0s` artifact `-`
- `02_pytest_focused_v2` exit `0` required `1` duration `380s` artifact `-`
- `03_runtime_smoke` exit `0` required `1` duration `35s` artifact `-`
- `r01_04_preflight_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_04_preflight_api_local/stdout.json`
- `r01_05_formal_api_local_memfd` exit `0` required `1` duration `2137s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_05_formal_api_local_memfd/stdout.json`
- `r01_06_formal_compare_api_local_memfd` exit `0` required `1` duration `323s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_06_formal_compare_api_local_memfd/stdout.json`
- `r01_07_dev_compare_api_local_memfd` exit `0` required `0` duration `144s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_07_dev_compare_api_local_memfd/stdout.json`
- `r01_08_carrier_compare_api_local_memfd` exit `0` required `0` duration `152s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_08_carrier_compare_api_local_memfd/stdout.json`
- `r01_09_continuous_api_local` exit `0` required `0` duration `2470s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_09_continuous_api_local/stdout.json`
- `r01_10_continuous_replay_api_local` exit `0` required `0` duration `2624s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_10_continuous_replay_api_local/stdout.json`
- `r01_11_replay_negative_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-20260707_091807/artifacts/stages/r01_11_replay_negative_api_local/stdout.json`
