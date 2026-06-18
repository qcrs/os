# StateBus Goal2 Requirement Map

Date: 2026-06-18

> Superseded status note, 2026-06-18:
> This Goal2 document is preserved as a pre-Goal3 review artifact.
> Its statements that the current headline is repeat-insufficient,
> fresh-retrieval-only, or missing current-headline memory/replay are no longer
> current. The frozen current-state source is now
> `docs/reports/final_claim_matrix_and_freeze_20260618.md`, backed by
> `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`.
> Keep using this document for requirement decomposition and claim separation,
> not for current Goal3 headline status.

Scope: current worktree at `/home/qcrs/statebus/project`, branch observed as
`goal/20260618-thickness-contract-r1`, with a dirty tree. This file is a review
artifact, not an implementation plan.

Primary local sources read:

- `docs/review/statebus_goal2_full_review_and_rebuild_20260618.md`
- `docs/reference/题目.md`
- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
- `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
- `docs/review/statebus_benchmark_charter_20260617.md`
- `docs/review/statebus_new_window_guidance_20260617.md`
- `docs/analysis/statebus_current_thinking_reset_20260617.md`
- `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
- `docs/analysis/statebus_full_repo_scan_20260617.md`
- `docs/analysis/honest_full_audit_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`
- run packages listed below.

Current run evidence checked:

- Historical comprehensive package: `runs/comprehensive_eval_20260607_131113/`
- Historical replay-aware package: `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- Current thickness deterministic repeat=1: `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/`
- Current thickness API repeat=1: `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/`

The two requested run paths under repo-local `runs/` did not exist in the
current repo root, but they do exist under `$STATEBUS_RUNS_DIR`:

- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/`
- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/`

Current validation snapshot:

- `source deploy/activate_statebus_host.sh && python -m runtime.smoke` passes as
  a deterministic repeat=1 host sanity check.
- The explicit path
  `/home/qcrs/statebus/conda-envs/statebus_host/bin/activate` is absent in the
  current filesystem; the repo activation script is the working environment
  entrypoint and reports Python `3.11.15`.
- A previous full `python -m pytest -q` run failed at
  `tests/test_llm_runtime.py:532`; the targeted recheck of that item now passes.
  This should be recorded as a planner-contract boundary to keep strict LLM
  planning separate from YAML validate-compat insertion, not as a current reason
  to repair code in this documentation goal.
- A fresh full `source deploy/activate_statebus_host.sh && python -m pytest -q`
  rerun after this documentation hardening passed with `207 passed, 101 warnings
  in 406.35s`.

## Contest Understanding Summary

The contest is not asking for a generic workflow wrapper. It asks for a
runable multi-agent infrastructure prototype around three mechanism claims:

1. low-overhead structured communication versus pure-text collaboration;
2. non-text intermediate state transfer through embedding, semantic vector,
   hidden-state-like feature, or another intermediate representation;
3. shared memory storage, retrieval, and cross-task reuse.

The main scoring object should therefore be a mechanism evaluation, not just a
scenario shell. The core variable must be the collaboration mechanism under
matched task conditions. CodeAct, container isolation, eBPF, WASM, Docker,
openEuler VM validation, LangGraph comparison, and open engineering baselines
can support the project, but they are not the contest-facing headline unless a
separate validated claim says so.

Pure-text baseline, structured protocol, non-text state transfer, and shared
memory reuse must stay separate:

- Pure text is the comparison object for communication. It cannot secretly
  receive typed decision fields, but it can share the same execution engine if
  the report says so honestly.
- Structured protocol is a communication/control-plane mechanism. It should not
  be credited with memory replay or typed-state gains unless the benchmark
  isolates that variable.
- Non-text state transfer is a state-object mechanism. It should not be reduced
  to lower text bytes, and it should not be described as hidden-state/KV cache
  transfer when the implementation is feature/packet/state-ref based.
- Shared memory reuse is a cross-task memory mechanism. It requires non-zero
  reuse gain or skipped steps for a performance claim; memory hits alone are
  assist evidence.

## Requirement-by-Requirement Status

| Contest requirement | Current status | Evidence | Judgment |
| --- | --- | --- | --- |
| At least 3 agents and 3 roles covering planning, retrieval, execution, summarization/tooling | Implemented, but internally staged | `agents/sample_agents.py` implements Planner, Retriever, Executor, Summarizer; README lists the same core layout. `tasks/sample_tasks.py:634` builds retrieve/validate/execute/summarize plans when required. | `contest closure required`: acceptable host prototype, but do not present as general distributed multi-agent runtime. |
| Multi-step complex task | Partly implemented | Current `contest_honest_headline_v1` now has static S1/S2 contract fields and a 4-step `retrieve -> validate -> execute -> summarize` plan. API repeat=1 report shows planned step count and message count consistent with this shape. | `task design issue`: this is a real validation step, but not connected multi-hop retrieval/execution. It is still one retrieval pass plus validation over the same route/tool decision. |
| Structured communication protocol with actions, parameters, results, capability/handshake | Implemented | README identifies protocol/runtime modules and active text/protocol task sets. `runtime/orchestrator.py` prepares plan emission, capability/schema validation, and state refs. | `contest closure required`: valid core capability. Do not overclaim all-agent external transport. |
| Text and structured protocol modes under same task conditions | Implemented for formal headline | Current API repeat=1 report for `contest_honest_headline_v1` says mode task counts are `{'text': 20, 'protocol': 20}`, single-variable contract is yes, variable axis is `mode`, and object parity gate passes. | `contest closure required`: current headline object is clean enough for correctness/object-purity, but formal repeat gate still withheld. |
| Non-text intermediate state transfer | Implemented at feature/packet/state-ref level | Current API repeat=1 transfer truth reports `typed_executor_minimal_expected_consumption_rate = 1.00`, expected kind match `1.00`, unexpected kind seen `0.00`, and primary object `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`. | `contest closure required`: valid non-text state object. `reporting / narrative issue`: never call it hidden-state or KV transfer. |
| Shared memory module with memory ID, source, time, topic, summary metadata | Implemented | Prior audit and current code show SQLite/FAISS memory store plus summarizer memory commits. `agents/sample_agents.py` builds shared metadata from source agent, task, route, doc ids, trace, and replay fields. | `contest closure required`: module exists. |
| Search historical memory by keyword/tags/semantic similarity and reuse in later tasks | Implemented in support/formal-secondary surfaces, not active in current headline | Historical package `host_goal_eval_20260608_093111_planner_contract_refresh` supports replay-aware repeat=10. Current `contest_honest_headline_v1` repeat=1 report has `assist_memory_hit_rate_mean = 0.00` and memory replay gate not applicable. | `benchmark artifact`: memory reuse exists, but current contest headline does not exercise it as a main effect. Do not merge old replay packages into the communication headline. |
| At least 2 groups of related continuous tasks to verify communication, non-text state, memory reuse | Partly implemented, claim narrowed | Current headline covers 5 families x 4 cases and carries S1/S2 metadata. But its manifest says all 40 rows are `memory_off`, all expected reuse modes are `none`, and `task_contract_counts.allow_memory_assist/allow_execute_prune/allow_exact_replay = 0`. Historical 18-task replay-aware packages show memory reuse elsewhere. | `task design issue`: related families exist, but the current formal headline verifies communication/state transfer only, not memory reuse. Memory scoring must use a separate support layer or a reset headline with real prior-dependent rows. |
| Show message count, token/char cost, non-text transfer count/size, latency, memory hit rate, overall improvement | Implemented metrics; claim scope limited | API repeat=1 report shows message count, state-transfer count, control bytes, handoff wire/payload bytes, LLM tokens, task latency, primary metrics. Memory hit is zero in the current headline. | `reporting / narrative issue`: reporting exists, but improvement must be claimed only per evidence layer. |
| Stable execution of at least 10 continuous rounds | Not proven for current headline | Current deterministic/API thickness runs are repeat=1 and both reports mark formal stability gate `not_yet`; withheld reason is `contest_repeat_insufficient`. Historical repeat=10 packages are not the same current headline object. | `contest closure required`: repeat=10 remains missing for the current contest-facing headline. |
| Complete source, design docs, deploy docs, experiment report, demo video; openEuler 24.03-LTS-SP3 final run | Partly implemented | Repo has source/docs/deploy scripts/reports. AGENTS and constraints explicitly keep openEuler VM as posterior validation and final delivery. | `contest closure required`: current host prototype is not final openEuler delivery. |
| CodeAct lightweight sandbox support encouraged | Not contest mainline | Feature-scope docs say strong sandbox and CodeAct final chain are postponed. Current executor is tool registry/subprocess/UDS sample, not CodeAct. | `later enhancement`: do not pull into headline to appear more innovative. |

## Innovation Implementation Map

### Structured Communication

Status: real and contest-relevant.

Evidence:

- `contest_honest_headline_v1` is the current formal dual-mode headline.
- Current API repeat=1: text control bytes `9553.50`, protocol `7502.90`, delta `-2050.60`.
- Protocol side consumes minimal typed state and keeps unexpected executor kind rate at `0.00`.

Classification:

- True contest mechanism for communication efficiency.
- Current gap is not existence; it is whether the benchmark is thick enough and repeat-stable enough to claim method strength.

### Non-Text State Transfer

Status: real at StateRef/packet/feature level.

Evidence:

- Protocol minimal packet contains `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`.
- API repeat=1 transfer truth: expected consumption `1.00`.
- `runtime/executor_runtime.py` loads `EXECUTOR_DECISION_PACKET` for
  `state_packet_minimal` and validates it.

Classification:

- True contest mechanism.
- Not hidden-state/KV transfer. That remains unsupported.

### Shared Memory and Replay

Status: real but not unified into the current contest headline.

Evidence:

- Historical `host_goal_eval_20260608_093111_planner_contract_refresh/` has replay-aware repeat=10 evidence.
- Current headline repeat=1 has memory hit `0.00`, skipped steps `0`, replay gate not applicable.

Classification:

- True support/formal-secondary mechanism.
- `benchmark artifact` if old replay results are used to prove the current headline.

### Tool / Executor Mechanism

Status: implemented as tool registry/playbook/subprocess/UDS sample.

Evidence:

- `runtime/executor_runtime.py` uses `ToolRegistry`, `ToolSpec`, route/tool selection, and `LightweightSubprocessRunner`.
- `agents/sample_agents.py` validation step gates route/tool decisions before execution.

Classification:

- Engineering implementation, not a new contest headline by itself.
- Still route/playbook shaped; not CodeAct and not general tool marketplace.

### StatePool / StateRef

Status: implemented and meaningful.

Evidence:

- README and feature scope list `StateRef + mmap/shared_memory + SQLite + FAISS`.
- Current API repeat=1 protocol mode has non-zero state-transfer count and StatePool payload bytes.

Classification:

- True state-transfer substrate.
- `shared_memory` backend is a real option but not the formal headline unless matched evidence says so.

## Evidence Layer Separation

### Formal Headline Evidence

Use only for contest-facing text-vs-protocol claims:

- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/`
- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/`

Current allowed claims:

- object parity passes;
- whole-lane text guard passes;
- protocol has lower control bytes in deterministic and API repeat=1;
- protocol has real typed executor consumption;
- formal headline remains withheld for repeat insufficiency.
- all current headline rows are fresh-retrieval rows: `memory_policy_counts.memory_off = 40`,
  `expected_reuse_mode_counts.none = 40`, and `memory_replay_evidence_gate.applicable = false`.

Current disallowed claims:

- repeat=10 stability;
- protocol latency win under API mode;
- LLM token saving under API mode;
- memory replay gain inside this headline.
- S2 replay rows as runtime reuse proof, because current S2 rows have
  `runtime_reuse_contract = reuse_disabled`.

### Support Evidence

Use for mechanism authenticity, memory replay, planner openness, and negative controls:

- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `memory_policy_controlled_v3`
- `memory_reuse_v3`
- `planner_support_v3`
- historical host replay packages.

Support evidence can prove implementation reality, but cannot be promoted to the formal communication headline.

### Audit-Only Evidence

Use for object/fairness guardrails:

- `memory_dual_mode_fairness_v3`
- `external_text_baseline_audit_v3`
- `text_definition_audit_v3`
- `carrier_microbench_v3`
- legacy authenticity/full-rich surfaces.

Audit-only surfaces are useful for detecting hidden leakage or compatibility problems. They are not headline performance evidence.

## Issue Classification List

| Issue | Classification | Evidence | Required action |
| --- | --- | --- | --- |
| Current headline still withheld by repeat insufficiency | `contest closure required` | Current deterministic/API repeat=1 reports mark formal stability `not_yet` and required repeat 10. | Do not claim final formal headline until repeat gate is rerun on the current object. |
| Static S1/S2 fields exist, but current runtime shape is fixed 4-step validate flow | `task design issue` | `tasks/sample_tasks.py:634-699`; current reports show fixed 20 text + 20 protocol rows and fresh retrieval only. | Treat as partial thickening, not full connected multihop proof. |
| Current headline does not exercise memory reuse | `benchmark artifact` | Current API repeat=1 shows assist memory hit `0.00` and memory replay gate not applicable. | Keep memory headline separate or design S2 where prior dependency changes admissible action. |
| Current S2 rows declare prior dependency but still disable runtime reuse | `task design issue` | `rr-billing-replay_reusable-protocol-001` has S2 fields and prior routes/rejections, while `runtime_reuse_contract = reuse_disabled`; current manifest has all rows `memory_off`. | Treat S2 as static contract until a reset task actually consumes prior state. |
| Text whole-lane has natural-language route/tool hints and lexical recovery | `structural design mismatch` | `agents/sample_agents.py:171-202`; `runtime/executor_runtime.py:1002-1015`; validation can recover text route/tool. | Document honestly; do not call it external pure-text baseline. |
| Protocol bytes win does not imply token or latency win | `reporting / narrative issue` | API repeat=1: control bytes down, LLM tokens +1.75, task ms +37.24. | Word headline as communication compactness unless repeat-thick benchmark proves more. |
| Hidden-state/KV, nsjail, Docker/openEuler validation absent | `later enhancement` | Feature-scope and constraints docs; current host boundary. | Keep out of current claims. |

## Requirement Conclusion

The system is a real host-side prototype and satisfies many literal contest
requirements at implementation level. However, current evidence does not prove
that the contest-facing method has a mature benchmark that can judge method
strength across all three scoring axes. The honest status is:

- communication/state-transfer mechanisms are implemented and measurable;
- memory reuse exists but is separated from the current headline;
- current benchmark has improved object purity and static thickness, but remains
  too route-shaped and fresh-retrieval-only to serve as final method裁决;
- openEuler/repeat=10 delivery closure remains missing.
