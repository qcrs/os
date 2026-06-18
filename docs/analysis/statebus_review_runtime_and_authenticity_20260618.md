# StateBus Goal2 Runtime and Authenticity Audit

Date: 2026-06-18

> Superseded status note, 2026-06-18:
> This file remains useful for runtime/authenticity analysis, but its
> current-headline status statements about memory being disabled or replay being
> absent are pre-Goal3. The current frozen headline source is
> `docs/reports/final_claim_matrix_and_freeze_20260618.md`, backed by
> `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`.
> Do not cite this file as evidence that current `contest_honest_headline_v1`
> still lacks repeat=10 stability or headline memory/replay.

This document audits whether the current runtime behavior is authentic for the
contest claims. It deliberately separates implementation reality from benchmark
story.

## Validation Snapshot

Current validation commands checked for this review hardening pass:

- `source deploy/activate_statebus_host.sh && python -m runtime.smoke` passed.
  The smoke output explicitly scopes itself as a deterministic repeat=1 host
  sanity check, not formal API timing evidence. Latest observed smoke values:
  text `memory_hits=0.0`, `messages=292.0`, `control_bytes=184033.0`;
  protocol `memory_hits=0.0`, `messages=292.0`, `control_bytes=150133.0`.
- An earlier full `python -m pytest -q` run during the Goal2 closeout failed at
  `tests/test_llm_runtime.py:532`, in
  `test_plan_parser_rejects_missing_validate_for_validate_first_task`, because
  `_plan_from_llm_output()` did not raise
  `ValueError("missing required semantics: validate")`.
- A targeted recheck in the current worktree,
  `python -m pytest -q tests/test_llm_runtime.py::test_plan_parser_rejects_missing_validate_for_validate_first_task`,
  now passes. This means the stale full-suite failure must not be treated as
  current proof of a red test without rerunning the full suite, but it remains a
  useful contract boundary to document.
- A fresh full-suite recheck after the documentation hardening edits,
  `source deploy/activate_statebus_host.sh && python -m pytest -q`, passed:
  `207 passed, 101 warnings in 406.35s`.

Runtime-contract meaning of the pytest item:

- `tests/test_llm_runtime.py:490-533` constructs a planner output for
  `planner-support-auth-llm-002` with `retrieve`, `execute`, and `summarize`,
  but no `validate`.
- `agents/sample_agents.py:1675-1715` parses LLM planner output and calls
  `_validate_planner_semantic_coverage()`.
- `agents/sample_agents.py:1718-1747` also has a compatibility insertion path
  that can add a validate step automatically when a YAML contest pack allows
  direct validate compatibility.
- `agents/sample_agents.py:2175-2180` is the strict semantic coverage check that
  should reject missing required roles.

The contract boundary is therefore not "runtime cannot run". It is: validate
compatibility insertion is acceptable for YAML contest headline compatibility,
but planner-support LLM surfaces must remain strict, otherwise static thickening
can hide a missing planner role.

## Runtime Role Map

### Planner

Current behavior:

- For the contest headline, `plan_source_default` is `yaml`.
- `PlannerAgent.plan_task()` returns `build_plan(task)` directly for YAML plans.
- `build_plan()` creates a fixed retrieve/validate/execute/summarize DAG when
  `required_plan_semantic_roles` contains `validate`.
- LLM planning exists as a support surface, but it is not the contest headline
  default.

Authenticity judgment:

- The Planner role exists and the plan contract is explicit.
- In the contest headline, planning is not open-ended reasoning; it is a static
  task contract compiler.

Classification:

- `contest closure required`: adequate for system completeness.
- `reporting / narrative issue`: do not imply headline task planning is fully
  LLM-open or adaptive.
- `structural design mismatch`: compatibility insertion of validate steps must
  stay scoped to YAML contest rows, not generalized into proof that LLM planners
  naturally emit the validate role.

### Retriever

Current behavior:

- Uses `retrieve_corpus_docs()` over repo-local corpus docs.
- Formal clean retrieval removes preferred-doc/theme/group bonuses.
- Still retrieves from a small curated corpus shaped around release-regression
  families.
- Extracts route/tool hints from corpus docs and builds feature bundles.
- Searches memory when the runtime contract allows it, but current headline
  disables memory reuse.

Authenticity judgment:

- Retriever is not a hardcoded YAML passthrough. It performs semantic/lexical/tag
  ranking over a local corpus and builds a real state object.
- It is not open retrieval. It is a curated corpus evidence packager with
  route/tool-labeled docs and route-shaped families.

Classification:

- `structural design mismatch`: fine for a contest prototype, weak for broad
  retrieval generality claims.
- `task design issue`: current tasks are too aligned to the corpus route labels.

### Executor

Current behavior:

- Implements route/tool selection through `ToolRegistry` and playbook execution.
- For `state_packet_minimal`, reads `EXECUTOR_DECISION_PACKET` plus evidence.
- For `text_whole_lane`, reconstructs a feature bundle from natural-language
  handoff text, then uses the same registry/playbook path.
- The validate step emits a `VALIDATION_GATE_PACKET` and can block protocol
  execution when validation fails.

Authenticity judgment:

- Executor is real enough as a tool/playbook executor, and the validation gate is
  not a dummy no-op.
- It is still mainly a route-to-playbook selector. It is not CodeAct, not a
  generic tool planner, and not a broad executor marketplace.

Classification:

- `contest closure required`: acceptable for current contest host prototype.
- `structural design mismatch`: insufficient if the claim becomes general tool
  execution or open-ended CodeAct.

### Summarizer

Current behavior:

- Uses LLM client for summarization.
- For `text_whole_lane`, summary evidence becomes executor action text.
- For protocol, summary input is a compact JSON-like packet with route, confidence,
  doc ids, matched signals, actions, and memory hint.
- Writes memory commits with route/tool/doc/replay metadata.

Authenticity judgment:

- Summarizer role is real and is the main LLM consumer in the current headline.
- It is not a strong differentiator for text/protocol method because both sides
  consume roughly similar summarization budgets under the current API run.

Classification:

- `contest closure required`: role implemented.
- `benchmark artifact`: current headline token deltas mostly reflect summarizer
  prompt symmetry, not structured protocol savings.

## State Transfer Authenticity

The current protocol path is authentic at the minimal packet level:

- `state_packet_minimal` produces `DENSE_EVIDENCE` and `EXECUTOR_DECISION_PACKET`.
- Current repeat=1 reports show expected executor consumption rate `1.00`.
- Unexpected support/audit typed-state visibility is `0.00`.

This is stronger than a documentation-only feature. The executor really consumes
the packet.

Boundary:

- It is not hidden-state, KV cache, activation, or neural latent reuse.
- `FEATURE_BUNDLE`, ranked evidence, tool candidates, channel snapshots, and
  replay bundles are support/audit unless a pack explicitly makes them primary.

Classification:

- `contest closure required`: valid implemented contest mechanism.
- `reporting / narrative issue`: keep wording precise.

## Memory and Replay Authenticity

Memory and replay are real in the codebase and historical evidence:

- Retriever can search memory and build memory priors.
- Summarizer commits memory with route/tool/reuse metadata.
- Orchestrator supports skip-retrieve-execute and skip-execute paths.
- Historical host packages show non-zero skipped steps and reuse gain.

But the current contest headline is fresh-retrieval-only:

- current API repeat=1 reports memory hit `0.00`;
- current headline replay gate is not applicable;
- current headline task rows have skipped step count `0`.

Authenticity judgment:

- Memory is implemented and should remain a core asset.
- Current headline does not prove memory reuse effect.

Classification:

- `benchmark artifact`: evidence exists in another layer, not in the current
  formal headline.

## Gold-Field and Benchmark-Hint Leakage Review

Current improvements:

- Formal structure clean retrieval disables preferred-doc bias and theme/group
  bonuses.
- `text_whole_lane` guard rejects explicit route/tool slot leakage.
- Object parity gate passes in latest repeat=1 packages.

Remaining authenticity risks:

- Corpus docs include `eval_route_label` and `eval_tool_label`.
- Runtime hint extraction can still derive route/tool hints from corpus docs.
- Queries and family docs are strongly route-shaped around known incident
  families.
- `required_prior_routes` and `required_prior_rejections` are static task fields,
  not yet dynamic evidence of a prior-dependent runtime decision in the headline.

This is no longer a simple hidden-field bug. It is a benchmark design and
generalization problem.

Classification:

- `task design issue`
- `structural design mismatch`

## Replay / Reuse Scaffold Review

The replay path has undergone cleanup from explicit source-task pointers toward
runtime evidence matching. That is good. However, current replay proof still
comes from controlled packages rather than the formal headline.

For contest memory scoring, the question is not just "can replay happen?" The
question is whether a related continuous task can reuse prior memory accurately
and efficiently in a way that changes repeated work or admissible action. The
current headline does not answer that.

Classification:

- `contest closure required`: keep replay proof package.
- `benchmark artifact`: do not claim it in current headline.

## Implementation Bugs vs Structural Mismatches

### Confirmed implementation bugs from older audit

Older audit identified two P0 report bugs:

- planner one-shot aggregation bug;
- memory fairness empty case contracts labeled `mismatch`.

Current worktree appears to have fixes:

- tests check planner one-shot report is `1.00`;
- `eval/runner.py` has `not_evaluated` path for empty contracts;
- tests assert `correctness_label == not_evaluated`.

No new implementation bug was found in the local review that should be patched
before the current goal's review output.

### Structural mismatches that should not be patched blindly

1. Text lane route recovery.
   - Text whole-lane handoff is natural language, but executor still uses lexical
     recovery and the shared registry.
   - This is acceptable for an internal baseline if stated honestly.

2. Static validate thickening.
   - The validate step is real but mostly confirms same retrieved decision.
   - Adding it was useful, but it is not enough for connected multihop.
   - The planner parser has a compatibility path that can insert validate for
     YAML contest rows. That path protects current headline compatibility, but
     it should not be over-read as planner-authentic validation behavior.

3. Memory disconnected from headline.
   - Memory is real but not exercised in current formal headline.

4. Route-shaped corpus.
   - Current corpus remains tuned to release-regression route families.

These are not one-line bugs. They imply benchmark/task/runtime contract redesign.

## File-Level Anchors

| Area | File anchors | Review meaning |
| --- | --- | --- |
| Static plan shape | `tasks/sample_tasks.py:634-699` | Fixed retrieve/validate/execute/summarize plan. |
| LLM planner strict role coverage | `agents/sample_agents.py:1675-1715`; `agents/sample_agents.py:2175-2180`; `tests/test_llm_runtime.py:490-533` | Missing `validate` should be rejected on strict planner-support surfaces. |
| Validate compatibility insertion | `agents/sample_agents.py:1718-1747`; `agents/sample_agents.py:1750-1799` | Useful for YAML contest compatibility, but should not become evidence of adaptive planning. |
| Thickness validators | `tasks/sample_tasks.py:1024-1086`; `tasks/contest_family_spec.py` validators | S1/S2 are enforced statically. |
| Retriever local corpus path | `agents/sample_agents.py:356-414`; `tasks/local_corpus.py:94-180` | Real retrieval, but repo-local and route-shaped. |
| Text whole-lane handoff | `agents/sample_agents.py:171-202`; `agents/sample_agents.py:762-781` | Natural-language text includes leading explanation and safest next step. |
| Text recovery and protocol packet path | `runtime/executor_runtime.py:1002-1027` | Text rebuilds features from handoff; protocol reads decision packet. |
| Validate gate | `agents/sample_agents.py:1017-1163`; `runtime/orchestrator.py:1460-1471` | Real validation packet; protocol execute can require validation. |
| Summarizer memory commit | `agents/sample_agents.py:1215-1370` | Summarizer is real LLM consumer and memory writer. |

## Runtime Authenticity Verdict

The current runtime is not fake. The protocol packet, StateRef, validation gate,
tool execution, and memory infrastructure are real code paths. The honest
negative finding is different: the current contest headline still does not
exercise enough task depth, dynamic dependency, or memory reuse to turn runtime
mechanism authenticity into a strong contest-facing method claim.

Recommended runtime stance:

- Do not rewrite runtime first.
- Do not add another carrier/profile.
- First redesign the benchmark/task contract so runtime changes are only made
  where a true S1/S2 task requires them.
- If S1 requires second retrieval, add it as a deliberate DAG extension, not as
  hidden benchmark scaffolding.
