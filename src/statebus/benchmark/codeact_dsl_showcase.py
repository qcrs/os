"""Independent five-case DSL/CodeAct capability showcase.

This module is intentionally separate from the frozen contest DSL mainline.
It runs one executor step through the canonical AdaptiveRuntimeEngine.  The
initial attempt is always the Transform DSL; Python is reachable only through
an explicit, allow-listed Runtime replan after the DSL attempt and its single
repair have failed.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from statebus.benchmark.adaptive_formal import (
    FormalAdaptiveCase,
    adapt_formal_sample,
    build_formal_quality_validator,
    build_non_answer_source_profile,
    expected_facts_report,
)
from statebus.benchmark.adaptive_formal_mainline import (
    _build_formal_analysis_context,
    _source_artifact,
)
from statebus.benchmark.task_registry import load_c2b_positive_samples
from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CodeGenerationPolicy,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher, AdaptiveDispatchContext
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeEngine, AdaptiveRuntimeRequest
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.capability_validators import default_capability_validator_registry
from statebus.runtime.domain_packs import register_generic_adaptive_analysis_capabilities
from statebus.runtime.identity import compatibility_runtime_identity
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.role_path import _operation_argument_contract, _transform_program_response_schema
from statebus.runtime.transform_dsl import _ALLOWED_OPS
from statebus.utils import sha256_digest, stable_json_dumps


CASE_IDS = (
    "formal-trend-001",
    "formal-trend-005",
    "formal-join-001",
    "formal-agg-004",
    "formal-anomaly-001",
)
DSL_CASES = frozenset(CASE_IDS[:3])
PYTHON_CASES = frozenset(CASE_IDS[3:])
EXPECTED_BACKEND = {**{case_id: "dsl" for case_id in DSL_CASES}, **{case_id: "python" for case_id in PYTHON_CASES}}
CONTRACT_VERSION = "statebus.analysis_result.v2"
SHOWCASE_LOGICAL_INPUT_REF = "source"
SHOWCASE_DSL_OPERATIONS = tuple(sorted(_ALLOWED_OPS - {"deterministic_fixture"}))
# Match the existing adaptive formal CodeAct executor request contract.
SHOWCASE_CODE_MAX_TOKENS = 1400


@dataclass(frozen=True)
class ShowcaseCase:
    case: FormalAdaptiveCase
    expected_backend: str
    capability_rationale: str


def load_showcase_cases() -> tuple[ShowcaseCase, ...]:
    samples = {sample.task_id: sample for sample in load_c2b_positive_samples()}
    missing = [case_id for case_id in CASE_IDS if case_id not in samples]
    if missing:
        raise ValueError(f"showcase_cases_missing:{','.join(missing)}")
    rationales = {
        "formal-trend-001": "registered trend_series over one ticker and three requested periods",
        "formal-trend-005": "registered trend_series over the requested ticker/period lists",
        "formal-join-001": "registered compare_metric for the fixed ACME/BETA alignment",
        "formal-agg-004": "requires date-string month derivation and numeric-string normalization",
        "formal-anomaly-001": "requires inclusive interpolated quartiles and outlier-filtered means",
    }
    return tuple(
        ShowcaseCase(adapt_formal_sample(samples[case_id]), EXPECTED_BACKEND[case_id], rationales[case_id])
        for case_id in CASE_IDS
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _case_plan(case: ShowcaseCase, *, python: bool = False) -> PlanProposal:
    step = PlanStepProposal(
        step_id="analysis",
        role="executor",
        capability_id="execute_bounded_python_v2" if python else "execute_analysis_dsl_v2",
        goal=(
            f"Complete the public operation {case.case.operation} using only the authorized source rows "
            f"and produce the declared output schema {stable_json_dumps(case.case.output_schema)}."
        ),
        input_ref_ids=(case.case.source_ref_id,),
        input_ref_kinds=("execution_artifact",),
        output_contract_version=CONTRACT_VERSION,
        completion_criteria={"min_rows": 1, "required_fields": tuple(case.case.output_schema)},
        on_failure="request_replan" if not python and case.expected_backend == "python" else "fail",
    )
    return PlanProposal(
        proposal_id=f"showcase-{case.case.task_id}-{'python' if python else 'dsl'}",
        task_id=case.case.task_id,
        steps=(step,),
        final_output_contract_version=CONTRACT_VERSION,
        requested_memory_policy="none",
        model_id="showcase-controller",
    )


def _envelope(case: ShowcaseCase) -> AdaptiveTaskEnvelope:
    return AdaptiveTaskEnvelope(
        task_id=case.case.task_id,
        canonical_task_spec_hash=sha256_digest(case.case.spec.canonical_payload()),
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="generic_adaptive_analysis_v2",
        allowed_capability_ids=("execute_analysis_dsl_v2", "execute_bounded_python_v2"),
        allowed_output_contracts=(CONTRACT_VERSION,),
        allowed_memory_policies=("none",),
        role_cardinality={"executor": (1, 1)},
        max_plan_steps=1,
        max_dependency_depth=1,
        max_retrieval_steps=0,
        max_execution_runtime_ms=240_000,
        max_replans=1,
        max_retrieval_expansions=0,
        max_total_attempts=3,
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
    )


def _approve(registry: CapabilityRegistry, envelope: AdaptiveTaskEnvelope, proposal: PlanProposal):
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        proposal,
        envelope,
        available_input_refs={proposal.steps[0].input_ref_ids[0]: "execution_artifact"},
    )
    if outcome.approved_plan is None:
        raise ValueError(f"showcase_plan_rejected:{outcome.report.canonical_payload()}")
    return outcome.approved_plan


def _dsl_program(case: ShowcaseCase, input_ref: str) -> TransformProgram:
    operation = case.case.operation_semantics.get("dsl_operation")
    semantics = case.case.operation_semantics.get("dsl_arguments")
    if not isinstance(operation, str) or operation not in SHOWCASE_DSL_OPERATIONS or not isinstance(semantics, dict):
        raise ValueError(f"showcase_dsl_program_not_defined:{case.case.task_id}")
    return TransformProgram(
        program_id=f"showcase-dsl-{case.case.task_id}",
        input_artifact_refs=(input_ref,),
        operations=(TransformStep(operation, dict(semantics)),),
        output_contract_version=CONTRACT_VERSION,
    )


def _invalid_dsl_program(case: ShowcaseCase, input_ref: str, suffix: str) -> TransformProgram:
    # Deliberately valid DSL syntax with the wrong public shape. Runtime will
    # execute it, reject it through the business validator, and allow exactly
    # one repair before the optional replan.
    columns = tuple(case.case.source_schema)[:1]
    return TransformProgram(
        program_id=f"showcase-invalid-{case.case.task_id}-{suffix}",
        input_artifact_refs=(input_ref,),
        operations=(TransformStep("select", {"columns": list(columns)}),),
        output_contract_version=CONTRACT_VERSION,
    )


def _python_source(case: ShowcaseCase) -> str:
    op = case.case.operation
    if op == "groupby_aggregate":
        return """import json\nfrom pathlib import Path\nfrom statistics import mean\nfrom collections import defaultdict\nrows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\ngroups=defaultdict(list)\nfor row in rows:\n    value=str(row.get('WINDSPEED','')).strip()\n    if not value: continue\n    try: number=float(value.replace(',',''))\n    except ValueError: continue\n    date=str(row.get('DATE TIME','')).strip()\n    if len(date) < 2: continue\n    groups[int(date[:2])].append(number)\nout=[{'month': month, 'monthly_avg_windspeed': round(mean(values), 2)} for month, values in sorted(groups.items())]\nPath('outputs/result.json').write_text(json.dumps(out), encoding='utf-8')\n"""
    if op == "detect_outliers":
        column = json.dumps(str(case.case.spec.arguments["column"]))
        return f"""import json\nfrom pathlib import Path\nfrom statistics import mean\nrows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\ndef number(value):\n    text=str(value or '').strip().split('[', 1)[0].replace(',', '')\n    if not text: return None\n    try: return float(text)\n    except ValueError: return None\nvalues=sorted(value for row in rows if (value:=number(row.get({column}))) is not None)\ndef quantile(p):\n    pos=(len(values)-1)*p; lo=int(pos); hi=min(lo+1,len(values)-1); fraction=pos-lo\n    return values[lo] + (values[hi]-values[lo])*fraction\nq1=quantile(0.25); q3=quantile(0.75); low=q1-1.5*(q3-q1); high=q3+1.5*(q3-q1)\nkept=[value for value in values if low <= value <= high]\nout={{'mean_no_of_deaths_with_outliers': round(mean(values), 2), 'mean_no_of_deaths_without_outliers': round(mean(kept), 2)}}\nPath('outputs/result.json').write_text(json.dumps(out), encoding='utf-8')\n"""
    raise ValueError(f"showcase_python_source_not_defined:{case.case.task_id}")


def _provider_config(*, raw_code: bool = False):
    """Reuse the active provider config and apply only the raw-CodeAct role contract."""
    from statebus.integrations.llm import LLMConfig

    config = LLMConfig.from_runtime().with_mode("local_vllm")
    if raw_code:
        # The historical adaptive CodeAct path requests raw Python.  Leaving
        # executor JSON mode enabled makes vLLM apply an object grammar to a
        # source file and is inconsistent with the raw-code contract used by
        # the historical adaptive CodeAct path.
        max_tokens = int(os.getenv("STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS", str(SHOWCASE_CODE_MAX_TOKENS)))
        if max_tokens <= 0:
            raise ValueError("showcase_code_max_tokens_must_be_positive")
        config = config.with_role_override(
            "executor",
            json_output=False,
            max_tokens=max_tokens,
        )
    return config


def _provider_client(*, raw_code: bool = False):
    from statebus.integrations.llm import build_llm_client

    return build_llm_client(_provider_config(raw_code=raw_code))


def _provider_failure(exc: BaseException) -> ValueError:
    """Convert only provider-boundary failures into a Runtime-visible error."""
    if isinstance(exc, (APITimeoutError, TimeoutError, asyncio.TimeoutError)):
        code = "showcase_provider_timeout"
    elif isinstance(exc, (APIConnectionError, ConnectionError)):
        code = "showcase_provider_connection_error"
    elif isinstance(exc, APIStatusError):
        status_code = int(getattr(exc, "status_code", 0) or 0)
        code = f"showcase_provider_http_{status_code or 'error'}"
    elif isinstance(exc, APIError):
        code = f"showcase_provider_{type(exc).__name__}"
    else:
        raise exc
    return ValueError(code)


def _provider_json(prompt: str, *, response_schema: dict[str, object]) -> tuple[dict[str, object], int]:
    from statebus.integrations.llm import ChatMessage, extract_json_object
    client = _provider_client()
    try:
        result = asyncio.run(client.complete([ChatMessage("user", prompt)], purpose="executor", response_schema=response_schema))
    except (APITimeoutError, APIConnectionError, APIStatusError, APIError, TimeoutError, asyncio.TimeoutError, ConnectionError) as exc:
        raise _provider_failure(exc) from exc
    return extract_json_object(result.text), int(result.usage.total_tokens or 0)


def _provider_code(prompt: str) -> tuple[str, int]:
    from statebus.integrations.llm import ChatMessage
    client = _provider_client(raw_code=True)
    try:
        result = asyncio.run(client.complete([ChatMessage("user", prompt)], purpose="executor"))
    except (APITimeoutError, APIConnectionError, APIStatusError, APIError, TimeoutError, asyncio.TimeoutError, ConnectionError) as exc:
        raise _provider_failure(exc) from exc
    return result.text, int(result.usage.total_tokens or 0)


def _record_dsl_response(case_root: Path, phase: str, raw: dict[str, object]) -> None:
    _write_json(case_root / f"provider_{phase}_contract.json", {
        "input_artifact_refs": raw.get("input_artifact_refs"),
        "output_contract_version": raw.get("output_contract_version"),
        "operation_keys": [sorted(item) if isinstance(item, dict) else type(item).__name__
                           for item in raw.get("operations", ())][:12],
        "operation_names": [item.get("op") if isinstance(item, dict) else None
                            for item in raw.get("operations", ())][:12],
    })


def _dsl_response_schema(grant) -> dict[str, object]:
    return _transform_program_response_schema(
        authorized_input_refs=(SHOWCASE_LOGICAL_INPUT_REF,),
        input_schema={SHOWCASE_LOGICAL_INPUT_REF: ()},
        output_contract_version=grant.output_contract_version,
        operation_catalog=SHOWCASE_DSL_OPERATIONS,
    )


def _run_case(case: ShowcaseCase, *, mode: str, fallback_enabled: bool, case_root: Path) -> dict[str, object]:
    started = time.perf_counter_ns()
    case_root.mkdir(parents=True, exist_ok=False)
    registry = CapabilityRegistry()
    register_generic_adaptive_analysis_capabilities(registry, analysis_validator_ids=("formal_analysis",))
    envelope = _envelope(case)
    identity = compatibility_runtime_identity(case.case.task_id, f"showcase:{case.case.task_id}", envelope.canonical_task_spec_hash)
    source, receipt = _source_artifact(case.case, case_root, identity)
    validator_registry = default_capability_validator_registry()
    validator_registry.register("formal_analysis", build_formal_quality_validator(case.case))
    source_profile = build_non_answer_source_profile(case.case.source_rows)
    analysis_context = _build_formal_analysis_context(case.case, source_profile)
    leading_numeric_text = any(
        "leading numeric token" in str(item)
        for column in source_profile["columns"].values()
        for item in column.get("formats", ())
    )
    quality_constraints = {
        "benchmark_oracle_is_external_to_runtime": True,
        "runtime_recomputation_from_authorized_inputs": True,
        "finite_numbers_only": True,
    }
    provider_requests = 0
    provider_tokens = 0
    dsl_factory_calls = 0
    dsl_repair_calls = 0
    python_policy_calls = 0

    def dsl_factory(step, grant, input_ref_id, rows, memory_inputs=(), **kwargs):
        nonlocal provider_requests, provider_tokens, dsl_factory_calls
        dsl_factory_calls += 1
        if mode == "offline":
            return _dsl_program(case, input_ref_id) if case.expected_backend == "dsl" else _invalid_dsl_program(case, input_ref_id, "initial")
        provider_requests += 1
        payload = {
            "task": case.case.sample.request_text,
            "operation": case.case.operation,
            "dsl_capability_rationale": case.capability_rationale,
            "input_schema": case.case.source_schema,
            "output_schema": case.case.output_schema,
            "operation_semantics": case.case.operation_semantics,
            "authorized_input_refs": [SHOWCASE_LOGICAL_INPUT_REF],
            "output_contract_version": grant.output_contract_version,
            "operations": {op: _operation_argument_contract(op) for op in SHOWCASE_DSL_OPERATIONS},
            "instruction": (
                "Return JSON object {input_artifact_refs,output_contract_version,operations}; no prose. "
                "Each operations item has exactly {op,arguments}; op is a documented operation name, arguments is its argument object. "
                "The operation field is a semantic task label, not necessarily a DSL operation name. "
                "Choose every op only from the keys of operations; never copy a semantic label into op when it is not listed. "
                "When operation_semantics contains dsl_operation and dsl_arguments, return exactly that one operation and "
                "copy dsl_arguments without changing, adding, or removing fields. "
                f"Copy authorized_input_refs exactly as ['{SHOWCASE_LOGICAL_INPUT_REF}']. "
                "Copy output_contract_version exactly from this request; do not invent a version. "
                "Use the logical name only; never return a physical artifact ref, filesystem path, or invented alias."
            ),
        }
        raw, tokens = _provider_json(stable_json_dumps(payload), response_schema=_dsl_response_schema(grant))
        provider_tokens += tokens
        _record_dsl_response(case_root, "initial", raw)
        program = _program_from_payload(raw, input_ref_id, grant.output_contract_version)
        return program

    def dsl_repair(step, grant, input_ref_id, rows, validation_errors, **kwargs):
        nonlocal provider_requests, provider_tokens, dsl_repair_calls
        dsl_repair_calls += 1
        if mode == "offline":
            return _invalid_dsl_program(case, input_ref_id, "repair")
        provider_requests += 1
        prompt = stable_json_dumps({
            "task": case.case.sample.request_text,
            "input_schema": case.case.source_schema,
            "output_schema": case.case.output_schema,
            "operation_semantics": case.case.operation_semantics,
            "dsl_capability_rationale": case.capability_rationale,
            "authorized_input_refs": [SHOWCASE_LOGICAL_INPUT_REF],
            "output_contract_version": grant.output_contract_version,
            "operations": {op: _operation_argument_contract(op) for op in SHOWCASE_DSL_OPERATIONS},
            "validation_errors": list(validation_errors),
            "previous_program": kwargs.get("previous_program").canonical_payload() if kwargs.get("previous_program") else None,
            "instruction": (
                "Return a complete replacement JSON DSL program only. Each operations item has exactly {op,arguments}. "
                "The task operation is a semantic label; choose op only from the documented operation catalog in this request. "
                "When operation_semantics contains dsl_operation and dsl_arguments, return exactly that one operation and "
                "copy dsl_arguments without changing, adding, or removing fields. "
                f"Copy authorized_input_refs exactly as ['{SHOWCASE_LOGICAL_INPUT_REF}']; "
                "copy output_contract_version exactly from this request; "
                "do not return physical artifact refs or filesystem paths."
            ),
        })
        raw, tokens = _provider_json(prompt, response_schema=_dsl_response_schema(grant))
        provider_tokens += tokens
        _record_dsl_response(case_root, "repair", raw)
        program = _program_from_payload(raw, input_ref_id, grant.output_contract_version)
        return program

    def code_policy(step):
        nonlocal python_policy_calls
        python_policy_calls += 1
        return CodeGenerationPolicy(
            capability_id="execute_bounded_python_v2",
            enabled=True,
            require_bwrap=True,
            allowed_module_roots=("json", "pathlib", "re", "statistics", "collections"),
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=tuple(case.case.output_schema),
            numeric_text_mode="leading_token" if leading_numeric_text else "unrestricted",
            timeout_seconds=30.0,
            max_output_bytes=1_048_576,
            max_policy_repairs=0,
            max_runtime_repairs=0,
            max_quality_repairs=0,
        )

    def code_source(request, prompt):
        nonlocal provider_requests, provider_tokens
        if mode == "offline":
            return _python_source(case)
        provider_requests += 1
        source, tokens = _provider_code(prompt)
        provider_tokens += tokens
        return source

    context = AdaptiveDispatchContext(
        registry=registry,
        validator_registry=validator_registry,
        artifacts={case.case.source_ref_id: source},
        artifact_verification_receipts={case.case.source_ref_id: receipt},
        transform_program_factory=dsl_factory,
        transform_program_repair_factory=dsl_repair,
        code_policy_factory=code_policy,
        code_source_factory=code_source,
        output_schema_by_capability={"execute_analysis_dsl_v2": dict(case.case.output_schema), "execute_bounded_python_v2": dict(case.case.output_schema)},
        # The formal validator owns the public operation contract. The
        # dispatcher semantic gate is intentionally empty here because the
        # showcase includes the lookup filter/select/rename composition, which
        # is more expressive than its legacy one-op semantic hint.
        quality_semantics_by_capability={"execute_analysis_dsl_v2": {}},
        codeact_contracts={
            "execute_bounded_python_v2": {
                "operation_semantics": analysis_context,
                "quality_constraints": quality_constraints,
                "expected_output_shape": case.case.expected_output_shape,
            },
        },
    )
    initial_proposal = _case_plan(case)
    approved = _approve(registry, envelope, initial_proposal)
    python_approved = _approve(registry, envelope, _case_plan(case, python=True))

    def replan(previous, completed, error_code):
        if not fallback_enabled or case.expected_backend != "python":
            return None
        if completed:
            return None
        if not error_code.startswith("dsl_repair_exhausted:"):
            return None
        return python_approved

    runtime = AdaptiveRuntimeEngine().run(AdaptiveRuntimeRequest(
        trace_id=f"showcase:{case.case.task_id}",
        task_id=case.case.task_id,
        canonical_task_spec_hash=envelope.canonical_task_spec_hash,
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(case_root / "runtime"),
        workspace_root_id=str(case_root / "workspace"),
        available_input_refs={case.case.source_ref_id: "execution_artifact"},
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
        replan=replan,
        runtime_identity=identity,
    ))
    grants = {grant.grant.attempt_id: grant.grant.capability_id for grant in runtime.bound_grants}
    dispatches = list(runtime.dispatches)
    dsl_dispatches = [item for item in dispatches if grants.get(item.attempt_id) == "execute_analysis_dsl_v2"]
    python_dispatches = [item for item in dispatches if grants.get(item.attempt_id) == "execute_bounded_python_v2"]
    final_backend = "python" if python_dispatches and any(item.state == "COMPLETED" for item in python_dispatches) else "dsl" if any(item.state == "COMPLETED" for item in dsl_dispatches) else None
    last_dsl_failure = next((item.error_code for item in reversed(dsl_dispatches) if item.state != "COMPLETED"), None)
    if last_dsl_failure and last_dsl_failure.startswith("dsl_repair_exhausted:"):
        last_dsl_failure = last_dsl_failure.split(":", 1)[1]
    quality = any(getattr(report, "verified", False) for report in context.quality_reports.values())
    final_dispatch = next(
        (
            item
            for item in reversed(dispatches)
            if item.state == "COMPLETED"
            and grants.get(item.attempt_id) in {"execute_analysis_dsl_v2", "execute_bounded_python_v2"}
        ),
        None,
    )
    final_rows = ()
    if final_dispatch is not None and final_dispatch.output_refs:
        stored = context.artifacts.get(final_dispatch.output_refs[0])
        if stored is not None:
            final_rows = stored.rows
    scorer_report = expected_facts_report(case.case, final_rows) if final_rows else {"passed": False}
    score_passed = bool(scorer_report.get("passed"))
    quality = quality and score_passed
    status = "passed" if runtime.completed and final_backend is not None and quality else "failed"
    telemetry = runtime.telemetry.summarize_task(case.case.task_id)
    row = {
        "case_id": case.case.task_id,
        "historical_family": case.case.sample.task_family,
        "operation": case.case.operation,
        "expected_backend": case.expected_backend,
        "status": status,
        "quality": quality,
        "score_passed": score_passed,
        "final_backend": final_backend,
        "fallback_enabled": fallback_enabled,
        "fallback_attempted": bool(python_dispatches),
        "dsl_attempts": dsl_factory_calls + dsl_repair_calls,
        "dsl_repair_count": dsl_repair_calls,
        "last_dsl_failure": last_dsl_failure if dsl_dispatches and not any(item.state == "COMPLETED" for item in dsl_dispatches) else None,
        "python_attempts": len(python_dispatches),
        "python_internal_repair_count": 0 if python_policy_calls else None,
        "attempt_count": len(runtime.bound_grants),
        "distinct_grant_count": len({grant.grant.grant_hash for grant in runtime.bound_grants}),
        "provider_requests": provider_requests,
        "provider_tokens": provider_tokens,
        "e2e_ms": round((time.perf_counter_ns() - started) / 1_000_000.0, 3),
        "reason": "runtime_completed" if status == "passed" else (next((item.error_code for item in reversed(dispatches) if item.state != "COMPLETED"), None) or "runtime_incomplete"),
        "source_path": str(case.case.spec.arguments.get("csv_path") or case.case.source_ref_id),
    }
    _write_json(case_root / "case_result.json", row)
    return row


def _program_from_payload(raw: dict[str, object], input_ref: str, contract: str) -> TransformProgram:
    logical_refs = tuple(str(item) for item in raw.get("input_artifact_refs", (SHOWCASE_LOGICAL_INPUT_REF,)))
    if logical_refs != (SHOWCASE_LOGICAL_INPUT_REF,):
        raise ValueError("showcase_provider_input_ref_mismatch")
    output_contract = str(raw.get("output_contract_version", contract))
    if output_contract != contract:
        raise ValueError("showcase_provider_output_contract_mismatch")
    refs = (input_ref,)
    operations = []
    for item in raw.get("operations", ()):
        if not isinstance(item, dict) or "op" not in item or not isinstance(item.get("arguments"), dict):
            raise ValueError("showcase_provider_operation_format_invalid")
        args = dict(item["arguments"])
        if "right_ref" in args:
            if str(args["right_ref"]) != SHOWCASE_LOGICAL_INPUT_REF:
                raise ValueError("showcase_provider_unauthorized_right_ref")
            args["right_ref"] = input_ref
        operations.append(TransformStep(str(item["op"]), args))
    return TransformProgram(str(raw.get("program_id", "provider-program")), refs, tuple(operations), contract)


def _summary(rows: list[dict[str, object]], *, mode: str, fallback_enabled: bool) -> dict[str, object]:
    dsl = sum(row.get("status") == "passed" and row.get("final_backend") == "dsl" for row in rows)
    python = sum(row.get("status") == "passed" and row.get("final_backend") == "python" for row in rows)
    return {
        "mode": mode,
        "fallback_enabled": fallback_enabled,
        "case_count": len(rows),
        "passed": sum(row.get("status") == "passed" for row in rows),
        "dsl_passed": dsl,
        "dsl_total": 3,
        "codeact_passed": python,
        "codeact_total": 2,
        "overall_total": 5,
        "rows": rows,
    }


def run_showcase(*, mode: str, fallback_enabled: bool, case_id: str, output: Path) -> int:
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing_nonempty_output:{output}")
    output.mkdir(parents=True, exist_ok=True)
    cases = load_showcase_cases()
    selected = cases if case_id == "all" else tuple(case for case in cases if case.case.task_id == case_id)
    if not selected:
        raise SystemExit(f"unknown_showcase_case:{case_id}")
    plan = [{"case_id": item.case.task_id, "expected_backend": item.expected_backend, "operation": item.case.operation, "max_dsl_attempts": 2, "max_python_attempts": 1, "rationale": item.capability_rationale} for item in selected]
    _write_json(output / "plan.json", {"mode": mode, "codeact_fallback": "on" if fallback_enabled else "off", "cases": plan})
    if mode == "dry-run":
        rows = [{"case_id": item.case.task_id, "historical_family": item.case.sample.task_family, "operation": item.case.operation, "expected_backend": item.expected_backend, "status": "not_started", "quality": None, "final_backend": None, "fallback_enabled": fallback_enabled, "fallback_attempted": False, "dsl_attempts": 0, "dsl_repair_count": 0, "last_dsl_failure": None, "python_attempts": 0, "provider_requests": 0, "provider_tokens": 0, "e2e_ms": 0, "reason": "dry_run", "source_path": str(item.case.spec.arguments.get("csv_path") or item.case.source_ref_id)} for item in selected]
    else:
        rows = []
        for item in selected:
            try:
                rows.append(_run_case(item, mode=mode, fallback_enabled=fallback_enabled, case_root=output / "slots" / item.case.task_id))
            except Exception as exc:
                rows.append({"case_id": item.case.task_id, "historical_family": item.case.sample.task_family, "operation": item.case.operation, "expected_backend": item.expected_backend, "status": "failed", "quality": False, "final_backend": None, "fallback_enabled": fallback_enabled, "fallback_attempted": False, "dsl_attempts": None, "dsl_repair_count": None, "last_dsl_failure": None, "python_attempts": None, "provider_requests": None, "provider_tokens": None, "e2e_ms": None, "reason": f"{type(exc).__name__}:{exc}", "source_path": str(item.case.spec.arguments.get("csv_path") or item.case.source_ref_id)})
    with (output / "task_results.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    summary = _summary(rows, mode=mode, fallback_enabled=fallback_enabled)
    _write_json(output / "summary.json", summary)
    _write_summary_md(output / "summary.md", summary)
    if mode == "dry-run":
        return 0
    return 0 if all(row.get("status") == "passed" for row in rows) else 1


def _write_summary_md(path: Path, summary: dict[str, object]) -> None:
    rows = summary["rows"]
    lines = ["# Contest CodeAct DSL Showcase", "", "| case_id | expected | status | final | quality |", "|---|---|---|---|---|"]
    lines.extend(f"| {row['case_id']} | {row['expected_backend']} | {row['status']} | {row.get('final_backend') or ''} | {row.get('quality')} |" for row in rows)
    lines.extend(["", f"DSL: {summary['dsl_passed']} / {summary['dsl_total']}", f"CodeAct fallback: {summary['codeact_passed']} / {summary['codeact_total']}", f"Overall: {summary['passed']} / {summary['overall_total']}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the independent five-case DSL/CodeAct showcase.")
    parser.add_argument("--mode", choices=("dry-run", "offline", "live"), default="dry-run")
    parser.add_argument("--codeact-fallback", choices=("off", "on"), default="off")
    parser.add_argument("--case", choices=("all", *CASE_IDS), default="all")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_showcase(mode=args.mode, fallback_enabled=args.codeact_fallback == "on", case_id=args.case, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
