# Contest39 Mainchain Results

Collection date: 2026-09-27.

This package summarizes the final 48-task Contest39 mainchain runs. The raw `runs/` directories are unchanged; `task_results.jsonl` is the detailed per-task source for analysis and citation.

## Overall

- Tasks: 48 planned, 48 passed.
- Quality pass rate: 1.000.
- Matched SB-FULL/P-TEXT task pairs: 24; quality matches: 24.

## Variant and Family

| Variant | Family | Passed | Provider requests | Provider tokens | Mean e2e ms | Repairs | State read bytes | Memory actual/replay |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SB-FULL | finance | 12/12 | 22 | 44968 | 77259.2 | 4 | 245760 | 6/6 |
| SB-FULL | service_ops | 12/12 | 19 | 29212 | 51352.7 | 1 | 245760 | 6/6 |
| P-TEXT | finance | 12/12 | 33 | 75275 | 105531.5 | 9 | - | -/- |
| P-TEXT | service_ops | 12/12 | 27 | 46427 | 64752.1 | 3 | - | -/- |

## Matched Comparison

| Family | P-TEXT tokens | SB-FULL tokens | P-TEXT - SB-FULL | P-TEXT requests | SB-FULL requests |
|---|---:|---:|---:|---:|---:|
| finance | 75275 | 44968 | 30307 | 33 | 22 |
| service_ops | 46427 | 29212 | 17215 | 27 | 19 |

## Observed Boundaries

- SB-FULL state metrics are observed for publish/transfer/consume/release, logical payload/read bytes, selected evidence bytes, downstream effects, and physical reclamation.
- P-TEXT state and memory are marked `not_applicable` because those mechanisms are disabled in that variant.
- Provider tokens are model-provider usage, not inter-agent communication tokens.
- `wire_bytes`, `typed_bytes`, object-boundary serialization bytes, and counterfactual avoided provider tokens are not collected or inferred.
- State downstream effects in this run are reported as observed event values; they are not by themselves a causal business-benefit claim.

## Files

- `tasks.jsonl`: one compact record per task.
- `tasks.csv`: flattened analysis index.
- `results.json`: machine-readable aggregate and matched comparison.
- `manifest.json`: collection inputs and scope.
