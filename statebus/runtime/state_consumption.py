from __future__ import annotations

import time

from statebus.contracts import StateConsumptionRecord


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
