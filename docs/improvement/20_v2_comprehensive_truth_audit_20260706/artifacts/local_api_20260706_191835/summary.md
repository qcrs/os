# StateBus v2 local+api comprehensive statistics

- Mode: `role_path_mode=api`, `embedding_mode=local`
- Stage count: `13`
- Failed stage count: `0`
- Failed required stage count: `0`

## Failed Required Stages
- none

## Key Metrics

### r01_04_preflight_api_local
- `preflight_ok`: `True`
- `embedding_model_path`: `/statebus/models/Qwen3-Embedding-0.6B`
- `embedding_device`: `cuda:0`
- `llm_config_source`: `/workspace/statebus/project/deploy/statebus_llm.yaml.local`

### r01_05_formal_api_local_memfd
- `suite_id`: `v2-local-api-20260706_191835-r01_05_formal_api_local_memfd-formal`
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
- `fixed_answer_external_comparison_valid`: `False`
- `external_comparator_claim_scope`: `formal_financial_family`
- `formal_superiority_claim_allowed`: `True`
- `formal_efficiency_claim_allowed`: `True`
- `formal_headline_eligible`: `False`
- `api_comparison_valid`: `0.0`
- `external_fairness_gate_coverage`: `True`
- `no_external_fairness_gate_failures`: `True`
- `external_fairness_gate_pass_count`: `8.0`
- `external_fairness_gate_failed_case_count`: `0.0`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `8.0`

### r01_07_dev_compare_api_local_memfd
- `fixed_answer_external_comparison_valid`: `True`
- `external_comparator_claim_scope`: `dev_fixed_answer_only`
- `formal_superiority_claim_allowed`: `False`
- `formal_efficiency_claim_allowed`: `False`
- `formal_headline_eligible`: `False`
- `api_comparison_valid`: `1.0`
- `api_llm_total_tokens_delta`: `-986.0`
- `api_prompt_bytes_delta`: `-5082.0`
- `api_control_bytes_delta`: `-305.0`
- `api_task_ms_delta`: `13546.113003999999`
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

### r01_12_flagship_ablation_api_local
- `stress_family_count`: `6`
- `stress_pass_family_count`: `4`
- `total_llm_prompt_saved_by_state_ref_bytes`: `22079.0`
- `total_prompt_visible_saved_by_state_ref_bytes`: `8514.0`


## Stage Log

- `00_env_probe` exit `0` required `1` duration `0s` artifact `-`
- `01_py_compile` exit `0` required `1` duration `0s` artifact `-`
- `02_pytest_focused_v2` exit `0` required `1` duration `383s` artifact `-`
- `03_runtime_smoke` exit `0` required `1` duration `36s` artifact `-`
- `r01_04_preflight_api_local` exit `0` required `1` duration `3s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_04_preflight_api_local/stdout.json`
- `r01_05_formal_api_local_memfd` exit `0` required `1` duration `866s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_05_formal_api_local_memfd/stdout.json`
- `r01_06_formal_compare_api_local_memfd` exit `0` required `1` duration `122s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_06_formal_compare_api_local_memfd/stdout.json`
- `r01_07_dev_compare_api_local_memfd` exit `0` required `0` duration `51s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_07_dev_compare_api_local_memfd/stdout.json`
- `r01_08_carrier_compare_api_local_memfd` exit `0` required `0` duration `55s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_08_carrier_compare_api_local_memfd/stdout.json`
- `r01_09_continuous_api_local` exit `0` required `0` duration `1067s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_09_continuous_api_local/stdout.json`
- `r01_10_continuous_replay_api_local` exit `0` required `0` duration `1051s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_10_continuous_replay_api_local/stdout.json`
- `r01_11_replay_negative_api_local` exit `0` required `1` duration `3s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_11_replay_negative_api_local/stdout.json`
- `r01_12_flagship_ablation_api_local` exit `0` required `0` duration `2737s` artifact `/statebus/runs/v2-local-api-20260706_191835/artifacts/stages/r01_12_flagship_ablation_api_local/stdout.json`
