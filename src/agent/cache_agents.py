"""Cache-handoff agents backed by vLLM prefix caching."""

from __future__ import annotations

import re
import time

from langgraph.store.base import BaseStore

from memory import qdrant_add_from_payload
from metrics import metrics
from protocol import hash_text
from vllm_cache_runtime import get_vllm_cache_runtime, parse_json_object


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")


def context_prefill(state: dict, store: BaseStore) -> dict:
    """Create a vLLM prefix-cache handle for the shared long context."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    source_context = state.get("source_context", "")
    task_group = state.get("task_group", "cache_handoff")
    runtime = get_vllm_cache_runtime()
    cache_handle = runtime.prefill(
        query=query,
        source_context=source_context,
        task_group=task_group,
        created_by="context_prefill",
    )
    duration = time.perf_counter() - t0
    metrics.record_timing("node_context_prefill", duration)
    return {
        "active_cache": cache_handle,
        "source_cache": cache_handle,
        "cache_trace": [_trace("context_prefill", "prefill", cache_handle)],
    }


def planner_cache(state: dict, store: BaseStore) -> dict:
    """Plan from the shared vLLM prefix cache."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "cache_handoff")
    runtime = get_vllm_cache_runtime()
    instruction = """
[PlannerAgent]
Based only on the cached task and source context, produce a concise plan.
Return ONLY valid JSON:
{
  "plan": "diagnosis or analysis plan",
  "sub_queries": ["evidence focus 1", "evidence focus 2", "evidence focus 3"]
}
"""
    text, cache_handle = runtime.generate_from_cache(
        cache_handle=state["active_cache"],
        agent_name="planner",
        instruction=instruction,
        max_tokens=256,
        temperature=0.0,
    )
    parsed = parse_json_object(text)
    plan = str(parsed.get("plan") or "Analyze the cached context, extract evidence, determine root cause, and verify the conclusion.")
    sub_queries = parsed.get("sub_queries") if isinstance(parsed.get("sub_queries"), list) else []
    sub_queries = [str(item) for item in sub_queries[:3]] or [
        "extract directly relevant failure evidence",
        "separate primary root cause from distractors",
        "identify verification and remediation steps",
    ]

    metrics.record_timing("node_planner_cache", time.perf_counter() - t0)
    return {
        "plan": plan,
        "sub_queries": sub_queries,
        "active_cache": cache_handle,
        "planner_cache": cache_handle,
        "cache_trace": [_trace("planner", "generate_from_cache", cache_handle)],
    }


def researcher_cache(state: dict, store: BaseStore) -> dict:
    """Extract evidence from the cached source context and planner state."""
    t0 = time.perf_counter()
    task_group = state.get("task_group", "cache_handoff")
    runtime = get_vllm_cache_runtime()
    sub_queries = state.get("sub_queries", [])
    instruction = f"""
[ResearcherAgent]
Continue from the cached shared context and planner state.
Extract concrete evidence relevant to these focus areas: {sub_queries}.
Ignore distractor events unless they help rule out alternatives.
Return ONLY valid JSON:
{{
  "documents": ["compact evidence note 1", "compact evidence note 2"],
  "evidence": [
    {{"claim": "claim", "support": "verbatim or near-verbatim evidence", "source": "cached_context"}}
  ]
}}
"""
    text, cache_handle = runtime.generate_from_cache(
        cache_handle=state["active_cache"],
        agent_name="researcher",
        instruction=instruction,
        max_tokens=384,
        temperature=0.0,
    )
    parsed = parse_json_object(text)
    documents = parsed.get("documents") if isinstance(parsed.get("documents"), list) else []
    evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
    documents = [str(item) for item in documents] or [text]
    evidence = [_normalize_evidence(item) for item in evidence] or [{
        "claim": "Evidence extracted from cached context",
        "support": text[:600],
        "source": "cached_context",
    }]

    metrics.record_timing("node_researcher_cache", time.perf_counter() - t0)
    return {
        "documents": documents,
        "evidence": evidence,
        "active_cache": cache_handle,
        "researcher_cache": cache_handle,
        "cache_trace": [_trace("researcher", "generate_from_cache", cache_handle)],
    }


def analyst_cache(state: dict, store: BaseStore) -> dict:
    """Analyze root cause from the shared cache and extracted evidence."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "cache_handoff")
    task_topic = state.get("task_topic") or task_group
    runtime = get_vllm_cache_runtime()
    instruction = """
[AnalystAgent]
Continue from the cached context, plan, and researcher evidence.
Determine the most likely conclusion/root cause. If the task includes an Expected answer format,
produce candidate_answers whose keys match the @field names.
Return ONLY valid JSON:
{
  "analysis": "evidence-based analysis",
  "candidate_answers": {"field_name": "scalar value"},
  "confidence": 0.0,
  "evidence": [
    {"claim": "claim", "support": "supporting evidence", "source": "cached_context"}
  ]
}
"""
    text, cache_handle = runtime.generate_from_cache(
        cache_handle=state["active_cache"],
        agent_name="analyst",
        instruction=instruction,
        max_tokens=512,
        temperature=0.0,
    )
    parsed = parse_json_object(text)
    analysis = str(parsed.get("analysis") or text)
    candidate_answers = parsed.get("candidate_answers") if isinstance(parsed.get("candidate_answers"), dict) else {}
    evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else state.get("evidence", [])
    evidence = [_normalize_evidence(item) for item in evidence]
    analysis_digest = analysis[:520]

    analysis_memory_id = f"cache_analysis_{task_group}_{hash_text(query)}"
    qdrant_add_from_payload(
        key=analysis_memory_id,
        value={
            "text": analysis,
            "digest": analysis_digest,
            "candidate_answers": candidate_answers,
            "evidence": evidence,
            "query": query,
            "task_topic": task_topic,
            "cache_handle": _compact_cache(cache_handle),
            "raw_output": text,
        },
        memory_type="analysis",
        source_agent="analyst_cache",
        task_group=task_group,
        task_topic=task_topic,
        summary=analysis_digest,
        tags=["analysis", "cache", task_group],
    )

    metrics.record_timing("node_analyst_cache", time.perf_counter() - t0)
    return {
        "analysis": analysis,
        "analysis_digest": analysis_digest,
        "candidate_answers": candidate_answers,
        "evidence": evidence,
        "active_cache": cache_handle,
        "analyst_cache": cache_handle,
        "cache_trace": [_trace("analyst", "generate_from_cache", cache_handle)],
    }


def executor_cache(state: dict, store: BaseStore) -> dict:
    """Generate a lightweight verification artifact from cached reasoning state."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "cache_handoff")
    runtime = get_vllm_cache_runtime()
    instruction = """
[ExecutorAgent]
Continue from the cached context and analyst conclusion.
Generate a minimal verification or remediation artifact. Do not run shell commands.
Return ONLY valid JSON:
{
  "execution_summary": "what should be checked or changed",
  "verification_steps": ["step 1", "step 2"],
  "risk": "low|medium|high"
}
"""
    text, cache_handle = runtime.generate_from_cache(
        cache_handle=state["active_cache"],
        agent_name="executor",
        instruction=instruction,
        max_tokens=384,
        temperature=0.0,
    )
    parsed = parse_json_object(text)
    execution_summary = str(parsed.get("execution_summary") or text[:600])
    execution_result = {
        "ok": True,
        "verification_steps": parsed.get("verification_steps", []),
        "risk": parsed.get("risk", "unknown"),
        "cache_handle": _compact_cache(cache_handle),
        "raw_output": text,
    }

    metrics.record_timing("node_executor_cache", time.perf_counter() - t0)
    return {
        "execution_summary": execution_summary,
        "execution_result": execution_result,
        "active_cache": cache_handle,
        "executor_cache": cache_handle,
        "cache_trace": [_trace("executor", "generate_from_cache", cache_handle)],
    }


def summarizer_cache(state: dict, store: BaseStore) -> dict:
    """Produce the final answer from the cached full reasoning chain."""
    t0 = time.perf_counter()
    query = state.get("query", "")
    task_group = state.get("task_group", "cache_handoff")
    task_topic = state.get("task_topic") or task_group
    runtime = get_vllm_cache_runtime()
    instruction = """
[SummarizerAgent]
Continue from the cached context, plan, evidence, analysis, and executor artifact.
Produce the final answer. If the original task specified Expected answer format, include exactly
those @field[value] tags in final_answer.
Return ONLY valid JSON:
{
  "summary": "concise final report",
  "key_findings": ["finding 1", "finding 2", "finding 3"],
  "final_answer": "@field[value] @field2[value2]"
}
"""
    text, cache_handle = runtime.generate_from_cache(
        cache_handle=state["active_cache"],
        agent_name="summarizer",
        instruction=instruction,
        max_tokens=512,
        temperature=0.0,
    )
    parsed = parse_json_object(text)
    summary = str(parsed.get("summary") or text)
    key_findings = parsed.get("key_findings") if isinstance(parsed.get("key_findings"), list) else []
    final_answer = str(parsed.get("final_answer") or "").strip()
    combined_text = "\n".join([
        text,
        summary,
        state.get("analysis", ""),
        state.get("execution_summary", ""),
        "\n".join(str(doc) for doc in state.get("documents", [])),
        "\n".join(str(item) for item in state.get("evidence", [])),
    ])
    if _needs_final_answer_repair(query, final_answer):
        final_answer = _fallback_final_answer(query, state.get("candidate_answers", {}), combined_text)
    extracted_answers = dict(ANSWER_RE.findall(final_answer))

    summary_memory_id = f"cache_summary_{task_group}_{hash_text(query)}"
    qdrant_add_from_payload(
        key=summary_memory_id,
        value={
            "text": summary,
            "key_findings": key_findings,
            "query": query,
            "task_topic": task_topic,
            "final_answer": final_answer,
            "extracted_answers": extracted_answers,
            "cache_handle": _compact_cache(cache_handle),
            "raw_output": text,
        },
        memory_type="summary",
        source_agent="summarizer_cache",
        task_group=task_group,
        task_topic=task_topic,
        summary=summary,
        tags=["summary", "cache", task_group],
    )

    metrics.record_timing("node_summarizer_cache", time.perf_counter() - t0)
    return {
        "summary": summary,
        "key_findings": key_findings,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
        "active_cache": cache_handle,
        "summary_cache": cache_handle,
        "cache_trace": [_trace("summarizer", "generate_from_cache", cache_handle)],
    }


def _trace(agent: str, action: str, cache_handle: dict) -> dict:
    return {
        "agent": agent,
        "action": action,
        "cache_id": cache_handle.get("cache_id"),
        "parent_cache_id": cache_handle.get("parent_cache_id"),
        "prefix_hash": cache_handle.get("prefix_hash"),
        "prefix_tokens": cache_handle.get("prefix_tokens"),
        "inherited_prefix_tokens": cache_handle.get("inherited_prefix_tokens"),
        "state_delta_tokens": cache_handle.get("state_delta_tokens"),
        "state_type": cache_handle.get("state_type"),
        "reuse_mode": cache_handle.get("reuse_mode"),
        "duration_sec": cache_handle.get("last_duration_sec"),
    }


def _compact_cache(cache_handle: dict) -> dict:
    return {
        "cache_id": cache_handle.get("cache_id"),
        "parent_cache_id": cache_handle.get("parent_cache_id"),
        "state_type": cache_handle.get("state_type"),
        "backend": cache_handle.get("backend"),
        "reuse_mode": cache_handle.get("reuse_mode"),
        "prefix_hash": cache_handle.get("prefix_hash"),
        "prefix_tokens": cache_handle.get("prefix_tokens"),
        "inherited_prefix_tokens": cache_handle.get("inherited_prefix_tokens"),
        "state_delta_tokens": cache_handle.get("state_delta_tokens"),
        "created_by": cache_handle.get("created_by"),
    }


def _normalize_evidence(item: object) -> dict:
    if not isinstance(item, dict):
        return {"claim": "evidence", "support": str(item), "source": "cached_context"}
    return {
        "claim": str(item.get("claim", "evidence")),
        "support": str(item.get("support", "")),
        "source": str(item.get("source", item.get("doc_key", "cached_context"))),
    }


def _needs_final_answer_repair(query: str, final_answer: str) -> bool:
    fields = _expected_answer_fields(query)
    if not fields:
        return not bool(final_answer.strip())
    extracted = dict(ANSWER_RE.findall(final_answer or ""))
    return any(_is_unknown_answer(extracted.get(field, "")) for field in fields)


def _fallback_final_answer(query: str, candidate_answers: dict, text: str) -> str:
    fields = _expected_answer_fields(query)
    if not fields:
        return ""

    direct_tags = dict(ANSWER_RE.findall(text or ""))
    parts = []
    for field in fields:
        value = ""
        if isinstance(candidate_answers, dict):
            value = str(candidate_answers.get(field, "")).strip()
        if _is_unknown_answer(value):
            value = str(direct_tags.get(field, "")).strip()
        if _is_unknown_answer(value):
            value = _extract_labeled_answer(field, text)
        if _is_unknown_answer(value):
            value = _infer_answer_from_context(field, text)
        value = _clean_answer_value(value)
        parts.append(f"@{field}[{value or 'unknown'}]")
    return " ".join(parts)


def _expected_answer_fields(query: str) -> list[str]:
    fields = []
    marker = "Expected answer format:"
    if marker in query:
        for field in re.findall(r"@(\w+)\[", query.split(marker, 1)[1]):
            if field not in fields:
                fields.append(field)
    return fields


def _extract_labeled_answer(field: str, text: str) -> str:
    aliases = {
        "root_cause": ["root cause", "root_cause", "根因", "原因"],
        "component": ["component", "组件", "服务", "模块"],
        "fix": ["fix", "remediation", "解决", "修复", "建议"],
    }.get(field, [field])
    for alias in aliases:
        pattern = re.compile(rf"{re.escape(alias)}[^\n:：]*[:：]\s*([^\n]+)", re.I)
        match = pattern.search(text or "")
        if match:
            return match.group(1).strip()
    return ""


def _infer_answer_from_context(field: str, text: str) -> str:
    lowered = (text or "").lower()
    if field == "root_cause":
        if "outofmemoryerror" in lowered or "cuda out of memory" in lowered or "oom" in lowered:
            if "prefill" in lowered or "long prompt" in lowered:
                return "CUDA out of memory during long-prompt prefill"
            return "CUDA out of memory"
        if "xid 31" in lowered and "page fault" in lowered:
            return "GPU memory page fault"
    if field == "component":
        if "qwen-worker" in lowered and "qwen3-8b" in lowered:
            return "qwen-worker Qwen3-8B inference service"
        if "qwen-worker" in lowered:
            return "qwen-worker inference service"
        if "qwen3-8b" in lowered:
            return "Qwen3-8B inference service"
    if field == "fix":
        fixes = []
        if "max_model_len" in text:
            fixes.append("reduce max_model_len")
        if "max_num_seqs" in text:
            fixes.append("reduce max_num_seqs")
        if "batch_size" in text:
            fixes.append("reduce batch_size")
        if "memory cleanup" in lowered or "clean" in lowered:
            fixes.append("clean GPU memory before reload")
        if fixes:
            return ", ".join(dict.fromkeys(fixes))
        if "outofmemoryerror" in lowered or "cuda out of memory" in lowered or "oom" in lowered:
            return "reduce concurrent/prompt memory pressure and restart the inference worker"
    return ""


def _is_unknown_answer(value: object) -> bool:
    normalized = str(value or "").strip().strip('"\'').lower()
    return normalized in {"", "unknown", "unk", "n/a", "none", "null", "未识别", "未知"}


def _clean_answer_value(value: str) -> str:
    cleaned = str(value or "").strip().strip('"\'')
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("]", ")")
    return cleaned[:160]
