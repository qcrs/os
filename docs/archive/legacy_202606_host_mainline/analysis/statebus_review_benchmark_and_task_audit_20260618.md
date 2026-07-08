# StateBus Goal2 Benchmark and Task Audit

Date: 2026-06-18

> Superseded status note, 2026-06-18:
> This audit captured the pre-Goal3 state of `contest_honest_headline_v1`.
> Its conclusions that the current headline was repeat=1, fresh-retrieval-only,
> or lacking headline memory/replay have been superseded by
> `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`.
> Use `docs/reports/final_claim_matrix_and_freeze_20260618.md` for current
> frozen headline status. Use this file only for historical audit reasoning,
> text-definition cautions, and benchmark/task boundary analysis.

This audit answers whether the current benchmark/task set can adjudicate the
StateBus method, not whether the current code can run. It uses the current
worktree and the latest available current run packages as authoritative.

## Current Benchmark State

Current contest-facing headline:

- `contest_honest_headline_v1`
- text object: `text_whole_lane`
- protocol object: `state_packet_minimal`
- variable axis: `mode`
- public surface: `formal_headline`

Current latest evidence:

- Deterministic repeat=1: `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/`
- API repeat=1: `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/`

Latest API repeat=1 report facts:

- `mode-specific task counts = {'text': 20, 'protocol': 20}`
- `single_variable = yes`, `variable_axes = mode`
- whole-lane text guard pass rate `1.00`
- hidden field leak rate `0.00`
- summarizer typed visibility rate `0.00`
- object parity gate `pass`
- formal stability gate `not_yet`
- withheld reason `contest_repeat_insufficient`
- fresh-retrieval control bytes: `9553.50 -> 7502.90`
- LLM total tokens: `414.30 -> 416.05`
- task latency: `1842.12 -> 1879.37`
- route exact `0.90`, tool exact `0.70`, exact match `0.70`, admissible `1.00`, wrong family `0.00`

Run-level manifest facts from
`/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/benchmark_results.json`:

- `task_count = 40`, split as 20 text rows and 20 protocol rows;
- `task_set_public_surface = formal_headline`;
- `task_set_single_variable = true`;
- `task_set_variable_axes = ["mode"]`;
- `task_set_plan_source_default = yaml`;
- `task_set_formal_structure_clean_retrieval = true`;
- `task_contract_counts = {"allow_memory_assist": 0, "allow_execute_prune": 0, "allow_exact_replay": 0}`;
- `expected_reuse_mode_counts = {"none": 40, "assist": 0, "skip_execute": 0, "skip_retrieve_execute": 0}`;
- `memory_policy_counts = {"memory_off": 40, "working_assist": 0, "long_term_assist": 0, "validated_replay": 0, "exact_replay": 0}`;
- `memory_replay_evidence_gate.applicable = false`;
- `formal_stability_gate.required_repeat = 10`, `run_count = 1` for both modes, and `passed = false`;
- `object_parity_gate.passed = true`.

The deterministic repeat=1 package
`/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/`
has the same structural manifest pattern: repeat 1, formal headline surface,
single variable `mode`, 40 rows, all rows `memory_off`, all expected reuse modes
`none`, and a failed formal stability gate only because `required_repeat = 10`
is not satisfied.

## Single-Variable and Object-Purity Review

### What is now clean

The current headline is substantially cleaner than older surfaces:

- It is the only contest-facing formal headline.
- It compares matched text/protocol rows over the same 20 cases.
- It uses `text_whole_lane` rather than the old `text_strict_pure_lane` that leaked explicit `Route:`/`Tool:` slots.
- It has object parity gate pass under both deterministic and API repeat=1.
- It no longer fails on hidden field leak or unexpected task failure in the latest run evidence.

Issue classification: `contest closure required`.

This is enough to say the object-purity layer is mostly closed for repeat=1.
It is not enough to say the headline has formal repeat stability.

### What is still not a pure external text baseline

`text_whole_lane` is not an external traditional pure-text multi-agent baseline.
It is the StateBus runtime with a natural-language handoff object.

Evidence:

- `agents/sample_agents.py` builds a natural-language retriever handoff that says the leading explanation and safest next step in prose.
- `runtime/executor_runtime.py` recovers a feature bundle from that text handoff before selecting the tool.
- `agents/sample_agents.py` validation can recover route/tool for text whole-lane without a decision packet.

This does not necessarily make the internal comparison invalid, because both
modes use the same executor engine. But it changes what the benchmark means:

- valid reading: StateBus internal text whole-lane handoff versus StateBus protocol packet handoff;
- invalid reading: external pure-text multi-agent framework versus StateBus protocol.

Issue classification: `reporting / narrative issue`.

## Task Thickness Review

### Static thickness now exists

Current `tasks/contest_family_spec.yaml` contains:

- family-level `thickness_contract`;
- case-level `thickness_setting`;
- `reasoning_hops_min`;
- `dependency_depth`;
- `expected_intermediate_decisions`;
- `abstention_boundary`;
- `required_plan_semantic_roles`;
- `required_prior_routes` for replay reusable cases.

`tasks/contest_family_spec.py` validates these fields and requires:

- S1 for clean/distractor/ambiguous;
- S2 for replay_reusable;
- `retrieve/validate/execute/summarize` roles;
- non-empty prior dependency fields for reusable cases.

Issue classification: `contest closure required`.

This is genuine progress over the earlier S0 object.

Concrete task-object samples loaded from `load_task_set_bundle("contest_honest_headline_v1")`:

| Task row | Static contract fields | Runtime reuse contract |
| --- | --- | --- |
| `rr-auth-clean-text-001` / `rr-auth-clean-protocol-001` | `thickness_setting=S1`, `reasoning_hops_min=2`, `dependency_depth=1`, roles `retrieve/validate/execute/summarize` | `reuse_disabled` |
| `rr-billing-replay_reusable-protocol-001` | `thickness_setting=S2`, `reasoning_hops_min=3`, `dependency_depth=2`, `required_prior_case_ids=("rr-billing-clean",)`, `required_prior_routes=("worker_queue_starvation",)`, `required_prior_rejections=("db_pool_saturation",)` | `reuse_disabled` |

This is the key evidence split: the S1/S2 and prior-dependency fields exist in
the task contract, but the current headline deliberately disables runtime reuse.
The current S2 rows are therefore dependency-contract rows, not replay-effect
rows.

### Runtime thickness is still limited

The runtime plan builder turns the static contract into a fixed plan:

```text
retrieve -> validate -> execute -> summarize
```

The validate step is real, but it validates the route/tool from the same
retrieval result; it does not perform a second retrieval or create a new
evidence-dependent branch. Current summary rows show planned step count `4`
for every task. Current headline is fresh-retrieval-only:

- API repeat=1 text aggregate: `memory_hits = 0`, `memory_query_count = 0`,
  `assist_memory_hit_rate = 0`, `skipped_step_count = 0`, `reuse_gain = 0`,
  `replay_probe_count = 0`, `planned_step_count = 80`,
  `trajectory_step_count = 80`;
- API repeat=1 protocol aggregate: same values for memory/reuse counters, with
  `planned_step_count = 80`, `trajectory_step_count = 80`;
- deterministic repeat=1 text/protocol aggregates show the same memory/reuse
  zero pattern;
- manifest: all 40 rows are `memory_off` and all expected reuse modes are
  `none`.

Therefore the current task set is no longer a three-step object, but it is
still not the connected multihop object described in the benchmark contract.
It is a one-pass retrieval/route decision with an executor validation gate.

Issue classification: `task design issue`.

Representative row-level evidence from the API repeat=1 package:

| Row | planned / trajectory steps | memory / replay counters | Interpretation |
| --- | ---: | --- | --- |
| `rr-auth-clean-text-001` | `4 / 4` | `memory_hits=0`, `memory_query_count=0`, `skipped_step_count=0`, `reuse_gain=0`, `replay_probe_count=0` | S1 clean row executes the fixed four-step path. |
| `rr-auth-clean-protocol-001` | `4 / 4` | same zero counters | Protocol row is matched but not deeper. |
| `rr-deploy-replay_reusable-text-001` | `4 / 4` | same zero counters | A row named `replay_reusable` still does not trigger replay in the current headline. |
| `rr-deploy-replay_reusable-protocol-001` | `4 / 4` | same zero counters | S2 contract exists, but runtime behavior is fresh retrieval. |

### Cross-task dependency is mostly static

Reusable rows declare `required_prior_case_ids`, `required_prior_rejections`,
and `required_prior_routes`. That is useful contract metadata. But current
headline execution disables memory reuse and does not use a prior run state to
change the admissible action. Current repeat=1 reports show no memory assist
or replay effect in the headline.

The S2 label therefore currently proves that a dependency contract is present
in the spec, not that the benchmark dynamically evaluates a prior-dependent
action boundary.

Issue classification: `benchmark artifact`.

Historical contrast:

- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/deterministic_repeat10/`
  has 18 tasks, repeat 10, expected reuse modes
  `assist=6`, `none=6`, `skip_execute=3`, `skip_retrieve_execute=3`,
  `memory_hits=45`, `memory_query_count=18`, `memory_hit_rate=0.83`,
  `skipped_step_count=9`, `reuse_gain=0.17`, and `expectation_match_rate=1.00`.
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/`
  carries the same replay-aware pattern under API mode and records protocol
  token/time reductions on that older 18-task replay-aware object.
- `runs/comprehensive_eval_20260607_131113/api_repeat10_serial/` is older and
  assist-only: `memory_hit_rate=0.75`, `skipped_step_count=0`,
  `reuse_gain=0`.

These packages prove memory infrastructure and replay-aware behavior exist in
other evidence layers. They do not prove memory reuse inside
`contest_honest_headline_v1`, because the current headline manifest disables
all memory policies and reuse modes.

### Route/tool competition remains corpus-shaped

Current families define route and tool competition. That is good. However:

- docs carry `eval_route_label` and `eval_tool_label`;
- local corpus helper can extract corpus feature hints from docs;
- retriever resolves runtime corpus hints from retrieved docs;
- tool selection is still tied to playbook route/tool labels and lexical pattern matching.

The current object is a stronger route-selection benchmark than before, but it
is still route-shaped and corpus-shaped. It does not yet force agents to
compose independent facts the way external multihop QA or long-memory tasks do.

Issue classification: `task design issue`.

## Report and Row-Level Consistency

The current high-level report aligns with manifest-level facts on:

- single-variable metadata;
- object-parity gate;
- withheld reason;
- control-byte delta;
- token and latency deltas;
- transfer truth summary.

Known older report bugs from `honest_full_audit_20260617.md` appear repaired
in the current worktree:

- tests assert planner one-shot report rate `1.00`;
- `eval/runner.py` returns `not_evaluated` for empty case contracts;
- tests cover `correctness_label == not_evaluated`.

However, the reduced `summary.<mode>.tasks` row layer does not carry full case
contract metadata such as `case_id`, `thickness_setting`, or
`expected_intermediate_decisions`. That makes post-hoc row-level audit harder
than it should be. The YAML spec carries the contract, the report carries
headline metrics, but the run row summary cannot itself reconstruct all
thickness decisions.

Issue classification: `reporting / narrative issue`.

Recommendation: preserve the task contract fields in the row-level output or
write a per-row task-contract sidecar. This is not a method improvement, but it
is needed for auditability.

Current workaround used in this review:

- task contract was recovered from `tasks/contest_family_spec.yaml` through
  `load_task_set_bundle("contest_honest_headline_v1")`;
- runtime counters were recovered from `benchmark_results.json`;
- full audit required manually joining by task id and task family.

This is acceptable for this review, but not a good handoff surface. Future
headline packages should carry enough row-level contract fields to prove S1/S2
behavior without reloading the YAML generator.

## Evidence-Layer Risk

The project currently has at least four layers:

1. `contest_honest_headline_v1` formal headline.
2. mechanism surfaces such as typed-state and consumer sensitivity.
3. memory/replay surfaces.
4. audit-only surfaces such as external text baseline and text-definition audit.

The risk is not that these layers are useless. The risk is that they are easy
to merge into one persuasive but false story. Examples:

- Using historical replay-aware repeat=10 packages to claim current headline
  memory gain is invalid.
- Using typed-state mechanism proof to claim current headline latency advantage
  is invalid.
- Using `external_text_baseline_audit_v3` to claim a formal external baseline is
  invalid while it remains audit-only.
- Using current repeat=1 object parity to claim formal repeat=10 stability is
  invalid.
- Using `host_goal_eval_20260608_093111_planner_contract_refresh` replay
  numbers to claim current `contest_honest_headline_v1` memory gain is invalid:
  the former has `skip_execute` and `skip_retrieve_execute` rows, while the
  latter has `expected_reuse_mode_counts.none = 40`.

Issue classification: `reporting / narrative issue`.

## Benchmark vs Implementation Mismatch Matrix

| Mismatch | Layer | Classification | Evidence | Consequence |
| --- | --- | --- | --- | --- |
| Headline evaluates only fresh retrieval while contest asks memory reuse effect | Benchmark | `benchmark artifact` | current headline memory hit `0.00`, replay gate not applicable | Cannot use headline to score memory reuse. |
| S2 reusable dependency is static contract, not dynamic prior-state dependency | Task design | `task design issue` | required prior fields in YAML, no headline reuse effect | Does not yet test whether prior rejection changes admissible action. |
| Text lane uses natural language but executor recovers route/tool with lexical machinery | Code path | `structural design mismatch` | text handoff + executor recovery code | Valid internal comparison, not external pure-text baseline. |
| Protocol lowers control bytes but not API latency/tokens | Method/evidence | `contest closure required` plus `reporting / narrative issue` | API repeat=1: bytes lower, tokens +1.75, latency +37.24 ms | Claim must be communication compactness, not end-to-end superiority. |
| Full case contract absent from reduced run rows | Report | `reporting / narrative issue` | summary tasks omit thickness/case fields | Harder to audit task thickness from run package alone. |

## Benchmark Verdict

Current benchmark status:

- Correctness/object-purity layer: mostly passed at repeat=1.
- Static thickness contract: implemented.
- Runtime/task thickness: partial, not enough for final method judgment.
- Repeat stability: not proven for current headline.
- Memory reuse in headline: absent.

Therefore the benchmark is not yet qualified to decide whether the StateBus
method is strong or weak. It is qualified to say that the implementation now has
a cleaner contest-facing headline floor and a measurable communication-byte
benefit under repeat=1.

## Required Next Benchmark Reset

This should be called a benchmark/task contract reset, not just a patch:

1. Keep `contest_honest_headline_v1` as the only headline name.
2. Preserve the object-purity gates and single-variable mode comparison.
3. Add a true S1 connected multihop slice where a second retrieval or validation
   outcome changes the executable action.
4. Add a true S2 dependency slice where the prior rejection/accepted route changes
   the admissible action and is visible in row-level output.
5. Keep memory replay claims separate unless the headline explicitly contains
   prior-dependent rows with non-zero reuse behavior.
6. Only then run deterministic/API repeat=1, followed by repeat=3/10 if clean.
