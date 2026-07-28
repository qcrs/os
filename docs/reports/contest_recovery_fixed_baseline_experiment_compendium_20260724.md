# StateBus Contest Recovery Fixed Baseline Experiment Compendium

Date: 2026-07-24

## 0. Purpose, Scope, And Reading Rule

This is the single factual ledger for the fixed contest recovery baseline. It
consolidates the useful, canonical E0-E6 experiment results before any new
experiment is chosen. Its purpose is to answer, without relying on memory or
slide wording:

1. What has actually been run and retained?
2. What exact data were measured for each experiment?
3. Which result supports which contest requirement and system claim?
4. Which apparent metrics are only observability fields, are confounded, or
   are missing a fair comparison?
5. What is genuinely worth adding next, rather than repeating a completed
   experiment or expanding scope?

This document contains no new benchmark, test, model request, vLLM operation,
or experiment workload. Every number below is extracted from the audited
artifact tree. A result appears here because it is useful for deciding the
next experiment; it is not automatically a public headline.

The governing interpretation rule is:

```text
canonical run + matched comparison boundary + quality floor
  -> claimable result

raw telemetry field, estimate, retry, or development run alone
  -> diagnostic observation only
```

## 1. Fixed Baseline Identity

| Field | Recorded fact | Consequence |
| --- | --- | --- |
| Recovery branch | `contest/recovery-core` | Current planning branch. |
| Recovery HEAD | `bda17745ecb8a160221efe3b58ca678644dac81a` | The branch is downstream of the recorded experiment commit. |
| Canonical experiment SHA | `a3a5ec836d13c5e9d77811edd25d58d24af227b6` | The SHA recorded by every formal manifest. |
| Worktree identity | `git_dirty=true` | The July 20 package is not a bit-for-bit replay source for the recovery HEAD. |
| Formal artifact root | `/home/qcrs/statebus/runs/contest_evidence_closure_20260720` | Source of the E0-E6 evidence in this document. |
| Runtime environment | `statebus-dev-qcrs`, openEuler 24.03 LTS-SP3 single container | The verified portability boundary is this container only. |
| Role model | local vLLM `qwen3-32b`, temperature 0 | Same recorded model profile in E1. There is no explicit server seed in the fairness manifest. |
| Embedding | `Qwen3-Embedding-0.6B`, local `cuda:0` | Non-text experiments use local GPU embedding, not a remote embedding API. |
| Formal execution order | `serial_execution=true` | Required for the formal timing record, but lane order was not balanced. |

The E4 Runtime freeze additionally records a dirty-worktree content ledger:
`runtime_freeze_sha=e0b04923132f4a139eaa4c2b0ec71b1299d5fd75ccb492d362987a67f5f95afa`,
59 per-file entries, and an unchanged `v2/runtime`, `v2/control`, `v2/state`,
and `v2/memory` surface after the holdout. This is a content snapshot audit,
not a Git commit-range freeze.

The environment records are internally consistent across all seven canonical
roots: the same container/image digest, openEuler/Python build, role model,
runtime-compatibility signature, Git SHA and serial-execution flag are present.
The container maps physical GPU `1` to local device `cuda:0`; this is not a
contradiction between host and container numbering.

| Stage | Wrapper elapsed | Role path / embedding interpretation |
| --- | ---: | --- |
| E0 | 636.284 s | Engineering tests plus deterministic preflight. GPU/model availability is recorded, but the preflight itself does not encode with the local model. |
| E1 | 1,222.892 s | Local vLLM roles; local `Qwen3-Embedding-0.6B` configuration. |
| E2 | 629.535 s | Local vLLM roles; local GPU embedding configuration. |
| E3 | 440.467 s | Local vLLM roles; local GPU embedding used for memory retrieval. |
| E4 | 486.527 s | Local vLLM roles; local GPU embedding used for dense semantic state. |
| E5 | 2,645.539 s | Local vLLM roles; table-oriented suite, so semantic StateRef use is zero. |
| E6 | 862.778 s | Full tests plus deterministic preflight; not a local-GPU embedding benchmark. |

Wrapper elapsed time includes suite setup/collection and is not interchangeable
with the sum of per-case `task_ms`. It is retained for reproducibility and run
planning, not performance comparison.

## 2. Container-Root Audit And Evidence Eligibility

The root-owned paths were read inside `statebus-dev-qcrs` as root. The completed
audit is exhaustive for the artifact root:

| Audit measure | Value |
| --- | ---: |
| Directories indexed | 53,182 |
| Files indexed | 64,472 |
| Reachable bytes | 552,105,404 |
| Parsed JSON/JSONL documents | 61,682 |
| Scan/read errors | 0 |
| JSON parse errors | 0 |
| E0-E6 checksum entries verified | 4,961 / 4,961 |

| Artifact class | Run groups | Files | JSON/JSONL | Treatment in this document |
| --- | ---: | ---: | ---: | --- |
| Canonical E0-E6 | 7 | 4,968 | 4,695 | Formal baseline facts. |
| Known failed/retry/diagnostic roots | 15 | 6,797 | 6,374 | Kept for failure analysis only. |
| Pre-canonical roots | 7 | 1,503 | 1,425 | Historical context only. |
| July 23-24 later/development roots | 27 | 51,203 | 49,188 | Quarantined from baseline aggregation. |

The audit was necessary because the initial host-side read found 36 unreadable,
root-owned `semantic_state_views` directories under later development runs. The
container-root run resolved that visibility issue; it did not promote any later
development result into the fixed baseline.

The canonical subset itself contains 4,068 directories, 54,239,906 bytes and
68 distinct declared schema versions. These values are useful for judging the
depth of the retained evidence, but neither file count nor schema count is an
experiment score. The 552 MB / 61,682-document headline is the full-root audit;
the 54.24 MB / 4,695-document subset is the only source eligible for E0-E6
formal aggregation.

The per-stage volume matters because it shows where detailed case evidence is
actually available. A checksum entry covers every run file except the checksum
file itself, so `files = verified entries + 1` in every row:

| Stage | Directories | Files | JSON/JSONL docs | Bytes | Declared schema types | Seven-slice docs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| E0 | 9 | 22 | 14 | 19,055 | 9 | 7 |
| E1 | 2,040 | 2,727 | 2,636 | 21,841,964 | 52 | 280 |
| E2 | 1,104 | 1,455 | 1,402 | 12,116,010 | 53 | 140 |
| E3 | 162 | 132 | 113 | 1,868,600 | 27 | 42 |
| E4 | 122 | 114 | 90 | 1,251,222 | 25 | 28 |
| E5 | 622 | 496 | 426 | 17,095,943 | 21 | 175 |
| E6 | 9 | 22 | 14 | 47,112 | 9 | 7 |
| Total | 4,068 | 4,968 | 4,695 | 54,239,906 | 68 distinct overall | 679 |

E1 and E2 contain most of the raw runtime depth: 2,270 and 1,212 additional
JSON objects plus 80 and 44 JSONL streams respectively. E5 is physically large
because it retains 25 adaptive model/execution workspaces. E0/E6 are small by
design: their seven slices are placeholders around engineering test gates, not
case-level model traces.

## 3. What Every Materialized Case Preserves

Each canonical E0-E6 root contains the following common envelope:

```text
run_manifest.json        environment.json       fairness_manifest.json
capability_registry.json summary.json           summary.md
pytest.log               console.log            wrapper.log
checksums.sha256
case_reports/            role_requests/         state_consumption/
memory_queries/          memory_consumption/    replay_decisions/
artifact_lineage/        runtime/               workspaces/
```

The seven audit slices are the core evidence surface. Each slice type is meant
to record a different part of the same real execution:

| Slice | Question it answers |
| --- | --- |
| `case_reports` | Did this case pass its quality and system gates? |
| `role_requests` | What was actually rendered to each role? |
| `state_consumption` | Which StateRef did a real consumer open and use? |
| `memory_queries` | Which candidates were visible to the memory gate? |
| `memory_consumption` | Which approved memory reached which real role input? |
| `replay_decisions` | Was a reuse/replay admitted, downgraded, or rejected, and why? |
| `artifact_lineage` | Which verified execution output is the provenance source? |

Across all 57 classified run groups, each of these seven slice categories has
459 documents. That is an audit-coverage number, not a canonical case count.
Within E0-E6, each category has 97 documents: 95 real E1-E5 cases plus one E0
and one E6 engineering-gate placeholder. The canonical slices are complemented
by 3,752 other JSON files and 194 JSONL streams in `runtime/` and `workspaces`;
those raw files retain prompts, plans, state manifests, validator reports,
telemetry and workspace artifacts.

The slice files are not equally dense. This matters when assigning evidence
strength:

| Run | Dense compact role requests | Dense compact state receipts | Dense compact memory queries | Dense compact memory consumption | Raw/workspace supplementation |
| --- | ---: | ---: | ---: | ---: | --- |
| E1 | 0/40 | 0/40 | 0/40 | 0/40 | 160 rendered role requests, 40 artifact audits and 2 unique memory-consumption receipts remain under `runtime/` / `workspaces/`. |
| E2 | 0/20 | 0/20 | 0/20 | 0/20 | 80 rendered role requests, 20 artifact audits and 9 unique memory-consumption receipts remain under `runtime/` / `workspaces/`. |
| E3 | 6/6 | 0/6 | 6/6 | 5/6 | Full query, compatibility, role-input and consumption evidence for the five warm cases. |
| E4 | 4/4 | 3/4 | 4/4 | 0/4 | Full StateRef selections and consumption receipts for all three semantic cases. |
| E5 | 25/25 | 0/25 | 25/25 | 0/25 | Full adaptive role/execution records; memory and semantic-state use are zero in this suite. |

Here, "dense compact" means the top-level slice contains materialized requests,
selections, query results, or consumption records rather than only a metric
roll-up. The compact E1/E2 memory slices are empty, but the workspace audit
files are not: E1 has 40 memory-audit files with two non-empty files and two
unique receipts; E2 has 20 files with seven non-empty files and nine unique
receipts. All 11 receipts identify an Executor consumer and a changed decision
surface. The correct conclusion is therefore not "E1/E2 have counters only";
it is "their evidence is split between compact slices and deeper workspace
logs." E3/E4 still provide the most self-contained top-level receipt packages.

The highest-frequency **canonical E0-E6** schemas show that the evidence is a
state-transition record, not only a final number. Earlier all-root counts were
larger because they included retries and July 23-24 development output; the
table below deliberately excludes those runs:

| Schema | Documents | Evidence role |
| --- | ---: | --- |
| `statebus.telemetry_event.v1` | 4,825 | Fine-grained runtime event trace. |
| `statebus.rendered_role_request.v1` | 659 | Actual role request, not intended request. |
| `statebus.evidence_pruning_hint.v1` | 623 | Why evidence was kept/dropped. |
| `statebus.role_prompt_slice.v1` | 488 | Prompt-visible payload per role. |
| `statebus.semantic_task_plan.v1` | 424 | Typed task/role plan. |
| `statebus.memory_ref.v2` | 296 | Memory reference and provenance. |
| `statebus.runtime_compatibility.v1` | 253 | Memory/state compatibility decision surface. |
| `statebus.artifact_validator_report.v1` | 248 | Verified execution-output gate. |
| `statebus.canonical_task_spec.v1` | 239 | Frozen task contract. |
| `statebus.memory_match_result.v1` | 196 | Retrieval and match decision. |
| `statebus.memory_rerank_result.v1` | 192 | Ranked/selected memory decision. |
| `statebus.codeact_plan.v1` | 184 | Constrained CodeAct plan. |
| `statebus.memory_candidate_pool.v1` | 182 | Candidate visibility before compatibility. |
| `statebus.memory_commit.v2` | 179 | Verified memory commit decision. |
| `statebus.structured_embedding.v1` | 146 | Typed embedding object. |

The machine report retains all 68 schema types and, for E1/E2, all 287
numeric case-report fields rather than only the metrics printed in this
document. That exhaustive catalog is intentionally machine-readable: it keeps
diagnostic timers, counters, sentinels and zero-only fields available for later
questions without turning every telemetry field into a claim.

Therefore the usable causal chain is:

```text
CanonicalTaskSpec
  -> SemanticTaskPlan / rendered role requests
  -> structured embedding or dense semantic StateRef
  -> actual state consumption receipt
  -> verified ExecutionArtifactRef
  -> MemoryRef compatibility / consume decision
  -> observed behavioral effect or recomputation
```

### 3.1 Configuration, Ledger Presence And Runtime Occurrence Are Different

Several case-report fields describe a configured backend or an always-written
ledger object. They must not be read as proof that the corresponding mechanism
was exercised:

| Field or object | What the baseline records | Actual occurrence boundary |
| --- | --- | --- |
| `state_pool_shared_memory_mode_count` | Non-zero in every E1 lane | Semantic publish/transfer occurs only in L2/L3: 9 each; L0/L1 remain zero. |
| E1 `memory_ref_count` / `memory_commit_count` | Present in every lane: 10 refs and 20 commit records per lane | Query/compatibility/consumption occurs only in L3: 10 queries and 2 consumptions. |
| E2 memory refs/commits | Ledger objects exist in all 20 L3 rounds | Only seven rounds consume memory; nine receipt records cross the gate. |
| Artifact `memory_commit_path` | Present for all 40 E1 and 20 E2 artifact audits | It proves that a verified artifact has an eligible promotion path, not that a later task reused it. |
| `gc_issue_count` | One emitted GC/lifecycle event is recorded per E1/E2 case | The name is historical telemetry vocabulary; it is not a count of GC failures. Published and released semantic bytes match. |
| Prefix estimates/service deltas | Non-zero in text and structured lanes | No cache-on/off isolation, TTFT campaign or clean service-state boundary exists. |
| Logit fields | Sentinel values are retained | `logit_state_transfer_count=0` and sequence length is zero; no LogitState feature occurred. |

This distinction is a reusable audit rule:

```text
configured or persisted
  != candidate visible
  != compatibility approved
  != consumed
  != behavior changed
  != work saved
```

## 4. Contest Requirement To Existing Experiment Map

| Contest requirement | Existing evidence | Status | Exact boundary |
| --- | --- | --- | --- |
| At least 3 collaborating roles | Four roles: Planner, Retriever, Executor, Summarizer; E1/E5 plus E0/E6 | Covered | Not a claim that every role is a separate remote process. |
| At least 3 task classes | E5 has five formal task families and ten operation labels | Covered | E1/E2 use two continuous families; the broader five-family result comes from E5. |
| Text and structured modes on the same tasks | E1 L0-L3 matched matrix | Covered | L0 is an internal matched pure-text lane, not an external competitor. |
| Structured action/parameter/result/capability control | E1 Protobuf lane, six-capability registry, 160 recorded ACKs, E0/E6 gates | Covered | Strong for control/wire efficiency and inspectability; it is a local UDS/subprocess protocol, not a distributed service-discovery benchmark. |
| Non-text intermediate state | E1 StateRef telemetry plus E4 cross-PID holdout | Covered mechanism | No transport-only text-vs-vector ablation yet. |
| Shared memory creation, retrieval and reuse | E1/E2 natural chains and E3 truth funnel | Covered mechanism/safety | Broad speedup is not yet established. |
| Required memory metadata | E3 commit registry: 7/7 have ID, source Agent, creation time, theme and summary; all also have tags and artifact/embedding refs | Covered | Seven includes the deliberately incompatible fixture; six are canonical case commits. |
| Keyword, tag or semantic retrieval | E3: 15/15 formal matches are `hybrid_rrf:vector`; E6 code/tests cover SQLite FTS keyword, tag and FAISS/cosine paths | Covered | The requirement is disjunctive (`or`): formal semantic retrieval satisfies it. Do not overstate task-level keyword/tag coverage or add an experiment merely to exercise all three. |
| Two related continuous tasks | E2: financial and operating families, 10 rounds each | Covered | L3-only stability run, not a four-lane comparison. |
| At least 10 stable rounds | E2 20/20 across two 10-round chains | Covered | Does not prove every L0-L3 layer over 10 rounds. |
| Message, token/character, state-size, latency, memory-reuse metrics | E1/E2 telemetry and E3/E4 audits | Metrics covered; comparative latency incomplete | Message/token/state sizes and decomposed memory rates are derivable now. Formal timing exists but is not balanced enough for a latency-superiority claim. |
| CodeAct encouraged | E5: 18 verified bounded-Python executions | Covered support | No isolated CodeAct performance comparator. |
| openEuler delivery | Fresh E0-E6 in one openEuler container | Covered at container scope | No VM, cross-machine, or arbitrary Linux claim. |
| Source, design, deployment, report and demo video | Repository contains source and extensive design/deployment/report material; no video file was found | Delivery incomplete | Video is a submission artifact, not another model benchmark. Its absence should remain visible in the final checklist. |

### 4.1 Contest Scorecard, Not A Generic Systems Scorecard

The contest gives explicit weights. The experiment package should therefore
spend effort in proportion to these five rows rather than to whichever runtime
field is easiest to measure:

| Scoring item | Weight | Best existing evidence | Present confidence | Remaining scoring risk |
| --- | ---: | --- | --- | --- |
| Communication efficiency | 25 | E1 L0/L3: total tokens -47.40%, wire -64.85%, equal 10/10 quality; L0/L1 isolates control bytes -83.05% | Strong for full-stack token/wire; strong for typed-control wire | Typed control alone increases tokens 2.70%; do not attribute the full-stack token win to Protobuf. |
| Non-text state innovation | 20 | E4: nine receipt-backed numeric selections across three cases, nine distinct consumer PIDs, changed decision surfaces and release closure | Strong mechanism/innovation evidence | No same-selection carrier comparator, no transport latency or crash-path campaign. |
| Memory reuse effect | 20 | E3 full truth funnel and one skipped LLM call; E2 natural 20-round behavior and receipt timeline | Strong safety/use evidence; bounded benefit | Query-normalized hit/use/effect rates can already be derived, but broad net-value evidence is too small for a general acceleration claim. |
| System completeness | 20 | Four model roles, dual mode, E2 20/20, E5 25/25, E0/E6, openEuler container | Strong | E5 is capability coverage, not a 25-case failure matrix; no demo video is present in the repository. |
| Experiment validation | 15 | Checksummed E0-E6, fairness manifest, per-case audits, preserved failed runs | Strong reproducibility; mixed causal coverage | Latency order is not balanced, server seeds are null, and C/N/M do not all reach the same evidence level. |

This scorecard changes the priority order. A balanced latency result and a
contest-ready memory-rate/net-value table directly reduce scoring risk. Prefix,
LogitState, a new dataset, or a CodeAct-vs-DSL speed race do not.

### 4.2 Why These Baseline Experiments Have Different Jobs

Earlier planning and PPT work is used here only as an interpretation framework,
not as a source of additional experiment numbers. The fixed baseline remains
E0-E6 only. Its experiments are deliberately complementary rather than seven
repetitions of one benchmark:

| Question from the system story | Why this requires its own experiment shape | Baseline experiment that answers it |
| --- | --- | --- |
| Are stable control semantics cheaper and inspectable than text relay? | The message count and workflow must stay fixed, otherwise lower bytes could simply mean less collaboration. | E1 L0/L1, with identical 50 logical messages and equal quality. |
| Is the non-text object really used by another process? | A StateRef being published is not enough; a physical consumer must read numeric bytes, select IDs, alter hydration and release the object. | E4, with distinct PIDs, cosine top-k, selected IDs, surface hashes and release receipts. |
| Does the system reduce prompt burden in the full workflow? | This is an integrated effect of semantic selection plus state/hydration, so it needs a matched multi-role matrix and not merely a shared-memory microtest. | E1 L1/L2 and L0/L3 token/prompt-surface tables. |
| Is memory actual reuse rather than approximate retrieval? | Candidate similarity, compatibility, role input, effect and saved work are different facts and need a negative case. | E3 truth funnel and incompatible fixture; E1/E2 natural continuous use. |
| Does the whole system keep working over time and task variety? | A one-off causal comparison cannot prove continuous stability or capability coverage. | E2 two 10-round chains, E5 25-case registry, E0/E6 gates. |

The prior design work also supplies the following four-level reading rule for
the already-collected baseline data:

```text
implemented -> actually consumed -> downstream effect -> quality-preserving net value
```

| Level | E0-E6 evidence that reaches it | What must not be inferred yet |
| --- | --- | --- |
| Implemented | E0/E6 tests; schemas, manifests and registries | A feature exists in code, therefore it helped a task. |
| Actually consumed | E4 StateRef receipts; E3 memory-consumption records | A published/reflected object necessarily changed downstream work. |
| Downstream effect | E4 selected IDs/surface changes; E1/E2/E3 memory behavioral effects | The effect is automatically a quality, token or latency win. |
| Net value | E1 L0/L3 quality-preserving token/wire result; E3's one skipped LLM call | Every component, task family or workload has the same net benefit. |

This is why the document keeps `candidate`, `compatible`, `consumed`, `effect`,
`skipped_step`, and `skipped_llm_call` separate. It is the central explanatory
logic behind the baseline, not an additional experiment.

### 4.3 Five Evidence Levels For Every Reusable Asset

The complete audit is useful only if unlike evidence is not collapsed. Every
fact discovered in the baseline now belongs to one of five levels:

| Evidence level | What belongs here | Examples from this baseline | Permitted use |
| --- | --- | --- | --- |
| A. Direct formal measurement | Canonical matched result or receipt with a declared gate | E1 token/wire/quality, E3 consumption/effect, E4 cross-PID receipts, E2 20/20, E5 25/25 | Public result within the stated comparison boundary. |
| B. Derived from canonical logs | Recomputed rate/distribution over formal records | E1 paired direction counts, E2 query-normalized rates, E3 15/16 compatibility, E5 family long tail | Public supporting analysis if formula and denominator are shown. |
| C. Engineering/code coverage | Behavior implemented and exercised by E6 tests, but not a task-level performance campaign | State corruption/expiry rejection, owner-only unlink, FTS/tag lookup, FAISS/cosine equivalence, replay corruption, UDS reject paths | Completeness/safety appendix; never a task-performance claim. |
| D. Formal experiment still required | A desired causal or comparative claim lacks a fair lane | Balanced latency, memory OFF/use attribution, optional same-selection carrier comparison | Cannot be claimed until the specified experiment exists. |
| E. Delivery gap | Required artifact rather than a mechanism benchmark | Demo video; clean source identity for any new formal run | Must be closed for submission, but should not trigger a new dataset or architecture project. |

The exhaustive 287-field catalogs and all 68 canonical schema types are retained
because a future question may move a field from diagnostic to decision-useful.
They do not move level automatically: a counter named `saved`, `replay`,
`prefix`, or `hit` still needs its semantic and comparison gate.

## 5. Canonical Experiment Dashboard

| ID | Canonical root | Design | Formal outcome | Main value | What it is not |
| --- | --- | --- | --- | --- | --- |
| E0 | `e0_focused_20260720_142422` | Focused tests + deterministic preflight | 135 passed; preflight OK | Engineering gate | Performance result. |
| E1 | `e1_causal_serial_20260720_150801` | 2 families x 5 rounds x L0-L3 | 40/40; each lane 10/10; fairness valid | Primary matched causal matrix | Transport-only or balanced-latency study. |
| E2 | `e2_stress_serial_20260720_152924` | 2 L3 families x 10 rounds | 20/20 | Continuous stability and natural memory behavior | Second L0-L3 comparison. |
| E3 | `e3_adaptive_memory_final_20260720_160244` | 5 financial cases + 1 incompatible-memory fixture | 6/6 | Memory truth funnel and fail-closed recompute | Broad acceleration proof. |
| E4 | `e4_semantic_holdout_final4_20260720_175430` | 3 semantic + 1 table holdout | 4/4 | Cross-PID numerical state and lifecycle closure | End-to-end latency comparison. |
| E5 | `e5_adaptive_final_20260720_190107` | Full 25-case capability registry | 25/25 | Adaptive registry and CodeAct/DSL coverage | CodeAct speed or accuracy advantage over a fixed alternative. |
| E6 | `e6_full_final_20260720_201043` | Full `tests/v2` + preflight | 558 passed, 100 warnings; preflight OK | Regression gate | Zero-warning or performance result. |

## 6. E1: The Primary Matched L0-L3 Matrix

### 6.1 Design And Fairness Boundary

E1 uses two repo-local offline financial/operating-analysis families, five
continuous rounds each, and four lanes. That is `2 x 5 x 4 = 40` serial
executions, with 10 matched cases in every lane.

| Lane | Enabled mechanism | Control carrier | Semantic state | Memory/replay |
| --- | --- | --- | --- | --- |
| L0 | Pure text collaboration | `utf8_text` | Off | Off |
| L1 | Typed control only | Protobuf | Off | Off |
| L2 | Typed control + semantic selection/pruning + StateRef | Protobuf | Shared-memory StateRef | Off |
| L3 | L2 + compatibility-gated memory/replay | Protobuf | Shared-memory StateRef | On |

The fairness manifest records `comparison_valid=true` and
`unexpected_difference_count=0`. It holds task contracts, source content,
prior facts, role graph, message boundary, model configuration, executor
validator, capability surface, external-gold visibility and subprocess topology
constant. All four lanes use `driver_uds_executor_subprocess`; only the carrier
and the semantic-state/memory feature flags are allowed to vary.

### 6.2 Full Communication, Token, State, Quality And Timing Record

All counts below aggregate the 10 matched cases in each lane.

| Metric | L0 | L1 | L2 | L3 |
| --- | ---: | ---: | ---: | ---: |
| Cases / quality pass | 10 / 10 | 10 / 10 | 10 / 10 | 10 / 10 |
| Agent messages | 50 | 50 | 50 | 50 |
| Control messages | 40 | 40 | 40 | 40 |
| Text frames | 50 | 0 | 0 | 0 |
| Protobuf frames | 0 | 50 | 50 | 50 |
| Control bytes | 25,196 | 4,270 | 4,507 | 5,357 |
| Total wire bytes | 36,069 | 11,200 | 11,827 | 12,677 |
| LLM prompt bytes | 130,676 | 126,406 | 56,326 | 57,738 |
| Raw evidence bytes seen by LLM | 73,266 | 73,266 | 11,693 | 11,687 |
| Prompt-visible bytes | 75,926 | 75,926 | 14,353 | 15,847 |
| Selected evidence bytes | 6,514 | 6,517 | 12,681 | 12,667 |
| Prompt tokens | 29,876 | 30,737 | 13,599 | 13,885 |
| Completion tokens | 4,098 | 4,154 | 4,140 | 3,985 |
| Total LLM tokens | 33,974 | 34,891 | 17,739 | 17,870 |
| LLM calls | 40 | 40 | 40 | 40 |
| Semantic StateRef count / transfer count | 0 / 0 | 0 / 0 | 9 / 9 | 9 / 9 |
| Shared-memory published bytes | 0 | 0 | 270,336 | 270,336 |
| Released StateRef bytes | 0 | 0 | 270,336 | 270,336 |
| Memory queries | 0 | 0 | 0 | 10 |
| Compatible / consumed memory | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 2 |
| Behavioral effects / validated replay | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 2 |
| Strict skipped steps / skipped LLM calls | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 0 |
| Aggregate `task_ms` | 315,678.327 | 302,063.154 | 305,236.727 | 295,728.340 |
| Aggregate `llm_wall_ms` | 288,725.158 | 280,225.653 | 275,277.555 | 265,573.954 |
| Descriptive p50 / p95 seconds | 31.953 / 33.440 | 32.355 / 35.589 | 32.391 / 36.336 | 29.135 / 35.212 |

The message count is intentionally constant. E1 proves that the same 50
logical agent messages can move from 50 text frames to 50 Protobuf frames
without changing the task/role topology. Lower bytes are therefore not caused
by sending fewer messages.

The control-plane evidence also includes 40 ACKs per lane (160 total), one
heartbeat/lifecycle record per case, six typed capability descriptors, and 160
gold-hidden rendered-role-request audits with zero violations. Every case
records four workflow steps and four completed steps. These facts close the
contest's handshake/capability/protocol-mapping requirement more directly than
the byte totals alone; they are protocol-completeness evidence, not extra
messages to subtract from the benchmark.

`raw_evidence_bytes_seen_by_llm`, `selected_evidence_bytes`, and
`prompt_visible_total_bytes` are distinct telemetry definitions. The first is
raw corpus material visible to LLM roles; the second is a selected/hydrated
evidence-object measure; the third is the rendered prompt-visible surface.
They must not be subtracted from one another as if they were one partition.

The stage timings are retained for latency diagnosis. They overlap with outer
timers and must not be summed into `task_ms` or used as a separate end-to-end
clock:

| E1 lane | Control-plane exchange ms | Persist/reload ms | Runtime-driver ms | CodeAct execution ms | Workspace input ms | Telemetry emit ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 8,807.767 | 413.328 | 9,479.014 | 9,374.324 | 70.719 | 18.623 |
| L1 | 8,581.649 | 385.105 | 9,174.276 | 9,216.410 | 67.483 | 17.928 |
| L2 | 8,434.841 | 478.902 | 9,150.996 | 9,178.439 | 165.609 | 22.984 |
| L3 | 8,520.296 | 440.300 | 9,183.277 | 9,197.122 | 169.385 | 21.043 |

This diagnostic confirms that StateRef and memory auditing introduce observable
workspace/persistence work. It is exactly why the next latency study must
separate LLM time, transport time, StatePool lifecycle time, and persistence
time under a balanced serial schedule.

### 6.3 Direct Whole-Stack Result: L0 To L3

This is the comparison that must appear in the baseline summary. It is a
whole-stack result, not a per-component attribution.

| Metric | L0 | L3 | Absolute delta | Relative delta |
| --- | ---: | ---: | ---: | ---: |
| Control bytes | 25,196 | 5,357 | -19,839 | -78.74% |
| Total wire bytes | 36,069 | 12,677 | -23,392 | -64.85% |
| LLM prompt bytes | 130,676 | 57,738 | -72,938 | -55.82% |
| Raw evidence seen by LLM | 73,266 | 11,687 | -61,579 | -84.05% |
| Prompt-visible bytes | 75,926 | 15,847 | -60,079 | -79.13% |
| Prompt tokens | 29,876 | 13,885 | -15,991 | -53.52% |
| Completion tokens | 4,098 | 3,985 | -113 | -2.76% |
| Total LLM tokens | 33,974 | 17,870 | -16,104 | -47.40% |
| LLM calls | 40 | 40 | 0 | 0.00% |
| Aggregate `task_ms` | 315,678.327 | 295,728.340 | -19,949.987 | -6.32% descriptive only |
| Aggregate `llm_wall_ms` | 288,725.158 | 265,573.954 | -23,151.203 | -8.02% descriptive only |
| Quality | 10/10 | 10/10 | 0 | Quality floor held |

Per matched case, total LLM consumption is `3,397.4 -> 1,787.0` tokens: about
1,610.4 fewer total tokens per case. The correct whole-system claim is:

> Under the E1 matched task, model, role topology, validator and serial
> subprocess boundary, L3 retains the 10/10 quality floor while using 47.40%
> fewer total LLM tokens and 64.85% fewer wire bytes than the L0 pure-text
> collaboration lane.

The correct limitation is equally important: E1 has fixed lane ordering and no
balanced reverse/random serial repetitions. The timing rows are retained as
descriptive measurements, not as a formal end-to-end latency superiority
claim.

### 6.4 Adjacent Attribution: Where The Token Change Comes From

| Adjacent comparison | Control/wire result | Prompt/token result | Interpretation |
| --- | --- | --- | --- |
| L0 -> L1 | Control bytes -83.05%; wire bytes -68.95% | Prompt tokens +2.88%; total tokens +2.70%; prompt-visible bytes unchanged | Typed Protobuf removes control/wire overhead and enables inspectable contracts. It does **not** save LLM tokens by itself. |
| L1 -> L2 | Control bytes +5.55%; wire bytes +5.60% | Prompt bytes -55.44%; prompt tokens -55.76%; total tokens -49.16%; prompt-visible bytes -81.10% | The large token reduction comes from semantic selection/pruning plus StateRef-driven local hydration. These two mechanisms are jointly enabled, so this is not a transport-only result. |
| L2 -> L3 | Control bytes +18.86%; wire bytes +7.19% | Prompt tokens +2.10%; total tokens +0.74%; prompt-visible bytes +10.41% | Compatibility checks, memory metadata and consumption add small overhead. The present L3 value is verified reuse, not a generic token-saving layer. |

This resolves an otherwise misleading story: the L0->L3 token result is strong,
but it must not be restated as "Protobuf saved 47.40% tokens" or "memory saved
47.40% tokens." The observed main contributor is the L1->L2 semantic evidence
selection/hydration path.

The retrieval cardinality itself is held stable across lanes: each lane records
862 candidate occurrences, 192 selected occurrences, 64 pruning keeps, 40
drops and the same 4,669-token pruning estimate. What changes at L2 is the
state/hydration and downstream prompt surface, not the number of top-level
retrieval candidates. This makes the actual prompt/token measurements more
important than the shared pruning estimate and prevents that estimate from
being double-counted as another saving.

### 6.5 Paired-Case Distribution: Efficiency Is Stable, Latency Is Not

Aggregate totals hide whether a result is broad or carried by one outlier. The
ten exact L0/L3 task pairs give a much sharper reading:

| Paired metric | L3 lower | Equal | L3 higher | Correct interpretation |
| --- | ---: | ---: | ---: | --- |
| Total LLM tokens | 10/10 | 0 | 0 | The token result is directionally consistent across every task. |
| Prompt tokens | 10/10 | 0 | 0 | Prompt reduction is not one-family-only. |
| Total wire bytes | 10/10 | 0 | 0 | The wire result is also directionally consistent. |
| Control bytes | 10/10 | 0 | 0 | Typed/ref control stays smaller than the text lane in every pair. |
| Prompt-visible bytes | 9/10 | 1 | 0 | One low-evidence case is equal; none is worse. |
| `task_ms` | 6/10 | 0 | 4/10 | No universal end-to-end latency win. |
| `llm_wall_ms` | 6/10 | 0 | 4/10 | The aggregate LLM-wall reduction also crosses over by task. |

The paired total-token reduction ranges from 17.58% to 63.07%; the paired
task-time change ranges from -27.49% to +15.59%. This is stronger evidence for
the token/wire headline and weaker evidence for the timing headline than the
aggregate mean alone suggests.

### 6.6 Workload Crossover: The Aggregate Latency Number Is Misleading

The two E1 families move in opposite directions from L0 to L3:

| Family, five matched tasks | `task_ms` L0 -> L3 | Delta | `llm_wall_ms` L0 -> L3 | Delta | Total tokens L0 -> L3 | Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Operating metrics | 159,896.378 -> 131,550.601 | -17.73% | 143,700.079 -> 116,735.175 | -18.76% | 19,935 -> 8,258 | -58.58% |
| Financial reports | 155,781.949 -> 164,177.739 | +5.39% | 145,025.079 -> 148,838.779 | +2.63% | 14,039 -> 9,612 | -31.53% |

All five operating cases are faster in L3. Four of five financial cases are
slower, even though all five still use fewer tokens. The likely presentation
story is a workload crossover: larger prompt/evidence reduction can amortize
StateRef, validation and memory overhead, while shorter tasks may not. The
current run does not locate a statistically defensible break-even point, so a
future timing experiment should model latency against removed prompt tokens or
raw-evidence bytes rather than search for one universal percentage.

### 6.7 Role-Level Attribution: The Reduction Is Downstream-Facing

The aggregate role prompt bytes show where L1->L2 actually changes the
workflow:

| Lane | Planner | Retriever | Executor | Summarizer |
| --- | ---: | ---: | ---: | ---: |
| L0 | 11,967 | 42,868 | 41,989 | 33,852 |
| L1 | 12,205 | 40,731 | 39,023 | 34,447 |
| L2 | 12,205 | 17,937 | 10,972 | 15,212 |
| L3 | 12,205 | 18,288 | 11,504 | 15,741 |

L1->L2 leaves Planner unchanged, while Retriever falls 55.96%, Executor
71.88%, and Summarizer 55.84%. This matches the mechanism: semantic selection
changes evidence hydration after planning, not the task contract itself.

L2->L3 then adds 500 bytes of memory input to each of Retriever, Executor and
Summarizer in the two consumed cases. That 1,500-byte role-level addition
almost exactly explains the 1,494-byte aggregate prompt-visible increase. The
memory layer is therefore observable overhead plus verified benefit; it is not
free token compression.

### 6.8 Control Bytes, Data-Plane Bytes And Prompt Bytes Are Different Budgets

The non-text state must not be hidden from byte accounting:

| Lane | Wire bytes | Shared-memory bytes published | Wire + published state, descriptive | Prompt-visible bytes |
| --- | ---: | ---: | ---: | ---: |
| L0 | 36,069 | 0 | 36,069 | 75,926 |
| L1 | 11,200 | 0 | 11,200 | 75,926 |
| L2 | 11,827 | 270,336 | 282,163 | 14,353 |
| L3 | 12,677 | 270,336 | 283,013 | 15,847 |

The `wire + published state` column is deliberately descriptive: shared-memory
publication is not network serialization and its bytes must not be treated as
equivalent to prompt or UDS bytes. It nevertheless proves that StateBus does
not reduce every physical byte count. It keeps a larger float32 object
out-of-band, sends a small Ref over the control plane, and exposes only selected
evidence to downstream prompts. The defensible benefit is lower control/wire
and prompt burden plus typed object identity, not universally lower memory
traffic.

The per-message control result is also concrete: L0 uses 629.9 control bytes
per control message, L1 106.75, L2 112.68, and L3 133.93. The L3 increase over
L1 is the visible cost of state/memory metadata.

### 6.9 Planner Recovery Observed Inside The Passing Matrix

Two of the 40 E1 cases record a semantic-plan validation error and use a
runtime retrieval-objective fallback: financial R1 in L0 and operating R4 in
L3. Both retain the quality floor, while `runtime_fallback_count`, StatePool
fallback and sandbox fallback remain zero for all 40 cases.

This is useful robustness evidence, but it also exposes a reproducibility
limit. Role temperatures are zero while all recorded role seeds are `null`, so
the model-generated plan is not guaranteed bit-identical across lanes. A fair
latency rerun must report plan/fallback status per pair and either stratify or
exclude fallback-mismatched pairs; it cannot silently treat model outputs as
identical merely because the static fairness manifest passed.

### 6.10 Typed Plan Consumption And Verified Artifact Promotion

The structured-control story is stronger than a Protobuf byte count. The raw
workspace records show whether Planner output became an effective retrieval
objective and whether the downstream Retriever consumed the same typed plan:

| E1 lane | Model plan valid / behavioral effect | Runtime objective fallback | Retriever consumed-hash matches | Completed workflow steps |
| --- | ---: | ---: | ---: | ---: |
| L0 | 9 / 9 | 1 | 40 | 40/40 |
| L1 | 10 / 10 | 0 | 40 | 40/40 |
| L2 | 10 / 10 | 0 | 40 | 40/40 |
| L3 | 9 / 9 | 1 | 40 | 40/40 |

There are four Retriever hash-match observations per case. In the two plan
validation failures, the model-generated objective is absent but the runtime
creates an effective fallback objective, so all cases still complete. This is
evidence of typed-plan consumption plus fail-closed recovery, not merely plan
serialization.

The next state-promotion boundary is also fully materialized:

| E1 artifact-promotion fact | Result |
| --- | ---: |
| Workspace artifact audits | 40 |
| Verified settlement / verification state | 40 / 40 |
| Quality-floor commit gate | 40/40 |
| Replay-ready / lineage-complete | 40 / 40 |
| Input-validator / validator references | 40 / 80 |
| Memory-commit paths | 40 |
| Artifact bytes, total / mean / p95 | 111,590 / 2,789.75 / 3,306.15 B |
| State storage kind | 18 shared-memory / 22 disabled |

The 18 shared-memory artifact audits correspond to the 18 semantic E1 cases
(nine each in L2/L3); the other 22 cases correctly record the state carrier as
disabled. The 40 artifacts contain 38 unique blob hashes, which is useful
deduplication evidence but must not be converted into two replay events without
a consumption receipt.

E1 also retains 600 workspace files, 1,232 telemetry-event writes and 992
telemetry-fact writes. These counts establish observability depth and explain
some mechanism overhead; they are not performance scores.

### 6.11 E1 Memory Detail: Strict Events Versus Historical Counters

| E1 L3 field | Count | Allowed reading |
| --- | ---: | --- |
| Hybrid memory queries | 10 | Ten actual gate invocations. |
| Candidates | 15 | Candidate visibility, not a hit. |
| Compatible / policy-approved / consumed | 2 / 2 / 2 | Two memories crossed the full gate and reached real consumers. |
| Behavioral effects | 2 | Two actual behavior changes. |
| Validated replay | 2 | Both are financial R2/R4. |
| Exact replay / answer restoration replay | 0 / 0 | Must not claim exact restoration. |
| Strict skipped steps / skipped LLM calls | 2 / 0 | Two steps skipped, but no model call was removed in E1. |
| History-backed artifact reuse | 13 | Historical linkage only; not 13 replay events. |
| `history_reuse_gain` / `history_step_reduction_count` | 5 / 7 | Telemetry counters that must not replace strict replay counts. |
| Incompatible candidates rejected | 13 | Fail-closed behavior is active. |

The two family-level readings are deliberately different:

| E1 L3 family | History artifact reuse | Validated replay | Replay headline eligibility |
| --- | ---: | ---: | --- |
| Financial reports | 4 | 2, rounds R2/R4 | Yes, `replay_admissible` |
| Operating metrics | 9 | 0 | No, `history_backed_only` |

The deeper workspace logs close the receipt detail that is absent from the
compact top-level slices:

| E1 receipt fact | Result |
| --- | ---: |
| Memory audit files / non-empty files | 40 / 2 |
| Unique receipts / unique consumed memory IDs | 2 / 1 |
| Consumer role | Executor 2/2 |
| Replay class / verdict | `validated_replay` 2 / `degraded` 2 |
| Behavioral effect | `recipe_reused_current_input_recomputed` 2 |
| Decision surface changed | 2/2 |
| Recipe recomputed | 2/2 |
| Skipped generation steps / LLM calls | 2 / 0 |

The receipts are financial R2 and R4, both consuming
`mem-current-formal-financial-001`. They prove a real consumer and a changed
decision surface, while also showing why "replay" is intentionally bounded:
the recipe is reused, current input is recomputed, and no model call is saved.

### 6.12 Prefix And Logit Observability Fields Are Not E1 Features

The raw telemetry contains prefix estimates and vLLM service-counter deltas.
They are kept here so they cannot be rediscovered later and accidentally
promoted into a claim:

| E1 lane | Neural prefix estimate: saved tokens | Estimated cache hits / queries | Observed vLLM hit delta / query delta | LogitState transfer / sequence length |
| --- | ---: | ---: | ---: | ---: |
| L0 | 1,407 | 9 / 18 | 211 / 1,852 | 0 / 0 |
| L1 | 1,407 | 9 / 18 | 816 / 1,907 | 0 / 0 |
| L2 | 1,647 | 9 / 18 | 423 / 839 | 0 / 0 |
| L3 | 1,644 | 9 / 18 | 717 / 856 | 0 / 0 |

L3's collection summary additionally has `kv_corpus_level_prefill_saved_tokens_estimate=1128`,
`kv_corpus_prefix_hash_reuse_count=6`, `kv_corpus_prefix_hash_unique_count=4`,
and `kv_engine_local_prefill_saved_tokens_estimate=1644`.

These fields cannot be used as E1 Prefix-reuse evidence: estimates also appear
in L0/L1, service counters are influenced by the shared vLLM process and its
lifetime state, and no matched cache-on/cache-off protocol or TTFT measurement
was run. LogitState has zero transfers and zero sequence length. Both remain
outside the fixed-baseline feature claim.

## 7. E2: Two 10-Round L3 Continuous Chains

### 7.1 Design And Aggregate Record

E2 is a stability and natural-use experiment, not another L0-L3 matrix. It
runs L3 only over two related families for ten rounds each:

| Measure | E2 L3 aggregate |
| --- | ---: |
| Families / rounds / cases | 2 / 20 / 20 |
| Quality | Financial 10/10; operating 10/10; total 20/20 |
| Agent messages / control messages | 100 / 80 |
| Protobuf frames | 100 |
| Control / total wire bytes | 10,714 / 25,354 |
| Prompt / completion / total tokens | 28,619 / 8,237 / 36,856 |
| Prompt-visible bytes | 33,091 |
| LLM calls | 80 |
| Aggregate `task_ms` / `llm_wall_ms` | 626,072.332 / 559,768.313 |
| Semantic StateRefs / transfers | 18 / 18 |
| Shared-memory bytes published / released | 540,672 / 540,672 |
| Financial descriptive p50 / p95 seconds | 33.596 / 38.430 |
| Operating descriptive p50 / p95 seconds | 28.676 / 35.805 |

No cross-layer efficiency conclusion follows from this table because E2 has no
L0, L1 or L2 lane. It establishes that the full L3 chain completes 20 related
rounds while preserving state lifecycle closure.

The E2 per-family stage profiles are useful when designing a latency study, but
are not cross-family or cross-layer performance comparisons. Timers overlap and
should not be summed:

| E2 L3 family, 10 rounds each | Control-plane exchange ms | Persist/reload ms | Runtime-driver ms | CodeAct execution ms | Dominant persist bundle-write ms | Workspace files |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Operating metrics | 8,676.865 | 450.493 | 9,366.622 | 9,681.306 | 321.318 | 150 |
| Financial reports | 8,690.559 | 475.217 | 9,384.903 | 9,699.352 | 344.504 | 150 |

The two profiles both identify control-plane exchange and CodeAct/runtime work
as the dominant recorded stage buckets, while integrity-aware persistence is a
smaller but visible component. This is diagnostic evidence for a future fair
latency decomposition, not a claim that any single mechanism caused the
observed p50/p95 values.

The continuous run also closes the typed-plan and artifact-promotion chain in
every round:

| E2 evidence surface | Operating, 10 rounds | Financial, 10 rounds | Total |
| --- | ---: | ---: | ---: |
| Valid model plan / behavioral effect | 10 / 10 | 10 / 10 | 20 / 20 |
| Runtime objective fallback | 0 | 0 | 0 |
| Retriever consumed-hash matches | 40 | 40 | 80 |
| Completed workflow steps | 40/40 | 40/40 | 80/80 |
| Workspace files | 150 | 150 | 300 |
| Telemetry event / fact writes | 322 / 262 | 330 / 270 | 652 / 532 |

All 20 artifact audits are verified, quality-floor committed, replay-ready and
lineage-complete. They retain 20 input-validator references, 40 validator
references and 20 memory-commit paths. Artifact storage is 18 shared-memory / 2
disabled, artifact bytes total 56,377, and all 20 blob hashes are unique. This
is the strongest continuous evidence for the middle
`ExecutionArtifactRef -> MemoryRef` promotion boundary.

### 7.2 Memory Funnel And Long-Horizon Truth Boundary

| E2 L3 field | Count | Meaning |
| --- | ---: | --- |
| Memory queries | 20 | One gate invocation per task round. |
| Candidates | 48 | Candidate pool only. |
| Compatible / approved / consumed / effect | 9 / 9 / 9 / 9 | Nine memories passed the full path and had observed effects. |
| Assist | 7 | Assist is not replay. |
| Validated replay | 2 | Financial R2/R4 only. |
| Exact replay / answer restoration | 0 / 0 | Not supported. |
| Strict skipped steps / skipped LLM calls | 2 / 0 | No broad LLM-call saving. |
| History-backed artifact reuse | 44 | Do not label as 44 replays. |
| `history_reuse_gain` / `history_step_reduction_count` | 9 / 14 | Historical telemetry, not strict saved-work counts. |
| Rejected incompatible candidates | 39 | Fail-closed rejection remains active. |

Family-level history counts further show why aggregation must be conservative:

| E2 family | History artifact reuse | Historical reuse gain / step-reduction counter | Validated replay | Headline scope |
| --- | ---: | ---: | ---: | --- |
| Financial reports | 16 | 7 / 10 | 2, R2/R4 | `replay_admissible` |
| Operating metrics | 28 | 2 / 4 | 0 | `history_backed_only` |

The deeper workspace evidence contains nine unique receipts in seven rounds:

| E2 receipt fact | Result |
| --- | ---: |
| Memory audit files / non-empty files | 20 / 7 |
| Unique receipts / unique consumed memory IDs | 9 / 6 |
| Consumer role / changed decision surface | Executor 9 / 9 |
| Assist / validated replay | 7 / 2 |
| `role_input_augmented` / current-input recompute | 7 / 2 |
| Compatibility verdict | `degraded` 9 |
| Skipped generation steps / LLM calls | 2 / 0 |

This is enough to state that E2 has real long-horizon consumption, not only
summary counters. It is still not enough to state broad acceleration because
seven assist receipts alter role input without skipping a step or model call.

### 7.3 Twenty-Round Memory Timeline

The full per-round timeline is more useful than one aggregate hit rate. Values
are `candidate / compatible / consumed`; the final column records the actual
effect class rather than treating every candidate as reuse.

| Round | Operating metrics | Operating effect | Financial reports | Financial effect |
| ---: | ---: | --- | ---: | --- |
| R1 | 0 / 0 / 0 | cold | 0 / 0 / 0 | cold |
| R2 | 1 / 0 / 0 | rejected | 1 / 1 / 1 | validated replay, 1 step skipped |
| R3 | 2 / 0 / 0 | rejected | 2 / 0 / 0 | rejected |
| R4 | 2 / 0 / 0 | rejected | 1 / 1 / 1 | validated replay, 1 step skipped |
| R5 | 4 / 0 / 0 | rejected | 2 / 0 / 0 | rejected |
| R6 | 1 / 0 / 0 | rejected | 2 / 2 / 2 | assist x2 |
| R7 | 2 / 0 / 0 | rejected | 2 / 0 / 0 | rejected |
| R8 | 2 / 1 / 1 | assist | 2 / 2 / 2 | assist x2 |
| R9 | 2 / 0 / 0 | rejected | 2 / 1 / 1 | assist |
| R10 | 9 / 1 / 1 | assist | 9 / 0 / 0 | all rejected |

Actual-use rounds are therefore operating R8/R10 and financial
R2/R4/R6/R8/R9. Financial R10 is especially important: the candidate pool has
grown to nine while compatible/use remains zero. It is direct evidence that
`candidate count != memory hit` and that the compatibility gate prevents a
growing history from becoming unconditional context injection.

Candidate-source counters also expose the retrieval surface. E2 records 48
vector candidates and 36 tag-channel candidates (the same candidate may appear
in more than one channel), while keyword candidates remain zero. E3 supplies
the fully materialized semantic/vector decisions; these E2 counters should be
used for diagnostics, not added as disjoint candidate totals.

### 7.4 Contest-Ready Memory Rates Derived From E2

The contest asks for a memory hit rate, but one undifferentiated percentage
would collapse retrieval, compatibility, use and saved work. E2 supports the
following query-normalized rates without any new model run:

| E2 rate | Formula | Result | Meaning |
| --- | --- | ---: | --- |
| Candidate-query rate | queries with >=1 candidate / all queries | 18/20 = 90.00% | Retrieval found something; not a hit. |
| Compatible-query rate | queries with >=1 compatible match / all queries | 7/20 = 35.00% | At least one candidate passed compatibility. |
| Actual-use query rate | queries with consumption / all queries | 7/20 = 35.00% | Approved memory entered the task path. |
| Effect query rate | queries with behavioral effect / all queries | 7/20 = 35.00% | Use changed recorded behavior. |
| Skipped-step query rate | queries with strict skipped step / all queries | 2/20 = 10.00% | A strict unit of work was removed. |
| Skipped-LLM-call query rate | queries with skipped model call / all queries | 0/20 = 0.00% | No model-call saving in E2. |
| Candidate compatibility | compatible candidates / all candidates | 9/48 = 18.75% | Candidate-level precision of the compatibility gate. |
| Candidate rejection | incompatible candidates / all candidates | 39/48 = 81.25% | Most retrieved candidates correctly fail closed. |

The recommended public label is not one `memory_hit_rate`. Show at least
`candidate`, `compatible`, `actual use`, `effect`, and `saved work`. If one
headline rate is unavoidable, use actual-use query rate and print the formula
beside it.

The two families also differ materially:

| E2 family | Candidate queries | Actual-use/effect queries | Candidate compatibility | Strict saved work |
| --- | ---: | ---: | ---: | ---: |
| Operating metrics | 9/10 | 2/10 | 2/25 = 8.00% | 0 skipped steps; 0 calls |
| Financial reports | 9/10 | 5/10 | 7/23 = 30.43% | 2 skipped steps; 0 calls |

This is useful task-selection information, not a reason to delete the weaker
family. It shows that memory value depends on compatibility structure. A future
memory experiment should preserve both a reuse-friendly family and a mostly
rejected family so that a high hit rate cannot be manufactured by choosing
only near-duplicate tasks.

E2's compact top-level slices retain only per-round counts, while its workspace
logs retain all nine consumption receipts. E3 remains complementary because it
materializes query decisions, role inputs and consumption records together and
adds a deliberate incompatible fixture.

### 7.5 E2 Prefix Fields

E2 has `kv_corpus_level_prefill_saved_tokens_estimate=2192`,
`kv_corpus_prefix_hash_reuse_count=13`, `kv_corpus_prefix_hash_unique_count=7`,
and `kv_engine_local_prefill_saved_tokens_estimate=3058`. As in E1, these are
estimate/counter fields rather than a controlled Prefix experiment. They must
not be added to E2 token savings, latency savings, or replay counts.

## 8. E3: Adaptive Memory Truth Funnel And Incompatible Negative Case

E3 is the strongest canonical proof that memory is more than a retrieval list.
It runs five financial cases plus one deliberately runtime-incompatible memory
fixture. Each case uses a fresh Runner but shares the family memory store.

| E3 measure | Result |
| --- | --- |
| Cases / quality pass | 6 / 6 |
| Verified artifact commits | 6 |
| Memory queries | 6 |
| Candidates | 16 |
| Compatible / policy-approved matches | 15 / 15 |
| Consumption records / behavioral effects | 23 / 23 |
| Unique memory IDs represented in consumption | 5 |
| Validated replay / exact replay | 1 / 0 |
| Strict skipped steps / skipped LLM calls | 1 / 1 |
| Rejected incompatible candidates | 1 |

`consumed=23` is not a counting error. One approved memory may be consumed by
more than one real role: the evidence records 8 Executor consumption records
and 15 Summarizer consumption records. The crucial negative fixture behavior
is all explicitly present:

```text
visible in candidate pool
  -> runtime signature incompatible
  -> decision recorded
  -> absent from all role inputs
  -> not consumed
  -> current output recomputed and verified
```

Each committed memory records verified artifact hash, terminal quality report,
input lineage, output contract and validator digest; commit records state
`benchmark_gold_used=false`. Therefore E3 supports "compatibility-gated,
verified, observable reuse" and one actual skipped LLM call. It does not
support a generalized latency/cost statement from one saving event.

E3's observed selection distribution is also useful for later test design:

| Capability | Count across six cases |
| --- | ---: |
| Table retrieval | 6 |
| Bounded Python | 4 |
| DSL | 2 |
| Claim-set composition | 5 |
| Risk memo composition | 1 |

### 8.1 Rates, Verdicts And Retrieval Channels

E3 supports a much more precise memory-rate display than a single ambiguous
"hit rate":

| E3 derived rate | Result | Correct reading |
| --- | ---: | --- |
| Candidate-query rate | 5/6 = 83.33% | Five queries saw at least one prior memory; sample 1 is the cold start. |
| Compatible-query rate | 5/6 = 83.33% | At least one candidate crossed the compatibility gate. |
| Actual-use/effect query rate | 5/6 = 83.33% | An approved memory reached a role and changed recorded behavior. |
| Warm/non-cold actual-use rate | 5/5 = 100.00% | Descriptive for this deliberately sequential six-case suite; not a population estimate. |
| Candidate compatibility | 15/16 = 93.75% | One deliberately incompatible fixture was rejected. |
| Saved-step / saved-call query rate | 1/6 = 16.67% each | Bounded strict saving, not broad acceleration. |

The 16 compatibility decisions are one `compatible`, 14 `degraded`, and one
`incompatible`. The 14 degraded decisions all record changed canonical task
arguments and changed input lineage; the incompatible fixture records a runtime
signature mismatch. This is a useful design result: reuse does not require
identical inputs, but changed inputs downgrade reuse to recipe/context
assistance rather than answer restoration.

All 15 formal matches were produced by `hybrid_rrf:vector`. Keyword and tag
source ranks are empty in E3 even though every MemoryRef carries tags and the
implementation has keyword/tag paths. Therefore the formal claim is "semantic
retrieval plus compatibility gating." This fully satisfies the contest's
keyword, tag **or** semantic-similarity retrieval requirement. Keyword/tag
support belongs to E6 engineering coverage and does not require another formal
experiment unless the PPT voluntarily claims all three channels were
task-benchmarked.

### 8.2 Per-Case Truth Funnel And Workload Record

| Case | Candidates / compatible | Consumption / effect | Strict saving | Tokens | Elapsed | Execution observation |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| sample 1, cold | 0 / 0 | 0 / 0 | none | 6,095 | 77.936 s | Initial bounded-Python generation. |
| sample 2 | 1 / 1 | 2 / 2 | none | 8,177 | 73.131 s | Prior recipe failed on changed input, then runtime repair passed. |
| sample 3 | 2 / 2 | 4 / 4 | none | 9,062 | 75.042 s | Same changed-input repair pattern. |
| sample 4 | 3 / 3 | 3 / 3 | none | 6,297 | 76.141 s | DSL path, no model code-generation record. |
| sample 5 | 4 / 4 | 4 / 4 | none | 6,291 | 75.237 s | DSL path, no model code-generation record. |
| incompatible negative | 6 / 5 | 10 / 10 | 1 step and 1 LLM call | 4,445 | 59.615 s | Incompatible fixture rejected; no Executor model role observed; current result still recomputed and verified. |

E3 totals 40,367 tokens and 437.102 seconds of per-case elapsed time. These are
workload descriptors, not memory-on/off benefits, because the suite has no
matched OFF lane. In the negative case, the incompatible fixture is ranked
second, rejected and absent from role inputs, while five other compatible
memories are consumed. The one skipped Executor model call belongs to that
compatible-memory execution path; it must **not** be attributed to the rejected
fixture. The negative fixture proves safety, while the compatible memories
provide the bounded saved-work observation.

### 8.3 Memory Storage And Required Metadata

The family memory root is physically materialized as:

| Backing object | Size | Role |
| --- | ---: | --- |
| `memory_index.sqlite3` | 49,152 B | Durable metadata/index source. |
| `embedding_registry.json` | 102,854 B | Embedding references used by semantic retrieval. |
| `commit_registry.json` | 32,093 B | Verified MemoryRef/commit and lineage ledger. |

The commit registry has seven entries: six case-produced memories plus the
deliberately incompatible fixture. All 7/7 have non-empty `memory_id`,
`source_agent`, `created_at_ns`, `task_theme`, `summary`, tags, embedding refs
and artifact refs; all are marked committed and validation-passed. All seven
were produced by Executor and are typed `validated_replay`. This directly
closes the contest's required memory-metadata checklist, while also exposing a
scope limit: this suite does not demonstrate multiple producer roles or task
families in the same memory store.

### 8.4 Runtime Adaptation Hidden By The 6/6 Headline

All six cases used Planner schema normalization, covering 38 normalized fields.
Five initially omitted the formal Summarizer evidence dependency; runtime
normalization recovered them without a hard policy rejection. Two Python cases
required runtime repair after a reused Q1-oriented recipe failed on current
input. Across the suite there were 18 approved steps, 18 dispatches, 20 role
invocations, four verified bwrap execution records, no timeout and no execution
fallback.

This is not a reason to weaken the E3 result. It identifies the actual technical
difficulty: reusable recipes and model plans must be revalidated against current
inputs and normalized contracts. The value of the memory layer is the verified
promotion/gating path, not an assumption that past code runs unchanged.

## 9. E4: Cross-Process Non-Text Semantic State Holdout

E4 is the cleanest mechanism/lifecycle experiment for the non-text pillar.
The runtime content was frozen before execution, the benchmark oracle was
hidden from role requests, and four offline holdout cases all passed.

| Case | Input shape | Retriever | Executor | Semantic StateRef | Result |
| --- | --- | --- | --- | --- | --- |
| S1 | Narrative only | Semantic | Bounded Python | Yes | PASS |
| S2 | Narrative only | Semantic | Bounded Python | Yes | PASS |
| S3 | Table only | Table | DSL | No | PASS |
| S4 | Narrative + table | Semantic | Bounded Python | Yes | PASS |

For S1, S2 and S4, the evidence captures the actual numerical object and the
consumer lifecycle:

| Physical state evidence | S1 | S2 | S4 |
| --- | ---: | ---: | ---: |
| Matrix shape | `[9,1024]` | `[9,1024]` | `[6,1024]` |
| One matrix size (little-endian float32) | 36,864 B | 36,864 B | 24,576 B |
| Physical matrices retained | 3 | 3 | 3 |
| Total retained state bytes | 110,592 B | 110,592 B | 73,728 B |
| Release records / released bytes | 3 / 110,592 B | 3 / 110,592 B | 3 / 73,728 B |

The semantic producer PID is 308338; executor consumer PIDs are separate
processes, including 308651, 308717 and 308783. Consumers execute
`cosine_topk_budget_pruning`; the record includes selected candidate IDs and
changed input/output decision-surface hashes. Thus E4 proves:

```text
local embedding generation
  -> shared-memory StateRef publish
  -> different-PID open and numerical top-k consumption
  -> selected-ID/hydration decision change
  -> receipt and byte-matched release
```

E4 does not prove that shared memory is faster than a same-selection serialized
vector or text carrier. The table/DSL S3 case is a useful control for routing,
but it is not a semantic-state comparison.

### 9.1 Selection, Receipt And Telemetry Accounting

The three semantic cases produce nine physical selection objects and nine
consumption receipts. Every selection has a distinct consumer PID from the one
producer PID; across the suite there are nine distinct consumer PIDs. The nine
top-k operations select 27 candidate occurrences drawn from six unique context
section IDs. Their recorded cosine scores range from 0.367006 to 0.778453
(median 0.563843), and the selected/hydrated evidence totals 5,963 bytes.

Two valid counters describe different edges of the lifecycle:

| E4 counter surface | Count / bytes | Meaning |
| --- | ---: | --- |
| Telemetry publish events | 18 | Instrumented event edges; not 18 independent physical matrices. |
| Telemetry transfer events | 18 | Instrumented transfer edges; not the receipt denominator. |
| Physical selections | 9 | StateRef selection objects across S1/S2/S4. |
| Consumption receipts | 9 | The correct denominator for the cross-PID usage claim. |
| Decision surfaces changed | 9/9 | Input and output decision-surface hashes differ after numerical selection. |
| Published/released physical bytes | 294,912 / 294,912 | Byte-matched lifecycle closure. |
| Release events | 9 | Owner-side closeout of the nine physical objects. |
| Embedding encode events | 75 | Query/candidate encoding workload, not StateRef transfer count. |

This distinction matters for the PPT. Use `9/9 cross-PID receipts`, not 18
"states transferred" and not 75 "non-text transfers." The latter numbers are
valid telemetry but answer different questions.

### 9.2 Workload And Repair Cost

| E4 case | Tokens | Elapsed | Generation/repair record | Interpretation |
| --- | ---: | ---: | --- | --- |
| S1 narrative | 8,425 | 115.436 s | One initial Python generation | Semantic StateRef path passed. |
| S2 narrative | 7,851 | 96.880 s | One initial Python generation | Semantic StateRef path passed. |
| S3 table | 6,504 | 78.317 s | DSL; no code-generation record | Routing control only. |
| S4 mixed | 22,489 | 191.845 s | Initial plus three repairs | Forbidden call, runtime error and quality mismatch were repaired before pass. |

The suite totals 45,269 tokens and 482.478 seconds. As in E3, these are
descriptive loads without a matched carrier comparator. S4 alone accounts for
49.68% of E4 tokens and 39.76% of elapsed time, so an average E4 latency number
would mostly measure one repaired mixed-input case rather than StateRef
transport.

All four cases used Planner schema normalization (27 fields) and initially
omitted the formal Summarizer evidence dependency. The final run still ends
with 12 approved steps, 12 dispatches, 14 role invocations, three verified
bwrap executions, one verified DSL execution, no timeout and no fallback.

### 9.3 What The Failed Holdout Runs Reveal

The four preserved attempts before `final4` are not extra samples for the 4/4
headline. They are diagnostic evidence about where the hard part was:

| Holdout attempt | Quality passes | System gates | Gold-hidden gates | Semantic StateRef gates | Main failure surface |
| --- | ---: | ---: | ---: | ---: | --- |
| `serial` | 1/4 | 4/4 | 4/4 | 3/3 semantic cases | Expected-facts quality failed in S1/S2/S4. |
| `final` | 2/4 | 4/4 | 4/4 | 3/3 | Expected-facts quality failed in S1/S4. |
| `final2` | 3/4 | 4/4 | 4/4 | 3/3 | S4 expected-facts quality failed. |
| `final3` | 2/4 | 4/4 | 4/4 | 3/3 | S3 and S4 expected-facts quality failed. |
| `final4` canonical | 4/4 | 4/4 | 4/4 | 3/3 | Closed. |

Across the 16 failed-attempt case executions, system and gold-visibility gates
stay 16/16, while the semantic cases continue to pass their StateRef mechanism
gate. The instability is downstream semantic/execution quality, especially S4,
not an inability to publish or open shared memory. This is direct evidence for
the technical-difficulty story: preserving task quality after numerical
selection and constrained execution is harder than moving the bytes.

## 10. E5: Adaptive Capability Registry And CodeAct Coverage

E5 executes the complete fixed 25-case registry across five task families:

| Formal task family | Cases |
| --- | ---: |
| Financial-report extraction | 8 |
| Multi-period trend | 5 |
| Cross-table join | 5 |
| Conditional aggregation | 4 |
| Anomaly detection | 3 |
| Total | 25 |

| E5 quality and adaptive metric | Value |
| --- | ---: |
| Cases attempted / completed / quality pass | 25 / 25 / 25 |
| Quality pass rate | 1.00 |
| Planner final approvals | 25 |
| Planner schema normalizations / hard rejections | 25 / 0 |
| Verified execution workflows | 25 |
| Bounded-Python CodeAct generated / executed / verified | 18 / 18 / 18 |
| DSL verified | 7 |
| CodeAct quality/runtime repairs | 0 / 0 |
| CodeAct sandbox fallback / model fallback / total fallback | 0 / 0 / 0 |
| Prompt / completion / total tokens | 144,726 / 37,101 / 181,827 |
| Aggregate `task_ms` | 2,643,069.867 |
| Per-case mean total tokens / `task_ms` | 7,273.08 / 105,722.795 |

| Capability | Selected and verified count |
| --- | ---: |
| `retrieve_table_evidence_v1` | 25 |
| `execute_bounded_python_v2` | 18 |
| `execute_analysis_dsl_v2` | 7 |
| `compose_claim_set_v2` | 23 |
| `compose_risk_memo_v1` | 2 |
| `retrieve_semantic_evidence_v1` | 0 in E5 |

All 18 Python records are bwrap-backed and record `UID/GID=65534:65534`.
Semantic retrieval is intentionally covered by E4 rather than forcing E5's
task distribution. E5 is strong coverage/completeness evidence; its token and
time totals are workload accounting only, because it has no fixed non-CodeAct
comparison lane and explicitly sets `latency_superiority_claim_allowed=false`.

### 10.1 Task And Operation Surface

The five registry families are not five names for one lookup template. Their
declared reasoning types are single-metric extraction, multi-period trend,
cross-table relation, conditional aggregation and anomaly detection. The 25
cases exercise ten operation labels:

| Operation | Cases | Operation | Cases |
| --- | ---: | --- | ---: |
| `lookup_metric` | 8 | `compare_metric` | 4 |
| `compute_trend` | 4 | `compute_delta` | 2 |
| `detect_outliers` | 2 | `aggregate_and_extreme` | 1 |
| `groupby_aggregate` | 1 | `materialize_clean_table` | 1 |
| `profile_and_mean` | 1 | `profile_table` | 1 |

Capability selection produced four complete combinations: 17 table -> Python
-> claim-set, one table -> Python -> risk-memo, six table -> DSL -> claim-set,
and one table -> DSL -> risk-memo. All four model roles were observed in all 25
cases; the records contain 75 approved steps, 75 dispatches and 94 role
invocations.

### 10.2 Per-Family Load And Long Tail

| E5 family | Cases | Mean / p95 elapsed | Mean total tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: |
| Financial extraction | 8 | 78.354 / 81.932 s | 6,338.25 | 50,706 |
| Multi-period trend | 5 | 131.387 / 183.913 s | 8,362.80 | 41,814 |
| Cross-table join | 5 | 107.083 / 170.009 s | 7,384.60 | 36,923 |
| Conditional aggregation | 4 | 126.278 / 230.343 s | 7,878.75 | 31,515 |
| Anomaly detection | 3 | 106.260 / 124.209 s | 6,956.33 | 20,869 |

The largest case is `formal-agg-004`: 254.698 seconds, 12,215 tokens and eight
role invocations. The next two long-tail cases are trend/join work at 194.291
and 190.683 seconds. This is useful for future benchmark design: latency must be
stratified by operation/complexity rather than reported as one unqualified E5
mean.

DSL cases average 77.839 seconds and 6,363 tokens; Python cases average 116.566
seconds and 7,627 tokens. This is **not** a DSL-vs-CodeAct advantage because the
planner assigns different task types to the two executors. Task selection,
operation complexity and execution method are confounded.

### 10.3 Normalization, Isolation And Negative Space

All 25 plans required schema normalization, covering 163 fields; 20 cases
initially omitted the formal Summarizer evidence dependency. There were no hard
planner rejection, generation repair, timeout, execution fallback or sandbox
fallback in the canonical run. All 18 Python executions were verified in
bwrap, and all 25 terminal quality reports were verified with the benchmark
oracle hidden from roles.

Equally useful are the zeroes: E5 has zero StateRef consumption, zero memory
consumption and zero memory commit. It proves adaptive task/capability coverage,
not all three StateBus pillars in every case. E4 and E3 remain the evidence
owners for semantic state and memory respectively.

The preserved predecessor run stopped at 24/25. `formal-agg-002` failed the
Executor `capability_quality_rejected` gate with category `model_quality`, while
system failure count remained zero. The canonical rerun closes the quality
case, but the failure explains why E5 should be presented as verified coverage,
not as an artificially flawless failure-path matrix.

## 11. E0 And E6: Engineering Gates

| Gate | Result | Time | Correct interpretation |
| --- | --- | ---: | --- |
| E0 focused tests | 135 passed; deterministic preflight `ok=true` | 632.42 s | Focused engineering correctness gate. |
| E6 complete `tests/v2` | 558 passed, 100 warnings; deterministic preflight `ok=true` | 858.69 s | Full regression gate in the target container. |

The 100 E6 warnings include existing Protobuf descriptor deprecation warnings.
They do not invalidate the pass, but they must not disappear from the delivery
record or be restated as a zero-warning result.

E0/E6 also record `embedding_mode=deterministic` and
`role_path_mode=deterministic` for their preflights. The environment has a
healthy local GPU and vLLM configuration, but these engineering gates must not
be cited as additional local-model task runs.

### 11.1 Engineering Coverage That Must Stay Separate From Benchmarks

The full suite covers several failure and storage behaviors that do not appear
as canonical E1-E5 task events:

| E6-covered engineering surface | What the tests establish | Why it is not a formal task claim |
| --- | --- | --- |
| Dense-state validation | Shape, encoder signature, expiry and corruption fail closed. | No task-level fault-injection rate or recovery latency. |
| Shared-memory ownership | Consumer closes its mapping; owner release unlinks; orphan finalizer is covered. | E4 only demonstrates the normal publish/consume/release path. |
| Runtime lifecycle | ACK timeout, lease expiry and GC state transitions are trapped. | No canonical crash/orphan campaign. |
| Workspace persistence | Identical JSON payloads can be reused without rewrite; persistence breakdown is emitted. | No matched I/O performance comparison. |
| Memory retrieval | SQLite FTS keyword, SQL tag filtering, hybrid RRF and FAISS/cosine ranking equivalence. | E3 formal matches come only from vector retrieval. |
| Replay safety | Changed intent/output contracts, unverified output, corrupted history and invalidation are rejected. | E3 has one deliberate runtime-signature negative; it is not the whole fault matrix. |
| Typed transport | Protobuf and UTF-8 subprocess round trips, typed refs, UDS sequence and malformed request rejection. | E1 measures bytes/quality, not parser throughput or malformed-input frequency. |

These tests are valuable system-completeness evidence. They should appear in a
technical appendix or architecture-defense slide, while the main result charts
continue to use E1-E5 task evidence.

The immediately preceding E6 attempt had 555 passes and three failures:
max-token override validation, subprocess transport loopback instrumentation,
and memory-slice visibility. The final 558-pass run supersedes it. Preserving
the failure names is useful for regression provenance; adding its partial pass
count to E6 would be invalid.

## 12. Preserved Failures, Retries And Diagnostics

The baseline is credible partly because failures remain visible. None of these
roots is aggregated with E0-E6:

| Root or group | Observed result | Why excluded / retained value |
| --- | --- | --- |
| `focused_20260720_140122` | 133 passed; adaptive planner capability-prompt failure | Superseded by fresh E0 135-pass gate. |
| `causal_20260720_142709` | 40/40 | Overlaps E0 timing; not serialized formal evidence. |
| `e1_causal_20260720_143554` | Child exit `-15` | Interrupted; fresh E1 is canonical. |
| `stress_20260720_145740` | Child exit `-15`, shared-memory cleanup warning | Interrupted; fresh E2 is canonical. |
| `e3_adaptive_memory_serial_20260720_154048` | 5/6 | Candidate was visible and absent from role input, but runtime incompatibility and recompute verification gates were not both closed; final E3 closes them. |
| E4 `serial`, `final`, `final2`, `final3` | 1/4, 2/4, 3/4, 2/4 | System/gold/StateRef gates held; expected-facts quality varied. `final4` is the only 4/4 formal source. |
| `e5_adaptive_serial_20260720_180846` | 24/25 | `formal-agg-002` Executor model-quality rejection with zero system failures; final E5 is 25/25. |
| `e5_formal_agg_002_probe_20260720_185808` | Single case passed | Diagnostic only; does not replace full E5. |
| `e6_full_serial_20260720_195042` | 555 passed, 3 failed | Superseded by fresh E6 558-pass suite. |
| `e6_memory_slice_probe_20260720_200735` | Input visibility probe | Not replay evidence. |

These roots are useful regression fixtures and explain the final fail-closed
behavior. They cannot be cherry-picked into an optimistic performance total.

The failures also sharpen the technical-difficulty statement:

1. **Control difficulty:** model plans often need schema normalization and
   dependency repair before typed execution, even at temperature zero.
2. **Non-text difficulty:** shared memory and cross-PID opening were stable
   before semantic quality was stable; selecting the right evidence and
   preserving downstream correctness is the harder part.
3. **Memory difficulty:** approximate similarity is insufficient. Current
   arguments, lineage, output contract, validator and runtime signature must be
   checked, and reused recipes may still require current-input repair.
4. **Capability difficulty:** aggregate/trend tasks create role-invocation and
   generation long tails even when the sandbox/system gates stay healthy.
5. **Evidence difficulty:** fixed ordering, null model seeds and shared service
   state make raw latency/prefix counters weaker than matched token/wire and
   receipt evidence.

Those are not generic claims inferred from the architecture. Each is tied to a
passing or preserved failed artifact above.

## 13. What The Fixed Baseline Already Earns

| Pillar | Evidence chain | Strongest factual statement |
| --- | --- | --- |
| Structured control | E1 L0/L1, same 50 messages and 10/10 quality | Typed Protobuf lowers control bytes 83.05% and total wire bytes 68.95%; it does not itself lower token consumption. |
| Whole-system efficiency | E1 L0/L3, same tasks and quality | Full L3 reduces total LLM tokens 47.40%, prompt-visible bytes 79.13%, and total wire bytes 64.85%. |
| Non-text state | E1 L1/L2 plus E4 | Local embeddings become shared-memory StateRefs, are consumed by another PID numerically, alter selection/hydration, and release cleanly. |
| Shared memory reuse | E3 plus E1/E2 | Memory is compatibility-gated, provenance-backed, consumed by real roles, rejected when incompatible, and has bounded observed saved work. |
| Continuous collaboration | E2 | Two associated ten-round L3 chains pass 20/20 with state/memory records. |
| CodeAct / system completeness | E5 plus E0/E6 | 25/25 registry coverage with 18 verified bounded Python and 7 DSL workflows, backed by full regression. |
| Delivery environment | E0-E6 | The full formal package ran in one openEuler 24.03 LTS-SP3 container. |

The cohesive story is therefore not three unrelated optimizations:

```text
typed control
  -> cross-process SemanticStateRef
  -> verified ExecutionArtifactRef
  -> compatibility-gated MemoryRef
```

The unifying innovation is a receipt-backed state-promotion chain. A task is
constrained before execution; a numerical state is consumed under a manifest;
an execution artifact is validated before it becomes memory; and a memory is
only called reuse after compatibility, consumption and observed effect.

### 13.1 Motivation, Difficulty, Mechanism And Evidence Are One Chain

| Contest problem / why this is needed | Actual technical difficulty | StateBus mechanism and highlight | Baseline evidence | Honest conclusion |
| --- | --- | --- | --- | --- |
| Natural-language relay repeats control context and is hard to validate. | A model plan is not automatically schema-valid or behaviorally consumed. | Typed Protobuf control, capability registry, ACK/error semantics and runtime fallback. | E1 L0/L1 same 50 messages; control bytes -83.05%; 160 ACKs; 38/40 model plans valid, two recovered; 160 Retriever consumed-hash matches. | Typed control is smaller on wire and inspectable at equal quality; it is not the source of the token win. |
| Converting evidence to text for each downstream role expands prompts and loses object identity. | Publishing shared memory is easy compared with proving a different process numerically consumed it and changed a decision. | Manifested `SemanticStateRef`, local GPU embedding, cross-PID open, numerical selection and receipt/release. | E4 9/9 cross-PID receipts and byte-matched release; E1 18 semantic cases and L1/L2 prompt reduction. | Non-text state is real and used; carrier-only latency superiority remains unisolated. |
| Unverified tool output must not silently become reusable knowledge. | Output validity, input lineage, contract and runtime signature must survive process/workspace boundaries. | Separate `ExecutionArtifactRef`, validator reports and quality-gated promotion. | E1 40/40 and E2 20/20 verified, replay-ready, lineage-complete artifact audits; 120 validator refs in total. | Receipt-backed artifact promotion is a core system contribution, not bookkeeping. |
| Similar history can be stale, incompatible or harmful. | Retrieval similarity, compatibility, real consumption, effect and saved work are different states. | `MemoryRef` funnel with compatibility gate, role-input receipt, downgrade/recompute and negative rejection. | E3 full funnel and negative fixture; E2 20-round timeline with 9 receipts but only 2 skipped steps. | Reuse is safe, observable and sometimes beneficial; broad acceleration is not yet proved. |
| A one-case prototype does not establish a usable system. | Model plans, semantic selection, constrained execution and memory must remain stable together. | Four-role runtime, two associated chains, adaptive capability registry and engineering gates. | E2 20/20, E5 25/25, E0 135 passes, E6 558 passes. | System completeness and target-container execution are strong; VM/cross-machine generalization is outside the evidence. |

This table is the answer to "why did we build these mechanisms?" The common
goal is not merely fewer tokens. It is to promote state across process and task
boundaries without losing type, provenance, validity or compatibility, then
measure the cost and benefit at each boundary.

### 13.2 PPT Experiment Pages 20-24: Evidence-Backed Replacement

The two main decks have the same 25-slide argument. Their experiment section
can be corrected without redesigning the architecture or inventing a dataset:

| Slide | Main-deck content to show | Use now | Move to appendix / mark open |
| --- | --- | --- | --- |
| 20, evaluation contract | Same task/model/role graph, serial execution, quality floor, gold hidden, checksum lineage | E1 fairness: 40/40 audits, 160 role-request checks, zero gold violations | Replace `seed fixed` with `temperature/profile/timeout recorded`; server seeds are null. |
| 21, evidence matrix | Four columns: C typed control, N non-text state, M memory, integration | C=E1; N=E4+E1; M=E3+E2; integration=E2/E5/E0/E6 | Do not leave `campaign pending`; label latency and carrier attribution as incomplete. |
| 22, efficiency attribution | L0/L1 bytes, L1/L2 joint semantic path, L0/L3 whole-stack token/wire and equal quality | Lead with -83.05% control bytes and -47.40% total tokens, with attribution labels | T2 remains a visibly missing optional bridge; do not draw a fully causal L0-L1-T2-L2-L3 ladder. |
| 23, state and continuity | E4 9/9 receipt lifecycle plus E2 20-round candidate/use timeline | Show cross-PID consumption and `candidate != use`; report actual-use 35%, skipped-step 10% | Put raw PID lists, state shapes, retries and stage timers in appendix. |
| 24, score-facing conclusion | Three claim cards with confidence/boundary: C wire efficiency, N mechanism innovation, M safe bounded reuse | Map directly to 25/20/20 scoring rows and add E5/E0/E6 completeness strip | Mark fair latency and broad memory net value as remaining evidence, not implemented advantage. |

Two non-experiment labels elsewhere in the deck also need correction: slides
10-11 should name the E4 consumer as the cross-process Executor
retrieve-evidence worker, not a separate `Selector` process; openEuler claims
must remain single-container only. Slides 12-13 should show candidate,
compatible, consumed, effect and saved-work as separate funnel levels.

The main deck should use four visuals only: L0-L3 efficiency/quality, E4 state
lifecycle, E2/E3 memory funnel/timeline, and system-completeness coverage. Role
prompt breakdowns, stage timings, artifact lineage, failed attempts, CodeAct
family loads and Prefix/Logit counters belong in backup slides. This keeps the
story narrow while preserving the full evidence for questions.

## 14. Explicit Gaps: What Is Not Yet Demonstrated

| Question | Existing useful asset | Why it is insufficient | Minimal additional evidence, if the claim is needed |
| --- | --- | --- | --- |
| Does StateRef transport itself beat same-selection text/vector transfer? | E4 mechanism and E1 L1/L2 token reduction | L1->L2 jointly changes pruning and carrier. | T2: same selected IDs and same evidence slice, text carrier versus StateRef, with quality held. |
| Is L3 reliably lower latency end-to-end? | E1/E2 raw serial timing | Fixed lane order, no warm-up policy, no AB/BA or randomized repeats. | Balanced serial timing campaign with cold/warm definition and per-stage time breakdown. |
| Does memory broadly reduce cost/time? | E3 one skipped LLM call; E1/E2 strict skipped steps | Savings are real but narrow; history counters are not replay. | Narrow matched memory-on/off comparison around known compatible and incompatible tasks. |
| What is the protocol parser/reject benefit? | Tests and typed control bytes | No measured parser/reject-rate comparison. | Small protocol-robustness report only if needed for the presentation. |
| Does lifecycle survive crash/orphan/expiry? | E4 publish/open/consume/release | No canonical fault-injection campaign. | One scoped lifecycle-fault test if the slide promises empirical recovery. |
| Does CodeAct outperform a fixed execution method? | E5 coverage and correctness | No comparison lane. | Only add if CodeAct is promoted beyond an encouraged supporting feature. |
| Does Prefix caching help StateBus? | Estimate/counter fields only | No cache-on/cache-off fair design or isolated vLLM service state. | Separate engine-local Prefix experiment, not part of this baseline. |
| Does LogitState work? | Zero transfers in E1 | No implemented canonical mechanism experiment. | Separate research item; do not add to the current story. |
| Does this generalize across VM/machines/open domain? | One openEuler container and repo-local tasks | No corresponding experiment. | Out of current recovery scope. |

## 15. Decision Rules For the Next Experiment Discussion

### 15.1 Baseline Conclusion

The E0-E6 baseline is already sufficient to tell one coherent, requirement-
aligned story. It does not need another architecture pass, a new dataset,
Prefix work, LogitState work, or a full rerun to become understandable:

```text
E1: same workflow, less total token/wire at equal quality
E4: numerical state is genuinely consumed across PIDs and released
E3: only compatible verified artifacts become usable memory; bad memory is rejected
E2: this chain remains stable across two 10-round task families
E5/E0/E6: the four-role execution surface and regression gates are complete
```

The correct presentation conclusion is therefore: StateBus' demonstrated
advantage is a quality-preserving reduction of the **whole workflow's** prompt
and wire burden, backed by actual cross-process state consumption and
compatibility-gated memory reuse. The evidence does not say that every layer is
individually faster, that every memory query saves a call, or that shared memory
alone causes the token reduction.

### 15.2 What Must Not Be Repeated

| Work item | Baseline decision | Reason |
| --- | --- | --- |
| E0/E6 engineering gates | Do not rerun for a result slide | They are already completed delivery gates. |
| E1 L0-L3 token/wire matrix | Do not rerun merely to recover the same number | The matched result is already checksum-verified and fully instrumented. |
| E2 two 10-round chains | Do not rerun merely to show continuity | 20/20 stability is already established. |
| E3 negative memory gate | Do not rerun merely to show safe rejection | The incompatible fixture already closes the truth funnel. |
| E4 cross-PID StateRef | Do not rerun merely to prove the mechanism exists | PID, numerical consume, effect and release are already present. |
| E5 CodeAct coverage | Do not rerun as a new performance experiment | It is supporting completeness evidence, not a core comparison. |
| Prefix / LogitState | Do not add to the baseline work package | Neither closes a current C/N/M evidence gap. |

### 15.3 The Only Claim-Upgrades Worth Discussing Later

| Priority | Candidate work | Existing story without it | Claim unlocked by doing it |
| --- | --- | --- | --- |
| P0 | Fair L0/L3 serial latency study | Token/wire advantage and descriptive timing remain valid | Contest-facing, quality-gated task-latency conclusion. |
| P1 | Frozen-memory OFF / gate-only / actual-use comparison | Safe observable reuse and decomposed hit/use rates remain valid | Memory search overhead, gross reuse value and net end-to-end value. |
| P2, conditional | T2 same-selection carrier study | Cross-PID non-text mechanism remains fully demonstrated | Carrier/representation attribution instead of the current joint L1/L2 result. |
| Appendix only | Parser/reject or lifecycle fault campaign | Engineering tests remain valid | Empirical parser/fault-path claim, only if the PPT explicitly promises it. |

This is an ordering, not an instruction to start all three. The baseline first
decides the claim; an experiment is added only when that specific stronger claim
is needed. If no latency headline is required, the current evidence should be
presented honestly rather than broadened for its own sake.

**Current operator decision (2026-07-24).** The executable follow-up is narrower
than the ideal designs below: one quality-gated AB/BA sanity cycle for L0/L3
(`P0-lite`) and one L2/L3 OFF/actual-use sanity cycle (`P1-lite`). The existing
runner has no supported frozen-snapshot/gate-only lane, so P1-lite must not be
presented as the full M0/M1/M2 causal experiment. T2 is excluded by default:
E4 already supports the non-text mechanism claim, while the local T2 code/path
is only needed for a stronger carrier-speed claim. Exact commands, environment,
metrics and CodeAct boundaries are fixed in
`docs/reports/contest_recovery_supplemental_experiment_operator_20260724.md`.

### 15.4 P0 Design: Fair Whole-Stack Latency

**Question.** Under the same E1 tasks and quality gates, does L3 change
end-to-end task latency relative to L0, and where is the break-even point
between LLM work saved and StateRef/validation/memory overhead added?

**Frozen inputs.** Reuse the exact ten E1 task identities, source-content
digests, role graph, capability registry, validator and local model profiles.
Do not add or remove a task after seeing timing. Preserve both operating and
financial families because the existing crossover is itself decision-useful.

**Schedule.** Run serially only. Perform one excluded warm-up for each
family/lane, then at least four measured paired blocks per task: two `L0->L3`
and two `L3->L0`, with block order pre-generated and recorded. This yields 40
paired deltas / 80 measured cases; use six blocks if time permits. No concurrent
API launches, no service restart inside a block, and no tuning between lanes.
The vLLM configuration and Prefix/APC state must be fixed for the whole
campaign. If APC cannot be disabled, record it as shared service state and do
not attribute any latency change to Prefix.

**Primary result.** Paired `task_ms(L3)-task_ms(L0)` over quality-passing pairs.
Report family-specific and pooled median/mean delta, p50/p95, win/tie/loss,
95% paired-bootstrap confidence interval and a paired sign or Wilcoxon test.
Never report only the ratio of aggregate sums.

**Required secondary fields.** `llm_wall_ms`, TTFT when emitted reliably,
prompt/completion/total tokens, wire bytes, StateRef bytes and lifecycle time,
memory query/gate/consumption time, validator/persistence/workspace time,
fallback/repair counts and quality result. New stage spans must be exclusive or
explicitly parent/child; the current overlapping timers cannot be added into a
fake total.

**Fair interpretation.** Keep all valid paired cases in the primary result.
Report fallback-matched sensitivity separately rather than silently deleting
slower repairs. If the confidence interval crosses zero, the conclusion is
latency parity/crossover, not failure: retain the proven token/wire result and
show which workload sizes amortize the safety mechanisms. A useful diagnostic
is latency delta versus prompt tokens or evidence bytes removed.

The PPT latency visual should decompose, without double counting:

```text
gross LLM time change
  + control/state lifecycle overhead
  + verification/persistence/memory-gate overhead
  = observed end-to-end paired delta
```

This is the fair way to explain that safety checks have a cost. Their time is
not subtracted from L3; it is measured, shown, and evaluated against the LLM
work they avoid.

### 15.5 P1 Design: Memory Net Value Without Task Specialization

Use every round in the existing two E2 chains, not only the seven known-hit
rounds. Materialize the memory store available before each round as an
immutable snapshot and restore the same snapshot before every lane/repeat.
This preserves the natural 35% actual-use / 65% no-use distribution instead of
manufacturing a high hit rate from near-duplicate tasks.

| Lane | Behavior | What it isolates |
| --- | --- | --- |
| M0 OFF | No search, gate or memory injection | Current-task baseline. |
| M1 gate-only | Run retrieval/rerank/compatibility but withhold approved memories from roles | Search and safety-gate overhead. |
| M2 actual-use | Full approved consumption/effect path | Gross and net value of real reuse. |
| M3 incompatible negative | Make the frozen incompatible fixture visible; require reject and recompute | Safety correctness and rejection overhead, not speedup. |

Run M0/M1/M2 in balanced serial order for every frozen round and repeat. M3 is
a scoped negative control, not a fourth population lane. Hold current input,
model profile, prompt template, capability route and validator fixed. A run is
invalid if the snapshot or compatibility signature differs across its lanes.

Report the existing funnel plus three explicit value equations:

```text
gate_overhead_ms       = task_ms(M1) - task_ms(M0)
gross_consumption_ms   = task_ms(M1) - task_ms(M2)
net_memory_value_ms    = task_ms(M0) - task_ms(M2)
```

The same deltas must be reported for prompt/total tokens, LLM calls and strict
steps. Also report candidate-query, compatible-query, actual-use, effect,
skipped-step and skipped-call rates with denominators; retrieval/gate latency;
consumption records and unique memory IDs; false-accept/reject counts; and the
quality floor. Stratify actual-use, rejected and cold rounds, then publish the
weighted all-20-round result. If memory improves only the two replay rounds but
adds overhead overall, that is the correct finding.

### 15.6 P2 Design: Optional T2 Attribution

E4 already proves the innovation mechanism. T2 is justified only if a slide
claims that the carrier or representation itself is faster. Two different
questions must not be mixed:

| Variant | Frozen boundary | Comparison | Claim it can support |
| --- | --- | --- | --- |
| T2a representation path | Same candidates, selected-ID gold and downstream validator | Selected evidence as text bridge versus StateRef-driven numeric selection/hydration | Cost of avoiding a text bridge at the integrated path level. |
| T2b carrier microbenchmark | Byte-identical float32 matrix, shape, dtype, consumer operation and selected IDs | Inline typed tensor bytes versus shared-memory `StateRef` | Copy/serialization/open/read/release cost of the carrier alone. |

T2a must report any change in work placement; it is not a pure transport test.
T2b should run without LLM calls to remove generation noise, repeat across the
observed 24,576 and 36,864-byte matrices plus larger predeclared sizes, and
measure producer serialization/write, UDS bytes, consumer decode/open/read,
top-k time, release, total time and byte-copy counts. Both variants require
hash-equal inputs, identical selected IDs and equal downstream quality. Neither
requires a new dataset.

### 15.7 Work That Does Not Close A Current Scoring Gap

| Proposed work | Decision now | Reason |
| --- | --- | --- |
| Keyword/tag benchmark | Do not add | The contest says keyword, tag **or** semantic retrieval; E3 formally covers semantic. |
| CodeAct-vs-DSL speed race | Do not add | E5 routes different task complexities to each path, and CodeAct is encouraged rather than a core pillar. |
| Prefix/APC optimization | Defer | It needs isolated service-state and TTFT evidence and does not repair C/N/M attribution. |
| LogitState | Defer | Zero canonical transfers and no current requirement gap justify a new research path. |
| New dataset / easier task family | Reject | It would break comparability and could manufacture an advantage. |
| Rerun E0-E6 unchanged | Reject | It consumes time without creating a new claim. |
| Demo video | Required delivery work, not an experiment | The repository audit found no submission video. |

Every new campaign must be registered as one question, one frozen comparison
and one acceptance rule before execution. Failed or interrupted attempts stay
visible; task membership cannot change after results arrive. New formal runs
must have a clean checkpoint identity, use local GPU embedding (operator may
assign host GPU 0 or 2, with the host-to-container mapping recorded), execute
inside the intended openEuler container, run serially, redirect output to logs
and wait silently for completion/error rather than frequent polling. vLLM
service start/restart remains an operator action, not an experiment script side
effect.

### 15.8 Non-Negotiable Reading Rules

1. Treat E1 L0->L3 `-47.40%` total tokens as the current full-stack efficiency
   result. Keep L0->L1 and L1->L2 adjacent tables beside it so component
   attribution remains honest.
2. Treat E3's one skipped LLM call, E1's two skipped steps and E2's two skipped
   steps as bounded evidence, never as a general replay/latency claim.
3. Preserve the distinction between StateRef's actual cross-PID consumption
   (already proved) and a carrier-only performance advantage (not isolated).
4. Do not use later July 23-24 development runs, new datasets or task changes
   to manufacture a favorable result. Any later formal experiment must record
   a clean source identity and preserve the same evidence slices.

## 16. Exhaustive Decision Inventory

The human tables above intentionally compress rather than discard the audit.
The derived ledger retains all 287 numeric case-report fields for E1 and E2,
all per-case source paths, all E3/E4/E5 adaptive records, and the complete
environment/capability identity. The useful surfaces are:

| Information family | Retained evidence | Questions answerable without a rerun |
| --- | --- | --- |
| Source/reproducibility | Git SHA/dirty flag, image digest, OS/Python, GPU mapping, model profile, task/validator/runtime digests, elapsed wrapper time | Which code/environment produced a number; whether two stages share an identity; what cannot be called clean replay. |
| Task/fairness | Task/family/lane/round, invariant digests, 40 gold-hidden audits, 160 rendered-role checks | Whether L0-L3 tasks and role boundaries match; which cases/families carry an aggregate. |
| Control plane | Messages, frames, request/response/control bytes, ACK, heartbeat, capability descriptors, handoff bytes | Wire savings, per-message overhead, protocol completeness and role-boundary size. |
| Model use | Per-role prompt/completion tokens and bytes, calls, wall time, scaffolding and prompt-visible payload categories | Which role receives the reduction; whether a saving comes from fewer calls or shorter prompts. |
| Planner semantics | Generated fields, valid plan, objective source, fallback fields, downstream consumed hashes and behavior effect | Whether typed planning changed execution or was repaired by runtime fallback. |
| Retrieval/pruning | Candidate pools, selected counts/bytes, keep/drop hints, hydrated bytes/items and estimated removed context | Where prompt reduction occurs and why L1/L2 is a joint semantic-path result. |
| Non-text state | Encoder/dimension/shape, backend, producer/consumer PID, publish/open/resolve/select/consume/release, bytes, hashes and scores | Whether an object is genuinely numeric, cross-process, decision-changing and lifecycle-closed. |
| Workspace/persistence | Input/output bundles, manifests, direct writes/reuse, integrity/reload spans, file counts | Observable mechanism overhead and which persistence substage dominates; not a causal speedup by itself. |
| ExecutionArtifactRef | Artifact size/hash/path, validator refs, settlement, quality gate, replay-ready flag, memory path and complete lineage | Whether output was verified before promotion and whether two artifacts share a blob. |
| Memory | Per-query candidates/channels/ranks/verdict/reasons, role-input records, memory IDs/roles/effects/classes, strict skipped work and registries | Candidate/use/effect/saved-work rates, negative rejection, consumed lineage and exact round timeline. |
| Adaptive execution | Planner normalization, selected capabilities, operation/family, generation attempts/repairs, bwrap identity, timeout/fallback, quality | Capability coverage, long tails and where model-quality repair occurs. |
| Failure provenance | Interrupted roots, failed quality gates, cleanup warnings and superseding canonical roots | Why a final run was selected and which regression/fault fixtures remain useful. |
| Deferred observability | Prefix estimates/service deltas and Logit sentinels | Why these fields do not establish Prefix or LogitState and what isolation a future study would need. |

Particularly useful zeroes are retained: no E1/E2 runtime/StatePool/sandbox
fallback, no exact/answer-restoration replay, no E1/E2 skipped LLM call, no E5
semantic or memory consumption, and zero LogitState transfer. Sentinel entropy
or peak values of `-1` are "not materialized," not negative measurements.

The baseline does **not** contain reliable TTFT/inter-token latency, exclusive
CPU time, copy-count/RSS profiles, a clean explicit model seed, balanced lane
order, a memory-OFF comparator or a same-selection carrier comparator. Those
are genuine missing measurements; they cannot be recovered by another JSON
aggregation pass. Everything else listed in this section should be queried
from the v6 ledger before proposing a rerun.

## 17. Source Files And Machine-Readable Ledgers

Human-readable source reports:

- `docs/reports/contest_recovery_baseline_asset_audit_20260724.md`


Container-root inventory:

```text
/home/qcrs/statebus/runs/contest_baseline_asset_audit_20260724_container/
  summary.md
  inventory.json
  document_index.jsonl.gz
  schema_catalog.json
  log_events.jsonl
```

Experiment-level evidence ledger:

```text
/home/qcrs/statebus/runs/contest_baseline_evidence_ledger_20260724_final/
  ledger.md
  ledger.json
  slice_records.jsonl.gz
  log_events.jsonl
```

Fixed-baseline derived metrics used by this compendium:

```text
tools/summarize_contest_fixed_baseline.py
/home/qcrs/statebus/runs/contest_fixed_baseline_derived_metrics_20260724.json
  schema_version = statebus.contest_fixed_baseline_derived_metrics.v6
```

The raw E0-E6 run roots remain under:

```text
/home/qcrs/statebus/runs/contest_evidence_closure_20260720/
```

Use this compendium as the baseline decision document. Consult the machine
ledger when a proposed slide or experiment needs per-case source paths or a
field-level audit rather than the aggregate numbers retained here.
