# Contest Requirement Guardrails 2026-06-08

## Why this note exists

During the latest host-mainline optimization pass, one protocol variant removed the planner and
summarizer LLM calls entirely. That variant produced a very large token/time win, but it moved the
comparison away from the intended contest reading of:

- pure-text multi-agent collaboration
- structured-protocol multi-agent collaboration

This note records why that direction should **not** remain the current mainline claim surface.

## Requirement-first reading

From `docs/reference/题目.md`, the stable object is:

1. at least 3 agents covering planning / retrieval / execution / summarization roles
2. both `text` and `protocol` collaboration modes
3. a reproducible comparison under the same task conditions
4. structured communication, non-text state transfer, and shared memory reuse

The contest is evaluating a multi-agent coordination mechanism, not a unilateral collapse of the
agent reasoning surface into a mostly non-LLM protocol path.

## Hard judgment

The protocol variant that removed planner/summarizer LLM calls was useful as a diagnostic, but it is
not the right current-worktree benchmark headline.

Reason:

- it changes not only the communication substrate
- it also changes who is doing semantic planning/summarization work
- so the token/time gain becomes partly a role-elimination gain, not just a structured-coordination gain

That weakens the fairness of the text-vs-protocol comparison for the contest surface.

## What remains valid after rollback

The following changes still fit the contest object and should remain:

1. protocol planner/summarizer prompt compaction
2. compact protocol summary handoff instead of full evidence replay
3. compact memory assist hints instead of replaying full old summaries
4. state-transfer handoff telemetry (`handoff_*`) instead of over-reading total `state_bytes`
5. transfer baseline cleanup so text mode does not pay unused non-text state cost

These improve fairness or reduce avoidable overhead without removing the role structure itself.

## What should not be treated as the current mainline optimization

Do not treat the following as the current benchmark headline:

1. protocol planner LLM removed entirely
2. protocol summarizer LLM removed entirely
3. protocol memory indexing that relies on those removed roles as a new semantic contract

Those variants may still be mentioned as exploratory diagnostics, but not as the main contest claim.

## Safer next optimization targets

The next optimization pass should stay within the role-preserving comparison:

1. shrink protocol planner prompt fields further without deleting the planner role
2. shrink protocol summarizer prompt fields further without deleting the summarizer role
3. reduce repeated text inside memory commit / retrieval context while keeping semantic summaries intact
4. improve memory assist usefulness so `assist_only` can beat `memory_off` without changing task semantics
5. separate phase-level telemetry further so protocol gains are easier to attribute cleanly

## Bottom line

For the contest mainline, the right standard is not:

> any change that makes protocol much faster

The right standard is:

> changes that preserve the multi-agent role comparison while making structured coordination more efficient

That is the guardrail for the next round of host-mainline optimization.
