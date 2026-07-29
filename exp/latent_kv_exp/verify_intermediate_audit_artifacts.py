#!/usr/bin/env python3
"""Verify intermediate audit artifacts for the one-round audit task."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TASK_FILE = PROJECT / "task/lantent/intermediate_audit_1round/intermediate_audit_task.json"

TERM_FIELDS = [
    "sensitivity_points",
    "volume_points",
    "channel_points",
    "anomaly_points",
    "repeat_points",
    "exposure_points",
    "mitigation_points",
]
FINAL_FIELDS = ["case_id", "risk_score", "tier", "action", "primary_control_gap"]


@dataclass
class CheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_json_objects(text: str) -> list[Any]:
    objects: list[Any] = []
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch not in "[{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        objects.append(obj)
    return objects


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(as_text(item) for item in value)
    return json.dumps(value, ensure_ascii=False)


def normalize_final_answer(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {field: value.get(field, "") for field in FINAL_FIELDS}
    text = as_text(value)
    for obj in find_json_objects(text):
        if isinstance(obj, dict) and all(field in obj for field in FINAL_FIELDS):
            return {field: obj.get(field, "") for field in FINAL_FIELDS}
    return {field: "" for field in FINAL_FIELDS}


def extract_first(artifact: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in artifact and artifact[key] not in (None, "", [], {}):
            return artifact[key]
    return None


def extract_final_answer(artifact: dict[str, Any]) -> dict[str, Any]:
    direct = extract_first(artifact, ["final_answer", "answer", "final_output", "summary"])
    final_answer = normalize_final_answer(direct)
    if any(final_answer.values()):
        return final_answer
    for key in ("raw_response", "output", "content"):
        if key in artifact:
            final_answer = normalize_final_answer(artifact[key])
            if any(final_answer.values()):
                return final_answer
    return final_answer


def extract_matrix(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        artifact.get("executor_matrix"),
        artifact.get("audit_matrix"),
        artifact.get("matrix"),
    ]
    execution_result = artifact.get("execution_result")
    if isinstance(execution_result, dict):
        candidates.extend([
            execution_result.get("executor_matrix"),
            execution_result.get("audit_matrix"),
        ])
        metrics = execution_result.get("metrics")
        if isinstance(metrics, dict):
            candidates.extend([
                metrics.get("executor_matrix"),
                metrics.get("audit_matrix"),
            ])
    for candidate in candidates:
        matrix = normalize_matrix(candidate)
        if matrix:
            return matrix
    for key in ("execution_summary", "executor_output", "raw_response", "output", "content"):
        text = artifact.get(key)
        if not text:
            continue
        for obj in find_json_objects(as_text(text)):
            matrix = normalize_matrix(obj)
            if matrix:
                return matrix
    return []


def normalize_matrix(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = None
        for key in ("cases", "rows", "matrix", "executor_matrix", "audit_matrix"):
            if isinstance(value.get(key), list):
                rows = value[key]
                break
        if rows is None and "case_id" in value:
            rows = [value]
    else:
        rows = None
    if not rows:
        return []
    return [row for row in rows if isinstance(row, dict)]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    terms = row.get("score_terms")
    if isinstance(terms, dict):
        for field_name in TERM_FIELDS:
            normalized.setdefault(field_name, terms.get(field_name))
    for field_name in [*TERM_FIELDS, "risk_score"]:
        if field_name in normalized:
            try:
                normalized[field_name] = int(normalized[field_name])
            except (TypeError, ValueError):
                pass
    evidence_ids = (
        row.get("supporting_evidence_ids")
        or row.get("evidence_ids")
        or row.get("supporting_evidence")
        or []
    )
    if isinstance(evidence_ids, str):
        evidence_ids = re.findall(r"E\d{3}", evidence_ids)
    normalized["supporting_evidence_ids"] = list(evidence_ids) if isinstance(evidence_ids, list) else []
    return normalized


def expected_cases(task_suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    task = task_suite["tasks"][0]
    cases = task["evidence_packet"]["candidate_cases"]
    out: dict[str, dict[str, Any]] = {}
    for case in cases:
        terms = case["score_terms"]
        score = (
            int(terms["sensitivity_points"])
            + int(terms["volume_points"])
            + int(terms["channel_points"])
            + int(terms["anomaly_points"])
            + int(terms["repeat_points"])
            + int(terms["exposure_points"])
            - int(terms["mitigation_points"])
        )
        tier = tier_for_score(score)
        action = task_suite["shared_context"]["valid_actions"][tier]
        evidence_ids = [item["evidence_id"] for item in case.get("evidence", [])]
        out[case["case_id"]] = {
            "case_id": case["case_id"],
            **terms,
            "risk_score": score,
            "tier": tier,
            "action": action,
            "primary_control_gap": case["primary_control_gap"],
            "evidence_ids": evidence_ids,
        }
    return out


def tier_for_score(score: int) -> str:
    if score >= 85:
        return "CRITICAL"
    if score >= 65:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def verify_researcher_report(text: str, task_suite: dict[str, Any], strict_lengths: bool) -> CheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    task = task_suite["tasks"][0]
    spec = task_suite["verifier_contract"]
    if not text.strip():
        errors.append("missing researcher_report")
        return CheckResult(False, errors, warnings)
    min_len = 900 if strict_lengths else 600
    max_len = 1300 if strict_lengths else 2200
    if len(text) < min_len:
        errors.append(f"researcher_report too short: {len(text)} chars < {min_len}")
    if len(text) > max_len:
        errors.append(f"researcher_report too long: {len(text)} chars > {max_len}")
    for case_id in task_suite["shared_context"]["case_id_space"]:
        if case_id not in text:
            errors.append(f"researcher_report missing case {case_id}")
    for evidence_id in spec["required_research_evidence_ids"]:
        if evidence_id not in text:
            errors.append(f"researcher_report missing required evidence {evidence_id}")
    if "reference_answer" in text:
        errors.append("researcher_report appears to mention reference_answer")
    return CheckResult(not errors, errors, warnings, {"chars": len(text)})


def verify_analyst_analysis(text: str, task_suite: dict[str, Any], strict_lengths: bool) -> CheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    spec = task_suite["verifier_contract"]
    if not text.strip():
        errors.append("missing analyst_analysis")
        return CheckResult(False, errors, warnings)
    min_len = 900 if strict_lengths else 600
    max_len = 1300 if strict_lengths else 2400
    if len(text) < min_len:
        errors.append(f"analyst_analysis too short: {len(text)} chars < {min_len}")
    if len(text) > max_len:
        errors.append(f"analyst_analysis too long: {len(text)} chars > {max_len}")
    compact = re.sub(r"\s+", "", text)
    required_order = "C-117>C-118>C-119>C-120"
    if required_order not in compact:
        errors.append("analyst_analysis missing required ranking C-117 > C-118 > C-119 > C-120")
    for phrase in spec["required_analyst_phrases"]:
        if phrase.replace(" ", "") not in compact:
            errors.append(f"analyst_analysis missing required phrase: {phrase}")
    for case_id in ("C-118", "C-119", "C-120"):
        case_pos = text.find(case_id)
        if case_pos < 0:
            errors.append(f"analyst_analysis missing exclusion discussion for {case_id}")
    return CheckResult(not errors, errors, warnings, {"chars": len(text)})


def verify_executor_matrix(matrix: list[dict[str, Any]], task_suite: dict[str, Any]) -> CheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    expected = expected_cases(task_suite)
    rows_by_case: dict[str, dict[str, Any]] = {}
    for raw_row in matrix:
        row = normalize_row(raw_row)
        case_id = str(row.get("case_id", ""))
        if case_id:
            rows_by_case[case_id] = row
    for case_id in expected:
        if case_id not in rows_by_case:
            errors.append(f"executor_matrix missing case {case_id}")
            continue
        row = rows_by_case[case_id]
        exp = expected[case_id]
        for field_name in TERM_FIELDS:
            if row.get(field_name) != exp[field_name]:
                errors.append(
                    f"{case_id}.{field_name} expected {exp[field_name]} got {row.get(field_name)!r}"
                )
        if all(isinstance(row.get(field_name), int) for field_name in TERM_FIELDS):
            computed = (
                row["sensitivity_points"]
                + row["volume_points"]
                + row["channel_points"]
                + row["anomaly_points"]
                + row["repeat_points"]
                + row["exposure_points"]
                - row["mitigation_points"]
            )
            if row.get("risk_score") != computed:
                errors.append(f"{case_id}.risk_score formula mismatch: row={row.get('risk_score')} computed={computed}")
        if row.get("risk_score") != exp["risk_score"]:
            errors.append(f"{case_id}.risk_score expected {exp['risk_score']} got {row.get('risk_score')!r}")
        if row.get("tier") != exp["tier"]:
            errors.append(f"{case_id}.tier expected {exp['tier']} got {row.get('tier')!r}")
        if row.get("action") != exp["action"]:
            errors.append(f"{case_id}.action expected {exp['action']} got {row.get('action')!r}")
        evidence_ids = set(str(item) for item in row.get("supporting_evidence_ids", []))
        known_ids = set(exp["evidence_ids"])
        if len(evidence_ids) < 2:
            errors.append(f"{case_id}.supporting_evidence_ids must contain at least 2 ids")
        unknown = sorted(evidence_ids - known_ids)
        if unknown:
            errors.append(f"{case_id}.supporting_evidence_ids contains ids outside the case: {unknown}")
    critical_required = {"E001", "E003", "E006"}
    critical_row = rows_by_case.get("C-117", {})
    critical_evidence = set(str(item) for item in critical_row.get("supporting_evidence_ids", []))
    missing_critical = sorted(critical_required - critical_evidence)
    if missing_critical:
        errors.append(f"C-117.supporting_evidence_ids missing critical evidence {missing_critical}")
    return CheckResult(not errors, errors, warnings, {"rows": len(matrix)})


def verify_final_answer(final_answer: dict[str, Any], task_suite: dict[str, Any]) -> CheckResult:
    errors: list[str] = []
    expected = task_suite["tasks"][0]["reference_answer"]
    normalized = dict(final_answer)
    try:
        normalized["risk_score"] = int(normalized.get("risk_score", ""))
    except (TypeError, ValueError):
        pass
    for field_name in FINAL_FIELDS:
        if normalized.get(field_name) != expected.get(field_name):
            errors.append(f"final_answer.{field_name} expected {expected.get(field_name)!r} got {normalized.get(field_name)!r}")
    return CheckResult(not errors, errors, [], {"answer": normalized})


def verify_artifact(artifact: dict[str, Any], task_suite: dict[str, Any], strict_lengths: bool = True) -> dict[str, Any]:
    researcher_report = as_text(extract_first(artifact, ["researcher_report", "research_report", "researcher_output", "documents"]))
    analyst_analysis = as_text(extract_first(artifact, ["analyst_analysis", "analysis", "analyst_output"]))
    matrix = extract_matrix(artifact)
    final_answer = extract_final_answer(artifact)
    checks = {
        "researcher_report": verify_researcher_report(researcher_report, task_suite, strict_lengths),
        "analyst_analysis": verify_analyst_analysis(analyst_analysis, task_suite, strict_lengths),
        "executor_matrix": verify_executor_matrix(matrix, task_suite),
        "final_answer": verify_final_answer(final_answer, task_suite),
    }
    all_errors = [error for result in checks.values() for error in result.errors]
    all_warnings = [warning for result in checks.values() for warning in result.warnings]
    return {
        "ok": not all_errors,
        "errors": all_errors,
        "warnings": all_warnings,
        "checks": {name: asdict(result) for name, result in checks.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify intermediate audit artifacts.")
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASK_FILE)
    parser.add_argument("--artifact", type=Path, required=True, help="JSON file containing model/system output artifacts.")
    parser.add_argument("--report", type=Path, help="Optional path to write verifier JSON report.")
    parser.add_argument("--relaxed-lengths", action="store_true", help="Use wider length bands for development/debug runs.")
    args = parser.parse_args()

    task_file = args.task_file if args.task_file.is_absolute() else PROJECT / args.task_file
    artifact_file = args.artifact if args.artifact.is_absolute() else PROJECT / args.artifact
    task_suite = load_json(task_file)
    artifact = load_json(artifact_file)
    if isinstance(artifact, list):
        artifact = artifact[0] if artifact else {}
    if not isinstance(artifact, dict):
        raise SystemExit("artifact JSON must be an object or a non-empty list of objects")
    report = verify_artifact(artifact, task_suite, strict_lengths=not args.relaxed_lengths)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        report_file = args.report if args.report.is_absolute() else PROJECT / args.report
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(output + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
