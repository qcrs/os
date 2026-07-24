# Contest Recovery PPT Evidence Reconciliation

Date: 2026-07-24

## Scope

This document reconciles the two final presentation decks preserved in commit
`9c5d6f6` with the fixed E0-E6 baseline audited in
`contest_recovery_baseline_asset_audit_20260724.md`.

The reviewed decks are:

```text
StateBus-v2-答辩终版-06-字体最终统一版.pptx
StateBus-v2-答辩终版-07-演示化重构版.pptx
```

They share the same 25-slide argument. Deck 07 is visually reworked but does
not change the technical story. This is a content reconciliation, not a claim
that the PPT itself is evidence.

## Bottom Line

The intended story is correct and should remain the main line:

```text
typed control
  -> cross-process SemanticStateRef
  -> verified ExecutionArtifactRef
  -> compatibility-gated MemoryRef
```

Its value is not three independent features. It is a controlled state
promotion chain: a task is constrained before execution; a numerical state is
consumed under a manifest; an execution artifact is verified before it can
become memory; memory is compatible, consumed, and observed before it is
called reuse.

The existing baseline supports this story much better than the deck's old
"campaign pending" placeholders suggest. It does **not** support a blanket
end-to-end latency win, a token win for typed control alone, a transport-only
semantic-state win, broad memory acceleration, Prefix reuse, or LogitState.

## Slide-Level Reconciliation

| Slides | Current message | Evidence status | Required correction |
| --- | --- | --- | --- |
| 1-3 | Local multi-agent state-coordination problem | Compatible with the contest task | Keep. Avoid turning privacy/local deployment into the product claim. |
| 4 | Requirement / implementation / evidence separation | Correct principle, but evidence column is stale | Replace every `待 campaign` / `待汇总` with E1-E6 facts below. |
| 5-6 | One task traverses control, state, verified artifact, memory | Strong architecture narrative | Keep, but label `ExecutionArtifactRef -> MemoryRef` as a verified promotion rule, not automatic storage. |
| 8-9 | Typed control contracts, policy reject/replan | E0/E6 test gates and E1 fairness/Protobuf evidence support it | Keep as mechanism/safety proof. Do not claim lower tokens or lower end-to-end time from this alone. |
| 10-11 | Cross-PID numerical state | E4 strongly supports distinct PID, shared-memory StateRef, numeric top-k, receipt/release | Change `Selector PID` to `cross-process consumer worker (Executor retrieve-evidence step)`; source records name the consumer role `executor`. |
| 12-13 | Memory candidate -> approved -> consumed -> effect -> saved | E3 is strong; E1/E2 add natural continuous-chain evidence | Keep the funnel, but distinguish `history reuse`, `validated replay`, skipped step, and skipped LLM call. Do not call every candidate/hit/reuse a saved computation. |
| 14 | CodeAct as constrained Executor extension | E5 gives 25/25, 18 bounded-Python and 7 DSL executions | Keep as support, not a fourth contest pillar or a performance result. |
| 16 | Policy rejection / repair | E0/E6 and failure artifacts show engineering gate coverage | Keep as correctness/safety story; do not fabricate a reject-rate benchmark. |
| 17 | State provenance, integrity, lifecycle | E4 proves publish/open/consume/release across PIDs | Separate implemented lifecycle states from tested states. No canonical crash/orphan/expiry fault campaign is present. |
| 18 | Memory rebinding, compatibility, recompute/reject | E3 negative fixture directly supports reject + recompute | Do not imply exact answer restoration or unrestricted full replay; canonical exact replay count is zero. |
| 20 | Five-level evidence and paired baseline | This is the right evaluation philosophy | Change `seed fixed` to `model profile / temperature / timeout recorded`; E1 manifests record no explicit server seed (`seed=null`). |
| 21 | C/N/M experiment matrix | E1/E3/E4 now fill part of it | Replace `formal campaign 未完成` with the precise completed/incomplete matrix below. |
| 22 | L0/L1/T2/L2/L3 adjacent attribution | E1 has L0/L1/L2/L3; T2 is absent | Do not display a complete adjacent causal ladder. L1->L2 confounds semantic pruning and StateRef transfer; T2 is still the missing bridge. |
| 23 | Two 10-round chains, failure recovery, release, openEuler | E2, E3, E4, E5, E0/E6 fill much of it | Change openEuler status to `single-container OpenEuler E0-E6 verified`; keep VM, cross-machine, and general-Linux claims out. |
| 24 | Three evidence chains map to scoring | Correct structure | Use per-chain confidence labels. C has byte savings; N has mechanism proof; M has bounded actual savings. Do not imply all three have an L5 performance result. |

## What Can Be Filled Now

### C: Typed Control

Use E1's matched L0/L1 comparison:

| Metric | L0 text | L1 typed Protobuf | Interpretation |
| --- | ---: | ---: | --- |
| Control bytes | 25,196 | 4,270 | 83.05% lower |
| Total wire bytes | 36,069 | 11,200 | 68.95% lower |
| Prompt tokens | 29,876 | 30,737 | Not a token saving |
| Total tokens | 33,974 | 34,891 | Not a token saving |
| Quality | 10/10 per lane | 10/10 per lane | Quality floor held |

The correct slide statement is: **typed control removes wire overhead and
makes contracts inspectable/rejectable under matched conditions; it does not
by itself establish token or latency superiority.**

### N: Non-Text State

Use E4, with E1 as prompt-surface support:

```text
E4: 4/4 holdouts
  3 semantic narrative/mixed cases: shared-memory StateRef, producer PID != consumer PID
  1 table case: table/DSL control case, no semantic-state claim
  all semantic cases: numeric cosine top-k, selected IDs, decision-surface change,
                      receipt/release, gold hidden from roles

E1 L1 -> L2: 9 semantic-state transfers; prompt-visible bytes
              75,926 -> 14,353 over the 40-case matrix
```

The correct slide statement is: **the StateRef mechanism is real and consumed
across processes; its current data do not isolate shared-memory transport from
semantic pruning, and do not establish a latency win.**

### M: Shared Memory

Use E3 for the truth funnel and E2 for 10-round behavior:

```text
E3: query 6 -> candidate 16 -> compatible 15 -> approved 15
    -> consumption records 23 -> behavioral effects 23
    rejected incompatible 1; skipped step 1; skipped LLM call 1

E2: two L3 chains, 10 rounds each, 20/20 quality
    query 20 -> candidate 48 -> compatible/approved/consumed/effect 9
    rejected incompatible 39; skipped steps 2; skipped LLM calls 0
```

The correct slide statement is: **memory reuse is compatibility-gated and
observable; actual saved work is present but narrow, so it is not yet a broad
latency or cost claim.**

### Completeness And CodeAct

Use the following without inventing a new task set:

| Requirement-facing asset | Existing evidence |
| --- | --- |
| Four roles / dual modes | E0/E6 test gates plus E1 matched L0/L1/L2/L3 |
| Two associated 10-round task chains | E2, 20/20 L3 cases |
| Non-text state | E4, 4/4 holdout, cross-PID consumption and lifecycle closure |
| Memory reuse | E3 safety funnel; E1/E2 natural continuous-chain decisions |
| CodeAct encouragement | E5, 25/25; 18 bounded Python, 7 DSL, zero fallback |
| openEuler delivery | E0-E6 in the single openEuler 24.03 container |

## Claims That Must Be Removed Or Downgraded

1. Do not state that typed control saves tokens. The matched E1 data say the
   opposite for L0->L1.
2. Do not state that StateRef is faster end-to-end. E4 proves mechanism and
   lifecycle, not a fair transport latency comparison.
3. Do not equate candidate count, history-backed artifact reuse, or compatible
   match count with replay or saved work.
4. Do not state exact replay, answer restoration, hidden-state/KV transfer,
   Prefix reuse, or LogitState as validated baseline features.
5. Do not call bwrap a production-grade sandbox.
6. Do not say openEuler VM, cross-machine, arbitrary Linux, or open-domain
   generalization is verified.
7. Do not say a random seed was fixed for the E1 causal comparison. The
   recorded profile uses temperature 0 but no explicit server seed.

## Minimal Evidence Gaps From The PPT Itself

The deck already identifies the right missing pieces. The fixed baseline lets
us narrow them instead of expanding scope.

| Priority | PPT gap | Why existing data cannot answer it | Needed decision before implementation |
| --- | --- | --- | --- |
| 1 | T2 same-selection text bridge | E1 L1->L2 changes both selection/pruning and carrier | Decide whether the non-text story needs a transport-only causal claim, or only the E4 mechanism claim. |
| 2 | Fair latency result | Existing timings have fixed order and no balanced serial reruns | Decide whether latency is a headline claim; the contest asks for it, but a weak comparison is worse than an honest bounded result. |
| 3 | Memory saving attribution | E3 has one skipped LLM call; E1/E2 have none | Decide whether to make memory safety/reuse the primary claim and quantify savings only where observed, or add a narrow matched actual-use comparison. |
| 4 | C parse/reject measurement | Tests prove behavior, not a comparative parser/reject performance result | Decide whether raw bytes plus safety tests already satisfy the deck, or whether parse/reject needs an explicit small report. |
| 5 | Lifecycle fault coverage | Release is observed; orphan/expiry/crash recovery is not a canonical campaign | Decide whether the deck shows lifecycle architecture only, or promises fault-path empirical coverage. |

Prefix and LogitState are deliberately not on this list. They do not close any
of the deck's existing evidence gaps. Adding them now would make the story
less coherent and consume time that should go to a fair T2/latency/memory
decision.

## Recommended Presentation State Before Any New Experiment

The presentation can now be made factually strong with this split:

```text
Already earned
  C: typed control lowers control and wire bytes at equal quality
  N: a numerical StateRef is consumed by another PID and released correctly
  M: memory reuse is gated, rejected when incompatible, and sometimes saves work
  Integration: four roles, two 10-round chains, 25 formal cases, openEuler container

Still open
  transport-only StateRef advantage
  fair latency superiority
  broad memory acceleration
```

This turns the deck from a feature tour into an honest systems argument. The
next experiment discussion should choose whether the remaining work is one
T2-plus-balanced-latency campaign, one narrow memory-attribution campaign, or
both. It should not reopen datasets, Prefix, or LogitState.
