# Mechanism-level metrics

Run: `longtext-demo-v3-20260929_104844-2545919`

The figures below are recomputed from the scored records in `records.jsonl`.
`task_wall_ms` is retained as a slot-level end-to-end measure, while the
mechanism claims use the fields that directly measure cache hits, consumer
prefill, TTFT, and logical input size.

## APC

The comparison is paired by case: `apc_on_independent` versus
`apc_on_shared` (4 pairs).

| metric | independent mean | shared mean | change |
|---|---:|---:|---:|
| task wall | 49,200.3 ms | 47,091.9 ms | 4.29% lower |
| consumer TTFT | 2,540.2 ms | 264.3 ms | 89.59% lower; 9.61x faster |
| observed hit tokens | 48 | 5,168 | 107.7x more |

Independent hit deltas are 48 tokens for all four pairs. Shared hit deltas
are 4,096, 4,160, 6,208, and 6,208 tokens. The aggregate task-wall change
is small and is not monotonic per case; the strongest APC evidence is the
prefix hit and consumer TTFT.

## KV

The comparison is paired by case: `full_replay` versus `continuation`
(4 pairs). The continuation path includes KV store/load, so those costs are
shown separately rather than hidden in the end-to-end number.

| metric | full replay mean | continuation mean | change |
|---|---:|---:|---:|
| task wall | 55,519.5 ms | 53,532.3 ms | 3.58% lower |
| consumer request wall | 16,772.0 ms | 14,779.9 ms | 11.88% lower |
| consumer TTFT | 2,570.6 ms | 1,005.7 ms | 60.88% lower; 2.56x faster |
| consumer computed prefill | 5,666.5 tokens | 545.5 tokens | 90.37% lower |
| consumer inherited KV | 0 tokens | 5,120 tokens | 20,480 tokens across 4 continuations |

Producer computed prefill is identical in the two conditions (5,874.5 tokens
mean). Continuation store and load average 2,986.4 ms and 749.0 ms,
respectively; this fixed overhead offsets much of the consumer-side gain in
the complete task wall.

## Logit

There are 3 resolved cases and 1 intentionally unresolved case. For the
resolved cases, the means are:

| metric | full context | compact | selective |
|---|---:|---:|---:|
| logical input | 3,726.7 tokens | 924.0 tokens | 924.0 tokens |
| provider request wall | 8,894.7 ms | 7,366.4 ms | 7,248.7 ms |

Compared with full context, compact/selective reduce logical input by 75.21%.
Provider request wall is 17.18% lower for compact and 18.51% lower for
selective on these resolved cases. The unresolved selective case expands from
621 to 3,008 logical tokens through a second full recheck (2,401.2 ms total)
and correctly returns `abstain`; selective is therefore an adaptive policy,
not a guaranteed latency win on every case.

## Run-level service overhead

Service transitions are separate from the mechanism metrics:

| transition | elapsed |
|---|---:|
| standard stop | 4,033.8 ms |
| KV start + health | 68,795.0 ms |
| KV stop | 4,042.0 ms |
| standard restore + health | 68,630.0 ms |
| total | 145,500.8 ms (145.5 s) |

This overhead is charged to the run workflow and cannot be attributed to an
individual APC, KV, or Logit slot.

Sources: [`records.jsonl`](./records.jsonl),
[`summary.json`](./summary.json), and
[`service/restore-evidence.json`](./service/restore-evidence.json).
