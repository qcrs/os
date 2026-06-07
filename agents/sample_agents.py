from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agents.base_agent import BaseAgent
from protocol.messages import (
    Capability,
    CapabilityItem,
    MemoryCommit,
    Plan,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StepResult,
)
from runtime.executor_runtime import build_feature_bundle, execute_playbook_step
from runtime.llm import (
    ChatMessage,
    DeterministicLLMClient,
    LLMClient,
    extract_json_object,
    tagged_json_block,
)
from runtime.uds_transport import request_response
from tasks.local_corpus import render_corpus_evidence, retrieve_corpus_docs
from tasks.sample_tasks import SampleTask

PROTOCOL_PLANNER_TAG = "sb-plan-v1"
PROTOCOL_SUMMARIZER_TAG = "sb-summary-v1"


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
        raise NotImplementedError("planner does not execute plan steps directly")

    async def plan_task(self, task: SampleTask, ctx: object) -> Plan:
        planner_input = {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "corpus_doc_ids": list(task.corpus_doc_ids),
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "reuse_tags": list(task.reuse_tags or task.tags),
            "reuse_signature": task.reuse_signature,
            "expected_reuse_mode": task.expected_reuse_mode,
            "summary_hint": task.summary_hint,
        }
        messages = _planner_messages(planner_input, mode=str(getattr(ctx, "mode", "protocol")))
        result = await self.llm_client.complete(messages, purpose="planner")
        ctx.record_llm_result(result)
        return _plan_from_llm_output(task, result.text)


@dataclass
class RetrieverAgent(BaseAgent):
    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        corpus_docs = retrieve_corpus_docs(
            query=str(step.params["query"]),
            tags=list(step.params.get("tags", [])),
            task_group=str(getattr(ctx, "task_group", "")),
            task_theme=str(getattr(ctx, "task_theme", "")),
            corpus_doc_ids=list(step.params.get("corpus_doc_ids", [])),
            embedder=ctx.memory_store.embedder,
        )
        fresh_evidence_text = render_corpus_evidence(corpus_docs)
        fresh_bundle = build_feature_bundle(
            query=str(step.params["query"]),
            evidence_text=fresh_evidence_text,
            tags=list(step.params.get("tags", [])),
            reuse_signature=str(step.params.get("reuse_signature", "")),
            reused_memory=False,
        )

        hits = []
        accepted_hit = None
        memory_hint_route = ""
        if step.params.get("allow_memory_reuse"):
            hits = ctx.search_memory(
                task_theme=ctx.task_theme,
                query_text=str(step.params["query"]),
                top_k=3,
                tags=[],
                tags_any=list(step.params.get("tags", [])),
                tags_all=[],
                min_confidence=0.6,
                encoder_id=ctx.memory_store.embedder.encoder_id,
            )
            if hits:
                for candidate in hits:
                    candidate_route = str(candidate.metadata.get("feature_route", "")).strip()
                    if (
                        candidate_route
                        and candidate_route == fresh_bundle["route"]
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
        evidence_sections = [fresh_evidence_text]
        if accepted_hit is not None:
            evidence_sections.append(f"MEMORY_ASSIST {accepted_hit.memory_id}: {accepted_hit.summary}")
        benchmark_note = str(step.params.get("evidence_text", "")).strip()
        if benchmark_note:
            evidence_sections.append(f"BENCHMARK_NOTE {benchmark_note}")
        evidence_text = "\n\n".join(section for section in evidence_sections if section.strip())

        evidence_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-evidence",
            kind="DENSE_EVIDENCE",
            text=evidence_text,
            metadata={
                "query": step.params["query"],
                "reused_memory": reused,
                "reuse_signature": step.params.get("reuse_signature"),
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "memory_assist_ids": memory_assist_ids,
            },
        )
        feature_bundle = build_feature_bundle(
            query=str(step.params["query"]),
            evidence_text=evidence_text,
            tags=list(step.params.get("tags", [])),
            reuse_signature=str(step.params.get("reuse_signature", "")),
            reused_memory=reused,
        )
        feature_bundle["corpus_doc_ids"] = [doc.doc_id for doc in corpus_docs]
        feature_bundle["memory_assist_ids"] = memory_assist_ids
        feature_bundle["memory_hint_route"] = memory_hint_route
        feature_bundle["expected_reuse_mode"] = str(step.params.get("expected_reuse_mode", "none"))
        feature_ref = ctx.put_feature_state(
            state_id=f"{ctx.task_id}-{step.step_id}-features",
            feature_bundle=feature_bundle,
            metadata={
                "query": step.params["query"],
                "reused_memory": reused,
                "reuse_signature": step.params.get("reuse_signature"),
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "memory_assist_ids": memory_assist_ids,
            },
        )
        embedding_ref = ctx.put_embedding_state(
            state_id=f"{ctx.task_id}-{step.step_id}-embedding",
            text=str(step.params["query"]),
            metadata={
                "query": step.params["query"],
                "source_text_kind": "query",
            },
        )
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[evidence_ref, feature_ref, embedding_ref],
            payload={
                "query": step.params["query"],
                "memory_hits": [hit.memory_id for hit in hits],
                "memory_assist_ids": memory_assist_ids,
                "reused_memory": reused,
                "reuse_mode": "assist" if reused else "none",
                "feature_route": feature_bundle["route"],
                "retrieved_doc_ids": [doc.doc_id for doc in corpus_docs],
                "corpus_doc_count": len(corpus_docs),
                "memory_hint_route": memory_hint_route,
            },
        )


@dataclass
class ExecutorAgent(BaseAgent):
    transport: str = "local"
    socket_path: str | None = None

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        retrieve_result = ctx.results[step.depends_on[0]]
        input_refs = [
            ref
            for ref in retrieve_result.output_state_refs
            if ref.kind in {"DENSE_EVIDENCE", "FEATURE_BUNDLE"}
        ]
        if self._should_use_uds(step):
            return self._execute_via_uds(step, ctx, input_refs)
        return execute_playbook_step(
            task_id=ctx.task_id,
            task_theme=ctx.task_theme,
            step=step,
            statepool=ctx.statepool,
            input_state_refs=input_refs,
        )

    def _should_use_uds(self, step: PlanStep) -> bool:
        transport = str(step.params.get("transport", self.transport or "local")).strip().lower()
        return transport == "uds"

    def _execute_via_uds(self, step: PlanStep, ctx: object, input_refs: list[object]) -> StepResult:
        socket_path = step.params.get("socket_path") or self.socket_path
        if not socket_path:
            raise ValueError("executor uds transport selected without socket_path")
        message = RemoteStepRequest(
            mode=str(getattr(ctx, "mode", "protocol")),
            task_id=str(ctx.task_id),
            task_theme=str(ctx.task_theme),
            state_root=str(ctx.statepool.root),
            step=step,
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
        retrieve_result = ctx.results["retrieve"]
        execute_result = ctx.results["execute"]
        evidence_ref = next(
            ref for ref in retrieve_result.output_state_refs if ref.kind == "DENSE_EVIDENCE"
        )
        feature_ref = next(
            (ref for ref in retrieve_result.output_state_refs if ref.kind == "FEATURE_BUNDLE"),
            None,
        )
        embedding_ref = next(
            (ref for ref in retrieve_result.output_state_refs if ref.kind == "EMBEDDING"),
            None,
        )
        artifact_ref = execute_result.output_state_refs[0]
        evidence_text = ctx.get_text_state(evidence_ref)
        actions_text = ctx.get_text_state(artifact_ref)
        reusable_steps = list(execute_result.payload.get("reusable_steps", ["retrieve", "execute"]))
        summary_input = {
            "task_id": ctx.task_id,
            "task_theme": ctx.task_theme,
            "summary_hint": step.params["summary_hint"],
            "evidence_text": evidence_text,
            "actions_text": actions_text,
            "tags": list(step.params.get("tags", [])),
            "reusable_steps": reusable_steps,
        }
        messages = _summarizer_messages(summary_input, mode=str(getattr(ctx, "mode", "protocol")))
        result = await self.llm_client.complete(messages, purpose="summarizer")
        ctx.record_llm_result(result)
        summary_payload = _summary_from_llm_output(result.text)
        summary_text = str(summary_payload["summary"]).strip()
        summary_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-summary",
            kind="TOOL_ARTIFACT",
            text=summary_text,
            metadata={"task_theme": ctx.task_theme},
        )
        commit = MemoryCommit(
            memory_id=f"mem-{ctx.task_id}",
            source_agent_id=self.agent_id,
            source_task_id=ctx.task_id,
            task_theme=ctx.task_theme,
            summary=summary_text,
            tags=list(summary_payload.get("tags") or step.params.get("tags", [])),
            evidence_state_ids=[
                evidence_ref.state_id,
                *([feature_ref.state_id] if feature_ref is not None else []),
                *([embedding_ref.state_id] if embedding_ref is not None else []),
                artifact_ref.state_id,
                summary_ref.state_id,
            ],
            reusable_steps=list(summary_payload.get("reusable_steps") or reusable_steps),
            confidence=float(summary_payload.get("confidence", 0.95)),
            embedding_text=summary_text,
            embedding_state_id=embedding_ref.state_id if embedding_ref is not None else None,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            metadata={
                "source_agent_id": self.agent_id,
                "goal": getattr(ctx, "task_id", ""),
                "task_group": getattr(ctx, "task_group", ""),
                "reuse_signature": step.params.get("reuse_signature"),
                "expected_reuse_mode": str(step.params.get("expected_reuse_mode", "none")),
                "feature_route": execute_result.payload.get("route", ""),
                "trace_id": ctx.trace_id,
                "llm_model": result.model,
            },
            evidence_state_refs=[
                evidence_ref,
                *([feature_ref] if feature_ref is not None else []),
                *([embedding_ref] if embedding_ref is not None else []),
                artifact_ref,
                summary_ref,
            ],
        )
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[summary_ref],
            payload={"summary": summary_text, "llm_model": result.model},
            memory_commit=commit,
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
                produced_state_kinds=["DENSE_EVIDENCE", "FEATURE_BUNDLE", "EMBEDDING"],
            ),
        ),
        "executor": ExecutorAgent(
            agent_id="executor",
            capability=_build_capability(
                "executor",
                action="EXECUTE_PLAYBOOK",
                accepted_state_kinds=["DENSE_EVIDENCE", "FEATURE_BUNDLE"],
                produced_state_kinds=["TOOL_ARTIFACT"],
            ),
            transport=executor_transport,
            socket_path=executor_socket_path,
        ),
        "summarizer": SummarizerAgent(
            agent_id="summarizer",
            capability=_build_capability(
                "summarizer",
                action="SUMMARIZE_AND_COMMIT",
                accepted_state_kinds=["DENSE_EVIDENCE", "TOOL_ARTIFACT"],
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
    expected_contract = _expected_plan_contract(task)
    if len(steps) != len(expected_contract):
        raise ValueError(f"planner output must contain exactly 3 steps: {output_text!r}")
    plan_steps: list[PlanStep] = []
    seen_step_ids: set[str] = set()
    for index, step in enumerate(steps):
        normalized = _normalize_planner_step(step, expected_contract[index])
        expected_step_id = normalized["expected_step_id"]
        expected_owner = normalized["expected_owner"]
        expected_action = normalized["expected_action"]
        step_id = normalized["step_id"]
        if step_id in seen_step_ids:
            raise ValueError(f"duplicate planner step_id: {step_id}")
        if (
            step_id != expected_step_id
            or normalized["owner_agent"] != expected_owner
            or normalized["action"] != expected_action
        ):
            raise ValueError(f"planner step contract mismatch at {step_id}: {output_text!r}")
        seen_step_ids.add(step_id)
        plan_steps.append(
            PlanStep(
                step_id=step_id,
                owner_agent=normalized["owner_agent"],
                action=normalized["action"],
                input_state_refs=normalized["input_state_refs"],
                params=normalized["params"],
                depends_on=normalized["depends_on"],
            )
        )
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


def _expected_plan_contract(task: SampleTask) -> list[dict[str, Any]]:
    return [
        {
            "step_id": "retrieve",
            "owner_agent": "retriever",
            "action": "RETRIEVE_EVIDENCE",
            "input_state_refs": [],
            "params": {
                "query": task.query,
                "corpus_doc_ids": list(task.corpus_doc_ids),
                "evidence_text": task.evidence_text,
                "tags": list(task.tags),
                "reuse_tags": list(task.reuse_tags or task.tags),
                "reuse_signature": task.reuse_signature,
                "expected_reuse_mode": task.expected_reuse_mode,
                "allow_memory_reuse": True,
            },
            "depends_on": [],
        },
        {
            "step_id": "execute",
            "owner_agent": "executor",
            "action": "EXECUTE_PLAYBOOK",
            "input_state_refs": [],
            "params": {},
            "depends_on": ["retrieve"],
        },
        {
            "step_id": "summarize",
            "owner_agent": "summarizer",
            "action": "SUMMARIZE_AND_COMMIT",
            "input_state_refs": [],
            "params": {
                "summary_hint": task.summary_hint,
                "tags": list(task.tags),
                "reuse_tags": list(task.reuse_tags or task.tags),
                "reuse_signature": task.reuse_signature,
                "expected_reuse_mode": task.expected_reuse_mode,
            },
            "depends_on": ["retrieve", "execute"],
        },
    ]


def _planner_messages(payload: dict[str, Any], *, mode: str) -> list[ChatMessage]:
    expected_reuse_mode = str(
        payload.get(
            "expected_reuse_mode",
            "assist" if bool(payload.get("expected_reuse", False)) else "none",
        )
    )
    if mode == "text":
        system_prompt = (
            "You are the StateBus Planner. Output strict JSON only. "
            "Return an object with a single key named steps. "
            "Use exactly three steps with these fixed contracts and exact field names: "
            "step_id, owner_agent, action, input_state_refs, params, depends_on. "
            "Step 1 must be retrieve -> owner_agent retriever action RETRIEVE_EVIDENCE. "
            "Step 2 must be execute -> owner_agent executor action EXECUTE_PLAYBOOK. "
            "Step 3 must be summarize -> owner_agent summarizer action SUMMARIZE_AND_COMMIT. "
            "retrieve.params must include query, corpus_doc_ids, evidence_text, tags, "
            "expected_reuse_mode, and allow_memory_reuse=true. execute.params must be {}. "
            "summarize.params must include summary_hint, tags, and expected_reuse_mode. "
            "Do not wrap each step inside a retrieve/execute/summarize key. "
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
            f"Expected reuse mode: {expected_reuse_mode}\n"
            f"Corpus docs: {', '.join(payload.get('corpus_doc_ids', []))}\n\n"
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
            "Return {\"r\":{...},\"x\":{},\"s\":{...}}. "
            "r must contain q,e,t,cd,rt,sig,erm. "
            "s must contain h,t,rt,sig,erm. "
            "Copy values from the input packet. Keep keys short. No markdown."
        )
        user_prompt = tagged_json_block(
            PROTOCOL_PLANNER_TAG,
            {
                "g": payload["goal"],
                "q": payload["query"],
                "e": payload["evidence_text"],
                "h": payload["summary_hint"],
                "t": list(payload["tags"]),
                "cd": list(payload.get("corpus_doc_ids", [])),
                "rt": list(payload.get("reuse_tags", payload["tags"])),
                "sig": payload.get("reuse_signature", ""),
                "erm": expected_reuse_mode,
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
    return [
        {
            "step_id": "retrieve",
            "params": {
                "query": retrieve.get("q", ""),
                "corpus_doc_ids": list(retrieve.get("cd", [])),
                "evidence_text": retrieve.get("e", ""),
                "tags": list(retrieve.get("t", [])),
                "reuse_tags": list(retrieve.get("rt", retrieve.get("t", []))),
                "reuse_signature": str(retrieve.get("sig", "")),
                "expected_reuse_mode": str(retrieve.get("erm", "none")),
                "allow_memory_reuse": True,
            },
        },
        {
            "step_id": "execute",
            "params": execute,
        },
        {
            "step_id": "summarize",
            "params": {
                "summary_hint": summarize.get("h", ""),
                "tags": list(summarize.get("t", [])),
                "reuse_tags": list(summarize.get("rt", summarize.get("t", []))),
                "reuse_signature": str(summarize.get("sig", "")),
                "expected_reuse_mode": str(summarize.get("erm", "none")),
            },
        },
    ]


def _normalize_planner_step(step: object, expected: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError(f"planner step must be an object: {step!r}")
    normalized = dict(step)
    expected_step_id = str(expected["step_id"])
    if "step_id" not in normalized:
        nested = normalized.get(expected_step_id)
        if nested is None and len(normalized) == 1:
            nested_key = next(iter(normalized))
            if nested_key in {"retrieve", "execute", "summarize"}:
                nested = normalized[nested_key]
                expected_step_id = str(nested_key)
        if nested is not None:
            if not isinstance(nested, dict):
                raise ValueError(f"planner nested step must be an object: {step!r}")
            normalized = {"step_id": expected_step_id, **dict(nested)}

    params = dict(expected["params"])
    params.update(dict(normalized.get("params", {}) or {}))
    input_state_refs = normalized.get("input_state_refs", expected["input_state_refs"])
    depends_on = normalized.get("depends_on", expected["depends_on"])
    return {
        "expected_step_id": str(expected["step_id"]),
        "expected_owner": str(expected["owner_agent"]),
        "expected_action": str(expected["action"]),
        "step_id": str(normalized.get("step_id", "")),
        "owner_agent": str(
            normalized.get("owner_agent", normalized.get("owner", expected["owner_agent"]))
        ),
        "action": str(normalized.get("action", expected["action"])),
        "input_state_refs": [str(item) for item in input_state_refs or []],
        "params": params,
        "depends_on": [str(item) for item in depends_on or []],
    }


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
