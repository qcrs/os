# E3 Dynamic Pruning Ablation - 2026-07-11

## Conclusion

E3 passes as a deterministic retrieval-level mechanism probe. Dynamic pruning reduced selected evidence and estimated KV pressure while preserving the hard-fact quality proxy.

| Metric | Dynamic off | Dynamic on | Delta |
| --- | ---: | ---: | ---: |
| Dynamic pruning enabled | false | true | enabled |
| Budget decision | empty | `capacity_critical` | n/a |
| Selected evidence bytes | 333 | 112 | -221 |
| Selected evidence tokens estimate | baseline | baseline - 56 | -56 |
| Dropped candidate count | 1 | 5 | +4 |
| Estimated KV tokens saved | 36 | 92 | +56 |
| Hard fact preserved | `fact-revenue-1` | `fact-revenue-1` | pass |

Primary result:

```text
dynamic_pruning_reduces_prompt_kv_pressure_with_quality_proxy_preserved
```

Claim boundary: this is input-level evidence pruning. It does not prune model-internal KV tensors and does not prove final formal quality by itself.

## Method

The probe used deterministic retrieval only, not a full LLM/formal run:

```text
task_family=financial_report_analysis
intent_op=compare_metric
ticker=ACME
quarter=2026Q1
metric=revenue
embedding_mode=deterministic
top_k=3
```

Dynamic-on settings:

```text
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=true equivalent
available_kv_cache_bytes=20000
kv_bytes_per_token=256
base_threshold=0.6
capacity_buffer=0.2
min_keep_semantic_contexts=1
min_keep_lexical_hints=0
```

Quality proxy:

```text
hard_fact_and_structured_evidence_preservation
```

The proxy passed because the required hard fact stayed identical across off/on:

```text
fact-revenue-1
```

## Artifact

| Artifact | Role |
| --- | --- |
| `artifacts/e3_dynamic_pruning_ablation_20260711.json` | Dynamic pruning off/on comparison. |
| `scripts/probe_dynamic_pruning_ablation.py` | Deterministic retrieval-level E3 probe. |

## Interpretation

E3 shows the intended mechanism: under tight KV budget assumptions, StateBus can raise the evidence importance threshold, drop lower-value context, and keep the hard fact needed by the task.

This supports moving to a later formal guard only after E1 and E2 are also considered stable. The formal guard should still verify end-to-end quality floor, because this E3 probe checks a retrieval-level quality proxy rather than final answer quality.
