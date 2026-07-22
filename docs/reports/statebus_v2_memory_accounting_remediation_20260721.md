# StateBus v2 Memory Accounting Remediation

This report records the post-review accounting contract. Historical JSON and
canonical run artifacts remain unchanged.

## Reporting Boundary

- The historical `23` rows are reported only as `recorded_consumption_count`.
- The historical role split (`8 Executor`, `15 Summarizer`) describes the
  pre-fix ledger and is not evidence that all rows reached a role boundary.
- The default Summarizer path is memory-free. A Summarizer row is counted only
  when a role receipt names an approved memory ID and supplies a persisted
  rendered-request hash.
- Executor recipe reuse is counted only for the recipe ID actually attempted.
  A failed attempt is `recipe_executed` with `execution_outcome=failed`; it is
  never `validated_replay` or `skipped`.
- `skipped_llm_call_count` is zero for deterministic transform replay. It is
  non-zero only when a paired call ledger proves that an LLM generation was
  avoided.

## Accounting Fields

New adaptive manifests expose `memory_consumption_accounting` alongside the
raw `memory_consumption_records`:

| Field | Meaning |
| --- | --- |
| `candidate_count` | IDs returned by hybrid retrieval |
| `approved_count` | IDs allowed by compatibility and policy |
| `disclosed_count` | narrow views sent to a role boundary |
| `recorded_consumption_count` | physical consumption-record rows |
| `actual_consumed_count` | receipt-backed rows with rendered or recipe hash |
| `rendered_count` / `recipe_executed_count` | atomic boundary evidence |
| `output_accepted_count` / `failed_attempt_count` | execution outcome |
| `validated_replay_count` / `exact_replay_count` | strict replay rows only |
| `skipped_generation_step_count` / `skipped_llm_call_count` | verified savings |
| `recorded_role_counts` | role split for all physical rows, including historical/controller-only rows |
| `actual_role_counts` | role split restricted to rendered/executed receipt rows |

Adaptive formal and adaptive-memory summaries also expose a collection-level
projection. The generator recomputes raw recorded and receipt-backed row counts
from each case ledger and sets `projection_consistent=false` if they disagree
with the case accounting payload. Formal system/safety gating rejects that
inconsistency.

The raw rows retain candidate IDs, prompt/recipe hashes, output decision
surface hashes, role, step, and outcome so a report can be recomputed without
trusting an aggregate counter.
