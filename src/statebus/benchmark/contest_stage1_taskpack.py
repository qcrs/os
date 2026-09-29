"""Published inputs for two ten-round campaigns and the shorter Memory chains.

Legacy raw batches are frozen; later tasks consume the same released periods,
then add budgets and individual request latency samples.
"""

from __future__ import annotations

import csv
import hashlib
import random
from pathlib import Path

from statebus.benchmark.adaptive_formal import FormalAdaptiveCase, _operation_semantics, _source_schema, formal_output_contract
from statebus.benchmark.minimal_runner import MinimalBenchmarkSample
from statebus.contracts import CanonicalTaskSpec


SEED = 20260924
FAMILIES = {"F": "finance", "O": "service_ops"}
# The original four tasks and their bytes remain stable.  The delivery
# campaign adds the remaining rounds as one ordered business chain per family.
PERIODS = {"F01": "2026-01", "F02": "2026-02", "O01": "W01", "O02": "W02"}
TASK_PERIODS = {
    **PERIODS,
    "F03": "2026-03", "F04": "2026-02", "F05": "2026-03", "F06": "2026-04", "F07": "2026-05",
    "F08": "2026-05", "F09": "2026-06", "F10": "2026-06", "O03": "W03", "O04": "W03", "O05": "W04",
    "O06": "W05", "O07": "W06", "O08": "W07", "O09": "W08", "O10": "W08",
}
V2_PERIODS = {"F06": "2026-04", "F07": "2026-05", "F08": "2026-05", "F09": "2026-06",
              "O06": "W05", "O07": "W06", "O08": "W07", "O09": "W08"}
V2_TASKS = frozenset(V2_PERIODS)
LEGACY_TASKS = frozenset({"F01", "F02", "O01", "O02", "F06", "O06"})
TASK_OPERATIONS = {
    "F01": "finance_monthly_review", "F02": "finance_monthly_review", "F03": "finance_quarterly_review",
    "F04": "finance_period_delta", "F05": "finance_period_delta", "F06": "finance_v2_monthly_review",
    "F07": "finance_v2_monthly_review", "F08": "finance_budget_status_review", "F09": "finance_budget_delta_review",
    "F10": "finance_half_year_review", "O01": "service_weekly_review", "O02": "service_weekly_review",
    "O03": "service_sequence_review", "O04": "service_error_delta", "O05": "service_error_delta",
    "O06": "service_v2_weekly_review", "O07": "service_v2_weekly_review", "O08": "service_p95_review",
    "O09": "service_p95_review", "O10": "service_multiweek_review",
}
DATA_PERIODS = {
    **{f"2026-{month:02d}": False for month in range(1, 4)},
    **{f"2026-{month:02d}": True for month in range(4, 7)},
    **{f"W{week:02d}": week >= 5 for week in range(1, 9)},
}
ENTITIES = {"F": ("U-A", "U-B", "U-C", "U-D"), "O": ("S-A", "S-B", "S-C", "S-D")}


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate_sealed(root: Path, *, seed: int = SEED) -> None:
    """Write the frozen public inputs for both ten-round chains.

    The four legacy files and F06/O06 v2 files retain their historical recipes;
    newly added periods use task/period-scoped RNG streams so extending the
    campaign cannot silently rewrite earlier evidence.
    """
    if root.exists():
        raise FileExistsError(root)
    legacy_rng = random.Random(seed)
    for prefix, family in FAMILIES.items():
        folder = root / family
        folder.mkdir(parents=True)
        (folder / "dictionary_v1.md").write_text(
            "# Public definitions\n\n" + (
                "Amounts are integer CNY. profit=sum(net_revenue_cny)-sum(cost_cny); "
                "margin_pct=100*profit/revenue, rounded to four decimals. "
                "Risk uses the UNROUNDED ratio profit/revenue < 0.20. Never average row margins.\n"
                if prefix == "F" else
                "Request counts include failed requests. error_rate_pct=100*sum(failed_request_count)/sum(request_count); "
                "mean_latency_ms=sum(latency_sum_ms)/sum(request_count), both rounded to four decimals. "
                "Risk uses the UNROUNDED ratio failed/request > slo_error_rate. Read each site's threshold from slo.csv. Never average hourly rates.\n"
            ), encoding="utf-8",
        )
        (folder / "dictionary_v2.md").write_text(
            "# Public definitions v2\n\n" + (
                "Amounts are integer CNY. net_revenue_cny is computed per row as "
                "booked_revenue_cny-refund_cny; profit=sum(net_revenue_cny)-sum(cost_cny); "
                "margin_pct=100*profit/revenue, rounded to four decimals. "
                "Risk uses the UNROUNDED ratio profit/revenue < 0.20. Never use booked revenue as net revenue.\n"
                if prefix == "F" else
                "completed_request_count includes requests that ultimately failed. "
                "error_rate_pct=100*sum(final_failed_request_count)/sum(completed_request_count); "
                "mean_latency_ms=sum(request_latency_sum_ms)/sum(completed_request_count), both rounded to four decimals. "
                "failed_attempt_count is diagnostic and must not be used as the error numerator. "
                "Risk uses the UNROUNDED ratio final_failed/completed > slo_error_rate.\n"
            ), encoding="utf-8",
        )
        if prefix == "O":
            _write_csv(folder / "slo.csv", ("site_id", "slo_error_rate", "sample_p95_latency_ms"), [
                {"site_id": key, "slo_error_rate": "0.02", "sample_p95_latency_ms": 500}
                for key in ENTITIES[prefix]
            ])

    # Write each physical period once. F08/F10 and O10 reuse already published
    # periods, so they do not create alternate bytes for the same filename.
    for prefix, family in FAMILIES.items():
        folder = root / family
        periods = [period for period, is_v2 in DATA_PERIODS.items()
                   if (period.startswith("2026-") if prefix == "F" else period.startswith("W"))]
        for period in periods:
            v2 = DATA_PERIODS[period]
            legacy = (prefix, period) in {("F", "2026-01"), ("F", "2026-02"), ("O", "W01"), ("O", "W02")}
            if legacy:
                rng = legacy_rng
            elif period in {"2026-04", "W05"}:
                rng = random.Random(f"{seed}:{'F06' if period == '2026-04' else 'O06'}:v2")
            else:
                rng = random.Random(f"{seed}:{prefix}:{period}:{'v2' if v2 else 'v1'}")
            notes = [f"# Synthetic {family} {period}", ""]
            explanations = (
                ("A partner promotion was active; rebates are already deducted from net revenue.",
                 "Expedited shipments increased fulfillment cost; figures include these invoices.",
                 "Supplier prices changed during the month; contract renewal remains under review.",
                 "Direct-channel orders increased; no revenue recognition policy changed.")
                if prefix == "F" else
                ("A gateway rollout occurred on day two; rollback completed that evening.",
                 "A dependency maintenance window occurred on day four; causation has not been established.",
                 "A traffic mix shift was observed; all completed requests remain in the denominator.",
                 "A capacity adjustment completed on day five; client-side timeouts require separate investigation.")
            )
            if v2:
                explanations = (
                    ("Refunds are reported separately from booked revenue; deduct them once under the v2 dictionary.",
                     "Fulfillment invoices are included in cost; refunds remain a separate revenue deduction.",
                     "Supplier renewal is under review; this note does not establish the cause of a margin change.",
                     "Direct-channel orders increased; only the published v2 accounting definition applies.")
                    if prefix == "F" else
                    ("Retries are recorded as failed attempts; only ultimate request failures enter the v2 error numerator.",
                     "A dependency maintenance window occurred; causation has not been established.",
                     "The traffic mix changed; all completed requests remain in the v2 denominator.",
                     "A capacity adjustment completed; failed attempts are diagnostic rather than final request outcomes.")
                )
            for key, explanation in zip(ENTITIES[prefix], explanations):
                notes.extend((f"## {key}", f"{key} {period}: {explanation}", ""))
            notes.extend(("## Scope", "These are synthetic development records. Events are contextual facts, not proven root causes.", "",
                          "## Accounting boundary" if prefix == "F" else "## Monitoring boundary",
                          f"Use the published {'v2' if v2 else 'v1'} dictionary. No future batches or subsequent-policy definitions are available.", ""))
            note_path = folder / f"{'notes' if prefix == 'F' else 'events'}_{period}.md"
            note_path.write_text("\n".join(notes), encoding="utf-8")
            rows = []
            for index, key in enumerate(ENTITIES[prefix]):
                if prefix == "F":
                    if legacy:
                        margin = ((16, 23, 18, 31) if period == "2026-01" else (24, 17, 18, 29))[index]
                    else:
                        margin = (19, 14, 23, 28)[index] if period == "2026-04" else ((18, 22, 16, 28)[index] if period in {"2026-03", "2026-05"} else (21, 15, 24, 27)[index])
                    for product in ("P1", "P2", "P3"):
                        for channel in ("direct", "partner"):
                            booked = 100_000 + 1_000 * index + rng.randrange(0, 2000) + (3000 if period == "2026-02" else 0)
                            if v2:
                                refund = 1_200 + 250 * index + rng.randrange(0, 700)
                                rows.append({"month": period, "unit_id": key, "region": ("north", "south")[index % 2],
                                             "product": product, "channel": channel, "booked_revenue_cny": booked,
                                             "refund_cny": refund, "cost_cny": (booked - refund) * (100 - margin) // 100})
                            else:
                                rows.append({"month": period, "unit_id": key, "region": ("north", "south")[index % 2],
                                             "product": product, "channel": channel, "net_revenue_cny": booked,
                                             "cost_cny": booked * (100 - margin) // 100})
                else:
                    if legacy:
                        rate = ((0.014, 0.026, 0.018, 0.034) if period == "W01" else (0.028, 0.013, 0.029, 0.014))[index]
                    else:
                        rate = (0.019, 0.031, 0.016, 0.027)[index] if period == "W05" else ((0.018, 0.024, 0.016, 0.030)[index] if period in {"W03", "W06", "W07"} else (0.022, 0.017, 0.027, 0.015)[index])
                    for hour in range(168):
                        requests = 60 + rng.randrange(0, 25)
                        failures = int(requests * rate * 10 + rng.randrange(0, 10)) // 10
                        if v2:
                            attempts = failures + rng.randrange(0, 4)
                            rows.append({"week": period, "hour": f"D{hour // 24 + 1}T{hour % 24:02d}", "site_id": key,
                                         "completed_request_count": requests, "final_failed_request_count": failures,
                                         "failed_attempt_count": attempts,
                                         "request_latency_sum_ms": requests * (120 + index * 23 + hour % 11)})
                        else:
                            rows.append({"week": period, "hour": f"D{hour // 24 + 1}T{hour % 24:02d}", "site_id": key,
                                         "request_count": requests, "failed_request_count": failures,
                                         "latency_sum_ms": requests * (120 + index * 23 + hour % 11)})
            fields = (("month", "unit_id", "region", "product", "channel", "booked_revenue_cny", "refund_cny", "cost_cny")
                      if prefix == "F" and v2 else
                      ("month", "unit_id", "region", "product", "channel", "net_revenue_cny", "cost_cny")
                      if prefix == "F" else
                      ("week", "hour", "site_id", "completed_request_count", "final_failed_request_count", "failed_attempt_count", "request_latency_sum_ms")
                      if v2 else
                      ("week", "hour", "site_id", "request_count", "failed_request_count", "latency_sum_ms"))
            _write_csv(folder / f"{'actual' if prefix == 'F' else 'hourly'}_{period}.csv", fields, rows)
        if prefix == "O":
            for period in ("W07", "W08"):
                rng = random.Random(f"{seed}:latency_samples:{period}")
                samples = []
                for index, key in enumerate(ENTITIES["O"]):
                    base = ((220, 560, 320, 610) if period == "W07" else (580, 310, 550, 280))[index]
                    for sample_id in range(128):
                        samples.append({"week": period, "site_id": key, "sample_id": f"{period}-{key}-{sample_id:03d}",
                                        "latency_ms": base + rng.randrange(-40, 121)})
                _write_csv(folder / f"latency_samples_{period}.csv", ("week", "site_id", "sample_id", "latency_ms"), samples)
        if prefix == "F":
            budget_rows = []
            for index, key in enumerate(ENTITIES["F"]):
                for period in ("2026-05", "2026-06"):
                    budget_rows.append({"month": period, "unit_id": key, "budget_net_revenue_cny": 600_000 + index * 8_000 + (20_000 if period == "2026-06" else 0)})
            for period in ("2026-05", "2026-06"):
                _write_csv(folder / f"budget_{period}.csv", ("month", "unit_id", "budget_net_revenue_cny"),
                           [row for row in budget_rows if row["month"] == period])

def _input_periods(task_id: str) -> tuple[str, ...]:
    if task_id == "F03": return ("2026-01", "2026-02", "2026-03")
    if task_id in {"F04"}: return ("2026-01", "2026-02")
    if task_id in {"F05"}: return ("2026-02", "2026-03")
    if task_id == "F06": return ("2026-04",)
    if task_id == "F07": return ("2026-04", "2026-05")
    if task_id == "F08": return ("2026-05",)
    if task_id == "F09": return ("2026-05", "2026-06")
    if task_id == "F10": return tuple(f"2026-{month:02d}" for month in range(1, 7))
    if task_id == "O03": return ("W01", "W02", "W03")
    if task_id == "O04": return ("W02", "W03")
    if task_id == "O05": return ("W03", "W04")
    if task_id == "O06": return ("W05",)
    if task_id == "O07": return ("W05", "W06")
    if task_id == "O08": return ("W07",)
    if task_id == "O09": return ("W07", "W08")
    if task_id == "O10": return tuple(f"W{week:02d}" for week in range(1, 9))
    return (TASK_PERIODS[task_id],)


def _required_periods(task_id: str) -> tuple[str, ...]:
    # F01/F02 and O01/O02 deliberately require their predecessor to be
    # published through the chain, preserving the release-isolation contract.
    if task_id == "F02": return ("2026-01", "2026-02")
    if task_id == "O02": return ("W01", "W02")
    return _input_periods(task_id)


def files_for(root: Path, task_id: str) -> tuple[Path, ...]:
    family = FAMILIES[task_id[0]]
    period = TASK_PERIODS[task_id]
    folder = root / family
    paths = [folder / ("dictionary_v2.md" if task_id in V2_TASKS else "dictionary_v1.md")]
    if task_id in {"F10", "O10"}:
        paths.append(folder / "dictionary_v2.md")
    if task_id.startswith("O"):
        paths.append(folder / "slo.csv")
    if task_id in {"F08", "F09"}:
        paths.append(folder / f"budget_{period}.csv")
    if task_id in {"O08", "O09"}:
        paths.append(folder / f"latency_samples_{period}.csv")
    paths.extend((folder / f"{'actual' if task_id.startswith('F') else 'hourly'}_{period}.csv",
                  folder / f"{'notes' if task_id.startswith('F') else 'events'}_{period}.md"))
    # Preserve order while removing the v2 dictionary duplicate in F10.
    return tuple(dict.fromkeys(paths))


def bound_rows(public_root: Path, task_id: str) -> tuple[dict[str, object], ...]:
    """Bind only released rows; all prior periods are explicit chain inputs."""
    prefix = task_id[0]
    family = FAMILIES[prefix]
    directory = public_root / family
    required = _required_periods(task_id)
    current = TASK_PERIODS[task_id]
    slo = {}
    if prefix == "O":
        with (directory / "slo.csv").open(newline="", encoding="utf-8") as handle:
            slo = {row["site_id"]: row for row in csv.DictReader(handle)}
    budget = {}
    if task_id in {"F08", "F09", "F10"}:
        for period in required:
            if period not in {"2026-05", "2026-06"}:
                continue
            with (directory / f"budget_{period}.csv").open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    key = (row["month"], row["unit_id"])
                    if key in budget:
                        raise ValueError(f"duplicate_budget_key:{key}")
                    budget[key] = int(row["budget_net_revenue_cny"])
    output = []
    for period in required:
        names = [f"{'actual' if prefix == 'F' else 'hourly'}_{period}.csv"]
        if task_id in {"O08", "O09"}:
            names = [f"latency_samples_{period}.csv"]
        elif task_id == "O10" and period in {"W07", "W08"}:
            names.append(f"latency_samples_{period}.csv")
        note = f"{'notes' if prefix == 'F' else 'events'}_{period}.md"
        text = (directory / note).read_text(encoding="utf-8")
        for name in names:
            with (directory / name).open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    key = row["unit_id" if prefix == "F" else "site_id"]
                    if f"## {key}\n" not in text:
                        raise ValueError(f"missing_published_note:{note}:{key}")
                    for field in tuple(row):
                        if field.endswith(("_cny", "_count", "_ms")):
                            row[field] = int(row[field])
                    row["note_locator" if prefix == "F" else "event_locator"] = f"{note}#{key}"
                    row["is_current"] = period == current
                    if prefix == "O":
                        row["slo_error_rate"] = float(slo[key]["slo_error_rate"])
                        if task_id in {"O08", "O09", "O10"}:
                            row["sample_p95_latency_ms"] = float(slo[key]["sample_p95_latency_ms"])
                        if task_id == "O10":
                            row["row_kind"] = "latency_sample" if name.startswith("latency_samples") else "hourly"
                    if prefix == "F" and (period, key) in budget:
                        row["budget_net_revenue_cny"] = budget[(period, key)]
                    output.append(row)
    return tuple(output)


def make_case(public_root: Path, task_id: str) -> FormalAdaptiveCase:
    prefix = task_id[0]
    current = TASK_PERIODS[task_id]
    required_periods = _required_periods(task_id)
    family = FAMILIES[prefix]
    operation = TASK_OPERATIONS[task_id]
    required_files = files_for(public_root, task_id)
    directory = public_root / family
    for period in required_periods:
        required_files += (directory / f"{'actual' if prefix == 'F' else 'hourly'}_{period}.csv",
                           directory / f"{'notes' if prefix == 'F' else 'events'}_{period}.md")
    if not all(path.is_file() for path in required_files):
        raise FileNotFoundError("unpublished_stage1_input:" + task_id)
    rows = bound_rows(public_root, task_id)
    entity_key = "unit_id" if prefix == "F" else "site_id"
    entities = tuple(sorted({str(row[entity_key]) for row in rows if row["is_current"]}))
    previous_period = ""
    if operation in {"finance_period_delta", "service_error_delta"}:
        previous_period = str(required_periods[0])
    elif task_id in {"F02", "F03", "F05", "F07", "F09", "F10", "O02", "O03", "O05", "O07", "O09", "O10"}:
        previous_period = required_periods[-2] if len(required_periods) > 1 else ""
    arguments = {
        "dataset_id": f"stage1-{family}-{current}", "csv_path": str(directory / f"{'actual' if prefix == 'F' else 'hourly'}_{current}.csv"),
        "current_period": current, "previous_period": previous_period, "periods": list(required_periods),
    }
    if operation in {"finance_period_delta", "service_error_delta"}:
        arguments.update(period_from=required_periods[0], period_to=required_periods[-1])
    if operation in {"finance_budget_review", "finance_budget_status_review"}:
        arguments["budget_path"] = str(directory / f"budget_{current}.csv")
    spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis", intent_op=operation,
        time_scope=current, target_entities=entities,
        required_outputs=tuple(formal_output_contract(CanonicalTaskSpec(task_family="continuous_csv_table_analysis", intent_op=operation, arguments=arguments, time_scope=current, target_entities=entities, required_outputs=(), required_tools=())).__getitem__(1)),
        required_tools=("read_csv", "bounded_python"), arguments=arguments,
    )
    _op, schema, shape = formal_output_contract(spec)
    raw_path = directory / f"{'actual' if prefix == 'F' else 'hourly'}_{current}.csv"
    request = (
        f"Complete {task_id}: analyze the published {family} records for {current}. "
        f"Use all released raw periods {', '.join(required_periods)} and the public dictionaries. "
        "Aggregate the raw rows with bounded Python, apply the declared operation semantics, and return the exact output schema. "
        "Current notes/events are Markdown PROSE, not a table corpus. The evidence capability is "
        "retrieve_semantic_evidence_v1, NOT retrieve_table_evidence_v1; the complete numeric data are already "
        "bound to the Executor's authorized input. Cite the current filename#entity locator. "
        "Prior verified outputs are cross-check evidence only; recompute every numeric field from authorized raw inputs. "
        f"Public calculation: {_operation_semantics(operation, arguments)['formula']} "
        f"Operation={operation}; output schema={schema}. The row count is determined by current entities, not a fixed literal. "
        f"Authorized source fields: {sorted(_source_schema(rows))}."
    )
    if operation in {
        "finance_quarterly_review", "finance_period_delta", "finance_budget_review", "finance_budget_status_review", "finance_budget_delta_review",
        "finance_half_year_review", "service_sequence_review", "service_error_delta",
        "service_p95_review", "service_multiweek_review",
    }:
        request += (
            " This is a multi-period operation: `is_current` is metadata only and MUST NOT filter rows. "
            "Use the declared month/week periods in the contract, aggregate every authorized row in those periods, "
            "and use current_period/previous_period only for the explicitly requested current or prior risk comparison."
        )
    sample = MinimalBenchmarkSample(
        task_id=task_id, request_text=request, canonical_task_spec=spec,
        task_family=spec.task_family, dataset_id=f"stage1-{family}-{current}",
        dataset_version="synthetic-dev-v2" if any("booked_revenue_cny" in row or "completed_request_count" in row for row in rows) else "synthetic-dev-v1",
        dataset_split="development", dataset_hash=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    )
    return FormalAdaptiveCase(
        sample=sample, operation=operation, capability_id="execute_bounded_python_v2",
        output_contract_version="statebus.analysis_result.v2", source_rows=rows,
        source_schema=_source_schema(rows), output_schema=schema, expected_output_shape=shape,
        operation_semantics=_operation_semantics(operation, spec.arguments),
        report_capability_ids=("compose_claim_set_v2",),
    )
