from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Any

from v2.contracts import GateAction, GateDecision, LogitPolicy
from v2.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    LogitGateResult,
    LogitStateGrantControl,
    LogitStateRefControl,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.refs import LogitStateRefV2
from v2.state.logit_state import (
    LogitStateGrant,
    LogitStateValidationError,
    ResolvedLogitState,
)
from v2.utils import sha256_digest, stable_json_dumps


class ConfidenceGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenGatePolicy:
    temperature: float
    accept_probability_min: float
    verify_probability_min: float
    selection_retry_margin_max: float
    max_actions: int = 1
    calibration_kind: str = "temperature_v1"
    schema_version: str = "statebus.logit_gate_policy.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "statebus.logit_gate_policy.v1":
            raise ValueError(f"unsupported gate policy schema: {self.schema_version}")
        if self.calibration_kind not in {"identity_v1", "temperature_v1"}:
            raise ValueError("unsupported LogitState calibration kind")
        if not math.isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError("LogitState calibration temperature must be positive")
        thresholds = (
            self.accept_probability_min,
            self.verify_probability_min,
            self.selection_retry_margin_max,
        )
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in thresholds):
            raise ValueError("LogitState gate thresholds must be finite probabilities")
        if self.accept_probability_min < self.verify_probability_min:
            raise ValueError("accept threshold must not be below verify threshold")
        if self.max_actions != 1:
            raise ValueError("LogitState gate action budget must equal one")

    @property
    def calibration_version(self) -> str:
        return sha256_digest(
            {
                "calibration_kind": self.calibration_kind,
                "temperature": self.temperature,
            }
        )

    @property
    def threshold_policy_version(self) -> str:
        return sha256_digest(
            {
                "accept_probability_min": self.accept_probability_min,
                "verify_probability_min": self.verify_probability_min,
                "selection_retry_margin_max": self.selection_retry_margin_max,
            }
        )

    @property
    def gate_budget_version(self) -> str:
        return sha256_digest({"max_actions": self.max_actions})

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "calibration_kind": self.calibration_kind,
            "temperature": self.temperature,
            "accept_probability_min": self.accept_probability_min,
            "verify_probability_min": self.verify_probability_min,
            "selection_retry_margin_max": self.selection_retry_margin_max,
            "max_actions": self.max_actions,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FrozenGatePolicy":
        policy = cls(
            temperature=float(payload.get("temperature", 0.0)),
            accept_probability_min=float(payload.get("accept_probability_min", -1.0)),
            verify_probability_min=float(payload.get("verify_probability_min", -1.0)),
            selection_retry_margin_max=float(payload.get("selection_retry_margin_max", -1.0)),
            max_actions=int(payload.get("max_actions", 0)),
            calibration_kind=str(payload.get("calibration_kind", "")),
            schema_version=str(payload.get("schema_version", "")),
        )
        expected = {
            "calibration_version": policy.calibration_version,
            "threshold_policy_version": policy.threshold_policy_version,
            "gate_budget_version": policy.gate_budget_version,
        }
        for name, value in expected.items():
            if payload.get(name) not in {None, "", value}:
                raise ValueError(f"LogitState gate policy digest mismatch: {name}")
        return policy

    @classmethod
    def load(cls, path: Path, *, expected_file_hash: str = "") -> "FrozenGatePolicy":
        raw = Path(path).read_bytes()
        if expected_file_hash and sha256_digest(raw) != expected_file_hash:
            raise ValueError("LogitState gate policy file hash mismatch")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("LogitState gate policy object required")
        return cls.from_payload(payload)


@dataclass(frozen=True)
class GateProcessResult:
    decision: GateDecision
    worker_pid: int
    grant_hash: str
    reused_action_decision: bool


def evaluate_logit_gate_in_subprocess(
    *,
    state_root: Path,
    ref: LogitStateRefV2,
    policy: FrozenGatePolicy | None = None,
    timeout_s: float = 10.0,
) -> GateProcessResult:
    if timeout_s <= 0:
        raise ValueError("confidence gate timeout must be positive")
    root = Path(state_root)
    transport = SubprocessExecutorTransport(
        socket_path=root / f".{ref.state_id}.logit-gate.sock",
        timeout_s=timeout_s,
    )
    response = transport.execute(
        ExecRequest(
            header=ControlHeader(
                trace_id=ref.contract.trace_id,
                task_id=ref.contract.task_id,
                step_id=ref.contract.step_id,
                attempt_id=ref.contract.attempt_id,
                target_role="confidence_gate",
                timeout_ms=max(1, int(timeout_s * 1000)),
                event_type=EventType.REQ_EXEC,
            ),
            state_refs=(RefHandle(ref_id=ref.state_id, ref_kind="logit_state"),),
            runtime_reuse_contract="logit_state_required",
            output_contract_version="statebus.gate_decision.v1",
            workspace_root=str(root),
            input_manifest_hash=ref.ref_digest,
            operation="logit_gate_v1",
            state_root=str(root),
            logit_state_ref=logit_control_ref_from_domain(ref),
            logit_gate_policy_json=(
                stable_json_dumps(policy.canonical_payload()) if policy else ""
            ),
        )
    )
    if isinstance(response, ErrorResult):
        raise ConfidenceGateError(response.error_detail or response.error_code)
    if not isinstance(response, SuccessResult) or response.logit_gate_result is None:
        raise ConfidenceGateError("confidence_gate_result_missing")
    audit = transport.last_exchange_audit
    worker_pid = int(audit.worker_pid if audit is not None else 0)
    if worker_pid <= 0 or worker_pid == os.getpid():
        raise ConfidenceGateError("confidence_gate_invalid_worker_pid")
    decision = gate_decision_from_control(response.logit_gate_result)
    if decision.ref_id != ref.state_id or response.consumed_state_ref_id != ref.state_id:
        raise ConfidenceGateError("confidence_gate_result_binding_mismatch")
    if not response.logit_action_reused and decision.consumer_pid != worker_pid:
        raise ConfidenceGateError("confidence_gate_result_binding_mismatch")
    if response.logit_action_reused and decision.consumer_pid == ref.contract.producer_pid:
        raise ConfidenceGateError("confidence_gate_reused_result_pid_invalid")
    if not response.logit_grant_hash:
        raise ConfidenceGateError("confidence_gate_grant_receipt_missing")
    return GateProcessResult(
        decision=decision,
        worker_pid=worker_pid,
        grant_hash=response.logit_grant_hash,
        reused_action_decision=response.logit_action_reused,
    )


def decide_from_resolved_logit_state(
    resolved: ResolvedLogitState,
    *,
    policy: FrozenGatePolicy | None,
) -> GateDecision:
    contract = resolved.ref.contract
    calibrated_values = _temperature_scale(resolved.values, policy.temperature if policy else 1.0)
    selected_ordinal = resolved.selected_candidate_ordinal
    candidate_values = calibrated_values[:-1]
    selected_probability = candidate_values[selected_ordinal]
    entropy = -sum(value * math.log(value) for value in calibrated_values if value > 0.0)
    normalized_entropy = entropy / math.log(len(calibrated_values))
    ordered = sorted(candidate_values, reverse=True)
    top_margin = ordered[0] - ordered[1]
    action = GateAction.ACCEPT
    reason = "telemetry_only_no_additional_action"
    if contract.policy is LogitPolicy.GATED:
        policy_error = _policy_binding_error(contract, policy)
        if policy_error:
            action = GateAction.FAIL_CLOSED
            reason = policy_error
        elif selected_probability >= policy.accept_probability_min:  # type: ignore[union-attr]
            action = GateAction.ACCEPT
            reason = "selected_probability_at_or_above_accept_threshold"
        elif selected_probability >= policy.verify_probability_min:  # type: ignore[union-attr]
            action = GateAction.VERIFY_ONCE
            reason = "selected_probability_in_verify_band"
        elif top_margin <= policy.selection_retry_margin_max:  # type: ignore[union-attr]
            action = GateAction.SELECTION_RETRY_ONCE
            reason = "candidate_margin_in_retry_band"
        else:
            action = GateAction.FAIL_CLOSED
            reason = "risk_above_bounded_action_policy"
    decision_basis = {
        "ref_id": resolved.ref.state_id,
        "task_id": contract.task_id,
        "request_id": contract.request_id,
        "calibration_version": contract.calibration_version,
        "threshold_policy_version": contract.threshold_policy_version,
        "gate_budget_version": contract.gate_budget_version,
        "action": action.value,
    }
    decision_id = sha256_digest({**decision_basis, "kind": "gate_decision"})
    action_token = sha256_digest({**decision_basis, "kind": "bounded_action_token", "max_actions": 1})
    return GateDecision(
        decision_id=decision_id,
        action_token=action_token,
        ref_id=resolved.ref.state_id,
        task_id=contract.task_id,
        request_id=contract.request_id,
        consumer_pid=resolved.consumer_pid,
        producer_pid=contract.producer_pid,
        action=action,
        selected_candidate_probability=selected_probability,
        entropy=entropy,
        normalized_entropy=normalized_entropy,
        top_margin=top_margin,
        other_mass=calibrated_values[-1],
        candidate_count=contract.candidate_count,
        calibration_version=contract.calibration_version,
        threshold_policy_version=contract.threshold_policy_version,
        gate_budget_version=contract.gate_budget_version,
        reason=reason,
    )


def persist_gate_action_decision(root: Path, decision: GateDecision) -> tuple[GateDecision, bool]:
    action_dir = root / "logit_actions"
    action_dir.mkdir(parents=True, exist_ok=True)
    path = action_dir / f"{decision.ref_id}.json"
    payload = stable_json_dumps(decision.canonical_payload()) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing_payload = json.loads(path.read_text(encoding="utf-8"))
        existing = _gate_decision_from_payload(existing_payload)
        if existing.action_token != decision.action_token or existing.ref_id != decision.ref_id:
            raise ConfidenceGateError("confidence_gate_duplicate_action_token_mismatch")
        return existing, True
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return decision, False


def _policy_binding_error(contract: Any, policy: FrozenGatePolicy | None) -> str:
    if policy is None:
        return "frozen_calibration_or_policy_missing"
    expected = {
        "calibration_version": policy.calibration_version,
        "threshold_policy_version": policy.threshold_policy_version,
        "gate_budget_version": policy.gate_budget_version,
    }
    for name, value in expected.items():
        if getattr(contract, name) != value:
            return f"frozen_policy_binding_mismatch:{name}"
    return ""


def _temperature_scale(values: tuple[float, ...], temperature: float) -> tuple[float, ...]:
    if temperature == 1.0:
        return values
    exponent = 1.0 / temperature
    scaled = tuple(value**exponent if value > 0.0 else 0.0 for value in values)
    total = sum(scaled)
    if not math.isfinite(total) or total <= 0.0:
        raise LogitStateValidationError("logit_state_calibration_invalid")
    return tuple(value / total for value in scaled)


def _gate_decision_from_payload(value: object) -> GateDecision:
    if not isinstance(value, dict):
        raise ConfidenceGateError("confidence_gate_decision_object_required")
    try:
        return GateDecision(
            decision_id=str(value.get("decision_id", "")),
            action_token=str(value.get("action_token", "")),
            ref_id=str(value.get("ref_id", "")),
            task_id=str(value.get("task_id", "")),
            request_id=str(value.get("request_id", "")),
            consumer_pid=int(value.get("consumer_pid", 0)),
            producer_pid=int(value.get("producer_pid", 0)),
            action=GateAction(str(value.get("action", ""))),
            selected_candidate_probability=float(value.get("selected_candidate_probability", 0.0)),
            entropy=float(value.get("entropy", 0.0)),
            normalized_entropy=float(value.get("normalized_entropy", 0.0)),
            top_margin=float(value.get("top_margin", 0.0)),
            other_mass=float(value.get("other_mass", 0.0)),
            candidate_count=int(value.get("candidate_count", 0)),
            calibration_version=str(value.get("calibration_version", "")),
            threshold_policy_version=str(value.get("threshold_policy_version", "")),
            gate_budget_version=str(value.get("gate_budget_version", "")),
            reason=str(value.get("reason", "")),
            schema_version=str(value.get("schema_version", "")),
        )
    except (TypeError, ValueError) as exc:
        raise ConfidenceGateError(str(exc) or "confidence_gate_decision_invalid") from exc


def logit_control_ref_from_domain(ref: LogitStateRefV2) -> LogitStateRefControl:
    contract = ref.contract
    return LogitStateRefControl(
        ref_id=ref.state_id,
        schema_version=ref.schema_version,
        task_id=contract.task_id,
        session_id=contract.session_id,
        trace_id=contract.trace_id,
        step_id=contract.step_id,
        request_id=contract.request_id,
        attempt_id=contract.attempt_id,
        storage_kind=ref.storage_kind.value,
        shared_memory_name=ref.shared_memory_name,
        mmap_relpath=ref.mmap_relpath,
        blob_hash=ref.blob_hash,
        size_bytes=ref.length,
        candidate_surface_digest=contract.candidate_surface_digest,
        alias_mapping_digest=contract.alias_mapping_digest,
        candidate_count=contract.candidate_count,
        producer_pid=contract.producer_pid,
        lease_expires_at_ns=contract.lease_expires_at_ns,
        model_id=contract.model_id,
        tokenizer_id=contract.tokenizer_id,
        chat_template_sha256=contract.chat_template_sha256,
        template_kwargs_sha256=contract.template_kwargs_sha256,
        response_schema_digest=contract.response_schema_digest,
        calibration_version=contract.calibration_version,
        threshold_policy_version=contract.threshold_policy_version,
        gate_budget_version=contract.gate_budget_version,
        policy=contract.policy.value,
        decision_type=contract.decision_type,
        dtype=contract.dtype,
        byte_order=contract.byte_order,
    )


def validate_logit_control_ref(
    ref: LogitStateRefV2,
    control_ref: LogitStateRefControl | None,
) -> None:
    if control_ref is None or control_ref != logit_control_ref_from_domain(ref):
        raise LogitStateValidationError("logit_gate_control_ref_mismatch")


def logit_control_grant_from_domain(grant: LogitStateGrant) -> LogitStateGrantControl:
    return LogitStateGrantControl(**grant.canonical_payload())


def logit_grant_from_control(control: LogitStateGrantControl | None) -> LogitStateGrant:
    if control is None:
        raise LogitStateValidationError("logit_gate_control_grant_missing")
    return LogitStateGrant.from_payload({
        name: getattr(control, name)
        for name in control.__dataclass_fields__
    })


def gate_decision_to_control(decision: GateDecision) -> LogitGateResult:
    payload = decision.canonical_payload()
    payload.pop("claim_boundary", None)
    return LogitGateResult(**payload)


def gate_decision_from_control(result: LogitGateResult) -> GateDecision:
    return _gate_decision_from_payload({
        name: getattr(result, name)
        for name in result.__dataclass_fields__
    })
