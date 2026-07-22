from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts.vllm_v0_prefix_counter_exporter import (
    cache_metric_totals,
    require_supported_vllm_version,
)


@dataclass
class _MetricData:
    num_completed_blocks: int
    completed_block_cache_hit_rate: float
    num_incompleted_block_queries: int
    num_incompleted_block_hit: int
    block_size: int = 1000


def test_cache_metric_totals_recovers_completed_and_partial_blocks() -> None:
    metric_data = _MetricData(
        num_completed_blocks=2,
        completed_block_cache_hit_rate=0.625,
        num_incompleted_block_queries=25,
        num_incompleted_block_hit=20,
    )

    assert cache_metric_totals(metric_data) == (2025, 1270)


def test_cache_metric_totals_rejects_impossible_state() -> None:
    metric_data = _MetricData(
        num_completed_blocks=0,
        completed_block_cache_hit_rate=0.0,
        num_incompleted_block_queries=2,
        num_incompleted_block_hit=3,
    )

    with pytest.raises(ValueError, match="invalid vLLM prefix cache metric state"):
        cache_metric_totals(metric_data)


@pytest.mark.parametrize("version", ["0.7.3", "0.9.2"])
def test_exporter_accepts_audited_vllm_versions(version: str) -> None:
    assert require_supported_vllm_version(version) == version


def test_exporter_fails_closed_for_unknown_vllm_version() -> None:
    with pytest.raises(RuntimeError, match="0.7.3, 0.9.2"):
        require_supported_vllm_version("0.10.0")
