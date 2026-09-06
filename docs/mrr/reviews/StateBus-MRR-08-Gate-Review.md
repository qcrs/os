# StateBus MRR-08 Gate Review

## Review Scope

- Review role: Runtime / Artifact Truth correctness reviewer
- Slice: MRR-08 - Artifact / Evidence Truth
- Branch: `feat/mrr-08-artifact-evidence-truth`
- Review mode: read-only source and recorded-evidence review
- Production source changes in this review: none
- History/SHA audit: not performed
- Docker, vLLM, benchmark, competition validation, full pytest, and broad
  regression suites: not run

The review was performed against:

- `docs/mrr/batch3/MRR-08-Artifact-Evidence-Truth-Slice-Spec.md`
- `docs/mrr/batch3/StateBus-MRR-Batch3-State-Artifact-Truth-Deep-Design.md`
- `docs/mrr/batch3/StateBus-MRR-Batch3-Implementation-Plan.md`
- `docs/mrr/implementation/MRR-08-IMPLEMENTATION-RECORD.md`
- current MRR-08 source and focused tests
- the preceding `StateBus-MRR-07B-Gate-Review.md`

## Gate Verdict

```text
MRR-08_GATE_FAIL
```

The Runtime receipt seam is present and the primary MRR-08 evidence is
credible, but the current branch has one observed compatibility regression and
one source-level producer-path failure. MRR-08 must not be closed until both
are resolved and retested.

## Blocking Findings

### 1. Direct dispatcher summarizer regression

The canonical adaptive consumer correctly requires a Runtime-created
`ArtifactVerificationReceipt` in
`statebus/runtime/adaptive_dispatcher.py:1612-1639`. The existing
`test_runtime_owned_summarizer_validates_candidate_before_issuing_claimset_artifact`
constructs an input with only the legacy `verification_state=VERIFIED` field
and no receipt (`tests/test_adaptive_dispatcher.py:325-385`). The permitted
single targeted rerun failed:

```text
python -m pytest -q \
  tests/test_adaptive_dispatcher.py::test_runtime_owned_summarizer_validates_candidate_before_issuing_claimset_artifact

1 failed
```

The failure is `result.success == False` at the direct dispatcher call because
the input is rejected as not receipt-backed. This is not an unrelated baseline
failure: the MRR-08 diff changed `_artifact_in_grant_scope()` from accepting a
legacy `VERIFIED` projection to requiring a matching Runtime receipt. The
canonical Runtime path is intentionally stricter, but the existing direct
dispatcher contract/test was not migrated to that boundary. This is an
unresolved regression for the current test/API surface.

### 2. CodeAct quality-repair candidates cannot pass the verifier workspace gate

The Runtime calls verification with the exact original Attempt workspace at
`statebus/runtime/adaptive_runtime.py:1321-1333`. The verifier requires the
candidate root to be inside that workspace at
`statebus/runtime/artifact_verification.py:142-152`.

After a quality repair, `LlmCodeActRunner` materializes the repaired execution
in a sibling directory:

```text
attempt_workspace.parent /
  f"{attempt_workspace.name}-quality-repair-{len(repairs)}"
```

(`statebus/runtime/llm_codeact.py:742-748`). The resulting candidate therefore
has a root outside the verifier's exact Attempt workspace and is rejected with
`artifact_candidate_path_outside_workspace`. The path is fail-closed rather
than unsafe, but a supported CodeAct producer mode cannot promote a valid
quality-repaired result into verified Artifact truth. The existing quality
repair integration test (`tests/test_adaptive_codeact_integration.py:625-694`)
was not rerun because the one-test review allowance was already consumed; the
failure is established by the current source call chain.

## Mandatory Checklist

| # | Review item | Result | Source basis |
|---|---|---|---|
| 1 | Only an active, admitted producer Attempt may promote a candidate | PASS | `RuntimeArtifactVerificationAuthority.verify_candidate()` requires an admitted result and the Session's active Attempt. |
| 2 | Candidate and Verified are separate truth dimensions | PASS | `register_candidate()` forces `CANDIDATE`; only the Runtime verifier projects `VERIFIED`. |
| 3 | Verified does not imply replay eligibility | PASS | Candidate and verified projections both keep `replay_ready=False`; the receipt has no replay decision. |
| 4 | Verified does not imply Memory admission | PASS | Memory commit remains in the later adaptive mainline gate and is not called by the verifier. |
| 5 | Provider/dispatcher creates candidates, not authoritative Verified truth | PASS | Transform DSL, CodeAct, and summarizer paths return registered candidates; canonical promotion is in `adaptive_runtime.py`. |
| 6 | One Runtime verification seam is used for adaptive artifact outputs | PASS | `admit_attempt_result()` precedes `_verify_artifact_candidates()`, which promotes all `execution_artifact` output refs. |
| 7 | Physical/local result admission precedes artifact promotion | PASS | Verification is structurally after the `AttemptResultAdmissionReceipt` is obtained. |
| 8 | Active-Attempt freshness is checked at promotion time | PASS | `_validate_admission()` checks receipt decision, observed Attempt, active Attempt, and Session active pointer. |
| 9 | Candidate identity and provenance are exact | PASS | Task, Session, Step, Attempt, Grant metadata, artifact ID, state, type, and manifest are checked. |
| 10 | Candidate bytes are re-read and hash/size checked | PASS | `_validate_content()` resolves the path, rejects symlinks/escapes, re-reads bytes, and recomputes length and SHA-256. |
| 11 | Validator/quality evidence is bound to exact candidate bytes | PASS | `_validate_evidence()` requires matching report/audit hash, verified status, and candidate blob hash. |
| 12 | Verification receipt is immutable Runtime evidence | PASS | `ArtifactVerificationReceipt` is frozen and binds candidate hash, size, producer Attempt, Binding, Grant, and validator hashes. |
| 13 | Legacy `verification_state` is only a receipt-backed projection on canonical consumers | PASS | `_artifact_in_grant_scope()` requires both the receipt and the projected field. Legacy manager projection remains outside canonical adaptive authority. |
| 14 | Stale producer candidates remain unverified | PASS | Recorded stale-candidate evidence shows Attempt A rejected after Attempt B becomes active, with bytes retained as `CANDIDATE`. |
| 15 | Cross-Attempt consumption is not incorrectly forbidden | PASS | Consumer paths authorize input refs through the consumer Grant while matching producer provenance from the Runtime receipt; producer and consumer Attempt IDs need not be equal. |
| 16 | Manifest persists receipt evidence without becoming authority | PASS | `adaptive_mainline.py:968-974` serializes receipts; no manifest path issues a promotion decision. |
| 17 | All supported artifact-producing paths complete the seam without regression | FAIL | Primary path evidence passes, but CodeAct quality-repair candidates are outside the verifier workspace and the existing direct summarizer test fails without a receipt. |

## Source Contradiction

```text
NONE
```

The written MRR-08 design and the current canonical Runtime call order agree:
providers return candidates, Runtime admits the result, Runtime validates the
active Attempt and bytes/evidence, and Runtime creates the receipt. The two
blocking findings are implementation coverage/regression gaps inside that
boundary rather than a competing architecture decision.

## Test Rerun

```text
TEST_RERUN = ONE TARGETED TEST EXECUTED
```

Environment was activated with `./deploy/activate_statebus_host.sh` in the
StateBus host Conda environment. The single rerun was selected to distinguish a
canonical receipt contract from an existing direct-dispatch compatibility
regression. Result: `1 failed` as described above. No second targeted rerun was
performed.

Existing implementation evidence remains:

- `artifacts/mrr-08/artifact_verification_trace.txt`
- `artifacts/mrr-08/stale_candidate_rejection.txt`
- `artifacts/mrr-08/truth_dimension_separation.txt`
- `artifacts/mrr-08/targeted_tests.txt`

Those records show three primary tests and one adjacent dispatcher integration
passing, but they do not cover the quality-repair workspace path or the failed
direct summarizer compatibility test.

## Non-Blocking Observations

- Evidence Projection creates an intermediate candidate in
  `adaptive_dispatcher.py:1563-1585`, but returns its rows as transient input;
  it is not an `AdaptiveStepResult.output_refs` artifact and is not consumed as
  verified Artifact truth. This is acceptable for the current slice, but the
  transient/non-canonical status should remain explicit in future changes.
- `ArtifactLifecycleManager.mark_verified()` is still used by legacy
  `RuntimeCommitGate` and formal benchmark setup. Canonical adaptive consumers
  require a matching Runtime receipt, so this remains a compatibility boundary,
  not evidence that the legacy method is safe as adaptive authority.
- Candidate bytes are retained after stale Attempt rejection. Cleanup and
  garbage collection remain outside MRR-08.
- No replay eligibility, Memory admission redesign, State identity migration,
  or final task-adoption redesign was introduced by this review.
- Competition behavior remains unvalidated.

## Gates

```text
SOURCE_GATE_PASS
MECHANISM_GATE_FAIL
INTEGRATION_GATE_FAIL
COMPETITION_GATE_UNVALIDATED
```

The Source Gate passes for the authority separation itself. The Mechanism Gate
fails because the quality-repair producer path cannot complete Runtime
promotion. The Integration Gate fails because the current branch leaves an
existing direct-dispatch test/API path broken under the new receipt contract.

```text
MRR-08 STATUS = BLOCKED_PENDING_FIX
BATCH_3 STATUS = NOT_READY_FOR_GATE_REVIEW
NEXT_ALLOWED_SLICE = NONE
```

