from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from v2.contracts import (
    CODEACT_EXECUTION_RECORD_SCHEMA_VERSION,
    CODEACT_PLAN_SCHEMA_VERSION,
    CODEACT_REQUEST_SCHEMA_VERSION,
)
from v2.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from v2.runtime.workspace import StepWorkspaceLayout, WorkspaceLayout, WorkspaceManager
from v2.utils import compact_json_payload, sha256_digest


@dataclass(frozen=True)
class CodeActAction:
    action_id: str
    kind: str
    title: str
    input_relpath: str = ""
    output_relpath: str = ""
    parameters: dict[str, object] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "title": self.title,
            "input_relpath": self.input_relpath,
            "output_relpath": self.output_relpath,
            "parameters": dict(sorted(self.parameters.items())),
        }

    def audit_payload(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "title": self.title,
            "input_relpath": self.input_relpath,
            "output_relpath": self.output_relpath,
            "parameter_keys": sorted(str(key) for key in self.parameters),
            "parameters_hash": sha256_digest(self.parameters),
        }


@dataclass(frozen=True)
class CodeActStage:
    stage_id: str
    title: str
    actions: tuple[CodeActAction, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "title": self.title,
            "actions": [action.canonical_payload() for action in self.actions],
        }

    def audit_payload(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "title": self.title,
            "action_count": len(self.actions),
            "actions": [action.audit_payload() for action in self.actions],
        }


@dataclass(frozen=True)
class CodeActPlan:
    plan_id: str
    task_id: str
    step_id: str
    execution_goal: str
    stages: tuple[CodeActStage, ...]
    schema_version: str = CODEACT_PLAN_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "execution_goal": self.execution_goal,
            "stages": [stage.canonical_payload() for stage in self.stages],
            "schema_version": self.schema_version,
        }

    def audit_payload(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "execution_goal": self.execution_goal,
            "stage_count": self.stage_count,
            "action_count": self.action_count,
            "stages": [stage.audit_payload() for stage in self.stages],
            "plan_hash": self.plan_hash,
            "schema_version": self.schema_version,
        }

    def audit_summary_payload(self, *, audit_relpath: str = "") -> dict[str, object]:
        payload = compact_json_payload(
            {
                "plan_id": self.plan_id,
                "stage_count": self.stage_count,
                "action_count": self.action_count,
                "plan_hash": self.plan_hash,
                "schema_version": self.schema_version,
            }
        )
        if audit_relpath:
            payload["audit_relpath"] = audit_relpath
        return payload

    def audit_detail_payload(self) -> dict[str, object]:
        return {
            "stages": [stage.canonical_payload() for stage in self.stages],
            "schema_version": self.schema_version,
        }

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def action_count(self) -> int:
        return sum(len(stage.actions) for stage in self.stages)

    @property
    def plan_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class CodeActRequest:
    task_id: str
    step_id: str
    attempt_id: str
    execution_goal: str
    query_text: str
    summary_suffix: str
    revenue_value: str
    selected_doc_hashes: tuple[str, ...]
    evidence_pack_hash: str
    retrieval_log_hash: str
    runtime_contract: str
    required_outputs: tuple[str, ...]
    route: str = ""
    tool_name: str = ""
    action_contract: str = ""
    metric_name: str = ""
    metric_value: str = ""
    supporting_doc_ids: tuple[str, ...] = ()
    planner_plan_payload: dict[str, object] = field(default_factory=dict)
    task_family: str = "financial_report_analysis"
    intent_op: str = ""
    spec_arguments: dict[str, object] = field(default_factory=dict)
    quality_checks: tuple[str, ...] = ()
    history_runtime_roots: tuple[str, ...] = ()
    execution_context: dict[str, object] = field(default_factory=dict)
    candidate_output_relpath: str = "tmp/candidate_result.json"
    downgraded_execution_goal: bool = False
    script_name: str = "run_executor.py"
    plan: CodeActPlan | None = None
    schema_version: str = CODEACT_REQUEST_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "execution_goal": self.execution_goal,
            "query_text": self.query_text,
            "summary_suffix": self.summary_suffix,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "revenue_value": self.revenue_value,
            "selected_doc_hashes": list(self.selected_doc_hashes),
            "evidence_pack_hash": self.evidence_pack_hash,
            "retrieval_log_hash": self.retrieval_log_hash,
            "runtime_contract": self.runtime_contract,
            "required_outputs": list(self.required_outputs),
            "route": self.route,
            "tool_name": self.tool_name,
            "action_contract": self.action_contract,
            "supporting_doc_ids": list(self.supporting_doc_ids),
            "planner_plan_payload": dict(sorted(self.planner_plan_payload.items())),
            "task_family": self.task_family,
            "intent_op": self.intent_op,
            "spec_arguments": dict(sorted(self.spec_arguments.items())),
            "quality_checks": list(self.quality_checks),
            "history_runtime_roots": list(self.history_runtime_roots),
            "execution_context": dict(sorted(self.execution_context.items())),
            "candidate_output_relpath": self.candidate_output_relpath,
            "downgraded_execution_goal": self.downgraded_execution_goal,
            "script_name": self.script_name,
            "plan": None if self.plan is None else self.plan.canonical_payload(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CodeActBundle:
    request: CodeActRequest
    plan: CodeActPlan

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request": self.request.canonical_payload(),
            "plan": self.plan.canonical_payload(),
        }


@dataclass(frozen=True)
class CodeActActionResult:
    action_id: str
    kind: str
    ok: bool
    output_relpath: str
    output_hash: str
    metadata: dict[str, object] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "ok": self.ok,
            "output_relpath": self.output_relpath,
            "output_hash": self.output_hash,
            "metadata": dict(sorted(self.metadata.items())),
        }


@dataclass(frozen=True)
class CodeActStageResult:
    stage_id: str
    ok: bool
    action_results: tuple[CodeActActionResult, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "ok": self.ok,
            "action_results": [item.canonical_payload() for item in self.action_results],
        }


@dataclass(frozen=True)
class CodeActExecutionRecord:
    task_id: str
    step_id: str
    attempt_id: str
    execution_goal: str
    script_relpath: str
    request_relpath: str
    output_relpath: str
    plan_relpath: str
    exit_code: int
    stdout_text: str
    stderr_text: str
    output_payload: dict[str, object]
    generated_code_hash: str
    request_hash: str
    plan_hash: str
    stage_results: tuple[CodeActStageResult, ...]
    sandbox_backend: str = "legacy_subprocess"
    sandbox_requested_backend: str = "legacy_subprocess"
    sandbox_fallback_reason: str = ""
    audit_stdout_bytes: int = -1
    audit_stderr_bytes: int = -1
    audit_output_payload_field_names: tuple[str, ...] = ()
    schema_version: str = CODEACT_EXECUTION_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "execution_goal": self.execution_goal,
            "script_relpath": self.script_relpath,
            "request_relpath": self.request_relpath,
            "output_relpath": self.output_relpath,
            "plan_relpath": self.plan_relpath,
            "exit_code": self.exit_code,
            "stdout_text": self.stdout_text,
            "stderr_text": self.stderr_text,
            "output_payload": self.output_payload,
            "generated_code_hash": self.generated_code_hash,
            "request_hash": self.request_hash,
            "plan_hash": self.plan_hash,
            "stage_results": [item.canonical_payload() for item in self.stage_results],
            "sandbox_backend": self.sandbox_backend,
            "sandbox_requested_backend": self.sandbox_requested_backend,
            "sandbox_fallback_reason": self.sandbox_fallback_reason,
            "schema_version": self.schema_version,
        }

    def audit_payload(self) -> dict[str, object]:
        stdout_bytes = self.audit_stdout_bytes
        if stdout_bytes < 0:
            stdout_bytes = len(self.stdout_text.encode("utf-8"))
        stderr_bytes = self.audit_stderr_bytes
        if stderr_bytes < 0:
            stderr_bytes = len(self.stderr_text.encode("utf-8"))
        output_payload_field_names = (
            sorted(str(key) for key in self.audit_output_payload_field_names)
            if self.audit_output_payload_field_names
            else sorted(str(key) for key in self.output_payload)
        )
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "execution_goal": self.execution_goal,
            "script_relpath": self.script_relpath,
            "request_relpath": self.request_relpath,
            "output_relpath": self.output_relpath,
            "plan_relpath": self.plan_relpath,
            "exit_code": self.exit_code,
            "generated_code_hash": self.generated_code_hash,
            "request_hash": self.request_hash,
            "plan_hash": self.plan_hash,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "output_payload_field_names": output_payload_field_names,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_requested_backend": self.sandbox_requested_backend,
            "sandbox_fallback_reason": self.sandbox_fallback_reason,
            "stage_results": [item.canonical_payload() for item in self.stage_results],
            "schema_version": self.schema_version,
        }

    @property
    def stage_count(self) -> int:
        return len(self.stage_results)

    @property
    def action_result_count(self) -> int:
        return sum(len(stage.action_results) for stage in self.stage_results)

    def audit_summary_payload(self, *, audit_relpath: str = "") -> dict[str, object]:
        audit_payload = self.audit_payload()
        payload = compact_json_payload(
            {
                "script_relpath": self.script_relpath,
                "request_relpath": self.request_relpath,
                "output_relpath": self.output_relpath,
                "plan_relpath": self.plan_relpath,
                "exit_code": self.exit_code,
                "generated_code_hash": self.generated_code_hash,
                "request_hash": self.request_hash,
                "plan_hash": self.plan_hash,
                "stdout_bytes": audit_payload["stdout_bytes"],
                "stderr_bytes": audit_payload["stderr_bytes"],
                "output_payload_field_names": audit_payload["output_payload_field_names"],
                "sandbox_backend": self.sandbox_backend,
                "sandbox_requested_backend": self.sandbox_requested_backend,
                "sandbox_fallback_reason": self.sandbox_fallback_reason,
                "stage_count": self.stage_count,
                "action_result_count": self.action_result_count,
                "schema_version": self.schema_version,
            }
        )
        if audit_relpath:
            payload["audit_relpath"] = audit_relpath
        return payload

    def audit_detail_payload(self) -> dict[str, object]:
        return {
            "stage_results": [item.canonical_payload() for item in self.stage_results],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CodeActExecutionResult:
    request: CodeActRequest
    plan: CodeActPlan
    record: CodeActExecutionRecord
    output_payload: dict[str, object]
    output_rendered: bytes
    script_path: Path
    request_path: Path
    plan_path: Path
    result_path: Path
    output_path: Path
    stdout_text: str
    stderr_text: str


@dataclass(frozen=True)
class _CodeActDeterministicCacheEntry:
    script_source: str
    result_payload: dict[str, object]
    output_rendered: bytes
    workspace_artifacts: tuple[tuple[str, bytes], ...]
    stdout_text: str
    stderr_text: str
    generated_code_hash: str
    request_hash: str
    plan_hash: str
    stage_results: tuple[CodeActStageResult, ...]
    sandbox_backend: str
    sandbox_requested_backend: str
    sandbox_fallback_reason: str


@dataclass
class CodeActRunner:
    python_executable: str = sys.executable
    output_name: str = "summary_json"
    sandbox_config: CodeActSandboxConfig | None = None
    _deterministic_cache: dict[str, _CodeActDeterministicCacheEntry] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _sandbox_runner: CodeActSandboxRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sandbox_runner = CodeActSandboxRunner(self.sandbox_config)

    def build_plan(self, *, request: CodeActRequest) -> CodeActPlan:
        if request.plan is not None:
            return request.plan
        if request.downgraded_execution_goal:
            stages = (
                CodeActStage(
                    stage_id="stage-materialize",
                    title="Prepare validated replay execution context",
                    actions=(
                        CodeActAction(
                            action_id="action-prepare-execution-context",
                            kind="prepare_execution_context",
                            title="Prepare replay-aware execution context snapshot",
                            parameters={
                                "route": request.route,
                                "tool_name": request.tool_name,
                                "action_contract": request.action_contract,
                            },
                        ),
                    ),
                ),
                CodeActStage(
                    stage_id="stage-execute",
                    title="Write validated replay candidate execution artifact",
                    actions=(
                        CodeActAction(
                            action_id="action-write-candidate-summary",
                            kind="write_candidate_summary_json",
                            title="Write validated replay candidate summary artifact",
                            output_relpath=request.candidate_output_relpath,
                            parameters={"required_outputs": list(request.required_outputs)},
                        ),
                    ),
                ),
            )
        else:
            stages = (
                CodeActStage(
                    stage_id="stage-materialize",
                    title="Prepare structured execution context",
                    actions=(
                        CodeActAction(
                            action_id="action-prepare-execution-context",
                            kind="prepare_execution_context",
                            title="Prepare execution context snapshot",
                            parameters={
                                "route": request.route,
                                "tool_name": request.tool_name,
                                "action_contract": request.action_contract,
                            },
                        ),
                    ),
                ),
                CodeActStage(
                    stage_id="stage-validate",
                    title="Validate route and workspace contract",
                    actions=(
                        CodeActAction(
                            action_id="action-validate-selection",
                            kind="validate_selection",
                            title="Validate chosen route and tool",
                            parameters={"required_outputs": list(request.required_outputs)},
                        ),
                    ),
                ),
                CodeActStage(
                    stage_id="stage-execute",
                    title="Write candidate execution artifact",
                    actions=(
                        CodeActAction(
                            action_id="action-write-candidate-summary",
                            kind="write_candidate_summary_json",
                            title="Write candidate summary artifact",
                            output_relpath=request.candidate_output_relpath,
                            parameters={"required_outputs": list(request.required_outputs)},
                        ),
                    ),
                ),
            )
        return CodeActPlan(
            plan_id=f"plan-{request.task_id}-{request.step_id}-{request.attempt_id}",
            task_id=request.task_id,
            step_id=request.step_id,
            execution_goal=request.execution_goal,
            stages=stages,
        )

    def run(
        self,
        *,
        workspace: WorkspaceManager,
        layout: WorkspaceLayout,
        step_layout: StepWorkspaceLayout,
        request: CodeActRequest,
    ) -> CodeActExecutionResult:
        del step_layout
        if not request.candidate_output_relpath.startswith("tmp/"):
            raise ValueError(
                f"codeact candidate output must stay under tmp/: {request.candidate_output_relpath}"
            )
        plan = self.build_plan(request=request)
        bundle = CodeActBundle(request=request, plan=plan)
        bundle_relpath = f"inputs/{request.step_id}.{request.attempt_id}.codeact_bundle.json"
        bundle_file = workspace.write_json(
            layout,
            bundle_relpath,
            bundle.canonical_payload(),
            logical_name="codeact_bundle",
        )
        script_relpath = f"script/{request.step_id}.{request.attempt_id}.{request.script_name}"
        result_relpath = f"tmp/{request.step_id}.{request.attempt_id}.codeact_result.json"
        script_path = layout.root / script_relpath
        result_path = layout.root / result_relpath
        cache_key = self._deterministic_cache_key(request=request, plan=plan)
        cache_entry = self._deterministic_cache.get(cache_key)
        if cache_entry is not None:
            return self._materialize_cached_execution(
                layout=layout,
                request=request,
                plan=plan,
                bundle_file=bundle_file.path,
                script_relpath=script_relpath,
                result_relpath=result_relpath,
                cache_entry=cache_entry,
            )
        script_source = self._build_script(
            bundle_relpath=bundle_relpath,
            result_relpath=result_relpath,
        )
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_source, encoding="utf-8")
        project_root = Path(__file__).resolve().parents[2]
        host_env = self._workspace_env(project_root=str(project_root))
        bwrap_env = self._workspace_env(project_root="/sandbox/project")
        sandbox_result = self._sandbox_runner.run(
            host_command=[self.python_executable, str(script_path)],
            bwrap_command=[
                self.python_executable,
                f"/sandbox/workspace/{script_relpath}",
            ],
            cwd=str(layout.root),
            host_env=host_env,
            bwrap_env=bwrap_env,
            workspace_root=layout.root,
            project_root=project_root,
        )
        completed = sandbox_result.completed
        if not result_path.exists():
            raise RuntimeError(
                "codeact result envelope missing: "
                f"{result_path}; exit_code={completed.returncode}; "
                f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
            )
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        output_relpath = str(result_payload.get("output_relpath", request.candidate_output_relpath))
        output_path = layout.root / output_relpath
        if not output_path.exists():
            raise RuntimeError(f"codeact output missing: {output_path}")
        output_rendered = output_path.read_bytes()
        output_payload = json.loads(output_rendered.decode("utf-8"))
        request_hash = sha256_digest(request.canonical_payload())
        stage_results = self._read_stage_results_from_payload(result_payload.get("stage_results", []))
        record = CodeActExecutionRecord(
            task_id=request.task_id,
            step_id=request.step_id,
            attempt_id=request.attempt_id,
            execution_goal=request.execution_goal,
            script_relpath=script_relpath,
            request_relpath=bundle_relpath,
            output_relpath=output_relpath,
            plan_relpath=bundle_relpath,
            exit_code=completed.returncode,
            stdout_text=completed.stdout,
            stderr_text=completed.stderr,
            output_payload=output_payload,
            generated_code_hash=sha256_digest(script_source.encode("utf-8")),
            request_hash=request_hash,
            plan_hash=plan.plan_hash,
            stage_results=stage_results,
            sandbox_backend=sandbox_result.actual_backend,
            sandbox_requested_backend=sandbox_result.requested_backend,
            sandbox_fallback_reason=sandbox_result.fallback_reason,
        )
        result = CodeActExecutionResult(
            request=request,
            plan=plan,
            record=record,
            output_payload=output_payload,
            output_rendered=output_rendered,
            script_path=script_path,
            request_path=bundle_file.path,
            plan_path=bundle_file.path,
            result_path=result_path,
            output_path=output_path,
            stdout_text=completed.stdout,
            stderr_text=completed.stderr,
        )
        if completed.returncode == 0:
            self._deterministic_cache[cache_key] = _CodeActDeterministicCacheEntry(
                script_source=script_source,
                result_payload={
                    "output_relpath": output_relpath,
                    "output_payload": output_payload,
                    "stage_results": [item.canonical_payload() for item in stage_results],
                },
                output_rendered=output_rendered,
                workspace_artifacts=self._workspace_artifacts(layout.root),
                stdout_text=completed.stdout,
                stderr_text=completed.stderr,
                generated_code_hash=record.generated_code_hash,
                request_hash=request_hash,
                plan_hash=plan.plan_hash,
                stage_results=stage_results,
                sandbox_backend=sandbox_result.actual_backend,
                sandbox_requested_backend=sandbox_result.requested_backend,
                sandbox_fallback_reason=sandbox_result.fallback_reason,
            )
        return result

    def _deterministic_cache_key(self, *, request: CodeActRequest, plan: CodeActPlan) -> str:
        return sha256_digest(
            {
                "request": request.canonical_payload(),
                "plan": plan.canonical_payload(),
            }
        )

    def _materialize_cached_execution(
        self,
        *,
        layout: WorkspaceLayout,
        request: CodeActRequest,
        plan: CodeActPlan,
        bundle_file: Path,
        script_relpath: str,
        result_relpath: str,
        cache_entry: _CodeActDeterministicCacheEntry,
    ) -> CodeActExecutionResult:
        script_path = layout.root / script_relpath
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(cache_entry.script_source, encoding="utf-8")

        result_path = layout.root / result_relpath
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                cache_entry.result_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

        output_relpath = str(cache_entry.result_payload.get("output_relpath", request.candidate_output_relpath))
        output_path = layout.root / output_relpath
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(cache_entry.output_rendered)
        for artifact_relpath, artifact_bytes in cache_entry.workspace_artifacts:
            artifact_path = layout.root / artifact_relpath
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(artifact_bytes)
        output_payload = json.loads(cache_entry.output_rendered.decode("utf-8"))
        record = CodeActExecutionRecord(
            task_id=request.task_id,
            step_id=request.step_id,
            attempt_id=request.attempt_id,
            execution_goal=request.execution_goal,
            script_relpath=script_relpath,
            request_relpath=str(bundle_file.relative_to(layout.root)),
            output_relpath=output_relpath,
            plan_relpath=str(bundle_file.relative_to(layout.root)),
            exit_code=0,
            stdout_text=cache_entry.stdout_text,
            stderr_text=cache_entry.stderr_text,
            output_payload=output_payload,
            generated_code_hash=cache_entry.generated_code_hash,
            request_hash=cache_entry.request_hash,
            plan_hash=cache_entry.plan_hash,
            stage_results=cache_entry.stage_results,
            sandbox_backend=cache_entry.sandbox_backend,
            sandbox_requested_backend=cache_entry.sandbox_requested_backend,
            sandbox_fallback_reason=cache_entry.sandbox_fallback_reason,
        )
        return CodeActExecutionResult(
            request=request,
            plan=plan,
            record=record,
            output_payload=output_payload,
            output_rendered=cache_entry.output_rendered,
            script_path=script_path,
            request_path=bundle_file,
            plan_path=bundle_file,
            result_path=result_path,
            output_path=output_path,
            stdout_text=cache_entry.stdout_text,
            stderr_text=cache_entry.stderr_text,
        )

    def _workspace_artifacts(self, root: Path) -> tuple[tuple[str, bytes], ...]:
        outputs_root = root / "outputs"
        if not outputs_root.exists():
            return ()
        artifacts: list[tuple[str, bytes]] = []
        for path in sorted(outputs_root.rglob("*")):
            if not path.is_file():
                continue
            artifacts.append((path.relative_to(root).as_posix(), path.read_bytes()))
        return tuple(artifacts)

    def _workspace_env(self, *, project_root: str) -> dict[str, str]:
        return {
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "STATEBUS_WORKSPACE_ROOT": ".",
            "STATEBUS_INPUT_ROOT": "./inputs",
            "STATEBUS_OUTPUT_ROOT": "./outputs",
            "STATEBUS_TMP_ROOT": "./tmp",
            "STATEBUS_LOG_ROOT": "./logs",
            "STATEBUS_PROJECT_ROOT": project_root,
        }

    def _read_stage_results_from_payload(self, payload: list[dict[str, object]]) -> tuple[CodeActStageResult, ...]:
        return tuple(
            CodeActStageResult(
                stage_id=str(stage["stage_id"]),
                ok=bool(stage["ok"]),
                action_results=tuple(
                    CodeActActionResult(
                        action_id=str(item["action_id"]),
                        kind=str(item["kind"]),
                        ok=bool(item["ok"]),
                        output_relpath=str(item.get("output_relpath", "")),
                        output_hash=str(item.get("output_hash", "")),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in stage.get("action_results", [])
                ),
            )
            for stage in payload
        )

    def _build_script(self, *, bundle_relpath: str, result_relpath: str) -> str:
        return f"""from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
project_root = os.environ.get("STATEBUS_PROJECT_ROOT", "")
if project_root:
    sys.path.insert(0, project_root)
from v2.runtime.codeact_data_tasks import build_candidate_output_payload


def _stable_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _render_bytes(payload: object) -> bytes:
    return (_stable_json(payload) + "\\n").encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


root = Path(os.environ.get("STATEBUS_WORKSPACE_ROOT", "."))
bundle = json.loads((root / {bundle_relpath!r}).read_text(encoding="utf-8"))
request = dict(bundle["request"])
plan = dict(bundle["plan"])
stage_results = []
candidate_output_relpath = ""
candidate_output_payload = {{}}

for stage in plan.get("stages", []):
    action_results = []
    for action in stage.get("actions", []):
        kind = action["kind"]
        output_relpath_local = str(action.get("output_relpath", ""))
        output_hash = ""
        metadata = {{}}
        if kind == "prepare_execution_context":
            execution_context = {{
                "task_id": request["task_id"],
                "route": request.get("route", ""),
                "tool_name": request.get("tool_name", ""),
                "action_contract": request.get("action_contract", ""),
                "supporting_doc_ids": request.get("supporting_doc_ids", []),
                "planner_plan_payload": request.get("planner_plan_payload", {{}}),
                "runtime_contract": request["runtime_contract"],
            }}
            rendered_context = _render_bytes(execution_context)
            output_hash = _sha256_bytes(rendered_context)
            metadata = {{
                "bytes": len(rendered_context),
                "bundle_relpath": {bundle_relpath!r},
                "workspace_env": {{
                    "STATEBUS_INPUT_ROOT": os.environ.get("STATEBUS_INPUT_ROOT", ""),
                    "STATEBUS_OUTPUT_ROOT": os.environ.get("STATEBUS_OUTPUT_ROOT", ""),
                    "STATEBUS_TMP_ROOT": os.environ.get("STATEBUS_TMP_ROOT", ""),
                }},
            }}
        elif kind == "validate_selection":
            route = str(request.get("route", "")).strip()
            tool_name = str(request.get("tool_name", "")).strip()
            action_contract = str(request.get("action_contract", "")).strip()
            ok = bool(route and tool_name and action_contract)
            validation_payload = {{
                "ok": ok,
                "route": route,
                "tool_name": tool_name,
                "action_contract": action_contract,
                "required_outputs": request.get("required_outputs", []),
            }}
            rendered_validation = _render_bytes(validation_payload)
            output_hash = _sha256_bytes(rendered_validation)
            metadata = {{"bytes": len(rendered_validation), "validated": ok}}
            if not ok:
                raise RuntimeError("missing route/tool/action_contract before candidate execution")
        elif kind == "write_candidate_summary_json":
            if str(request.get("task_family", "")) in {
                "continuous_csv_table_analysis",
                "continuous_long_doc_table_analysis",
                "cross_period_financial_analysis",
                "incident_diagnosis_v2",
            }:
                output_payload = build_candidate_output_payload(request, root)
            else:
                output_payload = {{
                    "task_id": request["task_id"],
                    "task_family": "financial_report_analysis",
                    "query_text": request["query_text"],
                    "summary_text": request["summary_suffix"],
                    "metric_name": request.get("metric_name", ""),
                    "metric_value": request.get("metric_value", request.get("revenue_value", "")),
                    "revenue_value": request["revenue_value"],
                    "selected_doc_hashes": request["selected_doc_hashes"],
                    "supporting_doc_ids": request.get("supporting_doc_ids", []),
                    "evidence_pack_hash": request["evidence_pack_hash"],
                    "retrieval_log_hash": request["retrieval_log_hash"],
                    "route": request.get("route", ""),
                    "tool_name": request.get("tool_name", ""),
                    "action_contract": request.get("action_contract", ""),
                    "downgraded_execution_goal": request["downgraded_execution_goal"],
                    "execution_goal": request["execution_goal"],
                    "planner_plan_payload": request.get("planner_plan_payload", {{}}),
                    "codeact_plan_hash": hashlib.sha256(_stable_json(plan).encode("utf-8")).hexdigest(),
                    "codeact_stage_count": len(plan.get("stages", [])),
                    "codeact_action_count": sum(len(stage.get("actions", [])) for stage in plan.get("stages", [])),
                }}
            required_outputs = request.get("required_outputs", [])
            for field_name in required_outputs:
                if not output_payload.get(field_name):
                    raise RuntimeError(f"missing required output field before candidate write: {{field_name}}")
            if not output_payload.get("route") or not output_payload.get("tool_name"):
                raise RuntimeError("missing route/tool before candidate write")
            candidate_output_relpath = str(request.get("candidate_output_relpath", output_relpath_local)).strip()
            if not candidate_output_relpath:
                raise RuntimeError("candidate output relpath missing")
            output_path = root / candidate_output_relpath
            output_path.parent.mkdir(parents=True, exist_ok=True)
            rendered = _render_bytes(output_payload)
            output_path.write_bytes(rendered)
            output_hash = _sha256_bytes(rendered)
            metadata = {{"bytes": len(rendered), "candidate_relpath": candidate_output_relpath}}
            candidate_output_payload = output_payload
        else:
            raise RuntimeError(f"unsupported codeact action kind: {{kind}}")
        action_results.append({{
            "action_id": action["action_id"],
            "kind": kind,
            "ok": True,
            "output_relpath": output_relpath_local or candidate_output_relpath,
            "output_hash": output_hash,
            "metadata": metadata,
        }})
    stage_results.append({{
        "stage_id": stage["stage_id"],
        "ok": all(item["ok"] for item in action_results),
        "action_results": action_results,
    }})

if not candidate_output_relpath:
    raise RuntimeError("candidate summary output missing")

result_path = root / {result_relpath!r}
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(
    _stable_json({{
        "output_relpath": candidate_output_relpath,
        "output_payload": candidate_output_payload,
        "stage_results": stage_results,
    }}) + "\\n",
    encoding="utf-8",
)
print(f"candidate_summary emitted for {{request['task_id']}}")
print(f"runtime_contract={{request['runtime_contract']}}", file=sys.stderr)
"""
