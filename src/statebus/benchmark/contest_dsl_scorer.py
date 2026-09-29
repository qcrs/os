"""Independent Decimal scorer for prompt-38, reading released raw CSV only.

Does not import or execute TransformProgram, the binder, or fixture programs.
Historical expected values are recomputed from source, never observed outputs.
"""
from collections import defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN
import math
from pathlib import Path

from statebus.benchmark.contest_dsl_taskpack import SIMPLE_PROFILE, task_contract

D = Decimal


def _csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _q(value):
    return float(value.quantize(D("0.0001"), rounding=ROUND_HALF_EVEN))


def _change(now, before):
    return {(True, True): "still_risk", (True, False): "new",
            (False, True): "resolved", (False, False): "still_clear"}[(now, before)]


def _simple_reference_rows(public_root: Path, task_id: str) -> list[dict]:
    """Independent raw CSV oracle; never reads bound/history/Runtime rows."""
    contract = task_contract(task_id, profile=SIMPLE_PROFILE)
    root = public_root / contract.family
    finance = contract.family == "finance"
    key = "unit_id" if finance else "site_id"
    metric = "revenue_cny" if finance else "failed_count"
    result = []
    for period in contract.periods:
        groups = defaultdict(list)
        for raw in _csv(root / f"{'actual' if finance else 'hourly'}_{period}.csv"):
            groups[raw[key]].append(raw)
        for entity, group in sorted(groups.items()):
            row = {"period": period, key: entity}
            if finance:
                revenue = sum(D(r["booked_revenue_cny"]) - D(r["refund_cny"]) if "booked_revenue_cny" in r else D(r["net_revenue_cny"]) for r in group)
                cost = sum(D(r["cost_cny"]) for r in group)
                row.update(revenue_cny=int(revenue), cost_cny=int(cost), profit_cny=int(revenue-cost))
            else:
                row.update(request_count=int(sum(D(r["completed_request_count"] if "completed_request_count" in r else r["request_count"]) for r in group)),
                           failed_count=int(sum(D(r["final_failed_request_count"] if "final_failed_request_count" in r else r["failed_request_count"]) for r in group)))
            result.append(row)
    if "verified_totals" in contract.method:
        quantities = ("revenue_cny", "cost_cny", "profit_cny") if finance else ("request_count", "failed_count")
        result = [{key: entity, "period_count": len(contract.periods),
                   **{field: sum(r[field] for r in result if r[key] == entity) for field in quantities}}
                  for entity in sorted({r[key] for r in result})]
    if "history" in contract.input_schemas:
        for i, producer in enumerate(contract.required_history, 1):
            prior = {r[key]: r for r in _simple_reference_rows(public_root, producer)}
            for row in result:
                row[f"period{i}_{metric}"] = prior[row[key]][metric]
    if "baseline" in contract.input_schemas:
        prior = {r[key]: r for r in _simple_reference_rows(public_root, contract.required_history[0])}
        for row in result:
            before = prior[row[key]]
            row.update(baseline_period=before["period"], baseline_value=before[metric], difference=row[metric]-before[metric])
    if "budgets" in contract.input_schemas or "plans" in contract.input_schemas:
        for row in result:
            filename = f"{'budget' if finance else 'plan'}_{row['period']}.csv"
            plan = next(r for r in _csv(root / filename) if r[key] == row[key])
            if finance:
                target = int(plan["budget_net_revenue_cny"])
                row.update(budget_cny=target, budget_delta_cny=row["revenue_cny"]-target)
            else:
                target = int(plan["planned_request_count"])
                row.update(planned_request_count=target, plan_delta_count=row["request_count"]-target)
    return [{field: row[field] for field in contract.output_schema} for row in result]


def reference_rows(public_root: Path, task_id: str, *, profile: str = "default") -> list[dict]:
    if profile == SIMPLE_PROFILE:
        return _simple_reference_rows(public_root, task_id)
    contract = task_contract(task_id, profile=profile)
    root = public_root / contract.family
    finance = contract.family == "finance"
    key = "unit_id" if finance else "site_id"
    method = contract.method
    slo = {} if finance else {r[key]: r for r in _csv(root / "slo.csv")}
    result = []
    if "cross_agent" in method:
        history = reference_rows(public_root, task_id[0] + "10")
        for entity in sorted({r[key] for r in history}):
            group = [r for r in history if r[key] == entity]
            row = {key: entity, "period_count": len(group)}
            if finance:
                for f in ("revenue_cny", "cost_cny", "profit_cny"):
                    row[f] = sum(r[f] for r in group)
                row.update(margin_pct=_q(100 * D(row["profit_cny"]) / D(row["revenue_cny"])),
                    minimum_month_margin_pct=min(r["margin_pct"] for r in group),
                    worst_budget_delta_cny=min(r["budget_delta_cny"] for r in group))
                row["budget_risk"] = row["worst_budget_delta_cny"] < 0
            else:
                for f in ("request_count", "failed_count", "latency_sum_ms"):
                    row[f] = sum(r[f] for r in group)
                row.update(error_rate_pct=_q(100 * D(row["failed_count"]) / D(row["request_count"])),
                    mean_latency_ms=_q(D(row["latency_sum_ms"]) / D(row["request_count"])),
                    max_p95_latency_ms=max(r["p95_latency_ms"] for r in group))
                row["p95_breached"] = row["max_p95_latency_ms"] > int(slo[entity]["sample_p95_latency_ms"])
            result.append(row)
        return result
    for period in contract.periods:
        filename = ("actual" if finance else "latency_samples" if "sample_p95" in method else "hourly") + f"_{period}.csv"
        groups = defaultdict(list)
        for raw in _csv(root / filename):
            groups[raw[key]].append(raw)
        budgets = {r[key]: int(r["budget_net_revenue_cny"]) for r in _csv(root / f"budget_{period}.csv")} if "budgets" in contract.input_schemas else {}
        for entity, group in sorted(groups.items()):
            row = {"period": period, key: entity}
            if finance:
                revenue = sum((D(r["booked_revenue_cny"]) - D(r["refund_cny"]) if "booked_revenue_cny" in r else D(r["net_revenue_cny"]) for r in group), D(0))
                cost = sum((D(r["cost_cny"]) for r in group), D(0))
                row.update(revenue_cny=int(revenue), cost_cny=int(cost), profit_cny=int(revenue-cost),
                    margin_pct=_q(100*(revenue-cost)/revenue), low_margin=(revenue-cost)/revenue < D("0.2"))
                if budgets:
                    budget = budgets[entity]
                    row.update(budget_cny=budget, budget_delta_cny=int(revenue)-budget,
                        attainment_pct=_q(100*revenue/D(budget)), under_budget=revenue < budget)
                if "quarter" in contract.output_schema:
                    row.update(quarter="2026-Q1" if period <= "2026-03" else "2026-Q2", verified_revenue_delta_cny=0,
                        budget_delta_cny=0 if period < "2026-05" else int(revenue)-next(int(r["budget_net_revenue_cny"]) for r in _csv(root / f"budget_{period}.csv") if r[key] == entity))
            elif "sample_p95" in method:
                samples = sorted(int(r["latency_ms"]) for r in group)
                threshold = int(slo[entity]["sample_p95_latency_ms"])
                p95 = samples[(95*len(samples)+99)//100-1]
                row.update(sample_count=len(samples), p95_latency_ms=p95, sample_p95_latency_ms=threshold, p95_breached=p95>threshold)
            else:
                req = sum(D(r.get("completed_request_count", r.get("request_count"))) for r in group)
                fail = sum(D(r.get("final_failed_request_count", r.get("failed_request_count"))) for r in group)
                latency = sum(D(r.get("request_latency_sum_ms", r.get("latency_sum_ms"))) for r in group)
                threshold = D(slo[entity]["slo_error_rate"])
                row.update(request_count=int(req), failed_count=int(fail), latency_sum_ms=int(latency),
                    error_rate_pct=_q(100*fail/req), mean_latency_ms=_q(latency/req),
                    slo_error_rate=float(threshold), slo_breached=fail/req>threshold)
                if "p95_available" in contract.output_schema:
                    p95 = 0
                    if period in ("W07", "W08"):
                        samples = sorted(int(r["latency_ms"]) for r in _csv(root / f"latency_samples_{period}.csv") if r[key] == entity)
                        p95 = samples[(95*len(samples)+99)//100-1]
                    row.update(p95_latency_ms=p95, p95_available=period in ("W07", "W08"), p95_breached=p95>int(slo[entity]["sample_p95_latency_ms"]))
            result.append(row)
    if "period_delta" in method:
        compared = []
        metric = "revenue_cny" if finance else "error_rate_pct"
        for entity in sorted({r[key] for r in result}):
            before, after = [r for r in result if r[key] == entity]
            lhs, rhs = D(str(before[metric])), D(str(after[metric]))
            compared.append({key: entity, "baseline_period": before["period"], "comparison_period": after["period"],
                "baseline_value": float(lhs), "comparison_value": float(rhs), "difference": float(rhs-lhs), "growth_pct": float(100*(rhs-lhs)/lhs)})
        ranked = sorted(compared, key=lambda r: (-r["difference"], r[key]))
        for row in compared:
            row["change_rank"] = ranked.index(row)+1
        result = compared
    if "prior" in contract.input_schemas:
        risk = next(x for x in contract.input_schemas["prior"] if x != key).removeprefix("prior_")
        previous = {r[key]: r for r in reference_rows(public_root, contract.required_history[0])}
        for row in result:
            row["risk_change"] = _change(row[risk], previous[row[key]][risk])
    if "three_period_sequence" in method:
        metric = "margin_pct" if finance else "error_rate_pct"
        for n, task in enumerate(contract.required_history, 1):
            previous = {r[key]: r for r in reference_rows(public_root, task)}
            for row in result:
                row[f"period{n}_{metric}"] = previous[row[key]][metric]
    return [{field: row[field] for field in contract.output_schema} for row in result]


def score_rows(public_root: Path, task_id: str, rows, *, profile: str = "default") -> dict:
    expected = reference_rows(public_root, task_id, profile=profile)
    schema = task_contract(task_id, profile=profile).output_schema
    errors = []
    if len(rows) != len(expected):
        errors.append("row_count")
    for index, (actual, reference) in enumerate(zip(rows, expected)):
        if not isinstance(actual, dict):
            errors.append(f"schema:{index}:expected_object")
            continue
        if set(actual) != set(schema):
            missing = ",".join(sorted(set(schema) - set(actual)))
            unexpected = ",".join(sorted(set(actual) - set(schema)))
            errors.append(f"schema:{index}:missing={missing}:unexpected={unexpected}")
            continue
        for field, value in reference.items():
            observed = actual[field]
            numeric = schema[field] in {"number", "integer"}
            if numeric:
                valid = type(observed) in (int, float) and math.isfinite(observed)
                valid = valid and (schema[field] != "integer" or type(observed) is int)
                valid = valid and math.isclose(observed, value, rel_tol=1e-10, abs_tol=1e-7)
            else:
                valid = type(observed) is type(value) and observed == value
            if not valid:
                errors.append(f"value:{index}:{field}")
    return {"passed": not errors, "errors": errors, "expected_row_count": len(expected),
            "scorer": "decimal_raw_csv_v1", "task_profile": profile, "expected_rows_used_for_execution": False}
