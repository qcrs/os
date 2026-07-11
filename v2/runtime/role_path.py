from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
import time
from typing import Any

from runtime.llm import (
    ChatMessage,
    LLMClient,
    LLMResult,
    LLMUsage,
    build_llm_client,
    extract_json_object,
    tagged_json_block,
)
from v2.contracts import CanonicalTaskSpec
from v2.route_tool_catalog import RouteToolSurfaceCandidate, build_route_tool_surface
from v2.retrieval.models import RetrievalCandidatePool
from v2.utils import sha256_digest


PREFIX_LAYOUT_PLAN_SCHEMA_VERSION = "statebus.prefix_layout_plan.v1"
PREFIX_LAYOUT_CLAIM_BOUNDARY = (
    "prompt_prefix_layout_control_plane_only_no_kv_tensor_export"
)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _run_sync(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _merge_llm_results(results: list[LLMResult]) -> LLMResult:
    if not results:
        return LLMResult(text="", model="", usage=LLMUsage())
    if len(results) == 1:
        return results[0]
    last = results[-1]
    return LLMResult(
        text=last.text,
        model=last.model,
        usage=LLMUsage(
            prompt_tokens=sum(result.usage.prompt_tokens for result in results),
            completion_tokens=sum(result.usage.completion_tokens for result in results),
            total_tokens=sum(result.usage.total_tokens for result in results),
        ),
    )


@dataclass(frozen=True)
class RoleToolCandidate(RouteToolSurfaceCandidate):
    pass


class RoleSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedRoleSelection:
    route: str = ""
    tool_name: str = ""
    candidate_key: str = ""
    candidate_rank: int | None = None
    supporting_doc_ids: tuple[str, ...] = ()
    reason: str = ""
    action_contract: str = ""


def best_visible_candidate(
    visible_candidates: tuple[RoleToolCandidate, ...],
) -> RoleToolCandidate:
    if not visible_candidates:
        raise ValueError("visible_candidates must not be empty")
    ranked = sorted(
        visible_candidates,
        key=lambda candidate: (-candidate.score, candidate.helper_rank, candidate.route, candidate.tool_name),
    )
    return ranked[0]


def constrain_visible_candidates(
    visible_candidates: tuple[RoleToolCandidate, ...],
    *,
    candidate_keys: tuple[str, ...] = (),
    required_tools: tuple[str, ...] = (),
) -> tuple[RoleToolCandidate, ...]:
    constrained = visible_candidates
    if candidate_keys:
        key_set = {key.strip() for key in candidate_keys if key.strip()}
        filtered = tuple(candidate for candidate in constrained if candidate.candidate_key() in key_set)
        if filtered:
            constrained = filtered
    if required_tools:
        tool_set = {tool.strip() for tool in required_tools if tool.strip()}
        filtered = tuple(candidate for candidate in constrained if candidate.tool_name in tool_set)
        if filtered:
            constrained = filtered
    return constrained


@dataclass(frozen=True)
class PlannerRoleResult:
    workflow_payload: dict[str, Any]
    retrieval_objective: dict[str, Any]
    raw_text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_bytes: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RetrieverRoleDecision:
    route: str
    tool_name: str
    supporting_doc_ids: tuple[str, ...]
    reason: str
    candidate_rank: int
    raw_text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_bytes: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ExecutorRoleDecision:
    route: str
    tool_name: str
    action_contract: str
    reason: str
    raw_text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_bytes: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class SummarizerRoleDecision:
    summary_text: str
    reusable_steps: tuple[str, ...]
    confidence: float
    tags: tuple[str, ...]
    raw_text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_bytes: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class JsonRoleCompletion:
    payload: dict[str, Any]
    result: LLMResult
    prompt_bytes: int
    latency_ms: float
    attempt_count: int


@dataclass(frozen=True)
class PrefixLayoutPlan:
    role_label: str
    payload_tag: str
    handoff_mode: str
    prefix_alignment_mode: str
    shared_prefix_enabled: bool
    shared_prefix_hash: str = ""
    shared_prefix_bytes: int = 0
    role_suffix_hash: str = ""
    role_suffix_bytes: int = 0
    prompt_hash: str = ""
    prompt_bytes: int = 0
    removed_payload_evidence: bool = False
    removed_text_section_count: int = 0
    removed_evidence_block_count: int = 0
    suffix_payload_keys: tuple[str, ...] = ()
    claim_boundary: str = PREFIX_LAYOUT_CLAIM_BOUNDARY
    schema_version: str = PREFIX_LAYOUT_PLAN_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "role_label": self.role_label,
            "payload_tag": self.payload_tag,
            "handoff_mode": self.handoff_mode,
            "prefix_alignment_mode": self.prefix_alignment_mode,
            "shared_prefix_enabled": self.shared_prefix_enabled,
            "shared_prefix_hash": self.shared_prefix_hash,
            "shared_prefix_bytes": self.shared_prefix_bytes,
            "role_suffix_hash": self.role_suffix_hash,
            "role_suffix_bytes": self.role_suffix_bytes,
            "prompt_hash": self.prompt_hash,
            "prompt_bytes": self.prompt_bytes,
            "removed_payload_evidence": self.removed_payload_evidence,
            "removed_text_section_count": self.removed_text_section_count,
            "removed_evidence_block_count": self.removed_evidence_block_count,
            "suffix_payload_keys": list(self.suffix_payload_keys),
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CompiledRolePrompt:
    prompt: str
    layout_plan: PrefixLayoutPlan

    def canonical_payload(self) -> dict[str, object]:
        return {
            "prompt": self.prompt,
            "layout_plan": self.layout_plan.canonical_payload(),
            "schema_version": "statebus.compiled_role_prompt.v1",
        }


@dataclass(frozen=True)
class RolePromptSlice:
    role: str
    hydrated_text: str = ""
    hydrated_bytes: int = 0
    item_count: int = 0
    table_text: str = ""
    table_bytes: int = 0
    table_item_count: int = 0
    artifact_text: str = ""
    artifact_bytes: int = 0
    artifact_item_count: int = 0
    memory_text: str = ""
    memory_bytes: int = 0
    memory_item_count: int = 0

    def combined_text(self) -> str:
        chunks = [
            self.hydrated_text.strip(),
            self.table_text.strip(),
            self.artifact_text.strip(),
            self.memory_text.strip(),
        ]
        return "\n".join(chunk for chunk in chunks if chunk)

    def total_bytes(self) -> int:
        return self.hydrated_bytes + self.table_bytes + self.artifact_bytes + self.memory_bytes

    def total_item_count(self) -> int:
        return self.item_count + self.table_item_count + self.artifact_item_count + self.memory_item_count

    def payload(self, *, include_text: bool = True) -> dict[str, object]:
        payload = {
            "item_count": self.total_item_count(),
            "hydrated_bytes": self.total_bytes(),
            "text_context": {
                "item_count": self.item_count,
                "hydrated_bytes": self.hydrated_bytes,
            },
            "table_facts": {
                "item_count": self.table_item_count,
                "hydrated_bytes": self.table_bytes,
            },
            "artifact_context": {
                "item_count": self.artifact_item_count,
                "hydrated_bytes": self.artifact_bytes,
            },
            "memory_reuse": {
                "item_count": self.memory_item_count,
                "hydrated_bytes": self.memory_bytes,
            },
        }
        if include_text:
            payload["hydrated_text"] = self.combined_text()
            payload["text_context"]["hydrated_text"] = self.hydrated_text
            payload["table_facts"]["hydrated_text"] = self.table_text
            payload["artifact_context"]["hydrated_text"] = self.artifact_text
            payload["memory_reuse"]["hydrated_text"] = self.memory_text
        return payload


def _text_collaboration_prompt(
    *,
    role_label: str,
    instruction: str,
    sections: tuple[tuple[str, str], ...],
) -> str:
    rendered_sections = []
    for title, body in sections:
        normalized = body.strip()
        if not normalized:
            continue
        rendered_sections.append(f"{title}:\n{normalized}")
    body = "\n\n".join(rendered_sections)
    return f"You are the StateBus v2 {role_label} role.\n{instruction}\n\n{body}\n"


def _structured_collaboration_prompt(
    *,
    role_label: str,
    instruction: str,
    payload_tag: str,
    payload: dict[str, Any],
    evidence_blocks: tuple[str, ...] = (),
) -> str:
    prompt = (
        f"You are the StateBus v2 {role_label} role.\n"
        f"{instruction}\n\n"
        f"{tagged_json_block(payload_tag, payload)}"
    )
    for block in evidence_blocks:
        normalized = block.strip()
        if normalized:
            prompt += f"\n\n{normalized}"
    return prompt + "\n"


def _prefix_aligned_prompt(
    *,
    role_label: str,
    shared_prefix_text: str,
    role_suffix_prompt: str,
) -> str:
    normalized_prefix = shared_prefix_text.strip()
    if not normalized_prefix:
        return role_suffix_prompt
    return (
        "<statebus-shared-prefix-v1>\n"
        f"{normalized_prefix}\n"
        "</statebus-shared-prefix-v1>\n\n"
        f"[STATEBUS_ROLE_SUFFIX:{role_label}]\n"
        f"{role_suffix_prompt}"
    )


def _shared_prefix_enabled(prefix_alignment_mode: str, shared_prefix_text: str) -> bool:
    return (
        prefix_alignment_mode.strip().lower() == "shared_evidence_prefix"
        and bool(shared_prefix_text.strip())
    )


def _role_suffix_payload_without_shared_prefix(
    payload: dict[str, Any],
    *,
    shared_prefix_text: str,
) -> dict[str, Any]:
    normalized_prefix = shared_prefix_text.strip()
    suffix_payload = dict(payload)
    if str(suffix_payload.get("e", "")).strip() == normalized_prefix:
        suffix_payload.pop("e", None)
        suffix_payload["sp"] = {
            "contract": "statebus-shared-prefix-v1",
            "contains": "hydrated_evidence",
            "bytes": len(normalized_prefix.encode("utf-8")),
        }
    return suffix_payload


def _role_suffix_sections_without_shared_prefix(
    sections: tuple[tuple[str, str], ...],
    *,
    shared_prefix_text: str,
) -> tuple[tuple[str, str], ...]:
    normalized_prefix = shared_prefix_text.strip()
    return tuple(
        (title, body)
        for title, body in sections
        if not (body.strip() == normalized_prefix and title.lower() in {"evidence note", "hydrated evidence"})
    )


def _role_suffix_blocks_without_shared_prefix(
    evidence_blocks: tuple[str, ...],
    *,
    shared_prefix_text: str,
) -> tuple[str, ...]:
    normalized_prefix = shared_prefix_text.strip()
    return tuple(block for block in evidence_blocks if block.strip() != normalized_prefix)


def compile_prefix_layout(
    *,
    role_label: str,
    instruction: str,
    payload_tag: str,
    payload: dict[str, Any],
    text_sections: tuple[tuple[str, str], ...],
    handoff_mode: str,
    prefix_alignment_mode: str,
    evidence_blocks: tuple[str, ...] = (),
    shared_prefix_text: str = "",
) -> CompiledRolePrompt:
    normalized_prefix = shared_prefix_text.strip()
    use_shared_prefix = _shared_prefix_enabled(prefix_alignment_mode, shared_prefix_text)
    suffix_payload = dict(payload)
    suffix_sections = text_sections
    suffix_blocks = evidence_blocks
    if use_shared_prefix:
        suffix_payload = _role_suffix_payload_without_shared_prefix(
            suffix_payload,
            shared_prefix_text=shared_prefix_text,
        )
        suffix_sections = _role_suffix_sections_without_shared_prefix(
            suffix_sections,
            shared_prefix_text=shared_prefix_text,
        )
        suffix_blocks = _role_suffix_blocks_without_shared_prefix(
            suffix_blocks,
            shared_prefix_text=shared_prefix_text,
        )
    if handoff_mode == "text_collaboration":
        role_suffix_prompt = _text_collaboration_prompt(
            role_label=role_label,
            instruction=instruction,
            sections=suffix_sections,
        )
    else:
        role_suffix_prompt = _structured_collaboration_prompt(
            role_label=role_label,
            instruction=instruction,
            payload_tag=payload_tag,
            payload=suffix_payload,
            evidence_blocks=suffix_blocks,
        )
    prompt = (
        _prefix_aligned_prompt(
            role_label=role_label,
            shared_prefix_text=shared_prefix_text,
            role_suffix_prompt=role_suffix_prompt,
        )
        if use_shared_prefix
        else role_suffix_prompt
    )
    removed_payload_evidence = bool(
        use_shared_prefix
        and "e" in payload
        and "e" not in suffix_payload
    )
    layout_plan = PrefixLayoutPlan(
        role_label=role_label,
        payload_tag=payload_tag,
        handoff_mode=handoff_mode,
        prefix_alignment_mode=prefix_alignment_mode,
        shared_prefix_enabled=use_shared_prefix,
        shared_prefix_hash=sha256_digest(normalized_prefix) if use_shared_prefix else "",
        shared_prefix_bytes=len(normalized_prefix.encode("utf-8")) if use_shared_prefix else 0,
        role_suffix_hash=sha256_digest(role_suffix_prompt),
        role_suffix_bytes=len(role_suffix_prompt.encode("utf-8")),
        prompt_hash=sha256_digest(prompt),
        prompt_bytes=len(prompt.encode("utf-8")),
        removed_payload_evidence=removed_payload_evidence,
        removed_text_section_count=max(len(text_sections) - len(suffix_sections), 0),
        removed_evidence_block_count=max(len(evidence_blocks) - len(suffix_blocks), 0),
        suffix_payload_keys=tuple(sorted(str(key) for key in suffix_payload)),
    )
    return CompiledRolePrompt(prompt=prompt, layout_plan=layout_plan)


def _candidate_surface_payload(
    visible_candidates: tuple["RoleToolCandidate", ...],
    *,
    include_helper_fields: bool,
) -> tuple[list[dict[str, Any]], str]:
    payload = [
        {
            "route": candidate.route,
            "tool_name": candidate.tool_name,
            "support_doc_count": candidate.support_doc_count,
            "supporting_doc_ids": list(candidate.supporting_doc_ids),
            "support_terms": list(candidate.support_terms),
            **(
                {
                    "helper_rank": candidate.helper_rank,
                    "score": candidate.score,
                    "matched_issue_ids": list(candidate.matched_issue_ids),
                    "rationale": candidate.rationale,
                }
                if include_helper_fields
                else {}
            ),
        }
        for candidate in visible_candidates
    ]
    text_notes = "; ".join(
        candidate.note_payload(include_helper_fields=include_helper_fields) for candidate in visible_candidates
    )
    return payload, text_notes


def _compact_candidate_surface_payload(
    visible_candidates: tuple["RoleToolCandidate", ...],
    *,
    include_helper_fields: bool,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for candidate in visible_candidates:
        item: dict[str, Any] = {
            "k": candidate.candidate_key(),
            "r": candidate.route,
            "t": candidate.tool_name,
        }
        if candidate.supporting_doc_ids:
            item["d"] = list(candidate.supporting_doc_ids)
        elif candidate.support_doc_count:
            item["n"] = candidate.support_doc_count
        if include_helper_fields and candidate.support_terms:
            item["s"] = list(candidate.support_terms)
        if include_helper_fields:
            item["h"] = candidate.helper_rank
            item["sc"] = candidate.score
            if candidate.matched_issue_ids:
                item["m"] = list(candidate.matched_issue_ids)
            if candidate.rationale:
                item["x"] = candidate.rationale
        payload.append(item)
    return payload


def _candidate_identity_line(visible_candidates: tuple["RoleToolCandidate", ...]) -> str:
    return "; ".join(candidate.candidate_key() for candidate in visible_candidates)


def _preferred_candidate_payload(
    visible_candidates: tuple["RoleToolCandidate", ...],
    *,
    route_hints: tuple[str, ...] = (),
) -> dict[str, Any]:
    preferred = best_visible_candidate(visible_candidates)
    payload: dict[str, Any] = {
        "k": preferred.candidate_key(),
        "r": preferred.route,
        "t": preferred.tool_name,
        "why": "top_ranked_visible_candidate",
    }
    normalized_hints = tuple(
        dict.fromkeys(
            hint.strip()
            for hint in route_hints
            if hint.strip() and hint.strip() not in {preferred.route, preferred.candidate_key()}
        )
    )
    if normalized_hints:
        payload["rh"] = list(normalized_hints)
    return payload


def _selection_retry_prompt(
    *,
    prompt: str,
    error: RoleSelectionError,
    visible_candidates: tuple["RoleToolCandidate", ...],
) -> str:
    visible_keys = ", ".join(candidate.candidate_key() for candidate in visible_candidates)
    return (
        f"{prompt}\n\n"
        "Selection retry instruction: the prior JSON selected an invisible or inconsistent "
        f"route/tool candidate ({error}). Return exactly one visible candidate from this list "
        f"and copy candidate_key, route, and tool_name exactly: {visible_keys}."
    )


def _tagged_text_block(tag: str, text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    return f"<{tag}>\n{normalized}\n</{tag}>"


def _compact_text_value(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    return "\n".join(line.strip() for line in normalized.splitlines() if line.strip())


def _first_non_empty_string(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_valid_int(*values: object) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _coerce_confidence(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip().lower()
    label_scores = {
        "certain": 1.0,
        "very_high": 0.95,
        "very high": 0.95,
        "high": 0.9,
        "medium_high": 0.75,
        "medium high": 0.75,
        "moderate": 0.6,
        "medium": 0.5,
        "low": 0.25,
        "very_low": 0.1,
        "very low": 0.1,
        "none": 0.0,
        "unknown": 0.0,
    }
    return label_scores.get(text, 0.0)


def _coerce_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def _selection_payload_candidates(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    candidates: list[dict[str, Any]] = [payload]
    for key in ("candidate", "selected_candidate", "choice"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return tuple(candidates)


def _parse_role_selection(payload: dict[str, Any]) -> ParsedRoleSelection:
    payload_candidates = _selection_payload_candidates(payload)
    route = _first_non_empty_string(
        *(candidate.get("route") for candidate in payload_candidates),
        *(candidate.get("r") for candidate in payload_candidates),
        *(candidate.get("selected_route") for candidate in payload_candidates),
        *(candidate.get("validated_route") for candidate in payload_candidates),
    )
    tool_name = _first_non_empty_string(
        *(candidate.get("tool_name") for candidate in payload_candidates),
        *(candidate.get("tool") for candidate in payload_candidates),
        *(candidate.get("t") for candidate in payload_candidates),
        *(candidate.get("selected_tool_name") for candidate in payload_candidates),
        *(candidate.get("validated_tool_name") for candidate in payload_candidates),
    )
    candidate_key_from_route_or_tool = _first_non_empty_string(
        *(
            candidate.get("route")
            for candidate in payload_candidates
            if "::" in str(candidate.get("route", "")).strip()
        ),
        *(
            candidate.get("r")
            for candidate in payload_candidates
            if "::" in str(candidate.get("r", "")).strip()
        ),
        *(
            candidate.get("tool_name")
            for candidate in payload_candidates
            if "::" in str(candidate.get("tool_name", "")).strip()
        ),
        *(
            candidate.get("tool")
            for candidate in payload_candidates
            if "::" in str(candidate.get("tool", "")).strip()
        ),
        *(
            candidate.get("t")
            for candidate in payload_candidates
            if "::" in str(candidate.get("t", "")).strip()
        ),
    )
    candidate_key = _first_non_empty_string(
        payload.get("candidate_key"),
        payload.get("selected_candidate_key"),
        payload.get("k"),
        payload.get("candidate") if isinstance(payload.get("candidate"), str) else None,
        payload.get("selected_candidate") if isinstance(payload.get("selected_candidate"), str) else None,
        payload.get("choice_key"),
        payload.get("choice") if isinstance(payload.get("choice"), str) else None,
        *(candidate.get("candidate_key") for candidate in payload_candidates),
        *(candidate.get("selected_candidate_key") for candidate in payload_candidates),
        *(candidate.get("k") for candidate in payload_candidates),
        *(candidate.get("key") for candidate in payload_candidates),
        candidate_key_from_route_or_tool,
    )
    if candidate_key and ("::" in candidate_key) and (not route or not tool_name):
        candidate_route, _, candidate_tool = candidate_key.partition("::")
        route = route or candidate_route.strip()
        tool_name = tool_name or candidate_tool.strip()
    elif candidate_key and ("::" in candidate_key):
        candidate_route, _, candidate_tool = candidate_key.partition("::")
        candidate_route = candidate_route.strip()
        candidate_tool = candidate_tool.strip()
        if route == candidate_key or route == candidate_tool:
            route = candidate_route or route
        if tool_name == candidate_key or tool_name == candidate_route:
            tool_name = candidate_tool or tool_name
    candidate_rank = _first_valid_int(
        payload.get("candidate_rank"),
        payload.get("selected_candidate_rank"),
        payload.get("helper_rank"),
        payload.get("rank"),
        payload.get("h"),
        *(candidate.get("candidate_rank") for candidate in payload_candidates),
        *(candidate.get("selected_candidate_rank") for candidate in payload_candidates),
        *(candidate.get("helper_rank") for candidate in payload_candidates),
        *(candidate.get("rank") for candidate in payload_candidates),
        *(candidate.get("h") for candidate in payload_candidates),
    )
    supporting_doc_ids = _coerce_string_tuple(
        payload.get("supporting_doc_ids")
        if payload.get("supporting_doc_ids") is not None
        else payload.get("d")
    )
    if not supporting_doc_ids:
        for candidate in payload_candidates:
            supporting_doc_ids = _coerce_string_tuple(
                candidate.get("supporting_doc_ids")
                if candidate.get("supporting_doc_ids") is not None
                else candidate.get("d")
            )
            if supporting_doc_ids:
                break
    reason = _first_non_empty_string(
        payload.get("reason"),
        payload.get("selection_reason"),
        payload.get("rationale"),
        payload.get("why"),
        *(candidate.get("reason") for candidate in payload_candidates),
        *(candidate.get("selection_reason") for candidate in payload_candidates),
        *(candidate.get("rationale") for candidate in payload_candidates),
    )
    action_contract = _first_non_empty_string(
        payload.get("action_contract"),
        payload.get("validated_action_contract"),
        payload.get("a"),
        *(candidate.get("action_contract") for candidate in payload_candidates),
        *(candidate.get("validated_action_contract") for candidate in payload_candidates),
        *(candidate.get("a") for candidate in payload_candidates),
    )
    return ParsedRoleSelection(
        route=route,
        tool_name=tool_name,
        candidate_key=candidate_key,
        candidate_rank=candidate_rank,
        supporting_doc_ids=supporting_doc_ids,
        reason=reason,
        action_contract=action_contract,
    )


def _canonicalize_planner_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def _canonical_step(step: dict[str, Any]) -> dict[str, Any]:
        semantic_role = str(step.get("semantic_role", step.get("step_id", ""))).strip()
        params = dict(step.get("params", {})) if isinstance(step.get("params"), dict) else {}
        if semantic_role == "retrieve":
            params = {
                "query": str(params.get("query", "")),
                "tags": [str(item) for item in params.get("tags", []) if str(item).strip()],
                "allow_memory_reuse": bool(params.get("allow_memory_reuse", True)),
            }
        elif semantic_role == "summarize":
            params = {
                "summary_hint": str(params.get("summary_hint", "")),
                "tags": [str(item) for item in params.get("tags", []) if str(item).strip()],
            }
        else:
            params = {}
        return {
            "step_id": str(step.get("step_id", semantic_role)).strip(),
            "semantic_role": semantic_role,
            "owner_agent": str(step.get("owner_agent", "")).strip(),
            "action": str(step.get("action", "")).strip(),
            "input_state_refs": [],
            "params": params,
            "depends_on": [str(item) for item in step.get("depends_on", []) if str(item).strip()],
        }

    if "steps" in payload:
        steps = payload.get("steps")
        if isinstance(steps, list):
            return {"steps": [_canonical_step(step) for step in steps if isinstance(step, dict)]}
        return {"steps": []}
    retrieve = payload.get("r")
    execute = payload.get("x")
    summarize = payload.get("s")
    if not isinstance(retrieve, dict) or not isinstance(execute, dict) or not isinstance(summarize, dict):
        return payload
    steps: list[dict[str, Any]] = [
        _canonical_step(
            {
            "step_id": str(retrieve.get("sid", "retrieve")),
            "semantic_role": str(retrieve.get("role", "retrieve")),
            "owner_agent": str(retrieve.get("owner", "retriever")),
            "action": str(retrieve.get("action", "RETRIEVE_EVIDENCE")),
            "input_state_refs": [],
            "params": {
                "query": str(retrieve.get("q", "")),
                "tags": [str(item) for item in retrieve.get("t", []) if str(item).strip()],
                "allow_memory_reuse": True,
            },
            "depends_on": [str(item) for item in retrieve.get("dep", []) if str(item).strip()],
            }
        )
    ]
    validate_sid = str(execute.get("vsid", "")).strip()
    if validate_sid:
        steps.append(
            _canonical_step(
                {
                "step_id": validate_sid,
                "semantic_role": str(execute.get("vrole", "validate")),
                "owner_agent": str(execute.get("vowner", "executor")),
                "action": str(execute.get("vaction", "VALIDATE_ROUTE")),
                "input_state_refs": [],
                "params": {},
                "depends_on": [str(item) for item in execute.get("vdep", []) if str(item).strip()],
                }
            )
        )
    steps.append(
        _canonical_step(
            {
            "step_id": str(execute.get("sid", "execute")),
            "semantic_role": str(execute.get("role", "execute")),
            "owner_agent": str(execute.get("owner", "executor")),
            "action": str(execute.get("action", "EXECUTE_PLAYBOOK")),
            "input_state_refs": [],
            "params": {},
            "depends_on": [str(item) for item in execute.get("dep", []) if str(item).strip()],
            }
        )
    )
    steps.append(
        _canonical_step(
            {
            "step_id": str(summarize.get("sid", "summarize")),
            "semantic_role": str(summarize.get("role", "summarize")),
            "owner_agent": str(summarize.get("owner", "summarizer")),
            "action": str(summarize.get("action", "SUMMARIZE_AND_COMMIT")),
            "input_state_refs": [],
            "params": {
                "summary_hint": str(summarize.get("h", "")),
                "tags": [str(item) for item in summarize.get("t", []) if str(item).strip()],
            },
            "depends_on": [str(item) for item in summarize.get("dep", []) if str(item).strip()],
            }
        )
    )
    return {"steps": steps}


@dataclass
class RolePathRunner:
    llm_client: LLMClient = field(default_factory=build_llm_client)
    handoff_mode: str = "structured_collaboration"
    json_response_max_attempts: int = 3
    prefix_alignment_mode: str = field(
        default_factory=lambda: os.getenv("STATEBUS_PREFIX_ALIGNMENT_MODE", "independent")
    )
    lean_completion_enabled: bool = field(default_factory=lambda: _env_flag("STATEBUS_LEAN_COMPLETION"))

    def _render_prompt(
        self,
        *,
        role_label: str,
        instruction: str,
        payload_tag: str,
        payload: dict[str, Any],
        text_sections: tuple[tuple[str, str], ...],
        evidence_blocks: tuple[str, ...] = (),
        shared_prefix_text: str = "",
    ) -> str:
        compiled = compile_prefix_layout(
            role_label=role_label,
            instruction=instruction,
            payload_tag=payload_tag,
            payload=payload,
            text_sections=text_sections,
            handoff_mode=self.handoff_mode,
            prefix_alignment_mode=self.prefix_alignment_mode,
            evidence_blocks=evidence_blocks,
            shared_prefix_text=shared_prefix_text,
        )
        return compiled.prompt

    def _planner_instruction(self) -> str:
        if self.lean_completion_enabled:
            return (
                "Return exactly one compact JSON object (json only). Prefer compact workflow keys r, x, and s; "
                "omit retrieval_objective, verbose step metadata, and empty fields."
            )
        return "Return a JSON object with stable retrieval_objective and steps."

    def _retriever_instruction(self) -> str:
        return (
            "Select exactly one visible route/tool candidate. Copy candidate_key, route, and tool_name "
            "exactly from a single visible tc item. Treat pc as the default tie-break when multiple tc "
            "items look plausible and the hydrated evidence does not clearly contradict pc or its route "
            "hints. Do not invent labels or use placeholders such as 'tool' or 'route'. Return a JSON "
            "object with keys candidate_key, route, tool_name, supporting_doc_ids, and reason."
        )

    def _executor_instruction(self) -> str:
        return (
            "Validate the chosen route/tool within the visible candidate set. Copy candidate_key, route, "
            "and tool_name exactly from a single visible tc item. Treat pc as the default tie-break when "
            "multiple tc items share the same tool and the hydrated evidence does not clearly contradict pc "
            "or its route hints. Do not invent labels or use placeholders such as 'tool' or 'route'. "
            "Return a JSON object with keys candidate_key, route, tool_name, action_contract, and reason."
        )

    def _summarizer_instruction(self) -> str:
        if self.lean_completion_enabled:
            return (
                "Return exactly one compact JSON object (json only) with key s for the summary text. "
                "Omit reusable_steps, confidence, and tags unless they materially change the answer."
            )
        return (
            "Return exactly one compact JSON object and no prose. Use keys summary, reusable_steps, "
            "confidence, and tags. Keep summary under 80 words. reusable_steps must contain at most 2 "
            "short generic step names, not detailed instructions."
        )

    def _complete_json_role(
        self,
        *,
        prompt: str,
        purpose: str,
    ) -> JsonRoleCompletion:
        attempts: list[LLMResult] = []
        prompt_bytes = 0
        current_prompt = prompt
        retry_note = (
            "\n\nJSON retry instruction: the prior response was empty or malformed. "
            "Return exactly one valid compact JSON object and no prose. Keep string values short."
        )
        max_attempts = max(1, self.json_response_max_attempts)
        start_ns = time.perf_counter_ns()
        last_error: ValueError | None = None
        for attempt_index in range(max_attempts):
            prompt_bytes += len(current_prompt.encode("utf-8"))
            result = _run_sync(
                self.llm_client.complete(
                    [ChatMessage(role="user", content=current_prompt)],
                    purpose=purpose,
                )
            )
            attempts.append(result)
            try:
                payload = extract_json_object(result.text)
            except ValueError as exc:
                last_error = exc
                if attempt_index + 1 >= max_attempts:
                    break
                current_prompt = f"{prompt}{retry_note}"
                continue
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            return JsonRoleCompletion(
                payload=payload,
                result=_merge_llm_results(attempts),
                prompt_bytes=prompt_bytes,
                latency_ms=latency_ms,
                attempt_count=len(attempts),
            )
        latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        last_text = attempts[-1].text if attempts else ""
        raise ValueError(
            f"{purpose} role returned invalid JSON after {len(attempts)} attempt(s): {last_text!r}"
        ) from last_error

    def build_retrieval_objective(
        self,
        *,
        spec: CanonicalTaskSpec,
        goal: str,
        query_text: str,
        tags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        arguments = spec.arguments or {}
        ticker = str(arguments.get("ticker", "")).strip()
        quarter = str(arguments.get("quarter", "")).strip()
        metric = str(arguments.get("metric", "")).strip()
        retrieval_query = " ".join(
            part
            for part in (
                query_text.strip(),
                ticker,
                quarter,
                metric,
                spec.intent_op,
            )
            if part
        ).strip()
        return {
            "query_text": retrieval_query,
            "goal": goal,
            "task_family": spec.task_family,
            "intent_op": spec.intent_op,
            "required_tools": list(spec.required_tools or tags),
            "required_outputs": list(spec.required_outputs),
        }

    @staticmethod
    def _normalize_candidate_selection(
        *,
        route: str,
        tool_name: str,
        candidate_key: str,
        candidate_rank: int | None,
        visible_candidates: tuple[RoleToolCandidate, ...],
        allow_assisted_correction: bool,
        route_hints: tuple[str, ...] = (),
    ) -> tuple[RoleToolCandidate, int]:
        if not visible_candidates:
            raise ValueError("visible_candidates must not be empty")
        route_normalized = route.strip()
        tool_normalized = tool_name.strip()
        candidate_key_normalized = candidate_key.strip()
        normalized_route_hints = tuple(dict.fromkeys(hint.strip() for hint in route_hints if hint.strip()))
        ranked = [best_visible_candidate(visible_candidates)]
        for candidate in visible_candidates:
            if candidate.route == route_normalized and candidate.tool_name == tool_normalized:
                return candidate, candidate.helper_rank
        if candidate_key_normalized:
            key_matches = [candidate for candidate in visible_candidates if candidate.candidate_key() == candidate_key_normalized]
            if len(key_matches) == 1:
                selected = key_matches[0]
                if (
                    not route_normalized
                    or route_normalized in {selected.route, selected.tool_name, selected.candidate_key()}
                ) and (
                    not tool_normalized
                    or tool_normalized in {selected.tool_name, selected.route, selected.candidate_key()}
                ):
                    return selected, selected.helper_rank
        if "::" in route_normalized:
            key_matches = [candidate for candidate in visible_candidates if candidate.candidate_key() == route_normalized]
            if len(key_matches) == 1 and (
                not tool_normalized
                or tool_normalized in {
                    key_matches[0].tool_name,
                    key_matches[0].route,
                    key_matches[0].candidate_key(),
                }
            ):
                return key_matches[0], key_matches[0].helper_rank
        if "::" in tool_normalized:
            key_matches = [candidate for candidate in visible_candidates if candidate.candidate_key() == tool_normalized]
            if len(key_matches) == 1 and (
                not route_normalized
                or route_normalized in {
                    key_matches[0].route,
                    key_matches[0].tool_name,
                    key_matches[0].candidate_key(),
                }
            ):
                return key_matches[0], key_matches[0].helper_rank
        if candidate_rank is not None:
            if 1 <= candidate_rank <= len(visible_candidates):
                selected = visible_candidates[candidate_rank - 1]
                return selected, selected.helper_rank
            helper_rank_matches = [candidate for candidate in visible_candidates if candidate.helper_rank == candidate_rank]
            if len(helper_rank_matches) == 1:
                return helper_rank_matches[0], helper_rank_matches[0].helper_rank
        route_matches = [candidate for candidate in visible_candidates if candidate.route == route_normalized]
        if len(route_matches) == 1 and tool_normalized == route_normalized:
            selected = route_matches[0]
            return selected, selected.helper_rank
        swapped_matches = [
            candidate
            for candidate in visible_candidates
            if candidate.route == tool_normalized and candidate.tool_name == route_normalized
        ]
        if len(swapped_matches) == 1:
            selected = swapped_matches[0]
            return selected, selected.helper_rank
        if route_normalized and route_normalized == tool_normalized and normalized_route_hints:
            hinted_matches = [
                candidate
                for candidate in visible_candidates
                if candidate.route in normalized_route_hints and candidate.tool_name == tool_normalized
            ]
            if len(hinted_matches) == 1:
                selected = hinted_matches[0]
                return selected, selected.helper_rank
        if not allow_assisted_correction:
            raise RoleSelectionError(
                f"strict_visible_candidate_mismatch:{route_normalized or '<empty>'}::{tool_normalized or '<empty>'}"
            )
        if len(route_matches) == 1:
            return route_matches[0], route_matches[0].helper_rank
        tool_matches = [candidate for candidate in visible_candidates if candidate.tool_name == tool_normalized]
        if len(tool_matches) == 1:
            return tool_matches[0], tool_matches[0].helper_rank
        return ranked[0], ranked[0].helper_rank

    def plan_workflow(
        self,
        *,
        task_id: str,
        task_group: str,
        task_theme: str,
        goal: str,
        query_text: str,
        summary_hint: str,
        visible_candidates: tuple[RoleToolCandidate, ...],
        prompt_slice: RolePromptSlice | None = None,
        strict_surface: bool = True,
        tags: tuple[str, ...] = (),
        required_roles: tuple[str, ...] = ("retrieve", "execute", "summarize"),
    ) -> PlannerRoleResult:
        prompt_slice = prompt_slice or RolePromptSlice(role="planner")
        instruction = self._planner_instruction()
        _, _candidate_notes = _candidate_surface_payload(
            visible_candidates,
            include_helper_fields=not strict_surface,
        )
        payload = {
            "g": goal,
            "q": query_text,
            "h": summary_hint,
            "t": list(tags),
            "rr": list(required_roles),
        }
        if task_theme.strip():
            payload["tf"] = task_theme
        evidence_text = _compact_text_value(prompt_slice.combined_text())
        if evidence_text:
            payload["e"] = evidence_text
        prompt = self._render_prompt(
            role_label="planner",
            instruction=instruction,
            payload_tag="sb-plan-v1",
            payload=payload,
            text_sections=(
                ("Task ID", task_id),
                ("Task group", task_group),
                ("Task Theme", task_theme),
                ("Goal", goal),
                ("Search query", query_text),
                ("Required semantic roles", ", ".join(required_roles)),
                ("Summary hint", summary_hint),
                ("Tags", ", ".join(tags)),
                ("Evidence note", evidence_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            prompt = (
                "You are the StateBus v2 planner role.\n"
                f"{instruction}\n\n"
                f"Task ID: {task_id}\n"
                f"Task group: {task_group}\n"
                f"Task theme: {task_theme}\n"
                f"Tags: {', '.join(tags)}\n\n"
                f"Goal:\n{goal}\n\n"
                f"Search query:\n{query_text}\n\n"
                f"Required semantic roles:\n{', '.join(required_roles)}\n\n"
                f"Summary hint:\n{summary_hint}\n\n"
                f"Evidence note:\n{prompt_slice.combined_text()}\n\n"
            )
        completion = self._complete_json_role(prompt=prompt, purpose="planner")
        result = completion.result
        payload = _canonicalize_planner_workflow_payload(completion.payload)
        retrieval_objective = payload.get("retrieval_objective", {})
        if not isinstance(retrieval_objective, dict):
            retrieval_objective = {}
        if "query_text" not in retrieval_objective:
            retrieval_objective["query_text"] = query_text
        if "required_tools" not in retrieval_objective:
            retrieval_objective["required_tools"] = list(tags)
        if "candidate_keys" not in retrieval_objective:
            retrieval_objective["candidate_keys"] = [candidate.candidate_key() for candidate in visible_candidates]
        return PlannerRoleResult(
            workflow_payload=payload,
            retrieval_objective=retrieval_objective,
            raw_text=result.text,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            prompt_bytes=completion.prompt_bytes,
            latency_ms=completion.latency_ms,
        )

    def choose_retrieval_candidate(
        self,
        *,
        query_text: str,
        retrieved_doc_ids: tuple[str, ...],
        visible_candidates: tuple[RoleToolCandidate, ...],
        prompt_slice: RolePromptSlice | None = None,
        strict_surface: bool = True,
        allow_assisted_correction: bool = True,
        route_hints: tuple[str, ...] = (),
    ) -> RetrieverRoleDecision:
        prompt_slice = prompt_slice or RolePromptSlice(role="retriever")
        instruction = self._retriever_instruction()
        candidate_payload, _candidate_notes = _candidate_surface_payload(
            visible_candidates,
            include_helper_fields=not strict_surface,
        )
        payload = {
            "q": query_text,
            "rd": list(retrieved_doc_ids),
            "tc": _compact_candidate_surface_payload(
                visible_candidates,
                include_helper_fields=not strict_surface,
            ),
        }
        if strict_surface and self.handoff_mode != "text_collaboration":
            payload["pc"] = _preferred_candidate_payload(
                visible_candidates,
                route_hints=route_hints,
            )
        evidence_text = _compact_text_value(prompt_slice.combined_text())
        if evidence_text:
            payload["e"] = evidence_text
        prompt = self._render_prompt(
            role_label="retriever",
            instruction=instruction,
            payload_tag="sb-retriever-v1",
            payload=payload,
            text_sections=(
                ("Query", query_text),
                ("Retrieved Doc IDs", ", ".join(retrieved_doc_ids)),
                ("Visible Candidates", "\n".join(_candidate_notes.split("; ")) if _candidate_notes else ""),
                ("Hydrated Evidence", evidence_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            prompt = (
                "You are the StateBus v2 retriever role.\n"
                f"{instruction}\n\n"
                f"Query: {query_text}\n"
                f"Retrieved docs: {','.join(retrieved_doc_ids)}\n"
                f"Visible candidates: {_candidate_identity_line(visible_candidates)}\n"
                f"Candidate notes: {_candidate_notes}\n\n"
                f"Evidence note:\n{prompt_slice.combined_text()}\n"
            )
        completions: list[JsonRoleCompletion] = []
        current_prompt = prompt
        max_attempts = max(1, self.json_response_max_attempts)
        last_error: RoleSelectionError | None = None
        for attempt_index in range(max_attempts):
            completion = self._complete_json_role(prompt=current_prompt, purpose="retriever")
            completions.append(completion)
            payload = completion.payload
            parsed_selection = _parse_role_selection(payload)
            try:
                selected_candidate, selected_rank = self._normalize_candidate_selection(
                    route=parsed_selection.route,
                    tool_name=parsed_selection.tool_name,
                    candidate_key=parsed_selection.candidate_key,
                    candidate_rank=parsed_selection.candidate_rank,
                    visible_candidates=visible_candidates,
                    allow_assisted_correction=allow_assisted_correction,
                    route_hints=route_hints,
                )
                break
            except RoleSelectionError as exc:
                last_error = exc
                if attempt_index + 1 >= max_attempts:
                    raise
                current_prompt = _selection_retry_prompt(
                    prompt=prompt,
                    error=exc,
                    visible_candidates=visible_candidates,
                )
        else:
            raise last_error or RoleSelectionError("selection_retry_exhausted")
        result = _merge_llm_results([completion.result for completion in completions])
        return RetrieverRoleDecision(
            route=selected_candidate.route,
            tool_name=selected_candidate.tool_name,
            supporting_doc_ids=parsed_selection.supporting_doc_ids or selected_candidate.supporting_doc_ids,
            reason=parsed_selection.reason,
            candidate_rank=selected_rank,
            raw_text=result.text,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            prompt_bytes=sum(completion.prompt_bytes for completion in completions),
            latency_ms=sum(completion.latency_ms for completion in completions),
        )

    def validate_execution_choice(
        self,
        *,
        route: str,
        tool_name: str,
        visible_candidates: tuple[RoleToolCandidate, ...],
        action_contract: str,
        prompt_slice: RolePromptSlice | None = None,
        strict_surface: bool = True,
        allow_assisted_correction: bool = True,
        route_hints: tuple[str, ...] = (),
    ) -> ExecutorRoleDecision:
        prompt_slice = prompt_slice or RolePromptSlice(role="executor")
        instruction = self._executor_instruction()
        candidate_payload, _candidate_notes = _candidate_surface_payload(
            visible_candidates,
            include_helper_fields=not strict_surface,
        )
        payload = {
            "r": route,
            "t": tool_name,
            "a": action_contract,
            "tc": _compact_candidate_surface_payload(
                visible_candidates,
                include_helper_fields=not strict_surface,
            ),
        }
        if strict_surface and self.handoff_mode != "text_collaboration":
            payload["pc"] = _preferred_candidate_payload(
                visible_candidates,
                route_hints=route_hints,
            )
        evidence_text = _compact_text_value(prompt_slice.combined_text())
        if evidence_text:
            payload["e"] = evidence_text
        prompt = self._render_prompt(
            role_label="executor",
            instruction=instruction,
            payload_tag="sb-executor-v1",
            payload=payload,
            text_sections=(
                ("Route", route),
                ("Tool", tool_name),
                ("Action Contract", action_contract),
                ("Visible Candidates", "\n".join(_candidate_notes.split("; ")) if _candidate_notes else ""),
                ("Hydrated Evidence", evidence_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            prompt = (
                "You are the StateBus v2 executor role.\n"
                f"{instruction}\n\n"
                f"Route: {route}\n"
                f"Tool: {tool_name}\n"
                f"Validated route: {route}\n"
                f"Validated tool: {tool_name}\n"
                f"Validated action contract: {action_contract}\n"
                f"Visible candidates: {_candidate_identity_line(visible_candidates)}\n"
                f"Candidate notes: {_candidate_notes}\n\n"
                f"Evidence note:\n{prompt_slice.combined_text()}\n"
            )
        completions: list[JsonRoleCompletion] = []
        current_prompt = prompt
        max_attempts = max(1, self.json_response_max_attempts)
        last_error: RoleSelectionError | None = None
        for attempt_index in range(max_attempts):
            completion = self._complete_json_role(prompt=current_prompt, purpose="executor")
            completions.append(completion)
            payload = completion.payload
            parsed_selection = _parse_role_selection(payload)
            try:
                selected_candidate, _ = self._normalize_candidate_selection(
                    route=parsed_selection.route or route,
                    tool_name=parsed_selection.tool_name or tool_name,
                    candidate_key=parsed_selection.candidate_key,
                    candidate_rank=parsed_selection.candidate_rank,
                    visible_candidates=visible_candidates,
                    allow_assisted_correction=allow_assisted_correction,
                    route_hints=route_hints,
                )
                break
            except RoleSelectionError as exc:
                last_error = exc
                if attempt_index + 1 >= max_attempts:
                    raise
                current_prompt = _selection_retry_prompt(
                    prompt=prompt,
                    error=exc,
                    visible_candidates=visible_candidates,
                )
        else:
            raise last_error or RoleSelectionError("selection_retry_exhausted")
        result = _merge_llm_results([completion.result for completion in completions])
        return ExecutorRoleDecision(
            route=selected_candidate.route,
            tool_name=selected_candidate.tool_name,
            action_contract=(
                parsed_selection.action_contract or action_contract
            ),
            reason=parsed_selection.reason,
            raw_text=result.text,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            prompt_bytes=sum(completion.prompt_bytes for completion in completions),
            latency_ms=sum(completion.latency_ms for completion in completions),
        )

    def summarize(
        self,
        *,
        task_id: str,
        task_theme: str,
        summary_hint: str,
        prompt_slice: RolePromptSlice | None = None,
        actions_text: str,
        tags: tuple[str, ...] = (),
        reusable_steps: tuple[str, ...] = ("retrieve", "execute"),
    ) -> SummarizerRoleDecision:
        prompt_slice = prompt_slice or RolePromptSlice(role="summarizer")
        instruction = self._summarizer_instruction()
        payload = {
            "tf": task_theme,
            "h": summary_hint,
            "t": list(tags),
            "r": list(reusable_steps),
        }
        evidence_text = _compact_text_value(prompt_slice.combined_text())
        compact_actions_text = _compact_text_value(actions_text)
        if evidence_text:
            payload["e"] = evidence_text
        if compact_actions_text:
            payload["a"] = compact_actions_text
        prompt = self._render_prompt(
            role_label="summarizer",
            instruction=instruction,
            payload_tag="sb-summary-v1",
            payload=payload,
            text_sections=(
                ("Task Theme", task_theme),
                ("Summary Hint", summary_hint),
                ("Tags", ", ".join(tags)),
                ("Reusable Steps", ", ".join(reusable_steps)),
                ("Hydrated Evidence", evidence_text),
                ("Action Handoff", compact_actions_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            prompt = (
                "You are the StateBus v2 summarizer role.\n"
                f"{instruction}\n\n"
                f"Task ID: {task_id}\n"
                f"Task theme: {task_theme}\n"
                f"Tags: {', '.join(tags)}\n"
                f"Reusable steps: {', '.join(reusable_steps)}\n\n"
                f"Summary hint:\n{summary_hint}\n\n"
                f"Evidence note:\n{prompt_slice.combined_text()}\n\n"
                f"Playbook actions:\n{actions_text}\n"
            )
        completion = self._complete_json_role(prompt=prompt, purpose="summarizer")
        result = completion.result
        payload = completion.payload
        summary_text = str(payload.get("summary", payload.get("s", ""))).strip()
        reusable = _coerce_string_tuple(payload.get("reusable_steps", payload.get("r", [])))
        tags_payload = _coerce_string_tuple(payload.get("tags", payload.get("t", [])))
        confidence_raw = payload.get("confidence", payload.get("c"))
        confidence = _coerce_confidence(confidence_raw) if confidence_raw not in (None, "") else 0.0
        return SummarizerRoleDecision(
            summary_text=summary_text,
            reusable_steps=reusable or tuple(str(item) for item in reusable_steps if str(item).strip()),
            confidence=confidence,
            tags=tags_payload or tuple(str(item) for item in tags if str(item).strip()),
            raw_text=result.text,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            prompt_bytes=completion.prompt_bytes,
            latency_ms=completion.latency_ms,
        )


def financial_tool_candidates(
    spec: CanonicalTaskSpec,
    candidate_pool: RetrievalCandidatePool | None = None,
) -> tuple[RoleToolCandidate, ...]:
    query_text = str(spec.arguments.get("request_text", ""))
    surface = build_route_tool_surface(
        spec,
        query_text=query_text,
        candidate_pool=candidate_pool,
    )
    return tuple(RoleToolCandidate(**candidate.__dict__) for candidate in surface)
