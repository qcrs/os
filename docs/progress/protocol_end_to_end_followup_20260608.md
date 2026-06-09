# Protocol End-to-End Follow-up 2026-06-08

## Question

After the benchmark fairness closure, the remaining question was:

- why is protocol end-to-end time still not dropping enough relative to text?
- why is protocol token reduction still smaller than expected?
- is that mostly a benchmark-definition problem or a code-path problem?
- is memory currently only checking whether a hit happened, or is it measuring real reuse outcomes?

## Short answer

As of the current worktree, this is **mostly a code-path problem, not a benchmark-definition problem**.

The benchmark already measures more than memory hit/no-hit:

- `memory_query_count`
- `memory_hit_rate`
- `memory_assist_task_count`
- `memory_rejected_task_count`
- `skipped_step_count`
- `reuse_gain`
- per-task reuse decisions (`assist`, `reject`, `skip_execute`, `skip_retrieve_execute`)

So the memory question is not “did we check whether a hit happened”. We did.

The real remaining question is:

> after a hit, does the current protocol / memory path actually reduce enough LLM work and enough live wall-clock to matter end-to-end?

## What the evidence showed before this follow-up

The earlier live package `runs/host_goal_eval_20260608_195707_memory_assist_compact_api_r1/` already showed:

- protocol total token reduction was real
- planner token reduction was real
- but summarizer cost was still large
- end-to-end wall-clock was still heavily dominated by summarizer phase and API jitter

That meant:

- benchmark lane definitions were not the primary bottleneck
- protocol still needed more aggressive summarizer-path compression

## Optimization landed in this follow-up

### 1. Protocol summarizer no longer consumes full evidence handoff text

Code:

- `agents/sample_agents.py`

The protocol summarizer path now receives a compact structured handoff instead of the full retrieved
evidence text. It includes:

- query
- route
- route source
- route confidence
- retrieved doc ids
- matched signals
- optional memory assist hint
- evidence preview

This keeps protocol summary generation closer to “structured cooperation” rather than drifting back
toward “full-text collaboration”.

### 2. Deterministic protocol summary output was tightened

Code:

- `runtime/llm.py`

The deterministic protocol summarizer now emits a shorter action-oriented summary string rather than
reconstructing `Evidence:` and `Playbook:` as a longer narrative block. This keeps the contract aligned
with the intended structured protocol path.

### 3. Tests were tightened

Code:

- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`

Added coverage for:

- compact protocol summary handoff shape
- compact protocol summary output shape
- deterministic protocol summarizer compact-output behavior

## Verification

- `python -m pytest -q`
  - `56 passed`
- `python -m runtime.smoke`
  - passed

New benchmark packages:

- `runs/host_goal_eval_20260608_203744_protocol_summary_compact_api_r1/`
- `runs/host_goal_eval_20260608_204904_protocol_summary_output_compact_api_r1/`

## What changed in the live evidence

### Aggregate

Comparing:

- before: `runs/host_goal_eval_20260608_195707_memory_assist_compact_api_r1/`
- mid: `runs/host_goal_eval_20260608_203744_protocol_summary_compact_api_r1/`
- after: `runs/host_goal_eval_20260608_204904_protocol_summary_output_compact_api_r1/`

Protocol aggregate token totals moved:

- `20938 -> 19975 -> 20266`

So:

- the first summarizer-input compression change produced a real token drop
- the second summarizer-output tightening did not further reduce aggregate protocol tokens in a stable way

Protocol aggregate task ms moved:

- `94390.26 -> 103090.79 -> 98622.38`

So:

- aggregate live wall-clock is still noisy at `repeat=1`
- a single live run is enough to expose direction, but not enough to prove a stable timing gain for every sub-change

### Lane-level signs are still useful

From `203744 -> 204904`, protocol lane task ms changed:

- `communication`: `4194.28 -> 3825.07`
- `state_transfer`: `4475.16 -> 3580.32`
- `memory`: `4056.14 -> 3626.20`

This is important:

- the protocol path itself is still capable of getting faster
- the remaining difficulty is that aggregate live timing is noisy and summarizer/API latency still dominates

### Memory-policy interpretation

The current live evidence still does **not** support a stronger assist-style memory claim.

For example, in the latest package:

- `memory_off` protocol task ms: `3708.61`
- `assist_only` protocol task ms: `3903.42`
- `replay_enabled` protocol task ms: `3660.89`

So the honest memory conclusion remains:

- replay / step-skipping is supported
- assist-only still does not stably beat memory-off end-to-end

## Conclusion

The current state supports these judgments:

1. The benchmark is not the main reason protocol gains look “too small”.
2. The main remaining bottleneck is implementation-side:
   - protocol still spends too much of the live budget in summarizer/API time
   - aggregate wall-clock remains sensitive to LLM latency jitter
3. Memory already measures real reuse outcomes, not just hit/no-hit.
4. The still-open gap is not “did memory hit”.
   It is “did the accepted reuse path reduce enough live cost to beat the baseline”.

## Recommended next step

The next worthwhile optimization should stay on the protocol summarizer path, not on benchmark redesign.

Best next target:

- make protocol summarization closer to a structured outcome record rather than a natural-language mini-summary
- keep memory commit text concise enough that future assist/replay retrieval does not re-inflate downstream prompts

That direction is more aligned with the contest claim than rewriting the benchmark again.
