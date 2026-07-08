# StateBus 4-LLM Refactor Independent Review - 2026-06-20

Scope: review the proposed route in `docs/analysis/statebus_four_llm_agent_refactor_design_20260620.md`.

Working branch observed: `feat/active-surface-and-external-text-baseline-20260619`.

Review posture: independent, strict, evidence-first. This document reviews the design direction only. It does not propose or perform implementation changes.

## A. Executive Judgment

### Findings First

The proposed 4-LLM route is addressing a real defect, but it is not yet a validated method improvement. Its current value is comparator repair, not architecture proof.

One-sentence judgment: support it only as a contract-first, minimal paired-comparator phase; do not treat it as a full StateBus architecture upgrade or new headline until the comparator, scoring, telemetry, and fairness gates are written and passed.

Decision label: conditional weak support.

I support continuing the route only if the next mainline unit is:

1. define a fixed 4-role paired benchmark contract;
2. enforce equivalent role graph and role I/O in StateBus carrier vs external pure-text carrier;
3. add role-level metrics and fairness gates before any API headline claim;
4. keep open-world/freer interaction out of the mainline until the fixed comparator is clean.

I do not support immediately upgrading `Planner / Retriever / Executor / Summarizer` into four live LLM agents and then searching for a positive result. That would convert a known comparator problem into a higher-cost, noisier, harder-to-attribute benchmark.

### Evidence Anchors

- Current contest and scope boundary: `README.md`, `docs/reference/题目.md`, `docs/constraints/current_host_and_migration.md`, `docs/constraints/current_feature_scope.md`, `docs/planning/implementation_plan.md`.
- Current architecture description: `docs/reports/architecture_and_data_flow.md`, `docs/review/statebus_contest_aligned_review_20260614.md`, `docs/reports/final_claim_matrix_and_freeze_20260618.md`.
- Current diagnosis docs: `docs/analysis/statebus_independent_full_repo_review_20260620.md`, `docs/analysis/statebus_independent_followup_deep_diagnosis_20260620.md`, `docs/analysis/statebus_external_pure_text_baseline_contract_20260620.md`, `docs/analysis/statebus_middle_layers_non_llm_hypothesis_review_20260620.md`, `docs/analysis/statebus_four_llm_agent_refactor_design_20260620.md`.
- Current implementation: `agents/sample_agents.py`, `runtime/orchestrator.py`, `runtime/langgraph_adapter.py`, `runtime/executor_runtime.py`, `protocol/messages.py`, `runtime/llm.py`, `tasks/sample_tasks.py`, `eval/runner.py`, `eval/open_runner.py`, `eval/text_open_baseline.py`.
- Formal headline artifacts: `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_report.md`, `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_results.json`.
- Deterministic repeat artifact: `runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_report.md`, `runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_results.json`.
- Current repeat=1 coverage artifacts under `runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/`.

## B. Problem Reframing

### Core Problem

The core project problem is not simply that StateBus currently has too few LLM calls. The core problem is that the current evidence stack does not yet isolate the method variable well enough.

There are three separable problems:

1. Benchmark/comparator problem: the formal `text_whole_lane` comparator is internal to the StateBus runtime, not an independent external pure-text multi-agent baseline.
2. Method problem: the current StateBus path is four-role in naming and control graph, but the semantic LLM work is concentrated mostly in `Summarizer`; the middle roles are deterministic runtime helpers.
3. Measurement problem: current headline metrics mostly show token deltas and exact/admissible parity on narrow objects, while memory reuse, role-level causality, external baseline weakness, and open interaction remain under-proven.

The proposed 4-LLM route mainly fixes the first two. It does not automatically fix the third.

### What The Proposed Refactor Actually Repairs

The proposal correctly targets:

- the mismatch between the contest's multi-agent framing and the current "LLM at endpoints plus deterministic helpers" implementation;
- the fact that `text_whole_lane` is a runtime-internal comparator rather than a traditional external text baseline;
- the lack of a same-role pure-text comparator that can answer whether StateBus carrier design is better than text carrier design under the same multi-agent workload;
- the current weakness that deterministic route/helper logic may be carrying too much of the method story.

These are real defects. The route is therefore not just narrative cosmetics.

### What It Does Not Repair

The route does not by itself repair:

- protocol payloads being converted back into text before an LLM consumes them;
- absence of role-level token accounting;
- absence of an external 4-role baseline contract;
- absence of a strict text-lane handoff contract;
- memory reuse still being assist-style unless non-zero `reuse_gain` or `skipped_step_count` is shown;
- scoring that may be too easy or too object-specific to prove broad method superiority;
- API repeatability and latency attribution under four LLM calls;
- exact separation between route planning, retrieval quality, executor tool semantics, and carrier effect;
- the fact that an open-world setting would add another major uncontrolled variable.

If the refactor is implemented before these contracts exist, it will likely make attribution worse.

## C. Code-to-Design Audit

### Current Code Behavior

The current implementation really is a fixed four-role system at the orchestration level:

- `runtime/orchestrator.py` runs `planner.plan` -> `retriever.retrieve` -> `executor.execute` -> `summarizer.summarize`.
- `runtime/langgraph_adapter.py` mirrors that graph when LangGraph is installed.
- `protocol/messages.py` defines structured envelopes such as plan, retrieval, execution, and summary messages.

But the current implementation is not a four-LLM semantic-agent system:

- `agents/sample_agents.py` has deterministic `PlannerAgent.plan()`.
- `agents/sample_agents.py` has deterministic `RetrieverAgent.retrieve()`.
- `agents/sample_agents.py` has deterministic `ExecutorAgent.execute()`.
- `agents/sample_agents.py` uses LLM calls mainly in `SummarizerAgent.summarize()` when API mode is enabled.
- `agents/sample_agents.py` has `OpenTextAgent.run()` for the open text baseline, but that is a single open prompt/agent, not a 4-role external baseline.

The current middle layers are runtime helpers:

- `runtime/executor_runtime.py` contains deterministic route planning, route corpus retrieval, route expansion, fallback matching, context packet construction, and tool execution.
- The protocol lane gives these helpers typed access to task state and route metadata.
- The final LLM-facing prompt in `SummarizerAgent` still serializes selected typed fields into text.

The current benchmark runner compares lanes inside this runtime:

- `eval/runner.py` supports `protocol`, `text`, and `text_whole_lane` style configurations.
- `text_whole_lane` is a StateBus runtime lane, not an external pure-text system.
- `eval/runner.py` records aggregate prompt/completion/total tokens, state bytes, exact/admissible metrics, memory fields, and replay fields.
- It does not yet record role-level LLM token use because the main StateBus path does not have four LLM calls.

The current external pure-text path is separate but underdeveloped:

- `eval/open_runner.py` and `eval/text_open_baseline.py` run an open text agent over open baseline tasks.
- `tasks/pure_text_open_live_api_slice_v1.yaml` is a tiny two-record slice.
- The open baseline does not currently share the same 4-role graph, role budget, role schemas, memory policy, or formal runner schema as StateBus.

### Accuracy Of The New Design Document

`docs/analysis/statebus_four_llm_agent_refactor_design_20260620.md` is accurate on the central diagnosis:

- current StateBus roles are not all semantic LLM agents;
- current `text_whole_lane` is not a sufficient external baseline;
- a fixed 4-node graph can isolate carrier differences better than open-ended agent autonomy;
- open-world should not be introduced in the same phase.

The document is under-specified on the engineering contracts that make the design admissible:

- it does not fully define role-level I/O schemas for both carriers;
- it does not define enough token accounting to attribute cost by role;
- it does not define a sufficient fairness gate for the external 4-role baseline;
- it does not define how to prevent the protocol lane from dumping all typed state into text prompts;
- it does not define how scoring rejects unsupported but plausible answers;
- it does not define migration acceptance criteria from current headline to new headline.

The design doc therefore has the right critique but not yet a sufficient execution contract.

### Misread Or Omitted Risks

The largest omitted risk is that "make all roles LLM-driven" can hide rather than reveal StateBus advantage. If role prompts, role memories, route helper access, or state serialization differ between lanes, the comparison will measure prompt design and hidden helper power rather than StateBus carrier design.

The second omitted risk is cost and repeatability. Four LLM calls per task multiply latency variance, token use, and failure modes. Without role-level traces, aggregate token and exactness metrics become less interpretable than the current single-LLM summarizer path.

The third omitted risk is that tasks may remain answerable by a strong text agent using one consolidated prompt. A 4-role graph alone does not prove StateBus value unless the benchmark object forces state handoff, role-local decisions, support validation, and carrier-sensitive constraints.

## D. Design Review Of 4-LLM Route

### Reasonable Design Points

The following parts are directionally sound:

- Fixed graph first. Keeping `Planner / Retriever / Executor / Summarizer` in a fixed graph is the right way to isolate carrier differences before testing open collaboration.
- Same-role external baseline. A pure-text baseline with the same four semantic roles is more contest-aligned than the current internal `text_whole_lane`.
- Carrier comparison. "4 LLM agents under text carrier vs StateBus carrier" is a cleaner research question than "current StateBus runtime vs its own whole-text lane".
- StateBus identity preserved in principle. The method can still be StateBus if the protocol lane uses typed control/state/memory carriers and the text lane uses only textual handoff under the same graph.
- Open-world deferral. The design doc is correct that freer interaction should not enter this phase.

### Unreasonable Or Under-Defined Points

The route is not yet reasonable as an implementation plan because too many core contracts are undefined:

- "Planner is LLM-driven" is not enough. The planner's allowed inputs, output schema, visible task metadata, route hints, and failure handling must be identical in both carriers except for carrier representation.
- "Retriever is LLM-driven" is dangerous unless retrieval corpus access is strictly normalized. Otherwise the StateBus lane may get structured route affordances while text lane gets flattened snippets.
- "Executor is LLM-driven" can easily become an uncontrolled CodeAct/tool-use benchmark. The executor must have a bounded tool contract and equivalent tool descriptions.
- "Summarizer consumes typed state" is only meaningful if it consumes bounded typed fields through an explicit access contract. If the protocol lane just serializes typed packets into text, the token advantage may disappear and the mechanism claim weakens.
- "External pure-text 4-agent baseline" cannot reuse StateBus deterministic helpers invisibly. If it does, it is not external. If it does not, the task must still expose equivalent information.

### Over-Optimistic Assumptions

The design is too optimistic if it assumes:

- more LLM roles automatically means a fairer comparator;
- a fixed graph automatically gives attribution;
- text carrier vs StateBus carrier can be isolated without role-level prompt and carrier contracts;
- exact/admissible equality on small tasks will remain meaningful under four semantic roles;
- an external text baseline will be weaker for the right reason;
- role-level LLM cost will be acceptable without repeat-depth loss;
- memory reuse will become real merely because more roles exist.

None of these follows from the current code or artifacts.

### Token, Latency, Exactness, And Fairness Risks

Token risk:

- Current formal API headline already shows a protocol token advantage against `text_whole_lane`, but this is mostly aggregate summarizer prompt behavior.
- Four LLM roles may increase total prompt tokens even if each prompt is smaller.
- If protocol fields are serialized into each role prompt, StateBus may lose the headline token advantage entirely.

Latency risk:

- Four sequential LLM calls increase p95 latency variance.
- Current frozen API headline already has protocol higher p95 latency than `text_whole_lane` despite lower tokens in `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_report.md`.
- Without serialized repeat runs and role-level timings, latency claims will be weaker than current evidence.

Exactness risk:

- LLM planner/retriever/executor roles introduce more points where a correct final answer can fail.
- If scoring only checks final answer strings, it may miss unsupported route choices.
- If scoring becomes more permissive to handle LLM variation, exact/admissible evidence becomes less strict.

Fairness risk:

- The StateBus lane may retain structured route metadata and deterministic tool affordances while the text lane receives flattened context.
- The text lane may accidentally become a mega-prompt baseline if it sees all role context at once.
- The external pure-text baseline may be too weak if it does not get equivalent retrieval/tool access, or too strong if it bypasses role handoff.

## E. Missing Pieces

### Benchmark Object

Missing: a formal paired task object designed for 4 semantic roles.

The object must force:

- planner-local decision;
- retriever-local evidence selection;
- executor-local tool/action result;
- summarizer-local synthesis;
- support IDs or route IDs that can be checked;
- constraints that prevent a single flat prompt from trivially solving the object.

The current formal headline object is useful history, but it is not sufficient proof for a 4-LLM route.

### External Baseline Contract

Missing: a hard external 4-role pure-text baseline contract.

It must specify:

- no StateBus typed packets;
- no StateBus private helper state;
- same role count;
- same graph order;
- same model, temperature, retry policy, and per-role budget;
- same retrieval corpus and tool catalog in text form;
- same final scoring;
- same repeat count and serialized API execution.

The current `eval/open_runner.py` plus `OpenTextAgent` path is not enough because it is a single open text agent over a tiny slice.

### Protocol Lane Contract

Missing: a precise protocol carrier contract.

It must define:

- what each role can read;
- what each role must write;
- which typed fields can be included in LLM prompts;
- field-level access logging;
- maximum serialized field budget;
- prohibition against dumping the entire typed packet into the role prompt unless the text lane receives an equivalent representation.

Without this, the StateBus lane may simply become structured preprocessing plus text prompting.

### Text Lane Contract

Missing: a pure text carrier contract.

It must define:

- role handoff transcript format;
- what prior role output each role can see;
- no direct all-task mega-prompt if the StateBus lane does not get equivalent global context;
- how corpus/tool information is represented;
- whether text memory is visible and how it is bounded;
- how role outputs are parsed for scoring and downstream roles.

### Role-Level Token Accounting

Missing: per-role metrics.

Required fields:

- `planner_prompt_tokens`, `planner_completion_tokens`, `planner_latency_ms`;
- `retriever_prompt_tokens`, `retriever_completion_tokens`, `retriever_latency_ms`;
- `executor_prompt_tokens`, `executor_completion_tokens`, `executor_latency_ms`;
- `summarizer_prompt_tokens`, `summarizer_completion_tokens`, `summarizer_latency_ms`;
- role error/retry counts;
- aggregate totals derived from role metrics;
- prompt digest or trace ID for audit without leaking full prompt text into every report.

Aggregate `avg_total_tokens` is not enough for the 4-LLM route.

### Memory Contract

Missing: a strict memory contract.

It must state:

- cold vs warm run status;
- what memory each role can read;
- what memory each role can write;
- whether memory is StateBus typed memory or text transcript memory;
- when `reuse_gain` is counted;
- when `skipped_step_count` is counted;
- how assist-style context is separated from true reuse.

Current evidence should continue to treat memory reuse as assist-style unless non-zero reuse or skipped-step fields are explicitly shown.

### Replay Contract

Missing: a replay contract for four LLM roles.

It must state:

- which role outputs can be replayed;
- whether replayed outputs count as formal API evidence;
- how deterministic smoke differs from live API evidence;
- how API retries are logged;
- how cached LLM calls are excluded or labeled;
- how repeat runs stay serialized for latency evidence.

### Fairness Gate

Missing: a pre-run gate that rejects unfair paired comparisons.

The gate must check:

- same task object;
- same role graph;
- same number of LLM calls unless explicitly accounted;
- same model and sampling parameters;
- same corpus/tool availability;
- same final answer validator;
- same admissibility validator;
- same support requirements;
- no hidden deterministic helper advantage in one lane;
- no cross-lane prompt leakage;
- serialized API execution for formal latency claims.

This gate should fail closed.

### Scoring / Exact / Admissible

Missing: scoring rules strong enough for semantic multi-role execution.

Required:

- final answer exactness;
- admissibility;
- support ID validation;
- route/tool validation where relevant;
- rejection of answers supported by the wrong evidence;
- rejection of correct-looking answers obtained from disallowed fields;
- role-output validity checks, not only final answer checks.

The current exact/admissible metrics are useful but too final-answer-centric for the proposed route.

### Telemetry / Tracing

Missing: full trace visibility.

Required:

- per-node input and output summaries;
- carrier byte counts per handoff;
- per-field read logs for protocol lane;
- text transcript length per handoff for text lane;
- role-level prompt digests;
- LLM usage per role;
- route/tool decisions;
- memory reads/writes;
- scoring reasons.

Without this, failures will be impossible to attribute.

### Migration Acceptance Criteria

Missing: acceptance criteria for moving from current headline route to 4-LLM comparator route.

Minimum criteria should be:

- contract doc accepted before implementation;
- at least one deterministic/local smoke object passes both carriers;
- role-level metrics are present;
- fairness gate passes before any API run;
- external text baseline is independent of StateBus typed runtime internals;
- API repeat results are serialized and artifacted;
- no headline claim is made until repeat depth and scoring audit pass.

### Failure Modes

Missing: explicit failure-mode taxonomy.

Likely failure modes:

- LLM role drift;
- planner and retriever making inconsistent assumptions;
- executor becoming an uncontrolled tool agent;
- StateBus lane leaking structured route hints unavailable to text lane;
- text lane receiving a de facto mega-prompt;
- protocol lane serializing every typed packet and losing token advantage;
- API cost preventing repeat depth;
- latency variance overwhelming p95 claims;
- final scoring accepting unsupported answers;
- memory assist being mislabeled as reuse;
- open-world freedom making attribution impossible.

## F. Open Environment Question

### Should open-world / freer interaction enter the mainline now?

No.

Open-world should not enter the mainline now. The current unresolved issue is not that the graph is too closed. The unresolved issue is that the current comparator and measurement contracts are not strong enough. Adding freer interaction before the fixed 4-role comparator is clean would make attribution worse.

### Missing Preconditions

Before open-world work enters the mainline, StateBus needs:

- a passing fixed-graph 4-role paired comparator;
- role-level token/latency/error telemetry;
- strict carrier contracts;
- support-aware scoring;
- a fairness gate that can reject invalid comparisons;
- memory and replay contracts;
- baseline artifacts showing that text carrier vs StateBus carrier is measurable under controlled conditions.

### Minimal Later Introduction

The minimal later open-world phase should not be full free-form autonomy. It should be a bounded perturbation phase:

- same task family;
- same role set;
- bounded extra interaction budget;
- explicit turn budget;
- explicit tool budget;
- same scoring contract;
- separate report label from the fixed-graph comparator.

### Ordering

The correct order is:

1. fixed 4-role comparator contract;
2. deterministic/local paired smoke object;
3. serialized API repeat for the fixed comparator;
4. only then bounded open interaction as a separate phase.

Open-world should be downstream evidence, not the next mainline variable.

## G. Final Decision

This route should continue, but only under a narrower name and stricter gate.

The route should not be called "upgrade StateBus to four LLM agents" as the main objective. That name encourages premature implementation. The main objective should be:

> build a contract-valid paired 4-role comparator for StateBus carrier vs external pure-text carrier.

That is the only defensible main direction.

If this contract-first constraint is accepted, the route is worth doing because it directly attacks the current comparator defect and better aligns with the contest's multi-agent framing.

If this constraint is rejected, the route should not continue. The fallback should be the current active-surface and external pure-text baseline hardening path, not open-world expansion and not broad 4-LLM implementation.

The StateBus method identity is preserved only if:

- StateBus lane differs from text lane by carrier/control/state/memory representation, not by hidden helper power;
- both lanes share the same semantic role graph;
- every role-level advantage is measurable;
- final claims remain bounded to validated artifacts.

## H. Minimal Next Step

The next step should be one document, not implementation:

Create a `4-role comparator contract` document that freezes:

- benchmark object;
- role I/O schemas;
- protocol lane contract;
- text lane contract;
- external baseline contract;
- role-level token accounting;
- memory and replay rules;
- fairness gate;
- exact/admissible/support scoring;
- telemetry requirements;
- migration acceptance criteria;
- known failure modes.

Only after that contract is accepted should the project implement one deterministic/local paired smoke object. Only after that smoke passes should API repeat runs start.

This is intentionally narrow. The project does not need a larger implementation menu right now.

## Evidence Appendix

### Current Headline Evidence

`runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_report.md` shows a valid narrow formal headline against internal `text_whole_lane`:

- protocol average tokens lower than `text_whole_lane`;
- exact and admissible parity at 1.0;
- protocol p95 latency higher than `text_whole_lane`;
- comparator is still internal to StateBus runtime, not an external pure-text baseline.

`runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_report.md` is useful for deterministic closure but not token evidence because deterministic token fields are zero.

### Current Repeat=1 Coverage

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/contest_honest_headline_v1_api_r1/benchmark_report.md` supports current-state token reduction and exact/admissible parity on the headline object, but remains a repeat=1 slice.

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/memory_policy_controlled_v3_api_r1/benchmark_report.md` does not prove strong memory reuse because reuse/skipped-step evidence remains absent or zero.

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/typed_state_consumer_sensitivity_v3_api_r1/benchmark_report.md` is useful secondary evidence that typed state can matter, but it is not an external comparator.

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/planner_support_v3_api_r1/benchmark_report.md` is not a clean token-win story because protocol token use is not clearly better there.

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/route_corpus_stress_whole_lane_audit_v1_api_r1/benchmark_report.md` is audit evidence, not a sufficient external baseline.

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/pure_text_open_live_api_slice_v1_api_r1/open_report.md` is useful as an external text smoke, but it is too small and not role-equivalent.

### Current Code Evidence

`agents/sample_agents.py` proves the main StateBus path is not currently four LLM semantic roles. It is a fixed four-role control graph with deterministic planner/retriever/executor and LLM summarization.

`runtime/executor_runtime.py` proves substantial route/helper/retrieval/tool semantics live in deterministic runtime code.

`runtime/orchestrator.py` and `runtime/langgraph_adapter.py` prove the fixed graph exists and is reusable as a comparator skeleton.

`protocol/messages.py` proves the typed envelope exists but does not by itself enforce role-level semantic contracts.

`runtime/llm.py` proves token usage can be collected per LLM call, but the benchmark schema must promote it to role-level formal metrics.

`eval/runner.py` proves the current formal runner can compare lanes and score exact/admissible outcomes, but it is not yet a 4-role external-baseline runner.

`eval/open_runner.py` and `eval/text_open_baseline.py` prove the external text path exists, but also show it is currently not the same-role paired comparator required by the proposed route.
