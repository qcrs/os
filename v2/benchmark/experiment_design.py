from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
import random
from statistics import median
import time
from typing import Callable, Mapping


@dataclass(frozen=True)
class LaneRunSpec:
    block_index: int
    sequence_index: int
    global_index: int
    lane: str
    order_pattern: str


@dataclass(frozen=True)
class LaneCallbackResult:
    quality_passed: bool = True
    component_ms: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LaneObservation:
    spec: LaneRunSpec
    elapsed_ms: float
    quality_passed: bool
    component_ms: tuple[tuple[str, float], ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "block_index": self.spec.block_index,
            "sequence_index": self.spec.sequence_index,
            "global_index": self.spec.global_index,
            "lane": self.spec.lane,
            "order_pattern": self.spec.order_pattern,
            "elapsed_ms": self.elapsed_ms,
            "quality_passed": self.quality_passed,
            "component_ms": dict(self.component_ms),
        }


def balanced_lane_schedule(
    *,
    repeat_count: int,
    lane_a: str,
    lane_b: str,
) -> tuple[LaneRunSpec, ...]:
    if repeat_count < 1:
        raise ValueError("balanced_repeat_count_must_be_positive")
    if not lane_a.strip() or not lane_b.strip() or lane_a == lane_b:
        raise ValueError("balanced_lanes_must_be_distinct_and_nonempty")
    schedule: list[LaneRunSpec] = []
    global_index = 0
    for block_index in range(1, repeat_count + 1):
        if block_index % 2:
            lanes = (lane_a, lane_b, lane_b, lane_a)
            pattern = "ABBA"
        else:
            lanes = (lane_b, lane_a, lane_a, lane_b)
            pattern = "BAAB"
        for sequence_index, lane in enumerate(lanes, start=1):
            global_index += 1
            schedule.append(LaneRunSpec(
                block_index=block_index,
                sequence_index=sequence_index,
                global_index=global_index,
                lane=lane,
                order_pattern=pattern,
            ))
    return tuple(schedule)


def _percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        raise ValueError("percentile_values_empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def bootstrap_confidence_interval(
    values: tuple[float, ...],
    *,
    confidence: float = 0.95,
    resample_count: int = 2_000,
    seed: int = 20260721,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap_values_empty")
    if not 0.0 < confidence < 1.0:
        raise ValueError("bootstrap_confidence_invalid")
    if resample_count < 100:
        raise ValueError("bootstrap_resample_count_too_small")
    if len(values) == 1:
        return float(values[0]), float(values[0])
    rng = random.Random(seed)
    estimates = tuple(
        median(tuple(rng.choice(values) for _ in values))
        for _ in range(resample_count)
    )
    tail = (1.0 - confidence) / 2.0
    return _percentile(estimates, tail), _percentile(estimates, 1.0 - tail)


def summarize_distribution(
    values: tuple[float, ...],
    *,
    bootstrap_seed: int = 20260721,
) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "median": None,
            "p90": None,
            "p95": None,
            "bootstrap_median_ci_95": None,
        }
    low, high = bootstrap_confidence_interval(values, seed=bootstrap_seed)
    return {
        "count": len(values),
        "median": float(median(values)),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
        "minimum": min(values),
        "maximum": max(values),
        "bootstrap_median_ci_95": [low, high],
    }


def summarize_balanced_lane_observations(
    observations: tuple[LaneObservation, ...],
    *,
    lane_a: str,
    lane_b: str,
    repeat_count: int,
    bootstrap_seed: int = 20260721,
) -> dict[str, object]:
    expected_schedule = balanced_lane_schedule(
        repeat_count=repeat_count,
        lane_a=lane_a,
        lane_b=lane_b,
    )
    observed_schedule = tuple(observation.spec for observation in observations)
    schedule_valid = observed_schedule == expected_schedule
    elapsed_by_lane: dict[str, list[float]] = defaultdict(list)
    components_by_lane: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    quality_passed = bool(observations)
    for observation in observations:
        elapsed_by_lane[observation.spec.lane].append(observation.elapsed_ms)
        quality_passed = quality_passed and observation.quality_passed
        for component, value in observation.component_ms:
            components_by_lane[observation.spec.lane][component].append(value)

    block_deltas: list[float] = []
    for block_index in range(1, repeat_count + 1):
        block = [
            observation
            for observation in observations
            if observation.spec.block_index == block_index
        ]
        a_values = tuple(
            observation.elapsed_ms
            for observation in block
            if observation.spec.lane == lane_a
        )
        b_values = tuple(
            observation.elapsed_ms
            for observation in block
            if observation.spec.lane == lane_b
        )
        if len(a_values) == len(b_values) == 2:
            block_deltas.append(float(median(a_values) - median(b_values)))

    delta_summary = summarize_distribution(
        tuple(block_deltas),
        bootstrap_seed=bootstrap_seed + 101,
    )
    delta_ci = delta_summary.get("bootstrap_median_ci_95")
    latency_superiority_claim_allowed = bool(
        schedule_valid
        and quality_passed
        and repeat_count >= 3
        and isinstance(delta_ci, list)
        and len(delta_ci) == 2
        and float(delta_ci[1]) < 0.0
    )
    lane_summaries = {
        lane: summarize_distribution(
            tuple(elapsed_by_lane.get(lane, ())),
            bootstrap_seed=bootstrap_seed + index,
        )
        for index, lane in enumerate((lane_a, lane_b), start=1)
    }
    component_summaries = {
        lane: {
            component: summarize_distribution(
                tuple(values),
                bootstrap_seed=bootstrap_seed + 1000 + index,
            )
            for index, (component, values) in enumerate(
                sorted(components_by_lane.get(lane, {}).items()),
                start=1,
            )
        }
        for lane in (lane_a, lane_b)
    }
    return {
        "schema_version": "statebus.balanced_lane_experiment.v1",
        "lane_a": lane_a,
        "lane_b": lane_b,
        "repeat_count": repeat_count,
        "observation_count": len(observations),
        "order_design": "alternating_abba_baab",
        "serialized_execution": True,
        "schedule_valid": schedule_valid,
        "quality_gate_passed": quality_passed,
        "lane_summaries": lane_summaries,
        "component_summaries": component_summaries,
        "paired_block_delta_a_minus_b_ms": delta_summary,
        "latency_superiority_claim_allowed": latency_superiority_claim_allowed,
        "claim_boundary": (
            "Latency superiority requires at least three serialized balanced blocks, "
            "equal quality, and a 95% bootstrap interval for lane A minus lane B below zero."
        ),
    }


def run_balanced_serialized_experiment(
    callbacks: Mapping[str, Callable[[LaneRunSpec], LaneCallbackResult]],
    *,
    lane_a: str,
    lane_b: str,
    repeat_count: int,
    bootstrap_seed: int = 20260721,
) -> tuple[tuple[LaneObservation, ...], dict[str, object]]:
    if set(callbacks) != {lane_a, lane_b}:
        raise ValueError("balanced_callback_lane_set_mismatch")
    observations: list[LaneObservation] = []
    for spec in balanced_lane_schedule(
        repeat_count=repeat_count,
        lane_a=lane_a,
        lane_b=lane_b,
    ):
        started_ns = time.perf_counter_ns()
        result = callbacks[spec.lane](spec)
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        observations.append(LaneObservation(
            spec=spec,
            elapsed_ms=elapsed_ms,
            quality_passed=result.quality_passed,
            component_ms=tuple(
                (str(key), float(value))
                for key, value in sorted(result.component_ms.items())
            ),
        ))
    frozen = tuple(observations)
    return frozen, summarize_balanced_lane_observations(
        frozen,
        lane_a=lane_a,
        lane_b=lane_b,
        repeat_count=repeat_count,
        bootstrap_seed=bootstrap_seed,
    )
