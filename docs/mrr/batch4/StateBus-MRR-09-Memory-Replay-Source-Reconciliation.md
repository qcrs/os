# StateBus MRR-09 — Memory / Replay Source Reconciliation

> Project: StateBus Mainline Runtime Reconciliation
> Phase: Batch 4 / MRR-09 — Memory / Replay
> Mode: DESIGN ONLY / READ ONLY
> Design input: Batch 3 closed truth + current MRR-09 source reconciliation.
> No SHA/history identity is used as design evidence.
> No source/test modification, no test execution, no benchmark.

Frozen prerequisites:

```text
Batch 1 = CLOSED
Batch 2 = CLOSED
Batch 3 = CLOSED
MRR-07 = CLOSED
MRR-08 = CLOSED

State Identity / Authority / Lifetime = FROZEN
Artifact Candidate / Runtime Verification Truth = FROZEN
```


## 1. Sources reviewed

Frozen closure:
- `docs/mrr/reviews/StateBus-MRR-Batch3-Gate-Review.md`
- `docs/mrr/reviews/StateBus-MRR-08-Gate-Review-v2.md`
- `docs/mrr/implementation/MRR-08-IMPLEMENTATION-RECORD.md`
- `docs/mrr/batch3/StateBus-MRR-Batch3-State-Artifact-Truth-Deep-Design.md`

Current production:
- `statebus/memory/models.py`
- `statebus/memory/store.py`
- `statebus/runtime/adaptive_mainline.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/replay.py`
- `statebus/runtime/driver.py`
- `statebus/runtime/ledger.py`
- `statebus/contracts/artifact.py`

Competition/reference:
- `docs/reference/题目.md`
- `docs/reference/statebus-audit/StateBus-Audit-02-Semantic-Memory-Cross-Task-Reuse-2026-09-03.md`

The audit document is reference only. Current source + frozen MRR reviews remain authoritative.

---

## 2. What exactly does StateBus Memory remember?

The canonical adaptive write path stores a persistent `MemoryCommit`, not a raw Provider result and not a live State object.

`MemoryRef` currently retains:

```text
memory_id
memory_type
replay_class
score
source_task_id
source_agent
created_at_ns
task_theme
tags
source_role_path
producer_run_id
artifact_ref_id
semantic_state_ref_id
embedding_ref_id
manifest_hash
commit_status
validation_status
answer_adopted
metadata
```

`MemoryCommit` additionally retains:

```text
CanonicalTaskSpec
required_outputs
quality_floor_pass
created_from_artifact_hash
```

Adaptive mainline metadata currently contains:

```text
runtime_signature_hash
output_contract_version
validator_digest
quality_report_hash
input_lineage_hashes
input_schema_digest
execution_recipe
execution_recipe_hash
replay_ready
artifact_root_id
artifact_relpath
artifact_blob_hash
benchmark_gold_used
```

A separate `StructuredEmbedding` is persisted/indexed.

Therefore current canonical Memory is best described as:

```text
Historical Verified-Artifact-Derived Memory Record
+
retrieval metadata / summary
+
Artifact lineage
+
optional executable procedure/recipe
+
external Artifact locator
```

It is not:

```text
a live StateRef lifetime owner
a provider-result authority
a resurrected previous Attempt
a self-contained exact Artifact byte store
```

---

## 3. Current Memory Truth Chain

```text
producer Attempt
        ↓
candidate ExecutionArtifactRef
        ↓
active-Attempt result admission
        ↓
RuntimeArtifactVerificationAuthority
        ↓
ArtifactVerificationReceipt
        ↓
AdaptiveMainlineRunner._commit_verified_memory()
        │
        ├─ runtime.completed
        ├─ terminal Artifact verified projection
        ├─ matching ArtifactVerificationReceipt
        ├─ Runtime/producer/grant/hash/size agreement
        ├─ artifact file/hash check
        ├─ matching verified quality report
        └─ execution recipe exists
        ↓
MemoryRef + MemoryCommit
        ↓
MemoryIndexStore.commit_candidate()
        ↓
COMMITTED + PASSED
        ↓
persistent store/index
        ↓
later lookup
```

Canonical adaptive Memory creation is Runtime-owned, but the persisted `MemoryCommit` does not itself retain an immutable Memory admission witness. Later lookup trusts `COMMITTED` / `PASSED` plus metadata. `MemoryIndexStore.put_commit()` is also a raw persistence primitive. This is the MRR-09A authority gap.

---

## 4. Matrix A — Current Memory Surfaces

| Surface | Producer | Stored truth | Authority today | Consumer | Problem |
|---|---|---|---|---|---|
| `MemoryRef` | mainline / legacy callers | Memory identity, summary, source task/agent, Artifact/embedding refs, replay projection | no independent authority | store/dispatcher | mixes identity/class/reuse projection |
| `MemoryCommit` | mainline / legacy | `MemoryRef` + task contract + required outputs + Artifact hash | canonical mainline checks MRR-08 receipt before commit | store | persistent object lacks immutable admission witness |
| `AdaptiveMemoryCommitDecision` | mainline | attempted/committed/reason + lineage | Runtime decision | telemetry/manifest | not durable cross-task authority |
| `StructuredEmbedding` | Memory plane | retrieval vector | none | store | retrieval data only |
| `MemoryMatchResult` | lookup | ranked candidates + compatibility decisions | retrieval projection | dispatcher | lookup candidate can become role input too directly |
| `MemoryConsumptionRecord` | dispatcher | actual/current use evidence | audit only | manifest/metrics | must not become replay/commit authority |
| `ReplayLedgerEntry` | strict legacy lane | replay audit/provenance | audit only | history replay tooling | not canonical adaptive authority |

---

## 5. Current Memory classes

The enum contains many classes, but the inspected canonical adaptive writer only maps:

```text
ReplayClass.EXACT_REPLAY
→ MemoryType.EXACT_REPLAY

ReplayClass.VALIDATED_REPLAY
→ MemoryType.VALIDATED_REPLAY

otherwise
→ MemoryType.STRATEGY
```

MRR-09 must not invent canonical admission semantics for enum values without a real current writer.

---

## 6. Current adaptive Replay Truth Chain

```text
retrieval/semantic state
        ↓
MemoryQuery
        ├─ query task/spec
        ├─ text/tags/embedding
        ├─ reuse policy
        ├─ runtime signature
        ├─ output contract
        ├─ CanonicalTaskSpec
        ├─ input lineage/schema
        └─ validator digest
        ↓
MemoryIndexStore.lookup_hybrid()
        ↓
keyword + tag + vector + RRF
        ↓
MemoryCompatibilityDecision
        ↓
MemoryMatchResult
        ↓
AdaptiveCapabilityDispatcher._memory_inputs_for_step()
        ↓
role input payload
        ↓
current role
```

`_compatibility_decision()` currently checks committed/validation status, runtime signature, output contract, validator digest, task family/intent/outputs, schema drift, lineage, persistent `replay_ready`, recipe and current query policy.

---

## 7. Current authority gap: Memory injection happens after Grant issuance

Adaptive Runtime builds semantic Step inputs, binds provider and issues `CapabilityGrant`.

Memory selection is produced separately inside dispatcher context, and `_memory_inputs_for_step()` later injects the matched Memory into Transform/CodeAct/Summarizer inputs.

Therefore current flow is approximately:

```text
CapabilityGrant already issued
        ↓
Memory lookup
        ↓
Memory role-input injection
```

The payload records the current grant hash, but:

```text
recording grant_hash
!=
grant authorizing the Memory
```

This is the central MRR-09B gap.

---

## 8. Adaptive “replay” is procedure reuse

`_validated_recipe()` accepts stored recipe only for replay-class matches and validates execution kind, capability ID and output contract.

Transform path:

```text
historical Transform program
→ CURRENT input
→ execute again
→ current validators/Artifact path
```

CodeAct path:

```text
historical Python source
→ CURRENT input
→ sandbox execute again
→ current validators/Artifact path
```

So adaptive replay is actually:

```text
VERIFIED_PROCEDURE_REUSE
```

and current Attempt result admission remains in the path.

---

## 9. Separate strict/history replay surface

`statebus/runtime/replay.py` has a separate history-replay subsystem based on:
- persisted MemoryCommit
- historical ExecutionArtifactRef
- ReplayLedgerEntry
- historical output path
- ReplayCandidate / ReplayAdmissibilityGate.

Its exact key includes task spec, input Artifact hashes, Runtime signature, code/extractor versions and output contract.

Its validated compatibility differs from adaptive Memory policy (for example required tools and argument schema shape). It also relies on legacy `replay_ready`.

Conclusion:

```text
Adaptive Memory path
=
future canonical Memory/reuse authority

runtime/replay.py strict history path
=
legacy/reference compatibility surface for MRR-09
```

MRR-09 does not maintain two canonical replay authorities.

---

## 10. Current `replay_ready`

MRR-08 keeps canonical adaptive artifacts at:

```text
replay_ready=False
```

Yet old Memory compatibility and strict history replay still read the flag.

Therefore:

```text
ExecutionArtifactRef.replay_ready
=
COMPATIBILITY PROJECTION / REMOVE LATER
```

It must not be restored as canonical authority.

---

## 11. Cross-task/session/run behavior

Current lookup does not require:

```text
source_task_id == query_task_id
```

A caller may provide a shared `memory_store_root`; otherwise mainline uses the Runtime-local default. History replay can also import explicit previous roots.

So current code can support cross-task/session/run reuse when the Runtime intentionally shares/imports persistent Memory.

Safe MRR-09 target:

```text
historical producer authority stays historical
current consumer gets fresh Runtime authority
```

---

## 12. State relationship

`semantic_state_ref_id` may remain in `MemoryRef`, but current canonical Memory consumers do not use it as a live State access path and State publications are released under MRR-07 lifetime truth.

Freeze:

```text
Memory logical retention != StatePin
semantic_state_ref_id = provenance only
```

---

## 13. Matrix B — Current Replay Surfaces

| Replay path | Trigger | Compatibility check | Current Attempt check | Commit path | Authority gap |
|---|---|---|---|---|---|
| adaptive ASSIST | Memory match + assist policy | Memory compatibility | selection itself not Attempt-bound | normal current execution/result admission | Memory not explicitly authorized by current Grant |
| adaptive validated | match + legacy projection | store compatibility + recipe validation | current execution result later passes Attempt admission | recompute current input → current result | eligibility is not current-Attempt receipt-backed |
| adaptive `EXACT_REPLAY` label | same | exact spec/lineage + recipe | current path still recomputes | same as procedure reuse | name overstates semantics |
| strict/history exact | history records + Replay gate | exact key/runtime/output | separate strict lane | strict driver | non-canonical adaptive; legacy replay_ready |
| strict/history validated | history candidate | different validated policy | separate strict lane | strict driver | policy drift |

---

## 14. Competition mapping

Hard requirements from `docs/reference/题目.md`:
- persistent shared Memory module;
- Memory ID/source Agent/time/theme/summary metadata;
- keyword/tag/semantic similarity retrieval;
- later Agents directly reuse historical Memory;
- two related continuous-task groups;
- Memory hit rate and efficiency evidence.

Not hard requirements:
- distributed cache service;
- global coherency;
- exact output resurrection;
- cluster leases.

MRR-09 should optimize for truthful persistent cross-task Memory reuse, not distributed cache sophistication.

---

## 15. Source contradiction

```text
SOURCE_CONTRADICTION = NONE
```

The design is grounded in the current source reconciliation and frozen Batch 3 closure. No SHA/history identity is required for this design.
