# Contest Completion And Delivery Audit

## Scope And Decision

This is a static, derived completion audit against `docs/reference/题目.md`. It
does not rerun a test, benchmark, model request, or validator, and it does not
modify runtime code, tests, gates, or retained run artifacts. Its evidence is
the P0/P1 evidence package already indexed by
`scripts/analyze_qwen3_p0_p1_experiment_evidence_20260715.py`.

The contest objective has three distinct completion states. They must not be
collapsed into one pass/fail label:

| State | Decision | Reason |
| --- | --- | --- |
| Functional prototype | partially complete | The repository has the required architectural surfaces and recorded executions of the main paths. |
| Experimental proof | partially complete | The ledger contains 948 primary normalized records, but several causal and fairness claims remain bounded. |
| Final contest delivery | not complete | No audited final openEuler delivery run exists; a demo-video deliverable is not evidenced; P0 and P1 remain historically non-all-pass. |

The safe external description is: **a four-role StateBus v2 prototype with
typed control, StateRef-backed semantic state, memory/replay, and recorded
P0/P1 executions**. It is not yet defensible to describe the package as a
fully validated openEuler final delivery, a pure-carrier performance win, or
agent-to-agent KV/hidden-state transfer.

Evidence levels are cumulative: `1` code definition, `2` executed path, `3`
retained raw runtime data, `4` recorded downstream behavior, and `5` repeated
fair A/B benefit. A level describes this evidence package, not a guarantee
about unobserved current behavior.

## Historical Integrity

The stage index contains 19 labels (`00` through `18`) and 18 user-level
experimental units (`01` through `18`); `00_preflight` is a precondition,
not an experiment. The later pytest-only repair is separate and was stopped
after Stage 02.

| Record | Historical status | Completion consequence |
| --- | --- | --- |
| P0 labels `00-15` | `01_pytest_v2` failed; 15/16 labels passed | P0 is complete as a record, not an all-green 16-stage matrix. The later 320-pass log supports only the repaired pytest conclusion. |
| P1 labels `16-18` | Stages 16-17 passed; Stage 18 failed | The four Stage 18 request pairs exist and pass the repaired static verifier, but this is `post_run_validator_repair`, not a historical rerun or status rewrite. |
| Current source tree | has later user changes | Current code is not evidence of the historical run except where the original audit labels it as post-run validation code. |

The provenance and counting basis are in `00_scope_and_run_index.md`; stage
status reconciliation is in `03_stage_integrity_matrix.csv` and
`04_full_experiment_truth_audit.md`.

## Requirement Completion Matrix

The machine-readable companion is `06_contest_completion_matrix.csv`. The
matrix below uses the competition requirement rather than a feature-list
interpretation. "Partially proven" therefore means the required surface or
path has evidence, but not all of the required effect, fairness, or delivery
conditions are established.

| Requirement | Completion | Level | What the evidence supports | Remaining boundary |
| --- | --- | ---: | --- | --- |
| At least three agents and three role types, completing multi-step work | partially proven | 3 | P0/P1 task and rendered-request evidence records Planner, Retriever, Executor, and Summarizer roles across multi-step task families. | Per-role call presence does not isolate a useful behavioral contribution; historical P0 pytest remains failed. |
| Structured communication with action, parameters, result, and capability/handshake | partially proven | 3 | Typed UDS/subprocess transport is exercised in P0 Stage 07 and P1 `memfd_subprocess`; control implementation is indexed in `v2/control/transport.py`. | Not every role and backend crosses a process boundary; functional transport is not a performance proof. |
| Text and structured collaboration modes under the same task condition | partially proven | 3 | P0 Stages 02, 06, 11-14 and P1 controls retain system-level text/structured comparisons. | Semantic selection, prompt layout, helpers, tools, and carrier change together in several comparisons. This is not a single-variable carrier result. |
| Non-text state generation, transfer, receipt, and subsequent use | partially proven | 3 | StateRef publication, transfer, receiver hydration, and three backend variants are retained. Runtime events total `STATE_PUBLISHED=1380` and `STATE_HYDRATED=4140`. | `STATE_CONSUME=0`; no role-attributed behavior effect proves downstream use. The state is not an LLM hidden-state or KV tensor handoff. |
| Memory units with required metadata | implemented, execution evidence bounded | 2 | `v2/memory/models.py` and `v2/memory/store.py` define memory ID, source agent, creation time, task theme, summary, and tags; P0/P1 replay and memory artifacts use the memory path. | The retained matrix does not independently prove every metadata field for every task or that each field affects an outcome. |
| Keyword, tag, and semantic retrieval of memory | implemented, execution evidence bounded | 2 | `v2/memory/store.py` defines keyword and tag retrieval; the memory/replay paths are represented in the recorded artifact ledger. | This audit does not establish a complete independent A/B of each retrieval mode or general retrieval quality. |
| Cross-task memory reuse | partially proven with class boundary | 4 | P0 Stages 03-05 and P1 Stage 17 retain memory/replay classes, output restoration, and selected call/token/reuse fields. | A memory match or validated replay is not automatically a skipped LLM/tool step or a positive `reuse_gain`; claims remain per replay class and case. |
| Two related continuous task groups and at least ten rounds | partially proven | 3 | P0 Stages 04-05 retain continuous-family and round evidence. | Family-specific results cannot be promoted to all workloads; the matrix is historically non-all-pass. |
| Communication, token/byte, state, latency, and reuse metrics | partially proven | 3 | Case, role, and stage ledgers preserve additive fields and recompute ratios without zero-filling missing values. | StateRef consumption and LogitState bytes are not persisted; timing superiority requires matched serialized reruns. |
| Runtime, protocol, state exchange, memory, and evaluation modules | partially proven | 3 | Source surfaces and P0/P1 execution paths cover runtime, typed control, statepool, memory/replay, and benchmark/evaluation. | The complete recorded matrix is not all green; no aggregate subsystem claim substitutes for its individual contracts. |
| CodeAct support and isolation | prototype only | 3 | A fallback-aware CodeAct/sandbox path and related telemetry are present. | No independent security evaluation, nsjail proof, or final openEuler isolation validation is retained. CodeAct is encouraged, not a core requirement. |
| Source, design, deployment, report, and demo-video submission package | incomplete | 1 | Source, design/reference documents, deployment material, and this experiment audit exist in the repository. | No immutable evidence of the required demo-video deliverable was located in the audited package; a reviewed submission manifest is absent. |
| openEuler 24.03-LTS-SP3 compile/run/test delivery | not proven | 2 | A prior container-boundary document and container-oriented paths exist. | The P0/P1 evidence roots contain no final openEuler VM delivery validation, so the contest delivery requirement cannot be claimed. |

## Evidence By Scoring Dimension

This is not a fabricated numerical score. It is a readiness assessment against
the published dimensions.

| Dimension | Evidence condition | Current readiness | Claim boundary |
| --- | --- | --- | --- |
| Communication efficiency (25) | Same-task token/byte comparison plus fair latency control | partial | Serialized P0 comparisons retain lower token totals, but all three task-time deltas are unfavorable and the source explicitly disallows latency-superiority. Carrier-only attribution is not identified. |
| State-transfer innovation (20) | Non-text object is generated, transferred, received, consumed, and shown useful | partial | Semantic StateRef is published, transferred, and hydrated. No distinct consume event or behavior-changing perturbation is retained. LogitState is telemetry only. |
| Memory reuse (20) | Cross-task reuse with verified output and real reduction | partial, strongest of the causal evidence | Exact/validated replay classes and restoration evidence exist, but class labels, skipped steps, calls, tokens, and `reuse_gain` must remain separate. |
| System completeness (20) | Multi-role runtime, protocol, statepool, memory, evaluation, stable execution | partial | The system surface is broad and its paths are exercised. Historical P0 pytest and P1 Stage 18 remain non-pass, and final openEuler delivery is unproven. |
| Experimental validation (15) | Reproducible, fair, quality-controlled comparisons | partial | The audit has complete input inventory, raw-field ledgering, and ratio recomputation. Fair single-variable carrier and clean-service timing proof are still missing. |

## Claim Cards

### Claims That Are Safe Now

- The P0/P1 audit indexed all three evidence roots, including 948 primary
  normalized records, and kept historical stage statuses immutable.
- StateBus v2 records four named role paths and typed UDS/subprocess execution
  evidence.
- Semantic StateRef publication, transfer, and receiver hydration are recorded
  for file-backed/shared-memory-related paths; the backend matrix functionally
  exercises `mmap`, `shared_memory`, and `memfd` variants.
- The repository has memory/replay execution evidence, including exact and
  validated replay classes subject to their per-case call/output boundaries.
- The P1 Stage 18 pair artifact passes the repaired static verifier, while the
  original Stage 18 status remains `fail`.

### Claims That Must Not Be Made

- P0 was a new all-green 16-stage matrix, or P1 Stage 18 was rerun and passed.
- The typed carrier alone caused token, latency, or quality improvement.
- StateRef proves behavior-changing downstream use, agent-to-agent KV transfer,
  hidden-state handoff, or cross-engine reuse.
- LogitState transferred a neural tensor or changed routing, tool use, retry,
  fallback, quality, or efficiency. There are 848 positive transfer-count rows
  but zero persisted `logit_state_bytes` values, no retained ref registration,
  receiving role, consumption event, or A/B.
- Prefix evidence proves end-to-end workload speedup or agent KV transfer. It
  only supports a bounded engine-local vLLM prefix-reuse reading, and the P1
  window was continuous rather than per-repeat clean-service.
- The current package is a final openEuler 24.03-LTS-SP3 delivery or a
  production-grade CodeAct sandbox.

## Prioritized Problem Analysis

| Priority | Problem | Why it blocks a stronger conclusion | Minimum corrective evidence needed |
| --- | --- | --- |
| Blocker | Final delivery proof is absent | The contest explicitly requires openEuler compile/run/test; the audited P0/P1 roots do not contain final VM delivery evidence, and the demo-video deliverable is not evidenced. | Versioned openEuler delivery bundle, immutable logs/artifacts, source/design/deploy/report/video manifest, and reviewer-readable reproduction instructions. |
| Blocker | Historical matrix is not all green | P0 has a failed pytest label and P1 has a failed Stage 18 label. Later evidence cannot rewrite either historical summary. | Preserve history; run and label a new complete matrix only after targeted regressions are repaired. |
| Blocker for state-effect claim | StateRef lacks consumption provenance | Hydration can occur while a role ignores the object. `STATE_CONSUME=0` leaves the required "subsequent use" step unproved. | Role/ref/field consumption event linked to route/tool/output plus StateRef on/off or perturbation A/B. |
| High | Text/structured comparison is multi-variable | Selection, visibility, prompt layout, helpers, tools, and carrier are not frozen together. | Serialized AB/BA matched-control repeats with the same task, model, evidence, tools, scorer, and output contract. |
| High | Timing result contradicts a speedup headline | The three serialized P0 repeats record `0/3` favorable task-time deltas and an explicit `latency_superiority_claim_allowed=False`. | A fresh matched timing protocol with service/load policy, medians, and tail distribution; do not use current token data as latency proof. |
| Medium | Memory/replay terminology can overstate savings | A match, assist, validated replay, exact replay, restored output, and skipped work are different facts. | Per-case source/target identity, output/artifact hash, call/token/tool delta, and `reuse_gain` consistency. |
| Medium | Prefix evidence has service-window confounding | `clean_service_requested=false`; warm cache and order can explain a local TTFT observation. | Clean and continuous cohorts, four AB/BA pairs per corpus, before/after counters, and scoped engine-local claim. |
| Medium | LogitState is not an end-to-end mechanism | Telemetry fields do not record persisted bytes or a receiver/consumer/decision chain. | Persist payload length/hash, ref registration, receiver hydrate/consume, enabled flag, and matched on/off result. |
| Medium | Generalization and taint boundary remains narrow | Holdout uses a precompiled CanonicalTaskSpec, and lexical taint hits require role-aware provenance before they can be called leaks. | No-oracle free-text task-contract holdout, role-aware prompt review, and explicit fallback/route provenance. |

## Completion Sequence

No validation is run by this audit. The following is the minimum order for
future work, because later experiments depend on the earlier contracts.

1. Preserve the P0/P1 histories and add targeted regression evidence for
   role-call accounting, Stage 18 verifier provenance, metric aggregation, and
   replay accounting.
2. Instrument StateRef consumption and LogitState provenance before measuring
   their claimed benefits.
3. Freeze a matched text-versus-structured contract, then collect serialized
   AB/BA quality, token, and timing evidence under documented cache policy.
4. Run clean and continuous prefix cohorts separately; keep their results as
   engine-local prefix evidence.
5. Produce an immutable openEuler final-delivery bundle and submission manifest
   only after the preceding targeted contracts hold. Include the demo video in
   that manifest rather than treating a source file as evidence of delivery.

## Evidence Index

- `00_scope_and_run_index.md`: roots, historical-status boundary, and run
  counts.
- `01_artifact_inventory.json` and `.md`: complete static artifact inventory,
  parse coverage, hashes, empties, and exclusions.
- `02_stage_layer_family_case.csv`, `02_role_case_metrics.csv`, and
  `02_normalized_evidence_ledger.json`: case- and role-level raw evidence.
- `03_contest_coverage_matrix.csv`: original requirement-to-code/run/fairness
  mapping.
- `03_mechanism_evidence_matrix.csv`, `03_prefix_pair_validation.csv`, and
  `03_logitstate_participation_matrix.csv`: mechanism and boundary evidence.
- `04_full_experiment_truth_audit.md`: authoritative P0/P1 truth report.
- `05_issue_ledger.csv` and `05_issue_and_minimum_validation_plan.md`:
  detailed repair and validation risks.
