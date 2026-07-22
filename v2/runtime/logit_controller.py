from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
from typing import Any, Callable

from v2.contracts import ActionEffectReceipt, CandidateSurfaceV2, GateDecision
from v2.runtime.confidence_gate import FrozenGatePolicy, evaluate_logit_gate_in_subprocess
from v2.runtime.logit_state import ExactChoiceLogitResult
from v2.state.logit_state import (
    LogitStatePublishContext,
    LogitStateStore,
    LogitStateValidationError,
)
from v2.utils import stable_json_dumps


@dataclass(frozen=True)
class LogitActionApplication:
    after_decision_surface_hash: str
    selection_changed: bool
    error_recovered: bool
    extra_llm_calls: int
    extra_tool_calls: int
    extra_tokens: int
    extra_latency_ms: float
    extra_evidence_bytes: int
    outcome: str
    fallback_reason: str = ""
    downstream_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogitLifecycleResult:
    metrics: dict[str, float]
    events: tuple[dict[str, Any], ...]
    gate_decision: GateDecision | None = None
    effect_receipt: ActionEffectReceipt | None = None
    state_id: str = ""
    producer_pid: int = 0
    consumer_pid: int = 0
    reject_reason: str = ""
    release_reason: str = ""
    effect_receipt_path: str = ""


def run_logit_state_lifecycle(
    *,
    store: LogitStateStore,
    extraction: ExactChoiceLogitResult,
    candidate_surface: CandidateSurfaceV2,
    context: LogitStatePublishContext,
    before_decision_surface_hash: str,
    apply_action: Callable[[GateDecision], LogitActionApplication],
    effect_root: Path,
    policy: FrozenGatePolicy | None = None,
    gate_timeout_s: float = 10.0,
) -> LogitLifecycleResult:
    metrics = _empty_metrics()
    events: list[dict[str, Any]] = []
    decision: GateDecision | None = None
    effect: ActionEffectReceipt | None = None
    application: LogitActionApplication | None = None
    publication = None
    consumer_pid = 0
    reject_reason = ""
    release_reason = ""
    effect_path = ""

    if extraction.available:
        metrics["logit_state_extraction_available_count"] = 1.0
        events.append(_event(
            "LOGIT_STATE_EXTRACTION_AVAILABLE",
            payload={
                "request_id": context.request_id,
                "attempt_id": context.attempt_id,
                "candidate_surface_digest": candidate_surface.candidate_surface_digest,
            },
            metrics={"logit_state_extraction_available_count": 1.0},
        ))
    else:
        reject_reason = extraction.receipt.unavailable_reason or "exact_producer_unavailable"
        metrics["logit_state_reject_count"] = 1.0
        events.append(_reject_event(reject_reason))
        return LogitLifecycleResult(metrics=metrics, events=tuple(events), reject_reason=reject_reason)

    try:
        publication = store.publish(
            extraction=extraction,
            candidate_surface=candidate_surface,
            context=context,
        )
        metrics["logit_state_publish_count"] = 1.0
        metrics["logit_state_bytes"] = float(publication.ref.length)
        events.append(_event(
            "LOGIT_STATE_PUBLISHED",
            payload={
                "state_id": publication.ref.state_id,
                "storage_kind": publication.ref.storage_kind.value,
                "producer_pid": publication.ref.contract.producer_pid,
                "candidate_surface_digest": publication.ref.contract.candidate_surface_digest,
            },
            metrics={
                "logit_state_publish_count": 1.0,
                "logit_state_bytes": publication.ref.length,
            },
        ))
        gate_result = evaluate_logit_gate_in_subprocess(
            state_root=store.root,
            ref=publication.ref,
            policy=policy,
            timeout_s=gate_timeout_s,
        )
        decision = gate_result.decision
        consumer_pid = gate_result.worker_pid
        metrics["logit_state_resolve_count"] = 1.0
        metrics["logit_state_consume_count"] = 1.0
        events.extend((
            _event(
                "LOGIT_STATE_RESOLVED",
                payload={
                    "state_id": publication.ref.state_id,
                    "producer_pid": publication.ref.contract.producer_pid,
                    "physical_consumer_pid": gate_result.worker_pid,
                    "grant_hash": gate_result.grant_hash,
                },
                metrics={"logit_state_resolve_count": 1.0},
            ),
            _event(
                "LOGIT_STATE_CONSUMED",
                payload={
                    "state_id": publication.ref.state_id,
                    "decision_id": decision.decision_id,
                    "physical_consumer_pid": gate_result.worker_pid,
                    "selected_candidate_probability": decision.selected_candidate_probability,
                },
                metrics={"logit_state_consume_count": 1.0},
            ),
        ))
        if gate_result.reused_action_decision:
            release_reason = "duplicate_action_not_reexecuted"
        else:
            metrics["logit_gate_action_count"] = 1.0
            metrics[f"logit_gate_action_{decision.action.value}_count"] = 1.0
            events.append(_event(
                "LOGIT_GATE_ACTION_DECIDED",
                payload=decision.canonical_payload(),
                metrics={
                    "logit_gate_action_count": 1.0,
                    f"logit_gate_action_{decision.action.value}_count": 1.0,
                },
            ))
            try:
                application = apply_action(decision)
                release_reason = "consumed"
            except Exception as exc:
                reject_reason = _exception_reason(exc)
                metrics["logit_state_reject_count"] = 1.0
                events.append(_reject_event(reject_reason, state_id=publication.ref.state_id))
                application = LogitActionApplication(
                    after_decision_surface_hash=before_decision_surface_hash,
                    selection_changed=False,
                    error_recovered=False,
                    extra_llm_calls=0,
                    extra_tool_calls=0,
                    extra_tokens=0,
                    extra_latency_ms=0.0,
                    extra_evidence_bytes=0,
                    outcome="action_failed_baseline_preserved",
                    fallback_reason=reject_reason,
                )
                release_reason = "action_failed"
        if publication is not None and decision is not None and application is not None:
            effect = ActionEffectReceipt(
                decision_id=decision.decision_id,
                action_token=decision.action_token,
                ref_id=publication.ref.state_id,
                task_id=publication.ref.contract.task_id,
                step_id=publication.ref.contract.step_id,
                consumer_pid=decision.consumer_pid,
                action=decision.action,
                before_decision_surface_hash=before_decision_surface_hash,
                after_decision_surface_hash=application.after_decision_surface_hash,
                selection_changed=application.selection_changed,
                error_recovered=application.error_recovered,
                extra_llm_calls=application.extra_llm_calls,
                extra_tool_calls=application.extra_tool_calls,
                extra_tokens=application.extra_tokens,
                extra_latency_ms=application.extra_latency_ms,
                extra_evidence_bytes=application.extra_evidence_bytes,
                outcome=application.outcome,
                fallback_reason=application.fallback_reason,
                release_reason=release_reason,
                downstream_ref_ids=application.downstream_ref_ids,
            )
            effect_path = str(_persist_effect_receipt(Path(effect_root), effect))
            metrics["logit_gate_effect_count"] = 1.0
            events.append(_event(
                "LOGIT_GATE_EFFECT_RECORDED",
                payload=effect.canonical_payload(),
                metrics={"logit_gate_effect_count": 1.0},
            ))
    except (LogitStateValidationError, ValueError, OSError, RuntimeError) as exc:
        reject_reason = _exception_reason(exc)
        metrics["logit_state_reject_count"] = 1.0
        events.append(_reject_event(
            reject_reason,
            state_id="" if publication is None else publication.ref.state_id,
        ))
        release_reason = "rejected"
    finally:
        if publication is not None:
            try:
                store.release(
                    publication.ref.state_id,
                    reason=release_reason or "rejected",
                    consumer_pid=consumer_pid,
                )
                metrics["logit_state_release_count"] = 1.0
                events.append(_event(
                    "LOGIT_STATE_RELEASED",
                    payload={
                        "state_id": publication.ref.state_id,
                        "release_reason": release_reason or "rejected",
                        "physical_consumer_pid": consumer_pid,
                    },
                    metrics={"logit_state_release_count": 1.0},
                ))
            except (LogitStateValidationError, OSError, ValueError) as exc:
                release_error = _exception_reason(exc)
                reject_reason = reject_reason or release_error
                metrics["logit_state_release_failed_count"] = 1.0
                events.append(_reject_event(release_error, state_id=publication.ref.state_id))

    return LogitLifecycleResult(
        metrics=metrics,
        events=tuple(events),
        gate_decision=decision,
        effect_receipt=effect,
        state_id="" if publication is None else publication.ref.state_id,
        producer_pid=0 if publication is None else publication.ref.contract.producer_pid,
        consumer_pid=consumer_pid,
        reject_reason=reject_reason,
        release_reason=release_reason,
        effect_receipt_path=effect_path,
    )


def empty_logit_lifecycle_metrics() -> dict[str, float]:
    return _empty_metrics()


def rejected_logit_lifecycle(
    reason: str,
    *,
    extraction_available: bool = False,
) -> LogitLifecycleResult:
    metrics = _empty_metrics()
    events: list[dict[str, Any]] = []
    if extraction_available:
        metrics["logit_state_extraction_available_count"] = 1.0
    metrics["logit_state_reject_count"] = 1.0
    events.append(_reject_event(reason))
    return LogitLifecycleResult(
        metrics=metrics,
        events=tuple(events),
        reject_reason=reason,
    )


def _empty_metrics() -> dict[str, float]:
    return {
        "logit_state_extraction_available_count": 0.0,
        "logit_state_publish_count": 0.0,
        "logit_state_resolve_count": 0.0,
        "logit_state_consume_count": 0.0,
        "logit_state_reject_count": 0.0,
        "logit_gate_action_count": 0.0,
        "logit_gate_effect_count": 0.0,
        "logit_state_release_count": 0.0,
        "logit_state_release_failed_count": 0.0,
        "logit_state_bytes": 0.0,
    }


def _event(
    event_type: str,
    *,
    payload: dict[str, Any],
    metrics: dict[str, float | int],
) -> dict[str, Any]:
    return {"event_type": event_type, "payload": payload, "metrics": metrics}


def _reject_event(reason: str, *, state_id: str = "") -> dict[str, Any]:
    return _event(
        "LOGIT_STATE_REJECTED",
        payload={"state_id": state_id, "reason": reason},
        metrics={"logit_state_reject_count": 1.0},
    )


def _exception_reason(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _persist_effect_receipt(root: Path, receipt: ActionEffectReceipt) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{receipt.ref_id}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(existing, dict)
            or existing.get("action_token") != receipt.action_token
            or existing.get("decision_id") != receipt.decision_id
        ):
            raise LogitStateValidationError("logit_effect_receipt_identity_mismatch")
        return path
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(stable_json_dumps(receipt.canonical_payload()) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
