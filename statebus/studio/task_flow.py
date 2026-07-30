from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAX_CASES = 120
MAX_JSON_BYTES = 12 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024


CAPABILITY_EXECUTION_KINDS = {
    "retrieve_table_evidence_v1": "retrieval",
    "retrieve_semantic_evidence_v1": "retrieval",
    "execute_bounded_python_v2": "python",
    "execute_analysis_dsl_v2": "dsl",
    "compose_claim_set_v2": "summary",
    "compose_risk_memo_v1": "summary",
}


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _read_json(path: Path, root: Path) -> dict[str, Any]:
    if not _is_within(path, root):
        return {}
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path, root: Path) -> str:
    if not _is_within(path, root):
        return ""
    try:
        if not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_structured_output(raw: Any) -> Any:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    value = raw.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value[:MAX_TEXT_BYTES]


def _strip_code_fence(source: str) -> str:
    lines = source.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _execution_capability(summary: dict[str, Any]) -> str:
    for capability_id in _list(summary.get("selected_capability_ids")):
        if capability_id in {"execute_bounded_python_v2", "execute_analysis_dsl_v2"}:
            return str(capability_id)
    for step in _list(summary.get("approved_steps")):
        capability_id = _text(_dict(step).get("capability_id"))
        if capability_id in {"execute_bounded_python_v2", "execute_analysis_dsl_v2"}:
            return capability_id
    return ""


def _task_status(summary: dict[str, Any]) -> str:
    if summary.get("ok") is True:
        return "completed"
    if summary.get("ok") is False:
        return "failed"
    return "running"


def _request_text(summary: dict[str, Any], trace: dict[str, Any], task_id: str) -> str:
    direct = _text(summary.get("request_text"))
    if direct:
        return direct
    effective = _dict(trace.get("effective_proposal"))
    for step in _list(summary.get("approved_steps")) or _list(effective.get("steps")):
        goal = _text(_dict(step).get("goal"))
        if not goal:
            continue
        for marker in (" Evidence strategy:", " Analysis strategy:", " Reporting strategy:"):
            if marker in goal:
                return goal.split(marker, 1)[0].strip()
        return goal
    return f"Registered task {task_id}"


def _role_invocations(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row_value in _list(summary.get("role_invocations")):
        row = _dict(row_value)
        role = _text(row.get("role")).lower()
        if not role:
            continue
        attempts = [_dict(item) for item in _list(row.get("attempts"))]
        last = attempts[-1] if attempts else {}
        result[role] = {
            "model": _text(row.get("model_id")) or _text(last.get("model")),
            "attempt_count": len(attempts),
            "prompt_tokens": sum(int(item.get("prompt_tokens", 0) or 0) for item in attempts),
            "completion_tokens": sum(int(item.get("completion_tokens", 0) or 0) for item in attempts),
            "total_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in attempts),
            "output_hash": _text(row.get("raw_output_hash")) or _text(last.get("raw_response_hash")),
            "structured_output": _parse_structured_output(last.get("raw_response")),
        }
    return result


def _runtime_maps(summary: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    workflow_steps = {
        _text(_dict(row).get("step_id")): _dict(row)
        for row in _list(_dict(summary.get("runtime_session")).get("workflow_steps"))
        if _text(_dict(row).get("step_id"))
    }
    dispatches = {
        _text(_dict(row).get("step_id")): _dict(row)
        for row in _list(summary.get("runtime_dispatches"))
        if _text(_dict(row).get("step_id"))
    }
    return workflow_steps, dispatches


def _quality_report(summary: dict[str, Any], capability_id: str) -> dict[str, Any]:
    reports = _list(summary.get("terminal_quality_reports")) or _list(summary.get("quality_reports"))
    for value in reports:
        report = _dict(value)
        if _text(report.get("capability_id")) == capability_id:
            return report
    return {}


def _step_status(workflow: dict[str, Any], summary: dict[str, Any]) -> str:
    state = _text(workflow.get("state")).lower()
    if state:
        return state
    return "completed" if summary.get("ok") is True else "pending"


def _validation_payload(report: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    checks = []
    check_fields = (
        ("schema_passed", "Output schema"),
        ("completion_criteria_passed", "Completion criteria"),
        ("execution_verified", "Execution receipt"),
        ("provenance_passed", "Provenance"),
        ("recomputation_passed", "Recomputation"),
    )
    for key, label in check_fields:
        if key in report:
            checks.append({"id": key, "label": label, "passed": report.get(key) is True})
    verified = report.get("verified") is True if report else _text(workflow.get("state")) == "COMPLETED"
    return {
        "status": "verified" if verified else ("failed" if report else "pending"),
        "validator_id": _text(report.get("validator_id")),
        "checks": checks,
        "error_codes": _list(report.get("error_codes")),
    }


def _planner_step(
    summary: dict[str, Any],
    trace: dict[str, Any],
    invocations: dict[str, dict[str, Any]],
    request_text: str,
) -> dict[str, Any]:
    policy = _dict(summary.get("initial_plan_policy_report")) or _dict(trace.get("effective_policy_report"))
    effective = _dict(trace.get("effective_proposal"))
    approved_steps = _list(summary.get("approved_steps")) or _list(effective.get("steps"))
    invocation = invocations.get("planner", {})
    status = "verified" if _text(policy.get("status")) == "approved" else "pending"
    return {
        "step_id": "planner",
        "role": "planner",
        "status": "completed" if approved_steps else "running",
        "capability_id": "adaptive_plan_policy_v1",
        "execution_kind": "llm_plan",
        "input": {
            "object_type": "CanonicalTaskSpec",
            "summary": request_text,
            "refs": [_text(summary.get("source_ref_id"))] if _text(summary.get("source_ref_id")) else [],
            "data": _dict(summary.get("canonical_task_spec")),
        },
        "transform": {
            "summary": "Model proposes a bounded DAG; the controller validates capabilities, contracts, and Ref wiring.",
            "model": invocation.get("model", ""),
            "usage": {key: invocation.get(key, 0) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "decision_note": _text(effective.get("planner_notes")) or _text(_dict(trace.get("candidate")).get("planner_notes")),
        },
        "output": {
            "object_type": "ApprovedPlan",
            "summary": f"{len(approved_steps)} typed workflow steps approved",
            "refs": [_text(summary.get("approved_plan_hash"))] if _text(summary.get("approved_plan_hash")) else [],
            "hash": _text(summary.get("approved_plan_hash")) or _text(invocation.get("output_hash")),
            "data": {
                "selected_capability_ids": _list(summary.get("selected_capability_ids")),
                "steps": approved_steps,
            },
        },
        "validation": {
            "status": status,
            "validator_id": _text(policy.get("policy_version")) or "statebus.plan_policy.v1",
            "checks": [{"id": "plan_policy", "label": "Plan policy", "passed": status == "verified"}],
            "error_codes": [],
        },
    }


def _runtime_step(
    step: dict[str, Any],
    summary: dict[str, Any],
    invocations: dict[str, dict[str, Any]],
    workflow_steps: dict[str, dict[str, Any]],
    dispatches: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    step_id = _text(step.get("step_id"))
    role = _text(step.get("role")).lower()
    capability_id = _text(step.get("capability_id"))
    workflow = workflow_steps.get(step_id, {})
    dispatch = dispatches.get(step_id, {})
    invocation = invocations.get(role, {})
    report = _quality_report(summary, capability_id)
    execution_records = [_dict(row) for row in _list(summary.get("execution_records"))]
    execution_record = execution_records[-1] if role == "executor" and execution_records else {}
    claims = _list(summary.get("claim_sets")) if role == "summarizer" else []
    retrieval_requests = _list(summary.get("retrieval_requests")) if role == "retriever" else []
    actual = _dict(_dict(summary.get("expected_facts_report")).get("actual")) if role == "executor" else {}

    input_type = {
        "retriever": "EvidenceRequest",
        "executor": "ExecutionArtifactRef + EvidencePack",
        "summarizer": "EvidencePack + ExecutionArtifactRef",
    }.get(role, "Typed input")
    output_type = {
        "retriever": "EvidencePack",
        "executor": "ExecutionArtifactRef",
        "summarizer": "ClaimSet",
    }.get(role, _text(step.get("output_contract_version")) or "Typed output")

    input_refs = [str(value) for value in _list(step.get("input_ref_ids")) if value]
    if role == "executor":
        input_refs = [str(value) for value in _list(execution_record.get("input_ref_ids")) if value] or input_refs
    output_refs = [str(value) for value in _list(dispatch.get("output_refs")) if value]
    output_hash = (
        _text(execution_record.get("output_hash"))
        or _text(report.get("output_artifact_hash"))
        or _text(workflow.get("output_ref_hash"))
    )

    if role == "retriever":
        input_data: Any = retrieval_requests
        output_data: Any = {"evidence_pack_hashes": _list(summary.get("evidence_pack_hashes"))}
        transform_summary = "Generate bounded queries, search the approved corpus, and assemble cited evidence."
    elif role == "executor":
        input_data = {
            "completion_criteria": _dict(step.get("completion_criteria")),
            "required_input_fields": _list(step.get("required_input_fields")),
        }
        output_data = actual or {"artifact_hash": output_hash}
        transform_summary = (
            "Generate policy-bounded Python, pass static checks, and execute it in bwrap."
            if capability_id == "execute_bounded_python_v2"
            else "Generate a bounded Transform DSL program and execute it with the verified interpreter."
        )
    else:
        input_data = {"depends_on": _list(step.get("depends_on"))}
        output_data = claims
        transform_summary = "Compose cited claims from verified evidence and execution artifacts."

    return {
        "step_id": step_id,
        "role": role,
        "status": _step_status(workflow, summary),
        "capability_id": capability_id,
        "execution_kind": CAPABILITY_EXECUTION_KINDS.get(capability_id, "runtime"),
        "input": {
            "object_type": input_type,
            "summary": _text(step.get("goal")),
            "refs": input_refs,
            "data": input_data,
        },
        "transform": {
            "summary": transform_summary,
            "model": invocation.get("model", ""),
            "usage": {key: invocation.get(key, 0) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "structured_output": invocation.get("structured_output", {}),
        },
        "output": {
            "object_type": output_type,
            "summary": _text(step.get("output_contract_version")),
            "refs": output_refs,
            "hash": output_hash,
            "data": output_data,
        },
        "validation": _validation_payload(report, workflow),
    }


def _program_payload(summary: dict[str, Any], case_root: Path, root: Path, invocations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    capability_id = _execution_capability(summary)
    if not capability_id:
        return {"kind": "none", "source": ""}
    report = _quality_report(summary, capability_id)
    execution_records = [_dict(row) for row in _list(summary.get("execution_records"))]
    record = execution_records[-1] if execution_records else {}
    planner_notes = ""
    trace = _read_json(case_root / "planner_trace.json", root)
    planner_notes = _text(_dict(trace.get("effective_proposal")).get("planner_notes"))

    if capability_id == "execute_bounded_python_v2":
        source = _strip_code_fence(_read_text(case_root / "executor_initial_raw.txt", root))
        generations = [_dict(row) for row in _list(summary.get("generation_attempts"))]
        generation = generations[-1] if generations else {}
        return {
            "kind": "python",
            "capability_id": capability_id,
            "model": _text(generation.get("model_id")) or "qwen3-32b",
            "selection_reason": planner_notes,
            "source": source,
            "input_refs": _list(record.get("input_ref_ids")),
            "output_contract": "statebus.analysis_result.v2",
            "policy": {
                "status": "approved" if _text(record.get("policy_report_hash")) and not _list(record.get("validator_errors")) else "unknown",
                "policy_report_hash": _text(record.get("policy_report_hash")),
                "source_hash": _text(record.get("source_hash")),
                "validator_errors": _list(record.get("validator_errors")),
            },
            "sandbox": {
                "requested_backend": _text(record.get("sandbox_requested_backend")),
                "actual_backend": _text(record.get("sandbox_actual_backend")),
                "uid": record.get("sandbox_uid"),
                "gid": record.get("sandbox_gid"),
                "network": "unshared" if _text(record.get("sandbox_actual_backend")) == "bwrap" else "unknown",
                "repository_mounted": False if _text(record.get("sandbox_actual_backend")) == "bwrap" else None,
                "timeout_triggered": record.get("timeout"),
            },
            "result": {
                "exit_code": record.get("exit_code"),
                "artifact_id": _text(record.get("verified_artifact_id")),
                "output_hash": _text(record.get("output_hash")),
                "schema_valid": record.get("output_schema_valid"),
                "quality_valid": record.get("output_quality_valid"),
                "verified": report.get("verified"),
            },
        }

    executor = invocations.get("executor", {})
    structured = executor.get("structured_output", {})
    source = json.dumps(structured, ensure_ascii=False, indent=2) if structured else ""
    return {
        "kind": "dsl",
        "capability_id": capability_id,
        "model": executor.get("model", ""),
        "selection_reason": planner_notes,
        "source": source,
        "input_refs": _list(_dict(structured).get("input_artifact_refs")),
        "output_contract": _text(_dict(structured).get("output_contract_version")),
        "policy": {
            "status": "approved" if report.get("schema_passed") is True else "unknown",
            "validator": "TransformProgramValidator",
            "operation_count": len(_list(_dict(structured).get("operations"))),
        },
        "sandbox": {
            "requested_backend": "verified_interpreter",
            "actual_backend": "Transform DSL interpreter",
            "network": "not_applicable",
        },
        "result": {
            "output_hash": _text(report.get("output_artifact_hash")),
            "schema_valid": report.get("schema_passed"),
            "quality_valid": report.get("completion_criteria_passed"),
            "verified": report.get("verified"),
        },
    }


def _final_answer(summary: dict[str, Any]) -> str:
    claims = []
    for claim_set_value in _list(summary.get("claim_sets")):
        for claim_value in _list(_dict(claim_set_value).get("claims")):
            text = _text(_dict(claim_value).get("claim_text"))
            if text:
                claims.append(text)
    return "\n".join(claims)


def _case_payload(summary: dict[str, Any], trace: dict[str, Any], case_root: Path, root: Path) -> dict[str, Any]:
    effective = _dict(trace.get("effective_proposal"))
    if not summary:
        summary = {
            "task_id": effective.get("task_id", ""),
            "approved_steps": _list(effective.get("steps")),
            "selected_capability_ids": [
                _text(_dict(step).get("capability_id")) for step in _list(effective.get("steps"))
            ],
        }
    task_id = _text(summary.get("task_id")) or _text(effective.get("task_id"))
    request_text = _request_text(summary, trace, task_id)
    invocations = _role_invocations(summary)
    workflow_steps, dispatches = _runtime_maps(summary)
    approved_steps = [_dict(row) for row in _list(summary.get("approved_steps")) or _list(effective.get("steps"))]
    steps = [_planner_step(summary, trace, invocations, request_text)]
    steps.extend(
        _runtime_step(step, summary, invocations, workflow_steps, dispatches)
        for step in approved_steps
    )
    capability_id = _execution_capability(summary)
    quality_reports = _list(summary.get("terminal_quality_reports")) or _list(summary.get("quality_reports"))
    return {
        "task_id": task_id,
        "request_text": request_text,
        "operation": _text(summary.get("operation")) or _text(_dict(summary.get("canonical_task_spec")).get("intent_op")),
        "task_family": _text(summary.get("task_family")) or _text(_dict(summary.get("canonical_task_spec")).get("task_family")),
        "status": _task_status(summary),
        "quality_passed": summary.get("ok") is True and summary.get("system_gate_passed", True) is True,
        "elapsed_ms": summary.get("elapsed_ms"),
        "execution_kind": CAPABILITY_EXECUTION_KINDS.get(capability_id, ""),
        "execution_capability_id": capability_id,
        "model": invocations.get("planner", {}).get("model", ""),
        "usage": _dict(summary.get("usage")),
        "final_answer": _final_answer(summary),
        "steps": steps,
        "generated_program": _program_payload(summary, case_root, root, invocations),
        "evidence": {
            "requests": _list(summary.get("retrieval_requests")),
            "pack_hashes": _list(summary.get("evidence_pack_hashes")),
            "claim_sets": _list(summary.get("claim_sets")),
        },
        "receipts": {
            "dispatches": _list(summary.get("runtime_dispatches")),
            "state_consumption": _list(summary.get("state_consumption_records")),
            "memory_consumption": _list(summary.get("memory_consumption_records")),
            "semantic_state_selections": _dict(summary.get("semantic_state_selections")),
        },
        "quality": {
            "system_gate_passed": summary.get("system_gate_passed"),
            "system_gate_checks": summary.get("system_gate_checks", {}),
            "terminal_reports": quality_reports,
            "expected_facts_report": _dict(summary.get("expected_facts_report")),
            "claim_validation_reports": _dict(summary.get("claim_validation_reports")),
        },
    }


def build_task_flow_index(run_root: Path, task_id: str = "") -> dict[str, Any]:
    root = run_root.resolve()
    if not root.is_dir():
        return {"available": False, "tasks": [], "selected": None}

    discovered: dict[str, tuple[Path | None, Path | None, dict[str, Any], dict[str, Any]]] = {}
    summary_paths = sorted(root.rglob("summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in summary_paths[:MAX_CASES]:
        summary = _read_json(path, root)
        discovered_task_id = _text(summary.get("task_id"))
        if not discovered_task_id or not (
            _list(summary.get("approved_steps")) or _dict(summary.get("canonical_task_spec"))
        ):
            continue
        if discovered_task_id in discovered:
            continue
        trace_path = path.parent / "planner_trace.json"
        trace = _read_json(trace_path, root)
        discovered[discovered_task_id] = (path, trace_path if trace else None, summary, trace)

    trace_paths = sorted(root.rglob("planner_trace.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in trace_paths[:MAX_CASES]:
        trace = _read_json(path, root)
        effective = _dict(trace.get("effective_proposal"))
        discovered_task_id = _text(effective.get("task_id"))
        if not discovered_task_id or discovered_task_id in discovered:
            continue
        discovered[discovered_task_id] = (None, path, {}, trace)

    tasks = []
    for discovered_task_id, (_, _, summary, trace) in discovered.items():
        effective = _dict(trace.get("effective_proposal"))
        effective_summary = summary or {
            "task_id": discovered_task_id,
            "approved_steps": _list(effective.get("steps")),
        }
        capability_id = _execution_capability(effective_summary)
        tasks.append({
            "task_id": discovered_task_id,
            "status": _task_status(summary) if summary else "running",
            "operation": _text(summary.get("operation")) or _text(_dict(summary.get("canonical_task_spec")).get("intent_op")),
            "execution_kind": CAPABILITY_EXECUTION_KINDS.get(capability_id, ""),
            "execution_capability_id": capability_id,
            "quality_passed": summary.get("ok") is True if summary else None,
        })
    tasks.sort(key=lambda row: row["task_id"])

    selected_task_id = task_id if task_id in discovered else (tasks[0]["task_id"] if tasks else "")
    selected = None
    if selected_task_id:
        summary_path, trace_path, summary, trace = discovered[selected_task_id]
        case_path = summary_path or trace_path
        if case_path is not None:
            selected = _case_payload(summary, trace, case_path.parent, root)
    return {
        "available": selected is not None,
        "tasks": tasks,
        "selected_task_id": selected_task_id,
        "selected": selected,
    }
