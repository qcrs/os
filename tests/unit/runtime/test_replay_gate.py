from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from statebus.benchmark.replay_gate import ReplayGateError, validate_replay_case_contract


def _case(replay_class: str, tmp_path: Path) -> dict[str, object]:
    exact = replay_class == "exact_replay"
    downstream = 0 if exact else 1
    output_path = tmp_path / f"{replay_class}.json"
    output_payload = {"task_id": f"task-{replay_class}"}
    if exact:
        output_payload.update(
            {
                "restored_replay_class": "exact_replay",
                "restored_from_memory_id": "memory-history",
            }
        )
    output_bytes = (json.dumps(output_payload, sort_keys=True) + "\n").encode("utf-8")
    output_path.write_bytes(output_bytes)
    output_hash = hashlib.sha256(output_bytes).hexdigest()
    return {
        "task_id": f"task-{replay_class}",
        "replay_class": replay_class,
        "output_artifact_path": str(output_path),
        "output_artifact_hash": output_hash,
        "metrics": {
            "planner_call_count": 1,
            "retriever_call_count": downstream,
            "executor_call_count": downstream,
            "summarizer_call_count": downstream,
            "llm_call_count": 1 + 3 * downstream,
            "answer_restoration_replay_count": 1 if exact else 0,
            "artifact_reuse_count": 1 if exact else 0,
            "skipped_step_count": 2 if exact else 1,
        },
        "audit_summary": {
            "replay": {"replay_class": replay_class},
            "artifact": {
                "verification_state": "verified",
                "output_artifact_hash": output_hash,
            },
        },
    }


def test_replay_gate_accepts_mixed_exact_and_validated_cases(tmp_path: Path) -> None:
    totals = validate_replay_case_contract(
        [_case("exact_replay", tmp_path), _case("validated_replay", tmp_path)],
        expected_case_count=2,
    )

    assert totals == {
        "planner_call_count": 2,
        "retriever_call_count": 1,
        "executor_call_count": 1,
        "summarizer_call_count": 1,
        "llm_call_count": 5,
        "answer_restoration_replay_count": 1,
        "exact_replay_count": 1,
        "validated_replay_count": 1,
    }


@pytest.mark.parametrize("role", ("retriever", "executor", "summarizer"))
def test_replay_gate_rejects_exact_downstream_calls(role: str, tmp_path: Path) -> None:
    case = _case("exact_replay", tmp_path)
    case["metrics"][f"{role}_call_count"] = 1
    case["metrics"]["llm_call_count"] = 2

    with pytest.raises(ReplayGateError, match=role):
        validate_replay_case_contract([case], expected_case_count=1)


def test_replay_gate_rejects_missing_validated_role_call(tmp_path: Path) -> None:
    case = _case("validated_replay", tmp_path)
    case["metrics"]["executor_call_count"] = 0
    case["metrics"]["llm_call_count"] = 3

    with pytest.raises(ReplayGateError, match="executor"):
        validate_replay_case_contract([case], expected_case_count=1)


def test_replay_gate_rejects_unverified_exact_restoration(tmp_path: Path) -> None:
    case = _case("exact_replay", tmp_path)
    case["audit_summary"]["artifact"]["verification_state"] = "invalidated"

    with pytest.raises(ReplayGateError, match="not verified"):
        validate_replay_case_contract([case], expected_case_count=1)
