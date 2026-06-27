from __future__ import annotations

from pathlib import Path

from v2.benchmark import BenchmarkLayer, BenchmarkRunReport, QualityFloorResult
from v2.contracts import (
    CanonicalTaskSpec,
    CompilerStatus,
    RuntimeCompatibilitySignature,
    StepLifecycleState,
    TaskCompilerInput,
    TaskMode,
)
from v2.runtime import (
    ArtifactLifecycleManager,
    ReplayAdmissibilityGate,
    ReplayCandidate,
    ReplayPolicy,
    RuntimeSupervisor,
    TaskCompiler,
    TelemetryEmitter,
    TelemetryEvent,
    WorkspaceManager,
)
from v2.refs import ExecutionArtifactRef


def _runtime_signature(os_digest: str = "os-a") -> RuntimeCompatibilitySignature:
    return RuntimeCompatibilitySignature(
        os_digest=os_digest,
        python_digest="py-a",
        dependency_digest="dep-a",
        tool_registry_digest="tool-a",
        prompt_bundle_digest="prompt-a",
        extractor_bundle_digest="extract-a",
    )


def test_task_compiler_rejects_benchmark_strict_without_precompiled_spec() -> None:
    compiler = TaskCompiler()
    result = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
        )
    )
    assert result.status == CompilerStatus.REJECTED


def test_replay_gate_distinguishes_exact_validated_and_assist() -> None:
    compiler = TaskCompiler()
    compiled = compiler.compile(
        TaskCompilerInput(
            request_text='{"task_family":"financial_report_analysis","intent_op":"compare_metric","required_outputs":["summary_text"]}',
            task_mode=TaskMode.BENCHMARK_STRICT,
        )
    )
    assert compiled.canonical_task_spec is not None
    candidate = ReplayCandidate(
        candidate_id="cand-1",
        canonical_task_spec=compiled.canonical_task_spec,
        input_artifact_hashes=("input-1",),
        runtime_signature=_runtime_signature(),
        output_contract_version="output-v1",
        verified_output=True,
        code_template_version="code-v1",
        extractor_version="extract-v1",
    )
    gate = ReplayAdmissibilityGate()

    exact = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v1",
    )
    assert exact.replay_class.value == "exact_replay"

    validated = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(os_digest="os-b"),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v1",
    )
    assert validated.replay_class.value == "validated_replay"

    assist = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, False, False),
        candidate=candidate,
        runtime_signature=_runtime_signature(os_digest="os-b"),
        input_artifact_hashes=("other-input",),
        output_contract_version="output-v2",
    )
    assert assist.replay_class.value == "assist"


def test_runtime_supervisor_enforces_lifecycle_transitions() -> None:
    supervisor = RuntimeSupervisor()
    supervisor.register(task_id="task-1", step_id="step-1", attempt_id="a1", role="executor")
    assert supervisor.dispatch("step-1").state == StepLifecycleState.DISPATCHED
    assert supervisor.ack("step-1").state == StepLifecycleState.ACKED
    assert supervisor.run_start("step-1").state == StepLifecycleState.RUNNING
    assert supervisor.complete("step-1").state == StepLifecycleState.COMPLETED
    assert supervisor.gc_pending("step-1").state == StepLifecycleState.GC_PENDING
    assert supervisor.gc_done("step-1").state == StepLifecycleState.GC_DONE


def test_workspace_and_artifact_lifecycle_keep_candidate_verified_invalidated_states() -> None:
    workspace = WorkspaceManager(Path("/statebus/workspaces"))
    layout = workspace.layout_for_task("task-1")
    assert layout.outputs_dir.as_posix().endswith("/task-1/outputs")

    lifecycle = ArtifactLifecycleManager()
    artifact = lifecycle.register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-1",
            task_id="task-1",
            step_id="step-1",
            artifact_type="json",
            root_id="workspace-root",
            relpath="outputs/result.json",
            blob_hash="sha256:artifact",
            size_bytes=42,
            produced_by="executor",
        )
    )
    assert artifact.verification_state.value == "candidate"
    verified = lifecycle.mark_verified("artifact-1")
    assert verified.verification_state.value == "verified"
    invalidated = lifecycle.mark_invalidated("artifact-1")
    assert invalidated.verification_state.value == "invalidated"


def test_telemetry_summary_and_quality_floor_report_are_formal_objects() -> None:
    emitter = TelemetryEmitter()
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="REPLAY_DECIDED",
            metrics={"reuse_gain": 0.25, "skipped_step_count": 2},
        )
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="TASK_SUMMARY_METRICS",
            metrics={"control_bytes": 1024},
        )
    )
    summary = emitter.summarize_task("task-1")
    assert summary["reuse_gain"] == 0.25
    assert summary["control_bytes"] == 1024.0

    report = BenchmarkRunReport(
        layer=BenchmarkLayer.L2,
        task_family="financial_report_analysis",
        quality_floor=QualityFloorResult(
            quality_floor_pass=True,
            deterministic_checks_passed=True,
            fact_coverage_passed=True,
            llm_judge_passed=None,
        ),
        metrics={"latency_ms": 10.0},
    )
    assert report.eligible_for_headline is True

