from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from runtime.llm import LLMConfig
from v2.benchmark.experiment_design import audit_preregistered_lane_matrix
from v2.runtime import runtime_preflight


_LATENT_INVARIANTS = (
    "latent_mode",
    "latent_handoff_mode",
    "latent_prompt_embeds_enabled",
)
_FORMAL_REQUEST_INVARIANTS = (
    "formal_request_mode",
    "formal_request_concurrency",
)
_ALLOWED_TREATMENT_VALUES = {
    "control_plane": {"matched_text_collaboration", "typed_protobuf_uds"},
    "semantic_state": {"off", "embedding_selected_hydration"},
    "memory_policy": {"off", "compatible_assist_replay"},
    "prefix_policy": {"off", "observe", "on"},
    "logit_policy": {"off", "telemetry_only", "gated"},
}


@dataclass(frozen=True)
class ContestTreatmentLane:
    matrix_id: str
    lane_id: str
    description: str
    control_plane: str
    semantic_state: str
    memory_policy: str
    prefix_policy: str
    logit_policy: str
    latent_mode: str = "off"
    latent_handoff_mode: str = "off"
    latent_prompt_embeds_enabled: bool = False
    formal_request_mode: str = "serialized"
    formal_request_concurrency: int = 1

    def canonical_payload(self) -> dict[str, object]:
        return {
            "matrix_id": self.matrix_id,
            "lane_id": self.lane_id,
            "description": self.description,
            "control_plane": self.control_plane,
            "semantic_state": self.semantic_state,
            "memory_policy": self.memory_policy,
            "prefix_policy": self.prefix_policy,
            "logit_policy": self.logit_policy,
            "latent_mode": self.latent_mode,
            "latent_handoff_mode": self.latent_handoff_mode,
            "latent_prompt_embeds_enabled": self.latent_prompt_embeds_enabled,
            "formal_request_mode": self.formal_request_mode,
            "formal_request_concurrency": self.formal_request_concurrency,
        }


def contest_main_treatment_matrix() -> tuple[ContestTreatmentLane, ...]:
    base = ContestTreatmentLane(
        matrix_id="contest-main-l0-l3-v1",
        lane_id="L0",
        description="matched text comparator inside StateBus harness",
        control_plane="matched_text_collaboration",
        semantic_state="off",
        memory_policy="off",
        prefix_policy="off",
        logit_policy="off",
    )
    return (
        base,
        replace(
            base,
            lane_id="L1",
            description="L0 plus typed Protobuf over UDS control",
            control_plane="typed_protobuf_uds",
        ),
        replace(
            base,
            lane_id="L2",
            description="L1 plus embedding SemanticStateRef selected hydration",
            control_plane="typed_protobuf_uds",
            semantic_state="embedding_selected_hydration",
        ),
        replace(
            base,
            lane_id="L3",
            description="L2 plus compatible MemoryRef assist and replay",
            control_plane="typed_protobuf_uds",
            semantic_state="embedding_selected_hydration",
            memory_policy="compatible_assist_replay",
        ),
    )


def contest_prefix_treatment_matrix() -> tuple[ContestTreatmentLane, ...]:
    base = ContestTreatmentLane(
        matrix_id="contest-prefix-pc-v1",
        lane_id="P-C-off",
        description="engine-local prefix policy disabled",
        control_plane="typed_protobuf_uds",
        semantic_state="embedding_selected_hydration",
        memory_policy="off",
        prefix_policy="off",
        logit_policy="off",
    )
    return (
        base,
        replace(
            base,
            lane_id="P-C-on",
            description="engine-local prefix policy enabled",
            prefix_policy="on",
        ),
    )


def contest_logit_treatment_matrix() -> tuple[ContestTreatmentLane, ...]:
    base = ContestTreatmentLane(
        matrix_id="contest-logit-lc-v1",
        lane_id="L-C-off",
        description="LogitState disabled",
        control_plane="typed_protobuf_uds",
        semantic_state="embedding_selected_hydration",
        memory_policy="off",
        prefix_policy="off",
        logit_policy="off",
    )
    return (
        base,
        replace(
            base,
            lane_id="L-C-telemetry",
            description="LogitState telemetry without action",
            logit_policy="telemetry_only",
        ),
        replace(
            base,
            lane_id="L-C-gated",
            description="calibrated LogitState bounded gate",
            logit_policy="gated",
        ),
    )


def _audit_treatment_matrix(
    lanes: Sequence[ContestTreatmentLane],
    *,
    matrix_id: str,
    expected_lane_order: Sequence[str],
    expected_adjacent_changes: Sequence[Sequence[str]],
) -> dict[str, object]:
    audit = audit_preregistered_lane_matrix(
        [lane.canonical_payload() for lane in lanes],
        matrix_id=matrix_id,
        expected_lane_order=expected_lane_order,
        expected_adjacent_changes=expected_adjacent_changes,
        invariant_fields=(*_LATENT_INVARIANTS, *_FORMAL_REQUEST_INVARIANTS),
    )
    errors = list(audit["errors"])
    for lane in lanes:
        payload = lane.canonical_payload()
        for field, allowed_values in _ALLOWED_TREATMENT_VALUES.items():
            if payload[field] not in allowed_values:
                errors.append({
                    "kind": "treatment_value_invalid",
                    "lane_id": lane.lane_id,
                    "field": field,
                    "observed": payload[field],
                })
        if (
            payload["latent_mode"] != "off"
            or payload["latent_handoff_mode"] != "off"
            or payload["latent_prompt_embeds_enabled"] is not False
        ):
            errors.append({
                "kind": "latent_treatment_forbidden",
                "lane_id": lane.lane_id,
            })
        if (
            payload["formal_request_mode"] != "serialized"
            or payload["formal_request_concurrency"] != 1
        ):
            errors.append({
                "kind": "formal_request_not_serialized",
                "lane_id": lane.lane_id,
            })
    return {**audit, "ok": not errors, "errors": errors}


def audit_contest_treatment_matrices(
    *,
    main: Sequence[ContestTreatmentLane] | None = None,
    prefix: Sequence[ContestTreatmentLane] | None = None,
    logit: Sequence[ContestTreatmentLane] | None = None,
) -> dict[str, object]:
    main_lanes = tuple(
        contest_main_treatment_matrix() if main is None else main
    )
    prefix_lanes = tuple(
        contest_prefix_treatment_matrix() if prefix is None else prefix
    )
    logit_lanes = tuple(
        contest_logit_treatment_matrix() if logit is None else logit
    )
    audits = {
        "main": _audit_treatment_matrix(
            main_lanes,
            matrix_id="contest-main-l0-l3-v1",
            expected_lane_order=("L0", "L1", "L2", "L3"),
            expected_adjacent_changes=(
                ("control_plane",),
                ("semantic_state",),
                ("memory_policy",),
            ),
        ),
        "prefix": _audit_treatment_matrix(
            prefix_lanes,
            matrix_id="contest-prefix-pc-v1",
            expected_lane_order=("P-C-off", "P-C-on"),
            expected_adjacent_changes=(("prefix_policy",),),
        ),
        "logit": _audit_treatment_matrix(
            logit_lanes,
            matrix_id="contest-logit-lc-v1",
            expected_lane_order=("L-C-off", "L-C-telemetry", "L-C-gated"),
            expected_adjacent_changes=(("logit_policy",), ("logit_policy",)),
        ),
    }
    return {
        "schema_version": "statebus.contest_treatment_matrix_audit.v1",
        "ok": all(bool(audit["ok"]) for audit in audits.values()),
        "matrices": {
            "main": [lane.canonical_payload() for lane in main_lanes],
            "prefix": [lane.canonical_payload() for lane in prefix_lanes],
            "logit": [lane.canonical_payload() for lane in logit_lanes],
        },
        "audits": audits,
    }


def benchmark_role_path_mode_missing_reason(role_path_mode: str) -> str:
    normalized_mode = str(role_path_mode).strip().lower()
    try:
        LLMConfig.from_runtime().with_mode(normalized_mode).require_api_ready()
    except Exception as exc:
        return f"role_path_mode={normalized_mode} not ready: {exc}"
    return ""


def benchmark_role_path_mode_ready(role_path_mode: str) -> bool:
    return benchmark_role_path_mode_missing_reason(role_path_mode) == ""


def benchmark_runtime_missing_reason(
    *,
    role_path_mode: str,
    embedding_mode: str = "deterministic",
) -> str:
    report = runtime_preflight(
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    if report.ok:
        return ""
    return "; ".join(report.missing_reasons)
