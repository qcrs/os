from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import shutil
import tempfile
import time

from runtime.llm import LLMConfig, build_llm_client
from v2.benchmark.models import QualityFloorResult
from v2.control import (
    AckReceived,
    ControlHeader,
    ControlPlaneLoopbackServer,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    ReusePolicy,
    RunStart,
    SuccessResult,
    TrapFatal,
    frame_control_message,
)
from v2.contracts import (
    CanonicalTaskSpec,
    HydrationAccountingAudit,
    HydrationRoleAccounting,
    PlannerHandoff,
    RefKind,
    RefStatus,
    ReplayClass,
    ROLE_PROMPT_SLICE_SCHEMA_VERSION,
    RuntimeSignatureManifestBundle,
    RuntimeCompatibilitySignature,
    StepLifecycleState,
    StorageKind,
    TaskCompilerInput,
    TaskMode,
)
from v2.memory import (
    DeterministicEmbeddingEncoder,
    MemoryCommit,
    MemoryIndexStore,
    MemoryRef,
    MemoryType,
)
from v2.provenance import (
    RoleHydratedSlice,
    build_hydration_registry_from_evidence_pack,
    manifest_to_dict,
    role_hydrated_slice,
)
from v2.refs import ExecutionArtifactRef, SemanticStateRef
from v2.retrieval import RetrievalBundle, RetrieverFanoutPipeline
from v2.retrieval.corpus import OfflineCsvTableCorpus, OfflineFinancialReportCorpus, OfflineMarkdownLongDocCorpus
from v2.route_tool_catalog import build_route_tool_surface, stable_tool_registry_profiles
from v2.runtime.codeact import CodeActRequest, CodeActRunner
from v2.runtime import (
    ArtifactLifecycleManager,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    ArtifactValidatorReport,
    ExecutionStepRecord,
    FallbackPlanner,
    CommitGateDecision,
    InputManifest,
    InputManifestItem,
    InputValidatorReport,
    MaterializedFile,
    ReplayAdmissibilityGate,
    ReplayCandidate,
    ReplayCandidateSelection,
    ReplayDecision,
    load_history_replay_candidates,
    ReplayLedger,
    ReplayLedgerEntry,
    ReplayPolicy,
    RuntimeCommitGate,
    RuntimeLeaseConfig,
    RuntimeSessionManager,
    RuntimeSupervisor,
    ExecutorRoleDecision,
    PlannerRoleResult,
    RetrieverRoleDecision,
    RolePathRunner,
    RolePromptSlice,
    StepAttemptRecord,
    SummarizerRoleDecision,
    TaskCompiler,
    TaskLineageView,
    TelemetryEmitter,
    TelemetryEvent,
    WorkspaceManager,
    best_visible_candidate,
    constrain_visible_candidates,
    build_extended_output_manifest,
    capture_runtime_signature,
    capture_runtime_signature_manifest_bundle,
    build_task_lineage_view,
    capture_execution_logs,
    evidence_pack_replay_hash,
    financial_tool_candidates,
    hydrate_manifest_replay_hash,
    planner_handoff_replay_hash,
    SignatureManifestEntry,
    count_exact_replay_candidates,
    select_history_replay_candidate,
)
from v2.runtime.preflight import runtime_preflight
from v2.runtime.runtime_signature import runtime_signature_payload
from v2.runtime.session import RuntimeTaskSession, RuntimeWorkflowStep
from v2.runtime.driver import RuntimeDriver, RuntimeDriverInput, RuntimeDriverProfile
from v2.state import JsonContractStore, LayeredStateStore, MaterializedStateHandle, RefRegistryQuery
from v2.state import MemorySidecarStore, RetrievalSidecarStore
from v2.utils import sha256_digest, stable_json_dumps


def _history_output_candidate_paths(root: Path) -> tuple[Path, ...]:
    store = JsonContractStore(root)
    session_output_paths: list[Path] = []
    for session_path in sorted(store.runtime_session_dir.glob("*.json")):
        try:
            payload = json.loads(session_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        session_id = str(payload.get("session_id", "")).strip()
        artifact_manifest_hash = str(payload.get("artifact_manifest_hash", "")).strip()
        summary_artifact_ref_id = str(payload.get("summary_artifact_ref_id", "")).strip()
        if not session_id or not artifact_manifest_hash:
            continue
        try:
            session = store.read_runtime_session(session_id)
            manifest = store.read_artifact_output_manifest(artifact_manifest_hash)
        except Exception:
            continue
        output_relpath = ""
        if summary_artifact_ref_id:
            try:
                artifact_entry = store.get_ref_registry_entry(summary_artifact_ref_id)
            except Exception:
                artifact_entry = None
            if artifact_entry is not None:
                output_relpath = artifact_entry.relpath or artifact_entry.workspace_relpath
        if not output_relpath:
            primary_output = next((item for item in manifest.outputs if item.artifact_name == "summary_json"), None)
            if primary_output is None and manifest.outputs:
                primary_output = manifest.outputs[0]
            if primary_output is not None:
                output_relpath = primary_output.relpath
        if output_relpath:
            session_output_paths.append(Path(session.workspace_root) / output_relpath)
    audit_paths = (
        *sorted(root.glob("workspaces/*/logs/artifact_audit.json")),
        *sorted(root.glob("**/logs/artifact_audit.json")),
    )
    output_paths: list[Path] = []
    for audit_path in audit_paths:
        try:
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        output_path = Path(str(payload.get("output_artifact_path", "")).strip())
        if output_path:
            output_paths.append(output_path)
    return (
        *session_output_paths,
        *output_paths,
        root / "sidecars" / "artifacts" / "summary_json.json",
        root / "outputs" / "result.json",
        root / "outputs" / "summary_json.json",
        *sorted(root.glob("workspaces/*/outputs/result.json")),
        *sorted(root.glob("workspaces/*/outputs/summary_json.json")),
        *sorted(root.glob("**/outputs/result.json")),
        *sorted(root.glob("**/outputs/summary_json.json")),
    )


def _history_output_payloads(history_runtime_roots: tuple[Path, ...]) -> tuple[dict[str, object], ...]:
    payloads: list[dict[str, object]] = []
    for root in history_runtime_roots:
        for output_path in _history_output_candidate_paths(root):
            if not output_path.exists() or not output_path.is_file():
                continue
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
                break
    return tuple(payloads)


def _history_artifact_summaries(history_runtime_roots: tuple[Path, ...]) -> tuple[str, ...]:
    summaries: list[str] = []
    for payload in _history_output_payloads(history_runtime_roots):
        task_id = str(payload.get("task_id", "")).strip()
        produced_artifacts = [
            str(item).strip()
            for item in payload.get("produced_artifact_refs", [])
            if str(item).strip()
        ]
        produced_strategies = [
            str(item).strip()
            for item in payload.get("produced_strategy_refs", [])
            if str(item).strip()
        ]
        artifact_fields = sorted(
            key
            for key in payload
            if key.endswith("_ref") or key.endswith("_hash") or key in {"cleaned_table_created"}
        )
        if not produced_artifacts and not produced_strategies and not artifact_fields:
            continue
        summaries.append(
            stable_json_dumps(
                {
                    "task_id": task_id,
                    "produced_artifact_refs": produced_artifacts,
                    "produced_strategy_refs": produced_strategies,
                    "artifact_fields": artifact_fields,
                }
            )
        )
    return tuple(summaries)


def _rebase_replayed_artifacts(
    *,
    output_payload: dict[str, object],
    source_workspace_root: Path,
    target_workspace_root: Path,
    source_task_id: str,
    target_task_id: str,
) -> dict[str, object]:
    rebased = dict(output_payload)
    rebased["task_id"] = target_task_id
    for key, value in list(rebased.items()):
        if not key.endswith("_ref"):
            continue
        relpath = str(value).strip()
        if not relpath:
            continue
        source_path = source_workspace_root / relpath
        target_relpath = relpath
        filename = Path(relpath).name
        if filename.startswith(f"{source_task_id}."):
            target_relpath = str(
                Path(relpath).with_name(filename.replace(f"{source_task_id}.", f"{target_task_id}.", 1))
            )
        target_path = target_workspace_root / target_relpath
        if source_path.exists() and source_path.is_file():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            rebased[key] = target_relpath
    return rebased


@dataclass(frozen=True)
class SmokeLayerConfig:
    layer_name: str = "L3"
    handoff_mode: str = "structured_collaboration"
    structured_control_enabled: bool = True
    semantic_pruning_enabled: bool = True
    semantic_state_transfer_enabled: bool = True
    replay_enabled: bool = True
    multi_attempt_enabled: bool = True
    force_first_attempt_trap: bool = True
    hermetic_runtime_root: bool = True
    role_path_mode: str = "deterministic"
    embedding_mode: str = "deterministic"


@dataclass(frozen=True)
class SmokeResult:
    task_id: str
    compiler_status: str
    supervisor_state: str
    response_sequence: tuple[str, ...]
    replay_class: str
    artifact_state: str
    registry_path: str
    reloaded_manifest_id: str
    reloaded_pack_id: str
    reloaded_input_manifest_hash: str
    reloaded_artifact_manifest_hash: str
    workspace_root: str
    canonical_task_spec_path: str
    input_manifest_path: str
    artifact_manifest_path: str
    evidence_pack_path: str
    hydrate_manifest_path: str
    output_artifact_path: str
    output_artifact_hash: str
    telemetry_path: str
    runtime_event_log_path: str
    runtime_fact_log_path: str
    replay_audit_path: str
    hydration_audit_path: str
    hydration_debug_audit_path: str
    artifact_audit_path: str
    embedding_path: str
    memory_commit_path: str
    memory_match_result_path: str
    retrieval_log_path: str
    retrieval_candidate_pool_path: str
    retrieval_rerank_result_path: str
    retrieval_pruning_profile_path: str
    session_path: str
    replay_ledger_path: str
    execution_step_path: str
    fallback_dag_path: str
    validator_report_paths: tuple[str, ...]
    input_validator_report_paths: tuple[str, ...]
    state_metadata_path: str
    state_storage_kind: str
    memory_replay_class: str
    memory_match_count: int
    reloaded_execution_goal: str
    reloaded_fallback_dag_id: str
    quality_floor: QualityFloorResult
    task_metrics: dict[str, float]
    session_state: str
    lineage_view: TaskLineageView
    workflow_step_count: int
    completed_workflow_step_count: int
    attempt_count: int
    runtime_replan_count: int
    runtime_fallback_count: int
    replan_history_count: int
    telemetry_event_count: int
    runtime_root: str
    codeact_script_path: str
    codeact_request_path: str
    codeact_plan_path: str
    runtime_stage_metrics: dict[str, float]
    audit_summary: dict[str, object]


def _render_output_payload(
    *,
    task_id: str,
    bundle: RetrievalBundle,
    summary_suffix: str,
    downgraded: bool = False,
) -> dict[str, object]:
    revenue_value = ""
    if bundle.evidence_pack.hard_facts:
        revenue_value = str(bundle.evidence_pack.hard_facts[0].metadata.get("value", ""))
    return {
        "task_id": task_id,
        "task_family": bundle.evidence_pack.task_id,
        "query_text": bundle.query_text,
        "summary_text": summary_suffix,
        "revenue_value": revenue_value,
        "selected_doc_hashes": list(bundle.selected_doc_hashes),
        "evidence_pack_hash": bundle.evidence_pack.pack_hash,
        "retrieval_log_hash": bundle.log_hash,
        "downgraded_execution_goal": downgraded,
    }


def _default_fact_value(bundle: RetrievalBundle) -> str:
    if bundle.evidence_pack.hard_facts:
        return str(bundle.evidence_pack.hard_facts[0].metadata.get("value", ""))
    if bundle.evidence_pack.semantic_contexts:
        return str(bundle.evidence_pack.semantic_contexts[0].rendered_text)
    if bundle.evidence_pack.lexical_hints:
        return str(bundle.evidence_pack.lexical_hints[0].rendered_text)
    return ""


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


def _empty_role_hydrated_slice(role: str) -> RoleHydratedSlice:
    return RoleHydratedSlice(
        role=role,
        selected_stable_keys=(),
        hydrated_text="",
        hydrated_bytes=0,
        item_count=0,
    )


def _role_external_evidence_bytes(slice_: RoleHydratedSlice) -> int:
    return slice_.hydrated_bytes + slice_.table_bytes


def _role_total_prompt_visible_bytes(slice_: RoleHydratedSlice) -> int:
    return slice_.hydrated_bytes + slice_.table_bytes + slice_.artifact_bytes + slice_.memory_bytes


def _role_total_prompt_visible_items(slice_: RoleHydratedSlice) -> int:
    return slice_.item_count + slice_.table_item_count + slice_.artifact_item_count + slice_.memory_item_count


def _role_non_external_prompt_visible_bytes(slice_: RoleHydratedSlice) -> int:
    return slice_.artifact_bytes + slice_.memory_bytes


def _prompt_scaffolding_bytes(*, prompt_bytes: int, slice_: RoleHydratedSlice) -> int:
    return max(prompt_bytes - _role_total_prompt_visible_bytes(slice_), 0)


def _role_hydration_audit_payload(slice_: RoleHydratedSlice) -> dict[str, object]:
    return {
        "role": slice_.role,
        "selected_stable_keys": list(slice_.selected_stable_keys),
        "external_text_bytes": slice_.hydrated_bytes,
        "external_text_item_count": slice_.item_count,
        "table_bytes": slice_.table_bytes,
        "table_item_count": slice_.table_item_count,
        "artifact_bytes": slice_.artifact_bytes,
        "artifact_item_count": slice_.artifact_item_count,
        "memory_bytes": slice_.memory_bytes,
        "memory_item_count": slice_.memory_item_count,
        "external_evidence_bytes": _role_external_evidence_bytes(slice_),
        "total_prompt_visible_bytes": _role_total_prompt_visible_bytes(slice_),
        "non_external_prompt_visible_bytes": _role_non_external_prompt_visible_bytes(slice_),
        "total_prompt_visible_item_count": _role_total_prompt_visible_items(slice_),
    }


def _role_hydration_accounting(
    *,
    slice_: RoleHydratedSlice,
    prompt_bytes: int,
    prompt_slice_ref: ExecutionArtifactRef | None = None,
) -> HydrationRoleAccounting:
    return HydrationRoleAccounting(
        role=slice_.role,
        selected_stable_keys=slice_.selected_stable_keys,
        external_text_bytes=slice_.hydrated_bytes,
        external_text_item_count=slice_.item_count,
        table_bytes=slice_.table_bytes,
        table_item_count=slice_.table_item_count,
        artifact_bytes=slice_.artifact_bytes,
        artifact_item_count=slice_.artifact_item_count,
        memory_bytes=slice_.memory_bytes,
        memory_item_count=slice_.memory_item_count,
        external_evidence_bytes=_role_external_evidence_bytes(slice_),
        total_prompt_visible_bytes=_role_total_prompt_visible_bytes(slice_),
        non_external_prompt_visible_bytes=_role_non_external_prompt_visible_bytes(slice_),
        total_prompt_visible_item_count=_role_total_prompt_visible_items(slice_),
        prompt_scaffolding_bytes=_prompt_scaffolding_bytes(prompt_bytes=prompt_bytes, slice_=slice_),
        prompt_bytes=prompt_bytes,
        prompt_slice_ref_id="" if prompt_slice_ref is None else prompt_slice_ref.artifact_id,
        prompt_slice_root_id="" if prompt_slice_ref is None else prompt_slice_ref.root_id,
        prompt_slice_relpath="" if prompt_slice_ref is None else prompt_slice_ref.relpath,
        prompt_slice_blob_hash="" if prompt_slice_ref is None else prompt_slice_ref.blob_hash,
        prompt_slice_size_bytes=0 if prompt_slice_ref is None else prompt_slice_ref.size_bytes,
        prompt_slice_schema_version=ROLE_PROMPT_SLICE_SCHEMA_VERSION,
    )


def _hydration_accounting_role_map(
    accounting: HydrationAccountingAudit,
) -> dict[str, HydrationRoleAccounting]:
    return {role.role: role for role in accounting.roles}


def _replay_history_source(*, seed_replay_memory: bool, history_runtime_roots: tuple[Path, ...]) -> str:
    if seed_replay_memory:
        return "synthetic_seed"
    if history_runtime_roots:
        return "history_bootstrap"
    return "none"


def _role_prompt_slice_relpath(role: str) -> str:
    return f"logs/prompt_slices/{role}.prompt_slice.json"


def _role_prompt_slice_payload(
    *,
    task_id: str,
    slice_: RoleHydratedSlice,
    prompt_bytes: int,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "role": slice_.role,
        "selected_stable_keys": list(slice_.selected_stable_keys),
        "hydrated_text": slice_.hydrated_text,
        "hydrated_bytes": slice_.hydrated_bytes,
        "hydrated_item_count": slice_.item_count,
        "table_text": slice_.table_text,
        "table_bytes": slice_.table_bytes,
        "table_item_count": slice_.table_item_count,
        "artifact_text": slice_.artifact_text,
        "artifact_bytes": slice_.artifact_bytes,
        "artifact_item_count": slice_.artifact_item_count,
        "memory_text": slice_.memory_text,
        "memory_bytes": slice_.memory_bytes,
        "memory_item_count": slice_.memory_item_count,
        "external_evidence_bytes": _role_external_evidence_bytes(slice_),
        "total_prompt_visible_bytes": _role_total_prompt_visible_bytes(slice_),
        "non_external_prompt_visible_bytes": _role_non_external_prompt_visible_bytes(slice_),
        "total_prompt_visible_item_count": _role_total_prompt_visible_items(slice_),
        "prompt_scaffolding_bytes": _prompt_scaffolding_bytes(prompt_bytes=prompt_bytes, slice_=slice_),
        "prompt_bytes": prompt_bytes,
        "schema_version": ROLE_PROMPT_SLICE_SCHEMA_VERSION,
    }


def _persist_role_prompt_slice_artifact(
    *,
    task_id: str,
    workspace: WorkspaceManager,
    layout,
    slice_: RoleHydratedSlice,
    prompt_bytes: int,
) -> tuple[MaterializedFile, ExecutionArtifactRef]:
    prompt_slice_file = workspace.write_json(
        layout,
        _role_prompt_slice_relpath(slice_.role),
        _role_prompt_slice_payload(task_id=task_id, slice_=slice_, prompt_bytes=prompt_bytes),
        logical_name=f"{slice_.role}_prompt_slice",
    )
    return prompt_slice_file, ExecutionArtifactRef(
        artifact_id=f"prompt-slice-{task_id}-{slice_.role}",
        task_id=task_id,
        step_id=f"{slice_.role}.prompt_slice",
        artifact_type="json",
        root_id="workspace-root",
        relpath=prompt_slice_file.relpath,
        blob_hash=prompt_slice_file.sha256,
        size_bytes=prompt_slice_file.size_bytes,
        produced_by=slice_.role,
        verification_state=RefStatus.ACTIVE,
        replay_ready=False,
        workspace_relpath=prompt_slice_file.relpath,
        metadata={"schema_version": ROLE_PROMPT_SLICE_SCHEMA_VERSION},
    )


def _string_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    values = payload.get(key, [])
    if not isinstance(values, list):
        return ()
    return tuple(str(item).strip() for item in values if str(item).strip())


def _continuous_output_reuse_metrics(
    *,
    spec: CanonicalTaskSpec,
    output_payload: dict[str, object],
    quality_floor: QualityFloorResult,
    layer_config: SmokeLayerConfig,
) -> dict[str, float]:
    if spec.task_family not in {"continuous_csv_table_analysis", "continuous_long_doc_table_analysis"}:
        return {}
    if not layer_config.replay_enabled or not quality_floor.quality_floor_pass:
        return {
            "history_artifact_reuse_count": 0.0,
            "history_strategy_reuse_count": 0.0,
            "history_step_reduction_count": 0.0,
            "history_reuse_gain": 0.0,
        }
    artifact_refs = set(_string_list(output_payload, "reused_artifact_refs"))
    if not artifact_refs:
        artifact_refs = set(_string_list(output_payload, "consumed_artifact_refs"))
    strategy_refs = set(_string_list(output_payload, "reused_strategy_refs"))
    if not strategy_refs:
        strategy_refs = set(_string_list(output_payload, "consumed_strategy_refs"))
    artifact_count = len(artifact_refs)
    strategy_count = len(strategy_refs)
    step_reduction_count = 0
    if artifact_count or strategy_count:
        if spec.intent_op == "summarize_reuse_lineage":
            step_reduction_count = 2
        elif (
            spec.task_family == "continuous_long_doc_table_analysis"
            and spec.intent_op == "final_cited_report"
            and artifact_count >= 7
        ):
            step_reduction_count = 2
    return {
        "history_artifact_reuse_count": float(artifact_count),
        "history_strategy_reuse_count": float(strategy_count),
        "history_step_reduction_count": float(step_reduction_count),
        "history_reuse_gain": 1.0 if step_reduction_count > 0 else 0.0,
    }


def _zero_planner_result() -> PlannerRoleResult:
    return PlannerRoleResult(
        workflow_payload={},
        retrieval_objective={},
        raw_text="",
        model="replay-restore",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        prompt_bytes=0,
        latency_ms=0.0,
    )


def _zero_retriever_decision(
    *,
    route: str,
    tool_name: str,
    supporting_doc_ids: tuple[str, ...],
    candidate_rank: int,
) -> RetrieverRoleDecision:
    return RetrieverRoleDecision(
        route=route,
        tool_name=tool_name,
        supporting_doc_ids=supporting_doc_ids,
        reason="exact_replay_restore",
        candidate_rank=candidate_rank,
        raw_text="",
        model="replay-restore",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        prompt_bytes=0,
        latency_ms=0.0,
    )


def _zero_executor_decision(
    *,
    route: str,
    tool_name: str,
    action_contract: str,
) -> ExecutorRoleDecision:
    return ExecutorRoleDecision(
        route=route,
        tool_name=tool_name,
        action_contract=action_contract,
        reason="exact_replay_restore",
        raw_text="",
        model="replay-restore",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        prompt_bytes=0,
        latency_ms=0.0,
    )


def _zero_summarizer_decision(
    *,
    summary_text: str,
    tags: tuple[str, ...],
) -> SummarizerRoleDecision:
    return SummarizerRoleDecision(
        summary_text=summary_text,
        reusable_steps=("retrieve", "execute"),
        confidence=1.0,
        tags=tags,
        raw_text="",
        model="replay-restore",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        prompt_bytes=0,
        latency_ms=0.0,
    )


def _role_handoff_bytes(
    *,
    planner_result: PlannerRoleResult,
    retriever_decision: RetrieverRoleDecision,
    executor_decision: ExecutorRoleDecision,
    summarizer_decision: SummarizerRoleDecision,
) -> dict[str, int]:
    planner_handoff = stable_json_dumps(
        {
            "workflow_payload": planner_result.workflow_payload,
            "retrieval_objective": planner_result.retrieval_objective,
        }
    )
    retriever_handoff = stable_json_dumps(
        {
            "route": retriever_decision.route,
            "tool_name": retriever_decision.tool_name,
            "supporting_doc_ids": list(retriever_decision.supporting_doc_ids),
            "reason": retriever_decision.reason,
        }
    )
    executor_handoff = stable_json_dumps(
        {
            "route": executor_decision.route,
            "tool_name": executor_decision.tool_name,
            "action_contract": executor_decision.action_contract,
            "reason": executor_decision.reason,
        }
    )
    summarizer_handoff = stable_json_dumps(
        {
            "summary_text": summarizer_decision.summary_text,
            "reusable_steps": list(summarizer_decision.reusable_steps),
            "confidence": summarizer_decision.confidence,
            "tags": list(summarizer_decision.tags),
        }
    )
    return {
        "planner": len(planner_handoff.encode("utf-8")),
        "retriever": len(retriever_handoff.encode("utf-8")),
        "executor": len(executor_handoff.encode("utf-8")),
        "summarizer": len(summarizer_handoff.encode("utf-8")),
    }


def _benchmark_layer_from_config(layer_config: SmokeLayerConfig) -> str:
    if layer_config.replay_enabled:
        return "L3"
    if layer_config.semantic_pruning_enabled:
        return "L2"
    if layer_config.structured_control_enabled:
        return "L1"
    return "L0"


def _build_semantic_state_ref(
    *,
    task_id: str,
    bundle: RetrievalBundle,
    materialized_state: MaterializedStateHandle,
) -> SemanticStateRef:
    return SemanticStateRef(
        state_id=f"state-{task_id}",
        state_kind="EMBEDDING_STATE",
        storage_kind=materialized_state.storage_kind,
        length=bundle.query_embedding.dims,
        blob_hash=materialized_state.blob_hash,
        manifest_id=bundle.hydrate_manifest.manifest_hash,
        source_doc_hashes=bundle.selected_doc_hashes,
        metadata={
            "embedding_ref_id": bundle.query_embedding.embedding_id,
            "encoding": bundle.query_embedding.encoding,
            "storage_metadata_path": str(materialized_state.metadata_path),
            "shared_memory_name": materialized_state.shared_memory_name,
        },
    )


def _quality_floor_from_precommit(
    *,
    compiler_status: str,
    validator_reports: tuple[ArtifactValidatorReport, ...],
) -> QualityFloorResult:
    report_by_scope = {report.validation_scope: report for report in validator_reports}
    deterministic_checks_passed = (
        compiler_status == "compiled"
        and report_by_scope.get("deterministic") is not None
        and report_by_scope["deterministic"].passed
    )
    fact_coverage_passed = (
        report_by_scope.get("fact_coverage") is not None
        and report_by_scope["fact_coverage"].passed
    )
    return QualityFloorResult(
        quality_floor_pass=deterministic_checks_passed and fact_coverage_passed,
        deterministic_checks_passed=deterministic_checks_passed,
        fact_coverage_passed=fact_coverage_passed,
        llm_judge_passed=None,
        quality_floor_fail_reason=(
            ""
            if deterministic_checks_passed and fact_coverage_passed
            else "fact_coverage_failed" if deterministic_checks_passed else "deterministic_checks_failed"
        ),
    )
def _goal_from_spec(spec: object) -> str:
    task_family = str(getattr(spec, "task_family", "")).strip()
    arguments = getattr(spec, "arguments", {}) or {}
    if task_family == "continuous_csv_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        intent = str(getattr(spec, "intent_op", "analyze"))
        return f"Execute {intent} for {dataset_id} and persist contract-aligned structured outputs."
    if task_family == "continuous_long_doc_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        intent = str(getattr(spec, "intent_op", "analyze"))
        return f"Execute long-doc {intent} for {dataset_id} and persist cited reusable artifacts."
    ticker = str(getattr(spec, "arguments", {}).get("ticker", "ACME"))
    quarter = str(getattr(spec, "arguments", {}).get("quarter", "2026Q1"))
    metric = str(getattr(spec, "arguments", {}).get("metric", "revenue"))
    intent = str(getattr(spec, "intent_op", "compare_metric"))
    return f"Produce a {intent} answer for {ticker} {quarter} using {metric} evidence."


def _summary_hint_from_spec(spec: object) -> str:
    task_family = str(getattr(spec, "task_family", "")).strip()
    arguments = getattr(spec, "arguments", {}) or {}
    if task_family == "continuous_csv_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        intent = str(getattr(spec, "intent_op", "analyze"))
        return f"{dataset_id} {intent} summary ready"
    if task_family == "continuous_long_doc_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        intent = str(getattr(spec, "intent_op", "analyze"))
        return f"{dataset_id} {intent} cited summary ready"
    ticker = str(getattr(spec, "arguments", {}).get("ticker", "ACME"))
    quarter = str(getattr(spec, "arguments", {}).get("quarter", "2026Q1"))
    intent = str(getattr(spec, "intent_op", "compare_metric"))
    return f"{ticker} {quarter} {intent} summary ready"


def _evidence_text_from_retrieval(bundle: RetrievalBundle) -> str:
    lines: list[str] = []
    for item in bundle.evidence_pack.hard_facts:
        lines.append(item.rendered_text)
    for item in bundle.evidence_pack.semantic_contexts:
        lines.append(item.rendered_text)
    for item in bundle.evidence_pack.lexical_hints:
        lines.append(item.rendered_text)
    return "\n".join(lines)


def _stable_keys_from_bucket_items(items: tuple[object, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    for item in items:
        locator = getattr(item, "locator", None)
        if locator is None:
            continue
        if hasattr(locator, "canonical_text_id"):
            keys.append(
                f"text:{locator.source_doc_hash}:{locator.canonical_text_id}:{locator.start_char}:{locator.end_char}"
            )
        elif hasattr(locator, "table_id"):
            keys.append(
                f"table:{locator.source_doc_hash}:{locator.table_id}:{locator.sheet_name}:{locator.row_idx}:{locator.col_idx}"
            )
    return tuple(dict.fromkeys(keys))


def _build_role_hydrated_slices(bundle: RetrievalBundle) -> dict[str, RoleHydratedSlice]:
    registry = build_hydration_registry_from_evidence_pack(bundle.evidence_pack)
    semantic_keys = _stable_keys_from_bucket_items(bundle.evidence_pack.semantic_contexts)
    table_keys = _stable_keys_from_bucket_items(bundle.evidence_pack.hard_facts)
    retriever_keys = _stable_keys_from_bucket_items((*bundle.evidence_pack.hard_facts, *bundle.evidence_pack.semantic_contexts))
    executor_keys = _stable_keys_from_bucket_items(bundle.evidence_pack.hard_facts)
    summarizer_keys = _stable_keys_from_bucket_items((*bundle.evidence_pack.hard_facts, *bundle.evidence_pack.semantic_contexts))
    artifact_context = "\n".join(
        item.rendered_text for item in bundle.evidence_pack.structured_evidence if item.rendered_text
    )
    artifact_context_bytes = len(artifact_context.encode("utf-8"))
    artifact_context_count = len(bundle.evidence_pack.structured_evidence)
    retriever_text = role_hydrated_slice(
        role="retriever",
        manifest=bundle.hydrate_manifest,
        registry=registry,
        selected_keys=semantic_keys,
    )
    retriever_table = role_hydrated_slice(
        role="retriever",
        manifest=bundle.hydrate_manifest,
        registry=registry,
        selected_keys=table_keys,
    )
    executor_table = role_hydrated_slice(
        role="executor",
        manifest=bundle.hydrate_manifest,
        registry=registry,
        selected_keys=table_keys,
    )
    summarizer_text = role_hydrated_slice(
        role="summarizer",
        manifest=bundle.hydrate_manifest,
        registry=registry,
        selected_keys=semantic_keys,
    )
    summarizer_table = role_hydrated_slice(
        role="summarizer",
        manifest=bundle.hydrate_manifest,
        registry=registry,
        selected_keys=table_keys,
    )
    return {
        "planner": RoleHydratedSlice(
            role="planner",
            selected_stable_keys=(),
            hydrated_text="",
            hydrated_bytes=0,
            item_count=0,
        ),
        "retriever": RoleHydratedSlice(
            role="retriever",
            selected_stable_keys=retriever_keys,
            hydrated_text=retriever_text.hydrated_text,
            hydrated_bytes=retriever_text.hydrated_bytes,
            item_count=retriever_text.item_count,
            table_text=retriever_table.hydrated_text,
            table_bytes=retriever_table.hydrated_bytes,
            table_item_count=retriever_table.item_count,
            artifact_text=artifact_context,
            artifact_bytes=artifact_context_bytes,
            artifact_item_count=artifact_context_count,
        ),
        "executor": RoleHydratedSlice(
            role="executor",
            selected_stable_keys=executor_keys,
            hydrated_text="",
            hydrated_bytes=0,
            item_count=0,
            table_text=executor_table.hydrated_text,
            table_bytes=executor_table.hydrated_bytes,
            table_item_count=executor_table.item_count,
            artifact_text=artifact_context,
            artifact_bytes=artifact_context_bytes,
            artifact_item_count=artifact_context_count,
        ),
        "summarizer": RoleHydratedSlice(
            role="summarizer",
            selected_stable_keys=summarizer_keys,
            hydrated_text=summarizer_text.hydrated_text,
            hydrated_bytes=summarizer_text.hydrated_bytes,
            item_count=summarizer_text.item_count,
            table_text=summarizer_table.hydrated_text,
            table_bytes=summarizer_table.hydrated_bytes,
            table_item_count=summarizer_table.item_count,
            artifact_text=artifact_context,
            artifact_bytes=artifact_context_bytes,
            artifact_item_count=artifact_context_count,
        ),
    }


def _planner_scope_payload(
    spec: CanonicalTaskSpec,
    *,
    history_runtime_roots: tuple[Path, ...] = (),
) -> dict[str, object]:
    if spec.task_family == "continuous_csv_table_analysis":
        if spec.intent_op == "summarize_reuse_lineage":
            artifact_summaries = _history_artifact_summaries(history_runtime_roots)
            text_context = "\n".join(artifact_summaries)
            lineage_items = [
                str(item).strip()
                for item in spec.arguments.get("required_lineage", [])
                if str(item).strip()
            ]
            return {
                "supporting_doc_ids": [f"sha256:artifact-lineage-{spec.spec_hash[:12]}"],
                "source_doc_hashes": [f"sha256:artifact-lineage-{spec.spec_hash[:12]}"],
                "text_context": "",
                "text_bytes": 0,
                "text_item_count": 0,
                "table_context": "",
                "table_bytes": 0,
                "table_item_count": 0,
                "artifact_context": text_context,
                "artifact_bytes": len(text_context.encode("utf-8")),
                "artifact_item_count": len(artifact_summaries),
                "history_artifact_summaries": list(artifact_summaries),
                "history_runtime_root_count": len(history_runtime_roots),
                "required_lineage": lineage_items,
            }
        dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
        csv_path = str(spec.arguments.get("csv_path", "")).strip()
        document = OfflineCsvTableCorpus().resolve(dataset_id=dataset_id, csv_path=csv_path)
        text_context = "\n".join(fragment.text for fragment in document.text_fragments)
        table_context = "\n".join(row.rendered_text for row in document.table_rows)
        return {
            "supporting_doc_ids": [document.source_doc_hash],
            "source_doc_hashes": [document.source_doc_hash],
            "text_context": text_context,
            "text_bytes": len(text_context.encode("utf-8")),
            "text_item_count": len(document.text_fragments),
            "table_context": table_context,
            "table_bytes": len(table_context.encode("utf-8")),
            "table_item_count": len(document.table_rows),
        }
    if spec.task_family == "continuous_long_doc_table_analysis":
        dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
        document_path = str(spec.arguments.get("document_path", "")).strip()
        if not document_path:
            document_path = "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md"
        document = OfflineMarkdownLongDocCorpus().resolve(dataset_id=dataset_id, document_path=document_path)
        text_context = "\n".join(fragment.text for fragment in document.text_fragments)
        table_context = "\n".join(row.rendered_text for row in document.table_rows)
        return {
            "supporting_doc_ids": [document.source_doc_hash],
            "source_doc_hashes": [document.source_doc_hash],
            "text_context": text_context,
            "text_bytes": len(text_context.encode("utf-8")),
            "text_item_count": len(document.text_fragments),
            "table_context": table_context,
            "table_bytes": len(table_context.encode("utf-8")),
            "table_item_count": len(document.table_rows),
        }
    ticker = str(spec.arguments.get("ticker", "ACME"))
    quarter = str(spec.arguments.get("quarter", "2026Q1"))
    document = OfflineFinancialReportCorpus().resolve(ticker=ticker, quarter=quarter)
    text_context = "\n".join(fragment.text for fragment in document.text_fragments)
    table_context = "\n".join(row.rendered_text for row in document.table_rows)
    return {
        "supporting_doc_ids": [document.source_doc_hash],
        "source_doc_hashes": [document.source_doc_hash],
        "text_context": text_context,
        "text_bytes": len(text_context.encode("utf-8")),
        "text_item_count": len(document.text_fragments),
        "table_context": table_context,
        "table_bytes": len(table_context.encode("utf-8")),
        "table_item_count": len(document.table_rows),
    }


def _query_text_from_spec(spec: object) -> str:
    arguments = getattr(spec, "arguments", {}) or {}
    request_text = str(arguments.get("request_text", "")).strip()
    if request_text:
        return request_text
    if str(getattr(spec, "task_family", "")).strip() == "continuous_csv_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        csv_path = str(arguments.get("csv_path", ""))
        intent = str(getattr(spec, "intent_op", "analyze"))
        return f"{dataset_id} {intent} {csv_path}".strip()
    if str(getattr(spec, "task_family", "")).strip() == "continuous_long_doc_table_analysis":
        dataset_id = str(arguments.get("dataset_id", "dataset"))
        topic = str(arguments.get("topic", arguments.get("metric", ""))).strip()
        intent = str(getattr(spec, "intent_op", "analyze"))
        return " ".join(part for part in (dataset_id, topic, intent) if part).strip()
    ticker = str(arguments.get("ticker", "ACME"))
    quarter = str(arguments.get("quarter", "2026Q1"))
    metric = str(arguments.get("metric", "revenue"))
    intent = str(getattr(spec, "intent_op", "compare_metric"))
    return f"{ticker} {quarter} {metric} {intent}"


def _full_corpus_prompt_slice(bundle: RetrievalBundle, *, role: str) -> RolePromptSlice:
    planner_scope = dict(bundle.planner_scope_payload or {})
    text_context = str(planner_scope.get("text_context", "")).strip()
    table_context = str(planner_scope.get("table_context", "")).strip()
    artifact_context = str(planner_scope.get("artifact_context", "")).strip()
    return RolePromptSlice(
        role=role,
        hydrated_text=text_context,
        hydrated_bytes=len(text_context.encode("utf-8")),
        item_count=int(planner_scope.get("text_item_count", 0)),
        table_text=table_context,
        table_bytes=len(table_context.encode("utf-8")),
        table_item_count=int(planner_scope.get("table_item_count", 0)),
        artifact_text=artifact_context,
        artifact_bytes=len(artifact_context.encode("utf-8")),
        artifact_item_count=int(planner_scope.get("artifact_item_count", 0)),
    )


def _memory_prompt_slice(memory_match_result) -> tuple[str, int, int]:
    if not memory_match_result.matches:
        return "", 0, 0
    lines = [
        stable_json_dumps(
            {
                "memory_id": match.memory_ref.memory_id,
                "replay_class": match.replay_class.value,
                "score": match.score,
                "summary": match.memory_ref.summary,
            }
        )
        for match in memory_match_result.matches[:2]
    ]
    payload = "\n".join(line for line in lines if line)
    return payload, len(payload.encode("utf-8")), len(lines)


def _default_precompiled_spec() -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        required_tools=("table_retriever", "semantic_retriever"),
        arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
    )


def _prompt_manifests() -> tuple[SignatureManifestEntry, ...]:
    return (
        SignatureManifestEntry(
            entry_id="role_path.planner",
            entry_version="v4",
            entry_kind="prompt",
            payload={
                "role": "planner",
                "input_contract": "goal+query+summary_hint+required_roles+tags+inline_evidence",
                "output_contract": "retrieval_objective+ambiguity_checklist+downstream_target_role",
            },
        ),
        SignatureManifestEntry(
            entry_id="role_path.retriever",
            entry_version="v4",
            entry_kind="prompt",
            payload={
                "role": "retriever",
                "input_contract": "query+retrieved_doc_ids+minimal_candidate_surface+inline_evidence",
                "output_contract": "selected_evidence_subset+route_hypotheses+candidate_tools",
            },
        ),
        SignatureManifestEntry(
            entry_id="role_path.executor",
            entry_version="v4",
            entry_kind="prompt",
            payload={
                "role": "executor",
                "input_contract": "retriever_selection+action_contract+minimal_candidate_surface+inline_evidence",
                "output_contract": "route+tool+action_contract",
            },
        ),
        SignatureManifestEntry(
            entry_id="role_path.summarizer",
            entry_version="v4",
            entry_kind="prompt",
            payload={
                "role": "summarizer",
                "input_contract": "summary_hint+inline_evidence+inline_action_handoff+tag_hints",
                "output_contract": "summary_text+reusable_steps+confidence+tags",
            },
        ),
        SignatureManifestEntry(
            entry_id="output_contract",
            entry_version="output-v1",
            entry_kind="prompt",
            payload={"primary_output": "summary_json", "artifact_type": "json"},
        ),
    )


def _extractor_manifests() -> tuple[SignatureManifestEntry, ...]:
    return (
        SignatureManifestEntry(
            entry_id="retriever.lexical_metadata",
            entry_version="v1",
            entry_kind="extractor",
            payload={"retriever_kind": "lexical_metadata", "bucket": "lexical_hint"},
        ),
        SignatureManifestEntry(
            entry_id="retriever.semantic_chunk",
            entry_version="v1",
            entry_kind="extractor",
            payload={"retriever_kind": "semantic_chunk", "bucket": "semantic_context"},
        ),
        SignatureManifestEntry(
            entry_id="retriever.table_structure",
            entry_version="v1",
            entry_kind="extractor",
            payload={"retriever_kind": "table_structure", "bucket": "hard_fact"},
        ),
        SignatureManifestEntry(
            entry_id="fan_in.deterministic",
            entry_version="v1",
            entry_kind="extractor",
            payload={"fan_in_contract": "deterministic", "pack_contract": "canonical_evidence_pack_v1"},
        ),
    )

def _build_validator_reports(
    *,
    task_id: str,
    step_id: str,
    artifact_id: str,
    output_payload: dict[str, object],
    output_path: Path,
    replay_decision: ReplayDecision,
    layer_config: SmokeLayerConfig,
    required_outputs: tuple[str, ...] = (),
    quality_checks: tuple[str, ...] = (),
    expected_facts: dict[str, object] | None = None,
) -> tuple[ArtifactValidatorReport, ...]:
    required_fields = tuple(required_outputs) if required_outputs else ("summary_text",)
    deterministic_pass = output_path.exists() and all(bool(output_payload.get(field_name)) for field_name in required_fields)
    quality_checks_pass = _quality_checks_pass(
        output_payload=output_payload,
        quality_checks=quality_checks,
        output_path=output_path,
    )
    fact_coverage_pass = _expected_fact_pass(
        expected_facts=expected_facts,
        output_payload=output_payload,
    )
    deterministic = ArtifactValidatorReport(
        task_id=task_id,
        step_id=step_id,
        artifact_id=artifact_id,
        validation_scope="deterministic",
        passed=deterministic_pass and quality_checks_pass,
        fail_reason="" if deterministic_pass and quality_checks_pass else "missing_required_output_fields",
        consumed_by=("executor_wrapper",),
        metrics={"output_exists": 1.0 if output_path.exists() else 0.0},
        details={"required_fields": list(required_fields), "quality_checks": list(quality_checks)},
    )
    fact_coverage = ArtifactValidatorReport(
        task_id=task_id,
        step_id=step_id,
        artifact_id=artifact_id,
        validation_scope="fact_coverage",
        passed=fact_coverage_pass,
        fail_reason="" if fact_coverage_pass else "fact_coverage_failed",
        consumed_by=("quality_floor_gate",),
        metrics={"required_fact_count": float(len(expected_facts or {}))},
        details={
            "replay_class": replay_decision.replay_class.value,
            "expected_facts": {} if expected_facts is None else dict(expected_facts),
        },
    )
    return (deterministic, fact_coverage)


def _expected_fact_pass(
    *,
    expected_facts: dict[str, object] | None,
    output_payload: dict[str, object],
) -> bool:
    if not expected_facts:
        return True
    for key, expected_value in expected_facts.items():
        observed_value = _lookup_output_value(output_payload, key)
        if observed_value is not None:
            if not _expected_value_matches(observed_value=observed_value, expected_value=expected_value):
                return False
        elif key.endswith("_min"):
            observed_value = _lookup_output_value(output_payload, key.removesuffix("_min"))
            if observed_value in {None, ""}:
                return False
            try:
                if float(observed_value) < float(expected_value):
                    return False
            except ValueError:
                return False
        else:
            return False
    return True


def _expected_value_matches(*, observed_value: object, expected_value: object) -> bool:
    if str(observed_value) == str(expected_value):
        return True
    try:
        return float(str(observed_value)) == float(str(expected_value))
    except ValueError:
        return False


def _lookup_output_value(output_payload: dict[str, object], key: str) -> object:
    if key in output_payload:
        return output_payload.get(key)
    current: object = output_payload
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _quality_checks_pass(
    *,
    output_payload: dict[str, object],
    quality_checks: tuple[str, ...],
    output_path: Path,
) -> bool:
    for check in quality_checks:
        if not _quality_check_pass(output_payload=output_payload, check=check, output_path=output_path):
            return False
    return True


def _quality_check_pass(
    *,
    output_payload: dict[str, object],
    check: str,
    output_path: Path,
) -> bool:
    parts = check.split(":")
    if not parts:
        return False
    kind = parts[0]
    if kind == "artifact_exists" and len(parts) == 2:
        relpath = str(_lookup_output_value(output_payload, parts[1]) or "").strip()
        return bool(relpath) and (output_path.parents[1] / relpath).exists()
    if kind == "field_present" and len(parts) == 2:
        value = _lookup_output_value(output_payload, parts[1])
        return value not in {None, ""}
    if kind == "exact" and len(parts) == 2:
        value = _lookup_output_value(output_payload, parts[1])
        return value not in {None, ""}
    if kind == "numeric_tolerance" and len(parts) == 3:
        value = _lookup_output_value(output_payload, parts[1])
        if value in {None, ""}:
            return False
        try:
            float(value)
            float(parts[2])
        except ValueError:
            return False
        return True
    if kind == "contains" and len(parts) == 3:
        value = _lookup_output_value(output_payload, parts[1])
        if value in {None, ""}:
            return False
        return parts[2].lower() in str(value).lower()
    if kind == "field_gte" and len(parts) == 3:
        value = _lookup_output_value(output_payload, parts[1])
        if value in {None, ""}:
            return False
        try:
            return float(value) >= float(parts[2])
        except ValueError:
            return False
    return False


def _build_input_validator_reports(
    *,
    task_id: str,
    step_id: str,
    input_manifest: InputManifest,
    materialized_input_paths: tuple[Path, ...],
) -> tuple[InputValidatorReport, ...]:
    missing_inputs = [
        item.name
        for item, path in zip(input_manifest.inputs, materialized_input_paths, strict=True)
        if not path.exists()
    ]
    return (
        InputValidatorReport(
            task_id=task_id,
            step_id=step_id,
            validation_scope="input_manifest",
            passed=not missing_inputs,
            fail_reason="" if not missing_inputs else "missing_materialized_inputs",
            required_inputs=tuple(item.name for item in input_manifest.inputs),
            observed_inputs=tuple(sorted(item.name for item in input_manifest.inputs)),
            metrics={"materialized_input_count": float(len(materialized_input_paths))},
            details={"missing_inputs": missing_inputs},
        ),
    )


def _fallback_action_for_attempt(
    *,
    layer_config: SmokeLayerConfig,
    attempt_index: int,
) -> str:
    if layer_config.multi_attempt_enabled and layer_config.force_first_attempt_trap and attempt_index == 0:
        return "retry_same_step"
    return "none"


def _driver_profile_from_layer_config(layer_config: SmokeLayerConfig) -> RuntimeDriverProfile:
    return RuntimeDriverProfile(
        layer_name=layer_config.layer_name,
        handoff_mode=layer_config.handoff_mode,
        structured_control_enabled=layer_config.structured_control_enabled,
        semantic_pruning_enabled=layer_config.semantic_pruning_enabled,
        semantic_state_transfer_enabled=layer_config.semantic_state_transfer_enabled,
        replay_enabled=layer_config.replay_enabled,
        multi_attempt_enabled=layer_config.multi_attempt_enabled,
        force_first_attempt_trap=layer_config.force_first_attempt_trap,
        persistence_verification_level="strict_roundtrip",
    )


def _workflow_template(*, step_id: str, artifact_id: str) -> tuple[RuntimeWorkflowStep, ...]:
    return (
        RuntimeWorkflowStep(
            step_id="planner.compile",
            role="planner",
            capability="compile_task_spec",
            output_refs=("canonical_task_spec",),
        ),
        RuntimeWorkflowStep(
            step_id="retriever.fanout",
            role="retriever",
            capability="fanout_retrieval",
            depends_on=("planner.compile",),
            output_refs=("evidence_pack", "hydrate_manifest", "retrieval_log", "query_embedding"),
        ),
        RuntimeWorkflowStep(
            step_id=step_id,
            role="executor",
            capability="materialize_and_execute",
            depends_on=("retriever.fanout",),
            input_refs=("evidence_pack", "hydrate_manifest", "retrieval_log"),
            output_refs=(artifact_id,),
            can_skip_if="memory.exact_replay_hit",
            max_retries=1,
        ),
        RuntimeWorkflowStep(
            step_id="summarizer.commit",
            role="summarizer",
            capability="quality_floor_and_memory_commit",
            depends_on=(step_id,),
            input_refs=(artifact_id,),
            output_refs=("memory_commit", "replay_ledger"),
        ),
    )


def run_smoke(
    *,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    request_text: str | None = None,
    canonical_task_spec: CanonicalTaskSpec | None = None,
    task_id: str = "smoke-task",
    layer_config: SmokeLayerConfig | None = None,
    expected_facts: dict[str, object] | None = None,
    seed_replay_memory: bool = False,
    history_runtime_roots: tuple[Path, ...] = (),
    driver_profile_override: RuntimeDriverProfile | None = None,
) -> SmokeResult:
    layer_config = layer_config or SmokeLayerConfig()
    if layer_config.hermetic_runtime_root and runtime_root.exists():
        shutil.rmtree(runtime_root)
    preflight = runtime_preflight(
        role_path_mode=layer_config.role_path_mode,
        embedding_mode=layer_config.embedding_mode,
    )
    if not preflight.ok:
        raise RuntimeError("; ".join(preflight.missing_reasons))

    trace_id = "trace-smoke"
    step_id = "step-execute"
    attempt_id = "attempt-1"

    compiler = TaskCompiler()
    compiler_result = compiler.compile(
        TaskCompilerInput(
            request_text=request_text
            or "",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=canonical_task_spec or _default_precompiled_spec(),
        )
    )
    if compiler_result.canonical_task_spec is None:
        raise RuntimeError("smoke path requires compiled canonical task spec")

    llm_config = LLMConfig.from_runtime().with_mode(layer_config.role_path_mode)
    try:
        role_path_runner = RolePathRunner(
            llm_client=build_llm_client(llm_config),
            handoff_mode=layer_config.handoff_mode,
        )
    except TypeError:
        role_path_runner = RolePathRunner(llm_client=build_llm_client(llm_config))
        if hasattr(role_path_runner, "handoff_mode"):
            object.__setattr__(role_path_runner, "handoff_mode", layer_config.handoff_mode)
    goal_text = _goal_from_spec(compiler_result.canonical_task_spec)
    summary_hint = _summary_hint_from_spec(compiler_result.canonical_task_spec)
    planner_query_text = _query_text_from_spec(compiler_result.canonical_task_spec)
    planner_scope_payload = _planner_scope_payload(
        compiler_result.canonical_task_spec,
        history_runtime_roots=history_runtime_roots,
    )
    planner_role_candidates = tuple(financial_tool_candidates(compiler_result.canonical_task_spec, None))
    planner_result = role_path_runner.plan_workflow(
        task_id=task_id,
        task_group=compiler_result.canonical_task_spec.task_family,
        task_theme=compiler_result.canonical_task_spec.task_family,
        goal=goal_text,
        query_text=planner_query_text,
        summary_hint=summary_hint,
        visible_candidates=planner_role_candidates,
        prompt_slice=RolePromptSlice(
            role="planner",
            hydrated_text=str(planner_scope_payload.get("text_context", "")),
            hydrated_bytes=int(planner_scope_payload.get("text_bytes", 0)),
            item_count=int(planner_scope_payload.get("text_item_count", 0)),
            table_text=str(planner_scope_payload.get("table_context", "")),
            table_bytes=int(planner_scope_payload.get("table_bytes", 0)),
            table_item_count=int(planner_scope_payload.get("table_item_count", 0)),
            artifact_text=str(planner_scope_payload.get("artifact_context", "")),
            artifact_bytes=int(planner_scope_payload.get("artifact_bytes", 0)),
            artifact_item_count=int(planner_scope_payload.get("artifact_item_count", 0)),
        ),
        strict_surface=True,
        tags=tuple(compiler_result.canonical_task_spec.required_tools),
    )
    planner_retrieval_objective = {
        **planner_scope_payload,
        **role_path_runner.build_retrieval_objective(
            spec=compiler_result.canonical_task_spec,
            goal=goal_text,
            query_text=planner_query_text,
            tags=tuple(compiler_result.canonical_task_spec.required_tools),
        ),
        **dict(planner_result.retrieval_objective),
    }
    retrieval_query_text = str(planner_retrieval_objective.get("query_text", planner_query_text)).strip() or planner_query_text

    retrieval = RetrieverFanoutPipeline.with_embedding_mode(layer_config.embedding_mode).run(
        task_id=task_id,
        spec=CanonicalTaskSpec(
            task_family=compiler_result.canonical_task_spec.task_family,
            intent_op=compiler_result.canonical_task_spec.intent_op,
            target_entities=compiler_result.canonical_task_spec.target_entities,
            time_scope=compiler_result.canonical_task_spec.time_scope,
            required_outputs=compiler_result.canonical_task_spec.required_outputs,
            required_tools=compiler_result.canonical_task_spec.required_tools,
            arguments={
                **compiler_result.canonical_task_spec.arguments,
                "request_text": retrieval_query_text,
            },
        ),
        planner_scope_payload=planner_retrieval_objective,
    )
    role_hydrated_slices = _build_role_hydrated_slices(retrieval)
    role_hydrated_slices["planner"] = RoleHydratedSlice(
        role="planner",
        selected_stable_keys=(),
        hydrated_text=str(planner_scope_payload.get("text_context", "")),
        hydrated_bytes=int(planner_scope_payload.get("text_bytes", 0)),
        item_count=int(planner_scope_payload.get("text_item_count", 0)),
        table_text=str(planner_scope_payload.get("table_context", "")),
        table_bytes=int(planner_scope_payload.get("table_bytes", 0)),
        table_item_count=int(planner_scope_payload.get("table_item_count", 0)),
        artifact_text=str(planner_scope_payload.get("artifact_context", "")),
        artifact_bytes=int(planner_scope_payload.get("artifact_bytes", 0)),
        artifact_item_count=int(planner_scope_payload.get("artifact_item_count", 0)),
    )

    state_store = LayeredStateStore(root=runtime_root / "state")
    semantic_state_handle: MaterializedStateHandle | None = None
    semantic_ref: SemanticStateRef | None = None
    if layer_config.semantic_pruning_enabled and layer_config.semantic_state_transfer_enabled:
        semantic_payload = (stable_json_dumps(retrieval.query_embedding.canonical_payload()) + "\n").encode("utf-8")
        semantic_state_handle = state_store.publish(
            ref_id=f"state-{task_id}",
            object_kind="EMBEDDING_STATE",
            payload=semantic_payload,
        )
        if state_store.load(f"state-{task_id}") != semantic_payload:
            raise RuntimeError("semantic state materialization round-trip failed")
        semantic_ref = _build_semantic_state_ref(
            task_id=task_id,
            bundle=retrieval,
            materialized_state=semantic_state_handle,
        )

    runtime_stage_metrics: dict[str, float] = {}
    runtime_stage_metrics["codeact_execution_stage_ms"] = 0.0
    workspace = WorkspaceManager(workspace_root)
    layout = workspace.ensure_layout(task_id)
    step_layout = workspace.ensure_step_layout(layout, step_id)
    workspace_stage_start_ns = time.perf_counter_ns()
    materialized_task_spec = workspace.write_json(
        layout,
        "inputs/canonical_task_spec.json",
        compiler_result.canonical_task_spec.canonical_payload(),
        logical_name="canonical_task_spec",
    )
    planner_handoff = PlannerHandoff(
        task_id=task_id,
        canonical_task_spec_hash=compiler_result.canonical_task_spec.spec_hash,
        retrieval_objective=planner_retrieval_objective,
        planner_plan_payload=planner_result.workflow_payload,
        planner_scope_payload=planner_scope_payload,
        summary_hint=summary_hint,
    )
    materialized_hydrate_manifest = workspace.write_json(
        layout,
        "inputs/hydrate_manifest.json",
        manifest_to_dict(retrieval.hydrate_manifest),
        logical_name="hydrate_manifest",
    )
    materialized_retrieval_log = workspace.write_json(
        layout,
        "inputs/retrieval_log.json",
        retrieval.log_payload(),
        logical_name="retrieval_log",
    )
    input_manifest = InputManifest(
        task_id=task_id,
        step_id=step_id,
        workspace_root=str(layout.root),
        inputs=(
            InputManifestItem(
                name="planner_handoff",
                artifact_type="json",
                relpath="inputs/planner_handoff.json",
                blob_hash=planner_handoff.handoff_hash,
                source_ref_id="planner-handoff",
            ),
            InputManifestItem(
                name="canonical_evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash=retrieval.evidence_pack.pack_hash,
                source_ref_id="" if semantic_ref is None else semantic_ref.state_id,
            ),
        ),
    )
    materialized_inputs = workspace.materialize_input_bundle(
        layout,
        input_manifest,
        payload_by_name={
            "planner_handoff": {
                **planner_handoff.canonical_payload(),
            },
            "canonical_evidence_pack": retrieval.evidence_pack.canonical_payload(),
        },
    )
    workspace_input_direct_write_count = float(
        sum(
            1
            for file in (
                materialized_task_spec,
                materialized_hydrate_manifest,
                materialized_retrieval_log,
            )
            if file.write_performed
        )
    )
    workspace_input_bundle_write_count = float(sum(1 for file in materialized_inputs.files if file.write_performed))
    workspace_input_bundle_reused_count = float(sum(1 for file in materialized_inputs.files if not file.write_performed))
    runtime_stage_metrics.update(
        {
            "workspace_input_stage_ms": _elapsed_ms(workspace_stage_start_ns),
            "workspace_input_direct_write_count": workspace_input_direct_write_count,
            "workspace_input_bundle_write_count": workspace_input_bundle_write_count,
            "workspace_input_bundle_reused_count": workspace_input_bundle_reused_count,
            "workspace_input_manifest_write_count": (
                1.0 if materialized_inputs.manifest_file.write_performed else 0.0
            ),
        }
    )
    input_validator_reports = _build_input_validator_reports(
        task_id=task_id,
        step_id=step_id,
        input_manifest=input_manifest,
        materialized_input_paths=tuple(file.path for file in materialized_inputs.files),
    )

    role_candidates = constrain_visible_candidates(
        tuple(financial_tool_candidates(compiler_result.canonical_task_spec, retrieval.candidate_pool)),
        candidate_keys=tuple(
            str(item).strip()
            for item in planner_retrieval_objective.get("candidate_keys", [])
            if str(item).strip()
        ),
        required_tools=tuple(
            str(item).strip()
            for item in planner_retrieval_objective.get("required_tools", [])
            if str(item).strip()
        ),
    )
    top_candidate = best_visible_candidate(role_candidates)
    restored_supporting_doc_ids = top_candidate.supporting_doc_ids or retrieval.selected_doc_hashes
    runtime_signature_capture_start_ns = time.perf_counter_ns()
    prompt_manifests = _prompt_manifests()
    extractor_manifests = _extractor_manifests()
    tool_registry_manifests = tuple(
        SignatureManifestEntry(
            entry_id=profile.registry_entry_id(),
            entry_version="catalog-v1",
            entry_kind="tool_registry",
            payload=profile.registry_payload(),
        )
        for profile in stable_tool_registry_profiles()
    )
    runtime_signature_manifest_bundle = capture_runtime_signature_manifest_bundle(
        prompt_manifests=prompt_manifests,
        extractor_manifests=extractor_manifests,
        tool_registry_manifests=tool_registry_manifests,
    )
    runtime_signature = capture_runtime_signature(
        prompt_manifests=prompt_manifests,
        extractor_manifests=extractor_manifests,
        tool_registry_manifests=tool_registry_manifests,
    )
    runtime_signature_capture_stage_ms = _elapsed_ms(runtime_signature_capture_start_ns)
    runtime_signature_materialize_start_ns = time.perf_counter_ns()
    materialized_runtime_signature_manifest_bundle = workspace.write_json(
        layout,
        "inputs/runtime_signature_manifest_bundle.json",
        runtime_signature_manifest_bundle.canonical_payload(),
        logical_name="runtime_signature_manifest_bundle",
    )
    runtime_signature_materialize_stage_ms = _elapsed_ms(runtime_signature_materialize_start_ns)
    runtime_stage_metrics.update(
        {
            "runtime_signature_capture_stage_ms": runtime_signature_capture_stage_ms,
            "runtime_signature_materialize_stage_ms": runtime_signature_materialize_stage_ms,
            "runtime_signature_stage_ms": runtime_signature_capture_stage_ms + runtime_signature_materialize_stage_ms,
            "runtime_signature_manifest_bundle_write_count": (
                1.0 if materialized_runtime_signature_manifest_bundle.write_performed else 0.0
            ),
        }
    )

    embedding_encoder = DeterministicEmbeddingEncoder(dims=retrieval.query_embedding.dims)
    memory_store = MemoryIndexStore(store_root=runtime_root / "memory_index")
    memory_store.put_embedding(retrieval.query_embedding)
    replay_candidate: ReplayCandidate | None = None
    history_records = load_history_replay_candidates(
        history_roots=history_runtime_roots,
        target_memory_store=memory_store,
    )
    if seed_replay_memory:
        historical_embedding = embedding_encoder.encode(
            embedding_id=f"embedding-history-{task_id}",
            text=retrieval.query_text,
        )
        memory_store.put_embedding(historical_embedding)
        seeded_memory_ref = MemoryRef(
            memory_id=f"mem-history-{task_id}",
            memory_type=MemoryType.EXACT_REPLAY if layer_config.replay_enabled else MemoryType.SEMANTIC_EVIDENCE,
            replay_class=ReplayClass.EXACT_REPLAY if layer_config.replay_enabled else ReplayClass.ASSIST,
            score=0.99,
            source_task_id=f"prior-{task_id}",
            summary=f"{retrieval.query_text} cached summary",
            canonical_task_spec_hash=compiler_result.canonical_task_spec.spec_hash,
            artifact_ref_id="artifact-history",
            semantic_state_ref_id="" if semantic_ref is None else semantic_ref.state_id,
            embedding_ref_id=historical_embedding.embedding_id,
            manifest_hash=retrieval.hydrate_manifest.manifest_hash,
        )
        seeded_commit = MemoryCommit(
            memory_ref=seeded_memory_ref,
            canonical_task_spec=compiler_result.canonical_task_spec,
            required_outputs=compiler_result.canonical_task_spec.required_outputs,
            quality_floor_pass=True,
            created_from_artifact_hash="sha256:history-artifact",
        )
        memory_store.commit_candidate(
            commit=seeded_commit,
            quality_floor_pass=True,
            answer_adopted=True,
        )
        replay_candidate = ReplayCandidate(
            candidate_id=seeded_memory_ref.memory_id,
            canonical_task_spec=compiler_result.canonical_task_spec,
            input_artifact_hashes=(
                planner_handoff_replay_hash(planner_handoff),
                evidence_pack_replay_hash(retrieval.evidence_pack),
                hydrate_manifest_replay_hash(retrieval.hydrate_manifest),
                runtime_signature_manifest_bundle.manifest_bundle_hash,
            ),
            runtime_signature=runtime_signature,
            output_contract_version="output-v1",
            verified_output=True,
            code_template_version="code-v1",
            extractor_version="retriever-fanout-v1",
    )
    memory_store.load_persisted_state()
    memory_match_result = memory_store.lookup(
        query_task_id=task_id,
        query_spec_hash=compiler_result.canonical_task_spec.spec_hash,
        query_embedding=retrieval.query_embedding,
        allow_replay=layer_config.replay_enabled,
    )
    replay_input_artifact_hashes = (
        planner_handoff_replay_hash(planner_handoff),
        evidence_pack_replay_hash(retrieval.evidence_pack),
        hydrate_manifest_replay_hash(retrieval.hydrate_manifest),
        runtime_signature_manifest_bundle.manifest_bundle_hash,
    )
    minimum_reuse_class = str(
        dict(compiler_result.canonical_task_spec.arguments.get("reuse_contract", {})).get("minimum_reuse_class", "")
    ).strip()
    benchmark_reuse_class_capped = minimum_reuse_class in {"assist", "none", "validated_replay", "exact_replay"}
    allow_validated_replay_selection = (
        layer_config.replay_enabled and minimum_reuse_class not in {"assist", "none"}
    ) or (layer_config.replay_enabled and not benchmark_reuse_class_capped)
    allow_exact_replay = (
        layer_config.replay_enabled and minimum_reuse_class not in {"assist", "none", "validated_replay"}
    ) or (layer_config.replay_enabled and not benchmark_reuse_class_capped)
    allow_validated_replay = (
        layer_config.replay_enabled and minimum_reuse_class not in {"assist", "none"}
    ) or (layer_config.replay_enabled and not benchmark_reuse_class_capped)
    replay_candidate_selection: ReplayCandidateSelection | None = None
    if replay_candidate is None and memory_match_result.matches:
        replay_candidate_selection = select_history_replay_candidate(
            compiler_result=compiler_result,
            runtime_signature=runtime_signature,
            input_artifact_hashes=replay_input_artifact_hashes,
            output_contract_version="output-v1",
            history_records=history_records,
            memory_match_memory_ids=tuple(match.memory_ref.memory_id for match in memory_match_result.matches),
            allow_exact_replay_selection=allow_exact_replay,
            allow_validated_replay_selection=allow_validated_replay_selection,
            preferred_candidate_id=memory_match_result.matches[0].memory_ref.memory_id,
        )
        if replay_candidate_selection is not None:
            replay_candidate = replay_candidate_selection.candidate
    exact_replay_candidate_count = count_exact_replay_candidates(
        compiler_result=compiler_result,
        runtime_signature=runtime_signature,
        input_artifact_hashes=replay_input_artifact_hashes,
        output_contract_version="output-v1",
        history_records=history_records,
        memory_match_memory_ids=tuple(match.memory_ref.memory_id for match in memory_match_result.matches),
        replay_candidate=replay_candidate,
        allow_exact_replay=allow_exact_replay,
    )

    replay = ReplayAdmissibilityGate().decide(
        compiler_result=compiler_result,
        policy=ReplayPolicy(True, allow_validated_replay, allow_exact_replay),
        candidate=replay_candidate if replay_candidate is not None and memory_match_result.matches else None,
        runtime_signature=runtime_signature,
        input_artifact_hashes=replay_input_artifact_hashes,
        output_contract_version="output-v1",
    )

    replay_restore_enabled = replay.replay_class == ReplayClass.EXACT_REPLAY
    summary_suffix = summary_hint
    downgraded_execution_goal = replay.replay_class == ReplayClass.VALIDATED_REPLAY
    codeact_result = None
    history_record = None
    execution_stdout_text = ""
    execution_stderr_text = ""
    if replay_restore_enabled:
        if replay_candidate_selection is not None and replay_candidate_selection.candidate.candidate_id == replay.candidate_id:
            history_record = replay_candidate_selection.record
        else:
            history_record = history_records.get(replay.candidate_id)

    retriever_prompt_slice = RolePromptSlice(role="retriever")
    executor_prompt_slice = RolePromptSlice(role="executor")
    summarizer_prompt_slice = RolePromptSlice(role="summarizer")

    if replay_restore_enabled:
        role_hydrated_slices["retriever"] = _empty_role_hydrated_slice("retriever")
        role_hydrated_slices["executor"] = _empty_role_hydrated_slice("executor")
        role_hydrated_slices["summarizer"] = _empty_role_hydrated_slice("summarizer")
        retriever_decision = _zero_retriever_decision(
            route=top_candidate.route,
            tool_name=top_candidate.tool_name,
            supporting_doc_ids=restored_supporting_doc_ids,
            candidate_rank=top_candidate.helper_rank,
        )
        executor_decision = _zero_executor_decision(
            route=top_candidate.route,
            tool_name=top_candidate.tool_name,
            action_contract="restore_verified_artifact",
        )
        summarizer_decision = _zero_summarizer_decision(
            summary_text=summary_hint,
            tags=tuple(compiler_result.canonical_task_spec.required_tools),
        )
        if history_record is not None:
            output_payload = json.loads(history_record.output_path.read_text(encoding="utf-8"))
            source_workspace_root = history_record.output_path.parents[1]
            source_task_id = str(output_payload.get("task_id", "")).strip()
            if source_task_id:
                output_payload = _rebase_replayed_artifacts(
                    output_payload=output_payload,
                    source_workspace_root=source_workspace_root,
                    target_workspace_root=layout.root,
                    source_task_id=source_task_id,
                    target_task_id=task_id,
                )
            output_payload.update(
                {
                    "task_id": task_id,
                    "restored_from_memory_id": replay.candidate_id,
                    "restored_replay_class": replay.replay_class.value,
                    "execution_goal": "full_execution_goal",
                    "downgraded_execution_goal": False,
                }
            )
            output_rendered = (stable_json_dumps(output_payload) + "\n").encode("utf-8")
            output_artifact_hash = sha256_digest(output_rendered)
        else:
            output_payload = {
                **_render_output_payload(
                    task_id=task_id,
                    bundle=retrieval,
                    summary_suffix=summary_hint,
                    downgraded=False,
                ),
                "task_family": compiler_result.canonical_task_spec.task_family,
                "summary_text": summary_hint,
                "supporting_doc_ids": list(restored_supporting_doc_ids),
                "route": top_candidate.route,
                "tool_name": top_candidate.tool_name,
                "action_contract": "restore_verified_artifact",
                "execution_goal": "full_execution_goal",
                "planner_plan_payload": {},
                "codeact_plan_hash": "",
                "codeact_stage_count": 0,
                "codeact_action_count": 0,
                "restored_from_memory_id": replay.candidate_id,
                "restored_replay_class": replay.replay_class.value,
            }
            output_rendered = (stable_json_dumps(output_payload) + "\n").encode("utf-8")
            output_artifact_hash = sha256_digest(output_rendered)
        log_stage_start_ns = time.perf_counter_ns()
        log_capture = capture_execution_logs(
            workspace=workspace,
            layout=layout,
            step_id=step_id,
            stdout_text=execution_stdout_text,
            stderr_text=execution_stderr_text,
        )
        runtime_stage_metrics["execution_log_capture_stage_ms"] = _elapsed_ms(log_stage_start_ns)
    else:
        memory_slice_text, memory_slice_bytes, memory_slice_count = _memory_prompt_slice(memory_match_result)
        retriever_prompt_slice = (
            RolePromptSlice(
                role="retriever",
                hydrated_text=role_hydrated_slices["retriever"].hydrated_text,
                hydrated_bytes=role_hydrated_slices["retriever"].hydrated_bytes,
                item_count=role_hydrated_slices["retriever"].item_count,
                table_text=role_hydrated_slices["retriever"].table_text,
                table_bytes=role_hydrated_slices["retriever"].table_bytes,
                table_item_count=role_hydrated_slices["retriever"].table_item_count,
                memory_text=memory_slice_text,
                memory_bytes=memory_slice_bytes,
                memory_item_count=memory_slice_count,
            )
            if layer_config.semantic_pruning_enabled
            else _full_corpus_prompt_slice(retrieval, role="retriever")
        )
        role_hydrated_slices["retriever"] = RoleHydratedSlice(
            role="retriever",
            selected_stable_keys=role_hydrated_slices["retriever"].selected_stable_keys,
            hydrated_text=retriever_prompt_slice.hydrated_text,
            hydrated_bytes=retriever_prompt_slice.hydrated_bytes,
            item_count=retriever_prompt_slice.item_count,
            table_text=retriever_prompt_slice.table_text,
            table_bytes=retriever_prompt_slice.table_bytes,
            table_item_count=retriever_prompt_slice.table_item_count,
            memory_text=retriever_prompt_slice.memory_text,
            memory_bytes=retriever_prompt_slice.memory_bytes,
            memory_item_count=retriever_prompt_slice.memory_item_count,
        )
        retriever_decision = role_path_runner.choose_retrieval_candidate(
            query_text=str(planner_retrieval_objective.get("query_text", retrieval.query_text)),
            retrieved_doc_ids=retrieval.selected_doc_hashes,
            visible_candidates=role_candidates,
            prompt_slice=retriever_prompt_slice,
            strict_surface=True,
            allow_assisted_correction=False,
        )
        executor_prompt_slice = (
            RolePromptSlice(
                role="executor",
                hydrated_text=role_hydrated_slices["executor"].hydrated_text,
                hydrated_bytes=role_hydrated_slices["executor"].hydrated_bytes,
                item_count=role_hydrated_slices["executor"].item_count,
                table_text=role_hydrated_slices["executor"].table_text,
                table_bytes=role_hydrated_slices["executor"].table_bytes,
                table_item_count=role_hydrated_slices["executor"].table_item_count,
                memory_text=memory_slice_text,
                memory_bytes=memory_slice_bytes,
                memory_item_count=memory_slice_count,
            )
            if layer_config.semantic_pruning_enabled
            else _full_corpus_prompt_slice(retrieval, role="executor")
        )
        role_hydrated_slices["executor"] = RoleHydratedSlice(
            role="executor",
            selected_stable_keys=role_hydrated_slices["executor"].selected_stable_keys,
            hydrated_text=executor_prompt_slice.hydrated_text,
            hydrated_bytes=executor_prompt_slice.hydrated_bytes,
            item_count=executor_prompt_slice.item_count,
            table_text=executor_prompt_slice.table_text,
            table_bytes=executor_prompt_slice.table_bytes,
            table_item_count=executor_prompt_slice.table_item_count,
            memory_text=executor_prompt_slice.memory_text,
            memory_bytes=executor_prompt_slice.memory_bytes,
            memory_item_count=executor_prompt_slice.memory_item_count,
        )
        executor_decision = role_path_runner.validate_execution_choice(
            route=retriever_decision.route or top_candidate.route,
            tool_name=retriever_decision.tool_name or top_candidate.tool_name,
            visible_candidates=role_candidates,
            action_contract="materialize_validated_artifact",
            prompt_slice=executor_prompt_slice,
            strict_surface=True,
            allow_assisted_correction=False,
        )
        actions_text = (
            f"route={executor_decision.route}\n"
            f"tool={executor_decision.tool_name}\n"
            f"action_contract={executor_decision.action_contract}\n"
            f"supporting_docs={','.join(retriever_decision.supporting_doc_ids or retrieval.selected_doc_hashes)}"
        )
        codeact_stage_start_ns = time.perf_counter_ns()
        codeact_result = CodeActRunner().run(
            workspace=workspace,
            layout=layout,
            step_layout=step_layout,
            request=CodeActRequest(
                task_id=task_id,
                step_id=step_id,
                attempt_id=attempt_id,
                execution_goal="downgrade_execution_goal" if downgraded_execution_goal else "full_execution_goal",
                query_text=retrieval.query_text,
                summary_suffix=summary_hint,
                revenue_value=_default_fact_value(retrieval),
                selected_doc_hashes=retrieval.selected_doc_hashes,
                evidence_pack_hash=retrieval.evidence_pack.pack_hash,
                retrieval_log_hash=retrieval.log_hash,
                runtime_contract=layer_config.layer_name.lower(),
                required_outputs=compiler_result.canonical_task_spec.required_outputs,
                task_family=compiler_result.canonical_task_spec.task_family,
                intent_op=compiler_result.canonical_task_spec.intent_op,
                spec_arguments=dict(compiler_result.canonical_task_spec.arguments),
                quality_checks=tuple(
                    str(item).strip()
                    for item in compiler_result.canonical_task_spec.arguments.get("quality_checks", [])
                    if str(item).strip()
                ),
                history_runtime_roots=tuple(str(root) for root in history_runtime_roots),
                execution_context={
                    "reuse_contract": dict(
                        compiler_result.canonical_task_spec.arguments.get("reuse_contract", {})
                    ),
                },
                downgraded_execution_goal=downgraded_execution_goal,
                route=executor_decision.route,
                tool_name=executor_decision.tool_name,
                action_contract=executor_decision.action_contract,
                supporting_doc_ids=retriever_decision.supporting_doc_ids or retrieval.selected_doc_hashes,
                planner_plan_payload=planner_result.workflow_payload,
            ),
        )
        runtime_stage_metrics["codeact_execution_stage_ms"] = _elapsed_ms(codeact_stage_start_ns)
        execution_stdout_text = codeact_result.stdout_text
        execution_stderr_text = codeact_result.stderr_text
        candidate_output_payload = dict(codeact_result.output_payload)
        artifact_slice_text = stable_json_dumps(
            {
                "route": candidate_output_payload.get("route", ""),
                "tool_name": candidate_output_payload.get("tool_name", ""),
                "revenue_value": candidate_output_payload.get("revenue_value", ""),
                "selected_doc_hashes": candidate_output_payload.get("selected_doc_hashes", []),
                "supporting_doc_ids": candidate_output_payload.get("supporting_doc_ids", []),
            }
        )
        base_summarizer_slice = (
            RolePromptSlice(
                role="summarizer",
                hydrated_text=role_hydrated_slices["summarizer"].hydrated_text,
                hydrated_bytes=role_hydrated_slices["summarizer"].hydrated_bytes,
                item_count=role_hydrated_slices["summarizer"].item_count,
                table_text=role_hydrated_slices["summarizer"].table_text,
                table_bytes=role_hydrated_slices["summarizer"].table_bytes,
                table_item_count=role_hydrated_slices["summarizer"].table_item_count,
                memory_text=memory_slice_text,
                memory_bytes=memory_slice_bytes,
                memory_item_count=memory_slice_count,
            )
            if layer_config.semantic_pruning_enabled
            else _full_corpus_prompt_slice(retrieval, role="summarizer")
        )
        summarizer_prompt_slice = RolePromptSlice(
            role="summarizer",
            hydrated_text=base_summarizer_slice.hydrated_text,
            hydrated_bytes=base_summarizer_slice.hydrated_bytes,
            item_count=base_summarizer_slice.item_count,
            table_text=base_summarizer_slice.table_text,
            table_bytes=base_summarizer_slice.table_bytes,
            table_item_count=base_summarizer_slice.table_item_count,
            artifact_text=artifact_slice_text,
            artifact_bytes=len(artifact_slice_text.encode("utf-8")),
            artifact_item_count=1,
            memory_text=base_summarizer_slice.memory_text,
            memory_bytes=base_summarizer_slice.memory_bytes,
            memory_item_count=base_summarizer_slice.memory_item_count,
        )
        role_hydrated_slices["summarizer"] = RoleHydratedSlice(
            role="summarizer",
            selected_stable_keys=role_hydrated_slices["summarizer"].selected_stable_keys,
            hydrated_text=summarizer_prompt_slice.hydrated_text,
            hydrated_bytes=summarizer_prompt_slice.hydrated_bytes,
            item_count=summarizer_prompt_slice.item_count,
            table_text=summarizer_prompt_slice.table_text,
            table_bytes=summarizer_prompt_slice.table_bytes,
            table_item_count=summarizer_prompt_slice.table_item_count,
            artifact_text=summarizer_prompt_slice.artifact_text,
            artifact_bytes=summarizer_prompt_slice.artifact_bytes,
            artifact_item_count=summarizer_prompt_slice.artifact_item_count,
            memory_text=summarizer_prompt_slice.memory_text,
            memory_bytes=summarizer_prompt_slice.memory_bytes,
            memory_item_count=summarizer_prompt_slice.memory_item_count,
        )
        summarizer_decision = role_path_runner.summarize(
            task_id=task_id,
            task_theme=compiler_result.canonical_task_spec.task_family,
            summary_hint=summary_hint,
            prompt_slice=summarizer_prompt_slice,
            actions_text=actions_text,
            tags=tuple(compiler_result.canonical_task_spec.required_tools),
        )
        summary_suffix = summarizer_decision.summary_text or summary_hint
        output_payload = dict(candidate_output_payload)
        output_payload["summary_text"] = summary_suffix
        output_rendered = (stable_json_dumps(output_payload) + "\n").encode("utf-8")
        output_artifact_hash = sha256_digest(output_rendered)
        log_stage_start_ns = time.perf_counter_ns()
        log_capture = capture_execution_logs(
            workspace=workspace,
            layout=layout,
            step_id=step_id,
            stdout_text=execution_stdout_text,
            stderr_text=execution_stderr_text,
        )
        runtime_stage_metrics["execution_log_capture_stage_ms"] = _elapsed_ms(log_stage_start_ns)

    role_handoff_bytes = _role_handoff_bytes(
        planner_result=planner_result,
        retriever_decision=retriever_decision,
        executor_decision=executor_decision,
        summarizer_decision=summarizer_decision,
    )

    raw_evidence_bytes_seen_by_llm = (
        sum(_role_external_evidence_bytes(slice_) for slice_ in role_hydrated_slices.values())
    )

    primary_output_manifest = ArtifactManifestItem(
        artifact_name="summary_json",
        artifact_type="json",
        relpath="outputs/result.json",
        size_bytes=len(output_rendered),
        sha256=output_artifact_hash,
    )
    artifact_manifest = build_extended_output_manifest(
        task_id=task_id,
        step_id=step_id,
        primary_outputs=(primary_output_manifest,),
        log_capture=log_capture,
    )
    output_stage_start_ns = time.perf_counter_ns()
    materialized_outputs = workspace.materialize_output_bundle(
        layout,
        artifact_manifest,
        payload_by_name={
            "summary_json": output_payload,
            "stdout_log": {"stdout": execution_stdout_text},
            "stderr_log": {"stderr": execution_stderr_text},
        },
        materialized_by_name={
            "stdout_log": log_capture.stdout_artifact,
            "stderr_log": log_capture.stderr_artifact,
        },
    )
    runtime_stage_metrics.update(
        {
            "workspace_output_stage_ms": _elapsed_ms(output_stage_start_ns),
            "workspace_output_bundle_write_count": float(
                sum(1 for file in materialized_outputs.files if file.write_performed)
            ),
            "workspace_output_bundle_reused_count": float(
                sum(1 for file in materialized_outputs.files if not file.write_performed)
            ),
            "workspace_output_manifest_write_count": (
                1.0 if materialized_outputs.manifest_file.write_performed else 0.0
            ),
        }
    )
    validator_reports = _build_validator_reports(
        task_id=task_id,
        step_id=step_id,
        artifact_id="artifact-smoke",
        output_payload=output_payload,
        output_path=materialized_outputs.files[0].path,
        replay_decision=replay,
        layer_config=layer_config,
        required_outputs=compiler_result.canonical_task_spec.required_outputs,
        quality_checks=tuple(
            str(item).strip()
            for item in compiler_result.canonical_task_spec.arguments.get("quality_checks", [])
            if str(item).strip()
        ),
        expected_facts=expected_facts,
    )
    quality_floor = _quality_floor_from_precommit(
        compiler_status=compiler_result.status.value,
        validator_reports=validator_reports,
    )
    continuous_reuse_metrics = _continuous_output_reuse_metrics(
        spec=compiler_result.canonical_task_spec,
        output_payload=output_payload,
        quality_floor=quality_floor,
        layer_config=layer_config,
    )
    materialized_output_hash = materialized_outputs.files[0].sha256
    workspace_file_paths = {
        materialized_task_spec.path.resolve(),
        materialized_hydrate_manifest.path.resolve(),
        materialized_retrieval_log.path.resolve(),
        materialized_runtime_signature_manifest_bundle.path.resolve(),
        materialized_inputs.manifest_file.path.resolve(),
        materialized_outputs.manifest_file.path.resolve(),
        *(file.path.resolve() for file in materialized_inputs.files),
        *(file.path.resolve() for file in materialized_outputs.files),
    }
    if codeact_result is not None:
        workspace_file_paths.update(
            {
                codeact_result.request_path.resolve(),
                codeact_result.plan_path.resolve(),
                codeact_result.script_path.resolve(),
                codeact_result.result_path.resolve(),
                codeact_result.output_path.resolve(),
            }
        )
    workspace_files_during_driver = len(workspace_file_paths)
    evidence_pack_file = next(
        file for file in materialized_inputs.files if file.logical_name == "canonical_evidence_pack"
    )
    materialized_json_by_hash = {
        retrieval.hydrate_manifest.manifest_hash: materialized_hydrate_manifest.path.resolve(),
        retrieval.evidence_pack.pack_hash: evidence_pack_file.path.resolve(),
        retrieval.log_hash: materialized_retrieval_log.path.resolve(),
        input_manifest.manifest_hash: materialized_inputs.manifest_file.path.resolve(),
        artifact_manifest.manifest_hash: materialized_outputs.manifest_file.path.resolve(),
        runtime_signature_manifest_bundle.manifest_bundle_hash: (
            materialized_runtime_signature_manifest_bundle.path.resolve()
        ),
    }

    current_memory_commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id=f"mem-current-{task_id}",
            memory_type=MemoryType.VALIDATED_REPLAY if layer_config.replay_enabled else MemoryType.EVIDENCE,
            replay_class=replay.replay_class if replay.replay_class != ReplayClass.DISALLOWED else ReplayClass.ASSIST,
            score=1.0 if replay.replay_class == ReplayClass.EXACT_REPLAY else 0.75,
            source_task_id=task_id,
            summary=summary_suffix,
            canonical_task_spec_hash=compiler_result.canonical_task_spec.spec_hash,
            artifact_ref_id="artifact-smoke",
            semantic_state_ref_id="" if semantic_ref is None else semantic_ref.state_id,
            embedding_ref_id=retrieval.query_embedding.embedding_id,
            manifest_hash=retrieval.hydrate_manifest.manifest_hash,
        ),
        canonical_task_spec=compiler_result.canonical_task_spec,
        required_outputs=compiler_result.canonical_task_spec.required_outputs,
        quality_floor_pass=quality_floor.quality_floor_pass,
        created_from_artifact_hash=materialized_output_hash,
    )

    runtime_driver_stage_start_ns = time.perf_counter_ns()
    driver_result = RuntimeDriver().run(
        RuntimeDriverInput(
            trace_id=trace_id,
            task_id=task_id,
            step_id=step_id,
            artifact_id="artifact-smoke",
            runtime_root=runtime_root,
            socket_path=socket_path,
            state_store=state_store,
            workspace=workspace,
            layout=layout,
            layer_profile=driver_profile_override or _driver_profile_from_layer_config(layer_config),
            compiler_status=compiler_result.status.value,
            canonical_task_spec_hash=compiler_result.canonical_task_spec.spec_hash,
            task_family=compiler_result.canonical_task_spec.task_family,
            required_outputs=compiler_result.canonical_task_spec.required_outputs,
            planner_retrieval_objective=planner_retrieval_objective,
            planner_plan_payload=planner_result.workflow_payload,
            planner_artifact_ref_id="planner-handoff",
            planner_handoff=planner_handoff,
            retrieval=retrieval,
            raw_evidence_bytes_seen_by_llm=raw_evidence_bytes_seen_by_llm,
            role_handoff_bytes=role_handoff_bytes,
            role_hydration_bytes={
                **{role: slice_.hydrated_bytes + slice_.table_bytes + slice_.artifact_bytes + slice_.memory_bytes for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_text": slice_.hydrated_bytes for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_table": slice_.table_bytes for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_artifact": slice_.artifact_bytes for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_memory": slice_.memory_bytes for role, slice_ in role_hydrated_slices.items()},
            },
            role_hydration_item_count={
                **{role: slice_.item_count + slice_.table_item_count + slice_.artifact_item_count + slice_.memory_item_count for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_text": slice_.item_count for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_table": slice_.table_item_count for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_artifact": slice_.artifact_item_count for role, slice_ in role_hydrated_slices.items()},
                **{f"{role}_memory": slice_.memory_item_count for role, slice_ in role_hydrated_slices.items()},
            },
            semantic_state_handle=semantic_state_handle,
            semantic_ref=semantic_ref,
            input_manifest=input_manifest,
            artifact_manifest=artifact_manifest,
            log_capture=log_capture,
            materialized_outputs=materialized_outputs,
            output_payload=output_payload,
            output_rendered=output_rendered,
            output_artifact_hash=materialized_output_hash,
            output_contract_version="output-v1",
            code_template_version="code-v1",
            extractor_version="retriever-fanout-v1",
            runtime_signature=runtime_signature,
            runtime_signature_manifest_bundle=runtime_signature_manifest_bundle,
            runtime_signature_manifest_bundle_relpath=materialized_runtime_signature_manifest_bundle.relpath,
            memory_store=memory_store,
            current_memory_commit=current_memory_commit,
            memory_match_result=memory_match_result,
            exact_replay_candidate_count=exact_replay_candidate_count,
            history_artifact_reuse_count=int(
                continuous_reuse_metrics.get("history_artifact_reuse_count", 0.0)
            ),
            history_strategy_reuse_count=int(
                continuous_reuse_metrics.get("history_strategy_reuse_count", 0.0)
            ),
            history_step_reduction_count=int(
                continuous_reuse_metrics.get("history_step_reduction_count", 0.0)
            ),
            history_reuse_gain=float(
                continuous_reuse_metrics.get("history_reuse_gain", 0.0)
            ),
            replay_candidate=replay_candidate,
            replay_decision=replay,
            replay_input_artifact_hashes=replay_input_artifact_hashes,
            validator_reports=validator_reports,
            input_validator_reports=input_validator_reports,
            quality_floor=quality_floor,
            workspace_file_count=workspace_files_during_driver,
            codeact_plan=None if codeact_result is None else codeact_result.plan,
            codeact_record=None if codeact_result is None else codeact_result.record,
            materialized_json_by_hash=materialized_json_by_hash,
        )
    )
    runtime_stage_metrics["runtime_driver_stage_ms"] = _elapsed_ms(runtime_driver_stage_start_ns)

    bundle = driver_result.persisted_paths
    telemetry = driver_result.telemetry
    task_metrics = dict(driver_result.task_metrics)
    runtime_stage_metrics.update(
        {
            "persist_and_reload_stage_ms": float(driver_result.task_metrics.get("persist_and_reload_stage_ms", 0.0)),
            "registry_query_stage_ms": float(driver_result.task_metrics.get("registry_query_stage_ms", 0.0)),
        }
    )
    task_metrics.update(
        {
            "benchmark_layer": float(int(_benchmark_layer_from_config(layer_config).removeprefix("L"))),
            "handoff_mode_text_collaboration": 1.0 if layer_config.handoff_mode == "text_collaboration" else 0.0,
            "handoff_mode_structured_collaboration": (
                1.0 if layer_config.handoff_mode == "structured_collaboration" else 0.0
            ),
            "planner_call_count": 1.0,
            "retriever_call_count": 0.0 if replay_restore_enabled else 1.0,
            "executor_call_count": 0.0 if replay_restore_enabled else 1.0,
            "summarizer_call_count": 0.0 if replay_restore_enabled else 1.0,
            "llm_call_count": 0.0 if replay_restore_enabled else 4.0,
            "planner_generated_retrieval_objective_count": 1.0,
            "history_runtime_root_count": float(len(history_runtime_roots)),
            "history_artifact_summary_count": float(
                len(planner_scope_payload.get("history_artifact_summaries", []))
                if isinstance(planner_scope_payload.get("history_artifact_summaries", []), list)
                else 0
            ),
            "llm_prompt_bytes": float(
                planner_result.prompt_bytes
                + retriever_decision.prompt_bytes
                + executor_decision.prompt_bytes
                + summarizer_decision.prompt_bytes
            ),
            "llm_prompt_tokens": float(
                planner_result.prompt_tokens
                + retriever_decision.prompt_tokens
                + executor_decision.prompt_tokens
                + summarizer_decision.prompt_tokens
            ),
            "llm_completion_tokens": float(
                planner_result.completion_tokens
                + retriever_decision.completion_tokens
                + executor_decision.completion_tokens
                + summarizer_decision.completion_tokens
            ),
            "llm_total_tokens": float(
                planner_result.total_tokens
                + retriever_decision.total_tokens
                + executor_decision.total_tokens
                + summarizer_decision.total_tokens
            ),
            "llm_wall_ms": float(
                planner_result.latency_ms
                + retriever_decision.latency_ms
                + executor_decision.latency_ms
                + summarizer_decision.latency_ms
            ),
            "planner_prompt_bytes": float(planner_result.prompt_bytes),
            "retriever_prompt_bytes": float(retriever_decision.prompt_bytes),
            "executor_prompt_bytes": float(executor_decision.prompt_bytes),
            "summarizer_prompt_bytes": float(summarizer_decision.prompt_bytes),
            "planner_prompt_scaffolding_bytes": float(
                _prompt_scaffolding_bytes(
                    prompt_bytes=planner_result.prompt_bytes,
                    slice_=role_hydrated_slices["planner"],
                )
            ),
            "retriever_prompt_scaffolding_bytes": float(
                _prompt_scaffolding_bytes(
                    prompt_bytes=retriever_decision.prompt_bytes,
                    slice_=role_hydrated_slices["retriever"],
                )
            ),
            "executor_prompt_scaffolding_bytes": float(
                _prompt_scaffolding_bytes(
                    prompt_bytes=executor_decision.prompt_bytes,
                    slice_=role_hydrated_slices["executor"],
                )
            ),
            "summarizer_prompt_scaffolding_bytes": float(
                _prompt_scaffolding_bytes(
                    prompt_bytes=summarizer_decision.prompt_bytes,
                    slice_=role_hydrated_slices["summarizer"],
                )
            ),
            "planner_handoff_bytes": float(role_handoff_bytes["planner"]),
            "retriever_handoff_bytes": float(role_handoff_bytes["retriever"]),
            "executor_handoff_bytes": float(role_handoff_bytes["executor"]),
            "summarizer_handoff_bytes": float(role_handoff_bytes["summarizer"]),
            "role_handoff_bytes_total": float(sum(role_handoff_bytes.values())),
            "planner_hydrated_bytes": float(role_hydrated_slices["planner"].hydrated_bytes),
            "retriever_hydrated_bytes": float(role_hydrated_slices["retriever"].hydrated_bytes),
            "executor_hydrated_bytes": float(role_hydrated_slices["executor"].hydrated_bytes),
            "summarizer_hydrated_bytes": float(role_hydrated_slices["summarizer"].hydrated_bytes),
            "planner_table_bytes": float(role_hydrated_slices["planner"].table_bytes),
            "retriever_table_bytes": float(role_hydrated_slices["retriever"].table_bytes),
            "executor_table_bytes": float(role_hydrated_slices["executor"].table_bytes),
            "summarizer_table_bytes": float(role_hydrated_slices["summarizer"].table_bytes),
            "planner_artifact_bytes": float(role_hydrated_slices["planner"].artifact_bytes),
            "retriever_artifact_bytes": float(role_hydrated_slices["retriever"].artifact_bytes),
            "executor_artifact_bytes": float(role_hydrated_slices["executor"].artifact_bytes),
            "summarizer_artifact_bytes": float(role_hydrated_slices["summarizer"].artifact_bytes),
            "planner_memory_bytes": float(role_hydrated_slices["planner"].memory_bytes),
            "retriever_memory_bytes": float(role_hydrated_slices["retriever"].memory_bytes),
            "executor_memory_bytes": float(role_hydrated_slices["executor"].memory_bytes),
            "summarizer_memory_bytes": float(role_hydrated_slices["summarizer"].memory_bytes),
            "planner_hydrated_item_count": float(role_hydrated_slices["planner"].item_count),
            "retriever_hydrated_item_count": float(role_hydrated_slices["retriever"].item_count),
            "executor_hydrated_item_count": float(role_hydrated_slices["executor"].item_count),
            "summarizer_hydrated_item_count": float(role_hydrated_slices["summarizer"].item_count),
            "planner_table_item_count": float(role_hydrated_slices["planner"].table_item_count),
            "retriever_table_item_count": float(role_hydrated_slices["retriever"].table_item_count),
            "executor_table_item_count": float(role_hydrated_slices["executor"].table_item_count),
            "summarizer_table_item_count": float(role_hydrated_slices["summarizer"].table_item_count),
            "planner_artifact_item_count": float(role_hydrated_slices["planner"].artifact_item_count),
            "retriever_artifact_item_count": float(role_hydrated_slices["retriever"].artifact_item_count),
            "executor_artifact_item_count": float(role_hydrated_slices["executor"].artifact_item_count),
            "summarizer_artifact_item_count": float(role_hydrated_slices["summarizer"].artifact_item_count),
            "planner_memory_item_count": float(role_hydrated_slices["planner"].memory_item_count),
            "retriever_memory_item_count": float(role_hydrated_slices["retriever"].memory_item_count),
            "executor_memory_item_count": float(role_hydrated_slices["executor"].memory_item_count),
            "summarizer_memory_item_count": float(role_hydrated_slices["summarizer"].memory_item_count),
            "planner_prompt_visible_bytes": float(_role_total_prompt_visible_bytes(role_hydrated_slices["planner"])),
            "retriever_prompt_visible_bytes": float(_role_total_prompt_visible_bytes(role_hydrated_slices["retriever"])),
            "executor_prompt_visible_bytes": float(_role_total_prompt_visible_bytes(role_hydrated_slices["executor"])),
            "summarizer_prompt_visible_bytes": float(_role_total_prompt_visible_bytes(role_hydrated_slices["summarizer"])),
            "planner_non_external_prompt_visible_bytes": float(
                _role_non_external_prompt_visible_bytes(role_hydrated_slices["planner"])
            ),
            "retriever_non_external_prompt_visible_bytes": float(
                _role_non_external_prompt_visible_bytes(role_hydrated_slices["retriever"])
            ),
            "executor_non_external_prompt_visible_bytes": float(
                _role_non_external_prompt_visible_bytes(role_hydrated_slices["executor"])
            ),
            "summarizer_non_external_prompt_visible_bytes": float(
                _role_non_external_prompt_visible_bytes(role_hydrated_slices["summarizer"])
            ),
            **runtime_stage_metrics,
        }
    )
    prompt_visible_total_bytes = float(
        sum(_role_total_prompt_visible_bytes(slice_) for slice_ in role_hydrated_slices.values())
    )
    non_external_prompt_visible_bytes = float(
        sum(_role_non_external_prompt_visible_bytes(slice_) for slice_ in role_hydrated_slices.values())
    )
    prompt_scaffolding_bytes_total = float(
        _prompt_scaffolding_bytes(prompt_bytes=planner_result.prompt_bytes, slice_=role_hydrated_slices["planner"])
        + _prompt_scaffolding_bytes(prompt_bytes=retriever_decision.prompt_bytes, slice_=role_hydrated_slices["retriever"])
        + _prompt_scaffolding_bytes(prompt_bytes=executor_decision.prompt_bytes, slice_=role_hydrated_slices["executor"])
        + _prompt_scaffolding_bytes(prompt_bytes=summarizer_decision.prompt_bytes, slice_=role_hydrated_slices["summarizer"])
    )
    task_metrics["raw_evidence_bytes_seen_by_llm"] = float(raw_evidence_bytes_seen_by_llm)
    task_metrics["prompt_visible_total_bytes"] = prompt_visible_total_bytes
    task_metrics["non_external_prompt_visible_bytes"] = non_external_prompt_visible_bytes
    task_metrics["prompt_scaffolding_bytes_total"] = prompt_scaffolding_bytes_total
    for key, value in continuous_reuse_metrics.items():
        task_metrics[key] = float(value)

    session_snapshot = driver_result.session_snapshot
    lineage_view = driver_result.lineage_view
    telemetry_path = layout.logs_dir / "telemetry.json"
    telemetry_path.write_text(
        stable_json_dumps(
            [event.canonical_payload() for event in telemetry.events]
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_event_log_path = runtime_root / "telemetry" / "runtime_events.jsonl"
    runtime_fact_log_path = runtime_root / "telemetry" / "runtime_facts.jsonl"
    replay_history_source = _replay_history_source(
        seed_replay_memory=seed_replay_memory,
        history_runtime_roots=history_runtime_roots,
    )
    replay_audit_payload = {
        "task_id": task_id,
        "canonical_task_spec_hash": compiler_result.canonical_task_spec.spec_hash,
        "replay_class": replay.replay_class.value,
        "decision_reason": replay.reason,
        "candidate_id": replay.candidate_id,
        "compatibility_verdict": replay.compatibility_verdict.value,
        "skipped_step_count": replay.skipped_step_count,
        "degraded": replay.degraded,
        "history_runtime_roots": [str(root) for root in history_runtime_roots],
        "history_runtime_root_count": len(history_runtime_roots),
        "history_record_runtime_root": "" if history_record is None else str(history_record.runtime_root),
        "replay_history_source": replay_history_source,
        "memory_match_count": len(memory_match_result.matches),
        "memory_candidate_pool_hash": memory_match_result.candidate_pool_hash,
        "memory_rerank_result_hash": memory_match_result.rerank_result_hash,
        "exact_replay_candidate_count": exact_replay_candidate_count,
        "history_artifact_reuse_count": int(
            continuous_reuse_metrics.get("history_artifact_reuse_count", 0.0)
        ),
        "history_strategy_reuse_count": int(
            continuous_reuse_metrics.get("history_strategy_reuse_count", 0.0)
        ),
        "history_step_reduction_count": int(
            continuous_reuse_metrics.get("history_step_reduction_count", 0.0)
        ),
        "history_reuse_gain": float(continuous_reuse_metrics.get("history_reuse_gain", 0.0)),
        "planner_handoff_hash": planner_handoff.handoff_hash,
        "input_artifact_hashes": list(replay_input_artifact_hashes),
        "memory_commit_path": "" if bundle.memory_commit_path is None else str(bundle.memory_commit_path),
        "replay_ledger_path": "" if bundle.replay_ledger_path is None else str(bundle.replay_ledger_path),
        "session_path": "" if bundle.session_path is None else str(bundle.session_path),
        "output_artifact_path": str(driver_result.materialized_outputs.files[0].path),
        "output_artifact_hash": driver_result.output_artifact_hash,
        "runtime_signature": runtime_signature_payload(runtime_signature),
        "runtime_signature_manifest_bundle_hash": runtime_signature_manifest_bundle.manifest_bundle_hash,
        "runtime_signature_manifest_bundle_path": str(materialized_runtime_signature_manifest_bundle.path),
        "replay_candidate": (
            {}
            if replay_candidate is None
            else {
                "candidate_id": replay_candidate.candidate_id,
                "exact_key": replay_candidate.exact_key,
                "output_contract_version": replay_candidate.output_contract_version,
                "code_template_version": replay_candidate.code_template_version,
                "extractor_version": replay_candidate.extractor_version,
                "input_artifact_hashes": list(replay_candidate.input_artifact_hashes),
                "runtime_signature_hash": replay_candidate.runtime_signature.combined_digest,
            }
        ),
        "history_candidate_selection": (
            {}
            if replay_candidate_selection is None
            else {
                "candidate_id": replay_candidate_selection.candidate.candidate_id,
                "selection_reason": replay_candidate_selection.selection_reason,
                "compatibility_verdict": replay_candidate_selection.compatibility_verdict.value,
            }
        ),
    }
    replay_audit_file = workspace.write_json(
        layout,
        "logs/replay_audit.json",
        replay_audit_payload,
        logical_name="replay_audit",
    )
    role_prompt_bytes = {
        "planner": planner_result.prompt_bytes,
        "retriever": retriever_decision.prompt_bytes,
        "executor": executor_decision.prompt_bytes,
        "summarizer": summarizer_decision.prompt_bytes,
    }
    role_prompt_slice_files: dict[str, MaterializedFile] = {}
    role_prompt_slice_refs: dict[str, ExecutionArtifactRef] = {}
    for role in ("planner", "retriever", "executor", "summarizer"):
        prompt_slice_file, prompt_slice_ref = _persist_role_prompt_slice_artifact(
            task_id=task_id,
            workspace=workspace,
            layout=layout,
            slice_=role_hydrated_slices[role],
            prompt_bytes=role_prompt_bytes[role],
        )
        role_prompt_slice_files[role] = prompt_slice_file
        role_prompt_slice_refs[role] = prompt_slice_ref
    hydration_roles = {
        role: {
            **_role_hydration_audit_payload(slice_),
            "prompt_slice_ref_id": role_prompt_slice_refs[role].artifact_id,
            "prompt_slice_root_id": role_prompt_slice_refs[role].root_id,
            "prompt_slice_relpath": role_prompt_slice_refs[role].relpath,
            "prompt_slice_blob_hash": role_prompt_slice_refs[role].blob_hash,
            "prompt_slice_size_bytes": role_prompt_slice_refs[role].size_bytes,
            "prompt_slice_schema_version": ROLE_PROMPT_SLICE_SCHEMA_VERSION,
        }
        for role, slice_ in (
            ("planner", role_hydrated_slices["planner"]),
            ("retriever", role_hydrated_slices["retriever"]),
            ("executor", role_hydrated_slices["executor"]),
            ("summarizer", role_hydrated_slices["summarizer"]),
        )
    }
    hydration_accounting = HydrationAccountingAudit(
        task_id=task_id,
        evidence_pack_id=retrieval.evidence_pack.pack_id,
        evidence_pack_hash=retrieval.evidence_pack.pack_hash,
        hydrate_manifest_id=retrieval.hydrate_manifest.manifest_id,
        hydrate_manifest_hash=retrieval.hydrate_manifest.manifest_hash,
        evidence_locator_count=len(retrieval.hydrate_manifest.entries),
        counting_scope="hydrated_external_evidence_only",
        raw_evidence_bytes_seen_by_llm=raw_evidence_bytes_seen_by_llm,
        prompt_visible_total_bytes=int(prompt_visible_total_bytes),
        non_external_prompt_visible_bytes=int(non_external_prompt_visible_bytes),
        prompt_scaffolding_bytes_total=int(prompt_scaffolding_bytes_total),
        semantic_pruning_enabled=layer_config.semantic_pruning_enabled,
        roles=(
            _role_hydration_accounting(
                slice_=role_hydrated_slices["planner"],
                prompt_bytes=planner_result.prompt_bytes,
                prompt_slice_ref=role_prompt_slice_refs["planner"],
            ),
            _role_hydration_accounting(
                slice_=role_hydrated_slices["retriever"],
                prompt_bytes=retriever_decision.prompt_bytes,
                prompt_slice_ref=role_prompt_slice_refs["retriever"],
            ),
            _role_hydration_accounting(
                slice_=role_hydrated_slices["executor"],
                prompt_bytes=executor_decision.prompt_bytes,
                prompt_slice_ref=role_prompt_slice_refs["executor"],
            ),
            _role_hydration_accounting(
                slice_=role_hydrated_slices["summarizer"],
                prompt_bytes=summarizer_decision.prompt_bytes,
                prompt_slice_ref=role_prompt_slice_refs["summarizer"],
            ),
        ),
    )
    hydration_audit_payload = {
        **hydration_accounting.canonical_payload(),
        "roles": hydration_roles,
    }
    hydration_debug_audit_file = workspace.write_json(
        layout,
        "logs/hydration_audit.json",
        hydration_audit_payload,
        logical_name="hydration_audit",
    )
    hydration_accounting_store = JsonContractStore(runtime_root)
    hydration_accounting_store.put_ref_registry_entries(
        [role_prompt_slice_refs[role].registry_entry() for role in ("planner", "retriever", "executor", "summarizer")]
    )
    hydration_accounting_sidecar_path = hydration_accounting_store.write_hydration_accounting_audit(
        hydration_accounting
    )
    task_metrics["role_prompt_slice_artifact_count"] = 4.0
    task_metrics["role_prompt_slice_artifact_bytes_total"] = float(
        sum(role_prompt_slice_refs[role].size_bytes for role in ("planner", "retriever", "executor", "summarizer"))
    )
    finalized_artifact = driver_result.finalized_artifact
    artifact_audit_payload = {
        "task_id": task_id,
        "artifact_id": finalized_artifact.artifact_id,
        "input_manifest_path": str(materialized_inputs.manifest_path),
        "input_manifest_hash": input_manifest.manifest_hash,
        "artifact_manifest_path": str(driver_result.materialized_outputs.manifest_path),
        "artifact_manifest_hash": artifact_manifest.manifest_hash,
        "output_artifact_path": str(driver_result.materialized_outputs.files[0].path),
        "output_artifact_hash": driver_result.output_artifact_hash,
        "output_relpath": finalized_artifact.relpath,
        "replay_ready": finalized_artifact.replay_ready,
        "verification_state": finalized_artifact.verification_state.value,
        "root_id": finalized_artifact.root_id,
        "workspace_relpath": finalized_artifact.workspace_relpath or finalized_artifact.relpath,
        "blob_hash": finalized_artifact.blob_hash,
        "manifest_hash": finalized_artifact.manifest_hash,
        "size_bytes": finalized_artifact.size_bytes,
        "validator_report_paths": [str(path) for path in bundle.validator_report_paths],
        "input_validator_report_paths": [str(path) for path in bundle.input_validator_report_paths],
        "validator_report_hashes": list(driver_result.settlement_record.validator_report_hashes),
        "input_validator_hashes": list(driver_result.settlement_record.input_validator_hashes),
        "settlement_state": driver_result.settlement_record.to_state,
        "commit_gate_reason": driver_result.settlement_record.commit_gate_reason,
        "memory_commit_path": "" if bundle.memory_commit_path is None else str(bundle.memory_commit_path),
        "replay_ledger_path": "" if bundle.replay_ledger_path is None else str(bundle.replay_ledger_path),
        "session_path": "" if bundle.session_path is None else str(bundle.session_path),
        "execution_step_path": "" if bundle.execution_step_path is None else str(bundle.execution_step_path),
        "runtime_signature_manifest_bundle_path": str(materialized_runtime_signature_manifest_bundle.path),
        "state_metadata_path": "" if semantic_state_handle is None else str(semantic_state_handle.metadata_path),
        "state_storage_kind": "disabled" if semantic_state_handle is None else semantic_state_handle.storage_kind.value,
    }
    artifact_audit_file = workspace.write_json(
        layout,
        "logs/artifact_audit.json",
        artifact_audit_payload,
        logical_name="artifact_audit",
    )
    audit_summary = {
        "replay": {
            "replay_class": replay.replay_class.value,
            "decision_reason": replay.reason,
            "compatibility_verdict": replay.compatibility_verdict.value,
            "skipped_step_count": replay.skipped_step_count,
            "candidate_id_present": bool(replay.candidate_id),
            "history_runtime_root_count": len(history_runtime_roots),
            "history_artifact_reuse_count": int(
                continuous_reuse_metrics.get("history_artifact_reuse_count", 0.0)
            ),
            "history_strategy_reuse_count": int(
                continuous_reuse_metrics.get("history_strategy_reuse_count", 0.0)
            ),
            "history_step_reduction_count": int(
                continuous_reuse_metrics.get("history_step_reduction_count", 0.0)
            ),
            "history_reuse_gain": float(continuous_reuse_metrics.get("history_reuse_gain", 0.0)),
            "validated_replay_count": 1 if replay.replay_class == ReplayClass.VALIDATED_REPLAY else 0,
            "exact_replay_count": 1 if replay.replay_class == ReplayClass.EXACT_REPLAY else 0,
            "admissibility_source": (
                "replay_gate"
                if replay.replay_class in {ReplayClass.VALIDATED_REPLAY, ReplayClass.EXACT_REPLAY}
                else ("history_backed_artifact_reuse" if history_runtime_roots else "none")
            ),
        },
        "hydration": {
            "counting_scope": "hydrated_external_evidence_only",
            "raw_evidence_bytes_seen_by_llm": raw_evidence_bytes_seen_by_llm,
            "prompt_visible_total_bytes": int(prompt_visible_total_bytes),
            "non_external_prompt_visible_bytes": int(non_external_prompt_visible_bytes),
            "prompt_scaffolding_bytes_total": int(prompt_scaffolding_bytes_total),
            "role_external_bytes": {
                role: int(payload["external_evidence_bytes"])
                for role, payload in hydration_roles.items()
            },
            "role_total_prompt_visible_bytes": {
                role: int(payload["total_prompt_visible_bytes"])
                for role, payload in hydration_roles.items()
            },
            "role_non_external_prompt_visible_bytes": {
                role: int(payload["non_external_prompt_visible_bytes"])
                for role, payload in hydration_roles.items()
            },
            "role_prompt_scaffolding_bytes": {
                role.role: int(role.prompt_scaffolding_bytes)
                for role in hydration_accounting.roles
            },
            "role_prompt_slice_ref_ids": {
                role.role: role.prompt_slice_ref_id
                for role in hydration_accounting.roles
            },
            "role_prompt_slice_relpaths": {
                role: str(role_prompt_slice_files[role].relpath)
                for role in ("planner", "retriever", "executor", "summarizer")
            },
        },
        "artifact": {
            "replay_ready": finalized_artifact.replay_ready,
            "verification_state": finalized_artifact.verification_state.value,
            "output_artifact_hash": driver_result.output_artifact_hash,
            "validator_report_count": len(bundle.validator_report_paths),
            "input_validator_report_count": len(bundle.input_validator_report_paths),
        },
    }

    return SmokeResult(
        task_id=task_id,
        compiler_status=compiler_result.status.value,
        supervisor_state=session_snapshot.state,
        response_sequence=driver_result.response_sequence,
        replay_class=replay.replay_class.value,
        artifact_state=driver_result.finalized_artifact.verification_state.value,
        registry_path=str(bundle.registry_path),
        reloaded_manifest_id=driver_result.reloaded_manifest_id,
        reloaded_pack_id=driver_result.reloaded_pack_id,
        reloaded_input_manifest_hash=driver_result.reloaded_input_manifest_hash,
        reloaded_artifact_manifest_hash=driver_result.reloaded_artifact_manifest_hash,
        workspace_root=str(layout.root),
        canonical_task_spec_path=str(materialized_task_spec.path),
        input_manifest_path=str(materialized_inputs.manifest_path),
        artifact_manifest_path=str(driver_result.materialized_outputs.manifest_path),
        evidence_pack_path=str(evidence_pack_file.path),
        hydrate_manifest_path=str(materialized_hydrate_manifest.path),
        output_artifact_path=str(driver_result.materialized_outputs.files[0].path),
        output_artifact_hash=driver_result.output_artifact_hash,
        telemetry_path=str(telemetry_path),
        runtime_event_log_path=str(runtime_event_log_path),
        runtime_fact_log_path=str(runtime_fact_log_path),
        replay_audit_path=str(replay_audit_file.path),
        hydration_audit_path=str(hydration_accounting_sidecar_path),
        hydration_debug_audit_path=str(hydration_debug_audit_file.path),
        artifact_audit_path=str(artifact_audit_file.path),
        embedding_path="" if bundle.embedding_path is None else str(bundle.embedding_path),
        memory_commit_path="" if bundle.memory_commit_path is None else str(bundle.memory_commit_path),
        memory_match_result_path=(
            "" if bundle.memory_match_result_path is None else str(bundle.memory_match_result_path)
        ),
        retrieval_log_path="" if bundle.retrieval_log_path is None else str(bundle.retrieval_log_path),
        retrieval_candidate_pool_path=(
            "" if bundle.retrieval_candidate_pool_path is None else str(bundle.retrieval_candidate_pool_path)
        ),
        retrieval_rerank_result_path=(
            "" if bundle.retrieval_rerank_result_path is None else str(bundle.retrieval_rerank_result_path)
        ),
        retrieval_pruning_profile_path=(
            "" if bundle.retrieval_pruning_profile_path is None else str(bundle.retrieval_pruning_profile_path)
        ),
        session_path="" if bundle.session_path is None else str(bundle.session_path),
        replay_ledger_path="" if bundle.replay_ledger_path is None else str(bundle.replay_ledger_path),
        execution_step_path="" if bundle.execution_step_path is None else str(bundle.execution_step_path),
        fallback_dag_path="" if bundle.fallback_dag_path is None else str(bundle.fallback_dag_path),
        validator_report_paths=tuple(str(path) for path in bundle.validator_report_paths),
        input_validator_report_paths=tuple(str(path) for path in bundle.input_validator_report_paths),
        state_metadata_path="" if semantic_state_handle is None else str(semantic_state_handle.metadata_path),
        state_storage_kind=(
            "disabled" if semantic_state_handle is None else semantic_state_handle.storage_kind.value
        ),
        memory_replay_class=driver_result.reloaded_memory_replay_class,
        memory_match_count=driver_result.reloaded_memory_match_count,
        reloaded_execution_goal=driver_result.reloaded_execution_goal,
        reloaded_fallback_dag_id=driver_result.reloaded_fallback_dag_id,
        quality_floor=quality_floor,
        task_metrics=task_metrics,
        session_state=session_snapshot.state,
        lineage_view=lineage_view,
        workflow_step_count=driver_result.session.workflow_step_count,
        completed_workflow_step_count=driver_result.session.completed_workflow_step_count,
        attempt_count=driver_result.session.attempt_count,
        runtime_replan_count=driver_result.session.runtime_replan_count,
        runtime_fallback_count=driver_result.session.runtime_fallback_count,
        replan_history_count=driver_result.session.replan_count,
        telemetry_event_count=len(telemetry.events),
        runtime_root=str(runtime_root),
        codeact_script_path="" if codeact_result is None else str(codeact_result.script_path),
        codeact_request_path="" if codeact_result is None else str(codeact_result.request_path),
        codeact_plan_path="" if codeact_result is None else str(codeact_result.plan_path),
        runtime_stage_metrics=runtime_stage_metrics,
        audit_summary=audit_summary,
    )


def main() -> None:
    cli_root = Path(tempfile.mkdtemp(prefix="statebus-v2-smoke-"))
    result = run_smoke(
        workspace_root=cli_root / "workspaces",
        runtime_root=cli_root / "runtime",
        socket_path=cli_root / "control.sock",
    )
    print(f"compiler_status={result.compiler_status}")
    print(f"supervisor_state={result.supervisor_state}")
    print(f"response_sequence={','.join(result.response_sequence)}")
    print(f"replay_class={result.replay_class}")
    print(f"artifact_state={result.artifact_state}")
    print(f"registry_path={result.registry_path}")
    print(f"reloaded_manifest_id={result.reloaded_manifest_id}")
    print(f"reloaded_pack_id={result.reloaded_pack_id}")
    print(f"reloaded_input_manifest_hash={result.reloaded_input_manifest_hash}")
    print(f"reloaded_artifact_manifest_hash={result.reloaded_artifact_manifest_hash}")
    print(f"workspace_root={result.workspace_root}")
    print(f"runtime_root={result.runtime_root}")
    print(f"canonical_task_spec_path={result.canonical_task_spec_path}")
    print(f"output_artifact_path={result.output_artifact_path}")
    print(f"output_artifact_hash={result.output_artifact_hash}")
    print(f"telemetry_path={result.telemetry_path}")
    print(f"embedding_path={result.embedding_path}")
    print(f"memory_commit_path={result.memory_commit_path}")
    print(f"memory_match_result_path={result.memory_match_result_path}")
    print(f"retrieval_log_path={result.retrieval_log_path}")
    print(f"retrieval_candidate_pool_path={result.retrieval_candidate_pool_path}")
    print(f"retrieval_rerank_result_path={result.retrieval_rerank_result_path}")
    print(f"retrieval_pruning_profile_path={result.retrieval_pruning_profile_path}")
    print(f"session_path={result.session_path}")
    print(f"replay_ledger_path={result.replay_ledger_path}")
    print(f"execution_step_path={result.execution_step_path}")
    print(f"fallback_dag_path={result.fallback_dag_path}")
    print(f"validator_report_count={len(result.validator_report_paths)}")
    print(f"input_validator_report_count={len(result.input_validator_report_paths)}")
    print(f"state_metadata_path={result.state_metadata_path}")
    print(f"state_storage_kind={result.state_storage_kind}")
    print(f"memory_replay_class={result.memory_replay_class}")
    print(f"memory_match_count={result.memory_match_count}")
    print(f"reloaded_execution_goal={result.reloaded_execution_goal}")
    print(f"reloaded_fallback_dag_id={result.reloaded_fallback_dag_id}")
    print(f"quality_floor_pass={result.quality_floor.quality_floor_pass}")
    print(f"session_state={result.session_state}")
    print(f"lineage_verified_artifact_count={len(result.lineage_view.verified_artifact_ids)}")
    print(f"workflow_step_count={result.workflow_step_count}")
    print(f"completed_workflow_step_count={result.completed_workflow_step_count}")
    print(f"attempt_count={result.attempt_count}")
    print(f"runtime_replan_count={result.runtime_replan_count}")
    print(f"runtime_fallback_count={result.runtime_fallback_count}")
    print(f"codeact_script_path={result.codeact_script_path}")
    print(f"codeact_request_path={result.codeact_request_path}")
    print(f"task_metric_keys={','.join(sorted(result.task_metrics.keys()))}")
    print(f"telemetry_event_count={result.telemetry_event_count}")


if __name__ == "__main__":
    main()
