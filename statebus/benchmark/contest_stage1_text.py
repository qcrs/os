"""Four real text agents using a bounded Python tool, no StateRef or Memory.

Only the sandbox/AST primitives are shared with SB. Inter-agent values are
materialized UTF-8 text in the receiver prompt, never out-of-band references.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from statebus.integrations.llm import ChatMessage, LLMConfig, build_llm_client, extract_json_object
from statebus.benchmark.request_journal import with_optional_request_journal, append_event
from statebus.contracts import CodeGenerationPolicy
from statebus.runtime.codeact_sandbox import CodeActSandboxRunner, CodeActSandboxConfig
from statebus.runtime.llm_codeact import (
    audit_generated_source,
    build_code_operation_guidance,
    build_code_repair_guidance,
    extract_python_source,
)
from statebus.benchmark.adaptive_formal import recompute_formal_rows, _rows_equal, _mismatched_row_fields
from statebus.benchmark.contest_metrics import record_handoff
from statebus.utils import stable_json_dumps
from statebus.benchmark.contest_stage1_report import REPORT_INSTRUCTIONS, report_errors, report_feedback, text_statements


EXTENDED_OPERATIONS = frozenset({
    "finance_quarterly_review", "finance_period_delta", "finance_budget_review",
    "finance_budget_status_review", "finance_budget_delta_review",
    "finance_half_year_review", "service_sequence_review", "service_error_delta",
    "service_p95_review", "service_multiweek_review",
})

ROLE_INSTRUCTIONS = {
    "planner": (
        "You are the Planner. Describe only the calculation and evidence-retrieval steps. "
        "Do not write a report, example output, placeholder identifiers or invented results."
    ),
    "retriever": (
        "You are the Retriever. Extract only published note/event facts and their actual entity IDs and "
        "full filename#section locators. Never invent identifiers, metrics, risk flags or risk changes. "
        "The final-report requirements in the task belong to the Summarizer, not you. "
        "A Planner example is not source evidence. Return one concise prose note per actual entity, "
        "preserving its complete source context sentence verbatim, including all uncertainty qualifiers."
    ),
    "executor": (
        "You are the Executor. Return complete Python source using only the authorized tool paths. "
        "Compute metrics and risks from the raw input and public operation contract, never from "
        "the Retriever's opinions. Input rows are NOT pre-aggregated: group by entity AND is_current, "
        "accumulating every required amount/count/latency_sum across ALL rows before calculating ratios. "
        "Never overwrite a group's values with its last row or emit one result per raw row. "
        "Do not write the final prose report."
    ),
    "summarizer": (
        "You are the Summarizer. Return the requested JSON report. The verified Executor table is the "
        "only source for numbers, entity IDs, risk flags, risk_change and source locators. "
        "For each row copy unit_id or site_id as the entity name; set risk to the literal boolean in "
        "the current risk field named in the public report contract; copy risk_change and the COMPLETE note_locator or event_locator "
        "including filename and #section. Do not substitute a bare entity ID for a locator. "
        "Use Retriever text only for the corresponding note/event context, never its risk assertions "
        "or placeholder IDs. Write summary as ONE STRING with newline separators, not an array. "
        "Each line must contain the entity, risk=<boolean>, risk_change=<value>, "
        "source=<full filename#section>, then context. "
        "A prior report flagged by validation is not a template to copy; correct it from the verified table."
    ),
}


def _current_entities(case) -> tuple[str, ...]:
    """Derive output cardinality from the current entities in bound rows."""
    entity_key = "unit_id" if case.operation.startswith("finance_") else "site_id"
    return tuple(sorted({
        str(row[entity_key])
        for row in case.source_rows
        if row.get("is_current") is True and entity_key in row
    }))


def output_matches(case, output):
    if not isinstance(output, list) or not all(isinstance(row, dict) for row in output):
        return False
    for row in output:
        for key, kind in case.output_schema.items():
            value = row.get(key)
            if kind == 'integer' and type(value) is not int:
                return False
            if kind == 'boolean' and type(value) is not bool:
                return False
            if kind == 'string' and not isinstance(value, str):
                return False
            if kind == 'number' and (type(value) not in (int, float) or not math.isfinite(value)):
                return False
    return _rows_equal(tuple(output), recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))


def run_text(case, root: Path, *, notes: str, report_sources: dict, historical_results=(),
             report_instructions=REPORT_INSTRUCTIONS, report_validator=None, source_name: str) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    config = LLMConfig.from_runtime().with_mode("local_vllm")
    config = config.with_provider_override(config.role_config("executor").provider, timeout_s=90, request_max_attempts=1)
    for role in ("planner", "retriever", "executor", "summarizer"):
        config = config.with_role_override(role, json_output=role == "summarizer")
    client = with_optional_request_journal(build_llm_client(config))
    def call(role, prompt, handoffs=(), *, response_schema=None, system_instruction=None):
        for sender, text in handoffs:
            record_handoff(root / "handoffs.jsonl", sender, role, text=text, scope="actual_receiver_text_handoff")
        response = asyncio.run(client.complete([
            ChatMessage(role="system", content=system_instruction or ROLE_INSTRUCTIONS[role]),
            ChatMessage(role="user", content=prompt),
        ], purpose=role, response_schema=response_schema))
        (root / f"{role}-{time.monotonic_ns()}.txt").write_text(response.text)
        if response.finish_reason == "length":
            raise ValueError(f"{role}_truncated")
        return response.text
    task = case.sample.request_text
    plan = call("planner", "Plan this task for a Retriever and a Python-capable Executor. Return concise prose, not results.\n" + task)
    evidence = call("retriever", task + "\nPlanner message:\n" + plan +
                    "\nRead the published notes below. Return a short prose evidence handoff covering every current entity, "
                    "their current-period source filenames and section headings; do not calculate metrics.\n" +
                    ("Published source filename: " + source_name + "\n") + notes,
                    (("planner", plan),))
    policy = CodeGenerationPolicy(capability_id="execute_bounded_python_v2", enabled=True, require_bwrap=True,
                                  allowed_module_roots=("json", "pathlib", "re", "statistics", "collections"),
                                  allowed_input_relpaths=("inputs/task.json",), output_relpath="outputs/result.json",
                                  output_required_fields=tuple(case.output_schema), timeout_seconds=30)
    executor_instruction = ROLE_INSTRUCTIONS["executor"]
    if case.operation in EXTENDED_OPERATIONS:
        executor_instruction = (
            "You are the Executor for a multi-period operation. Return complete Python source using only the "
            "authorized tool paths. The input contains rows from several declared periods. `is_current` is "
            "metadata for output provenance and MUST NOT be used to filter out prior periods or to decide which "
            "rows enter an aggregate. Group by entity and the declared month/week field, aggregate every row "
            "whose period is listed in the public contract, then derive the requested current/prior risk fields. "
            "Never replace the declared period set with only the current period and never emit one row per raw row."
        )
    prompt = (
        "You are the Executor. Generate only complete Python source, with no prose. Your file tool has already read "
        "all released CSVs and joined public SLO and section-locator metadata, without aggregating anything. "
        "Read this top-level JSON row array with Path('inputs/task.json').read_text(); write the final JSON array "
        "using Path('outputs/result.json').write_text(json.dumps(result)). Do not create directories or open other paths. "
        "Use imports only json, pathlib, re, statistics, collections. Do not use open/eval/exec or system/network APIs. "
        "Read numeric JSON values directly; do not use .replace or .strip on numbers. Follow the public contract for threshold sources. "
        "Output one current row per entity, sorted by the declared entity key; do not assume a fixed row count.\n" + task +
        "\nRetriever message:\n" + evidence +
        "\nInput schema:\n" + stable_json_dumps(case.source_schema) +
        "\nPublic operation contract:\n" + stable_json_dumps(case.operation_semantics) +
        "\n" + build_code_operation_guidance(case.operation, case.source_schema) +
        "\nOutput schema:\n" + stable_json_dumps(case.output_schema)
    )
    source = call("executor", prompt, (("retriever", evidence),), system_instruction=executor_instruction)
    tool_records = []
    repairs = {"policy": 0, "runtime": 0, "quality": 0}
    output = None
    while True:
        source = extract_python_source(source)
        audit = audit_generated_source(source, policy)
        errors = list(audit.violations)
        kind = "policy"
        attempt = root / f"tool-{len(tool_records) + 1}"
        attempt.mkdir()
        record = {"attempt": len(tool_records)+1, "policy_passed": audit.passed, "started_ns": time.monotonic_ns()}
        if audit.passed:
            inputs, outputs = attempt / "inputs", attempt / "outputs"
            inputs.mkdir(); outputs.mkdir()
            input_path = inputs / "task.json"
            input_path.write_text(stable_json_dumps(case.source_rows))
            input_path.chmod(0o444); inputs.chmod(0o555); outputs.chmod(0o777)
            program = attempt / "generated.py"
            program.write_text(source); program.chmod(0o444)
            sandbox = CodeActSandboxRunner(replace(CodeActSandboxConfig.from_env(), timeout_seconds=policy.timeout_seconds))
            executed = sandbox.run_llm_bwrap(source_path=program, inputs_dir=inputs, outputs_dir=outputs,
                                             policy_version=policy.sandbox_policy_version)
            record.update(backend=executed.actual_backend, returncode=executed.completed.returncode,
                          sandbox_uid=sandbox.config.sandbox_uid, sandbox_gid=sandbox.config.sandbox_gid,
                          stdout=executed.completed.stdout, stderr=executed.completed.stderr)
            kind = "runtime"
            errors = [] if executed.completed.returncode == 0 else [executed.completed.stderr[-2000:]]
            if not errors:
                kind = "quality"
                path = outputs / "result.json"
                if not path.is_file() or path.is_symlink() or len(list(outputs.iterdir())) != 1:
                    errors = ["missing_or_extra_output"]
                elif path.stat().st_size > policy.max_output_bytes:
                    errors = ["output_byte_budget_exceeded"]
                else:
                    try:
                        output = json.loads(path.read_text())
                    except json.JSONDecodeError:
                        errors = ["invalid_json"]
                    expected_entities = _current_entities(case)
                    if not errors and isinstance(output, list) and len(output) != len(expected_entities):
                        errors = [
                            f"output_row_count:expected={len(expected_entities)},observed={len(output)}; "
                            + ("aggregate all declared periods by entity before emitting one current row per entity"
                               if case.operation in EXTENDED_OPERATIONS else
                               "aggregate all raw rows separately by entity and is_current before emitting one current row per entity")
                        ]
                    if not errors and not output_matches(case, output):
                        errors = ["public_contract_recomputation_mismatch"]
                        if isinstance(output, list) and all(isinstance(row, dict) for row in output):
                            expected = recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows)
                            errors.extend(
                                f"formal_recomputation_field_mismatch:{field}"
                                for field in _mismatched_row_fields(tuple(output), expected)
                            )
        record.update(errors=errors, ended_ns=time.monotonic_ns())
        tool_records.append(record)
        append_event(root / "tool-events.jsonl", record)
        if not errors:
            break
        if repairs[kind] >= 1:
            raise ValueError(f"text_tool_{kind}_failed:{errors}")
        repairs[kind] += 1
        append_event(root / "metric-events.jsonl", {"event": "repair_requested", "kind": kind, "role": "executor"})
        # Share the same typed diagnostics as the SB repair caller. Bare
        # tracebacks/mismatch messages bypass runtime and quality guidance.
        violations = tuple(errors) if kind == "policy" else tuple(f"{kind}_error:{error}" for error in errors)
        source = call(
            "executor",
            prompt + "\nRepair this source:\n" + source + "\nErrors: " + str(errors) +
            "\nRepair guidance: " + build_code_repair_guidance(
                violations, policy, operation_semantics=case.operation_semantics,
            ) +
            "\nReturn the complete replacement Python file, preserving the authorized paths and output schema.",
            (("retriever", evidence),),
            system_instruction=executor_instruction,
        )
    # Closing reports contain nine real predecessor outputs plus a wide table.
    # Scope both to the entities in this batch instead of overflowing the fixed
    # model window. Ordinary, already validated four-row reviews are unchanged.
    batches = [[row] for row in output] if historical_results else [output]
    checks, reports, combined_rows = [], [], []
    for batch_index, batch in enumerate(batches, 1):
        entities = {str(row.get("unit_id", row.get("site_id"))) for row in batch}
        history = [{"task_id": item["task_id"], "rows": [row for row in item["rows"]
                   if str(row.get("unit_id", row.get("site_id"))) in entities]} for item in historical_results]
        transferred = stable_json_dumps(batch)
        # Retriever already produced one line per entity; retain its actual
        # message, not a controller-written replacement or reference answer.
        cited = evidence
        report_schema = {
            "type": "object", "additionalProperties": False, "required": ["rows", "summary"],
            "properties": {
                "rows": {"type": "array", "minItems": len(batch), "maxItems": len(batch),
                         "items": {"type": "object", "additionalProperties": False, "required": list(case.output_schema),
                                   "properties": {key: {"type": kind} for key, kind in case.output_schema.items()}}},
                "summary": {"type": "string"},
            },
        }
        report_task = (f"Complete the closing report for {case.task_id}, for only the supplied entities. "
                       "Calculations have already been verified; summarize and cross-check the supplied history."
                       if history else task)
        report_prompt = (report_task + "\nExecutor calculated table (copy exactly):\n" + transferred +
                         "\nRetriever message:\n" + cited +
                         '\nReturn JSON with "rows" containing the exact computed table, and "summary" as ONE STRING '
                         'with newline separators, NOT an array. Do not change numbers. ' + report_instructions)
        history_handoff = ()
        if history:
            history_text = stable_json_dumps(history)
            report_prompt += "\nOwn-profile historical_results (cross-check only):\n" + history_text
            history_handoff = (("prior_verified_executors", history_text),)
        for attempt in range(2):
            if attempt:
                append_event(root / "metric-events.jsonl", {"event": "repair_requested", "kind": "report", "role": "summarizer"})
            report = extract_json_object(call("summarizer", report_prompt,
                (("executor", transferred), ("retriever", cited)) + history_handoff, response_schema=report_schema))
            statements = text_statements(report.get("summary", ""))
            errors = ((report_validator(batch, statements) if report_validator is not None else
                       report_errors(batch, statements, sources=report_sources))
                      if isinstance(report.get("summary"), str) else ["report_summary_type:string_required"])
            observed = report.get("rows")
            if (not isinstance(observed, list) or not all(isinstance(row, dict) for row in observed)
                    or not _rows_equal(tuple(observed), tuple(batch))):
                errors.append("report_changed_verified_table")
            checks.append({"batch": batch_index, "attempt": attempt + 1, "errors": errors})
            append_event(root / "report-events.jsonl", checks[-1])
            if not errors:
                break
            # Only the summary needs correction; the verified table already
            # occurs above. Do not duplicate it in a repair prompt.
            report_prompt += (
                "\nPrior report errors: " + ",".join(errors) + "\nPrior summary: " + str(report.get("summary", "")) +
                "\nField feedback: " + stable_json_dumps(report_feedback(errors)) +
                "\nRegenerate the summary, correcting every listed error. Copy exact entity IDs, risk booleans, "
                "risk_change and full filename#section locators from the verified table. Put source=<full locator> "
                "inside EACH line. Keep the verified rows unchanged."
            )
        if errors:
            break
        reports.append(report["summary"])
        combined_rows.extend(report["rows"])
    if not errors and not output_matches(case, combined_rows):
        errors = ["report_changed_verified_table"]

    return {"output_rows": combined_rows, "tool_output_rows": output, "summary_text": "\n".join(reports),
            "tool_records": tool_records, "repairs": repairs, "runtime_completed": True,
            "report_checks": checks, "ok": not errors}
