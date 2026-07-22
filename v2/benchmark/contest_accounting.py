from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from v2.benchmark.contest_evidence_closure import (
    _pytest_junit_payload,
    _write_checksums,
    verify_artifact_checksums,
)
from v2.contracts import (
    CanonicalTaskSpec,
    CompatibilityVerdict,
    PlanStepProposal,
    ReplayClass,
)
from v2.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.memory import (
    MemoryCommit,
    MemoryCommitStatus,
    MemoryIndexStore,
    MemoryQuery,
    MemoryRef,
    MemoryType,
    MemoryValidationStatus,
    StructuredEmbedding,
    memory_effect_evidence_hash,
    summarize_memory_consumption,
)
from v2.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from v2.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    AdaptiveDispatchError,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.state_consumption import (
    build_state_consumption_record,
    close_state_consumption_record,
    summarize_state_consumption,
)
from v2.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    SemanticStateValidationError,
    publish_dense_semantic_state,
    resolve_dense_semantic_state,
)
from v2.utils import sha256_digest, stable_json_dumps


A1_SCHEMA_VERSION = "statebus.contest_rebuild_a1.v1"
ACTION_GATES = (
    "STATEBUS_CONTEST_ALLOW_METRICS_CHECK",
    "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
    "STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD",
    "STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS",
    "STATEBUS_CONTEST_ALLOW_COLD_CACHE",
    "STATEBUS_CONTEST_ALLOW_SERVICE_RESTART",
    "STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(project_root), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_identity(project_root: Path) -> dict[str, object]:
    status = _git(project_root, "status", "--porcelain=v1")
    paths = (
        "v2/contracts/adaptive.py",
        "v2/memory/models.py",
        "v2/runtime/adaptive_dispatcher.py",
        "v2/runtime/state_consumption.py",
        "v2/state/semantic_state.py",
    )
    return {
        "schema_version": "statebus.a1_source_identity.v1",
        "git_commit": _git(project_root, "rev-parse", "HEAD"),
        "git_tree": _git(project_root, "rev-parse", "HEAD^{tree}"),
        "git_branch": _git(project_root, "branch", "--show-current"),
        "worktree_clean": not bool(status),
        "dirty_diff_digest": sha256_digest({"status": status}),
        "contract_file_hashes": {
            path: sha256_digest((project_root / path).read_bytes())
            for path in paths
        },
    }


def _memory_input(
    memory_id: str,
    *,
    replay_class: ReplayClass = ReplayClass.ASSIST,
) -> dict[str, object]:
    payload = {
        "ref_id": memory_id,
        "source_agent": "executor",
        "replay_class": replay_class.value,
        "compatibility_verdict": CompatibilityVerdict.COMPATIBLE.value,
        "execution_recipe_hash": f"recipe-{memory_id}",
        "bound_execution_recipe_hash": f"recipe-{memory_id}",
    }
    payload["input_payload_hash"] = sha256_digest(payload)
    return payload


def _memory_fixtures() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    step = PlanStepProposal(
        step_id="execute",
        role="executor",
        capability_id="fixture-executor",
        goal="exercise accounting only",
        output_contract_version="fixture-output-v1",
    )
    memory_input = _memory_input("memory-h2")

    h0_context = AdaptiveDispatchContext(registry=CapabilityRegistry())
    h0_metrics = AdaptiveCapabilityDispatcher(
        context=h0_context
    )._record_memory_consumption(
        memory_inputs=(),
        step=step,
        downstream_ref_ids=(),
        before_surface_hash="h0-before",
    )

    h1_context = AdaptiveDispatchContext(registry=CapabilityRegistry())
    h1_metrics = AdaptiveCapabilityDispatcher(
        context=h1_context
    )._record_memory_consumption(
        memory_inputs=(memory_input,),
        step=step,
        downstream_ref_ids=(),
        before_surface_hash="h1-before",
    )

    pair_payload = {
        "pair_id": "memory-h0-h2",
        "order": ["H0", "H2", "H2", "H0"],
        "serialized": True,
        "quality_equivalent": True,
        "claim_scope": "accounting_fixture_only_no_benefit_claim",
    }
    counterfactual_hash = sha256_digest(pair_payload)
    output_hash = sha256_digest({"lane": "H2", "decision": "memory_used"})
    effect_hash = memory_effect_evidence_hash(
        memory_id="memory-h2",
        before_decision_surface_hash="h2-before",
        output_decision_surface_hash=output_hash,
        behavioral_effect="changed",
        counterfactual_evidence_hash=counterfactual_hash,
    )
    h2_context = AdaptiveDispatchContext(registry=CapabilityRegistry())
    h2_metrics = AdaptiveCapabilityDispatcher(
        context=h2_context
    )._record_memory_consumption(
        memory_inputs=(memory_input,),
        step=step,
        downstream_ref_ids=("artifact-h2",),
        before_surface_hash="h2-before",
        consumed_memory_ids=("memory-h2",),
        consumption_modes={"memory-h2": "rendered_prompt"},
        rendered_request_hash="h2-approved-request",
        approved_rendered_request_hash="h2-approved-request",
        output_decision_surface_hash=output_hash,
        memory_actions={"memory-h2": "rendered_into_request"},
        behavioral_effects={"memory-h2": "changed"},
        effect_evidence_hashes={"memory-h2": effect_hash},
        counterfactual_evidence_hash=counterfactual_hash,
        producer_role="executor",
        producer_pid=os.getpid(),
        physical_consumer_component="fixture_executor_boundary",
        physical_consumer_pid=os.getpid(),
        logical_target_role="executor",
    )

    h3_spec = CanonicalTaskSpec(
        task_family="contest_a1_accounting_fixture",
        intent_op="verify_current_recompute",
        required_outputs=("fixture_output",),
    )
    h3_commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id="memory-h3-incompatible",
            memory_type=MemoryType.STRATEGY,
            replay_class=ReplayClass.ASSIST,
            score=1.0,
            source_task_id="memory-h3-source",
            summary="incompatible accounting fixture",
            canonical_task_spec_hash=h3_spec.spec_hash,
            commit_status=MemoryCommitStatus.COMMITTED,
            validation_status=MemoryValidationStatus.PASSED,
            metadata={"runtime_signature_hash": "stored-runtime-signature"},
        ),
        canonical_task_spec=h3_spec,
        required_outputs=h3_spec.required_outputs,
        quality_floor_pass=True,
        created_from_artifact_hash="artifact-h3-source",
    )
    h3_query = MemoryQuery(
        query_task_id="memory-h3-current",
        query_spec_hash=h3_spec.spec_hash,
        canonical_task_spec=h3_spec,
        compatibility_signature="current-runtime-signature",
        allow_assist=True,
    )
    h3_decision = MemoryIndexStore._compatibility_decision(
        h3_commit,
        h3_query,
        raw_rank=1,
    )
    h3_rejected = bool(
        h3_decision.verdict == CompatibilityVerdict.INCOMPATIBLE
        and not h3_decision.policy_approved
        and "runtime_signature_mismatch" in h3_decision.reasons
    )
    h3_context = AdaptiveDispatchContext(registry=CapabilityRegistry())
    h3_metrics = AdaptiveCapabilityDispatcher(
        context=h3_context
    )._record_memory_consumption(
        memory_inputs=(),
        step=step,
        downstream_ref_ids=("artifact-current-recompute",),
        before_surface_hash="h3-before",
    )

    rejections: list[dict[str, object]] = [{
        "fixture_id": "H3-incompatible",
        "ref_id": "memory-h3-incompatible",
        "stage": "compatibility",
        "expected_reason": "runtime_signature_mismatch",
        "observed_reasons": list(h3_decision.reasons),
        "compatibility_decision": h3_decision.canonical_payload(),
        "disclosed": False,
        "actual_consumed": False,
        "current_recompute_verified": True,
        "rejected": h3_rejected,
    }]
    probes = (
        (
            "H2-wrong-rendered-hash",
            {
                "memory_inputs": (memory_input,),
                "consumed_memory_ids": ("memory-h2",),
                "consumption_modes": {"memory-h2": "rendered_prompt"},
                "rendered_request_hash": "wrong",
                "approved_rendered_request_hash": "approved",
                "output_decision_surface_hash": output_hash,
            },
            "memory_consumption_rendered_request_hash_mismatch",
        ),
        (
            "H2-ambiguous-recipe-binding",
            {
                "memory_inputs": (
                    _memory_input(
                        "memory-recipe-a",
                        replay_class=ReplayClass.VALIDATED_REPLAY,
                    ),
                    _memory_input(
                        "memory-recipe-b",
                        replay_class=ReplayClass.VALIDATED_REPLAY,
                    ),
                ),
                "consumed_memory_ids": ("memory-recipe-a", "memory-recipe-b"),
                "consumption_modes": {
                    "memory-recipe-a": "recipe_executed",
                    "memory-recipe-b": "recipe_executed",
                },
                "executed_recipe_hashes": (
                    "recipe-memory-recipe-a",
                    "recipe-memory-recipe-b",
                ),
                "output_decision_surface_hash": output_hash,
            },
            "memory_consumption_recipe_binding_ambiguous",
        ),
    )
    for fixture_id, arguments, expected_reason in probes:
        try:
            AdaptiveCapabilityDispatcher(
                context=AdaptiveDispatchContext(registry=CapabilityRegistry())
            )._record_memory_consumption(
                step=step,
                downstream_ref_ids=("artifact-rejected",),
                before_surface_hash="probe-before",
                **arguments,
            )
        except AdaptiveDispatchError as exc:
            observed = str(exc)
        else:
            observed = "not_rejected"
        rejections.append({
            "fixture_id": fixture_id,
            "stage": "receipt_validation",
            "expected_reason": expected_reason,
            "observed_reason": observed,
            "rejected": observed == expected_reason,
        })

    fixtures = {
        "H0": {
            "lane": "H0",
            "definition": "memory_off",
            "metrics": h0_metrics,
            "accounting": summarize_memory_consumption(
                h0_context.memory_consumption_records,
                candidate_count=0,
                approved_count=0,
                disclosed_count=0,
            ),
        },
        "H1": {
            "lane": "H1",
            "definition": "candidate_disclosed_role_did_not_use",
            "metrics": h1_metrics,
            "accounting": summarize_memory_consumption(
                h1_context.memory_consumption_records,
                candidate_count=1,
                approved_count=1,
                disclosed_count=1,
            ),
        },
        "H2": {
            "lane": "H2",
            "definition": "actual_receipt_bound_consumption",
            "metrics": h2_metrics,
            "records": [
                record.canonical_payload()
                for record in h2_context.memory_consumption_records
            ],
            "accounting": summarize_memory_consumption(
                h2_context.memory_consumption_records,
                candidate_count=1,
                approved_count=1,
                disclosed_count=1,
            ),
            "paired_effect_ledger": {
                **pair_payload,
                "counterfactual_evidence_hash": counterfactual_hash,
                "effect_evidence_hash": effect_hash,
            },
        },
        "H3": {
            "lane": "H3",
            "definition": "incompatible_candidate_rejected_current_recompute",
            "metrics": h3_metrics,
            "accounting": summarize_memory_consumption(
                h3_context.memory_consumption_records,
                candidate_count=1,
                approved_count=0,
                disclosed_count=0,
            ),
            "compatibility_decision": h3_decision.canonical_payload(),
            "rejection_fixture_id": "H3-incompatible",
            "current_recompute_verified": (
                h3_rejected
                and not h3_context.memory_consumption_records
                and h3_metrics["memory_consumed_count"] == 0.0
            ),
        },
    }
    return fixtures, rejections


@dataclass(frozen=True)
class _SemanticFixture:
    store: LayeredStateStore
    publication: object


def _embedding(embedding_id: str, vector: tuple[float, float]) -> StructuredEmbedding:
    return StructuredEmbedding(
        embedding_id=embedding_id,
        vector=vector,
        dims=2,
        source_text_hash=sha256_digest({"embedding_id": embedding_id}),
        encoding="contest-a1-semantic-fixture-v1",
    )


def _publish_semantic_fixture(
    root: Path,
    *,
    state_id: str,
    query_vector: tuple[float, float],
    candidate_order: tuple[str, str] = ("candidate-a", "candidate-b"),
) -> _SemanticFixture:
    vectors = {
        "candidate-a": (1.0, 0.0),
        "candidate-b": (0.0, 1.0),
    }
    manifest = HydrateManifest(
        manifest_id=f"manifest-{state_id}",
        source_doc_hashes=("doc-contest-a1",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=candidate_id,
                locator=FragmentLocator(
                    source_doc_hash="doc-contest-a1",
                    fragment_id=candidate_id,
                    extractor_version="contest-a1-v1",
                ),
                stable_key=candidate_id,
                byte_hint=32,
                importance_score=1.0,
            )
            for index, candidate_id in enumerate(candidate_order, start=1)
        ),
        canonicalizer_version="contest-a1-v1",
        extractor_version="contest-a1-v1",
    )
    store = LayeredStateStore(
        root=root / state_id,
        policy=LayeredStoragePolicy.for_state_pool_mode("mmap"),
    )
    publication = publish_dense_semantic_state(
        store=store,
        state_id=state_id,
        query_embedding=_embedding(f"query-{state_id}", query_vector),
        candidate_embeddings=tuple(
            _embedding(candidate_id, vectors[candidate_id])
            for candidate_id in candidate_order
        ),
        hydrate_manifest=manifest,
        owner_session_id="contest-a1-session",
        encoder_revision="contest-a1-v1",
    )
    return _SemanticFixture(store=store, publication=publication)


def _consume_semantic_fixture(
    root: Path,
    fixture: _SemanticFixture,
    *,
    expected_encoder_signature: str = "",
):
    publication = fixture.publication
    request = ExecRequest(
        header=ControlHeader(
            trace_id=f"trace-{publication.ref.state_id}",
            task_id="contest-a1-semantic",
            step_id="retrieve",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=20_000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(
            RefHandle(ref_id=publication.ref.state_id, ref_kind="semantic_state"),
        ),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(root / "workspace"),
        input_manifest_hash=publication.contract.hydrate_manifest_hash,
        operation="semantic_select_v1",
        state_root=str(fixture.store.root),
        hydrate_manifest_id=publication.contract.hydrate_manifest_id,
        semantic_top_k=1,
        evidence_budget_bytes=64,
        expected_encoder_signature=(
            expected_encoder_signature or publication.contract.encoder_signature
        ),
        capability_grant_hash="contest-a1-semantic-grant",
    )
    return SubprocessExecutorTransport(
        socket_path=root / f"{publication.ref.state_id}.sock",
        timeout_s=20.0,
    ).execute(request)


def _semantic_record(fixture: _SemanticFixture, selection: SuccessResult):
    publication = fixture.publication
    output_hash = sha256_digest({
        "selected_candidate_ids": selection.selected_candidate_ids,
        "selected_scores": selection.selected_scores,
    })
    record = build_state_consumption_record(
        state_ref_id=publication.ref.state_id,
        consumer_role="executor",
        consumer_step_id="retrieve",
        operation="cosine_topk_budget_pruning",
        read_field_ids=tuple(
            f"row:{index}" for index in (0, *selection.selected_row_indices)
        ),
        input_decision_surface_hash=sha256_digest({
            "manifest_hash": publication.contract.hydrate_manifest_hash,
        }),
        output_decision_surface_hash=output_hash,
        selected_ids=selection.selected_candidate_ids,
        downstream_ref_ids=("evidence:contest-a1:retrieve",),
        logical_owner_role="retriever",
        logical_step_id="retrieve",
        producer_role="retriever",
        producer_pid=selection.producer_pid,
        physical_consumer_component="runtime_semantic_selector",
        physical_consumer_pid=selection.consumer_pid,
        physical_consumer_uid=os.getuid(),
        downstream_role="executor",
        logical_target_role="executor",
        downstream_hydration_roles=("executor",),
        hydrate_manifest_id=publication.contract.hydrate_manifest_id,
        hydrate_manifest_hash=publication.contract.hydrate_manifest_hash,
        hydration_receipt_id=(
            f"state-hydration:{publication.ref.state_id}:retrieve:attempt-1"
        ),
    )
    fixture.store.release(publication.ref.state_id)
    return close_state_consumption_record(
        record,
        released_by_component="runtime_semantic_state_owner",
        release_reason="selection_hydrated",
    )


def _semantic_fixtures(
    root: Path,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    state_root = root / "semantic_state_fixtures"
    s1 = _publish_semantic_fixture(
        state_root,
        state_id="semantic-s1",
        query_vector=(1.0, 0.0),
    )
    s2 = _publish_semantic_fixture(
        state_root,
        state_id="semantic-s2-perturbed",
        query_vector=(0.0, 1.0),
    )
    s2_permuted = _publish_semantic_fixture(
        state_root,
        state_id="semantic-s2-permuted",
        query_vector=(1.0, 0.0),
        candidate_order=("candidate-b", "candidate-a"),
    )
    s3_signature = _publish_semantic_fixture(
        state_root,
        state_id="semantic-s3-signature",
        query_vector=(1.0, 0.0),
    )
    s3_expiry = _publish_semantic_fixture(
        state_root,
        state_id="semantic-s3-expiry",
        query_vector=(1.0, 0.0),
    )

    s1_selection = _consume_semantic_fixture(root, s1)
    s2_selection = _consume_semantic_fixture(root, s2)
    permuted_selection = _consume_semantic_fixture(root, s2_permuted)
    if not all(
        isinstance(item, SuccessResult)
        for item in (s1_selection, s2_selection, permuted_selection)
    ):
        raise RuntimeError("semantic_fixture_consumer_failed")
    s1_record = _semantic_record(s1, s1_selection)
    s2_record = _semantic_record(s2, s2_selection)
    permuted_record = _semantic_record(s2_permuted, permuted_selection)

    signature_result = _consume_semantic_fixture(
        root,
        s3_signature,
        expected_encoder_signature="wrong-signature",
    )
    signature_reason = (
        signature_result.error_detail
        if isinstance(signature_result, ErrorResult)
        else "not_rejected"
    )
    s3_signature.store.release(s3_signature.publication.ref.state_id)

    try:
        resolve_dense_semantic_state(
            state_root=s3_expiry.store.root,
            ref=s3_expiry.publication.ref,
            now_ns=s3_expiry.publication.contract.lease_expires_at_ns + 1,
        )
    except SemanticStateValidationError as exc:
        expiry_reason = str(exc)
    else:
        expiry_reason = "not_rejected"
    s3_expiry.store.release(s3_expiry.publication.ref.state_id)

    rejections = [
        {
            "fixture_id": "S3-wrong-encoder-signature",
            "stage": "semantic_resolve",
            "expected_reason": "dense_state_encoder_signature_mismatch",
            "observed_reason": signature_reason,
            "rejected": "encoder_signature_mismatch" in signature_reason,
            "released": not bool(s3_signature.store.materializations),
        },
        {
            "fixture_id": "S3-expired-lease",
            "stage": "semantic_resolve",
            "expected_reason": "dense_state_expired",
            "observed_reason": expiry_reason,
            "rejected": expiry_reason == "dense_state_expired",
            "released": not bool(s3_expiry.store.materializations),
        },
    ]
    return {
        "S0": {
            "lane": "S0",
            "definition": "semantic_state_off",
            "accounting": summarize_state_consumption([]),
        },
        "S1": {
            "lane": "S1",
            "definition": "cross_pid_dense_state_selection",
            "record": s1_record.canonical_payload(),
            "accounting": summarize_state_consumption([s1_record]),
        },
        "S2": {
            "lane": "S2",
            "definition": "approved_perturbation_and_matching_permutation",
            "perturbed_record": s2_record.canonical_payload(),
            "matching_permutation_record": permuted_record.canonical_payload(),
            "baseline_selected_ids": list(s1_record.selected_ids),
            "perturbed_selected_ids": list(s2_record.selected_ids),
            "matching_permutation_selected_ids": list(permuted_record.selected_ids),
            "perturbation_changed_selected_ids": (
                s1_record.selected_ids != s2_record.selected_ids
            ),
            "perturbation_changed_action_surface": (
                s1_record.output_decision_surface_hash
                != s2_record.output_decision_surface_hash
            ),
            "matching_permutation_preserved_identity": (
                s1_record.selected_ids == permuted_record.selected_ids
            ),
            "accounting": summarize_state_consumption(
                [s2_record, permuted_record]
            ),
        },
        "S3": {
            "lane": "S3",
            "definition": "incompatible_or_expired_ref_fail_closed",
            "rejection_fixture_ids": [item["fixture_id"] for item in rejections],
            "all_released": all(item["released"] for item in rejections),
        },
    }, rejections


def _accounting_contract() -> dict[str, object]:
    return {
        "schema_version": "statebus.accounting_contract.v1",
        "memory_funnel": [
            "candidate",
            "approved",
            "projected",
            "actual_consumed",
            "action",
            "effect",
        ],
        "memory_actual_consumption_rule": (
            "receipt_validated=true and an approved rendered_request_hash or "
            "candidate-specific executed_recipe_hash is present"
        ),
        "memory_effect_rule": (
            "effect_evidence_hash must bind the before/output surfaces and paired "
            "counterfactual evidence; action alone is not effect"
        ),
        "legacy_rule": (
            "legacy smoke rows remain recorded compatibility evidence and never "
            "become actual consumption without receipt validation"
        ),
        "semantic_identity_fields": [
            "producer_role",
            "producer_pid",
            "physical_consumer_component",
            "physical_consumer_pid",
            "logical_target_role",
            "downstream_hydration_roles",
        ],
        "semantic_lifecycle": [
            "publish",
            "resolve",
            "consume",
            "hydrate",
            "release",
        ],
        "pid_accounting_rule": "PID values are identity sets, never additive metrics",
        "formal_invariants": {
            "latent_mode": "off",
            "latent_handoff_mode": "off",
            "latent_prompt_embeds_enabled": False,
            "benefit_claim_allowed": False,
        },
        "memory_lanes": {
            "H0": "memory off",
            "H1": "candidate disclosed but unused",
            "H2": "actual prompt or recipe receipt",
            "H3": "incompatible or expired candidate rejected",
        },
        "semantic_lanes": {
            "S0": "semantic state off",
            "S1": "typed dense state with independent selector",
            "S2": "approved perturbation and permutation controls",
            "S3": "incompatible or expired ref rejected",
        },
    }


def write_a1_acceptance_bundle(
    *,
    run_root: Path,
    project_root: Path,
    pytest_junit: Path | None = None,
    test_command: str = "python3 -m pytest -q",
) -> dict[str, object]:
    run_root = Path(run_root)
    if run_root.exists():
        raise FileExistsError(f"a1_run_root_already_exists:{run_root}")
    run_root.mkdir(parents=True)

    source_identity = _source_identity(project_root)
    memory, memory_rejections = _memory_fixtures()
    semantic, semantic_rejections = _semantic_fixtures(run_root)
    rejections = [*memory_rejections, *semantic_rejections]
    checks = {
        "source_worktree_clean": source_identity["worktree_clean"] is True,
        "H0_zero_actual": memory["H0"]["accounting"]["actual_consumed_count"] == 0,
        "H1_disclosed_zero_actual": (
            memory["H1"]["accounting"]["disclosed_count"] == 1
            and memory["H1"]["accounting"]["actual_consumed_count"] == 0
        ),
        "H2_receipt_actual_action_effect_separate": (
            memory["H2"]["accounting"]["actual_consumed_count"] == 1
            and memory["H2"]["accounting"]["action_count"] == 1
            and memory["H2"]["accounting"]["behavioral_effect_count"] == 1
        ),
        "H3_rejected_zero_actual": (
            memory["H3"]["accounting"]["actual_consumed_count"] == 0
            and memory["H3"]["compatibility_decision"]["verdict"]
            == CompatibilityVerdict.INCOMPATIBLE.value
            and memory["H3"]["compatibility_decision"]["policy_approved"] is False
            and memory["H3"]["current_recompute_verified"] is True
        ),
        "S0_zero_state": semantic["S0"]["accounting"]["record_count"] == 0,
        "S1_cross_pid_hydrated_released": (
            semantic["S1"]["accounting"]["cross_process_count"] == 1
            and semantic["S1"]["accounting"]["hydrated_count"] == 1
            and semantic["S1"]["accounting"]["released_count"] == 1
        ),
        "S2_perturbation_and_permutation_controls": (
            semantic["S2"]["perturbation_changed_selected_ids"] is True
            and semantic["S2"]["perturbation_changed_action_surface"] is True
            and semantic["S2"]["matching_permutation_preserved_identity"] is True
        ),
        "S3_fail_closed_and_released": (
            semantic["S3"]["all_released"] is True
            and all(item.get("rejected") is True for item in semantic_rejections)
        ),
        "all_negative_probes_rejected": all(
            item.get("rejected") is True for item in rejections
        ),
        "all_live_action_gates_off": all(
            os.getenv(gate, "0").strip() == "0" for gate in ACTION_GATES
        ),
    }
    tests_payload: dict[str, object] = {
        "schema_version": "statebus.a1_tests.v1",
        "command": test_command,
        "junit_attached": False,
    }
    if pytest_junit is not None:
        tests_dir = run_root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        copied_junit = tests_dir / "pytest-junit.xml"
        shutil.copyfile(pytest_junit, copied_junit)
        tests_payload = {
            **_pytest_junit_payload(
                copied_junit,
                command=test_command,
                source_git_commit=str(source_identity["git_commit"]),
            ),
            "junit_attached": True,
            "junit_path": str(copied_junit.relative_to(run_root)),
        }
        checks["attached_pytest_passed"] = tests_payload["ok"] is True

    summary = {
        "schema_version": A1_SCHEMA_VERSION,
        "stage": "A1",
        "status": "passed" if all(checks.values()) else "failed",
        "ok": all(checks.values()),
        "checks": checks,
        "claim_scope": {
            "implemented": True,
            "tested": True,
            "live_model_observed": False,
            "memory_benefit_observed": False,
            "semantic_benefit_observed": False,
            "unlocked_future_runs": ["R1", "R4"],
        },
        "created_at_ns": time.time_ns(),
    }
    _write_json(run_root / "accounting_contract.json", _accounting_contract())
    for lane, payload in sorted(memory.items()):
        _write_json(run_root / "fixtures" / "memory" / f"{lane}.json", payload)
    for lane, payload in sorted(semantic.items()):
        _write_json(run_root / "fixtures" / "semantic" / f"{lane}.json", payload)
    _write_json(run_root / "rejection_ledger.json", {
        "schema_version": "statebus.a1_rejection_ledger.v1",
        "records": rejections,
    })
    _write_json(run_root / "source_identity.json", source_identity)
    _write_json(run_root / "environment.json", {
        "schema_version": "statebus.a1_environment.v1",
        "pid": os.getpid(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "action_gates": {gate: os.getenv(gate, "0") for gate in ACTION_GATES},
        "live_endpoint_accessed": False,
    })
    _write_json(run_root / "tests.json", tests_payload)
    _write_json(run_root / "summary.json", summary)
    _write_checksums(run_root)
    checksum_result = verify_artifact_checksums(run_root)
    return {
        **summary,
        "run_root": str(run_root),
        "checksums": checksum_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the offline StateBus contest rebuild A1 accounting bundle."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--pytest-junit", type=Path)
    parser.add_argument("--test-command", default="python3 -m pytest -q")
    args = parser.parse_args()
    result = write_a1_acceptance_bundle(
        run_root=args.run_root,
        project_root=args.project_root,
        pytest_junit=args.pytest_junit,
        test_command=args.test_command,
    )
    print(stable_json_dumps({
        "stage": "A1",
        "status": result["status"],
        "ok": result["ok"],
        "run_root": result["run_root"],
        "checksums_ok": result["checksums"]["ok"],
    }))
    raise SystemExit(0 if result["ok"] and result["checksums"]["ok"] else 1)


if __name__ == "__main__":
    main()
