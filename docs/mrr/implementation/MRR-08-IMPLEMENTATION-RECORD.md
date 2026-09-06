# MRR-08 Implementation Record

## Goal

Freeze the Artifact truth invariant: only Runtime may promote bytes produced by
an active, admitted producer Attempt from candidate status into verified
Artifact truth.

## Files changed

Production:

- `statebus/contracts/artifact.py`
- `statebus/contracts/__init__.py`
- `statebus/runtime/artifact_verification.py`
- `statebus/runtime/__init__.py`
- `statebus/runtime/workspace.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/adaptive_mainline.py`
- `statebus/runtime/transform_dsl.py`
- `statebus/runtime/evidence_projection.py`
- `statebus/runtime/llm_codeact.py`

Tests:

- `tests/test_mrr_08_artifact_truth.py`
- `tests/test_adaptive_dispatcher.py`

Evidence and record:

- `artifacts/mrr-08/artifact_verification_trace.txt`
- `artifacts/mrr-08/stale_candidate_rejection.txt`
- `artifacts/mrr-08/truth_dimension_separation.txt`
- `artifacts/mrr-08/targeted_tests.txt`
- `docs/mrr/implementation/MRR-08-IMPLEMENTATION-RECORD.md`

## Candidate semantics

Adaptive Transform DSL, CodeAct, Evidence Projection, and Summarizer paths now
materialize `ExecutionArtifactRef` candidates without promoting them. Candidate
registration forces `verification_state=CANDIDATE` and `replay_ready=False`.
Candidate bytes and provider-local validator evidence may exist before Runtime
admission, but they have no verified Artifact authority.

## Runtime verification authority

`RuntimeArtifactVerificationAuthority` is the only canonical adaptive promotion
authority. It consumes the existing Runtime identity, Session active-Attempt
truth, the exact `BoundCapabilityGrant`, and the existing Attempt result
admission receipt. The adaptive Runtime calls it after result admission and
before output refs mutate workflow state.

`ArtifactLifecycleManager.mark_verified()` remains a legacy compatibility field
projection. It does not create a Runtime receipt, and canonical adaptive
consumers do not accept that projection without the matching receipt.

## Verification receipt / projection

`ArtifactVerificationReceipt` is immutable Runtime evidence binding:

- Artifact ID and candidate byte identity;
- Runtime task, run, session, producer Step, and producer Attempt;
- Execution Binding and Capability Grant hashes;
- candidate size, validator IDs, and validator report hashes;
- Runtime verification decision and reason.

The Runtime stores receipts in `AdaptiveDispatchContext`, writes them into the
adaptive mainline manifest, and projects the receipt hash onto the legacy
`ExecutionArtifactRef` metadata. The legacy `verification_state` field is not
accepted as independent authority.

## Active-Attempt ordering

The promotion call is structurally after
`RuntimeSessionManager.admit_attempt_result()`. The verifier also checks that
the admission receipt authorized commit and that the producer Attempt is still
the Session's active Attempt before reading candidate bytes or validator
evidence.

## Stale candidate behavior

If Attempt A settles and Attempt B becomes active, A's otherwise valid
candidate is rejected with `artifact_producer_attempt_not_active`. Its bytes may
remain for audit, but its status stays `CANDIDATE` and B's authority is not
changed.

## Legacy ExecutionArtifactRef compatibility

`verification_state=VERIFIED` is a projection of the Runtime receipt on the
canonical adaptive path. `ArtifactLifecycleManager` is retained for legacy
storage/projection compatibility, but a manager-only status change cannot pass
canonical adaptive input admission because it has no matching Runtime receipt.

## Replay separation

Candidate registration and Runtime verification both keep
`replay_ready=False`. MRR-08 creates no replay eligibility decision and does not
use verification as replay authority.

## Memory separation

The verifier has no Memory dependency and performs no Memory commit. Existing
Memory code was not changed. Any later Memory admission remains a separate
Runtime gate outside this Slice.

## Tests actually run

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
STATEBUS_LLM_CONFIG_FILE=/home/qcrs/statebus/os/deploy/statebus_llm.yaml.local
PYTHONPATH=/home/qcrs/statebus/os
PYTHONDONTWRITEBYTECODE=1

python -m pytest -q tests/test_mrr_08_artifact_truth.py
python -m pytest -q tests/test_mrr_08_artifact_truth.py tests/test_adaptive_dispatcher.py::test_runtime_dispatcher_executes_retrieval_projection_dsl_and_registered_builtin
```

No full suite, Docker, vLLM, benchmark, competition benchmark, coverage,
performance test, or broad predecessor regression was run.

## Results

The three primary tests passed in 0.69 seconds. The final targeted run repeated
those tests with the single allowed adjacent dispatcher integration and passed
all four tests in 0.97 seconds.

## Source Gate

`SOURCE_GATE_PASS`

Provider candidate and Runtime verification authority are separate. Promotion
follows active-Attempt result admission; candidate identity, provenance,
workspace path, byte size/hash, and exact validator evidence are checked before
the Runtime creates a receipt. Stale Attempts cannot promote candidates.
Legacy status is receipt-backed on the canonical path, replay readiness remains
false, and no second Artifact Attempt authority was introduced.

## Mechanism Gate

`MECHANISM_GATE_PASS`

Real candidate bytes, ref metadata, result admission, active-Attempt authority,
content validation, validator evidence, receipt creation, and verified
projection traversed the production Runtime seam.

## Integration Gate

`INTEGRATION_GATE_PASS`

The canonical adaptive Runtime plus dispatcher completed Artifact-producing
workflows with candidate production followed by Runtime promotion. The existing
retrieval/projection/Transform/Runtime-builtin integration completed under the
new separation.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

## Known limitations

- Verification receipts are Runtime-local truth persisted by the adaptive
  mainline manifest; this Slice does not add a separate Artifact database.
- Candidate garbage collection and stale-byte cleanup are not implemented.
- Replay eligibility, Memory admission, and final adoption remain separate
  existing or future Runtime decisions and were not implemented here.
- Ref Registry entries continue to expose legacy status projections; canonical
  adaptive authority comes from the Runtime receipt.

## NEXT_ALLOWED_SLICE

`NEXT_ALLOWED_SLICE = MRR-08_GATE_REVIEW`

## Corrective Pass

Gate blockers addressed without relaxing Runtime authority.

- Blocker 1: migrated the direct dispatcher summarizer fixture to a
  receipt-backed verified Artifact contract; dispatcher-produced outputs remain
  candidates until Runtime promotion.
- Blocker 2: moved CodeAct runtime/quality repair workspaces below the
  authorized Attempt workspace so repaired candidates remain inside the
  verifier boundary.
- Targeted tests and results are recorded in
  `artifacts/mrr-08/corrective_tests.txt`.
- No Memory/Replay changes, authority relaxation, or defensive fallback was
  added.

Status after corrective pass:

```text
MRR-08_CORRECTIVE_IMPLEMENTATION_COMPLETE
```

## Corrective Pass 2

The second corrective pass closed the remaining MRR-08 gate blockers without
relaxing the Runtime verification authority.

- CodeAct standalone execution remains a producer contract: `LlmCodeActRunner`
  returns `CANDIDATE` and leaves `verified_artifact_id` empty. The old
  provider-side verified-cache hit expectation was migrated.
- `LlmCodeActCache` was confirmed to be legacy/standalone only: the canonical
  adaptive path had no production cache admission, so the obsolete cache
  lookup/write path was removed instead of resurrecting provider-side
  `VERIFIED` authority. No cache entry can bypass a Runtime receipt.
- Existing Memory admission now requires the executor artifact's matching
  `ArtifactVerificationReceipt`: artifact ID, Runtime task/session identity,
  producer Attempt, grant hash, candidate hash/size, decision, and projected
  receipt hash must agree before commit.
- The MRR-08 integration fixture now exercises the production chain: a Runtime
  builtin produces a candidate, `AdaptiveRuntimeEngine` issues and stores the
  receipt, and a dependent canonical Transform consumer reads the same
  receipt-backed artifact through normal dispatcher admission.
- No Memory redesign, replay eligibility, Replay implementation, or new
  verification authority was added.

Targeted evidence is recorded in
`artifacts/mrr-08/corrective_pass2_tests.txt`.

Status after corrective pass 2:

```text
MRR-08_CORRECTIVE_PASS_2_COMPLETE
NEXT_ALLOWED_ACTION = MRR-08_GATE_REVIEW_V2
```
