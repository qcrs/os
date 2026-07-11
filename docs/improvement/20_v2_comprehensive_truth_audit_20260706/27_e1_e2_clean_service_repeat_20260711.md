# E1/E2 Clean-Service Repeat - 2026-07-11

## Conclusion

The clean-service repeat strengthens the E1/E2 mechanism evidence. Each mode was run after restarting the GPU0 Qwen3-32B vLLM service, so the observed prefix-cache hit-rate gauges started from `0.0` for every mode.

Result: E1 cache-friendly scheduling and E2 shared evidence prefix both reproduced with cleaner hit-rate evidence and lower TTFT. This remains evidence for engine-local prefix reuse through schedule/layout control only. It is not evidence for KV tensor export, hidden-state transfer, cross-engine reuse, or multi-GPU success.

## Service Control

```text
model=qwen3-32b
base_url=http://127.0.0.1:53334/v1
cuda_visible_devices=0
max_model_len=8192
gpu_memory_utilization=0.82
num_gpu_blocks_override=573
tensor_parallel_size=1
enable_prefix_caching=True
```

Restart policy:

- restart before E1 `cache_hostile`
- restart before E1 `cache_friendly`
- restart before E2 `independent`
- restart before E2 `shared_evidence_prefix`

No unrelated GPU process was killed.

## E1 Clean Schedule Repeat

| Metric | Cache-hostile | Cache-friendly | Friendly - hostile |
| --- | ---: | ---: | ---: |
| Requests | 10 | 10 | 0 |
| Errors | 0 | 0 | 0 |
| Initial `gpu_prefix_cache_hit_rate` | 0.000000 | 0.000000 | 0.000000 |
| Final `gpu_prefix_cache_hit_rate` | 0.523947 | 0.789094 | +0.265147 |
| Mean TTFT | 1568.78 ms | 884.81 ms | -683.97 ms |
| Mean latency | 3477.67 ms | 3260.59 ms | -217.08 ms |

Result: `cache_friendly_clean_service_hit_rate_and_ttft_better_than_cache_hostile`.

## E2 Clean Prefix-Alignment Repeat

| Metric | Independent | Shared evidence prefix | Shared - independent |
| --- | ---: | ---: | ---: |
| Requests | 5 | 5 | 0 |
| Errors | 0 | 0 | 0 |
| Mean prompt bytes | 29519.60 | 29417.00 | -102.60 |
| Mean shared prefix bytes | 0.00 | 28910.00 | +28910.00 |
| Initial `gpu_prefix_cache_hit_rate` | 0.000000 | 0.000000 | 0.000000 |
| Final `gpu_prefix_cache_hit_rate` | 0.000000 | 0.779545 | +0.779545 |
| Mean TTFT | 3525.84 ms | 967.28 ms | -2558.56 ms |
| Mean latency | 5980.76 ms | 3345.05 ms | -2635.71 ms |

Result: `shared_evidence_prefix_clean_service_hit_rate_and_ttft_better_than_independent_layout`.

## Artifacts

| Artifact | Role |
| --- | --- |
| `artifacts/e1_e2_clean_service_repeat_summary_20260711_1438.json` | Clean-service summary. |
| `artifacts/e1_kv_schedule_cache_hostile_clean_r1_20260711_1438.json` | E1 hostile raw clean run. |
| `artifacts/e1_kv_schedule_cache_friendly_clean_r1_20260711_1438.json` | E1 friendly raw clean run. |
| `artifacts/e2_prefix_alignment_independent_clean_r1_20260711_1438.json` | E2 independent raw clean run. |
| `artifacts/e2_prefix_alignment_shared_clean_r1_20260711_1438.json` | E2 shared-prefix raw clean run. |

## Next Action

Proceed to E6 formal 25-case guard with explicit mechanism switches:

- `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`
- `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1`

The E6 claim boundary remains formal quality preservation. It still does not prove KV tensor handoff.
