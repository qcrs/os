# E0 32B Observability Probe - 2026-07-11

## Conclusion

E0 was initially blocked because the Qwen3-32B local vLLM endpoint was not listening on `127.0.0.1:53334`.

After operator clarification that GPU0 should be used, E0 was recovered on GPU0 as a single-card Qwen3-32B vLLM service with `max_model_len=8192`, prefix caching enabled, and live `/health` plus `/metrics` observability. E1/E2/E3 mechanism ablations can proceed cautiously against this service.

This was a service-availability/configuration blocker, not a StateBus benchmark failure.

## Commands Run

```bash
git status --short --branch
git log -2 --oneline
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && curl -sS -i http://127.0.0.1:53334/health
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && curl -sS http://127.0.0.1:53334/metrics | rg 'prefix|cache|kv'
pgrep -af 'vllm|Qwen3|53334|53333'
nvidia-smi
ss -ltnp
ps -fp 2906243 3391328 3394943
source deploy/activate_statebus_host.sh && python scripts/audit_local_vllm_kv_results.py
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && scripts/run_v2_local_vllm_container_check.sh
kill 3008883
setsid env CUDA_VISIBLE_DEVICES=0 VLLM_USE_V1=0 /home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/vllm serve /data/models/Qwen3-32B --served-model-name qwen3-32b --host 127.0.0.1 --port 53334 --dtype bfloat16 --max-model-len 8192 --max-num-seqs 1 --max-num-batched-tokens 8192 --gpu-memory-utilization 0.82 --tensor-parallel-size 1 --enable-prefix-caching --enforce-eager
bash -n deploy/activate_statebus_local_vllm_profile.sh
bash -n scripts/start_vllm_qwen3_32b_prefix_cache.sh
source deploy/activate_statebus_host.sh && python -m py_compile scripts/audit_local_vllm_kv_results.py
```

## Initial Findings

| Check | Result |
| --- | --- |
| Git status | Only pre-existing unrelated `tatus --short --branch` remains untracked. |
| Latest commits | `148bd7d kv: tighten local vllm audit coverage`, `df6d35b kv: add local vllm audit and guardrails`. |
| 32B health | `curl: (7) Failed to connect to 127.0.0.1 port 53334: Connection refused`. |
| 32B metrics | `curl: (7) Failed to connect to 127.0.0.1 port 53334: Connection refused`; no prefix/cache/KV metrics exposed. |
| Port listening | `ss -ltnp` showed no listener on `53334` or `53333`. |
| vLLM process scan | No vLLM server process matched; one unrelated Qwen3.5 sampling command matched the model-name grep. |
| GPU2 state | GPU2 had about 65 GiB allocated by existing non-StateBus Python/LLaMA-Factory work. |
| Container check | `scripts/run_v2_local_vllm_container_check.sh` with the 32B profile failed at the host health probe before container execution. |
| Audit JSON | Refreshed `local_vllm_kv_audit_20260711.json`; it records health and metrics as connection refused. |

Observed GPU2 processes:

| PID | Owner | Summary |
| ---: | --- | --- |
| `2906243` | `double` | `python -m CE3_baselines.main ... --cuda_id 2` |
| `3391328` | `dev001` | `llamafactory-cli webui` |
| `3394943` | `dev001` | `llamafactory-cli train ... Qwen2.5-32B-Instruct ...` |

## Recovery Update

The service was restarted on GPU0 only. No unrelated GPU0/GPU1/GPU2 processes were killed.

| Check | Result |
| --- | --- |
| Active profile | `qwen3-32b` now defaults to `STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=0`, `STATEBUS_VLLM_MAX_MODEL_LEN=8192`, `STATEBUS_VLLM_GPU_MEMORY_UTILIZATION=0.82`, `STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS=8192`, `STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE=573`. |
| Start script defaults | `scripts/start_vllm_qwen3_32b_prefix_cache.sh` now defaults to GPU0 and `gpu_memory_utilization=0.82`. |
| Launch log | `/home/qcrs/statebus/logs/vllm_qwen3_32b_gpu0_53334_8192_20260711_133225.log`. |
| Parent / engine PID | Parent `3021478`; engine `3021678`. |
| vLLM version/backend | vLLM `0.7.3`; Qwen3 falls back to the Transformers backend. |
| Context | `max_model_len=8192`, `max_num_batched_tokens=8192`, `max_num_seqs=1`, `tensor_parallel_size=1`. |
| Memory profile | Weights `61.0249 GiB`; activation peak `1.62 GiB`; KV cache `2.25 GiB`. |
| KV blocks | `num_gpu_blocks=575`, `num_cpu_blocks=1024`; vLLM reported maximum concurrency `1.12x` for 8192-token requests. |
| Health | `HTTP/1.1 200 OK` for `http://127.0.0.1:53334/health`. |
| Metrics | Prefix/cache/KV gauge lines are exposed, including `enable_prefix_caching="True"`, `gpu_memory_utilization="0.82"`, `num_gpu_blocks="575"`, `gpu_prefix_cache_hit_rate=0.0`, and `cpu_prefix_cache_hit_rate=0.0`. |
| Audit JSON | Refreshed `local_vllm_kv_audit_20260711.json`; it records health `ok=true` and preserves raw prefix/cache/KV metric lines. |

Important claim boundary: these metrics prove observability and prefix-cache configuration, not a hit/miss mechanism win yet. The hit-rate gauges were still `0.0` at idle.

## Decision

E0 now passes for a GPU0 single-card Qwen3-32B service at 8192 context. E1/E2/E3 can run as small mechanism probes.

Do not run E4/E5 yet. The 8192 service has limited single-request headroom, and no two-GPU success is claimed.

## Next Action

Run E1 cache-friendly/cache-hostile first, then E2 shared evidence prefix on/off, then E3 dynamic pruning on/off. Before each probe, recheck:

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
curl -sS http://127.0.0.1:53334/health
curl -sS http://127.0.0.1:53334/metrics | rg 'prefix|cache|kv'
```
