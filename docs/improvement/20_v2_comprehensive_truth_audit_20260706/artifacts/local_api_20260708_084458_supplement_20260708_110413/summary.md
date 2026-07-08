# StateBus v2 local+api supplement statistics

- Base run: `sb2-gpu1-20260708_084458`
- Supplement run: `sb2-gpu1-health-20260708_110413`
- Stage count: `14`
- Failed stage count: `2`
- Failed required stage count: `2`
- CUDA_VISIBLE_DEVICES: `1`
- STATEBUS_EMBED_DEVICE: `cuda:0`

## Scope

- Incremental health check over current risky surfaces: container root/GPU, py_compile, targeted pytest, KV prefix static contract, import gate, CodeAct smoke/acceptance, explicit KV prefix demo, optional vLLM metrics/alignment probes, flagship ablation.
- Do not rerun already passed base stages: formal 25/5, carrier compare, external compare, continuous, continuous replay, replay-negative audit.

## Key Metrics

- `base_failed_stage_count`: `1`
- `base_failed_required_stage_count`: `0`
- `base_artifact_integrity_ok`: `False`
- `base_claim_boundary_ok`: `False`
- `base_formal_registry_case_count`: `25.0`
- `base_formal_registry_family_count`: `5`
- `base_external_claim_kind`: `quality_superiority`
- `base_serialized_latency_superiority_claim_allowed`: `0.0`
- `container_effective_uid`: `0`
- `container_root_ok`: `True`
- `torch_cuda_available`: `True`
- `torch_cuda_device_count`: `1`
- `py_compile_health_ok`: `True`
- `py_compile_checked_count`: `19`
- `targeted_pytest_ok`: `True`
- `targeted_pytest_passed_count`: `49`
- `kv_prefix_static_health_ok`: `True`
- `kv_prefix_claim_boundary`: `engine_local_prefix_reuse_probe_only_no_kv_tensor_export`
- `kv_prefix_cache_friendly_max_run`: `5`
- `kv_prefix_cache_hostile_max_run`: `1`
- `import_probe_ok`: `True`
- `codeact_bwrap_smoke_ok`: `True`
- `codeact_acceptance_success_count`: `5`
- `codeact_acceptance_total_runs`: `5`
- `codeact_acceptance_target_met`: `True`
- `kv_prefix_demo_task_family`: `kv_prefix_reuse_v1`
- `kv_prefix_demo_L3_case_count`: `10.0`
- `kv_prefix_demo_L3_quality_pass_count`: `10.0`
- `kv_prefix_demo_L3_reuse_gain`: `6.0`
- `kv_prefix_demo_corpus_prefix_reuse_count`: `8.0`
- `kv_prefix_demo_corpus_prefill_saved_tokens_estimate`: `2144.0`
- `kv_prefix_demo_engine_local_prefill_saved_tokens_estimate`: `2680.0`
- `kv_prefix_demo_semantic_state_transfer_count`: `10.0`
- `vllm_prefix_probe_ok`: `True`
- `vllm_prefix_probe_skipped`: `True`
- `vllm_prefix_alignment_ok`: `True`
- `vllm_prefix_alignment_skipped`: `True`
- `flagship_stress_family_count`: `6`
- `flagship_stress_pass_family_count`: `5`
- `flagship_stress_fail_family_count`: `1`
- `flagship_diagnostic_only_family_count`: `1`
- `flagship_total_prompt_visible_saved_by_state_ref_bytes`: `7875.0`
- `flagship_total_llm_prompt_saved_by_state_ref_bytes`: `21325.0`

## Failed Required Stages

- `s01_00b_base_artifact_integrity_audit` exit `1`
- `s01_00c_base_claim_boundary_audit` exit `1`

## Stage Log

- `s01_00_base_run_snapshot` exit `0` required `1` duration `1s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_00_base_run_snapshot/stdout.json`
- `s01_00b_base_artifact_integrity_audit` exit `1` required `1` duration `0s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_00b_base_artifact_integrity_audit/stdout.json`
- `s01_00c_base_claim_boundary_audit` exit `1` required `1` duration `0s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_00c_base_claim_boundary_audit/stdout.json`
- `s01_01_container_root_gpu_probe` exit `0` required `1` duration `2s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_01_container_root_gpu_probe/stdout.json`
- `s01_02_py_compile_health` exit `0` required `1` duration `0s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_02_py_compile_health/stdout.json`
- `s01_03_targeted_pytest_health` exit `0` required `1` duration `47s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_03_targeted_pytest_health/stdout.json`
- `s01_04_kv_prefix_static_health` exit `0` required `1` duration `1s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_04_kv_prefix_static_health/stdout.json`
- `s01_05_import_probe` exit `0` required `1` duration `1s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_05_import_probe/stdout.json`
- `s01_06_codeact_bwrap_smoke` exit `0` required `1` duration `1s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_06_codeact_bwrap_smoke/stdout.json`
- `s01_07_codeact_acceptance_api` exit `0` required `1` duration `19s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_07_codeact_acceptance_api/stdout.json`
- `s01_08_kv_prefix_demo_api_local` exit `0` required `1` duration `366s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_08_kv_prefix_demo_api_local/stdout.json`
- `s01_09_vllm_prefix_metrics_probe_skipped` exit `0` required `0` duration `0s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_09_vllm_prefix_metrics_probe_skipped/stdout.json`
- `s01_09b_vllm_prefix_alignment_probe_skipped` exit `0` required `0` duration `0s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_09b_vllm_prefix_alignment_probe_skipped/stdout.json`
- `s01_10_flagship_ablation_api_local` exit `0` required `1` duration `2364s` artifact `/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/stages/s01_10_flagship_ablation_api_local/stdout.json`

## Claim Boundaries

- This supplement does not supersede the base local+api comprehensive run; read evidence as base plus supplement.
- Formal 25-case / 5-family benchmark, formal carrier compare, formal external compare, continuous, continuous replay, and replay-negative audit are inherited from the base run and are not rerun here.
- Base artifact integrity and claim-boundary audits are machine checks over inherited evidence; they do not create new benchmark evidence.
- Container execution uses docker exec -u 0; container root and GPU visibility are checked in the health probe.
- Targeted pytest is a risk-surface health check over CodeAct, flagship summary, continuous replay, retrieval, and live-runner plumbing; it does not replace the base full pytest run.
- CodeAct evidence is bounded CodeAct acceptance only, not a general-purpose CodeAct benchmark superiority claim.
- KV prefix demo is an explicit demo_secondary family run; it is not part of the inherited formal 25-case / 5-family registry.
- KV/prefix/neural-state fields remain Engine-Local Prefix Reuse/control-plane scheduling evidence unless separately validated as actual engine KV cache reuse.
- KV prefix static health validates task-family and scheduling contracts only; actual vLLM prefix-cache mechanism evidence requires metrics deltas and TTFT.
- Optional vLLM prefix alignment probe is skipped unless STATEBUS_RUN_VLLM_PREFIX_PROBE=1 and a local vLLM OpenAI-compatible service is reachable.
- Latency superiority remains unclaimed unless serialized latency gate explicitly allows it.
