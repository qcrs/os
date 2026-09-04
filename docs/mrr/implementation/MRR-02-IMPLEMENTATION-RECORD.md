# MRR-02 Implementation Record

## Source identity

- Source checkout: `/home/qcrs/statebus/os`
- Branch: `feat/mrr-02-plan-provenance`
- Source SHA: `8b6646137fca4a4d79dfe3e67945122045c11d32`
- Frozen MRR-02 audited base: `8bfc6464ec236c0e121911095fc283129b0e7696`
- The current source SHA is the MRR-01 implementation commit on top of the
  frozen base; `git merge-base HEAD <frozen-base>` is the frozen base.
- Date: 2026-09-04
- No reset, rebase, merge, or push was performed. No container, vLLM service,
  or benchmark was started.

## Files read

MRR source/specification material:

- `docs/mrr/batch1/StateBus-MRR-Batch1-Implementation-Readiness-Review.md`
- `docs/mrr/batch1/MRR-01-Identity-Authority-Slice-Spec.md`
- `docs/mrr/batch1/MRR-02-Plan-Provenance-Slice-Spec.md`
- `docs/mrr/batch1/MRR-03A-Engine-Mode-Generalization-Slice-Spec.md`
- `docs/mrr/batch1/MRR-03B-Fixed-Compatibility-Mainline-Slice-Spec.md`
- `docs/mrr/batch1/MRR-04-Capability-Provider-Binding-Slice-Spec.md`
- `/home/qcrs/.codex/attachments/7b4e07b4-75e2-46f0-b79b-612b3e7b557a/pasted-text-1.txt`
- `docs/reference/statebus-audit/StateBus-Final-Architecture-Reconciliation-Target-Contracts-and-Implementation-DAG-2026-09-03.md`
- `docs/reference/statebus-audit/StateBus-System-Audit-Master-Map-and-Batch01-Task-Plan-Authority-2026-09-03.md`
- `docs/reference/statebus-audit/StateBus-System-Audit-Master-Map-Batch01-Batch02-Evidence-Provenance-Audit-2026-09-03.md`

MRR-02 source/test review:

- `statebus/runtime/compiler.py`
- `statebus/runtime/role_path.py`
- `statebus/runtime/adaptive_plan_compiler.py`
- `statebus/runtime/plan_policy.py`
- `statebus/runtime/adaptive_mainline.py`
- `statebus/runtime/domain_packs.py`
- `statebus/runtime/driver.py`
- `statebus/runtime/smoke.py`
- `statebus/contracts/adaptive.py`
- `statebus/contracts/__init__.py`
- `tests/test_adaptive_planner_policy.py`
- `tests/test_adaptive_mainline_integration.py`
- `statebus/contracts/identity.py`
- `statebus/runtime/identity.py`

## Files changed

MRR-02 production boundary:

- Added `statebus/contracts/plan_provenance.py`.
- Added `statebus/runtime/static_role_recipe.py`.
- Modified `statebus/contracts/__init__.py` to export provenance contracts and
  semantic hash helpers.
- Modified `statebus/runtime/__init__.py` to export static recipe helpers.
- Modified `statebus/runtime/adaptive_mainline.py` to retain source/effective
  proposal provenance, emit normalization receipts, classify semantic repair
  as replan-required, preserve explicit fallback provenance, and return an
  `ApprovedPlanBundle`.
- Modified `statebus/runtime/plan_policy.py` to reuse the shared semantic and
  mechanical-equivalence predicates and derive minimum plan size from the
  Envelope's declared role cardinality instead of a global two-step topology.

Tests and evidence:

- Added `tests/test_plan_provenance.py`.
- Added `tests/test_static_role_recipe.py`.
- Extended `tests/test_adaptive_planner_policy.py`.
- Extended `tests/test_adaptive_mainline_integration.py`.
- Added nine files under `artifacts/mrr-02/`, including the six names required
  by the execution brief and compatibility aliases for the Ready Pack names.
- Added this implementation record.

Pre-existing dirty files in deployment/docs/manual areas were left untouched.
The MRR-02 boundary did not modify `compiler.py`, `role_path.py`, `driver.py`,
`smoke.py`, `state/*`, `memory/*`, routing, providers, or benchmark entrypoints.
In particular, the pre-existing changes in `README.md`, `deploy/*`,
`docker/README.md`, `scripts/vllm/*`, `AGENTS.md`, `docs/mrr/batch1/`,
`docs/mrr/packages/`, and `docs/reference/statebus-audit/` were not overwritten,
deleted, or included in an MRR-02 commit.

## Contracts changed

### Semantic plan provenance

- `semantic_plan_hash()` and `mechanical_semantic_plan_hash()` separate plan
  semantics from planner telemetry and controller-owned typed-edge wiring.
- `PlanNormalizationReceipt` records source/effective proposal hashes,
  normalizer identity/version, changed fields, and the hard invariant
  `before_semantic_hash == after_semantic_hash`.
- Receipt construction merges the normalizer-reported operations with the
  observed proposal field delta. For the typed-edge fixture this records both
  controller operation labels and the exact changed field
  `steps.summarize.depends_on`.
- `ApprovedPlanBundle` links the runtime task and contract projections to the
  source proposal, effective proposal, normalization receipt, policy report,
  approved plan, and logical capability registry digest. Embedded objects are
  checked against their recorded hashes.

### Static recipe bridge

- `StaticRoleRecipe` and `StaticRoleRecipeStep` describe only logical roles,
  capabilities, contracts, dependencies, completion criteria, and failure
  semantics.
- `StaticRoleRecipeCompiler` emits an untrusted deterministic `PlanProposal`
  and has no runtime, provider, workspace, Attempt, or CapabilityGrant side
  effect.
- Static proposal identity includes `recipe_id`, `recipe_version`, and
  `runtime_task_id`, so a semantic recipe version produces a new policy
  subject while repeated compilation of the same version remains stable.
- The representative fixed recipe is the post-plan topology
  `retriever -> executor -> summarizer`.
- `compile_static_role_recipe_plan()` stops at `ApprovedPlanBundle`; it does
  not invoke `AdaptiveRuntimeEngine.run()` or a dispatcher.

### Mainline repair/fallback provenance

- A mechanical normalizer may only complete/reorder registered typed edges.
- A semantic graph replacement is not recorded as a schema repair and is
  surfaced as `semantic_replan_required` when no valid fallback exists.
- Registered fallback remains a policy decision with status
  `FALLBACK_FIXED_PLAN`, source proposal provenance, and a fallback proposal
  hash in the bundle.

## Tests executed

All commands used the current checkout's host environment:

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_plan_provenance.py tests/test_static_role_recipe.py \
  tests/test_adaptive_planner_policy.py \
  tests/test_adaptive_mainline_integration.py \
  -k 'not adaptive_product_retrieval_owns_cross_process_semantic_state'

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_adaptive_role_prompts.py tests/test_semantic_plan.py \
  tests/test_adaptive_smoke.py tests/test_adaptive_contracts.py

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_runtime_identity.py tests/test_adaptive_driver.py \
  tests/test_adaptive_mainline_integration.py \
  -k 'not adaptive_product_retrieval_owns_cross_process_semantic_state'

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_runtime_session_and_ledger.py tests/test_replay.py \
  tests/test_replay_gate.py tests/test_memory_runtime.py tests/test_memory_store.py

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_plan_provenance.py tests/test_static_role_recipe.py \
  tests/test_adaptive_planner_policy.py tests/test_adaptive_role_prompts.py \
  tests/test_semantic_plan.py tests/test_adaptive_smoke.py \
  tests/test_adaptive_contracts.py tests/test_runtime_identity.py \
  tests/test_adaptive_driver.py tests/test_adaptive_mainline_integration.py \
  tests/test_runtime_session_and_ledger.py tests/test_replay.py \
  tests/test_replay_gate.py tests/test_memory_runtime.py tests/test_memory_store.py \
  -k 'not adaptive_product_retrieval_owns_cross_process_semantic_state'

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m compileall -q statebus tests
git diff --check
```

## Test results

- MRR-02 provenance/static recipe/plan-policy/mainline set:
  **46 passed, 1 deselected**.
- RolePath proposal, semantic plan, adaptive smoke, and contract regression
  set: **21 passed**.
- MRR-01 identity, adaptive driver, and adaptive mainline regression set:
  **37 passed, 1 deselected**.
- Session, ledger, replay, and memory regression set: **32 passed**.
- Final consolidated MRR-02 plus directly related regression verification:
  **123 passed, 1 deselected**.
- `compileall`: **passed**.
- `git diff --check`: **passed**.
- All nine evidence artifacts were generated from the current source objects;
  the bundle hash-link check is `true` and the JSON payloads validate as strict
  JSON. The mechanical fixture receipt contains the exact observed field path
  `steps.summarize.depends_on` in addition to the two controller operation
  labels returned by `compile_required_input_wiring()`.

## Gates

### Source Gate: `SOURCE_GATE_PASS`

`StaticRoleRecipeCompiler`, `PlanNormalizationReceipt`, and
`ApprovedPlanBundle` exist. Semantic mutation tests reject attempts to pass
capability, role, goal, dependency, completion-criteria, failure-policy,
required-field, stage, memory-policy, or output-contract changes as mechanical
normalization. Mainline repair and fallback provenance are explicit and
covered by integration tests. Generic plan minimums are now projected from
Envelope role cardinality; the policy does not invent the Fixed topology.

### Mechanism Gate: `MECHANISM_GATE_N/A`

MRR-02 is a control-plane plan/provenance slice. Runtime execution, provider
binding, workspace materialization, State/Memory identity, and CapabilityGrant
creation are intentionally not changed or validated here.

### Integration Gate: `INTEGRATION_GATE_PASS`

The representative fixed task produces a policy-approved
`ApprovedPlanBundle` from `RuntimeIdentity`, a static recipe, typed-input
normalization, and policy validation without calling
`AdaptiveRuntimeEngine.run()`, a dispatcher, a role LLM, Attempt/Grant
creation, or a workspace side effect. Legacy post-plan role ordering,
transitive dependency graph, and registry-owned logical responsibilities
remain structurally equivalent.

### Competition Gate: `COMPETITION_GATE_UNVALIDATED`

No container, vLLM service, live model, benchmark, or competition end-to-end
run was started, as required for this local-only slice validation.

## Regressions

No MRR-02-introduced regression was observed in the targeted or direct related
regression sets.

The cross-process control-plane test
`test_adaptive_product_retrieval_owns_cross_process_semantic_state` remains a
`PRE_EXISTING_FAILURE` in this sandbox: Unix-domain socket/shared-memory setup
is rejected with `PermissionError: [Errno 1] Operation not permitted`. It was
excluded from the targeted run and was not modified. The existing MRR-01
record also documents the unrelated CodeAct/bwrap `NETLINK_ROUTE` restriction.

## Evidence paths

- `artifacts/mrr-02/fixed_plan_proposal.json`
- `artifacts/mrr-02/plan_normalization_receipt.json`
- `artifacts/mrr-02/plan_policy_report.json`
- `artifacts/mrr-02/approved_plan_bundle.json`
- `artifacts/mrr-02/fixed_recipe_structural_parity.txt`
- `artifacts/mrr-02/plan_semantic_mutation_negative_tests.txt`

Additional/compatibility evidence:

- `artifacts/mrr-02/approved_plan.json`
- `artifacts/mrr-02/legacy_structural_parity.txt`
- `artifacts/mrr-02/semantic_mutation_negative_tests.txt`

The representative evidence hashes are:

```text
proposal_hash                  a6d2f6b4bafe2945cf0087f28c0d4f349139e38014efddc22510dcfda58af905
normalization_receipt_hash     99a9fedf157f857895b419123d837ca700793df5f8cf45afb27d1c809b7263c1
mechanical_fixture_receipt_hash 4e566e5cdba7d1c64e201a6f3a94883a7fa453c6aa3d1dd062c9a606d7570d99
plan_policy_report_hash        4f0b15f7f5cc79d7a9f9747809bdf5e332074269044ae8636bee6e9e4deba4a7
approved_plan_hash             5fdd1fe1feeb87cd102495ca139e1d32b2bb327cae6866f60406f0bff8a7f964
approved_plan_bundle_hash      0c2d90c9a49478e90d7a4b356473fea76542bd931964d4f93db9e2c396d0dd68
semantic_replan_bundle_hash    ab6c9ae13a9b555fa81dbd9b91648bd4cb7c9082b44116eefc5a87c3632ab452
mechanical_semantic_plan_hash   e7d5b403c266519186d5427bbb5a648410b49191b351a0851fe2312b504e4de4
semantic_plan_hash               aa06b46d051983d9cb6b4b23bef9214416c34f1afbf671cf7c0e6caa5388e924
```

## Open questions

- The static recipe is an opt-in control-plane bridge. Connecting it to the
  generalized runtime is deferred to MRR-03A/03B.
- Physical provider eligibility and binding remain deferred to MRR-04.
- State, Memory, Artifact, replay, and workspace identity migrations remain
  outside this slice.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-03A`

MRR-03A is allowed by the dependency order only because Source and Integration
Gates passed, the required evidence exists, and no unresolved MRR-02 regression
was found. MRR-03A was not started in this turn.
