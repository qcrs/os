# MRR-07B — State Ownership + Pin / Release Lifecycle — Slice Spec v2

## Type

IMPLEMENTATION SLICE

Depends on:

```text
MRR-07A ACCEPTED
```

## Single invariant

> A State physical object cannot be reclaimed while an authorized live consumer
> still depends on it, and logical release/unpin is safe and idempotent.

## Required model

Minimal Runtime-local lifetime state per immutable ref:

```text
owner/session publication scope
producer provenance
owner_released
live consumer pins
physical_reclaimed
```

Do not implement distributed reference counting.

## Consumer pin

A new pin requires valid READ authority and an active Attempt at acquisition.

Pin is a lifetime dependency, not a new State authority root.

## Logical owner release

Owner release:

```text
owner_released = True
```

must be idempotent.

It must not immediately reclaim while a live consumer pin exists.

## UNPIN

`unpin(pin_id)` must be idempotent and remain legal as cleanup for a stale
Attempt's already-existing pin.

## Physical reclaim

Only when:

```text
owner_released
AND live_pin_count == 0
AND not already_reclaimed
```

## Attempt settlement

Settlement:

```text
revokes future authority
releases/unpins Attempt-owned consumer dependencies
```

but does **not** blindly destroy every State produced by that Attempt.

```text
Attempt settle != physical unlink
```

## Explicit non-goals

```text
no distributed GC
no cluster reference counting
no generic lease service
no Artifact/Memory work
no generation
```

## Minimum tests

1. Producer -> consumer pin -> owner release -> State remains physically
   available -> consumer unpin -> physical reclaim.
2. Repeated owner release and repeated unpin are idempotent.
3. Attempt settlement releases its consumer dependencies without destroying
   a publication still needed by another authorized consumer.

At most one adjacent 07A access-authority regression.

## Gates

```text
Source Gate:
identity/authority/lifetime remain separate

Mechanism Gate:
real physical backend lifetime follows pin/release rule

Integration Gate:
canonical State consumer completes without premature reclaim

Competition Gate:
UNVALIDATED
```

## Evidence

```text
artifacts/mrr-07b/pin_release_trace.txt
artifacts/mrr-07b/idempotent_release.txt
artifacts/mrr-07b/attempt_cleanup.txt
artifacts/mrr-07b/targeted_tests.txt
```

## Stop boundary

Do not start MRR-08 automatically.

```text
NEXT_ALLOWED_SLICE = MRR-08_GATE_REVIEW
```
