# Protocol Planner Fastpath Validation 2026-06-08

## Question

After the protocol summarizer compaction work, the remaining question was whether protocol end-to-end
gains still looked small because:

- the benchmark definition was hiding the effect, or
- the implementation was still spending too much live cost in the planner path.

## Change

Code:

- `agents/sample_agents.py`
- `tests/test_smoke.py`

The protocol planner now bypasses the planner LLM and reconstructs the fixed task plan directly from
the repo task contract via `build_plan(task)`.

Text mode is unchanged and still uses the natural-language planner baseline.

This keeps the benchmark aligned with the contest framing:

- text mode remains a text-first coordination path
- protocol mode becomes a structure-first coordination path

## Verification

- `python -m pytest -q`
  - `57 passed`
- `python -m runtime.smoke`
  - passed

Benchmark packages:

- previous comparison point:
  - `runs/host_goal_eval_20260608_204904_protocol_summary_output_compact_api_r1/`
- new formal serialized rerun:
  - `runs/host_goal_eval_20260608_210907_protocol_planner_fastpath_api_r3/`

## What changed

### Aggregate

Comparing protocol before vs after the planner fastpath:

- total tokens: `20266.00 -> 9944.33`
- task ms: `98622.38 -> 54195.78`
- control bytes: `132497.00 -> 125483.00`

Text stayed near the previous range in the `repeat=3` rerun:

- text total tokens: `29715.67`
- text task ms: `131592.69`

So the protocol gain is not just a `repeat=1` spike. It remains large under serialized `repeat=3`.

### Role-level tokens

Protocol role-level token accounting is now:

- `planner_requests = 0.00`
- `planner_total_tokens = 0.00`
- `summarizer_total_tokens = 9944.33`

This is the main new result.

The earlier “protocol still does not save enough token/time” diagnosis was mostly an implementation
issue: protocol was still paying a planner LLM cost that the structure-first path did not need.

### Phase timing

Protocol phase timing moved to:

- `planner_ms = 0.48`
- `summarize_ms = 35486.95`
- `task_ms = 54195.78`

This sharply narrows the remaining bottleneck:

- planner is no longer the live latency problem
- summarizer plus external API latency are now the dominant remaining cost

### Contest lanes

Protocol lane metrics in the new `repeat=3` run:

- `communication`: `382.00` tokens, `2244.22ms`
- `state_transfer`: `369.67` tokens, `2221.04ms`
- `memory`: `396.00` tokens, `1999.71ms`

Compared with the previous protocol package, every contest lane improved materially in both tokens and
task time.

### Memory interpretation

This run does not change the honest memory conclusion.

The benchmark is already measuring more than hit/no-hit, including:

- `memory_query_count`
- `memory_hit_rate`
- `skipped_step_count`
- `reuse_gain`
- per-task reuse decisions

But `assist_only` still does not beat `memory_off` end-to-end in protocol mode:

- `memory_off`: `375.67` tokens, `2197.14ms`
- `assist_only`: `388.79` tokens, `2226.36ms`
- `replay_enabled`: `376.57` tokens, `1724.31ms`

So the supported claim remains:

- replay / step-skipping works
- assist-only memory still does not show a stable end-to-end win

## Conclusion

The current evidence supports a stronger judgment than before:

1. The benchmark definition is not the main reason protocol gains once looked too small.
2. The main issue was implementation-side: protocol was still paying unnecessary planner LLM cost.
3. After removing that cost, protocol now shows a large and stable live token/time win over text.
4. The remaining optimization target is the summarizer path, not the planner path.
5. Memory is already measured beyond hit/no-hit, but assist-only memory still lacks a stable end-to-end
   advantage.
