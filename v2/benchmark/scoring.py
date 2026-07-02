from __future__ import annotations

from dataclasses import dataclass

from v2.benchmark.models import QualityFloorResult


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


def score_fixed_answer_case(
    *,
    observed: FixedAnswerLaneResult,
    expected_route: str,
    expected_tool_name: str,
    expected_facts: dict[str, object],
) -> FixedAnswerScore:
    expected_revenue = str(expected_facts.get("revenue_value", "")).strip()
    expected_doc_hashes = tuple(str(item).strip() for item in expected_facts.get("selected_doc_hashes", []) if str(item).strip())
    route_exact = observed.route == expected_route
    tool_exact = observed.tool_name == expected_tool_name
    revenue_exact = observed.revenue_value == expected_revenue if expected_revenue else bool(observed.revenue_value)
    selected_doc_hashes_exact = (
        observed.selected_doc_hashes == expected_doc_hashes if expected_doc_hashes else bool(observed.selected_doc_hashes)
    )
    summary_present = bool(observed.summary_text.strip())
    exact_match = route_exact and tool_exact
    admissible_match = exact_match and revenue_exact and selected_doc_hashes_exact
    quality_floor = QualityFloorResult(
        quality_floor_pass=summary_present and admissible_match and not observed.contamination_detected,
        deterministic_checks_passed=summary_present and revenue_exact,
        fact_coverage_passed=admissible_match,
        llm_judge_passed=None,
        quality_floor_fail_reason=(
            ""
            if summary_present and admissible_match and not observed.contamination_detected
            else "contamination_detected"
            if observed.contamination_detected
            else "fact_coverage_failed"
            if summary_present and revenue_exact
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
    )
