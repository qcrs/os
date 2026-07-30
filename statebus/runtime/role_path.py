from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import os
import time
from typing import Any

from statebus.integrations.llm import (
    ChatMessage,
    LLMClient,
    LLMResult,
    LLMUsage,
    build_llm_client,
    extract_json_object,
    tagged_json_block,
)
from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CandidateSurfaceV2,
    CanonicalTaskSpec,
    Claim,
    ClaimSet,
    ClaimSetStatus,
    EvidenceRequest,
    PlanProposal,
    PlanStepProposal,
    TransformProgram,
    TransformStep,
    LogitProducerReceipt,
)
from statebus.route_tool_catalog import RouteToolSurfaceCandidate, build_route_tool_surface
from statebus.retrieval.models import RetrievalCandidatePool
from statebus.runtime.logit_state import (
    ExactChoiceLogitResult,
    extract_exact_choice_logit_state,
)
from statebus.runtime.semantic_plan import planner_semantic_plan_response_schema
from statebus.utils import sha256_digest


PREFIX_LAYOUT_PLAN_SCHEMA_VERSION = "statebus.prefix_layout_plan.v1"
RENDERED_ROLE_REQUEST_SCHEMA_VERSION = "statebus.rendered_role_request.v1"
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
        top_logprobs=last.top_logprobs,
    )


def _normalize_logit_gate_mode(value: str) -> str:
    normalized = str(value).strip().lower() or "off"
    if normalized not in {"off", "telemetry", "retry_once"}:
        raise ValueError("STATEBUS_LOGIT_GATE_MODE must be off, telemetry, or retry_once")
    return normalized


def _coerce_optional_string_tuple(value: object) -> tuple[str, ...]:
    values = _coerce_string_tuple(value)
    null_markers = {"", "[]", "none", "null", "n/a", "not_applicable"}
    return tuple(item for item in values if item.strip().lower() not in null_markers)


def _string_schema(values: tuple[str, ...]) -> dict[str, Any]:
    # vLLM 0.7.3 routes any schema containing enum to outlines. Keep the
    # generation grammar structural and enforce these values in policy code.
    del values
    return {"type": "string"}


def _string_array_schema(
    values: tuple[str, ...] = (),
    *,
    min_items: int = 0,
    max_items: int = 16,
) -> dict[str, Any]:
    # vLLM 0.7.3 also routes minItems/maxItems to outlines. The caller's
    # contract validator remains authoritative for cardinality and budgets.
    del min_items, max_items
    return {"type": "array", "items": _string_schema(values)}


def _adaptive_plan_response_schema(
    *,
    capability_surface: tuple[dict[str, object], ...],
    allowed_outputs: tuple[str, ...],
    allowed_memory_policies: tuple[str, ...],
    max_steps: int,
    role_slot_layout: bool = False,
) -> dict[str, Any]:
    capability_ids = tuple(str(item.get("id", "")) for item in capability_surface)
    roles = tuple(str(item.get("role", "")) for item in capability_surface)
    output_contracts = tuple(
        dict.fromkeys(
            (
                *allowed_outputs,
                *(str(item.get("output_contract", "")) for item in capability_surface),
            )
        )
    )
    ref_kinds = tuple(
        dict.fromkeys(
            str(kind)
            for item in capability_surface
            for key in ("accepts", "produces")
            for kind in (item.get(key, ()) if isinstance(item.get(key, ()), (list, tuple)) else ())
        )
    )
    completion_criteria = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "min_locator_count": {"type": "integer"},
            "min_rows": {"type": "integer"},
            "required_evidence_types": _string_array_schema(max_items=8),
            "required_fields": _string_array_schema(max_items=16),
            "max_conflicts": {"type": "integer"},
        },
    }
    step_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "step_id": {"type": "string"},
            "role": _string_schema(roles),
            "capability_id": _string_schema(capability_ids),
            "goal": {"type": "string"},
            "depends_on": _string_array_schema(max_items=max_steps),
            "input_ref_ids": _string_array_schema(max_items=max_steps),
            "input_ref_kinds": _string_array_schema(ref_kinds, max_items=max_steps),
            "required_input_fields": _string_array_schema(max_items=64),
            "output_contract_version": _string_schema(output_contracts),
            "completion_criteria": completion_criteria,
        },
        "required": [
            "step_id",
            "role",
            "capability_id",
            "goal",
            "depends_on",
            "input_ref_ids",
            "input_ref_kinds",
            "output_contract_version",
            "completion_criteria",
        ],
    }
    plan_properties: dict[str, Any]
    plan_required: list[str]
    if role_slot_layout:
        plan_properties = {
            "retriever_step": step_schema,
            "primary_executor_step": step_schema,
            "additional_executor_steps": {"type": "array", "items": step_schema},
            "summarizer_step": step_schema,
        }
        plan_required = [
            "retriever_step",
            "primary_executor_step",
            "summarizer_step",
        ]
    else:
        plan_properties = {"steps": {"type": "array", "items": step_schema}}
        plan_required = ["steps"]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposal_id": {"type": "string"},
            **plan_properties,
            "final_output_contract_version": _string_schema(allowed_outputs),
            "requested_memory_policy": _string_schema(allowed_memory_policies),
            "planner_notes": {"type": "string"},
        },
        "required": [
            "proposal_id",
            *plan_required,
            "final_output_contract_version",
            "requested_memory_policy",
            "planner_notes",
        ],
    }


def _evidence_request_response_schema(
    *,
    corpus_scope_ids: tuple[str, ...],
    evidence_types: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "queries": _string_array_schema(min_items=1, max_items=3),
            "evidence_types": _string_array_schema(evidence_types, min_items=1, max_items=8),
            "corpus_scope_ids": _string_array_schema(corpus_scope_ids, min_items=1, max_items=8),
            "max_candidates": {"type": "integer"},
        },
        "required": [
            "queries",
            "evidence_types",
            "corpus_scope_ids",
            "max_candidates",
        ],
    }


def _operation_argument_contract(op: str) -> dict[str, object]:
    contracts: dict[str, dict[str, object]] = {
        "select": {"required": ["columns"], "fields": {"columns": "authorized column[]"}},
        "rename": {
            "required": ["source", "target"],
            "fields": {
                "source": "authorized existing column",
                "target": "new output column that does not already exist",
            },
        },
        "project_claim_fields": {"required": ["columns"], "fields": {"columns": "authorized column[]"}},
        "sort": {"required": ["columns"], "fields": {"columns": "authorized column[]"}},
        "group_by": {"required": ["columns"], "fields": {"columns": "authorized column[]"}},
        "limit": {"required": ["count"], "fields": {"count": "integer 0..10000"}},
        "filter_eq": {"required": ["column", "value"], "fields": {"column": "authorized column", "value": "scalar"}},
        "filter_contains": {"required": ["column", "value"], "fields": {"column": "authorized column", "value": "string"}},
        "filter_in": {"required": ["column", "values"], "fields": {"column": "authorized column", "values": "scalar[]"}},
        "filter_range": {"required": ["column"], "fields": {"column": "authorized column", "min": "number|null", "max": "number|null"}},
        "aggregate": {"required": ["column", "function", "output"], "fields": {"column": "authorized column", "function": "count|sum|mean|min|max", "output": "new column"}},
        "aggregate_grouped": {
            "required": ["group_field", "value_field"],
            "fields": {
                "group_field": "authorized group column",
                "value_field": "authorized numeric column",
                "group_output": "optional output group field",
                "sum_output": "optional output sum field",
                "mean_output": "optional output mean field",
                "min_output": "optional output minimum field",
                "max_output": "optional output maximum field",
                "count_output": "optional output count field",
            },
        },
        "derive_safe": {"required": ["numerator", "denominator", "output", "kind"], "fields": {"numerator": "authorized column", "denominator": "authorized column", "output": "new column", "kind": "difference|ratio|pct_change"}},
        "compare_periods": {
            "required": ["period_field", "value_field"],
            "fields": {
                "period_field": "authorized ordered period column",
                "value_field": "authorized numeric column",
                "carry_fields": "optional authorized column[]; each must have one invariant value across compared rows",
                "baseline_period_output": "optional output field",
                "comparison_period_output": "optional output field",
                "baseline_value_output": "optional output field",
                "comparison_value_output": "optional output field",
                "difference_output": "optional output field",
                "ratio_output": "optional output field",
                "growth_pct_output": "optional output field",
            },
        },
        "join_by_key": {"required": ["right_ref", "left_key", "right_key"], "fields": {"right_ref": "authorized ref", "left_key": "authorized column", "right_key": "authorized column"}},
        "anomaly_check": {"required": ["column", "output"], "fields": {"column": "authorized numeric column", "output": "new boolean column"}},
        "anomaly_zscore": {
            "required": ["period_field", "value_field"],
            "fields": {
                "period_field": "authorized ordered period column",
                "value_field": "authorized numeric column",
                "z_threshold": "controller-defined non-negative scalar; required when operation_semantics provides it",
                "baseline_output": "optional output mean field",
                "threshold_output": "optional output threshold field",
                "flag_output": "optional output boolean field",
            },
        },
    }
    return contracts.get(op, {"required": [], "fields": {}})


def _transform_program_response_schema(
    *,
    authorized_input_refs: tuple[str, ...],
    input_schema: dict[str, tuple[str, ...]],
    output_contract_version: str,
    operation_catalog: tuple[str, ...],
) -> dict[str, Any]:
    operation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "op": _string_schema(operation_catalog),
            "arguments": {"type": "object", "additionalProperties": True},
        },
        "required": ["op", "arguments"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "input_artifact_refs": _string_array_schema(
                authorized_input_refs,
                min_items=1,
                max_items=max(1, len(authorized_input_refs)),
            ),
            "operations": {
                "type": "array",
                "items": operation_schema,
            },
            "output_contract_version": {"type": "string", "const": output_contract_version},
        },
        "required": ["input_artifact_refs", "operations", "output_contract_version"],
    }


def _claim_set_response_schema(
    *,
    verified_artifact_refs: tuple[str, ...],
    evidence_items: tuple[dict[str, str], ...],
    numeric_field_names: tuple[str, ...],
) -> dict[str, Any]:
    evidence_ids = tuple(item.get("id", "") for item in evidence_items)
    locators = tuple(item.get("locator", "") for item in evidence_items)
    claim_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"},
            "claim_text": {"type": "string"},
            "claim_type": _string_schema(("fact", "inference", "risk")),
            "supporting_evidence_item_ids": _string_array_schema(evidence_ids, max_items=8),
            "supporting_artifact_ref_ids": _string_array_schema(verified_artifact_refs, max_items=8),
            "citation_locators": _string_array_schema(locators, max_items=8),
            "numeric_fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    field: {"type": "number"}
                    for field in numeric_field_names
                },
            },
            "uncertainty_note": {"type": "string"},
            "status": _string_schema(("ready", "missing_citation")),
        },
        "required": [
            "claim_id",
            "claim_text",
            "claim_type",
            "supporting_evidence_item_ids",
            "supporting_artifact_ref_ids",
            "citation_locators",
            "numeric_fields",
            "uncertainty_note",
            "status",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claims": {"type": "array", "items": claim_schema},
            "status": _string_schema(("ready",)),
        },
        "required": ["claims", "status"],
    }


def _claim_citation_repair_response_schema(
    *,
    claim_ids: tuple[str, ...],
    verified_artifact_refs: tuple[str, ...],
    evidence_items: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    evidence_ids = tuple(item.get("id", "") for item in evidence_items)
    locators = tuple(item.get("locator", "") for item in evidence_items)
    repair_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": _string_schema(claim_ids),
            "supporting_evidence_item_ids": _string_array_schema(evidence_ids, max_items=8),
            "supporting_artifact_ref_ids": _string_array_schema(verified_artifact_refs, max_items=8),
            "citation_locators": _string_array_schema(locators, max_items=8),
        },
        "required": [
            "claim_id",
            "supporting_evidence_item_ids",
            "supporting_artifact_ref_ids",
            "citation_locators",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"repairs": {"type": "array", "items": repair_schema}},
        "required": ["repairs"],
    }


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
    model_semantic_plan: dict[str, Any] = field(default_factory=dict)
    model_generated_field_count: int = 0


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
    logit_entropy: float = 0.0
    logit_confidence_proxy: float = 0.0
    logit_state_bytes: int = 0
    logit_varentropy: float = 0.0
    logit_top_gap: float = 0.0
    logit_peak_position: int = -1
    logit_sequence_length: int = 0
    logit_decision_entropy: float = -1.0
    logit_gate_mode: str = "off"
    logit_state_payload: bytes = field(default=b"", repr=False)
    logit_candidate_surface: CandidateSurfaceV2 | None = None
    logit_producer_receipt: LogitProducerReceipt | None = None
    logit_exact_result: ExactChoiceLogitResult | None = field(default=None, repr=False)
    logit_unavailable_reason: str = "policy_off"


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
    return f"You are the StateBus {role_label} role.\n{instruction}\n\n{body}\n"


def _structured_collaboration_prompt(
    *,
    role_label: str,
    instruction: str,
    payload_tag: str,
    payload: dict[str, Any],
    evidence_blocks: tuple[str, ...] = (),
) -> str:
    prompt = (
        f"You are the StateBus {role_label} role.\n"
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


def _closed_set_selection_schema(
    visible_candidates: tuple["RoleToolCandidate", ...],
) -> dict[str, Any] | None:
    """Build a closed-set JSON schema for a role selection over visible candidates.

    Every field is an enum drawn from the visible candidate surface, and
    ``additionalProperties`` is false, so the response grammar contains NO
    unbounded string/array value. This structurally removes the greedy
    copy-attractor: with a poison prompt (e.g. a ``support_terms=a,b,c`` blob)
    and temperature=0, an unbounded free-text field like ``reason`` or an
    unbounded ``supporting_doc_ids`` array is a copy sink the model degenerates
    into. Constraining the whole object to closed sets makes that impossible
    while staying deterministic. Consumed only in local_vllm mode; other clients
    ignore ``response_schema``.

    Returns None when there are no visible candidates (an empty enum is an
    invalid grammar), so the caller falls back to the generic object grammar.
    """
    keys = tuple(dict.fromkeys(c.candidate_key() for c in visible_candidates if c.candidate_key()))
    routes = tuple(dict.fromkeys(c.route for c in visible_candidates if c.route))
    tools = tuple(dict.fromkeys(c.tool_name for c in visible_candidates if c.tool_name))
    if not keys or not routes or not tools:
        return None
    return {
        "type": "object",
        "properties": {
            "candidate_key": {"type": "string", "enum": list(keys)},
            "route": {"type": "string", "enum": list(routes)},
            "tool_name": {"type": "string", "enum": list(tools)},
        },
        "required": ["candidate_key", "route", "tool_name"],
        "additionalProperties": False,
    }


def _logit_candidate_surface(
    visible_candidates: tuple["RoleToolCandidate", ...],
) -> CandidateSurfaceV2 | None:
    if not 2 <= len(visible_candidates) <= 8:
        return None
    candidate_ids = tuple(candidate.candidate_key() for candidate in visible_candidates)
    candidate_digests = tuple(
        sha256_digest({
            "candidate_id": candidate.candidate_key(),
            "route": candidate.route,
            "tool_name": candidate.tool_name,
            "supporting_doc_ids": list(candidate.supporting_doc_ids),
        })
        for candidate in visible_candidates
    )
    try:
        return CandidateSurfaceV2.from_candidate_ids(
            candidate_ids,
            candidate_digests=candidate_digests,
        )
    except ValueError:
        return None


def _closed_logit_choice_schema(surface: CandidateSurfaceV2) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "choice_code": {"type": "string", "enum": list(surface.aliases)},
        },
        "required": ["choice_code"],
        "additionalProperties": False,
    }


def _logit_alias_payload(surface: CandidateSurfaceV2) -> list[dict[str, str]]:
    return [
        {
            "choice_code": binding.alias,
            "candidate_key": binding.candidate_id,
            "candidate_digest": binding.candidate_digest,
        }
        for binding in surface.bindings
    ]


def _preferred_candidate_payload(
    visible_candidates: tuple["RoleToolCandidate", ...],
    *,
    route_hints: tuple[str, ...] = (),
) -> dict[str, Any]:
    normalized_route_hints = tuple(
        dict.fromkeys(hint.strip() for hint in route_hints if hint.strip())
    )
    if not normalized_route_hints:
        return {}
    preferred: RoleToolCandidate | None = None
    for normalized_hint in normalized_route_hints:
        matching = tuple(
            candidate
            for candidate in visible_candidates
            if normalized_hint in {candidate.route, candidate.candidate_key()}
        )
        if matching:
            preferred = best_visible_candidate(matching)
            break
    if preferred is None:
        preferred = best_visible_candidate(visible_candidates)
    payload: dict[str, Any] = {
        "k": preferred.candidate_key(),
        "r": preferred.route,
        "t": preferred.tool_name,
        "why": "top_ranked_visible_candidate",
    }
    remaining_hints = tuple(
        hint
        for hint in normalized_route_hints
        if hint not in {preferred.route, preferred.candidate_key()}
    )
    if remaining_hints:
        payload["rh"] = list(remaining_hints)
    return payload


def _preferred_candidate_text(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    return (
        f"candidate_key={payload.get('k', '')}; "
        f"route={payload.get('r', '')}; "
        f"tool_name={payload.get('t', '')}; "
        "basis=top-ranked visible candidate"
    )


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
    def _with_semantic_plan(result: dict[str, Any]) -> dict[str, Any]:
        semantic_plan = payload.get("semantic_task_plan")
        if isinstance(semantic_plan, dict):
            result["semantic_task_plan"] = semantic_plan
        retrieval_objective = payload.get("retrieval_objective")
        if isinstance(retrieval_objective, dict):
            result["retrieval_objective"] = retrieval_objective
        return result

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
            return _with_semantic_plan(
                {"steps": [_canonical_step(step) for step in steps if isinstance(step, dict)]}
            )
        return _with_semantic_plan({"steps": []})
    retrieve = payload.get("r")
    execute = payload.get("x")
    summarize = payload.get("s")
    if not isinstance(retrieve, dict) or not isinstance(execute, dict) or not isinstance(summarize, dict):
        return _with_semantic_plan({})
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
    return _with_semantic_plan({"steps": steps})


@dataclass
class RolePathRunner:
    llm_client: LLMClient = field(default_factory=build_llm_client)
    handoff_mode: str = "structured_collaboration"
    json_response_max_attempts: int = 3
    prefix_alignment_mode: str = field(
        default_factory=lambda: os.getenv("STATEBUS_PREFIX_ALIGNMENT_MODE", "independent")
    )
    lean_completion_enabled: bool = field(default_factory=lambda: _env_flag("STATEBUS_LEAN_COMPLETION"))
    logit_gate_mode: str = field(
        default_factory=lambda: os.getenv("STATEBUS_LOGIT_GATE_MODE", "off")
    )
    rendered_request_audit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

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
        return (
            "Return exactly one JSON object containing semantic_task_plan with these exact flat keys: goal, "
            "entities, time_scope, lexical_query, lexical_objective, semantic_query, semantic_objective, "
            "table_query, table_objective, memory_query, memory_objective, memory_reuse_intent, "
            "required_evidence, required_outputs. Give lexical, semantic, table, and memory different retrieval "
            "goals. memory_reuse_intent must be none, assist, artifact, or strategy. required_evidence may only "
            "contain lexical_metadata, semantic_context, table_cell, table_schema, artifact_summary, "
            "memory_artifact, memory_strategy, or citation. Use only allowed required outputs. Do not emit workflow "
            "steps, DAGs, code, case IDs, routes, tools, candidate keys, expected facts, values, or answers."
        )

    def _retriever_instruction(self, *, preferred_candidate_enabled: bool) -> str:
        tie_break = (
            "Treat pc as the default tie-break when multiple tc items look plausible and the hydrated "
            "evidence does not clearly contradict pc or its route hints. "
            if preferred_candidate_enabled
            else "Choose independently from the complete visible tc candidate set using the request and evidence. "
        )
        return (
            "Select exactly one visible route/tool candidate. Copy candidate_key, route, and tool_name "
            "exactly from a single visible tc item. "
            f"{tie_break}"
            "Do not invent labels or use placeholders such as 'tool' or 'route'. "
            "Return a JSON object (starting with { and ending with }) "
            "with keys candidate_key, route, tool_name, supporting_doc_ids, and reason."
        )

    def _executor_instruction(self, *, preferred_candidate_enabled: bool) -> str:
        tie_break = (
            "Treat pc as the default tie-break when multiple tc items share the same tool and the hydrated "
            "evidence does not clearly contradict pc or its route hints. "
            if preferred_candidate_enabled
            else "Validate only the Retriever-selected route/tool against the complete visible tc candidate set. "
        )
        return (
            "Validate the chosen route/tool within the visible candidate set. Copy candidate_key, route, "
            "and tool_name exactly from a single visible tc item. "
            f"{tie_break}"
            "Do not invent labels or use placeholders such as 'tool' or 'route'. "
            "Return a JSON object (starting with { and ending with }) "
            "with keys candidate_key, route, tool_name, action_contract, and reason."
        )

    @staticmethod
    def _executor_logit_choice_instruction(*, recheck: bool) -> str:
        recheck_instruction = (
            " The prior choice did not pass the numeric confidence gate. Re-evaluate all aliases once; "
            "do not preserve the prior alias merely for consistency."
            if recheck
            else ""
        )
        return (
            "Select exactly one candidate from lc. Return exactly one JSON object with the single key "
            "choice_code and copy its ASCII alias exactly. Do not return route, tool, candidate text, "
            f"reason, confidence, prose, or any additional field.{recheck_instruction}"
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
        response_schema: dict[str, Any] | None = None,
    ) -> JsonRoleCompletion:
        attempts: list[LLMResult] = []
        prompt_bytes = 0
        current_prompt = prompt
        retry_note = (
            "\n\nJSON retry instruction: the prior response was empty or malformed. "
            "Return exactly one valid compact JSON object and no prose. "
            "The response MUST start with { and end with }. Do NOT return a JSON array. "
            "Keep string values short."
        )
        max_attempts = max(1, self.json_response_max_attempts)
        start_ns = time.perf_counter_ns()
        last_error: ValueError | None = None
        for attempt_index in range(max_attempts):
            prompt_bytes += len(current_prompt.encode("utf-8"))
            self._record_rendered_request(
                role=purpose,
                prompt=current_prompt,
                response_schema=response_schema,
            )
            result = _run_sync(
                self.llm_client.complete(
                    [ChatMessage(role="user", content=current_prompt)],
                    purpose=purpose,
                    response_schema=response_schema,
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

    def _record_rendered_request(
        self,
        *,
        role: str,
        prompt: str,
        response_schema: dict[str, Any] | None,
    ) -> None:
        role_requests = self.rendered_request_audit.setdefault(role, [])
        describe_role = getattr(self.llm_client, "describe_role", None)
        if callable(describe_role):
            execution_profile = dict(describe_role(role))
        else:
            client_description = self.llm_client.describe()
            role_config = dict(client_description.get("roles", {})).get(role, {})
            execution_profile = {
                **dict(client_description),
                "role": role,
                "execution_mode": str(client_description.get("mode", "")),
                "role_config": dict(role_config) if isinstance(role_config, dict) else {},
            }
        request_payload: dict[str, Any] = {
            "role": role,
            "attempt_index": len(role_requests) + 1,
            "purpose": role,
            "execution_profile": execution_profile,
            "messages": [{"role": "user", "content": prompt}],
            "response_schema": response_schema or {},
            "prompt_sha256": sha256_digest(prompt.encode("utf-8")),
            "prompt_bytes": len(prompt.encode("utf-8")),
        }
        request_payload["request_sha256"] = sha256_digest(request_payload)
        role_requests.append(request_payload)

    def rendered_request_audit_payload(
        self,
        role: str,
        *,
        include_content: bool = True,
    ) -> dict[str, Any]:
        requests: list[dict[str, Any]] = []
        audit_by_role = getattr(self, "rendered_request_audit", {})
        for request in audit_by_role.get(role, []):
            item = dict(request)
            if not include_content:
                item.pop("messages", None)
                response_schema = item.pop("response_schema", {})
                item["response_schema_sha256"] = sha256_digest(response_schema)
            requests.append(item)
        return {
            "schema_version": RENDERED_ROLE_REQUEST_SCHEMA_VERSION,
            "role": role,
            "content_persisted": include_content,
            "request_count": len(requests),
            "requests": requests,
        }

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
        allowed_required_outputs: tuple[str, ...] = (),
        target_entities: tuple[str, ...] = (),
        time_scope: str = "",
    ) -> PlannerRoleResult:
        del task_id, task_group, task_theme, visible_candidates, tags, required_roles
        prompt_slice = prompt_slice or RolePromptSlice(role="planner")
        instruction = self._planner_instruction()
        del prompt_slice, strict_surface
        payload = {
            "g": goal,
            "q": query_text,
            "h": summary_hint,
            "ao": list(allowed_required_outputs),
            "en": list(target_entities),
            "ts": time_scope,
        }
        prompt = self._render_prompt(
            role_label="planner",
            instruction=instruction,
            payload_tag="sb-plan-v1",
            payload=payload,
            text_sections=(
                ("Goal", goal),
                ("Task request", query_text),
                ("Summary hint", summary_hint),
                ("Allowed required outputs", ", ".join(allowed_required_outputs)),
                ("Entity hints", ", ".join(target_entities)),
                ("Time scope hint", time_scope),
            ),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="planner",
            response_schema=planner_semantic_plan_response_schema(
                allowed_required_outputs=allowed_required_outputs,
            ),
        )
        result = completion.result
        payload = _canonicalize_planner_workflow_payload(completion.payload)
        retrieval_objective = payload.get("retrieval_objective", {})
        retrieval_objective = retrieval_objective if isinstance(retrieval_objective, dict) else {}
        semantic_plan = payload.get("semantic_task_plan", {})
        semantic_plan = semantic_plan if isinstance(semantic_plan, dict) else {}
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
            model_semantic_plan=semantic_plan,
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
        preferred_candidate = (
            _preferred_candidate_payload(visible_candidates, route_hints=route_hints)
            if strict_surface
            else {}
        )
        instruction = self._retriever_instruction(
            preferred_candidate_enabled=bool(preferred_candidate)
        )
        if preferred_candidate and self.handoff_mode != "text_collaboration":
            payload["pc"] = preferred_candidate
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
                ("Preferred Candidate", _preferred_candidate_text(preferred_candidate)),
                ("Hydrated Evidence", evidence_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            preferred_candidate_section = (
                f"Preferred candidate: {_preferred_candidate_text(preferred_candidate)}\n\n"
                if preferred_candidate
                else ""
            )
            prompt = (
                "You are the StateBus retriever role.\n"
                f"{instruction}\n\n"
                f"Query: {query_text}\n"
                f"Retrieved docs: {','.join(retrieved_doc_ids)}\n"
                f"Visible candidates: {_candidate_identity_line(visible_candidates)}\n"
                f"Candidate notes: {_candidate_notes}\n\n"
                f"{preferred_candidate_section}"
                f"Evidence note:\n{prompt_slice.combined_text()}\n"
            )
        completions: list[JsonRoleCompletion] = []
        current_prompt = prompt
        _selection_schema = _closed_set_selection_schema(visible_candidates)
        max_attempts = max(1, self.json_response_max_attempts)
        last_error: RoleSelectionError | None = None
        for attempt_index in range(max_attempts):
            completion = self._complete_json_role(
                prompt=current_prompt,
                purpose="retriever",
                response_schema=_selection_schema,
            )
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
        logit_recheck: bool = False,
    ) -> ExecutorRoleDecision:
        prompt_slice = prompt_slice or RolePromptSlice(role="executor")
        logit_gate_mode = _normalize_logit_gate_mode(self.logit_gate_mode)
        logit_surface = (
            _logit_candidate_surface(visible_candidates)
            if logit_gate_mode != "off"
            else None
        )
        dedicated_logit_choice = logit_surface is not None
        logit_unavailable_reason = (
            "policy_off"
            if logit_gate_mode == "off"
            else "candidate_surface_requires_2_to_8_unique_candidates"
        )
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
        preferred_candidate = (
            _preferred_candidate_payload(visible_candidates, route_hints=route_hints)
            if strict_surface
            else {}
        )
        instruction = (
            self._executor_logit_choice_instruction(recheck=logit_recheck)
            if dedicated_logit_choice
            else self._executor_instruction(
                preferred_candidate_enabled=bool(preferred_candidate)
            )
        )
        if logit_surface is not None:
            payload["lc"] = _logit_alias_payload(logit_surface)
        if preferred_candidate and self.handoff_mode != "text_collaboration":
            payload["pc"] = preferred_candidate
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
                ("Preferred Candidate", _preferred_candidate_text(preferred_candidate)),
                ("Hydrated Evidence", evidence_text),
            ),
            shared_prefix_text=evidence_text,
        )
        if self.handoff_mode == "text_collaboration" and not _shared_prefix_enabled(
            self.prefix_alignment_mode,
            evidence_text,
        ):
            preferred_candidate_section = (
                f"Preferred candidate: {_preferred_candidate_text(preferred_candidate)}\n\n"
                if preferred_candidate
                else ""
            )
            prompt = (
                "You are the StateBus executor role.\n"
                f"{instruction}\n\n"
                f"Route: {route}\n"
                f"Tool: {tool_name}\n"
                f"Validated route: {route}\n"
                f"Validated tool: {tool_name}\n"
                f"Validated action contract: {action_contract}\n"
                f"Visible candidates: {_candidate_identity_line(visible_candidates)}\n"
                f"Candidate notes: {_candidate_notes}\n\n"
                + (
                    "Alias choices: "
                    + "; ".join(
                        f"{binding.alias}={binding.candidate_id}"
                        for binding in logit_surface.bindings
                    )
                    + "\n\n"
                    if logit_surface is not None
                    else ""
                )
                + f"{preferred_candidate_section}"
                + f"Evidence note:\n{prompt_slice.combined_text()}\n"
            )
        completions: list[JsonRoleCompletion] = []
        current_prompt = prompt
        _selection_schema = (
            _closed_logit_choice_schema(logit_surface)
            if logit_surface is not None
            else _closed_set_selection_schema(visible_candidates)
        )
        max_attempts = max(1, self.json_response_max_attempts)
        last_error: RoleSelectionError | None = None
        parsed_selection = ParsedRoleSelection()
        for attempt_index in range(max_attempts):
            completion = self._complete_json_role(
                prompt=current_prompt,
                purpose="executor",
                response_schema=_selection_schema,
            )
            completions.append(completion)
            completion_payload = completion.payload
            try:
                if logit_surface is not None:
                    if set(completion_payload) != {"choice_code"}:
                        raise RoleSelectionError("logit_choice_schema_mismatch")
                    choice_code = completion_payload.get("choice_code")
                    if not isinstance(choice_code, str) or choice_code not in logit_surface.aliases:
                        raise RoleSelectionError("logit_choice_alias_outside_surface")
                    selected_candidate = visible_candidates[
                        logit_surface.aliases.index(choice_code)
                    ]
                    parsed_selection = ParsedRoleSelection(
                        route=selected_candidate.route,
                        tool_name=selected_candidate.tool_name,
                        candidate_key=selected_candidate.candidate_key(),
                        candidate_rank=selected_candidate.helper_rank,
                        reason=f"closed_alias_choice:{choice_code}",
                        action_contract=action_contract,
                    )
                else:
                    parsed_selection = _parse_role_selection(completion_payload)
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
                current_prompt = (
                    f"{prompt}\n\nSelection retry instruction: return exactly one choice_code from "
                    f"{', '.join(logit_surface.aliases)} and no other field."
                    if logit_surface is not None
                    else _selection_retry_prompt(
                        prompt=prompt,
                        error=exc,
                        visible_candidates=visible_candidates,
                    )
                )
        else:
            raise last_error or RoleSelectionError("selection_retry_exhausted")
        result = _merge_llm_results([completion.result for completion in completions])
        _logit_entropy = 0.0
        _logit_confidence_proxy = 0.0
        _logit_state_bytes = 0
        _logit_varentropy = 0.0
        _logit_top_gap = 0.0
        _logit_peak_position = -1
        _logit_sequence_length = 0
        _logit_decision_entropy = -1.0
        _logit_payload = b""
        _logit_receipt: LogitProducerReceipt | None = None
        _logit_exact_result: ExactChoiceLogitResult | None = None
        if logit_surface is not None:
            request_id = f"executor-{sha256_digest(prompt)[:20]}"
            attempt_id = f"{request_id}:{'recheck' if logit_recheck else 'initial'}"
            exact_result = extract_exact_choice_logit_state(
                completion_text=result.text,
                top_logprobs=result.top_logprobs,
                candidate_surface=logit_surface,
                request_id=request_id,
                attempt_id=attempt_id,
            )
            _logit_exact_result = exact_result
            _logit_receipt = exact_result.receipt
            logit_unavailable_reason = exact_result.receipt.unavailable_reason
            if exact_result.available:
                if exact_result.selected_candidate_id != selected_candidate.candidate_key():
                    raise RoleSelectionError("logit_selected_candidate_binding_mismatch")
                _logit_payload = exact_result.payload_bytes
                _logit_entropy = exact_result.entropy
                _logit_confidence_proxy = exact_result.candidate_probabilities[
                    exact_result.selected_candidate_ordinal
                ]
                _logit_state_bytes = len(exact_result.payload_bytes)
                _logit_top_gap = exact_result.top_margin
                _logit_peak_position = exact_result.receipt.decision_token_position
                _logit_sequence_length = exact_result.receipt.sequence_length
                _logit_decision_entropy = exact_result.entropy
                logit_unavailable_reason = ""
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
            logit_entropy=_logit_entropy,
            logit_confidence_proxy=_logit_confidence_proxy,
            logit_state_bytes=_logit_state_bytes,
            logit_varentropy=_logit_varentropy,
            logit_top_gap=_logit_top_gap,
            logit_peak_position=_logit_peak_position,
            logit_sequence_length=_logit_sequence_length,
            logit_decision_entropy=_logit_decision_entropy,
            logit_gate_mode=logit_gate_mode,
            logit_state_payload=_logit_payload,
            logit_candidate_surface=logit_surface,
            logit_producer_receipt=_logit_receipt,
            logit_exact_result=_logit_exact_result,
            logit_unavailable_reason=logit_unavailable_reason,
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
                "You are the StateBus summarizer role.\n"
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

    def propose_plan(
        self,
        *,
        envelope: AdaptiveTaskEnvelope,
        task_goal: str,
        allowed_inputs: tuple[dict[str, str], ...],
        capability_surface: tuple[dict[str, object], ...],
        required_roles: tuple[str, ...] = (),
        role_cardinality: dict[str, tuple[int, int]] | None = None,
        replan_context: dict[str, object] | None = None,
        role_slot_layout: bool = False,
    ) -> PlanProposal:
        """Return an untrusted plan candidate; policy approval remains in the Driver."""
        unique_required_roles = tuple(dict.fromkeys(required_roles))
        if role_cardinality is None and envelope.role_cardinality:
            role_cardinality = dict(envelope.role_cardinality)
        if role_cardinality is None:
            role_cardinality = {
                role: (
                    (1, max(1, envelope.max_plan_steps - len(unique_required_roles) + 1))
                    if role == "executor"
                    else (1, 1)
                )
                for role in unique_required_roles
            }
        if role_slot_layout and (
            role_cardinality.get("retriever") != (1, 1)
            or role_cardinality.get("summarizer") != (1, 1)
            or role_cardinality.get("executor", (0, 0))[0] != 1
        ):
            raise ValueError("adaptive_plan_role_slot_layout_cardinality_mismatch")
        plan_response_layout = (
            {
                "kind": "required_role_slots",
                "required_slots": [
                    "retriever_step",
                    "primary_executor_step",
                    "summarizer_step",
                ],
                "optional_slots": ["additional_executor_steps"],
                "additional_executor_limit": max(role_cardinality.get("executor", (1, 1))[1] - 1, 0),
            }
            if role_slot_layout
            else {"kind": "steps_array", "required_slots": ["steps"]}
        )
        capability_ids_by_role = {
            role: [
                str(item.get("id", ""))
                for item in capability_surface
                if str(item.get("role", "")) == role and str(item.get("id", ""))
            ]
            for role in unique_required_roles
        }
        payload = {
            "task": {"goal": task_goal, "allowed_inputs": list(allowed_inputs)},
            "capability_surface": list(capability_surface),
            "authority": {
                "risk_class": envelope.risk_class.value,
                "controller_owned_failure_actions": {
                    "retriever": "request_replan for at most one eligible step",
                    "executor": "fallback_deterministic",
                    "summarizer": "fail",
                },
                "allowed_memory_policies": list(envelope.allowed_memory_policies),
                "allowed_completion_keys": [
                    "min_locator_count",
                    "min_rows",
                    "required_evidence_types",
                    "required_fields",
                    "max_conflicts",
                ],
                "required_roles": list(unique_required_roles),
                "capability_ids_by_role": capability_ids_by_role,
                "role_cardinality": {
                    role: {"minimum": bounds[0], "maximum": bounds[1]}
                    for role, bounds in sorted(role_cardinality.items())
                },
                "plan_response_layout": plan_response_layout,
                # Python availability is an Envelope/Controller decision.  The
                # Planner sees only its bounded capability closure; it cannot
                # turn this flag on or change sandbox/validator readiness.
                "allow_llm_python": envelope.allow_llm_python,
                "risk_class_allows_bounded_code": envelope.risk_class.value == "bounded_code",
                "authorized_python_capability_ids": [
                    str(item.get("id", ""))
                    for item in capability_surface
                    if str(item.get("execution_kind", "")) == "llm_bounded_python"
                ],
            },
            "budgets": {
                "max_steps": envelope.max_plan_steps,
                "max_replans": envelope.max_replans,
                "max_retrieval_expansions": envelope.max_retrieval_expansions,
            },
            "allowed_outputs": list(envelope.allowed_output_contracts),
            "replan_context": replan_context,
        }
        instruction = (
            "You are StateBus Planner. Propose a bounded DAG only; you do not dispatch, call roles, "
            "register capabilities, write code, shell commands, paths, or network addresses. Copy only "
            "capability IDs in capability_surface and keep each role/output contract consistent with that same "
            "capability entry. For every step, capability_id must be copied from "
            "authority.capability_ids_by_role[role]; verify each required role slot against that exact allowlist before "
            "returning. Return JSON using authority.plan_response_layout and final_output_contract_version. "
            "Each step has step_id, role, capability_id, goal, depends_on, input_ref_ids, input_ref_kinds, "
            "output_contract_version, and completion_criteria. Do not emit on_failure: it is controller-owned "
            "recovery policy and will be attached after policy validation, with no more than budgets.max_replans "
            "request_replan actions. Follow authority.role_cardinality exactly; extra duplicate role stages are invalid. "
            "Use the fewest Executor stages that fully express the task. Add another Executor only when the first "
            "produces a distinct, necessary intermediate artifact that retains every field the downstream stage needs. "
            "Do not split one analysis merely to rename, project, summarize, or repeat work that one registered capability "
            "can complete. A capability and its fallback_capability_id are alternative recovery paths and must never be "
            "placed consecutively as ordinary plan stages. The plan may contain additional Executor steps only up to "
            "budgets.max_steps. Each "
            "capability_surface entry contains completion_criteria: only use "
            "criteria keys, fields, list values, and numeric ranges listed on the same capability entry. For a derived Executor stage, "
            "required_fields must name meaningful outputs produced by that stage, not merely repeat source columns. The final Executor's "
            "required_fields must cover the required final analysis schema supplied in the task goal. Use stable short step IDs. A downstream step should name its producer in "
            "depends_on and leave input_ref_ids/input_ref_kinds empty unless the task supplied an explicit input Ref. "
            "Omit required_input_fields for the Retriever, the primary Executor, and the Summarizer. Every additional "
            "Executor must include required_input_fields listing the exact fields it consumes from its immediate upstream "
            "Executor; those fields must be a subset of that producer's completion_criteria.required_fields. "
            "A retriever has no input Ref; the controller supplies the approved corpus. Only an executor may consume the "
            "explicit task input Ref, and a downstream executor should consume its immediate upstream artifact through depends_on. "
            "Choose the narrowest registered execution capability that fully expresses the task. Use bounded Python when the "
            "declarative operation surface cannot represent a required categorical output, parsing rule, statistical method, or stage. "
            "A linear declarative row pipeline cannot split one input into branches and recombine them, self-join or pivot category "
            "rows into columns, or compare values that remain on different rows; choose bounded Python when any of those operations "
            "is required. "
            "Dependency values must be step IDs from this proposal, never a task Ref or capability ID. "
            "Include exactly the role counts declared by authority.role_cardinality. Use only an "
            "authority.allowed_memory_policies value for requested_memory_policy. Represent no dependencies or refs "
            "with an empty JSON array []; never put none, null, n/a, or other sentinel strings in an array."
        )
        if role_slot_layout:
            instruction += (
                " Put exactly one Retriever object in retriever_step, the first Executor in "
                "primary_executor_step and exactly one Summarizer in summarizer_step. Omit additional_executor_steps "
                "when one Executor can satisfy the task; otherwise put only the necessary remaining Executors there. "
                "Do not emit a top-level steps field. The slot fixes the role, but you still choose each registered "
                "capability, goal, completion criteria, and optional extra Executor."
            )
        else:
            instruction += " Put the complete proposed DAG in the top-level steps array."
        if replan_context is not None:
            instruction += (
                " This is the one permitted policy repair. Return a complete replacement plan, not a patch and not "
                "a copy of replan_context.invalid_proposal. Add, remove, or reorder steps when needed to satisfy every "
                "authority.role_cardinality bound and every reported policy issue. Before returning, count the roles "
                "in the replacement and verify that every depends_on value names a step in that same replacement."
            )
        prompt = self._render_prompt(
            role_label="planner",
            instruction=instruction,
            payload_tag="sb-adaptive-plan-v1",
            payload=payload,
            text_sections=(("Task goal", task_goal),),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="planner",
            response_schema=_adaptive_plan_response_schema(
                capability_surface=capability_surface,
                allowed_outputs=envelope.allowed_output_contracts,
                allowed_memory_policies=envelope.allowed_memory_policies,
                max_steps=envelope.max_plan_steps,
                role_slot_layout=role_slot_layout,
            ),
        )
        steps_with_roles: list[tuple[object, str | None]]
        if role_slot_layout:
            retriever_raw = completion.payload.get("retriever_step")
            primary_executor_raw = completion.payload.get("primary_executor_step")
            summarizer_raw = completion.payload.get("summarizer_step")
            additional_raw = completion.payload.get("additional_executor_steps", [])
            if not all(isinstance(item, dict) for item in (
                retriever_raw, primary_executor_raw, summarizer_raw,
            )):
                raise ValueError("adaptive_plan_required_role_slot_not_object")
            if not isinstance(additional_raw, list):
                raise ValueError("adaptive_plan_additional_executors_not_list")
            steps_with_roles = [
                (retriever_raw, "retriever"),
                (primary_executor_raw, "executor"),
                *((item, "executor") for item in additional_raw),
                (summarizer_raw, "summarizer"),
            ]
        else:
            steps_raw = completion.payload.get("steps", [])
            if not isinstance(steps_raw, list):
                raise ValueError("adaptive_plan_steps_not_list")
            steps_with_roles = [(item, None) for item in steps_raw]
        steps: list[PlanStepProposal] = []
        remaining_replan_slots = envelope.max_replans
        for item, assigned_role in steps_with_roles:
            if not isinstance(item, dict):
                raise ValueError("adaptive_plan_step_not_object")
            role = assigned_role or str(item.get("role", ""))
            on_failure = "fail"
            if role == "retriever" and remaining_replan_slots > 0:
                on_failure = "request_replan"
                remaining_replan_slots -= 1
            elif role == "executor":
                on_failure = "fallback_deterministic"
            steps.append(
                PlanStepProposal(
                    step_id=str(item.get("step_id", "")),
                    role=role,
                    capability_id=str(item.get("capability_id", "")),
                    goal=str(item.get("goal", "")),
                    depends_on=_coerce_optional_string_tuple(item.get("depends_on", [])),
                    input_ref_ids=_coerce_optional_string_tuple(item.get("input_ref_ids", [])),
                    input_ref_kinds=_coerce_optional_string_tuple(item.get("input_ref_kinds", [])),
                    output_contract_version=str(item.get("output_contract_version", "")),
                    completion_criteria=(item.get("completion_criteria", {}) if isinstance(item.get("completion_criteria", {}), dict) else {}),
                    on_failure=on_failure,
                    required_input_fields=_coerce_optional_string_tuple(item.get("required_input_fields", [])),
                )
            )
        result = completion.result
        return PlanProposal(
            proposal_id=str(completion.payload.get("proposal_id", f"proposal-{envelope.task_id}")),
            task_id=envelope.task_id,
            steps=tuple(steps),
            final_output_contract_version=str(completion.payload.get("final_output_contract_version", "")),
            requested_memory_policy=str(completion.payload.get("requested_memory_policy", "none")),
            planner_notes=str(completion.payload.get("planner_notes", ""))[:512],
            model_id=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            latency_ms=completion.latency_ms,
            raw_output_hash=sha256_digest(result.text.encode("utf-8")),
        )

    def build_evidence_request(
        self,
        *,
        task_id: str,
        step_id: str,
        step_goal: str,
        corpus_scope_ids: tuple[str, ...],
        evidence_types: tuple[str, ...],
        target_entities: tuple[str, ...] = (),
        time_scope: str = "",
        task_goal: str = "",
        gap_context: dict[str, object] | None = None,
    ) -> EvidenceRequest:
        payload = {
            "task": {"goal": task_goal or step_goal},
            "step": {"id": step_id, "goal": step_goal},
            "corpus_scope": list(corpus_scope_ids),
            "evidence_types": list(evidence_types),
            "authority": {
                "target_entities": list(target_entities),
                "time_scope": time_scope,
                "controller_injects_target_entities_and_time_scope": True,
            },
            "gap_context": gap_context,
            "limits": {"max_queries": 3, "max_candidates": 12},
        }
        instruction = (
            "You are StateBus Retriever. Propose a bounded evidence request only. Return JSON with queries, "
            "evidence_types, corpus_scope_ids and max_candidates. Use only supplied corpus IDs and evidence types. "
            "authority.target_entities and authority.time_scope are read-only query context: do not emit either field. "
            "The controller injects them after your request is validated, so you cannot add, remove, rename, infer, or "
            "broaden those constraints. The task goal explains what the queries should seek, while authority defines "
            "what the request is allowed to require. "
            "Do not return an answer, paths, tools, code, or data sources."
        )
        prompt = self._render_prompt(
            role_label="retriever",
            instruction=instruction,
            payload_tag="sb-evidence-request-v1",
            payload=payload,
            text_sections=(("Task goal", task_goal or step_goal), ("Evidence goal", step_goal)),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="retriever",
            response_schema=_evidence_request_response_schema(
                corpus_scope_ids=corpus_scope_ids,
                evidence_types=evidence_types,
            ),
        )
        response = completion.payload
        queries = _coerce_string_tuple(response.get("queries", []))
        selected_evidence_types = _coerce_string_tuple(response.get("evidence_types", evidence_types))
        selected_corpus_scope_ids = _coerce_string_tuple(response.get("corpus_scope_ids", corpus_scope_ids))
        max_candidates = int(response.get("max_candidates", 12))
        if not 1 <= len(queries) <= 3:
            raise ValueError("adaptive_evidence_query_count_out_of_bounds")
        if not set(selected_evidence_types) <= set(evidence_types) or not selected_evidence_types:
            raise ValueError("adaptive_evidence_type_outside_authority")
        if not set(selected_corpus_scope_ids) <= set(corpus_scope_ids) or not selected_corpus_scope_ids:
            raise ValueError("adaptive_corpus_scope_outside_authority")
        if not 1 <= max_candidates <= 12:
            raise ValueError("adaptive_candidate_budget_out_of_bounds")
        return EvidenceRequest(
            request_id=str(response.get("request_id", f"evidence-{task_id}-{step_id}")),
            task_id=task_id,
            step_id=step_id,
            queries=queries,
            evidence_types=selected_evidence_types,
            target_entities=target_entities,
            time_scope=time_scope,
            corpus_scope_ids=selected_corpus_scope_ids,
            memory_policy=str(response.get("memory_policy", "none")),
            max_candidates=max_candidates,
            source_plan_step_id=step_id,
        )

    def build_transform_program(
        self,
        *,
        program_id: str,
        authorized_input_refs: tuple[str, ...],
        input_schema: dict[str, tuple[str, ...]],
        output_contract_version: str,
        operation_catalog: tuple[str, ...],
        step_goal: str = "",
        desired_output_fields: tuple[str, ...] = (),
        input_preview: tuple[dict[str, object], ...] = (),
        operation_semantics: dict[str, object] | None = None,
        repair_context: dict[str, object] | None = None,
    ) -> TransformProgram:
        payload = {
            "step_goal": step_goal,
            "authorized_input_refs": list(authorized_input_refs),
            "input_schema": {key: list(value) for key, value in sorted(input_schema.items())},
            "input_preview": [dict(sorted(row.items())) for row in input_preview[:4]],
            "desired_output_fields": list(desired_output_fields),
            "output_contract_version": output_contract_version,
            "operation_catalog": list(operation_catalog),
            "operation_semantics": dict(operation_semantics or {}),
            "repair_context": dict(repair_context or {}),
            "operation_contracts": {
                op: _operation_argument_contract(op)
                for op in operation_catalog
            },
        }
        instruction = (
            "You are StateBus Executor. Return a TransformProgram JSON only. Do not generate Python, shell, paths, "
            "or arbitrary expressions. Use only supplied input refs, columns, and operation_catalog. "
            "Choose operations that satisfy step_goal and desired_output_fields. Copy argument field names from "
            "operation_contracts exactly and satisfy the controller-owned operation_semantics exactly. "
            "When an existing field only needs a new output name, use rename; never use derive_safe to copy or rename "
            "a value, and never put a numeric literal where an operation contract requires a column. "
            "Track the output columns of every operation in order and never reference a column that has not been "
            "supplied or produced. compare_periods emits only its declared result fields plus carry_fields; use "
            "carry_fields for invariant identifiers needed by desired_output_fields. When repair_context is non-empty, "
            "replace the invalid program and address every "
            "reported validation error without changing input authority or output contract. "
            "Return input_artifact_refs, operations, and output_contract_version; "
            "each operation has op and arguments."
        )
        prompt = self._render_prompt(
            role_label="executor",
            instruction=instruction,
            payload_tag="sb-transform-program-v1",
            payload=payload,
            text_sections=(),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="executor",
            response_schema=_transform_program_response_schema(
                authorized_input_refs=authorized_input_refs,
                input_schema=input_schema,
                output_contract_version=output_contract_version,
                operation_catalog=operation_catalog,
            ),
        )
        response = completion.payload
        if str(response.get("output_contract_version", "")) != output_contract_version:
            raise ValueError("adaptive_transform_output_contract_mismatch")
        operations_raw = response.get("operations", [])
        if not isinstance(operations_raw, list):
            raise ValueError("transform_operations_not_list")
        operations = tuple(
            TransformStep(
                op=str(item.get("op", "")),
                arguments=(item.get("arguments", {}) if isinstance(item.get("arguments", {}), dict) else {}),
            )
            for item in operations_raw
            if isinstance(item, dict)
        )
        return TransformProgram(
            program_id=program_id,
            input_artifact_refs=_coerce_string_tuple(response.get("input_artifact_refs", authorized_input_refs)),
            operations=operations,
            output_contract_version=output_contract_version,
        )

    def build_claim_set(
        self,
        *,
        task_id: str,
        claim_set_id: str,
        verified_artifact_refs: tuple[str, ...],
        evidence_items: tuple[dict[str, str], ...],
        task_goal: str = "",
        artifact_summaries: tuple[dict[str, object], ...] = (),
        expected_claim_count: int | None = None,
    ) -> ClaimSet:
        if expected_claim_count is not None and expected_claim_count < 1:
            raise ValueError("adaptive_expected_claim_count_invalid")
        numeric_field_names = tuple(sorted({
            str(key)
            for item in artifact_summaries
            for row in item.get("rows", [])
            if isinstance(row, dict)
            for key, value in row.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }))
        payload = {
            "task_goal": task_goal,
            "reference_catalog": {
                "evidence": [
                    {
                        "evidence_id": item.get("id", ""),
                        "citation_locator": item.get("locator", ""),
                        "evidence_text": item.get("text", ""),
                    }
                    for item in evidence_items
                ],
                "artifacts": [
                    {
                        "artifact_ref_id": str(item.get("artifact_ref_id", "")),
                        "status": str(item.get("status", "")),
                        "verified_rows": item.get("rows", []),
                        "numeric_field_names": sorted({
                            str(key)
                            for row in item.get("rows", [])
                            if isinstance(row, dict)
                            for key, value in row.items()
                            if isinstance(value, (int, float)) and not isinstance(value, bool)
                        }),
                    }
                    for item in artifact_summaries
                ],
            },
        }
        if expected_claim_count is not None:
            payload["claim_contract"] = {
                "expected_claim_count": expected_claim_count,
                "evidence_is_support_only": True,
                "one_claim_per_verified_row": True,
            }
        instruction = (
            "You are StateBus Summarizer. Return a ClaimSet JSON only. Use reference_catalog as three typed columns: "
            "supporting_evidence_item_ids may contain only evidence.evidence_id values; citation_locators may contain "
            "only evidence.citation_locator values; supporting_artifact_ref_ids may contain only "
            "artifacts.artifact_ref_id values. Never put an artifact ID in an evidence-ID field, never put an artifact "
            "row or artifact ID in citation_locators, and never invent a reference. Artifact rows support numeric values "
            "but are not citation locators. For every claim with numeric_fields, use only values present in its "
            "supporting artifact's verified_rows, and use only that artifact's numeric_field_names as numeric_fields keys. "
            "Do not encode or convert period/date/string labels as numbers, and do not assert a numeric value that appears "
            "only in evidence text. "
            "Do not modify verified numbers. Use the evidence text and verified rows to answer task_goal. claim_type "
            "must be fact, inference, or risk. Claim status may only be ready or "
            "missing_citation. Create one compact claim per verified output row; do not split a row across claims or "
            "repeat a claim. Keep claim_text to one short sentence and put the exact numeric values in numeric_fields. "
            "Use only the source locators needed for the claim and never repeat a locator within a claim. Use top-level "
            "status ready because this request contains verified support."
        )
        if expected_claim_count is not None:
            instruction += (
                " Return exactly claim_contract.expected_claim_count claims and no others. Evidence items are support "
                "for the supplied verified rows; they do not authorize claims for rows absent from verified_rows."
            )
        prompt = self._render_prompt(
            role_label="summarizer",
            instruction=instruction,
            payload_tag="sb-claim-set-v1",
            payload=payload,
            text_sections=(),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="summarizer",
            response_schema=_claim_set_response_schema(
                verified_artifact_refs=verified_artifact_refs,
                evidence_items=evidence_items,
                numeric_field_names=numeric_field_names,
            ),
        )
        response = completion.payload
        claims_raw = response.get("claims", [])
        if not isinstance(claims_raw, list):
            raise ValueError("claims_not_list")
        if expected_claim_count is not None and len(claims_raw) != expected_claim_count:
            raise ValueError(
                f"adaptive_claim_count_mismatch:{len(claims_raw)}:{expected_claim_count}"
            )
        claims: list[Claim] = []
        for item in claims_raw:
            if not isinstance(item, dict):
                continue
            claim_type = str(item.get("claim_type", "fact"))
            claim_status = str(item.get("status", "ready"))
            if claim_type not in {"fact", "inference", "risk"}:
                raise ValueError("adaptive_claim_type_outside_contract")
            if claim_status not in {"ready", "missing_citation"}:
                raise ValueError("adaptive_claim_status_outside_contract")
            numeric_raw = item.get("numeric_fields", {})
            if isinstance(numeric_raw, dict) and not set(map(str, numeric_raw)) <= set(numeric_field_names):
                raise ValueError("adaptive_claim_numeric_field_outside_contract")
            numeric = {str(key): float(value) for key, value in numeric_raw.items()} if isinstance(numeric_raw, dict) else {}
            claims.append(
                Claim(
                    claim_id=str(item.get("claim_id", "")),
                    claim_text=str(item.get("claim_text", "")),
                    claim_type=claim_type,
                    supporting_evidence_item_ids=_coerce_string_tuple(item.get("supporting_evidence_item_ids", [])),
                    supporting_artifact_ref_ids=_coerce_string_tuple(item.get("supporting_artifact_ref_ids", [])),
                    citation_locators=_coerce_string_tuple(item.get("citation_locators", [])),
                    numeric_fields=numeric,
                    uncertainty_note=str(item.get("uncertainty_note", "")),
                    status=claim_status,
                )
            )
        status_value = str(response.get("status", ClaimSetStatus.READY.value))
        try:
            status = ClaimSetStatus(status_value)
        except ValueError:
            status = ClaimSetStatus.MISSING_CITATION
        return ClaimSet(claim_set_id=claim_set_id, task_id=task_id, claims=tuple(claims), status=status)

    def repair_claim_citations(
        self,
        *,
        claim_set: ClaimSet,
        verified_artifact_refs: tuple[str, ...],
        evidence_items: tuple[dict[str, str], ...],
        validation_errors: tuple[str, ...],
    ) -> ClaimSet:
        """Repair only typed reference fields; claim content and numbers remain controller-owned."""
        if not claim_set.claims:
            raise ValueError("adaptive_claim_repair_requires_claims")
        payload = {
            "validation_errors": list(validation_errors),
            "claim_ids": [claim.claim_id for claim in claim_set.claims],
            "reference_catalog": {
                "evidence": [
                    {
                        "evidence_id": item.get("id", ""),
                        "citation_locator": item.get("locator", ""),
                    }
                    for item in evidence_items
                ],
                "artifacts": [{"artifact_ref_id": artifact_id} for artifact_id in verified_artifact_refs],
            },
        }
        instruction = (
            "You are StateBus Summarizer performing one citation-only repair. Return JSON with repairs only. "
            "Each repair must preserve its supplied claim_id and may change only supporting_evidence_item_ids, "
            "supporting_artifact_ref_ids, and citation_locators. Do not return claim text, numeric fields, claim type, "
            "status, or any new claims. Use only the matching typed reference_catalog column: evidence_id for "
            "supporting_evidence_item_ids, citation_locator for citation_locators, artifact_ref_id for "
            "supporting_artifact_ref_ids."
        )
        prompt = self._render_prompt(
            role_label="summarizer",
            instruction=instruction,
            payload_tag="sb-claim-citation-repair-v1",
            payload=payload,
            text_sections=(),
            shared_prefix_text="",
        )
        completion = self._complete_json_role(
            prompt=prompt,
            purpose="summarizer",
            response_schema=_claim_citation_repair_response_schema(
                claim_ids=tuple(claim.claim_id for claim in claim_set.claims),
                verified_artifact_refs=verified_artifact_refs,
                evidence_items=evidence_items,
            ),
        )
        repairs_raw = completion.payload.get("repairs", [])
        if not isinstance(repairs_raw, list):
            raise ValueError("adaptive_claim_repair_not_list")
        repairs_by_id: dict[str, dict[str, object]] = {}
        for repair in repairs_raw:
            if not isinstance(repair, dict):
                raise ValueError("adaptive_claim_repair_not_object")
            claim_id = str(repair.get("claim_id", ""))
            if not claim_id or claim_id in repairs_by_id:
                raise ValueError("adaptive_claim_repair_duplicate_or_empty_claim_id")
            repairs_by_id[claim_id] = repair
        expected_ids = {claim.claim_id for claim in claim_set.claims}
        if set(repairs_by_id) != expected_ids:
            raise ValueError("adaptive_claim_repair_claim_ids_mismatch")
        allowed_evidence_ids = {item.get("id", "") for item in evidence_items}
        allowed_locators = {item.get("locator", "") for item in evidence_items}
        allowed_artifact_ids = set(verified_artifact_refs)
        repaired_claims: list[Claim] = []
        for claim in claim_set.claims:
            repair = repairs_by_id[claim.claim_id]
            evidence_ids = _coerce_string_tuple(repair.get("supporting_evidence_item_ids", []))
            artifact_ids = _coerce_string_tuple(repair.get("supporting_artifact_ref_ids", []))
            locators = _coerce_string_tuple(repair.get("citation_locators", []))
            if (
                not set(evidence_ids) <= allowed_evidence_ids
                or not set(artifact_ids) <= allowed_artifact_ids
                or not set(locators) <= allowed_locators
            ):
                raise ValueError("adaptive_claim_repair_reference_outside_authority")
            repaired_claims.append(
                replace(
                    claim,
                    supporting_evidence_item_ids=evidence_ids,
                    supporting_artifact_ref_ids=artifact_ids,
                    citation_locators=locators,
                )
            )
        return ClaimSet(
            claim_set_id=claim_set.claim_set_id,
            task_id=claim_set.task_id,
            claims=tuple(repaired_claims),
            status=claim_set.status,
            schema_version=claim_set.schema_version,
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
