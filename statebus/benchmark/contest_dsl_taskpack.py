"""Frozen, public prompt-38 DSL contracts and release-only input binding.

Binding only parses, renames and projects raw values or verified historical
artifacts. Business arithmetic belongs to TransformDslInterpreter. Offline gold
and fixture programs live in separate modules and are never provider inputs.
"""
from __future__ import annotations

import csv
import hashlib
import random
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from statebus.benchmark.contest_stage1_taskpack import ENTITIES, SEED, generate_sealed as _generate_legacy_sealed

FAMILIES = {"F": "finance", "O": "service_ops"}
CONTRACT_VERSION = "statebus.contest_dsl.v1"
RAW_FINANCE = {"period": "string", "quarter": "string", "unit_id": "string", "gross_cny": "number", "refund_cny": "number", "cost_cny": "number"}
RAW_SERVICE = {"period": "string", "site_id": "string", "request_count": "number", "failed_count": "number", "latency_sum_ms": "number"}
FINANCE = {"period": "string", "unit_id": "string", "revenue_cny": "number", "cost_cny": "number", "profit_cny": "number", "margin_pct": "number", "low_margin": "boolean"}
SERVICE = {"period": "string", "site_id": "string", "request_count": "number", "failed_count": "number", "latency_sum_ms": "number", "error_rate_pct": "number", "mean_latency_ms": "number", "slo_error_rate": "number", "slo_breached": "boolean"}
BUDGET = {**FINANCE, "budget_cny": "number", "budget_delta_cny": "number", "attainment_pct": "number", "under_budget": "boolean"}
P95 = {"period": "string", "site_id": "string", "sample_count": "integer", "p95_latency_ms": "number", "sample_p95_latency_ms": "number", "p95_breached": "boolean"}
SLO = {"site_id": "string", "slo_error_rate": "number", "sample_p95_latency_ms": "number"}


@dataclass(frozen=True)
class DslTaskContract:
    task_id: str
    family: str
    method: str
    periods: tuple[str, ...]
    required_files: tuple[str, ...]
    release_files: tuple[str, ...]
    required_history: tuple[str, ...]
    input_schemas: dict[str, dict[str, str]]
    output_schema: dict[str, str]
    instructions: str
    output_contract_version: str
    max_operations: int = 6

    @property
    def operation(self) -> str:
        return self.method

    @property
    def round(self) -> int:
        return int(self.task_id[1:])

    def public_view(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("periods", "required_files", "release_files", "required_history"):
            result[key] = list(result[key])
        result["round"] = self.round
        return result


def _source_files(prefix: str, periods: tuple[str, ...], samples: bool = False) -> list[str]:
    files: list[str] = []
    for period in periods:
        v2 = (period >= "2026-04") if prefix == "F" else period >= "W05"
        files.extend((f"dictionary_v{2 if v2 else 1}.md", f"{'notes' if prefix == 'F' else 'events'}_{period}.md"))
        files.append(f"{'actual' if prefix == 'F' else 'latency_samples' if samples else 'hourly'}_{period}.csv")
    if prefix == "O":
        files.append("slo.csv")
    return files


def _contracts() -> dict[str, DslTaskContract]:
    specs: dict[str, dict[str, Any]] = {}
    finance_periods = (("2026-01",), ("2026-02",), ("2026-03",), ("2026-01", "2026-02"), ("2026-02", "2026-03"), ("2026-04",), ("2026-05",), ("2026-05",), ("2026-06",), tuple(f"2026-{m:02}" for m in range(1, 7)), ("2026-06",), tuple(f"2026-{m:02}" for m in range(1, 7)))
    service_periods = (("W01",), ("W02",), ("W03",), ("W02", "W03"), ("W03", "W04"), ("W05",), ("W06",), ("W07",), ("W08",), tuple(f"W{w:02}" for w in range(1, 9)), ("W08",), tuple(f"W{w:02}" for w in range(1, 9)))
    for prefix, all_periods in (("F", finance_periods), ("O", service_periods)):
        for number, periods in enumerate(all_periods, 1):
            task_id = f"{prefix}{number:02}"
            finance = prefix == "F"
            sample = not finance and number in (8, 9, 11)
            files = _source_files(prefix, periods, sample)
            base = FINANCE if finance else SERVICE
            schemas = {"source": dict(RAW_FINANCE if finance else RAW_SERVICE)}
            if not finance:
                schemas["thresholds"] = dict(SLO)
            history: tuple[str, ...] = ()
            schema = dict(base)
            method = f"{'finance' if finance else 'service'}_monthly_v{2 if number in (6, 7) else 1}"
            instructions = (
                "Group raw rows by period and unit_id. revenue_cny=sum(gross_cny)-sum(refund_cny); cost_cny=sum(cost_cny); profit_cny=revenue_cny-cost_cny; margin_pct=100*profit_cny/revenue_cny rounded to four decimals. low_margin uses the UNROUNDED ratio profit_cny/revenue_cny < 0.20."
                if finance else
                "Group raw rows by period and site_id. Sum request_count, failed_count and latency_sum_ms. Join thresholds by site_id. error_rate_pct=100*failed_count/request_count and mean_latency_ms=latency_sum_ms/request_count, rounded to four decimals. slo_breached uses the UNROUNDED failed_count/request_count > slo_error_rate. failed_count in v2 is FINAL failures, never failed attempts."
            )
            if number in (2, 7):
                prior_id = f"{prefix}{1 if number == 2 else 6:02}"
                history = (prior_id,)
                risk = "low_margin" if finance else "slo_breached"
                schemas["prior"] = {"unit_id" if finance else "site_id": "string", f"prior_{risk}": "boolean"}
                schema["risk_change"] = "string"
                instructions += f" Join prior by entity; risk_change=boolean_change(current {risk},prior_{risk}): new,resolved,still_risk,still_clear."
                method += "_change"
            if number == 3:
                history = (f"{prefix}01", f"{prefix}02")
                metric = "margin_pct" if finance else "error_rate_pct"
                key = "unit_id" if finance else "site_id"
                schemas["history"] = {key: "string", f"period1_{metric}": "number", f"period2_{metric}": "number"}
                schema.update({f"period1_{metric}": "number", f"period2_{metric}": "number"})
                instructions += f" Join history by {key}; preserve period1_{metric} and period2_{metric} from verified rounds 1/2 to form a compact three-period sequence alongside current {metric}."
                method = f"{'finance' if finance else 'service'}_three_period_sequence"
            if number in (4, 5):
                metric = "revenue_cny" if finance else "error_rate_pct"
                key = "unit_id" if finance else "site_id"
                schema = {key: "string", "baseline_period": "string", "comparison_period": "string", "baseline_value": "number", "comparison_value": "number", "difference": "number", "growth_pct": "number", "change_rank": "integer"}
                method = f"{'finance_revenue' if finance else 'service_error'}_period_delta"
                instructions += f" Compare exactly {periods[0]} then {periods[1]} within each {key}, using {metric}; return signed difference=current-baseline and growth_pct=100*difference/baseline. Comparison results retain full numeric precision; service input error_rate_pct is rounded to four decimals. For service, difference is percentage points. change_rank is ordinal descending difference, ties ascending entity."
            if number in (8, 9, 11):
                if finance:
                    method = "finance_budget" + ("_change" if number in (9, 11) else "")
                    schema = dict(BUDGET)
                    files.append(f"budget_{periods[0]}.csv")
                    schemas["budgets"] = {"period": "string", "unit_id": "string", "budget_cny": "number"}
                    instructions += " Join budgets on period/unit_id; budget_delta_cny=revenue_cny-budget_cny, attainment_pct=100*revenue_cny/budget_cny (four decimals), under_budget=revenue_cny<budget_cny."
                    risk = "under_budget"
                else:
                    method = "service_sample_p95" + ("_change" if number in (9, 11) else "")
                    schema = dict(P95)
                    schemas["source"] = {"period": "string", "site_id": "string", "sample_id": "string", "latency_ms": "number"}
                    instructions = "Group samples by period/site_id. p95_latency_ms is sorted latency_ms[ceil(0.95*N)-1], sample_count=N. Join thresholds by site_id; p95_breached=p95_latency_ms>sample_p95_latency_ms. Do not use hourly aggregates."
                    risk = "p95_breached"
                if number in (9, 11):
                    history = (f"{prefix}08",)
                    schemas["prior"] = {"unit_id" if finance else "site_id": "string", f"prior_{risk}": "boolean"}
                    schema["risk_change"] = "string"
                    instructions += f" Join prior by entity; risk_change=boolean_change({risk},prior_{risk}). Re-read and recompute current data, including when reusing a validated method."
            if number == 10:
                history = tuple(f"{prefix}{n:02}" for n in range(1, 10))
                if finance:
                    method = "finance_half_year_monthly_audit"
                    schema = {**FINANCE, "quarter": "string", "budget_delta_cny": "number", "verified_revenue_delta_cny": "number"}
                    schemas["history"] = {"period": "string", "unit_id": "string", "verified_revenue_cny": "number", "budget_delta_cny": "number"}
                    files.extend(("budget_2026-05.csv", "budget_2026-06.csv"))
                    instructions += " Preserve quarter in grouping. Emit six monthly rows per unit annotated with quarter (compact monthly/quarter-indexed report, not a wide half-year table). Join history on period/unit_id; verified_revenue_delta_cny=recomputed revenue_cny-verified_revenue_cny MUST be zero. Carry validated May/June budget_delta_cny; months without a published budget use zero only as not-applicable sentinel."
                else:
                    method = "service_eight_week_audit"
                    schema = {**SERVICE, "p95_latency_ms": "number", "p95_available": "boolean", "p95_breached": "boolean"}
                    schemas["history"] = {"period": "string", "site_id": "string", "p95_latency_ms": "number", "p95_available": "boolean"}
                    files.extend(("latency_samples_W07.csv", "latency_samples_W08.csv"))
                    instructions += " Emit eight weekly rows per site, join verified history by period/site_id. p95_available is true only W07/W08; other weeks carry p95_latency_ms=0 as not-applicable sentinel. p95_breached=p95_latency_ms>sample_p95_latency_ms. Raw hourly and raw sample tables are never mixed."
            if number == 12:
                # The executor re-runs the R10 method against the same released
                # raw sources. The summarizer audits against the prior verified
                # structured artifact, never against the producer's report.
                prior = specs[f"{prefix}10"]
                history = (*prior["required_history"], f"{prefix}10")
                schemas = {name: dict(fields) for name, fields in prior["input_schemas"].items()}
                schema = dict(prior["output_schema"])
                method = prior["method"]
                files = list(prior["required_files"])
                instructions = prior["instructions"] + " Recompute the same public audit contract from current sources. The Summarizer must cross-check the verified round-10 structured artifact and issue its own cited report; never copy the producer report."
            instructions += " Return exactly the output_schema fields, sorted ascending by period/entity when present, otherwise entity; no causal inference from contextual notes."
            specs[task_id] = dict(task_id=task_id, family=FAMILIES[prefix], method=method, periods=periods, required_files=tuple(dict.fromkeys(files)), required_history=history, input_schemas=schemas, output_schema=schema, instructions=instructions, output_contract_version=f"{CONTRACT_VERSION}.{method}")
    tasks: dict[str, DslTaskContract] = {}
    for prefix in FAMILIES:
        published: set[str] = set()
        for number in range(1, 13):
            item = specs[f"{prefix}{number:02}"]
            release = tuple(name for name in item["required_files"] if name not in published)
            published.update(release)
            tasks[item["task_id"]] = DslTaskContract(**item, release_files=release)
    return tasks


TASKS = _contracts()


SIMPLE_PROFILE = "mechanism_simple_v2"
PROFILES = ("default", SIMPLE_PROFILE)
SIMPLE_FINANCE = {key: value for key, value in FINANCE.items() if key not in {"margin_pct", "low_margin"}}
SIMPLE_SERVICE = {key: value for key, value in SERVICE.items() if key in {"period", "site_id", "request_count", "failed_count"}}


def _simple_contracts() -> dict[str, DslTaskContract]:
    tasks = {}
    for prefix, family in FAMILIES.items():
        finance = prefix == "F"
        key = "unit_id" if finance else "site_id"
        metric = "revenue_cny" if finance else "failed_count"
        base = SIMPLE_FINANCE if finance else SIMPLE_SERVICE
        raw = {k: v for k, v in (RAW_FINANCE if finance else RAW_SERVICE).items()
               if k not in {"quarter", "latency_sum_ms"}}
        periods = (("2026-01", "2026-02", "2026-03", "2026-02", "2026-03", "2026-04", "2026-05", "2026-05", "2026-06")
                   if finance else ("W01", "W02", "W03", "W03", "W04", "W05", "W06", "W07", "W08"))
        # One verified producer per physical period: never double-count rechecks.
        producers = (1, 2, 3, 6, 7, 9) if finance else (1, 2, 3, 5, 6, 7, 8, 9)
        published = set()
        for number in range(1, 13):
            task_id = f"{prefix}{number:02}"
            current = periods[number - 1] if number <= 9 else periods[-1]
            task_periods = (current,)
            files = [f for f in _source_files(prefix, task_periods) if f != "slo.csv"]
            version = 2 if current >= ("2026-04" if finance else "W05") else 1
            method = f"{family}_simple_summary_v{version}"
            inputs = {"source": dict(raw)}
            output = dict(base)
            history = ()
            instructions = (
                "Group source by period and unit_id. Sum gross_cny, refund_cny and cost_cny. "
                "revenue_cny = summed gross_cny minus summed refund_cny; profit_cny = revenue_cny minus summed cost_cny. "
                "The published v1 binding maps net_revenue_cny to gross_cny and refund_cny to zero; v2 deducts refunds exactly once."
                if finance else
                "Group source by period and site_id, summing request_count and failed_count. "
                "failed_count is FINAL failed requests, never diagnostic failed attempts."
            )
            if number == 3:
                method = f"{family}_simple_sequence_v1"
                history = (f"{prefix}01", f"{prefix}02")
                prior_fields = {f"period{i}_{metric}": "number" for i in (1, 2)}
                inputs["history"] = {key: "string", **prior_fields}
                output.update(prior_fields)
                instructions += f" Join history by {key}, retaining the two verified earlier {metric} values alongside current {metric}; this is a three-period sequence."
            if number in (4, 5):
                method = f"{family}_simple_delta_v1"
                producer = (1 if number == 4 else 2) if finance else (2 if number == 4 else 3)
                history = (f"{prefix}{producer:02}",)
                inputs["baseline"] = {key: "string", "baseline_period": "string", "baseline_value": "number"}
                output.update(baseline_period="string", baseline_value="number", difference="number")
                instructions += f" Join baseline by {key}; difference = current {metric} minus baseline_value. Retain current-period base quantities and baseline_period. This is a count/amount change, not a rate or growth ranking."
            if number in (8, 9, 11):
                method = f"{family}_simple_plan_join_v2"
                plan = "budgets" if finance else "plans"
                field = "budget_cny" if finance else "planned_request_count"
                delta = "budget_delta_cny" if finance else "plan_delta_count"
                actual = "revenue_cny" if finance else "request_count"
                inputs[plan] = {"period": "string", key: "string", field: "number"}
                output.update({field: "number", delta: "number"})
                files.append(f"{'budget' if finance else 'plan'}_{current}.csv")
                if not finance:
                    files.append("plan_generation.md")
                instructions += f" Join {plan} on period and {key}; {delta} = {actual} minus {field}. Retain all current-period base quantities."
                if number == 11:
                    instructions += " Reuse a compatible verified method when available, but read and recompute current inputs. This is a same-source recomputation audit, not new-data evaluation."
            if number in (10, 12):
                method = f"{family}_simple_verified_totals_v2"
                task_periods = tuple(periods[n - 1] for n in producers)
                history = tuple(f"{prefix}{n:02}" for n in producers)
                if number == 12:
                    history += (f"{prefix}10",)
                inputs = {"source": dict(base)}
                quantities = {k: v for k, v in base.items() if k not in {"period", key}}
                output = {key: "string", "period_count": "integer", **quantities}
                instructions = f"Source contains only verified earlier period artifacts, one row per period/{key}. Group by {key}, sum " + ", ".join(quantities) + f", and count {metric} as period_count. Do not recompute from raw CSV or copy previous totals."
                if number == 12:
                    instructions += " A different Agent, Summarizer, must read the round-10 structured artifact, cross-check all current totals and generate its own cited audit report."
                # These already-released files support independent scoring and
                # contextual retrieval; they are NOT the Executor source table.
                files = [f for f in _source_files(prefix, task_periods) if f != "slo.csv"]
            instructions += f" Return exactly output_schema, sorted ascending by " + (f"period then {key}." if "period" in output else f"{key}.") + " No ratios, risk thresholds, ranking or causal inference."
            required = tuple(dict.fromkeys(files))
            release = tuple(f for f in required if f not in published)
            published.update(release)
            tasks[task_id] = DslTaskContract(task_id, family, method, task_periods, required, release,
                history, inputs, output, instructions, f"{SIMPLE_PROFILE}.{method}", max_operations=5)
    return tasks


SIMPLE_TASKS = _simple_contracts()


def task_contract(task_id: str, *, profile: str = "default") -> DslTaskContract:
    if profile not in PROFILES:
        raise ValueError(f"unknown_task_profile:{profile}")
    return (SIMPLE_TASKS if profile == SIMPLE_PROFILE else TASKS)[task_id]


def tasks_for_family(family: str, *, profile: str = "default") -> tuple[DslTaskContract, ...]:
    if family not in FAMILIES.values():
        raise ValueError(f"unknown_family:{family}")
    return tuple(task_contract(task.task_id, profile=profile) for task in TASKS.values() if task.family == family)


def generate_sealed(root: Path, *, seed: int = SEED, profile: str = "default") -> None:
    if profile not in PROFILES:
        raise ValueError(f"unknown_task_profile:{profile}")
    _generate_legacy_sealed(root, seed=seed)
    if profile != SIMPLE_PROFILE:
        return
    folder = root / "service_ops"
    (folder / "plan_generation.md").write_text(
        f"# Public request plan generation\nSeed={seed}. For W07/W08 independently: "
        "rng=random.Random(f'{seed}:service_request_plan:{period}'); for S-A,S-B,S-C,S-D "
        "in that order (zero-based index), planned_request_count=12000+250*index+rng.randrange(0,600). "
        "Plans are frozen before execution and independent of actual results/model output.\n", encoding="utf-8")
    for period in ("W07", "W08"):
        rng = random.Random(f"{seed}:service_request_plan:{period}")
        with (folder / f"plan_{period}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("week", "site_id", "planned_request_count"))
            writer.writeheader()
            writer.writerows({"week": period, "site_id": entity, "planned_request_count": 12000 + 250*i + rng.randrange(0, 600)}
                             for i, entity in enumerate(ENTITIES["O"]))


def release_task(sealed_root: Path, public_root: Path, task_id: str, *, profile: str = "default") -> tuple[Path, ...]:
    contract = task_contract(task_id, profile=profile)
    folder = public_root / contract.family
    folder.mkdir(parents=True, exist_ok=True)
    for name in contract.required_files:
        target = folder / name
        source = sealed_root / contract.family / name
        if name not in contract.release_files and not target.is_file():
            raise ValueError(f"prior_release_missing:{name}")
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f"released_source_changed:{name}")
    for name in contract.release_files:
        target = folder / name
        if not target.exists():
            shutil.copyfile(sealed_root / contract.family / name, target)
    return tuple(folder / name for name in contract.required_files)


def publish_required_files(sealed_root: Path, public_root: Path, task_id: str, *, profile: str = "default") -> tuple[Path, ...]:
    """Publish exactly one task's declared public inputs, independent of round order.

    This is the bounded mechanism-experiment publisher.  It never publishes a
    future task's files and never imports historical artifacts or answers.
    Existing files must remain byte-identical to the sealed public dataset.
    """
    contract = task_contract(task_id, profile=profile)
    folder = public_root / contract.family
    folder.mkdir(parents=True, exist_ok=True)
    published = []
    for name in contract.required_files:
        source = sealed_root / contract.family / name
        target = folder / name
        if not source.is_file():
            raise ValueError(f"sealed_source_missing:{contract.family}/{name}")
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                raise ValueError(f"released_source_changed:{name}")
        else:
            shutil.copyfile(source, target)
        published.append(target)
    return tuple(published)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def input_file_hashes(public_root: Path, task_id: str, *, profile: str = "default") -> dict[str, str]:
    contract = task_contract(task_id, profile=profile)
    return {f"{contract.family}/{name}": hashlib.sha256((public_root / contract.family / name).read_bytes()).hexdigest() for name in contract.required_files}


def _history_rows(history: Mapping[str, list[dict[str, Any]]], task: str) -> list[dict[str, Any]]:
    if task not in history:
        raise ValueError(f"verified_history_missing:{task}")
    return history[task]


def bind_inputs(public_root: Path, task_id: str, *, history: Mapping[str, list[dict[str, Any]]] | None = None, profile: str = "default") -> dict[str, list[dict[str, Any]]]:
    contract = task_contract(task_id, profile=profile)
    root = public_root / contract.family
    for name in contract.required_files:
        if not (root / name).is_file():
            raise ValueError(f"required_release_missing:{name}")
    history = {} if history is None else history
    for prior in contract.required_history:
        _history_rows(history, prior)
    if profile == SIMPLE_PROFILE:
        return _bind_simple_inputs(root, contract, history)
    prefix, number = task_id[0], contract.round
    finance = prefix == "F"
    tables: dict[str, list[dict[str, Any]]] = {"source": []}
    if not finance and number in (8, 9, 11):
        for period in contract.periods:
            tables["source"].extend({"period": row["week"], "site_id": row["site_id"], "sample_id": row["sample_id"], "latency_ms": int(row["latency_ms"])} for row in _csv(root / f"latency_samples_{period}.csv"))
    else:
        for period in contract.periods:
            for row in _csv(root / f"{'actual' if finance else 'hourly'}_{period}.csv"):
                if finance:
                    tables["source"].append({"period": row["month"], "quarter": "2026-Q1" if row["month"] <= "2026-03" else "2026-Q2", "unit_id": row["unit_id"], "gross_cny": int(row["booked_revenue_cny"] if "booked_revenue_cny" in row else row["net_revenue_cny"]), "refund_cny": int(row.get("refund_cny", "0")), "cost_cny": int(row["cost_cny"])})
                else:
                    v2 = "completed_request_count" in row
                    tables["source"].append({"period": row["week"], "site_id": row["site_id"], "request_count": int(row["completed_request_count" if v2 else "request_count"]), "failed_count": int(row["final_failed_request_count" if v2 else "failed_request_count"]), "latency_sum_ms": int(row["request_latency_sum_ms" if v2 else "latency_sum_ms"])})
    if "thresholds" in contract.input_schemas:
        tables["thresholds"] = [{"site_id": row["site_id"], "slo_error_rate": float(row["slo_error_rate"]), "sample_p95_latency_ms": int(row["sample_p95_latency_ms"])} for row in _csv(root / "slo.csv")]
    if "budgets" in contract.input_schemas:
        tables["budgets"] = [{"period": row["month"], "unit_id": row["unit_id"], "budget_cny": int(row["budget_net_revenue_cny"])} for period in contract.periods for row in _csv(root / f"budget_{period}.csv")]
    key = "unit_id" if finance else "site_id"
    if "prior" in contract.input_schemas:
        field = next(field for field in contract.input_schemas["prior"] if field != key)
        tables["prior"] = [{key: row[key], field: row[field.removeprefix("prior_")]} for row in _history_rows(history, contract.required_history[0])]
    if number == 3:
        metric = "margin_pct" if finance else "error_rate_pct"
        first = {row[key]: row[metric] for row in _history_rows(history, f"{prefix}01")}
        tables["history"] = [{key: row[key], f"period1_{metric}": first[row[key]], f"period2_{metric}": row[metric]} for row in _history_rows(history, f"{prefix}02")]
    if number in (10, 12):
        if finance:
            monthly = {period: _history_rows(history, task) for period, task in (("2026-01", "F01"), ("2026-02", "F02"), ("2026-03", "F03"), ("2026-04", "F06"), ("2026-05", "F07"), ("2026-06", "F09"))}
            budgets = {(row["period"], row[key]): row["budget_delta_cny"] for task in ("F08", "F09") for row in _history_rows(history, task)}
            tables["history"] = [{"period": period, key: row[key], "verified_revenue_cny": row["revenue_cny"], "budget_delta_cny": budgets.get((period, row[key]), 0)} for period, rows in monthly.items() for row in rows]
        else:
            p95 = {(row["period"], row[key]): row["p95_latency_ms"] for task in ("O08", "O09") for row in _history_rows(history, task)}
            entities = [row["site_id"] for row in tables["thresholds"]]
            tables["history"] = [{"period": period, "site_id": entity, "p95_latency_ms": p95.get((period, entity), 0), "p95_available": (period, entity) in p95} for period in contract.periods for entity in entities]
    if set(tables) != set(contract.input_schemas):
        raise ValueError("bound_table_schema_mismatch")
    for name, rows in tables.items():
        if any(set(row) != set(contract.input_schemas[name]) for row in rows):
            raise ValueError(f"bound_row_schema_mismatch:{name}")
    return tables


def _bind_simple_inputs(root: Path, contract: DslTaskContract, history) -> dict[str, list[dict[str, Any]]]:
    """Projection/field mapping only; all arithmetic stays in Runtime DSL."""
    finance = contract.family == "finance"
    key = "unit_id" if finance else "site_id"
    tables = {"source": []}
    if "verified_totals" in contract.method:
        for producer in contract.required_history:
            if producer.endswith("10"):
                continue  # R12 audit witness; not another period in the totals.
            tables["source"].extend({field: row[field] for field in contract.input_schemas["source"]}
                                    for row in _history_rows(history, producer))
    else:
        for period in contract.periods:
            for row in _csv(root / f"{'actual' if finance else 'hourly'}_{period}.csv"):
                if finance:
                    values = {"period": row["month"], key: row[key],
                        "gross_cny": int(row["booked_revenue_cny"] if "booked_revenue_cny" in row else row["net_revenue_cny"]),
                        "refund_cny": int(row.get("refund_cny", "0")), "cost_cny": int(row["cost_cny"])}
                else:
                    v2 = "completed_request_count" in row
                    values = {"period": row["week"], key: row[key],
                        "request_count": int(row["completed_request_count" if v2 else "request_count"]),
                        "failed_count": int(row["final_failed_request_count" if v2 else "failed_request_count"])}
                tables["source"].append(values)
    if "history" in contract.input_schemas:
        metric = "revenue_cny" if finance else "failed_count"
        first = {row[key]: row[metric] for row in _history_rows(history, contract.required_history[0])}
        tables["history"] = [{key: row[key], f"period1_{metric}": first[row[key]], f"period2_{metric}": row[metric]}
                             for row in _history_rows(history, contract.required_history[1])]
    if "baseline" in contract.input_schemas:
        metric = "revenue_cny" if finance else "failed_count"
        tables["baseline"] = [{key: row[key], "baseline_period": row["period"], "baseline_value": row[metric]}
                              for row in _history_rows(history, contract.required_history[0])]
    if "budgets" in contract.input_schemas:
        tables["budgets"] = [{"period": row["month"], key: row[key], "budget_cny": int(row["budget_net_revenue_cny"])}
                             for period in contract.periods for row in _csv(root / f"budget_{period}.csv")]
    if "plans" in contract.input_schemas:
        tables["plans"] = [{"period": row["week"], key: row[key], "planned_request_count": int(row["planned_request_count"])}
                           for period in contract.periods for row in _csv(root / f"plan_{period}.csv")]
    if set(tables) != set(contract.input_schemas):
        raise ValueError("bound_table_schema_mismatch")
    for name, rows in tables.items():
        if any(set(row) != set(contract.input_schemas[name]) for row in rows):
            raise ValueError(f"bound_row_schema_mismatch:{name}")
    return tables
