"""Offline-only authored programs. Never used by the live provider path.

These exercise generic operators against raw inputs; no scorer output or task
answer is consulted. Branches select public method families, not task IDs.
"""
from statebus.contracts import TransformProgram, TransformStep
from statebus.benchmark.contest_dsl_taskpack import DslTaskContract


def offline_program(contract: DslTaskContract, refs: dict[str, str]) -> TransformProgram:
    if contract.output_contract_version.startswith("mechanism_simple_v2."):
        return _simple_program(contract, refs)
    ops = []
    calculations = []
    finance = contract.family == "finance"
    key = "unit_id" if finance else "site_id"
    method = contract.method
    fields = contract.output_schema

    def add(op, **args):
        ops.append(TransformStep(op, args))

    def aggregate(groups, metrics):
        add("aggregate_grouped", group_fields=groups,
            value_fields=[x[0] for x in metrics], functions=[x[1] for x in metrics],
            outputs=[x[2] for x in metrics])

    def join(name, keys):
        add("join_by_key", right_ref=refs[name], left_keys=keys, right_keys=keys)

    def calc(output, kind, lhs, rhs, *formatting):
        calculations.append([output, kind, lhs, rhs, *formatting])

    if "cross_agent" in method:
        if finance:
            aggregate([key], [("revenue_cny", "count", "period_count"),
                *[(x, "sum", x) for x in ("revenue_cny", "cost_cny", "profit_cny")],
                ("margin_pct", "min", "minimum_month_margin_pct"),
                ("budget_delta_cny", "min", "worst_budget_delta_cny")])
            calc("margin_pct", "ratio", "profit_cny", "revenue_cny", 100, 4)
            calc("budget_risk", "less_than", "worst_budget_delta_cny", 0)
        else:
            aggregate([key], [("request_count", "count", "period_count"),
                *[(x, "sum", x) for x in ("request_count", "failed_count", "latency_sum_ms")],
                ("p95_latency_ms", "max", "max_p95_latency_ms")])
            join("thresholds", [key])
            calc("error_rate_pct", "ratio", "failed_count", "request_count", 100, 4)
            calc("mean_latency_ms", "ratio", "latency_sum_ms", "request_count", 1, 4)
            calc("p95_breached", "greater_than", "max_p95_latency_ms", "sample_p95_latency_ms")
    elif "sample_p95" in method:
        add("percentile_nearest_rank", group_fields=["period", key], value_field="latency_ms",
            percentile=95, output="p95_latency_ms", sample_count_output="sample_count")
        join("thresholds", [key])
        calc("p95_breached", "greater_than", "p95_latency_ms", "sample_p95_latency_ms")
    else:
        groups = ["period", key]
        if "quarter" in fields:
            groups.append("quarter")
        if finance:
            aggregate(groups, [(x, "sum", x) for x in ("gross_cny", "refund_cny", "cost_cny")])
            calc("revenue_cny", "difference", "gross_cny", "refund_cny")
            calc("profit_cny", "difference", "revenue_cny", "cost_cny")
            calc("margin_ratio", "ratio", "profit_cny", "revenue_cny")
            calc("margin_pct", "ratio", "profit_cny", "revenue_cny", 100, 4)
            calc("low_margin", "less_than", "margin_ratio", 0.2)
        else:
            aggregate(groups, [(x, "sum", x) for x in ("request_count", "failed_count", "latency_sum_ms")])
            if "period_delta" not in method:
                join("thresholds", [key])
                calc("error_ratio", "ratio", "failed_count", "request_count")
                calc("slo_breached", "greater_than", "error_ratio", "slo_error_rate")
            calc("error_rate_pct", "ratio", "failed_count", "request_count", 100, 4)
            calc("mean_latency_ms", "ratio", "latency_sum_ms", "request_count", 1, 4)
        if "period_delta" in method:
            add("derive_safe", calculations=calculations)
            add("compare_periods", group_fields=[key], period_field="period",
                value_field="revenue_cny" if finance else "error_rate_pct")
            add("rank", metric="difference", output="change_rank", descending=True, tie_break_columns=[key])
            add("select", columns=list(fields))
            return TransformProgram("offline-method-fixture", tuple(refs.values()), tuple(ops), contract.output_contract_version)
        if "budgets" in refs:
            join("budgets", ["period", key])
            calc("budget_delta_cny", "difference", "revenue_cny", "budget_cny")
            calc("attainment_pct", "ratio", "revenue_cny", "budget_cny", 100, 4)
            calc("under_budget", "less_than", "revenue_cny", "budget_cny")
    if "prior" in refs:
        join("prior", [key])
        prior = next(x for x in contract.input_schemas["prior"] if x != key)
        calc("risk_change", "boolean_change", prior.removeprefix("prior_"), prior)
    if "history" in refs:
        join("history", ["period", key] if "period" in contract.input_schemas["history"] else [key])
        if "verified_revenue_delta_cny" in fields:
            calc("verified_revenue_delta_cny", "difference", "revenue_cny", "verified_revenue_cny")
        if "p95_breached" in fields:
            calc("p95_breached", "greater_than", "p95_latency_ms", "sample_p95_latency_ms")
    add("derive_safe", calculations=calculations)
    add("sort", columns=(["period"] if "period" in fields else []) + [key])
    add("select", columns=list(fields))
    if len(ops) > contract.max_operations:
        raise ValueError(f"offline_fixture_operation_budget:{method}:{len(ops)}")
    return TransformProgram("offline-method-fixture", tuple(refs.values()), tuple(ops), contract.output_contract_version)


def _simple_program(contract: DslTaskContract, refs: dict[str, str]) -> TransformProgram:
    """Offline fixtures by method family only; no per-round answer/program map."""
    finance = contract.family == "finance"
    key = "unit_id" if finance else "site_id"
    totals = "verified_totals" in contract.method
    values = (["revenue_cny", "cost_cny", "profit_cny"] if finance else ["request_count", "failed_count"]) if totals else (["gross_cny", "refund_cny", "cost_cny"] if finance else ["request_count", "failed_count"])
    functions = ["sum"] * len(values)
    outputs = list(values)
    if totals:
        values = [*values, values[0]]
        functions.append("count")
        outputs.append("period_count")
    ops = [TransformStep("aggregate_grouped", {"group_fields": [key] if totals else ["period", key],
        "value_fields": values, "functions": functions, "outputs": outputs})]
    for name in refs:
        if name != "source":
            keys = ["period", key] if name in {"budgets", "plans"} else [key]
            ops.append(TransformStep("join_by_key", {"right_ref": refs[name], "left_keys": keys, "right_keys": keys}))
    calculations = []
    if finance and not totals:
        calculations.extend([["revenue_cny", "difference", "gross_cny", "refund_cny"],
                             ["profit_cny", "difference", "revenue_cny", "cost_cny"]])
    if "baseline" in refs:
        calculations.append(["difference", "difference", "revenue_cny" if finance else "failed_count", "baseline_value"])
    if "budgets" in refs:
        calculations.append(["budget_delta_cny", "difference", "revenue_cny", "budget_cny"])
    if "plans" in refs:
        calculations.append(["plan_delta_count", "difference", "request_count", "planned_request_count"])
    if calculations:
        ops.append(TransformStep("derive_safe", {"calculations": calculations}))
    ops.extend([TransformStep("sort", {"columns": [key] if totals else ["period", key]}),
                TransformStep("select", {"columns": list(contract.output_schema)})])
    if len(ops) > contract.max_operations:
        raise ValueError(f"offline_fixture_operation_budget:{contract.method}:{len(ops)}")
    return TransformProgram("offline-method-fixture", tuple(refs.values()), tuple(ops), contract.output_contract_version)
