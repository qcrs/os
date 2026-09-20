from __future__ import annotations

import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import pytest

import statebus.benchmark.low_overhead_ablation as p2


def test_low_overhead_ablation_closes_matched_denominator(tmp_path: Path) -> None:
    root = tmp_path / "p2"
    result = p2.run_low_overhead_ablation(
        output_root=root,
        payload_count_per_size=1,
        repeats=1,
        sizes={"small": 128, "medium": 2_048, "large": 8_192},
        timeout_s=5,
    )

    rows = json.loads((root / "rows.json").read_text(encoding="utf-8"))
    denominator = json.loads(
        (root / "denominator.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert len(rows) == 9
    assert denominator == {
        "schema_version": "statebus.p2.low_overhead_denominator.v1",
        "planned_count": 9,
        "observed_count": 9,
        "success_count": 9,
        "runtime_fail_count": 0,
        "matched_payload_count": 3,
        "matched_groups_closed": True,
        "arithmetic_closed": True,
    }
    for payload_id in {row["matched_payload_id"] for row in rows}:
        group = [row for row in rows if row["matched_payload_id"] == payload_id]
        assert {row["variant"] for row in group} == set(p2.VARIANTS)
        assert len({row["semantic_payload_sha256"] for row in group}) == 1
        assert all(row["cross_process"] is True for row in group)
        assert all(row["quality"]["passed"] is True for row in group)
        assert all(row["copy_count"]["status"] == "unsupported" for row in group)
        assert all(row["prompt_tokens"]["status"] == "unsupported" for row in group)
    shm_rows = [row for row in rows if row["variant"] == "typed_protobuf_shm_ref"]
    assert all(row["state_publish_ms"] is not None for row in shm_rows)
    assert all(row["state_map_ms"] is not None for row in shm_rows)
    assert all(row["state_read_ms"] is not None for row in shm_rows)
    assert all(row["state_release_ms"] is not None for row in shm_rows)


def test_shm_is_unlinked_when_worker_exits_before_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created_names: list[str] = []
    real_shared_memory = p2.SharedMemory

    def tracked_shared_memory(*args, **kwargs):
        shared = real_shared_memory(*args, **kwargs)
        if kwargs.get("create"):
            created_names.append(shared.name)
        return shared

    def exit_before_ready(_socket_path: str, _variant: str, _ready) -> None:
        return None

    monkeypatch.setattr(p2, "SharedMemory", tracked_shared_memory)
    monkeypatch.setattr(p2, "_worker", exit_before_ready)
    socket_path = tmp_path / "failed-worker.sock"

    with pytest.raises(RuntimeError, match="p2_worker_start_failed"):
        p2._run_variant(
            variant="typed_protobuf_shm_ref",
            payload=b"statebus-p2-cleanup",
            payload_id="cleanup:001:repeat-1",
            socket_path=socket_path,
            timeout_s=1,
        )

    assert len(created_names) == 1
    assert not socket_path.exists()
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=created_names[0])
