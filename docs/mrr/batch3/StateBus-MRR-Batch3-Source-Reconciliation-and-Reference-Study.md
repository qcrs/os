# StateBus MRR Batch 3 — Source Reconciliation and Reference Study v2

## Current-source reconciliation summary

The design is based on these current facts:

```text
LayeredStateStore.publish(ref_id, ...)
→ materializes physical State and registers by ref_id

LayeredStateStore.load/get(ref_id)
→ resolves materialization by ref_id

LayeredStateStore.release(ref_id)
→ removes current registration and physically releases backend resource
```

Current semantic-state resolution validates representation, content hash,
storage metadata and lease/liveness, but caller Attempt/Binding/Grant authority
is not itself the acquisition capability.

`CapabilityGrant.input_ref_ids` is already the correct upstream semantic
allowlist and should remain the root for existing input refs.

## Design consequences

### Identity

Use immutable publication identity.

```text
REF_REUSE_FORBIDDEN
generation = not required
```

If a future logical alias is needed:

```text
logical alias -> immutable StateRef
```

### Authority

`StateAccessGrant` is a derived authorization witness, not a new root
capability.

Both local/in-process and physical worker consumers must use equivalent
admission semantics.

### Lifetime

Use a Runtime-local owner + consumer-pin model. Do not adopt a cluster-wide
distributed reference-counting system.

### External patterns intentionally borrowed

- Object-capability principle: possession of identity is distinct from
  permission to operate.
- Fencing principle: stale execution cannot obtain new authority.
- Shared-memory lifetime principle: OS object lifetime semantics are not a
  substitute for application-level ownership/pinning.

### Patterns intentionally not adopted

```text
Ray-style distributed reference counting
generation/incarnation by default
distributed lease manager
worker-owned active Attempt registry
mid-flight remote mapping revocation
```

These would add machinery without solving an additional current StateBus
competition correctness requirement.
