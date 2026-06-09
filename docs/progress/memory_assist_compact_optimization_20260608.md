# Memory Assist Compact Optimization 2026-06-08

## Why this was the right post-benchmark optimization

After the benchmark fairness closure, the clearest remaining host-mainline gap was the `assist_only`
memory path.

The benchmark package `runs/host_goal_eval_20260608_26task_lane_audit_api_r3/` showed:

- `communication` claim: already supported
- `state_transfer` claim: already supported, with the explicit `text brief handoff` scope
- `memory` claim: replay / step-skipping was supported, but `assist_only` was still not beating
  `memory_off`

The live `api_r3` memory-policy rows before this change were:

- `memory_off`
  - text `llm_total_tokens=1128.17`, `task_ms=4401.01`
  - protocol `llm_total_tokens=729.56`, `task_ms=3543.84`
- `assist_only`
  - text `llm_total_tokens=1146.03`, `task_ms=4562.10`
  - protocol `llm_total_tokens=767.77`, `task_ms=3591.56`

That pattern strongly suggested the current assist implementation was paying too much prompt/context
overhead relative to the help it provided.

## Local and upstream design signal

This optimization direction is consistent with the local `third_party/` references that were reviewed
for stage 7:

- `third_party/haystack/README.md`
  - says Haystack is built for context engineering with explicit control over how information is
    retrieved, ranked, filtered, combined, structured, and routed before it reaches the model
- `third_party/langgraph/README.md`
  - emphasizes long-running, stateful agents plus explicit memory layers rather than uncontrolled
    prompt growth
- `third_party/memsearch/README.md`
  - emphasizes progressive retrieval and layered recall instead of blindly pasting all recalled text
- `third_party/semantic-router/README.md`
  - emphasizes a fast routing / decision layer so tool-use decisions do not wait on unnecessary LLM work

The relevant upstream repos for those local mirrors are:

- `https://github.com/deepset-ai/haystack`
- `https://github.com/langchain-ai/langgraph`
- `https://github.com/zilliztech/memsearch`
- `https://github.com/aurelio-labs/semantic-router`

## What changed

The retriever memory-assist path was tightened in two ways:

1. accepted assist memory is now injected into `DENSE_EVIDENCE` as a bounded
   `MEMORY_ASSIST_HINT ...` line rather than as the full prior summary text
2. the executor-facing `FEATURE_BUNDLE` is now built from fresh corpus evidence only, while still
   carrying structured assist metadata such as:
   - `memory_assist_ids`
   - `memory_assist_hint`
   - `memory_hint_route`

This keeps the assist path alive and measurable, but stops it from inflating planner/summarizer
context more than necessary.

## Code surface

- `agents/sample_agents.py`
  - added compact assist-hint construction
  - stopped using full assist summary text as feature-bundle evidence input
- `tests/test_smoke.py`
  - added compact-hint unit coverage
  - added end-to-end assist-path regression coverage

## Verification

### Functional verification

- `python -m pytest -q`
  - `54 passed`
- `python -m runtime.smoke`
  - passed

### Deterministic regression package

- `runs/host_goal_eval_20260608_195707_memory_assist_compact_det_r1/`

This package mainly verifies:

- no replay-contract regression
- no lane-structure regression
- no task expectation mismatch regression

### Live API direction-check package

- `runs/host_goal_eval_20260608_195707_memory_assist_compact_api_r1/`

This package is not a new formal timing package. It is a targeted direction-check for the stage-7
optimization.

## Result after the optimization

Compared to the earlier formal live package `runs/host_goal_eval_20260608_26task_lane_audit_api_r3/`,
the new `api_r1` package shows the expected direction for `assist_only`:

- `assist_only` text
  - tokens: `1146.03 -> 1138.46`
  - planner tokens: `667.46 -> 666.23`
  - summarizer tokens: `478.56 -> 472.23`
  - summarize ms: `1425.93 -> 1578.82`
  - retrieve ms: `605.08 -> 644.78`
  - task ms: `4562.10 -> 4836.88`
- `assist_only` protocol
  - tokens: `767.77 -> 768.62`
  - planner tokens: `326.69 -> 326.77`
  - summarizer tokens: `441.08 -> 441.85`
  - summarize ms: `1292.52 -> 1440.14`
  - retrieve ms: `594.67 -> 563.40`
  - task ms: `3591.56 -> 3741.02`

At the single-task level, the canonical assist case `sample-cache-002` did improve materially:

- text
  - control bytes: `11520 -> 6225`
  - total tokens: `1176`
  - planner tokens: `670`
  - summarizer tokens: `506`
  - task ms: `4490.11`
- protocol
  - control bytes: `10672 -> 4900`
  - total tokens: `764`
  - planner tokens: `330`
  - summarizer tokens: `434`
  - task ms: `4430.05`

So the implementation change is real and moves the intended object in the right direction.

## Honest conclusion

This optimization is worth keeping because it makes the assist path more natural and less bloated.

But it does **not** justify upgrading the overall memory claim:

- replay / step-skipping is still the clear supported advantage
- assist-style shared memory still does not have stable end-to-end superiority over `memory_off`
  on the current 26-task live package family

So the benchmark claim boundary remains:

- `communication`: supported
- `state_transfer`: supported, with the explicit `text brief handoff` baseline scope
- `memory`: supported for replay / step-skipping, not yet for broad assist-style end-to-end gain
