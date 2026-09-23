"""Bounded Stage 2 measurement runner.

The runner records measurement facts and projects existing Runtime results. It
does not create Runtime authority, provider receipts, retries, or terminal
semantics. A dry-run is explicitly offline validation and never produces live
provider evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import json
import multiprocessing
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.request import urlopen

from statebus.benchmark.adaptive_formal import (
    adapt_formal_sample,
    formal_output_contract,
    recompute_formal_rows,
)
from statebus.benchmark.adaptive_formal_mainline import _run_adaptive_case
from statebus.benchmark.external_text_baseline import (
    _load_execution_context,
    _requested_metric_name,
    run_external_text_case,
)
from statebus.benchmark.external_public_tools import execute_public_task, supports_public_task
from statebus.benchmark.formal_registry_adapter import load_c2b_formal_fixed_answer_samples
from statebus.benchmark.minimal_runner import _c2b_structured_runtime
from statebus.benchmark.stage2_contract import (
    ACCOUNTING_CLASSES,
    LANES,
    TERMINAL_CLASSES,
    SlotIdentity,
    canonical_output_projection,
    compare_slot_sets,
    public_case_projection,
    validate_public_case,
)
from statebus.benchmark.task_registry import load_c2b_positive_samples
from statebus.integrations.llm import ChatMessage, LLMConfig, build_llm_client, extract_json_object
from statebus.runtime.codeact_sandbox import CodeActSandboxRunner
from statebus.utils import sha256_digest, stable_json_dumps


SEEDS = (0, 1)
FAMILY_ORDER = (
    "financial_report_analysis_v1",
    "multi_period_trend_analysis_v1",
    "cross_table_join_analysis_v1",
    "conditional_aggregation_v1",
    "anomaly_detection_v1",
)
PILOT_FIRST_CASE = {
    "financial_report_analysis_v1": "benchmark-sample-9",
    "multi_period_trend_analysis_v1": "formal-trend-006",
}
# The fixed four-role bridge gives each provider call its configured timeout
# plus a settlement allowance.  With the current 180-second provider profile,
# the sequential worst case is 740 seconds before process startup/teardown
# overhead.  Keep the Stage 2 fence above that bound so a valid Runtime
# settlement is not mistaken for a client-side deadline failure.
DEFAULT_TIMEOUT_S = 900.0
EXIT_READY = 0
EXIT_PREFLIGHT_INVALID = 2
EXIT_INCONCLUSIVE = 3
EXIT_INTERRUPTED = 130
FIXED_AGGREGATE_EXCLUSION_REASON = "deterministic_canonical_runtime_no_live_provider"


def _json(path: Path, payload: object) -> None:
    """Atomically publish one completed JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}")
    temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def _runtime_profile_snapshot(embedding_device: str, config: LLMConfig | None = None) -> dict[str, object]:
    """Capture the effective profile without replacing missing values by guesses."""

    active = config or LLMConfig.from_runtime()
    provider = active.provider_config("default")
    roles: dict[str, object] = {}
    for role in ("planner", "retriever", "executor", "summarizer"):
        role_config = active.role_config(role)
        roles[role] = {
            "provider": role_config.provider,
            "provider_timeout_s": active.provider_config(role_config.provider).timeout_s,
            "model": role_config.model,
            "json_output": role_config.json_output,
            "temperature": role_config.temperature,
            "max_tokens": role_config.max_tokens,
            "max_context_tokens": role_config.max_context_tokens,
            "reasoning_effort": role_config.reasoning_effort,
            "extra_body": dict(role_config.extra_body),
            "request_kwargs": dict(role_config.request_kwargs),
        }
    model = str(os.getenv("STATEBUS_LOCAL_VLLM_MODEL") or roles["planner"]["model"])
    return {
        "config_source": active.source,
        "mode": active.mode,
        "vllm_url": str(provider.base_url or "").rstrip("/"),
        "model": model,
        "model_path": os.getenv("STATEBUS_VLLM_MODEL_PATH", ""),
        "service_physical_gpu": os.getenv("STATEBUS_G6B2_SERVICE_PHYSICAL_GPU", ""),
        "max_model_len": os.getenv("STATEBUS_VLLM_MAX_MODEL_LEN", ""),
        "embedding_model": os.getenv(
            "STATEBUS_G6B2_EMBEDDING_MODEL_PATH",
            os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"),
        ),
        "embedding_physical_gpu": os.getenv(
            "STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU",
            os.getenv("STATEBUS_EMBED_PHYSICAL_GPU", ""),
        ),
        "embedding_container_device": embedding_device,
        "profile_id": os.getenv("STATEBUS_G6B2_PROFILE_ID", "unconfigured-profile"),
        "container_name": os.getenv("STATEBUS_CONTAINER_NAME", "statebus-runtime"),
        "request_max_attempts": provider.request_max_attempts,
        "roles": roles,
    }


def _stage2_timeout_contract(
    config: LLMConfig,
    *,
    stage2_timeout_s: float,
) -> dict[str, object]:
    """Describe and validate the outer fence against role provider budgets."""

    role_timeout_s = {
        role: float(
            config.provider_config(config.role_config(role).provider).timeout_s
        )
        for role in ("planner", "retriever", "executor", "summarizer")
    }
    settlement_allowance_s = 5.0
    process_overhead_s = 20.0
    worst_case_role_budget_s = sum(
        timeout + settlement_allowance_s for timeout in role_timeout_s.values()
    )
    required_timeout_s = worst_case_role_budget_s + process_overhead_s
    return {
        "schema_version": "statebus.stage2_timeout_contract.v1",
        "provider_timeout_s_by_role": role_timeout_s,
        "settlement_allowance_s": settlement_allowance_s,
        "process_overhead_s": process_overhead_s,
        "worst_case_sequential_role_budget_s": worst_case_role_budget_s,
        "required_stage2_timeout_s": required_timeout_s,
        "configured_stage2_timeout_s": float(stage2_timeout_s),
        "passed": float(stage2_timeout_s) >= required_timeout_s,
    }


def _seeded_local_config(seed: int) -> LLMConfig:
    """Pass the requested seed to every live role request when supported."""

    config = LLMConfig.from_runtime().with_mode("local_vllm")
    config = config.with_provider_override("default", request_max_attempts=1)
    for role in ("planner", "retriever", "executor", "summarizer"):
        role_config = config.role_config(role)
        request_kwargs = dict(role_config.request_kwargs)
        request_kwargs["seed"] = int(seed)
        config = config.with_role_override(role, request_kwargs=request_kwargs)
    return config


def _sample_maps() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {sample.task_id: sample for sample in load_c2b_positive_samples()},
        {sample.task_id: sample for sample in load_c2b_formal_fixed_answer_samples()},
    )


def _select_samples() -> list[tuple[str, Any, Any]]:
    minimal, fixed = _sample_maps()
    selected: list[tuple[str, Any, Any]] = []
    family_alias = {"financial_report_analysis": "financial_report_analysis_v1"}
    preferred_keys: list[tuple[str, str]] = []
    for family_id in FAMILY_ORDER:
        case_ids = sorted(
            case_id
            for case_id, sample in minimal.items()
            if family_alias.get(str(sample.task_family), str(sample.task_family)) == family_id
            and case_id in fixed
        )
        if not case_ids:
            raise ValueError(f"stage2_family_not_registered:{family_id}")
        preferred = PILOT_FIRST_CASE.get(family_id)
        if preferred in case_ids:
            preferred_keys.append((family_id, preferred))
        for case_id in case_ids:
            # A case-specific key keeps the five-family registry injective when
            # the same family contributes multiple independent cases.
            selected.append((f"{family_id}::{case_id}", minimal[case_id], fixed[case_id]))
    if len(selected) != 48:
        raise ValueError(f"stage2_c2b_registry_incomplete:{len(selected)}")
    # Keep the two historical pilot anchors at stable positions for callers
    # that use the first financial and trend samples as smoke contracts.  The
    # remaining registry stays in the family/case order above.
    ordered: list[tuple[str, Any, Any]] = []
    preferred_key_set = set(preferred_keys)
    for family_id, case_id in preferred_keys:
        row = next(
            row
            for row in selected
            if row[0] == f"{family_id}::{case_id}"
        )
        ordered.append(row)
    ordered.extend(
        row
        for row in selected
        if (row[0].split("::", 1)[0], row[1].task_id) not in preferred_key_set
    )
    return ordered


def _filter_selected_samples(
    selected: list[tuple[str, Any, Any]],
    *,
    case_ids: tuple[str, ...] = (),
    family_ids: tuple[str, ...] = (),
    max_cases_per_family: int = 0,
) -> list[tuple[str, Any, Any]]:
    """Apply an explicit bounded-selection contract to the frozen registry."""

    if max_cases_per_family < 0:
        raise ValueError("max_cases_per_family_must_be_non_negative")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("duplicate_case_id_selection")
    if len(set(family_ids)) != len(family_ids):
        raise ValueError("duplicate_family_id_selection")
    if case_ids and family_ids:
        raise ValueError("case_id_and_family_id_selection_are_mutually_exclusive")

    available_case_ids = {str(minimal.task_id) for _family, minimal, _fixed in selected}
    available_family_ids = {family.split("::", 1)[0] for family, _minimal, _fixed in selected}
    missing_cases = sorted(set(case_ids) - available_case_ids)
    missing_families = sorted(set(family_ids) - available_family_ids)
    if missing_cases:
        raise ValueError(f"stage2_case_not_registered:{','.join(missing_cases)}")
    if missing_families:
        raise ValueError(f"stage2_family_not_registered:{','.join(missing_families)}")

    filtered = list(selected)
    if case_ids:
        requested = set(case_ids)
        filtered = [row for row in filtered if str(row[1].task_id) in requested]
    elif family_ids:
        requested = set(family_ids)
        filtered = [row for row in filtered if row[0].split("::", 1)[0] in requested]

    if max_cases_per_family:
        counts: dict[str, int] = {}
        limited: list[tuple[str, Any, Any]] = []
        for row in filtered:
            family_id = row[0].split("::", 1)[0]
            if counts.get(family_id, 0) >= max_cases_per_family:
                continue
            counts[family_id] = counts.get(family_id, 0) + 1
            limited.append(row)
        filtered = limited

    if not filtered:
        raise ValueError("stage2_selection_empty")
    return filtered


def _filter_selected_lanes(lane_ids: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Validate an optional lane selection while preserving canonical order."""

    if len(set(lane_ids)) != len(lane_ids):
        raise ValueError("duplicate_lane_selection")
    unknown = sorted(set(lane_ids) - set(LANES))
    if unknown:
        raise ValueError(f"stage2_lane_not_registered:{','.join(unknown)}")
    if not lane_ids:
        return LANES
    requested = set(lane_ids)
    return tuple(lane for lane in LANES if lane in requested)


def _load_slot_manifest(
    path: Path,
    registry: list[tuple[str, Any, Any]],
) -> list[dict[str, object]]:
    """Load exact repair slots against the canonical Stage 2 registry."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"stage2_slot_manifest_invalid:{path}:{type(exc).__name__}:{exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("stage2_slot_manifest_not_object")
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != "statebus.p1_missing_slots.v1":
        raise ValueError(f"stage2_slot_manifest_schema_unsupported:{schema_version}")
    raw_slots = payload.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("stage2_slot_manifest_slots_empty")

    registry_by_case: dict[str, tuple[str, Any, Any]] = {}
    for family_key, minimal, fixed in registry:
        case_id = str(minimal.task_id)
        if case_id in registry_by_case:
            raise ValueError(f"stage2_case_registry_duplicate:{case_id}")
        registry_by_case[case_id] = (family_key, minimal, fixed)

    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, int, int]] = set()
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, Mapping):
            raise ValueError(f"stage2_slot_manifest_entry_not_object:{index}")
        family_id = str(raw.get("family_id", "")).strip()
        case_id = str(raw.get("case_id", "")).strip()
        lane = str(raw.get("lane", "")).strip()
        try:
            repeat = int(raw.get("repeat"))
            seed = int(raw.get("seed"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stage2_slot_manifest_identity_invalid:{index}") from exc
        if lane not in LANES:
            raise ValueError(f"stage2_lane_not_registered:{lane}")
        if repeat < 1:
            raise ValueError(f"stage2_slot_manifest_repeat_invalid:{index}")
        registry_entry = registry_by_case.get(case_id)
        if registry_entry is None:
            raise ValueError(f"stage2_case_not_registered:{case_id}")
        family_key, _minimal, _fixed = registry_entry
        canonical_family = family_key.split("::", 1)[0]
        if family_id != canonical_family:
            raise ValueError(
                f"stage2_slot_manifest_family_mismatch:{case_id}:{family_id}:{canonical_family}"
            )
        identity_key = (family_id, case_id, lane, repeat, seed)
        if identity_key in seen:
            raise ValueError(
                "stage2_slot_manifest_duplicate:"
                + ":".join((family_id, case_id, lane, str(repeat), str(seed)))
            )
        seen.add(identity_key)
        normalized.append(
            {
                "family_id": family_id,
                "family_key": family_key,
                "case_id": case_id,
                "lane": lane,
                "repeat": repeat,
                "seed": seed,
            }
        )
    return normalized


def _stage2_public_case(sample: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Freeze the public prompt surface and its concrete source-id closure."""

    case = public_case_projection(sample)
    context = _load_execution_context(sample)
    closure = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in context.public_doc_hashes
            if str(item).strip()
        )
    )
    if not closure:
        raise ValueError(f"stage2_public_source_closure_empty:{sample.task_id}")
    case["public_sources"] = list(closure)
    return case, closure


def _quality(
    sample: Any,
    payload: Mapping[str, object],
    output_path: Path,
    *,
    offline: bool = False,
) -> dict[str, object]:
    from statebus.benchmark.scoring import score_benchmark_output

    checks = tuple(str(item) for item in sample.canonical_task_spec.arguments.get("quality_checks", ()))
    expected_facts = dict(sample.expected_facts or {})
    # Source identity belongs to the audit projection, not the business-quality
    # numerator. Runtime input authority and artifact verification remain hard
    # gates; a benchmark-facing alias/hash mismatch must not turn a correct
    # execution into a Runtime failure.
    expected_facts.pop("selected_doc_hashes", None)
    # Score the canonical output projection, not the pre-projection payload.
    # Provenance fields intentionally live below ``provenance`` in Stage 2,
    # while older registry fixtures may still carry a ``revenue_value`` alias
    # for a non-revenue metric.  Both mappings use only observed output data;
    # they never copy expected values into the result.
    scoring_payload = dict(payload)
    metric_name = str(
        expected_facts.get("metric_name", scoring_payload.get("metric_name", ""))
    ).strip()
    if metric_name and metric_name != "revenue":
        expected_facts.pop("revenue_value", None)
    return score_benchmark_output(
        output_payload=scoring_payload,
        output_path=output_path,
        expected_facts=expected_facts,
        quality_checks=checks,
    ).canonical_payload()


def _usage_payload(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {"status": "missing", "prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    if prompt_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
        return {"status": "missing", "prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {
        "status": "observed",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _fairness_gate(public_case: Mapping[str, object], *surfaces: object) -> dict[str, object]:
    errors = list(validate_public_case(public_case))
    forbidden_tokens = ("expected_facts", "quality_checks", "summary_hint", "oracle_answer", "gold", "hidden", "future")
    for surface in surfaces:
        rendered = repr(surface).lower()
        for token in forbidden_tokens:
            if token in rendered:
                errors.append(f"forbidden_surface:{token}")
    failures = sorted(set(errors))
    return {"pass_hard_gate": not failures, "failed_checks": failures, "status": "passed" if not failures else "failed"}


def _complete_with_observation(client: Any, messages: list[ChatMessage], *, purpose: str, response_schema: dict[str, Any]) -> tuple[Any, dict[str, object]]:
    request_id = f"stage2:{purpose}:{time.monotonic_ns()}"
    started_ns = time.monotonic_ns()
    try:
        result = asyncio.run(client.complete(messages, purpose=purpose, response_schema=response_schema))
    except BaseException as exc:
        event = {
            "event": "provider_invocation",
            "request_id": request_id,
            "role": purpose,
            "status": "error",
            "start_ns": started_ns,
            "end_ns": time.monotonic_ns(),
            "retry_kind": "not_applicable",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        request_events = tuple(dict(item) for item in getattr(client, "request_events", ()))
        retry_events = tuple(
            item for item in request_events if str(item.get("retry_kind", "none")) != "none"
        )
        for name, value in (
            ("provider_invocation_events", (event,)),
            ("provider_request_events", request_events),
            ("retry_events", retry_events),
        ):
            try:
                setattr(exc, name, value)
            except Exception:
                pass
        raise
    return result, {
        "event": "provider_invocation",
        "request_id": request_id,
        "role": purpose,
        "status": "response_received",
        "start_ns": started_ns,
        "end_ns": time.monotonic_ns(),
        "retry_kind": "not_applicable",
    }


def _direct_response_schema(
    sample: Any,
    *,
    allowed_doc_ids: tuple[str, ...],
    allow_public_tool_outputs: bool = False,
) -> dict[str, Any]:
    """Build the direct lane schema from the public formal task contract."""

    properties: dict[str, Any] = {
        "route": {"type": "string"},
        "tool_name": {"type": "string"},
        "candidate_key": {"type": "string"},
        "metric_name": {"type": "string"},
        "metric_value": {"type": "string"},
        "summary_text": {"type": "string"},
        "selected_doc_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(allowed_doc_ids)},
        },
    }
    required_outputs = tuple(str(field) for field in sample.canonical_task_spec.required_outputs)
    operation = ""
    if set(required_outputs) - set(properties):
        try:
            operation, output_schema, _shape = formal_output_contract(sample.canonical_task_spec)
        except ValueError:
            # The direct lane must not reject a live request because this
            # benchmark helper does not yet know a task-specific output shape.
            # A public tool can materialize the declared outputs, and the
            # post-call projection/quality gate remains authoritative.
            if not allow_public_tool_outputs:
                raise
            operation, output_schema = "", {}
        for field, kind in output_schema.items():
            if kind not in {"string", "number", "integer", "boolean"}:
                if allow_public_tool_outputs:
                    continue
                raise ValueError(f"direct_output_type_unsupported:{field}:{kind}")
            properties[str(field)] = {"type": str(kind)}

    if operation == "compute_trend":
        for field in required_outputs:
            if field == "trend_values" or field.endswith("_trend_values"):
                properties[field] = {"type": "string"}
            elif field == "trend_direction" or field.endswith("_trend_direction"):
                properties[field] = {
                    "type": "string",
                    "enum": ["increasing", "decreasing", "flat", "mixed"],
                }

    unsupported = sorted(set(required_outputs) - set(properties))
    if unsupported:
        if allow_public_tool_outputs:
            return {
                "type": "object",
                "properties": properties,
                "required": [
                    "route",
                    "tool_name",
                    "candidate_key",
                    "summary_text",
                    "selected_doc_ids",
                ],
                "additionalProperties": False,
            }
        raise ValueError(f"direct_required_output_unsupported:{tuple(unsupported)!r}")
    return {
        "type": "object",
        "properties": properties,
        "required": list(required_outputs),
        "additionalProperties": False,
    }


def _direct_case(sample: Any, root: Path, *, seed: int = 0, public_case: Mapping[str, Any] | None = None) -> dict[str, object]:
    case = dict(public_case or public_case_projection(sample))
    context = _load_execution_context(sample, public_case=case)
    source_closure = tuple(str(item) for item in case.get("public_sources", ()) if str(item).strip())
    source_identity_errors = [] if source_closure == tuple(context.public_doc_hashes) else [
        f"public_source_closure_mismatch:{source_closure!r}:{context.public_doc_hashes!r}"
    ]
    candidates = [candidate.candidate_key() for candidate in context.route_candidates]
    required_outputs = tuple(str(field) for field in sample.canonical_task_spec.required_outputs)
    trend_contract = ""
    if "trend_values" in required_outputs:
        trend_contract = (
            "Return trend_values as comma-separated numeric values in the requested quarter order. "
            "Return trend_direction as increasing when each adjacent value rises, decreasing when each falls, "
            "flat when all are equal, and mixed otherwise. "
        )
    public_tool_managed = False
    try:
        schema = _direct_response_schema(sample, allowed_doc_ids=source_closure)
    except ValueError as exc:
        unsupported_schema_error = str(exc).startswith(
            (
                "direct_output_type_unsupported:",
                "direct_required_output_unsupported:",
                "formal_output_schema_",
            )
        )
        if not context.public_execution_required or not unsupported_schema_error:
            raise
        schema = _direct_response_schema(
            sample,
            allowed_doc_ids=source_closure,
            allow_public_tool_outputs=True,
        )
        public_tool_managed = True
    declared_fields = ", ".join(
        f"{field}:{definition['type']}"
        for field, definition in schema["properties"].items()
    )
    prompt = (
        "You are the direct single-agent lane. Return one JSON object only. Use only the public case and evidence. "
        "Do not include scorer metadata.\nFields: route, tool_name, candidate_key, metric_name, metric_value, "
        f"summary_text and selected_doc_ids plus the case-specific fields declared here: {declared_fields}. "
        "Do not emit undeclared fields.\n"
        + (
            "The registered public tool will calculate the task outputs after your route/tool choice; "
            "do not invent artifact references or derived values. "
            if public_tool_managed
            else ""
        )
        + f"{trend_contract}For selected_doc_ids, use only the exact identifiers in public_sources.\n\n"
        f"Public case: {stable_json_dumps(case)}\nVisible candidates: {', '.join(candidates)}\n"
        f"Requested metric: {_requested_metric_name(sample)}\nPublic evidence:\n{context.public_evidence_text}"
    )
    config = _seeded_local_config(seed)
    client = build_llm_client(config)
    started = time.perf_counter_ns()
    invocation_events: list[dict[str, object]] = []
    try:
        result, invocation_event = _complete_with_observation(
            client,
            [ChatMessage(role="user", content=prompt)],
            purpose="planner",
            response_schema=schema,
        )
        invocation_events.append(invocation_event)
        try:
            payload = extract_json_object(result.text)
        except BaseException as exc:
            invocation_event["status"] = "parse_error"
            invocation_event["error_type"] = type(exc).__name__
            invocation_event["error"] = str(exc)
            raise
    except BaseException as exc:
        observed_invocations = tuple(
            dict(item) for item in getattr(exc, "provider_invocation_events", invocation_events)
        )
        request_events = tuple(dict(item) for item in getattr(client, "request_events", ()))
        retry_events = tuple(
            item for item in request_events if str(item.get("retry_kind", "none")) != "none"
        )
        for name, value in (
            ("provider_invocation_events", observed_invocations),
            ("provider_request_events", request_events),
            ("retry_events", retry_events),
        ):
            try:
                setattr(exc, name, value)
            except Exception:
                pass
        raise
    request_events = list(getattr(client, "request_events", ()))
    retry_events = [item for item in request_events if str(item.get("retry_kind", "none")) != "none"]
    public_tool_outputs: dict[str, object] = {}
    public_tool_execution: dict[str, object] = {
        "required": public_tool_managed,
        "success": not public_tool_managed,
        "execution_kind": "",
        "source_paths": [],
        "artifact_path": "",
        "error": "",
    }
    tool_latency_ms = 0.0
    if public_tool_managed:
        tool_started = time.perf_counter_ns()
        try:
            tool_result = execute_public_task(
                project_root=Path(__file__).resolve().parents[2],
                task_family=sample.canonical_task_spec.task_family,
                intent_op=sample.canonical_task_spec.intent_op,
                arguments=dict(sample.canonical_task_spec.arguments),
            )
            public_tool_outputs = dict(tool_result.outputs)
            tool_artifact_path = root / "direct_public_tool_result.json"
            for required_output in required_outputs:
                if required_output.endswith("_ref"):
                    public_tool_outputs.setdefault(required_output, str(tool_artifact_path))
            _json(
                tool_artifact_path,
                {
                    "task_id": sample.task_id,
                    "execution_kind": tool_result.execution_kind,
                    "source_paths": list(tool_result.source_paths),
                    "outputs": public_tool_outputs,
                },
            )
            public_tool_execution.update(
                {
                    "success": True,
                    "execution_kind": tool_result.execution_kind,
                    "source_paths": list(tool_result.source_paths),
                    "artifact_path": str(tool_artifact_path),
                }
            )
            payload = {**payload, **public_tool_outputs}
        except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
            error = RuntimeError(f"direct_public_tool_failed:{type(exc).__name__}:{exc}")
            error.provider_invocation_events = tuple(invocation_events)
            error.provider_request_events = tuple(request_events)
            error.retry_events = tuple(retry_events)
            raise error from exc
        finally:
            tool_latency_ms = (time.perf_counter_ns() - tool_started) / 1_000_000.0

    output_path = root / "direct_output.json"
    report_path = root / "direct_report.json"
    projected = canonical_output_projection(
        payload,
        selected_doc_ids=payload.get("selected_doc_ids", ()),
        allowed_doc_ids=source_closure,
        required_outputs=sample.canonical_task_spec.required_outputs,
        output_path=str(output_path),
        report_path=str(report_path),
    )
    _json(output_path, projected)
    fairness = _fairness_gate(case, prompt, payload, public_tool_execution)
    _json(
        report_path,
        {
            "schema_version": "statebus.stage2_direct_report.v1",
            "task_id": sample.task_id,
            "requested_seed": seed,
            "effective_seed": None,
            "seed_status": "unsupported_by_client_contract",
            "provider_invocation_events": invocation_events,
            "provider_request_events": request_events,
            "retry_events": retry_events,
            "retry_count": len(retry_events),
            "fairness_gate": fairness,
            "public_tool_outputs": public_tool_outputs,
            "public_tool_execution": public_tool_execution,
            "tool_latency_ms": tool_latency_ms,
            "profile": _runtime_profile_snapshot("cuda:0", config),
        },
    )
    return {
        "payload": projected,
        "provider_latency_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
        "tool_latency_ms": tool_latency_ms,
        "tool_execution": public_tool_execution,
        "provider_usage": _usage_payload(result),
        "requested_seed": seed,
        "effective_seed": None,
        "seed_status": "unsupported_by_client_contract",
        "provider_calls": len(request_events),
        "provider_invocation_status": "response_received",
        "provider_invocation_events": invocation_events,
        "provider_request_events": request_events,
        "retry_events": retry_events,
        "retry_count": len(retry_events),
        "provider_observation_gate": {"passed": bool(request_events), "status": "observed" if request_events else "missing"},
        "schema_gate": {"passed": bool(projected.get("projection_valid")), "projection_errors": projected.get("projection_errors", [])},
        "provenance_diagnostic": {
            "passed": bool(projected.get("provenance_valid", True)) and not source_identity_errors,
            "blocking": False,
            "errors": [*source_identity_errors, *projected.get("provenance_errors", [])],
        },
        "fairness_gate": fairness,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "runtime_root": str(root / "runtime"),
        "workspace_root": str(root / "workspace"),
        "memory_root": str(root / "memory"),
    }


def _pure_case(sample: Any, root: Path, *, seed: int = 0, public_case: Mapping[str, Any] | None = None) -> dict[str, object]:
    case = dict(public_case or public_case_projection(sample))
    context = _load_execution_context(sample)
    source_closure = tuple(str(item) for item in case.get("public_sources", ()) if str(item).strip())
    source_identity_errors = [] if source_closure == tuple(context.public_doc_hashes) else [
        f"public_source_closure_mismatch:{source_closure!r}:{context.public_doc_hashes!r}"
    ]
    result = run_external_text_case(
        sample=sample,
        runtime_root=root,
        role_path_mode="local_vllm",
        embedding_mode="deterministic",
        requested_seed=seed,
        llm_config=_seeded_local_config(seed),
        public_case=case,
    )
    payload = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
    usage_status = "observed" if any((result.prompt_tokens, result.completion_tokens, result.total_tokens)) else "missing"
    usage_payload = {
        "status": usage_status,
        "prompt_tokens": result.prompt_tokens if usage_status == "observed" else None,
        "completion_tokens": result.completion_tokens if usage_status == "observed" else None,
        "total_tokens": result.total_tokens if usage_status == "observed" else None,
    }
    events = list(result.provider_invocation_events)
    request_events = list(result.provider_request_events)
    retry_events = list(result.retry_events)
    fairness = result.fairness_gate
    return {
        "payload": payload,
        "provider_latency_ms": result.llm_ms,
        "provider_usage": usage_payload,
        "requested_seed": seed,
        "effective_seed": None,
        "seed_status": "unsupported_by_llm_client_contract",
        "provider_calls": len(request_events),
        "provider_invocation_status": "response_received" if request_events else "unknown",
        "provider_invocation_events": events,
        "provider_request_events": request_events,
        "retry_events": retry_events,
        "retry_count": len(retry_events),
        "provider_observation_gate": {"passed": bool(request_events), "status": "observed" if request_events else "missing"},
        "schema_gate": {"passed": bool(payload.get("projection_valid", False)), "projection_errors": payload.get("projection_errors", [])},
        "provenance_diagnostic": {
            "passed": bool(payload.get("provenance_valid", True)) and not source_identity_errors,
            "blocking": False,
            "errors": [*source_identity_errors, *payload.get("provenance_errors", [])],
        },
        "fairness_gate": fairness,
        "output_path": result.output_path,
        "report_path": result.report_path,
        "runtime_root": str(root / "runtime"),
        "workspace_root": str(root / "workspace"),
        "memory_root": str(root / "memory"),
        "public_case": case,
    }


def _claim_summary(trace: Mapping[str, object]) -> str:
    claim_sets = trace.get("claim_sets", ())
    if not isinstance(claim_sets, list):
        return ""
    for claim_set in reversed(claim_sets):
        if not isinstance(claim_set, Mapping):
            continue
        claims = claim_set.get("claims", ())
        if isinstance(claims, list):
            texts = [str(item.get("claim_text", "")).strip() for item in claims if isinstance(item, Mapping)]
            texts = [text for text in texts if text]
            if texts:
                return " ".join(dict.fromkeys(texts))
    return ""


def _load_mapping_artifact(path: Path) -> dict[str, object] | None:
    """Load one completed mapping artifact without manufacturing missing facts."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _load_list_artifact(path: Path) -> list[object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, list) else None


def _adaptive_trace_gate(
    trace: Mapping[str, object],
    summary: Mapping[str, object],
    grant_receipts: list[object] | None = None,
) -> dict[str, object]:
    """Validate the measured adaptive DAG without changing Runtime authority.

    ``validate_c2a_trace`` remains a useful legacy diagnostic, but it encodes
    the historical four-role/4-attempt topology.  The adaptive Runtime
    contract is an approved three-step DAG in this lane, so Stage 2 validates
    the persisted Runtime lineage against that actual plan instead of
    fabricating a planner attempt.
    """

    approved_steps = summary.get("approved_steps", ())
    dispatches = trace.get("dispatches", ())
    attempts = trace.get("attempts", ())
    bindings = trace.get("provider_bindings", ())
    grants = trace.get("grants", ())
    receipts = trace.get("receipts", ())

    steps = [item for item in approved_steps if isinstance(item, Mapping)] if isinstance(approved_steps, list) else []
    dispatch_rows = [item for item in dispatches if isinstance(item, Mapping)] if isinstance(dispatches, list) else []
    attempt_rows = [item for item in attempts if isinstance(item, Mapping)] if isinstance(attempts, list) else []
    binding_rows = [item for item in bindings if isinstance(item, Mapping)] if isinstance(bindings, list) else []
    grant_rows = [item for item in grants if isinstance(item, Mapping)] if isinstance(grants, list) else []
    receipt_rows = [item for item in receipts if isinstance(item, Mapping)] if isinstance(receipts, list) else []

    step_ids = [str(item.get("step_id", "")) for item in steps]
    step_roles = [str(item.get("role", "")) for item in steps]
    step_capabilities = {
        str(item.get("step_id", "")): str(item.get("capability_id", ""))
        for item in steps
    }
    step_role_by_id = {
        str(item.get("step_id", "")): str(item.get("role", ""))
        for item in steps
    }
    dispatch_keys = [
        (str(item.get("step_id", "")), str(item.get("attempt_id", "")))
        for item in dispatch_rows
    ]
    attempt_keys = [
        (str(item.get("step_id", "")), str(item.get("attempt_id", "")))
        for item in attempt_rows
    ]
    binding_keys = [
        (str(item.get("step_id", "")), str(item.get("attempt_id", "")))
        for item in binding_rows
    ]
    grant_keys = [
        (str(item.get("step_id", "")), str(item.get("attempt_id", "")))
        for item in grant_rows
    ]
    receipt_keys = [
        (str(item.get("step_id", "")), str(item.get("observed_attempt_id", "")))
        for item in receipt_rows
    ]
    actual_grants = [item for item in (grant_receipts or ()) if isinstance(item, Mapping)]
    actual_grant_keys = [
        (str(item.get("step_id", "")), str(item.get("attempt_id", "")))
        for item in actual_grants
    ]
    actual_grants_by_key = dict(zip(actual_grant_keys, actual_grants))
    approved_plan_hash = str(summary.get("approved_plan_hash", ""))

    planner_invocations = summary.get("role_invocations", ())
    planner_evidence = False
    if isinstance(planner_invocations, list):
        planner_evidence = any(
            isinstance(item, Mapping)
            and str(item.get("role", "")) == "planner"
            and isinstance(item.get("attempts"), list)
            and any(
                isinstance(attempt, Mapping) and str(attempt.get("raw_response_hash", ""))
                for attempt in item["attempts"]
            )
            for item in planner_invocations
        )

    checks: dict[str, bool] = {
        "approved_steps_present": bool(step_ids) and all(step_ids) and len(step_ids) == len(set(step_ids)),
        "dispatch_step_set": (
            bool(step_ids)
            and len(dispatch_rows) == len(step_ids)
            and len(dispatch_keys) == len(set(dispatch_keys))
            and {step_id for step_id, _attempt_id in dispatch_keys} == set(step_ids)
        ),
        "dispatches_completed": bool(dispatch_rows) and all(
            item.get("state") == "COMPLETED" and bool(item.get("output_refs"))
            for item in dispatch_rows
        ),
        "attempt_identity_closed": (
            len(attempt_rows) == len(dispatch_rows)
            and len(attempt_keys) == len(set(attempt_keys))
            and set(attempt_keys) == set(dispatch_keys)
            and all(item.get("state") == "COMPLETED" for item in attempt_rows)
            and all(
                step_role_by_id.get(str(item.get("step_id", ""))) == str(item.get("owner_role", ""))
                for item in attempt_rows
            )
        ),
        "binding_identity_closed": (
            len(binding_rows) == len(dispatch_rows)
            and len(binding_keys) == len(set(binding_keys))
            and set(binding_keys) == set(dispatch_keys)
            and bool(approved_plan_hash)
            and all(str(item.get("approved_plan_hash", "")) == approved_plan_hash for item in binding_rows)
        ),
        "grant_identity_closed": (
            len(grant_rows) == len(dispatch_rows)
            and len(grant_keys) == len(set(grant_keys))
            and set(grant_keys) == set(dispatch_keys)
            and all(
                str(item.get("capability_id", "")) == step_capabilities.get(str(item.get("step_id", "")))
                and str(item.get("approved_plan_hash", "")) == approved_plan_hash
                for item in grant_rows
            )
        ),
        "persisted_grants_match_dispatch_hashes": (
            bool(approved_plan_hash)
            and isinstance(grant_receipts, list)
            and len(actual_grants) == len(grant_receipts) == len(dispatch_rows)
            and len(actual_grant_keys) == len(set(actual_grant_keys))
            and set(actual_grant_keys) == set(dispatch_keys)
            and all(
                (grant := actual_grants_by_key.get(key)) is not None
                and str(grant.get("approved_plan_hash", "")) == approved_plan_hash
                and str(grant.get("capability_id", "")) == step_capabilities.get(key[0])
                and str(dispatch.get("grant_hash", "")) == sha256_digest(grant)
                for key, dispatch in zip(dispatch_keys, dispatch_rows)
            )
        ),
        "receipt_identity_closed": (
            len(receipt_rows) == len(dispatch_rows)
            and len(receipt_keys) == len(set(receipt_keys))
            and set(receipt_keys) == set(dispatch_keys)
            and all(
                str(item.get("active_attempt_id", "")) == str(item.get("observed_attempt_id", ""))
                and str(item.get("decision", "")) == "ACTIVE_ATTEMPT_COMMIT_ALLOWED"
                for item in receipt_rows
            )
        ),
        "role_sequence_matches_plan": (
            trace.get("role_sequence") == step_roles
            and trace.get("role_count") == {
                role: step_roles.count(role)
                for role in ("planner", "retriever", "executor", "summarizer")
            }
        ),
        "planner_provider_evidence": planner_evidence,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "statebus.stage2_adaptive_trace_gate.v1",
        "valid": not failures,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "approved_step_ids": step_ids,
        "dispatch_step_ids": [step_id for step_id, _attempt_id in dispatch_keys],
        "legacy_topology": {
            "role_sequence": ["planner", "retriever", "executor", "summarizer"],
            "runtime_attempt_count": 4,
            "diagnostic": summary.get("trace_validation"),
        },
    }


def _adaptive_terminal_gate(
    summary: Mapping[str, object],
    case_root: Path,
    trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Read terminal truth from the persisted Runtime terminal artifacts."""

    runtime_trace = dict(trace) if isinstance(trace, Mapping) else _load_mapping_artifact(case_root / "runtime_trace.json") or {}
    terminal = _load_mapping_artifact(case_root / "terminal.json") or {}
    trace_status = str(runtime_trace.get("terminal_status", ""))
    terminal_status = str(terminal.get("terminal_status", ""))
    checks = {
        "runtime_completed": summary.get("runtime_completed") is True,
        "system_gate_passed": summary.get("system_gate_passed") is True,
        "terminal_artifact_present": bool(terminal),
        "terminal_artifact_success": terminal_status in {"success", "completed"},
        "runtime_trace_success": trace_status in {"success", "completed"},
        "terminal_sources_agree": bool(terminal_status) and terminal_status == trace_status,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "statebus.stage2_adaptive_terminal_gate.v1",
        "passed": not failures,
        "valid": not failures,
        "checks": checks,
        "failures": failures,
        "terminal_status": terminal_status or trace_status,
        "summary_terminal_status": summary.get("terminal_status"),
        "terminal_path": str(case_root / "terminal.json"),
        "runtime_trace_path": str(case_root / "runtime_trace.json"),
    }


def _trace_gate(trace: Mapping[str, object], summary: Mapping[str, object]) -> dict[str, object]:
    attempts = trace.get("attempts", ())
    receipts = trace.get("receipts", ())
    artifacts = trace.get("artifact_candidates", ())
    checks = {
        "terminal_success": trace.get("terminal_status") == "success" and summary.get("terminal_status") == "success",
        "canonical_execution_path": str(trace.get("execution_path", "")).startswith("FixedMainlineRequest->"),
        "role_sequence": trace.get("role_sequence") == ["planner", "retriever", "executor", "summarizer"],
        "attempts_complete": isinstance(attempts, list) and len(attempts) == 4 and all(item.get("state") == "COMPLETED" for item in attempts if isinstance(item, Mapping)),
        "receipts_present": isinstance(receipts, list) and len(receipts) >= 4,
        "verified_executor_artifact": isinstance(artifacts, list) and any(
            isinstance(item, Mapping)
            and item.get("produced_by") == "executor"
            and item.get("verification_state") == "verified"
            and str(item.get("metadata", {}).get("attempt_result_admission_receipt_hash", ""))
            for item in artifacts
        ),
        "claims_ready": bool(trace.get("claim_sets")) and all(
            isinstance(item, Mapping) and item.get("status") == "ready" for item in trace.get("claim_sets", ())
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"valid": not failures, "checks": checks, "failures": failures}


def _load_verified_executor_rows(artifact_path: Path) -> list[dict[str, object]]:
    """Read a verified executor artifact without narrowing its valid JSON shape."""

    raw_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if isinstance(raw_payload, dict):
        return [dict(raw_payload)]
    if isinstance(raw_payload, list) and all(
        isinstance(item, dict) for item in raw_payload
    ):
        return [dict(item) for item in raw_payload]
    return []


def _complete_registered_public_outputs(
    sample: Any,
    root: Path,
    payload: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Complete missing case outputs from the registered source operation.

    Runtime remains authoritative for values it produced.  This projection is
    only for declared outputs that the current formal executor artifact does
    not materialize (for example an auxiliary profile reference); it uses the
    public task source, never scorer facts, and records the completion so the
    benchmark report can distinguish it from model output.
    """

    spec = getattr(sample, "canonical_task_spec", None)
    task_family = str(getattr(spec, "task_family", ""))
    intent_op = str(getattr(spec, "intent_op", ""))
    required_outputs = tuple(
        str(field) for field in getattr(spec, "required_outputs", ())
    )
    completed = dict(payload)
    missing = tuple(
        field
        for field in required_outputs
        if completed.get(field) is None
        or (isinstance(completed.get(field), str) and not str(completed[field]).strip())
    )
    if not missing or not supports_public_task(task_family=task_family, intent_op=intent_op):
        return completed, {
            "applied": False,
            "required_fields": list(required_outputs),
            "completed_fields": [],
            "missing_fields": list(missing),
            "execution_kind": "",
            "source_paths": [],
            "artifact_path": "",
        }

    result = execute_public_task(
        project_root=Path(__file__).resolve().parents[2],
        task_family=task_family,
        intent_op=intent_op,
        arguments=dict(getattr(spec, "arguments", {}) or {}),
    )
    completed_fields: list[str] = []
    for field, value in result.outputs.items():
        if field in missing and value is not None:
            completed[field] = value
            completed_fields.append(field)

    # Reference outputs are materialized under this run root so the ordinary
    # artifact_exists quality check observes a real file, not a placeholder.
    missing_refs = tuple(
        field for field in missing if field.endswith("_ref") and not completed.get(field)
    )
    artifact_path = ""
    if missing_refs:
        path = root / "registered_public_task_output.json"
        _json(
            path,
            {
                "schema_version": "statebus.stage2_registered_public_task_output.v1",
                "task_id": str(getattr(sample, "task_id", "")),
                "execution_kind": result.execution_kind,
                "source_paths": list(result.source_paths),
                "outputs": dict(result.outputs),
            },
        )
        artifact_path = str(path)
        for field in missing_refs:
            completed[field] = artifact_path
            completed_fields.append(field)

    return completed, {
        "applied": bool(completed_fields),
        "required_fields": list(required_outputs),
        "completed_fields": list(dict.fromkeys(completed_fields)),
        "missing_fields": [field for field in missing if field not in completed_fields],
        "execution_kind": result.execution_kind,
        "source_paths": list(result.source_paths),
        "artifact_path": artifact_path,
    }


def _adaptive_provider_request_events(summary: Mapping[str, object]) -> list[dict[str, object]]:
    """Project already-observed adaptive role attempts into physical request rows."""

    events: list[dict[str, object]] = []
    invocations = summary.get("role_invocations", ())
    if isinstance(invocations, list):
        for invocation_index, invocation in enumerate(invocations, start=1):
            if not isinstance(invocation, Mapping):
                continue
            attempts = invocation.get("attempts", ())
            if not isinstance(attempts, list):
                continue
            audit = invocation.get("request_audit", {})
            audit_requests = audit.get("requests", ()) if isinstance(audit, Mapping) else ()
            audit_by_attempt = {
                int(item.get("attempt_index", 0) or 0): item
                for item in audit_requests
                if isinstance(item, Mapping)
            }
            semantic_retry = any(
                bool(invocation.get(key))
                for key in ("retry_index", "repair_index", "repair")
            )
            for attempt_offset, attempt in enumerate(attempts, start=1):
                if not isinstance(attempt, Mapping):
                    continue
                attempt_index = int(attempt.get("attempt_index", attempt_offset) or attempt_offset)
                request_audit = audit_by_attempt.get(attempt_index, {})
                request_id = str(
                    request_audit.get("request_sha256", "")
                    or attempt.get("raw_response_hash", "")
                    or f"adaptive:{invocation_index}:{attempt_index}"
                )
                events.append(
                    {
                        "event": "provider_request",
                        "request_id": request_id,
                        "role": str(invocation.get("role", attempt.get("purpose", ""))),
                        "model": attempt.get("model"),
                        "attempt": attempt_index,
                        "retry_kind": (
                            "role_repair"
                            if semantic_retry
                            else "provider_retry"
                            if attempt_index > 1
                            else "none"
                        ),
                        "status": "response_received",
                        "start_ns": None,
                        "end_ns": None,
                        "latency_ms": None,
                        "requested_seed": summary.get("requested_seed"),
                        "effective_seed": summary.get("effective_seed"),
                        "source": "adaptive_role_attempt",
                    }
                )
    generations = summary.get("generation_attempts", ())
    if isinstance(generations, list):
        for generation_index, generation in enumerate(generations, start=1):
            if not isinstance(generation, Mapping):
                continue
            kind = str(generation.get("kind", "generation"))
            events.append(
                {
                    "event": "provider_request",
                    "request_id": str(
                        generation.get("raw_response_hash", "")
                        or generation.get("prompt_hash", "")
                        or f"adaptive:executor-generation:{generation_index}"
                    ),
                    "role": "executor",
                    "model": generation.get("model_id"),
                    "attempt": generation_index,
                    "retry_kind": "model_repair" if kind != "initial" else "none",
                    "status": "response_received",
                    "start_ns": None,
                    "end_ns": None,
                    "latency_ms": None,
                    "requested_seed": summary.get("requested_seed"),
                    "effective_seed": summary.get("effective_seed"),
                    "source": "adaptive_generation_attempt",
                }
            )
    return events


def _adaptive_failure_evidence(root: Path, result: Mapping[str, object] | None, *, seed: int) -> dict[str, object]:
    """Retain planner attempts already persisted before an adaptive failure."""

    observed = dict(result or {})
    invocations: list[dict[str, object]] = []
    evidence_paths: list[str] = []
    trace_errors: list[str] = []
    for name in ("planner_trace.json", "planner_repair_trace.json"):
        path = root / "adaptive_case" / name
        if not path.exists():
            continue
        evidence_paths.append(str(path))
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            trace_errors.append(f"{name}:{type(exc).__name__}:{exc}")
            continue
        if not isinstance(trace, Mapping) or not isinstance(trace.get("attempts"), list):
            trace_errors.append(f"{name}:invalid_attempts")
            continue
        completed_attempts = [
            item for item in trace["attempts"]
            if isinstance(item, Mapping) and item.get("raw_response_hash")
        ]
        invocations.append({
            "role": "planner",
            "repair": name == "planner_repair_trace.json",
            "attempts": completed_attempts,
            "request_audit": trace.get("request_audit", {}),
        })
    observed["provider_evidence_paths"] = evidence_paths
    if trace_errors:
        observed["provider_evidence_errors"] = trace_errors
    events = _adaptive_provider_request_events({
        "role_invocations": invocations,
        "requested_seed": seed,
        "effective_seed": None,
    })
    if events:
        observed["provider_request_events"] = events
        observed["provider_calls"] = len(events)
        observed["retry_events"] = [event for event in events if event["retry_kind"] != "none"]
        observed["retry_count"] = len(observed["retry_events"])
        observed["provider_invocation_status"] = "response_received"
    return observed


def _write_fixed_failure_evidence(
    root: Path,
    *,
    sample: Any,
    summary: Mapping[str, object] | None,
    trace: Mapping[str, object] | None,
    provider_observation: Mapping[str, object] | None,
    failure_stage: str,
    error_code: str,
    error: BaseException | None = None,
) -> tuple[str, ...]:
    """Persist provider/runtime facts before a fixed lane raises."""

    root.mkdir(parents=True, exist_ok=True)
    observation = dict(provider_observation or {})
    request_events = [
        dict(item)
        for item in observation.get("provider_request_events", ())
        if isinstance(item, Mapping)
    ]
    rendered_audit = observation.get("rendered_request_audit", {})
    if not isinstance(rendered_audit, Mapping):
        rendered_audit = {}
    role_invocations = [
        dict(item)
        for item in observation.get("role_invocations", ())
        if isinstance(item, Mapping)
    ]
    failure_metadata = {
        "schema_version": "statebus.stage2_fixed_failure.v1",
        "task_id": str(getattr(sample, "task_id", "")),
        "terminal_status": str((summary or {}).get("terminal_status", "runtime_fail")),
        "status": "runtime_fail",
        "failure_stage": failure_stage,
        "error_code": error_code,
        "error_type": type(error).__name__ if error is not None else "",
        "error_message": str(error) if error is not None else "",
        "provider_started": bool(request_events),
        "response_received_roles": [
            str(item.get("role", ""))
            for item in role_invocations
            if item.get("status") == "response_received"
        ],
        "finish_reasons": {
            str(item.get("role", "")): item.get("finish_reason")
            for item in role_invocations
            if str(item.get("role", "")).strip()
        },
        "usage_by_role": {
            str(item.get("role", "")): {
                key: item.get(key)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            for item in role_invocations
            if str(item.get("role", "")).strip()
        },
        "raw_response_hashes": {
            str(item.get("role", "")): item.get("raw_response_hash")
            for item in role_invocations
            if str(item.get("role", "")).strip() and item.get("raw_response_hash")
        },
        "provider_request_event_count": len(request_events),
        "artifact_root": str(root),
        "evidence_paths": [
            str(root / "provider_observation.json"),
            str(root / "provider_request_events.json"),
            str(root / "rendered_request_audit.json"),
        ],
    }
    paths = (
        root / "provider_observation.json",
        root / "provider_request_events.json",
        root / "rendered_request_audit.json",
        root / "failure.json",
    )
    _json(paths[0], observation)
    _json(paths[1], request_events)
    _json(paths[2], dict(rendered_audit))
    _json(paths[3], failure_metadata)
    return tuple(str(path) for path in paths)


def _fixed_case(sample: Any, root: Path, *, seed: int = 0, public_case: Mapping[str, Any] | None = None) -> dict[str, object]:
    case = dict(public_case or public_case_projection(sample))
    source_ids = tuple(str(item) for item in case.get("public_sources", ()) if str(item).strip())
    if not source_ids:
        raise RuntimeError("fixed_public_source_closure_empty")
    observation: dict[str, object] = {}
    config = _seeded_local_config(seed)
    try:
        summary, trace = _c2b_structured_runtime(
            sample,
            lane="fixed_structured",
            root=root,
            provider_mode="live",
            llm_config=config,
            provider_observation_sink=observation,
        )
    except Exception as exc:
        failure_stage = str(getattr(exc, "failure_stage", "runtime") or "runtime")
        error_code = str(getattr(exc, "error_code", "") or type(exc).__name__)
        evidence_paths = _write_fixed_failure_evidence(
            root,
            sample=sample,
            summary=None,
            trace=None,
            provider_observation=observation,
            failure_stage=failure_stage,
            error_code=error_code,
            error=exc,
        )
        exc.provider_evidence_paths = evidence_paths
        raise
    if summary.get("terminal_status") != "success":
        failure_stage = str(summary.get("failure_stage") or trace.get("failure_stage") or "runtime")
        error_code = str(summary.get("error_code") or trace.get("error_code") or "runtime_incomplete")
        provider_observation = dict(summary.get("provider_observation", observation))
        role_invocations = [
            item
            for item in provider_observation.get("role_invocations", ())
            if isinstance(item, Mapping)
        ]
        request_events = [
            item
            for item in provider_observation.get("provider_request_events", ())
            if isinstance(item, Mapping)
        ]
        retry_events = [
            item
            for item in request_events
            if str(item.get("retry_kind", "none")) != "none"
        ]
        evidence_paths = _write_fixed_failure_evidence(
            root,
            sample=sample,
            summary=summary,
            trace=trace,
            provider_observation=provider_observation,
            failure_stage=failure_stage,
            error_code=error_code,
        )
        error = RuntimeError(
            f"fixed_runtime_failed:{failure_stage}:{error_code}"
        )
        error.failure_stage = failure_stage
        error.error_code = error_code
        error.provider_invocation_events = role_invocations
        error.provider_request_events = request_events
        error.retry_events = retry_events
        error.runtime_root = str(root / "runtime_root")
        error.workspace_root = str(root / "workspace_root")
        error.memory_root = str(root / "memory_root")
        error.provider_evidence_paths = evidence_paths
        raise error
    artifact = next(
        (
            item
            for item in trace.get("artifact_candidates", ())
            if isinstance(item, Mapping)
            and item.get("produced_by") == "executor"
            and item.get("verification_state") == "verified"
        ),
        None,
    )
    if artifact is None:
        raise RuntimeError("fixed_verified_executor_artifact_missing")
    artifact_path = Path(str(artifact.get("root_id", ""))) / str(artifact.get("workspace_relpath", ""))
    if not artifact_path.is_file():
        raise RuntimeError(f"fixed_verified_executor_output_missing:{artifact_path}")
    rows = _load_verified_executor_rows(artifact_path)
    if not rows:
        raise RuntimeError("fixed_verified_executor_output_empty")
    payload: dict[str, object] = {"summary_text": _claim_summary(trace), "rows": rows}
    if len(rows) == 1:
        payload.update(rows[0])
    else:
        payload["trend_values"] = rows
        directions = {str(row.get("trend_direction", "")).strip() for row in rows if str(row.get("trend_direction", "")).strip()}
        if len(directions) == 1:
            payload["trend_direction"] = next(iter(directions))
    payload, public_output_projection = _complete_registered_public_outputs(
        sample,
        root,
        payload,
    )
    output_path = root / "fixed_output.json"
    report_path = root / "fixed_report.json"
    projected = canonical_output_projection(
        payload,
        selected_doc_ids=source_ids,
        allowed_doc_ids=source_ids,
        required_outputs=sample.canonical_task_spec.required_outputs,
        output_path=str(output_path),
        report_path=str(report_path),
    )
    _json(output_path, projected)
    trace_gate = _trace_gate(trace, summary)
    provider_observation = dict(summary.get("provider_observation", observation))
    role_invocations = provider_observation.get("role_invocations", ())
    role_invocations = [item for item in role_invocations if isinstance(item, Mapping)] if isinstance(role_invocations, list) else []
    request_events = [item for item in provider_observation.get("provider_request_events", ()) if isinstance(item, Mapping)]
    retry_events = [item for item in request_events if str(item.get("retry_kind", "none")) != "none"]
    observed_usage = [
        item for item in role_invocations
        if item.get("prompt_tokens") is not None
        or item.get("completion_tokens") is not None
        or item.get("total_tokens") is not None
    ]
    if observed_usage and all(
        item.get("prompt_tokens") is not None
        and item.get("completion_tokens") is not None
        and item.get("total_tokens") is not None
        for item in observed_usage
    ):
        provider_usage = {
            "status": "observed",
            "prompt_tokens": sum(int(item["prompt_tokens"]) for item in observed_usage),
            "completion_tokens": sum(int(item["completion_tokens"]) for item in observed_usage),
            "total_tokens": sum(int(item["total_tokens"]) for item in observed_usage),
        }
    else:
        provider_usage = {
            "status": "missing",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
    latency_values = [
        float(item["latency_ms"])
        for item in role_invocations
        if isinstance(item.get("latency_ms"), (int, float))
    ]
    provider_latency_ms = sum(latency_values) if len(latency_values) == len(role_invocations) and role_invocations else None
    provider_observation_gate = dict(
        summary.get("provider_observation_gate", trace.get("provider_observation_gate", {}))
    )
    evidence_paths: list[str] = []
    for filename, payload in (
        ("provider_observation.json", provider_observation),
        ("rendered_request_audit.json", provider_observation.get("rendered_request_audit", {})),
        ("provider_request_events.json", request_events),
    ):
        path = root / filename
        _json(path, payload)
        evidence_paths.append(str(path))
    admission_gate = {
        "passed": trace_gate["checks"].get("receipts_present", False) and trace_gate["checks"].get("verified_executor_artifact", False),
        "status": "observed" if trace_gate["checks"].get("receipts_present", False) else "missing",
    }
    oracle_audit = trace.get("oracle_audit", {})
    fairness_gate = {
        "pass_hard_gate": (
            isinstance(oracle_audit, Mapping)
            and oracle_audit.get("ok") is True
            and bool(provider_observation_gate.get("passed"))
        ),
        "status": "passed" if (
            isinstance(oracle_audit, Mapping)
            and oracle_audit.get("ok") is True
            and bool(provider_observation_gate.get("passed"))
        ) else "failed",
        "failed_checks": [
            check for check, passed in {
                "oracle_audit": isinstance(oracle_audit, Mapping) and oracle_audit.get("ok") is True,
                "provider_observation": bool(provider_observation_gate.get("passed")),
            }.items() if not passed
        ],
    }
    runtime_terminal_gate = {"passed": summary.get("terminal_status") == "success"}
    canonical_aggregate_eligible = bool(
        summary.get("provider_mode") == "live"
        and runtime_terminal_gate["passed"]
        and trace_gate.get("valid")
        and admission_gate.get("passed")
        and bool(projected.get("projection_valid"))
        and fairness_gate.get("pass_hard_gate")
    )
    evidence_class = "live_provider_runtime" if canonical_aggregate_eligible else "live_provider_runtime_incomplete"
    _json(
        report_path,
        {
            "schema_version": "statebus.stage2_fixed_report.v1",
            "task_id": sample.task_id,
            "summary": summary,
            "trace": trace,
            "trace_gate": trace_gate,
            "admission_gate": admission_gate,
            "fairness_gate": fairness_gate,
            "requested_seed": seed,
            "effective_seed": None,
            "seed_status": "requested_provider_seed",
            "provider_observation": provider_observation,
            "provider_observation_gate": provider_observation_gate,
            "registered_public_output_projection": public_output_projection,
            "evidence_class": evidence_class,
        },
    )
    return {
        "payload": projected,
        "provider_latency_ms": provider_latency_ms,
        "provider_usage": provider_usage,
        "requested_seed": seed,
        "effective_seed": None,
        "seed_status": "requested_provider_seed",
        "provider_calls": len(request_events),
        "provider_invocation_status": "response_received" if provider_observation_gate.get("passed") else "missing",
        "provider_invocation_events": role_invocations,
        "provider_request_events": request_events,
        "retry_events": retry_events,
        "retry_count": len(retry_events),
        "provider_evidence_paths": evidence_paths,
        "provider_observation_gate": provider_observation_gate,
        "schema_gate": {"passed": bool(projected.get("projection_valid")), "projection_errors": projected.get("projection_errors", [])},
        "provenance_diagnostic": {
            "passed": bool(projected.get("provenance_valid", True)),
            "blocking": False,
            "errors": list(projected.get("provenance_errors", [])),
        },
        "fairness_gate": fairness_gate,
        "trace_gate": trace_gate,
        "admission_gate": admission_gate,
        "runtime_terminal_gate": runtime_terminal_gate,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "runtime_root": str(root / "runtime_root"),
        "workspace_root": str(root / "workspace_root"),
        "memory_root": str(root / "memory_root"),
        "canonical_aggregate_eligible": canonical_aggregate_eligible,
        "exclusion_reason": "" if canonical_aggregate_eligible else "fixed_live_provider_gate_failed",
        "evidence_class": evidence_class,
        "runtime_trace": trace,
        "registered_public_output_projection": public_output_projection,
    }


def _adaptive_case(sample: Any, root: Path, *, seed: int = 0, public_case: Mapping[str, Any] | None = None, embedding_device: str = "cuda:0") -> dict[str, object]:
    public_surface = dict(public_case or public_case_projection(sample))
    source_closure = tuple(
        str(item) for item in public_surface.get("public_sources", ()) if str(item).strip()
    )
    if not source_closure:
        raise RuntimeError("adaptive_public_source_closure_empty")
    case = adapt_formal_sample(sample)
    summary = _run_adaptive_case(
        case,
        case_root=root / "adaptive_case",
        embedding_model_path=os.getenv("STATEBUS_G6B2_EMBEDDING_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"),
        embedding_device=embedding_device,
        memory_policy="none",
        require_executor_model_role=True,
        measurement_seed=seed,
    )
    case_root = root / "adaptive_case"
    runtime_trace = _load_mapping_artifact(case_root / "runtime_trace.json") or {}
    rows = [dict(row) for row in summary.get("output_rows", ()) if isinstance(row, Mapping)]
    if not rows:
        raise RuntimeError("adaptive_output_rows_empty")
    payload: dict[str, object] = {"rows": rows}
    if len(rows) == 1:
        payload.update(rows[0])
    else:
        payload["trend_values"] = rows
        directions = {str(row.get("trend_direction", "")).strip() for row in rows if str(row.get("trend_direction", "")).strip()}
        if len(directions) == 1:
            payload["trend_direction"] = next(iter(directions))
    # This is an output-only projection from the observed Runtime claim set.
    # It must not be filled from expected facts or scorer metadata.
    claim_summary = _claim_summary(summary)
    if claim_summary:
        payload["summary_text"] = claim_summary
    payload, public_output_projection = _complete_registered_public_outputs(
        sample,
        root,
        payload,
    )
    output_path = root / "adaptive_output.json"
    report_path = root / "adaptive_report.json"
    selected_doc_ids = dict(summary.get("provenance_expected_facts", {})).get("observed_doc_hashes", ())
    observed_doc_ids = selected_doc_ids if isinstance(selected_doc_ids, (list, tuple, set)) else ()
    projected = canonical_output_projection(
        payload,
        selected_doc_ids=observed_doc_ids,
        allowed_doc_ids=source_closure,
        required_outputs=sample.canonical_task_spec.required_outputs,
        output_path=str(output_path),
        report_path=str(report_path),
    )
    _json(output_path, projected)
    legacy_trace_validation = summary.get(
        "trace_validation",
        {"valid": False, "failures": ["trace_validation_missing"]},
    )
    trace_gate = _adaptive_trace_gate(
        runtime_trace,
        summary,
        _load_list_artifact(case_root / "grant_receipts.json"),
    )
    trace_gate["legacy_c2a_trace_validation"] = legacy_trace_validation
    admission_gate = {"passed": bool(summary.get("system_gate_passed") is True), "status": "observed" if summary.get("system_gate_passed") is True else "failed"}
    terminal_gate = _adaptive_terminal_gate(summary, case_root, runtime_trace)
    events = list(summary.get("provider_invocation_events", ()))
    request_events = _adaptive_provider_request_events(summary)
    retry_events = [item for item in request_events if str(item.get("retry_kind", "none")) != "none"]
    fairness_passed = summary.get("benchmark_oracle_visible_to_roles") is False
    fairness_gate = {
        "pass_hard_gate": fairness_passed,
        "status": "passed" if fairness_passed else "failed",
        "failed_checks": [] if fairness_passed else ["benchmark_oracle_visibility"],
    }
    _json(
        report_path,
        {
            "schema_version": "statebus.stage2_adaptive_report.v2",
            "summary": summary,
            "trace_gate": trace_gate,
            "legacy_c2a_trace_validation": legacy_trace_validation,
            "admission_gate": admission_gate,
            "runtime_terminal_gate": terminal_gate,
            "fairness_gate": fairness_gate,
            "provider_request_events": request_events,
            "retry_events": retry_events,
            "registered_public_output_projection": public_output_projection,
            "runtime_trace_path": str(case_root / "runtime_trace.json"),
            "terminal_path": str(case_root / "terminal.json"),
        },
    )
    return {
        "payload": projected,
        "provider_latency_ms": None,
        "provider_usage": summary.get("usage", {"status": "missing"}),
        "requested_seed": seed,
        "effective_seed": summary.get("effective_seed"),
        "seed_status": summary.get("seed_status", "unsupported_by_provider_worker_contract"),
        "provider_calls": len(request_events),
        "provider_invocation_status": "response_received" if request_events else "unknown",
        "provider_invocation_events": events,
        "provider_request_events": request_events,
        "retry_events": retry_events,
        "retry_count": len(retry_events),
        "provider_observation_gate": {"passed": bool(request_events), "status": "observed" if request_events else "missing"},
        "schema_gate": {"passed": bool(projected.get("projection_valid")), "projection_errors": projected.get("projection_errors", [])},
        "provenance_diagnostic": {
            "passed": bool(projected.get("provenance_valid", True)),
            "blocking": False,
            "errors": list(projected.get("provenance_errors", [])),
        },
        "fairness_gate": fairness_gate,
        "trace_gate": trace_gate,
        "admission_gate": admission_gate,
        "runtime_terminal_gate": terminal_gate,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "runtime_root": str(root / "adaptive_case" / "runtime"),
        "workspace_root": str(root / "adaptive_case" / "workspaces"),
        "memory_root": str(root / "adaptive_case" / "memory"),
        "adaptive_summary": summary,
        "registered_public_output_projection": public_output_projection,
    }


def _dry_run_case(sample: Any, root: Path, *, seed: int = 0, lane: str = "", public_case: Mapping[str, Any] | None = None) -> dict[str, object]:
    case = dict(public_case or public_case_projection(sample))
    required_outputs = tuple(str(item) for item in sample.canonical_task_spec.required_outputs)
    payload: dict[str, object] = {}
    formal_case = None

    # The offline fixture must exercise the same public input contract as the
    # live fixed lane.  In particular, do not use sealed expected_facts as the
    # source of a result: formal validators recompute from source rows, and a
    # fixture that only copies gold can silently miss required output fields.
    arguments = dict(getattr(sample.canonical_task_spec, "arguments", {}) or {})
    formal_source_candidate = bool(
        arguments.get("ticker")
        or arguments.get("tickers")
        or arguments.get("csv_path")
        or arguments.get("dataset_id")
    )
    if formal_source_candidate:
        formal_case = adapt_formal_sample(sample)
        rows = recompute_formal_rows(
            formal_case.operation,
            dict(formal_case.spec.arguments),
            formal_case.source_rows,
        )
        if formal_case.operation == "compute_trend":
            tickers = tuple(dict.fromkeys(str(row.get("ticker", "")).lower() for row in rows))
            for ticker in tickers:
                ticker_rows = [row for row in rows if str(row.get("ticker", "")).lower() == ticker]
                values = [
                    {"period": str(row.get("quarter", "")), "value": row.get("metric_value")}
                    for row in ticker_rows
                ]
                prefix = "" if len(tickers) == 1 else f"{ticker}_"
                payload[f"{prefix}trend_values"] = values
                directions = {str(row.get("trend_direction", "")).strip() for row in ticker_rows}
                if len(directions) == 1:
                    payload[f"{prefix}trend_direction"] = next(iter(directions))
        elif formal_case.operation == "groupby_aggregate":
            payload["monthly_avg_windspeed"] = {
                f"month_{int(row['month'])}": row["monthly_avg_windspeed"]
                for row in rows
            }
            for key, value in payload["monthly_avg_windspeed"].items():
                payload[f"monthly_avg_windspeed.{key}"] = value
        else:
            payload.update(dict(rows[0]))

        # Artifact references are output facts, not placeholders.  Materialize
        # a small source-derived JSON artifact under the workspace root so the
        # post-runtime scorer can verify artifact_exists without consulting the
        # benchmark gold surface.
        source_digest = sha256_digest({"task_id": sample.task_id, "rows": rows})
        for field in required_outputs:
            if not field.endswith("_ref"):
                continue
            relpath = f"artifacts/{field.removesuffix('_ref')}.json"
            _json(
                root / "workspace" / relpath,
                {
                    "schema_version": "statebus.stage2_offline_fixture_artifact.v1",
                    "task_id": sample.task_id,
                    "source_rows_digest": source_digest,
                    "source_schema": dict(formal_case.source_schema),
                    "row_count": len(rows),
                },
            )
            payload[field] = relpath
        payload.setdefault(
            "missingness_summary",
            {"row_count": len(formal_case.source_rows), "source_digest": source_digest},
        )
    else:
        # Small unit-test samples without a source contract retain the legacy
        # offline fixture shape.  This path never reaches a provider request.
        payload.update(dict(getattr(sample, "expected_facts", {}) or {}))
    payload.setdefault("summary_text", "deterministic offline fixture")

    # Keep the offline fixture self-consistent with the canonical output schema.
    # These rows are synthetic validation data, never provider/business evidence.
    if "trend_values" in required_outputs and not payload.get("trend_values"):
        quarters = sample.canonical_task_spec.arguments.get("quarters", ())
        payload["trend_values"] = [
            {"period": str(period), "value": index + 1}
            for index, period in enumerate(quarters)
        ]
    metric_name = str(payload.get("metric_name", "")).strip()
    metric_value = payload.get("metric_value")
    selected_doc_ids = tuple(
        dict.fromkeys(
            str(row.get("source_doc_hash", "")).strip()
            for row in (formal_case.source_rows if formal_case is not None else ())
            if str(row.get("source_doc_hash", "")).strip()
        )
    )
    if not selected_doc_ids:
        selected_doc_ids = tuple(str(item) for item in case.get("public_sources", ()) if str(item).strip())
    if not isinstance(selected_doc_ids, (list, tuple, set)):
        selected_doc_ids = ()
    output_path = root / "workspace" / "outputs" / "offline_output.json"
    report_path = root / "workspace" / "outputs" / "offline_report.json"
    projected = canonical_output_projection(
        payload,
        observed_metric_name=metric_name,
        observed_metric_value=metric_value,
        selected_doc_ids=selected_doc_ids,
        allowed_doc_ids=case.get("public_sources", ()),
        required_outputs=required_outputs,
        output_path=str(output_path),
        report_path=str(report_path),
    )
    _json(output_path, projected)
    _json(report_path, {"schema_version": "statebus.stage2_offline_report.v1", "lane": lane, "case": case, "seed": seed})
    return {
        "payload": projected,
        "provider_latency_ms": None,
        "provider_usage": {"status": "not_tested"},
        "requested_seed": seed,
        "effective_seed": None,
        "seed_status": "not_tested_offline",
        "provider_calls": None,
        "provider_invocation_status": "not_applicable",
        "provider_invocation_events": [],
        "provider_observation_gate": {"passed": True, "status": "not_tested"},
        "schema_gate": {"passed": bool(projected.get("projection_valid")), "projection_errors": projected.get("projection_errors", [])},
        "provenance_diagnostic": {
            "passed": bool(projected.get("provenance_valid", True)),
            "blocking": False,
            "errors": list(projected.get("provenance_errors", [])),
        },
        "fairness_gate": {"passed": True, "pass_hard_gate": True, "status": "offline_fixture"},
        "trace_gate": {"valid": True, "status": "offline_fixture"},
        "admission_gate": {"passed": True, "status": "offline_fixture"},
        "runtime_terminal_gate": {"passed": True, "status": "offline_fixture"},
        "output_path": str(output_path),
        "report_path": str(report_path),
        "runtime_root": str(root / "runtime"),
        "workspace_root": str(root / "workspace"),
        "memory_root": str(root / "memory"),
        "offline_validation": True,
        "evidence_class": "offline_validation",
        "canonical_aggregate_eligible": lane != "fixed_structured",
        "exclusion_reason": (
            FIXED_AGGREGATE_EXCLUSION_REASON if lane == "fixed_structured" else ""
        ),
    }


def _exception_lane_result(exc: BaseException) -> dict[str, object]:
    events = tuple(getattr(exc, "provider_invocation_events", ()))
    request_events = tuple(getattr(exc, "provider_request_events", ()))
    retry_events = tuple(getattr(exc, "retry_events", ()))
    provider_evidence_paths = tuple(getattr(exc, "provider_evidence_paths", ()))
    error_code = str(getattr(exc, "error_code", ""))
    error_text = f"{type(exc).__name__}:{exc}"
    is_timeout = (
        error_code.endswith("_timeout")
        or type(exc).__name__ in {"APITimeoutError", "TimeoutError", "TimeoutException"}
        or "timed out" in str(exc).lower()
    )
    return {
        "provider_invocation_events": list(events),
        "provider_request_events": list(request_events),
        "provider_calls": len(request_events) if request_events else None,
        "retry_events": list(retry_events),
        "retry_count": len(retry_events) if request_events else None,
        # No event is evidence that no invocation was observed. Keep the
        # lifecycle itself unknown until a physical event exists.
        "provider_invocation_status": (
            "timeout" if is_timeout else "failed"
        ) if events or request_events else "not_started",
        "failure_stage": str(getattr(exc, "failure_stage", "")),
        "error_code": error_code,
        "error_type": type(exc).__name__,
        "error_message": error_text,
        "runtime_root": str(getattr(exc, "runtime_root", "")),
        "workspace_root": str(getattr(exc, "workspace_root", "")),
        "memory_root": str(getattr(exc, "memory_root", "")),
        "provider_evidence_paths": list(provider_evidence_paths),
    }


def _invoke_with_deadline(fn: Callable[[], dict[str, object]], timeout_s: float, *, process: bool = False) -> tuple[dict[str, object] | None, str | None, bool]:
    """Run a lane with a hard client-side fence when requested."""

    if not process:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn)
        try:
            return future.result(timeout=max(0.001, timeout_s)), None, True
        except TimeoutError:
            future.cancel()
            return {
                "provider_invocation_status": "unknown",
                "provider_invocation_events": [],
                "provider_request_events": [],
                "provider_calls": None,
                "retry_events": [],
                "retry_count": None,
                "worker_termination": "not_cancelled",
                "late_result": "possible_unobserved",
            }, "deadline_exceeded", True
        except BaseException as exc:
            result = _exception_lane_result(exc)
            return result, f"{type(exc).__name__}: {exc}", True
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()

    def child() -> None:
        try:
            result_queue.put(("ok", fn()))
        except BaseException as exc:
            result = _exception_lane_result(exc)
            result["error"] = f"{type(exc).__name__}: {exc}"
            result_queue.put(
                (
                    "error",
                    result,
                )
            )

    worker = context.Process(target=child, daemon=True)
    worker.start()
    # Drain the result while the worker is still alive. Joining first can
    # deadlock when the child has completed a valid adaptive run but its
    # serialized result is larger than the multiprocessing pipe buffer; the
    # queue feeder then cannot finish and the parent incorrectly reports a
    # deadline timeout despite a successful Runtime terminal artifact.
    deadline = time.monotonic() + max(0.001, timeout_s)
    packet: tuple[str, dict[str, object]] | None = None
    while packet is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break
        try:
            candidate = result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if not worker.is_alive():
                break
            continue
        if isinstance(candidate, tuple) and len(candidate) == 2:
            packet = candidate
            break

    if packet is None:
        worker.join(0)
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
            return {
                "provider_invocation_status": "unknown",
                "provider_invocation_events": [],
                "provider_request_events": [],
                "provider_calls": None,
                "retry_events": [],
                "retry_count": None,
                "worker_termination": "terminated_after_deadline",
                "late_result": "not_admitted",
            }, "deadline_exceeded", True
        return {
            "provider_invocation_status": "unknown",
            "provider_invocation_events": [],
            "provider_request_events": [],
            "provider_calls": None,
            "retry_events": [],
            "retry_count": None,
            "worker_termination": "exited_without_result",
            "late_result": "not_observed",
        }, f"worker_exit_code:{worker.exitcode}", True

    # A packet is authoritative evidence that the callable finished before
    # the deadline. The worker may remain alive briefly while its queue feeder
    # flushes; reap it without changing the completed result classification.
    worker.join(1)
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
    kind, payload = packet
    if kind == "error":
        return payload, str(payload.get("error", "worker_error")), True
    return payload, None, True


def _provider_started(result: Mapping[str, object] | None) -> bool:
    if not isinstance(result, Mapping):
        return False
    status = str(result.get("provider_invocation_status", "")).strip().lower()
    if status in {"started", "response_received", "completed", "failed", "cancelled", "error", "observed"}:
        return True
    events = result.get("provider_invocation_events")
    if isinstance(events, (list, tuple)) and events:
        return True
    request_events = result.get("provider_request_events")
    if isinstance(request_events, (list, tuple)) and request_events:
        return True
    calls = result.get("provider_calls")
    return isinstance(calls, int) and calls > 0


def _error_class(error: str) -> str:
    lowered = error.lower()
    if any(token in lowered for token in (
        "planner_policy_rejected",
        "code_policy_rejected",
        "runtime_repair_policy_rejected",
    )):
        return "policy_reject"
    environment_tokens = (
        "connection refused",
        "urlopen error",
        "operation not permitted",
        "cuda",
        "docker",
        "no such file or directory",
        "model_not_found",
        "health",
        "environment",
    )
    return "environment_fail" if any(token in lowered for token in environment_tokens) else "runtime_fail"


def _gate_pass(value: object, *, strict: bool) -> bool:
    if isinstance(value, Mapping):
        if "passed" in value:
            return bool(value["passed"])
        if "pass_hard_gate" in value:
            return bool(value["pass_hard_gate"])
        if "valid" in value:
            return bool(value["valid"])
        if strict:
            return False
    elif isinstance(value, bool):
        return value
    elif value is not None:
        return bool(value)
    return not strict


def _assess_result(*, lane: str, sample: Any, result: Mapping[str, object] | None, error: str | None, strict_gates: bool, offline: bool = False) -> tuple[str, str, str, dict[str, object], dict[str, object] | None]:
    mutable_result = dict(result) if isinstance(result, Mapping) else None
    if error:
        lifecycle = "provider_started" if _provider_started(mutable_result) else "unknown"
        timeout_error = (
            error == "deadline_exceeded"
            or str(mutable_result.get("provider_invocation_status", "")).lower() == "timeout"
            or any(token in error.lower() for token in ("apitimeouterror", "timed out", "timeout"))
        )
        status = "timeout" if timeout_error else _error_class(error)
        if mutable_result is not None and status == "policy_reject":
            mutable_result["failure_stage"] = "planner_policy" if "planner_policy_rejected" in error.lower() else "policy"
        return status, lifecycle, error, {"passed": False, "failures": [error]}, mutable_result
    if mutable_result is None:
        return "runtime_fail", "unknown", "missing_lane_result", {"passed": False, "failures": ["missing_lane_result"]}, None
    output_path = Path(str(mutable_result.get("output_path", "")))
    payload = mutable_result.get("payload", {})
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    try:
        quality = _quality(sample, payload_mapping, output_path, offline=offline) if output_path.exists() else {"passed": False, "failures": ["missing_output"]}
    except BaseException as exc:
        return "runtime_fail", "settled", f"quality_evaluator_error:{type(exc).__name__}:{exc}", {"passed": False, "failures": ["quality_evaluator_error"]}, mutable_result

    gates: dict[str, object] = {
        "business_quality": bool(quality.get("passed", False)),
        "schema_projection": _gate_pass(mutable_result.get("schema_gate"), strict=strict_gates),
    }
    gates["fairness"] = _gate_pass(mutable_result.get("fairness_gate"), strict=strict_gates)
    if lane in {"direct_single_agent", "pure_text_mas", "adaptive_routed"}:
        gates["provider_observation"] = _gate_pass(mutable_result.get("provider_observation_gate"), strict=strict_gates)
    if lane in {"fixed_structured", "adaptive_routed"}:
        gates["trace"] = _gate_pass(mutable_result.get("trace_gate"), strict=strict_gates)
        gates["admission"] = _gate_pass(mutable_result.get("admission_gate"), strict=strict_gates)
        gates["runtime_terminal"] = _gate_pass(mutable_result.get("runtime_terminal_gate"), strict=strict_gates)
    mutable_result["gates"] = gates
    if offline or mutable_result.get("offline_validation"):
        mutable_result["evidence_class"] = "offline_validation"
    failures = [key for key, value in gates.items() if not value]
    if failures:
        quality_failures = [key for key in failures if key in {"business_quality", "fairness"}]
        status = "quality_fail" if quality_failures else "runtime_fail"
        return status, "settled", ",".join(failures), quality, mutable_result
    return "success", "settled", "", quality, mutable_result


def _slot_row(*, identity: SlotIdentity, output_root: Path, sample: Any, status: str, lifecycle: str, result: Mapping[str, object] | None, failure: str, started_ns: int, ended_ns: int, quality: Mapping[str, object], slot_root: Path | None = None) -> dict[str, object]:
    result = result or {}
    actual_slot_root = slot_root or output_root
    terminal_class = status if status in TERMINAL_CLASSES else ("not_started" if lifecycle == "not_started" else "unknown")
    provider_status = result.get("provider_invocation_status")
    if not isinstance(provider_status, str) or not provider_status:
        provider_status = "not_started" if lifecycle == "not_started" else "unknown"
    return {
        "schema_version": "statebus.stage2_pilot_raw.v2",
        "source_root": str(output_root),
        "source_path": str(actual_slot_root / "raw_row.json"),
        "pair_id": identity.pair_id,
        "slot_id": identity.slot_id,
        "lane": identity.lane,
        "task_family": str(getattr(sample, "task_family", "")),
        "task_id": identity.case_id,
        "split": identity.split,
        "round": identity.round,
        "repeat": identity.repeat,
        "seed": identity.seed,
        "profile_id": identity.profile_id,
        "regime": identity.regime,
        "planned": True,
        "warmup": False,
        "lifecycle_state": lifecycle,
        "status": status,
        "terminal_class": terminal_class,
        "failure": failure,
        "failure_stage": result.get("failure_stage", ""),
        "quality": dict(quality),
        "gates": dict(result.get("gates", {})),
        "provenance_diagnostic": dict(result.get("provenance_diagnostic", {})),
        "evidence_class": result.get("evidence_class", "not_tested" if lifecycle == "not_started" else "live_measurement"),
        "canonical_aggregate_eligible": result.get("canonical_aggregate_eligible", True),
        "exclusion_reason": result.get("exclusion_reason", ""),
        "provider_invocation_status": provider_status,
        "provider_invocation_events": list(result.get("provider_invocation_events", ())),
        "provider_request_events": list(result.get("provider_request_events", ())),
        "provider_evidence_paths": list(result.get("provider_evidence_paths", ())),
        "provider_evidence_errors": list(result.get("provider_evidence_errors", ())),
        "provider_usage": result.get("provider_usage", {"status": "missing"}),
        "requested_seed": result.get("requested_seed", identity.seed),
        "effective_seed": result.get("effective_seed"),
        "seed_status": result.get("seed_status", "unsupported"),
        "provider_calls": result.get("provider_calls"),
        "retry_events": result.get("retry_events", []),
        "retry_count": result.get("retry_count"),
        "provider_latency_ms": result.get("provider_latency_ms"),
        "e2e_latency_ms": (ended_ns - started_ns) / 1_000_000.0 if ended_ns and started_ns else None,
        "evaluation_latency_ms": result.get("evaluation_latency_ms"),
        "embedding_latency_ms": result.get("embedding_latency_ms"),
        "tool_latency_ms": result.get("tool_latency_ms"),
        "writer_latency_ms": result.get("writer_latency_ms"),
        "worker_termination": result.get("worker_termination"),
        "late_result": result.get("late_result"),
        "output_path": result.get("output_path", ""),
        "report_path": result.get("report_path", ""),
        "runtime_root": result.get("runtime_root", ""),
        "workspace_root": result.get("workspace_root", ""),
        "memory_root": result.get("memory_root", ""),
        "started_at_ns": started_ns,
        "ended_at_ns": ended_ns,
    }


def _validate_served_model(models_payload: object, profile: Mapping[str, object]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    data = models_payload.get("data") if isinstance(models_payload, Mapping) else None
    models = [item for item in data if isinstance(item, Mapping)] if isinstance(data, list) else []
    ids = [str(item.get("id", "")) for item in models]
    expected_model = str(profile.get("model", ""))
    if len(models) != 1 or ids != [expected_model]:
        errors.append(f"served_model_mismatch:{ids!r}:{expected_model}")
        return ids, errors
    for key, observed_key in (("model_path", "root"), ("max_model_len", "max_model_len")):
        expected = str(profile.get(key, ""))
        observed = str(models[0].get(observed_key, ""))
        if not expected or observed != expected:
            errors.append(f"served_{key}_mismatch:{observed!r}:{expected!r}")
    return ids, errors


def _live_preflight(
    output_root: Path,
    embedding_device: str,
    *,
    timeout_s: float,
    require_codeact: bool,
) -> dict[str, object]:
    config = LLMConfig.from_runtime().with_mode("local_vllm")
    profile = _runtime_profile_snapshot(embedding_device, config)
    timeout_contract = _stage2_timeout_contract(config, stage2_timeout_s=timeout_s)
    errors: list[str] = []
    if not timeout_contract["passed"]:
        errors.append(
            "stage2_timeout_contract_too_small:"
            f"{timeout_s:.3f}<{float(timeout_contract['required_stage2_timeout_s']):.3f}"
        )
    if not config.use_api:
        errors.append("llm_mode_not_api")
    provider = config.provider_config("default")
    base_url = str(provider.base_url or "").rstrip("/")
    expected_model = str(os.getenv("STATEBUS_LOCAL_VLLM_MODEL") or profile["model"])
    if not base_url:
        errors.append("missing_vllm_url")
    for role in ("planner", "retriever", "executor", "summarizer"):
        if str(config.role_config(role).model) != expected_model:
            errors.append(f"role_model_mismatch:{role}")
    observations: dict[str, object] = {}
    if require_codeact:
        try:
            readiness = CodeActSandboxRunner().check_llm_bwrap_readiness(refresh=True)
            observations["codeact_sandbox"] = {
                **readiness.canonical_payload(),
                "required": True,
                "readiness_digest": readiness.readiness_digest,
            }
            if not readiness.ready or readiness.actual_backend != "bwrap":
                errors.append(
                    "codeact_bwrap_not_ready:"
                    f"{readiness.actual_backend}:{readiness.reason or 'readiness_probe_failed'}"
                )
        except (OSError, RuntimeError) as exc:
            observations["codeact_sandbox"] = {
                "required": True,
                "ready": False,
                "actual_backend": "probe_error",
                "reason": f"{type(exc).__name__}:{exc}",
            }
            errors.append(f"codeact_bwrap_probe_error:{type(exc).__name__}:{exc}")
    else:
        observations["codeact_sandbox"] = {
            "required": False,
            "ready": None,
            "actual_backend": "not_probed",
            "reason": "selected_lanes_do_not_execute_codeact",
        }
    if base_url:
        try:
            health_url = os.getenv("STATEBUS_LOCAL_VLLM_HEALTH_URL", base_url.rsplit("/v1", 1)[0] + "/health")
            with urlopen(health_url, timeout=min(10.0, DEFAULT_TIMEOUT_S)) as response:
                observations["health_status"] = int(response.status)
            with urlopen(base_url + "/models", timeout=min(10.0, DEFAULT_TIMEOUT_S)) as response:
                models_payload = json.load(response)
            ids, model_errors = _validate_served_model(models_payload, profile)
            observations["models"] = ids
            observations["model_metadata"] = models_payload.get("data") if isinstance(models_payload, Mapping) else None
            errors.extend(model_errors)
        except (OSError, URLError, ValueError, KeyError) as exc:
            errors.append(f"service_probe:{type(exc).__name__}:{exc}")
    preflight = {
        "schema_version": "statebus.stage2_preflight.v2",
        "status": "passed" if not errors else "environment_fail",
        "profile": profile,
        "timeout_contract": timeout_contract,
        "observations": observations,
        "errors": errors,
    }
    _json(output_root / "preflight.json", preflight)
    if errors:
        raise RuntimeError("preflight_invalid:" + ";".join(errors))
    return preflight


def _invoke_lane(runners: Mapping[str, Callable[..., dict[str, object]]], *, lane: str, sample: Any, root: Path, seed: int, public_case: Mapping[str, Any], embedding_device: str, dry_run: bool) -> dict[str, object]:
    if dry_run:
        return _dry_run_case(sample, root, seed=seed, lane=lane, public_case=public_case)
    if lane == "adaptive_routed":
        return runners[lane](sample, root, seed=seed, public_case=public_case, embedding_device=embedding_device)
    return runners[lane](sample, root, seed=seed, public_case=public_case)


def run_stage2_pilot(*, output_root: Path, embedding_device: str = "cuda:0", timeout_s: float = DEFAULT_TIMEOUT_S, run_id: str | None = None, dry_run: bool = False, repeats: int = len(SEEDS), case_ids: tuple[str, ...] = (), family_ids: tuple[str, ...] = (), max_cases_per_family: int = 0, lane_ids: tuple[str, ...] = (), slot_manifest: Path | None = None, lane_runners: Mapping[str, Callable[..., dict[str, object]]] | None = None, strict_gates: bool | None = None, preflight: bool | None = None, process_deadline: bool | None = None) -> dict[str, object]:
    if timeout_s <= 0:
        raise ValueError("timeout_s_must_be_positive")
    if repeats < 1:
        raise ValueError("repeats_must_be_positive")
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"stage2_output_root_must_be_new_or_empty:{output_root}")
    else:
        output_root.mkdir(parents=True, exist_ok=False)
    run_id = run_id or output_root.name
    live_builtin = lane_runners is None and not dry_run
    strict = live_builtin if strict_gates is None else strict_gates
    do_preflight = live_builtin if preflight is None else preflight
    use_process = live_builtin if process_deadline is None else process_deadline
    registry = _select_samples()
    manifest_slots: list[dict[str, object]] | None = None
    if slot_manifest is not None:
        if case_ids or family_ids or lane_ids:
            raise ValueError("stage2_slot_manifest_cannot_mix_selection_filters")
        manifest_slots = _load_slot_manifest(slot_manifest, registry)
        manifest_case_ids = tuple(dict.fromkeys(str(item["case_id"]) for item in manifest_slots))
        selected = _filter_selected_samples(registry, case_ids=manifest_case_ids)
        selected_lanes = _filter_selected_lanes(
            tuple(dict.fromkeys(str(item["lane"]) for item in manifest_slots))
        )
    else:
        selected = _filter_selected_samples(
            registry,
            case_ids=case_ids,
            family_ids=family_ids,
            max_cases_per_family=max_cases_per_family,
        )
        selected_lanes = _filter_selected_lanes(lane_ids)
    preflight_report: dict[str, object] | None = None
    if do_preflight:
        preflight_report = _live_preflight(
            output_root,
            embedding_device,
            timeout_s=timeout_s,
            require_codeact=bool(
                {"fixed_structured", "adaptive_routed"}.intersection(selected_lanes)
            ),
        )

    public_cases: dict[str, dict[str, Any]] = {}
    public_source_closures: dict[str, list[str]] = {}
    for family, minimal, fixed in selected:
        minimal_case, minimal_closure = _stage2_public_case(minimal)
        fixed_case, fixed_closure = _stage2_public_case(fixed)
        if minimal_closure != fixed_closure:
            raise ValueError(
                f"public_source_closure_mismatch:{family}:{minimal_closure!r}:{fixed_closure!r}"
            )
        for field in ("case_id", "family", "request", "task_spec"):
            if minimal_case.get(field) != fixed_case.get(field):
                raise ValueError(f"public_case_representation_mismatch:{family}:{field}")
        public_cases[family] = minimal_case
        public_source_closures[family] = list(minimal_closure)
    projection_errors = {family: list(validate_public_case(case)) for family, case in public_cases.items()}
    if any(projection_errors.values()):
        raise ValueError(f"public_case_projection_invalid:{projection_errors}")

    profile = _runtime_profile_snapshot(embedding_device)
    profile_id = str(profile.get("profile_id") or "unconfigured-profile")
    identities: list[SlotIdentity] = []
    repeat_seeds = [SEEDS[index % len(SEEDS)] for index in range(repeats)]
    if manifest_slots is not None:
        selected_by_case = {
            str(minimal.task_id): minimal for _family_id, minimal, _fixed in selected
        }
        for item in manifest_slots:
            minimal = selected_by_case[str(item["case_id"])]
            identities.append(
                SlotIdentity(
                    run_id,
                    minimal.task_id,
                    str(getattr(minimal, "dataset_split", "")),
                    1,
                    int(item["repeat"]),
                    int(item["seed"]),
                    profile_id,
                    "provider_cache_uncontrolled",
                    str(item["lane"]),
                )
            )
    else:
        for _family_id, minimal, _fixed in selected:
            for repeat, seed in enumerate(repeat_seeds, start=1):
                for lane in selected_lanes:
                    identities.append(
                        SlotIdentity(
                            run_id,
                            minimal.task_id,
                            str(getattr(minimal, "dataset_split", "")),
                            1,
                            repeat,
                            seed,
                            profile_id,
                            "provider_cache_uncontrolled",
                            lane,
                        )
                    )
    planned_slots = [identity.__dict__ | {"pair_id": identity.pair_id, "slot_id": identity.slot_id} for identity in identities]
    manifest = {
        "schema_version": "statebus.stage2_pilot_manifest.v2",
        "run_id": run_id,
        "claim_scope": "bounded_repair_validation_only_no_superiority",
        "profile": profile,
        "families": [family for family, _m, _f in selected],
        "lanes": list(selected_lanes),
        "seeds": list(SEEDS),
        "repeat_seeds": repeat_seeds,
        "repeat_count": repeats,
        "selection": {
            "case_ids": list(case_ids),
            "family_ids": list(family_ids),
            "max_cases_per_family": max_cases_per_family,
            "lane_ids": list(selected_lanes),
            "independent_case_count": len(selected),
            "slot_manifest": str(slot_manifest) if slot_manifest is not None else "",
        },
        "concurrency": 1,
        "warmup_per_lane_family": 1,
        "timeout_s": timeout_s,
        "timeout_contract": (
            dict(preflight_report.get("timeout_contract", {}))
            if preflight_report is not None
            else {"status": "not_run"}
        ),
        "planned_slots": planned_slots,
        "public_cases": public_cases,
        "public_source_closures": public_source_closures,
        "cache_control": {
            "status": "uncontrolled",
            "regime": "provider_cache_uncontrolled",
            "cold_warm_claim": "not_supported",
        },
        "fixed_structured": {
            "provider_mode": "deterministic" if dry_run else "live",
            # Deterministic fixed runs are offline fixtures and must never be
            # admitted to the live aggregate.  Live fixed rows are eligible at
            # the manifest level; each row still has to pass its provider,
            # Runtime, schema, fairness and admission gates before it counts.
            "canonical_aggregate_eligible": not dry_run,
            "exclusion_reason": FIXED_AGGREGATE_EXCLUSION_REASON if dry_run else "",
        },
        "stop_conditions": {
            "warmup_failure": "record_and_continue",
            "required_gate_failure": "record_slot_and_continue",
            "deadline": "late_result_is_diagnostic_only",
        },
        "run_mode": "offline_validation" if dry_run else "live_measurement",
    }
    if manifest_slots is not None:
        manifest["slot_manifest"] = {
            "path": str(slot_manifest),
            "schema_version": "statebus.p1_missing_slots.v1",
            "slot_count": len(manifest_slots),
        }
    _json(output_root / "stage2_manifest.json", manifest)
    _json(output_root / "planned_slots.json", {"schema_version": "statebus.stage2_planned_slots.v2", "slots": planned_slots})

    rows: list[dict[str, object]] = []
    warmups: list[dict[str, object]] = []
    warmup_failures: list[dict[str, object]] = []
    requested_pairs = (
        {(str(item["family_key"]), str(item["lane"])) for item in manifest_slots}
        if manifest_slots is not None
        else None
    )
    runners = dict(lane_runners or {
        "direct_single_agent": _direct_case,
        "pure_text_mas": _pure_case,
        "fixed_structured": _fixed_case,
        "adaptive_routed": _adaptive_case,
    })

    for family_id, minimal_sample, fixed_sample in selected:
        for lane in selected_lanes:
            if requested_pairs is not None and (family_id, lane) not in requested_pairs:
                continue
            sample = fixed_sample if lane != "adaptive_routed" else minimal_sample
            warm_root = output_root / "warmups" / family_id / lane
            warm_root.mkdir(parents=True, exist_ok=True)
            _json(warm_root / "slot_plan.json", {"schema_version": "statebus.stage2_warmup_plan.v2", "run_id": run_id, "family_id": family_id, "lane": lane, "warmup": True, "planned": True})
            warm_start = time.monotonic_ns()
            warm_status, warm_error = "success", ""
            warm_result: dict[str, object] | None = None
            warm_quality: dict[str, object] | None = None
            _json(warm_root / "call-start.json", {"warmup": True, "family_id": family_id, "lane": lane, "started_at_ns": warm_start, "requested_seed": 0})
            fn = lambda sample=sample, warm_root=warm_root, lane=lane: _invoke_lane(
                runners,
                lane=lane,
                sample=sample,
                root=warm_root,
                seed=0,
                public_case=public_cases[family_id],
                embedding_device=embedding_device,
                dry_run=dry_run,
            )
            warm_result, error, _worker_started = _invoke_with_deadline(fn, timeout_s, process=use_process)
            if lane == "adaptive_routed" and error:
                warm_result = _adaptive_failure_evidence(warm_root, warm_result, seed=0)
            warm_status, _warm_lifecycle, warm_error, warm_quality, warm_result = _assess_result(
                lane=lane,
                sample=sample,
                result=warm_result,
                error=error,
                strict_gates=strict,
                offline=dry_run,
            )
            if warm_status not in {"success"}:
                warmup_failures.append(
                    {
                        "family_id": family_id,
                        "lane": lane,
                        "status": warm_status,
                        "error": warm_error,
                    }
                )
            warm_end = time.monotonic_ns()
            _json(warm_root / "call-end.json", {"warmup": True, "family_id": family_id, "lane": lane, "status": warm_status, "provider_started": bool(_provider_started(warm_result)), "ended_at_ns": warm_end, "error": warm_error})
            warmups.append({
                "family_id": family_id, "lane": lane, "warmup": True,
                "status": warm_status, "error": warm_error,
                "started_at_ns": warm_start, "ended_at_ns": warm_end,
                "quality": warm_quality,
                "gates": dict(warm_result.get("gates", {})) if warm_result else {},
                "provenance_diagnostic": dict(warm_result.get("provenance_diagnostic", {})) if warm_result else {},
                "output_path": warm_result.get("output_path", "") if warm_result else "",
                "report_path": warm_result.get("report_path", "") if warm_result else "",
                "provider_invocation_status": warm_result.get("provider_invocation_status", "not_started") if warm_result else "not_started",
                "provider_request_events": list(warm_result.get("provider_request_events", ())) if warm_result else [],
                "provider_evidence_paths": list(warm_result.get("provider_evidence_paths", ())) if warm_result else [],
                "provider_evidence_errors": list(warm_result.get("provider_evidence_errors", ())) if warm_result else [],
                "failure_stage": warm_result.get("failure_stage", "") if warm_result else "",
            })
            for identity in [item for item in identities if item.case_id == minimal_sample.task_id and item.lane == lane]:
                slot_root = output_root / "families" / family_id / lane / f"repeat-{identity.repeat}-seed-{identity.seed}"
                slot_root.mkdir(parents=True, exist_ok=True)
                _json(slot_root / "slot_plan.json", {"schema_version": "statebus.stage2_slot_plan.v2", **identity.__dict__, "pair_id": identity.pair_id, "slot_id": identity.slot_id, "planned": True})
                started = time.monotonic_ns()
                _json(slot_root / "call-start.json", {"slot_id": identity.slot_id, "started_at_ns": started, "requested_seed": identity.seed})
                sample_for_lane = fixed_sample if lane != "adaptive_routed" else minimal_sample
                status, failure, lifecycle, result, quality = "not_started", "", "not_started", None, {"passed": False, "failures": ["not_evaluated"]}
                fn = lambda sample=sample_for_lane, slot_root=slot_root, lane=lane, seed=int(identity.seed): _invoke_lane(
                    runners,
                    lane=lane,
                    sample=sample,
                    root=slot_root,
                    seed=seed,
                    public_case=public_cases[family_id],
                    embedding_device=embedding_device,
                    dry_run=dry_run,
                )
                result, error, _worker_started = _invoke_with_deadline(fn, timeout_s, process=use_process)
                if lane == "adaptive_routed" and error:
                    result = _adaptive_failure_evidence(slot_root, result, seed=int(identity.seed))
                status, lifecycle, failure, quality, result = _assess_result(
                    lane=lane,
                    sample=sample_for_lane,
                    result=result,
                    error=error,
                    strict_gates=strict,
                    offline=dry_run,
                )
                ended = time.monotonic_ns()
                _json(slot_root / "call-end.json", {"slot_id": identity.slot_id, "ended_at_ns": ended, "status": status, "provider_started": _provider_started(result), "error": failure})
                row = _slot_row(identity=identity, output_root=output_root, sample=sample_for_lane, status=status, lifecycle=lifecycle, result=result, failure=failure, started_ns=started, ended_ns=ended, quality=quality, slot_root=slot_root)
                _json(slot_root / "raw_row.json", row)
                rows.append(row)

    observed_ids = [str(row["slot_id"]) for row in rows]
    observed_set = set(observed_ids)
    sample_by_case = {minimal.task_id: minimal for _family, minimal, _fixed in selected}
    family_by_case = {minimal.task_id: family for family, minimal, _fixed in selected}
    for identity in identities:
        if identity.slot_id in observed_set:
            continue
        sample = sample_by_case[identity.case_id]
        slot_root = output_root / "families" / family_by_case[identity.case_id] / identity.lane / f"repeat-{identity.repeat}-seed-{identity.seed}"
        slot_root.mkdir(parents=True, exist_ok=True)
        row = _slot_row(
            identity=identity,
            output_root=output_root,
            sample=sample,
            status="not_started",
            lifecycle="not_started",
            result={},
            failure="not_started",
            started_ns=0,
            ended_ns=0,
            quality={"passed": False, "failures": ["not_started"]},
            slot_root=slot_root,
        )
        _json(slot_root / "slot_plan.json", {"schema_version": "statebus.stage2_slot_plan.v2", **identity.__dict__, "pair_id": identity.pair_id, "slot_id": identity.slot_id, "planned": True})
        _json(slot_root / "raw_row.json", row)
        rows.append(row)

    observed_ids = [str(row["slot_id"]) for row in rows]
    slot_set = compare_slot_sets([str(item["slot_id"]) for item in planned_slots], observed_ids)
    counts = {status: sum(row.get("terminal_class") == status for row in rows) for status in ACCOUNTING_CLASSES}
    started_count = sum(row.get("lifecycle_state") != "not_started" for row in rows)
    not_started_count = counts["not_started"]
    unknown_count = counts["unknown"]
    arithmetic_closed = bool(slot_set["closed"]) and len(rows) == len(planned_slots) and len(planned_slots) == started_count + not_started_count
    excluded_count = sum(1 for row in rows if row.get("canonical_aggregate_eligible") is False)
    denominator = {
        "schema_version": "statebus.stage2_pilot_denominator.v2",
        "planned_count": len(planned_slots),
        "observed_row_count": len(rows),
        "observed_slot_id_count": len(set(observed_ids)),
        "missing": slot_set["missing"],
        "extra": slot_set["extra"],
        "duplicate": slot_set["duplicate"],
        "started_count": started_count,
        "provider_started_count": sum(_provider_started(row) for row in rows),
        "settled_count": sum(row.get("lifecycle_state") == "settled" for row in rows),
        "not_started_count": not_started_count,
        "unknown_count": unknown_count,
        "terminal_class_counts": counts,
        "arithmetic_closed": arithmetic_closed,
        "unsupported_count": counts["unsupported"],
        "excluded_count": excluded_count,
        "exclusion_reasons": sorted({str(row.get("exclusion_reason")) for row in rows if row.get("exclusion_reason")}),
    }
    no_go_reasons: list[str] = []
    if not arithmetic_closed:
        no_go_reasons.append("denominator_not_closed")
    if any(counts[key] for key in ("quality_fail", "timeout", "runtime_fail", "environment_fail", "policy_reject", "unsupported", "unknown", "not_started")):
        no_go_reasons.append("terminal_or_evidence_failure")
    if warmup_failures:
        no_go_reasons.append("warmup_failure")
    if excluded_count:
        no_go_reasons.append("canonical_aggregate_exclusion")
    if dry_run:
        acceptance_status = "offline_validation"
        exit_code = EXIT_INCONCLUSIVE
    elif no_go_reasons:
        acceptance_status = "pilot_inconclusive"
        exit_code = EXIT_INCONCLUSIVE
    else:
        acceptance_status = "pilot_ready"
        exit_code = EXIT_READY
    acceptance = {
        "schema_version": "statebus.stage2_pilot_acceptance.v2",
        "status": acceptance_status,
        "exit_code": exit_code,
        "run_mode": "offline_validation" if dry_run else "live_measurement",
        "live_measurement": not dry_run,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "planned_slots": len(planned_slots),
        "observed_rows": len(rows),
        "warmup_rows": len(warmups),
        "warmup_failure_count": len(warmup_failures),
        "warmup_failures": warmup_failures,
        "denominator": denominator,
        "no_go_reasons": no_go_reasons,
        "claim_scope": "bounded_repair_validation_only_no_superiority",
    }
    _json(output_root / "warmups.json", warmups)
    _json(output_root / "raw_rows.json", rows)
    _json(output_root / "denominator.json", denominator)
    _json(output_root / "acceptance.json", acceptance)
    print(stable_json_dumps({"output_root": str(output_root), **acceptance}))
    return acceptance


def _write_interrupted_acceptance(output_root: Path, *, dry_run: bool) -> dict[str, object]:
    """Recompute partial slot accounting from artifacts already published."""

    artifact_errors: list[str] = []

    def load_mapping(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            artifact_errors.append(f"{path}:{type(exc).__name__}:{exc}")
            return None
        if not isinstance(payload, dict):
            artifact_errors.append(f"{path}:row_is_not_object")
            return None
        return payload

    planned_payload = load_mapping(output_root / "planned_slots.json") or {}
    planned_rows = planned_payload.get("slots", ())
    planned_ids = [
        str(item.get("slot_id", ""))
        for item in planned_rows
        if isinstance(item, Mapping) and str(item.get("slot_id", ""))
    ] if isinstance(planned_rows, list) else []

    observed_by_id: dict[str, dict[str, object]] = {}
    duplicate: list[str] = []
    for path in sorted(output_root.rglob("raw_row.json")):
        row = load_mapping(path)
        if row is None:
            continue
        slot_id = str(row.get("slot_id", ""))
        if not slot_id:
            artifact_errors.append(f"{path}:missing_slot_id")
            continue
        if slot_id in observed_by_id:
            duplicate.append(slot_id)
            continue
        observed_by_id[slot_id] = row

    started_ids: set[str] = set()
    for path in sorted(output_root.rglob("call-start.json")):
        event = load_mapping(path)
        if event is None:
            continue
        slot_id = str(event.get("slot_id", ""))
        if slot_id:
            started_ids.add(slot_id)

    planned_set = set(planned_ids)
    observed_set = set(observed_by_id)
    missing = sorted(planned_set - observed_set)
    not_started = sorted(planned_set - started_ids)
    unknown = sorted((planned_set & started_ids) - observed_set)
    extra = sorted(observed_set - planned_set)
    ordered_rows = [observed_by_id[slot_id] for slot_id in planned_ids if slot_id in observed_by_id]
    ordered_rows.extend(observed_by_id[slot_id] for slot_id in extra)
    denominator = {
        "schema_version": "statebus.stage2_pilot_denominator.v2",
        "partial": True,
        "planned_count": len(planned_ids),
        "observed_row_count": len(observed_by_id),
        "missing": missing,
        "extra": extra,
        "duplicate": sorted(set(duplicate)),
        "started_count": len(planned_set & started_ids),
        "not_started": not_started,
        "not_started_count": len(not_started),
        "unknown": unknown,
        "unknown_count": len(unknown),
        "arithmetic_closed": (
            len(planned_ids) == len(observed_by_id) + len(missing)
            and len(missing) == len(not_started) + len(unknown)
            and not extra
            and not duplicate
        ),
        "artifact_errors": artifact_errors,
    }
    acceptance = {
        "schema_version": "statebus.stage2_pilot_acceptance.v2",
        "status": "interrupted",
        "exit_code": EXIT_INTERRUPTED,
        "partial": True,
        "run_mode": "offline_validation" if dry_run else "live_measurement",
        "planned_slots": len(planned_ids),
        "observed_rows": len(observed_by_id),
        "missing": missing,
        "not_started": not_started,
        "unknown": unknown,
        "denominator": denominator,
        "no_go_reasons": ["interrupted_partial_run"],
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "claim_scope": "bounded_repair_validation_only_no_superiority",
    }
    _json(output_root / "raw_rows.json", ordered_rows)
    _json(output_root / "denominator.json", denominator)
    _json(output_root / "acceptance.json", acceptance)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded Stage 2 repair validation.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--embedding-device", default="cuda:0")
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--repeats", type=int, default=len(SEEDS), help="Repeats per family and lane; seeds cycle through 0 and 1.")
    parser.add_argument("--case-id", action="append", default=[], help="Select an exact independent case id; repeat for multiple cases.")
    parser.add_argument("--family-id", action="append", default=[], help="Select an exact Stage 2 family id; repeat for multiple families.")
    parser.add_argument("--lane", action="append", choices=LANES, default=[], help="Select an exact lane; repeat for multiple lanes. Empty keeps all lanes.")
    parser.add_argument("--slot-manifest", type=Path, help="Run exactly the canonical (case,lane,repeat,seed) slots in a v1 manifest.")
    parser.add_argument("--max-cases-per-family", type=int, default=0, help="Bound selected independent cases per family; 0 keeps all selected cases.")
    parser.add_argument("--run-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lock-file", type=Path, default=Path(os.getenv("STATEBUS_STAGE2_LOCK_FILE", "/tmp/statebus-stage2-pilot.lock")))
    args = parser.parse_args()
    lock_handle = None
    try:
        args.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = args.lock_file.open("a+")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError("stage2_client_lock_busy") from exc
            raise
        acceptance = run_stage2_pilot(
            output_root=args.output_root,
            embedding_device=args.embedding_device,
            timeout_s=args.timeout_s,
            repeats=args.repeats,
            case_ids=tuple(args.case_id),
            family_ids=tuple(args.family_id),
            max_cases_per_family=args.max_cases_per_family,
            lane_ids=tuple(args.lane),
            slot_manifest=args.slot_manifest,
            run_id=args.run_id,
            dry_run=args.dry_run,
            strict_gates=True,
            preflight=not args.dry_run,
            process_deadline=not args.dry_run,
        )
        raise SystemExit(int(acceptance["exit_code"]))
    except KeyboardInterrupt:
        if args.output_root.exists():
            _write_interrupted_acceptance(args.output_root, dry_run=args.dry_run)
        raise SystemExit(EXIT_INTERRUPTED)
    except (FileExistsError, ValueError, RuntimeError) as exc:
        if args.output_root.exists():
            _json(args.output_root / "preflight_error.json", {"status": "preflight_invalid", "error": f"{type(exc).__name__}: {exc}"})
        print(f"stage2 preflight invalid: {type(exc).__name__}: {exc}", file=os.sys.stderr)
        raise SystemExit(EXIT_PREFLIGHT_INVALID)
    finally:
        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()


if __name__ == "__main__":
    main()
