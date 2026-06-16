from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import msgpack

from agents.base_agent import BaseAgent
from protocol.messages import (
    Capability,
    CapabilityItem,
    ChannelPatch,
    ChannelSnapshot,
    MemoryCommit,
    Plan,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StepResult,
)
from runtime.executor_runtime import (
    _build_natural_handoff_text,
    _build_text_packet_minimal,
    build_executor_decision_packet,
    build_feature_bundle,
    build_ranked_evidence_bundle,
    build_replay_eligibility_bundle,
    build_tool_candidate_set,
    execute_playbook_step,
)
from runtime.llm import (
    ChatMessage,
    DeterministicLLMClient,
    LLMClient,
    extract_json_object,
    tagged_json_block,
)
from runtime.uds_transport import request_response
from tasks.local_corpus import (
    extract_corpus_feature_hints,
    render_corpus_evidence,
    retrieve_corpus_docs,
)
from tasks.sample_tasks import TaskSetMetadata
from tasks.sample_tasks import SampleTask

PROTOCOL_PLANNER_TAG = "sb-plan-v1"
PROTOCOL_SUMMARIZER_TAG = "sb-summary-v1"
MAX_MEMORY_ASSIST_HINT_CHARS = 160
MAX_PROTOCOL_SUMMARY_DOC_IDS = 3
MAX_PROTOCOL_SUMMARY_SIGNALS = 4
ALLOWED_PLANNER_OWNER_AGENTS = ("planner", "retriever", "executor", "summarizer")
ALLOWED_PLANNER_ACTIONS = (
    "RETRIEVE_EVIDENCE",
    "EXECUTE_PLAYBOOK",
    "SUMMARIZE_AND_COMMIT",
    "VALIDATE_ROUTE",
    "CHECK_MEMORY_REUSE",
)
CONTEST_REQUIRED_PLANNER_ACTIONS = (
    "RETRIEVE_EVIDENCE",
    "EXECUTE_PLAYBOOK",
    "SUMMARIZE_AND_COMMIT",
)
TEXT_WHOLE_LANE_HIDDEN_FIELDS = (
    "route",
    "tool_name",
    "route_source",
    "tool_candidates",
    "matched_signals",
    "matched_tags",
    "decision_packet",
    "channel_snapshot",
    "ranked_evidence_bundle",
    "replay_eligibility_bundle",
    "benchmark_note",
)

AUDIT_TYPED_STATE_KINDS = (
    "FEATURE_BUNDLE",
    "CHANNEL_SNAPSHOT",
    "TOOL_CANDIDATE_SET",
    "RANKED_EVIDENCE_BUNDLE",
    "REPLAY_ELIGIBILITY_BUNDLE",
)


def _build_memory_assist_lookup_text(
    *,
    query: str,
    task_theme: str,
    tags: list[str],
    reuse_signature: str,
    retrieved_doc_ids: list[str],
    retrieved_hints: list[dict[str, str]],
) -> str:
    hint_parts = [
        f"{hint.get('route', '').strip()}/{hint.get('tool_name', '').strip()}"
        for hint in retrieved_hints
        if str(hint.get("route", "")).strip() or str(hint.get("tool_name", "")).strip()
    ]
    return "\n".join(
        [
            "StateBus assist memory lookup",
            f"Task theme: {task_theme}",
            f"Query: {query.strip()}",
            f"Tags: {', '.join(tags) if tags else 'none'}",
            f"Retrieved docs: {', '.join(retrieved_doc_ids) if retrieved_doc_ids else 'none'}",
            f"Corpus hints: {', '.join(hint_parts) if hint_parts else 'none'}",
            f"Reuse signature: {reuse_signature}",
        ]
    )


def _build_memory_commit_embedding_text(
    *,
    memory_purpose: str,
    task_theme: str,
    query: str,
    summary: str,
    route: str,
    route_source: str,
    tool_name: str,
    retrieved_doc_ids: list[str],
    reuse_signature: str,
    reusable_steps: list[str],
    tags: list[str],
    evidence_state_ids: list[str],
) -> str:
    return "\n".join(
        [
            f"memory_purpose: {memory_purpose}",
            f"task_theme: {task_theme}",
            f"query: {query.strip()}",
            f"summary: {summary.strip()}",
            f"route: {route.strip()}",
            f"route_source: {route_source.strip()}",
            f"tool_name: {tool_name.strip()}",
            f"retrieved_doc_ids: {', '.join(retrieved_doc_ids) if retrieved_doc_ids else 'none'}",
            f"reuse_signature: {reuse_signature}",
            f"reusable_steps: {', '.join(reusable_steps) if reusable_steps else 'none'}",
            f"tags: {', '.join(tags) if tags else 'none'}",
            f"evidence_state_ids: {', '.join(evidence_state_ids) if evidence_state_ids else 'none'}",
        ]
    )


def _strip_text_whole_lane_evidence_text(value: str) -> str:
    filtered_lines: list[str] = []
    for line in str(value).splitlines():
        upper = line.strip().upper()
        if upper.startswith("BENCHMARK_NOTE "):
            continue
        if upper.startswith("MEMORY_ASSIST_HINT "):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines).strip()


def _build_text_whole_lane_retriever_handoff(
    *,
    goal: str,
    query: str,
    evidence_text: str,
    upstream_text: str = "",
) -> str:
    parts = [
        "Retriever handoff in plain language.",
        f"User goal: {goal.strip()}",
        f"Query: {query.strip()}",
        "Evidence:",
        evidence_text.strip(),
    ]
    if upstream_text.strip():
        parts.extend(["Prior natural-language context:", upstream_text.strip()])
    return "\n".join(part for part in parts if part.strip()) + "\n"


def _build_text_strict_pure_lane_retriever_handoff(
    *,
    goal: str,
    query: str,
    evidence_text: str,
    upstream_text: str = "",
) -> str:
    parts = [
        "Retriever handoff in plain language.",
        f"User goal: {goal.strip()}",
        f"Query: {query.strip()}",
        "Use only the cited evidence below. Do not assume any hidden route, tool, memory hint, or structured packet exists.",
        "Evidence:",
        evidence_text.strip(),
    ]
    if upstream_text.strip():
        parts.extend(["Prior natural-language context:", upstream_text.strip()])
    return "\n".join(part for part in parts if part.strip()) + "\n"


def _build_text_whole_lane_executor_handoff(
    *,
    query: str,
    route: str,
    tool_name: str,
    actions: list[str],
) -> str:
    route_text = route.replace("_", " ").strip()
    tool_text = tool_name.split(".")[-1].replace("_", " ").strip() if tool_name else "unknown tool"
    action_lines = "\n".join(f"- {action}" for action in actions if str(action).strip())
    return (
        "Executor handoff in plain language.\n"
        f"Request: {query.strip()}\n"
        f"Most likely issue: {route_text or 'generic triage'}.\n"
        f"Chosen playbook: {tool_text}.\n"
        "Actions taken:\n"
        f"{action_lines}\n"
    )


def _build_memory_prior(hit: Any) -> dict[str, Any] | None:
    route = str(getattr(hit, "metadata", {}).get("feature_route", "")).strip()
    if not route or route == "generic_triage":
        return None
    return {
        "memory_id": str(getattr(hit, "memory_id", "")).strip(),
        "source_task_id": str(getattr(hit, "source_task_id", "")).strip(),
        "route": route,
        "confidence": float(getattr(hit, "confidence", 0.0)),
        "summary": str(getattr(hit, "summary", "")).strip(),
        "tool_name": str(getattr(hit, "metadata", {}).get("feature_tool_name", "")).strip(),
    }


def _build_capability(
    agent_id: str,
    *,
    action: str,
    accepted_state_kinds: list[str],
    produced_state_kinds: list[str],
    input_schema: str = "dict",
    output_schema: str = "StepResult",
) -> Capability:
    return Capability(
        agent_id=agent_id,
        items=[
            CapabilityItem(
                name=action,
                kind="TOOLCHAIN",
                input_schema=input_schema,
                output_schema=output_schema,
                accepted_state_kinds=accepted_state_kinds,
                produced_state_kinds=produced_state_kinds,
            )
        ],
    )


@dataclass
class PlannerAgent(BaseAgent):
    llm_client: LLMClient

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        raise NotImplementedError(
            "planner steps are not executed on the host mainline; "
            "open-plan tasks use PlannerAgent.plan_task() only as a pre-plan compilation pass"
        )

    async def plan_task(self, task: SampleTask, ctx: object) -> Plan:
        from tasks.sample_tasks import build_plan, normalize_plan_source

        if normalize_plan_source(getattr(task, "plan_source", "yaml")) == "yaml":
            return build_plan(task)
        planner_input = {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
        }
        messages = _planner_messages(planner_input, mode=str(getattr(ctx, "mode", "protocol")))
        result = await self.llm_client.complete(messages, purpose="planner")
        ctx.record_llm_result(result, purpose="planner")
        return _plan_from_llm_output(task, result.text)


@dataclass
class RetrieverAgent(BaseAgent):
    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        preferred_doc_ids = ctx.preferred_corpus_doc_ids(step)
        reuse_signature = ctx.reuse_signature(step)
        transfer_strategy = ctx.transfer_strategy()
        handoff_profile = ctx.handoff_profile()
        corpus_docs = retrieve_corpus_docs(
            query=str(step.params["query"]),
            tags=list(step.params.get("tags", [])),
            task_group=str(getattr(ctx, "task_group", "")),
            task_theme=str(getattr(ctx, "task_theme", "")),
            corpus_doc_ids=preferred_doc_ids,
            embedder=ctx.memory_store.embedder,
            corpus_path=ctx.corpus_path(),
            allow_preferred_doc_bias=_runtime_preferred_doc_bias_allowed(ctx),
            formal_structure_clean_retrieval=_formal_structure_clean_retrieval(ctx),
        )
        retrieved_hints = _resolve_runtime_corpus_hints(ctx=ctx, corpus_docs=corpus_docs)
        fresh_evidence_text = render_corpus_evidence(corpus_docs)

        hits = []
        accepted_hit = None
        memory_hint_route = ""
        memory_prior = None
        if step.params.get("allow_memory_reuse") and ctx.runtime_gates["allow_memory_assist"]:
            if transfer_strategy == "text_strict_pure_lane":
                hits = []
            else:
                assist_lookup_text = _build_memory_assist_lookup_text(
                    query=str(step.params["query"]),
                    task_theme=str(getattr(ctx, "task_theme", "")),
                    tags=list(step.params.get("tags", [])),
                    reuse_signature=reuse_signature,
                    retrieved_doc_ids=[doc.doc_id for doc in corpus_docs],
                    retrieved_hints=retrieved_hints,
                )
                hits = ctx.search_memory(
                    task_theme=ctx.task_theme,
                    query_text=assist_lookup_text,
                    top_k=3,
                    tags=[],
                    tags_any=[],
                    tags_all=[],
                    min_confidence=0.6,
                    encoder_id=ctx.memory_store.embedder.encoder_id,
                    required_metadata={"memory_purpose": "assist"},
                )
                if hits:
                    memory_prior = _build_memory_prior(hits[0])

        feature_bundle = build_feature_bundle(
            query=str(step.params["query"]),
            evidence_text=fresh_evidence_text,
            tags=list(step.params.get("tags", [])),
            reuse_signature=reuse_signature,
            reused_memory=False,
            retrieved_hints=retrieved_hints,
            memory_prior=memory_prior,
        )

        if hits:
            for candidate in hits:
                candidate_route = str(candidate.metadata.get("feature_route", "")).strip()
                if (
                    candidate_route
                    and candidate_route == feature_bundle["route"]
                    and candidate_route != "generic_triage"
                ):
                    accepted_hit = candidate
                    memory_hint_route = candidate_route
                    ctx.note_reuse(candidate, reuse_mode="assist")
                    break
            if accepted_hit is None:
                ctx.note_rejected_memory(hits[0])

        reused = accepted_hit is not None
        memory_assist_ids = [] if accepted_hit is None else [accepted_hit.memory_id]
        assist_hint = ""
        evidence_sections = [fresh_evidence_text]
        if accepted_hit is not None:
            assist_hint = _build_memory_assist_hint(accepted_hit)
            evidence_sections.append(assist_hint)
        benchmark_note = str(step.params.get("evidence_text", "")).strip()
        if benchmark_note and transfer_strategy != "text_whole_lane":
            evidence_sections.append(f"BENCHMARK_NOTE {benchmark_note}")
        evidence_text = "\n\n".join(section for section in evidence_sections if section.strip())
        text_whole_lane_evidence_text = _strip_text_whole_lane_evidence_text(evidence_text)

        evidence_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-evidence",
            kind="DENSE_EVIDENCE",
            text=evidence_text,
            metadata={
                "query": step.params["query"],
                "reused_memory": reused,
                "reuse_signature": reuse_signature,
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "memory_assist_ids": memory_assist_ids,
                "memory_assist_hint": assist_hint,
            },
        )
        feature_bundle["reused_memory"] = reused
        canonical_fresh_evidence = "\n\n".join(
            f"[{doc.doc_id}] {doc.title}\n{doc.text}".strip()
            for doc in sorted(corpus_docs, key=lambda item: item.doc_id)
        )
        feature_bundle["fresh_evidence_sha256"] = hashlib.sha256(
            canonical_fresh_evidence.encode("utf-8")
        ).hexdigest()
        feature_bundle["corpus_doc_ids"] = [doc.doc_id for doc in corpus_docs]
        feature_bundle["memory_assist_ids"] = memory_assist_ids
        feature_bundle["memory_assist_hint"] = assist_hint
        feature_bundle["memory_hint_route"] = memory_hint_route
        feature_bundle["handoff_profile"] = handoff_profile
        if memory_prior is not None:
            feature_bundle["memory_prior_id"] = memory_prior["memory_id"]
            feature_bundle["memory_prior_source_task_id"] = memory_prior["source_task_id"]
            feature_bundle["memory_prior_summary"] = memory_prior["summary"]
        ranked_docs = [
            {
                "rank": index + 1,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "route_hint": doc.runtime_route_hint,
                "tool_name": doc.runtime_tool_name,
                "tags": list(doc.tags),
            }
            for index, doc in enumerate(corpus_docs)
        ]
        ranked_evidence_bundle = build_ranked_evidence_bundle(
            query=str(step.params["query"]),
            feature_bundle=feature_bundle,
            ranked_docs=ranked_docs,
            retrieved_doc_ids=[doc.doc_id for doc in corpus_docs],
            evidence_text=fresh_evidence_text,
        )
        tool_candidate_set = build_tool_candidate_set(feature_bundle)
        replay_eligibility_bundle = build_replay_eligibility_bundle(
            query=str(step.params["query"]),
            feature_bundle=feature_bundle,
            retrieved_doc_ids=[doc.doc_id for doc in corpus_docs],
            fresh_evidence_sha256=feature_bundle["fresh_evidence_sha256"],
        )
        if accepted_hit is not None:
            prior_applied = bool(feature_bundle.get("memory_prior_applied"))
            ctx.metrics.memory_assist_prior_applied_task_count += int(
                prior_applied
            )
            ctx.metrics.memory_assist_candidate_reduction += int(
                feature_bundle.get("memory_candidate_reduction", 0)
            )
            ctx.metrics.memory_assist_route_agreement_task_count += int(
                prior_applied and bool(feature_bundle.get("memory_prior_route_agreement"))
            )
            ctx.metrics.memory_assist_rescue_task_count += int(
                bool(feature_bundle.get("memory_prior_rescue"))
            )
        channel_patch_ref = None
        channel_snapshot_ref = None
        feature_ref = None
        ranked_evidence_ref = None
        tool_candidate_ref = None
        replay_eligibility_ref = None
        disabled_state_kinds = {
            str(value).strip()
            for value in step.params.get("audit_disable_state_kinds", [])
            if str(value).strip()
        }
        if transfer_strategy == "state_ref":
            channel_values = {
                "query": str(step.params["query"]),
                "route": feature_bundle["route"],
                "tool_name": feature_bundle["tool_name"],
                "route_source": feature_bundle["route_source"],
                "route_confidence": feature_bundle["route_confidence"],
                "route_provenance": feature_bundle["route_provenance"],
                "matched_signals": feature_bundle["matched_signals"],
                "matched_tags": feature_bundle["matched_tags"],
                "match_score": feature_bundle["match_score"],
                "hint_doc_ids": feature_bundle["hint_doc_ids"],
                "hint_route": feature_bundle["hint_route"],
                "hint_tool_name": feature_bundle["hint_tool_name"],
                "tool_candidates": tool_candidate_set["tool_candidates"],
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                "reuse_signature": reuse_signature,
                "reused_memory": reused,
                "memory_assist_ids": memory_assist_ids,
            }
            channel_patch = ChannelPatch(
                channel_name="route",
                ops=channel_values,
                patch_id=f"{ctx.task_id}-{step.step_id}-route-patch",
            )
            channel_patch_ref = ctx.put_channel_patch(
                state_id=f"{ctx.task_id}-{step.step_id}-route-patch",
                patch=channel_patch,
                metadata={
                    "query": step.params["query"],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_route_provenance": feature_bundle["route_provenance"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                },
            )
            route_snapshot = ChannelSnapshot(
                channel_name="route",
                kind="LAST_VALUE",
                values=channel_values,
                state_ref_ids=[evidence_ref.state_id, channel_patch_ref.state_id],
            )
            channel_snapshot_ref = ctx.put_channel_snapshot(
                state_id=f"{ctx.task_id}-{step.step_id}-route-snapshot",
                snapshot=route_snapshot,
                metadata={
                    "query": step.params["query"],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_route_provenance": feature_bundle["route_provenance"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                },
            )
            feature_ref = ctx.put_feature_state(
                state_id=f"{ctx.task_id}-{step.step_id}-features",
                feature_bundle=feature_bundle,
                metadata={
                    "query": step.params["query"],
                    "reused_memory": reused,
                    "reuse_signature": reuse_signature,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "memory_assist_ids": memory_assist_ids,
                    "memory_assist_hint": assist_hint,
                    "memory_prior_applied": feature_bundle["memory_prior_applied"],
                    "memory_candidate_reduction": feature_bundle["memory_candidate_reduction"],
                    "memory_prior_route": feature_bundle["memory_prior_route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_hint_doc_ids": feature_bundle["hint_doc_ids"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_route_provenance": feature_bundle["route_provenance"],
                    "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                },
            )
            ranked_evidence_ref = ctx.put_ranked_evidence_state(
                state_id=f"{ctx.task_id}-{step.step_id}-ranked-evidence",
                ranked_evidence_bundle=ranked_evidence_bundle,
                metadata={
                    "query": step.params["query"],
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                },
            )
            tool_candidate_ref = ctx.put_tool_candidate_state(
                state_id=f"{ctx.task_id}-{step.step_id}-tool-candidates",
                tool_candidate_set=tool_candidate_set,
                metadata={
                    "query": step.params["query"],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                },
            )
            replay_eligibility_ref = ctx.put_replay_eligibility_state(
                state_id=f"{ctx.task_id}-{step.step_id}-replay-eligibility",
                replay_eligibility_bundle=replay_eligibility_bundle,
                metadata={
                    "query": step.params["query"],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_route_provenance": feature_bundle["route_provenance"],
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                },
            )
            if "FEATURE_BUNDLE" in disabled_state_kinds:
                feature_ref = None
            if "CHANNEL_SNAPSHOT" in disabled_state_kinds:
                channel_snapshot_ref = None
            if "TOOL_CANDIDATE_SET" in disabled_state_kinds:
                tool_candidate_ref = None
            if "RANKED_EVIDENCE_BUNDLE" in disabled_state_kinds:
                ranked_evidence_ref = None
            if "REPLAY_ELIGIBILITY_BUNDLE" in disabled_state_kinds:
                replay_eligibility_ref = None
        elif transfer_strategy == "text_whole_lane":
            replay_eligibility_ref = ctx.put_replay_eligibility_state(
                state_id=f"{ctx.task_id}-{step.step_id}-replay-eligibility",
                replay_eligibility_bundle=replay_eligibility_bundle,
                metadata={
                    "query": step.params["query"],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_route_provenance": feature_bundle["route_provenance"],
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                    "proof_only": True,
                },
            )
            if "REPLAY_ELIGIBILITY_BUNDLE" in disabled_state_kinds:
                replay_eligibility_ref = None
        transfer_brief_ref = None
        decision_packet_ref = None
        decision_packet = build_executor_decision_packet(
            query=str(step.params["query"]),
            feature_bundle=feature_bundle,
            retrieved_doc_ids=[doc.doc_id for doc in corpus_docs],
        )
        if transfer_strategy == "text_brief":
            transfer_brief_text = _build_transfer_brief(
                query=str(step.params["query"]),
                retrieved_doc_ids=[doc.doc_id for doc in corpus_docs],
                route=str(feature_bundle["route"]),
                tool_name=str(feature_bundle["tool_name"]),
                route_source=str(feature_bundle["route_source"]),
                route_confidence=float(feature_bundle["route_confidence"]),
                route_provenance=[str(item) for item in feature_bundle["route_provenance"]],
                matched_signals=[str(item) for item in feature_bundle["matched_signals"]],
                matched_tags=[str(item) for item in feature_bundle["matched_tags"]],
                match_score=int(feature_bundle["match_score"]),
                hint_doc_ids=[str(item) for item in feature_bundle["hint_doc_ids"]],
                hint_route=str(feature_bundle["hint_route"]),
                hint_tool_name=str(feature_bundle["hint_tool_name"]),
                tool_candidates=[dict(item) for item in feature_bundle["tool_candidates"]],
                memory_assist_ids=memory_assist_ids,
                evidence_text=evidence_text,
            )
            transfer_brief_ref = ctx.put_text_state(
                state_id=f"{ctx.task_id}-{step.step_id}-brief",
                kind="TOOL_ARTIFACT",
                text=transfer_brief_text,
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                },
            )
        elif transfer_strategy == "text_packet_minimal":
            transfer_brief_ref = ctx.put_text_state(
                state_id=f"{ctx.task_id}-{step.step_id}-text-packet",
                kind="TOOL_ARTIFACT",
                text=_build_text_packet_minimal(decision_packet),
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                },
            )
        elif transfer_strategy == "natural_handoff_text":
            transfer_brief_ref = ctx.put_text_state(
                state_id=f"{ctx.task_id}-{step.step_id}-natural-handoff",
                kind="TOOL_ARTIFACT",
                text=_build_natural_handoff_text(
                    query=str(step.params["query"]),
                    evidence_text=evidence_text,
                ),
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                },
            )
        elif transfer_strategy == "text_strict_pure_lane":
            transfer_brief_ref = ctx.put_text_state(
                state_id=f"{ctx.task_id}-{step.step_id}-text-strict-pure-lane",
                kind="TOOL_ARTIFACT",
                text=_build_text_strict_pure_lane_retriever_handoff(
                    goal=str(getattr(ctx.task, "goal", "")),
                    query=str(step.params["query"]),
                    evidence_text=text_whole_lane_evidence_text,
                ),
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "handoff_profile": handoff_profile,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                },
            )
        elif transfer_strategy == "text_whole_lane":
            transfer_brief_ref = ctx.put_text_state(
                state_id=f"{ctx.task_id}-{step.step_id}-text-whole-lane",
                kind="TOOL_ARTIFACT",
                text=_build_text_whole_lane_retriever_handoff(
                    goal=str(getattr(ctx.task, "goal", "")),
                    query=str(step.params["query"]),
                    evidence_text=text_whole_lane_evidence_text,
                ),
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "handoff_profile": handoff_profile,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                },
            )
        elif transfer_strategy == "inline_text_handoff":
            pass
        elif transfer_strategy == "state_packet_minimal":
            override_route = str(
                getattr(getattr(ctx, "task", None), "audit_decision_packet_override_route", "")
            ).strip()
            override_tool_name = str(
                getattr(getattr(ctx, "task", None), "audit_decision_packet_override_tool_name", "")
            ).strip()
            audit_decision_packet_mode = ""
            if override_route:
                decision_packet["route"] = override_route
            if override_tool_name:
                decision_packet["tool_name"] = override_tool_name
            if override_route or override_tool_name:
                audit_decision_packet_mode = "override_mismatch_abstain"
                decision_packet["audit_mode"] = audit_decision_packet_mode
                overridden_route = str(decision_packet.get("route", "")).strip()
                overridden_tool = str(decision_packet.get("tool_name", "")).strip()
                decision_packet["tool_candidates"] = [
                    {
                        "tool_name": overridden_tool or "tool.collect_more_evidence",
                        "route": overridden_route or "generic_triage",
                        "score": int(decision_packet.get("match_score", 0)),
                        "matched_signals": list(decision_packet.get("matched_signals", [])),
                        "matched_tags": list(decision_packet.get("matched_tags", [])),
                        "source": "audit_override",
                    }
                ]
            decision_packet_ref = ctx.put_executor_decision_state(
                state_id=f"{ctx.task_id}-{step.step_id}-decision-packet",
                decision_packet=decision_packet,
                metadata={
                    "query": step.params["query"],
                    "transfer_strategy": transfer_strategy,
                    "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                    "feature_route": feature_bundle["route"],
                    "feature_route_source": feature_bundle["route_source"],
                    "feature_route_confidence": feature_bundle["route_confidence"],
                    "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                    "audit_decision_packet_mode": audit_decision_packet_mode,
                },
            )
            if getattr(ctx.runtime_profile, "resolved_benchmark_lane", "") == "memory":
                replay_eligibility_ref = ctx.put_replay_eligibility_state(
                    state_id=f"{ctx.task_id}-{step.step_id}-replay-certificate",
                    replay_eligibility_bundle={
                        **replay_eligibility_bundle,
                        "certificate_scope": "minimal_state_packet_replay_gate",
                        "mode_compatible_restore_kinds": [
                            "DENSE_EVIDENCE",
                            "EXECUTOR_DECISION_PACKET",
                            "TOOL_ARTIFACT",
                        ],
                        "executor_decision_packet_hash": decision_packet_ref.canonical_hash,
                    },
                    metadata={
                        "query": step.params["query"],
                        "feature_route": feature_bundle["route"],
                        "feature_route_source": feature_bundle["route_source"],
                        "feature_route_confidence": feature_bundle["route_confidence"],
                        "feature_route_provenance": feature_bundle["route_provenance"],
                        "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                        "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                        "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                        "certificate_scope": "minimal_state_packet_replay_gate",
                        "proof_only": True,
                    },
                )
            if "EXECUTOR_DECISION_PACKET" in disabled_state_kinds:
                decision_packet_ref = None
        embedding_ref = None
        if transfer_strategy == "state_ref":
            embedding_ref = ctx.put_embedding_state(
                state_id=f"{ctx.task_id}-{step.step_id}-embedding",
                text=str(step.params["query"]),
                metadata={
                    "query": step.params["query"],
                    "source_text_kind": "query",
                },
            )
        output_state_refs = [evidence_ref]
        if channel_patch_ref is not None:
            output_state_refs.append(channel_patch_ref)
        if channel_snapshot_ref is not None:
            output_state_refs.append(channel_snapshot_ref)
        if feature_ref is not None:
            output_state_refs.append(feature_ref)
        if ranked_evidence_ref is not None:
            output_state_refs.append(ranked_evidence_ref)
        if tool_candidate_ref is not None:
            output_state_refs.append(tool_candidate_ref)
        if replay_eligibility_ref is not None:
            output_state_refs.append(replay_eligibility_ref)
        if transfer_brief_ref is not None:
            output_state_refs.append(transfer_brief_ref)
        if decision_packet_ref is not None:
            output_state_refs.append(decision_packet_ref)
        if embedding_ref is not None:
            output_state_refs.append(embedding_ref)
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=output_state_refs,
            payload={
                "query": step.params["query"],
                "memory_hits": [hit.memory_id for hit in hits],
                "memory_assist_ids": memory_assist_ids,
                "memory_assist_hint": assist_hint,
                "reused_memory": reused,
                "reuse_mode": "assist" if reused else "none",
                "transfer_strategy": transfer_strategy,
                "transfer_brief_state_id": (
                    transfer_brief_ref.state_id if transfer_brief_ref is not None else ""
                ),
                "inline_handoff_text": (
                    (
                        _build_text_strict_pure_lane_retriever_handoff(
                            goal=str(getattr(ctx.task, "goal", "")),
                            query=str(step.params["query"]),
                            evidence_text=text_whole_lane_evidence_text,
                        )
                        if transfer_strategy == "text_strict_pure_lane"
                        else _build_text_whole_lane_retriever_handoff(
                            goal=str(getattr(ctx.task, "goal", "")),
                            query=str(step.params["query"]),
                            evidence_text=text_whole_lane_evidence_text,
                        )
                    )
                    if transfer_strategy in {"inline_text_handoff", "text_whole_lane", "text_strict_pure_lane"}
                    else ""
                ),
                "feature_route": feature_bundle["route"],
                "feature_route_source": feature_bundle["route_source"],
                "feature_hint_doc_ids": feature_bundle["hint_doc_ids"],
                "feature_route_confidence": feature_bundle["route_confidence"],
                "feature_route_provenance": feature_bundle["route_provenance"],
                "memory_prior_applied": feature_bundle["memory_prior_applied"],
                "memory_candidate_reduction": feature_bundle["memory_candidate_reduction"],
                "memory_prior_route": feature_bundle["memory_prior_route"],
                "feature_evidence_sha256": feature_bundle["evidence_sha256"],
                "feature_fresh_evidence_sha256": feature_bundle["fresh_evidence_sha256"],
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "corpus_doc_count": len(corpus_docs),
                "memory_hint_route": memory_hint_route,
                "channel_snapshot_state_id": (
                    "" if channel_snapshot_ref is None else channel_snapshot_ref.state_id
                ),
                "channel_snapshot_hash": (
                    "" if channel_snapshot_ref is None else ctx.get_channel_snapshot_state(channel_snapshot_ref).snapshot_hash
                ),
                "ranked_evidence_state_id": (
                    "" if ranked_evidence_ref is None else ranked_evidence_ref.state_id
                ),
                "tool_candidate_state_id": (
                    "" if tool_candidate_ref is None else tool_candidate_ref.state_id
                ),
                "decision_packet_state_id": (
                    "" if decision_packet_ref is None else decision_packet_ref.state_id
                ),
                "replay_eligibility_state_id": (
                    "" if replay_eligibility_ref is None else replay_eligibility_ref.state_id
                ),
                "replay_certificate_state_id": (
                    "" if replay_eligibility_ref is None else replay_eligibility_ref.state_id
                ),
                "replay_certificate_hash": (
                    "" if replay_eligibility_ref is None else replay_eligibility_ref.canonical_hash
                ),
                "audit_disabled_state_kinds": sorted(
                    kind for kind in disabled_state_kinds if kind in AUDIT_TYPED_STATE_KINDS
                ),
            },
        )


@dataclass
class ExecutorAgent(BaseAgent):
    transport: str = "local"
    socket_path: str | None = None

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        if step.action == "VALIDATE_ROUTE":
            return self._validate_route_step(step, ctx)
        transfer_strategy = ctx.transfer_strategy()
        input_refs = ctx.step_input_refs(step.step_id)
        ctx.record_transfer_inputs(input_refs)
        if transfer_strategy not in {"natural_handoff_text", "inline_text_handoff"} and self._should_use_uds(step):
            self._record_hash_first_fetches(
                ctx=ctx,
                refs=input_refs,
                requester_id="uds_executor",
            )
        if self._should_use_uds(step):
            return self._execute_via_uds(step, ctx, input_refs)
        return execute_playbook_step(
            task_id=ctx.task_id,
            task_theme=ctx.task_theme,
            step=step,
            statepool=ctx.statepool,
            input_state_refs=input_refs,
            transfer_strategy=transfer_strategy,
            handoff_profile=ctx.handoff_profile(),
            inline_handoff_text=(
                str(ctx.result_for_role("retrieve").payload.get("inline_handoff_text", ""))
                if transfer_strategy in {"inline_text_handoff", "text_whole_lane", "text_strict_pure_lane"} and ctx.result_for_role("retrieve") is not None
                else ""
            ),
        )

    @staticmethod
    def _validate_route_step(step: PlanStep, ctx: object) -> StepResult:
        input_refs = ctx.step_input_refs(step.step_id)
        ctx.record_transfer_inputs(input_refs)
        retrieve_result = ctx.result_for_role("retrieve")
        retrieve_payload = {} if retrieve_result is None else dict(retrieve_result.payload)
        validated_route = str(retrieve_payload.get("feature_route", "")).strip()
        validated_tool = str(retrieve_payload.get("tool_name", "")).strip() or str(
            retrieve_payload.get("feature_tool_name", "")
        ).strip()
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[],
            payload={
                "validated_route": validated_route,
                "validated_tool_name": validated_tool,
                "route_source": str(retrieve_payload.get("feature_route_source", "")).strip(),
                "route_confidence": float(retrieve_payload.get("feature_route_confidence", 0.0)),
                "retrieved_doc_ids": [
                    str(item) for item in retrieve_payload.get("retrieved_doc_ids", [])
                ],
            },
        )

    def _should_use_uds(self, step: PlanStep) -> bool:
        transport = str(step.params.get("transport", self.transport or "local")).strip().lower()
        return transport == "uds"

    @staticmethod
    def _record_hash_first_fetches(*, ctx: object, refs: list[object], requester_id: str) -> None:
        seen_hashes: set[str] = set()
        for ref in refs:
            blob_hash = str(getattr(ref, "canonical_hash", "") or "").strip()
            if not blob_hash or blob_hash in seen_hashes:
                continue
            seen_hashes.add(blob_hash)
            ctx.fetch_blob(ref, requester_id=requester_id)

    def _execute_via_uds(self, step: PlanStep, ctx: object, input_refs: list[object]) -> StepResult:
        socket_path = step.params.get("socket_path") or self.socket_path
        if not socket_path:
            raise ValueError("executor uds transport selected without socket_path")
        effective_step = PlanStep(
            step_id=step.step_id,
            owner_agent=step.owner_agent,
            action=step.action,
            input_state_refs=list(step.input_state_refs),
            params={
                **step.params,
                "transfer_strategy": ctx.transfer_strategy(),
                "handoff_profile": ctx.handoff_profile(),
                "inline_handoff_text": (
                    str(ctx.result_for_role("retrieve").payload.get("inline_handoff_text", ""))
                    if ctx.transfer_strategy() in {"inline_text_handoff", "text_whole_lane", "text_strict_pure_lane"} and ctx.result_for_role("retrieve") is not None
                    else ""
                ),
            },
            depends_on=list(step.depends_on),
            semantic_role=step.semantic_role,
        )
        message = RemoteStepRequest(
            mode=str(getattr(ctx, "mode", "protocol")),
            task_id=str(ctx.task_id),
            task_theme=str(ctx.task_theme),
            state_root=str(ctx.statepool.root),
            step=effective_step,
            input_state_refs=list(input_refs),
        )
        response = request_response(socket_path, message)
        if not isinstance(response, RemoteStepResponse):
            raise TypeError(f"unexpected uds executor response: {type(response).__name__}")
        return response.result


@dataclass
class SummarizerAgent(BaseAgent):
    llm_client: LLMClient

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        retrieve_result = ctx.result_for_role("retrieve")
        execute_result = ctx.result_for_role("execute")
        if retrieve_result is None or execute_result is None:
            raise ValueError("summarizer requires retrieve and execute semantic results")
        input_refs = ctx.step_input_refs(step.step_id)
        transfer_strategy = ctx.transfer_strategy()
        retrieve_output_refs = list(retrieve_result.output_state_refs)
        evidence_ref = next((ref for ref in input_refs if ref.kind == "DENSE_EVIDENCE"), None)
        feature_ref = next(
            (ref for ref in input_refs if ref.kind == "FEATURE_BUNDLE"),
            None,
        )
        route_channel_snapshot_ref = next(
            (
                ref
                for ref in retrieve_output_refs
                if ref.kind == "CHANNEL_SNAPSHOT"
                and str(ref.metadata.get("channel_name", ref.channel)).strip() == "route"
            ),
            None,
        )
        ranked_evidence_ref = next(
            (ref for ref in retrieve_output_refs if ref.kind == "RANKED_EVIDENCE_BUNDLE"),
            None,
        )
        tool_candidate_ref = next(
            (ref for ref in retrieve_output_refs if ref.kind == "TOOL_CANDIDATE_SET"),
            None,
        )
        replay_eligibility_ref = next(
            (ref for ref in retrieve_output_refs if ref.kind == "REPLAY_ELIGIBILITY_BUNDLE"),
            None,
        )
        decision_packet_ref = next(
            (ref for ref in retrieve_output_refs if ref.kind == "EXECUTOR_DECISION_PACKET"),
            None,
        )
        embedding_ref = next(
            (ref for ref in retrieve_output_refs if ref.kind == "EMBEDDING"),
            None,
        )
        artifact_ref = next(ref for ref in input_refs if ref.kind == "TOOL_ARTIFACT")
        evidence_text = "" if evidence_ref is None else ctx.get_text_state(evidence_ref)
        feature_bundle = _load_feature_bundle_from_ref(ctx, feature_ref)
        actions_text = ctx.get_text_state(artifact_ref)
        reusable_steps = list(execute_result.payload.get("reusable_steps", ["retrieve", "execute"]))
        mode = str(getattr(ctx, "mode", "protocol"))
        summary_contract = str(getattr(ctx, "summary_contract", "actions_plus_evidence")).strip().lower()
        summary_evidence_text = evidence_text
        if transfer_strategy == "text_whole_lane":
            summary_evidence_text = actions_text
        elif mode != "text" and transfer_strategy != "text_whole_lane" and summary_contract == "protocol_handoff_audit":
            summary_evidence_text = _build_protocol_summary_handoff(
                query=str(retrieve_result.payload.get("query", "")),
                route=str(execute_result.payload.get("route", "")),
                route_source=str(retrieve_result.payload.get("feature_route_source", "")),
                route_confidence=float(retrieve_result.payload.get("feature_route_confidence", 0.0)),
                retrieved_doc_ids=[str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])],
                matched_signals=(
                    [] if feature_bundle is None else [str(item) for item in feature_bundle.get("matched_signals", [])]
                ),
                memory_assist_hint=str(retrieve_result.payload.get("memory_assist_hint", "")),
                evidence_preview=(
                    "" if feature_bundle is None else str(feature_bundle.get("evidence_preview", ""))
                ),
            )
        elif mode != "text" and transfer_strategy != "text_whole_lane":
            summary_evidence_text = json.dumps(
                _build_protocol_summary_input_packet(
                    query=str(retrieve_result.payload.get("query", "")),
                    route=str(execute_result.payload.get("route", "")),
                    route_source=str(retrieve_result.payload.get("feature_route_source", "")),
                    route_confidence=float(
                        retrieve_result.payload.get("feature_route_confidence", 0.0)
                    ),
                    retrieved_doc_ids=[
                        str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])
                    ],
                    matched_signals=(
                        []
                        if feature_bundle is None
                        else [str(item) for item in feature_bundle.get("matched_signals", [])]
                    ),
                    actions_text=actions_text,
                    summary_hint=str(step.params["summary_hint"]),
                    memory_assist_hint=str(retrieve_result.payload.get("memory_assist_hint", "")),
                ),
                ensure_ascii=False,
            )
        summary_input = {
            "task_id": ctx.task_id,
            "task_theme": ctx.task_theme,
            "summary_hint": step.params["summary_hint"],
            "evidence_text": summary_evidence_text,
            "actions_text": actions_text,
            "tags": list(step.params.get("tags", [])),
            "reusable_steps": reusable_steps,
        }
        messages = _summarizer_messages(summary_input, mode=mode)
        result = await self.llm_client.complete(messages, purpose="summarizer")
        ctx.record_llm_result(result, purpose="summarizer")
        result_model = result.model
        summary_payload = _summary_from_llm_output(result.text)
        summary_text = str(summary_payload["summary"]).strip()
        summary_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-summary",
            kind="TOOL_ARTIFACT",
            text=summary_text,
            metadata={"task_theme": ctx.task_theme},
        )
        tags = list(summary_payload.get("tags") or step.params.get("tags", []))
        confidence = float(summary_payload.get("confidence", 0.95))
        replay_reusable_steps = list(summary_payload.get("reusable_steps") or reusable_steps)
        replay_class = (
            "exact_replay"
            if {"retrieve", "execute"}.issubset({str(step_id) for step_id in replay_reusable_steps})
            else "validated_replay"
            if "execute" in {str(step_id) for step_id in replay_reusable_steps}
            else "assist"
        )
        shared_metadata = {
            "source_agent_id": self.agent_id,
            "goal": getattr(ctx, "task_id", ""),
            "task_group": getattr(ctx, "task_group", ""),
            "reuse_signature": ctx.reuse_signature(step),
            "case_id": str(getattr(getattr(ctx, "task", None), "case_id", "")).strip(),
            "feature_route": execute_result.payload.get("route", ""),
            "feature_tool_name": execute_result.payload.get("tool_name", ""),
            "feature_route_source": retrieve_result.payload.get("feature_route_source", ""),
            "feature_hint_doc_ids": retrieve_result.payload.get("feature_hint_doc_ids", []),
            "feature_route_confidence": retrieve_result.payload.get("feature_route_confidence", 0.0),
            "feature_route_provenance": retrieve_result.payload.get("feature_route_provenance", []),
            "feature_evidence_sha256": retrieve_result.payload.get("feature_evidence_sha256", ""),
            "feature_fresh_evidence_sha256": retrieve_result.payload.get(
                "feature_fresh_evidence_sha256",
                "",
            ),
            "feature_query": retrieve_result.payload.get("query", ""),
            "retrieve_inline_handoff_text": retrieve_result.payload.get("inline_handoff_text", ""),
            "retrieved_doc_ids": retrieve_result.payload.get("retrieved_doc_ids", []),
            "channel_snapshot_hash": retrieve_result.payload.get("channel_snapshot_hash", ""),
            "replay_certificate_hash": retrieve_result.payload.get("replay_certificate_hash", ""),
            "replay_certificate_state_id": retrieve_result.payload.get("replay_certificate_state_id", ""),
            "cas_blob_hashes": sorted(
                {
                    ref.canonical_hash
                    for ref in input_refs
                    if getattr(ref, "canonical_hash", "")
                }
            ),
            "trace_id": ctx.trace_id,
            "llm_model": result_model,
            "handoff_profile": ctx.handoff_profile(),
            "chosen_route": str(execute_result.payload.get("route", "")).strip(),
            "rejected_routes": [
                str(item).strip()
                for item in getattr(getattr(ctx, "task", None), "acceptable_routes", ())
                if str(item).strip()
                and str(item).strip() != str(execute_result.payload.get("route", "")).strip()
            ],
            "safe_first_action": (
                next(
                    (
                        str(action).strip()
                        for action in execute_result.payload.get("actions", [])
                        if str(action).strip()
                    ),
                    "",
                )
            ),
            "first_validation_check": (
                next(
                    (
                        line.strip()
                        for line in summary_text.splitlines()
                        if "validation" in line.lower() or "check" in line.lower()
                    ),
                    "",
                )
            ),
        }
        assist_refs = [
            *([evidence_ref] if evidence_ref is not None else []),
            *([route_channel_snapshot_ref] if route_channel_snapshot_ref is not None else []),
            *([feature_ref] if feature_ref is not None else []),
            *([ranked_evidence_ref] if ranked_evidence_ref is not None else []),
            *([tool_candidate_ref] if tool_candidate_ref is not None else []),
            *(
                [replay_eligibility_ref]
                if replay_eligibility_ref is not None and transfer_strategy != "state_packet_minimal"
                else []
            ),
            *([embedding_ref] if embedding_ref is not None else []),
            summary_ref,
        ]
        if transfer_strategy == "text_whole_lane":
            assist_refs = [summary_ref]
        replay_refs = [
            *assist_refs,
            *([decision_packet_ref] if decision_packet_ref is not None else []),
            *([replay_eligibility_ref] if replay_eligibility_ref is not None else []),
            artifact_ref,
        ]
        if transfer_strategy == "text_whole_lane":
            replay_refs = [
                summary_ref,
                *([replay_eligibility_ref] if replay_eligibility_ref is not None else []),
                artifact_ref,
            ]
        assist_embedding_text = _build_memory_commit_embedding_text(
            memory_purpose="assist",
            task_theme=ctx.task_theme,
            query=str(retrieve_result.payload.get("query", "")),
            summary=summary_text,
            route=str(execute_result.payload.get("route", "")),
            route_source=str(retrieve_result.payload.get("feature_route_source", "")),
            tool_name=str(execute_result.payload.get("tool_name", "")),
            retrieved_doc_ids=[str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])],
            reuse_signature=ctx.reuse_signature(step),
            reusable_steps=["retrieve"],
            tags=tags,
            evidence_state_ids=[ref.state_id for ref in assist_refs],
        )
        replay_embedding_text = _build_memory_commit_embedding_text(
            memory_purpose="replay",
            task_theme=ctx.task_theme,
            query=str(retrieve_result.payload.get("query", "")),
            summary=summary_text,
            route=str(execute_result.payload.get("route", "")),
            route_source=str(retrieve_result.payload.get("feature_route_source", "")),
            tool_name=str(execute_result.payload.get("tool_name", "")),
            retrieved_doc_ids=[str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])],
            reuse_signature=ctx.reuse_signature(step),
            reusable_steps=replay_reusable_steps,
            tags=tags,
            evidence_state_ids=[ref.state_id for ref in replay_refs],
        )
        memory_commits = [
            MemoryCommit(
                memory_id=f"mem-{ctx.task_id}-assist",
                source_agent_id=self.agent_id,
                source_task_id=ctx.task_id,
                task_theme=ctx.task_theme,
                summary=summary_text,
                tags=tags,
                evidence_state_ids=[ref.state_id for ref in assist_refs],
                reusable_steps=["retrieve"],
                confidence=confidence,
                embedding_text=assist_embedding_text,
                embedding_state_id=embedding_ref.state_id if embedding_ref is not None else None,
                encoder_id=ctx.memory_store.embedder.encoder_id,
                metadata={
                    **shared_metadata,
                    "memory_purpose": "assist",
                    "memory_layer": "summary",
                },
                evidence_state_refs=assist_refs,
                memory_purpose="assist",
                memory_layer="summary",
                replay_class="assist",
                route=str(execute_result.payload.get("route", "")),
                route_source=str(retrieve_result.payload.get("feature_route_source", "")),
                route_provenance=[
                    str(item) for item in retrieve_result.payload.get("feature_route_provenance", [])
                ],
                route_confidence=float(retrieve_result.payload.get("feature_route_confidence", 0.0)),
                retrieved_doc_ids=[
                    str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])
                ],
                fresh_evidence_sha256=str(
                    retrieve_result.payload.get("feature_fresh_evidence_sha256", "")
                ),
                reuse_signature=ctx.reuse_signature(step),
                step_output_state_ids=[ref.state_id for ref in assist_refs],
                step_output_state_refs=assist_refs,
                tool_name=str(execute_result.payload.get("tool_name", "")),
                source_session_id=ctx.trace_id,
            ),
            MemoryCommit(
                memory_id=f"mem-{ctx.task_id}-replay",
                source_agent_id=self.agent_id,
                source_task_id=ctx.task_id,
                task_theme=ctx.task_theme,
                summary=summary_text,
                tags=tags,
                evidence_state_ids=[ref.state_id for ref in replay_refs],
                reusable_steps=replay_reusable_steps,
                confidence=confidence,
                embedding_text=replay_embedding_text,
                embedding_state_id=embedding_ref.state_id if embedding_ref is not None else None,
                encoder_id=ctx.memory_store.embedder.encoder_id,
                metadata={
                    **shared_metadata,
                    "memory_purpose": "replay",
                    "memory_layer": "episode",
                },
                evidence_state_refs=replay_refs,
                memory_purpose="replay",
                memory_layer="episode",
                replay_class=replay_class,
                route=str(execute_result.payload.get("route", "")),
                route_source=str(retrieve_result.payload.get("feature_route_source", "")),
                route_provenance=[
                    str(item) for item in retrieve_result.payload.get("feature_route_provenance", [])
                ],
                route_confidence=float(retrieve_result.payload.get("feature_route_confidence", 0.0)),
                retrieved_doc_ids=[
                    str(item) for item in retrieve_result.payload.get("retrieved_doc_ids", [])
                ],
                fresh_evidence_sha256=str(
                    retrieve_result.payload.get("feature_fresh_evidence_sha256", "")
                ),
                reuse_signature=ctx.reuse_signature(step),
                step_output_state_ids=[ref.state_id for ref in replay_refs],
                step_output_state_refs=replay_refs,
                tool_name=str(execute_result.payload.get("tool_name", "")),
                source_session_id=ctx.trace_id,
            ),
        ]
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[summary_ref],
            payload={
                "summary": summary_text,
                "summary_state_id": summary_ref.state_id,
                "llm_model": result_model,
            },
            memory_commit=memory_commits[0],
            memory_commits=memory_commits[1:],
        )


def build_sample_agents(llm_client: LLMClient | None = None) -> dict[str, BaseAgent]:
    active_llm = llm_client or DeterministicLLMClient()
    executor_transport = os.getenv("STATEBUS_EXECUTOR_TRANSPORT", "local").strip().lower()
    executor_socket_path = os.getenv("STATEBUS_EXECUTOR_SOCKET_PATH")
    return {
        "planner": PlannerAgent(
            agent_id="planner",
            capability=_build_capability(
                "planner",
                action="PLAN_TASK",
                accepted_state_kinds=[],
                produced_state_kinds=[],
                input_schema="SampleTask",
                output_schema="Plan",
            ),
            llm_client=active_llm,
        ),
        "retriever": RetrieverAgent(
            agent_id="retriever",
            capability=_build_capability(
                "retriever",
                action="RETRIEVE_EVIDENCE",
                accepted_state_kinds=[],
                produced_state_kinds=[
                    "DENSE_EVIDENCE",
                    "CHANNEL_PATCH",
                    "CHANNEL_SNAPSHOT",
                    "FEATURE_BUNDLE",
                    "RANKED_EVIDENCE_BUNDLE",
                    "TOOL_CANDIDATE_SET",
                    "REPLAY_ELIGIBILITY_BUNDLE",
                    "EXECUTOR_DECISION_PACKET",
                    "TOOL_ARTIFACT",
                    "EMBEDDING",
                ],
            ),
        ),
        "executor": ExecutorAgent(
            agent_id="executor",
            capability=Capability(
                agent_id="executor",
                items=[
                    CapabilityItem(
                        name="EXECUTE_PLAYBOOK",
                        kind="TOOLCHAIN",
                        input_schema="dict",
                        output_schema="StepResult",
                        accepted_state_kinds=[
                            "DENSE_EVIDENCE",
                            "CHANNEL_SNAPSHOT",
                            "FEATURE_BUNDLE",
                            "TOOL_CANDIDATE_SET",
                            "EXECUTOR_DECISION_PACKET",
                            "TOOL_ARTIFACT",
                        ],
                        produced_state_kinds=["TOOL_ARTIFACT"],
                    ),
                    CapabilityItem(
                        name="VALIDATE_ROUTE",
                        kind="TOOLCHAIN",
                        input_schema="dict",
                        output_schema="StepResult",
                        accepted_state_kinds=[
                            "DENSE_EVIDENCE",
                            "FEATURE_BUNDLE",
                            "EXECUTOR_DECISION_PACKET",
                        ],
                        produced_state_kinds=[],
                    ),
                ],
            ),
            transport=executor_transport,
            socket_path=executor_socket_path,
        ),
        "summarizer": SummarizerAgent(
            agent_id="summarizer",
            capability=_build_capability(
                "summarizer",
                action="SUMMARIZE_AND_COMMIT",
                accepted_state_kinds=[
                    "DENSE_EVIDENCE",
                    "FEATURE_BUNDLE",
                    "TOOL_ARTIFACT",
                ],
                produced_state_kinds=["TOOL_ARTIFACT"],
            ),
            llm_client=active_llm,
        ),
    }


def build_sample_agents_with_executor(
    *,
    llm_client: LLMClient | None = None,
    executor_transport: str | None = None,
    executor_socket_path: str | None = None,
) -> dict[str, BaseAgent]:
    previous_transport = os.environ.get("STATEBUS_EXECUTOR_TRANSPORT")
    previous_socket_path = os.environ.get("STATEBUS_EXECUTOR_SOCKET_PATH")
    try:
        if executor_transport is None:
            os.environ.pop("STATEBUS_EXECUTOR_TRANSPORT", None)
        else:
            os.environ["STATEBUS_EXECUTOR_TRANSPORT"] = executor_transport
        if executor_socket_path is None:
            os.environ.pop("STATEBUS_EXECUTOR_SOCKET_PATH", None)
        else:
            os.environ["STATEBUS_EXECUTOR_SOCKET_PATH"] = executor_socket_path
        return build_sample_agents(llm_client=llm_client)
    finally:
        if previous_transport is None:
            os.environ.pop("STATEBUS_EXECUTOR_TRANSPORT", None)
        else:
            os.environ["STATEBUS_EXECUTOR_TRANSPORT"] = previous_transport
        if previous_socket_path is None:
            os.environ.pop("STATEBUS_EXECUTOR_SOCKET_PATH", None)
        else:
            os.environ["STATEBUS_EXECUTOR_SOCKET_PATH"] = previous_socket_path


def _plan_from_llm_output(task: SampleTask, output_text: str) -> Plan:
    payload = extract_json_object(output_text)
    steps = payload.get("steps")
    if not isinstance(steps, list) and any(key in payload for key in ("r", "x", "s")):
        steps = _compact_planner_output_to_steps(payload)
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"planner output missing steps: {output_text!r}")
    if not 3 <= len(steps) <= 5:
        raise ValueError(f"planner output must contain 3-5 steps: {output_text!r}")
    plan_steps: list[PlanStep] = []
    seen_step_ids: set[str] = set()
    for step in steps:
        normalized = _normalize_planner_step(step, task=task)
        step_id = normalized["step_id"]
        if step_id in seen_step_ids:
            raise ValueError(f"duplicate planner step_id: {step_id}")
        seen_step_ids.add(step_id)
        plan_steps.append(
            PlanStep(
                step_id=step_id,
                owner_agent=normalized["owner_agent"],
                action=normalized["action"],
                input_state_refs=normalized["input_state_refs"],
                params=normalized["params"],
                depends_on=normalized["depends_on"],
                semantic_role=normalized["semantic_role"],
            )
        )
    _validate_plan_dag(plan_steps)
    _validate_planner_semantic_coverage(task=task, plan_steps=plan_steps)
    return Plan(task_id=task.task_id, goal=task.goal, steps=plan_steps)


def _summary_from_llm_output(output_text: str) -> dict[str, Any]:
    payload = extract_json_object(output_text)
    if "summary" not in payload and "s" in payload:
        payload = {
            "summary": payload.get("s", ""),
            "confidence": payload.get("c", payload.get("confidence", 0.95)),
            "tags": payload.get("t", payload.get("tags", [])),
            "reusable_steps": payload.get("r", payload.get("reusable_steps", ["retrieve", "execute"])),
        }
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        raise ValueError(f"summarizer output missing summary: {output_text!r}")
    payload["summary"] = summary
    payload["confidence"] = _normalize_confidence(payload.get("confidence", 0.95))
    payload["tags"] = [str(tag) for tag in payload.get("tags", [])]
    reusable_steps = payload.get("reusable_steps", ["retrieve", "execute"])
    if isinstance(reusable_steps, str):
        reusable_steps = [reusable_steps]
    payload["reusable_steps"] = [str(step_id) for step_id in reusable_steps]
    return payload


def _planner_messages(payload: dict[str, Any], *, mode: str) -> list[ChatMessage]:
    if mode == "text":
        system_prompt = (
            "You are the StateBus Planner. Output strict JSON only. "
            "Return an object with a single key named steps. "
            "Each step must include step_id, semantic_role, owner_agent, action, input_state_refs, params, depends_on. "
            "Return an executable DAG with 3 to 5 steps. "
            "Allowed owner_agent values: planner, retriever, executor, summarizer. "
            "Allowed action values: RETRIEVE_EVIDENCE, EXECUTE_PLAYBOOK, SUMMARIZE_AND_COMMIT, VALIDATE_ROUTE, CHECK_MEMORY_REUSE. "
            "The plan must include retrieve, execute, and summarize semantics, but step ids and wording do not need to be fixed. "
            "For RETRIEVE_EVIDENCE include query, evidence_text, tags, allow_memory_reuse, and audit_disable_state_kinds in params. "
            "For SUMMARIZE_AND_COMMIT include summary_hint and tags in params. "
            "For EXECUTE_PLAYBOOK params may be {}. "
            "Do not infer replay eligibility, corpus filters, or tool routes from hidden benchmark hints. "
            "Use unique step_id values and valid depends_on edges only. "
            "Do not add prose or markdown."
        )
        system_prompt = (
            "You are the StateBus Planner in a text-only collaboration baseline. "
            "Another agent is handing you a natural language task brief instead of a structured control packet. "
            + system_prompt
        )
        user_prompt = (
            "Planner brief for a text-only multi-agent workflow.\n\n"
            f"Task ID: {payload['task_id']}\n"
            f"Task group: {payload['task_group']}\n"
            f"Task theme: {payload['task_theme']}\n"
            f"Tags: {', '.join(payload.get('tags', []))}\n"
            "\n"
            "Goal:\n"
            f"{payload['goal']}\n\n"
            "Search query:\n"
            f"{payload['query']}\n\n"
            "Summary hint:\n"
            f"{payload['summary_hint']}\n\n"
            "Evidence note:\n"
            f"{payload['evidence_text']}\n"
        )
    else:
        system_prompt = (
            "You are the StateBus Planner. Output JSON only. "
            "Return either {\"steps\":[...]} or the compact shape {\"r\":{...},\"x\":{},\"s\":{...}}. "
            "If you use steps, emit a 3-5 step executable DAG. "
            "Allowed owner_agent values: planner, retriever, executor, summarizer. "
            "Allowed action values: RETRIEVE_EVIDENCE, EXECUTE_PLAYBOOK, SUMMARIZE_AND_COMMIT, VALIDATE_ROUTE, CHECK_MEMORY_REUSE. "
            "The plan must cover retrieve, execute, and summarize semantics. "
            "If you use the compact shape, r must contain q,e,t and optional sid/dep/action/owner/role. s must contain h,t and optional sid/dep/action/owner/role. "
            "Do not emit replay labels, corpus filters, or tool-route hints. "
            "No markdown."
        )
        user_prompt = tagged_json_block(
            PROTOCOL_PLANNER_TAG,
            {
                "g": payload["goal"],
                "q": payload["query"],
                "e": payload["evidence_text"],
                "h": payload["summary_hint"],
                "t": list(payload["tags"]),
            },
        )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]


def _summarizer_messages(payload: dict[str, Any], *, mode: str) -> list[ChatMessage]:
    if mode == "text":
        system_prompt = (
            "You are the StateBus Summarizer. Output strict JSON only. "
            "Return an object with summary, confidence, tags, and reusable_steps. "
            "Base the summary on the evidence and playbook. Keep it concise but concrete. "
            "Do not add markdown fences or extra prose."
        )
        system_prompt = (
            "You are the StateBus Summarizer in a text-only collaboration baseline. "
            "You are receiving a natural language handoff from prior agents instead of a structured packet. "
            + system_prompt
        )
        user_prompt = (
            "Summarizer handoff for a text-only multi-agent workflow.\n\n"
            f"Task ID: {payload['task_id']}\n"
            f"Task theme: {payload['task_theme']}\n"
            f"Tags: {', '.join(payload['tags'])}\n"
            f"Reusable steps: {', '.join(payload['reusable_steps'])}\n\n"
            "Summary hint:\n"
            f"{payload['summary_hint']}\n\n"
            "Evidence note:\n"
            f"{payload['evidence_text']}\n\n"
            "Playbook actions:\n"
            f"{payload['actions_text']}\n"
        )
    else:
        system_prompt = (
            "You are the StateBus Summarizer. Output JSON only. "
            "Return {\"s\":\"summary\",\"c\":0.95,\"t\":[...],\"r\":[...]} . "
            "Use concise concrete summary text. No markdown."
        )
        user_prompt = tagged_json_block(
            PROTOCOL_SUMMARIZER_TAG,
            {
                "h": payload["summary_hint"],
                "e": payload["evidence_text"],
                "a": payload["actions_text"],
                "t": list(payload["tags"]),
                "r": list(payload["reusable_steps"]),
            },
        )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]


def _compact_planner_output_to_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    retrieve = dict(payload.get("r") or {})
    execute = dict(payload.get("x") or {})
    summarize = dict(payload.get("s") or {})
    if not retrieve and not summarize and "steps" not in payload:
        raise ValueError(f"planner output missing steps: {payload!r}")
    retrieve_params: dict[str, Any] = {
        "query": retrieve.get("q", ""),
        "evidence_text": retrieve.get("e", ""),
        "tags": list(retrieve.get("t", [])),
        "allow_memory_reuse": True,
    }
    summarize_params: dict[str, Any] = {
        "summary_hint": summarize.get("h", ""),
        "tags": list(summarize.get("t", [])),
    }
    has_validate_step = any(key in execute for key in ("vsid", "vowner", "vaction", "vdep"))
    steps = [
        {
            "step_id": retrieve.get("sid", "retrieve"),
            "semantic_role": retrieve.get("role", "retrieve"),
            "owner_agent": retrieve.get("owner", "retriever"),
            "action": retrieve.get("action", "RETRIEVE_EVIDENCE"),
            "depends_on": retrieve.get("dep", []),
            "params": retrieve_params,
        }
    ]
    if has_validate_step:
        steps.append(
            {
                "step_id": execute.get("vsid", "validate"),
                "semantic_role": execute.get("vrole", "validate"),
                "owner_agent": execute.get("vowner", "executor"),
                "action": execute.get("vaction", "VALIDATE_ROUTE"),
                "depends_on": execute.get("vdep", ["retrieve"]),
                "params": {},
            }
        )
    steps.extend(
        [
            {
                "step_id": execute.get("sid", "execute"),
                "semantic_role": execute.get("role", "execute"),
                "owner_agent": execute.get("owner", "executor"),
                "action": execute.get("action", "EXECUTE_PLAYBOOK"),
                "depends_on": execute.get("dep", ["retrieve", "validate"] if has_validate_step else ["retrieve"]),
                "params": execute,
            },
            {
                "step_id": summarize.get("sid", "summarize"),
                "semantic_role": summarize.get("role", "summarize"),
                "owner_agent": summarize.get("owner", "summarizer"),
                "action": summarize.get("action", "SUMMARIZE_AND_COMMIT"),
                "depends_on": summarize.get("dep", ["retrieve", "execute"]),
                "params": summarize_params,
            },
        ]
    )
    return steps


def _normalize_planner_step(step: object, *, task: SampleTask) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError(f"planner step must be an object: {step!r}")
    normalized = dict(step)
    nested_step_alias = ""
    if "step_id" not in normalized and len(normalized) == 1:
        nested_key = next(iter(normalized))
        nested = normalized[nested_key]
        if nested_key in {"retrieve", "execute", "summarize", "validate", "planner"}:
            if not isinstance(nested, dict):
                raise ValueError(f"planner nested step must be an object: {step!r}")
            normalized = {"step_id": nested_key, **dict(nested)}
            nested_step_alias = nested_key

    raw_step_id = str(normalized.get("step_id", "")).strip()
    if not raw_step_id:
        raise ValueError(f"planner step missing step_id: {step!r}")
    normalized_step_aliases = {
        "1": "retrieve",
        "2": "execute",
        "3": "summarize",
        "retrieve": "retrieve",
        "execute": "execute",
        "summarize": "summarize",
    }
    step_id = normalized_step_aliases.get(raw_step_id.lower(), raw_step_id)
    if nested_step_alias:
        step_id = normalized_step_aliases.get(nested_step_alias, nested_step_alias)
    semantic_role = str(
        normalized.get("semantic_role", normalized.get("role", nested_step_alias))
    ).strip().lower()
    owner_agent = str(normalized.get("owner_agent", normalized.get("owner", ""))).strip().lower()
    action = str(normalized.get("action", "")).strip().upper()
    if owner_agent not in ALLOWED_PLANNER_OWNER_AGENTS:
        raise ValueError(f"planner step owner_agent unsupported: {owner_agent!r}")
    if action not in ALLOWED_PLANNER_ACTIONS:
        raise ValueError(f"planner step action unsupported: {action!r}")
    if not semantic_role:
        raise ValueError(f"planner step missing semantic_role: {step!r}")
    raw_params = dict(normalized.get("params", {}) or {})
    params = dict(raw_params)
    if action == "RETRIEVE_EVIDENCE":
        params = {
            "query": raw_params.get("query", task.query),
            "evidence_text": raw_params.get("evidence_text", task.evidence_text),
            "tags": raw_params.get("tags", list(task.tags)),
            "allow_memory_reuse": raw_params.get("allow_memory_reuse", True),
            "audit_disable_state_kinds": raw_params.get(
                "audit_disable_state_kinds",
                list(task.audit_disable_state_kinds),
            ),
        }
    elif action == "SUMMARIZE_AND_COMMIT":
        params = {
            "summary_hint": raw_params.get("summary_hint", task.summary_hint),
            "tags": raw_params.get("tags", list(task.tags)),
        }
    raw_depends_on = [str(item) for item in normalized.get("depends_on", []) or []]
    depends_on = [normalized_step_aliases.get(dep.lower(), dep) for dep in raw_depends_on]
    if semantic_role == "summarize" and depends_on == ["execute"]:
        depends_on = ["retrieve", "execute"]
    if not depends_on:
        if semantic_role == "execute":
            depends_on = ["retrieve"]
        elif semantic_role == "summarize":
            depends_on = ["retrieve", "execute"]
    return {
        "step_id": step_id,
        "semantic_role": semantic_role,
        "owner_agent": owner_agent,
        "action": action,
        "input_state_refs": [str(item) for item in normalized.get("input_state_refs", []) or []],
        "params": params,
        "depends_on": depends_on,
    }


def _validate_plan_dag(plan_steps: list[PlanStep]) -> None:
    step_ids = {step.step_id for step in plan_steps}
    for step in plan_steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                raise ValueError(f"planner step depends_on unknown step_id: {dep}")
            if dep == step.step_id:
                raise ValueError(f"planner step cannot depend on itself: {dep}")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {step.step_id: step for step in plan_steps}

    def _visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            raise ValueError(f"planner depends_on must form a DAG, cycle at {step_id}")
        visiting.add(step_id)
        for dep in by_id[step_id].depends_on:
            _visit(dep)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in by_id:
        _visit(step_id)


def _validate_planner_semantic_coverage(task: SampleTask, plan_steps: list[PlanStep]) -> None:
    del task
    semantic_roles = {str(step.semantic_role or step.step_id).strip().lower() for step in plan_steps}
    missing = [role for role in ("retrieve", "execute", "summarize") if role not in semantic_roles]
    if missing:
        raise ValueError(f"planner output missing required semantics: {', '.join(missing)}")


def _normalize_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if not text:
        return 0.95
    if text == "high":
        return 0.95
    if text == "medium":
        return 0.75
    if text == "low":
        return 0.55
    try:
        return float(text)
    except ValueError:
        return 0.95


def _build_transfer_brief(
    *,
    query: str,
    retrieved_doc_ids: list[str],
    route: str,
    tool_name: str,
    route_source: str,
    route_confidence: float,
    route_provenance: list[str],
    matched_signals: list[str],
    matched_tags: list[str],
    match_score: int,
    hint_doc_ids: list[str],
    hint_route: str,
    hint_tool_name: str,
    tool_candidates: list[dict[str, Any]],
    memory_assist_ids: list[str],
    evidence_text: str,
) -> str:
    preview = evidence_text.strip().splitlines()
    evidence_preview = " ".join(line.strip() for line in preview[:4] if line.strip())[:280]
    lines = [
        "StateBus transfer brief",
        f"Query: {query}",
        f"Retrieved docs: {', '.join(retrieved_doc_ids) if retrieved_doc_ids else 'none'}",
        f"Suggested route: {route}",
        f"Suggested tool: {tool_name or 'none'}",
        f"Route source: {route_source}",
        f"Route confidence: {route_confidence:.2f}",
        f"Route provenance: {', '.join(route_provenance) if route_provenance else 'none'}",
        f"Match score: {match_score}",
        f"Tool candidates: {_format_transfer_tool_candidates(tool_candidates)}",
    ]
    if matched_signals:
        lines.append(f"Matched signals: {', '.join(matched_signals)}")
    if matched_tags:
        lines.append(f"Matched tags: {', '.join(matched_tags)}")
    if hint_doc_ids:
        lines.append(f"Hint docs: {', '.join(hint_doc_ids)}")
    if hint_route:
        lines.append(f"Hint route: {hint_route}")
    if hint_tool_name:
        lines.append(f"Hint tool: {hint_tool_name}")
    if memory_assist_ids:
        lines.append(f"Memory assist ids: {', '.join(memory_assist_ids)}")
    lines.append(f"Evidence preview: {evidence_preview}")
    return "\n".join(lines) + "\n"


def _format_transfer_tool_candidates(candidates: list[dict[str, Any]]) -> str:
    serialized: list[str] = []
    for candidate in candidates:
        tool_name = str(candidate.get("tool_name", "")).strip()
        route = str(candidate.get("route", "")).strip()
        source = str(candidate.get("source", "")).strip()
        score = int(candidate.get("score", 0))
        if not tool_name or not route:
            continue
        serialized.append(f"{tool_name}@{route}#{source}#{score}")
    return "; ".join(serialized) if serialized else "none"


def _build_memory_assist_hint(hit: MemoryCommit | Any) -> str:
    memory_id = str(getattr(hit, "memory_id", "")).strip()
    summary = " ".join(str(getattr(hit, "summary", "")).split())
    if len(summary) > MAX_MEMORY_ASSIST_HINT_CHARS:
        summary = summary[: MAX_MEMORY_ASSIST_HINT_CHARS - 3].rstrip() + "..."
    if not memory_id and not summary:
        return ""
    if not summary:
        return f"MEMORY_ASSIST_HINT {memory_id}".strip()
    return f"MEMORY_ASSIST_HINT {memory_id}: {summary}".strip()


def _load_feature_bundle_from_ref(ctx: object, ref: object | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    payload = ctx.statepool.get_bytes(ref)
    feature_bundle = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(feature_bundle, dict):
        return None
    return dict(feature_bundle)


def _build_protocol_summary_handoff(
    *,
    query: str,
    route: str,
    route_source: str,
    route_confidence: float,
    retrieved_doc_ids: list[str],
    matched_signals: list[str],
    memory_assist_hint: str,
    evidence_preview: str,
) -> str:
    doc_ids = ", ".join(retrieved_doc_ids[:MAX_PROTOCOL_SUMMARY_DOC_IDS]) if retrieved_doc_ids else "none"
    signals = ", ".join(matched_signals[:MAX_PROTOCOL_SUMMARY_SIGNALS]) if matched_signals else "none"
    parts = [
        "StateBus protocol summary handoff",
        f"Query: {query}",
        f"Route: {route or 'generic_triage'}",
        f"Route source: {route_source or 'protocol'}",
        f"Route confidence: {route_confidence:.2f}",
        f"Retrieved docs: {doc_ids}",
        f"Matched signals: {signals}",
    ]
    if memory_assist_hint.strip():
        parts.append(memory_assist_hint.strip())
    if evidence_preview.strip():
        parts.append(f"Evidence preview: {evidence_preview.strip()}")
    return "\n".join(parts) + "\n"


def _build_protocol_summary_input_packet(
    *,
    query: str,
    route: str,
    route_source: str,
    route_confidence: float,
    retrieved_doc_ids: list[str],
    matched_signals: list[str],
    actions_text: str,
    summary_hint: str,
    memory_assist_hint: str,
) -> dict[str, Any]:
    return {
        "schema": "statebus.summary_input_packet.v1",
        "query": query,
        "route": route or "generic_triage",
        "route_source": route_source or "protocol",
        "route_confidence": route_confidence,
        "retrieved_doc_ids": retrieved_doc_ids[:MAX_PROTOCOL_SUMMARY_DOC_IDS],
        "matched_signals": matched_signals[:MAX_PROTOCOL_SUMMARY_SIGNALS],
        "actions_text": actions_text.strip(),
        "summary_hint": summary_hint.strip(),
        "memory_assist_hint": memory_assist_hint.strip(),
    }


def _resolve_runtime_corpus_hints(*, ctx: object, corpus_docs: list[object]) -> list[dict[str, str]]:
    if _formal_structure_clean_retrieval(ctx):
        return []
    task_metadata = getattr(getattr(ctx, "task", None), "task_set_metadata", None)
    runtime_hint_allowed = True
    if isinstance(task_metadata, TaskSetMetadata):
        runtime_hint_allowed = task_metadata.runtime_hint_allowed
    if not runtime_hint_allowed:
        return []
    return extract_corpus_feature_hints(corpus_docs)


def _runtime_preferred_doc_bias_allowed(ctx: object) -> bool:
    task_metadata = getattr(getattr(ctx, "task", None), "task_set_metadata", None)
    if isinstance(task_metadata, TaskSetMetadata):
        return task_metadata.runtime_hint_allowed and not task_metadata.formal_structure_clean_retrieval
    return True


def _formal_structure_clean_retrieval(ctx: object) -> bool:
    task_metadata = getattr(getattr(ctx, "task", None), "task_set_metadata", None)
    if isinstance(task_metadata, TaskSetMetadata):
        return task_metadata.formal_structure_clean_retrieval
    return False
