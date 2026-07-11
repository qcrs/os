# E1 KV Schedule Ablation - 2026-07-11

## Conclusion

E1 passes as a mechanism probe under the controlled repeat=4 / 573 GPU-block stress condition.

The cache-friendly schedule produced higher vLLM GPU prefix-cache hit-rate and lower TTFT than the cache-hostile schedule:

| Metric | Cache-friendly | Cache-hostile | Delta |
| --- | ---: | ---: | ---: |
| Requests | 10 | 10 | 0 |
| Errors | 0 | 0 | 0 |
| Max contiguous same-corpus run | 5 | 1 | +4 |
| Affinity switches | 1 | 9 | -8 |
| Final `gpu_prefix_cache_hit_rate` | 0.788866 | 0.523494 | +0.265373 |
| Mean TTFT | 657.55 ms | 1378.70 ms | -721.14 ms |
| Mean latency | 2340.79 ms | 3424.93 ms | -1084.14 ms |

Claim boundary: this is evidence for engine-local prefix reuse from schedule/layout control. It is not evidence for KV tensor export, cross-engine KV transfer, or hidden-state transfer.

## Service Control

The probe used the recovered Qwen3-32B local vLLM service on GPU0:

```text
model=qwen3-32b
base_url=http://127.0.0.1:53334/v1
max_model_len=8192
max_num_batched_tokens=8192
max_num_seqs=1
gpu_memory_utilization=0.82
tensor_parallel_size=1
enable_prefix_caching=True
```

For the primary repeat=4 comparison, both modes used `num_gpu_blocks=573`.

Friendly cache config:

```text
vllm:cache_config_info{block_size="16",cache_dtype="auto",calculate_kv_scales="False",cpu_offload_gb="0",enable_prefix_caching="True",gpu_memory_utilization="0.82",is_attention_free="False",num_cpu_blocks="1024",num_gpu_blocks="573",num_gpu_blocks_override="None",sliding_window="None",swap_space_bytes="4294967296"} 1.0
```

Hostile cache config:

```text
vllm:cache_config_info{block_size="16",cache_dtype="auto",calculate_kv_scales="False",cpu_offload_gb="0",enable_prefix_caching="True",gpu_memory_utilization="0.82",is_attention_free="False",num_cpu_blocks="1024",num_gpu_blocks="573",num_gpu_blocks_override="573",sliding_window="None",swap_space_bytes="4294967296"} 1.0
```

## Artifacts

Primary artifacts:

| Artifact | Role |
| --- | --- |
| `artifacts/e1_kv_schedule_ablation_summary_20260711_134159.json` | Primary E1 comparison summary. |
| `artifacts/e1_kv_schedule_cache_friendly_r4_20260711_134159.json` | Repeat=4 cache-friendly raw probe. |
| `artifacts/e1_kv_schedule_cache_hostile_r4_20260711_134159.json` | Repeat=4 cache-hostile raw probe. |
| `scripts/probe_local_vllm_kv_schedule.py` | Direct local-vLLM schedule probe script. |

Exploratory artifacts:

| Artifact | Result |
| --- | --- |
| `artifacts/e1_kv_schedule_cache_friendly_20260711_134159.json` | Repeat=3 pressure was too low to distinguish schedule benefit. |
| `artifacts/e1_kv_schedule_cache_hostile_20260711_134159.json` | Repeat=3 reached the same final hit-rate as friendly and is not the primary mechanism result. |

## Interpretation

The repeat=3 exploratory probe showed why E1 needs a capacity-aware stress setting: both corpus prefixes could effectively remain cache-resident, so cache-friendly and cache-hostile schedules converged to the same final hit-rate.

The repeat=4 probe increased corpus-prefix pressure while staying under the 8192-token service limit. Under that condition, cache-friendly ordering kept same-corpus requests contiguous and produced substantially better engine-local prefix reuse behavior.

This supports the next mechanism work:

1. E2 should isolate prompt layout by comparing shared evidence prefix on/off.
2. E3 should isolate input-level dynamic pruning on/off.
3. E6 formal guard should wait until E2/E3 also show stable benefit.
