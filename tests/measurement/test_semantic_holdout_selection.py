from __future__ import annotations

import pytest

from statebus.benchmark.semantic_holdout import (
    _select_semantic_holdout_cases,
    load_semantic_holdout_cases,
)


def test_semantic_holdout_bounded_selection_is_exact_and_ordered() -> None:
    selected = _select_semantic_holdout_cases(
        load_semantic_holdout_cases(),
        case_ids=("semantic-holdout-s4", "semantic-holdout-s1"),
        max_cases=1,
    )

    assert [case.task_id for case in selected] == ["semantic-holdout-s4"]


def test_semantic_holdout_bounded_selection_rejects_unknown_case() -> None:
    with pytest.raises(ValueError, match="semantic_holdout_unknown_case_ids"):
        _select_semantic_holdout_cases(
            load_semantic_holdout_cases(),
            case_ids=("semantic-holdout-missing",),
        )
