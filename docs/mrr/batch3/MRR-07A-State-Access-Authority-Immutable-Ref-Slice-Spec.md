# MRR-07A — State Access Authority + Immutable Ref Identity — Slice Spec v2

## Type

IMPLEMENTATION SLICE

Depends on:

```text
BATCH_2_GATE_PASS
```

## Single invariant

> Knowing State identity is not sufficient authority to acquire State.

## Required changes

### Immutable publication

Canonical State publication must fail closed on duplicate `ref_id`.

```text
REF_REUSE_FORBIDDEN
generation = NOT_REQUIRED
```

### Derived StateAccessGrant

Add the smallest contract/witness necessary to bind State READ to existing:

```text
RuntimeIdentity
Attempt
ExecutionBinding
CapabilityGrant
State identity
consumer/provider
physical invocation where applicable
expiry
```

It must be a **derived witness**, not independent root authority.

### Authority bases

Existing upstream ref:

```text
CAPABILITY_INPUT
ref_id must be present in CapabilityGrant.input_ref_ids
```

Runtime-created execution intermediate:

```text
RUNTIME_INTERMEDIATE
```

is legal only if all are true:

```text
active Attempt matches
publication occurs through Runtime-owned publication seam
State/output kind is permitted by current authorized capability/output contract
binding/grant/provider still match
immutable publication is registered before READ witness issuance
```

### Canonical access boundary

The same authorization semantics apply to:

```text
local/in-process provider
subprocess worker
provider-internal semantic-state worker
```

Low-level:

```text
LayeredStateStore.load/get
resolve_*
```

remain materialization primitives, not business authority APIs.

Canonical business paths may not bypass StateAccessGrant admission by directly
calling them.

### Worker enforcement

Before physical acquisition, validate State identity + access witness against
current invocation scope.

### Stale Attempt

A settled/stale Attempt cannot:

```text
mint new StateAccessGrant
start a new authorized acquisition
publish authoritative State
acquire a new pin
```

07A does not require retroactive revocation of an already-issued witness that
was bound to an already-dispatched invocation while the Attempt was active.

Such physical work may finish; Batch 2 active-Attempt result admission still
fences stale semantic output.

## Explicit non-goals

```text
no StatePin implementation
no release lifecycle redesign
no generation
no BoundRefHandle
no distributed reference counting
no worker-owned Attempt registry
no mapping revocation service
no Artifact/Memory implementation
```

## Preferred production scope

Keep to the minimum files directly involved in:

```text
State access contract
Runtime issuance
physical request projection if needed
State resolver/admission
duplicate publication guard
```

Do not refactor the State package broadly.

## Minimum tests

1. Authorized canonical State access succeeds through the real consumer path.
2. Wrong/stale Attempt or wrong Grant/Binding/ref witness is denied before
   State acquisition; parameterize mismatch cases.
3. Duplicate immutable `ref_id` publication fails without replacing the old
   object.

At most one adjacent semantic-state regression.

## Gates

```text
Source Gate:
identity != authority encoded; no local bypass in canonical path

Mechanism Gate:
real consumer acquires authorized State;
stale/wrong authority is rejected

Integration Gate:
existing canonical semantic State path continues through new authority seam

Competition Gate:
UNVALIDATED
```

## Evidence

Keep minimal:

```text
artifacts/mrr-07a/authorized_state_access.txt
artifacts/mrr-07a/state_access_rejection.txt
artifacts/mrr-07a/immutable_ref_publication.txt
artifacts/mrr-07a/targeted_tests.txt
```

## Stop boundary

Do not start MRR-07B.

```text
NEXT_ALLOWED_SLICE = MRR-07B_GATE_REVIEW
```
