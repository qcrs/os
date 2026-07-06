"""Executor-owned CodeAct agent capability."""

from __future__ import annotations

import json
import os
import re
import textwrap

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from codeact_runtime import build_codeact_prompt_context, run_codeact_python
from metrics import metrics
from models import get_model
from protocol import summarize_text


_ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_BOOL_RE = re.compile(r"\b(True|False|true|false)\b")


def codeact(state: dict, store: BaseStore | None = None) -> dict:
    """Run CodeAct as an executor-owned agent component."""
    del store

    query = state.get("query", "")
    analysis = state.get("analysis", "")
    candidate_answers = state.get("candidate_answers", {})
    evidence = state.get("evidence", [])
    selected_context_packets = state.get("selected_context_packets", [])
    hidden_guidance = state.get("hidden_guidance", {})
    artifact_refs = state.get("artifact_refs", [])
    selected_strategy = "legacy_metrics_only"
    code = ""
    raw_execution_result: dict = _failed_execution_result("CodeAct did not run.")
    execution_result: dict = dict(raw_execution_result)

    answer_format = extract_answer_format(query)
    required_fields = required_answer_fields(answer_format)
    route = _resolve_codeact_route(artifact_refs=artifact_refs)
    route_guidance = _route_specific_llm_guidance(required_fields)

    if route["kind"] == "table_csv":
        selected_strategy, code, raw_execution_result, execution_result = _execute_llm_codeact(
            query=query,
            candidate_answers=candidate_answers,
            analysis=analysis,
            evidence=evidence,
            selected_context_packets=selected_context_packets,
            hidden_guidance=hidden_guidance,
            artifact_refs=artifact_refs,
            required_fields=required_fields,
            route=route,
            route_guidance=route_guidance,
        )
    else:
        code = _build_legacy_codeact_program(
            evidence=evidence,
            selected_context_packets=selected_context_packets,
            hidden_guidance=hidden_guidance,
            analysis=analysis,
        )
        raw_execution_result = run_codeact_python(code, artifact_refs=[])
        execution_result = dict(raw_execution_result)
        execution_result.pop("artifacts", None)
        execution_result.pop("duration_s", None)

    fallback_used = False
    answer_format_rebuilt = False
    final_answer = ""
    extracted_answers: dict[str, str] = {}
    if raw_execution_result.get("ok"):
        if raw_execution_result.get("final_answer"):
            final_answer = str(raw_execution_result["final_answer"]).strip()
        if raw_execution_result.get("extracted_answers"):
            extracted_answers = clean_candidate_answers(
                raw_execution_result["extracted_answers"],
                required_fields,
            )
        extracted_answers = _normalize_required_answer_values(extracted_answers, required_fields)
        if required_fields and _has_complete_required_fields(extracted_answers, required_fields):
            rebuilt_final_answer = _compose_final_answer(required_fields, extracted_answers, final_answer)
            if rebuilt_final_answer != final_answer:
                answer_format_rebuilt = True
            final_answer = rebuilt_final_answer
        elif (not final_answer or not _has_complete_required_fields(extracted_answers, required_fields)):
            final_answer, extracted_answers = build_final_answer(
                query=query,
                candidate_answers=candidate_answers,
                analysis=analysis,
                execution_result=execution_result,
                existing_answers=extracted_answers,
            )
            fallback_used = True
    else:
        extracted_answers = {}
    extracted_answers = _normalize_required_answer_values(extracted_answers, required_fields)
    if final_answer or extracted_answers:
        final_answer = _compose_final_answer(required_fields, extracted_answers, final_answer)
    if final_answer:
        execution_result["final_answer"] = final_answer
        execution_result["extracted_answers"] = extracted_answers
    execution_result["selected_strategy"] = selected_strategy
    execution_result["fallback_answer_used"] = fallback_used
    execution_result["answer_format_rebuilt"] = answer_format_rebuilt
    _finalize_execution_status(
        route=route,
        required_fields=required_fields,
        execution_result=execution_result,
        extracted_answers=extracted_answers,
    )

    execution_trace = _build_execution_trace(
        route=route,
        required_fields=required_fields,
        artifact_refs=artifact_refs,
        raw_execution_result=raw_execution_result,
        execution_result=execution_result,
    )
    tool_results = _build_tool_results(
        route=route,
        artifact_refs=artifact_refs,
        raw_execution_result=raw_execution_result,
    )
    execution_result["trace"] = execution_trace
    execution_result["tool_results"] = tool_results
    execution_summary = summarize_execution_result(execution_result)

    return {
        "execution_code": code,
        "execution_result": execution_result,
        "execution_summary": execution_summary,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
        "execution_trace": execution_trace,
        "tool_results": tool_results,
    }


def extract_answer_format(query: str) -> str:
    marker = "Expected answer format:"
    if marker not in query:
        return ""
    tail = query.split(marker, 1)[1]
    stop_marker = "\nSample data"
    if stop_marker in tail:
        tail = tail.split(stop_marker, 1)[0]
    return " ".join(tail.strip().split())


def _codeact_executor_enabled() -> bool:
    return str(os.getenv("ENABLE_CODEACT_EXECUTOR", "0")).strip().lower() in {"1", "true", "yes"}


def required_answer_fields(answer_format: str) -> list[str]:
    fields = []
    seen = set()
    for field in re.findall(r"@(\w+)\[", answer_format or ""):
        if field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return fields


def build_final_answer(
    *,
    query: str,
    candidate_answers: object,
    analysis: str,
    execution_result: dict,
    existing_answers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    answer_format = extract_answer_format(query)
    required_fields = required_answer_fields(answer_format)
    if not required_fields:
        return "", {}

    candidates = clean_candidate_answers(candidate_answers, required_fields)
    existing = clean_candidate_answers(existing_answers or {}, required_fields)
    search_text = "\n".join([
        analysis or "",
        str(execution_result.get("final_answer", "")) if isinstance(execution_result, dict) else "",
        execution_result.get("stdout", "") if isinstance(execution_result, dict) else "",
        str(execution_result.get("extracted_answers", {})) if isinstance(execution_result, dict) else "",
        str(execution_result.get("metrics", {})) if isinstance(execution_result, dict) else "",
    ])

    extracted = {}
    for field in required_fields:
        value = (
            existing.get(field, "").strip()
            or candidates.get(field, "").strip()
            or _find_value_for_field(field, search_text)
        )
        extracted[field] = value or "unknown"
    final_answer = " ".join(f"@{field}[{extracted[field]}]" for field in required_fields)
    return final_answer, extracted


def clean_candidate_answers(value: object, required_fields: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = dict(_ANSWER_RE.findall(str(value or "")))
    allowed = set(required_fields)
    cleaned = {}
    for key, raw in value.items():
        field = str(key).strip().lstrip("@").split("[", 1)[0]
        if field not in allowed:
            continue
        text = str(raw).strip() if not isinstance(raw, (list, dict)) else str(raw)
        tag_match = _ANSWER_RE.fullmatch(text)
        cleaned[field] = tag_match.group(2).strip() if tag_match else text
    return cleaned


def summarize_execution_result(result: dict) -> str:
    if not result.get("ok"):
        return summarize_text(f"CodeAct execution failed: {result.get('error', '')}", 320)
    metrics_payload = result.get("metrics", {})
    strategy = str(result.get("selected_strategy", "")).strip()
    prefix = "CodeAct execution succeeded"
    if strategy:
        prefix += f" via {strategy}"
    return summarize_text(
        f"{prefix} with metrics: "
        f"{json.dumps(metrics_payload, ensure_ascii=False, sort_keys=True)}",
        360,
    )


def _route_specific_llm_guidance(required_fields: list[str]) -> str:
    base = (
        "Infer the required computation directly from the question and required fields. "
        "Inspect the schema first, prefer simple row loops or generic helpers, and compute the answer from the mounted CSV artifact only. "
        "For category-count tasks, prefer value_counts() or direct counting loops. "
        "For column summaries, prefer numeric_values(), mean(), std(), median(), quantile(), sample_skew(), pearson_corr(), or zscore_outlier_count() as appropriate."
    )
    return (
        f"{base} Treat the route hint as optional guidance, not ground truth. "
        f"If the question and required fields imply a different computation, follow the question. "
        f"Required fields: {required_fields}."
    )


def _normalize_required_answer_values(
    extracted_answers: dict[str, str],
    required_fields: list[str],
) -> dict[str, str]:
    if not required_fields:
        return dict(extracted_answers)
    normalized = dict(extracted_answers)
    boolean_fields = {"is_normal", "normality_test_result"}
    for field in required_fields:
        raw = str(normalized.get(field, "")).strip()
        if not raw:
            continue
        if field in boolean_fields:
            lowered = raw.lower()
            if lowered in {"true", "1", "1.0", "yes"}:
                normalized[field] = "True"
            elif lowered in {"false", "0", "0.0", "no"}:
                normalized[field] = "False"
        elif raw.lower() in {"nan", "none", "null", "n/a"}:
            normalized[field] = "unknown"
    return normalized


def _is_missing_required_value(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return text.lower() in {"unknown", "nan", "none", "null", "n/a"}


def _compose_final_answer(
    required_fields: list[str],
    extracted_answers: dict[str, str],
    fallback_final_answer: str,
) -> str:
    if required_fields:
        return " ".join(
            f"@{field}[{str(extracted_answers.get(field, 'unknown')).strip() or 'unknown'}]"
            for field in required_fields
        )
    return str(fallback_final_answer or "").strip()


def _find_value_for_field(field: str, text: str) -> str:
    if not text:
        return ""
    lower_text = text.lower()
    field_terms = [field, field.replace("_", " ")]
    for term in field_terms:
        index = lower_text.find(term.lower())
        if index < 0:
            continue
        window = text[index:index + 240]
        bool_match = _BOOL_RE.search(window)
        if bool_match:
            return bool_match.group(1).capitalize()
        number_match = _NUMBER_RE.search(window)
        if number_match:
            return number_match.group(0)
    bool_match = _BOOL_RE.search(text)
    if bool_match:
        return bool_match.group(1).capitalize()
    numbers = _NUMBER_RE.findall(text)
    return numbers[-1] if numbers else ""


def _resolve_codeact_route(*, artifact_refs: list[dict]) -> dict[str, str]:
    if not _codeact_executor_enabled():
        return {
            "kind": "legacy",
            "route": "legacy_metrics_only",
            "reason": "ENABLE_CODEACT_EXECUTOR is disabled.",
        }
    has_csv = any(
        isinstance(artifact, dict) and str(artifact.get("kind", "")).lower() == "csv"
        for artifact in artifact_refs
    )
    if not has_csv:
        return {
            "kind": "legacy",
            "route": "legacy_no_csv_artifact",
            "reason": "No CSV artifact is mounted for deterministic table execution.",
        }
    return {
        "kind": "table_csv",
        "route": "generic_csv_question",
        "reason": "CSV artifact detected; use generic CSV reasoning only.",
    }


def _generate_codeact_program(
    *,
    query: str,
    candidate_answers: dict[str, str],
    analysis: str,
    evidence: list[dict],
    selected_context_packets: list[dict],
    hidden_guidance: dict,
    artifact_refs: list[dict],
    required_fields: list[str],
    route: dict[str, str],
    route_guidance: str,
) -> dict[str, str]:
    prompt_context = build_codeact_prompt_context(artifact_refs)
    answer_format = extract_answer_format(query)
    model = get_model(temperature=0.0)
    analysis_hint = summarize_text(analysis or "", 320)
    csv_schema_hint = _csv_schema_hint(artifact_refs)
    messages = [
        SystemMessage(content="""You are a CodeAct Python generator.
Write a single Python program for a restricted runtime.

Hard requirements:
- Return ONLY Python code. No markdown fences. No explanation.
- Do not import modules.
- Do not define functions or classes.
- Use the provided helpers like load_csv_rows(), artifact_path(), list_artifacts().
- Read the CSV artifact and compute the answer from data, not from the sample rows in the prompt.
- The runtime provides math plus row/stat helpers. Never write import statements.
- Prefer `rows = load_csv_rows()` plus column_names(), column_values(), value_counts(), unique_values(), numeric_values(), paired_numeric_values(), mean(), std(), median(), quantile(), pearson_corr(), sample_skew(), normality_pvalue(), zscore_outlier_count().
- Remember that `load_csv_rows()` returns `list[dict[str, str]]`. Row values are usually stripped strings unless you convert them with to_float(), int(), or float().
- Column lookup is whitespace-normalized, so a CSV header like ` WINDSPEED` can be accessed as `row["WINDSPEED"]`.
- `numeric_values()` and `paired_numeric_values()` skip missing/unparseable values. If the task asks for missing-value counts, inspect raw rows directly instead of numeric_values().
- Avoid complex pandas idioms, boolean-mask chains, and fancy syntax when a simple row loop or helper call works.
- If no specialized route matches, inspect column names first and solve the task with generic helpers or direct row loops instead of guessing from field names alone.
- Compute the requested field values explicitly and assign them directly into extracted_answers.
- Never emit placeholder values like unknown, n/a, null, or 0.0 for boolean fields.
- Set extracted_answers to a dict[str, str].
- If required_fields is non-empty, you MUST set final_answer using the computed extracted_answers values, not placeholder literals.
- Never copy literal placeholders from the prompt such as `[value]`, `[number]`, or `[count]` into final_answer.
- Never invent alternative formats like `@field[value]=x`, JSON, prose, or extra punctuation.
- The safest pattern is:
- append one exact answer part per required field using the concrete field names
- then join them with a single space
- Set metrics to a dict with task_route, route_reason, and any audit values you compute.
- Print concise diagnostics if useful.
"""),
        HumanMessage(content=f"""Task query:
{query}

Exact expected answer format text:
{answer_format}

Required answer fields:
{required_fields}

Executor route hint:
{json.dumps(route, ensure_ascii=False)}

Route-specific guidance:
{route_guidance}

CSV schema hint:
{csv_schema_hint}

Lightweight analyst hint:
{analysis_hint or "N/A"}

Optional candidate answers hint:
{json.dumps(candidate_answers, ensure_ascii=False)}

Runtime:
{prompt_context}

Use this exact minimal skeleton shape:
final_answer = ""
extracted_answers = {{}}
rows = load_csv_rows()
# ... compute values here without imports ...
# Build final_answer after extracted_answers is complete:
{_final_answer_code_example(required_fields)}
metrics = {{}}
"""),
    ]
    response = model.invoke(messages)
    _record_codeact_llm_tokens(response, agent_name="codeact_generate")
    metrics.increment("codeact_llm_generate_calls")
    code = _extract_python_code(response.content if hasattr(response, "content") else str(response))
    if code.strip():
        return {"code": code}
    metrics.increment("codeact_llm_generate_empty")
    return {"code": ""}


def _execute_llm_codeact(
    *,
    query: str,
    candidate_answers: dict[str, str],
    analysis: str,
    evidence: list[dict],
    selected_context_packets: list[dict],
    hidden_guidance: dict,
    artifact_refs: list[dict],
    required_fields: list[str],
    route: dict[str, str],
    route_guidance: str,
) -> tuple[str, str, dict, dict]:
    code = ""
    raw_execution_result = _failed_execution_result("CodeAct did not run.")
    execution_result = dict(raw_execution_result)
    selected_strategy = "llm_not_run"
    answer_format = extract_answer_format(query)
    try:
        llm_plan = _generate_codeact_program(
            query=query,
            candidate_answers=candidate_answers,
            analysis=analysis,
            evidence=evidence,
            selected_context_packets=selected_context_packets,
            hidden_guidance=hidden_guidance,
            artifact_refs=artifact_refs,
            required_fields=required_fields,
            route=route,
            route_guidance=route_guidance,
        )
        selected_strategy = "llm_generate"
        code = _prepend_codeact_runtime_bindings(
            _sanitize_generated_code(llm_plan["code"]),
            required_fields=required_fields,
            answer_format=answer_format,
        )
        raw_execution_result = run_codeact_python(code, artifact_refs=artifact_refs)
        execution_result = dict(raw_execution_result)
        initial_answers = clean_candidate_answers(
            execution_result.get("extracted_answers", {}),
            required_fields,
        )
        initial_answers = _normalize_required_answer_values(initial_answers, required_fields)
        if not _is_execution_acceptable(
            required_fields=required_fields,
            execution_result=execution_result,
            normalized_answers=initial_answers,
        ):
            repair_plan = _repair_codeact_program(
                query=query,
                analysis=analysis,
                required_fields=required_fields,
                artifact_refs=artifact_refs,
                route=route,
                route_guidance=route_guidance,
                failed_code=code,
                execution_result=execution_result,
            )
            if repair_plan.get("code"):
                code = _prepend_codeact_runtime_bindings(
                    _sanitize_generated_code(repair_plan["code"]),
                    required_fields=required_fields,
                    answer_format=answer_format,
                )
                raw_execution_result = run_codeact_python(code, artifact_refs=artifact_refs)
                execution_result = dict(raw_execution_result)
                selected_strategy = "llm_repair"
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        raw_execution_result = _failed_execution_result(error_text)
        execution_result = dict(raw_execution_result)
        selected_strategy = "llm_exception"
        metrics.increment("codeact_llm_path_errors")
    return selected_strategy, code, raw_execution_result, execution_result


def _repair_codeact_program(
    *,
    query: str,
    analysis: str,
    required_fields: list[str],
    artifact_refs: list[dict],
    route: dict[str, str],
    route_guidance: str,
    failed_code: str,
    execution_result: dict,
) -> dict[str, str]:
    prompt_context = build_codeact_prompt_context(artifact_refs)
    answer_format = extract_answer_format(query)
    model = get_model(temperature=0.0)
    analysis_hint = summarize_text(analysis or "", 240)
    messages = [
        SystemMessage(content="""You are repairing a failed CodeAct Python program.
Return ONLY corrected Python code. No markdown fences. No explanation.
Keep the same restricted-runtime rules: no imports, no functions, no classes.
Ensure extracted_answers and final_answer are populated correctly.
Prefer load_csv_rows() and the provided helper functions over pandas-specific code when fixing CSV tasks."""),
        HumanMessage(content=f"""Original query:
{query}

Exact expected answer format text:
{answer_format}

Required answer fields:
{required_fields}

Route hint:
{json.dumps(route, ensure_ascii=False)}

Route-specific guidance:
{route_guidance}

Lightweight analyst hint:
{analysis_hint or "N/A"}

Runtime:
{prompt_context}

Failed code:
{failed_code}

Execution result:
{json.dumps(execution_result, ensure_ascii=False)}

If the prior code contained `import`, remove all imports and use only the preloaded runtime objects.
If the prior code assumed unavailable dataframe/statistics libraries, rewrite it to use load_csv_rows(), numeric_values(), paired_numeric_values(), mean(), std(), pearson_corr(), sample_skew(), normality_pvalue(), or zscore_outlier_count() where appropriate.
Remember that `load_csv_rows()` returns row dicts with mostly string values unless converted, column lookup is whitespace-normalized, and numeric_values()/paired_numeric_values() skip missing or unparseable cells.
If the task asks for missing-value counts, inspect raw row values directly instead of relying on numeric_values().
If the failed result used unknown, empty values, or the wrong field names, correct extracted_answers and rebuild final_answer from the required fields only.
If the failed code copied placeholders like `[value]` or wrote formats like `@field[value]=x`, replace final_answer with:
{_final_answer_code_example(required_fields)}
"""),
    ]
    response = model.invoke(messages)
    _record_codeact_llm_tokens(response, agent_name="codeact_repair")
    metrics.increment("codeact_llm_repair_calls")
    code = _extract_python_code(response.content if hasattr(response, "content") else str(response))
    return {"code": code}


def _extract_python_code(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    fence_match = re.search(r"```(?:python)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return raw


def _csv_schema_hint(artifact_refs: list[dict]) -> str:
    try:
        rows = run_codeact_python(
            "rows = load_csv_rows(nrows=1)\nmetrics = {'column_names': column_names(rows) if rows else []}",
            artifact_refs=artifact_refs,
        )
    except Exception:
        return "Unavailable."
    if not rows.get("ok"):
        return "Unavailable."
    column_names_value = ((rows.get("metrics") or {}).get("column_names")) or []
    if not column_names_value:
        return "Unavailable."
    return ", ".join(str(name) for name in column_names_value)


def _sanitize_generated_code(code: str) -> str:
    lines = []
    removed_import = False
    for line in str(code or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            removed_import = True
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if removed_import:
        metrics.increment("codeact_sanitized_import_lines")
    return cleaned


def _prepend_codeact_runtime_bindings(
    code: str,
    *,
    required_fields: list[str],
    answer_format: str,
) -> str:
    preamble = [
        f"required_fields = {required_fields!r}",
        f"expected_answer_format = {answer_format!r}",
    ]
    body = str(code or "").strip()
    if not body:
        return "\n".join(preamble)
    return "\n".join(preamble + [body])


def _final_answer_code_example(required_fields: list[str]) -> str:
    if not required_fields:
        return 'final_answer = ""'
    lines = ["answer_parts = []"]
    for field in required_fields:
        lines.append(f'answer_parts.append(f"@{field}[{{extracted_answers[{field!r}]}}]")')
    lines.append('final_answer = " ".join(answer_parts)')
    return "\n".join(lines)


def _failed_execution_result(error: str) -> dict:
    return {
        "ok": False,
        "stdout": "",
        "metrics": {},
        "error": str(error or "").strip(),
        "final_answer": "",
        "extracted_answers": {},
        "artifacts": [],
        "duration_s": 0.0,
    }


def _is_execution_acceptable(
    *,
    required_fields: list[str],
    execution_result: dict | None,
    normalized_answers: dict[str, str] | None = None,
) -> bool:
    if not execution_result or not isinstance(execution_result, dict):
        return False
    if not execution_result.get("ok"):
        return False
    if not required_fields:
        return True
    extracted = normalized_answers
    if extracted is None:
        extracted = clean_candidate_answers(execution_result.get("extracted_answers", {}), required_fields)
        extracted = _normalize_required_answer_values(extracted, required_fields)
    for field in required_fields:
        if _is_missing_required_value(extracted.get(field, "")):
            return False
    return True


def _has_complete_required_fields(extracted_answers: dict[str, str], required_fields: list[str]) -> bool:
    if not required_fields:
        return True
    for field in required_fields:
        if _is_missing_required_value(extracted_answers.get(field, "")):
            return False
    return True


def _record_codeact_llm_tokens(response, *, agent_name: str) -> None:
    usage = getattr(response, "usage_metadata", None)
    if usage:
        metrics.record_tokens(
            agent_name,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )


def _build_legacy_codeact_program(
    *,
    evidence: list[dict],
    selected_context_packets: list[dict],
    hidden_guidance: dict,
    analysis: str,
) -> str:
    evidence_payload = [
        {
            "claim": str(item.get("claim", "")),
            "support": str(item.get("support", "")),
            "doc_key": str(item.get("doc_key", "")),
            "span_id": str(item.get("span_id", "")),
        }
        for item in evidence
    ]
    packet_payload = [
        {
            "doc_key": str(packet.get("doc_key", "")),
            "reliable": bool((packet.get("verification") or {}).get("reliable", False)),
            "rehydrated": bool((packet.get("verification") or {}).get("rehydrated", False)),
        }
        for packet in selected_context_packets
    ]
    hidden_payload = {
        "used": bool(hidden_guidance.get("used", False)),
        "selected_packets": int(hidden_guidance.get("selected_packets", 0) or 0),
        "candidate_packets": int(hidden_guidance.get("candidate_packets", 0) or 0),
    }

    return textwrap.dedent(f"""
    evidence = {repr(evidence_payload)}
    packets = {repr(packet_payload)}
    hidden_guidance = {repr(hidden_payload)}
    analysis_text = {repr(str(analysis))}

    doc_keys = sorted(set(item["doc_key"] for item in evidence if item["doc_key"]))
    supported_claims = sum(1 for item in evidence if item["support"])
    reliable_packets = sum(1 for item in packets if item["reliable"])
    rehydrated_packets = sum(1 for item in packets if item["rehydrated"])
    coverage_ratio = round(supported_claims / max(len(evidence), 1), 4)

    metrics = {{
        "evidence_count": len(evidence),
        "supported_claims": supported_claims,
        "unique_doc_keys": len(doc_keys),
        "reliable_packets": reliable_packets,
        "rehydrated_packets": rehydrated_packets,
        "coverage_ratio": coverage_ratio,
        "hidden_routing_used": hidden_guidance["used"],
        "analysis_chars": len(analysis_text),
    }}
    print("CodeAct metrics:", metrics)
    """).strip()


def _build_execution_trace(
    *,
    route: dict[str, str],
    required_fields: list[str],
    artifact_refs: list[dict],
    raw_execution_result: dict,
    execution_result: dict,
) -> list[dict]:
    return [
        {
            "stage": "codeact.route",
            "kind": route["kind"],
            "route": route["route"],
            "reason": route["reason"],
            "required_fields": required_fields,
            "artifact_count": len(artifact_refs),
        },
        {
            "stage": "codeact.runtime",
            "ok": bool(raw_execution_result.get("ok")),
            "duration_s": raw_execution_result.get("duration_s"),
            "error": raw_execution_result.get("error", ""),
            "metric_keys": sorted((execution_result.get("metrics") or {}).keys()),
            "final_answer_present": bool(execution_result.get("final_answer")),
            "generated_by_llm": route.get("kind") == "table_csv",
            "fallback_answer_used": bool(execution_result.get("fallback_answer_used", False)),
            "answer_format_rebuilt": bool(execution_result.get("answer_format_rebuilt", False)),
            "missing_required_fields": [
                field
                for field in required_fields
                if str(execution_result.get("extracted_answers", {}).get(field, "")).strip() in {"", "unknown"}
            ],
            "selected_strategy": execution_result.get("selected_strategy", ""),
        },
    ]


def _finalize_execution_status(
    *,
    route: dict[str, str],
    required_fields: list[str],
    execution_result: dict,
    extracted_answers: dict[str, str],
) -> None:
    missing_fields = [
        field
        for field in required_fields
        if str(extracted_answers.get(field, "")).strip() in {"", "unknown"}
    ]
    if not missing_fields:
        return
    reason = f"Missing required CodeAct answer fields: {missing_fields}"
    if route.get("kind") == "table_csv":
        reason += " (generic CSV route)"
    error = str(execution_result.get("error", "") or "").strip()
    execution_result["ok"] = False
    execution_result["error"] = f"{error}; {reason}" if error else reason


def _build_tool_results(
    *,
    route: dict[str, str],
    artifact_refs: list[dict],
    raw_execution_result: dict,
) -> list[dict]:
    return [{
        "tool": "codeact_runtime.python",
        "kind": route["kind"],
        "route": route["route"],
        "ok": bool(raw_execution_result.get("ok")),
        "duration_s": raw_execution_result.get("duration_s"),
        "artifact_refs": [
            {
                "kind": str(artifact.get("kind", "")),
                "label": str(artifact.get("label", "")),
                "path": str(artifact.get("path", "")),
            }
            for artifact in artifact_refs
            if isinstance(artifact, dict)
        ],
        "error": raw_execution_result.get("error", ""),
    }]
