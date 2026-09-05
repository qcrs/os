# StateBus MRR Batch 3 — Implementation Plan v2

## DAG

```text
Batch 2 Gate PASS
        ↓
MRR-07A
State Access Authority + Immutable Ref Identity
        ↓
MRR-07A Gate
        ↓
MRR-07B
State Ownership + Pin / Release Lifecycle
        ↓
MRR-07B Gate
        ↓
MRR-08
Artifact / Evidence Truth
        ↓
Batch 3 Gate Review
```

## MRR-07A

Single correctness invariant:

> Knowing a valid StateRef identity is not sufficient authority to acquire State.

Expected outcomes:

```text
immutable ref-id publication
derived StateAccessGrant
RUNTIME_INTERMEDIATE constrained by existing output authority
canonical local + worker access enforcement
stale Attempt cannot mint new access authority
already-dispatched invocation is not forcibly revoked mid-flight
```

Does not implement consumer pins/release lifecycle.

## MRR-07B

Single correctness invariant:

> A physical State object cannot be reclaimed while an authorized live consumer
> still depends on it, and logical release is idempotent.

Expected outcomes:

```text
Runtime-local lifetime record
owner logical release
consumer pins
idempotent unpin/release
reclaim only when owner_released && live_pins == 0
Attempt settlement cleans consumer dependencies
producer Attempt settlement does not blindly destroy downstream State
```

## MRR-08

Single correctness invariant:

> Only a Runtime-admitted active producer Attempt may promote candidate bytes
> into verified Artifact truth.

Expected separation:

```text
Candidate
!= Verified
!= Replay Eligible
!= Memory Admitted
!= Final Adopted
```

Legacy artifact status fields remain compatibility projections.

## Testing discipline

Per Slice:

```text
<= 3 primary targeted tests
+ at most 1 adjacent regression
```

No full-suite, Docker, benchmark, vLLM or performance run unless a later
competition gate explicitly requires it.
