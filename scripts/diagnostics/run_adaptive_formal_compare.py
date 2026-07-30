"""Thin CLI compatibility entry for the product adaptive formal benchmark."""

from statebus.benchmark.adaptive_formal_mainline import (
    _case_gate_failure,
    _classify_failure,
    _compile_formal_controller_wiring,
    _evaluate_formal_gates,
    _model_plan_errors,
    _normalize_formal_planner_array_leakage,
    _partition_planner_repair_errors,
    _row_scoped_evidence_items,
    main,
)

__all__ = [
    "_case_gate_failure",
    "_classify_failure",
    "_compile_formal_controller_wiring",
    "_evaluate_formal_gates",
    "_model_plan_errors",
    "_normalize_formal_planner_array_leakage",
    "_partition_planner_repair_errors",
    "_row_scoped_evidence_items",
    "main",
]


if __name__ == "__main__":
    main()
