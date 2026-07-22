from __future__ import annotations

from dataclasses import replace
import time

from v2.contracts import StateConsumptionRecord
from v2.utils import sha256_digest


class StateConsumptionValidationError(ValueError):
    pass


def hydration_receipt_hash(
    *,
    state_ref_id: str,
    selected_ids: tuple[str, ...],
    downstream_ref_ids: tuple[str, ...],
    logical_target_role: str,
    downstream_hydration_roles: tuple[str, ...],
    hydrate_manifest_hash: str,
    output_decision_surface_hash: str,
) -> str:
    return sha256_digest({
        "state_ref_id": state_ref_id,
        "selected_ids": list(selected_ids),
        "downstream_ref_ids": list(downstream_ref_ids),
        "logical_target_role": logical_target_role,
        "downstream_hydration_roles": list(downstream_hydration_roles),
        "hydrate_manifest_hash": hydrate_manifest_hash,
        "output_decision_surface_hash": output_decision_surface_hash,
    })


def release_receipt_hash(
    *,
    receipt_id: str,
    state_ref_id: str,
    hydration_receipt_hash_value: str,
    producer_pid: int,
    physical_consumer_pid: int,
    released_by_component: str,
    release_reason: str,
    released_at_ns: int,
) -> str:
    return sha256_digest({
        "receipt_id": receipt_id,
        "state_ref_id": state_ref_id,
        "hydration_receipt_hash": hydration_receipt_hash_value,
        "producer_pid": producer_pid,
        "physical_consumer_pid": physical_consumer_pid,
        "released_by_component": released_by_component,
        "release_reason": release_reason,
        "released_at_ns": released_at_ns,
    })


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
    logical_owner_role: str = "",
    logical_step_id: str = "",
    producer_role: str = "",
    producer_pid: int = 0,
    physical_consumer_component: str = "",
    physical_consumer_pid: int = 0,
    physical_consumer_uid: int = 0,
    downstream_role: str = "",
    logical_target_role: str = "",
    downstream_hydration_roles: tuple[str, ...] = (),
    hydrate_manifest_id: str = "",
    hydrate_manifest_hash: str = "",
    hydration_receipt_id: str = "",
    hydration_receipt_hash_value: str = "",
    comparable_decision_surfaces: bool = True,
    consumed_at_ns: int | None = None,
) -> StateConsumptionRecord:
    target_role = logical_target_role or downstream_role or consumer_role
    hydration_roles = tuple(dict.fromkeys(downstream_hydration_roles))
    expected_hydration_hash = ""
    if hydration_receipt_id:
        expected_hydration_hash = hydration_receipt_hash(
            state_ref_id=state_ref_id,
            selected_ids=selected_ids,
            downstream_ref_ids=downstream_ref_ids,
            logical_target_role=target_role,
            downstream_hydration_roles=hydration_roles,
            hydrate_manifest_hash=hydrate_manifest_hash,
            output_decision_surface_hash=output_decision_surface_hash,
        )
        if hydration_receipt_hash_value and hydration_receipt_hash_value != expected_hydration_hash:
            raise StateConsumptionValidationError("state_hydration_receipt_hash_mismatch")
    record = StateConsumptionRecord(
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
        logical_owner_role=logical_owner_role,
        logical_step_id=logical_step_id,
        producer_role=producer_role or logical_owner_role,
        producer_pid=int(producer_pid),
        physical_consumer_component=physical_consumer_component,
        physical_consumer_pid=int(physical_consumer_pid),
        physical_consumer_uid=int(physical_consumer_uid),
        downstream_role=downstream_role,
        logical_target_role=target_role,
        downstream_hydration_roles=hydration_roles,
        hydrate_manifest_id=hydrate_manifest_id,
        hydrate_manifest_hash=hydrate_manifest_hash,
        hydration_receipt_id=hydration_receipt_id,
        hydration_receipt_hash=expected_hydration_hash,
        consumed_at_ns=time.time_ns() if consumed_at_ns is None else consumed_at_ns,
    )
    validate_state_consumption_record(record, require_release=False)
    return record


def close_state_consumption_record(
    record: StateConsumptionRecord,
    *,
    released_by_component: str,
    release_reason: str,
    released_at_ns: int | None = None,
) -> StateConsumptionRecord:
    timestamp = time.time_ns() if released_at_ns is None else int(released_at_ns)
    receipt_id = f"state-release:{record.state_ref_id}:{record.consumer_step_id}"
    receipt_hash = release_receipt_hash(
        receipt_id=receipt_id,
        state_ref_id=record.state_ref_id,
        hydration_receipt_hash_value=record.hydration_receipt_hash,
        producer_pid=record.producer_pid,
        physical_consumer_pid=record.physical_consumer_pid,
        released_by_component=released_by_component,
        release_reason=release_reason,
        released_at_ns=timestamp,
    )
    closed = replace(
        record,
        release_receipt_id=receipt_id,
        release_receipt_hash=receipt_hash,
        released_by_component=released_by_component,
        release_reason=release_reason,
        released_at_ns=timestamp,
    )
    validate_state_consumption_record(closed, require_release=True)
    return closed


def validate_state_consumption_record(
    record: StateConsumptionRecord,
    *,
    require_release: bool,
) -> None:
    if record.producer_pid < 0 or record.physical_consumer_pid < 0:
        raise StateConsumptionValidationError("state_consumer_pid_invalid")
    if record.physical_consumer_pid and record.producer_pid == record.physical_consumer_pid:
        raise StateConsumptionValidationError("state_consumer_not_cross_process")
    if bool(record.hydration_receipt_id) != bool(record.hydration_receipt_hash):
        raise StateConsumptionValidationError("state_hydration_receipt_incomplete")
    if record.hydration_receipt_id:
        expected = hydration_receipt_hash(
            state_ref_id=record.state_ref_id,
            selected_ids=record.selected_ids,
            downstream_ref_ids=record.downstream_ref_ids,
            logical_target_role=record.logical_target_role,
            downstream_hydration_roles=record.downstream_hydration_roles,
            hydrate_manifest_hash=record.hydrate_manifest_hash,
            output_decision_surface_hash=record.output_decision_surface_hash,
        )
        if record.hydration_receipt_hash != expected:
            raise StateConsumptionValidationError("state_hydration_receipt_hash_mismatch")
    release_fields = (
        record.release_receipt_id,
        record.release_receipt_hash,
        record.released_by_component,
        record.release_reason,
        record.released_at_ns,
    )
    if any(release_fields):
        if not all(release_fields) or record.released_at_ns < record.consumed_at_ns:
            raise StateConsumptionValidationError("state_release_receipt_missing")
        expected_release_hash = release_receipt_hash(
            receipt_id=record.release_receipt_id,
            state_ref_id=record.state_ref_id,
            hydration_receipt_hash_value=record.hydration_receipt_hash,
            producer_pid=record.producer_pid,
            physical_consumer_pid=record.physical_consumer_pid,
            released_by_component=record.released_by_component,
            release_reason=record.release_reason,
            released_at_ns=record.released_at_ns,
        )
        if record.release_receipt_hash != expected_release_hash:
            raise StateConsumptionValidationError("state_release_receipt_hash_mismatch")
    elif require_release:
        raise StateConsumptionValidationError("state_release_receipt_missing")


def summarize_state_consumption(
    records: tuple[StateConsumptionRecord, ...] | list[StateConsumptionRecord],
) -> dict[str, object]:
    rows = tuple(records)
    consumer_pids = sorted({row.physical_consumer_pid for row in rows if row.physical_consumer_pid > 0})
    producer_pids = sorted({row.producer_pid for row in rows if row.producer_pid > 0})
    return {
        "record_count": len(rows),
        "hydrated_count": sum(bool(row.hydration_receipt_hash) for row in rows),
        "released_count": sum(bool(row.release_receipt_hash) for row in rows),
        "cross_process_count": sum(
            row.producer_pid > 0
            and row.physical_consumer_pid > 0
            and row.producer_pid != row.physical_consumer_pid
            for row in rows
        ),
        "producer_pids": producer_pids,
        "physical_consumer_pids": consumer_pids,
        "logical_target_roles": sorted({row.logical_target_role for row in rows if row.logical_target_role}),
        "downstream_hydration_roles": sorted({
            role for row in rows for role in row.downstream_hydration_roles
        }),
    }
