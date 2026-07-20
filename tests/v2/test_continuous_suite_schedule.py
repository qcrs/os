from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from v2.benchmark.continuous_runner import run_continuous_benchmark_collection
from v2.benchmark.continuous_task_family import load_continuous_task_family


SOURCE_MANIFEST = Path(
    "v2/benchmark/samples/continuous_task_families/csv_table_profile/manifest.json"
)
FORMAL_FAMILY_DIRS = (
    Path("v2/benchmark/samples/continuous_task_families/formal_operating_metrics"),
    Path("v2/benchmark/samples/continuous_task_families/formal_financial_reports"),
)


def _two_round_family(tmp_path: Path, family_id: str):
    payload = deepcopy(json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8")))
    payload["family_id"] = family_id
    payload["round_count"] = 2
    payload["rounds"] = payload["rounds"][:2]
    payload["l0_l3_expectations"]["L3"]["target_nonzero_rounds"] = [2]
    family_dir = tmp_path / family_id
    family_dir.mkdir()
    (family_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_continuous_task_family(family_dir)


def test_family_minimum_is_two_related_rounds(tmp_path: Path) -> None:
    family = _two_round_family(tmp_path, "short-operating-metrics-a")

    assert family.round_count == 2
    assert family.rounds[1].depends_on_rounds == (1,)


def test_collection_owns_ten_execution_minimum(tmp_path: Path) -> None:
    first = _two_round_family(tmp_path, "short-operating-metrics-a")
    second = _two_round_family(tmp_path, "short-operating-metrics-b")

    with pytest.raises(ValueError, match="at least ten total executions"):
        run_continuous_benchmark_collection(
            families=(first, second),
            workspace_root=tmp_path / "workspaces",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "control.sock",
            suite_id="short-collection",
        )


def test_formal_collection_declares_causal_and_long_horizon_views() -> None:
    families = tuple(load_continuous_task_family(path) for path in FORMAL_FAMILY_DIRS)
    causal_families = tuple(family.select_view("causal_core") for family in families)
    long_horizon_families = tuple(
        family.select_view("long_horizon") for family in families
    )
    causal_task_ids = [
        round_.task_id
        for family in causal_families
        for round_ in family.rounds
    ]
    long_horizon_task_ids = [
        round_.task_id
        for family in long_horizon_families
        for round_ in family.rounds
    ]

    assert [family.round_count for family in families] == [10, 10]
    assert [family.round_count for family in causal_families] == [5, 5]
    assert [family.round_count for family in long_horizon_families] == [10, 10]
    assert len(causal_task_ids) == len(set(causal_task_ids)) == 10
    assert len(long_horizon_task_ids) == len(set(long_horizon_task_ids)) == 20
    assert all(
        family.selected_experiment_view == "causal_core"
        for family in causal_families
    )
    assert all(
        family.selected_experiment_view == "long_horizon"
        for family in long_horizon_families
    )
    assert all(
        any(round_.depends_on_rounds for round_ in family.rounds)
        for family in families
    )
