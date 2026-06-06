from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.base_agent import BaseAgent
from protocol.messages import (
    Capability,
    CapabilityItem,
    MemoryCommit,
    Plan,
    PlanStep,
    StepResult,
)
from runtime.llm import (
    ChatMessage,
    DeterministicLLMClient,
    LLMClient,
    extract_json_object,
    tagged_json_block,
)
from tasks.sample_tasks import SampleTask


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
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
        }
        messages = _planner_messages(planner_input, mode=str(getattr(ctx, "mode", "protocol")))
        result = await self.llm_client.complete(messages, purpose="planner")
        ctx.record_llm_result(result)
        return _plan_from_llm_output(task, result.text)


@dataclass
class RetrieverAgent(BaseAgent):
    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        hits = []
        if step.params.get("allow_memory_reuse"):
            hits = ctx.search_memory(
                task_theme=ctx.task_theme,
                query_text=str(step.params["query"]),
                top_k=1,
                tags=list(step.params.get("tags", [])),
                tags_any=list(step.params.get("tags", [])),
                min_confidence=0.6,
                encoder_id=ctx.memory_store.embedder.encoder_id,
            )

        reused = bool(hits)
        evidence_text = str(step.params["evidence_text"])
        if reused:
            evidence_text = (
                f"REUSED_MEMORY {hits[0].memory_id}: {hits[0].summary}\n"
                f"FRESH_EVIDENCE {evidence_text}"
            )

        evidence_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-evidence",
            kind="DENSE_EVIDENCE",
            text=evidence_text,
            metadata={
                "query": step.params["query"],
                "reused_memory": reused,
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
            output_state_refs=[evidence_ref, embedding_ref],
            payload={
                "query": step.params["query"],
                "memory_hits": [hit.memory_id for hit in hits],
                "reused_memory": reused,
            },
        )


@dataclass
class ExecutorAgent(BaseAgent):
    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        retrieve_result = ctx.results[step.depends_on[0]]
        evidence_ref = next(
            ref for ref in retrieve_result.output_state_refs if ref.kind == "DENSE_EVIDENCE"
        )
        evidence_text = ctx.get_text_state(evidence_ref)
        reusable_steps = ["retrieve", "execute"]
        if "DB pool saturation" in evidence_text or "database pool contention" in evidence_text:
            actions = [
                "rollback release-17",
                "create orders_created_at index",
                "check database pool sizing",
            ]
        elif "cache invalidation" in evidence_text or "stale inventory" in evidence_text:
            actions = [
                "force inventory aggregate invalidation",
                "rerun post-sync invalidation hook",
                "verify cache freshness after batch sync",
            ]
        else:
            actions = ["collect more evidence"]
            reusable_steps = ["retrieve"]
        artifact_text = "\n".join(actions)
        artifact_ref = ctx.put_text_state(
            state_id=f"{ctx.task_id}-{step.step_id}-artifact",
            kind="TOOL_ARTIFACT",
            text=artifact_text,
            metadata={"source_evidence": evidence_ref.state_id},
        )
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[artifact_ref],
            payload={"actions": actions, "reusable_steps": reusable_steps},
        )


@dataclass
class SummarizerAgent(BaseAgent):
    llm_client: LLMClient

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        retrieve_result = ctx.results["retrieve"]
        execute_result = ctx.results["execute"]
        evidence_ref = next(
            ref for ref in retrieve_result.output_state_refs if ref.kind == "DENSE_EVIDENCE"
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
                "trace_id": ctx.trace_id,
                "llm_model": result.model,
            },
            evidence_state_refs=[
                evidence_ref,
                *([embedding_ref] if embedding_ref is not None else []),
                artifact_ref,
                summary_ref,
            ],
        )
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[summary_ref],
            payload={"memory_commit": commit, "summary": summary_text, "llm_model": result.model},
        )


def build_sample_agents(llm_client: LLMClient | None = None) -> dict[str, BaseAgent]:
    active_llm = llm_client or DeterministicLLMClient()
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
                produced_state_kinds=["DENSE_EVIDENCE", "EMBEDDING"],
            ),
        ),
        "executor": ExecutorAgent(
            agent_id="executor",
            capability=_build_capability(
                "executor",
                action="EXECUTE_PLAYBOOK",
                accepted_state_kinds=["DENSE_EVIDENCE"],
                produced_state_kinds=["TOOL_ARTIFACT"],
            ),
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


def _plan_from_llm_output(task: SampleTask, output_text: str) -> Plan:
    payload = extract_json_object(output_text)
    steps = payload.get("steps")
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
                "evidence_text": task.evidence_text,
                "tags": list(task.tags),
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
            },
            "depends_on": ["retrieve", "execute"],
        },
    ]


def _planner_messages(payload: dict[str, Any], *, mode: str) -> list[ChatMessage]:
    system_prompt = (
        "You are the StateBus Planner. Output strict JSON only. "
        "Return an object with a single key named steps. "
        "Use exactly three steps with these fixed contracts and exact field names: "
        "step_id, owner_agent, action, input_state_refs, params, depends_on. "
        "Step 1 must be retrieve -> owner_agent retriever action RETRIEVE_EVIDENCE. "
        "Step 2 must be execute -> owner_agent executor action EXECUTE_PLAYBOOK. "
        "Step 3 must be summarize -> owner_agent summarizer action SUMMARIZE_AND_COMMIT. "
        "retrieve.params must include query, evidence_text, tags, and allow_memory_reuse=true. "
        "execute.params must be {}. summarize.params must include summary_hint and tags. "
        "Do not wrap each step inside a retrieve/execute/summarize key. "
        "Do not add prose or markdown."
    )
    if mode == "text":
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
            f"Tags: {', '.join(payload['tags'])}\n\n"
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
        user_prompt = tagged_json_block("statebus-planner-input", payload)
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]


def _summarizer_messages(payload: dict[str, Any], *, mode: str) -> list[ChatMessage]:
    system_prompt = (
        "You are the StateBus Summarizer. Output strict JSON only. "
        "Return an object with summary, confidence, tags, and reusable_steps. "
        "Base the summary on the evidence and playbook. Keep it concise but concrete. "
        "Do not add markdown fences or extra prose."
    )
    if mode == "text":
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
        user_prompt = tagged_json_block("statebus-summary-input", payload)
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
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
