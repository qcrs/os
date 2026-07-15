from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from v2.contracts import CanonicalTaskSpec
from v2.utils import sha256_digest


SEMANTIC_TASK_PLAN_SCHEMA_VERSION = "statebus.semantic_task_plan.v1"
REGISTERED_RETRIEVAL_OBJECTIVES = (
    "lexical_metadata",
    "semantic_chunk",
    "table_structure",
    "memory",
)
REGISTERED_EVIDENCE_TYPES = {
    "lexical_metadata",
    "semantic_context",
    "table_cell",
    "table_schema",
    "artifact_summary",
    "memory_artifact",
    "memory_strategy",
    "citation",
}
REGISTERED_REUSE_INTENTS = {"none", "assist", "artifact", "strategy"}
_FORBIDDEN_KEY_PARTS = (
    "answer",
    "candidate",
    "code",
    "dag",
    "depend",
    "expected",
    "lease",
    "oracle",
    "route",
    "step",
    "tool",
)
_FORBIDDEN_VALUE_MARKERS = (
    "expected_facts",
    "expected_route",
    "expected_tool",
    "oracle_answer",
    "candidate_key",
    "::",
    "table_retriever",
    "semantic_retriever",
    "lexical_retriever",
)
_CASE_ID_PATTERN = re.compile(
    r"\b(?:formal|genericity|benchmark-sample|smoke-task)-[a-z0-9_-]+\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticPlanResolution:
    model_plan: dict[str, Any]
    fallback_plan: dict[str, Any]
    effective_plan: dict[str, Any]
    field_provenance: dict[str, str]
    objective_source: str
    model_generated_field_count: int
    fallback_field_count: int
    semantic_plan_valid: bool
    semantic_equivalence: bool
    validation_errors: tuple[str, ...]
    consumption_mode: str

    @property
    def model_plan_hash(self) -> str:
        return sha256_digest(self.model_plan) if self.model_plan else ""

    @property
    def fallback_plan_hash(self) -> str:
        return sha256_digest(self.fallback_plan)

    @property
    def effective_plan_hash(self) -> str:
        return sha256_digest(self.effective_plan)

    @property
    def behavioral_effect(self) -> bool:
        return (
            self.semantic_plan_valid
            and self.consumption_mode != "disabled"
            and self.model_generated_field_count > 0
            and self.effective_plan_hash != self.fallback_plan_hash
        )

    def audit_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SEMANTIC_TASK_PLAN_SCHEMA_VERSION,
            "objective_source": self.objective_source,
            "consumption_mode": self.consumption_mode,
            "semantic_plan_valid": self.semantic_plan_valid,
            "semantic_equivalence": self.semantic_equivalence,
            "validation_errors": list(self.validation_errors),
            "model_generated_field_count": self.model_generated_field_count,
            "fallback_field_count": self.fallback_field_count,
            "model_plan_hash": self.model_plan_hash,
            "fallback_plan_hash": self.fallback_plan_hash,
            "effective_plan_hash": self.effective_plan_hash,
            "behavioral_effect_before_consumption": self.behavioral_effect,
            "field_provenance": dict(sorted(self.field_provenance.items())),
            "model_plan": self.model_plan,
            "fallback_plan": self.fallback_plan,
            "effective_plan": self.effective_plan,
        }


@dataclass(frozen=True)
class SemanticPlanComparison:
    equivalent: bool
    required_outputs_equal: bool
    goal_present: bool
    goal_token_overlap: float
    entities_compatible: bool
    time_scope_compatible: bool
    retrieval_objective_overlap: float
    evidence_capability_overlap: float

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "equivalent": self.equivalent,
            "required_outputs_equal": self.required_outputs_equal,
            "goal_present": self.goal_present,
            "goal_token_overlap": self.goal_token_overlap,
            "entities_compatible": self.entities_compatible,
            "time_scope_compatible": self.time_scope_compatible,
            "retrieval_objective_overlap": self.retrieval_objective_overlap,
            "evidence_capability_overlap": self.evidence_capability_overlap,
            "comparison_contract": "statebus.semantic_plan_comparison.v1",
            "claim_boundary": (
                "bounded_contract_equivalence_not_free_text_intent_compilation"
            ),
        }


def compare_semantic_task_plans(
    left: dict[str, Any],
    right: dict[str, Any],
) -> SemanticPlanComparison:
    """Compare bounded plan meaning while ignoring harmless wording drift."""
    left_semantics = _mapping(left.get("task_semantics"))
    right_semantics = _mapping(right.get("task_semantics"))
    left_goal = str(left_semantics.get("goal", "")).strip()
    right_goal = str(right_semantics.get("goal", "")).strip()
    goal_present = bool(left_goal and right_goal)
    goal_overlap = _set_overlap(_semantic_tokens(left_goal), _semantic_tokens(right_goal))

    left_entities = _normalized_values(left_semantics.get("entities"))
    right_entities = _normalized_values(right_semantics.get("entities"))
    entities_compatible = (
        not left_entities
        or not right_entities
        or bool(left_entities & right_entities)
    )
    left_time = _normalized_scalar(left_semantics.get("time_scope"))
    right_time = _normalized_scalar(right_semantics.get("time_scope"))
    time_scope_compatible = not left_time or not right_time or left_time == right_time

    left_objectives = _mapping(left.get("retrieval_objectives"))
    right_objectives = _mapping(right.get("retrieval_objectives"))
    objective_overlap = _set_overlap(set(left_objectives), set(right_objectives))
    evidence_overlap = _set_overlap(
        _evidence_capabilities(left),
        _evidence_capabilities(right),
    )
    left_outputs = _normalized_values(left.get("required_outputs"))
    right_outputs = _normalized_values(right.get("required_outputs"))
    outputs_equal = bool(left_outputs) and left_outputs == right_outputs

    equivalent = (
        outputs_equal
        and goal_present
        and entities_compatible
        and time_scope_compatible
        and objective_overlap >= 0.5
        and evidence_overlap > 0.0
    )
    return SemanticPlanComparison(
        equivalent=equivalent,
        required_outputs_equal=outputs_equal,
        goal_present=goal_present,
        goal_token_overlap=goal_overlap,
        entities_compatible=entities_compatible,
        time_scope_compatible=time_scope_compatible,
        retrieval_objective_overlap=objective_overlap,
        evidence_capability_overlap=evidence_overlap,
    )


def planner_semantic_plan_response_schema(
    *,
    allowed_required_outputs: tuple[str, ...] = (),
) -> dict[str, Any]:
    # Keep the engine-side contract flat. Some vLLM/xgrammar versions spend
    # minutes compiling the equivalent deeply nested schema. Runtime converts
    # this fixed-key wire shape into the canonical nested plan and performs the
    # full fail-closed semantic validation.
    del allowed_required_outputs
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "semantic_task_plan": {
                "type": "object",
                "additionalProperties": True,
            }
        },
        "required": ["semantic_task_plan"],
    }


def build_runtime_semantic_plan(
    *,
    spec: CanonicalTaskSpec,
    goal: str,
    query_text: str,
) -> dict[str, Any]:
    arguments = dict(spec.arguments or {})
    entities = list(spec.target_entities)
    for key in ("ticker", "dataset_id", "service_name", "metric"):
        value = str(arguments.get(key, "")).strip()
        if value:
            entities.append(value)
    for key in ("tickers", "quarters"):
        values = arguments.get(key, [])
        if isinstance(values, (list, tuple)):
            entities.extend(str(item).strip() for item in values if str(item).strip())
    entities = list(dict.fromkeys(entities))[:12]
    time_scope = str(spec.time_scope or arguments.get("quarter", "")).strip()
    if not time_scope:
        time_scope = " ".join(
            part
            for part in (
                str(arguments.get("period_from", "")).strip(),
                str(arguments.get("period_to", "")).strip(),
            )
            if part
        )
    anchors = " ".join(
        part
        for part in (
            query_text.strip(),
            spec.intent_op.strip(),
            " ".join(entities),
            time_scope,
        )
        if part
    ).strip()
    table_query = " ".join(
        part
        for part in (
            spec.intent_op,
            str(arguments.get("metric", arguments.get("column", ""))).strip(),
            " ".join(entities),
            time_scope,
        )
        if part
    ).strip() or anchors
    return {
        "schema_version": SEMANTIC_TASK_PLAN_SCHEMA_VERSION,
        "task_semantics": {
            "goal": goal.strip() or query_text.strip(),
            "entities": entities,
            "time_scope": time_scope,
        },
        "retrieval_objectives": {
            "lexical_metadata": {
                "query_text": " ".join(part for part in (" ".join(entities), time_scope) if part).strip() or anchors,
                "objective": "locate the relevant corpus metadata and document scope",
                "evidence_types": ["lexical_metadata"],
            },
            "semantic_chunk": {
                "query_text": anchors,
                "objective": "retrieve explanatory text and citation-bearing context for the requested analysis",
                "evidence_types": ["semantic_context", "citation"],
            },
            "table_structure": {
                "query_text": table_query,
                "objective": "retrieve the table cells and schema needed for the requested computation",
                "evidence_types": ["table_cell", "table_schema"],
            },
            "memory": {
                "query_text": anchors,
                "objective": "find compatible prior artifacts or strategies without bypassing the replay gate",
                "evidence_types": ["memory_artifact", "memory_strategy"],
                "reuse_intent": "assist",
            },
        },
        "required_evidence": ["table_cell", "semantic_context", "citation"],
        "required_outputs": list(spec.required_outputs),
    }


def resolve_semantic_task_plan(
    *,
    spec: CanonicalTaskSpec,
    goal: str,
    fallback_query_text: str,
    model_payload: dict[str, Any] | None,
    consumption_mode: str | None = None,
) -> SemanticPlanResolution:
    fallback = build_runtime_semantic_plan(
        spec=spec,
        goal=goal,
        query_text=fallback_query_text,
    )
    normalized_model, errors = _normalize_and_validate_model_plan(
        model_payload or {},
        allowed_required_outputs=spec.required_outputs,
    )
    mode = (consumption_mode or os.getenv("STATEBUS_PLANNER_CONSUMPTION_MODE", "effective")).strip().lower()
    if mode not in {"effective", "disabled", "perturbed"}:
        mode = "effective"
    valid = bool(normalized_model) and not errors
    semantic_equivalence = valid and _semantically_compatible(
        normalized_model,
        allowed_required_outputs=spec.required_outputs,
    )
    if valid and not semantic_equivalence:
        errors.append("semantic_plan_not_compatible_with_runtime_output_contract")
        valid = False
    if mode == "disabled" or not valid:
        effective = fallback
        provenance = {
            path: "runtime_fallback" for path in _leaf_paths(fallback)
        }
        source = "runtime_fallback"
    else:
        model_for_merge = _perturb_model_plan(normalized_model) if mode == "perturbed" else normalized_model
        effective, provenance = _merge_model_with_fallback(model_for_merge, fallback)
        source = "hybrid" if any(value != "runtime_fallback" for value in provenance.values()) else "runtime_fallback"
    return SemanticPlanResolution(
        model_plan=normalized_model,
        fallback_plan=fallback,
        effective_plan=effective,
        field_provenance=provenance,
        objective_source=source,
        model_generated_field_count=_leaf_count(normalized_model) if valid else 0,
        fallback_field_count=sum(1 for source_name in provenance.values() if source_name != "model_generated"),
        semantic_plan_valid=valid,
        semantic_equivalence=semantic_equivalence,
        validation_errors=tuple(errors),
        consumption_mode=mode,
    )


def _normalize_and_validate_model_plan(
    payload: dict[str, Any],
    *,
    allowed_required_outputs: tuple[str, ...],
) -> tuple[dict[str, Any], list[str]]:
    candidate = payload.get("semantic_task_plan")
    if not isinstance(candidate, dict) and "retrieval_objectives" in payload:
        candidate = payload
    if not isinstance(candidate, dict):
        legacy = payload.get("retrieval_objective")
        if isinstance(legacy, dict) and str(legacy.get("query_text", "")).strip():
            query = str(legacy["query_text"]).strip()
            candidate = {
                "task_semantics": {"goal": query, "entities": [], "time_scope": ""},
                "retrieval_objectives": {
                    "semantic_chunk": {
                        "query_text": query,
                        "objective": "retrieve context relevant to the request",
                        "evidence_types": ["semantic_context"],
                    }
                },
                "required_evidence": ["semantic_context"],
                "required_outputs": [],
            }
    if not isinstance(candidate, dict):
        return {}, ["semantic_task_plan_missing"]
    errors: list[str] = []
    _scan_forbidden(candidate, errors=errors, path="semantic_task_plan")
    if "retrieval_objectives" not in candidate and _looks_like_flat_wire_plan(candidate):
        candidate = _canonical_plan_from_flat_wire(candidate)
    semantics_raw = candidate.get("task_semantics", {})
    semantics = semantics_raw if isinstance(semantics_raw, dict) else {}
    normalized_semantics = {
        "goal": _bounded_text(semantics.get("goal"), 384),
        "entities": _bounded_text_list(semantics.get("entities"), max_items=12, max_length=96),
        "time_scope": _bounded_text(semantics.get("time_scope"), 128),
    }
    objectives_raw = candidate.get("retrieval_objectives", {})
    if not isinstance(objectives_raw, dict):
        objectives_raw = {}
        errors.append("retrieval_objectives_must_be_object")
    unknown_objectives = sorted(set(objectives_raw) - set(REGISTERED_RETRIEVAL_OBJECTIVES))
    if unknown_objectives:
        errors.append(f"unregistered_retrieval_objective:{','.join(unknown_objectives)}")
    objectives: dict[str, dict[str, Any]] = {}
    for name in REGISTERED_RETRIEVAL_OBJECTIVES:
        raw = objectives_raw.get(name)
        if not isinstance(raw, dict):
            continue
        query_text = _bounded_text(raw.get("query_text", raw.get("query")), 512)
        objective = _bounded_text(raw.get("objective"), 256)
        evidence_types = _bounded_text_list(raw.get("evidence_types"), max_items=6, max_length=64)
        invalid_evidence = sorted(set(evidence_types) - REGISTERED_EVIDENCE_TYPES)
        if invalid_evidence:
            errors.append(f"unregistered_evidence_type:{name}:{','.join(invalid_evidence)}")
        normalized: dict[str, Any] = {
            "query_text": query_text,
            "objective": objective,
            "evidence_types": [item for item in evidence_types if item in REGISTERED_EVIDENCE_TYPES],
        }
        if name == "memory":
            reuse_intent = _bounded_text(raw.get("reuse_intent"), 32).lower() or "assist"
            if reuse_intent not in REGISTERED_REUSE_INTENTS:
                errors.append(f"unregistered_reuse_intent:{reuse_intent}")
                reuse_intent = "assist"
            normalized["reuse_intent"] = reuse_intent
        if query_text:
            objectives[name] = normalized
    if not objectives:
        errors.append("retrieval_objective_query_missing")
    required_evidence = _bounded_text_list(candidate.get("required_evidence"), max_items=8, max_length=64)
    invalid_required_evidence = sorted(set(required_evidence) - REGISTERED_EVIDENCE_TYPES)
    if invalid_required_evidence:
        errors.append(f"unregistered_required_evidence:{','.join(invalid_required_evidence)}")
    required_outputs = _bounded_text_list(candidate.get("required_outputs"), max_items=12, max_length=96)
    invalid_outputs = sorted(set(required_outputs) - set(allowed_required_outputs))
    if invalid_outputs:
        errors.append(f"unregistered_required_output:{','.join(invalid_outputs)}")
    normalized_plan = {
        "schema_version": SEMANTIC_TASK_PLAN_SCHEMA_VERSION,
        "task_semantics": normalized_semantics,
        "retrieval_objectives": objectives,
        "required_evidence": [item for item in required_evidence if item in REGISTERED_EVIDENCE_TYPES],
        "required_outputs": [item for item in required_outputs if item in set(allowed_required_outputs)],
    }
    return normalized_plan, errors


def _canonical_plan_from_flat_wire(payload: dict[str, Any]) -> dict[str, Any]:
    def wire_value(key: str, default: Any = "") -> Any:
        direct = payload.get(key)
        if direct not in (None, "", [], {}):
            return direct
        for value in payload.values():
            if isinstance(value, dict):
                nested = value.get(key)
                if nested not in (None, "", [], {}):
                    return nested
        return default

    evidence_by_objective = {
        "lexical_metadata": ["lexical_metadata"],
        "semantic_chunk": ["semantic_context", "citation"],
        "table_structure": ["table_cell", "table_schema"],
        "memory": ["memory_artifact", "memory_strategy"],
    }
    objectives: dict[str, dict[str, Any]] = {}
    for name, prefix in (
        ("lexical_metadata", "lexical"),
        ("semantic_chunk", "semantic"),
        ("table_structure", "table"),
        ("memory", "memory"),
    ):
        objective = {
            "query_text": wire_value(f"{prefix}_query"),
            "objective": wire_value(f"{prefix}_objective"),
            "evidence_types": evidence_by_objective[name],
        }
        if name == "memory":
            objective["reuse_intent"] = wire_value("memory_reuse_intent", "assist")
        objectives[name] = objective
    return {
        "task_semantics": {
            "goal": wire_value("goal"),
            "entities": (
                wire_value("entities", [])
                if isinstance(wire_value("entities", []), (list, tuple))
                else []
            ),
            "time_scope": wire_value("time_scope"),
        },
        "retrieval_objectives": objectives,
        "required_evidence": wire_value("required_evidence", []),
        "required_outputs": wire_value("required_outputs", []),
    }


def _looks_like_flat_wire_plan(payload: dict[str, Any]) -> bool:
    wire_keys = {
        "lexical_query",
        "lexical_objective",
        "semantic_query",
        "semantic_objective",
        "table_query",
        "table_objective",
        "memory_query",
        "memory_objective",
    }
    if wire_keys & set(payload):
        return True
    return any(
        bool(wire_keys & set(value))
        for value in payload.values()
        if isinstance(value, dict)
    )


def _merge_model_with_fallback(
    model: dict[str, Any],
    fallback: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    effective = {
        "schema_version": SEMANTIC_TASK_PLAN_SCHEMA_VERSION,
        "task_semantics": dict(fallback["task_semantics"]),
        "retrieval_objectives": {},
        "required_evidence": list(fallback["required_evidence"]),
        "required_outputs": list(fallback["required_outputs"]),
    }
    provenance: dict[str, str] = {
        path: "runtime_fallback" for path in _leaf_paths(effective)
    }
    model_semantics = model.get("task_semantics", {})
    if isinstance(model_semantics, dict):
        for key in ("goal", "entities", "time_scope"):
            value = model_semantics.get(key)
            if value not in (None, "", []):
                effective["task_semantics"][key] = value
                provenance[f"task_semantics.{key}"] = "model_generated"
    model_objectives = model.get("retrieval_objectives", {})
    fallback_objectives = fallback["retrieval_objectives"]
    for name in REGISTERED_RETRIEVAL_OBJECTIVES:
        fallback_objective = dict(fallback_objectives[name])
        model_objective = model_objectives.get(name, {}) if isinstance(model_objectives, dict) else {}
        if not isinstance(model_objective, dict) or not str(model_objective.get("query_text", "")).strip():
            effective["retrieval_objectives"][name] = fallback_objective
            continue
        merged = dict(fallback_objective)
        model_query = str(model_objective["query_text"]).strip()
        fallback_query = str(fallback_objective.get("query_text", "")).strip()
        merged["query_text"] = _hybrid_query(model_query, fallback_query)
        provenance[f"retrieval_objectives.{name}.query_text"] = "hybrid"
        for key in ("objective", "reuse_intent"):
            value = model_objective.get(key)
            if value not in (None, ""):
                merged[key] = value
                provenance[f"retrieval_objectives.{name}.{key}"] = "model_generated"
        model_evidence = model_objective.get("evidence_types", [])
        merged["evidence_types"] = list(
            dict.fromkeys([*model_evidence, *fallback_objective.get("evidence_types", [])])
        )
        provenance[f"retrieval_objectives.{name}.evidence_types"] = "hybrid"
        effective["retrieval_objectives"][name] = merged
    model_required_evidence = model.get("required_evidence", [])
    if model_required_evidence:
        effective["required_evidence"] = list(
            dict.fromkeys([*model_required_evidence, *fallback["required_evidence"]])
        )
        provenance["required_evidence"] = "hybrid"
    model_required_outputs = model.get("required_outputs", [])
    if model_required_outputs:
        effective["required_outputs"] = list(
            dict.fromkeys([*model_required_outputs, *fallback["required_outputs"]])
        )
        provenance["required_outputs"] = "hybrid"
    for path in _leaf_paths(effective):
        provenance.setdefault(path, "runtime_fallback")
    return effective, provenance


def _semantically_compatible(
    plan: dict[str, Any],
    *,
    allowed_required_outputs: tuple[str, ...],
) -> bool:
    outputs = plan.get("required_outputs", [])
    return isinstance(outputs, list) and set(outputs).issubset(set(allowed_required_outputs))


def _scan_forbidden(value: Any, *, errors: list[str], path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
                errors.append(f"forbidden_field:{path}.{key}")
            _scan_forbidden(child, errors=errors, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_forbidden(child, errors=errors, path=f"{path}[{index}]")
    elif isinstance(value, str):
        normalized_value = value.lower()
        for marker in _FORBIDDEN_VALUE_MARKERS:
            if marker in normalized_value:
                errors.append(f"forbidden_value:{path}:{marker}")
        if _CASE_ID_PATTERN.search(value):
            errors.append(f"forbidden_case_id:{path}")


def _bounded_text(value: Any, max_length: int) -> str:
    return " ".join(str(value or "").split())[:max_length]


def _bounded_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(
        dict.fromkeys(
            item
            for item in (_bounded_text(raw, max_length) for raw in value[:max_items])
            if item
        )
    )


def _hybrid_query(model_query: str, fallback_query: str) -> str:
    if model_query.casefold() == fallback_query.casefold():
        return fallback_query
    return f"{model_query} | runtime anchors: {fallback_query}"[:1024]


def _perturb_model_plan(model: dict[str, Any]) -> dict[str, Any]:
    perturbed = {
        **model,
        "task_semantics": dict(model.get("task_semantics", {})),
        "retrieval_objectives": {
            key: dict(value)
            for key, value in dict(model.get("retrieval_objectives", {})).items()
            if isinstance(value, dict)
        },
    }
    for objective in perturbed["retrieval_objectives"].values():
        query = str(objective.get("query_text", "")).strip()
        if query:
            objective["query_text"] = f"unrelated archival scheduling metadata {query}"
    return perturbed


def _leaf_count(value: Any) -> int:
    return len(_leaf_paths(value))


def _leaf_paths(value: Any, prefix: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "schema_version":
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, (dict, list, tuple)):
                child_paths = _leaf_paths(child, path)
                paths.extend(child_paths or (path,))
            else:
                paths.append(path)
    elif isinstance(value, (list, tuple)):
        if value:
            paths.append(prefix)
    elif prefix:
        paths.append(prefix)
    return tuple(dict.fromkeys(paths))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized_scalar(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _normalized_values(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {
        normalized
        for item in value
        if (normalized := _normalized_scalar(item))
    }


def _semantic_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", value.casefold()))


def _set_overlap(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _evidence_capabilities(plan: dict[str, Any]) -> set[str]:
    evidence = _normalized_values(plan.get("required_evidence"))
    for objective in _mapping(plan.get("retrieval_objectives")).values():
        if isinstance(objective, dict):
            evidence.update(_normalized_values(objective.get("evidence_types")))
    return evidence
