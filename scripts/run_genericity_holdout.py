#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from statebus.benchmark.models import BenchmarkLayer  # noqa: E402
from statebus.benchmark.minimal_runner import run_minimal_benchmark_family  # noqa: E402
from statebus.benchmark.reporting import family_report_to_dict  # noqa: E402
from statebus.benchmark.task_registry import load_registered_formal_samples  # noqa: E402
from statebus.integrations.llm import parse_tagged_json  # noqa: E402
from statebus.runtime.semantic_plan import compare_semantic_task_plans  # noqa: E402
from statebus.utils import sha256_digest, stable_json_dumps  # noqa: E402


HOLDOUT_REQUESTS = {
    "formal-trend-001": (
        "Review the three ACME quarterly records and state the direction of change, "
        "including the first-to-last difference requested by the output contract."
    ),
    "formal-join-004": (
        "Align the ACME and BETA period records, then report whether their movement "
        "directions agree and provide the requested supporting figures."
    ),
    "formal-agg-004": (
        "Organize the weather observations by month and return the requested monthly "
        "summary statistics from the supplied table."
    ),
    "formal-anomaly-001": (
        "Inspect the disease mortality observations for exceptional values and return "
        "the requested outlier evidence without assuming a named tool."
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a paraphrased cross-family no-route-hint holdout.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--socket-path", type=Path, required=True)
    parser.add_argument("--suite-id", default="statebus-genericity-holdout")
    parser.add_argument("--role-path-mode", choices=("deterministic", "api", "local_vllm"), default="local_vllm")
    parser.add_argument("--embedding-mode", choices=("deterministic", "local"), default="local")
    parser.add_argument("--state-pool-mode", choices=("auto", "shared_memory", "memfd"), default="auto")
    parser.add_argument(
        "--persistence-profile",
        choices=("audit_full", "benchmark_balanced"),
        default="audit_full",
    )
    parser.add_argument(
        "--planner-ablation",
        choices=("none", "disabled", "perturbed", "both"),
        default="both",
        help="Run bounded Planner consumption ablations; full genericity evidence defaults to both.",
    )
    parser.add_argument(
        "--skip-original-baseline",
        action="store_true",
        help="Skip the original-request semantic-equivalence baseline for a quick smoke only.",
    )
    return parser


ROLE_REQUEST_POLICY = {
    "planner": {
        "tag": "sb-plan-v1",
        "required_keys": {"g", "q", "h", "ao", "en", "ts"},
        "allowed_keys": {"g", "q", "h", "ao", "en", "ts"},
    },
    "retriever": {
        "tag": "sb-retriever-v1",
        "required_keys": {"q", "rd", "tc"},
        "allowed_keys": {"q", "rd", "tc", "e", "sp"},
    },
    "executor": {
        "tag": "sb-executor-v1",
        "required_keys": {"r", "t", "a", "tc"},
        "allowed_keys": {"r", "t", "a", "tc", "e", "sp"},
    },
    "summarizer": {
        "tag": "sb-summary-v1",
        "required_keys": {"tf", "h", "t", "r"},
        "allowed_keys": {"tf", "h", "t", "r", "e", "a", "sp"},
    },
}

SHARED_PREFIX_ROLES = {"retriever", "executor", "summarizer"}
SHARED_PREFIX_CONTRACT = "statebus-shared-prefix-v1"
SHARED_PREFIX_CONTAINS = "hydrated_evidence"
SHARED_PREFIX_PATTERN = re.compile(
    r"<statebus-shared-prefix-v1>\r?\n(.*?)\r?\n</statebus-shared-prefix-v1>",
    flags=re.DOTALL,
)


def _contains_mapping_key(value: object, forbidden_keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) in forbidden_keys or _contains_mapping_key(item, forbidden_keys)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_mapping_key(item, forbidden_keys) for item in value)
    return False


def _shared_prefix_metadata_error(
    *,
    role: str,
    prompt: str,
    tagged_payload: dict[str, object],
) -> dict[str, object] | None:
    metadata_present = "sp" in tagged_payload
    prefix_matches = SHARED_PREFIX_PATTERN.findall(prompt)
    if not metadata_present and not prefix_matches:
        return None
    if role not in SHARED_PREFIX_ROLES:
        return {"reason": "role_not_allowed", "role": role}
    if not metadata_present:
        return {"reason": "metadata_missing"}
    if len(prefix_matches) != 1:
        return {"reason": "shared_prefix_marker_count", "count": len(prefix_matches)}

    metadata = tagged_payload.get("sp")
    if not isinstance(metadata, dict):
        return {"reason": "metadata_not_object"}
    expected_keys = {"contract", "contains", "bytes"}
    actual_keys = set(metadata)
    if actual_keys != expected_keys:
        return {
            "reason": "metadata_keys",
            "missing": sorted(expected_keys - actual_keys),
            "unexpected": sorted(actual_keys - expected_keys),
        }
    if metadata.get("contract") != SHARED_PREFIX_CONTRACT:
        return {"reason": "contract", "observed": metadata.get("contract")}
    if metadata.get("contains") != SHARED_PREFIX_CONTAINS:
        return {"reason": "contains", "observed": metadata.get("contains")}
    byte_count = metadata.get("bytes")
    if type(byte_count) is not int or byte_count < 0:
        return {"reason": "bytes_type_or_range", "observed": byte_count}
    expected_bytes = len(prefix_matches[0].encode("utf-8"))
    if byte_count != expected_bytes:
        return {
            "reason": "bytes_mismatch",
            "observed": byte_count,
            "expected": expected_bytes,
        }
    return None


def _group_violations(violations: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for violation in violations:
        role = str(violation.get("role", ""))
        kind = str(violation.get("kind", ""))
        detail = stable_json_dumps(violation.get("detail"))
        key = (role, kind, detail)
        group = grouped.setdefault(
            key,
            {
                "role": role,
                "kind": kind,
                "detail": violation.get("detail"),
                "occurrence_count": 0,
                "paths": [],
            },
        )
        group["occurrence_count"] = int(group["occurrence_count"]) + 1
        path = str(violation.get("path", "")).strip()
        if path and path not in group["paths"]:
            group["paths"].append(path)
    return list(grouped.values())


def _prompt_taint_audit(workspace_roots: tuple[Path, ...]) -> dict[str, object]:
    forbidden_fields = (
        "expected_facts",
        "expected_route",
        "expected_tool_name",
        "oracle_answer",
        "planner_workflow_step",
        "case_id",
    )
    violations: list[dict[str, object]] = []
    role_request_counts = {role: 0 for role in ROLE_REQUEST_POLICY}
    task_roles: dict[str, set[str]] = {}
    scanned_files = 0
    scanned_requests = 0
    artifact_paths: list[str] = []
    preferred_candidate_match_count = 0
    for workspace_root in workspace_roots:
        for path in sorted(workspace_root.rglob("*.rendered_request.json")):
            scanned_files += 1
            artifact_paths.append(str(path))
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                violations.append(
                    {"path": str(path), "kind": "request_artifact_parse_error", "detail": str(exc)}
                )
                continue
            task_id = str(artifact.get("task_id", path.parent.parent.parent.name)).strip()
            role = str(artifact.get("role", "")).strip()
            if role not in ROLE_REQUEST_POLICY:
                violations.append(
                    {"path": str(path), "kind": "unexpected_role", "detail": role}
                )
                continue
            task_roles.setdefault(task_id, set()).add(role)
            if artifact.get("content_persisted") is not True:
                violations.append(
                    {"path": str(path), "kind": "rendered_request_content_not_persisted"}
                )
            requests = artifact.get("requests", [])
            if not isinstance(requests, list) or not requests:
                violations.append({"path": str(path), "kind": "missing_rendered_request"})
                continue
            policy = ROLE_REQUEST_POLICY[role]
            for request in requests:
                scanned_requests += 1
                role_request_counts[role] += 1
                if not isinstance(request, dict):
                    violations.append({"path": str(path), "kind": "invalid_request_record"})
                    continue
                messages = request.get("messages", [])
                prompt = ""
                if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
                    prompt = str(messages[-1].get("content", ""))
                if not prompt:
                    violations.append({"path": str(path), "kind": "missing_rendered_prompt"})
                    continue
                for marker in forbidden_fields:
                    field_pattern = rf'(?:"{re.escape(marker)}"\s*:|\b{re.escape(marker)}\s*=)'
                    if re.search(field_pattern, prompt, flags=re.IGNORECASE):
                        violations.append(
                            {
                                "path": str(path),
                                "role": role,
                                "kind": "forbidden_oracle_field",
                                "detail": marker,
                            }
                        )
                base_task_id = _base_task_id(task_id)
                for case_marker in {task_id, base_task_id}:
                    if case_marker and case_marker.lower() in prompt.lower():
                        violations.append(
                            {
                                "path": str(path),
                                "role": role,
                                "kind": "case_id_specialization",
                                "detail": case_marker,
                            }
                        )
                try:
                    tagged_payload = parse_tagged_json(prompt, str(policy["tag"]))
                except (ValueError, json.JSONDecodeError) as exc:
                    violations.append(
                        {
                            "path": str(path),
                            "role": role,
                            "kind": "tagged_request_parse_error",
                            "detail": str(exc),
                        }
                    )
                    continue
                payload_keys = set(tagged_payload)
                required_keys = set(policy["required_keys"])
                allowed_keys = set(policy["allowed_keys"])
                if not required_keys.issubset(payload_keys):
                    violations.append(
                        {
                            "path": str(path),
                            "role": role,
                            "kind": "missing_required_role_payload_keys",
                            "detail": sorted(required_keys - payload_keys),
                        }
                    )
                if not payload_keys.issubset(allowed_keys):
                    violations.append(
                        {
                            "path": str(path),
                            "role": role,
                            "kind": "unexpected_role_payload_keys",
                            "detail": sorted(payload_keys - allowed_keys),
                        }
                    )
                shared_prefix_error = _shared_prefix_metadata_error(
                    role=role,
                    prompt=prompt,
                    tagged_payload=tagged_payload,
                )
                if shared_prefix_error is not None:
                    violations.append(
                        {
                            "path": str(path),
                            "role": role,
                            "kind": "invalid_shared_prefix_metadata",
                            "detail": shared_prefix_error,
                        }
                    )
                if role in {"retriever", "executor"}:
                    preferred_candidate_present = (
                        _contains_mapping_key(tagged_payload, {"pc", "rh"})
                        or "preferred candidate" in prompt.lower()
                        or "treat pc" in prompt.lower()
                    )
                    if preferred_candidate_present:
                        preferred_candidate_match_count += 1
                        violations.append(
                            {
                                "path": str(path),
                                "role": role,
                                "kind": "no_hint_preferred_candidate_present",
                            }
                        )
    required_roles = set(ROLE_REQUEST_POLICY)
    missing_roles_by_task = {
        task_id: sorted(required_roles - roles)
        for task_id, roles in sorted(task_roles.items())
        if roles != required_roles
    }
    for task_id, missing_roles in missing_roles_by_task.items():
        violations.append(
            {
                "task_id": task_id,
                "kind": "missing_role_request_artifact",
                "detail": missing_roles,
            }
        )
    return {
        "schema_version": "statebus.role_request_taint_audit.v3",
        "scope": "actual_llm_client_messages_and_response_schema_metadata",
        "workspace_roots": [str(root) for root in workspace_roots],
        "scanned_task_count": len(task_roles),
        "scanned_role_request_file_count": scanned_files,
        "scanned_request_count": scanned_requests,
        "role_request_counts": role_request_counts,
        "forbidden_fields": list(forbidden_fields),
        "allowed_role_surfaces": {
            "planner": "bounded semantic-plan inputs only",
            "retriever": "complete tc capability surface; no pc/rh preferred candidate",
            "executor": "Retriever-selected r/t plus complete tc validation surface; no pc/rh",
            "summarizer": "evidence and downstream action handoff",
        },
        "no_hint_preferred_candidate_absent": preferred_candidate_match_count == 0,
        "preferred_candidate_match_count": preferred_candidate_match_count,
        "missing_roles_by_task": missing_roles_by_task,
        "violation_count": len(violations),
        "violations": violations,
        "violation_group_count": len(_group_violations(violations)),
        "violation_groups": _group_violations(violations),
        "artifact_paths": artifact_paths,
        "pass": bool(task_roles) and scanned_files > 0 and scanned_requests > 0 and not violations,
    }


def _run_family(
    *,
    args,
    samples,
    workspace_root: Path,
    runtime_root: Path,
    suite_suffix: str,
    consumption_mode: str,
):
    previous = os.environ.get("STATEBUS_PLANNER_CONSUMPTION_MODE")
    os.environ["STATEBUS_PLANNER_CONSUMPTION_MODE"] = consumption_mode
    try:
        return run_minimal_benchmark_family(
            samples=samples,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            socket_path=args.socket_path.with_name(
                f"{args.socket_path.stem}-{suite_suffix}{args.socket_path.suffix}"
            ),
            suite_id=f"{args.suite_id}-{suite_suffix}",
            layer=BenchmarkLayer.L3,
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            benchmark_tier="formal",
            claim_level="diagnostic_genericity_holdout",
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
        )
    finally:
        if previous is None:
            os.environ.pop("STATEBUS_PLANNER_CONSUMPTION_MODE", None)
        else:
            os.environ["STATEBUS_PLANNER_CONSUMPTION_MODE"] = previous


def _workspace_planner_facts(workspace_root: Path) -> dict[str, dict[str, object]]:
    facts: dict[str, dict[str, object]] = {}
    for handoff_path in sorted(workspace_root.rglob("inputs/planner_handoff.json")):
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        task_id = str(handoff.get("task_id", handoff_path.parent.parent.name))
        audit = handoff.get("semantic_plan_audit", {})
        audit = audit if isinstance(audit, dict) else {}
        result_path = handoff_path.parent.parent / "outputs" / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        model_plan = audit.get("model_plan", {})
        effective_plan = audit.get("effective_plan", {})
        facts[task_id] = {
            "objective_source": audit.get("objective_source", ""),
            "semantic_plan_valid": bool(audit.get("semantic_plan_valid")),
            "semantic_equivalence": bool(audit.get("semantic_equivalence")),
            "model_plan_hash": audit.get("model_plan_hash", ""),
            "fallback_plan_hash": audit.get("fallback_plan_hash", ""),
            "effective_plan_hash": audit.get("effective_plan_hash", ""),
            "behavioral_effect": bool(audit.get("behavioral_effect_before_consumption")),
            "validation_errors": audit.get("validation_errors", []),
            "model_plan": model_plan if isinstance(model_plan, dict) else {},
            "effective_plan": effective_plan if isinstance(effective_plan, dict) else {},
            "consumed_objective_hashes": handoff.get("retriever_consumed_objective_hashes", {}),
            "semantic_signature": _semantic_signature(
                model_plan if isinstance(model_plan, dict) else {}
            ),
            "effective_semantic_signature": _semantic_signature(
                effective_plan if isinstance(effective_plan, dict) else {}
            ),
            "route": result.get("route", ""),
            "tool_name": result.get("tool_name", ""),
        }
    return facts


def _semantic_signature(plan: dict[str, object]) -> str:
    semantics = plan.get("task_semantics", {})
    semantics = semantics if isinstance(semantics, dict) else {}
    objectives = plan.get("retrieval_objectives", {})
    objectives = objectives if isinstance(objectives, dict) else {}
    signature = {
        "task_semantics": {
            "goal": semantics.get("goal", ""),
            "entities": semantics.get("entities", []),
            "time_scope": semantics.get("time_scope", ""),
        },
        "retrieval_shape": {
            name: {
                "evidence_types": objective.get("evidence_types", []),
                "reuse_intent": objective.get("reuse_intent", ""),
            }
            for name, objective in sorted(objectives.items())
            if isinstance(objective, dict)
        },
        "required_evidence": plan.get("required_evidence", []),
        "required_outputs": plan.get("required_outputs", []),
    }
    return sha256_digest(signature)


def _case_quality_map(report_payload: dict[str, object]) -> dict[str, bool]:
    return {
        str(case.get("task_id", "")): bool(
            dict(case.get("quality_floor", {})).get("quality_floor_pass")
        )
        for case in report_payload.get("cases", [])
        if isinstance(case, dict)
    }


def _base_task_id(task_id: str) -> str:
    for prefix in (
        "genericity-original-",
        "genericity-disabled-",
        "genericity-perturbed-",
        "genericity-",
    ):
        if task_id.startswith(prefix):
            return task_id.removeprefix(prefix)
    return task_id


def main() -> int:
    args = _parser().parse_args()
    os.environ["STATEBUS_ROUTE_HINTS_ENABLED"] = "0"
    registered = {sample.task_id: sample for sample in load_registered_formal_samples()}
    missing = sorted(set(HOLDOUT_REQUESTS) - set(registered))
    if missing:
        raise SystemExit(f"genericity holdout sample(s) missing: {', '.join(missing)}")
    samples = [
        replace(
            registered[task_id],
            task_id=f"genericity-{task_id}",
            request_text=request_text,
            scenario_tags=tuple(
                dict.fromkeys((*registered[task_id].scenario_tags, "genericity-holdout", "paraphrased"))
            ),
        )
        for task_id, request_text in HOLDOUT_REQUESTS.items()
    ]
    report = _run_family(
        args=args,
        samples=samples,
        workspace_root=args.workspace_root,
        runtime_root=args.runtime_root,
        suite_suffix="primary",
        consumption_mode="effective",
    )
    report_payload = family_report_to_dict(report)
    cases = report_payload.get("cases", [])
    primary_facts = _workspace_planner_facts(args.workspace_root)
    case_audit = []
    for case in cases:
        metrics = case.get("metrics", {})
        case_audit.append(
            {
                "task_id": case.get("task_id"),
                "task_family": case.get("task_family"),
                "quality_floor_pass": bool(case.get("quality_floor", {}).get("quality_floor_pass")),
                "route_hints_enabled": float(metrics.get("route_hints_enabled", -1.0)),
                "planner_objective_present": float(metrics.get("planner_objective_present", 0.0)),
                "planner_workflow_step_count": float(metrics.get("planner_workflow_step_count", 0.0)),
                "planner_semantic_plan_valid": float(metrics.get("planner_semantic_plan_valid", 0.0)),
                "planner_semantic_equivalence": float(metrics.get("planner_semantic_equivalence", 0.0)),
                "planner_behavioral_effect": float(metrics.get("planner_behavioral_effect", 0.0)),
                "planner_model_generated_field_count": float(
                    metrics.get("planner_model_generated_field_count", 0.0)
                ),
                "planner_downstream_consumed_field_count": float(
                    metrics.get("planner_downstream_consumed_field_count", 0.0)
                ),
                "planner_retriever_consumed_hash_match_count": float(
                    metrics.get("planner_retriever_consumed_hash_match_count", 0.0)
                ),
                "objective_source_hybrid": float(
                    metrics.get("planner_objective_source_hybrid", 0.0)
                ),
                "four_role_call_count": sum(
                    int(float(metrics.get(f"{role}_call_count", 0.0)) > 0.0)
                    for role in ("planner", "retriever", "executor", "summarizer")
                ),
            }
        )
    auxiliary_root = args.workspace_root.parent / f"{args.workspace_root.name}-planner-audit"
    auxiliary_runtime_root = args.runtime_root.parent / f"{args.runtime_root.name}-planner-audit"
    original_report_payload: dict[str, object] = {}
    original_facts: dict[str, dict[str, object]] = {}
    if not args.skip_original_baseline:
        original_samples = [
            replace(registered[task_id], task_id=f"genericity-original-{task_id}")
            for task_id in HOLDOUT_REQUESTS
        ]
        original_report = _run_family(
            args=args,
            samples=original_samples,
            workspace_root=auxiliary_root / "original",
            runtime_root=auxiliary_runtime_root / "original",
            suite_suffix="original",
            consumption_mode="effective",
        )
        original_report_payload = family_report_to_dict(original_report)
        original_facts = _workspace_planner_facts(auxiliary_root / "original")

    ablation_payloads: dict[str, dict[str, object]] = {}
    ablation_facts: dict[str, dict[str, dict[str, object]]] = {}
    modes = (
        ("disabled", "perturbed")
        if args.planner_ablation == "both"
        else (() if args.planner_ablation == "none" else (args.planner_ablation,))
    )
    for mode in modes:
        mode_samples = [
            replace(sample, task_id=f"genericity-{mode}-{_base_task_id(sample.task_id)}")
            for sample in samples
        ]
        mode_report = _run_family(
            args=args,
            samples=mode_samples,
            workspace_root=auxiliary_root / mode,
            runtime_root=auxiliary_runtime_root / mode,
            suite_suffix=mode,
            consumption_mode=mode,
        )
        ablation_payloads[mode] = family_report_to_dict(mode_report)
        ablation_facts[mode] = _workspace_planner_facts(auxiliary_root / mode)

    request_audit_roots = [args.workspace_root]
    if not args.skip_original_baseline:
        request_audit_roots.append(auxiliary_root / "original")
    request_audit_roots.extend(auxiliary_root / mode for mode in modes)
    taint_audit = _prompt_taint_audit(tuple(request_audit_roots))

    primary_by_base = {_base_task_id(key): value for key, value in primary_facts.items()}
    original_by_base = {_base_task_id(key): value for key, value in original_facts.items()}
    model_paraphrase_comparisons = {
        task_id: compare_semantic_task_plans(
            dict(primary_by_base[task_id].get("model_plan", {})),
            dict(original_by_base.get(task_id, {}).get("model_plan", {})),
        ).canonical_payload()
        for task_id in primary_by_base
    }
    model_paraphrase_equivalence = {
        task_id: bool(comparison.get("equivalent"))
        for task_id, comparison in model_paraphrase_comparisons.items()
    }
    effective_paraphrase_comparisons = {
        task_id: compare_semantic_task_plans(
            dict(primary_by_base[task_id].get("effective_plan", {})),
            dict(original_by_base.get(task_id, {}).get("effective_plan", {})),
        ).canonical_payload()
        for task_id in primary_by_base
    }
    effective_paraphrase_equivalence = {
        task_id: bool(comparison.get("equivalent"))
        for task_id, comparison in effective_paraphrase_comparisons.items()
    }
    paraphrase_surface_hash_equal = {
        task_id: bool(
            task_id in original_by_base
            and primary_by_base[task_id].get("semantic_signature")
            == original_by_base[task_id].get("semantic_signature")
        )
        for task_id in primary_by_base
    }
    cross_family_signatures = {
        str(value.get("semantic_signature", "")) for value in primary_by_base.values()
    }
    ablation_audit: dict[str, object] = {}
    for mode, facts in ablation_facts.items():
        by_base = {_base_task_id(key): value for key, value in facts.items()}
        quality_by_base = {
            _base_task_id(key): value
            for key, value in _case_quality_map(ablation_payloads[mode]).items()
        }
        ablation_audit[mode] = {
            "case_count": len(by_base),
            "all_quality_pass": bool(by_base) and all(quality_by_base.get(key, False) for key in by_base),
            "all_effective_plan_hash_changed": bool(by_base) and all(
                by_base[key].get("effective_plan_hash")
                != primary_by_base.get(key, {}).get("effective_plan_hash")
                for key in by_base
            ),
            "all_consumed_objective_hashes_changed": bool(by_base) and all(
                by_base[key].get("consumed_objective_hashes")
                != primary_by_base.get(key, {}).get("consumed_objective_hashes")
                for key in by_base
            ),
            "all_route_tool_stable": bool(by_base) and all(
                (
                    by_base[key].get("route"),
                    by_base[key].get("tool_name"),
                )
                == (
                    primary_by_base.get(key, {}).get("route"),
                    primary_by_base.get(key, {}).get("tool_name"),
                )
                for key in by_base
            ),
            "all_runtime_fallback_source": bool(by_base) and all(
                by_base[key].get("objective_source") == "runtime_fallback"
                for key in by_base
            ),
            "all_behavioral_effect_disabled": bool(by_base) and all(
                not bool(by_base[key].get("behavioral_effect")) for key in by_base
            ),
            "all_hybrid_source": bool(by_base) and all(
                by_base[key].get("objective_source") == "hybrid" for key in by_base
            ),
            "all_behavioral_effect_present": bool(by_base) and all(
                bool(by_base[key].get("behavioral_effect")) for key in by_base
            ),
            "facts": by_base,
        }
    passed = bool(case_audit) and all(
        item["quality_floor_pass"]
        and item["route_hints_enabled"] == 0.0
        and item["planner_objective_present"] == 1.0
        and item["planner_semantic_plan_valid"] == 1.0
        and item["planner_semantic_equivalence"] == 1.0
        and item["planner_behavioral_effect"] == 1.0
        and item["planner_model_generated_field_count"] > 0.0
        and item["planner_downstream_consumed_field_count"] > 0.0
        and item["planner_retriever_consumed_hash_match_count"] == 4.0
        and item["objective_source_hybrid"] == 1.0
        and item["four_role_call_count"] == 4
        for item in case_audit
    ) and bool(taint_audit["pass"])
    if not args.skip_original_baseline:
        passed = (
            passed
            and bool(effective_paraphrase_equivalence)
            and all(effective_paraphrase_equivalence.values())
        )
    passed = passed and len(cross_family_signatures) >= 2
    for mode in modes:
        mode_audit = dict(ablation_audit.get(mode, {}))
        passed = passed and bool(mode_audit.get("all_quality_pass"))
        passed = passed and bool(mode_audit.get("all_effective_plan_hash_changed"))
        passed = passed and bool(mode_audit.get("all_consumed_objective_hashes_changed"))
        if mode == "disabled":
            passed = passed and bool(mode_audit.get("all_runtime_fallback_source"))
            passed = passed and bool(mode_audit.get("all_behavioral_effect_disabled"))
        if mode == "perturbed":
            passed = passed and bool(mode_audit.get("all_hybrid_source"))
            passed = passed and bool(mode_audit.get("all_behavioral_effect_present"))
    payload = {
        "schema_version": "statebus.genericity_holdout.v2",
        "ok": passed,
        "claim_boundary": (
            "paraphrase_and_no-preferred-candidate_route-selection_holdout_with_precompiled_canonical_task_spec; "
            "does_not_claim_free-form_intent_compilation_generalization"
        ),
        "route_hint_policy": "disabled",
        "selected_case_count": len(samples),
        "selected_family_count": len({sample.task_family for sample in samples}),
        "request_hashes": {
            sample.task_id: sha256_digest(sample.request_text) for sample in samples
        },
        "case_audit": case_audit,
        "planner_facts": primary_by_base,
        "model_paraphrase_stability_pass": bool(model_paraphrase_equivalence)
        and all(model_paraphrase_equivalence.values()),
        "effective_contract_safety_pass": bool(effective_paraphrase_equivalence)
        and all(effective_paraphrase_equivalence.values()),
        "paraphrase_model_semantic_equivalence": model_paraphrase_equivalence,
        "paraphrase_model_semantic_equivalence_details": model_paraphrase_comparisons,
        "paraphrase_effective_contract_equivalence": effective_paraphrase_equivalence,
        "paraphrase_effective_contract_equivalence_details": effective_paraphrase_comparisons,
        "paraphrase_semantic_equivalence": model_paraphrase_equivalence,
        "paraphrase_semantic_equivalence_details": model_paraphrase_comparisons,
        "paraphrase_surface_hash_equal": paraphrase_surface_hash_equal,
        "cross_family_semantic_signature_count": len(cross_family_signatures),
        "cross_family_objective_differentiation_pass": len(cross_family_signatures) >= 2,
        "planner_ablation": ablation_audit,
        "prompt_taint_audit": taint_audit,
        "report": report_payload,
        "original_request_report": original_report_payload,
        "ablation_reports": ablation_payloads,
    }
    print(stable_json_dumps(payload))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
