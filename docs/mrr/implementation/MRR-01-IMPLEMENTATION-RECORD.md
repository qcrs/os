# MRR-01 Implementation Record

## Source identity

- Source checkout: `/home/qcrs/statebus/os`
- Source SHA: `8bfc6464ec236c0e121911095fc283129b0e7696`
- Branch: `master`
- Date: `2026-09-04`
- Ready Pack: `StateBus-MRR-Batch1-Codex-Ready-Pack.zip`
- The frozen MRR-01 specification identifies `master` and the same SHA. The
  user-described feature branch was not present locally; no rebase, merge, or
  reset was performed.

## Files read

MRR source/specification material:

- `StateBus-MRR-Batch1-Implementation-Readiness-Review.md` (read from the
  Ready Pack ZIP)
- `MRR-01-Identity-Authority-Slice-Spec.md` (read from the Ready Pack ZIP)
- `MRR-02-Plan-Provenance-Slice-Spec.md` (downstream context)
- `MRR-03A-Engine-Mode-Generalization-Slice-Spec.md` (downstream context)
- `MRR-03B-Fixed-Compatibility-Mainline-Slice-Spec.md` (downstream context)
- `MRR-04-Capability-Provider-Binding-Slice-Spec.md` (downstream context)

Mandatory source/test review:

- `statebus/runtime/session.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_mainline.py`
- `statebus/runtime/driver.py`
- `statebus/runtime/workspace.py`
- `statebus/runtime/smoke.py`
- `statebus/contracts/adaptive.py`
- `statebus/contracts/__init__.py`
- `tests/test_adaptive_driver.py`
- `tests/test_adaptive_mainline_integration.py`

## Files changed

MRR-01 production boundary:

- Added `statebus/contracts/identity.py`.
- Added `statebus/runtime/identity.py`.
- Modified `statebus/contracts/__init__.py` and `statebus/runtime/__init__.py`
  to export the new contract/factory symbols.
- Modified `statebus/runtime/adaptive_mainline.py` to resolve identity once at
  product assembly, validate envelope projections, retain the legacy workspace
  projection, pass identity to Runtime, and persist identity in the manifest.
- Modified `statebus/runtime/adaptive_runtime.py` to use explicit session/run
  identity, create run-scoped attempt IDs on the canonical path, issue grants
  with the resolved identity, and retain legacy labels for compatibility
  callers.
- Modified `statebus/runtime/driver.py` to resolve an optional identity for
  strict legacy input and return it without changing the old workspace layout.

Tests and evidence:

- Added `tests/test_runtime_identity.py`.
- Extended `tests/test_adaptive_driver.py`.
- Extended `tests/test_adaptive_mainline_integration.py`.
- Added `artifacts/mrr-01/runtime_identity_payload.json`.
- Added `artifacts/mrr-01/runtime_identity_negative_tests.txt`.
- Added `artifacts/mrr-01/adaptive_identity_integration.txt`.
- Added `artifacts/mrr-01/legacy_identity_compatibility.txt`.
- Added this implementation record.

Unrelated pre-existing worktree edits in `README.md`, `deploy/*`,
`docker/README.md`, `scripts/vllm/*`, `AGENTS.md`, and the Ready Pack ZIP were
left untouched.

## Contracts changed

### `TaskContractIdentity` v1

Introduces `contract_kind`, `contract_hash`, optional public-context and input
asset hashes, `legacy_canonical_task_spec_hash`, and `schema_version`. The
current CanonicalTaskSpec bridge enforces:

```text
contract_hash == legacy_canonical_task_spec_hash
```

No second semantic task hash was introduced.

### `RuntimeIdentity` v1

Introduces the additive aggregate:

```text
external_case_id (optional)
runtime_task_id
run_id
session_id
trace_id
task_contract
schema_version
```

`task_id` remains a read-only compatibility projection of `runtime_task_id`.
`canonical_task_spec_hash` remains a projection of
`TaskContractIdentity.contract_hash`.

### Compatibility and authority

- `compatibility_runtime_identity(...)` creates a first-class identity from
  legacy `task_id`, `trace_id`, and canonical contract hash.
- `resolve_runtime_identity(...)` validates all legacy projections and rejects
  mismatches before execution.
- Runtime execution creates attempt IDs and CapabilityGrants. Provider/role
  callbacks can only return the attempt they were granted; a forged successor
  attempt is rejected as `grant_binding_mismatch`.
- Explicit adaptive runs use `adaptive-attempt-{run_id}-{counter}`. Legacy
  adaptive callers retain `adaptive-attempt-{counter}` and the historical
  `adaptive-session-{task_id}` convention.
- No StateRef, MemoryRef, ArtifactRef, workspace layout, replay identity, or
  StepID/AttemptID wrapper migration was performed.

## Tests executed

All commands used:

```text
source ./deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/test_runtime_identity.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/test_adaptive_driver.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/test_adaptive_mainline_integration.py -k 'not adaptive_product_retrieval_owns_cross_process_semantic_state'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/test_runtime_session_and_ledger.py tests/test_replay.py tests/test_replay_gate.py tests/test_memory_runtime.py tests/test_memory_store.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m compileall -q statebus/contracts statebus/runtime tests/test_runtime_identity.py tests/test_adaptive_driver.py tests/test_adaptive_mainline_integration.py
git diff --check
```

## Test results

- `tests/test_runtime_identity.py`: **15 passed**.
- `tests/test_adaptive_driver.py`: **9 passed**.
- `tests/test_adaptive_mainline_integration.py` identity/regression path:
  **9 passed, 1 deselected**. The deselected test requires cross-process
  shared-memory/UDS permissions unavailable in this sandbox.
- Direct session/ledger/replay/memory regression set: **32 passed**.
- Adjacent adaptive contract/dispatcher/planner/smoke and the same direct
  regression set: **60 passed** in the final combined run.
- Static compile/import check: **passed**.
- `git diff --check`: **passed**.

## Gates

### Source Gate: `SOURCE_GATE_PASS`

Identity contracts import cleanly, canonical payload/hash behavior passes, all
new identity negative contracts pass, and legacy request construction remains
source-compatible.

### Mechanism Gate: `MECHANISM_GATE_PASS`

The adaptive runtime uses the resolved session identity, creates distinct
run-scoped attempt IDs for explicit runs, attaches attempt records to that
session, and binds CapabilityGrants to the runtime-created attempt. State and
Memory mechanisms are intentionally not changed in this slice.

### Integration Gate: `INTEGRATION_GATE_PASS`

Both canonical explicit-identity reruns and a legacy no-identity adaptive
request were exercised. Canonical reruns retain the same logical task and
contract while separating RunID/SessionID and their attempt records. Legacy
startup still reaches the existing path.

### Competition Gate: `COMPETITION_GATE_UNVALIDATED`

No container, vLLM service, benchmark, or competition end-to-end run was
started, per the slice instructions.

## Regressions

No Slice-introduced regression was observed in the targeted tests or direct
session/ledger/replay/memory regression set.

The following are recorded as `PRE_EXISTING_FAILURE` and were not modified:

- `test_adaptive_product_retrieval_owns_cross_process_semantic_state`: the
  sandbox rejects the shared-memory/UDS bind with
  `PermissionError: [Errno 1] Operation not permitted`.
- CodeAct/bwrap checks: the environment rejects the required
  `NETLINK_ROUTE` socket with `Operation not permitted`.
- An initial full pytest collection encountered the historical
  `/home/qcrs/statebus/runs/studio` read-only path; rerunning with a temporary
  Studio root exposed the same environment-level failures and was stopped.

## Evidence paths

- `artifacts/mrr-01/runtime_identity_payload.json`
- `artifacts/mrr-01/runtime_identity_negative_tests.txt`
- `artifacts/mrr-01/adaptive_identity_integration.txt`
- `artifacts/mrr-01/legacy_identity_compatibility.txt`

## Open questions

- `run_smoke()` remains the legacy fixed orchestration lane; the fixed bridge
  is intentionally deferred to MRR-03A/03B.
- State/Memory/Artifact identity migration and late-result fencing remain
  downstream concerns and must not be pulled into MRR-01.
- Competition and live-service behavior remain unvalidated until a later
  explicitly authorized run.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-02`

This recommendation is limited to the frozen dependency order and is made only
because Source, Mechanism, and Integration Gates passed with no unresolved
Slice regression. MRR-02 was not started in this turn.
