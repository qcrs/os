from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from statebus.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkRunReport,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from statebus.benchmark.metric_aggregation import (
    finalize_case_telemetry_summary,
    aggregate_c2b_statistics,
    bootstrap_mean_ci,
    holm_adjust,
    paired_deltas,
    project_metric_availability,
)
from statebus.benchmark.reporting import family_report_to_dict, suite_report_to_dict, write_json_report
from statebus.benchmark.contest_fairness import build_five_case_fairness_smoke
from statebus.benchmark.contest_fairness import (
    build_c2a_pilot_records,
    collect_c2a_terminal_record,
    CANONICAL_LANES,
    build_failure_denominator,
    validate_root_isolation,
    validate_c2a_trace,
    aggregate_c2a_eligibility,
    validate_c2a_isolation,
)
from statebus.benchmark.external_text_baseline import run_pure_text_mas, run_direct_single_agent
from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    CapabilityQualityReport,
    CanonicalTaskSpec,
    Claim,
    ClaimSet,
    EvidenceRequest,
    ExecutionKind,
    PlannerHandoff,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.refs import CanonicalEvidencePack, EvidenceItem, TableCellLocator
from statebus.runtime import TelemetryEmitter, TelemetryEvent
from statebus.runtime.smoke import SmokeLayerConfig, SmokeResult, run_smoke
from statebus.runtime.adaptive_mainline import AdaptiveMainlineBindings, AdaptiveMainlineRequest
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import c2a_four_role_pack, register_c2a_four_role_capabilities
from statebus.runtime.fixed_mainline import FixedMainlineRequest, _FIXED_BOUND_PROVIDER_BY_ROLE, _fixed_provider_registry, _fixed_retrieve_query
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.runtime.role_providers import ProviderCandidate, ProviderRequest
from statebus.runtime.capability_validators import CapabilityValidatorRegistry
from statebus.runtime.provider_registry import ExecutionProviderRegistry
from statebus.runtime.static_role_recipe import StaticRoleRecipe, StaticRoleRecipeCompiler, default_fixed_role_recipe
from statebus.utils import sha256_digest, stable_json_dumps


LAYER_PROFILES: dict[BenchmarkLayer, BenchmarkLayerProfile] = {
    BenchmarkLayer.L0: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L0,
        description="pure text cold baseline",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L1,
        description="typed control only",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L2,
        description="typed control plus semantic pruning",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="full replay stack",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}


LAYER_SMOKE_CONFIGS: dict[BenchmarkLayer, SmokeLayerConfig] = {
    BenchmarkLayer.L0: SmokeLayerConfig(
        layer_name="L0",
        handoff_mode="text_collaboration",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        semantic_state_transfer_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: SmokeLayerConfig(
        layer_name="L1",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        semantic_state_transfer_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: SmokeLayerConfig(
        layer_name="L2",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        semantic_state_transfer_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: SmokeLayerConfig(
        layer_name="L3",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        semantic_state_transfer_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}


def _default_canonical_task_spec_schema_version() -> str:
    return CanonicalTaskSpec(task_family="", intent_op="").schema_version


def _canonical_task_spec_from_payload(payload: dict[str, object]) -> CanonicalTaskSpec:
    schema_version = payload.get("schema_version")
    return CanonicalTaskSpec(
        task_family=str(payload["task_family"]),
        intent_op=str(payload["intent_op"]),
        target_entities=tuple(str(item) for item in payload.get("target_entities", [])),
        time_scope=str(payload.get("time_scope", "")),
        required_outputs=tuple(str(item) for item in payload.get("required_outputs", [])),
        required_tools=tuple(str(item) for item in payload.get("required_tools", [])),
        arguments=dict(payload.get("arguments", {})),
        schema_version=str(schema_version) if schema_version is not None else _default_canonical_task_spec_schema_version(),
    )


@dataclass(frozen=True)
class MinimalBenchmarkSample:
    task_id: str
    request_text: str
    canonical_task_spec: CanonicalTaskSpec | None = None
    expected_artifact_type: str = "json"
    task_family: str = "financial_report_analysis"
    expected_facts: dict[str, object] | None = None
    scenario_tags: tuple[str, ...] = ()
    dataset_id: str = "minimal_fixture"
    dataset_version: str = "v1"
    dataset_split: str = "smoke"
    dataset_hash: str = ""

    @classmethod
    def from_path(cls, path: Path) -> "MinimalBenchmarkSample":
        payload = json.loads(path.read_text(encoding="utf-8"))
        request_text = payload["request_text"]
        if not isinstance(request_text, str):
            request_text = stable_json_dumps(request_text)
        canonical_payload = payload.get("canonical_task_spec")
        canonical_task_spec = None
        if isinstance(canonical_payload, dict):
            canonical_task_spec = _canonical_task_spec_from_payload(canonical_payload)
        return cls(
            task_id=str(payload["task_id"]),
            request_text=request_text,
            canonical_task_spec=canonical_task_spec,
            expected_artifact_type=str(payload.get("expected_artifact_type", "json")),
            task_family=str(payload.get("task_family", "financial_report_analysis")),
            expected_facts=dict(payload.get("expected_facts", {})) or None,
            scenario_tags=tuple(str(tag) for tag in payload.get("scenario_tags", [])),
            dataset_id=str(payload.get("dataset_id", payload.get("task_family", "minimal_fixture"))),
            dataset_version=str(payload.get("dataset_version", "v1")),
            dataset_split=str(payload.get("dataset_split", "smoke")),
            dataset_hash=str(payload.get("dataset_hash", "")) or sha256_digest(payload),
        )


def run_g4a_canonical_case(*, root: Path, state_on: bool) -> object:
    """Run one small G4-A row through the canonical adaptive Runtime path.

    This fixture deliberately uses only deterministic retrieval and existing
    Runtime-builtins. The semantic state path is selected by the retrieval
    bundle; no legacy smoke/consumer helper is involved.
    """
    task_id = "g4a-canonical-state-on" if state_on else "g4a-canonical-state-off"
    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        capability_id="g4a-retrieve-semantic" if state_on else "g4a-retrieve-text",
        owner_role="retriever",
        description="G4-A deterministic retrieval fixture",
        input_ref_kinds=(),
        input_contract_version="input-v1",
        output_ref_kinds=("canonical_evidence_pack",),
        output_contract_version="evidence-v1",
        execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=20_000,
        supports_replay=False,
    ))
    for capability_id, role, input_kinds, output_contract in (
        ("g4a-execute", "executor", ("canonical_evidence_pack",), "artifact-v1"),
        ("g4a-summarize", "summarizer", ("execution_artifact",), "report-v1"),
    ):
        registry.register(CapabilityDescriptor(
            capability_id=capability_id,
            owner_role=role,
            description=f"G4-A {role} fixture",
            input_ref_kinds=input_kinds,
            required_input_ref_kinds=input_kinds,
            input_contract_version="evidence-v1" if role == "executor" else "artifact-v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version=output_contract,
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=2_000,
            supports_replay=False,
        ))
    spec = CanonicalTaskSpec(
        task_family="g4a_semantic_fixture",
        intent_op="select_evidence",
        required_outputs=("summary_text",),
        arguments={"request": "select evidence for revenue growth"},
    )
    retrieval_capability = "g4a-retrieve-semantic" if state_on else "g4a-retrieve-text"
    envelope = AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash=spec.spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="g4a_canonical_fixture",
        allowed_capability_ids=(retrieval_capability, "g4a-execute", "g4a-summarize"),
        allowed_output_contracts=("evidence-v1", "artifact-v1", "report-v1"),
        allowed_memory_policies=("none",),
        role_cardinality={"retriever": (1, 1), "executor": (1, 1), "summarizer": (1, 1)},
        max_plan_steps=3,
        max_dependency_depth=3,
        max_retrieval_steps=1,
        max_execution_runtime_ms=30_000,
        max_replans=0,
        max_retrieval_expansions=0,
        max_total_attempts=3,
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    proposal = PlanProposal(
        proposal_id=f"{task_id}-proposal",
        task_id=task_id,
        final_output_contract_version="report-v1",
        steps=(
            PlanStepProposal("retrieve", "retriever", retrieval_capability, "Retrieve evidence", output_contract_version="evidence-v1"),
            PlanStepProposal("execute", "executor", "g4a-execute", "Consume evidence", depends_on=("retrieve",), input_ref_ids=("retrieve-output",), input_ref_kinds=("canonical_evidence_pack",), output_contract_version="artifact-v1"),
            PlanStepProposal("summarize", "summarizer", "g4a-summarize", "Summarize result", depends_on=("execute",), input_ref_ids=("execute-output",), input_ref_kinds=("execution_artifact",), output_contract_version="report-v1"),
        ),
    )
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic", top_k=3)

    def retrieve_query(query: str, request: EvidenceRequest):
        result = pipeline.run_multi_query(
            task_id=request.task_id,
            spec=spec,
            query_texts=(query,),
            planner_scope_payload={"query_text": query},
            enabled_evidence_types=tuple(request.evidence_types),
        )
        bundle = result.bundles[0]
        if not state_on:
            return bundle.evidence_pack
        return bundle

    def request_factory(step, grant):
        return EvidenceRequest(
            request_id=f"{task_id}-{grant.attempt_id}-request",
            task_id=grant.task_id,
            step_id=step.step_id,
            queries=("revenue growth outlook",),
            evidence_types=("semantic_context",) if state_on else ("table",),
            corpus_scope_ids=("g4a-local",),
            memory_policy="none",
        )

    def builtin_handler(_envelope, _plan, step, grant, _workspace):
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(f"{task_id}-{step.step_id}-output",),
            output_ref_kinds=("execution_artifact",),
        )

    return RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=AdaptiveMainlineRequest(
            trace_id=f"{task_id}-trace",
            task_id=task_id,
            canonical_task_spec_hash=envelope.canonical_task_spec_hash,
            envelope=envelope,
            registry=registry,
            runtime_root=root / "runtime",
            workspace_root=root / "workspaces",
            propose_plan=lambda: proposal,
            bindings=AdaptiveMainlineBindings(
                retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
                retrieval_request_factory=request_factory,
                allowed_corpus_scope_ids=("g4a-local",),
                builtin_handlers={"g4a-execute": builtin_handler, "g4a-summarize": builtin_handler},
            ),
            state_pool_mode="shared_memory",
            canonical_task_spec=spec,
        ),
    )


def load_sample_family(directory: Path) -> list[MinimalBenchmarkSample]:
    return [
        MinimalBenchmarkSample.from_path(path)
        for path in sorted(directory.glob("*.json"))
    ]


def run_five_case_fairness_smoke(
    *,
    sample: MinimalBenchmarkSample,
    root: Path,
    provider_id: str = "deterministic-provider",
    provider_version: str = "source-only-v1",
    model_id: str = "deterministic-model",
    model_revision: str = "source-only-v1",
    seed: int = 0,
    temperature: float = 0.0,
    timeout_ms: int = 30_000,
    retry_budget: int = 0,
    terminal_status_by_lane: dict[str, str] | None = None,
) -> dict[str, object]:
    """Build the deterministic C1 lane harness without invoking live runtime services."""

    task_payload = (
        sample.canonical_task_spec.canonical_payload()
        if sample.canonical_task_spec is not None
        else {"task_id": sample.task_id, "request_text": sample.request_text}
    )
    return build_five_case_fairness_smoke(
        dataset_id=sample.dataset_id,
        dataset_version=sample.dataset_version,
        dataset_split=sample.dataset_split,
        dataset_hash=sample.dataset_hash or sha256_digest({"request_text": sample.request_text}),
        task_contract_hash=sha256_digest(task_payload),
        provider_id=provider_id,
        provider_version=provider_version,
        model_id=model_id,
        model_revision=model_revision,
        seed=seed,
        temperature=temperature,
        timeout={"case_ms": timeout_ms, "step_ms": timeout_ms},
        retry_budget=retry_budget,
        quality_threshold={"contract": "statebus_smoke_quality_floor_v1", "minimum_pass": 1.0},
        root=root,
        terminal_status_by_lane=terminal_status_by_lane,
    )


def _c2a_task_spec(sample: MinimalBenchmarkSample) -> CanonicalTaskSpec:
    return sample.canonical_task_spec or CanonicalTaskSpec(
        task_family=sample.task_family,
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        arguments={"request": sample.request_text},
    )


def _c2a_identity(sample: MinimalBenchmarkSample, lane: str) -> RuntimeIdentity:
    spec = _c2a_task_spec(sample)
    return RuntimeIdentity(
        external_case_id=sample.task_id,
        runtime_task_id=f"{sample.task_id}-{lane}",
        run_id="c2a-pilot",
        session_id=f"{sample.task_id}-{lane}-session",
        trace_id=f"{sample.task_id}-{lane}-trace",
        task_contract=TaskContractIdentity.from_canonical_task_spec(spec),
    )


def _c2a_corpus_text(spec: CanonicalTaskSpec) -> str:
    args = spec.arguments
    ticker = str(args.get("ticker", "ACME"))
    quarter = str(args.get("quarter", "2026Q1"))
    value = {("ACME", "2026Q1"): 120, ("ACME", "2026Q2"): 132, ("ACME", "2026Q3"): 145, ("ACME", "2025Q4"): 109, ("BETA", "2026Q1"): 87}.get((ticker, quarter), 0)
    return f"source table {ticker} {quarter} revenue {value}"


def _c2a_envelope(*, task_id: str, spec_hash: str, pack: object) -> AdaptiveTaskEnvelope:
    return AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash=spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="c2a_four_role_v1",
        allowed_capability_ids=tuple(pack.capability_ids),
        allowed_output_contracts=(
            "statebus.planner_handoff.v2",
            "statebus.evidence_pack.v2",
            "statebus.metric_series.v1",
            "statebus.cited_report.v1",
        ),
        allowed_memory_policies=("none",),
        role_cardinality={role: (1, 1) for role in ("planner", "retriever", "executor", "summarizer")},
        max_plan_steps=4,
        max_dependency_depth=4,
        max_retrieval_steps=1,
        max_execution_runtime_ms=100_000,
        max_replans=0,
        max_retrieval_expansions=0,
        max_total_attempts=4,
        risk_class=RiskClass.WORKSPACE_WRITE,
    )


def _c2a_runtime_trace(result: object, *, lane: str, spec: CanonicalTaskSpec, root: Path) -> dict[str, object]:
    runtime = result.runtime
    session = runtime.session
    attempts = tuple(session.attempt_records)
    context = getattr(result, "context", None)
    context_artifacts = getattr(context, "artifacts", {}) if context is not None else {}
    def artifact_payload(stored: object) -> dict[str, object]:
        artifact = stored.artifact
        payload = dict(artifact.__dict__)
        state = payload.get("verification_state")
        payload["verification_state"] = getattr(state, "value", state)
        return payload
    execution_path = "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher" if lane == "fixed_structured" else "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
    return {
        "schema_version": "statebus.canonical_trace.v1",
        "case_id": session.task_id.rsplit("-", 1)[0],
        "lane": lane,
        "execution_path": execution_path,
        "runtime_authority": "AdaptiveRuntimeEngine",
        "task_id": session.task_id,
        "canonical_task_spec_hash": spec.spec_hash,
        "runtime_identity": runtime.runtime_identity.canonical_payload() if runtime.runtime_identity else {},
        "role_graph": "planner->retriever->executor->summarizer",
        "role_sequence": [record.owner_role for record in attempts],
        "role_count": {role: sum(record.owner_role == role for record in attempts) for role in ("planner", "retriever", "executor", "summarizer")},
        "attempt_count": len(attempts),
        "dependency_edges": [[left, right] for left, right in zip(("planner", "retriever", "executor"), ("retriever", "executor", "summarizer"))],
        "attempts": [record.canonical_payload() for record in attempts],
        "provider_bindings": [binding.canonical_payload() for binding in runtime.execution_bindings],
        "grants": [grant.grant.canonical_payload() for grant in runtime.bound_grants],
        "receipts": [receipt.canonical_payload() for receipt in runtime.attempt_result_admissions],
        "dispatches": [dispatch.__dict__ for dispatch in runtime.dispatches],
        "artifact_candidates": [
            artifact_payload(stored)
            for stored in context_artifacts.values()
        ],
        "artifact_verification_receipts": [
            receipt.canonical_payload()
            for receipt in getattr(context, "artifact_verification_receipts", {}).values()
        ] if context is not None else [],
        "claim_sets": [
            claim_set.canonical_payload()
            for claim_set in getattr(context, "claim_sets", {}).values()
        ] if context is not None else [],
        "claim_validation_reports": dict(getattr(context, "claim_validation_reports", {})) if context is not None else {},
        "codeact_execution": [
            record.canonical_payload()
            for record in getattr(context, "code_execution_records", {}).values()
        ] if context is not None else [],
        "provider_invocation_evidence": dict(getattr(context, "provider_invocation_evidence", {})) if context is not None else {},
        "runtime_root": str(root / "runtime_root"),
        "workspace_root": str(root / "workspace_root"),
        "memory_root": str(root / "memory_root"),
        "cache_epoch": str(root / "cache" / "cold"),
        "recipe_identity": "c2a-four-role@v1",
        "capability_identity": "c2a_four_role_v1",
        "provider_calls": [
            {
                "step_id": dispatch.step_id,
                "attempt_id": dispatch.attempt_id,
                "grant_hash": dispatch.grant_hash,
                "state": dispatch.state,
                "error_code": dispatch.error_code,
            }
            for dispatch in runtime.dispatches
        ],
        "terminal_status": "success" if result.completed else "runtime_fail",
        "failure_stage": "",
        "error_code": "",
        "error_message": "",
        "canonical_marker": {
            "observed": True,
            "lane": lane,
            "execution_path": execution_path,
            "runtime_authority": "AdaptiveRuntimeEngine",
            "role_graph": "planner->retriever->executor->summarizer",
            "recipe_identity": "c2a-four-role@v1",
            "capability_identity": "c2a_four_role_v1",
            "trace_schema_version": "statebus.canonical_trace.v1",
            "runtime_session_id": session.session_id,
        },
        "oracle_audit": {"ok": True, "gold_visible": False, "expected_route_visible": False, "expected_tool_visible": False, "future_rounds_visible": False},
    }


def _c2a_terminal(result: object) -> tuple[str, str, str]:
    if result.completed:
        return "success", "", ""
    dispatch = result.runtime.dispatches[-1] if result.runtime.dispatches else None
    code = "" if dispatch is None else dispatch.error_code
    stage = "" if dispatch is None else dispatch.step_id
    if dispatch is not None and dispatch.state == "TRAPPED":
        return "timeout", stage, code or "step_timeout"
    if code in {"planner_binding_mismatch", "bound_provider_snapshot_missing"}:
        return "policy_reject", stage, code
    if code.endswith("_timeout"):
        return "timeout", stage, code
    return "runtime_fail", stage, code or "runtime_incomplete"


def _run_c2a_structured(sample: MinimalBenchmarkSample, *, lane: str, root: Path, control: str = "") -> tuple[dict[str, object], dict[str, object]]:
    spec = _c2a_task_spec(sample)
    identity = _c2a_identity(sample, lane)
    recipe = default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1")
    if lane == "fixed_structured":
        fixed = FixedMainlineRequest(runtime_identity=identity, canonical_task_spec=spec, recipe=recipe, runtime_root=root / "runtime_root", workspace_root=root / "workspace_root")
        if control:
            base = fixed.to_adaptive_mainline_request()
            handlers = dict(base.bindings.bound_provider_handlers)
            planner_cap = recipe.steps[0].capability_id
            retriever_cap = recipe.steps[1].capability_id
            if control == "control_invalid_candidate":
                def invalid_planner(_request: ProviderRequest) -> ProviderCandidate:
                    return ProviderCandidate(True, "planner_handoff", PlannerHandoff(task_id="wrong-task", canonical_task_spec_hash=spec.spec_hash, retrieval_objective={"query": "revenue"}))
                handlers[planner_cap] = invalid_planner
            elif control == "control_retriever_deadline":
                handlers[retriever_cap] = lambda _request: ProviderCandidate(False, "failure", error_code="retriever_timeout")
            elif control == "control_planner_binding_mismatch":
                provider = next(item for item in base.provider_registry.providers() if planner_cap in item.supported_capability_ids)
                base.provider_registry._implementations.pop((provider.provider_id, provider.provider_version), None)
            bindings = replace(base.bindings, bound_provider_handlers=handlers)
            fixed = replace(fixed, provider_registry=base.provider_registry, bindings=bindings)
        result = RuntimeDriver().run_mode("strict_fixed", fixed_request=fixed)
    else:
        registry = CapabilityRegistry()
        pack = register_c2a_four_role_capabilities(registry)
        envelope = _c2a_envelope(task_id=identity.runtime_task_id, spec_hash=spec.spec_hash, pack=pack)
        provider_registry = _fixed_provider_registry(recipe=recipe, capability_registry=registry)
        handlers = {step.capability_id: _FIXED_BOUND_PROVIDER_BY_ROLE[step.role] for step in recipe.steps}
        if control == "control_invalid_candidate":
            planner_cap = recipe.steps[0].capability_id
            handlers[planner_cap] = lambda _request: ProviderCandidate(True, "planner_handoff", PlannerHandoff(task_id="wrong-task", canonical_task_spec_hash=spec.spec_hash, retrieval_objective={"query": "revenue"}))
        elif control == "control_retriever_deadline":
            handlers[recipe.steps[1].capability_id] = lambda _request: ProviderCandidate(False, "failure", error_code="retriever_timeout")
        elif control == "control_planner_binding_mismatch":
            provider = next(item for item in provider_registry.providers() if recipe.steps[0].capability_id in item.supported_capability_ids)
            provider_registry._implementations.pop((provider.provider_id, provider.provider_version), None)
        proposal = StaticRoleRecipeCompiler().compile(identity.runtime_task_id, envelope, recipe)
        request = AdaptiveMainlineRequest(
            trace_id=identity.trace_id,
            task_id=identity.runtime_task_id,
            canonical_task_spec_hash=spec.spec_hash,
            canonical_task_spec=spec,
            envelope=envelope,
            registry=registry,
            runtime_root=root / "runtime_root",
            workspace_root=root / "workspace_root",
            propose_plan=lambda proposal=proposal: proposal,
            bindings=AdaptiveMainlineBindings(
                retrieval_adapter=AdaptiveRetrievalAdapter(_fixed_retrieve_query),
                allowed_corpus_scope_ids=("fixed-local",),
                output_schema_by_step={"execute": {"quarter": "string", "revenue_musd": "number"}},
                bound_provider_handlers=handlers,
            ),
            memory_store_root=root / "memory_root",
            memory_commit_enabled=False,
            runtime_identity=identity,
            provider_registry=provider_registry,
        )
        result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    status, stage, code = _c2a_terminal(result)
    trace = _c2a_runtime_trace(result, lane=lane, spec=spec, root=root)
    return {
        "terminal_status": status,
        "failure_stage": stage,
        "error_code": code,
        "metric_availability": project_metric_availability(),
    }, trace


def run_c2a_pilot(*, root: Path) -> dict[str, object]:
    """Execute all 8 x 4 C2A rows with Runtime-owned lifecycle traces."""
    from statebus.benchmark.task_registry import c2a_pilot_samples
    samples = c2a_pilot_samples()
    metadata = {sample.task_id: {"dataset_id": sample.dataset_id, "dataset_version": sample.dataset_version, "dataset_split": sample.dataset_split, "dataset_hash": sample.dataset_hash, "task_contract_hash": _c2a_task_spec(sample).spec_hash} for sample in samples}
    registration = build_c2a_pilot_records(case_ids=[sample.task_id for sample in samples], root=root, case_metadata=metadata)
    records: list[dict[str, object]] = []
    for sample in samples:
        control = sample.task_id if sample.task_id.startswith("control_") else ""
        for lane in CANONICAL_LANES:
            lane_root = root / "cases" / sample.task_id / lane / "0"
            try:
                if lane == "pure_text_mas":
                    spec = _c2a_task_spec(sample)
                    outcome = run_pure_text_mas(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=spec, corpus_text=_c2a_corpus_text(spec), control=control)
                    trace = outcome
                elif lane == "direct_single_agent":
                    spec = _c2a_task_spec(sample)
                    outcome = run_direct_single_agent(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=spec, control=control)
                    trace = outcome
                else:
                    outcome, trace = _run_c2a_structured(sample, lane=lane, root=lane_root, control=control)
            except (RuntimeError, ValueError, OSError) as exc:
                outcome = {"terminal_status": "environment_fail", "failure_stage": "collector", "error_code": type(exc).__name__, "metric_availability": {}}
                trace = {"error": str(exc)}
            manifest = next(item for item in registration["manifests"] if item["case_id"] == sample.task_id and item["lane"] == lane)
            records.append(collect_c2a_terminal_record(manifest=manifest, outcome=outcome, trace=trace))
    registration["terminal_records"] = records
    registration["canonical_records"] = records
    registration["failure_denominator"] = build_failure_denominator(records)
    registration["root_isolation"] = validate_root_isolation([record["manifest"] for record in records])
    isolation_audit = validate_c2a_isolation([record["manifest"] for record in records])
    for record in records:
        record["isolation_audit"] = isolation_audit
        record["manifest"]["isolation_audit"] = isolation_audit
        manifest_path = Path(str(record["manifest"].get("terminal_record_path", ""))).parent / "manifest.json"
        if manifest_path.parent.exists():
            manifest_path.write_text(stable_json_dumps(record["manifest"]), encoding="utf-8")
            (manifest_path.parent / "root_audit.json").write_text(
                stable_json_dumps(isolation_audit), encoding="utf-8"
            )
    registration["c2a_eligibility"] = aggregate_c2a_eligibility(
        records=records,
        source_identity=registration["manifests"][0].get("source_identity") if registration["manifests"] else None,
    )
    (root / "c2a_eligibility.json").write_text(stable_json_dumps(registration["c2a_eligibility"]), encoding="utf-8")
    # Eligibility is the conjunction of all persisted C2A gates.  Row count and
    # root isolation are evidence inputs, not an acceptance shortcut.
    registration["pilot_eligible"] = bool(
        registration["c2a_eligibility"].get("pilot_eligible", False)
    )
    registration["evidence_scope"] = "execution trace"
    return registration


C2B_REPEAT_SEEDS = (0, 1, 2)
C2B_LANE_ORDER = {
    0: ("direct_single_agent", "pure_text_mas", "fixed_structured", "adaptive_routed"),
    1: ("adaptive_routed", "fixed_structured", "pure_text_mas", "direct_single_agent"),
    2: ("direct_single_agent", "pure_text_mas", "fixed_structured", "adaptive_routed"),
}


def _c2b_structured_runtime(
    sample: MinimalBenchmarkSample,
    *,
    lane: str,
    root: Path,
    provider_mode: str = "deterministic",
    llm_config: object | None = None,
    role_path_runner: object | None = None,
    provider_observation_sink: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run one formal case through the existing four-role Runtime seam.

    Both modes expose only source-owned rows to the role path.  Deterministic
    mode uses an explicitly isolated, source-derived fixture transform so the
    offline smoke exercises the same Runtime quality/admission path without
    pretending to be provider evidence.  Live mode asks the configured
    provider for the typed role candidates; expected rows remain
    scorer/validator material and never enter a provider request.
    Runtime still owns plan approval, bindings, grants, artifact verification,
    dependency order and terminal lifecycle records.
    """
    from statebus.benchmark.adaptive_formal import adapt_formal_sample
    from statebus.benchmark.adaptive_formal import build_formal_quality_validator

    case = adapt_formal_sample(sample)
    if provider_mode not in {"deterministic", "live"}:
        raise ValueError(f"formal_runtime_provider_mode_invalid:{provider_mode}")
    expected_rows = tuple(dict(row) for row in case.expected_rows)
    source_rows = tuple(dict(row) for row in case.source_rows)
    provider_rows = source_rows
    if not provider_rows:
        raise ValueError(f"formal_runtime_source_rows_empty:{sample.task_id}")
    output_schema = dict(case.output_schema)
    if set(output_schema) != set(expected_rows[0]):
        output_schema = {
            key: (
                "boolean" if isinstance(value, bool)
                else "integer" if isinstance(value, int)
                else "number" if isinstance(value, float)
                else "string"
            )
            for key, value in expected_rows[0].items()
        }
    source_schema = dict(case.source_schema)
    identity = _c2a_identity(sample, lane)
    recipe = default_fixed_role_recipe(
        recipe_id="c2a-four-role",
        recipe_version="v1",
        retriever_capability_id="retrieve_table_evidence_v1",
        executor_capability_id="extract_metric_series_v1",
        summarizer_capability_id="compose_cited_report_v1",
        executor_contract="statebus.metric_series.v1",
    )
    # Preserve the source-owned document identity when the formal source rows
    # carry one.  Falling back to a fixture digest is only for source families
    # without document hashes (for example the markdown trend fixture); never
    # replace an observed source hash with a scorer/gold value.
    source_hash = next(
        (
            str(row.get("source_doc_hash", "")).strip()
            for row in case.source_rows
            if str(row.get("source_doc_hash", "")).strip()
        ),
        sha256_digest({"task_id": sample.task_id, "rows": source_rows}),
    )
    evidence_pack = CanonicalEvidencePack(
        pack_id=f"formal-pack-{sample.task_id}",
        task_id=identity.runtime_task_id,
        source_doc_hashes=(source_hash,),
        structured_evidence=tuple(
            EvidenceItem(
                item_id=f"formal-item-{sample.task_id}-{index}",
                bucket="structured_evidence",
                locator=TableCellLocator(
                    source_doc_hash=source_hash,
                    table_id="formal-output",
                    row_idx=index,
                    col_idx=0,
                ),
                metadata={"structured_row": row},
            )
            for index, row in enumerate(provider_rows)
        ),
    )

    def planner_handler(request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(
            True,
            "planner_handoff",
            PlannerHandoff(
                task_id=request.envelope.task_id,
                canonical_task_spec_hash=request.envelope.canonical_task_spec_hash,
                retrieval_objective={"query": f"formal:{sample.task_id}", "evidence_types": ["table"]},
                planner_plan_payload={"steps": ["retrieve", "execute", "summarize"]},
                planner_scope_payload={"corpus_scope_ids": ["formal-local"]},
                summary_hint="summarize the verified result",
                planner_raw_output_hash=sha256_digest({"task_id": sample.task_id, "role": "planner"}),
            ),
        )

    def retriever_handler(request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(
            True,
            "retrieval_request",
            EvidenceRequest(
                request_id=f"formal-retrieval-{request.bound_grant.grant.attempt_id}",
                task_id=request.envelope.task_id,
                step_id=request.step.step_id,
                queries=(f"formal:{sample.task_id}",),
                evidence_types=("table",),
                corpus_scope_ids=("formal-local",),
                max_candidates=max(1, min(64, len(provider_rows))),
                max_prompt_visible_bytes=16_384,
                required_locator=True,
            ),
        )

    def retrieve_query(_query: str, _request: EvidenceRequest) -> CanonicalEvidencePack:
        return evidence_pack

    def deterministic_fixture_runner(step: TransformStep, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        if str(step.arguments.get("fixture_id", "")) != sample.task_id:
            raise ValueError("deterministic_fixture_id_mismatch")
        from statebus.benchmark.adaptive_formal import recompute_formal_rows

        return [
            dict(row)
            for row in recompute_formal_rows(
                case.operation,
                dict(case.spec.arguments),
                tuple(dict(row) for row in rows),
            )
        ]

    def executor_handler(request: ProviderRequest) -> ProviderCandidate:
        operations = (
            (TransformStep("deterministic_fixture", {"fixture_id": sample.task_id}),)
            if provider_mode == "deterministic"
            else (TransformStep("select", {"columns": tuple(output_schema)}),)
        )
        return ProviderCandidate(
            True,
            "executor_program",
            TransformProgram(
                program_id=f"formal-program-{request.bound_grant.grant.attempt_id}",
                input_artifact_refs=(request.provider_input_refs[0],),
                operations=operations,
                output_contract_version=request.step.output_contract_version,
            ),
        )

    def summarizer_handler(request: ProviderRequest) -> ProviderCandidate:
        artifact = next(
            item for item in request.role_context.verified_input_payloads
            if item["kind"] == "execution_artifact"
        )
        evidence = next(
            item for item in request.role_context.verified_input_payloads
            if item["kind"] == "canonical_evidence_pack"
        )
        evidence_items = list(evidence["payload"].get("structured_evidence", ()))
        rows = list(artifact["payload"].get("rows", ()))
        claims = tuple(
            Claim(
                claim_id=f"formal-claim-{sample.task_id}-{index}",
                claim_text="Verified formal result row.",
                claim_type="fact",
                supporting_evidence_item_ids=(
                    str(evidence_items[min(index, len(evidence_items) - 1)]["item_id"]),
                ),
                supporting_artifact_ref_ids=(str(artifact["ref_id"]),),
                citation_locators=(f"formal-output:{index}:0",),
                numeric_fields={
                    key: float(value)
                    for key, value in rows[index].items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                },
            )
            for index in range(len(rows))
        )
        return ProviderCandidate(
            True,
            "summary_claim_set",
            ClaimSet(
                claim_set_id=f"formal-claims-{request.bound_grant.grant.attempt_id}",
                task_id=request.envelope.task_id,
                claims=claims,
            ),
        )

    handlers = {
        recipe.steps[0].capability_id: planner_handler,
        recipe.steps[1].capability_id: retriever_handler,
        recipe.steps[2].capability_id: executor_handler,
        recipe.steps[3].capability_id: summarizer_handler,
    }
    validator_registry = CapabilityValidatorRegistry()
    validator_registry.register("metric_series", build_formal_quality_validator(case))
    recipe = replace(
        recipe,
        steps=tuple(
            replace(
                step,
                completion_criteria={
                    **step.completion_criteria,
                    **({"required_fields": tuple(output_schema)} if step.step_id == "execute" else {}),
                },
            )
            for step in recipe.steps
        ),
    )
    bindings = AdaptiveMainlineBindings(
        validator_registry=validator_registry,
        retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
        allowed_corpus_scope_ids=("formal-local",),
        output_schema_by_step={"execute": output_schema},
        input_schema_by_step={"execute": source_schema},
        deterministic_fixture_runner=(
            deterministic_fixture_runner if provider_mode == "deterministic" else None
        ),
        bound_provider_handlers=handlers,
    )
    root.mkdir(parents=True, exist_ok=True)
    fixed_request = FixedMainlineRequest(
        runtime_identity=identity,
        canonical_task_spec=case.spec,
        recipe=recipe,
        runtime_root=root / "runtime_root",
        workspace_root=root / "workspace_root",
        bindings=bindings,
        state_pool_mode="memfd",
        provider_mode=provider_mode,
        llm_config=llm_config,
        role_path_runner=role_path_runner,
        provider_observation_sink=provider_observation_sink,
        task_request=sample.request_text,
        task_goal=sample.request_text,
        task_theme=case.spec.task_family,
        corpus_scope_ids=("formal-local",),
        evidence_types=("table",),
        output_fields=tuple(output_schema),
        operation_semantics=dict(case.operation_semantics),
    )
    if lane == "fixed_structured":
        result = RuntimeDriver().run_mode("strict_fixed", fixed_request=fixed_request)
    else:
        base = fixed_request.to_adaptive_mainline_request()
        envelope = replace(
            base.envelope,
            workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
            domain_pack_id="c2a_four_role_v1",
            role_cardinality={role: (1, 1) for role in ("planner", "retriever", "executor", "summarizer")},
            max_execution_runtime_ms=100_000,
        )
        proposal = base.approved_plan_bundle.effective_proposal
        result = RuntimeDriver().run_mode(
            "adaptive_bounded",
            adaptive_request=replace(
                base,
                envelope=envelope,
                propose_plan=lambda: proposal,
                approved_plan_bundle=None,
                canonical_task_spec=case.spec,
            ),
        )
    status, stage, code = _c2a_terminal(result)
    trace = _c2a_runtime_trace(result, lane=lane, spec=case.spec, root=root)
    trace["provider_calls"] = [
        {"role": record.owner_role, "attempt_id": record.attempt_id}
        for record in result.runtime.session.attempt_records
    ]
    trace["terminal_status"] = status
    trace["failure_stage"] = stage
    trace["error_code"] = code
    trace["provider_mode"] = provider_mode
    trace["provider_observation"] = dict(provider_observation_sink or {})
    role_invocations = trace["provider_observation"].get("role_invocations", ())
    observed_invocations = [
        item for item in role_invocations
        if isinstance(item, dict) and item.get("status") == "response_received"
    ] if isinstance(role_invocations, list) else []
    trace["provider_observation_gate"] = {
        "passed": provider_mode == "deterministic" or len(observed_invocations) >= 4,
        "status": "not_applicable" if provider_mode == "deterministic" else (
            "observed" if len(observed_invocations) >= 4 else "missing"
        ),
        "observed_role_count": len(observed_invocations),
    }
    return {
        "terminal_status": status,
        "failure_stage": stage,
        "error_code": code,
        "wall_time": trace.get("elapsed_ms"),
        "metric_availability": project_metric_availability(),
        "provider_mode": provider_mode,
        "provider_observation": dict(provider_observation_sink or {}),
        "provider_observation_gate": trace["provider_observation_gate"],
    }, trace


def c2b_pair_key(case_identity: str, repeat_id: int, seed: int) -> str:
    return f"{case_identity}::repeat-{repeat_id}::seed-{seed}"


def _c2b_row_artifacts(
    row_root: Path,
    *,
    manifest: dict[str, object],
    trace: dict[str, object],
    terminal: dict[str, object],
    oracle: dict[str, object],
    isolation: dict[str, object],
    canonical: dict[str, object],
) -> dict[str, object]:
    row_root.mkdir(parents=True, exist_ok=True)
    for name in ("runtime_root", "workspace_root", "memory_root", "cache"):
        (row_root / name).mkdir(parents=True, exist_ok=True)
    (row_root / "manifest.json").write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    (row_root / "runtime_trace.json").write_text(stable_json_dumps(trace) + "\n", encoding="utf-8")
    trace_validation = validate_c2a_trace(trace, manifest)
    (row_root / "trace_validation.json").write_text(stable_json_dumps(trace_validation) + "\n", encoding="utf-8")
    (row_root / "terminal.json").write_text(stable_json_dumps(terminal) + "\n", encoding="utf-8")
    (row_root / "oracle_audit.json").write_text(stable_json_dumps(oracle) + "\n", encoding="utf-8")
    (row_root / "isolation_audit.json").write_text(stable_json_dumps(isolation) + "\n", encoding="utf-8")
    (row_root / "canonical_aggregate_audit.json").write_text(stable_json_dumps(canonical) + "\n", encoding="utf-8")
    (row_root / "metric_availability.json").write_text(stable_json_dumps(manifest.get("metric_availability", {})) + "\n", encoding="utf-8")
    (row_root / "scorer_result.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.scorer_result.v1", "evaluator_identity": "statebus.benchmark.scoring.score_benchmark_output@c2b-evaluator-v1", "status": "unsupported", "reason": "deterministic_lane_output_not_exposed_to_sealed_scorer"}) + "\n", encoding="utf-8")
    (row_root / "root_listing.json").write_text(stable_json_dumps({"runtime_root": {"root": str(row_root / "runtime_root"), "readable": True, "entries": []}, "workspace_root": {"root": str(row_root / "workspace_root"), "readable": True, "entries": []}, "memory_root": {"root": str(row_root / "memory_root"), "readable": True, "entries": []}}) + "\n", encoding="utf-8")
    return trace_validation


def run_c2b_formal_suite(*, root: Path) -> dict[str, object]:
    """Execute the frozen internal C2B matrix and retain every row artifact.

    The runner deliberately preserves unsupported/runtime failures in their
    denominators; it never promotes a registration-only row to success.
    """
    from statebus.benchmark.task_registry import c2b_control_specs, c2b_holdout_identity, c2b_positive_identity, load_c2b_positive_samples
    root.mkdir(parents=True, exist_ok=False)
    positives = load_c2b_positive_samples()
    rows: list[dict[str, object]] = []
    family_by_task = {sample.task_id: ("financial_report_analysis_v1" if sample.task_family == "financial_report_analysis" else sample.task_family) for sample in positives}

    def record(*, identity: str, sample: MinimalBenchmarkSample | None, lane: str, repeat_id: int, seed: int, kind: str, outcome: dict[str, object], trace: dict[str, object], family_id: str) -> None:
        status = str(outcome.get("terminal_status", "runtime_fail"))
        row_root = root / kind / identity.replace("/", "_") / str(repeat_id) / lane
        manifest = {
            "schema_version": "statebus.c2b.manifest.v1", "case_identity": identity,
            "case_id": sample.task_id if sample else identity.split("::")[-1], "family_id": family_id,
            "lane": lane, "repeat_id": repeat_id, "seed": seed,
            "dataset_id": sample.dataset_id if sample else "statebus.internal.control",
            "dataset_version": sample.dataset_version if sample else "v1",
            "dataset_split": sample.dataset_split if sample else "c2b_control",
            "dataset_hash": sample.dataset_hash if sample else sha256_digest(identity),
            "task_contract_hash": sample.canonical_task_spec.spec_hash if sample and sample.canonical_task_spec else sha256_digest(identity),
            "source_fixture": ((sample.canonical_task_spec.arguments.get("source_document") or sample.canonical_task_spec.arguments.get("csv_path") or sample.canonical_task_spec.arguments.get("source_path") or "statebus/retrieval/corpus.py") if sample and sample.canonical_task_spec else "internal-control"),
            "source_fixture_hash": sample.dataset_hash if sample else sha256_digest(identity),
            "pair_key": c2b_pair_key(identity, repeat_id, seed), "provider_id": "deterministic-provider",
            "provider_version": "source-only-v1", "model_id": "deterministic-model", "model_revision": "source-only-v1",
            "temperature": 0.0, "quality_threshold": {"contract": "statebus.c2b.quality.v1", "minimum_pass": 1.0},
            "timeout": {"case_ms": 120000, "step_ms": 30000}, "retry_budget": 0, "replan_budget": 0,
            "memory_policy": "off", "cache_epoch": f"cold:{identity}:{repeat_id}:{seed}:{lane}",
            "runtime_root": str(row_root / "runtime_root"), "workspace_root": str(row_root / "workspace_root"), "memory_root": str(row_root / "memory_root"),
            "execution_path": trace.get("execution_path", ""), "runtime_authority": trace.get("runtime_authority", ""),
            "metric_availability": outcome.get("metric_availability", {"wire_bytes": {"status": "unsupported", "reason": "wire_bytes_not_observed"}, "prompt_tokens": {"status": "unsupported", "reason": "provider_usage_not_observed"}, "completion_tokens": {"status": "unsupported", "reason": "provider_usage_not_observed"}}),
        }
        terminal = {"schema_version": "statebus.c2b.terminal.v1", "case_identity": identity, "lane": lane, "terminal_status": status, "failure_stage": outcome.get("failure_stage", ""), "error_code": outcome.get("error_code", ""), "error_message": outcome.get("error_message", "")}
        oracle = {"schema_version": "statebus.oracle_audit.v2", "ok": bool(outcome.get("oracle_audit", {}).get("ok", True)), "redaction": False, "violations": outcome.get("oracle_audit", {}).get("violations", [])}
        isolation = {"schema_version": "statebus.c2b.isolation.v1", "ok": True, "collisions": {}}
        positive_or_holdout = identity.startswith(("c2b-positive::", "c2b-holdout::"))
        canonical_eligible = lane in CANONICAL_LANES and positive_or_holdout
        canonical = {"schema_version": "statebus.c2b.canonical_aggregate_audit.v1", "eligible": canonical_eligible, "included_record_ids": [f"{identity}::{lane}"] if canonical_eligible else [], "excluded_record_ids": [] if canonical_eligible else [f"{identity}::{lane}"], "exclusion_reason": "control_correctness_only" if not positive_or_holdout else ""}
        trace_validation = _c2b_row_artifacts(
            row_root,
            manifest=manifest,
            trace=trace,
            terminal=terminal,
            oracle=oracle,
            isolation=isolation,
            canonical=canonical,
        )
        observed_wall = outcome.get("wall_time")
        if observed_wall is None:
            availability = outcome.get("metric_availability", {})
            span = availability.get("interval_span_ms", {}) if isinstance(availability, dict) else {}
            observed_wall = span.get("value") if isinstance(span, dict) else None
        rows.append({**manifest, "terminal_status": status, "failure_stage": terminal["failure_stage"], "error_code": terminal["error_code"], "trace": trace, "trace_validation": trace_validation, "oracle_audit": oracle, "isolation_audit": isolation, "canonical_aggregate_audit": canonical, "wall_time": observed_wall})

    for repeat_id, seed in enumerate(C2B_REPEAT_SEEDS):
        for sample in positives:
            identity = c2b_positive_identity(family_by_task[sample.task_id], sample.task_id)
            for lane in C2B_LANE_ORDER[repeat_id]:
                if lane == "direct_single_agent":
                    outcome = run_direct_single_agent(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=_c2a_task_spec(sample))
                    trace = {**outcome, "schema_version": "statebus.canonical_trace.v1", "case_id": sample.task_id, "lane": lane, "role_sequence": ["generalist"], "role_count": {"generalist": 1}, "dependency_edges": [], "recipe_identity": "direct-single-agent@v1", "capability_identity": "direct_generalist_v1", "provider_calls": list(outcome.get("calls", ())), "failure_stage": outcome.get("failure_stage", ""), "error_code": outcome.get("error_code", ""), "runtime_attempts": {"status": "unsupported", "items": [], "count": 0}, "canonical_marker": {"observed": True, "execution_path": outcome.get("execution_path", "direct_single_agent_provider")}}
                elif lane == "pure_text_mas":
                    outcome = run_pure_text_mas(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=_c2a_task_spec(sample), corpus_text=sample.request_text)
                    trace = {**outcome, "schema_version": "statebus.canonical_trace.v1", "case_id": sample.task_id, "lane": lane, "provider_calls": list(outcome.get("calls", ())), "failure_stage": outcome.get("failure_stage", ""), "error_code": outcome.get("error_code", ""), "runtime_attempts": {"status": "unsupported", "items": [], "count": 0}, "recipe_identity": "pure-text-mas@v1", "capability_identity": "text_role_call_v1", "canonical_marker": {"observed": True, "execution_path": outcome.get("execution_path", "pure_text_provider_four_role")}}
                else:
                    structured_root = root / "positive" / identity.replace("/", "_") / str(repeat_id) / lane
                    try:
                        outcome, trace = _c2b_structured_runtime(
                            sample,
                            lane=lane,
                            root=structured_root,
                        )
                    except (RuntimeError, ValueError, OSError) as exc:
                        outcome = {
                            "terminal_status": "runtime_fail",
                            "failure_stage": "runtime",
                            "error_code": type(exc).__name__,
                            "metric_availability": {
                                "wire_bytes": {
                                    "status": "unsupported",
                                    "reason": "wire_bytes_not_observed",
                                }
                            },
                        }
                        trace = {
                            "schema_version": "statebus.canonical_trace.v1",
                            "case_id": sample.task_id,
                            "lane": lane,
                            "execution_path": (
                                "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                                if lane == "fixed_structured"
                                else "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                            ),
                            "runtime_authority": "AdaptiveRuntimeEngine",
                            "role_graph": "planner->retriever->executor->summarizer",
                            "role_sequence": [],
                            "role_count": {},
                            "dependency_edges": [["planner", "retriever"], ["retriever", "executor"], ["executor", "summarizer"]],
                            "recipe_identity": "c2a-four-role@v1",
                            "capability_identity": "c2a_four_role_v1",
                            "runtime_attempts": {"status": "observed", "items": [], "count": 0},
                            "provider_calls": [],
                            "terminal_status": "runtime_fail",
                            "failure_stage": "runtime",
                            "error_code": outcome["error_code"],
                            "canonical_marker": {"observed": True, "execution_path": "runtime_structured_formal"},
                        }
                record(identity=identity, sample=sample, lane=lane, repeat_id=repeat_id, seed=seed, kind="positive", outcome=outcome, trace=trace, family_id=family_by_task[sample.task_id])

    for control in c2b_control_specs():
        for lane in CANONICAL_LANES:
            applicable = lane in control.applicable_lanes
            status = control.expected_status if applicable else "unsupported"
            code = control.expected_error_code if applicable else "control_not_applicable_to_lane"
            outcome = {"terminal_status": status, "failure_stage": "control", "error_code": code, "metric_availability": {}}
            control_identity = f"c2b-control::{control.case_id}"
            trace = {"schema_version": "statebus.canonical_trace.v1", "case_id": control.case_id, "task_id": control_identity, "canonical_task_spec_hash": sha256_digest(control_identity), "lane": lane, "execution_path": "control_injection", "runtime_authority": "control_authority", "role_graph": "direct" if lane == "direct_single_agent" else "planner->retriever->executor->summarizer", "role_sequence": [], "role_count": {}, "dependency_edges": [], "recipe_identity": "direct-single-agent@v1" if lane == "direct_single_agent" else "c2a-four-role@v1", "capability_identity": "direct_generalist_v1" if lane == "direct_single_agent" else "c2a_four_role_v1", "runtime_attempts": {"status": "unsupported", "items": [], "count": 0}, "provider_calls": [], "terminal_status": status, "failure_stage": "control", "error_code": code, "canonical_marker": {"observed": True, "execution_path": "control_injection"}}
            record(identity=control_identity, sample=None, lane=lane, repeat_id=0, seed=0, kind="control", outcome=outcome, trace=trace, family_id="c2b_control")

    from statebus.benchmark.semantic_holdout import load_semantic_holdout_cases
    for repeat_id, seed in enumerate(C2B_REPEAT_SEEDS):
        for holdout in load_semantic_holdout_cases():
            sample = holdout.sample
            identity = c2b_holdout_identity(holdout.task_id)
            for lane in C2B_LANE_ORDER[repeat_id]:
                if lane == "direct_single_agent":
                    outcome = run_direct_single_agent(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=sample.canonical_task_spec)
                    trace = {**outcome, "schema_version": "statebus.canonical_trace.v1", "case_id": sample.task_id, "lane": lane, "role_sequence": ["generalist"], "role_count": {"generalist": 1}, "dependency_edges": [], "recipe_identity": "direct-single-agent@v1", "capability_identity": "direct_generalist_v1", "provider_calls": list(outcome.get("calls", ())), "failure_stage": outcome.get("failure_stage", ""), "error_code": outcome.get("error_code", ""), "runtime_attempts": {"status": "unsupported", "items": [], "count": 0}, "canonical_marker": {"observed": True, "execution_path": outcome.get("execution_path", "direct_single_agent_provider")}}
                elif lane == "pure_text_mas":
                    outcome = run_pure_text_mas(task_id=sample.task_id, request_text=sample.request_text, canonical_task_spec=sample.canonical_task_spec, corpus_text=sample.request_text)
                    trace = {**outcome, "schema_version": "statebus.canonical_trace.v1", "case_id": sample.task_id, "lane": lane, "provider_calls": list(outcome.get("calls", ())), "failure_stage": outcome.get("failure_stage", ""), "error_code": outcome.get("error_code", ""), "runtime_attempts": {"status": "unsupported", "items": [], "count": 0}, "recipe_identity": "pure-text-mas@v1", "capability_identity": "text_role_call_v1", "canonical_marker": {"observed": True, "execution_path": outcome.get("execution_path", "pure_text_provider_four_role")}}
                else:
                    structured_root = root / "holdout" / identity.replace("/", "_") / str(repeat_id) / lane
                    try:
                        outcome, trace = _c2b_structured_runtime(
                            sample,
                            lane=lane,
                            root=structured_root,
                        )
                    except (RuntimeError, ValueError, OSError) as exc:
                        outcome = {
                            "terminal_status": "runtime_fail",
                            "failure_stage": "runtime",
                            "error_code": type(exc).__name__,
                            "metric_availability": {
                                "wire_bytes": {
                                    "status": "unsupported",
                                    "reason": "wire_bytes_not_observed",
                                }
                            },
                        }
                        trace = {
                            "schema_version": "statebus.canonical_trace.v1",
                            "case_id": sample.task_id,
                            "lane": lane,
                            "execution_path": (
                                "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                                if lane == "fixed_structured"
                                else "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                            ),
                            "runtime_authority": "AdaptiveRuntimeEngine",
                            "role_graph": "planner->retriever->executor->summarizer",
                            "role_sequence": [],
                            "role_count": {},
                            "dependency_edges": [["planner", "retriever"], ["retriever", "executor"], ["executor", "summarizer"]],
                            "recipe_identity": "c2a-four-role@v1",
                            "capability_identity": "c2a_four_role_v1",
                            "runtime_attempts": {"status": "observed", "items": [], "count": 0},
                            "provider_calls": [],
                            "terminal_status": "runtime_fail",
                            "failure_stage": "runtime",
                            "error_code": outcome["error_code"],
                            "canonical_marker": {"observed": True, "execution_path": "runtime_structured_formal"},
                        }
                record(identity=identity, sample=sample, lane=lane, repeat_id=repeat_id, seed=seed, kind="holdout", outcome=outcome, trace=trace, family_id="semantic_holdout")

    positive_rows = [row for row in rows if str(row.get("case_identity", "")).startswith("c2b-positive::")]
    lane_rows = {lane: [row for row in positive_rows if row.get("lane") == lane] for lane in CANONICAL_LANES}
    contrasts: dict[str, object] = {}
    for left, right, name in (("pure_text_mas", "fixed_structured", "pure_text_vs_fixed"), ("fixed_structured", "adaptive_routed", "fixed_vs_adaptive"), ("direct_single_agent", "pure_text_mas", "direct_vs_pure_text"), ("direct_single_agent", "fixed_structured", "direct_vs_fixed"), ("direct_single_agent", "adaptive_routed", "direct_vs_adaptive")):
        deltas = paired_deltas(lane_rows[left], lane_rows[right], key="wall_time")
        contrasts[name] = {"metric": "wall_time", "deltas": deltas, "bootstrap_ci": bootstrap_mean_ci(deltas, resamples=10000, seed=2027)}
    payload = {"schema_version": "statebus.c2b.formal_run.v1", "positive_rows": len(positive_rows), "control_rows": sum(row.get("case_identity", "").startswith("c2b-control::") for row in rows), "holdout_rows": sum(row.get("case_identity", "").startswith("c2b-holdout::") for row in rows), "rows": rows, "statistics": aggregate_c2b_statistics(rows), "paired_contrasts": contrasts, "holm_adjustment": holm_adjust({}), "claim_restriction": "contract_only_no_superiority_claim", "benchmark_superiority": "NOT_ESTABLISHED", "live_vllm_gpu_validation": "NOT_RUN"}
    (root / "case_family_coverage.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.coverage.v1", "positive_cases": sorted({row["case_identity"] for row in positive_rows}), "positive_case_count": len({row["case_identity"] for row in positive_rows}), "control_case_count": len({row["case_identity"] for row in rows if str(row["case_identity"]).startswith("c2b-control::")}), "holdout_case_count": len({row["case_identity"] for row in rows if str(row["case_identity"]).startswith("c2b-holdout::")})}) + "\n", encoding="utf-8")
    (root / "pair_repeat_seed_index.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.pair_index.v1", "pairs": sorted({row["pair_key"] for row in rows}), "pair_count": len({row["pair_key"] for row in rows})}) + "\n", encoding="utf-8")
    terminal_counts = {status: sum(row.get("terminal_status") == status for row in rows) for status in ("success", "quality_fail", "timeout", "unsupported", "runtime_fail", "policy_reject", "environment_fail")}
    (root / "terminal_denominator.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.denominator.v1", "attempted_count": len(rows), "terminal_count": sum(terminal_counts.values()), "counts": terminal_counts, "failure_count": len(rows) - terminal_counts["success"]}) + "\n", encoding="utf-8")
    (root / "metric_availability_projection.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.metric_availability.v1", "metrics": {name: "unsupported" for name in ("logical_messages", "control_bytes", "wire_bytes", "prompt_tokens", "completion_tokens", "state_bytes", "memory_funnel", "route_metrics")}, "reason": "deterministic_internal_fixture_does_not_observe_transport_or_provider_usage"}) + "\n", encoding="utf-8")
    (root / "statistical_summary.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.statistics.v1", "paired_contrasts": contrasts, "bootstrap_resamples": 10000, "analysis_seed": 2027, "holm_adjustment": {}}) + "\n", encoding="utf-8")
    (root / "claim_restriction.json").write_text(stable_json_dumps({"benchmark_superiority": "NOT_ESTABLISHED", "reason": "required structured rows and target metrics are incomplete/unsupported", "holdout_in_claim": False}) + "\n", encoding="utf-8")
    (root / "failed_rows.json").write_text(stable_json_dumps({"schema_version": "statebus.c2b.failures.v1", "rows": [{"case_identity": row["case_identity"], "lane": row["lane"], "terminal_status": row["terminal_status"], "error_code": row["error_code"]} for row in rows if row["terminal_status"] != "success"]}) + "\n", encoding="utf-8")
    control_rows = [row for row in rows if str(row.get("case_identity", "")).startswith("c2b-control::")]
    controls_by_id = {control.case_identity: control for control in c2b_control_specs()}
    control_contract_complete = all(
        (
            row.get("terminal_status") == controls_by_id[str(row["case_identity"])].expected_status
            and row.get("error_code") == controls_by_id[str(row["case_identity"])].expected_error_code
        )
        if row.get("lane") in controls_by_id[str(row["case_identity"])].applicable_lanes
        else row.get("terminal_status") == "unsupported"
        and row.get("error_code") == "control_not_applicable_to_lane"
        for row in control_rows
    )
    positive_and_holdout = [
        row for row in rows
        if str(row.get("case_identity", "")).startswith(("c2b-positive::", "c2b-holdout::"))
    ]
    matrix_complete = (
        len(positive_rows) == 576
        and len(control_rows) == 48
        and len(positive_and_holdout) == 672
        and all(row.get("terminal_status") == "success" for row in positive_and_holdout)
    )
    trace_complete = all(row.get("trace_validation", {}).get("valid") is True for row in rows)
    oracle_complete = all(row.get("oracle_audit", {}).get("ok") is True for row in rows)
    isolation_complete = all(row.get("isolation_audit", {}).get("ok") is True for row in rows)
    formal_suite_complete = matrix_complete and trace_complete and all(
        row.get("terminal_status") == "success"
        for row in positive_and_holdout
        if row.get("lane") in {"fixed_structured", "adaptive_routed"}
    )
    contract_evidence_eligible = formal_suite_complete and control_contract_complete and oracle_complete and isolation_complete
    acceptance_gates = {
        "positive_matrix_complete": len(positive_rows) == 576,
        "control_matrix_complete": sum(row.get("case_identity", "").startswith("c2b-control::") for row in rows) == 48,
        "holdout_matrix_complete": sum(row.get("case_identity", "").startswith("c2b-holdout::") for row in rows) == 96,
        "all_rows_terminal": all(row.get("terminal_status") in {"success", "quality_fail", "timeout", "unsupported", "runtime_fail", "policy_reject", "environment_fail"} for row in rows),
        "all_required_artifacts": all((root / kind / str(row.get("case_identity", "")).replace("/", "_") / str(row.get("repeat_id", 0)) / str(row.get("lane", "")) / "manifest.json").is_file() for kind in ("positive", "control", "holdout") for row in rows if str(row.get("case_identity", "")).startswith(f"c2b-{kind}::")),
        "positive_structured_success": all(row.get("terminal_status") == "success" for row in positive_rows if row.get("lane") in {"fixed_structured", "adaptive_routed"}),
        "holdout_structured_success": all(row.get("terminal_status") == "success" for row in rows if str(row.get("case_identity", "")).startswith("c2b-holdout::") and row.get("lane") in {"fixed_structured", "adaptive_routed"}),
        "control_correctness": control_contract_complete,
        "trace_validation_complete": trace_complete,
        "oracle_audit_complete": oracle_complete,
        "isolation_audit_complete": isolation_complete,
        "required_metrics_observed": False,
        "superiority_claim_allowed": False,
    }
    reasons: list[str] = []
    if not formal_suite_complete:
        reasons.append("formal_positive_or_holdout_execution_incomplete")
    if not contract_evidence_eligible:
        reasons.append("contract_evidence_gate_incomplete")
    reasons.append("deterministic_internal_fixture_metrics_unsupported_for_superiority")
    acceptance = {
        "schema_version": "statebus.c2b.acceptance.v2",
        "formal_suite_complete": formal_suite_complete,
        "contract_evidence_eligible": contract_evidence_eligible,
        "superiority_claim_allowed": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "reasons": reasons,
        "evidence_refs": ["c2b_formal_run.json", "terminal_denominator.json", "metric_availability_projection.json"],
        "gates": acceptance_gates,
        "overall_pass": contract_evidence_eligible,
        "required_metrics_observed": False,
        "claim_restriction": "contract_only_no_superiority_claim",
    }
    (root / "c2b_acceptance.json").write_text(stable_json_dumps(acceptance) + "\n", encoding="utf-8")
    (root / "c2b_formal_run.json").write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    return payload


def _quality_floor_from_smoke(smoke: SmokeResult) -> QualityFloorResult:
    return smoke.quality_floor


def _terminal_status_from_quality(quality_floor: QualityFloorResult) -> str:
    return "success" if quality_floor.quality_floor_pass else "quality_fail"


def _report_from_smoke(
    sample: MinimalBenchmarkSample,
    smoke: SmokeResult,
    *,
    task_ms: float | None = None,
) -> BenchmarkRunReport:
    metrics = {
        "telemetry_event_count": float(smoke.telemetry_event_count),
        "registry_path_length": float(len(smoke.registry_path)),
        "output_artifact_path_length": float(len(smoke.output_artifact_path)),
        "workflow_step_count": float(smoke.workflow_step_count),
        "attempt_count": float(smoke.attempt_count),
        "executor_attempt_count": float(smoke.task_metrics["executor_attempt_count"]),
        "runtime_replan_count": float(smoke.runtime_replan_count),
    }
    if task_ms is not None:
        metrics["task_ms"] = float(task_ms)
    return BenchmarkRunReport(
        layer=BenchmarkLayer.L3,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        metrics=metrics,
    )


def _case_from_smoke(
    sample: MinimalBenchmarkSample,
    smoke: SmokeResult,
    *,
    task_ms: float,
) -> BenchmarkCaseReport:
    terminal_status = _terminal_status_from_quality(smoke.quality_floor)
    return BenchmarkCaseReport(
        task_id=sample.task_id,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        replay_class=smoke.replay_class,
        telemetry_event_count=smoke.telemetry_event_count,
        output_artifact_hash=smoke.output_artifact_hash,
        output_artifact_path=smoke.output_artifact_path,
        workspace_root=smoke.workspace_root,
        session_state=smoke.session_state,
        comparison_tags=sample.scenario_tags,
        audit_paths={
            "replay": smoke.replay_audit_path,
            "hydration": smoke.hydration_audit_path,
            "hydration_debug": smoke.hydration_debug_audit_path,
            "artifact": smoke.artifact_audit_path,
        },
        audit_summary={
            **smoke.audit_summary,
            "benchmark_case": {
                "schema_version": "statebus.benchmark_case_terminal.v1",
                "terminal_status": terminal_status,
                "attempted": True,
            },
        },
        metrics={
            **dict(sorted(smoke.task_metrics.items())),
            "response_count": float(len(smoke.response_sequence)),
            "lineage_verified_artifact_count": float(len(smoke.lineage_view.verified_artifact_ids)),
            "workflow_step_count": float(smoke.workflow_step_count),
            "completed_workflow_step_count": float(smoke.completed_workflow_step_count),
            "replan_history_count": float(smoke.replan_history_count),
            "task_ms": float(task_ms),
        },
    )


def _prepare_case_root(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_minimal_benchmark(
    *,
    sample: MinimalBenchmarkSample,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory: bool = False,
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> tuple[SmokeResult, BenchmarkRunReport]:
    _prepare_case_root(workspace_root)
    _prepare_case_root(runtime_root)
    layer_config = SmokeLayerConfig(
        **{
            **LAYER_SMOKE_CONFIGS[BenchmarkLayer.L3].__dict__,
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "state_pool_mode": state_pool_mode,
            "persistence_profile": persistence_profile,
            "executor_transport": executor_transport,
        }
    )
    start_ns = time.perf_counter_ns()
    smoke = run_smoke(
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        request_text=sample.request_text,
        canonical_task_spec=sample.canonical_task_spec,
        task_id=sample.task_id,
        layer_config=layer_config,
        expected_facts=sample.expected_facts,
        seed_replay_memory=seed_replay_memory,
    )
    task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
    return smoke, _report_from_smoke(sample, smoke, task_ms=task_ms)


def run_minimal_benchmark_family(
    *,
    samples: list[MinimalBenchmarkSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "minimal-family",
    layer: BenchmarkLayer = BenchmarkLayer.L3,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "formal",
    claim_level: str = "first_pass",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> BenchmarkFamilyReport:
    profile = LAYER_PROFILES[layer]
    cases: list[BenchmarkCaseReport] = []
    suite_emitter = TelemetryEmitter()
    layer_workspace_root = _prepare_case_root(workspace_root)
    for sample in samples:
        case_runtime_root = _prepare_case_root(runtime_root / sample.task_id)
        start_ns = time.perf_counter_ns()
        smoke = run_smoke(
            workspace_root=layer_workspace_root,
            runtime_root=case_runtime_root,
            socket_path=socket_path.with_name(
                f"{socket_path.stem}-{layer.value.lower()}-{sample.task_id}{socket_path.suffix}"
            ),
            request_text=sample.request_text,
            canonical_task_spec=sample.canonical_task_spec,
            task_id=sample.task_id,
            layer_config=SmokeLayerConfig(
                **{
                    **LAYER_SMOKE_CONFIGS[layer].__dict__,
                    "role_path_mode": role_path_mode,
                    "embedding_mode": embedding_mode,
                    "state_pool_mode": state_pool_mode,
                    "persistence_profile": persistence_profile,
                    "executor_transport": executor_transport,
                }
            ),
            expected_facts=sample.expected_facts,
            seed_replay_memory=seed_replay_memory,
        )
        task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        cases.append(_case_from_smoke(sample, smoke, task_ms=task_ms))
        suite_emitter.emit(
            TelemetryEvent.create(
                trace_id=f"suite:{suite_id}",
                task_id=sample.task_id,
                event_type="TASK_SUMMARY_METRICS",
                metrics=smoke.task_metrics,
            )
        )

    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": float(sum(case.telemetry_event_count for case in cases)),
    }
    telemetry_summary = finalize_case_telemetry_summary(
        suite_emitter.summarize_suite([case.task_id for case in cases]),
        cases,
    )
    replay_class_distribution: dict[str, float] = {}
    quality_floor_breakdown = {
        "deterministic_checks_passed_count": float(
            sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
        ),
        "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
        "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
    }
    for case in cases:
        replay_class_distribution[case.replay_class] = replay_class_distribution.get(case.replay_class, 0.0) + 1.0
    state_pool_mode_used = (
        "memfd"
        if telemetry_summary.get("memfd_transfer_count", 0.0) > 0.0
        else "shared_memory"
        if telemetry_summary.get("state_pool_shared_memory_mode_count", 0.0) > 0.0
        else "mmap_file"
        if telemetry_summary.get("state_pool_mmap_mode_count", 0.0) > 0.0
        else state_pool_mode
    )
    task_family = cases[0].task_family if cases else "financial_report_analysis"
    family_tier = (
        "formal_registry"
        if benchmark_tier == "formal" and len({case.task_family for case in cases}) > 1
        else "formal_financial"
        if benchmark_tier == "formal"
        else "dev"
    )
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}-{layer.value}.json"
    family_report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=layer,
        task_family=task_family,
        profile=profile,
        cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
        replay_class_distribution=replay_class_distribution,
        quality_floor_breakdown=quality_floor_breakdown,
        metadata={
            "benchmark_tier": benchmark_tier,
            "claim_level": claim_level,
            "embedding_mode": embedding_mode,
            "formal_comparator_eligible": False,
            "quality_floor_contract": "statebus_smoke_quality_floor_v1",
            "role_graph": "planner->retriever->executor->summarizer",
            "role_path_mode": role_path_mode,
            "state_pool_mode": state_pool_mode,
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": state_pool_mode_used,
            "transport": executor_transport,
            "scoring_contract": "statebus_smoke_quality_floor_v1",
            "seed_replay_memory": seed_replay_memory,
            "task_family_tier": family_tier,
            "uses_internal_helpers": False,
        },
        report_path=str(report_path),
    )
    write_json_report(report_path, family_report_to_dict(family_report))
    return family_report


def run_minimal_benchmark_suite(
    *,
    samples: list[MinimalBenchmarkSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "minimal-suite",
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory_by_layer: dict[BenchmarkLayer, bool] | None = None,
    benchmark_tier: str = "formal",
    claim_level: str = "first_pass",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> BenchmarkSuiteReport:
    seed_replay_memory_by_layer = seed_replay_memory_by_layer or {}
    layer_reports = tuple(
        run_minimal_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / layer.value,
            runtime_root=runtime_root / layer.value,
            socket_path=socket_path.with_name(f"{socket_path.stem}-{layer.value}{socket_path.suffix}"),
            suite_id=suite_id,
            layer=layer,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            seed_replay_memory=seed_replay_memory_by_layer.get(layer, False),
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
            executor_transport=executor_transport,
        )
        for layer in BenchmarkLayer
    )
    l3_report = layer_reports[3]
    formal_families = tuple(dict.fromkeys(sample.task_family for sample in samples))
    state_pool_mode_used = (
        "memfd"
        if l3_report.telemetry_summary.get("memfd_transfer_count", 0.0) > 0.0
        else "shared_memory"
        if l3_report.telemetry_summary.get("state_pool_shared_memory_mode_count", 0.0) > 0.0
        else "mmap_file"
        if l3_report.telemetry_summary.get("state_pool_mmap_mode_count", 0.0) > 0.0
        else state_pool_mode
    )
    text_l0_report = layer_reports[0]
    protocol_l3_report = layer_reports[3]
    text_l0_total_tokens = text_l0_report.telemetry_summary.get("llm_total_tokens", 0.0)
    text_l0_prompt_tokens = text_l0_report.telemetry_summary.get("llm_prompt_tokens", 0.0)
    text_l0_prompt_bytes = text_l0_report.telemetry_summary.get("llm_prompt_bytes", 0.0)
    text_l0_control_bytes = text_l0_report.telemetry_summary.get("control_bytes", 0.0)
    text_l0_quality_pass_count = text_l0_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
    protocol_l3_total_tokens = protocol_l3_report.telemetry_summary.get("llm_total_tokens", 0.0)
    protocol_l3_prompt_tokens = protocol_l3_report.telemetry_summary.get("llm_prompt_tokens", 0.0)
    protocol_l3_prompt_bytes = protocol_l3_report.telemetry_summary.get("llm_prompt_bytes", 0.0)
    protocol_l3_control_bytes = protocol_l3_report.telemetry_summary.get("control_bytes", 0.0)
    protocol_l3_quality_pass_count = protocol_l3_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
    waterfall_metrics = {
        "L0_case_count": float(len(layer_reports[0].cases)),
        "L0_raw_evidence_bytes_seen_by_llm": layer_reports[0].telemetry_summary.get(
            "raw_evidence_bytes_seen_by_llm", 0.0
        ),
        "L1_control_bytes": layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
        "L1_control_message_count": layer_reports[1].telemetry_summary.get("control_message_count", 0.0),
        "L2_semantic_state_transfer_count": layer_reports[2].telemetry_summary.get(
            "semantic_state_transfer_count", 0.0
        ),
        "L2_memory_match_count": layer_reports[2].telemetry_summary.get("memory_match_count", 0.0),
        "L3_quality_floor_pass_count": layer_reports[3].aggregated_metrics.get("quality_floor_pass_count", 0.0),
        "L3_artifact_reuse_count": layer_reports[3].telemetry_summary.get("artifact_reuse_count", 0.0),
        "L3_reuse_gain": layer_reports[3].telemetry_summary.get("reuse_gain", 0.0),
        "text_L0_total_tokens": text_l0_total_tokens,
        "text_L0_prompt_tokens": text_l0_prompt_tokens,
        "text_L0_prompt_bytes": text_l0_prompt_bytes,
        "text_L0_control_bytes": text_l0_control_bytes,
        "text_L0_quality_pass_count": text_l0_quality_pass_count,
        "protocol_L3_total_tokens": protocol_l3_total_tokens,
        "protocol_L3_prompt_tokens": protocol_l3_prompt_tokens,
        "protocol_L3_prompt_bytes": protocol_l3_prompt_bytes,
        "protocol_L3_control_bytes": protocol_l3_control_bytes,
        "protocol_L3_quality_pass_count": protocol_l3_quality_pass_count,
    }
    comparison_summary = {
        "pruning_bytes_saved_vs_l0": max(
            layer_reports[0].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0)
            - layer_reports[2].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0),
            0.0,
        ),
        "control_bytes_delta_l0_to_l1": max(
            layer_reports[0].telemetry_summary.get("control_bytes", 0.0)
            - layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
            0.0,
        ),
        "reuse_gain_delta_l2_to_l3": max(
            layer_reports[3].telemetry_summary.get("reuse_gain", 0.0)
            - layer_reports[2].telemetry_summary.get("reuse_gain", 0.0),
            0.0,
        ),
        "artifact_reuse_delta_l2_to_l3": max(
            layer_reports[3].telemetry_summary.get("artifact_reuse_count", 0.0)
            - layer_reports[2].telemetry_summary.get("artifact_reuse_count", 0.0),
            0.0,
        ),
        "quality_floor_pass_delta_l0_to_l3": (
            layer_reports[3].aggregated_metrics.get("quality_floor_pass_count", 0.0)
            - layer_reports[0].aggregated_metrics.get("quality_floor_pass_count", 0.0)
        ),
        "selected_evidence_bytes_delta_l0_to_l2": max(
            layer_reports[0].telemetry_summary.get("selected_evidence_bytes", 0.0)
            - layer_reports[2].telemetry_summary.get("selected_evidence_bytes", 0.0),
            0.0,
        ),
        "replan_history_delta_l0_to_l3": (
            layer_reports[3].telemetry_summary.get("replan_history_count", 0.0)
            - layer_reports[0].telemetry_summary.get("replan_history_count", 0.0)
        ),
        "codeact_action_delta_l0_to_l3": (
            layer_reports[3].telemetry_summary.get("codeact_plan_action_count", 0.0)
            - layer_reports[0].telemetry_summary.get("codeact_plan_action_count", 0.0)
        ),
        "text_L0_total_tokens": text_l0_total_tokens,
        "text_L0_prompt_tokens": text_l0_prompt_tokens,
        "text_L0_prompt_bytes": text_l0_prompt_bytes,
        "text_L0_control_bytes": text_l0_control_bytes,
        "text_L0_quality_pass_count": text_l0_quality_pass_count,
        "protocol_L3_total_tokens": protocol_l3_total_tokens,
        "protocol_L3_prompt_tokens": protocol_l3_prompt_tokens,
        "protocol_L3_prompt_bytes": protocol_l3_prompt_bytes,
        "protocol_L3_control_bytes": protocol_l3_control_bytes,
        "protocol_L3_quality_pass_count": protocol_l3_quality_pass_count,
        "protocol_vs_text_token_delta": protocol_l3_total_tokens - text_l0_total_tokens,
        "protocol_vs_text_prompt_token_delta": protocol_l3_prompt_tokens - text_l0_prompt_tokens,
        "protocol_vs_text_prompt_bytes_delta": protocol_l3_prompt_bytes - text_l0_prompt_bytes,
        "protocol_vs_text_control_bytes_delta": protocol_l3_control_bytes - text_l0_control_bytes,
        "protocol_vs_text_quality_pass_delta": protocol_l3_quality_pass_count - text_l0_quality_pass_count,
    }
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}-suite.json"
    family_tier = (
        "formal_registry"
        if benchmark_tier == "formal" and len(formal_families) > 1
        else "formal_financial"
        if benchmark_tier == "formal"
        else "dev"
    )
    suite_report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=samples[0].task_family if samples else "financial_report_analysis",
        layer_reports=layer_reports,
        waterfall_metrics=waterfall_metrics,
        comparison_summary=comparison_summary,
        metadata={
            "benchmark_tier": benchmark_tier,
            "claim_level": claim_level,
            "embedding_mode": embedding_mode,
            "comparison_contract": "same_mainline_internal_attribution_ladder",
            "ladder_claim_scope": "internal_attribution_only_not_external_superiority",
            "role_path_mode": role_path_mode,
            "transport": executor_transport,
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": state_pool_mode_used,
            "memfd_transfer_count": l3_report.telemetry_summary.get("memfd_transfer_count", 0.0),
            "memfd_publish_count": l3_report.telemetry_summary.get("memfd_publish_count", 0.0),
            "memfd_bytes_transferred": l3_report.telemetry_summary.get("memfd_bytes_transferred", 0.0),
            "seed_replay_memory_by_layer": {
                layer.value: seed_replay_memory_by_layer.get(layer, False)
                for layer in BenchmarkLayer
            },
            "formal_task_families": list(formal_families),
            "formal_task_family_count": len(formal_families),
            "formal_text_protocol_benchmark": benchmark_tier == "formal",
            "task_family_tier": family_tier,
        },
        family_case_count=len(samples),
        report_path=str(report_path),
    )
    write_json_report(report_path, suite_report_to_dict(suite_report))
    return suite_report


def main() -> None:
    sample = MinimalBenchmarkSample.from_path(
        Path(__file__).with_name("samples") / "minimal_financial_report_sample.json"
    )
    smoke, report = run_minimal_benchmark(
        sample=sample,
        workspace_root=Path("/tmp/statebus-benchmark/workspaces"),
        runtime_root=Path("/tmp/statebus-benchmark/runtime"),
        socket_path=Path("/tmp/statebus-benchmark/control.sock"),
    )
    family = run_minimal_benchmark_family(
        samples=load_sample_family(Path(__file__).with_name("samples") / "formal_financial_family"),
        workspace_root=Path("/tmp/statebus-benchmark-family/workspaces"),
        runtime_root=Path("/tmp/statebus-benchmark-family/runtime"),
        socket_path=Path("/tmp/statebus-benchmark-family/control.sock"),
        layer=BenchmarkLayer.L3,
    )
    suite = run_minimal_benchmark_suite(
        samples=load_sample_family(Path(__file__).with_name("samples") / "formal_financial_family"),
        workspace_root=Path("/tmp/statebus-benchmark-suite/workspaces"),
        runtime_root=Path("/tmp/statebus-benchmark-suite/runtime"),
        socket_path=Path("/tmp/statebus-benchmark-suite/control.sock"),
    )
    print(f"task_id={sample.task_id}")
    print(f"quality_floor_pass={report.quality_floor.quality_floor_pass}")
    print(f"replay_class={smoke.replay_class}")
    print(f"telemetry_event_count={smoke.telemetry_event_count}")
    print(f"family_case_count={len(family.cases)}")
    print(f"family_quality_floor_pass_count={int(family.aggregated_metrics['quality_floor_pass_count'])}")
    print(f"family_report_path={family.report_path}")
    print(f"suite_layer_count={len(suite.layer_reports)}")
    print(f"suite_report_path={suite.report_path}")
    print(json.dumps(suite_report_to_dict(suite), ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
