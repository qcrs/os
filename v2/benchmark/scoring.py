from __future__ import annotations

from dataclasses import dataclass

from v2.benchmark.models import QualityFloorResult
from v2.utils import stable_json_dumps


@dataclass(frozen=True)
class FixedAnswerLaneResult:
    task_id: str
    route: str
    tool_name: str
    summary_text: str
    revenue_value: str
    selected_doc_hashes: tuple[str, ...]
    supporting_doc_ids: tuple[str, ...] = ()
    contamination_detected: bool = False
    metric_name: str = ""
    metric_value: str = ""


@dataclass(frozen=True)
class FixedAnswerScore:
    route_exact: bool
    tool_exact: bool
    revenue_exact: bool
    selected_doc_hashes_exact: bool
    summary_present: bool
    exact_match: bool
    admissible_match: bool
    correctness_label: str
    quality_floor: QualityFloorResult
    metric_name_exact: bool = False
    metric_value_exact: bool = False


def expected_facts_for_scoring(
    *,
    expected_facts: dict[str, object],
    metric_projection_key: str = "",
) -> dict[str, object]:
    projected = dict(expected_facts)
    if not metric_projection_key or projected.get("metric_name") or projected.get("metric_value"):
        return projected
    if metric_projection_key in projected:
        current: object = projected[metric_projection_key]
    else:
        current = projected
        for segment in metric_projection_key.split("."):
            if not isinstance(current, dict) or segment not in current:
                return projected
            current = current[segment]
    projected["metric_name"] = metric_projection_key
    projected["metric_value"] = (
        stable_json_dumps(current)
        if isinstance(current, (dict, list, tuple))
        else str(current)
    )
    return projected


def score_fixed_answer_case(
    *,
    observed: FixedAnswerLaneResult,
    expected_route: str,
    expected_tool_name: str,
    expected_facts: dict[str, object],
) -> FixedAnswerScore:
    expected_metric_name = str(expected_facts.get("metric_name", "")).strip()
    expected_metric_value = str(
        expected_facts.get("metric_value", expected_facts.get("revenue_value", ""))
    ).strip()
    expected_revenue = str(expected_facts.get("revenue_value", "")).strip()
    expected_doc_hashes = tuple(str(item).strip() for item in expected_facts.get("selected_doc_hashes", []) if str(item).strip())
    observed_metric_name = str(observed.metric_name or "").strip()
    observed_metric_value = str(observed.metric_value or observed.revenue_value or "").strip()
    route_exact = observed.route == expected_route
    tool_exact = observed.tool_name == expected_tool_name
    revenue_exact = observed.revenue_value == expected_revenue if expected_revenue else bool(observed.revenue_value)
    metric_name_exact = observed_metric_name == expected_metric_name if expected_metric_name else True
    metric_value_exact = (
        observed_metric_value == expected_metric_value
        if expected_metric_value
        else bool(observed_metric_value)
    )
    selected_doc_hashes_exact = (
        observed.selected_doc_hashes == expected_doc_hashes if expected_doc_hashes else bool(observed.selected_doc_hashes)
    )
    summary_present = bool(observed.summary_text.strip())
    exact_match = route_exact and tool_exact
    requested_metric_exact = metric_name_exact and metric_value_exact
    admissible_match = exact_match and requested_metric_exact and selected_doc_hashes_exact
    quality_floor = QualityFloorResult(
        quality_floor_pass=summary_present and admissible_match and not observed.contamination_detected,
        deterministic_checks_passed=summary_present and requested_metric_exact,
        fact_coverage_passed=admissible_match,
        llm_judge_passed=None,
        quality_floor_fail_reason=(
            ""
            if summary_present and admissible_match and not observed.contamination_detected
            else "contamination_detected"
            if observed.contamination_detected
            else "fact_coverage_failed"
            if summary_present and requested_metric_exact
            else "deterministic_checks_failed"
        ),
    )
    return FixedAnswerScore(
        route_exact=route_exact,
        tool_exact=tool_exact,
        revenue_exact=revenue_exact,
        selected_doc_hashes_exact=selected_doc_hashes_exact,
        summary_present=summary_present,
        exact_match=exact_match,
        admissible_match=admissible_match,
        correctness_label="exact_match" if admissible_match else "mismatch",
        quality_floor=quality_floor,
        metric_name_exact=metric_name_exact,
        metric_value_exact=metric_value_exact,
    )
