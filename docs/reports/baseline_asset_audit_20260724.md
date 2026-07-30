# StateBus Baseline Asset Audit

Date: 2026-07-24

## Purpose And Boundary

This document fixes the factual starting point for the recovery branch before
choosing any new experiment. It answers only four questions:

1. What experiment artifacts already exist?
2. Which artifacts are canonical evidence, and which are retries, failures, or later development output?
3. What does each canonical experiment actually demonstrate?
4. What evidence is still absent or too weak to support a claim?

No benchmark, test, model request, vLLM operation, or experiment workload was
started to create this document. The only new work was read-only extraction of
existing artifacts, performed inside the already-running container where root
ownership was required to read the complete artifact tree.

This is an asset audit, not a new performance report. A metric is not promoted
to a claim unless its comparison boundary supports that interpretation.

## Baseline Identity

| Item | Recorded fact |
| --- | --- |
| Active recovery branch | `contest/recovery-core` |
| Recovery HEAD | `bda17745ecb8a160221efe3b58ca678644dac81a` |
| Artifact root | `/home/qcrs/statebus/runs/contest_evidence_closure_20260720` |
| Recorded experiment Git SHA | `a3a5ec836d13c5e9d77811edd25d58d24af227b6` |
| Relationship | `a3a5ec8` is an ancestor of `bda1774` |
| Experiment worktree state | `git_dirty=true` in each canonical manifest |
| Container | `statebus-dev-qcrs`, `openEuler 24.03 LTS-SP3` |
| Role model | `qwen3-32b` through local vLLM |
| Embedding model/device | `Qwen3-Embedding-0.6B`, `cuda:0` |
| Execution order | canonical manifests record `serial_execution=true` |

The ancestor relationship means the recovery baseline is downstream of the
recorded experiment commit. The dirty-worktree flag means it is not valid to
describe `bda1774` as a bit-for-bit replay source for the July 20 artifacts.
Any new formal evidence must record a clean source identity of its own.

## Audit Method And Completeness

Two read-only tools were added:

- `scripts/evidence/audit_baseline_assets.py`
  - indexes every reachable file and directory;
  - parses every JSON/JSONL source, extracts schema/field/metric indexes and
    log events;
  - checks every run-local `checksums.sha256` relative to its own run root;
  - records permission and parse errors rather than skipping them.
- `scripts/evidence/extract_baseline_ledger.py`
  - extracts root manifests, environment, fairness, capability registry,
    summaries, audit slices, root logs, and non-canonical outcomes into a
    review ledger.

The first host audit found 36 unreadable paths. They were all root-owned
`semantic_state_views` directories under later July 23 development runs, not
under E0-E6. The same audit was then run in `statebus-dev-qcrs` as root:

```text
64,472 files
61,682 JSON/JSONL documents
0 scan/read errors
```

Canonical checksum verification also completed without a mismatch:

| Run | Checked entries | Success | Failure | Unreadable |
| --- | ---: | ---: | ---: | ---: |
| E0 | 21 | 21 | 0 | 0 |
| E1 | 2,726 | 2,726 | 0 | 0 |
| E2 | 1,454 | 1,454 | 0 | 0 |
| E3 | 131 | 131 | 0 | 0 |
| E4 | 113 | 113 | 0 | 0 |
| E5 | 495 | 495 | 0 | 0 |
| E6 | 21 | 21 | 0 | 0 |
| Total | 4,961 | 4,961 | 0 | 0 |

Machine-readable outputs are intentionally outside Git:

```text
/home/qcrs/statebus/runs/contest_baseline_asset_audit_20260724_container/
  summary.md
  inventory.json
  document_index.jsonl.gz
  schema_catalog.json
  log_events.jsonl

/home/qcrs/statebus/runs/contest_baseline_evidence_ledger_20260724_final/
  ledger.md
  ledger.json
  slice_records.jsonl.gz
  log_events.jsonl
```

The inventory has every source path, size, mtime, SHA-256, parsed-document
projection, schema catalog, checksum result, and error boundary. The ledger
keeps the readable experiment-level view without discarding raw source paths.

## Artifact Layout

Every canonical E0-E6 root has the common envelope:

```text
run_manifest.json        environment.json       fairness_manifest.json
capability_registry.json summary.json           summary.md
pytest.log               console.log            wrapper.log
checksums.sha256
case_reports/            role_requests/         state_consumption/
memory_queries/          memory_consumption/    replay_decisions/
artifact_lineage/        runtime/               workspaces/
```

The seven audit-slice directories are not decorative. For every materialized
case they preserve: case result, rendered role request, actual state consumer,
memory query, actual memory consumption, replay decision, and artifact
lineage. E0/E6 are engineering gates, so their one-record-per-slice payloads
are placeholders; E1-E5 carry suite-native case evidence.

## Full Root Classification

| Class | Run groups | Files | JSON/JSONL | Meaning |
| --- | ---: | ---: | ---: | --- |
| Canonical | 7 | 4,968 | 4,695 | Formal E0-E6 only |
| Known non-canonical | 15 | 6,797 | 6,374 | Failures, retries, overlap, or diagnostics |
| Pre-canonical | 7 | 1,503 | 1,425 | Earlier closure work, not headline evidence |
| Later/development | 27 | 51,203 | 49,188 | July 23-24 development material; quarantined from this baseline |
| Root metadata | 1 | 1 | 0 | `.formal_stage.lock` |

The later/development roots are retained but excluded from baseline aggregation:

```text
development-adaptive-gpu0-20260723a/b
development-adaptive-memory-gpu0-20260723a
development-causal-current-20260723a/b/c
development-memory-anchor-20260723b/c
development-semantic-holdout-current-20260723a
development-semantic-holdout-paramfix-20260723a
development-semantic-holdout-promptv2-20260723a
development-semantic-holdout-promptv2-gpu0-20260723a
development-stress-current-20260723a
fresh-adaptive-memory-gpu0-20260723a
fresh-causal-gpu0-20260723a
fresh-flagship-gpu0-20260723a/b
fresh-full-regression-gpu0-20260723a
fresh-numeric-carrier-gpu0-20260723a
fresh-semantic-holdout-gpu0-20260723a
fresh-stress-gpu0-20260723a
fresh-structured-control-gpu0-20260723a
full-adaptive-fresh-gpu0-20260723a
targeted-formal-fixes-gpu0-20260723a
targeted-summarizer-fixes-gpu0-20260723a
focused-m2-n3-20260724
focused-memory-latency-20260724
```

They may later be mined for debugging context, but they must not be used to
replace, improve, or silently aggregate the fixed E0-E6 baseline.

## Canonical Evidence Map

| Stage | Exact structure | Materialized slice records | Established result | Correct use |
| --- | --- | ---: | --- | --- |
| E0 | focused tests + deterministic preflight | 7 | `135 passed`; preflight OK | Engineering gate |
| E1 | 2 families x 5 rounds x L0-L3 | 280 | 40/40 quality; matched causal matrix | Control/state/memory mechanism comparison |
| E2 | 2 families x 10 rounds, L3 only | 140 | 20/20 | Continuous-task stability and memory behavior |
| E3 | 5 financial cases + 1 incompatible-memory negative case | 42 | 6/6 | Memory truth funnel and fail-closed rejection |
| E4 | 3 semantic holdout + 1 table holdout | 28 | 4/4 | Cross-process semantic StateRef consumption |
| E5 | 25 formal cases, five task families | 175 | 25/25 | Adaptive registry and CodeAct coverage |
| E6 | full `tests` + deterministic preflight | 7 | `558 passed, 100 warnings`; preflight OK | Regression gate |

### E0 And E6: Engineering Gates

E0 and E6 are useful for stability and delivery completeness, not for a
performance headline. Root logs record `135 passed` for E0 and `558 passed`
for E6. E6 retains 100 warnings; the pass result does not erase them.

### E1: Matched L0-L3 Causal Matrix

E1 is the main comparison asset. It uses two repo-local financial-analysis
families, five continuous rounds per family, and four layers under one
serialised, subprocess topology. The fairness manifest records the intended
single-variable ladder:

```text
L0: text collaboration, utf8_text carrier
L1: structured collaboration, Protobuf carrier
L2: L1 + semantic pruning + shared-memory StateRef transfer
L3: L2 + compatibility-gated memory/replay
```

The manifest freezes the capability surface, task contracts, role graph,
model profile, external-gold visibility audit, and per-case runtime signature.
It records `comparison_valid=true`; this is the strongest existing fairness
asset.

Aggregate telemetry across the full 40-case matrix is already present in the
source summaries:

| Layer | Control bytes | Total wire bytes | LLM prompt bytes | Prompt tokens | Total tokens | Prompt-visible bytes | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 25,196 | 36,069 | 130,676 | 29,876 | 33,974 | 75,926 | 40 |
| L1 | 4,270 | 11,200 | 126,406 | 30,737 | 34,891 | 75,926 | 40 |
| L2 | 4,507 | 11,827 | 56,326 | 13,599 | 17,739 | 14,353 | 40 |
| L3 | 5,357 | 12,677 | 57,738 | 13,885 | 17,870 | 15,847 | 40 |

What this supports:

- L0 to L1: structured control reduces control bytes by 83.05% and total
  wire bytes by 68.95% under the matched topology.
- L1 to L2: nine observed semantic-state transfers coincide with a large
  reduction in prompt-visible evidence and prompt tokens.
- L2 to L3: two actual memory consumptions produced two behavioral effects
  and two skipped steps in the financial family.

What it does not support:

- L0 to L1 does not reduce token use: prompt tokens rise 2.88% and total
  tokens rise 2.70%.
- L2 changes both semantic pruning and semantic-state transfer, so it is not
  a clean transport-only ablation.
- L3 has 40 LLM calls, so E1 does not show LLM-call reduction.
- Per-case timing telemetry exists, but lane order was fixed and not repeated
  in reverse/random order. It is descriptive telemetry, not a latency
  superiority result.

### E2: Two 10-Round Continuous Chains

E2 is not a second four-layer comparison. It runs L3 only: two associated task
families for 10 rounds each, 20/20 quality passes.

Its memory funnel is:

```text
query 20 -> candidate 48 -> compatible 9 -> approved 9
-> consumed 9 -> behavioral effect 9
rejected incompatible 39
skipped steps 2; skipped LLM calls 0
```

The artifact also records 44 history-backed artifact reuses, but that is not
44 replay events. Only two validated replay events exist, both in the
financial family. E2 therefore supports stable 10-round execution and
fail-closed memory behavior, not an end-to-end latency or broad replay claim.

### E3: Memory Truth Funnel And Negative Gate

E3 contains five financial cases and one deliberately runtime-incompatible
memory fixture. Each new case uses a fresh Runner against the same family
store. It proves six verified commits and records:

```text
query 6 -> candidate 16 -> compatible 15 -> approved 15
-> consumed records 23 -> behavioral effects 23
rejected incompatible 1
validated replay 1; skipped step 1; skipped LLM call 1
```

The consumption count exceeds the compatible-match count because one approved
memory may be consumed by more than one real role. The negative fixture is
visible in the candidate pool, has an incompatible runtime signature, is
absent from role inputs, is not consumed, and forces recomputation with a
verified current output. Commit records explicitly state
`benchmark_gold_used=false`.

This is the strongest existing evidence for the *correctness and safety* of
memory reuse. It is not evidence of broad time reduction: one skipped LLM call
is observed here, while E1/E2 report zero skipped LLM calls.

### E4: Non-Text Semantic State Across Processes

E4 freezes the relevant Runtime content by a 59-file dirty-worktree hash
ledger, then runs four holdout cases:

| Case | Input shape | Retriever | Executor | Semantic StateRef | Quality |
| --- | --- | --- | --- | --- | --- |
| S1 | narrative only | semantic | bounded Python | yes | pass |
| S2 | narrative only | semantic | bounded Python | yes | pass |
| S3 | table only | table | DSL | no | pass |
| S4 | narrative + table | semantic | bounded Python | yes | pass |

For semantic cases, source records show a producer PID distinct from executor
consumer PIDs, shared-memory state references, numeric cosine top-k selection,
changed input/output decision-surface hashes, selected candidate IDs, and
release records. The benchmark oracle is explicitly hidden from role requests.

This supports non-text state generation, cross-process transfer, reception,
numeric consumption, and lifecycle closure. It does not compare shared memory
against an equal-quality serialized-vector transport, nor does it establish
an end-to-end latency improvement.

### E5: Adaptive Registry And CodeAct Coverage

E5 runs all 25 formal cases across five families:

```text
financial report extraction: 8
multi-period trend:          5
cross-table join:            5
conditional aggregation:     4
anomaly detection:           3
```

All 25 quality gates pass. The fixed six-capability registry records:

| Capability outcome | Count |
| --- | ---: |
| table retrieval | 25 |
| bounded Python / CodeAct verified | 18 |
| DSL verified | 7 |
| claim-set composition | 23 |
| risk-memo composition | 2 |
| model/runtime/sandbox fallback | 0 |

The bounded-Python records are bwrap-backed and record UID/GID `65534:65534`.
E5 proves adaptive capability selection and outcome correctness on the fixed
registry. It is not a component-isolated CodeAct performance comparison, and
the source itself sets `latency_superiority_claim_allowed=false`.

## Preserved Failure And Retry Evidence

Failures were not deleted. They explain why only the final named roots are
canonical:

| Root(s) | Observed outcome | Baseline treatment |
| --- | --- | --- |
| `focused_20260720_140122` | 133 passed, 1 adaptive planner capability-prompt failure | Excluded; E0 later reached 135 |
| `causal_20260720_142709` | 40/40 but overlaps E0 timing | Excluded from serial formal evidence |
| `e1_causal_20260720_143554` | child exit `-15` | Excluded; fresh E1 used |
| `stress_20260720_145740` | child exit `-15`, shared-memory cleanup warning retained | Excluded; fresh E2 used |
| `e3_adaptive_memory_serial_20260720_154048` | 5/6; negative gate not closed | Excluded; E3 final is 6/6 |
| E4 retries `serial`, `final`, `final2`, `final3` | 1/4, 2/4, 3/4, 2/4 | Excluded; only `final4` is 4/4 |
| `e5_adaptive_serial_20260720_180846` | 24/25; `formal-agg-002` quality rejection | Excluded; single-case probe and E5 final retained |
| `e6_full_serial_20260720_195042` | 555 passed, 3 failed; preflight still passed | Excluded; E6 is 558 passed |
| `e6_memory_slice_probe_20260720_200735` | diagnostic input visibility probe | Not replay evidence |
| phase-5 focused runs | old adaptive planner prompt assertion failure then follow-up | Historical only |

The extracted root logs preserve the named failed tests for the failed focused
and full suites. The `ledger.json` retains each retry summary and failure
classification, rather than replacing it with a success-only narrative.

## Assets That Are Reusable Without Rerunning Old Work

1. **Matched causal task suite and fairness manifests.** E1 supplies the
   tasks, case order, L0-L3 feature flags, model profile, registry digest,
   source-task manifest hash, and gold-visibility audit.
2. **Continuous-chain task suite.** E2 supplies two 10-round families and
   memory/replay decision schemas.
3. **Memory safety fixtures.** E3 supplies verified commit lineage and a
   runtime-incompatible negative fixture.
4. **Non-text state fixtures.** E4 supplies narrative/table holdouts,
   StateRef metadata, cross-PID consumer records, decision-surface hashes, and
   lifecycle events.
5. **Formal CodeAct set.** E5 supplies a 25-case five-family registry, both
   DSL and bounded-Python examples, and quality contracts.
6. **Telemetry schema.** All E1-E5 roots supply the same seven audit slices,
   so a new experiment can reuse the evidence format rather than inventing a
   new logging surface.
7. **Failure corpus.** The 15 non-canonical roots are valuable regression and
   truth-boundary data, but must remain separate from headline aggregation.

## Evidence Gaps: Do Not Paper Over These

These are inventory findings, not yet a proposed experiment plan.

| Question | Existing asset | What is missing or confounded |
| --- | --- | --- |
| Structured communication reduces bytes | E1 L0/L1 is matched and strong | Token reduction is not shown; L0/L1 tokens rise |
| StateRef is genuinely non-text and cross-process | E4 is strong | No transport-only ablation or fair state-transfer latency comparison |
| Semantic state reduces prompt burden | E1 L1/L2 shows prompt reduction | L2 jointly enables pruning and transfer, so attribution is not transport-only |
| Memory is real and safe | E3 is strong; E1/E2 show natural use | Broad latency/LLM-call saving is not shown; replay must not be inflated from candidate/reuse counts |
| Ten-round stability | E2 shows 20/20 L3 cases | It does not establish stability of every L0-L3 layer |
| End-to-end latency advantage | Timing fields exist in E1/E2/E5 | No randomized/reversed serial repeats, warmup policy, or causal timing conclusion |
| Overall efficiency improvement | Bytes, prompt surface, steps and calls exist | No single fair composite metric or causal end-to-end gain is justified yet |
| CodeAct value | E5 gives 25/25 and 18 verified Python executions | No comparison proving CodeAct is faster or more accurate than a fixed alternative |
| Prefix reuse | Telemetry contains estimate/counter fields | No canonical prefix-reuse implementation experiment or formal causal claim |
| LogitState | Some telemetry fields exist and are zero in the E1 matrix | No canonical LogitState mechanism experiment or claim |
| Environment portability | OpenEuler container evidence exists | No openEuler VM, cross-machine, or general-Linux claim |

The last two rows are especially important for recovery scope: do not turn
observability fields such as `vllm_prefix_*`, estimated prefix savings, or
zero-valued `logit_state_*` fields into a baseline capability claim. The fixed
baseline has no canonical experiment designed to validate prefix optimization
or LogitState.

## Reading Order Before Designing Anything New

1. This audit for the claim boundary and asset map.
2. `/home/qcrs/statebus/runs/contest_baseline_evidence_ledger_20260724_final/ledger.md`
   and `ledger.json` for every root summary, manifest and log event.
3. `/home/qcrs/statebus/runs/contest_baseline_asset_audit_20260724_container/summary.md`
   and `inventory.json` for every source path and integrity record.

The next discussion should start from these gaps and the presentation story:
which existing asset becomes a slide, which claim is already earned, and which
small number of new fair experiments are truly necessary. It should not start
by adding datasets, prefix work, or LogitState work.
