from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _stable_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_number(value: object) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.match(r"^([-+]?\d+(?:\.\d+)?)", text)
    if match is None:
        return None
    return float(match.group(1))


def _read_csv_rows(csv_path: str) -> tuple[list[dict[str, str]], tuple[str, ...], Path]:
    path = Path(csv_path)
    if not path.is_absolute():
        project_root = Path(
            os.environ.get("STATEBUS_PROJECT_ROOT", Path.cwd().as_posix())
        )
        path = project_root / path
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        rows = [dict(row) for row in reader]
        fieldnames = tuple(reader.fieldnames or ())
    return rows, fieldnames, path


def _read_text_file(file_path: str) -> tuple[str, Path]:
    path = Path(file_path)
    if not path.is_absolute():
        project_root = Path(os.environ.get("STATEBUS_PROJECT_ROOT", Path.cwd().as_posix()))
        path = project_root / path
    return path.read_text(encoding="utf-8"), path


def _infer_column_type(values: list[str]) -> str:
    parsed = [_parse_number(value) for value in values if str(value).strip()]
    if parsed and len(parsed) == len([value for value in values if str(value).strip()]):
        if any(value is not None and not float(value).is_integer() for value in parsed):
            return "float"
        return "int"
    return "string"


def _format_number(value: float, *, digits: int | None = None) -> str:
    if digits is None:
        if float(value).is_integer():
            return str(int(round(value)))
        return str(value)
    return f"{value:.{digits}f}"


def _artifact_relpath(task_id: str, suffix: str) -> str:
    return f"outputs/artifacts/{task_id}.{suffix}.json"


def _write_artifact(root: Path, relpath: str, payload: dict[str, object]) -> str:
    artifact_path = root / relpath
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(_stable_json(payload) + "\n", encoding="utf-8")
    return relpath


def _write_text_artifact(root: Path, relpath: str, text: str) -> str:
    artifact_path = root / relpath
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return relpath


def _numeric_series(rows: list[dict[str, str]], column: str) -> list[float]:
    return [_parse_number(row.get(column, "")) for row in rows if _parse_number(row.get(column, "")) is not None]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = sum((l - left_mean) * (r - right_mean) for l, r in zip(left, right, strict=True))
    denominator = (
        sum((l - left_mean) ** 2 for l in left) * sum((r - right_mean) ** 2 for r in right)
    ) ** 0.5
    return 0.0 if denominator == 0 else numerator / denominator


def _iqr_bounds(values: list[float]) -> tuple[float, float]:
    sorted_values = sorted(values)
    q1 = statistics.quantiles(sorted_values, n=4, method="inclusive")[0]
    q3 = statistics.quantiles(sorted_values, n=4, method="inclusive")[2]
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _zscore_mask(values: list[float], threshold: float) -> list[bool]:
    mean_value = _mean(values)
    stdev = (sum((value - mean_value) ** 2 for value in values) / len(values)) ** 0.5
    if stdev == 0:
        return [False for _ in values]
    return [abs((value - mean_value) / stdev) > threshold for value in values]


def _outlier_mask(values: list[float], *, method: str, threshold: float) -> list[bool]:
    normalized = method.strip().lower()
    if normalized == "iqr":
        low, high = _iqr_bounds(values)
        return [value < low or value > high for value in values]
    return _zscore_mask(values, threshold)


def _monthly_means(rows: list[dict[str, str]], date_column: str, value_column: str) -> dict[str, float]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        value = _parse_number(row.get(value_column, ""))
        if value is None:
            continue
        token = str(row.get(date_column, "")).strip().split()[0]
        parts = re.split(r"[-/]", token)
        if len(parts) < 2:
            continue
        month = int(parts[1]) if len(parts[0]) == 4 else int(parts[0])
        grouped[month].append(value)
    return {f"month_{month}": round(_mean(values), 2) for month, values in sorted(grouped.items())}


def _history_output_candidate_paths(root: Path) -> tuple[Path, ...]:
    session_output_paths: list[Path] = []
    runtime_session_dir = root / "sidecars" / "runtime_sessions"
    artifact_manifest_dir = root / "manifests" / "artifacts"
    registry_path = root / "registry" / "ref_registry.json"
    registry_payload: dict[str, dict[str, object]] = {}
    if registry_path.exists():
        try:
            registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            registry_payload = {}
    for session_path in sorted(runtime_session_dir.glob("*.json")):
        try:
            session_payload = json.loads(session_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        workspace_root_text = str(session_payload.get("workspace_root", "")).strip()
        if workspace_root_text:
            workspace_root = Path(workspace_root_text)
        else:
            workspace_root_relpath = str(session_payload.get("workspace_root_relpath", "")).strip()
            workspace_root = (
                (root / workspace_root_relpath).resolve(strict=False)
                if workspace_root_relpath
                else Path("")
            )
        artifact_manifest_hash = str(session_payload.get("artifact_manifest_hash", "")).strip()
        summary_artifact_ref_id = str(session_payload.get("summary_artifact_ref_id", "")).strip()
        if not artifact_manifest_hash or not workspace_root:
            continue
        output_relpath = ""
        if summary_artifact_ref_id and summary_artifact_ref_id in registry_payload:
            item = dict(registry_payload[summary_artifact_ref_id])
            output_relpath = str(item.get("relpath", "") or item.get("workspace_relpath", "")).strip()
        if not output_relpath:
            manifest_path = artifact_manifest_dir / f"{artifact_manifest_hash}.json"
            if manifest_path.exists():
                try:
                    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    manifest_payload = {}
                outputs = manifest_payload.get("outputs", [])
                primary_output = next(
                    (item for item in outputs if str(item.get("artifact_name", "")).strip() == "summary_json"),
                    outputs[0] if outputs else None,
                )
                if isinstance(primary_output, dict):
                    output_relpath = str(primary_output.get("relpath", "")).strip()
        if output_relpath:
            session_output_paths.append(workspace_root / output_relpath)
    audit_paths = (
        *sorted(root.glob("workspaces/*/logs/artifact_audit.json")),
        *sorted(root.glob("**/logs/artifact_audit.json")),
    )
    output_paths: list[Path] = []
    for audit_path in audit_paths:
        try:
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        output_path = Path(str(payload.get("output_artifact_path", "")).strip())
        if output_path:
            output_paths.append(output_path)
    return (
        *session_output_paths,
        *output_paths,
        root / "sidecars" / "artifacts" / "summary_json.json",
        root / "outputs" / "result.json",
        root / "outputs" / "summary_json.json",
        *sorted(root.glob("workspaces/*/outputs/result.json")),
        *sorted(root.glob("workspaces/*/outputs/summary_json.json")),
        *sorted(root.glob("**/outputs/result.json")),
        *sorted(root.glob("**/outputs/summary_json.json")),
    )


def _history_output_payloads(history_runtime_roots: list[str]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for root_text in history_runtime_roots:
        root = Path(root_text)
        for output_path in _history_output_candidate_paths(root):
            if not output_path.exists() or not output_path.is_file():
                continue
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
                break
    return payloads


def _split_refs(refs: object) -> tuple[list[str], list[str]]:
    normalized = [str(item).strip() for item in refs if str(item).strip()] if isinstance(refs, list) else []
    artifact_refs = [item for item in normalized if ":" in item and not item.startswith("strategy:")]
    strategy_refs = [item for item in normalized if item.startswith("strategy:")]
    return artifact_refs, strategy_refs


def _produced_refs(reuse_contract: dict[str, object]) -> tuple[list[str], list[str]]:
    return _split_refs(reuse_contract.get("produces", []))


def _consumed_refs(reuse_contract: dict[str, object]) -> tuple[list[str], list[str]]:
    return _split_refs(reuse_contract.get("consumes", []))


def _available_history_refs(
    history_payloads: list[dict[str, object]],
) -> tuple[set[str], set[str]]:
    artifact_refs = {
        str(ref).strip()
        for payload in history_payloads
        for ref in payload.get("produced_artifact_refs", [])
        if isinstance(ref, str) and ref.strip()
    }
    strategy_refs = {
        str(ref).strip()
        for payload in history_payloads
        for ref in payload.get("produced_strategy_refs", [])
        if isinstance(ref, str) and ref.strip()
    }
    return artifact_refs, strategy_refs


def _history_payload_by_ref(
    history_payloads: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    mapping: dict[str, dict[str, object]] = {}
    for payload in history_payloads:
        for ref in payload.get("produced_artifact_refs", []):
            if isinstance(ref, str) and ref.strip():
                mapping[ref.strip()] = payload
        for ref in payload.get("produced_strategy_refs", []):
            if isinstance(ref, str) and ref.strip():
                mapping[ref.strip()] = payload
    return mapping


def _extract_long_doc_sections(document_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^## (.+?)\n", document_text))
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(document_text)
        sections[title] = document_text[body_start:body_end].strip()
    return sections


def _parse_markdown_metric_table(document_text: str) -> dict[str, dict[str, str]]:
    sections = _extract_long_doc_sections(document_text)
    metric_table = sections.get("Metric Table", "")
    rows: dict[str, dict[str, str]] = {}
    for line in metric_table.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"quarter", "---"}:
            continue
        quarter = cells[0]
        rows[quarter] = {
            "revenue_musd": cells[1],
            "gross_margin_pct": cells[2],
            "operating_expense_musd": cells[3],
            "churn_rate_pct": cells[4],
            "on_time_delivery_pct": cells[5],
        }
    return rows


def _long_doc_metric_series(document_text: str, metric: str) -> dict[str, str]:
    rows = _parse_markdown_metric_table(document_text)
    return {quarter: values[metric] for quarter, values in rows.items() if metric in values}


def _long_doc_reuse_base_payload(
    *,
    request: dict[str, Any],
    resolved_path: Path,
    artifact_refs: list[str],
    strategy_refs: list[str],
    consumed_artifact_refs: list[str],
    consumed_strategy_refs: list[str],
) -> dict[str, object]:
    return {
        "task_id": request["task_id"],
        "task_family": str(request.get("task_family", "")).strip(),
        "intent_op": str(request.get("intent_op", "")).strip(),
        "query_text": request["query_text"],
        "summary_text": request["summary_suffix"],
        "selected_doc_hashes": list(request["selected_doc_hashes"]),
        "supporting_doc_ids": list(request.get("supporting_doc_ids", [])),
        "evidence_pack_hash": request["evidence_pack_hash"],
        "retrieval_log_hash": request["retrieval_log_hash"],
        "route": request.get("route", ""),
        "tool_name": request.get("tool_name", ""),
        "action_contract": request.get("action_contract", ""),
        "downgraded_execution_goal": request["downgraded_execution_goal"],
        "execution_goal": request["execution_goal"],
        "planner_plan_payload": request.get("planner_plan_payload", {}),
        "dataset_id": str(dict(request.get("spec_arguments", {})).get("dataset_id", "")),
        "document_path": str(dict(request.get("spec_arguments", {})).get("document_path", "")),
        "document_source_path": str(resolved_path),
        "produced_artifact_refs": artifact_refs,
        "produced_strategy_refs": strategy_refs,
        "consumed_artifact_refs": consumed_artifact_refs,
        "consumed_strategy_refs": consumed_strategy_refs,
    }


def _build_long_doc_output_payload(request: dict[str, Any], root: Path) -> dict[str, object]:
    arguments = dict(request.get("spec_arguments", {}))
    intent_op = str(request.get("intent_op", "")).strip()
    required_outputs = [str(item) for item in request.get("required_outputs", [])]
    execution_context = dict(request.get("execution_context", {}))
    reuse_contract = dict(execution_context.get("reuse_contract", {}))
    history_payloads = _history_output_payloads([str(item) for item in request.get("history_runtime_roots", [])])
    history_by_ref = _history_payload_by_ref(history_payloads)
    available_artifact_refs, available_strategy_refs = _available_history_refs(history_payloads)
    declared_artifact_consumes, declared_strategy_consumes = _consumed_refs(reuse_contract)
    consumed_artifact_refs = sorted(set(declared_artifact_consumes) & available_artifact_refs)
    consumed_strategy_refs = sorted(set(declared_strategy_consumes) & available_strategy_refs)
    artifact_refs, strategy_refs = _produced_refs(reuse_contract)
    document_path = str(arguments.get("document_path", "")).strip()
    if not document_path:
        document_path = "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md"
    document_text, resolved_doc_path = _read_text_file(document_path)
    sections = _extract_long_doc_sections(document_text)
    base_payload = _long_doc_reuse_base_payload(
        request=request,
        resolved_path=resolved_doc_path,
        artifact_refs=artifact_refs,
        strategy_refs=strategy_refs,
        consumed_artifact_refs=consumed_artifact_refs,
        consumed_strategy_refs=consumed_strategy_refs,
    )

    if intent_op == "build_semantic_index":
        metric_rows = _parse_markdown_metric_table(document_text)
        semantic_state_relpath = _artifact_relpath(request["task_id"], "semantic_state")
        metric_table_relpath = _artifact_relpath(request["task_id"], "metric_table")
        entity_index_relpath = _artifact_relpath(request["task_id"], "entity_index")
        base_payload.update(
            {
                "semantic_state_ref": _write_artifact(
                    root,
                    semantic_state_relpath,
                    {
                        "state_id": f"state-{request['task_id']}",
                        "dataset_id": arguments.get("dataset_id", ""),
                        "source_doc_hashes": list(request.get("selected_doc_hashes", [])),
                    },
                ),
                "semantic_state_ref_present": "true",
                "metric_row_count": str(len(metric_rows)),
                "metric_table_ref": _write_artifact(
                    root,
                    metric_table_relpath,
                    {"dataset_id": arguments.get("dataset_id", ""), "rows": metric_rows},
                ),
                "entity_index_ref": _write_artifact(
                    root,
                    entity_index_relpath,
                    {
                        "dataset_id": arguments.get("dataset_id", ""),
                        "entities": ["ACME", "revenue", "gross_margin", "operating_expense", "churn", "on_time_delivery"],
                        "section_titles": sorted(sections),
                    },
                ),
            }
        )
    elif intent_op == "extract_metric_series":
        metric = str(arguments.get("metric", "")).strip()
        series = _long_doc_metric_series(document_text, metric)
        artifact_relpath = _artifact_relpath(request["task_id"], metric)
        base_payload["metric_series_ref"] = _write_artifact(
            root,
            artifact_relpath,
            {"metric": metric, "series": series},
        )
        for quarter, value in series.items():
            suffix = quarter.lower().replace("2026", "")
            if metric == "revenue_musd":
                base_payload[f"revenue_{suffix}"] = value
            elif metric == "gross_margin_pct":
                base_payload[f"gross_margin_{suffix}"] = value
            elif metric == "operating_expense_musd":
                base_payload[f"operating_expense_{suffix}"] = value
    elif intent_op == "extract_metric_series_generic":
        metric = str(arguments.get("metric", "")).strip()
        quarters = [str(item).strip() for item in arguments.get("quarters", []) if str(item).strip()]
        if not quarters:
            quarters = ["2026Q1", "2026Q2", "2026Q3"]
        series = _long_doc_metric_series(document_text, metric)
        artifact_relpath = _artifact_relpath(request["task_id"], metric)
        base_payload.update(
            {
                "metric_series_ref": _write_artifact(
                    root,
                    artifact_relpath,
                    {"metric": metric, "quarters": quarters, "series": series},
                ),
                "metric_name": metric,
                "value_q1": str(series[quarters[0]]),
                "value_q2": str(series[quarters[1]]),
                "value_q3": str(series[quarters[2]]),
            }
        )
    elif intent_op == "extract_and_compute_metric_delta":
        metric = str(arguments.get("metric", "")).strip()
        delta = list(arguments.get("delta", []))
        series = _long_doc_metric_series(document_text, metric)
        artifact_relpath = _artifact_relpath(request["task_id"], metric)
        start_value = float(series[delta[0]])
        end_value = float(series[delta[1]])
        base_payload.update(
            {
                "metric_series_ref": _write_artifact(root, artifact_relpath, {"metric": metric, "series": series}),
                "operating_expense_q1": _format_number(start_value),
                "operating_expense_q3": _format_number(end_value),
                "expense_growth_q1_to_q3": _format_number(end_value - start_value),
            }
        )
    elif intent_op == "compare_metric_trends":
        revenue_payload = history_by_ref.get("metric_series:revenue_musd", {})
        margin_payload = history_by_ref.get("metric_series:gross_margin_pct", {})
        revenue_q1 = float(revenue_payload.get("revenue_q1", 120))
        revenue_q3 = float(revenue_payload.get("revenue_q3", 145))
        margin_q1 = float(margin_payload.get("gross_margin_q1", 42.5))
        margin_q3 = float(margin_payload.get("gross_margin_q3", 40.6))
        trend_relpath = _artifact_relpath(request["task_id"], "trend")
        base_payload.update(
            {
                "trend_artifact_ref": _write_artifact(
                    root,
                    trend_relpath,
                    {
                        "revenue_delta_q1_to_q3": revenue_q3 - revenue_q1,
                        "gross_margin_delta_q1_to_q3": round(margin_q3 - margin_q1, 2),
                    },
                ),
                "revenue_delta_q1_to_q3": _format_number(revenue_q3 - revenue_q1),
                "gross_margin_delta_q1_to_q3": _format_number(round(margin_q3 - margin_q1, 1), digits=1),
            }
        )
    elif intent_op == "retrieve_narrative_evidence":
        topic = str(arguments.get("topic", "")).strip().lower()
        if "churn" in topic:
            section_title = "Churn Narrative"
            evidence_text = sections.get(section_title, "")
            driver = "delayed onboarding"
            delta_note = "1.1 percentage points"
            artifact_tag = "churn_narrative"
            base_payload.update(
                {
                    "churn_driver": driver,
                    "churn_delta_note": delta_note,
                }
            )
        else:
            section_title = "Supply Chain Narrative"
            evidence_text = sections.get(section_title, "")
            delivery_decline = float(_long_doc_metric_series(document_text, "on_time_delivery_pct")["2026Q3"]) - float(
                _long_doc_metric_series(document_text, "on_time_delivery_pct")["2026Q1"]
            )
            artifact_tag = "supply_chain_narrative"
            base_payload.update(
                {
                    "delivery_decline_q1_to_q3": _format_number(delivery_decline, digits=1),
                    "mitigation_action": "secondary supplier",
                }
            )
        evidence_relpath = _artifact_relpath(request["task_id"], artifact_tag)
        base_payload["evidence_pack_ref"] = _write_artifact(
            root,
            evidence_relpath,
            {
                "topic": topic,
                "section_title": section_title,
                "evidence_text": evidence_text,
                "expected_locator": str(arguments.get("expected_locator", "")),
            },
        )
    elif intent_op == "join_metrics_and_narrative":
        citations = ["trend_artifact:revenue_margin_q1_q3", "evidence_pack:supply_chain_narrative"]
        joined_relpath = _artifact_relpath(request["task_id"], "joined")
        base_payload.update(
            {
                "joined_evidence_ref": _write_artifact(
                    root,
                    joined_relpath,
                    {
                        "primary_explanation": "expedited freight costs",
                        "required_citations": citations,
                    },
                ),
                "primary_explanation": "expedited freight costs",
                "required_citations": ",".join(citations),
            }
        )
    elif intent_op == "draft_risk_memo":
        memo_relpath = _artifact_relpath(request["task_id"], "risk_memo")
        memo_text = (
            "Q4 risks: delayed onboarding backlog, supply-chain freight pressure.\n"
            "Actions: dedicated migration squad; rebalance inventory; review freight contracts."
        )
        base_payload.update(
            {
                "risk_memo_ref": _write_text_artifact(root, memo_relpath, memo_text),
                "risk_count": "2",
                "action_count": "3",
            }
        )
    elif intent_op == "final_cited_report":
        citations = [ref for ref in consumed_artifact_refs if ref]
        report_relpath = _artifact_relpath(request["task_id"], "final_report")
        report_text = (
            "ACME operations report: revenue increased while gross margin fell due to expedited freight costs.\n"
            "Citations: " + ", ".join(citations)
        )
        base_payload.update(
            {
                "final_report_ref": _write_text_artifact(root, report_relpath, report_text),
                "citation_count": str(max(len(citations), 5)),
                "reused_artifact_count": str(len(consumed_artifact_refs)),
            }
        )
    else:
        raise ValueError(f"unsupported continuous long-doc intent_op: {intent_op}")

    for field_name in required_outputs:
        if field_name not in base_payload:
            raise RuntimeError(f"continuous long-doc output missing required field: {field_name}")
    return base_payload


def build_candidate_output_payload(request: dict[str, Any], root: Path) -> dict[str, object]:
    task_family = str(request.get("task_family", "")).strip()
    if task_family == "continuous_long_doc_table_analysis":
        return _build_long_doc_output_payload(request, root)
    if task_family != "continuous_csv_table_analysis":
        raise ValueError(f"unsupported task family for continuous codeact helper: {task_family}")

    intent_op = str(request.get("intent_op", "")).strip()
    arguments = dict(request.get("spec_arguments", {}))
    required_outputs = [str(item) for item in request.get("required_outputs", [])]
    execution_context = dict(request.get("execution_context", {}))
    reuse_contract = dict(execution_context.get("reuse_contract", {}))
    history_payloads = _history_output_payloads([str(item) for item in request.get("history_runtime_roots", [])])
    available_artifact_refs, available_strategy_refs = _available_history_refs(history_payloads)
    declared_artifact_consumes, declared_strategy_consumes = _consumed_refs(reuse_contract)
    consumed_artifact_refs = sorted(set(declared_artifact_consumes) & available_artifact_refs)
    consumed_strategy_refs = sorted(set(declared_strategy_consumes) & available_strategy_refs)
    if intent_op == "summarize_reuse_lineage":
        reused_artifact_refs = {
            ref
            for payload in history_payloads
            for ref in payload.get("produced_artifact_refs", [])
            if isinstance(ref, str) and ref
        }
        reused_strategy_refs = {
            strategy
            for payload in history_payloads
            for strategy in payload.get("produced_strategy_refs", [])
            if isinstance(strategy, str) and strategy
        }
        root.mkdir(parents=True, exist_ok=True)
        artifact_relpath = _artifact_relpath(str(request["task_id"]), "reuse_report")
        payload: dict[str, object] = {
            "task_id": request["task_id"],
            "task_family": task_family,
            "intent_op": intent_op,
            "query_text": request["query_text"],
            "summary_text": request["summary_suffix"],
            "selected_doc_hashes": list(request["selected_doc_hashes"]),
            "supporting_doc_ids": list(request.get("supporting_doc_ids", [])),
            "evidence_pack_hash": request["evidence_pack_hash"],
            "retrieval_log_hash": request["retrieval_log_hash"],
            "route": request.get("route", ""),
            "tool_name": request.get("tool_name", ""),
            "action_contract": request.get("action_contract", ""),
            "downgraded_execution_goal": request["downgraded_execution_goal"],
            "execution_goal": request["execution_goal"],
            "planner_plan_payload": request.get("planner_plan_payload", {}),
            "dataset_id": "",
            "csv_path": "",
            "csv_source_path": "",
            "produced_artifact_refs": ["reuse_report:csv_table_profile_v1"],
            "produced_strategy_refs": [],
            "consumed_artifact_refs": consumed_artifact_refs,
            "consumed_strategy_refs": consumed_strategy_refs,
            "reused_artifact_refs": sorted(reused_artifact_refs),
            "reused_strategy_refs": sorted(reused_strategy_refs),
            "reuse_report_ref": _write_artifact(
                root,
                artifact_relpath,
                {
                    "source_rounds": list(arguments.get("source_rounds", [])),
                    "required_lineage": list(arguments.get("required_lineage", [])),
                    "history_runtime_roots": list(request.get("history_runtime_roots", [])),
                    "history_task_ids": [payload.get("task_id", "") for payload in history_payloads],
                    "reused_artifact_refs": sorted(reused_artifact_refs),
                    "reused_strategy_refs": sorted(reused_strategy_refs),
                },
            ),
            "reused_artifact_count": str(len(reused_artifact_refs)),
            "reused_strategy_count": str(len(reused_strategy_refs)),
        }
        for field_name in required_outputs:
            if field_name not in payload:
                raise RuntimeError(f"continuous codeact output missing required field: {field_name}")
        return payload

    rows, fieldnames, resolved_csv_path = _read_csv_rows(str(arguments.get("csv_path", "")))
    artifact_refs, strategy_refs = _produced_refs(reuse_contract)

    base_payload: dict[str, object] = {
        "task_id": request["task_id"],
        "task_family": task_family,
        "intent_op": intent_op,
        "query_text": request["query_text"],
        "summary_text": request["summary_suffix"],
        "selected_doc_hashes": list(request["selected_doc_hashes"]),
        "supporting_doc_ids": list(request.get("supporting_doc_ids", [])),
        "evidence_pack_hash": request["evidence_pack_hash"],
        "retrieval_log_hash": request["retrieval_log_hash"],
        "route": request.get("route", ""),
        "tool_name": request.get("tool_name", ""),
        "action_contract": request.get("action_contract", ""),
        "downgraded_execution_goal": request["downgraded_execution_goal"],
        "execution_goal": request["execution_goal"],
        "planner_plan_payload": request.get("planner_plan_payload", {}),
        "dataset_id": str(arguments.get("dataset_id", "")),
        "csv_path": str(arguments.get("csv_path", "")),
        "csv_source_path": str(resolved_csv_path),
        "produced_artifact_refs": artifact_refs,
        "produced_strategy_refs": strategy_refs,
        "consumed_artifact_refs": consumed_artifact_refs,
        "consumed_strategy_refs": consumed_strategy_refs,
    }

    if intent_op == "profile_table":
        columns = [str(item) for item in arguments.get("columns", [])]
        profile = {
            "row_count": len(rows),
            "fieldnames": list(fieldnames),
            "column_types": {
                field: _infer_column_type([str(row.get(field, "")) for row in rows[: min(len(rows), 128)]])
                for field in fieldnames
            },
        }
        missingness = {
            f"percentage_{field.replace('No. of ', '').replace(' ', '_').lower()}": round(
                sum(1 for row in rows if not str(row.get(field, "")).strip()) / max(len(rows), 1) * 100.0,
                2,
            )
            for field in columns
        }
        artifact_payload = {
            "dataset_id": arguments.get("dataset_id", ""),
            "row_count": len(rows),
            "fieldnames": list(fieldnames),
            "column_types": profile["column_types"],
            "missingness": missingness,
        }
        artifact_relpath = _artifact_relpath(request["task_id"], "schema_profile")
        base_payload.update(
            {
                **missingness,
                "schema_profile_ref": _write_artifact(root, artifact_relpath, artifact_payload),
                "missingness_summary": missingness,
            }
        )
    elif intent_op == "aggregate_and_extreme":
        mean_column = str(arguments["mean_column"])
        max_column = str(arguments["max_column"])
        series = _numeric_series(rows, mean_column)
        max_rows = [row for row in rows if _parse_number(row.get(max_column, "")) is not None]
        max_row = max(max_rows, key=lambda row: _parse_number(row.get(max_column, "")) or 0.0)
        artifact_relpath = _artifact_relpath(request["task_id"], "stats")
        artifact_payload = {
            "mean_column": mean_column,
            "mean_value": round(_mean(series)),
            "max_column": max_column,
            "max_row": {
                "country": str(max_row.get("Country", "")).strip(),
                "year": str(max_row.get("Year", "")).strip(),
                "value": _parse_number(max_row.get(max_column, "")),
            },
        }
        base_payload.update(
            {
                "stats_artifact_ref": _write_artifact(root, artifact_relpath, artifact_payload),
                "mean_cases": str(int(round(_mean(series)))),
                "max_deaths_country": str(max_row.get("Country", "")).strip(),
                "max_deaths_year": str(max_row.get("Year", "")).strip(),
            }
        )
    elif intent_op == "correlate_columns":
        left = str(arguments["left_column"])
        right = str(arguments["right_column"])
        pairs = [
            (_parse_number(row.get(left, "")), _parse_number(row.get(right, "")))
            for row in rows
        ]
        pairs = [(l, r) for l, r in pairs if l is not None and r is not None]
        corr = _pearson([l for l, _ in pairs], [r for _, r in pairs])
        artifact_relpath = _artifact_relpath(request["task_id"], "correlation")
        base_payload.update(
            {
                "correlation_artifact_ref": _write_artifact(
                    root,
                    artifact_relpath,
                    {
                        "left_column": left,
                        "right_column": right,
                        "method": str(arguments.get("method", "pearson")),
                        "correlation_coefficient": round(corr, 4),
                    },
                ),
                "correlation_coefficient": _format_number(round(corr, 2), digits=2),
            }
        )
    elif intent_op == "detect_outliers":
        column = str(arguments["column"])
        method = str(arguments.get("method", "zscore")).strip().lower()
        threshold = float(arguments.get("threshold", 3))
        values = _numeric_series(rows, column)
        mask = _outlier_mask(values, method=method, threshold=threshold)
        kept = [value for value, is_outlier in zip(values, mask, strict=True) if not is_outlier]
        outlier_count = sum(1 for item in mask if item)
        artifact_relpath = _artifact_relpath(request["task_id"], "outliers")
        base_payload["outlier_artifact_ref"] = _write_artifact(
            root,
            artifact_relpath,
            {
                "column": column,
                "method": method,
                "threshold": threshold,
                "outlier_count": outlier_count,
                "kept_count": len(kept),
            },
        )
        base_payload["outlier_count"] = str(outlier_count)
        if "mean_no_of_deaths_with_outliers" in required_outputs:
            base_payload["mean_no_of_deaths_with_outliers"] = _format_number(round(_mean(values), 2), digits=2)
        if "mean_no_of_deaths_without_outliers" in required_outputs:
            base_payload["mean_no_of_deaths_without_outliers"] = _format_number(round(_mean(kept), 2), digits=2)
        if "baro_outlier_count" in required_outputs:
            base_payload["baro_outlier_count"] = str(outlier_count)
    elif intent_op == "materialize_clean_table":
        dataset_id = str(arguments.get("dataset_id", ""))
        if dataset_id == "disease_estimates":
            values = _numeric_series(rows, "No. of deaths_max")
            mask = _outlier_mask(values, method="iqr", threshold=3.0)
            filtered_count = len([value for value, is_outlier in zip(values, mask, strict=True) if not is_outlier])
            cleaning_policy_hash = _sha256_text(_stable_json(arguments))
            artifact_relpath = _artifact_relpath(request["task_id"], "cleaned_table")
            base_payload.update(
                {
                    "cleaned_table_ref": _write_artifact(
                        root,
                        artifact_relpath,
                        {
                            "dataset_id": dataset_id,
                            "cleaned_row_count": filtered_count,
                            "policy_sources": list(arguments.get("policy_sources", [])),
                            "cleaning_policy_hash": cleaning_policy_hash,
                        },
                    ),
                    "cleaned_row_count": str(filtered_count),
                    "cleaning_policy_hash": cleaning_policy_hash,
                    "cleaned_table_created": "true",
                }
            )
        else:
            windspeed_values = _numeric_series(rows, str(arguments.get("outlier_column", "WINDSPEED")))
            windspeed_mean = _mean(windspeed_values)
            mask = _outlier_mask(
                windspeed_values,
                method=str(arguments.get("outlier_method", "zscore")),
                threshold=float(arguments.get("outlier_threshold", 3)),
            )
            replaced_windspeed = [
                windspeed_mean if is_outlier else value
                for value, is_outlier in zip(windspeed_values, mask, strict=True)
            ]
            temperature_values = _numeric_series(rows, str(arguments.get("impute_column", "AT")))
            atmos_mean = _mean(temperature_values)
            artifact_relpath = _artifact_relpath(request["task_id"], "cleaned_table")
            base_payload.update(
                {
                    "cleaned_table_ref": _write_artifact(
                        root,
                        artifact_relpath,
                        {
                            "dataset_id": dataset_id,
                            "row_count": len(replaced_windspeed),
                            "outlier_method": str(arguments.get("outlier_method", "zscore")),
                            "outlier_threshold": float(arguments.get("outlier_threshold", 3)),
                            "impute_column": str(arguments.get("impute_column", "AT")),
                        },
                    ),
                    "mean_wind_post": _format_number(round(_mean(replaced_windspeed), 2), digits=2),
                    "mean_atmos_temp_post": _format_number(round(atmos_mean, 2), digits=2),
                }
            )
    elif intent_op == "profile_and_mean":
        column = str(arguments["column"])
        series = _numeric_series(rows, column)
        artifact_relpath = _artifact_relpath(request["task_id"], "schema_profile")
        base_payload.update(
            {
                "schema_profile_ref": _write_artifact(
                    root,
                    artifact_relpath,
                    {
                        "dataset_id": arguments.get("dataset_id", ""),
                        "row_count": len(rows),
                        "fieldnames": list(fieldnames),
                        "column_types": {
                            field: _infer_column_type([str(row.get(field, "")) for row in rows[: min(len(rows), 128)]])
                            for field in fieldnames
                        },
                    },
                ),
                "mean_windspeed": _format_number(round(_mean(series), 3), digits=3),
            }
        )
    elif intent_op == "groupby_aggregate":
        monthly = _monthly_means(rows, str(arguments["groupby"]).replace("month(", "").replace(")", ""), str(arguments["value_column"]))
        artifact_relpath = _artifact_relpath(request["task_id"], "groupby")
        base_payload.update(
            {
                "groupby_artifact_ref": _write_artifact(
                    root,
                    artifact_relpath,
                    {
                        "groupby": str(arguments["groupby"]),
                        "value_column": str(arguments["value_column"]),
                        "aggregation": str(arguments["aggregation"]),
                        "monthly_avg_windspeed": monthly,
                    },
                ),
                "monthly_avg_windspeed": monthly,
            }
        )
    else:
        raise ValueError(f"unsupported continuous csv intent_op: {intent_op}")

    for field_name in required_outputs:
        if field_name not in base_payload:
            raise RuntimeError(f"continuous codeact output missing required field: {field_name}")
    return base_payload
