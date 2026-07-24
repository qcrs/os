from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from v2.runtime.codeact import CodeActRequest, CodeActRunner
from v2.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from v2.runtime.workspace import WorkspaceManager


def _run_bwrap_smoke() -> dict[str, object]:
    bwrap_path = shutil.which("bwrap")
    if not bwrap_path:
        return {
            "ok": False,
            "reason": "bwrap_not_installed",
        }
    command = [
        bwrap_path,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--chdir",
        "/tmp",
        "/usr/bin/python3",
        "-c",
        "print('bwrap-ok')",
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _run_codeact_bwrap_smoke() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="statebus-codeact-bwrap-") as tmp_dir:
        workspace = WorkspaceManager(Path(tmp_dir) / "workspace")
        layout = workspace.ensure_layout("task-1")
        step_layout = workspace.ensure_step_layout(layout, "step-1")
        try:
            result = CodeActRunner(
                python_executable="/usr/bin/python3",
                sandbox_config=CodeActSandboxConfig(requested_backend="bwrap"),
            ).run(
                workspace=workspace,
                layout=layout,
                step_layout=step_layout,
                request=CodeActRequest(
                    task_id="task-1",
                    step_id="step-1",
                    attempt_id="attempt-1",
                    execution_goal="full_execution_goal",
                    query_text="Compare ACME revenue with the previous quarter",
                    summary_suffix="candidate summary",
                    revenue_value="120",
                    selected_doc_hashes=("sha256:doc-1",),
                    evidence_pack_hash="sha256:pack-1",
                    retrieval_log_hash="sha256:retrieval-1",
                    runtime_contract="l3-fixed-answer-cold-start",
                    required_outputs=("summary_text", "revenue_value"),
                    route="compare_metric",
                    tool_name="table_retriever",
                    action_contract="materialize_validated_artifact",
                    supporting_doc_ids=("doc-1",),
                    planner_plan_payload={"steps": ["retrieve", "execute"]},
                ),
            )
        except Exception as exc:
            return {
                "ok": False,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
        return {
            "ok": result.record.exit_code == 0 and result.record.sandbox_backend == "bwrap",
            "sandbox_requested_backend": result.record.sandbox_requested_backend,
            "sandbox_backend": result.record.sandbox_backend,
            "sandbox_fallback_reason": result.record.sandbox_fallback_reason,
            "exit_code": result.record.exit_code,
            "stdout": result.record.stdout_text,
            "stderr": result.record.stderr_text,
            "output_payload": result.output_payload,
        }


def _run_llm_bwrap_readiness() -> dict[str, object]:
    readiness = CodeActSandboxRunner().check_llm_bwrap_readiness(refresh=True)
    payload = readiness.canonical_payload()
    payload["ok"] = readiness.ready
    payload["readiness_digest"] = readiness.readiness_digest
    return payload


def main() -> None:
    bwrap_smoke = _run_bwrap_smoke()
    codeact_smoke = _run_codeact_bwrap_smoke() if bwrap_smoke.get("ok") else {
        "ok": False,
        "reason": "skipped_because_bwrap_smoke_failed",
    }
    llm_bwrap_readiness = _run_llm_bwrap_readiness()
    payload = {
        "schema_version": "statebus.codeact_bwrap_sandbox_check.v2",
        "ok": (
            bool(bwrap_smoke.get("ok"))
            and bool(codeact_smoke.get("ok"))
            and bool(llm_bwrap_readiness.get("ok"))
        ),
        "bwrap_smoke": bwrap_smoke,
        "codeact_bwrap_smoke": codeact_smoke,
        "llm_bwrap_readiness": llm_bwrap_readiness,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
