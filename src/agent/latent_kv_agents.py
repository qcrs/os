"""Latent KV agents for the D mode multi-agent collaboration.

These agents operate in latent_kv mode where:
- planner_explicit_for_latent: emits explicit structured plan/sub_queries
- researcher_explicit_for_latent: emits explicit evidence/context packets
- analyst_latent: prefills from structured packets, then runs latent steps
- executor_latent: inherits analyst KV, runs latent steps + CodeAct
- summarizer_latent: inherits full KV chain, generates final natural language

The older full-chain latent planner/researcher helpers remain in this module
for compatibility with existing scripts, but build_latent_kv_graph() wires the
explicit planner/researcher stage before the latent analyst stage.
"""

import json
import re
import time

from langgraph.store.base import BaseStore

from config import (
    ANALYST_LATENT_STEPS,
    EXECUTOR_LATENT_STEPS,
    NS_ANALYSIS,
    NS_DOCS,
    NS_EXECUTIONS,
    NS_PLANS,
    NS_SUMMARIES,
    PLANNER_LATENT_STEPS,
    POST_EXEC_LATENT_STEPS,
    RESEARCHER_LATENT_STEPS,
    SUMMARIZER_LATENT_STEPS,
)
from latent_kv_runtime import get_latent_kv_runtime
from memory import store_put, store_search
from metrics import metrics
from protocol import (
    ActionType,
    build_context_packet,
    format_context_for_prompt,
    hash_text,
    make_document_key,
    make_message,
    summarize_text,
)

from .shared import (
    _clean_json_contract_answer,
    _extract_json_final_contract_fields,
    _json_contract_answer_to_text,
    _normalize_sub_queries,
)
from .executor import (
    _build_classified_data_audit_program,
    _build_final_answer,
    _build_no_code_execution_result,
    _requires_no_code_executor,
    _summarize_execution_result,
)

# Safe Python execution (reuse from executor.py)
SAFE_BUILTINS = {
    "len": len,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "enumerate": enumerate,
    "zip": zip,
    "range": range,
    "True": True,
    "False": False,
    "None": None,
}


def _compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _safe_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction for model outputs that may include prose/fences."""
    if not text:
        return {}

    candidates = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE):
        candidates.append(match.group(1).strip())
    candidates.append(text.strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        for i, ch in enumerate(candidate):
            if ch != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _coerce_text_list(value, *, fallback: list[str], max_items: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = []

    items: list[str] = []
    seen = set()
    for item in value:
        text = _compact_text(item, max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= max_items:
            break

    for item in fallback:
        text = _compact_text(item, max_chars)
        if text and text not in seen:
            items.append(text)
            seen.add(text)
        if len(items) >= max_items:
            break
    return items


def _best_effort_delete(runtime, handle_id: str | None):
    if not handle_id:
        return
    try:
        runtime.delete_handle(handle_id)
    except Exception:
        pass


def _prior_context(store: BaseStore, query: str) -> str:
    try:
        prior_results = store_search(store, NS_SUMMARIES, query, limit=2)
    except Exception:
        prior_results = []
    if not prior_results:
        return ""
    metrics.increment("memory_reuse_hits")
    return "\n".join(
        _compact_text(r.value.get("text", "") or r.value.get("summary", ""), 300)
        for r in prior_results
    )


def _fallback_evidence(decoded: str, sub_query: str) -> list[str]:
    source = decoded if decoded and not decoded.startswith("[sim]") else sub_query
    pieces = re.split(r"(?<=[。.!?])\s+|\n+", source)
    fallback = [
        f"{sub_query}: identify relevant facts and constraints.",
        f"{sub_query}: preserve document references for downstream verification.",
        f"{sub_query}: keep claims compact so analyst can reason in latent KV.",
    ]
    return _coerce_text_list(pieces, fallback=fallback, max_items=5, max_chars=220)


def _build_analyst_material(state: dict) -> tuple[str, list[dict], list[dict]]:
    query = state.get("query", "")
    plan = state.get("plan", "")
    sub_queries = state.get("sub_queries", [])
    context_packets = state.get("context_packets", []) or []
    research_evidence = state.get("research_evidence", []) or []
    documents = state.get("documents", []) or []

    selected_packets = context_packets[:6]
    parts = [
        "\n<|agent_analyst_input|>",
        f"# Task\n{_compact_text(query, 1200)}",
    ]
    if plan:
        parts.append(f"# Explicit Planner Plan\n{_compact_text(plan, 800)}")
    if sub_queries:
        parts.append("# Explicit Sub Queries\n" + "\n".join(f"- {_compact_text(s, 240)}" for s in sub_queries[:5]))

    if selected_packets:
        parts.append("# Explicit Research Context Packets\n" + format_context_for_prompt(selected_packets))
        doc_refs = []
        for packet in selected_packets:
            full_ref = packet.get("full_doc_ref", {})
            doc_refs.append({
                "doc_key": packet.get("doc_key", ""),
                "source_query": packet.get("source_query", ""),
                "text_hash": full_ref.get("text_hash", ""),
            })
        parts.append("# Document References\n" + _safe_json({"refs": doc_refs}))
    elif research_evidence:
        parts.append("# Explicit Research Evidence\n" + _safe_json({"evidence": research_evidence[:6]}))
    elif documents:
        parts.append("# Fallback Research Documents\n" + "\n".join(_compact_text(d, 360) for d in documents[:3]))

    parts.append(
        "# Analyst Contract\n"
        "Do main reasoning in latent space. Do not decode a long analysis. "
        "Carry conclusions forward as Delta KV for executor."
    )
    parts.append("</|agent_analyst_input|>\n")
    return "\n".join(parts), selected_packets, research_evidence


def planner_explicit_for_latent(state: dict, store: BaseStore) -> dict:
    """Run the normal planner as explicit structured collaboration for D mode."""
    from .planner import planner as structured_planner

    forced_state = dict(state)
    forced_state["mode"] = "structured"
    return structured_planner(forced_state, store)


def researcher_explicit_for_latent(state: dict, store: BaseStore) -> dict:
    """Run the normal researcher as explicit structured packet generation."""
    from .researcher import researcher as structured_researcher

    forced_state = dict(state)
    forced_state["mode"] = "structured"
    forced_state.pop("latent_kv_handle_id", None)
    return structured_researcher(forced_state, store)


def _run_safe_python(code: str) -> dict:
    """Execute Python code in a restricted sandbox."""
    try:
        import ast

        tree = ast.parse(code, mode="exec")
        # Simplified validation (full validation in executor.py)
        exec_globals = {"__builtins__": SAFE_BUILTINS}
        exec_locals = {}
        exec(compile(tree, "<string>", "exec"), exec_globals, exec_locals)

        return {
            "ok": True,
            "metrics": exec_locals.get("metrics", {}),
            "stdout": "",
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "metrics": {},
            "stdout": "",
            "error": str(e),
        }


def planner_latent(state: dict, store: BaseStore) -> dict:
    """Planner performs internal latent reasoning and explicitly emits routing fields."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "latent_kv")
    runtime = get_latent_kv_runtime()

    prior = _prior_context(store, query)
    prefix = (
        "<|agent_planner|>\n"
        "You are the planner in a LatentMAS chain. Think internally in latent space, "
        "then expose only the routing payload required by researchers.\n"
        f"# Task\n{query}\n"
        + (f"# Prior Context\n{prior}\n" if prior else "")
    )

    handle = runtime.prefill(prefix, task_group, created_by="planner_prefill")
    handle = runtime.run_latent_steps(handle.handle_id, PLANNER_LATENT_STEPS, "planner")

    instruction = (
        "\nDecode the explicit planner payload only. Return valid JSON with exactly:\n"
        '{"plan":"concise plan","sub_queries":["single focused sub-query"]}\n'
        "No analysis prose."
    )
    decoded, handle = runtime.decode_text(
        handle.handle_id,
        instruction,
        max_tokens=320,
        temperature=0.0,
        metric_name="planner_latent_decode",
    )
    parsed = _extract_json_object(decoded)
    if not isinstance(parsed, dict):
        parsed = {}

    plan = _compact_text(parsed.get("plan", ""), 900) or f"Research plan for: {query}"
    sub_queries = _normalize_sub_queries(query, parsed.get("sub_queries", []))
    explicit_payload = {"plan": plan, "sub_queries": sub_queries}
    handle = runtime.inject_result_text(
        handle.handle_id,
        "\n<planner_explicit_output>" + _safe_json(explicit_payload) + "</planner_explicit_output>\n",
    )

    plan_memory_id = f"latent_plan_{task_group}_{hash_text(query)}"
    store_put(
        store,
        NS_PLANS,
        plan_memory_id,
        {
            "text": plan,
            "sub_queries": sub_queries,
            "query": query,
            "latent_kv_handle_id": handle.handle_id,
            "latent_steps": PLANNER_LATENT_STEPS,
            "mode": "latent_kv",
        },
        memory_type="plan",
        source_agent="planner_latent",
        task_group=task_group,
        task_topic=query,
        summary=plan,
        tags=["plan", "planner", "latent_kv", task_group],
    )

    msg = make_message(
        source="planner_latent",
        target="researcher_latent",
        action=ActionType.PLAN,
        params={"query": query, "task_group": task_group},
        result=explicit_payload,
        task_group=task_group,
    )
    metrics.record_message(
        source="planner_latent",
        target="researcher_latent",
        action="plan",
        param_chars=len(query),
        result_chars=len(plan) + sum(len(s) for s in sub_queries),
        has_embedding=False,
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_planner_latent", duration)
    return {
        "plan": plan,
        "sub_queries": sub_queries,
        "latent_kv_handle_id": handle.handle_id,
        "messages": [msg.to_dict()],
    }


def researcher_latent(state: dict, store: BaseStore) -> dict:
    """Researcher performs latent source analysis and emits verifiable compact evidence."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    sub_query = state.get("sub_query", query)
    plan = state.get("plan", "")
    source_context = state.get("source_context", "")
    task_group = state.get("task_group", "latent_kv")
    parent_handle_id = state.get("latent_kv_handle_id")
    runtime = get_latent_kv_runtime()

    role_payload = (
        "\n<|agent_researcher|>\n"
        "Use latent reasoning to inspect the assigned sub-query. "
        "Emit only compact evidence, a Context Packet summary, and document references.\n"
        f"# Sub Query\n{sub_query}\n"
        + (f"# Planner Plan\n{_compact_text(plan, 700)}\n" if plan else "")
        + (f"# Source Context\n{_compact_text(source_context, 1200)}\n" if source_context else "")
    )
    if parent_handle_id:
        handle = runtime.inject_role_transition(parent_handle_id, role_payload)
    else:
        handle = runtime.prefill(role_payload, task_group, created_by="researcher_prefill")

    handle = runtime.run_latent_steps(handle.handle_id, RESEARCHER_LATENT_STEPS, "researcher")
    instruction = (
        "\nDecode the explicit researcher payload only. Return valid JSON with exactly:\n"
        "{"
        '"evidence":["short factual evidence 1","short factual evidence 2","short factual evidence 3"],'
        '"context_packet":{"summary":"compact query-focused summary","coverage":"what this evidence covers"},'
        '"document_refs":["source/ref/id 1","source/ref/id 2"]'
        "}\n"
        "No long analysis prose."
    )
    decoded, handle = runtime.decode_text(
        handle.handle_id,
        instruction,
        max_tokens=512,
        temperature=0.1,
        metric_name="researcher_latent_decode",
    )
    parsed = _extract_json_object(decoded)
    if not isinstance(parsed, dict):
        parsed = {}

    evidence = _coerce_text_list(
        parsed.get("evidence"),
        fallback=_fallback_evidence(decoded, sub_query),
        max_items=5,
        max_chars=240,
    )
    context_obj = parsed.get("context_packet") if isinstance(parsed.get("context_packet"), dict) else {}
    context_summary = _compact_text(context_obj.get("summary", ""), 420)
    doc_refs = _coerce_text_list(
        parsed.get("document_refs"),
        fallback=[f"latent_research:{task_group}:{hash_text(sub_query)}"],
        max_items=4,
        max_chars=180,
    )

    doc_text_parts = [
        f"Sub-query: {sub_query}",
        f"Planner context: {_compact_text(plan, 500)}" if plan else "",
        "Evidence:",
        *[f"- {item}" for item in evidence],
        f"Context summary: {context_summary}" if context_summary else "",
        "Document refs:",
        *[f"- {ref}" for ref in doc_refs],
    ]
    doc_text = "\n".join(part for part in doc_text_parts if part).strip()
    if decoded and decoded not in doc_text:
        doc_text += "\nDecoded payload excerpt: " + _compact_text(decoded, 500)

    doc_key = make_document_key(task_group, sub_query, doc_text)
    store_put(
        store,
        NS_DOCS,
        doc_key,
        {
            "text": doc_text,
            "sub_query": sub_query,
            "task_group": task_group,
            "evidence": evidence,
            "document_refs": doc_refs,
            "mode": "latent_kv",
        },
        memory_type="document",
        source_agent="researcher_latent",
        task_group=task_group,
        task_topic=sub_query,
        summary=summarize_text(doc_text, 240),
        tags=["document", "researcher", "latent_kv", task_group, *sub_query.split()[:6]],
    )

    context_packet = build_context_packet(
        doc_key=doc_key,
        sub_query=sub_query,
        doc_text=doc_text,
        task_group=task_group,
        embedding_ref=doc_key,
    )
    context_packet["explicit_evidence"] = evidence
    context_packet["document_refs"] = doc_refs
    if context_summary:
        context_packet["researcher_summary"] = context_summary

    document_payload = {
        "doc_key": doc_key,
        "sub_query": sub_query,
        "text_hash": hash_text(doc_text),
        "original_chars": len(doc_text),
        "document_refs": doc_refs,
    }
    research_evidence = {
        "doc_key": doc_key,
        "sub_query": sub_query,
        "evidence": evidence,
        "document_refs": doc_refs,
    }
    msg = make_message(
        source="researcher_latent",
        target="analyst_latent",
        action=ActionType.RESEARCH,
        params={"sub_query": sub_query, "doc_key": doc_key},
        result={
            "doc_key": doc_key,
            "summary": context_packet.get("summary", ""),
            "evidence_count": len(evidence),
            "document_refs": doc_refs,
            "context_packet": True,
        },
        task_group=task_group,
    )
    metrics.record_message(
        source="researcher_latent",
        target="analyst_latent",
        action="research",
        param_chars=len(sub_query) + len(doc_key),
        result_chars=len(context_packet.get("summary", "")) + sum(len(e) for e in evidence),
        has_embedding=False,
    )
    metrics.record_context_compression(
        original_chars=len(doc_text),
        compressed_chars=context_packet["compressed_chars"],
        source="researcher_latent",
    )

    _best_effort_delete(runtime, handle.handle_id)
    duration = time.perf_counter() - t0
    metrics.record_timing("node_researcher_latent", duration)
    return {
        "context_packets": [context_packet],
        "document_payloads": [document_payload],
        "research_evidence": [research_evidence],
        "messages": [msg.to_dict()],
    }


def researchers_latent(state: dict, store: BaseStore) -> dict:
    """Sequential researcher fan-in for real latent KV mode.

    The real HuggingFace server stores mutable GPU KV handles and is not robust
    under parallel requests that inject from the same parent handle. This node
    preserves the multi-researcher semantics while running them sequentially on
    one cumulative KV chain.
    """
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "latent_kv")
    sub_queries = _normalize_sub_queries(query, state.get("sub_queries", []))
    plan = state.get("plan", "")
    source_context = state.get("source_context", "")
    current_handle_id = state.get("latent_kv_handle_id")
    runtime = get_latent_kv_runtime()

    all_packets: list[dict] = []
    all_payloads: list[dict] = []
    all_evidence: list[dict] = []
    all_messages: list[dict] = []

    for index, sub_query in enumerate(sub_queries, 1):
        role_payload = (
            f"\n<|agent_researcher_{index}|>\n"
            "Use latent reasoning to inspect the assigned sub-query. "
            "Emit only compact evidence, a Context Packet summary, and document references.\n"
            f"# Sub Query\n{sub_query}\n"
            + (f"# Planner Plan\n{_compact_text(plan, 700)}\n" if plan else "")
            + (f"# Source Context\n{_compact_text(source_context, 1200)}\n" if source_context else "")
        )
        if current_handle_id:
            handle = runtime.inject_role_transition(current_handle_id, role_payload)
        else:
            handle = runtime.prefill(role_payload, task_group, created_by="researcher_prefill")

        handle = runtime.run_latent_steps(
            handle.handle_id,
            RESEARCHER_LATENT_STEPS,
            f"researcher_{index}",
        )
        instruction = (
            "\nDecode the explicit researcher payload only. Return valid JSON with exactly:\n"
            "{"
            '"evidence":["short factual evidence 1","short factual evidence 2","short factual evidence 3"],'
            '"context_packet":{"summary":"compact query-focused summary","coverage":"what this evidence covers"},'
            '"document_refs":["source/ref/id 1","source/ref/id 2"]'
            "}\n"
            "No long analysis prose."
        )
        decoded, handle = runtime.decode_text(
            handle.handle_id,
            instruction,
            max_tokens=512,
            temperature=0.1,
            metric_name=f"researcher_{index}_latent_decode",
        )
        parsed = _extract_json_object(decoded)
        if not isinstance(parsed, dict):
            parsed = {}

        evidence = _coerce_text_list(
            parsed.get("evidence"),
            fallback=_fallback_evidence(decoded, sub_query),
            max_items=5,
            max_chars=240,
        )
        context_obj = parsed.get("context_packet") if isinstance(parsed.get("context_packet"), dict) else {}
        context_summary = _compact_text(context_obj.get("summary", ""), 420)
        doc_refs = _coerce_text_list(
            parsed.get("document_refs"),
            fallback=[f"latent_research:{task_group}:{hash_text(sub_query)}"],
            max_items=4,
            max_chars=180,
        )

        doc_text_parts = [
            f"Sub-query: {sub_query}",
            f"Planner context: {_compact_text(plan, 500)}" if plan else "",
            "Evidence:",
            *[f"- {item}" for item in evidence],
            f"Context summary: {context_summary}" if context_summary else "",
            "Document refs:",
            *[f"- {ref}" for ref in doc_refs],
        ]
        doc_text = "\n".join(part for part in doc_text_parts if part).strip()
        if decoded and decoded not in doc_text:
            doc_text += "\nDecoded payload excerpt: " + _compact_text(decoded, 500)

        doc_key = make_document_key(task_group, sub_query, doc_text)
        store_put(
            store,
            NS_DOCS,
            doc_key,
            {
                "text": doc_text,
                "sub_query": sub_query,
                "task_group": task_group,
                "evidence": evidence,
                "document_refs": doc_refs,
                "mode": "latent_kv",
                "researcher_index": index,
            },
            memory_type="document",
            source_agent="researchers_latent",
            task_group=task_group,
            task_topic=sub_query,
            summary=summarize_text(doc_text, 240),
            tags=["document", "researcher", "latent_kv", task_group, *sub_query.split()[:6]],
        )

        context_packet = build_context_packet(
            doc_key=doc_key,
            sub_query=sub_query,
            doc_text=doc_text,
            task_group=task_group,
            embedding_ref=doc_key,
        )
        context_packet["explicit_evidence"] = evidence
        context_packet["document_refs"] = doc_refs
        context_packet["researcher_index"] = index
        if context_summary:
            context_packet["researcher_summary"] = context_summary

        document_payload = {
            "doc_key": doc_key,
            "sub_query": sub_query,
            "text_hash": hash_text(doc_text),
            "original_chars": len(doc_text),
            "document_refs": doc_refs,
            "researcher_index": index,
        }
        research_evidence = {
            "doc_key": doc_key,
            "sub_query": sub_query,
            "evidence": evidence,
            "document_refs": doc_refs,
            "researcher_index": index,
        }
        msg = make_message(
            source="researchers_latent",
            target="analyst_latent",
            action=ActionType.RESEARCH,
            params={"sub_query": sub_query, "doc_key": doc_key, "researcher_index": index},
            result={
                "doc_key": doc_key,
                "summary": context_packet.get("summary", ""),
                "evidence_count": len(evidence),
                "document_refs": doc_refs,
                "context_packet": True,
            },
            task_group=task_group,
        )
        metrics.record_message(
            source="researchers_latent",
            target="analyst_latent",
            action="research",
            param_chars=len(sub_query) + len(doc_key),
            result_chars=len(context_packet.get("summary", "")) + sum(len(e) for e in evidence),
            has_embedding=False,
        )
        metrics.record_context_compression(
            original_chars=len(doc_text),
            compressed_chars=context_packet["compressed_chars"],
            source="researchers_latent",
        )

        all_packets.append(context_packet)
        all_payloads.append(document_payload)
        all_evidence.append(research_evidence)
        all_messages.append(msg.to_dict())
        current_handle_id = handle.handle_id

    duration = time.perf_counter() - t0
    metrics.record_timing("node_researchers_latent", duration)
    return {
        "latent_kv_handle_id": current_handle_id,
        "context_packets": all_packets,
        "document_payloads": all_payloads,
        "research_evidence": all_evidence,
        "messages": all_messages,
    }


def analyst_latent(state: dict, store: BaseStore) -> dict:
    """Analyst runs latent KV steps without generating text.

    Input: explicit planner/researcher packet metadata, or an inherited KV chain
    Output: Delta KV handle ID for executor
    """
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "latent_kv")
    parent_handle_id = state.get("latent_kv_handle_id")
    runtime = get_latent_kv_runtime()

    analyst_material, selected_packets, research_evidence = _build_analyst_material(state)
    if parent_handle_id:
        handle = runtime.inject_role_transition(parent_handle_id, "\n<|agent_analyst|>\n")
        handle = runtime.inject_result_text(handle.handle_id, analyst_material)
    else:
        handle = runtime.prefill(analyst_material, task_group, created_by="analyst_prefill")

    # Run analyst latent steps
    handle = runtime.run_latent_steps(handle.handle_id, ANALYST_LATENT_STEPS, "analyst")

    # Store minimal metadata
    store_put(
        store,
        NS_ANALYSIS,
        f"latent_analysis_{task_group}_{hash_text(query)}",
        {
            "query": query,
            "latent_kv_handle_id": handle.handle_id,
            "latent_steps": ANALYST_LATENT_STEPS,
            "mode": "latent_kv",
            "kv_bytes": handle.kv_bytes,
            "selected_context_packets": [
                {
                    "doc_key": packet.get("doc_key", ""),
                    "source_query": packet.get("source_query", ""),
                    "score": packet.get("score", 0),
                }
                for packet in selected_packets
            ],
        },
        memory_type="analysis",
        source_agent="analyst_latent",
        task_group=task_group,
        task_topic=query,
        summary=f"[Delta KV analyst] {ANALYST_LATENT_STEPS} latent steps",
        tags=["analysis", "latent_kv", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_analyst_latent", duration)

    return {
        "latent_kv_handle_id": handle.handle_id,
        "analysis": "",  # No text in latent mode
        "analysis_digest": (
            f"[Delta KV analyst: {ANALYST_LATENT_STEPS} latent steps, "
            f"{handle.kv_bytes // 1024} KB]"
        ),
        "candidate_answers": {},
        "evidence": research_evidence,
        "selected_context_packets": selected_packets,
    }


def executor_latent(state: dict, store: BaseStore) -> dict:
    """Executor inherits analyst KV, runs latent steps + CodeAct.

    Input: latent KV handle from analyst
    Output: execution result + updated KV handle
    """
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "latent_kv")
    handle_id = state.get("latent_kv_handle_id")

    if not handle_id:
        raise ValueError("No latent_kv_handle_id in state")

    runtime = get_latent_kv_runtime()

    # Inject executor role token
    handle = runtime.inject_role_transition(handle_id, "\n<|agent_executor|>\n")

    # Executor latent reasoning steps
    handle = runtime.run_latent_steps(handle.handle_id, EXECUTOR_LATENT_STEPS, "executor")

    no_code_executor = _requires_no_code_executor(query)
    # Prefer deterministic tool code for exact arithmetic tasks. Fall back to
    # model-generated CodeAct for open-ended tasks. Some reasoning benchmarks
    # explicitly forbid executor code/tools; for those, emit only an evidence
    # synthesis artifact.
    code = "" if no_code_executor else _build_classified_data_audit_program(query)
    if no_code_executor:
        handle = runtime.inject_result_text(
            handle.handle_id,
            "\n<executor_mode>no_code_evidence_synthesis</executor_mode>\n",
        )
    elif code:
        handle = runtime.inject_result_text(
            handle.handle_id,
            "\n<executor_tool>classified_data_audit_scorer</executor_tool>\n",
        )
    else:
        code, handle = runtime.generate_code(handle.handle_id, max_tokens=256)

    # Execute in sandbox unless the task explicitly forbids code/tools.
    if no_code_executor:
        result = _build_no_code_execution_result(
            evidence=state.get("evidence", []) or [],
            selected_context_packets=state.get("selected_context_packets", []) or [],
            analysis=state.get("analysis", ""),
        )
    else:
        result = _run_safe_python(code)

    # Inject result back into KV chain
    result_text = json.dumps(result, ensure_ascii=False)
    handle = runtime.inject_result_text(handle.handle_id, result_text)

    # Post-execution latent steps
    handle = runtime.run_latent_steps(handle.handle_id, POST_EXEC_LATENT_STEPS, "executor_post")

    final_answer, extracted_answers = _build_final_answer(
        query=query,
        candidate_answers={},
        analysis="",
        execution_result=result,
    )
    if final_answer:
        result["final_answer"] = final_answer
        result["extracted_answers"] = extracted_answers
    execution_summary = _summarize_execution_result(result)

    # Store execution metadata
    store_put(
        store,
        NS_EXECUTIONS,
        f"latent_execution_{task_group}_{hash_text(query)}",
        {
            "query": query,
            "execution_code": code,
            "execution_result": result,
            "execution_summary": execution_summary,
            "final_answer": final_answer,
            "extracted_answers": extracted_answers,
            "latent_kv_handle_id": handle.handle_id,
            "latent_steps": EXECUTOR_LATENT_STEPS + POST_EXEC_LATENT_STEPS,
            "mode": "latent_kv",
        },
        memory_type="execution",
        source_agent="executor_latent",
        task_group=task_group,
        task_topic=query,
        summary=f"[Latent KV] {EXECUTOR_LATENT_STEPS} + {POST_EXEC_LATENT_STEPS} steps",
        tags=["execution", "latent_kv", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_executor_latent", duration)

    return {
        "latent_kv_handle_id": handle.handle_id,
        "execution_code": code,
        "execution_result": result,
        "execution_summary": execution_summary,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
    }


def summarizer_latent(state: dict, store: BaseStore) -> dict:
    """Summarizer inherits full KV chain, generates final natural language.

    Input: latent KV handle from executor
    Output: final summary (first natural language output)
    """
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "latent_kv")
    handle_id = state.get("latent_kv_handle_id")

    if not handle_id:
        raise ValueError("No latent_kv_handle_id in state")

    runtime = get_latent_kv_runtime()

    # Inject summarizer role token
    handle = runtime.inject_role_transition(handle_id, "\n<|agent_summarizer|>\n")

    if SUMMARIZER_LATENT_STEPS > 0:
        handle = runtime.run_latent_steps(
            handle.handle_id,
            SUMMARIZER_LATENT_STEPS,
            "summarizer",
        )

    # Generate final summary (natural language decoding)
    instruction = (
        "You are the final summarizer. Decode the final answer from the inherited "
        "analyst and executor latent KV state.\n"
        "If the task specifies a required JSON answer contract, output only that JSON. "
        "Otherwise provide a concise final answer.\n"
        f"Task:\n{query}\n"
    )
    summary, handle = runtime.generate_summary(handle.handle_id, instruction, max_tokens=512)

    # Extract key findings (placeholder)
    key_findings = [
        f"使用 latent KV 模式完成分析",
        f"summarizer latent steps: {SUMMARIZER_LATENT_STEPS}",
        f"总共 {handle.seq_len} 个序列位置",
        f"KV cache 大小: {handle.kv_bytes // 1024} KB",
    ]

    # Get final answer from executor, then normalize the decoded summary through
    # the same JSON contract path used by text/structured modes.
    final_answer = state.get("final_answer", "")
    extracted_answers = state.get("extracted_answers", {})
    json_contract_fields = _extract_json_final_contract_fields(query)
    if json_contract_fields:
        contract_answer = _clean_json_contract_answer(final_answer, json_contract_fields)
        contract_answer.update({
            key: value
            for key, value in _clean_json_contract_answer(summary, json_contract_fields).items()
            if key not in contract_answer
        })
        if contract_answer:
            for field in json_contract_fields:
                contract_answer.setdefault(field, "")
            final_answer = _json_contract_answer_to_text(contract_answer, json_contract_fields)
            extracted_answers = contract_answer

    # Store summary
    store_put(
        store,
        NS_SUMMARIES,
        f"latent_summary_{task_group}_{hash_text(query)}",
        {
            "query": query,
            "summary": summary,
            "key_findings": key_findings,
            "final_answer": final_answer,
            "latent_kv_handle_id": handle.handle_id,
            "latent_steps": SUMMARIZER_LATENT_STEPS,
            "mode": "latent_kv",
        },
        memory_type="summary",
        source_agent="summarizer_latent",
        task_group=task_group,
        task_topic=query,
        summary=summary[:200],
        tags=["summary", "latent_kv", task_group],
    )

    # Release the final server-side handle after task completion.
    _best_effort_delete(runtime, handle.handle_id)

    duration = time.perf_counter() - t0
    metrics.record_timing("node_summarizer_latent", duration)

    return {
        "summary": summary,
        "key_findings": key_findings,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
    }
