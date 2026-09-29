from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path


class ReplayGateError(ValueError):
    pass


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _count(metrics: Mapping[str, object], key: str, *, task_id: str) -> int:
    raw = metrics.get(key, 0)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ReplayGateError(f"{task_id} has invalid {key}: {raw!r}") from exc
    if not value.is_integer() or value < 0:
        raise ReplayGateError(f"{task_id} has invalid {key}: {raw!r}")
    return int(value)


def validate_replay_case_contract(
    cases: Sequence[Mapping[str, object]],
    *,
    expected_case_count: int,
) -> dict[str, int]:
    """Validate replay calls and restoration evidence without aggregate cancellation."""

    if len(cases) != expected_case_count:
        raise ReplayGateError(
            f"replay case detail coverage {len(cases)}/{expected_case_count}"
        )

    totals = {
        "planner_call_count": 0,
        "retriever_call_count": 0,
        "executor_call_count": 0,
        "summarizer_call_count": 0,
        "llm_call_count": 0,
        "answer_restoration_replay_count": 0,
        "exact_replay_count": 0,
        "validated_replay_count": 0,
    }
    for index, case in enumerate(cases):
        task_id = str(case.get("task_id", f"case-{index}")).strip() or f"case-{index}"
        replay_class = str(case.get("replay_class", "")).strip()
        if replay_class not in {"exact_replay", "validated_replay"}:
            raise ReplayGateError(f"{task_id} has unexpected replay class {replay_class!r}")

        metrics = _mapping(case.get("metrics"))
        expected_downstream = 0 if replay_class == "exact_replay" else 1
        expected_role_calls = {
            "planner_call_count": 1,
            "retriever_call_count": expected_downstream,
            "executor_call_count": expected_downstream,
            "summarizer_call_count": expected_downstream,
        }
        observed_role_calls = {
            key: _count(metrics, key, task_id=task_id) for key in expected_role_calls
        }
        for key, expected in expected_role_calls.items():
            observed = observed_role_calls[key]
            if observed != expected:
                raise ReplayGateError(
                    f"{task_id} {replay_class} {key} {observed}/{expected}"
                )
            totals[key] += observed

        observed_llm_calls = _count(metrics, "llm_call_count", task_id=task_id)
        expected_llm_calls = sum(observed_role_calls.values())
        if observed_llm_calls != expected_llm_calls:
            raise ReplayGateError(
                f"{task_id} llm_call_count {observed_llm_calls}/{expected_llm_calls}"
            )
        totals["llm_call_count"] += observed_llm_calls

        observed_restorations = _count(
            metrics,
            "answer_restoration_replay_count",
            task_id=task_id,
        )
        expected_restorations = 1 if replay_class == "exact_replay" else 0
        if observed_restorations != expected_restorations:
            raise ReplayGateError(
                f"{task_id} answer restoration {observed_restorations}/{expected_restorations}"
            )
        totals["answer_restoration_replay_count"] += observed_restorations

        skipped_steps = _count(metrics, "skipped_step_count", task_id=task_id)
        minimum_skipped_steps = 2 if replay_class == "exact_replay" else 1
        if skipped_steps < minimum_skipped_steps:
            raise ReplayGateError(
                f"{task_id} skipped_step_count {skipped_steps}/{minimum_skipped_steps}"
            )

        audit_summary = _mapping(case.get("audit_summary"))
        replay_audit = _mapping(audit_summary.get("replay"))
        if replay_audit.get("replay_class") != replay_class:
            raise ReplayGateError(f"{task_id} replay audit class mismatch")

        totals[f"{replay_class}_count"] += 1
        if replay_class != "exact_replay":
            continue

        if _count(metrics, "artifact_reuse_count", task_id=task_id) < 1:
            raise ReplayGateError(f"{task_id} exact replay did not reuse an artifact")
        artifact_audit = _mapping(audit_summary.get("artifact"))
        if artifact_audit.get("verification_state") != "verified":
            raise ReplayGateError(f"{task_id} restored artifact is not verified")
        case_hash = str(case.get("output_artifact_hash", "")).strip()
        audit_hash = str(artifact_audit.get("output_artifact_hash", "")).strip()
        if not case_hash or case_hash != audit_hash:
            raise ReplayGateError(f"{task_id} restored output hash mismatch")
        output_path = Path(str(case.get("output_artifact_path", "")))
        if not output_path.is_file():
            raise ReplayGateError(f"{task_id} restored output artifact is missing")
        output_bytes = output_path.read_bytes()
        if hashlib.sha256(output_bytes).hexdigest() != case_hash:
            raise ReplayGateError(f"{task_id} restored output content hash mismatch")
        try:
            output_payload = json.loads(output_bytes)
        except json.JSONDecodeError as exc:
            raise ReplayGateError(f"{task_id} restored output is not valid JSON") from exc
        if output_payload.get("restored_replay_class") != "exact_replay":
            raise ReplayGateError(f"{task_id} exact replay restore marker is missing")
        if not str(output_payload.get("restored_from_memory_id", "")).strip():
            raise ReplayGateError(f"{task_id} restored memory id is missing")

    return totals
