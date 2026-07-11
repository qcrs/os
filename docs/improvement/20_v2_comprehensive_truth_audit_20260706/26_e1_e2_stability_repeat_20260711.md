# E1/E2 Stability Repeat - 2026-07-11

## Conclusion

The E1 and E2 mechanism directions reproduced without restarting the Qwen3-32B vLLM service.

This repeat should be treated as a stability check, not a new formal guard. It supports the current mechanism interpretation: StateBus schedule/layout controls can improve engine-local prefix reuse behavior. It does not support KV tensor export, hidden-state transfer, cross-engine cache reuse, or two-GPU claims.

## Service Control

The repeat used the same recovered local service baseline:

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

No service restart, E4, E5, or E6 run was performed.

## E1 Schedule Repeat

The repeat intentionally ran `cache_hostile` first and `cache_friendly` second to reduce concern that the original result only reflected probe ordering.

| Metric | Cache-hostile | Cache-friendly | Friendly - hostile |
| --- | ---: | ---: | ---: |
| Requests | 10 | 10 | 0 |
| Errors | 0 | 0 | 0 |
| Final `gpu_prefix_cache_hit_rate` | 0.344461 | 0.520883 | +0.176422 |
| Mean TTFT | 1735.72 ms | 871.15 ms | -864.56 ms |
| Mean latency | 4126.31 ms | 3177.87 ms | -948.44 ms |

Result: `cache_friendly_remains_better_than_cache_hostile`.

## E2 Prefix-Alignment Repeat

The repeat ran `independent` first and `shared_evidence_prefix` second. Prompt size stayed effectively matched while shared mode exposed a large common prefix.

| Metric | Independent | Shared evidence prefix | Shared - independent |
| --- | ---: | ---: | ---: |
| Requests | 5 | 5 | 0 |
| Errors | 0 | 0 | 0 |
| Mean prompt bytes | 29539.60 | 29437.00 | -102.60 |
| Mean shared prefix bytes | 0.00 | 28926.00 | +28926.00 |
| Final `gpu_prefix_cache_hit_rate` | 0.431510 | 0.481196 | +0.049686 |
| Mean TTFT | 3517.59 ms | 939.11 ms | -2578.48 ms |
| Mean latency | 5942.28 ms | 3338.81 ms | -2603.47 ms |

Result: `shared_evidence_prefix_remains_faster_than_independent_layout`.

Important interpretation: because the service was not restarted, E2 independent no longer had a zero final hit-rate gauge. That makes the absolute hit-rate weaker than in the clean primary E2 run. The stronger stability signal here is that shared mode still reduced TTFT and total latency substantially while using nearly the same prompt size.

## Artifacts

| Artifact | Role |
| --- | --- |
| `artifacts/e1_e2_stability_repeat_summary_20260711_1425.json` | Summary of this stability repeat. |
| `artifacts/e1_kv_schedule_cache_hostile_stability_r1_20260711_1425.json` | E1 hostile raw repeat. |
| `artifacts/e1_kv_schedule_cache_friendly_stability_r1_20260711_1425.json` | E1 friendly raw repeat. |
| `artifacts/e2_prefix_alignment_independent_stability_r1_20260711_1425.json` | E2 independent raw repeat. |
| `artifacts/e2_prefix_alignment_shared_stability_r1_20260711_1425.json` | E2 shared-prefix raw repeat. |

## Next Decision

E1/E2 are now stable enough to justify either:

1. accepting the mechanism direction and moving to E6 formal guard with explicit approval for a long run; or
2. doing one clean-service E1/E2 rerun later, after a safe vLLM restart, if the goal is a stronger headline around raw prefix-cache hit-rate.

E4/E5 should remain deferred unless GPU capacity and restart risk are explicitly acceptable.
