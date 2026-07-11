# StateBus v2 local+api non-KV extra stages

- Non-KV only: `true`
- Excluded families: `kv_prefix_reuse`, `kv_prefix_reuse_v1`
- Stage count: `35`
- Failed stage count: `1`
- Failed required stage count: `0`

## Failed Required Stages
- none

## Key Metrics

### x04_preflight_api_local
- `ok`: `True`
- `embedding_device`: `cuda:0`
- `embedding_model_path`: `/statebus/models/Qwen3-Embedding-0.6B`
- `llm_config_source`: `env`

### x04b_import_probe
- `ok`: `True`
- `runtime_file`: `/workspace/statebus/project/v2/runtime/__init__.py`
- `codeact_file`: `/workspace/statebus/project/v2/runtime/codeact.py`
- `neural_state_file`: `/workspace/statebus/project/v2/runtime/neural_state.py`

### x04c_codeact_bwrap_smoke
- `ok`: `True`
- `bwrap_ok`: `True`
- `codeact_bwrap_ok`: `True`

### x04d_codeact_acceptance_api
- `success_count`: `5`
- `total_runs`: `5`
- `target_success_count`: `3`
- `target_met`: `True`
- `sandbox_backend_required`: `bwrap`

### x05_design_csv_table_profile
- `family_id`: `csv_table_profile_v1`
- `claim_tier`: `formal_primary`
- `round_count`: `10`
- `dataset_count`: `2`

### x06_design_incident_diagnosis
- `family_id`: `incident_diagnosis_v2`
- `claim_tier`: `formal_secondary`
- `round_count`: `10`
- `dataset_count`: `3`

### x07_design_long_doc_table
- `family_id`: `long_doc_table_v1`
- `claim_tier`: `formal_secondary`
- `round_count`: `10`
- `dataset_count`: `1`

### x08_design_csv_correlation_replay
- `family_id`: `csv_correlation_replay_v1`
- `claim_tier`: `formal_primary`
- `round_count`: `10`
- `dataset_count`: `1`

### x09_design_cross_period_financial
- `family_id`: `cross_period_financial_v1`
- `claim_tier`: `formal_secondary`
- `round_count`: `10`
- `dataset_count`: `1`

### x10_design_long_doc_metric_replay
- `family_id`: `long_doc_metric_replay_v1`
- `claim_tier`: `formal_secondary`
- `round_count`: `10`
- `dataset_count`: `1`

### x10b_design_gridops_world
- `family_id`: `gridops_world_v1`
- `claim_tier`: `demo_secondary`
- `round_count`: `10`
- `dataset_count`: `1`

### x11_dev_statebus_api_local_memfd
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x11_dev_statebus_api_local_memfd-cold-start-statebus`
- `benchmark_tier`: `dev`
- `family_case_count`: `3`
- `L3_case_count`: `3.0`
- `L3_quality_pass_count`: `3.0`
- `state_pool_mode_requested`: `memfd`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `3.0`
- `shared_memory_publish_count`: `0.0`

### x12_dev_external_api_local
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x12_dev_external_api_local-external`
- `benchmark_tier`: `dev`
- `family_case_count`: `3`

### x13_dev_compare_api_local_memfd
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x13_dev_compare_api_local_memfd-cold-start-compare`
- `benchmark_tier`: `dev`
- `state_pool_mode_requested`: `memfd`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `3.0`
- `formal_compare_case_count`: `3`
- `formal_compare_family_count`: `1`
- `formal_compare_full_registry_coverage`: `False`
- `strict_equal_quality_comparison_valid`: `True`

### x14_dev_carrier_compare_api_local_memfd
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x14_dev_carrier_compare_api_local_memfd-cold-start-carrier-compare`
- `benchmark_tier`: `dev`

### x15_continuous_csv_table_profile_api_local
- `family_id`: `csv_table_profile_v1`
- `semantic_state_transfer_count`: `10.0`

### x16_continuous_incident_diagnosis_api_local
- `family_id`: `incident_diagnosis_v2`
- `semantic_state_transfer_count`: `10.0`

### x17_continuous_long_doc_table_api_local
- `family_id`: `long_doc_table_v1`
- `semantic_state_transfer_count`: `10.0`

### x18_continuous_replay_csv_correlation_api_local
- `family_id`: `csv_correlation_replay_v1`
- `semantic_state_transfer_count`: `10.0`

### x19_continuous_replay_cross_period_financial_api_local
- `family_id`: `cross_period_financial_v1`
- `semantic_state_transfer_count`: `10.0`

### x20_continuous_replay_long_doc_metric_api_local
- `family_id`: `long_doc_metric_replay_v1`
- `semantic_state_transfer_count`: `10.0`

### x21_formal_api_local_shared_memory
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x21_formal_api_local_shared_memory-formal`
- `benchmark_tier`: `formal`
- `family_case_count`: `25`
- `family_count`: `5`
- `L3_case_count`: `25.0`
- `L3_quality_pass_count`: `25.0`
- `state_pool_mode_requested`: `shared_memory`
- `state_pool_mode_used`: `shared_memory`
- `transport`: `loopback`
- `memfd_transfer_count`: `0.0`
- `shared_memory_publish_count`: `25.0`

### x22_formal_carrier_compare_api_local_shared_memory
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x22_formal_carrier_compare_api_local_shared_memory-cold-start-carrier-compare`
- `benchmark_tier`: `formal`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_compare_full_registry_coverage`: `True`

### x23_formal_compare_api_local_shared_memory
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x23_formal_compare_api_local_shared_memory-cold-start-compare`
- `benchmark_tier`: `formal`
- `state_pool_mode_requested`: `shared_memory`
- `state_pool_mode_used`: `shared_memory`
- `memfd_transfer_count`: `0.0`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_compare_full_registry_coverage`: `True`
- `strict_equal_quality_comparison_valid`: `False`

### x23b_formal_api_local_shared_memory_subprocess
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x23b_formal_api_local_shared_memory_subprocess-formal`
- `benchmark_tier`: `formal`
- `family_case_count`: `25`
- `family_count`: `5`
- `L3_case_count`: `25.0`
- `L3_quality_pass_count`: `25.0`
- `state_pool_mode_requested`: `shared_memory`
- `state_pool_mode_used`: `shared_memory`
- `transport`: `subprocess`
- `memfd_transfer_count`: `0.0`
- `shared_memory_publish_count`: `25.0`

### x24_formal_api_local_memfd_benchmark_balanced
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x24_formal_api_local_memfd_benchmark_balanced-formal`
- `benchmark_tier`: `formal`
- `family_case_count`: `25`
- `family_count`: `5`
- `L3_case_count`: `25.0`
- `L3_quality_pass_count`: `25.0`
- `state_pool_mode_requested`: `memfd`
- `state_pool_mode_used`: `memfd`
- `transport`: `loopback`
- `memfd_transfer_count`: `25.0`
- `shared_memory_publish_count`: `0.0`

### x25_formal_carrier_compare_api_local_memfd_benchmark_balanced
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x25_formal_carrier_compare_api_local_memfd_benchmark_balanced-cold-start-carrier-compare`
- `benchmark_tier`: `formal`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_compare_full_registry_coverage`: `True`

### x26_formal_compare_api_local_memfd_benchmark_balanced
- `suite_id`: `v2-local-api-non-kv-followup-20260709_083750-extras-x26_formal_compare_api_local_memfd_benchmark_balanced-cold-start-compare`
- `benchmark_tier`: `formal`
- `state_pool_mode_requested`: `memfd`
- `state_pool_mode_used`: `memfd`
- `memfd_transfer_count`: `25.0`
- `formal_compare_case_count`: `25`
- `formal_compare_family_count`: `5`
- `formal_compare_full_registry_coverage`: `True`
- `strict_equal_quality_comparison_valid`: `False`

### x27_continuous_collection_api_local_benchmark_balanced
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `replay_target_round_count`: `9.0`
- `validated_replay_count`: `5.0`
- `exact_replay_count`: `4.0`

### x28_continuous_replay_collection_api_local_benchmark_balanced
- `family_count`: `3.0`
- `continuous_round_count`: `30.0`
- `replay_target_round_count`: `20.0`
- `validated_replay_count`: `18.0`
- `exact_replay_count`: `2.0`


## Stage Log

- `x00_env_probe` exit `0` required `1` duration `0s` artifact `-`
- `x01_py_compile_non_kv` exit `0` required `1` duration `1s` artifact `-`
- `x02_pytest_full_non_kv_v2` exit `0` required `1` duration `370s` artifact `-`
- `x03_runtime_smoke` exit `0` required `1` duration `33s` artifact `-`
- `x04_preflight_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x04_preflight_api_local/stdout.json`
- `x04b_import_probe` exit `0` required `1` duration `1s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x04b_import_probe/stdout.json`
- `x04c_codeact_bwrap_smoke` exit `0` required `1` duration `1s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x04c_codeact_bwrap_smoke/stdout.json`
- `x04d_codeact_acceptance_api` exit `0` required `1` duration `27s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x04d_codeact_acceptance_api/stdout.json`
- `x05_design_csv_table_profile` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x05_design_csv_table_profile/stdout.json`
- `x06_design_incident_diagnosis` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x06_design_incident_diagnosis/stdout.json`
- `x07_design_long_doc_table` exit `0` required `1` duration `3s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x07_design_long_doc_table/stdout.json`
- `x08_design_csv_correlation_replay` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x08_design_csv_correlation_replay/stdout.json`
- `x09_design_cross_period_financial` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x09_design_cross_period_financial/stdout.json`
- `x10_design_long_doc_metric_replay` exit `0` required `1` duration `3s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x10_design_long_doc_metric_replay/stdout.json`
- `x10b_design_gridops_world` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x10b_design_gridops_world/stdout.json`
- `x11_dev_statebus_api_local_memfd` exit `0` required `0` duration `294s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x11_dev_statebus_api_local_memfd/stdout.json`
- `x12_dev_external_api_local` exit `0` required `0` duration `50s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x12_dev_external_api_local/stdout.json`
- `x13_dev_compare_api_local_memfd` exit `0` required `0` duration `128s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x13_dev_compare_api_local_memfd/stdout.json`
- `x14_dev_carrier_compare_api_local_memfd` exit `0` required `0` duration `142s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x14_dev_carrier_compare_api_local_memfd/stdout.json`
- `x15_continuous_csv_table_profile_api_local` exit `0` required `0` duration `934s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x15_continuous_csv_table_profile_api_local/stdout.json`
- `x16_continuous_incident_diagnosis_api_local` exit `0` required `0` duration `859s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x16_continuous_incident_diagnosis_api_local/stdout.json`
- `x17_continuous_long_doc_table_api_local` exit `0` required `0` duration `923s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x17_continuous_long_doc_table_api_local/stdout.json`
- `x17b_continuous_gridops_world_api_local` exit `1` required `0` duration `2s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x17b_continuous_gridops_world_api_local/stdout.json`
- `x18_continuous_replay_csv_correlation_api_local` exit `0` required `0` duration `751s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x18_continuous_replay_csv_correlation_api_local/stdout.json`
- `x19_continuous_replay_cross_period_financial_api_local` exit `0` required `0` duration `1320s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x19_continuous_replay_cross_period_financial_api_local/stdout.json`
- `x20_continuous_replay_long_doc_metric_api_local` exit `0` required `0` duration `983s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x20_continuous_replay_long_doc_metric_api_local/stdout.json`
- `x21_formal_api_local_shared_memory` exit `0` required `0` duration `2353s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x21_formal_api_local_shared_memory/stdout.json`
- `x22_formal_carrier_compare_api_local_shared_memory` exit `0` required `0` duration `1139s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x22_formal_carrier_compare_api_local_shared_memory/stdout.json`
- `x23_formal_compare_api_local_shared_memory` exit `0` required `0` duration `1192s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x23_formal_compare_api_local_shared_memory/stdout.json`
- `x23b_formal_api_local_shared_memory_subprocess` exit `0` required `0` duration `2346s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x23b_formal_api_local_shared_memory_subprocess/stdout.json`
- `x24_formal_api_local_memfd_benchmark_balanced` exit `0` required `0` duration `2249s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x24_formal_api_local_memfd_benchmark_balanced/stdout.json`
- `x25_formal_carrier_compare_api_local_memfd_benchmark_balanced` exit `0` required `0` duration `1137s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x25_formal_carrier_compare_api_local_memfd_benchmark_balanced/stdout.json`
- `x26_formal_compare_api_local_memfd_benchmark_balanced` exit `0` required `0` duration `1211s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x26_formal_compare_api_local_memfd_benchmark_balanced/stdout.json`
- `x27_continuous_collection_api_local_benchmark_balanced` exit `0` required `0` duration `2523s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x27_continuous_collection_api_local_benchmark_balanced/stdout.json`
- `x28_continuous_replay_collection_api_local_benchmark_balanced` exit `0` required `0` duration `2895s` artifact `/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x28_continuous_replay_collection_api_local_benchmark_balanced/stdout.json`
