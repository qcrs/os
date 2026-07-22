"""Summarizer agent for producing final research outputs."""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.store.base import BaseStore

from config import NS_SUMMARIES, PERSISTENT_MEMORY_ENABLED
from memory import qdrant_add_from_payload, store_put
from metrics import metrics
from models import get_model
from protocol import ActionType, hash_text, make_message

from .shared import _get_mode


# ─── Summarizer Agent ───


def summarizer(state: dict, store: BaseStore) -> dict:
    """Produce a final summary with key findings.

    Structured mode reads the analyst digest and executor artifact instead of
    the full analysis when constructing the summarizer prompt.
    """
    t0 = time.perf_counter()
    mode = _get_mode(state)

    query = state.get("query", "")
    plan = state.get("plan", "")
    analysis = state.get("analysis", "")
    analysis_digest = state.get("analysis_digest", "")
    evidence = state.get("evidence", [])
    execution_summary = state.get("execution_summary", "")
    execution_result = state.get("execution_result", {})
    final_answer = state.get("final_answer", "")
    extracted_answers = state.get("extracted_answers", {})
    task_group = state.get("task_group", "default")
    task_topic = state.get("task_topic") or task_group

    model = get_model(temperature=0.5)
    parser = JsonOutputParser()

    evidence_text = "\n".join(
        f"- {e.get('claim', '')}: {e.get('support', '')}"
        + (f" [{e.get('doc_key')}]" if e.get("doc_key") else "")
        for e in evidence
    ) if evidence else "No evidence available."
    analysis_for_prompt = analysis_digest if mode == "structured" and analysis_digest else analysis
    execution_text = _format_execution_context(execution_summary, execution_result)

    system_prompt = """You are a research summarizer. Given all the
research materials, produce a clear final summary that directly answers the
original user task. The executor may provide a machine-evaluation answer, but
your `summary` field is for human-readable reporting and is not used for
automatic grading.

Return ONLY valid JSON:
{
  "summary": "A concise executive summary (3-5 paragraphs)",
  "key_findings": ["Finding 1", "Finding 2", "Finding 3"],
  "recommendations": ["Recommendation 1", "Recommendation 2"]
}"""
    format_instruction = "Write a natural summary. Do not force @field[value] tags unless they are useful in prose."

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""Original query: {query}
{format_instruction}
Research plan: {plan}
Analysis: {analysis_for_prompt}
Evidence:
{evidence_text}
Executor CodeAct result:
{execution_text}
Executor final answer for machine evaluation: {final_answer or 'N/A'}"""),
    ]

    response = model.invoke(messages)
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        metrics.record_tokens("summarizer", um.get("input_tokens", 0), um.get("output_tokens", 0))
    try:
        parsed = parser.invoke(response)
    except Exception:
        parsed = {
            "summary": f"Summary of research on: {query}",
            "key_findings": ["Key finding from the research"],
            "recommendations": ["Further investigation recommended"],
        }

    summary = str(parsed.get("summary", "")).strip()
    key_findings = parsed.get("key_findings", [])
    recommendations = parsed.get("recommendations", [])
    summary_memory_id = f"summary_{task_group}_{hash_text(query or summary)}"

    summary_memory_payload = {
        "text": summary,
        "key_findings": key_findings,
        "recommendations": recommendations,
        "query": query,
        "execution_summary": execution_summary,
        "execution_result": execution_result,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
        "task_topic": task_topic,
    }
    qdrant_add_from_payload(
        key=summary_memory_id,
        value=summary_memory_payload,
        memory_type="summary",
        source_agent="summarizer",
        task_group=task_group,
        task_topic=task_topic,
        summary=summary,
        tags=["summary", "summarizer", task_group],
    )
    if PERSISTENT_MEMORY_ENABLED:
        store_put(
            store,
            NS_SUMMARIES,
            summary_memory_id,
            summary_memory_payload,
            memory_type="summary",
            source_agent="summarizer",
            task_group=task_group,
            task_topic=task_topic,
            summary=summary,
            tags=["summary", "summarizer", task_group],
        )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_summarizer", duration)

    result = {
        "summary": summary,
        "key_findings": key_findings,
        "final_answer": final_answer,
        "extracted_answers": extracted_answers,
    }
    if mode == "structured":
        msg = make_message(
            source="summarizer", target="output",
            action=ActionType.SUMMARIZE,
            params={
                "analysis_chars": len(analysis_for_prompt),
                "evidence_count": len(evidence),
                "execution_summary_chars": len(execution_summary),
            },
            result={
                "summary_chars": len(summary),
                "final_answer_chars": len(final_answer),
                "finding_count": len(key_findings),
            },
            task_group=task_group,
        )
        metrics.record_message(
            source="summarizer", target="output", action="summarize",
            param_chars=len(analysis_for_prompt) + len(execution_text), result_chars=len(summary),
            has_embedding=False,
        )
        result["messages"] = [msg.to_dict()]

    return result


def _format_execution_context(execution_summary: str, execution_result: dict) -> str:
    """Render executor output for the summarizer prompt."""
    if not execution_summary and not execution_result:
        return "No executor artifact available."
    metrics_payload = execution_result.get("metrics", {}) if isinstance(execution_result, dict) else {}
    stdout = execution_result.get("stdout", "") if isinstance(execution_result, dict) else ""
    error = execution_result.get("error", "") if isinstance(execution_result, dict) else ""
    parts = []
    if execution_summary:
        parts.append(f"Summary: {execution_summary}")
    if metrics_payload:
        parts.append(f"Metrics: {metrics_payload}")
    if stdout:
        parts.append(f"Stdout: {stdout}")
    if error:
        parts.append(f"Error: {error}")
    return "\n".join(parts) if parts else "No executor artifact available."
