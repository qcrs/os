from __future__ import annotations

import pytest

from statebus.benchmark.kv_prefix_schedule import (
    DependencyAwarePrefixScheduler,
    PrefixScheduleNode,
)
from statebus.runtime import PrefixReuseScheduleHint


def _node(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    affinity: str = "a",
    priority: float = 0.0,
) -> PrefixScheduleNode:
    return PrefixScheduleNode(
        hint=PrefixReuseScheduleHint(
            task_id=task_id,
            corpus_prefix_hash=f"sha256:{affinity}",
            cache_affinity_group=affinity,
            schedule_priority=priority,
        ),
        dependency_ids=dependencies,
    )


def test_affinity_only_selects_from_dependency_ready_set() -> None:
    scheduler = DependencyAwarePrefixScheduler(
        (
            _node("root-a", affinity="a"),
            _node("root-b", affinity="b"),
            _node("child-a", dependencies=("root-a",), affinity="a", priority=100.0),
        )
    )

    first = scheduler.choose_next(warmed_affinity_groups={"a"})
    assert first is not None
    assert first.task_id == "root-a"
    assert "child-a" not in scheduler.ready_task_ids()

    second = scheduler.choose_next(
        completed_task_ids={"root-a"},
        warmed_affinity_groups={"a"},
    )
    assert second is not None
    assert second.task_id == "child-a"


def test_cycle_and_missing_dependency_fail_before_requests() -> None:
    with pytest.raises(ValueError, match="cycle"):
        DependencyAwarePrefixScheduler(
            (_node("a", dependencies=("b",)), _node("b", dependencies=("a",)))
        )
    with pytest.raises(ValueError, match="missing dependencies"):
        DependencyAwarePrefixScheduler((_node("a", dependencies=("missing",)),))


def test_failed_dependency_blocks_descendant() -> None:
    scheduler = DependencyAwarePrefixScheduler(
        (_node("root"), _node("child", dependencies=("root",)))
    )

    with pytest.raises(RuntimeError, match="failed dependency"):
        scheduler.choose_next(failed_task_ids={"root"})


def test_adaptive_score_reorders_only_ready_nodes() -> None:
    scheduler = DependencyAwarePrefixScheduler(
        (
            _node("a", affinity="alpha"),
            _node("b", affinity="beta"),
            _node("c", dependencies=("a",), affinity="gamma"),
        )
    )

    selected = scheduler.choose_next(
        adaptive_affinity_scores={"gamma": 999.0, "beta": 2.0}
    )
    assert selected is not None
    assert selected.task_id == "b"
    assert scheduler.dependency_proof_digest
