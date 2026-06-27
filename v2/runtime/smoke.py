from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from v2.control import (
    AckReceived,
    ControlHeader,
    ControlPlaneLoopbackServer,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
    TrapFatal,
)
from v2.contracts import RefKind, RefStatus, RuntimeCompatibilitySignature, StorageKind, TaskCompilerInput, TaskMode
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate, manifest_to_dict
from v2.refs import (
    ExecutionArtifactRef,
    HydrateManifest,
    HydrateManifestEntry,
    SemanticStateRef,
    TextSpanLocator,
)
from v2.runtime import (
    ArtifactLifecycleManager,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    InputManifest,
    InputManifestItem,
    ReplayAdmissibilityGate,
    ReplayCandidate,
    ReplayPolicy,
    RuntimeSupervisor,
    TaskCompiler,
    TaskLineageView,
    TelemetryEmitter,
    TelemetryEvent,
    WorkspaceManager,
    build_task_lineage_view,
)
from v2.state import JsonContractStore, RefRegistryQuery
from v2.utils import sha256_digest, stable_json_dumps


@dataclass(frozen=True)
class SmokeLayerConfig:
    layer_name: str = "L3"
    structured_control_enabled: bool = True
    semantic_pruning_enabled: bool = True
    replay_enabled: bool = True


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
    task_metrics: dict[str, float]
    session_state: str
    lineage_view: TaskLineageView
    telemetry_event_count: int


def run_smoke(
    *,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    request_text: str | None = None,
    task_id: str = "smoke-task",
    layer_config: SmokeLayerConfig | None = None,
) -> SmokeResult:
    layer_config = layer_config or SmokeLayerConfig()
    compiler = TaskCompiler()
    compiler_result = compiler.compile(
        TaskCompilerInput(
            request_text=request_text
            or (
                '{"task_family":"financial_report_analysis","intent_op":"compare_metric",'
                '"required_outputs":["summary_text"],"arguments":{"ticker":"ACME","quarter":"2026Q1"}}'
            ),
            task_mode=TaskMode.BENCHMARK_STRICT,
        )
    )
    if compiler_result.canonical_task_spec is None:
        raise RuntimeError("smoke path requires compiled canonical task spec")

    quarter = str(compiler_result.canonical_task_spec.arguments.get("quarter", "unknown"))
    ticker = str(compiler_result.canonical_task_spec.arguments.get("ticker", "UNKNOWN"))
    normalized_quarter = quarter.lower()

    locator = TextSpanLocator(
        source_doc_hash=f"sha256:doc-{ticker.lower()}-{normalized_quarter}",
        canonical_text_id="chunk-1",
        start_char=0,
        end_char=42,
        extractor_version="chunker-v1",
    )
    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-smoke",
        source_doc_hashes=(f"sha256:doc-{ticker.lower()}-{normalized_quarter}",),
        entries=(
            HydrateManifestEntry(
                row_idx=0,
                stable_key="text_span:smoke",
                byte_hint=42,
                locator=locator,
            ),
        ),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(
        pack_id="pack-smoke",
        task_id=task_id,
        text_candidates=[
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=locator,
                rendered_text=f"Revenue increased for {ticker} in {quarter}.",
                source_name="semantic",
                rank=1,
            )
        ],
        budget_meta={"quality_floor_required": True},
    )
    semantic_ref = None
    if layer_config.semantic_pruning_enabled:
        semantic_ref = SemanticStateRef(
            state_id="state-smoke",
            state_kind="DENSE_SEMANTIC_STATE",
            storage_kind=StorageKind.MMAP_FILE,
            length=128,
            blob_hash="sha256:state-smoke",
            manifest_id=hydrate_manifest.manifest_hash,
            source_doc_hashes=(f"sha256:doc-{ticker.lower()}-{normalized_quarter}",),
        )

    workspace = WorkspaceManager(workspace_root)
    layout = workspace.ensure_layout(task_id)
    materialized_task_spec = workspace.write_json(
        layout,
        "inputs/canonical_task_spec.json",
        compiler_result.canonical_task_spec.canonical_payload(),
        logical_name="canonical_task_spec",
    )

    input_manifest = InputManifest(
        task_id=task_id,
        step_id="step-execute",
        workspace_root=str(layout.root),
        inputs=(
            InputManifestItem(
                name="canonical_evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash=evidence_pack.pack_hash,
                source_ref_id="" if semantic_ref is None else semantic_ref.state_id,
            ),
        ),
    )
    artifacts = ArtifactLifecycleManager()
    output_payload = {
        "task_id": task_id,
        "task_family": compiler_result.canonical_task_spec.task_family,
        "intent_op": compiler_result.canonical_task_spec.intent_op,
        "arguments": dict(sorted(compiler_result.canonical_task_spec.arguments.items())),
        "summary_text": (
            f"ACME {compiler_result.canonical_task_spec.arguments.get('quarter', 'unknown')} "
            f"compare_metric summary ready"
        ),
        "evidence_pack_hash": evidence_pack.pack_hash,
    }
    output_rendered = (json.dumps(output_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    output_artifact_hash = sha256_digest(output_rendered)
    artifact_manifest = ArtifactOutputManifest(
        task_id=task_id,
        step_id="step-execute",
        outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=len(output_rendered),
                sha256=output_artifact_hash,
            ),
        ),
    )
    materialized_inputs = workspace.materialize_input_bundle(
        layout,
        input_manifest,
        payload_by_name={"canonical_evidence_pack": evidence_pack.canonical_payload()},
    )
    materialized_hydrate_manifest = workspace.write_json(
        layout,
        "inputs/hydrate_manifest.json",
        manifest_to_dict(hydrate_manifest),
        logical_name="hydrate_manifest",
    )
    materialized_outputs = workspace.materialize_output_bundle(
        layout,
        artifact_manifest,
        payload_by_name={"summary_json": output_payload},
    )
    artifacts.register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-smoke",
            task_id=task_id,
            step_id="step-execute",
            artifact_type="json",
            root_id="workspace-root",
            relpath="outputs/result.json",
            blob_hash=output_artifact_hash,
            size_bytes=len(output_rendered),
            produced_by="executor",
            manifest_hash=artifact_manifest.manifest_hash,
        )
    )
    verified_artifact = artifacts.mark_verified("artifact-smoke")

    store = JsonContractStore(runtime_root)
    bundle = store.persist_contract_bundle(
        registry_entries=(
            [verified_artifact.registry_entry()]
            if semantic_ref is None
            else [semantic_ref.registry_entry(), verified_artifact.registry_entry()]
        ),
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
    )

    reloaded_artifact_entry = store.get_ref_registry_entry("artifact-smoke")
    reloaded_pack = store.read_evidence_pack(evidence_pack.pack_hash)
    reloaded_input_manifest = store.read_input_manifest(input_manifest.manifest_hash)
    reloaded_artifact_manifest = store.read_artifact_output_manifest(artifact_manifest.manifest_hash)
    reloaded_state_entry = None
    reloaded_manifest = None
    if semantic_ref is not None:
        reloaded_state_entry = store.get_ref_registry_entry("state-smoke")
        reloaded_manifest = store.read_hydrate_manifest(hydrate_manifest.manifest_hash)

    supervisor = RuntimeSupervisor()
    supervisor.register(task_id=task_id, step_id="step-execute", attempt_id="attempt-1", role="executor")
    supervisor.dispatch("step-execute")

    header = ControlHeader(
        trace_id="trace-smoke",
        task_id=task_id,
        step_id="step-execute",
        attempt_id="attempt-1",
        target_role="executor",
        timeout_ms=5000,
        event_type=EventType.REQ_EXEC,
    )
    runtime_contract_tokens = [layer_config.layer_name.lower()]
    if layer_config.replay_enabled:
        runtime_contract_tokens.append("benchmark_strict:exact_replay_allowed")
    if not layer_config.semantic_pruning_enabled:
        runtime_contract_tokens.append("no_semantic_state")
    loopback_message = ExecRequest(
        header=header,
        state_refs=()
        if reloaded_state_entry is None
        else (RefHandle(ref_id=reloaded_state_entry.ref_id, ref_kind="semantic_state"),),
        artifact_refs=(RefHandle(ref_id=reloaded_artifact_entry.ref_id, ref_kind="execution_artifact"),),
        runtime_reuse_contract="|".join(runtime_contract_tokens),
        output_contract_version="output-v1",
        workspace_root=str(layout.root),
        input_manifest_hash=reloaded_input_manifest.manifest_hash,
    )
    responses = ControlPlaneLoopbackServer(socket_path).exchange_sequence(loopback_message)

    telemetry = TelemetryEmitter()
    response_sequence: list[str] = []
    for response in responses:
        response_sequence.append(response.header.event_type.name)
        if isinstance(response, AckReceived):
            supervisor.ack("step-execute")
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id="trace-smoke",
                    task_id=task_id,
                    step_id="step-execute",
                    attempt_id="attempt-1",
                    event_type="STEP_ACKED",
                    role="executor",
                    metrics={"ack_count": 1.0},
                )
            )
        elif isinstance(response, RunStart):
            supervisor.run_start("step-execute")
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id="trace-smoke",
                    task_id=task_id,
                    step_id="step-execute",
                    attempt_id="attempt-1",
                    event_type="STEP_RUNNING",
                    role="executor",
                    metrics={"run_start_count": 1.0},
                )
            )
        elif isinstance(response, Heartbeat):
            supervisor.heartbeat("step-execute")
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id="trace-smoke",
                    task_id=task_id,
                    step_id="step-execute",
                    attempt_id="attempt-1",
                    event_type="STEP_HEARTBEAT",
                    role="executor",
                    payload={"worker_state": response.worker_state},
                    metrics={"heartbeat_count": 1.0},
                )
            )
        elif isinstance(response, SuccessResult):
            if response.artifact_refs[0].ref_id != reloaded_artifact_entry.ref_id:
                raise RuntimeError("worker harness returned unexpected artifact ref")
            if reloaded_artifact_manifest.manifest_hash != artifact_manifest.manifest_hash:
                raise RuntimeError("artifact manifest hash mismatch after disk reload")
            supervisor.complete("step-execute")
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id="trace-smoke",
                    task_id=task_id,
                    step_id="step-execute",
                    attempt_id="attempt-1",
                    event_type="STEP_COMPLETED",
                    role="executor",
                    metrics={
                        "control_bytes": float(len(loopback_message.header.trace_id)),
                        "reuse_gain": 1.0 if layer_config.replay_enabled else 0.0,
                        "output_bytes": float(len(output_rendered)),
                    },
                )
            )
        elif isinstance(response, TrapFatal):
            supervisor.trap("step-execute", response.error_detail)
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id="trace-smoke",
                    task_id=task_id,
                    step_id="step-execute",
                    attempt_id="attempt-1",
                    event_type="STEP_TRAPPED",
                    role="executor",
                    severity="error",
                    payload={"trap_reason": response.trap_reason},
                    metrics={"trap_count": 1.0},
                )
            )
            raise RuntimeError(response.error_detail)

    candidate = ReplayCandidate(
        candidate_id="candidate-smoke",
        canonical_task_spec=compiler_result.canonical_task_spec,
        input_artifact_hashes=("sha256:input-smoke",),
        runtime_signature=RuntimeCompatibilitySignature(
            os_digest="os-a",
            python_digest="py-a",
            dependency_digest="dep-a",
            tool_registry_digest="tool-a",
            prompt_bundle_digest="prompt-a",
            extractor_bundle_digest="extract-a",
        ),
        output_contract_version="output-v1",
        verified_output=True,
        code_template_version="code-v1",
        extractor_version="extract-v1",
    )
    if reloaded_manifest is not None and reloaded_manifest.manifest_id != hydrate_manifest.manifest_id:
        raise RuntimeError("hydrate manifest mismatch after disk reload")
    if reloaded_pack.pack_id != evidence_pack.pack_id:
        raise RuntimeError("evidence pack mismatch after disk reload")
    if reloaded_input_manifest.manifest_hash != input_manifest.manifest_hash:
        raise RuntimeError("input manifest mismatch after disk reload")
    replay = ReplayAdmissibilityGate().decide(
        compiler_result=compiler_result,
        policy=ReplayPolicy(True, layer_config.replay_enabled, layer_config.replay_enabled),
        candidate=candidate,
        runtime_signature=candidate.runtime_signature,
        input_artifact_hashes=("sha256:input-smoke",),
        output_contract_version="output-v1",
    )
    registry_summary = {
        "semantic_state_ref_count": float(
            len(store.query_ref_registry(RefRegistryQuery(ref_kind=RefKind.SEMANTIC_STATE)))
        ),
        "verified_artifact_ref_count": float(
            len(
                store.query_ref_registry(
                    RefRegistryQuery(ref_kind=RefKind.EXECUTION_ARTIFACT, status=RefStatus.VERIFIED)
                )
            )
        ),
    }
    telemetry.emit(
        TelemetryEvent.create(
            trace_id="trace-smoke",
            task_id=task_id,
            step_id="step-execute",
            attempt_id="attempt-1",
            event_type="REPLAY_DECIDED",
            role="runtime_supervisor",
            payload={"replay_class": replay.replay_class.value, "decision_source": replay.reason},
            metrics={
                "skipped_step_count": float(replay.skipped_step_count),
                "reuse_gain": 1.0 if replay.replay_class.value == "exact_replay" else 0.0,
            },
        )
    )

    supervisor.gc_pending("step-execute")
    supervisor.gc_done("step-execute")

    telemetry.emit(
        TelemetryEvent.create(
            trace_id="trace-smoke",
            task_id=task_id,
            event_type="TASK_SUMMARY_METRICS",
            metrics={
                "artifact_count": 1.0,
                "telemetry_events": 1.0,
                "workspace_files": float(
                    len(materialized_inputs.files)
                    + len(materialized_outputs.files)
                    + 4
                ),
                "candidate_artifact_count": 0.0,
                "verified_artifact_count": 1.0,
                "control_message_count": float(len(response_sequence)),
                "semantic_state_transfer_count": 1.0 if layer_config.semantic_pruning_enabled else 0.0,
                "artifact_reuse_count": 1.0 if layer_config.replay_enabled else 0.0,
                "raw_evidence_bytes_seen_by_llm": float(
                    len(evidence_pack.semantic_contexts[0].rendered_text.encode("utf-8"))
                    if layer_config.semantic_pruning_enabled
                    else len(stable_json_dumps(evidence_pack.canonical_payload()).encode("utf-8"))
                ),
                **registry_summary,
            },
        )
    )
    task_metrics = telemetry.summarize_task(task_id)
    session_snapshot = supervisor.snapshot("step-execute")
    lineage_view = build_task_lineage_view(
        task_id=task_id,
        semantic_states=[] if semantic_ref is None else [semantic_ref],
        artifacts=list(artifacts.artifacts.values()),
    )
    telemetry_path = layout.logs_dir / "telemetry.json"
    telemetry_path.write_text(
        json.dumps(
            [
                {
                    "event_id": event.event_id,
                    "trace_id": event.trace_id,
                    "task_id": event.task_id,
                    "step_id": event.step_id,
                    "attempt_id": event.attempt_id,
                    "event_type": event.event_type,
                    "role": event.role,
                    "severity": event.severity,
                    "metrics": dict(event.metrics),
                    "payload": dict(event.payload),
                    "schema_version": event.schema_version,
                }
                for event in telemetry.events
            ],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    return SmokeResult(
        task_id=task_id,
        compiler_status=compiler_result.status.value,
        supervisor_state=supervisor.steps["step-execute"].state.value,
        response_sequence=tuple(response_sequence),
        replay_class=replay.replay_class.value,
        artifact_state=verified_artifact.verification_state.value,
        registry_path=str(bundle.registry_path),
        reloaded_manifest_id="" if reloaded_manifest is None else reloaded_manifest.manifest_id,
        reloaded_pack_id=reloaded_pack.pack_id,
        reloaded_input_manifest_hash=reloaded_input_manifest.manifest_hash,
        reloaded_artifact_manifest_hash=reloaded_artifact_manifest.manifest_hash,
        workspace_root=str(layout.root),
        canonical_task_spec_path=str(materialized_task_spec.path),
        input_manifest_path=str(materialized_inputs.manifest_path),
        artifact_manifest_path=str(materialized_outputs.manifest_path),
        evidence_pack_path=str((layout.root / input_manifest.inputs[0].relpath)),
        hydrate_manifest_path=str(materialized_hydrate_manifest.path),
        output_artifact_path=str(materialized_outputs.files[0].path),
        output_artifact_hash=output_artifact_hash,
        telemetry_path=str(telemetry_path),
        task_metrics=task_metrics,
        session_state=session_snapshot.state,
        lineage_view=lineage_view,
        telemetry_event_count=len(telemetry.events),
    )
def main() -> None:
    result = run_smoke(
        workspace_root=Path("/tmp/statebus-v2-smoke/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-smoke/runtime"),
        socket_path=Path("/tmp/statebus-v2-smoke/control.sock"),
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
    print(f"canonical_task_spec_path={result.canonical_task_spec_path}")
    print(f"output_artifact_path={result.output_artifact_path}")
    print(f"output_artifact_hash={result.output_artifact_hash}")
    print(f"telemetry_path={result.telemetry_path}")
    print(f"session_state={result.session_state}")
    print(f"lineage_verified_artifact_count={len(result.lineage_view.verified_artifact_ids)}")
    print(f"task_metric_keys={','.join(sorted(result.task_metrics.keys()))}")
    print(f"telemetry_event_count={result.telemetry_event_count}")


if __name__ == "__main__":
    main()
