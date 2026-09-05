# MRR-08 — Artifact / Evidence Truth — Slice Spec v2

## Type

IMPLEMENTATION SLICE

Recommended dependency:

```text
MRR-07A/07B accepted before implementation
```

The design is frozen now; implementation should not race ahead of State
authority closure without reviewer approval.

## Single invariant

> Only an active, admitted producer Attempt may cause Runtime to promote
> candidate artifact bytes into verified Artifact truth.

## Required truth separation

```text
Candidate
!= Verified
!= Replay Eligible
!= Memory Admitted
!= Final Adopted
```

Do not collapse these dimensions into a single enum.

## Provider boundary

Provider may:

```text
write candidate bytes
compute candidate hash
produce validator/quality evidence
return candidate reference
```

Provider may not authoritatively:

```text
mark VERIFIED
mark replay-ready
commit Memory
final-adopt task output
```

## Runtime verification seam

Expected order:

```text
candidate result
→ physical/local result admission
→ active-Attempt admission
→ candidate identity/hash/path validation
→ validator/quality evidence validation
→ Runtime verification promotion
→ separate replay eligibility
→ optional Memory admission
→ optional final adoption
```

A stale producer Attempt may leave candidate bytes for audit/cleanup, but may
not create Verified truth.

## Legacy compatibility fields

Current `ExecutionArtifactRef` fields such as:

```text
verification_state
replay_ready
```

are compatibility projections only.

Provider-created candidates begin as:

```text
verification_state = CANDIDATE
replay_ready = False
```

Only Runtime-owned verification/replay decisions may justify later projection
onto those fields.

Do not allow legacy fields and new Runtime receipts to become competing
authority truths.

## Cross-Attempt consumption

Consumer Attempt B need not equal producer Attempt A.

Authority requires the artifact to be a verified Runtime truth and to be
explicitly authorized as B's input, with compatible task/session provenance.

## Explicit non-goals

```text
no Memory/replay implementation
no final task-selection rewrite
no provider-side verification authority
no State lifetime redesign
```

## Minimum tests

1. Active admitted producer candidate can be Runtime-verified.
2. Stale producer candidate is never promoted to Verified.
3. Verified artifact does not automatically become replay eligible or memory
   admitted.

At most one adjacent Artifact/commit-gate regression.

## Gates

```text
Source Gate:
provider candidate != Runtime verification authority

Mechanism Gate:
real candidate bytes/hash/evidence traverse verification seam

Integration Gate:
canonical artifact-producing path preserves separate truth dimensions

Competition Gate:
UNVALIDATED
```

## Evidence

```text
artifacts/mrr-08/artifact_verification_trace.txt
artifacts/mrr-08/stale_candidate_rejection.txt
artifacts/mrr-08/truth_dimension_separation.txt
artifacts/mrr-08/targeted_tests.txt
```

## Stop boundary

```text
NEXT_ALLOWED_SLICE = BATCH_3_GATE_REVIEW
```
