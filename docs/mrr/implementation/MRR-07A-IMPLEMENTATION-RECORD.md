# MRR-07A Implementation Record

## Goal

Freeze the invariant that immutable State identity is not State READ authority.
Canonical adaptive semantic State acquisition now requires a Runtime-derived
`StateAccessGrant`, and canonical publication rejects `ref_id` reuse.

## Files changed

Production:

- `statebus/contracts/state_access.py`
- `statebus/contracts/__init__.py`
- `statebus/refs/models.py`
- `statebus/state/store.py`
- `statebus/state/__init__.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/control/statebus_control.proto`
- `statebus/control/schema.py`
- `statebus/control/messages.py`
- `statebus/control/subprocess_worker.py`

Tests:

- `tests/test_mrr_07a_state_access_authority.py`
- `tests/test_adaptive_mainline_integration.py`

Evidence and record:

- `artifacts/mrr-07a/authorized_state_access.txt`
- `artifacts/mrr-07a/state_access_rejection.txt`
- `artifacts/mrr-07a/immutable_ref_publication.txt`
- `artifacts/mrr-07a/targeted_tests.txt`
- `docs/mrr/implementation/MRR-07A-IMPLEMENTATION-RECORD.md`

## Immutable ref rule

`LayeredStateStore.publish()` raises `state_ref_reuse_forbidden` before any
backend materialization when the `ref_id` is already registered or its
publication metadata already exists. The prior object is not released,
overwritten, renamed, or assigned a generation.

`SemanticStateRef.state_identity_hash` identifies the immutable publication
from its ref ID/kind, State kind, storage kind, blob hash, length, manifest,
and contract hash. It carries no access authority.

## StateAccessGrant semantics

`StateAccessGrant` is a READ-only derived authorization witness. It binds task,
run, session, Step, Attempt, ExecutionBinding, CapabilityGrant, immutable State
identity, consumer provider/role, optional physical invocation, and bounded
expiry. It does not create Attempts, select providers, publish by itself, or
control State lifetime.

## Authority derivation

`RuntimeStateAccessAuthority` receives the active `RuntimeSessionManager`,
`RuntimeIdentity`, and exact `BoundCapabilityGrant`. It refuses publication,
witness issuance, and new local acquisition after the Attempt settles.

`CAPABILITY_INPUT` requires membership in the existing
`CapabilityGrant.input_ref_ids`. `RUNTIME_INTERMEDIATE` requires a matching
immutable publication previously registered through the same Runtime object.

## Canonical local/worker enforcement

The adaptive semantic worker request carries `RefHandle` and a separate
`StateAccessGrant`. Before physical acquisition, the worker checks execution
scope, Binding and Grant hashes, Ref identity, provider/role, invocation,
READ mode, and expiry, then verifies the immutable State identity reconstructed
from publication metadata.

The in-process Runtime query read uses a second witness and performs the same
scope and immutable-identity checks before calling the low-level resolver. No
fake worker header or physical invocation is created for the local path.

## RUNTIME_INTERMEDIATE constraint

Dense semantic intermediate publication is enabled only for the bound
retrieval-adapter capability when its authorized output contract matches and
permits `canonical_evidence_pack`. The publication completes first; only then
may the Runtime issue a READ witness for that exact State identity.

## Stale Attempt semantics

Settlement clears the session's active Attempt pointer. Subsequent publication,
witness issuance, or local acquisition through that authority fails with
`state_access_attempt_not_active`. An already-issued, invocation-bound worker
witness is not retroactively revoked; Batch 2 result admission remains the
semantic fence for late work.

## Tests actually run

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=/home/qcrs/statebus/os

python -m pytest -q tests/test_mrr_07a_state_access_authority.py
python -m pytest -q tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state
```

No Docker, vLLM, benchmark, full suite, coverage, or performance run was used.

## Results

Focused rejection and immutable publication file: `8 passed in 0.75s` across
two test functions, one parameterized over seven authority mismatches.

Canonical semantic integration: `1 passed in 1.74s` in the approved local
Conda context. The restricted sandbox first denied UDS bind with
`Operation not permitted`; the identical test passed outside that restriction.

## Source Gate

`SOURCE_GATE_PASS`

Identity and authority are separate, duplicate publication is rejected,
issuance derives from active Attempt/Binding/Grant, intermediate publication is
output-constrained, local and worker canonical consumers enforce admission,
and stale Attempts cannot mint new authority. No lifetime or Artifact work was
added.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The real UDS/protobuf worker acquired the State only after validating the
Runtime-derived witness. Negative cases stopped before the physical resolver.

## Integration Gate

`INTEGRATION_GATE_PASS`

The existing adaptive semantic State mainline completed through the new worker
and local authority boundary.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

## Known limitations

Low-level `load/get/resolve_*` functions remain materialization primitives and
do not claim hostile-process isolation. Standalone benchmark and diagnostic
helpers were not promoted into the canonical adaptive Runtime path. State
pinning, release ownership, reclamation, and settlement cleanup remain outside
07A, and no mid-flight revocation mechanism was added.

## NEXT_ALLOWED_SLICE

`NEXT_ALLOWED_SLICE = MRR-07A_GATE_REVIEW`
