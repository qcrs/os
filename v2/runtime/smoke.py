from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from v2.control import (
    AckReceived,
    ControlHeader,
    ControlPlaneLoopbackServer,
    EventType,
    ExecRequest,
    RefHandle,
    RunStart,
    SuccessResult,
)
from v2.contracts import RuntimeCompatibilitySignature, StorageKind, TaskCompilerInput, TaskMode
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate
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
    TelemetryEmitter,
    TelemetryEvent,
    WorkspaceManager,
)
from v2.state import JsonContractStore


@dataclass(frozen=True)
class SmokeResult:
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
    telemetry_event_count: int


def run_smoke(
    *,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    request_text: str | None = None,
    task_id: str = "smoke-task",
) -> SmokeResult:
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

    locator = TextSpanLocator(
        source_doc_hash="sha256:doc-acme-q1",
        canonical_text_id="chunk-1",
        start_char=0,
        end_char=42,
        extractor_version="chunker-v1",
    )
    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-smoke",
        source_doc_hashes=("sha256:doc-acme-q1",),
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
        task_id="smoke-task",
        text_candidates=[
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=locator,
                rendered_text="Revenue increased for ACME in 2026Q1.",
                source_name="semantic",
                rank=1,
            )
        ],
        budget_meta={"quality_floor_required": True},
    )
    semantic_ref = SemanticStateRef(
        state_id="state-smoke",
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=StorageKind.MMAP_FILE,
        length=128,
        blob_hash="sha256:state-smoke",
        manifest_id=hydrate_manifest.manifest_hash,
        source_doc_hashes=("sha256:doc-acme-q1",),
    )

    workspace = WorkspaceManager(workspace_root)
    layout = workspace.layout_for_task(task_id)
    for directory in (
        layout.root,
        layout.inputs_dir,
        layout.outputs_dir,
        layout.logs_dir,
        layout.tmp_dir,
        layout.script_dir,
        layout.manifest_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

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
                source_ref_id=semantic_ref.state_id,
            ),
        ),
    )
    artifacts = ArtifactLifecycleManager()
    artifact_manifest = ArtifactOutputManifest(
        task_id=task_id,
        step_id="step-execute",
        outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=64,
                sha256="sha256:artifact-smoke",
            ),
        ),
    )
    artifacts.register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-smoke",
            task_id=task_id,
            step_id="step-execute",
            artifact_type="json",
            root_id="workspace-root",
            relpath="outputs/result.json",
            blob_hash="sha256:artifact-smoke",
            size_bytes=64,
            produced_by="executor",
            manifest_hash=artifact_manifest.manifest_hash,
        )
    )
    verified_artifact = artifacts.mark_verified("artifact-smoke")

    store = JsonContractStore(runtime_root)
    bundle = store.persist_contract_bundle(
        registry_entries=[semantic_ref.registry_entry(), verified_artifact.registry_entry()],
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
    )

    (
        reloaded_state_entry,
        reloaded_artifact_entry,
        reloaded_manifest,
        reloaded_pack,
        reloaded_input_manifest,
        reloaded_artifact_manifest,
    ) = (
        store.load_contract_bundle(
            state_ref_id="state-smoke",
            artifact_ref_id="artifact-smoke",
            evidence_pack_hash=evidence_pack.pack_hash,
            input_manifest_hash=input_manifest.manifest_hash,
        )
    )

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
    loopback_message = ExecRequest(
        header=header,
        state_refs=(RefHandle(ref_id=reloaded_state_entry.ref_id, ref_kind="semantic_state"),),
        artifact_refs=(RefHandle(ref_id=reloaded_artifact_entry.ref_id, ref_kind="execution_artifact"),),
        runtime_reuse_contract="benchmark_strict:exact_replay_allowed",
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
                    metrics={"control_bytes": float(len(loopback_message.header.trace_id)), "reuse_gain": 1.0},
                )
            )

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
    if reloaded_manifest.manifest_id != hydrate_manifest.manifest_id:
        raise RuntimeError("hydrate manifest mismatch after disk reload")
    if reloaded_pack.pack_id != evidence_pack.pack_id:
        raise RuntimeError("evidence pack mismatch after disk reload")
    if reloaded_input_manifest.manifest_hash != input_manifest.manifest_hash:
        raise RuntimeError("input manifest mismatch after disk reload")
    replay = ReplayAdmissibilityGate().decide(
        compiler_result=compiler_result,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=candidate.runtime_signature,
        input_artifact_hashes=("sha256:input-smoke",),
        output_contract_version="output-v1",
    )

    supervisor.gc_pending("step-execute")
    supervisor.gc_done("step-execute")

    telemetry.emit(
        TelemetryEvent.create(
            trace_id="trace-smoke",
            task_id=task_id,
            event_type="TASK_SUMMARY_METRICS",
            metrics={"artifact_count": 1.0, "telemetry_events": 1.0},
        )
    )

    return SmokeResult(
        compiler_status=compiler_result.status.value,
        supervisor_state=supervisor.steps["step-execute"].state.value,
        response_sequence=tuple(response_sequence),
        replay_class=replay.replay_class.value,
        artifact_state=verified_artifact.verification_state.value,
        registry_path=str(bundle.registry_path),
        reloaded_manifest_id=reloaded_manifest.manifest_id,
        reloaded_pack_id=reloaded_pack.pack_id,
        reloaded_input_manifest_hash=reloaded_input_manifest.manifest_hash,
        reloaded_artifact_manifest_hash=reloaded_artifact_manifest.manifest_hash,
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
    print(f"telemetry_event_count={result.telemetry_event_count}")


if __name__ == "__main__":
    main()
