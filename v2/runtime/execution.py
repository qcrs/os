from __future__ import annotations

from dataclasses import dataclass

from v2.contracts import EXECUTION_STEP_RECORD_SCHEMA_VERSION
from v2.runtime.codeact import CodeActExecutionRecord, CodeActPlan
from v2.runtime.workspace import (
    ArtifactInvalidationRecord,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    ArtifactSettlementRecord,
    ArtifactValidatorReport,
    InputValidatorReport,
    MaterializedFile,
    WorkspaceLayout,
    WorkspaceManager,
)
from v2.utils import compact_json_payload


def _validator_report_audit_payload(report: ArtifactValidatorReport) -> dict[str, object]:
    return compact_json_payload(
        {
        "artifact_id": report.artifact_id,
        "step_id": report.step_id,
        "validation_scope": report.validation_scope,
        "passed": report.passed,
        "fail_reason": report.fail_reason,
        "consumed_by": list(report.consumed_by),
        "metrics": dict(report.metrics),
        "details_hash": report.report_hash,
        "schema_version": report.schema_version,
        }
    )


def _input_validator_report_audit_payload(report: InputValidatorReport) -> dict[str, object]:
    return compact_json_payload(
        {
        "step_id": report.step_id,
        "validation_scope": report.validation_scope,
        "passed": report.passed,
        "fail_reason": report.fail_reason,
        "required_inputs": list(report.required_inputs),
        "observed_inputs": list(report.observed_inputs),
        "metrics": dict(report.metrics),
        "details_hash": report.report_hash,
        "schema_version": report.schema_version,
        }
    )


@dataclass(frozen=True)
class ExecutionLogCapture:
    stdout_preview: str
    stderr_preview: str
    stdout_artifact: MaterializedFile
    stderr_artifact: MaterializedFile
    stdout_truncated: bool
    stderr_truncated: bool


@dataclass(frozen=True)
class ExecutionStepRecord:
    task_id: str
    step_id: str
    attempt_id: str
    workspace_root: str
    execution_goal: str
    exit_code: int
    output_manifest: ArtifactOutputManifest
    log_capture: ExecutionLogCapture
    input_validator_reports: tuple[InputValidatorReport, ...]
    validator_reports: tuple[ArtifactValidatorReport, ...]
    settlement_record: ArtifactSettlementRecord | None = None
    invalidation_record: ArtifactInvalidationRecord | None = None
    invalidation_reasons: tuple[str, ...] = ()
    codeact_plan: CodeActPlan | None = None
    codeact_record: CodeActExecutionRecord | None = None
    schema_version: str = EXECUTION_STEP_RECORD_SCHEMA_VERSION

    @property
    def codeact_plan_audit_relpath(self) -> str:
        if self.codeact_plan is None:
            return ""
        return f"sidecars/codeact_plan_audits/{self.codeact_plan.plan_hash}.json"

    @property
    def codeact_record_audit_relpath(self) -> str:
        if self.codeact_record is None:
            return ""
        return f"sidecars/codeact_record_audits/{self.task_id}.{self.step_id}.{self.attempt_id}.json"

    @property
    def output_manifest_audit_relpath(self) -> str:
        return f"manifests/artifacts/{self.output_manifest.manifest_hash}.json"

    def codeact_plan_audit_detail_payload(self) -> dict[str, object] | None:
        if self.codeact_plan is None:
            return None
        return self.codeact_plan.audit_detail_payload()

    def codeact_record_audit_detail_payload(self) -> dict[str, object] | None:
        if self.codeact_record is None:
            return None
        return self.codeact_record.audit_detail_payload()

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "workspace_root": self.workspace_root,
            "execution_goal": self.execution_goal,
            "exit_code": self.exit_code,
            "output_manifest_hash": self.output_manifest.manifest_hash,
            "output_manifest_relpath": self.output_manifest_audit_relpath,
            "stdout_preview": self.log_capture.stdout_preview,
            "stderr_preview": self.log_capture.stderr_preview,
            "stdout_truncated": self.log_capture.stdout_truncated,
            "stderr_truncated": self.log_capture.stderr_truncated,
            "input_validator_reports": [
                _input_validator_report_audit_payload(report) for report in self.input_validator_reports
            ],
            "validator_reports": [_validator_report_audit_payload(report) for report in self.validator_reports],
            "settlement_record": (
                None
                if self.settlement_record is None
                else {
                    "artifact_id": self.settlement_record.artifact_id,
                    "task_id": self.settlement_record.task_id,
                    "step_id": self.settlement_record.step_id,
                    "from_state": self.settlement_record.from_state,
                    "to_state": self.settlement_record.to_state,
                    "commit_gate_reason": self.settlement_record.commit_gate_reason,
                    "quality_floor_pass": self.settlement_record.quality_floor_pass,
                    "validator_report_hashes": list(self.settlement_record.validator_report_hashes),
                    "input_validator_hashes": list(self.settlement_record.input_validator_hashes),
                    "replay_ready": self.settlement_record.replay_ready,
                    "settlement_hash": self.settlement_record.settlement_hash,
                    "schema_version": self.settlement_record.schema_version,
                }
            ),
            "invalidation_record": (
                None
                if self.invalidation_record is None
                else {
                    "artifact_id": self.invalidation_record.artifact_id,
                    "task_id": self.invalidation_record.task_id,
                    "step_id": self.invalidation_record.step_id,
                    "invalidation_reason": self.invalidation_record.invalidation_reason,
                    "invalidated_from_state": self.invalidation_record.invalidated_from_state,
                    "validator_report_hashes": list(self.invalidation_record.validator_report_hashes),
                    "input_validator_hashes": list(self.invalidation_record.input_validator_hashes),
                    "invalidation_hash": self.invalidation_record.invalidation_hash,
                    "schema_version": self.invalidation_record.schema_version,
                }
            ),
            "invalidation_reasons": list(self.invalidation_reasons),
            "codeact_plan": (
                None
                if self.codeact_plan is None
                else self.codeact_plan.audit_summary_payload(
                    audit_relpath=self.codeact_plan_audit_relpath,
                )
            ),
            "codeact_record": (
                None
                if self.codeact_record is None
                else self.codeact_record.audit_summary_payload(
                    audit_relpath=self.codeact_record_audit_relpath,
                )
            ),
            "schema_version": self.schema_version,
            }
        )


def capture_execution_logs(
    *,
    workspace: WorkspaceManager,
    layout: WorkspaceLayout,
    step_id: str,
    stdout_text: str,
    stderr_text: str,
    capture_limit_bytes: int = 16384,
) -> ExecutionLogCapture:
    stdout_bytes = stdout_text.encode("utf-8")
    stderr_bytes = stderr_text.encode("utf-8")
    stdout_preview = stdout_bytes[:capture_limit_bytes].decode("utf-8", errors="ignore")
    stderr_preview = stderr_bytes[:capture_limit_bytes].decode("utf-8", errors="ignore")
    stdout_artifact = workspace.write_json(
        layout,
        f"logs/{step_id}.stdout.json",
        {"stdout": stdout_text},
        logical_name="stdout_log",
    )
    stderr_artifact = workspace.write_json(
        layout,
        f"logs/{step_id}.stderr.json",
        {"stderr": stderr_text},
        logical_name="stderr_log",
    )
    return ExecutionLogCapture(
        stdout_preview=stdout_preview,
        stderr_preview=stderr_preview,
        stdout_artifact=stdout_artifact,
        stderr_artifact=stderr_artifact,
        stdout_truncated=len(stdout_bytes) > capture_limit_bytes,
        stderr_truncated=len(stderr_bytes) > capture_limit_bytes,
    )


def build_extended_output_manifest(
    *,
    task_id: str,
    step_id: str,
    primary_outputs: tuple[ArtifactManifestItem, ...],
    log_capture: ExecutionLogCapture,
) -> ArtifactOutputManifest:
    return ArtifactOutputManifest(
        task_id=task_id,
        step_id=step_id,
        outputs=primary_outputs
        + (
            ArtifactManifestItem(
                artifact_name="stdout_log",
                artifact_type="json",
                relpath=log_capture.stdout_artifact.relpath,
                size_bytes=log_capture.stdout_artifact.size_bytes,
                sha256=log_capture.stdout_artifact.sha256,
            ),
            ArtifactManifestItem(
                artifact_name="stderr_log",
                artifact_type="json",
                relpath=log_capture.stderr_artifact.relpath,
                size_bytes=log_capture.stderr_artifact.size_bytes,
                sha256=log_capture.stderr_artifact.sha256,
            ),
        ),
    )
