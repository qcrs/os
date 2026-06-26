"""Executor agent with a small, sandboxed CodeAct step."""

import ast
import io
import json
import re
import textwrap
import time
from contextlib import redirect_stdout

from langgraph.store.base import BaseStore

from config import NS_EXECUTIONS
from memory import store_put
from metrics import metrics
from protocol import ActionType, hash_text, make_message, summarize_text

from .shared import _get_mode, _hidden_state_summary, _record_hidden_state_received


SAFE_BUILTINS = {
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
}

SAFE_AST_NODES = {
    ast.Module,
    ast.Assign,
    ast.AugAssign,
    ast.Expr,
    ast.Load,
    ast.Store,
    ast.Name,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.If,
    ast.For,
    ast.comprehension,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Call,
    ast.keyword,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
}


def executor(state: dict, store: BaseStore) -> dict:
    """Run a bounded CodeAct verification step after analyst output.

    This executor is intentionally small: it does not call shells, open files, or
    access the network. It builds a short Python snippet from structured state,
    validates the AST against a whitelist, executes it with safe builtins, and
    records the resulting artifact for the summarizer.
    """
    t0 = time.perf_counter()
    mode = _get_mode(state)

    query = state.get("query", "")
    plan = state.get("plan", "")
    analysis = state.get("analysis", "")
    analysis_digest = state.get("analysis_digest", "")
    candidate_answers = state.get("candidate_answers", {})
    evidence = state.get("evidence", [])
    selected_context_packets = state.get("selected_context_packets", [])
    hidden_guidance = state.get("hidden_guidance", {})
    task_group = state.get("task_group", "default")
    planner_hidden_state = state.get("planner_hidden_state")
    _record_hidden_state_received("executor", planner_hidden_state)

    code = _build_codeact_program(
        evidence=evidence,
        selected_context_packets=selected_context_packets,
        hidden_guidance=hidden_guidance,
        analysis=analysis,
    )
    execution_result = _run_safe_python(code)
    final_answer, extracted_answers = _build_final_answer(
        query=query,
        candidate_answers=candidate_answers,
        analysis=analysis,
        execution_result=execution_result,
    )
    if final_answer:
        execution_result["final_answer"] = final_answer
        execution_result["extracted_answers"] = extracted_answers
    execution_summary = _summarize_execution_result(execution_result)
    execution_memory_id = f"execution_{task_group}_{hash_text(query or plan or analysis_digest)}"

    store_put(store, NS_EXECUTIONS, execution_memory_id, {
        "query": query,
        "plan": plan,
        "analysis_digest": analysis_digest,
        "code": code,
        "execution_result": execution_result,
        "execution_summary": execution_summary,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
        "hidden_guidance": hidden_guidance,
        "planner_hidden_state": _hidden_state_summary(planner_hidden_state),
    },
        memory_type="execution",
        source_agent="executor",
        task_group=task_group,
        task_topic=query,
        summary=execution_summary,
        tags=["execution", "executor", "codeact", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_executor", duration)

    result = {
        "execution_code": code,
        "execution_result": execution_result,
        "execution_summary": execution_summary,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
    }
    if planner_hidden_state:
        result["planner_hidden_state"] = planner_hidden_state

    if mode == "structured":
        msg = make_message(
            source="executor", target="summarizer",
            action=ActionType.EXECUTE,
            params={
                "analysis_chars": len(analysis),
                "evidence_count": len(evidence),
                "selected_context_count": len(selected_context_packets),
                "planner_hidden_state": _hidden_state_summary(planner_hidden_state),
            },
            result={
                "execution_ok": execution_result["ok"],
                "execution_summary": execution_summary,
                "final_answer": final_answer,
                "answer_field_count": len(extracted_answers),
                "metric_count": len(execution_result.get("metrics", {})),
            },
            task_group=task_group,
            hidden_state=planner_hidden_state,
        )
        metrics.record_message(
            source="executor", target="summarizer", action="execute",
            param_chars=len(analysis_digest) + len(str(len(evidence))),
            result_chars=len(execution_summary) + len(final_answer),
            has_embedding=False,
            has_hidden_state=planner_hidden_state is not None,
            hidden_state_dims=planner_hidden_state.get("dims", 0) if planner_hidden_state else 0,
        )
        result["messages"] = [msg.to_dict()]

    return result


def _extract_answer_format(query: str) -> str:
    """Extract the expected @field[value] format from the task query."""
    marker = "Expected answer format:"
    if marker not in query:
        return ""
    tail = query.split(marker, 1)[1]
    stop_marker = "\nSample data"
    if stop_marker in tail:
        tail = tail.split(stop_marker, 1)[0]
    return " ".join(tail.strip().split())


_ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_BOOL_RE = re.compile(r"\b(True|False|true|false)\b")


def _required_answer_fields(answer_format: str) -> list[str]:
    """Return field names required by an @field[...] answer format."""
    fields = []
    seen = set()
    for field in re.findall(r"@(\w+)\[", answer_format or ""):
        if field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return fields


def _build_final_answer(
    *,
    query: str,
    candidate_answers: object,
    analysis: str,
    execution_result: dict,
) -> tuple[str, dict[str, str]]:
    """Create the machine-graded final answer from executor-owned state."""
    answer_format = _extract_answer_format(query)
    required_fields = _required_answer_fields(answer_format)
    if not required_fields:
        return "", {}

    candidates = _clean_candidate_answers(candidate_answers, required_fields)
    search_text = "\n".join([
        analysis or "",
        execution_result.get("stdout", "") if isinstance(execution_result, dict) else "",
        str(execution_result.get("metrics", {})) if isinstance(execution_result, dict) else "",
    ])

    extracted = {}
    for field in required_fields:
        value = candidates.get(field, "").strip() or _find_value_for_field(field, search_text)
        extracted[field] = value or "unknown"
    final_answer = " ".join(f"@{field}[{extracted[field]}]" for field in required_fields)
    return final_answer, extracted


def _clean_candidate_answers(value: object, required_fields: list[str]) -> dict[str, str]:
    """Normalize candidate answers to required scalar fields."""
    if not isinstance(value, dict):
        value = dict(_ANSWER_RE.findall(str(value or "")))
    allowed = set(required_fields)
    cleaned = {}
    for key, raw in value.items():
        field = str(key).strip().lstrip("@").split("[", 1)[0]
        if field not in allowed:
            continue
        if isinstance(raw, (list, dict)):
            text = str(raw)
        else:
            text = str(raw).strip()
        tag_match = _ANSWER_RE.fullmatch(text)
        cleaned[field] = tag_match.group(2).strip() if tag_match else text
    return cleaned


def _find_value_for_field(field: str, text: str) -> str:
    """Best-effort extraction of a scalar value close to a field mention."""
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


def _build_codeact_program(
    *,
    evidence: list[dict],
    selected_context_packets: list[dict],
    hidden_guidance: dict,
    analysis: str,
) -> str:
    """Build deterministic CodeAct code from structured state."""
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


def _run_safe_python(code: str) -> dict:
    """Validate and execute a small Python snippet with restricted globals."""
    try:
        tree = ast.parse(code, mode="exec")
        _validate_ast(tree)
        stdout = io.StringIO()
        env = {"__builtins__": SAFE_BUILTINS}
        with redirect_stdout(stdout):
            exec(compile(tree, "<executor_codeact>", "exec"), env, env)
        return {
            "ok": True,
            "stdout": stdout.getvalue().strip(),
            "metrics": env.get("metrics", {}),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "stdout": "",
            "metrics": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) not in SAFE_AST_NODES:
            raise ValueError(f"Unsafe CodeAct node: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_BUILTINS:
                raise ValueError("Only whitelisted builtin calls are allowed")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Dunder names are not allowed")


def _summarize_execution_result(result: dict) -> str:
    if not result.get("ok"):
        return summarize_text(f"CodeAct execution failed: {result.get('error', '')}", 320)
    metrics_payload = result.get("metrics", {})
    return summarize_text(
        "CodeAct execution succeeded with metrics: "
        f"{json.dumps(metrics_payload, ensure_ascii=False, sort_keys=True)}",
        360,
    )
