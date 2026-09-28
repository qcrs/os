"""External development scorer. Reads raw released CSVs, not Runtime output code.

Decimal-based reference implementation is deliberately separate from the Runtime
float-based validator. Nothing from this module is passed to provider prompts.
"""
from __future__ import annotations

import csv
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
import math

from statebus.benchmark.contest_stage1_taskpack import (
    TASK_OPERATIONS, TASK_PERIODS, V2_TASKS, _required_periods,
)


def _csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


EXTENDED = frozenset({
    "finance_quarterly_review", "finance_period_delta", "finance_budget_review", "finance_budget_status_review", "finance_budget_delta_review",
    "finance_half_year_review", "service_sequence_review", "service_error_delta",
    "service_p95_review", "service_multiweek_review",
})


def _released_rows(public_root: Path, task_id: str) -> list[dict]:
    prefix = task_id[0]
    family = "finance" if prefix == "F" else "service_ops"
    root = public_root / family
    periods = _required_periods(task_id)
    slo = {r["site_id"]: Decimal(r["slo_error_rate"]) for r in _csv(root / "slo.csv")} if prefix == "O" else {}
    budget = {}
    if task_id in {"F08", "F09", "F10"}:
        for period in periods:
            if period in {"2026-05", "2026-06"}:
                for row in _csv(root / f"budget_{period}.csv"):
                    key = (row["month"], row["unit_id"])
                    if key in budget:
                        raise ValueError(f"duplicate_budget_key:{key}")
                    budget[key] = Decimal(row["budget_net_revenue_cny"])
    rows = []
    for period in periods:
        names = [f"{'actual' if prefix == 'F' else 'hourly'}_{period}.csv"]
        if task_id in {"O08", "O09"}:
            names = [f"latency_samples_{period}.csv"]
        elif task_id == "O10" and period in {"W07", "W08"}:
            names.append(f"latency_samples_{period}.csv")
        note = f"{'notes' if prefix == 'F' else 'events'}_{period}.md"
        note_text = (root / note).read_text(encoding="utf-8")
        for name in names:
            for raw in _csv(root / name):
                row = dict(raw)
                key = row["unit_id" if prefix == "F" else "site_id"]
                if f"## {key}\n" not in note_text:
                    raise ValueError("scorer_missing_raw_note")
                for field, value in list(row.items()):
                    if field.endswith(("_cny", "_count", "_ms")):
                        row[field] = Decimal(value)
                row["is_current"] = period == TASK_PERIODS[task_id]
                row["note_locator" if prefix == "F" else "event_locator"] = f"{note}#{key}"
                if prefix == "O":
                    row["slo_error_rate"] = slo[key]
                    row["sample_p95_latency_ms"] = Decimal(next(x["sample_p95_latency_ms"] for x in _csv(root / "slo.csv") if x["site_id"] == key))
                    row["row_kind"] = "latency_sample" if name.startswith("latency_samples") else "hourly"
                if (period, key) in budget:
                    row["budget_net_revenue_cny"] = budget[(period, key)]
                rows.append(row)
    return rows


def _money(row):
    return ((row["booked_revenue_cny"] - row["refund_cny"]) if "booked_revenue_cny" in row else row["net_revenue_cny"], row["cost_cny"])


def _fin(batch):
    revenue = sum((_money(r)[0] for r in batch), Decimal(0)); cost = sum((_money(r)[1] for r in batch), Decimal(0))
    ratio = (revenue - cost) / revenue
    return revenue, cost, float((Decimal(100) * ratio).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)), ratio < Decimal("0.20")


def _svc_amount(row):
    if "completed_request_count" in row:
        return row["completed_request_count"], row["final_failed_request_count"], row["request_latency_sum_ms"]
    return row["request_count"], row["failed_request_count"], row["latency_sum_ms"]


def _svc(batch):
    req = sum((_svc_amount(r)[0] for r in batch), Decimal(0)); fail = sum((_svc_amount(r)[1] for r in batch), Decimal(0)); lat = sum((_svc_amount(r)[2] for r in batch), Decimal(0))
    error = float((Decimal(100) * fail / req).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
    mean = float((lat / req).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
    return req, fail, lat, error, mean, fail / req > batch[0]["slo_error_rate"]


def _latencies(batch):
    return [r["latency_ms"] for r in batch]


def _nearest(values):
    ordered = sorted(values); return ordered[max(1, int(math.ceil(len(ordered) * Decimal("0.95")))) - 1]


def _change(current, previous):
    if previous is None: return "initial"
    if current and not previous: return "new"
    if previous and not current: return "resolved"
    return "still_risk" if current else "still_clear"


def _q(value):
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


def _extended_reference(public_root: Path, task_id: str) -> list[dict]:
    operation = TASK_OPERATIONS[task_id]
    rows = _released_rows(public_root, task_id)
    periods = _required_periods(task_id)
    current = TASK_PERIODS[task_id]
    field, key_field = ("month", "unit_id") if task_id.startswith("F") else ("week", "site_id")
    grouped = {}
    for row in rows:
        grouped.setdefault(row[key_field], {}).setdefault(row[field], []).append(row)
    out = []
    for key in sorted(grouped):
        batches = grouped[key]
        now = batches[current]
        before = batches.get(periods[-2], []) if len(periods) > 1 else []
        if operation == "finance_quarterly_review":
            rev, cost, margin, risk = _fin(now)
            result = {"unit_id": key, "net_revenue_cny": int(rev), "cost_cny": int(cost), "profit_cny": int(rev-cost),
                      "margin_pct": margin, "below_20_pct": risk, "risk_change": _change(risk, _fin(before)[3]),
                      "note_locator": now[0]["note_locator"]}
            for month in periods:
                result[f"m{month[-2:]}_margin_pct"] = _fin(batches[month])[2]
            out.append(result)
        elif operation == "finance_half_year_review":
            rev, cost, margin, _ = _fin([r for p in periods for r in batches[p]])
            result = {"unit_id": key, "half_year_net_revenue_cny": int(rev), "half_year_cost_cny": int(cost),
                      "half_year_profit_cny": int(rev-cost), "half_year_margin_pct": margin,
                      "below_20_pct": _fin(now)[3], "risk_change": _change(_fin(now)[3], _fin(before)[3]),
                      "note_locator": now[0]["note_locator"]}
            for month in periods:
                revenue, cost, margin, _ = _fin(batches[month])
                result.update({f"m{month[-2:]}_net_revenue_cny": int(revenue), f"m{month[-2:]}_profit_cny": int(revenue-cost),
                               f"m{month[-2:]}_margin_pct": margin})
            for quarter in (1, 2):
                group = [r for r in rows if r["unit_id"] == key and (int(r["month"][-2:])-1)//3+1 == quarter]
                revenue, cost, _, _ = _fin(group)
                result.update({f"q{quarter}_net_revenue_cny": int(revenue), f"q{quarter}_profit_cny": int(revenue-cost)})
            for month in periods[-2:]:
                revenue = _fin(batches[month])[0]; budget = batches[month][0]["budget_net_revenue_cny"]
                result[f"m{month[-2:]}_attainment_pct"] = _q(100*revenue/budget)
                result[f"m{month[-2:]}_under_budget"] = revenue < budget
            result["budget_risk_change"] = _change(result["m06_under_budget"], result["m05_under_budget"])
            out.append(result)
        elif operation == "finance_period_delta":
            left, _, _, lr = _fin(before); right, _, _, rr = _fin(now)
            out.append({"unit_id": key, "period_from": periods[0], "period_to": periods[-1], "revenue_from_cny": int(left),
                        "revenue_to_cny": int(right), "delta_cny": int(right-left), "growth_pct": _q((right-left)/left*100),
                        "below_20_pct": rr, "risk_change": _change(rr,lr), "note_locator": now[0]["note_locator"]})
        elif operation in {"finance_budget_review", "finance_budget_status_review"}:
            actual = _fin(now)[0]; budget = now[0]["budget_net_revenue_cny"]
            under = actual < budget
            prior = _fin(before)[0] < before[0]["budget_net_revenue_cny"] if before else None
            result = {"unit_id": key, "actual_net_revenue_cny": int(actual), "budget_net_revenue_cny": int(budget),
                      "variance_cny": int(actual-budget), "under_budget": under,
                      "risk_change": _change(under,prior), "note_locator": now[0]["note_locator"]}
            if operation == "finance_budget_review":
                result.update({"variance_pct": _q((actual-budget)/budget*100),
                               "attainment_pct": _q(actual/budget*100)})
            out.append(result)
        elif operation == "finance_budget_delta_review":
            current_actual = _fin(now)[0]; prior_actual = _fin(before)[0]
            current_budget = now[0]["budget_net_revenue_cny"]; prior_budget = before[0]["budget_net_revenue_cny"]
            current_under = current_actual < current_budget; prior_under = prior_actual < prior_budget
            out.append({"unit_id": key, "current_actual_net_revenue_cny": int(current_actual),
                        "prior_actual_net_revenue_cny": int(prior_actual),
                        "current_budget_net_revenue_cny": int(current_budget),
                        "prior_budget_net_revenue_cny": int(prior_budget),
                        "current_variance_cny": int(current_actual-current_budget),
                        "prior_variance_cny": int(prior_actual-prior_budget),
                        "current_under_budget": current_under, "prior_under_budget": prior_under,
                        "risk_change": _change(current_under, prior_under),
                        "note_locator": now[0]["note_locator"]})
        elif operation in {"service_sequence_review", "service_multiweek_review"}:
            hourly = {p: [r for r in batches[p] if r["row_kind"] == "hourly"] for p in periods}
            recent = _svc(hourly[current]); prior = _svc(hourly[periods[-2]])
            stats = recent if operation == "service_sequence_review" else _svc([r for p in periods for r in hourly[p]])
            result = {"site_id": key, "request_count": int(stats[0]), "failed_request_count": int(stats[1]),
                      "error_rate_pct": stats[3], "mean_latency_ms": stats[4], "exceeds_slo": recent[5],
                      "risk_change": _change(recent[5], prior[5]), "event_locator": now[0]["event_locator"]}
            for week in periods:
                result[f"{week.lower()}_error_rate_pct"] = _svc(hourly[week])[3]
            if operation == "service_multiweek_review":
                result["weeks_included"] = len(periods)
                for week in periods[-2:]:
                    samples = [r for r in batches[week] if r["row_kind"] == "latency_sample"]
                    p95 = int(_nearest(_latencies(samples)))
                    result[f"{week.lower()}_p95_latency_ms"] = p95
                    result[f"{week.lower()}_p95_exceeds_slo"] = p95 > samples[0]["sample_p95_latency_ms"]
                result["p95_risk_change"] = _change(result["w08_p95_exceeds_slo"],result["w07_p95_exceeds_slo"])
            out.append(result)
        elif operation == "service_error_delta":
            left, right = _svc(before), _svc(now)
            out.append({"site_id": key, "period_from": periods[0], "period_to": periods[-1], "error_rate_from_pct": left[3],
                        "error_rate_to_pct": right[3], "error_rate_delta_pp": _q(Decimal(str(right[3]))-Decimal(str(left[3]))),
                        "exceeds_slo": right[5], "risk_change": _change(right[5],left[5]), "event_locator": now[0]["event_locator"]})
        elif operation == "service_p95_review":
            p95 = int(_nearest(_latencies(now))); threshold = now[0]["sample_p95_latency_ms"]
            risk = p95 > threshold; prior = _nearest(_latencies(before)) > threshold if before else None
            out.append({"site_id": key, "period": current, "sample_count": len(now), "p95_latency_ms": p95,
                        "exceeds_slo": risk, "risk_change": _change(risk,prior), "event_locator": now[0]["event_locator"]})
    if operation == "finance_period_delta":
        for rank, row in enumerate(sorted(out, key=lambda r: (Decimal(r["delta_cny"])/r["revenue_from_cny"],r["unit_id"])), 1):
            row["decline_rank"] = rank
    if operation == "service_error_delta":
        for rank, row in enumerate(sorted(out, key=lambda r: (-Decimal(str(r["error_rate_delta_pp"])),r["site_id"])), 1):
            row["deterioration_rank"] = rank
    return out


def reference_rows(public_root: Path, task_id: str) -> list[dict]:
    if TASK_OPERATIONS[task_id] in EXTENDED:
        return _extended_reference(public_root, task_id)
    finance = task_id.startswith("F")
    family, key = ("finance", "unit_id") if finance else ("service_ops", "site_id")
    root = public_root / family
    current = TASK_PERIODS[task_id]
    v2 = task_id in V2_TASKS
    periods = list(_required_periods(task_id)) if task_id in {"F02", "O02", "F07", "O07"} else [current]
    risks = {}
    result = []
    thresholds = {r["site_id"]: Decimal(r["slo_error_rate"]) for r in _csv(root / "slo.csv")} if not finance else {}
    for period in periods:
        raw = _csv(root / f"{'actual' if finance else 'hourly'}_{period}.csv")
        for entity in sorted({r[key] for r in raw}):
            group = [r for r in raw if r[key] == entity]
            def total(field):
                return sum((Decimal(r[field]) for r in group), Decimal(0))
            def quant(value):
                return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
            if finance:
                revenue = total("booked_revenue_cny") - total("refund_cny") if v2 else total("net_revenue_cny")
                cost = total("cost_cny")
                ratio = (revenue-cost)/revenue
                risk = ratio < Decimal("0.20")
                record = {key: entity, "net_revenue_cny": int(revenue), "cost_cny": int(cost),
                          "profit_cny": int(revenue-cost), "margin_pct": quant(100*ratio), "below_20_pct": risk}
            else:
                requests = total("completed_request_count" if v2 else "request_count")
                failures = total("final_failed_request_count" if v2 else "failed_request_count")
                risk = failures/requests > thresholds[entity]
                record = {key: entity, "request_count": int(requests), "failed_request_count": int(failures),
                          "error_rate_pct": quant(100*failures/requests),
                          "mean_latency_ms": quant(total("request_latency_sum_ms" if v2 else "latency_sum_ms")/requests), "exceeds_slo": risk}
            before = risks.get(entity)
            record["risk_change"] = ("initial" if before is None else "new" if risk and not before else
                                     "resolved" if before and not risk else "still_risk" if risk else "still_clear")
            notes = f"{'notes' if finance else 'events'}_{period}.md"
            if f"## {entity}\n" not in (root / notes).read_text():
                raise ValueError("scorer_missing_raw_note")
            record["note_locator" if finance else "event_locator"] = f"{notes}#{entity}"
            risks[entity] = risk
            if period == current:
                result.append(record)
    return result


def score_rows(public_root: Path, task_id: str, observed) -> dict:
    expected = reference_rows(public_root, task_id)
    checks = {"row_count": len(observed) == len(expected)}
    for index, right in enumerate(expected):
        left = observed[index] if index < len(observed) and isinstance(observed[index], dict) else {}
        checks[f"{index}:fields"] = set(left) == set(right)
        for key, value in right.items():
            actual = left.get(key)
            if isinstance(value, float):
                passed = isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, value, rel_tol=0, abs_tol=0.00011)
            else:
                passed = type(actual) is type(value) and actual == value
            checks[f"{index}:{key}"] = passed
    return {"passed": all(checks.values()), "checks": checks, "expected": expected, "actual": list(observed)}
