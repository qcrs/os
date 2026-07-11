# E2 Prefix Alignment Ablation - 2026-07-11

## Conclusion

E2 passes as a mechanism probe. `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` makes the repeated evidence prefix visible to vLLM automatic prefix caching, while the default independent role-first layout does not.

| Metric | Shared evidence prefix | Independent | Delta |
| --- | ---: | ---: | ---: |
| Requests | 5 | 5 | 0 |
| Errors | 0 | 0 | 0 |
| Mean prompt bytes | 29387.0 | 29489.6 | -102.6 |
| Mean shared prefix bytes | 28886.0 | 0.0 | +28886.0 |
| Final `gpu_prefix_cache_hit_rate` | 0.780876 | 0.000000 | +0.780876 |
| Mean TTFT | 951.61 ms | 3540.27 ms | -2588.66 ms |
| Mean latency | 3338.36 ms | 5957.38 ms | -2619.02 ms |

Claim boundary: this is evidence for prompt layout enabling engine-local prefix reuse. It is not evidence for true KV tensor transfer, hidden-state transfer, or cross-engine reuse.

## Method

Both modes used the same Qwen3-32B GPU0 service controls:

```text
max_model_len=8192
gpu_memory_utilization=0.82
num_gpu_blocks=573
enable_prefix_caching=True
tensor_parallel_size=1
```

The probe used one repeated Orion operating-report evidence block and five role prompts: planner, retriever, executor, summarizer, verifier.

Shared mode used the real `compile_prefix_layout(..., prefix_alignment_mode="shared_evidence_prefix")` path. The compiled prompts had `shared_prefix_enabled=true` and a shared prefix of about 28.9 KB. The first role was cold; later roles hit the engine-local prefix cache.

Independent mode used `compile_prefix_layout(..., prefix_alignment_mode="independent")`. Evidence remained inside each role-specific suffix, after the role-specific opening text, so the long evidence did not form a common prompt prefix.

## Artifacts

| Artifact | Role |
| --- | --- |
| `artifacts/e2_prefix_alignment_ablation_summary_20260711_1359.json` | Primary E2 comparison summary. |
| `artifacts/e2_prefix_alignment_shared_20260711_1359.json` | Shared evidence prefix raw probe. |
| `artifacts/e2_prefix_alignment_independent_20260711_1359.json` | Independent role-first raw probe. |
| `scripts/probe_local_vllm_prefix_alignment.py` | Direct local-vLLM prefix-layout probe script. |

## Interpretation

This directly validates the intended mechanism behind `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`: the system is not moving KV tensors, but it is shaping prompt layout so vLLM can reuse the same engine-local prefix across role calls.

The result is stronger than E1 for prefix layout specifically because prompt size is essentially matched while only the prefix position changes.

## Next Action

Proceed to E3 dynamic pruning on/off. E3 should check whether input-level pruning reduces prompt/KV pressure without harming the quality floor.
