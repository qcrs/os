from __future__ import annotations

import json
from pathlib import Path

from v2.benchmark.scoring import score_benchmark_output


def test_post_runtime_benchmark_scorer_preserves_field_gte_contract(tmp_path: Path) -> None:
    output_path = tmp_path / "workspace" / "outputs" / "result.json"
    output_path.parent.mkdir(parents=True)
    output_payload = {
        "reused_artifact_count": 7,
        "reused_strategy_count": "3",
    }
    output_path.write_text(json.dumps(output_payload), encoding="utf-8")

    passing = score_benchmark_output(
        output_payload=output_payload,
        output_path=output_path,
        quality_checks=(
            "field_gte:reused_artifact_count:7",
            "field_gte:reused_strategy_count:3",
        ),
    )
    failing = score_benchmark_output(
        output_payload=output_payload,
        output_path=output_path,
        quality_checks=("field_gte:reused_artifact_count:8",),
    )

    assert passing.passed is True
    assert passing.quality_checks_passed is True
    assert failing.passed is False
    assert failing.failures == ("quality_check_failed:field_gte:reused_artifact_count:8",)


def test_post_runtime_benchmark_scorer_fails_closed_for_unknown_check(tmp_path: Path) -> None:
    output_path = tmp_path / "workspace" / "outputs" / "result.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("{}", encoding="utf-8")

    score = score_benchmark_output(
        output_payload={},
        output_path=output_path,
        quality_checks=("unsupported_check:field",),
    )

    assert score.passed is False
    assert score.failures == ("quality_check_failed:unsupported_check:field",)
