# StateBus Goal2 Reading, Search, and Judgment Log

Date: 2026-06-18

> Superseded status note, 2026-06-18:
> This is a historical reading/search log for the Goal2 review. Later Goal3
> artifacts changed the current headline facts: API repeat=10 is closed,
> S1/S2 runtime gates are ready, and headline memory replay effect is present.
> Use `docs/reports/final_claim_matrix_and_freeze_20260618.md` for current
> frozen headline status.

Scope: documentation hardening for the already completed Goal2 review. This log
records what was read, what was searched, what changed the judgment, and what
still remains only partially verified. It is not an implementation plan and it
does not authorize code, benchmark-contract, Docker, openEuler, nsjail,
hidden-state, or KV-cache work.

## Environment and Validation Record

Requested environment entry sequence:

```bash
source /home/qcrs/statebus/conda-envs/statebus_host/bin/activate
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
```

Observed environment nuance:

- `/home/qcrs/statebus/conda-envs/statebus_host/bin/activate` is absent in the
  current filesystem.
- `source deploy/activate_statebus_host.sh` works and reports:
  - active env: `/home/qcrs/statebus/conda-envs/statebus_host`;
  - Python: `3.11.15`;
  - model dir: `/home/qcrs/statebus/models`;
  - statepool dir: `/home/qcrs/statebus/work/statepool`;
  - LLM config: `deploy/statebus_llm.yaml.local`.

Validation results recorded during the hardening pass:

| Command | Current observed result | Review meaning |
| --- | --- | --- |
| `source deploy/activate_statebus_host.sh && python -m runtime.smoke` | Passed. Latest observed text row: `memory_hits=0.0`, `messages=292.0`, `control_bytes=184033.0`; protocol row: `memory_hits=0.0`, `messages=292.0`, `control_bytes=150133.0`. | Confirms runnable host sanity path only. The smoke itself says it is deterministic repeat=1 host sanity, not formal API timing evidence. |
| earlier `source deploy/activate_statebus_host.sh && python -m pytest -q` | Failed once at `tests/test_llm_runtime.py:532`, `test_plan_parser_rejects_missing_validate_for_validate_first_task`. | Important contract signal: validate-first LLM planner output missing `validate` must not be silently accepted. |
| `source deploy/activate_statebus_host.sh && python -m pytest -q tests/test_llm_runtime.py::test_plan_parser_rejects_missing_validate_for_validate_first_task` | Passed in the current worktree. | The earlier full-suite failure is not current targeted proof of a red item, but the contract boundary remains important enough to document. |
| final `source deploy/activate_statebus_host.sh && python -m pytest -q` | Passed: `207 passed, 101 warnings in 406.35s`. | Current worktree test status is green after this documentation hardening pass. |

The failing/passing test is not about benchmark row correctness. It is about
strict planner semantics. `tests/test_llm_runtime.py:490-533` builds a planner
output with `retrieve`, `execute`, and `summarize`, while omitting `validate`,
then expects `_plan_from_llm_output()` to reject it for
`planner-support-auth-llm-002`.

Code anchors:

- `agents/sample_agents.py:1675-1715`: parses LLM planner output and validates it.
- `agents/sample_agents.py:1718-1747`: determines whether a validate-compat
  step may be inserted.
- `agents/sample_agents.py:1750-1799`: inserts the compatibility validate step.
- `agents/sample_agents.py:2175-2180`: rejects missing required semantic roles.
- `tasks/sample_tasks.py:634-699`: YAML headline plan builder emits fixed
  `retrieve -> validate -> execute -> summarize` when validate is required.

Interpretation: validate compatibility insertion is acceptable only as a scoped
YAML contest-headline compatibility mechanism. It should not be treated as
evidence that LLM planning authentically produced a validate-first plan.

## Local Reading Record

| Material | Question answered | Judgment impact |
| --- | --- | --- |
| `docs/review/statebus_goal2_full_review_and_rebuild_20260618.md` | What did Goal2 require beyond a summary? | Established that this pass must preserve reading/search/judgment traces and use external calibration after local reconstruction. |
| `docs/reference/题目.md` | What does the contest actually score? | Re-centered the review on communication efficiency, non-text state transfer, memory reuse, system completeness, and experiment validation. |
| `README.md` | What is the current repo-facing claim surface? | Confirmed `contest_honest_headline_v1` is the formal headline and other v3 packs are support/audit surfaces. |
| `docs/constraints/current_host_and_migration.md` | What environment assumptions are allowed? | Confirmed host-first development and no Docker/nsjail/openEuler-as-current-mainline boundary. |
| `docs/constraints/current_feature_scope.md` | Which features are implemented vs planned? | Confirmed StateRef/mmap/shared_memory/SQLite/FAISS/UDS are real, while hidden-state/KV/nsjail/openEuler final delivery are not current claims. |
| `docs/analysis/statebus_review_requirement_map_20260618.md` | What requirement statuses had already been assigned? | Needed tightening around branch name, validation state, and memory reuse being absent from the current headline. |
| `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md` | What benchmark/task critique already existed? | Correct conclusion, but needed exact row/run evidence from the current packages. |
| `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md` | What runtime authenticity boundaries were already documented? | Needed latest pytest/runtime-smoke evidence and strict planner-vs-compat clarification. |
| `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md` | What external calibration had already been written? | Correct source families, but it needed search process, conflicts, and effect-on-conclusion columns. |
| `tasks/sample_tasks.py` | Is the runtime plan adaptive or fixed? | `build_plan()` confirms a fixed semantic DAG, with validate included from task metadata. |
| `tasks/contest_family_spec.yaml` and `tasks/contest_family_spec.py` | Are S1/S2 fields real? | They are real static contract fields and validators, but not proof of dynamic connected multihop. |
| `agents/sample_agents.py` | Does the planner/retriever/executor behavior exist as code? | Confirmed real parser/validator/retriever/executor paths plus validate-compat insertion boundary. |
| `runtime/orchestrator.py` | Is validate a runtime semantic role? | Confirms validate role can gate protocol execution, but current headline still follows a fixed four-step shape. |
| `runtime/executor_runtime.py` | Does text/protocol executor consumption differ? | Confirms text recovery and protocol packet consumption are different handoff objects under the same executor engine. |
| `tests/test_llm_runtime.py` | What does the latest pytest issue mean? | It is a strict semantic role coverage contract, not a reason to patch code in this documentation goal. |
| `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/` | What does deterministic repeat=1 currently prove? | Object/gate clean at repeat=1, fresh retrieval only, no repeat=10 closure. |
| `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/` | What does API repeat=1 currently prove? | Same object/gate clean and lower protocol control bytes, but no token/latency win and no memory reuse. |
| `runs/host_goal_eval_20260608_093111_planner_contract_refresh/` | What does historical replay-aware evidence prove? | Memory/replay exists with repeat=10 and non-zero skipped steps, but it is a different 18-task object. |
| `runs/comprehensive_eval_20260607_131113/` | What does older comprehensive evidence prove? | Host env and older assist-style memory are valid background, but not current headline proof. |

Materials that changed or tightened the judgment:

- `docs/reference/题目.md` tightened the standard: memory reuse must be judged by
  actual reuse behavior, not by the existence of a memory module.
- Current headline manifests tightened the benchmark judgment: every current
  row is `memory_off`, expected reuse is `none`, and the formal stability gate
  fails only because repeat is 1 of required 10.
- `load_task_set_bundle("contest_honest_headline_v1")` tightened the S2 judgment:
  S2 rows carry prior fields but still have `runtime_reuse_contract =
  reuse_disabled`.
- Historical replay packages prevented an overly negative conclusion: memory
  and replay are real in support evidence, so the correct classification is
  evidence-layer separation, not "memory is fake".
- External framework sources weakened any generic "multi-agent framework"
  novelty claim and forced the innovation tree back to protocol/state/memory
  mechanisms.

## Run-Level Evidence Log

Current headline packages:

| Package | Key facts | Judgment |
| --- | --- | --- |
| `/home/qcrs/statebus/runs/contest_honest_headline_thickness_api_r1_fix1/` | `task_count=40`, `repeat=1`, public surface `formal_headline`, single variable `mode`, object parity passed, formal stability failed with `required_repeat=10`, all `memory_policy_counts.memory_off=40`, all `expected_reuse_mode_counts.none=40`, `memory_replay_evidence_gate.applicable=false` | Valid repeat=1 object/gate evidence; not repeat=10 or memory-reuse evidence. |
| `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix4/` | Same structural manifest pattern; deterministic text/protocol aggregates have `memory_hits=0`, `memory_query_count=0`, `skipped_step_count=0`, `reuse_gain=0`, and `planned_step_count=80` / `trajectory_step_count=80` | Confirms the fresh-retrieval-only shape is not API-specific. |

Representative current API rows:

| Row | planned / trajectory | reuse counters | Judgment |
| --- | ---: | --- | --- |
| `rr-auth-clean-text-001` | `4 / 4` | `memory_hits=0`, `memory_query_count=0`, `skipped_step_count=0`, `reuse_gain=0` | S1 row is fixed four-step fresh retrieval. |
| `rr-auth-clean-protocol-001` | `4 / 4` | same zero counters | Protocol row is matched but not deeper. |
| `rr-deploy-replay_reusable-text-001` | `4 / 4` | same zero counters | Name says reusable, but current headline does not trigger reuse. |
| `rr-deploy-replay_reusable-protocol-001` | `4 / 4` | same zero counters | S2 metadata is not runtime replay proof. |

Historical contrast packages:

| Package | Key facts | Judgment |
| --- | --- | --- |
| `runs/host_goal_eval_20260608_093111_planner_contract_refresh/deterministic_repeat10/` | 18 tasks, repeat 10, expected reuse modes `assist=6`, `none=6`, `skip_execute=3`, `skip_retrieve_execute=3`, `memory_hit_rate=0.83`, `skipped_step_count=9`, `reuse_gain=0.17`, `expectation_match_rate=1.00` | Proves replay-aware machinery exists, but on a different object. |
| `runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/` | Same replay-aware shape under API mode; text tokens `24384.4`, protocol tokens `16625.9`; text task ms `81184.06`, protocol `60776.34` | Valid support evidence for replay-aware host mainline, not current contest headline. |
| `runs/comprehensive_eval_20260607_131113/api_repeat10_serial/` | 12 tasks, repeat 10, `memory_hit_rate=0.75`, `skipped_step_count=0`, `reuse_gain=0` | Older assist-style memory evidence; useful boundary example. |

## External Search Record

Search date: 2026-06-18.

### Benchmark / Task Thickness

| Query | Primary source checked | What it supports | What conflicts or cautions |
| --- | --- | --- | --- |
| `HotpotQA arXiv 1809.09600 official supporting facts distractor` | HotpotQA paper / dataset framing, https://arxiv.org/abs/1809.09600 | Supporting-fact and distractor design support a stronger evidence topology than StateBus's current route-shaped rows. | HotpotQA is QA, not a StateBus runtime benchmark; only borrow support/distractor discipline. |
| `MuSiQue arXiv 2108.00573 connected multi-hop questions` | MuSiQue paper, https://arxiv.org/abs/2108.00573 | Connected multihop and shortcut-reduction support the critique that static S1/S2 labels are not enough. | Do not import QA composition directly; adapt to release-regression action chains. |
| `BRIGHT arXiv 2407.12883 reasoning-intensive retrieval benchmark` | BRIGHT paper, https://arxiv.org/abs/2407.12883 | Reasoning-before-retrieval supports the critique that current retrieval should not be solvable by route keywords alone. | It is a retrieval benchmark, not a multi-agent communication benchmark. |
| `LongMemEval arXiv 2410.10813 benchmark long-term memory LLM agents` | LongMemEval paper, https://arxiv.org/abs/2410.10813 | Long-history memory retrieval supports requiring prior-history dependency for memory claims. | Chat-memory tasks should not replace StateBus's system-layer benchmark. |
| `LongMemEval-V2 long-term memory benchmark arXiv 2026 LLM agents` | LongMemEval-V2 paper, https://arxiv.org/abs/2606.18045 | Strengthens that memory should be evaluated as an environment/experience mechanism, not only memory hit counters. | Newer external object; use as calibration, not as a local benchmark target. |

### Agent / Tool Benchmark Calibration

| Query | Primary source checked | What it supports | What conflicts or cautions |
| --- | --- | --- | --- |
| `tau-bench arXiv 2406.12045 benchmark tool agents official GitHub` | tau-bench paper, https://arxiv.org/abs/2406.12045 | End-state/task-success evaluation supports adding verifiers beyond route labels. | The retail/airline environments should not be copied into this contest pack. |
| `AgentBench arXiv 2308.03688 official benchmark agents` | AgentBench paper, https://arxiv.org/abs/2308.03688 | Multi-environment agent evaluation supports repeated reliability rather than one-run aggregate claims. | It is broader than StateBus and can distract from mechanism isolation. |
| `ToolBench arXiv 2307.16789 tool learning benchmark official GitHub` | ToolBench paper, https://arxiv.org/abs/2307.16789 | Tool/API selection can be a real benchmark object if the tool universe is nontrivial. | StateBus's small playbook registry is not comparable to ToolBench-scale tool use. |
| `GAIA benchmark general AI assistants arXiv 2311.12983 official` | GAIA paper, https://arxiv.org/abs/2311.12983 | Multi-step reasoning/tool/information gathering supports verifier discipline. | GAIA is open assistant QA, not low-overhead communication. |

### Multi-Agent Communication / Role / Memory

| Query | Primary source checked | What it supports | What conflicts or cautions |
| --- | --- | --- | --- |
| `AutoGen multi-agent conversation framework arXiv 2308.08155 official GitHub` | AutoGen paper, https://arxiv.org/abs/2308.08155 | Roles and message protocols can be first-class system objects. | Weakens novelty if StateBus is framed as just another multi-agent conversation framework. |
| `CAMEL communicative agents role-playing inception prompting arXiv 2303.17760 official GitHub` | CAMEL paper, https://arxiv.org/abs/2303.17760 | Role-based communicative agents are a known baseline pattern. | Role play does not prove low-overhead state transfer. |
| `MetaGPT multi-agent framework SOP arXiv 2308.00352 official GitHub` | MetaGPT paper, https://arxiv.org/abs/2308.00352 | SOP/team workflow design is a useful contrast for planner/executor narratives. | Copying it would move StateBus toward generic workflow orchestration. |
| `Mem0 memory layer AI agents arXiv official GitHub` | Mem0 official repo, https://github.com/mem0ai/mem0 | Persistent memory should be a separate extraction/search/update layer with separate metrics. | Mem0 is not a communication-overhead benchmark. |

## Judgment Revision Record

| Initial judgment | Evidence that changed it | Revised judgment |
| --- | --- | --- |
| Current object/gate cleanup might be enough to proceed to heavier repeats. | Current task rows are all `memory_off`, expected reuse is all `none`, and S2 rows have `reuse_disabled`. | Do not rush repeat=10 before task thickness is made executable; repeat count cannot fix missing memory/runtime dependency. |
| S1/S2 labels may be sufficient as benchmark thickening. | MuSiQue/HotpotQA/BRIGHT calibration and local row evidence show connected evidence dependency matters. | S1/S2 fields are a schema for thickness, not proof of connected multihop behavior. |
| Memory may be too weak globally. | `host_goal_eval_20260608_093111_planner_contract_refresh` has non-zero skipped steps and reuse gain under repeat=10. | Memory/replay is real support evidence, but absent from the current headline. |
| Multi-agent role structure itself could be a central innovation claim. | AutoGen/CAMEL/MetaGPT make multi-agent role/message frameworks a known object. | Roles satisfy completeness; innovation must be protocol/state/memory mechanism under matched benchmark. |
| The pytest failure means the current code is necessarily red. | Targeted recheck of the failing test now passes. | Record the strict planner-contract boundary; do not patch code in this documentation goal; rely on the final full-suite result for current verification. |

## Current Stoplines

- Stop presenting `contest_honest_headline_v1` as memory-reuse evidence until a
  headline row actually has non-zero memory/replay behavior.
- Stop treating static S2 prior fields as runtime prior-state use.
- Stop treating repeat=1 object parity as repeat=10 formal stability.
- Stop using historical replay-aware repeat=10 packages as if they were current
  contest headline proof.
- Stop framing StateBus as a generic multi-agent orchestration framework; keep
  the claim at low-overhead protocol, typed state, and replay-aware memory.

## Remaining Uncertainty

- External sources were used for calibration only. No external benchmark has
  been imported or run locally.
- The exact future implementation of connected S1 and executable S2 tasks is
  intentionally out of scope for this documentation-only goal.
