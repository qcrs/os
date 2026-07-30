# KV Prefix Reuse Probe Dataset

This directory contains a mechanism-only continuous family for testing StateBus cache-aware prompt layout and corpus-aware scheduling.

## Requirement

The dataset should isolate this question:

> If StateBus groups tasks that share the same long evidence corpus, can local vLLM automatic prefix caching show higher prefix-cache hit rate and lower TTFT than an interleaved schedule?

It must not require StateBus to export, pass, or rewrite model-internal KV tensors. The KV tensor remains engine-local. StateBus only controls prefix identity, prompt layout, evidence pruning, and task order.

## Design

The family uses two realistic operating reports:

- `orion_factory_ops_report_2026.md`
- `nova_retail_ops_report_2026.md`

Both reports share the same metric table schema:

```text
quarter, revenue_musd, gross_margin_pct, operating_expense_musd, churn_rate_pct, on_time_delivery_pct
```

They differ in content, entity, narrative, and file hash. This gives the runtime two distinct `corpus_prefix_hash` groups while keeping deterministic fact checks simple.

## Probe Schedules

The manifest declares two intended schedules:

```text
cache_friendly:
  Orion warmup -> Orion metrics -> Nova warmup -> Nova metrics

cache_hostile:
  Orion warmup -> Nova warmup -> Orion metric -> Nova metric -> ...
```

The manifest records both orders in `kv_prefix_probe`. The family is available as an explicit mechanism probe, and `statebus.benchmark.kv_prefix_schedule` can materialize both schedule plans. It is intentionally excluded from the default formal continuous collection and remains `demo_secondary`.

## Expected Evidence

Estimated evidence can be collected without local vLLM:

- `kv_corpus_prefix_hash_reuse_count`
- `kv_corpus_level_prefill_saved_tokens_estimate`
- `evidence_pruning_estimated_kv_tokens_saved`

Mechanism evidence requires local vLLM with prefix caching enabled:

- prefix-cache query/hit deltas from `/metrics`
- streaming TTFT for cache-friendly vs cache-hostile order
- unchanged deterministic quality floor

## Claim Boundary

This dataset supports a claim about engine-local prefix reuse planning. It does not support claims about cross-process KV tensor transfer, cross-model KV sharing, or internal KV compression.
