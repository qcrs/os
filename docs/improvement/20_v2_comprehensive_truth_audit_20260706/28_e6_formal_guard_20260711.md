# E6 Formal Guard - 2026-07-11

## Conclusion

E6 passes. The 25-case formal guard completed with the mechanism switches enabled and preserved the quality floor across all four layers.

| Layer | Case count | Quality floor pass count |
| --- | ---: | ---: |
| L0 | 25 | 25 |
| L1 | 25 | 25 |
| L2 | 25 | 25 |
| L3 | 25 | 25 |

Claim boundary: this validates formal quality preservation for the current local-vLLM mechanism profile. It does not prove KV tensor export, hidden-state transfer, cross-engine KV reuse, or multi-GPU success.

## Run Control

```text
run_id=kv-e6-guard-20260711-1448
model=qwen3-32b
base_url=http://127.0.0.1:53334/v1
benchmark_tier=formal
role_path_mode=local_vllm
embedding_mode=deterministic
state_pool_mode=shared_memory
transport=loopback
max_context_tokens=8192
```

Mechanism switches:

```text
STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1
STATEBUS_EVIDENCE_AVAILABLE_KV_CACHE_BYTES=700000
STATEBUS_EVIDENCE_KV_BYTES_PER_TOKEN=256
STATEBUS_EVIDENCE_BASE_IMPORTANCE_THRESHOLD=0.6
STATEBUS_EVIDENCE_CAPACITY_BUFFER=0.2
STATEBUS_EVIDENCE_MIN_KEEP_SEMANTIC_CONTEXTS=1
STATEBUS_EVIDENCE_MIN_KEEP_LEXICAL_HINTS=0
```

The wrapper was also fixed to pass the `STATEBUS_EVIDENCE_*` environment variables into the container before this run.

## Results

| Metric | Text L0 | Protocol L3 | Delta |
| --- | ---: | ---: | ---: |
| Total tokens | 113949 | 62667 | -51282 |
| Prompt tokens | 99200 | 53548 | -45652 |
| Control bytes | 42926 | 11670 | -31256 |
| Quality pass count | 25 | 25 | 0 |

L3 mechanism telemetry excerpt:

| Metric | Value |
| --- | ---: |
| `evidence_pruning_drop_count` | 25 |
| `evidence_pruning_estimated_kv_tokens_saved` | 9644 |
| `neural_prefix_reuse_estimate_count` | 25 |
| `neural_prefix_cache_hit_count_estimate` | 25 |
| `neural_prefix_shared_prefix_bytes` | 4359 |
| `pruning_gain_bytes` | 77134 |
| `state_pool_shared_memory_mode_count` | 25 |
| `semantic_state_transfer_count` | 25 |

Final vLLM metrics excerpt:

| Metric | Value |
| --- | ---: |
| `gpu_prefix_cache_hit_rate` | 0.658764 |
| `request_prompt_tokens_sum` | 337210 |
| `generation_tokens_total` | 42653 |
| `request_success_total{stop}` | 402 |
| `request_success_total{length}` | 4 |
| `num_gpu_blocks` | 573 |
| `num_gpu_blocks_override` | 573 |

## Artifacts

| Artifact | Role |
| --- | --- |
| `artifacts/e6_formal_guard_summary_20260711_1448.json` | Compact formal wrapper summary copied from the run root. |
| `artifacts/e6_formal_guard_mechanism_excerpt_20260711_1448.json` | Small mechanism and metrics excerpt for documentation. |
| `/home/qcrs/statebus/runs/kv-e6-guard-20260711-1448/formal_suite.stdout.json` | Full live-runner JSON output. |
| `/home/qcrs/statebus/runs/kv-e6-guard-20260711-1448/runtime/benchmark_reports/kv-e6-guard-20260711-1448-formal-suite.json` | Full benchmark report. |

## Interpretation

E6 closes the immediate quality-risk question after E1/E2/E3:

- E1/E2 show engine-local prefix reuse benefits from scheduling and shared evidence prefix layout.
- E3 shows input-level dynamic pruning reduces evidence/KV pressure in a retrieval-level probe.
- E6 shows the combined current profile preserves the formal 25-case quality floor.

This supports a stronger mechanism-benefit story, but the supported term remains `Engine-Local Prefix Reuse`. True KV tensor handoff remains future work.
