#!/usr/bin/env python3
"""Recompute bounded performance cohorts without pooling repair/source epochs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics


ROLES = ("planner", "retriever", "executor", "summarizer")
TOKENS = ("prompt_tokens", "completion_tokens", "total_tokens")


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def stats(values):
    observed = [value for value in values if finite(value)]
    return {
        "n": len(observed), "missing": len(values) - len(observed),
        "sum": sum(observed) if observed else None,
        "mean": statistics.mean(observed) if observed else None,
        "median": statistics.median(observed) if observed else None,
        "status": "observed" if observed and len(observed) == len(values) else "partial" if observed else "unsupported",
    }


def interval_union(events):
    intervals = [(event.get("start_ns"), event.get("end_ns")) for event in events]
    if not intervals or any(not finite(a) or not finite(b) or b < a for a, b in intervals):
        return None
    total, start, end = 0, *sorted(intervals)[0]
    for left, right in sorted(intervals)[1:]:
        if left > end:
            total += end - start
            start, end = left, right
        else:
            end = max(end, right)
    return (total + end - start) / 1_000_000


class Reader:
    def __init__(self, path_maps=()):
        self.path_maps = tuple(path_maps)
        self.issues = []

    def issue(self, path, code, detail):
        self.issues.append({"path": str(path), "code": code, "detail": detail})

    def read(self, path, kind, required=True):
        if not path.exists() and not required:
            return kind()
        try:
            text = path.read_text(encoding="utf-8")
            data = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.issue(path, "unreadable_artifact", str(exc))
            return kind()
        if not isinstance(data, kind):
            self.issue(path, "schema_error", f"expected {kind.__name__}")
            return kind()
        return data

    def linked(self, value, root):
        if not value:
            return None
        path = Path(str(value))
        for before, after in self.path_maps:
            if path.is_relative_to(before):
                path = Path(after) / path.relative_to(before)
                break
        path = path.resolve()
        if not path.is_relative_to(root.resolve()):
            self.issue(path, "outside_input_root", str(root))
            return None
        return path


def request_sections(request):
    messages = request.get("messages")
    if not isinstance(messages, list):
        return None
    sections = []
    for message in messages:
        text = message.get("content", "")
        if not isinstance(text, str):
            continue
        # Tagged role payloads are JSON; never execute or reconstruct artifact code.
        start = text.find("<sb-")
        if start >= 0:
            tag_end = text.find(">", start)
            tag = text[start + 1:tag_end]
            end = text.find(f"</{tag}>", tag_end)
            try:
                payload = json.loads(text[tag_end + 1:end])
            except json.JSONDecodeError:
                sections.append({"section": "unparsed_message", "bytes": len(text.encode())})
                continue
            sections.append({"section": "instruction", "bytes": len(text[:start].encode())})
            for key, value in payload.items():
                sections.append({"section": key, "json_value_bytes": len(json.dumps(value, ensure_ascii=False).encode())})
        else:
            # CodeAct uses a labeled line format. These are bytes, not token estimates.
            for line in text.splitlines(keepends=True):
                label, sep, _ = line.partition(": ")
                sections.append({"section": label if sep and len(label) < 40 else "instruction", "bytes": len(line.encode())})
    return sections


def aggregate(rows, keys, metrics):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key) for key in keys)].append(row)
    return [
        {**dict(zip(keys, identity)), "rows": len(items),
         "success": sum(item["status"] == "success" for item in items),
         "quality_pass": sum(item.get("quality_pass") is True for item in items),
         "metrics": {metric: stats([item.get(metric) for item in items]) for metric in metrics}}
        for identity, items in sorted(groups.items(), key=lambda pair: str(pair[0]))
    ]


def aggregate_request_sections(requests):
    keys = ("cohort", "phase", "order", "lane", "role", "task_id", "section")
    groups = defaultdict(list)
    for request in requests:
        for section in request.get("sections") or ():
            if isinstance(section, dict):
                identity = tuple(request.get(key) for key in keys[:-1]) + (section.get("section"),)
                groups[identity].append(section)
    return [{
        **dict(zip(keys, identity)), "requests": len(items),
        "raw_bytes": stats([item.get("bytes") for item in items]),
        "serialized_json_value_bytes": stats([item.get("json_value_bytes") for item in items]),
    } for identity, items in sorted(groups.items(), key=lambda pair: str(pair[0]))]


def aggregate_request_dispositions(requests):
    keys = ("cohort", "phase", "order", "lane", "role", "finish_reason", "retry_kind")
    groups = defaultdict(list)
    for request in requests:
        groups[tuple(request.get(key) for key in keys)].append(request)
    return [{
        **dict(zip(keys, identity)), "requests": len(items),
        "prompt_tokens": stats([item.get("prompt_tokens") for item in items]),
        "completion_tokens": stats([item.get("completion_tokens") for item in items]),
        "provider_ms": stats([item.get("provider_ms") for item in items]),
    } for identity, items in sorted(groups.items(), key=lambda pair: str(pair[0]))]


def load_cohort(reader, label, root):
    root = root.resolve()
    if (root / "stage2-pilot").is_dir():
        root = root / "stage2-pilot"
    manifest = reader.read(root / "stage2_manifest.json", dict)
    acceptance = reader.read(root / "acceptance.json", dict)
    planned_document = reader.read(root / "planned_slots.json", dict)
    planned = planned_document.get("slots", [])
    if not isinstance(planned, list) or not all(isinstance(slot, dict) for slot in planned):
        reader.issue(root / "planned_slots.json", "schema_error", "slots must be an array of objects")
        planned = []
    recorded_denominator = reader.read(root / "denominator.json", dict)
    raw_path = root / "raw_rows.json"
    if not raw_path.exists() and (root / "rows.jsonl").exists():
        raw_path = root / "rows.jsonl"
    raw = reader.read(raw_path, list)
    warmups = reader.read(root / "warmups.json", list)
    planned_ids = [slot.get("slot_id") for slot in planned if isinstance(slot, dict)]
    observed_ids = [row.get("slot_id") for row in raw if isinstance(row, dict)]
    missing = sorted(set(planned_ids) - set(observed_ids), key=str)
    extra = sorted(set(observed_ids) - set(planned_ids), key=str)
    duplicate = [key for key, count in Counter(observed_ids).items() if count > 1]
    duplicate_planned = [key for key, count in Counter(planned_ids).items() if count > 1]
    if missing or extra or duplicate or duplicate_planned or None in planned_ids + observed_ids:
        reader.issue(raw_path, "denominator_mismatch", {"missing": missing, "extra": extra, "duplicate": duplicate})
    lanes = manifest.get("lanes", [])
    order = "AB" if lanes == ["pure_text_mas", "fixed_structured"] else "BA" if lanes == ["fixed_structured", "pure_text_mas"] else ">".join(lanes)
    rows, requests = [], []
    for phase, items in (("measured", raw), ("warmup", warmups)):
        for index, row in enumerate(items):
            if not isinstance(row, dict):
                reader.issue(raw_path, "schema_error", f"{phase} row {index} not object")
                rows.append({"cohort": label, "root": str(root), "phase": phase, "status": "malformed", "lane": None})
                continue
            family_id = str(row.get("family_id", ""))
            family, _, task = family_id.partition("::")
            identity = {
                "cohort": label, "root": str(root), "phase": phase, "order": order,
                "task_id": row.get("task_id", task), "family": row.get("task_family", family),
                "lane": row.get("lane"), "slot_id": row.get("slot_id", f"warmup:{family_id}:{row.get('lane')}"),
                "pair_id": row.get("pair_id"), "repeat": row.get("repeat"),
                "status": row.get("status"), "quality_pass": row.get("quality", {}).get("passed"),
            }
            if phase == "measured" and row.get("schema_version") != "statebus.stage2_pilot_raw.v2":
                reader.issue(raw_path, "schema_error", f"unknown row schema: {row.get('schema_version')}")
            events = row.get("provider_request_events", [])
            if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
                reader.issue(raw_path, "schema_error", f"{identity['slot_id']}: invalid events")
                events = []
            if row.get("provider_calls") is not None and row["provider_calls"] != len(events):
                reader.issue(raw_path, "provider_count_mismatch", identity["slot_id"])
            report_path = reader.linked(row.get("report_path"), root)
            report = reader.read(report_path, dict) if report_path else {}
            audits = {}
            audit_path = next((path for value in row.get("provider_evidence_paths", [])
                               if (path := reader.linked(value, root)) is not None and path.name == "rendered_request_audit.json"), None)
            if audit_path:
                audits = reader.read(audit_path, dict)
            role_indexes = Counter()
            for event in events:
                role = event.get("role")
                position = role_indexes[role]
                role_indexes[role] += 1
                rendered = audits.get(role, {}).get("requests", [])
                request = rendered[position] if position < len(rendered) else {}
                prompt_bytes = request.get("prompt_bytes")
                if prompt_bytes is None and sum(e.get("role") == role for e in events) == 1:
                    prompt_bytes = report.get("role_usage", {}).get(role, {}).get("prompt_bytes")
                entry = {**identity, "role": role, "request_id": event.get("request_id"),
                         "request_status": event.get("status"), "finish_reason": event.get("finish_reason"),
                         "attempt": event.get("attempt"), "retry_kind": event.get("retry_kind"),
                         "role_request_index": position + 1,
                         "codeact_repair_prompt": any("<sb-current-python-source>" in message.get("content", "")
                                                      for message in request["messages"]) if isinstance(request.get("messages"), list) else None,
                         "prompt_bytes": prompt_bytes, "provider_ms": interval_union([event]),
                         "sections": request_sections(request), "response_schema": request.get("response_schema"),
                         "response_schema_bytes": len(json.dumps(request["response_schema"], ensure_ascii=False, sort_keys=True).encode("utf-8")) if isinstance(request.get("response_schema"), dict) else None,
                         "response_schema_sha256": request.get("response_schema_sha256")}
                for metric in TOKENS:
                    entry[metric] = event.get(f"response_{metric}")
                    if not finite(entry[metric]):
                        reader.issue(raw_path, "missing_or_invalid_metric", f"{entry['slot_id']}:{role}:{metric}")
                if entry["provider_ms"] is None or entry["finish_reason"] is None:
                    reader.issue(raw_path, "missing_provider_metadata", f"{entry['slot_id']}:{role}")
                requests.append(entry)
            request_ids = [event.get("request_id") for event in events]
            if len(set(request_ids)) != len(request_ids):
                reader.issue(raw_path, "duplicate_request", identity["slot_id"])
            usage = {metric: sum(event[f"response_{metric}"] for event in events)
                     if events and all(finite(event.get(f"response_{metric}")) for event in events) else None for metric in TOKENS}
            for metric, value in usage.items():
                row_value = row.get("provider_usage", {}).get(metric)
                if row_value is not None and row_value != value:
                    reader.issue(raw_path, "usage_mismatch", f"{identity['slot_id']}:{metric}")
            elapsed = row.get("e2e_latency_ms")
            if phase == "warmup":
                elapsed = interval_union([{"start_ns": row.get("started_at_ns"), "end_ns": row.get("ended_at_ns")}])
            rows.append({**identity, **usage, "e2e_ms": elapsed, "provider_union_ms": interval_union(events),
                         "provider_calls": len(events), "retry_count": row.get("retry_count"),
                         "additional_role_requests": sum(max(0, count - 1) for count in role_indexes.values()),
                         "failure": row.get("failure", row.get("error")), "gates": row.get("gates"),
                         "provenance_diagnostic": row.get("provenance_diagnostic"),
                         "embedding_ms": row.get("embedding_latency_ms"), "wire_bytes": None,
                         "runtime_exclusive_ms": None})
    denominator = {
        "cohort": label, "root": str(root), "order": order, "planned": len(planned),
        "recorded": len(raw), "attempted": sum(isinstance(row, dict) and row.get("lifecycle_state") != "not_started" for row in raw),
        "success": sum(isinstance(row, dict) and row.get("status") == "success" for row in raw),
        "non_success_recorded": sum(not isinstance(row, dict) or row.get("status") != "success" for row in raw),
        "status_counts": dict(Counter(row.get("status", "unknown") if isinstance(row, dict) else "malformed" for row in raw)),
        "missing": missing, "extra": extra, "duplicate": duplicate, "warmups": len(warmups),
        "warmup_success": sum(isinstance(row, dict) and row.get("status") == "success" for row in warmups),
        "arithmetic_closed": bool(planned) and not (missing or extra or duplicate or duplicate_planned) and None not in planned_ids + observed_ids and len(raw) == len(planned),
        "recorded_denominator": recorded_denominator, "acceptance": acceptance,
        "manifest": manifest,
    }
    return denominator, rows, requests


def lane_comparisons(groups, identity_keys):
    grouped = defaultdict(dict)
    for group in groups:
        grouped[tuple(group[key] for key in identity_keys)][group["lane"]] = group
    comparisons = []
    for identity, lanes in grouped.items():
        pure, fixed = lanes.get("pure_text_mas"), lanes.get("fixed_structured")
        if pure is None or fixed is None:
            continue
        metrics = {}
        for key in pure["metrics"]:
            a, b = pure["metrics"][key], fixed["metrics"][key]
            complete = a["status"] == b["status"] == "observed"
            metrics[key] = {
                "pure_mean": a["mean"], "fixed_mean": b["mean"],
                "fixed_minus_pure": b["mean"] - a["mean"] if complete else None,
                "fixed_over_pure": b["mean"] / a["mean"] if complete and a["mean"] else None,
                "coverage_complete": complete,
            }
        comparisons.append({**dict(zip(identity_keys, identity)), "pure_rows": pure["rows"],
                            "fixed_rows": fixed["rows"], "metrics": metrics})
    return comparisons


def summarize(cohorts, output, path_maps=(), memory_root=None, semantic_summary=None, carrier_root=None,
              preflight_roots=(), embedding_probes=()):
    output = Path(output).resolve()
    inputs = [Path(root).resolve() for _, root in cohorts]
    inputs += [Path(root).resolve() for root in (memory_root, carrier_root) if root]
    inputs += [Path(semantic_summary).resolve().parent] if semantic_summary else []
    inputs += [Path(root).resolve() for root in preflight_roots]
    inputs += [Path(path).resolve() for path in embedding_probes]
    if any(output == root or output.is_relative_to(root) for root in inputs):
        raise ValueError("output_must_be_outside_input_roots")
    cohort_roots = [Path(root).resolve() for _, root in cohorts]
    if len(set(cohort_roots)) != len(cohort_roots):
        raise ValueError("duplicate_input_root")
    output.mkdir(parents=True, exist_ok=False)
    reader = Reader(path_maps)
    denominators, rows, requests = [], [], []
    seen = set()
    for label, root in cohorts:
        identity = Path(root).resolve()
        if identity in seen:
            raise ValueError(f"duplicate_input_root:{identity}")
        seen.add(identity)
        denominator, part_rows, part_requests = load_cohort(reader, label, identity)
        denominators.append(denominator)
        rows.extend(part_rows)
        requests.extend(part_requests)
    mechanisms = {}
    preflight_failures = [{"root": str(root), "error": reader.read(Path(root) / "preflight_error.json", dict),
                           "preflight": reader.read(Path(root) / "preflight.json", dict)} for root in preflight_roots]
    if embedding_probes:
        mechanisms["embedding_probes"] = [{"source": str(path), **reader.read(Path(path), dict)} for path in embedding_probes]
    if memory_root:
        root = Path(memory_root)
        memory_rows = reader.read(root / "rows.json", list)
        mechanisms["memory"] = {"source": str(root), "rows": memory_rows,
            "manifest": reader.read(root / "manifest.json", dict),
            "acceptance": reader.read(root / "acceptance.json", dict),
            "denominator": reader.read(root / "denominator.json", dict),
            "reported_receipt_metrics": reader.read(root / "metrics.json", dict),
            "negative_controls": reader.read(root / "negative_controls.json", list),
            "by_variant": {variant: {
                "rows": len(items), "terminal_counts": dict(Counter(row.get("terminal_status") for row in items)),
                **{field: stats([row.get(field) for row in items]) for field in ("runtime_elapsed_ms", "provider_boundary_call_count", "skipped_generation_step_count")},
                "query_observed": sum(isinstance(row.get("query"), dict) for row in items),
                "provider_kinds": dict(Counter(row.get("provider_invocation_evidence", {}).get("provider_kind", "not_started_or_unsupported") for row in items)),
                "quality_pass": sum(row.get("quality_evidence", {}).get("passed") is True for row in items),
                "funnel": {field: dict(Counter(str(row.get(field)) for row in items)) for field in ("candidate", "compatible", "policy_approved", "actual_use", "behavioral_effect", "validated_replay")},
            } for variant in sorted({row["variant"] for row in memory_rows})
              for items in [[row for row in memory_rows if row["variant"] == variant]]}}
    if semantic_summary:
        mechanisms["semantic"] = reader.read(Path(semantic_summary), dict)
    if carrier_root:
        root = Path(carrier_root)
        mechanisms["carrier"] = {"source": str(root), "rows": reader.read(root / "rows.json", list),
                                 "acceptance": reader.read(root / "acceptance.json", dict),
                                 "denominator": reader.read(root / "denominator.json", dict)}
    metrics = (*TOKENS, "e2e_ms", "provider_union_ms", "provider_calls", "retry_count", "additional_role_requests", "embedding_ms", "wire_bytes", "runtime_exclusive_ms")
    summary = {
        "schema_version": "statebus.contest_performance.v1",
        "claim_scope": "descriptive_cohorts_no_causal_or_statistical_superiority",
        "denominators": denominators,
        "by_lane": aggregate(rows, ("cohort", "phase", "lane"), metrics),
        "by_case": aggregate(rows, ("cohort", "phase", "task_id", "lane"), metrics),
        "by_family": aggregate(rows, ("cohort", "phase", "family", "lane"), metrics),
        "by_order": aggregate(rows, ("cohort", "phase", "order", "lane"), metrics),
        "by_role": aggregate(requests, ("cohort", "phase", "lane", "role"), (*TOKENS, "prompt_bytes", "provider_ms")),
        "by_case_role": aggregate(requests, ("cohort", "phase", "task_id", "lane", "role"), (*TOKENS, "prompt_bytes", "provider_ms")),
        "by_order_role": aggregate(requests, ("cohort", "phase", "order", "lane", "role"), (*TOKENS, "prompt_bytes", "provider_ms")),
        "by_order_case_role": aggregate(requests, ("cohort", "phase", "order", "task_id", "lane", "role"), (*TOKENS, "prompt_bytes", "provider_ms")),
        "by_request_sections": aggregate_request_sections(requests),
        "by_request_disposition": aggregate_request_dispositions(requests),
        "finish_reasons": dict(Counter(str(row["finish_reason"]) for row in requests)),
        "issues": reader.issues, "mechanisms": mechanisms,
        "preflight_failures": preflight_failures,
        "rows": rows, "requests": requests,
        "missing_fields": dict(Counter(field for row in requests for field in
                                        ("prompt_bytes", "sections", "response_schema", "response_schema_bytes", "response_schema_sha256")
                                        if row[field] is None)),
    }
    summary["lane_comparisons"] = lane_comparisons(summary["by_lane"], ("cohort", "phase"))
    summary["case_comparisons"] = lane_comparisons(summary["by_case"], ("cohort", "phase", "task_id"))
    summary["role_comparisons"] = lane_comparisons(summary["by_role"], ("cohort", "phase", "role"))
    lines = ["# Contest Performance Audit", "", "Descriptive only. Cohorts remain separate; warmups and failures are retained.", "",
             "## Denominators", "", "| Cohort | Order | Measured success/planned | Recorded | Warmup success/recorded | Closed |", "|---|---|---:|---:|---:|---|"]
    for item in denominators:
        lines.append(f"| {item['cohort']} | {item['order']} | {item['success']}/{item['planned']} | {item['recorded']} | {item['warmup_success']}/{item['warmups']} | {item['arithmetic_closed']} |")
    for title, name, columns in (("Lane Means", "by_lane", ("e2e_ms", "provider_union_ms", *TOKENS)),
                                  ("Case Means", "by_case", ("e2e_ms", *TOKENS)),
                                  ("Role Means", "by_role", ("prompt_bytes", *TOKENS, "provider_ms"))):
        labels = ("cohort", "phase", "lane") + (("role",) if name == "by_role" else ("task_id",) if name == "by_case" else ())
        lines += ["", f"## {title}", "", "| " + " | ".join((*labels, "n", "success", "quality_pass", *columns)) + " |",
                  "|" + "---|" * (len(labels) + 3 + len(columns))]
        for item in summary[name]:
            values = [str(item[key]) for key in labels] + [str(item["rows"]), str(item["success"]), str(item["quality_pass"])]
            values += ["unsupported" if item["metrics"][key]["mean"] is None else f"{item['metrics'][key]['mean']:.2f} (n={item['metrics'][key]['n']})" for key in columns]
            lines.append("| " + " | ".join(values) + " |")
    lines += ["", "## Fixed/Pure Descriptive Ratios", "", "| Cohort | Phase | Pure n | Fixed n | E2E | Prompt | Completion | Total | Calls | Extra role requests |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in summary["lane_comparisons"]:
        ratios = [item["metrics"][key]["fixed_over_pure"] for key in ("e2e_ms", *TOKENS, "provider_calls", "additional_role_requests")]
        values = ["unsupported" if value is None else f"{value:.3f}" for value in ratios]
        lines.append(f"| {item['cohort']} | {item['phase']} | {item['pure_rows']} | {item['fixed_rows']} | " + " | ".join(values) + " |")
    lines += ["", "## Role Request Disposition", "", "| Cohort | Phase | Order | Lane | Role | Finish | Retry kind | Requests | Prompt | Completion | Provider ms |",
              "|---|---|---|---|---|---|---|---:|---:|---:|---:|"]
    for item in summary["by_request_disposition"]:
        fields = ("cohort", "phase", "order", "lane", "role", "finish_reason", "retry_kind", "requests")
        values = [str(item.get(key)) for key in fields]
        values += ["unsupported" if item[metric]["mean"] is None else f"{item[metric]['mean']:.2f}" for metric in ("prompt_tokens", "completion_tokens", "provider_ms")]
        lines.append("| " + " | ".join(values) + " |")
    lines += ["", "## Rendered Request Sections", "", "Raw section bytes and serialized JSON-value bytes remain separate metrics.", "",
              "| Cohort | Phase | Order | Lane | Task | Role | Section | Requests | Raw bytes | JSON value bytes |",
              "|---|---|---|---|---|---|---|---:|---:|---:|"]
    for item in summary["by_request_sections"]:
        fields = ("cohort", "phase", "order", "lane", "task_id", "role", "section", "requests")
        values = [str(item.get(key)) for key in fields]
        values += [str(item[field]["sum"]) if item[field]["sum"] is not None else "unsupported" for field in ("raw_bytes", "serialized_json_value_bytes")]
        lines.append("| " + " | ".join(values) + " |")
    if "memory" in mechanisms:
        lines += ["", "## Historical Memory Receipts", "", "Deterministic provider-boundary evidence, not Qwen inference savings.", "",
                  "| Variant | Rows | Quality pass | Query | Candidate | Compatible | Approved | Actual use | Generation skipped | Total ms | Mean ms |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for variant, item in mechanisms["memory"]["by_variant"].items():
            funnel = [item["funnel"][key].get("True", 0) for key in ("candidate", "compatible", "policy_approved", "actual_use")]
            values = [item["rows"], item["quality_pass"], item["query_observed"], *funnel, item["skipped_generation_step_count"]["sum"],
                      item["runtime_elapsed_ms"]["sum"], item["runtime_elapsed_ms"]["mean"]]
            lines.append("| " + " | ".join([variant, *map(str, values)]) + " |")
        timing = mechanisms["memory"]["reported_receipt_metrics"].get("timing_accounting", {})
        lines += ["", "Recorded producer-inclusive timing: `" + json.dumps(timing, sort_keys=True) + "`."]
    if "semantic" in mechanisms:
        lines += ["", "## Historical Semantic State", "", "Eligible and inactive cases remain separate; not a full-system latency claim.", "",
                  "| Case | Variant | Quality | Actual use | Effect | Publish | Transfer | Consume | Provider calls | Release closed |",
                  "|---|---|---|---|---|---:|---:|---:|---:|---|"]
        for item in mechanisms["semantic"].get("rows", []):
            fields = ("task_id", "variant", "quality_pass", "actual_use", "behavioral_effect", "semantic_publish_count",
                      "semantic_transfer_count", "semantic_consume_count", "provider_call_count", "state_release_reclaim_closed")
            lines.append("| " + " | ".join(str(item.get(key, "unsupported")) for key in fields) + " |")
    if "embedding_probes" in mechanisms:
        lines += ["", "## Isolated Embedding Probes", "", "Separate fresh processes; not a measured campaign cost.", "",
                  "| Source | Device | Model loads | Encodes | Shared object | Operations (ms) |",
                  "|---|---|---:|---:|---|---|"]
        for item in mechanisms["embedding_probes"]:
            operations = "; ".join(f"{op['name']}={op['duration_ms']:.3f}" for op in item["operations"])
            lines.append(f"| {item['source']} | {item['device']} | {item['model_load_count']} | {item['encode_count']} | {item['shared_model_object']} | {operations} |")
    if preflight_failures:
        lines += ["", "## Preflight Failures", "", "These attempts did not enter the measured slot denominator."]
        lines += [f"- `{item['root']}`: `{json.dumps(item['error'], sort_keys=True)}`" for item in preflight_failures]
    lines += ["", "## Evidence Limits", "", "- Provider time uses interval union; missing intervals remain null.",
              "- Provider retry_count does not include all model-level repairs; additional_role_requests and captured CodeAct repair prompts remain separate.",
              "- Means include recorded failures when their metrics are observed; partial coverage reports n.",
              "- Section sizes are UTF-8/JSON bytes, not additive tokenizer estimates.",
              "- Wire bytes, Runtime-exclusive spans and embedding time stay unsupported unless directly observed.",
              "- Mechanism receipt summaries are retained separately, never pooled into full-system rows.",
              f"- Missing request metadata: `{summary['missing_fields']}`.", f"- Schema/accounting issues: {len(reader.issues)}."]
    lines += [f"- `{issue['code']}` {issue['path']}: {issue['detail']}" for issue in reader.issues]
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    failures = [row for row in rows if row.get("status") != "success"]
    (output / "failure_summary.json").write_text(json.dumps({"rows": failures, "preflight_failures": preflight_failures, "issues": reader.issues}, ensure_ascii=False, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", action="append", required=True, metavar="LABEL=ROOT")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--path-map", action="append", default=[], metavar="CONTAINER=HOST")
    parser.add_argument("--memory-root", type=Path)
    parser.add_argument("--semantic-summary", type=Path)
    parser.add_argument("--carrier-root", type=Path)
    parser.add_argument("--preflight-root", type=Path, action="append", default=[])
    parser.add_argument("--embedding-probe", type=Path, action="append", default=[])
    args = parser.parse_args()
    for value in args.cohort + args.path_map:
        if "=" not in value:
            parser.error(f"expected KEY=VALUE: {value}")
    result = summarize([value.split("=", 1) for value in args.cohort], args.output_root,
                       [value.split("=", 1) for value in args.path_map], args.memory_root, args.semantic_summary, args.carrier_root,
                       args.preflight_root, args.embedding_probe)
    print(json.dumps({"output": str(args.output_root), "rows": len(result["rows"]), "issues": len(result["issues"])}))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
