# StateBus Goal2 External Alignment and Rebuild Decision

Date: 2026-06-18

> Superseded status note, 2026-06-18:
> This external alignment pass was written before the Goal3 S1/S2/memory/repeat
> closures. Its external calibration remains useful, but its local diagnosis that
> the current headline is fresh-retrieval-only or repeat-insufficient is no
> longer current. The frozen current-state source is
> `docs/reports/final_claim_matrix_and_freeze_20260618.md`.

This file records the external calibration pass required by Goal2 and uses it
to decide whether StateBus needs patching, benchmark reset, task reconstruction,
runtime restructuring, or claim reduction.

## External Calibration Question

Based on the local review, the main question is not "can StateBus run?" It can.
The question is:

> Does the current contest headline benchmark evaluate the mechanisms the contest
> actually cares about strongly enough to judge method strength?

The local diagnosis says no, mainly because:

- current headline is fresh-retrieval-only and does not exercise memory reuse;
- S1/S2 thickness is mostly static plus a fixed validate gate;
- tasks remain route/corpus shaped rather than connected multihop;
- current API repeat=1 shows communication bytes win, but not token or latency win.

External sources were used to calibrate benchmark/task design, not to copy a
framework.

## Search Procedure

Search date: 2026-06-18.

The review first rebuilt the local problem from `docs/reference/题目.md`, the
current StateBus review docs, code, tests, and run packages. Only after that
local diagnosis did it use external search to calibrate the benchmark standard.
Representative queries used:

- `HotpotQA arXiv 1809.09600 official supporting facts distractor`
- `MuSiQue arXiv 2108.00573 connected multi-hop questions`
- `BRIGHT arXiv 2407.12883 reasoning-intensive retrieval benchmark`
- `LongMemEval arXiv 2410.10813 benchmark long-term memory LLM agents`
- `LongMemEval-V2 long-term memory benchmark arXiv 2026 LLM agents`
- `tau-bench arXiv 2406.12045 benchmark tool agents official GitHub`
- `AgentBench arXiv 2308.03688 official benchmark agents`
- `ToolBench arXiv 2307.16789 tool learning benchmark official GitHub`
- `GAIA benchmark general AI assistants arXiv 2311.12983 official`
- `AutoGen multi-agent conversation framework arXiv 2308.08155 official GitHub`
- `CAMEL communicative agents role-playing inception prompting arXiv 2303.17760 official GitHub`
- `MetaGPT multi-agent framework SOP arXiv 2308.00352 official GitHub`
- `Mem0 memory layer AI agents arXiv official GitHub`

Priority rule: use paper pages, official dataset/benchmark pages, or official
repositories. Third-party summaries were not used as evidence.

## External Sources Checked

Benchmark/task thickness:

- HotpotQA paper / official dataset framing: multi-hop QA with supporting facts
  and distractor settings.
  Source: https://arxiv.org/abs/1809.09600
- MuSiQue paper: connected multi-hop questions constructed to reduce shortcut
  reasoning.
  Source: https://arxiv.org/abs/2108.00573
- BRIGHT benchmark: reasoning-intensive retrieval where retrieval requires
  reasoning before evidence selection.
  Source: https://arxiv.org/abs/2407.12883
- LongMemEval / LongMemEval-V2 line: long-term memory evaluation over histories,
  where relevant prior interactions must be retrieved and used.
  Source: https://arxiv.org/abs/2410.10813
- LongMemEval-V2: newer long-term memory benchmark for memory agents, useful
  because it emphasizes a memory environment over accumulated user-agent
  interactions rather than one-shot current-context retrieval.
  Source: https://arxiv.org/abs/2606.18045

Retrieval/routing/tool selection:

- semantic-router official repository/docs: explicit semantic route layer before
  execution.
  Source: https://github.com/aurelio-labs/semantic-router
- LangGraph BigTool official examples/docs: large tool selection through graph
  state and retrieval-like tool lookup.
  Source: https://github.com/langchain-ai/langgraph-bigtool
- Haystack official docs: components/pipelines/agents with retrievers and tool
  calling as explicit orchestration objects.
  Source: https://docs.haystack.deepset.ai/docs/agent

Memory/replay/layered retrieval:

- Mem0 official repository/docs and paper materials: persistent agent memory as
  its own layer, not just prompt assist.
  Source: https://github.com/mem0ai/mem0
- MemSearch papers/repos found in search: memory retrieval tasks emphasize
  searching historical context rather than only reusing current-case labels.
  Source: https://github.com/zilliztech/memsearch
- AgentRx search materials: feedback/memory for agents; relevant as a reminder
  that replay/reuse needs an evaluation loop, not just stored summaries.
  Source: https://arxiv.org/abs/2602.02475

Agent evaluation / tool-using benchmark calibration:

- tau-bench: evaluates agents by task success/end-state in realistic tool
  environments over repeated trials.
  Source: https://arxiv.org/abs/2406.12045
- AgentBench: evaluates LLMs as agents across environments rather than only
  single-step classification.
  Source: https://arxiv.org/abs/2308.03688
- ToolBench: tool-use benchmark with API/tool-selection behavior.
  Source: https://arxiv.org/abs/2307.16789
- GAIA: assistant benchmark requiring tool use, reasoning, and multi-step
  information gathering.
  Source: https://arxiv.org/abs/2311.12983

Multi-agent structured communication / intermediate representation:

- AutoGen, CAMEL, and MetaGPT papers/docs were checked as representative
  multi-agent communication/framework lines.
  Sources: https://arxiv.org/abs/2308.08155,
  https://arxiv.org/abs/2303.17760, https://arxiv.org/abs/2308.00352
- They reinforce that "many agents exchanging messages" is not sufficient; the
  benchmark must show the communication/intermediate representation changes
  task behavior or efficiency.

Conflict / caution sources:

- AutoGen, CAMEL, and MetaGPT are useful multi-agent role/protocol references,
  but they can weaken a StateBus claim if StateBus is presented as "another
  multi-agent workflow framework". They do not by themselves validate low-cost
  state transfer.
- semantic-router and Haystack show explicit routing/retrieval components, but
  they also reveal that StateBus's current route selector is not novel if the
  claim stops at route classification. StateBus must keep the claim at
  protocol/state/memory mechanism level.
- tau-bench, AgentBench, ToolBench, and GAIA are broader agent/tool evaluation
  objects. They support end-state/verifier discipline, but their environments
  should not be copied into this contest headline.

## External Contrast Table

| Current StateBus problem | External object | Borrowed mechanism / evaluation idea | Why it fits | Why not copy directly | Effect on current conclusion |
| --- | --- | --- | --- | --- | --- |
| Current tasks remain route-shaped and can be solved by one retrieval pass | HotpotQA | supporting facts plus distractor universe | Requires explicit evidence support and distractor exclusion, matching StateBus route-competition needs | HotpotQA is QA, not multi-agent state-transfer; borrow supporting-fact contract, not dataset | Supports C: task contract needs thickening, not whole-project abandonment |
| Static S1/S2 fields do not force connected reasoning | MuSiQue | connected multihop composition and shortcut reduction | Gives a clear rule: removing one hop should break the answer | Do not import QA composition wholesale; adapt to release-regression action chains | Strengthens benchmark reset: S1/S2 labels are insufficient |
| Retrieval is often evidence packaging after query terms reveal route | BRIGHT | reasoning-before-retrieval | Forces retrieval to depend on inferred intent rather than direct keyword overlap | BRIGHT is retrieval benchmark, not runtime benchmark; borrow query design pressure | Strengthens "route-shaped corpus" critique |
| Memory headline absent from current formal object | LongMemEval / LongMemEval-V2 | history-to-evidence memory retrieval over prior interactions | Fits contest memory reuse requirement directly and demands memory use beyond current context | Do not turn StateBus into chat-memory benchmark; borrow prior-history dependency contract | Strengthens claim reduction: current headline cannot claim memory reuse |
| Route/tool selector is too playbook-shaped | semantic-router | explicit route layer with semantic thresholds | Helps make routing first-class and auditable | Already similar; copying router library does not solve benchmark thickness | Weakens any claim that route selection alone is novel |
| Tool selection is static registry over small known tools | LangGraph BigTool | retrieve/select among many tools using graph state | Suggests scaling tool competition and recording state transitions | Full LangGraph replacement is unnecessary and not the contest headline | Supports future task/tool competition, not immediate framework migration |
| Retriever/executor pipeline is monolithic | Haystack | componentized retriever/agent/tool pipeline | Useful modular reference for cleanup and explicit component contracts | Do not migrate framework; preserve StateBus protocol/statepool value | Supports code cleanup only after benchmark reset |
| Memory proof split from headline | Mem0 | memory as a persistent extraction/search/update layer | Supports treating memory as a separate mechanism with own metrics | Mem0 is a memory layer, not a StateBus communication benchmark | Supports evidence-layer separation |
| Replay needs dynamic evidence, not only static fields | MemSearch / AgentRx | memory/search/feedback evaluation loop | Reinforces need for prior-dependent tasks and reuse correctness | Source fit is conceptual; local implementation should stay repo-specific | Strengthens "S2 static contract is not replay proof" |
| Current method judged on aggregate bytes only | tau-bench | end-state task success in realistic tool environments | Shows tool-agent benchmarks should judge final state, not only communication object labels | tau-bench task environments are not this contest object | Strengthens need for verifier/action outcomes |
| Current tool/evaluator surface is narrower than agent benchmark norms | AgentBench | multi-environment agent evaluation | Reminds that an agent system claim needs environment interaction and reliability | Too broad for this host-side contest prototype | Supports narrowing claims rather than copying benchmark |
| Tool use is mostly small registry/playbook selection | ToolBench | tool/API-selection supervision and evaluation | Shows tool selection can be a benchmark object if the tool universe is nontrivial | ToolBench API environment does not test StateRef/protocol overhead | Supports stronger tool competition only as secondary slice |
| Complex assistant task success is not captured by current route labels | GAIA | multi-step reasoning/tool/information tasks with answer verification | Supports end-state/verifier discipline | GAIA is open assistant QA, not low-overhead communication | Strengthens reporting: route exact is not enough |
| Multi-agent story risks becoming workflow orchestration | AutoGen | multi-agent conversation programming | Useful reference for role/message orchestration | Does not prove lower overhead or non-text state | Weakens overbroad "multi-agent framework" claim |
| Role-playing agents can look impressive without mechanism proof | CAMEL | role-based communicative agents | Confirms role decomposition is a known pattern | Role-play is not a state-transfer benchmark | Supports keeping StateBus claim system-layered |
| SOP-style multi-agent workflows overlap with planner/executor narratives | MetaGPT | SOP/team workflow decomposition | Useful contrast for structured roles | If copied, StateBus becomes generic orchestration | Strengthens need to foreground protocol/state/memory mechanism |

## Judgment Revisions from External Pass

Initial local judgment:

- The current implementation has real mechanisms, but the benchmark remains too
  thin and too split across surfaces.

After external comparison:

- This judgment became stronger. External multihop and agent benchmarks use
  either supporting facts, connected hops, prior-history dependencies, tool-state
  verifiers, or repeated reliability to avoid evaluating a shallow scenario
  shell. StateBus currently has static approximations of these features, but
  not enough runtime-enforced depth in the formal headline.

Most important correction:

- The current S1/S2 fields are useful scaffolding, but they should not be
  considered completion of task thickness. They are a schema for thickness, not
  a full thick benchmark.

Second correction:

- External multi-agent frameworks weaken, rather than strengthen, any story that
  StateBus is novel merely because it has Planner/Retriever/Executor/Summarizer
  roles. Those roles satisfy contest completeness, but the innovation evidence
  must come from low-overhead protocol, typed intermediate state, and replay-aware
  memory under a thick benchmark.

## Rebuild Decision

### Is current work patch-only?

No.

Current known issues are not primarily implementation bugs. The object-purity
and report layers are mostly patched. The remaining issue is that the formal
benchmark/task object is not strong enough to adjudicate method strength.

Decision: not patch-only.

### Does benchmark need reset?

Yes.

But this should be a scoped reset, not a new headline name or new pack sprawl:

- keep `contest_honest_headline_v1`;
- reset its task contract from static S1/S2 labels to executable S1/S2 behavior;
- add row-level contract preservation;
- rerun minimal gates.

Decision: benchmark reset required.

### Does task set need reconstruction?

Yes.

The current task set should be reconstructed around:

- true connected multihop cases;
- dynamic validation branches;
- prior-dependent reusable cases;
- explicit abstention/collect-more-evidence verifiers;
- multi-tool competition where wrong tool is plausible and harmful.

Decision: task set reconstruction required.

### Does retrieval/executor/replay need structural reconstruction?

Partially, after the task reset.

Do not rewrite runtime first. But a true S1/S2 task may require:

- a second retrieval step after validation/executor output;
- a validation step that can change the plan branch, not only approve the current
  route/tool;
- a reusable case where prior memory changes admissible action and is verified;
- executor artifacts that feed back into retrieval as structured state.

Decision: partial structure reconstruction likely, but task-contract-first.

### Do claims need reduction?

Yes.

Allowed current claims:

- host-side prototype runs;
- formal headline repeat=1 object purity passes;
- protocol reduces control bytes under current headline;
- minimal typed-state packet is produced/transferred/consumed;
- memory/replay exists in support/formal-secondary evidence.

Withheld current claims:

- final formal repeat=10 headline;
- protocol end-to-end latency advantage;
- protocol LLM token saving;
- memory reuse benefit in current formal headline;
- external pure-text baseline win;
- hidden-state/KV transfer;
- CodeAct/sandbox/openEuler final delivery.

Decision: claim reduction required.

### Does StateBus need a new innovation mainline?

Not a completely new one.

The strongest contest-valid mainline remains:

> StateBus is a low-overhead state bus for multi-agent systems, combining
> structured control messages, typed intermediate state, and replay-aware shared
> memory.

But the evidence mainline must be rewritten as:

- communication compactness is the current formal headline floor;
- typed-state and consumer sensitivity are mechanism proof;
- memory replay is a separate mechanism proof until integrated into a thick
  headline;
- benchmark reset is required before method strength is judged.

Decision: no new project identity, but a stricter innovation evidence tree.

## Final Category Choice

Chosen category: **C. 主线局部偏了，需要部分重构**

Reason:

- The implementation is not fake and not design-only.
- The core StateBus idea still fits the contest.
- The benchmark/task surface has drifted: it over-relies on clean object/fairness
  gates and static thickness metadata, while under-testing connected multihop,
  dynamic dependency, and memory reuse inside the contest-facing headline.
- This is larger than a patch but not a full abandonment of the mainline.

Category B is too weak because runtime/task structure will likely need some
changes after benchmark reset. Category D is too strong because the current
mechanisms still align with the contest's three required axes.

## Action Tree

### Must Do

1. Preserve current object-purity gates and do not reopen old compatibility bugs
   as the main problem.
2. Treat `contest_repeat_insufficient` as still blocking formal headline, but do
   not rush repeat=10 before the task object is thick enough.
3. Reset `contest_honest_headline_v1` task contract from static S1/S2 fields to
   executable thick tasks.
4. Add row-level output of `case_id`, `case_type`, `thickness_setting`,
   `reasoning_hops_min`, `dependency_depth`, `expected_intermediate_decisions`,
   `required_prior_*`, and `required_plan_semantic_roles`.
5. Build at least one S1 connected multihop family where a second evidence hop
   changes route/tool/action.
6. Build at least one S2 reusable family where prior rejection or scoped route
   changes admissible action and can be verified.
7. Rerun only minimal gates first: pytest, runtime smoke, deterministic
   repeat=1, API repeat=1.
8. Only after the above, run repeat=3 or repeat=10.

### Can Do

1. Refactor monolithic benchmark/report code after the contract is stable.
2. Add stronger route/tool competition inspired by HotpotQA distractors and
   MuSiQue connected hops.
3. Add verifier/end-state checks inspired by tau-bench.
4. Strengthen tool competition using BigTool/Haystack-like selection structure.
5. Keep external text baseline as audit-only until it becomes a real baseline.

### Should Not Do

1. Do not add a new permanent headline pack.
2. Do not re-promote `contest_dual_mode_controlled_v3`.
3. Do not merge memory replay evidence into communication headline.
4. Do not claim API latency/token wins from current repeat=1 evidence.
5. Do not add hidden fields or route shortcuts to make protocol look better.
6. Do not start Docker/openEuler/nsjail/CodeAct work in this review scope.
7. Do not copy LangGraph/Haystack/Mem0 as a framework migration.

### Current Stop Items

1. Stop treating static thickness fields as proof of thick benchmark completion.
2. Stop running heavier repeats on the current object as if repeat count alone
   would solve task thickness.
3. Stop presenting `text_whole_lane` as external pure text.
4. Stop treating support/audit surfaces as headline proof.
5. Stop expanding carrier/handoff variants before the benchmark question is
   settled.

## Deliverable Status

This review produced four detailed analysis documents:

- `docs/analysis/statebus_review_requirement_map_20260618.md`
- `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
- `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
- `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`

No code was changed. That is intentional: the requested work was review,
analysis,定位, and rebuild judgment. The conclusion is not "small patch";
the next implementation should start from the benchmark/task reset described
above.
