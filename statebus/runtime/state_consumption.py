from __future__ import annotations

import time

from statebus.contracts import StateConsumptionRecord
from statebus.utils import sha256_digest


def build_state_publication_receipt(
    *,
    publication: object,
    runtime_identity: object,
    producer_grant: object,
    producer_binding_id: str,
    execution_binding_hash: str,
    cache_epoch: str,
) -> dict[str, object]:
    """Project Runtime-owned publication provenance without changing State contracts."""
    ref = getattr(publication, "ref")
    contract = getattr(publication, "contract")
    grant = getattr(producer_grant, "grant", producer_grant)
    return {
        "schema_version": "statebus.state_publication_receipt.v1",
        "task_id": str(getattr(runtime_identity, "runtime_task_id", "")),
        "run_id": str(getattr(runtime_identity, "run_id", "")),
        "session_id": str(getattr(runtime_identity, "session_id", "")),
        "step_id": str(getattr(grant, "step_id", "")),
        "attempt_id": str(getattr(grant, "attempt_id", "")),
        "grant_id": str(getattr(grant, "grant_id", "")),
        "capability_grant_hash": str(getattr(grant, "grant_hash", "")),
        "execution_binding_hash": execution_binding_hash,
        "producer_binding_id": producer_binding_id,
        "state_ref_id": str(getattr(ref, "state_id", "")),
        "state_identity_hash": str(getattr(ref, "state_identity_hash", "")),
        "state_kind": str(getattr(ref, "state_kind", "")),
        "blob_hash": str(getattr(ref, "blob_hash", "")),
        "size_bytes": int(getattr(ref, "length", 0)),
        "manifest_id": str(getattr(ref, "manifest_id", "")),
        "manifest_hash": str(getattr(contract, "hydrate_manifest_hash", "")),
        "encoder_signature": str(getattr(contract, "encoder_signature", "")),
        "encoder_hash": str(getattr(contract, "encoder_signature", "")),
        "producer_pid": int(getattr(contract, "producer_pid", 0)),
        "cache_epoch": cache_epoch,
        "published_at_ns": time.time_ns(),
        "receipt_status": "observed",
    }


def build_semantic_consumer_receipt(
    *,
    publication: object,
    response: object,
    runtime_identity: object,
    grant: object,
    state_access_grant_hash: str,
    execution_binding_hash: str,
    pin_id: str,
    downstream_ref_ids: tuple[str, ...],
    input_decision_surface_hash: str,
    output_decision_surface_hash: str,
    response_admission_hash: str = "",
    descriptor_identity: dict[str, object] | None = None,
    read_started_at_ns: int = 0,
    read_completed_at_ns: int = 0,
) -> dict[str, object]:
    """Project an admitted worker result as an auditable consumer receipt."""
    ref = getattr(publication, "ref")
    descriptor = dict(descriptor_identity or {})
    terminal_admission_hash = response_admission_hash or sha256_digest({
        "invocation_id": str(getattr(getattr(response, "header", None), "invocation_id", "")),
        "state_ref_id": str(getattr(ref, "state_id", "")),
        "completed_at_ns": int(getattr(response, "completed_at_ns", 0)),
    })
    return {
        "schema_version": "statebus.semantic_consumer_receipt.v1",
        "trace_id": str(getattr(runtime_identity, "trace_id", "")),
        "task_id": str(getattr(runtime_identity, "runtime_task_id", "")),
        "run_id": str(getattr(runtime_identity, "run_id", "")),
        "session_id": str(getattr(runtime_identity, "session_id", "")),
        "step_id": str(getattr(grant, "step_id", "")),
        "attempt_id": str(getattr(grant, "attempt_id", "")),
        "invocation_id": str(getattr(getattr(response, "header", None), "invocation_id", "")),
        "execution_binding_hash": execution_binding_hash,
        "capability_grant_hash": str(getattr(grant, "grant_hash", "")),
        "state_ref_id": str(getattr(ref, "state_id", "")),
        "state_identity_hash": str(getattr(ref, "state_identity_hash", "")),
        "state_access_grant_hash": state_access_grant_hash,
        "grant_id": str(getattr(grant, "grant_id", "")),
        "binding_id": str(descriptor.get("binding_id", "")),
        "binding_hash": execution_binding_hash,
        "descriptor_identity": descriptor,
        "handle_identity": descriptor.get("handle_identity", {}),
        "blob_hash": str(descriptor.get("blob_hash", getattr(ref, "blob_hash", ""))),
        "manifest_id": str(descriptor.get("manifest_id", getattr(ref, "manifest_id", ""))),
        "manifest_hash": str(descriptor.get("manifest_hash", "")),
        "encoder_hash": str(descriptor.get("encoder_hash", "")),
        "cache_epoch": str(descriptor.get("cache_epoch", "")),
        "observed_size_bytes": int(descriptor.get("size_bytes", 0)),
        "observed_shape": list(descriptor.get("shape", ())),
        "observed_dtype": str(descriptor.get("dtype", "")),
        "observed_blob_hash": str(descriptor.get("blob_hash", getattr(ref, "blob_hash", ""))),
        "producer_pid": int(getattr(response, "producer_pid", 0)),
        "consumer_pid": int(getattr(response, "consumer_pid", 0)),
        "read_started_at_ns": int(read_started_at_ns),
        "read_completed_at_ns": int(read_completed_at_ns or getattr(response, "completed_at_ns", 0)),
        "selected_candidate_ids": list(getattr(response, "selected_candidate_ids", ())),
        "selected_row_indices": list(getattr(response, "selected_row_indices", ())),
        "selected_evidence_bytes": int(getattr(response, "selected_evidence_bytes", 0)),
        "selected_ids": list(getattr(response, "selected_candidate_ids", ())),
        "selected_rows": list(getattr(response, "selected_row_indices", ())),
        "selected_bytes": int(getattr(response, "selected_evidence_bytes", 0)),
        "input_decision_surface_hash": input_decision_surface_hash,
        "output_decision_surface_hash": output_decision_surface_hash,
        "downstream_ref_ids": list(downstream_ref_ids),
        "behavioral_effect": (
            "changed"
            if input_decision_surface_hash != output_decision_surface_hash
            else "no_effect"
        ),
        "pin_id": pin_id,
        "release_status": "pending_response_admission",
        "response_admission_hash": terminal_admission_hash,
        "downstream_ref": downstream_ref_ids[0] if downstream_ref_ids else "",
        "receipt_status": "observed",
    }


def build_state_pin_receipt(
    *,
    pin: object,
    phase: str,
    status: str,
    released_at_ns: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": "statebus.state_pin_receipt.v1",
        "pin_id": str(getattr(pin, "pin_id", "")),
        "state_ref_id": str(getattr(pin, "ref_id", "")),
        "session_id": str(getattr(pin, "session_id", "")),
        "step_id": str(getattr(pin, "step_id", "")),
        "attempt_id": str(getattr(pin, "attempt_id", "")),
        "state_access_grant_id": str(getattr(pin, "state_access_grant_id", "")),
        "physical_invocation_id": str(getattr(pin, "physical_invocation_id", "")),
        "consumer_role": str(getattr(pin, "consumer_role", "")),
        "consumer_provider_id": str(getattr(pin, "consumer_provider_id", "")),
        "phase": phase,
        "status": status,
        "acquired_at_ns": int(getattr(pin, "acquired_at_ns", 0)),
        "released_at_ns": released_at_ns,
    }


def build_state_release_reclaim_receipt(
    *,
    lifetime: object,
    owner_session_id: str,
    released_at_ns: int | None = None,
    producer_task_id: str = "",
    producer_grant_hash: str = "",
    lease_id: str = "",
    lease_expires_at_ns: int = 0,
    response_admitted_at_ns: int = 0,
    downstream_effect_completed_at_ns: int = 0,
    worker_pin_released_at_ns: int = 0,
    runtime_pin_released_at_ns: int = 0,
    owner_released_at_ns: int = 0,
    physical_reclaimed_at_ns: int = 0,
) -> dict[str, object]:
    released_pin_ids = sorted(getattr(lifetime, "released_pins", {}) or {})
    return {
        "schema_version": "statebus.state_release_reclaim.v1",
        "producer_task_id": producer_task_id,
        "producer_session_id": owner_session_id,
        "state_ref_id": str(getattr(lifetime, "ref_id", "")),
        "owner_session_id": owner_session_id,
        "producer_step_id": str(getattr(lifetime, "producer_step_id", "")),
        "producer_attempt_id": str(getattr(lifetime, "producer_attempt_id", "")),
        "grant_hash": producer_grant_hash,
        "lease_id": lease_id,
        "lease_expires_at_ns": lease_expires_at_ns,
        "owner_released": bool(getattr(lifetime, "owner_released", False)),
        "live_pin_count": int(getattr(lifetime, "live_pin_count", 0)),
        "released_pin_ids": released_pin_ids,
        "physical_reclaimed": bool(getattr(lifetime, "physical_reclaimed", False)),
        "released_at_ns": time.time_ns() if released_at_ns is None else released_at_ns,
        "release_status": "reclaimed" if getattr(lifetime, "physical_reclaimed", False) else "released",
        "response_admitted_at_ns": response_admitted_at_ns,
        "downstream_effect_completed_at_ns": downstream_effect_completed_at_ns,
        "worker_pin_released_at_ns": worker_pin_released_at_ns,
        "runtime_pin_released_at_ns": runtime_pin_released_at_ns,
        "owner_released_at_ns": owner_released_at_ns,
        "physical_reclaimed_at_ns": physical_reclaimed_at_ns,
        "release_after_response_admission": bool(
            response_admitted_at_ns
            and downstream_effect_completed_at_ns
            and worker_pin_released_at_ns
            and runtime_pin_released_at_ns
            and owner_released_at_ns
            and physical_reclaimed_at_ns
            and response_admitted_at_ns < downstream_effect_completed_at_ns
            <= worker_pin_released_at_ns <= runtime_pin_released_at_ns
            <= owner_released_at_ns <= physical_reclaimed_at_ns
        ),
    }


def build_state_consumption_record(
    *,
    state_ref_id: str,
    consumer_role: str,
    consumer_step_id: str,
    operation: str,
    read_field_ids: tuple[str, ...],
    input_decision_surface_hash: str,
    output_decision_surface_hash: str,
    selected_ids: tuple[str, ...],
    downstream_ref_ids: tuple[str, ...] = (),
    comparable_decision_surfaces: bool = True,
    consumed_at_ns: int | None = None,
) -> StateConsumptionRecord:
    return StateConsumptionRecord(
        state_ref_id=state_ref_id,
        consumer_role=consumer_role,
        consumer_step_id=consumer_step_id,
        operation=operation,
        read_field_ids=tuple(sorted(read_field_ids)),
        input_decision_surface_hash=input_decision_surface_hash,
        output_decision_surface_hash=output_decision_surface_hash,
        selected_ids=tuple(selected_ids),
        behavioral_effect=(
            "changed" if input_decision_surface_hash != output_decision_surface_hash else "no_effect"
        ) if comparable_decision_surfaces else "not_evaluated",
        downstream_ref_ids=tuple(sorted(downstream_ref_ids)),
        consumed_at_ns=time.time_ns() if consumed_at_ns is None else consumed_at_ns,
    )
