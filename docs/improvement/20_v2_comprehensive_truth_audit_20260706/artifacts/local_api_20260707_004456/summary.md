# StateBus v2 local+api comprehensive statistics

- Mode: `role_path_mode=api`, `embedding_mode=local`
- Stage count: `13`
- Failed stage count: `7`
- Failed required stage count: `2`
- Activation script: `/usr/local/bin/activate_statebus_container.sh`
- Activation status: `success`
- Python executable: `/usr/bin/python3`

## Failed Required Stages
- `r01_05_formal_api_local_memfd` exit `1`
- `r01_06_formal_compare_api_local_memfd` exit `1`

## Key Metrics

### r01_04_preflight_api_local
- `preflight_ok`: `True`
- `embedding_model_path`: `/statebus/models/Qwen3-Embedding-0.6B`
- `embedding_device`: `cuda:0`
- `llm_config_source`: `env`

### r01_11_replay_negative_api_local
- `audit_pass`: `True`
- `case_count`: `7`


## Compare Case Diagnostics

- none

## Stage Log

- `00_env_probe` exit `0` required `1` duration `0s` artifact `-`
- `01_py_compile` exit `0` required `1` duration `1s` artifact `-`
- `02_pytest_focused_v2` exit `0` required `1` duration `370s` artifact `-`
- `03_runtime_smoke` exit `0` required `1` duration `36s` artifact `-`
- `r01_04_preflight_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_04_preflight_api_local/stdout.json`
- `r01_05_formal_api_local_memfd` exit `1` required `1` duration `108s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_05_formal_api_local_memfd/stdout.json`
- `r01_06_formal_compare_api_local_memfd` exit `1` required `1` duration `52s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_06_formal_compare_api_local_memfd/stdout.json`
- `r01_07_dev_compare_api_local_memfd` exit `1` required `0` duration `36s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_07_dev_compare_api_local_memfd/stdout.json`
- `r01_08_carrier_compare_api_local_memfd` exit `1` required `0` duration `25s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_08_carrier_compare_api_local_memfd/stdout.json`
- `r01_09_continuous_api_local` exit `1` required `0` duration `31s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_09_continuous_api_local/stdout.json`
- `r01_10_continuous_replay_api_local` exit `1` required `0` duration `24s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_10_continuous_replay_api_local/stdout.json`
- `r01_11_replay_negative_api_local` exit `0` required `1` duration `2s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_11_replay_negative_api_local/stdout.json`
- `r01_12_flagship_ablation_api_local` exit `1` required `0` duration `27s` artifact `/statebus/runs/v2-local-api-20260707_004456/artifacts/stages/r01_12_flagship_ablation_api_local/stdout.json`
