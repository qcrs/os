"""Canonical DSL caller with explicit legacy and mechanism_simple_v2 profiles.

Offline fixtures and live provider programs both enter RuntimeDriver. No service
startup, implicit task fallback, or claim of live success from offline results.
Use scripts/run_contest_dsl_mainchains.sh for the two live 12-round chains.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import time
import uuid

from openai import APITimeoutError

from statebus.benchmark.contest_dsl_taskpack import (
    CONTRACT_VERSION, PROFILES, SIMPLE_PROFILE, bind_inputs, generate_sealed, input_file_hashes,
    release_task, task_contract, tasks_for_family,
)
from statebus.benchmark.contest_dsl_scorer import score_rows
from statebus.benchmark.contest_dsl_metrics import collect_slot_metrics, write_reports
from statebus.benchmark.contest_dsl_transport import HandoffTransport
from statebus.benchmark.request_journal import JournalClient, append_event
from statebus.benchmark.contest_model_assist import (
    ContestModelAssistSettings,
    build_contest_model_assist_client,
    render_public_context,
)
from statebus.contracts import (
    AdaptiveTaskEnvelope, ArtifactVerificationDecision, ArtifactVerificationReceipt,
    CanonicalTaskSpec, CapabilityDescriptor, CapabilityQualityReport, Claim, ClaimSet,
    CodeGenerationPolicy,
    EvidenceRequest, ExecutionKind, PlanProposal, PlanStepProposal, ReplayClass,
    RiskClass, RuntimeIdentity, TaskContractIdentity, TransformProgram, TransformStep,
    WorkflowMode,
)
from statebus.refs import ExecutionArtifactRef
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.retrieval.corpus import CorpusTextFragment
from statebus.retrieval.pruning import DynamicPruningConfig
from statebus.runtime.adaptive_dispatcher import StoredAdaptiveArtifact
from statebus.runtime.adaptive_mainline import AdaptiveMainlineBindings, AdaptiveMainlineRequest
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.capability_validators import CapabilityValidatorRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.transform_dsl import TransformProgramValidator
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps
from statebus.runtime.model_assist import MODEL_ASSIST_PROFILES


OPERATIONS = ("filter_eq", "filter_in", "filter_range", "aggregate", "aggregate_grouped",
              "derive_safe", "compare_periods", "join_by_key", "rank", "percentile_nearest_rank", "sort", "select")
R12_BLOCKER = "cross_agent_memory_artifact_read_authority_not_closed"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _source_artifact(root, name, rows, identity, source_hashes):
    root.mkdir(parents=True, exist_ok=True)
    payload = stable_json_dumps(rows).encode("utf-8")
    path = root / f"{name}.json"
    path.write_bytes(payload)
    ref = f"source:{name}"
    grant_hash = sha256_digest({"source": ref, "identity": identity.canonical_payload(), "sources": source_hashes})
    lifecycle = ArtifactLifecycleManager()
    candidate = lifecycle.register_candidate(ExecutionArtifactRef(
        artifact_id=ref, task_id=identity.runtime_task_id, step_id="controller-source",
        artifact_type="json", root_id=str(root), relpath=path.name, blob_hash=sha256_digest(payload),
        size_bytes=len(payload), produced_by="released-input-binding", workspace_relpath=path.name,
        manifest_hash=sha256_digest(source_hashes), metadata={"session_id": identity.session_id,
            "attempt_id": "controller-source", "grant_hash": grant_hash, "source_files": source_hashes},
    ))
    artifact = lifecycle.mark_verified(candidate.artifact_id)
    receipt = ArtifactVerificationReceipt(
        artifact_id=ref, runtime_task_id=identity.runtime_task_id, run_id=identity.run_id,
        session_id=identity.session_id, producer_step_id=artifact.step_id,
        producer_attempt_id="controller-source", execution_binding_hash=grant_hash,
        capability_grant_hash=grant_hash, candidate_blob_hash=artifact.blob_hash,
        candidate_size_bytes=len(payload), validator_ids=(), validator_report_hashes=(),
        decision=ArtifactVerificationDecision.VERIFIED, reason="controller_bound_released_source",
    )
    artifact = replace(artifact, metadata={**artifact.metadata, "artifact_verification_receipt_hash": receipt.receipt_hash})
    return StoredAdaptiveArtifact(artifact, tuple(rows), tuple(source_hashes)), receipt


_PYTHON_CAPABILITY_ID = "execute_bounded_python_v2"


def _registry(contract, *, codeact_fallback_enabled: bool = False):
    registry = CapabilityRegistry()
    for capability, role, inputs, outputs, version, kind, validators in (
        ("dsl-retrieve", "retriever", (), ("canonical_evidence_pack",), "dsl-evidence-v1", ExecutionKind.RETRIEVAL_ADAPTER, ()),
        ("dsl-execute", "executor", ("execution_artifact", "canonical_evidence_pack"), ("execution_artifact",), contract.output_contract_version, ExecutionKind.TRANSFORM_DSL, ("contest-dsl-raw",)),
        ("dsl-report", "summarizer", ("execution_artifact", "canonical_evidence_pack"), ("execution_artifact",), "dsl-report-v1", ExecutionKind.RUNTIME_BUILTIN, ()),
    ):
        registry.register(CapabilityDescriptor(
            capability_id=capability, owner_role=role, description=f"Public DSL {role} boundary",
            input_ref_kinds=inputs, required_input_ref_kinds=inputs,
            input_contract_version="dsl-input-v1", output_ref_kinds=outputs,
            output_contract_version=version, execution_kind=kind,
            side_effect_class=RiskClass.WORKSPACE_WRITE if inputs else RiskClass.READ_ONLY,
            max_runtime_ms=20_000 if role == "retriever" else 600_000, supports_replay=role == "executor", validator_ids=validators,
        ))
    if codeact_fallback_enabled:
        registry.register(CapabilityDescriptor(
            capability_id=_PYTHON_CAPABILITY_ID,
            owner_role="executor",
            description=(
                "Generate and execute bounded Python for the same approved Contest39 analysis contract "
                "when the DSL attempt and its single repair are exhausted."
            ),
            input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
            required_input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.analysis_input.v2",
            output_ref_kinds=("execution_artifact",),
            output_contract_version=contract.output_contract_version,
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            max_runtime_ms=120_000,
            supports_replay=True,
            validator_ids=("contest-dsl-raw",),
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 100_000},
                "required_fields": {"type": "string_list", "min_items": 1, "max_items": 64},
            },
        ))
    return registry


DEFAULT_PROVIDER_TIMEOUT_S = 480.0
EXECUTOR_MAX_TOKENS = 3072
SUMMARIZER_MAX_TOKENS = 1536


class ProviderOutputTruncatedError(ValueError):
    """The provider ended a structured response at its token limit."""

    code = "provider_output_truncated"

    def __init__(self, role: str):
        self.role = role
        super().__init__(f"{self.code}:{role}:finish_reason=length")


class RepairProtocolViolation(ValueError):
    """A repair candidate did not preserve a contract-derived edit boundary."""

    code = "repair_protocol_violation"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"{self.code}:{detail}")


def _live_client(
    path,
    model,
    base_url,
    max_context,
    provider_timeout_s=DEFAULT_PROVIDER_TIMEOUT_S,
    *,
    model_assist_profile: str = "off",
    task_id: str = "",
    run_id: str = "",
    runtime_root: Path | None = None,
    shared_prefix_text: str = "",
):
    from statebus.integrations.llm import LLMConfig, ProviderConfig, RoleLLMConfig, build_llm_client
    provider_timeout_s = float(provider_timeout_s)
    if provider_timeout_s <= 0:
        raise ValueError("provider_timeout_s_must_be_positive")
    config = LLMConfig(mode="local_vllm", source="contest-dsl-fixed-budget",
        providers={"default": ProviderConfig(base_url=base_url, timeout_s=provider_timeout_s, request_max_attempts=1)},
        roles={role: RoleLLMConfig(model=model, temperature=0.0,
            max_tokens=EXECUTOR_MAX_TOKENS if role == "executor" else SUMMARIZER_MAX_TOKENS,
            max_context_tokens=max_context,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
            for role in ("planner", "retriever", "executor", "summarizer")})
    raw = build_llm_client(config)
    if model_assist_profile == "off":
        return JournalClient(raw, path)
    try:
        settings = ContestModelAssistSettings.from_enabled_inputs(
            profile=model_assist_profile,
            task_id=task_id or "contest-task",
            run_id=run_id or "contest-run",
            root=runtime_root or path.parent,
            model=model,
            base_url=base_url,
            max_context=max_context,
            provider_timeout_s=provider_timeout_s,
            shared_prefix_text=shared_prefix_text,
        )
        return build_contest_model_assist_client(raw, journal_path=path, settings=settings)
    except BaseException:
        close = getattr(raw, "close", None)
        if callable(close):
            close()
        raise


def _live_codeact_source(prompt: str, *, journal_path: Path | None = None) -> str:
    """Use the existing bounded-CodeAct raw source provider contract."""
    from statebus.benchmark.adaptive_formal_mainline import _complete_raw_code

    previous_journal = os.environ.get("STATEBUS_PROVIDER_JOURNAL")
    if journal_path is not None:
        os.environ["STATEBUS_PROVIDER_JOURNAL"] = str(journal_path)
    try:
        source, _model, _usage, _provider_event = asyncio.run(_complete_raw_code(prompt))
    finally:
        if previous_journal is None:
            os.environ.pop("STATEBUS_PROVIDER_JOURNAL", None)
        else:
            os.environ["STATEBUS_PROVIDER_JOURNAL"] = previous_journal
    return source


def _provider_json(client, role, payload, instruction, schema=None, *, model_assist_context=None):
    from statebus.integrations.llm import ChatMessage, extract_json_object
    context = {"role": role, **dict(model_assist_context or {})}
    messages = [ChatMessage("system", instruction), ChatMessage("user", stable_json_dumps(payload))]
    try:
        result = asyncio.run(client.complete(
            messages,
            purpose=role,
            **({"response_schema": schema} if schema else {}),
        ))
    except BaseException as exc:
        recorder = getattr(client, "observe_error", None)
        if callable(recorder):
            recorder(exc, context=context)
        raise
    recorder = getattr(client, "observe_result", None)
    if callable(recorder):
        recorder(result, context=context)
    if getattr(result, "finish_reason", None) == "length":
        raise ProviderOutputTruncatedError(role)
    return extract_json_object(result.text)


def _logical_program(program: TransformProgram, refs: dict[str, str]) -> TransformProgram:
    """Project a rejected Runtime program back to the provider's namespace."""
    names = {ref: name for name, ref in refs.items()}
    operations = []
    for operation in program.operations:
        args = dict(operation.arguments)
        if "right_ref" in args:
            args["right_ref"] = names[args["right_ref"]]
        operations.append(TransformStep(operation.op, args))
    return replace(program, input_artifact_refs=tuple(names[ref] for ref in program.input_artifact_refs),
                   operations=tuple(operations))


def _bind_provider_program(raw: dict, refs: dict[str, str], output_contract: str) -> TransformProgram:
    """Bind only the declared logical names, without accepting physical aliases."""
    if tuple(raw["input_artifact_refs"]) != tuple(refs):
        raise ValueError("provider_logical_input_bindings_mismatch")
    if raw["output_contract_version"] != output_contract:
        raise ValueError("provider_output_contract_mismatch")
    operations = []
    for item in raw["operations"]:
        args = dict(item["arguments"])
        if "right_ref" in args:
            if args["right_ref"] not in refs:
                raise ValueError("provider_unauthorized_right_ref")
            args["right_ref"] = refs[args["right_ref"]]
        operations.append(TransformStep(item["op"], args))
    return TransformProgram("model-program", tuple(refs.values()), tuple(operations), output_contract)


def _generation_metrics(root: Path) -> dict:
    path = root / "generation-events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return {"executor_generation_count": len(events),
            "executor_repair_count": sum(event["repair"] for event in events)}


_REPAIR_ERROR_GUIDANCE = {
    "unknown_column": (
        "Every referenced column must exist in the current sequential pipeline; do not use expressions or implicit field names. "
        "Use missing_referenced_columns and column_trace to identify the missing name at the failed operation. "
        "If an upstream aggregate already computes that metric under another name, rename its existing output and "
        "update all downstream references; apply required_aggregate_renames as an in-place edit; do not append a "
        "duplicate aggregate entry or duplicate any parallel value_fields/functions/outputs position. select cannot rename columns. "
        "aggregate_grouped emits only its grouping keys and aggregate outputs, so a later grouped aggregate replaces the "
        "earlier row schema; consolidate same-key sums and counts into one batch aggregate when later steps need all outputs. "
        "When required_program_edits is present, preserve every unlisted valid operation and aggregate entry; only the "
        "listed edits and their explicit reference_updates may change the rejected program."
    ),
    "invalid_aggregate_outputs": (
        "Use aggregate_output_issues (including duplicate_entries) to inspect duplicate names and parallel array lengths. outputs must contain "
        "one distinct name per aggregate entry, disjoint from group_fields. Rename or remove redundant entries "
        "while keeping value_fields/functions/outputs aligned, and update downstream references. Do not append "
        "the same aggregation again to rename an existing output; delete the redundant position from all three parallel arrays. "
        "When required_program_edits is present, apply its exact in-place array edit and preserve the parallel-array lengths; "
        "do not rename or add any unlisted valid aggregate entry."
    ),
    "invalid_aggregate_functions": (
        "The grouped aggregate parallel arrays value_fields/functions/outputs must have equal lengths and functions must be one of "
        "sum, mean, min, max, or count. Repair the existing arrays in place, preserving one aligned entry per position; do not append "
        "a second entry to rename an existing output. Use aggregate_output_issues for the exact array lengths."
    ),
    "invalid_aggregate_value_fields": (
        "Every grouped aggregate value_fields entry must be a non-empty authorized column name. Keep value_fields/functions/outputs "
        "parallel and aligned, and repair the existing entry rather than appending a duplicate aggregation."
    ),
    "derive_output_collision": (
        "A derive output must be a new column name, distinct from all columns visible before that calculation. "
        "Use colliding_derive_outputs to locate its earlier declaration. If the public formula requires the "
        "derived value, remove the redundant upstream aggregate entry or give that intermediate a distinct name; "
        "keep value_fields/functions/outputs aligned. Changing the final select cannot fix an earlier collision. "
        "Do not delete a required calculation merely to make validation pass. Preserve all unlisted valid operations "
        "and aggregate entries; apply only required_program_edits and their explicit reference_updates."
    ),
    "invalid_derive_calculation": "Each calculations item is [new_output, kind, left_column, right_column_or_scalar, optional_scale, optional_decimals]; it has 4 to 6 items.",
    "invalid_derive_numeric_format": "For less_than/greater_than/boolean_change the calculation has exactly 4 items; omit scale and decimals, and use an existing column or scalar as the right operand.",
    "invalid_derive_operand": "A derive right operand is either an existing column name or a finite numeric scalar; expressions and null placeholders are invalid.",
    "invalid_derive_kind": (
        "derive_safe supports only difference, ratio, pct_change, less_than, greater_than, and boolean_change. "
        "count is an aggregate function, not a derive kind; put a count item in the same aggregate_grouped batch "
        "as the other grouped metrics, using a repeated value_fields entry when needed."
    ),
    "invalid_grouped_aggregate_arguments": (
        "aggregate_grouped has exactly one API. The multi-column form must contain exactly group_fields, value_fields, "
        "functions, and outputs; do not include group_field or value_field with it. Every outputs[i] must be a distinct "
        "final column name, and when a source metric is itself required by output_schema (for example cost_cny), use that "
        "exact name and reference it downstream. Put grouped counts in this same batch (repeat the counted value field); "
        "do not add a second grouped aggregate or a derive_safe count. A repair must replace the rejected argument shape, "
        "not repeat it."
    ),
    "provider_logical_input_bindings_mismatch": "Copy authorized_input_refs exactly, in the same order, using logical names rather than source: physical aliases.",
    "join_output_collision": "Join on every shared identity key using matching left_keys/right_keys with no prefix; identical shared join keys are not duplicated. If a right_prefix is used, it prefixes EVERY right column, including join keys, and all downstream references must use those names. Preserve required output_schema names within the operation budget.",
    "schema": (
        "Final fields must exactly match output_schema: missing/unexpected list the mismatch. "
        "The final operation must be select(columns=output_schema keys in order); select projects existing names and cannot rename or alias a column. "
        "Reserve one operation slot for that final select and merge compatible derive_safe calculations into one ordered calculations array when needed. "
        "In aggregate_grouped, when a value_field is itself a required final field, outputs[i] must use that exact final field name "
        "(for example value_field=cost_cny requires outputs[i]=cost_cny, never sum_cost_cny); update every downstream reference. "
        "A replacement identical to the rejected program does not fix this error."
    ),
}


def _repair_error_key(error: object) -> str:
    """Collapse row-index noise while preserving the substantive error."""
    text = str(error)
    parts = text.split(":", 2)
    if len(parts) == 3 and parts[0] in {"schema", "value"} and parts[1].isdigit():
        return f"{parts[0]}:*:{parts[2]}"
    return text


def _compact_repair_errors(errors) -> tuple[str, ...]:
    """Return provider-facing validation errors without equivalent row repeats."""
    compact = []
    seen = set()
    for error in errors:
        key = _repair_error_key(error)
        if key in seen:
            continue
        seen.add(key)
        compact.append(str(error))
    return tuple(compact)


def _repair_error_details(errors) -> list[str]:
    details = []
    seen = set()
    for error in errors:
        code = str(error).split(":", 1)[0]
        guidance = _REPAIR_ERROR_GUIDANCE.get(code, "Re-check the documented operation argument contract and preserve all valid dependent operations.")
        if guidance in seen:
            continue
        seen.add(guidance)
        details.append(guidance)
    return details


def _repair_column_trace(program: TransformProgram, input_schemas: dict[str, dict[str, str]]) -> list[dict]:
    """Show the provider the names its prior program made visible at each step."""
    validator = TransformProgramValidator()
    available = {name: tuple(schema) for name, schema in input_schemas.items()}
    columns = set(available[program.input_artifact_refs[0]])
    trace = []
    for index, step in enumerate(program.operations):
        error = validator._validate_arguments(step, columns, program.input_artifact_refs, available)
        trace.append({"index": index, "op": step.op, "input_columns": sorted(columns),
                      "error": error or None})
        if error:
            break  # Later columns cannot be inferred from an invalid operation.
        columns = validator._output_columns(step, columns, available)
        trace[-1]["output_columns"] = sorted(columns)
    return trace


def _aggregate_output_name_constraints(program: TransformProgram, output_schema: dict[str, str]) -> list[dict]:
    """Expose exact names required for aggregate metrics that survive to output."""
    constraints = []
    derived_outputs = set()
    for step in program.operations:
        if step.op == "derive_safe":
            calculations = step.arguments.get("calculations", [[step.arguments.get("output")]])
            derived_outputs.update(calculation[0] for calculation in calculations
                                   if isinstance(calculation, (list, tuple)) and calculation
                                   and isinstance(calculation[0], str))
    for index, step in enumerate(program.operations):
        if step.op != "aggregate_grouped" or "group_fields" not in step.arguments:
            continue
        value_fields = step.arguments.get("value_fields", ())
        functions = step.arguments.get("functions", ())
        outputs = step.arguments.get("outputs", ())
        for value_field, function, output in zip(value_fields, functions, outputs):
            value_field = str(value_field)
            # Repeated sums or counts do not establish a unique final metric.
            if (value_field not in output_schema or value_field in derived_outputs or function != "sum"
                    or sum(v == value_field and f == "sum" for v, f in zip(value_fields, functions)) != 1):
                continue
            output = str(output)
            constraints.append({
                "operation_index": index,
                "value_field": value_field,
                "function": str(function),
                "current_output": output,
                "required_final_name": value_field,
                "matches_required_final_name": output == value_field,
            })
    return constraints


def _required_aggregate_renames(program: TransformProgram, output_schema: dict[str, str]) -> list[dict]:
    """Describe safe, contract-derived aggregate name edits for a repair.

    This is feedback only. The provider still returns the complete replacement
    program and the Runtime validator remains authoritative. A rename is
    advertised only for a unique grouped sum whose source field is itself a
    required final field; no business value or task-specific answer is added.
    """
    return [
        {
            "operation_index": item["operation_index"],
            "from": item["current_output"],
            "to": item["required_final_name"],
            "value_field": item["value_field"],
            "function": item["function"],
            "action": "rename_existing_output_in_place",
            "update_downstream_references": True,
            "do_not_append_parallel_entry": True,
        }
        for item in _aggregate_output_name_constraints(program, output_schema)
        if not item["matches_required_final_name"]
    ]


def _parallel_aggregate_entries(step: TransformStep) -> list[dict] | None:
    """Return aligned batch-aggregate entries, or None for an ambiguous shape."""
    if step.op != "aggregate_grouped" or "group_fields" not in step.arguments:
        return None
    values = step.arguments.get("value_fields")
    functions = step.arguments.get("functions")
    outputs = step.arguments.get("outputs")
    if not all(isinstance(value, (list, tuple)) for value in (values, functions, outputs)):
        return None
    if not (len(values) == len(functions) == len(outputs)):
        return None
    if any(not isinstance(value, str) for value in values):
        return None
    if any(not isinstance(function, str) for function in functions):
        return None
    if any(not isinstance(output, str) for output in outputs):
        return None
    return [
        {"position": position, "value_field": value, "function": function, "output": output}
        for position, (value, function, output) in enumerate(zip(values, functions, outputs))
    ]


def _derive_calculations(step: TransformStep) -> list[tuple[int, list | tuple]]:
    """Expose derive calculations with their original positions."""
    calculations = step.arguments.get("calculations")
    if isinstance(calculations, (list, tuple)):
        return [(index, calculation) for index, calculation in enumerate(calculations)
                if isinstance(calculation, (list, tuple))]
    if all(key in step.arguments for key in ("output", "kind", "numerator", "denominator")):
        return [(0, [step.arguments["output"], step.arguments["kind"],
                     step.arguments["numerator"], step.arguments["denominator"]])]
    return []


def _program_strings(value: object):
    """Yield string leaves with paths, for scoped downstream reference hints."""
    def walk(item, path):
        if isinstance(item, str):
            yield path, item
        elif isinstance(item, dict):
            for key, child in item.items():
                yield from walk(child, (*path, key))
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                yield from walk(child, (*path, index))
    yield from walk(value, ())


def _aggregate_reference_updates(
    program: TransformProgram,
    operation_index: int,
    source_name: str,
    target_name: str,
    *,
    stop_after_derive_output: str | None = None,
) -> list[dict]:
    """Describe exact downstream string paths that should follow an aggregate rename."""
    updates = []
    derived_name_seen = False
    for index in range(operation_index + 1, len(program.operations)):
        step = program.operations[index]
        if derived_name_seen:
            break
        if step.op == "derive_safe" and stop_after_derive_output is not None:
            calculations = step.arguments.get("calculations")
            if isinstance(calculations, (list, tuple)):
                for calculation_index, calculation in enumerate(calculations):
                    if not isinstance(calculation, (list, tuple)) or len(calculation) < 4:
                        continue
                    # Only operands are references to the old aggregate. The
                    # calculation output itself is a declaration and must not
                    # be renamed.
                    for operand_index in (2, 3):
                        if calculation[operand_index] == source_name:
                            updates.append({
                                "operation_index": index,
                                "path": ["arguments", "calculations", calculation_index, operand_index],
                                "from": source_name, "to": target_name,
                            })
                    if calculation[0] == stop_after_derive_output:
                        derived_name_seen = True
                        break
                continue
            if step.arguments.get("output") == stop_after_derive_output:
                for key in ("numerator", "denominator"):
                    if step.arguments.get(key) == source_name:
                        updates.append({
                            "operation_index": index,
                            "path": ["arguments", key],
                            "from": source_name, "to": target_name,
                        })
                derived_name_seen = True
                continue
        for path, value in _program_strings(step.arguments):
            if value != source_name:
                continue
            # If the aggregate name is also the output of a derive calculation,
            # only operands before that new declaration are references to the
            # aggregate. Later uses of the same spelling refer to the derived
            # value and must remain unchanged.
            if derived_name_seen:
                continue
            updates.append({"operation_index": index, "path": ["arguments", *path],
                            "from": source_name, "to": target_name})
    return updates


def _safe_intermediate_name(value_field: str, function: str, occupied: set[str]) -> str:
    """Choose a deterministic non-contract name for an intermediate aggregate."""
    candidates = [f"{function}_{value_field}", f"{value_field}_{function}", f"{value_field}_intermediate"]
    for candidate in candidates:
        if candidate and candidate not in occupied:
            return candidate
    base = f"{value_field}_{function}_intermediate"
    suffix = 2
    candidate = base
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _derive_collision_program_edits(
    program: TransformProgram,
    output_schema: dict[str, str],
    collisions: list[dict],
) -> list[dict]:
    """Describe safe aggregate edits for derive names predeclared upstream.

    A colliding aggregate is deleted only when an identical source/function
    entry remains and no downstream reference depends on the colliding output.
    Otherwise the existing entry is renamed to a deterministic intermediate;
    no new parallel-array entry is ever suggested.
    """
    edits = []
    occupied = set(output_schema)
    derived_outputs = {item["output"] for item in collisions if isinstance(item.get("output"), str)}
    for step in program.operations:
        entries = _parallel_aggregate_entries(step)
        if entries:
            occupied.update(entry["output"] for entry in entries)
        for _, calculation in _derive_calculations(step):
            if calculation and isinstance(calculation[0], str):
                occupied.add(calculation[0])

    seen_positions = set()
    for collision in collisions:
        operation_index = collision.get("prior_declaration", {}).get("operation_index")
        calculation_index = collision.get("calculation_index")
        if not isinstance(operation_index, int) or not (0 <= operation_index < len(program.operations)):
            continue
        step = program.operations[operation_index]
        entries = _parallel_aggregate_entries(step)
        if entries is None:
            continue
        output = collision.get("output")
        matches = [entry for entry in entries if entry["output"] == output]
        if len(matches) != 1:
            continue
        entry = matches[0]
        position = entry["position"]
        position_key = (operation_index, position)
        if position_key in seen_positions:
            continue
        seen_positions.add(position_key)
        duplicates = [candidate for candidate in entries
                      if candidate["position"] != position
                      and candidate["value_field"] == entry["value_field"]
                      and candidate["function"] == entry["function"]]
        # Prefer a non-colliding entry with the required final name. Otherwise
        # one unique non-colliding duplicate is still a safe canonical source.
        canonical = [candidate for candidate in duplicates
                     if candidate["output"] not in derived_outputs
                     and candidate["output"] in output_schema]
        if not canonical:
            canonical = [candidate for candidate in duplicates if candidate["output"] not in derived_outputs]
        if len(canonical) == 1:
            canonical_output = canonical[0]["output"]
            reference_updates = _aggregate_reference_updates(
                program, operation_index, output, canonical_output,
                stop_after_derive_output=output,
            )
            edits.append({
                "kind": "delete_parallel_array_position",
                "operation_index": operation_index,
                "arrays": ["value_fields", "functions", "outputs"],
                "position": position,
                "reason": "duplicate_aggregate_entry_predeclares_derive_output",
                "preserve_parallel_array_alignment": True,
                "update_downstream_references": bool(reference_updates),
                **({"reference_updates": reference_updates} if reference_updates else {}),
                "do_not_append_parallel_entry": True,
            })
            continue
        target = _safe_intermediate_name(entry["value_field"], entry["function"], occupied)
        occupied.add(target)
        reference_updates = _aggregate_reference_updates(
            program, operation_index, output, target,
            stop_after_derive_output=output,
        )
        edits.append({
            "kind": "replace_parallel_array_value",
            "operation_index": operation_index,
            "array": "outputs",
            "position": position,
            "from": output,
            "to": target,
            "reason": "aggregate_output_predeclares_derive_output",
            "update_downstream_references": True,
            "reference_updates": reference_updates,
            "do_not_append_parallel_entry": True,
            "preserve_parallel_array_lengths": True,
        })
    return sorted(
        edits,
        key=lambda item: (item.get("operation_index", -1), item.get("position", -1)),
        reverse=True,
    )


def _duplicate_aggregate_program_edits(program: TransformProgram) -> list[dict]:
    """Delete only duplicate aggregate entries with identical semantics."""
    edits = []
    for operation_index, step in enumerate(program.operations):
        entries = _parallel_aggregate_entries(step)
        if entries is None:
            continue
        by_output = {}
        for entry in entries:
            by_output.setdefault(entry["output"], []).append(entry)
        for output, duplicates in by_output.items():
            if len(duplicates) < 2:
                continue
            first = duplicates[0]
            if any((entry["value_field"], entry["function"]) !=
                   (first["value_field"], first["function"]) for entry in duplicates[1:]):
                # Same output spelling with different semantics is ambiguous;
                # expose the validator issue but do not guess which one wins.
                continue
            for entry in duplicates[1:]:
                edits.append({
                    "kind": "delete_parallel_array_position",
                    "operation_index": operation_index,
                    "arrays": ["value_fields", "functions", "outputs"],
                    "position": entry["position"],
                    "reason": "duplicate_aggregate_output_same_semantics",
                    "duplicate_output": output,
                    "preserve_parallel_array_alignment": True,
                    "update_downstream_references": False,
                    "do_not_append_parallel_entry": True,
                })
    return sorted(
        edits,
        key=lambda item: (item.get("operation_index", -1), item.get("position", -1)),
        reverse=True,
    )


def _apply_program_edits_to_aggregate_entries(program: TransformProgram, edits: list[dict]) -> dict[int, list[dict]]:
    """Project feedback edits onto aggregate entries for subsequent constraints."""
    projected = {}
    for operation_index, step in enumerate(program.operations):
        entries = _parallel_aggregate_entries(step)
        if entries is not None:
            projected[operation_index] = [dict(entry) for entry in entries]
    for edit in sorted(
        edits,
        key=lambda item: (item.get("operation_index", -1), item.get("position", -1)),
        reverse=True,
    ):
        operation_index = edit.get("operation_index")
        entries = projected.get(operation_index)
        if entries is None:
            continue
        position = edit.get("position")
        if not isinstance(position, int) or not (0 <= position < len(entries)):
            continue
        if edit.get("kind") == "delete_parallel_array_position":
            entries.pop(position)
        elif edit.get("kind") == "replace_parallel_array_value":
            entries[position]["output"] = edit.get("to", entries[position]["output"])
    return projected


def _required_final_aggregate_edits(
    program: TransformProgram,
    output_schema: dict[str, str],
    prior_edits: list[dict],
) -> list[dict]:
    """Add exact final-name edits after safe collision edits are projected."""
    projected = _apply_program_edits_to_aggregate_entries(program, prior_edits)
    derived_outputs = set()
    for step in program.operations:
        if step.op != "derive_safe":
            continue
        for _, calculation in _derive_calculations(step):
            if calculation and isinstance(calculation[0], str):
                derived_outputs.add(calculation[0])
    edits = []
    for operation_index, entries in projected.items():
        for entry in entries:
            value_field = entry["value_field"]
            if (value_field not in output_schema or value_field in derived_outputs
                    or entry["function"] != "sum" or entry["output"] == value_field):
                continue
            matching = [candidate for candidate in entries
                        if candidate["value_field"] == value_field and candidate["function"] == "sum"]
            if len(matching) != 1:
                continue
            original_position = entry["position"]
            if any(edit.get("operation_index") == operation_index
                   and edit.get("position") == original_position
                   and edit.get("kind") == "replace_parallel_array_value"
                   and edit.get("to") == value_field for edit in prior_edits + edits):
                continue
            edits.append({
                "kind": "replace_parallel_array_value",
                "operation_index": operation_index,
                "array": "outputs",
                "position": original_position,
                "from": entry["output"],
                "to": value_field,
                "reason": "required_final_source_metric_name",
                "update_downstream_references": True,
                "reference_updates": _aggregate_reference_updates(
                    program, operation_index, entry["output"], value_field,
                ),
                "do_not_append_parallel_entry": True,
                "preserve_parallel_array_lengths": True,
            })
    return edits


def _columns_before_operation(
    program: TransformProgram,
    input_schemas: dict[str, dict[str, str]],
    operation_index: int,
) -> set[str] | None:
    """Best-effort column projection used only to prove a join edit is safe."""
    if not program.input_artifact_refs:
        return None
    first = program.input_artifact_refs[0]
    if first not in input_schemas:
        return None
    columns = set(input_schemas[first])
    available = {name: tuple(schema) for name, schema in input_schemas.items()}
    validator = TransformProgramValidator()
    for step in program.operations[:operation_index]:
        try:
            columns = set(validator._output_columns(step, columns, available))
        except (KeyError, TypeError, ValueError):
            return None
    return columns


def _required_join_program_edits(
    program: TransformProgram,
    input_schemas: dict[str, dict[str, str]],
    output_schema: dict[str, str],
) -> list[dict]:
    """Suggest removing a prefix when it would hide required RHS fields.

    The suggestion is emitted only for exact shared identity keys and when
    removing the prefix cannot create a non-key collision on the left side.
    """
    edits = []
    for operation_index, step in enumerate(program.operations):
        if step.op != "join_by_key":
            continue
        args = step.arguments
        prefix = args.get("right_prefix", "")
        right_ref = args.get("right_ref")
        if not isinstance(prefix, str) or not prefix or not isinstance(right_ref, str):
            continue
        right_schema = input_schemas.get(right_ref)
        if not isinstance(right_schema, dict):
            continue
        if "left_keys" in args or "right_keys" in args:
            left_keys, right_keys = args.get("left_keys"), args.get("right_keys")
        else:
            left_keys, right_keys = [args.get("left_key")], [args.get("right_key")]
        if (not isinstance(left_keys, (list, tuple)) or not isinstance(right_keys, (list, tuple))
                or not left_keys or len(left_keys) != len(right_keys)
                or any(not isinstance(left, str) or not isinstance(right, str)
                       or left != right for left, right in zip(left_keys, right_keys))):
            continue
        if any(key not in right_schema for key in right_keys):
            continue
        left_columns = _columns_before_operation(program, input_schemas, operation_index)
        if left_columns is None or any(key not in left_columns for key in left_keys):
            continue
        right_fields = set(right_schema)
        non_key_fields = right_fields - set(right_keys)
        if non_key_fields & left_columns:
            continue
        required_right_fields = sorted(non_key_fields & set(output_schema))
        if not required_right_fields:
            continue
        mapping = {}
        reference_updates = []
        for index in range(operation_index + 1, len(program.operations)):
            for path, value in _program_strings(program.operations[index].arguments):
                for field in right_fields:
                    source = prefix + field
                    if value == source:
                        target = field
                        mapping[source] = target
                        reference_updates.append({
                            "operation_index": index,
                            "path": ["arguments", *path],
                            "from": source,
                            "to": target,
                        })
        edits.append({
            "kind": "remove_join_right_prefix",
            "operation_index": operation_index,
            "from": prefix,
            "to": "",
            "required_right_fields": required_right_fields,
            "preserve_shared_join_keys": True,
            "update_downstream_references": mapping,
            "reference_updates": reference_updates,
            "reason": "right_prefix_would_hide_required_final_columns",
            "do_not_add_rename_operation": True,
        })
    return edits


def _program_path_value(value: object, path: list[object] | tuple[object, ...]) -> object:
    current = value
    for component in path:
        try:
            current = current[component]  # type: ignore[index]
        except (IndexError, KeyError, TypeError):
            raise RepairProtocolViolation(
                f"reference_path_missing:{stable_json_dumps(list(path))}"
            ) from None
    return current


def _set_program_path_value(
    value: object,
    path: list[object] | tuple[object, ...],
    replacement: object,
) -> None:
    if not path:
        raise RepairProtocolViolation("reference_path_empty")
    parent = value
    for component in path[:-1]:
        try:
            parent = parent[component]  # type: ignore[index]
        except (IndexError, KeyError, TypeError):
            raise RepairProtocolViolation(
                f"reference_path_missing:{stable_json_dumps(list(path))}"
            ) from None
    component = path[-1]
    try:
        parent[component] = replacement  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        raise RepairProtocolViolation(
            f"reference_path_not_writable:{stable_json_dumps(list(path))}"
        ) from None


def _repair_edit_source_entry(
    source_program: TransformProgram,
    edit: dict,
) -> tuple[int, dict, TransformStep]:
    operation_index = edit.get("operation_index")
    position = edit.get("position")
    if not isinstance(operation_index, int) or operation_index < 0 or operation_index >= len(source_program.operations):
        raise RepairProtocolViolation(f"edit_operation_index_invalid:{operation_index}")
    operation = source_program.operations[operation_index]
    entries = _parallel_aggregate_entries(operation)
    if entries is None:
        raise RepairProtocolViolation(f"edit_target_not_aligned_aggregate:{operation_index}")
    if not isinstance(position, int) or position < 0 or position >= len(entries):
        raise RepairProtocolViolation(f"edit_position_invalid:{operation_index}:{position}")
    return operation_index, entries[position], operation


def _apply_required_program_edits(
    program: TransformProgram,
    edits: list[dict] | tuple[dict, ...],
    *,
    source_program: TransformProgram | None = None,
) -> tuple[TransformProgram, tuple[dict, ...]]:
    """Apply only contract-derived mechanical repair edits to a provider candidate.

    The model remains responsible for the complete replacement program and for
    any semantic correction not mechanically proven by the contract.  These
    edits are the opposite boundary: their positions and references are
    derived by Runtime from the rejected program, so silently asking the model
    to reproduce them is not an adequate protocol.  The operation is strict
    and idempotent: an edit is either applied, already present, or rejected as
    a protocol violation.  No business formula, row value, or task identity is
    inferred here.
    """
    normalized_edits = tuple(dict(edit) for edit in edits)
    if not normalized_edits:
        return program, ()
    source = source_program or program
    operations = [TransformStep(step.op, deepcopy(step.arguments)) for step in program.operations]
    source_operations = source.operations
    applied: list[dict] = []

    # Array deletions must run from high to low positions.  This preserves the
    # original positional contract when a provider has not performed any of
    # the requested deletes yet.  Replacements and join edits are independent
    # of those array positions and run afterward.
    structural = [
        (index, edit) for index, edit in enumerate(normalized_edits)
        if edit.get("kind") in {
            "delete_parallel_array_position",
            "replace_parallel_array_value",
            "remove_join_right_prefix",
        }
    ]
    structural.sort(key=lambda item: (
        int(item[1].get("operation_index", -1)),
        0 if item[1].get("kind") == "delete_parallel_array_position" else 1,
        -int(item[1].get("position", -1))
        if item[1].get("kind") == "delete_parallel_array_position" else 0,
        item[0],
    ))

    for edit_index, edit in structural:
        kind = edit.get("kind")
        operation_index = edit.get("operation_index")
        if not isinstance(operation_index, int) or operation_index < 0 or operation_index >= len(operations):
            raise RepairProtocolViolation(f"edit_operation_index_invalid:{operation_index}")
        if operation_index >= len(source_operations):
            raise RepairProtocolViolation(f"source_edit_operation_index_invalid:{operation_index}")
        source_operation = source_operations[operation_index]
        candidate_operation = operations[operation_index]
        if candidate_operation.op != source_operation.op:
            raise RepairProtocolViolation(
                f"edit_operation_changed:{operation_index}:{source_operation.op}->{candidate_operation.op}"
            )

        if kind == "remove_join_right_prefix":
            if source_operation.op != "join_by_key":
                raise RepairProtocolViolation(f"edit_target_not_join:{operation_index}")
            source_prefix = source_operation.arguments.get("right_prefix", "")
            expected_prefix = edit.get("from", source_prefix)
            target_prefix = edit.get("to", "")
            if source_prefix != expected_prefix:
                raise RepairProtocolViolation(
                    f"join_prefix_source_mismatch:{operation_index}:{source_prefix!r}!={expected_prefix!r}"
                )
            current_prefix = candidate_operation.arguments.get("right_prefix", "")
            if current_prefix == expected_prefix:
                candidate_operation.arguments["right_prefix"] = target_prefix
                status = "applied"
            elif current_prefix == target_prefix:
                status = "already_applied"
            else:
                raise RepairProtocolViolation(
                    f"join_prefix_candidate_mismatch:{operation_index}:{current_prefix!r}"
                )
            applied.append({"edit_index": edit_index, "kind": kind, "status": status,
                            "operation_index": operation_index})
            continue

        source_index, source_entry, source_operation = _repair_edit_source_entry(source, edit)
        if source_index != operation_index or source_operation.op != "aggregate_grouped":
            raise RepairProtocolViolation(f"edit_target_not_grouped_aggregate:{operation_index}")
        candidate_entries = _parallel_aggregate_entries(candidate_operation)
        if candidate_entries is None:
            raise RepairProtocolViolation(f"candidate_target_not_aligned_aggregate:{operation_index}")
        arrays = {
            key: candidate_operation.arguments.get(key)
            for key in ("value_fields", "functions", "outputs")
        }
        if not all(isinstance(value, list) for value in arrays.values()):
            raise RepairProtocolViolation(f"candidate_parallel_arrays_invalid:{operation_index}")

        source_identity = (
            source_entry["value_field"], source_entry["function"], source_entry["output"]
        )

        if kind == "delete_parallel_array_position":
            source_semantics = (
                source_entry["value_field"], source_entry["function"]
            )
            source_semantic_count = sum(
                (entry["value_field"], entry["function"]) == source_semantics
                for entry in _parallel_aggregate_entries(source_operation) or ()
            )
            current_semantic_positions = [
                index for index, entry in enumerate(candidate_entries)
                if (entry["value_field"], entry["function"]) == source_semantics
            ]
            reason = str(edit.get("reason", ""))
            if reason == "duplicate_aggregate_output_same_semantics":
                # A provider may already have removed the requested duplicate;
                # compare semantic multiplicity before selecting an entry.
                if len(current_semantic_positions) == source_semantic_count:
                    target_positions = [
                        index for index in current_semantic_positions
                        if candidate_entries[index]["output"] == source_entry["output"]
                    ]
                    if not target_positions:
                        raise RepairProtocolViolation(
                            f"delete_target_missing:{operation_index}:{source_entry['output']}"
                        )
                    current_position = target_positions[-1]
                elif len(current_semantic_positions) == source_semantic_count - 1:
                    current_position = None
                else:
                    raise RepairProtocolViolation(
                        f"delete_duplicate_multiplicity_invalid:{operation_index}:{source_entry['output']}"
                    )
            else:
                target_positions = [
                    index for index in current_semantic_positions
                    if candidate_entries[index]["output"] == source_entry["output"]
                ]
                if len(current_semantic_positions) == source_semantic_count:
                    if len(target_positions) != 1:
                        raise RepairProtocolViolation(
                            f"delete_target_ambiguous:{operation_index}:{source_entry['output']}"
                        )
                    current_position = target_positions[0]
                elif (len(current_semantic_positions) == source_semantic_count - 1
                      and not target_positions):
                    current_position = None
                else:
                    raise RepairProtocolViolation(
                        f"delete_collision_multiplicity_invalid:{operation_index}:{source_entry['output']}"
                    )
            if current_position is not None:
                for key in arrays:
                    del arrays[key][current_position]
                status = "applied"
            else:
                status = "already_applied"
            applied.append({"edit_index": edit_index, "kind": kind, "status": status,
                            "operation_index": operation_index, "source_position": edit.get("position")})
            continue

        if kind != "replace_parallel_array_value":
            raise RepairProtocolViolation(f"unsupported_edit_kind:{kind}")
        expected_from = edit.get("from")
        expected_to = edit.get("to")
        if source_entry["output"] != expected_from or not isinstance(expected_to, str) or not expected_to:
            raise RepairProtocolViolation(
                f"replace_source_mismatch:{operation_index}:{source_entry['output']!r}->{expected_from!r}"
            )
        from_positions = [
            index for index, entry in enumerate(candidate_entries)
            if entry["value_field"] == source_entry["value_field"]
            and entry["function"] == source_entry["function"]
            and entry["output"] == expected_from
        ]
        to_positions = [
            index for index, entry in enumerate(candidate_entries)
            if entry["value_field"] == source_entry["value_field"]
            and entry["function"] == source_entry["function"]
            and entry["output"] == expected_to
        ]
        if len(from_positions) > 1 or len(to_positions) > 1:
            raise RepairProtocolViolation(
                f"replace_target_ambiguous:{operation_index}:{expected_from}->{expected_to}"
            )
        if from_positions:
            if to_positions:
                raise RepairProtocolViolation(
                    f"replace_from_and_to_both_present:{operation_index}:{expected_from}->{expected_to}"
                )
            arrays["outputs"][from_positions[0]] = expected_to
            status = "applied"
        elif to_positions:
            status = "already_applied"
        else:
            raise RepairProtocolViolation(
                f"replace_target_missing:{operation_index}:{expected_from}->{expected_to}"
            )
        applied.append({"edit_index": edit_index, "kind": kind, "status": status,
                        "operation_index": operation_index, "from": expected_from, "to": expected_to})

    # Reference updates are applied after structural edits.  They are
    # idempotent as well, which lets a provider perform a subset of the safe
    # changes without making Runtime guess whether a path moved.
    for edit_index, edit in enumerate(normalized_edits):
        updates = edit.get("reference_updates", ())
        if not isinstance(updates, (list, tuple)):
            raise RepairProtocolViolation(f"reference_updates_invalid:{edit_index}")
        for update in updates:
            if not isinstance(update, dict):
                raise RepairProtocolViolation(f"reference_update_invalid:{edit_index}")
            operation_index = update.get("operation_index")
            path = update.get("path")
            source_value = update.get("from")
            target_value = update.get("to")
            if (not isinstance(operation_index, int) or operation_index < 0
                    or operation_index >= len(operations)
                    or not isinstance(path, (list, tuple)) or not path
                    or path[0] != "arguments"):
                raise RepairProtocolViolation(f"reference_update_shape_invalid:{edit_index}")
            if operation_index >= len(source_operations):
                raise RepairProtocolViolation(f"reference_update_source_index_invalid:{operation_index}")
            current_operation = operations[operation_index]
            if current_operation.op != source_operations[operation_index].op:
                raise RepairProtocolViolation(f"reference_update_operation_changed:{operation_index}")
            nested_path = tuple(path[1:])
            current_value = _program_path_value(current_operation.arguments, nested_path)
            if current_value == source_value:
                _set_program_path_value(current_operation.arguments, nested_path, target_value)
                status = "applied"
            elif current_value == target_value:
                status = "already_applied"
            else:
                # A provider may legally reorder a select list or an
                # independent calculation while preserving the operation
                # contract.  The generated path is still the authority for
                # the value being changed, but it is not a stable list index
                # across that provider rewrite.  Relocate only when the old
                # value occurs exactly once in the candidate operation; any
                # ambiguity remains a protocol violation rather than a guess.
                candidate_paths = [
                    candidate_path for candidate_path, candidate_value
                    in _program_strings(current_operation.arguments)
                    if candidate_value == source_value
                ]
                if not candidate_paths:
                    target_paths = [
                        candidate_path for candidate_path, candidate_value
                        in _program_strings(current_operation.arguments)
                        if candidate_value == target_value
                    ]
                    if target_paths:
                        status = "already_applied"
                    else:
                        raise RepairProtocolViolation(
                            f"reference_update_value_missing:{operation_index}:{stable_json_dumps(list(path))}"
                        )
                elif len(candidate_paths) == 1:
                    _set_program_path_value(current_operation.arguments, candidate_paths[0], target_value)
                    status = "applied_relocated"
                else:
                    raise RepairProtocolViolation(
                        f"reference_update_value_ambiguous:{operation_index}:{stable_json_dumps(list(path))}"
                    )
            applied.append({"edit_index": edit_index, "kind": "reference_update", "status": status,
                            "operation_index": operation_index, "path": list(path),
                            "from": source_value, "to": target_value})

    return replace(program, operations=tuple(operations)), tuple(applied)


def _required_edit_surfaces_match(
    candidate: TransformProgram,
    mechanical: TransformProgram,
    edits: list[dict] | tuple[dict, ...],
) -> bool:
    """Check that a provider did not rewrite an edited structural surface.

    The provider may still make semantic changes on unedited operations.  For
    the mechanically proven surfaces, however, accepting an extra aggregate,
    changing an unlisted parallel entry, or retaining a prefix would make the
    repair nondeterministic.  Falling back to the source program plus the
    exact edits is the fair, task-independent behavior.
    """
    touched_operations = {
        edit.get("operation_index") for edit in edits
        if edit.get("kind") in {
            "delete_parallel_array_position",
            "replace_parallel_array_value",
            "remove_join_right_prefix",
        }
    }
    if any(not isinstance(index, int) or index < 0 for index in touched_operations):
        return False
    if len(candidate.operations) != len(mechanical.operations):
        return False
    for operation_index in touched_operations:
        if operation_index >= len(candidate.operations) or operation_index >= len(mechanical.operations):
            return False
        candidate_step = candidate.operations[operation_index]
        mechanical_step = mechanical.operations[operation_index]
        if candidate_step.op != mechanical_step.op:
            return False
        if candidate_step.op == "aggregate_grouped":
            for key in ("group_fields", "value_fields", "functions", "outputs"):
                if candidate_step.arguments.get(key) != mechanical_step.arguments.get(key):
                    return False
        elif candidate_step.op == "join_by_key":
            # Removing a prefix is the only mechanically authorized join edit.
            # Lock every other join argument so a provider cannot change the
            # RHS, key mapping, or key arity while appearing to apply the
            # required prefix edit.  Treat an omitted empty prefix and an
            # explicit empty prefix as equivalent, since both are the
            # canonical post-edit form.
            candidate_join = dict(candidate_step.arguments)
            mechanical_join = dict(mechanical_step.arguments)
            candidate_join.pop("right_prefix", None)
            mechanical_join.pop("right_prefix", None)
            if candidate_join != mechanical_join:
                return False
    return True


def _complete_grouped_repair_candidate(
    candidate: TransformProgram,
    previous_program: TransformProgram,
    input_schemas: dict[str, dict[str, str]],
    output_schema: dict[str, str],
    errors,
) -> TransformProgram | None:
    """Complete one narrowly provable grouped-repair shape.

    A malformed repair can collapse several single-column grouped aggregates
    into one valid batch aggregate but omit the final select or add diagnostic
    count columns.  Accept that shape only when the previous program contains
    nothing but grouped aggregates followed by optional sort/select operations,
    and the candidate's group fields and retained outputs exactly cover the
    public output schema.  Otherwise leave provider authority untouched.
    """
    if not any(str(error).split(":", 1)[0] == "invalid_grouped_aggregate_arguments" for error in errors):
        return None
    if len(candidate.operations) != 1 or candidate.operations[0].op != "aggregate_grouped":
        return None
    candidate_step = candidate.operations[0]
    candidate_args = candidate_step.arguments
    if set(candidate_args) != {"group_fields", "value_fields", "functions", "outputs"}:
        return None
    arrays = {key: candidate_args.get(key) for key in ("group_fields", "value_fields", "functions", "outputs")}
    if not all(isinstance(value, list) and value for value in arrays.values()):
        return None
    if len({len(arrays[key]) for key in ("value_fields", "functions", "outputs")}) != 1:
        return None

    aggregate_steps = []
    tail = []
    for step in previous_program.operations:
        if step.op == "aggregate_grouped":
            if "group_fields" in step.arguments:
                return None
            group_field = step.arguments.get("group_field")
            value_field = step.arguments.get("value_field")
            if not isinstance(group_field, str) or not isinstance(value_field, str):
                return None
            aggregate_steps.append(step)
        else:
            tail.append(step)
    if len(aggregate_steps) < 2 or not tail or tail[-1].op != "select":
        return None
    if any(step.op not in {"sort", "select"} for step in tail):
        return None

    group_fields = []
    for step in aggregate_steps:
        group_field = step.arguments["group_field"]
        if group_field not in group_fields:
            group_fields.append(group_field)
    if arrays["group_fields"] != group_fields:
        return None
    final_columns = tail[-1].arguments.get("columns")
    if not isinstance(final_columns, list) or final_columns != list(output_schema):
        return None

    available_fields = {field for schema in input_schemas.values() for field in schema}
    retained = []
    seen_outputs = set()
    for value_field, function, output in zip(
        arrays["value_fields"], arrays["functions"], arrays["outputs"]
    ):
        if (not isinstance(value_field, str) or value_field not in available_fields
                or function not in {"sum", "mean", "min", "max", "count"}
                or not isinstance(output, str) or output in group_fields
                or output not in final_columns or output in seen_outputs):
            continue
        retained.append((value_field, function, output))
        seen_outputs.add(output)
    required_outputs = set(final_columns) - set(group_fields)
    if seen_outputs != required_outputs:
        return None

    completed_arguments = {
        "group_fields": list(group_fields),
        "value_fields": [item[0] for item in retained],
        "functions": [item[1] for item in retained],
        "outputs": [item[2] for item in retained],
    }
    completed_operations = (TransformStep("aggregate_grouped", completed_arguments), *tail)
    return replace(candidate, operations=completed_operations)


def _required_program_edits(program: TransformProgram, output_schema: dict[str, str]) -> list[dict]:
    """Describe unambiguous mechanical edits without changing provider authority.

    The provider still returns a complete replacement program and the Runtime
    validator remains authoritative.  These edits are emitted only when the
    grouped aggregate has aligned parallel arrays, unique output names, and a
    single sum for a source field that is required unchanged by the public
    output contract.  Ambiguous programs deliberately receive prose guidance
    only rather than an unsafe guessed position.
    """
    # Collision edits are assembled by _repair_constraints, where the real
    # input schemas and validator trace are available. This helper retains the
    # existing public behavior for schema-only rename hints.
    edits = []
    for operation_index, step in enumerate(program.operations):
        entries = _parallel_aggregate_entries(step)
        if entries is None or len({entry["output"] for entry in entries}) != len(entries):
            continue
        for entry in entries:
            if (entry["value_field"] in output_schema and entry["function"] == "sum"
                    and entry["output"] != entry["value_field"]
                    and sum(candidate["value_field"] == entry["value_field"]
                            and candidate["function"] == "sum" for candidate in entries) == 1):
                edits.append({
                    "kind": "replace_parallel_array_value",
                    "operation_index": operation_index,
                    "array": "outputs",
                    "position": entry["position"],
                    "from": entry["output"],
                    "to": entry["value_field"],
                    "update_downstream_references": True,
                    "reference_updates": _aggregate_reference_updates(
                        program, operation_index, entry["output"], entry["value_field"],
                    ),
                    "do_not_append_parallel_entry": True,
                    "preserve_parallel_array_lengths": True,
                })
    return edits


def _derive_output_collisions(program: TransformProgram, trace: list[dict]) -> list[dict]:
    """Locate prior declarations without executing or repairing the program."""
    origins = {name: {"input_ref": program.input_artifact_refs[0]}
               for name in trace[0]["input_columns"]} if trace else {}
    collisions = []
    for entry in trace:
        index = entry["index"]
        step = program.operations[index]
        if step.op == "derive_safe":
            calculations = step.arguments.get("calculations", [[step.arguments.get("output")]])
            for calculation_index, calculation in enumerate(calculations):
                if not isinstance(calculation, (list, tuple)) or not calculation or not isinstance(calculation[0], str):
                    continue
                output = calculation[0]
                if output in origins:
                    collisions.append({"operation_index": index, "calculation_index": calculation_index,
                                       "output": output, "prior_declaration": origins[output]})
                else:
                    origins[output] = {"operation_index": index, "op": step.op,
                                       "calculation_index": calculation_index}
        if entry["error"]:
            break
        outputs = entry["output_columns"]
        if step.op in {"aggregate", "aggregate_grouped", "compare_periods", "percentile_nearest_rank"}:
            origins = {name: {"operation_index": index, "op": step.op} for name in outputs}
        else:
            origins = {name: origins.get(name, {"operation_index": index, "op": step.op}) for name in outputs}
    return collisions


def _repair_constraints(program: TransformProgram, input_schemas: dict[str, dict[str, str]],
                        output_schema: dict[str, str], errors) -> dict:
    trace = _repair_column_trace(program, input_schemas)
    constraints = {"column_trace": trace, "required_final_columns": list(output_schema)}
    constraints["aggregate_output_name_constraints"] = _aggregate_output_name_constraints(program, output_schema)
    constraints["required_aggregate_renames"] = _required_aggregate_renames(program, output_schema)
    collision_edits = []
    collision_details = []
    if trace and trace[-1]["error"] == "derive_output_collision":
        collision_details = _derive_output_collisions(program, trace)
        constraints["colliding_derive_outputs"] = collision_details
        collision_edits = _derive_collision_program_edits(program, output_schema, collision_details)
    duplicate_edits = _duplicate_aggregate_program_edits(program)
    required_program_edits = _required_program_edits(program, output_schema)
    required_program_edits = duplicate_edits + collision_edits + required_program_edits
    required_program_edits += _required_final_aggregate_edits(
        program, output_schema, required_program_edits,
    )
    required_program_edits += _required_join_program_edits(program, input_schemas, output_schema)
    # Keep feedback deterministic and avoid duplicate suggestions when a
    # collision edit and a final-name edit describe the same array position.
    unique_edits = []
    seen_edit_keys = set()
    for edit in required_program_edits:
        key = stable_json_dumps(edit)
        if key in seen_edit_keys:
            continue
        seen_edit_keys.add(key)
        unique_edits.append(edit)
    if unique_edits:
        constraints["required_program_edits"] = unique_edits
    if trace and trace[-1]["error"] == "unknown_column":
        failed = trace[-1]
        args = program.operations[failed["index"]].arguments
        references = []
        for key in ("column", "columns", "group_by", "group_field", "period_field", "value_field",
                    "ticker_field", "metric_field", "left_key", "left_keys", "numerator", "denominator",
                    "source", "carry_fields", "tie_break_columns", "group_fields", "value_fields"):
            value = args.get(key)
            if isinstance(value, str):
                references.append(value)
            elif isinstance(value, (list, tuple)):
                references.extend(str(item) for item in value)
        if program.operations[failed["index"]].op == "derive_safe":
            calculations = args.get("calculations", [[None, None, args.get("numerator"), args.get("denominator")]])
            visible = set(failed["input_columns"])
            missing_derive_columns = set()
            for calculation in calculations:
                if isinstance(calculation, (list, tuple)) and len(calculation) >= 4:
                    for name in calculation[2:4]:
                        if isinstance(name, str) and name not in visible:
                            missing_derive_columns.add(name)
                    if isinstance(calculation[0], str):
                        visible.add(calculation[0])
        else:
            missing_derive_columns = set()
        constraints["missing_referenced_columns"] = sorted(
            {name for name in references if isinstance(name, str) and name not in failed["input_columns"]}
            | missing_derive_columns)
    grouped_aggregate_errors = {
        "invalid_aggregate_outputs", "invalid_aggregate_functions", "invalid_aggregate_value_fields",
        "invalid_grouped_aggregate_arguments",
    }
    if trace and trace[-1]["error"] in grouped_aggregate_errors:
        index = trace[-1]["index"]
        args = program.operations[index].arguments
        outputs = args.get("outputs")
        positions = {}
        if isinstance(outputs, (list, tuple)):
            for position, name in enumerate(outputs):
                if isinstance(name, str):
                    positions.setdefault(name, []).append(position)
        constraints["aggregate_output_issues"] = {
            "operation_index": index,
            **({"validation_error": trace[-1]["error"]}
               if trace[-1]["error"] != "invalid_aggregate_outputs" else {}),
            "value_field_count": len(args["value_fields"]) if isinstance(args.get("value_fields"), (list, tuple)) else None,
            "function_count": len(args["functions"]) if isinstance(args.get("functions"), (list, tuple)) else None,
            "output_count": len(outputs) if isinstance(outputs, (list, tuple)) else None,
            "duplicate_outputs": [{"name": name, "positions": indices} for name, indices in positions.items()
                                  if len(indices) > 1],
        }
        if all(isinstance(args.get(key), (list, tuple)) for key in ("value_fields", "functions", "outputs")):
            values, functions = args["value_fields"], args["functions"]
            lengths = {key: len(args[key]) for key in ("value_fields", "functions", "outputs")}
            if len(set(lengths.values())) > 1:
                constraints["aggregate_output_issues"]["parallel_array_lengths"] = lengths
                constraints["aggregate_output_issues"]["parallel_array_length_mismatch"] = True
            constraints["aggregate_output_issues"]["duplicate_entries"] = [
                {
                    "position": position,
                    "value_field": values[position] if position < len(values) else None,
                    "function": functions[position] if position < len(functions) else None,
                    "output": outputs[position],
                    "same_as_first_position": position != indices[0],
                }
                for name, indices in positions.items() if len(indices) > 1
                for position in indices
            ]
    grouped_steps = []
    for index, step in enumerate(program.operations):
        if step.op != "aggregate_grouped":
            continue
        args = step.arguments
        group_fields = args.get("group_fields")
        if group_fields is None:
            group_fields = [args.get("group_field")]
        grouped_steps.append((index, tuple(str(field) for field in group_fields)))
    repeated_grouped = [
        {
            "prior_operation_index": prior_index,
            "operation_index": current_index,
            "group_fields": list(group_fields),
            "rule": (
                "aggregate_grouped replaces the current row schema with grouping keys and its aggregate outputs; "
                "consolidate same-key sums and counts into one batch operation, repeating value_fields for count."
            ),
        }
        for position, (prior_index, group_fields) in enumerate(grouped_steps)
        for current_index, current_fields in grouped_steps[position + 1:]
        if group_fields == current_fields
    ]
    invalid_derive_kinds = []
    allowed_derive_kinds = {"difference", "ratio", "pct_change", "less_than", "greater_than", "boolean_change"}
    for index, step in enumerate(program.operations):
        if step.op != "derive_safe":
            continue
        calculations = step.arguments.get("calculations")
        if calculations is None:
            calculations = [[step.arguments.get("output"), step.arguments.get("kind")]]
        for calculation_index, calculation in enumerate(calculations):
            if isinstance(calculation, (list, tuple)) and len(calculation) >= 2:
                kind = str(calculation[1])
                if kind not in allowed_derive_kinds:
                    invalid_derive_kinds.append({
                        "operation_index": index,
                        "calculation_index": calculation_index,
                        "kind": kind,
                        "rule": "count belongs to aggregate_grouped.functions, never derive_safe.kind",
                    })
    if repeated_grouped or invalid_derive_kinds:
        constraints["generic_structural_constraints"] = {
            "repeated_grouped_aggregates": repeated_grouped,
            "invalid_derive_kinds": invalid_derive_kinds,
        }
    if trace and trace[-1].get("output_columns") is not None and len(trace) == len(program.operations):
        final = set(trace[-1]["output_columns"])
        constraints["missing_final_columns"] = sorted(set(output_schema) - final)
        constraints["unexpected_final_columns"] = sorted(final - set(output_schema))
    for error in errors:
        if str(error).startswith("join_output_collision:"):
            index = int(str(error).split(":", 1)[1])
            if index >= len(trace) or program.operations[index].op != "join_by_key":
                continue
            args = program.operations[index].arguments
            right = set(input_schemas[args["right_ref"]])
            prefix = str(args.get("right_prefix", ""))
            left_keys = args.get("left_keys", [args.get("left_key")])
            right_keys = args.get("right_keys", [args.get("right_key")])
            common_keys = {left for left, right_key in zip(left_keys, right_keys)
                           if left == right_key and not prefix}
            constraints["colliding_join_columns"] = sorted(
                ({prefix + name for name in right} & set(trace[index]["input_columns"])) - common_keys)
            constraints["shared_join_keys"] = sorted(right & set(trace[index]["input_columns"]))
            break
    return constraints


def _handoff_transport(root: Path, variant: str, tokenizer_path: Path | None) -> HandoffTransport:
    counter = None
    if variant == "P-TEXT" and tokenizer_path is not None and (tokenizer_path / "tokenizer.json").is_file():
        from statebus.benchmark.contest_metrics import _tokenizer
        tokenizer = _tokenizer(str(tokenizer_path))
        counter = lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)
    return HandoffTransport(root / "handoffs.jsonl", mode="typed" if variant == "SB-FULL" else "text",
        token_counter=counter, tokenizer_name=f"{tokenizer_path}:local_no_special_tokens" if counter else None)


def _checked_report(claims, rows):
    """Exact row-level coverage in addition to the Runtime citation validator."""
    if len(claims) != len(rows):
        raise ValueError("report_row_count")
    for index, (claim, row) in enumerate(zip(claims, rows)):
        expected = {k: float(v) for k, v in row.items() if type(v) in (int, float)}
        if claim.numeric_fields != expected:
            raise ValueError(f"report_numeric_fields:{index}")
        # Structured verbatim row facts and complete source context are required;
        # arbitrary narrative is not treated as factual evidence.
        required = [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in row.items() if type(v) in (str, bool)]
        if any(token not in claim.claim_text for token in required):
            raise ValueError(f"report_row_identity_or_risk:{index}")


def _simple_report_claims(
    client,
    received,
    *,
    artifact_id: str,
    start: int,
    model_assist_context: dict[str, object] | None = None,
):
    """Typed fact report: validate model-selected rows and citations, then render.

    Identities belong to structured fields, not a second brittle key=value copy
    in prose. No missing fact, source qualification or Memory check is repaired
    or inserted on the model's behalf.
    """
    fields = {}
    for key, value in received["rows"][0].items():
        fields[key] = {"type": "boolean" if type(value) is bool else
                       "number" if type(value) in (int, float) else "string"}
    item_schema = {"type": "object", "additionalProperties": False,
        "required": ["row", "evidence_id", "context_text"], "properties": {
            "row": {"type": "object", "additionalProperties": False,
                    "properties": fields, "required": list(fields)},
            "evidence_id": {"type": "string", "enum": [e["id"] for e in received["evidence"]]},
            "context_text": {"type": "string", "enum": [e["text"] for e in received["evidence"]]}}}
    witness = received.get("memory_cross_check")
    if witness:
        item_schema["required"] += ["memory_id", "matches_memory"]
        item_schema["properties"].update(memory_id={"type": "string"}, matches_memory={"type": "boolean"})
    # This marker is intentionally scoped to the simplified Contest39 report
    # contract.  The provider keeps legacy summarizer JSON-object decoding for
    # other callers because older reports may contain negative fractional
    # values that vLLM 0.9.2's schema grammar rejects.
    schema = {"title": "statebus_simple_fact_report_v1",
        "type": "object", "additionalProperties": False, "required": ["claims"],
        "properties": {"claims": {"type": "array", "minItems": len(received["rows"]),
                                   "maxItems": len(received["rows"]), "items": item_schema}}}
    raw = _provider_json(client, "summarizer", received,
        "Produce a structured fact report, one claim per current row in input order. "
        "Copy every current row field into row; choose the matching entity's evidence_id and COMPLETE context_text. "
        "Do not infer causes. If memory_cross_check is supplied, independently compare each current row against "
        "its matching producer row, return memory_id and matches_memory. Never copy a producer report.", schema,
        model_assist_context=model_assist_context)
    if len(raw["claims"]) != len(received["rows"]):
        raise ValueError("report_row_count")
    claims = []
    for index, (item, expected) in enumerate(zip(raw["claims"], received["rows"])):
        row = item["row"]
        if row != expected or any((type(row[k]) is bool) != (type(v) is bool) for k, v in expected.items()):
            raise ValueError(f"report_row_values:{index}")
        source = next(e for e in received["evidence"] if e["id"] == item["evidence_id"])
        entity = row.get("unit_id", row.get("site_id"))
        if item["context_text"] != source["text"] or not source["text"].startswith(entity + " "):
            raise ValueError("report_context_or_entity_mismatch")
        text = " ".join(f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in row.items()) + ". " + item["context_text"]
        if witness:
            if item["memory_id"] != witness["memory_id"] or item["matches_memory"] is not True:
                raise ValueError("report_memory_cross_check_missing_or_rejected")
            if row not in witness["rows"]:
                raise ValueError("report_memory_cross_check_mismatch")
            text += f" memory_ref={item['memory_id']} producer_agent={witness['producer_agent']} consumer_agent=summarizer artifact_cross_check=verified_structured_artifact"
        claims.append(Claim(str(start+index), text, "fact", (source["id"],), (artifact_id,),
            (source["locator"],), {k: float(v) for k, v in row.items() if type(v) in (int, float)}))
    return claims


def _r12_source_task_id(task_id: str) -> str:
    """Return the round-10 producer task for the same business family."""
    return f"{task_id[0]}10"


def _select_r12_memory(memory_inputs, *, task_id: str) -> tuple[str, ...]:
    """Select one admitted round-10 producer Memory for the R12 consumer.

    The selector is deliberately narrow.  Runtime still owns the Grant and
    compatibility checks; this callback only chooses among already-granted
    descriptors and cannot manufacture a MemoryRef.
    """
    source_task_id = _r12_source_task_id(task_id)
    candidates = sorted(
        (
            item for item in memory_inputs
            if str(item.get("source_task_id", "")) == source_task_id
            and str(item.get("source_agent", "")) == "executor"
            and str(item.get("artifact_lineage", {}).get("artifact_ref_id", ""))
        ),
        key=lambda item: str(item.get("ref_id", "")),
    )
    if not candidates:
        raise ValueError(f"r12_cross_agent_memory_candidate_missing:{source_task_id}")
    return (str(candidates[0]["ref_id"]),)


def _r12_memory_witness(memory_inputs, memory_artifacts, *, task_id: str, output_schema: dict[str, str]) -> dict[str, object]:
    """Validate the structured producer artifact read used by the R12 report.

    Natural-language producer claims are never passed through this boundary.
    Only the Runtime-verified structured artifact rows and immutable identity
    metadata are exposed to the consumer callback.
    """
    if not memory_artifacts:
        raise ValueError("r12_memory_artifact_read_missing")
    selected = [
        item for item in memory_inputs
        if str(item.get("ref_id", "")) in memory_artifacts
    ]
    if len(selected) != 1:
        raise ValueError("r12_memory_selection_ambiguous")
    descriptor = selected[0]
    memory_id = str(descriptor["ref_id"])
    rows = tuple(dict(row) for row in memory_artifacts[memory_id])
    if not rows or any(set(row) != set(output_schema) for row in rows):
        raise ValueError("r12_memory_artifact_schema_mismatch")
    source_task_id = _r12_source_task_id(task_id)
    if str(descriptor.get("source_task_id", "")) != source_task_id:
        raise ValueError("r12_memory_producer_task_mismatch")
    source_agent = str(descriptor.get("source_agent", ""))
    if not source_agent or source_agent == "summarizer":
        raise ValueError("r12_memory_producer_consumer_identity_mismatch")
    lineage = descriptor.get("artifact_lineage", {})
    return {
        "memory_id": memory_id,
        "source_task_id": source_task_id,
        "producer_agent": source_agent,
        "consumer_agent": "summarizer",
        "artifact_ref_id": str(lineage.get("artifact_ref_id", "")),
        "artifact_hash": str(lineage.get("artifact_hash", "")),
        "manifest_hash": str(lineage.get("manifest_hash", "")),
        "row_count": len(rows),
        "schema": dict(output_schema),
        "rows": [dict(row) for row in rows],
        "use": "verified_structured_artifact_cross_check",
    }


def _build_codeact_fallback_plan(
    *,
    current_plan,
    completed_step_ids: tuple[str, ...],
    failed_step: PlanStepProposal,
    error_code: str,
    envelope: AdaptiveTaskEnvelope,
    registry: CapabilityRegistry,
    available_input_refs: dict[str, str],
):
    """Replace only the exhausted DSL executor with one fresh CodeAct step.

    The Runtime owns the retry lifecycle. This controller callback only builds
    and policy-validates the replacement plan; it does not carry the rejected
    DSL program or its diagnostics into the Python prompt.
    """
    if (
        failed_step.capability_id != "dsl-execute"
        or failed_step.on_failure != "request_replan"
        or not error_code.startswith("dsl_repair_exhausted:")
        or failed_step.step_id in completed_step_ids
        or not envelope.allow_llm_python
        or len(current_plan.steps) + 1 > envelope.max_total_attempts
    ):
        return None
    current_steps = {step.step_id: step for step in current_plan.steps}
    if current_steps.get(failed_step.step_id) != failed_step:
        return None
    fallback_step_id = f"{failed_step.step_id}-codeact-fallback"
    if fallback_step_id in current_steps:
        return None
    fallback_step = replace(
        failed_step,
        step_id=fallback_step_id,
        capability_id=_PYTHON_CAPABILITY_ID,
        output_contract_version=registry.get(_PYTHON_CAPABILITY_ID).output_contract_version,
        on_failure="fail",
    )
    replacement_steps = []
    for step in current_plan.steps:
        if step.step_id == failed_step.step_id:
            replacement_steps.append(fallback_step)
        elif failed_step.step_id in step.depends_on:
            replacement_steps.append(replace(
                step,
                depends_on=tuple(
                    fallback_step_id if dependency == failed_step.step_id else dependency
                    for dependency in step.depends_on
                ),
            ))
        else:
            replacement_steps.append(step)
    proposal = PlanProposal(
        proposal_id=f"{current_plan.source_proposal_id}-codeact-fallback-{failed_step.step_id}",
        task_id=current_plan.task_id,
        steps=tuple(replacement_steps),
        final_output_contract_version=current_plan.final_output_contract_version,
        requested_memory_policy=current_plan.requested_memory_policy,
        planner_notes="Runtime-authorized bounded-Python attempt after exhausted DSL repair.",
    )
    outcome = PlanPolicyValidator(
        registry, allow_llm_python=envelope.allow_llm_python,
    ).validate(
        proposal,
        envelope,
        available_input_refs=available_input_refs,
    )
    return outcome.approved_plan


def _run_slot(root: Path, public: Path, task_id: str, *, history: dict, variant: str,
             mode: str = "offline", model: str = "qwen3-32b", base_url: str = "http://127.0.0.1:53334/v1",
             max_context: int = 8192, embedding_mode: str = "deterministic", embedding_model=None,
             embedding_device=None, tokenizer_path: Path | None = None, profile: str = "default",
             provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
             memory_enabled: bool | None = None, semantic_state_mode: str | None = None,
             codeact_fallback_enabled: bool = False,
             model_assist_profile: str = "off", _client_holder: dict[str, object] | None = None):
    contract = task_contract(task_id, profile=profile)
    memory_override = memory_enabled is not None
    memory_enabled = variant == "SB-FULL" if memory_enabled is None else bool(memory_enabled)
    # Historical P-TEXT/SB-FULL defaults keep the existing lookup projection.
    # The mechanism runner passes an explicit override so its off control
    # disables query/consume/replay/commit as required by design 40.
    memory_query_enabled = memory_enabled if memory_override else True
    semantic_state_mode = ("on" if variant == "SB-FULL" else "off") if semantic_state_mode is None else semantic_state_mode
    if semantic_state_mode not in {"off", "on"}:
        raise ValueError(f"contest_dsl_semantic_state_mode_invalid:{semantic_state_mode}")
    if model_assist_profile not in MODEL_ASSIST_PROFILES:
        raise ValueError(f"contest_dsl_model_assist_profile_invalid:{model_assist_profile}")
    root.mkdir(parents=True, exist_ok=False)
    transport = _handoff_transport(root, variant, tokenizer_path)
    inputs = bind_inputs(public, task_id, history=history, profile=profile)
    hashes = input_file_hashes(public, task_id, profile=profile)
    # The exposed CSV is controller-selected from this round's released files.
    primary = next(name for name in contract.required_files if name.startswith(("actual_", "hourly_", "latency_samples_")))
    spec = CanonicalTaskSpec(task_family="continuous_csv_table_analysis", intent_op=contract.method,
        required_outputs=tuple(contract.output_schema), required_tools=("dsl",),
        arguments={"dataset_id": contract.family, "csv_path": str(public / contract.family / primary),
                   "periods": list(contract.periods)})
    run_id = "dsl-" + uuid.uuid4().hex[:12]
    identity = RuntimeIdentity(runtime_task_id=task_id, run_id=run_id, session_id=run_id,
        trace_id=run_id, task_contract=TaskContractIdentity.from_hash(spec.spec_hash))
    artifacts, receipts = {}, {}
    for name, rows in inputs.items():
        stored, receipt = _source_artifact(root / "source", name, rows, identity, hashes)
        artifacts[stored.artifact.artifact_id], receipts[stored.artifact.artifact_id] = stored, receipt
    write_json(root / "input-lineage.json", {"files": hashes,
        "history": {key: sha256_digest(history[key]) for key in contract.required_history},
        "artifacts": {key: asdict(value.artifact) for key, value in artifacts.items()},
        "verification_receipts": {key: asdict(value) for key, value in receipts.items()}})
    shared_prefix_text = render_public_context(contract.public_view(), task_id=task_id)
    if mode == "live":
        if model_assist_profile == "off":
            client = _live_client(root / "provider.jsonl", model, base_url, max_context, provider_timeout_s)
        else:
            client = _live_client(
                root / "provider.jsonl",
                model,
                base_url,
                max_context,
                provider_timeout_s,
                model_assist_profile=model_assist_profile,
                task_id=task_id,
                run_id=run_id,
                runtime_root=root,
                shared_prefix_text=shared_prefix_text,
            )
    else:
        client = None
    if _client_holder is not None:
        _client_holder["client"] = client
    write_json(root / "manifest.json", {"contract": contract.public_view(), "variant": variant,
        "mode": mode, "task_profile": profile, "runtime_identity": identity.canonical_payload(), "fixed_context_tokens": max_context,
        "executor_max_tokens": EXECUTOR_MAX_TOKENS, "summarizer_max_tokens": SUMMARIZER_MAX_TOKENS,
        "provider_timeout_s": provider_timeout_s,
        "codeact_fallback_enabled": bool(codeact_fallback_enabled),
        "model_assist_profile": model_assist_profile,
        "codeact_fallback_contract": (
            "one new bounded Python attempt after DSL initial and single repair are exhausted"
            if codeact_fallback_enabled else "disabled"
        ),
        "mechanism_configuration": {
            "transport": "typed" if variant == "SB-FULL" else "text",
            "memory": "on" if memory_enabled else "off",
            "semantic_state": semantic_state_mode,
            "model_assist_profile": model_assist_profile,
            "shared_public_context": (
                shared_prefix_text
                if model_assist_profile in {
                    "apc",
                    "kv_replay",
                    "kv_continuation",
                    "kv_logit",
                    "auto",
                }
                else None
            ),
            "model_assist_sidecar": str(root / "model-assist.jsonl") if model_assist_profile != "off" else None,
        },
        "request_max_attempts": 1, "dynamic_prompt_compression": False,
        "handoff_tokenizer_path": str(tokenizer_path) if tokenizer_path is not None else None,
        "planner": "deterministic_public_graph", "retriever": "registered_fanout",
        "report_contract": "simple_fact_report_v1" if profile == SIMPLE_PROFILE else "legacy_prose_report_v1",
        "provider": client.describe() if client else None})
    pipeline = RetrieverFanoutPipeline.with_embedding_mode(embedding_mode, model_path=embedding_model,
        device=embedding_device, top_k=4)
    pipeline.dynamic_pruning_config = DynamicPruningConfig(enabled=False)
    doc = pipeline.csv_corpus.resolve(dataset_id=contract.family, csv_path=spec.arguments["csv_path"])
    # Use real current contextual facts, with hashes and precise character spans.
    note_name = f"{'notes' if contract.family == 'finance' else 'events'}_{contract.periods[-1]}.md"
    note = (public / contract.family / note_name).read_text(encoding="utf-8")
    fragments = []
    for line in note.splitlines():
        if line.startswith(("U-", "S-")):
            start = note.index(line)
            fragments.append(CorpusTextFragment(note_name + "#" + line.split()[0], sha256_digest(note), line, start, start+len(line)))
    doc = replace(doc, source_doc_hash=sha256_digest((public / contract.family / primary).read_bytes()),
                  text_fragments=tuple(fragments))
    pipeline.csv_corpus._cache[f"{contract.family}:{spec.arguments['csv_path']}"] = doc
    policy = "validated_replay" if memory_enabled else "none"
    is_r12 = contract.round == 12
    is_r12_memory_consumer = is_r12 and memory_enabled
    registry = _registry(contract, codeact_fallback_enabled=codeact_fallback_enabled)
    validators = CapabilityValidatorRegistry()

    def validate(context):
        scored = score_rows(public, task_id, context.output_rows, profile=profile)
        equal = list(context.output_rows) == list(context.expected_rows)
        errors = tuple(scored["errors"]) + (() if equal else ("independent_dsl_recompute_mismatch",))
        return CapabilityQualityReport(capability_id=context.capability_id, validator_id=context.validator_id,
            input_artifact_hashes=context.input_artifact_hashes, output_artifact_hash=context.output_artifact_hash,
            schema_passed=not scored["errors"], recomputation_passed=not errors,
            provenance_passed=bool(context.provenance_item_ids), completion_criteria_passed=not errors,
            verified=not errors and bool(context.provenance_item_ids), error_codes=errors)

    validators.register("contest-dsl-raw", validate)

    def propose():
        def receive(payload):
            proposal = PlanProposal("dsl-public-plan", task_id, (
                PlanStepProposal("retrieve", "retriever", "dsl-retrieve", "Read current published facts", output_contract_version="dsl-evidence-v1"),
                PlanStepProposal("execute", "executor", "dsl-execute", payload["instructions"], depends_on=("retrieve",),
                    input_ref_ids=tuple(artifacts), input_ref_kinds=("execution_artifact",)*len(artifacts),
                    output_contract_version=contract.output_contract_version,
                    on_failure="request_replan" if codeact_fallback_enabled else "fail"),
                PlanStepProposal("summarize", "summarizer", "dsl-report", "Cite verified rows and current facts",
                    depends_on=("retrieve", "execute"), output_contract_version="dsl-report-v1"),
            ), "dsl-report-v1", requested_memory_policy=policy)
            write_json(root / "plan.json", proposal.canonical_payload())
            return proposal
        return transport.invoke("controller", "planner", "plan", contract.public_view(), receive)

    def retrieve(query, request):
        return transport.invoke("planner", "retriever", request.step_id,
            {"query": query, "files": list(hashes)}, lambda payload: pipeline.run(task_id=task_id, spec=spec,
                planner_scope_payload={"query_text": payload["query"]}, enabled_evidence_types=("table", "semantic_context")))

    def generate(
        step,
        grant,
        ref,
        rows,
        memory_inputs=(),
        *,
        input_tables,
        errors=(),
        previous_program=None,
        repair_stage="initial",
    ):
        del ref, rows, memory_inputs
        refs = {key.removeprefix("source:"): key for key in input_tables}
        provider_errors = _compact_repair_errors(errors)
        append_event(root / "generation-events.jsonl", {
            "event": "started", "repair": previous_program is not None, "stage": repair_stage,
            "validation_errors": list(errors),
            "previous_program_hash": previous_program.program_hash if previous_program is not None else None,
        })
        payload = {"contract": {key: value for key, value in contract.public_view().items() if key not in {"task_id", "round", "required_history"}},
                   "authorized_input_refs": list(refs),
                   "tables": {name: [dict(row) for row in input_tables[reference]] for name, reference in refs.items()},
                   "errors": list(provider_errors),
                   "output_naming_constraints": {
                       "select_cannot_rename": True,
                       "aggregate_value_field_final_name_rule": (
                           "For a single sum of a source field preserved as that same final metric (not count or a "
                           "downstream derived value), use its required final name; outputs[i] must be exactly the "
                           "same name as that required final field. Other intermediate aggregate outputs must not "
                           "predeclare names created by later derive_safe calculations. "
                           "select only projects existing names and cannot rename or alias columns."
                       ),
                   }}
        if previous_program is not None:
            logical = _logical_program(previous_program, refs)
            payload["repair_context"] = {
                "stage": repair_stage,
                "validation_errors": list(provider_errors),
                "validation_error_details": _repair_error_details(errors),
                "previous_program": logical.canonical_payload(),
                "previous_program_hash": logical.program_hash,
                "runtime_program_hash": previous_program.program_hash,
                **_repair_constraints(logical, contract.input_schemas, contract.output_schema, errors),
                "instruction": (
                    "Return a complete replacement for previous_program that differs from the rejected program. "
                    "Preserve authorized input refs and output contract; correct every reported error, "
                    "including dependent operations and final column names."
                    " When required_program_edits is present, treat it as the complete set of mechanical edits for the "
                    "identified structural issue: preserve every unlisted valid operation, array entry, and name, and "
                    "change only explicitly listed reference_updates in downstream arguments. Do not add extra aggregate "
                    "or count entries while applying a repair."
                    " Apply the generic structural constraints: grouped aggregation replaces the current row schema, "
                    "so same-key sums and counts must be one batch aggregate; count is an aggregate function, not a "
                    "derive_safe kind. Use colliding_derive_outputs when present to fix the earlier declaration, "
                    "not merely a downstream select. If required_aggregate_renames is present, apply each rename "
                    "to the existing parallel output entry exactly once and update every downstream reference; "
                    "never add a second entry for that rename. If required_program_edits is present, treat each item "
                    "as a positional edit to the existing program. For delete_parallel_array_position, delete the "
                    "same original position from value_fields, functions, and outputs (apply multiple deletes from "
                    "highest position to lowest) and do not append a replacement entry. For "
                    "replace_parallel_array_value, replace only the named outputs position, keep "
                    "value_fields/functions/outputs aligned and the same length, and follow reference_updates "
                    "exactly; when a colliding derive output is preserved, change only its earlier aggregate operand "
                    "references and keep the later derived output name. For remove_join_right_prefix, remove "
                    "right_prefix in place, preserve shared join keys, and apply the listed downstream reference "
                    "updates without adding a rename operation."
                ),
            }

        def receiver(received):
            repair_edits_applied = ()
            provider_program_hash = None
            if client is None:
                from statebus.benchmark.contest_dsl_fixtures import offline_program
                program = offline_program(contract, refs)
            else:
                from statebus.runtime.role_path import _operation_argument_contract, _transform_program_response_schema
                # Fixed schema plus one example per table; no dynamic compression,
                # no expected rows, no task-specific implementation prompt.
                request = {"contract": received["contract"], "authorized_input_refs": received["authorized_input_refs"], "tables": {
                    name: {"schema": contract.input_schemas[name], "row_count": len(table), "example": table[:1]}
                    for name, table in received["tables"].items()}, "errors": received["errors"],
                    "output_naming_constraints": received["output_naming_constraints"],
                    "operations": {op: _operation_argument_contract(op) for op in OPERATIONS}}
                if "repair_context" in received:
                    request["repair_context"] = received["repair_context"]
                raw = _provider_json(client, "executor", request,
                    "Return one JSON TransformProgram. Compose only documented generic operations. "
                    "Return compact JSON without markdown fences or insignificant indentation/newlines. "
                    "Copy authorized_input_refs in order into input_artifact_refs; use those logical table names in right_ref. Do not write Python or answers. "
                    "The program is a sequential pipeline: an operation may reference only columns produced by the "
                    "preceding operation. Intermediate columns are allowed and should have distinct names; aggregate "
                    "outputs replace the raw input columns for later operations. Pack dependent calculations into one "
                    "ordered derive_safe calculations array when useful. Omit absent optional tuple items rather than using "
                    "null placeholders; comparison calculations have exactly four items. Use ratio with scale 100 for a "
                    "percentage ratio, and reserve pct_change for (left-right)/right*100. The final operation MUST be select with exactly "
                    "the public output schema columns in contract order; reserve one operation slot for it. Pack compatible dependent "
                    "calculations into one ordered derive_safe calculations array so sorting, when needed, can appear immediately before select. "
                    "aggregate_grouped has two mutually exclusive forms: either the single-column "
                    "form with exactly group_field/value_field plus optional named outputs, or the batch form with exactly "
                    "group_fields/value_fields/functions/outputs. The batch form MUST NOT contain group_field or value_field. "
                    "A grouped aggregate emits only its grouping keys and aggregate outputs; a later grouped aggregate "
                    "replaces that row schema, so consolidate same-key sums and counts into one batch operation. "
                    "For a count, repeat the counted value in value_fields and use function=count; count is not a "
                    "derive_safe kind. "
                    "Each aggregate output is only the declared function of its one value_field; naming a sum after "
                    "a derived metric does not compute that metric. Do not add aggregate outputs for names that "
                    "later derive_safe calculations create; each derived name must be absent before its calculation. "
                    "For a summed source metric preserved unchanged in the final schema, use that required final name "
                    "and make every downstream derive/select reference the resulting name. "
                    "select only projects existing columns and cannot rename or alias. For joins with shared identity columns, use all shared keys in left_keys/right_keys "
                    "without a prefix so matching keys are not duplicated; a right_prefix renames ALL right columns. "
                    f"Maximum {contract.max_operations} operations. All supplied input tables must be declared, source first.",
                    _transform_program_response_schema(authorized_input_refs=tuple(refs),
                        input_schema={k: tuple(v) for k, v in contract.input_schemas.items()},
                        output_contract_version=contract.output_contract_version, operation_catalog=OPERATIONS),
                    model_assist_context={
                        "step": step.step_id,
                        "attempt": grant.attempt_id,
                        "stage": "generate",
                        "repair_stage": repair_stage,
                    })
                program = _bind_provider_program(raw, refs, grant.output_contract_version)
                provider_program_hash = program.program_hash
                completed_grouped_candidate = None
                if previous_program is not None:
                    completed_grouped_candidate = _complete_grouped_repair_candidate(
                        program,
                        previous_program,
                        contract.input_schemas,
                        contract.output_schema,
                        errors,
                    )
                if completed_grouped_candidate is not None:
                    program = completed_grouped_candidate
                    append_event(root / "repair-events.jsonl", {
                        "event": "repair_program_completed",
                        "stage": repair_stage,
                        "previous_program_hash": previous_program.program_hash,
                        "provider_program_hash": provider_program_hash,
                        "normalized_program_hash": program.program_hash,
                        "normalization_mode": "deterministic_grouped_repair_completion",
                        "normalization_reason": "provider_batch_omitted_final_select_or_extra_contract_columns",
                    })
                if previous_program is not None and received.get("repair_context", {}).get("required_program_edits"):
                    required_edits = received["repair_context"]["required_program_edits"]
                    mechanical_program, mechanical_edits_applied = _apply_required_program_edits(
                        previous_program,
                        required_edits,
                        source_program=previous_program,
                    )
                    normalization_mode = "provider_candidate"
                    normalization_reason = None
                    provider_protocol_violation = None
                    try:
                        normalized_provider_program, provider_edits_applied = _apply_required_program_edits(
                            program,
                            required_edits,
                            source_program=previous_program,
                        )
                    except RepairProtocolViolation as exc:
                        # A candidate that cannot be aligned to the
                        # contract-derived edit surface is untrusted.  The
                        # runtime already has a deterministic, task-agnostic
                        # source-plus-edits candidate, so use it instead of
                        # turning provider protocol drift into a task failure.
                        program = mechanical_program
                        repair_edits_applied = mechanical_edits_applied
                        normalization_mode = "deterministic_required_edits"
                        normalization_reason = "provider_protocol_violation"
                        provider_protocol_violation = str(exc)
                    else:
                        program = normalized_provider_program
                        repair_edits_applied = provider_edits_applied
                    if provider_protocol_violation is None and not _required_edit_surfaces_match(program, mechanical_program, required_edits):
                        # The provider changed an edited aggregate/join surface
                        # beyond the contract-derived allowlist (for example,
                        # by adding count entries while repairing a collision).
                        # Discard only those untrusted structural changes and
                        # use the deterministic source-plus-edits candidate.
                        program = mechanical_program
                        repair_edits_applied = mechanical_edits_applied
                        normalization_mode = "deterministic_required_edits"
                        normalization_reason = "provider_edit_surface_mismatch"
                    append_event(root / "repair-events.jsonl", {
                        "event": "required_program_edits_applied",
                        "stage": repair_stage,
                        "previous_program_hash": previous_program.program_hash,
                        "provider_program_hash": provider_program_hash,
                        "normalized_program_hash": program.program_hash,
                        "required_program_edits": required_edits,
                        "applied_edits": list(repair_edits_applied),
                        "normalization_mode": normalization_mode,
                        **({"normalization_reason": normalization_reason}
                           if normalization_reason else {}),
                        **({"provider_protocol_violation": provider_protocol_violation}
                           if provider_protocol_violation else {}),
                    })
            if previous_program is not None and program.program_hash == previous_program.program_hash:
                raise ValueError("provider_repair_no_change")
            if not codeact_fallback_enabled and (
                not 1 <= len(program.operations) <= contract.max_operations
                or any(op.op not in OPERATIONS for op in program.operations)
            ):
                # Preserve the frozen off-path behavior exactly.  The on-path
                # deliberately lets Runtime own this validation so its
                # existing DSL repair can reach the CodeAct replan boundary.
                raise ValueError("public_operation_budget_or_catalog_violation")
            append_event(root / "programs.jsonl", {
                "program": program.canonical_payload(),
                "program_hash": program.program_hash,
                "repair": bool(errors),
                "repair_edits_applied": list(repair_edits_applied),
            })
            return program
        return transport.invoke("retriever" if not errors else "runtime", "executor", step.step_id, payload, receiver)

    def repair(
        step,
        grant,
        ref,
        rows,
        errors,
        *,
        input_tables,
        previous_program,
        repair_stage,
    ):
        return generate(
            step,
            grant,
            ref,
            rows,
            input_tables=input_tables,
            errors=errors,
            previous_program=previous_program,
            repair_stage=repair_stage,
        )

    def report(step, grant, artifact, rows, evidence_pack, memory_inputs=(), *, memory_artifacts=None):
        evidence = [{"id": item.item_id, "locator": repr(item.locator), "text": item.rendered_text}
                    for item in evidence_pack.semantic_contexts if item.locator is not None]
        if not evidence:
            raise ValueError("report_current_context_missing")
        memory_witness = None
        if is_r12_memory_consumer:
            memory_witness = _r12_memory_witness(
                memory_inputs,
                memory_artifacts or {},
                task_id=task_id,
                output_schema=contract.output_schema,
            )
            if memory_witness["rows"] != [dict(row) for row in rows]:
                raise ValueError("r12_memory_artifact_values_mismatch")
            memory_witness["values_match"] = True
            write_json(root / "r12-memory-cross-check.json", {
                key: value for key, value in memory_witness.items() if key != "rows"
            })
        claims = []
        for start in range(0, len(rows), 4):
            batch = rows[start:start+4]
            payload = {"rows": list(batch), "evidence": evidence}
            if memory_witness is not None:
                # This is the verified structured artifact, not the producer's
                # final natural-language report.  The current rows remain the
                # only values accepted by the claim/scorer gate.
                payload["memory_cross_check"] = {
                    key: value for key, value in memory_witness.items()
                    if key != "rows"
                }
                payload["memory_cross_check"]["rows"] = memory_witness["rows"]

            def receiver(received):
                batch_claims = []
                if client is None:
                    for index, row in enumerate(received["rows"]):
                        entity = row.get("unit_id", row.get("site_id"))
                        source = next(item for item in received["evidence"] if item["text"].startswith(entity + " "))
                        text = " ".join(f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in row.items()) + ". " + source["text"]
                        if memory_witness is not None:
                            text += (
                                f" memory_ref={memory_witness['memory_id']}"
                                f" producer_agent={memory_witness['producer_agent']}"
                                " consumer_agent=summarizer"
                                " artifact_cross_check=verified_structured_artifact"
                            )
                        batch_claims.append(Claim(str(start+index), text, "fact", (source["id"],), (artifact.artifact_id,),
                            (source["locator"],), {k: float(v) for k, v in row.items() if type(v) in (int, float)}))
                elif profile == SIMPLE_PROFILE:
                    batch_claims = _simple_report_claims(
                        client,
                        received,
                        artifact_id=artifact.artifact_id,
                        start=start,
                        model_assist_context={
                            "step": step.step_id,
                            "attempt": grant.attempt_id,
                            "stage": "report",
                            "batch_index": start // 4,
                        },
                    )
                else:
                    raw = _provider_json(client, "summarizer", received,
                        'Return JSON {"claims":[{"text":"...","evidence_id":"...","numeric_fields":{...}}]}. One claim per row in input order. Include every string and boolean row field verbatim as key=value (lowercase booleans), all numeric fields with exact values in numeric_fields, and the COMPLETE current contextual sentence for that entity, including qualifications. Cite its evidence_id. When memory_cross_check is present, use it only as a verified structured-artifact cross-check; do not copy a producer report or replace current rows. Do not infer causes.',
                        model_assist_context={
                            "step": step.step_id,
                            "attempt": grant.attempt_id,
                            "stage": "report",
                            "batch_index": start // 4,
                        })
                    for index, item in enumerate(raw["claims"]):
                        source = next(e for e in received["evidence"] if e["id"] == item["evidence_id"])
                        batch_claims.append(Claim(str(start+index), item["text"], "fact", (source["id"],),
                            (artifact.artifact_id,), (source["locator"],), item["numeric_fields"]))
                _checked_report(batch_claims, received["rows"])
                for claim in batch_claims:
                    source = next(e for e in received["evidence"] if e["id"] in claim.supporting_evidence_item_ids)
                    if source["text"] not in claim.claim_text:
                        raise ValueError("report_context_qualification_missing")
                return batch_claims
            claims.extend(transport.invoke("executor", "summarizer", step.step_id, payload, receiver))
        return ClaimSet("claims-" + grant.attempt_id, grant.task_id, tuple(claims))

    allowed_capabilities = ("dsl-retrieve", "dsl-execute", "dsl-report")
    allowed_contracts = ("dsl-evidence-v1", contract.output_contract_version, "dsl-report-v1")
    if codeact_fallback_enabled:
        allowed_capabilities = (*allowed_capabilities, _PYTHON_CAPABILITY_ID)
    envelope = AdaptiveTaskEnvelope(
        task_id, spec.spec_hash, WorkflowMode.ADAPTIVE_BOUNDED,
        SIMPLE_PROFILE if profile == SIMPLE_PROFILE else CONTRACT_VERSION,
        allowed_capabilities, allowed_contracts,
        allowed_memory_policies=(policy,),
        role_cardinality={"retriever": (1,1), "executor": (1,1), "summarizer": (1,1)},
        max_plan_steps=3,
        max_retrieval_steps=1,
        max_total_attempts=4 if codeact_fallback_enabled else 3,
        max_execution_runtime_ms=1_220_000,
        **({"risk_class": RiskClass.BOUNDED_CODE, "allow_llm_python": True, "max_replans": 1}
           if codeact_fallback_enabled else {}),
    )
    request = AdaptiveMainlineRequest(trace_id=run_id, task_id=task_id, canonical_task_spec_hash=spec.spec_hash,
        canonical_task_spec=spec, runtime_identity=identity,
        envelope=envelope,
        registry=registry, runtime_root=root / "runtime", workspace_root=root / "workspaces", propose_plan=propose,
        bindings=AdaptiveMainlineBindings(
            semantic_state_mode=semantic_state_mode, memory_query_enabled=memory_query_enabled,
            validator_registry=validators, artifacts=artifacts, artifact_verification_receipts=receipts,
            retrieval_adapter=AdaptiveRetrievalAdapter(retrieve), allowed_corpus_scope_ids=(contract.family,),
            retrieval_request_factory=lambda step, grant: EvidenceRequest("request-"+task_id, task_id, step.step_id,
                (contract.method,), ("table", "semantic_context"), corpus_scope_ids=(contract.family,), memory_policy=policy),
            transform_program_factory=generate, transform_program_repair_factory=repair,
            output_schema_by_capability={_PYTHON_CAPABILITY_ID: contract.output_schema},
            output_schema_by_step={"execute": contract.output_schema}, claim_set_factory=report,
            code_source_factory=(
                (lambda _request, prompt: _live_codeact_source(prompt, journal_path=root / "provider.jsonl"))
                if codeact_fallback_enabled and mode == "live"
                else (lambda _request, _prompt: "")
            ),
            code_policy_factory=(
                lambda _step: CodeGenerationPolicy(
                    capability_id=_PYTHON_CAPABILITY_ID,
                    enabled=True,
                    require_bwrap=True,
                    allowed_module_roots=("json", "pathlib", "re", "statistics", "collections"),
                    allowed_input_relpaths=("inputs/task.json",),
                    output_relpath="outputs/result.json",
                    output_required_fields=tuple(contract.output_schema),
                    timeout_seconds=30.0,
                    max_output_bytes=1_048_576,
                    max_policy_repairs=0,
                    max_runtime_repairs=0,
                    max_quality_repairs=0,
                )
            ) if codeact_fallback_enabled else None,
            codeact_contracts=({
                _PYTHON_CAPABILITY_ID: {
                    "operation_semantics": {
                        "operation": contract.method,
                        "task_contract": contract.instructions,
                        "input_schema": contract.input_schemas,
                        "output_schema": contract.output_schema,
                    },
                    "quality_constraints": {
                        "benchmark_oracle_is_external_to_runtime": True,
                        "runtime_recomputation_from_authorized_inputs": True,
                        "finite_numbers_only": True,
                        "ordered_output_by": "period" if "period" in contract.output_schema else (
                            "unit_id" if "unit_id" in contract.output_schema else "site_id"
                        ),
                    },
                    "expected_output_shape": "array",
                }
            } if codeact_fallback_enabled else {}),
            claim_memory_selector=(
                (lambda memory_inputs: _select_r12_memory(memory_inputs, task_id=task_id))
                if is_r12_memory_consumer else None
            ),
            memory_assist_capability_ids=(
                ("dsl-report",) if is_r12_memory_consumer else ()
            )),
        available_input_refs={key: "execution_artifact" for key in artifacts}, state_pool_mode="mmap",
        memory_store_root=root.parent.parent / "memory", memory_commit_enabled=memory_enabled,
        memory_commit_replay_class=ReplayClass.VALIDATED_REPLAY,
        memory_topic=contract.family, memory_tags=(contract.family, contract.method),
        input_schema_digest=sha256_digest(contract.input_schemas),
        validator_digest=sha256_digest(Path(__file__).with_name("contest_dsl_scorer.py").read_bytes()),
        runtime_compatibility_signature=sha256_digest(Path(__file__).parents[1].joinpath("runtime/transform_dsl.py").read_bytes()))
    if codeact_fallback_enabled:
        def replan_for_codeact(current_plan, completed_step_ids, failed_step, error_code):
            disable_pair = getattr(client, "disable_pair", None)
            if callable(disable_pair):
                # The bounded Python replan is outside the DSL
                # Executor-to-Summarizer KV pair.  Release any producer
                # handle before Runtime starts the fresh attempt.
                disable_pair()
            return _build_codeact_fallback_plan(
                current_plan=current_plan,
                completed_step_ids=completed_step_ids,
                failed_step=failed_step,
                error_code=error_code,
                envelope=envelope,
                registry=registry,
                available_input_refs={key: "execution_artifact" for key in artifacts},
            )
        request = replace(request, replan_for_step=replan_for_codeact,
                          skip_memory_commit_on_replan=True)
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    for event in result.runtime.telemetry.events:
        append_event(root / "telemetry.jsonl", event.canonical_payload())
    context = result.context
    write_json(root / "runtime-evidence.json", {
        "completed": result.completed, "manifest_path": str(result.manifest_path),
        "grants": [asdict(bound) for bound in result.runtime.bound_grants],
        "memory_commit": result.memory_commit_decision.canonical_payload(),
        "memory_queries": {k: asdict(v) for k,v in context.memory_queries_by_task.items()},
        "memory_matches": {k: asdict(v) for k,v in context.memory_match_results.items()},
        "memory_reads": context.memory_read_evidence_by_id,
        "memory_consumption": [asdict(v) for v in context.memory_consumption_records],
        "recipes": context.execution_recipes_by_artifact,
        "state_consumers": context.semantic_consumer_receipts,
        "state_publications": {k: asdict(v) for k,v in context.semantic_state_publications.items()},
        "state_release_receipts": context.state_release_reclaim_receipts,
        "state_effects": context.downstream_effects,
        "activation": context.component_activation_receipts,
        "quality": {k: asdict(v) for k,v in context.quality_reports.items()},
        "artifact_receipts": {k: asdict(v) for k,v in context.artifact_verification_receipts.items()},
    })
    bound_capabilities = {
        bound.grant.attempt_id: bound.grant.capability_id
        for bound in result.runtime.bound_grants
    }
    completed_dispatches = [
        dispatch for dispatch in result.runtime.dispatches
        if (
            dispatch.state == "COMPLETED"
            and dispatch.output_refs
            and bound_capabilities.get(dispatch.attempt_id)
            in {"dsl-execute", _PYTHON_CAPABILITY_ID}
        )
    ]
    final_output = None
    if completed_dispatches:
        final_output = context.artifacts.get(completed_dispatches[-1].output_refs[0])
    rows = list(final_output.rows) if final_output is not None else []
    scored = score_rows(public, task_id, rows, profile=profile)
    write_json(root / "rows.json", rows)
    write_json(root / "scorer.json", scored)
    write_json(root / "report.json", {k: v.canonical_payload() for k,v in context.claim_sets.items()})
    _mechanism_events(
        root, result, variant=variant, task_id=task_id, memory_enabled=memory_enabled,
        codeact_fallback_enabled=codeact_fallback_enabled,
    )
    metrics = collect_slot_metrics(root) if client else {"provider_request_count": 0,
        "provider_observed_request_count": 0, "provider_prompt_tokens": None, "provider_completion_tokens": None,
        "provider_total_tokens": None, "provider_usage_missing_reason": "offline_no_model_calls"}
    metrics.update(_generation_metrics(root))
    requests = metrics["executor_generation_count"]
    metrics["executor_request_count"] = metrics.get("executor_request_count", 0) if client else 0
    gate = result.completed and scored["passed"]
    # Mechanism gates are only diagnosable after the business execution has
    # produced a verified result.  A failed execution cannot demonstrate a
    # replay/cross-agent read, but that absence is a consequence, not a
    # second root cause.  Keep the overall gate closed while avoiding
    # misleading cascading failure codes.
    mechanism_check_ready = gate
    mechanism_errors = []
    if contract.round == 11 and memory_enabled:
        replay_ok = requests == 0 and any(r.recipe_recomputed and r.attempt_result_admission_receipt_hash for r in context.memory_consumption_records)
        if mechanism_check_ready:
            if not replay_ok:
                mechanism_errors.append("r11_validated_replay_not_observed")
            gate = gate and replay_ok
    if is_r12_memory_consumer:
        memory_store = result.infrastructure.memory_store
        r12_records = [
            record for record in context.memory_consumption_records
            if record.consumer_step_id == "summarize"
            and bool(record.attempt_result_admission_receipt_hash)
        ]
        cross_agent_reads = []
        for record in r12_records:
            commit = memory_store.commits.get(record.memory_id) if memory_store is not None else None
            read = context.memory_read_evidence_by_id.get(record.memory_id, {})
            if commit is None:
                continue
            if (
                commit.memory_ref.source_agent
                and commit.memory_ref.source_agent != record.consumer_role
                and read.get("status") == "observed"
                and read.get("artifact_read") == "observed"
                and int(read.get("artifact_read_bytes", 0)) > 0
                and record.capability_grant_hash
                and record.memory_admission_receipt_hash
                and record.downstream_ref_ids
            ):
                cross_agent_reads.append(record)
        cross_agent_ok = bool(cross_agent_reads) and (root / "r12-memory-cross-check.json").is_file()
        if mechanism_check_ready:
            if not cross_agent_ok:
                mechanism_errors.append("r12_cross_agent_consumption_not_observed")
            gate = gate and cross_agent_ok
    runtime_dispatches = getattr(result.runtime, "dispatches", ())
    python_dispatches = [
        dispatch for dispatch in runtime_dispatches
        if bound_capabilities.get(dispatch.attempt_id) == _PYTHON_CAPABILITY_ID
    ]
    dsl_dispatches = [
        dispatch for dispatch in runtime_dispatches
        if bound_capabilities.get(dispatch.attempt_id) == "dsl-execute"
    ]
    fallback_attempted = bool(python_dispatches)
    return {"status": "success" if gate else "quality_fail" if result.completed else "runtime_fail",
            "quality": scored["passed"] and result.completed, "business_quality": scored["passed"] and result.completed, "returncode": 0 if gate else 1,
            "repair": metrics["executor_repair_count"], "metrics": metrics,
            "failure_codes": [record.error_code for record in result.runtime.dispatches if record.error_code] + mechanism_errors,
            "scorer_errors": scored["errors"], "mechanism_gate_passed": gate,
            "codeact_fallback_enabled": bool(codeact_fallback_enabled),
            "codeact_fallback_attempted": fallback_attempted,
            "codeact_python_attempts": len(python_dispatches),
            "dsl_execute_attempts": len(dsl_dispatches),
            "rows": rows}


def run_slot(root: Path, public: Path, task_id: str, **kwargs):
    """Run one slot and release any task-local model-assist resources."""
    holder: dict[str, object] = {}
    try:
        return _run_slot(root, public, task_id, _client_holder=holder, **kwargs)
    finally:
        client = holder.get("client")
        finalize = getattr(client, "finalize", None)
        if callable(finalize):
            try:
                finalize()
            except Exception:
                # Preserve the task result; the sidecar retains the per-call
                # evidence even when the optional APC observation cannot close.
                pass
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # Cleanup must never replace a Runtime/quality failure.
                pass


def _mechanism_events(root, result, *, variant: str, task_id: str,
                      memory_enabled: bool | None = None,
                      codeact_fallback_enabled: bool = False):
    ctx = result.context
    memory_enabled = variant == "SB-FULL" if memory_enabled is None else bool(memory_enabled)
    if not memory_enabled:
        append_event(root / "memory-events.jsonl", {
            "status": "not_applicable",
            "event": "not_applicable",
            "query_count": 0,
            "actual_consumption": 0,
            "missing_reason": "memory_disabled_for_mechanism_control",
        })
    if variant == "P-TEXT" and task_id[1:] == "12":
        append_event(root / "memory-events.jsonl", {
            "status": "not_applicable",
            "event": "not_applicable",
            "query_count": None,
            "actual_consumption": None,
            "missing_reason": "memory_disabled_for_p_text_control",
        })
    for query_task_id, query in ctx.memory_queries_by_task.items():
        if variant == "P-TEXT" and query_task_id[1:] == "12":
            continue
        match = next(iter(ctx.memory_match_results.values()))
        append_event(root / "memory-events.jsonl", {"event": "query", "query_id": query.query_hash,
            "query_count": 1, "candidate_count": len(match.candidate_pool.candidate_memory_ids),
            "queries_with_candidate": int(bool(match.candidate_pool.candidate_memory_ids)),
            "decisions": [asdict(v) for v in match.compatibility_decisions]})
    for record in ctx.memory_consumption_records:
        admitted = bool(record.attempt_result_admission_receipt_hash)
        commit = result.infrastructure.memory_store.commits.get(record.memory_id)
        if commit is None:
            continue
        read = ctx.memory_read_evidence_by_id.get(record.memory_id, {})
        append_event(root / "memory-events.jsonl", {"event": "consume" if admitted else "pending_consumption",
            "query_id": record.query_hash, "memory_ref": record.memory_id, "grant_id": record.capability_grant_hash,
            "consumer_agent": record.consumer_role, "source_agent": commit.memory_ref.source_agent,
            "source_task_id": commit.memory_ref.source_task_id,
            "producer_run_id": commit.memory_ref.producer_run_id,
            "artifact_ref_id": commit.memory_ref.artifact_ref_id,
            "memory_commit_hash": record.memory_commit_hash,
            "memory_admission_receipt_hash": record.memory_admission_receipt_hash,
            "compatibility_verdict": record.compatibility_verdict.value,
            "replay_class": record.replay_class.value,
            "consume_receipt": record.attempt_result_admission_receipt_hash, "actual_consumption": int(admitted),
            "replay_count": int(admitted and record.recipe_recomputed), "input_recomputed": record.recipe_recomputed,
            "skipped_executor_generation": record.skipped_generation_step_count,
            "downstream_effect": record.behavioral_effect,
            "artifact_read": read.get("artifact_read"),
            "artifact_read_bytes": read.get("artifact_read_bytes"),
            "artifact_hash": read.get("artifact_hash"),
            "manifest_hash": read.get("manifest_hash"),
            "avoided_tokens": None,
            "missing_reason": "counterfactual_avoided_tokens_not_measured"})
    for ref, publication in ctx.semantic_state_publications.items():
        append_event(root / "state-events.jsonl", {"event": "publish", "ref": ref, "state_type": "semantic_embedding_matrix",
            "payload_bytes": publication.handle.size_bytes, "hash": publication.contract.blob_hash,
            "schema": publication.contract.schema_version, "producer_pid": publication.contract.producer_pid,
            "generation_ms": None, "generation_missing_reason": "embedding_generation_not_separately_timed"})
    for event in result.runtime.telemetry.events:
        if event.event_type == "STATE_RESOLVED" and event.channel == "semantic_state":
            append_event(root / "state-events.jsonl", {"event": "transfer", "ref": event.payload["ref_id"],
                "state_type": "semantic_embedding_matrix", "telemetry_event_id": event.event_id,
                "transfer_count": event.metrics.get("semantic_state_transfer_count"),
                "producer_pid": event.payload.get("producer_pid"), "consumer_pid": event.payload.get("consumer_pid"),
                "transfer_scope": "cross_process_ref_resolution_not_a_payload_copy", "wire_bytes": None})
    for ref, receipt in ctx.semantic_consumer_receipts.items():
        publication = ctx.semantic_state_publications[ref]
        start, end = receipt.get("read_started_at_ns"), receipt.get("read_completed_at_ns")
        consume_ms = (end - start) / 1e6 if start and end and end >= start else None
        append_event(root / "state-events.jsonl", {"event": "consume", "ref": ref, "receipt": receipt,
            "state_type": "semantic_embedding_matrix", "schema": publication.contract.schema_version,
            "hash": receipt.get("observed_blob_hash"), "producer_pid": receipt.get("producer_pid"),
            "consumer_pid": receipt.get("consumer_pid"), "consume_ms": consume_ms,
            "consume_timing_scope": "worker_run_start_to_completion_including_read_and_selection",
            "consume_timing_missing_reason": "worker_timestamps_unavailable" if consume_ms is None else None,
            "consumer": "semantic_state_worker", "downstream_effect": receipt.get("behavioral_effect"),
            "activity": {"changed": "active", "no_effect": "no_effect"}.get(receipt.get("behavioral_effect")),
            "read_bytes": receipt.get("observed_size_bytes"), "hydrate_bytes": receipt.get("observed_size_bytes"),
            "read_byte_scope": "logical_matrix_read; hydrate_bytes_is_alias_not_additional_io",
            "selected_evidence_bytes": receipt.get("selected_evidence_bytes"),
            "missing_reason": None if receipt.get("observed_size_bytes") is not None else "receipt_size_unavailable"})
    for ref, receipt in ctx.state_release_reclaim_receipts.items():
        append_event(root / "state-events.jsonl", {"event": "release", "ref": ref,
            "state_type": "semantic_embedding_matrix", "receipt": receipt,
            "release_count": int(receipt["owner_released"]), "physical_reclaimed": receipt["physical_reclaimed"],
            "released_bytes": ctx.semantic_state_publications[ref].handle.size_bytes if receipt["owner_released"] else None,
            "release_status": receipt["release_status"]})
    bound_capabilities = {
        bound.grant.attempt_id: bound.grant.capability_id
        for bound in getattr(result.runtime, "bound_grants", ())
    }
    runtime_dispatches = getattr(result.runtime, "dispatches", ())
    python_dispatches = [
        dispatch for dispatch in runtime_dispatches
        if bound_capabilities.get(dispatch.attempt_id) == _PYTHON_CAPABILITY_ID
    ]
    dsl_dispatches = [
        dispatch for dispatch in runtime_dispatches
        if bound_capabilities.get(dispatch.attempt_id) == "dsl-execute"
    ]
    if not codeact_fallback_enabled:
        append_event(root / "codeact-events.jsonl", {
            "status": "not_applicable",
            "fallback_enabled": False,
            "fallback_attempted": False,
            "missing_reason": "codeact_fallback_disabled",
        })
    elif not python_dispatches:
        append_event(root / "codeact-events.jsonl", {
            "status": "not_used",
            "fallback_enabled": True,
            "fallback_attempted": False,
            "dsl_execute_attempts": len(dsl_dispatches),
            "missing_reason": "dsl_verified_before_fallback",
        })
    else:
        for dispatch in python_dispatches:
            append_event(root / "codeact-events.jsonl", {
                "status": "observed",
                "fallback_enabled": True,
                "fallback_attempted": True,
                "first_attempt": False,
                "final_result": dispatch.state.lower(),
                "attempt_id": dispatch.attempt_id,
                "error_code": dispatch.error_code,
                "dsl_execute_attempts": len(dsl_dispatches),
                "python_attempts": len(python_dispatches),
                "internal_repair_count": 0,
                "sandbox": "bwrap",
                "validator": "contest-dsl-raw",
                "citation": "runtime_grant_and_original_scorer",
            })


def _dependency_block_reason(task, ledger_by_task: dict[str, dict]) -> str | None:
    """Return a dependency-aware block reason for one scheduled task.

    ``required_history`` is the contract's dependency declaration.  A task is
    runnable when every declared producer completed successfully; an unrelated
    producer failure must not stop this task.  The scheduler is ordered by
    round, so dependencies should already have terminal ledger rows, but a
    not-yet-observed dependency is conservatively treated as unavailable.
    """
    unavailable = []
    for dependency in task.required_history:
        row = ledger_by_task.get(dependency)
        status = row.get("status") if row is not None else "not_observed"
        if status != "success":
            unavailable.append(f"{dependency}:{status}")
    if not unavailable:
        return None
    return "blocked_by_dependency:" + ",".join(unavailable)


def _is_timeout_error(exc: BaseException) -> bool:
    """Classify both local transport and OpenAI-compatible provider timeouts."""
    return isinstance(exc, (TimeoutError, APITimeoutError))


def run_chain(output: Path, *, family: str, variant: str, rounds: int = 3, mode: str = "offline", profile: str = "default", **kwargs):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tasks = tasks_for_family(family, profile=profile)
    generate_sealed(output / "sealed", profile=profile)
    write_json(output / "taskpack.json", [task.public_view() for task in tasks])
    ledger = [{"chain_id": family+":"+variant, "family": family, "variant": variant,
               "round": task.round, "task_id": task.task_id, "task_profile": profile, "mode": mode, "status": "not_started",
               "slot_root": str(output / "slots" / task.task_id)} for task in tasks]
    history = {}
    ledger_by_task = {row["task_id"]: row for row in ledger}
    for row, task in zip(ledger[:rounds], tasks):
        blocked_reason = _dependency_block_reason(task, ledger_by_task)
        if blocked_reason:
            row.update(status="blocked", blocked_reason=blocked_reason, returncode=1, quality=False,
                       business_quality=False, mechanism_gate_passed=False)
            write_json(output / "ledger.json", ledger)
            continue
        row["status"] = "running"
        write_json(output / "ledger.json", ledger)
        started = time.monotonic_ns()
        try:
            release_task(output / "sealed", output / "public", task.task_id, profile=profile)
            result = run_slot(Path(row["slot_root"]), output / "public", task.task_id,
                              history=history, variant=variant, mode=mode, profile=profile, **kwargs)
            observed_rows = result.pop("rows")
            row.update(result)
            if row["status"] == "success":
                history[task.task_id] = observed_rows
        except Exception as exc:
            # One top-level task boundary preserves real failures and stops the
            # task only when later tasks explicitly depend on its verified
            # history.  Independent rounds remain eligible to run.
            failure_code = getattr(exc, "code", None) or str(exc)
            row.update(status="timeout" if _is_timeout_error(exc) else "runtime_fail",
                       returncode=1, quality=False, error=f"{type(exc).__name__}:{exc}",
                       failure_codes=[failure_code])
            metrics = {**collect_slot_metrics(Path(row["slot_root"])), **_generation_metrics(Path(row["slot_root"]))}
            row.update(metrics=metrics, repair=metrics["executor_repair_count"])
        row["e2e_ms"] = (time.monotonic_ns()-started)/1e6
        write_json(Path(row["slot_root"]) / "task-row.json", row)
        write_json(output / "ledger.json", ledger)
        write_reports(output / "metrics", ledger)
    summary = write_reports(output / "metrics", ledger)
    if profile == SIMPLE_PROFILE:
        write_json(output / "readiness.json", {
            "task_profile": profile, "mode": mode, "requested_rounds": rounds,
            "planned_slots": 12, "passed_slots": summary["aggregate"]["passed_count"],
            "continuous_12_completed": rounds == 12 and summary["aggregate"]["passed_count"] == 12,
            "continuous_12_live_passed": mode == "live" and rounds == 12 and summary["aggregate"]["passed_count"] == 12,
            "r11_replay": ledger[10]["status"] if variant == "SB-FULL" else "not_applicable",
            "r12_cross_agent_memory": ledger[11]["status"] if variant == "SB-FULL" else "not_applicable",
            "b2_boundary": "actual_in_process_receiver; wire bytes unavailable",
            "codeact": "not_applicable_to_dsl_mainline"})
    else:
        r12_rows = [row for row in ledger if row["round"] == 12]
        r12_ready = bool(r12_rows) and all(row["status"] == "success" for row in r12_rows)
        blockers = ["minimal_live_parity_not_yet_validated"]
        if not r12_ready:
            blockers.insert(0, R12_BLOCKER)
        write_json(output / "readiness.json", {"stage3_ready": False,
            "r12_cross_agent_memory_ready": r12_ready if variant == "SB-FULL" else "not_applicable",
            "blockers": blockers,
            "diagnostic_rounds": rounds, "mode": mode,
            "no_prompt_compression_or_dynamic_allocation": True,
            "b2_boundary": "actual_in_process_receiver; wire bytes unavailable",
            "codeact": "not_applicable_to_dsl_mainline"})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="default", help="Explicit task contract; legacy default unchanged")
    parser.add_argument("--family", required=True, choices=("finance", "service_ops"))
    parser.add_argument("--variant", required=True, choices=("SB-FULL", "P-TEXT"))
    parser.add_argument("--output", required=True, type=Path, help="New output directory; never overwritten")
    parser.add_argument("--rounds", type=int, default=3, choices=range(1,13))
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument(
        "--codeact-fallback", choices=("off", "on"), default="off",
        help="After DSL initial execution and its existing single repair fail, authorize one fresh bounded-Python attempt.",
    )
    parser.add_argument(
        "--model-assist-profile", choices=tuple(sorted(MODEL_ASSIST_PROFILES)), default="off",
        help="Explicit model-side Logit/APC/KV routing profile; default off.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print contracts/settings only; execute nothing")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--max-context", type=int, default=8192)
    parser.add_argument("--provider-timeout-s", type=float, default=DEFAULT_PROVIDER_TIMEOUT_S,
                        help="Per-provider HTTP timeout for every role; default 480s, no implicit retry")
    parser.add_argument("--embedding-mode", choices=("deterministic", "local"), default="deterministic")
    parser.add_argument("--embedding-model", type=Path)
    parser.add_argument("--embedding-device")
    parser.add_argument("--tokenizer-path", type=Path, default=os.getenv("STATEBUS_VLLM_TOKENIZER_PATH"),
                        help="Local model directory for handoff tokens (no special tokens); unset/unavailable is missing, not zero")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps({"tasks": [t.public_view() for t in tasks_for_family(args.family, profile=args.profile)][:args.rounds],
                          "configuration": vars(args), "executed": False}, default=str, indent=2))
        return 0
    if args.mode == "live" and args.embedding_mode != "local":
        parser.error("Live parity requires explicit local embedding model/device; deterministic embedding is offline only.")
    if args.provider_timeout_s <= 0:
        parser.error("--provider-timeout-s must be positive")
    if args.embedding_mode == "local" and (not args.embedding_model or not args.embedding_device):
        parser.error("local embedding requires --embedding-model and --embedding-device")
    config = vars(args)
    config.pop("dry_run")
    config["codeact_fallback_enabled"] = config.pop("codeact_fallback") == "on"
    output = config.pop("output")
    summary = run_chain(output, **config)
    print(json.dumps(summary["aggregate"], indent=2))
    return int(summary["aggregate"]["passed_count"] != args.rounds)


if __name__ == "__main__":
    raise SystemExit(main())
