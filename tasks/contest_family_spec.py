from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


TASKS_DIR = Path(__file__).resolve().parent
CONTEST_SPEC_PATH = TASKS_DIR / "contest_family_spec.yaml"
CONTEST_BENCHMARK_PATH = TASKS_DIR / "contest_dual_mode_controlled_v3_benchmark.yaml"
CONTEST_CORPUS_PATH = TASKS_DIR / "contest_release_regression_corpus.yaml"
CONTEST_HONEST_HEADLINE_NAME = "contest_honest_headline_v1_pack"

REQUIRED_DOC_ROLES = {
    "incident",
    "metrics",
    "logs",
    "structural_anchor",
    "cross_family_distractor",
    "ambiguity_note",
    "scope_note",
    "reuse_dependency_note",
}
DOC_ROLE_ALIASES = {
    "rotation": "structural_anchor",
    "runbook": "structural_anchor",
    "config": "structural_anchor",
    "flag-diff": "structural_anchor",
    "rate-limit-false": "cross_family_distractor",
    "db-false": "cross_family_distractor",
    "worker-false": "cross_family_distractor",
    "replica-false": "cross_family_distractor",
    "ambiguous": "ambiguity_note",
    "scope": "scope_note",
    "reuse": "reuse_dependency_note",
}
REQUIRED_CASE_KEYS = {"clean", "distractor", "ambiguous", "replay_reusable"}
THICKNESS_SETTINGS = {"S0", "S1", "S2"}
S1_CASE_KEYS = {"clean", "distractor", "ambiguous"}
S2_CASE_KEYS = {"replay_reusable"}
REQUIRED_THICKNESS_CASE_FIELDS = {
    "thickness_setting",
    "reasoning_hops_min",
    "dependency_depth",
    "expected_intermediate_decisions",
    "abstention_boundary",
    "required_plan_semantic_roles",
}
REQUIRED_THICKNESS_FAMILY_FIELDS = {
    "route_competition_min",
    "tool_competition_min",
}


def load_contest_family_spec() -> dict[str, Any]:
    payload = yaml.safe_load(CONTEST_SPEC_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"contest family spec must be a mapping: {CONTEST_SPEC_PATH}")
    task_set = dict(payload.get("task_set", {}) or {})
    corpus_metadata = dict(payload.get("corpus_metadata", {}) or {})
    families = list(payload.get("families", []) or [])
    if not task_set:
        raise ValueError(f"contest family spec missing task_set: {CONTEST_SPEC_PATH}")
    if not families:
        raise ValueError(f"contest family spec missing families: {CONTEST_SPEC_PATH}")
    _validate_contest_family_spec(task_set=task_set, corpus_metadata=corpus_metadata, families=families)
    return {
        "task_set": task_set,
        "corpus_metadata": corpus_metadata,
        "families": families,
    }


def generate_contest_benchmark_payload(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = load_contest_family_spec() if spec is None else deepcopy(spec)
    tasks: list[dict[str, Any]] = []
    for family in loaded["families"]:
        task_group = str(family["task_group"]).strip()
        task_theme = str(family["task_theme"]).strip()
        for case_index, case_key in enumerate(_case_order(family), start=1):
            case = dict(family["cases"][case_key])
            case_id = str(case["case_id"]).strip()
            corpus_doc_ids = [
                str(family["docs"][role]["doc_id"]).strip()
                for role in case["corpus_doc_roles"]
            ]
            common = {
                "task_group": task_group,
                "task_theme": task_theme,
                "benchmark_lane": "state_transfer",
                "corpus_path": CONTEST_CORPUS_PATH.name,
                "goal": str(case["goal"]).strip(),
                "query": str(case["query"]).strip(),
                "corpus_doc_ids": corpus_doc_ids,
                "tags": list(case["tags"]),
                "reuse_tags": list(case["reuse_tags"]),
                "expected_reuse_mode": "none",
                "runtime_reuse_contract": "reuse_disabled",
                "summary_hint": str(case["summary_hint"]).strip(),
                "case_id": case_id,
                "case_type": str(case["case_type"]).strip(),
                "eval_scope": str(case["eval_scope"]).strip(),
                "expected_family": str(case["expected_family"]).strip(),
                "primary_expected_route": str(case["primary_expected_route"]).strip(),
                "primary_expected_tool": str(case["primary_expected_tool"]).strip(),
                "acceptable_routes": list(case["acceptable_routes"]),
                "acceptable_tools": list(case["acceptable_tools"]),
                "disallowed_families": list(case["disallowed_families"]),
                "required_prior_case_ids": list(case["required_prior_case_ids"]),
                "required_prior_rejections": list(case["required_prior_rejections"]),
                "abstention_allowed": bool(case["abstention_allowed"]),
                "allowed_abstain_tool": str(case["allowed_abstain_tool"]).strip(),
                "abstain_only_when": str(case["abstain_only_when"]).strip(),
                "complexity_bucket": str(case["complexity_bucket"]).strip(),
                "summary_contract": str(case["summary_contract"]).strip(),
                "thickness_setting": str(case["thickness_setting"]).strip(),
                "reasoning_hops_min": int(case["reasoning_hops_min"]),
                "dependency_depth": int(case["dependency_depth"]),
                "expected_intermediate_decisions": list(case["expected_intermediate_decisions"]),
                "abstention_boundary": str(case["abstention_boundary"]).strip(),
                "required_plan_semantic_roles": list(case["required_plan_semantic_roles"]),
                "required_prior_routes": list(case["required_prior_routes"]),
            }
            text_order = (case_index * 2) - 1
            protocol_order = case_index * 2
            tasks.append(
                {
                    **common,
                    "task_order": text_order,
                    "allowed_modes": ["text"],
                    "evidence_text": str(case["text_evidence_text"]).strip(),
                    "task_id": f"{case_id}-text-001",
                    "transfer_strategy": "text_strict_pure_lane",
                    "handoff_profile": "text_strict_pure_lane",
                }
            )
            tasks.append(
                {
                    **common,
                    "task_order": protocol_order,
                    "allowed_modes": ["protocol"],
                    "evidence_text": str(case["protocol_evidence_text"]).strip(),
                    "task_id": f"{case_id}-protocol-001",
                    "transfer_strategy": "state_packet_minimal",
                    "handoff_profile": "protocol_minimal_state_packet",
                }
            )
    return {"task_set": deepcopy(loaded["task_set"]), "tasks": tasks}


def generate_contest_honest_headline_payload(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    benchmark_payload = generate_contest_benchmark_payload(spec)
    task_set = dict(benchmark_payload["task_set"])
    task_set.update(
        {
            "name": CONTEST_HONEST_HEADLINE_NAME,
            "pack_type": "contest_honest_headline_v1",
            "description": (
                "Contest-facing dual-mode formal headline pack with matched natural whole-lane text "
                "and minimal typed-state protocol rows on the same 20 contest-release cases."
            ),
            "reading_contract": (
                "Read this pack only as the contest-facing dual-mode formal headline. "
                "Each pair keeps the same family, query, evidence universe, summary contract, "
                "and plan source fixed; only mode differs, with text using natural whole-lane "
                "handoff and protocol using the minimal typed-state packet."
            ),
            "single_variable": True,
            "variable_axes": ["mode"],
            "public_surface": "formal_headline",
            "evidence_tier": "formal_headline",
        }
    )
    tasks: list[dict[str, Any]] = []
    for task in benchmark_payload["tasks"]:
        row = deepcopy(task)
        if row.get("transfer_strategy") == "text_strict_pure_lane":
            row["transfer_strategy"] = "text_whole_lane"
            row["handoff_profile"] = "text_whole_lane"
            row["evidence_text"] = (
                "Use only the referenced release artifacts. "
                "This row is the contest-facing natural-language whole-lane text baseline."
            )
        tasks.append(row)
    return {"task_set": task_set, "tasks": tasks}


def generate_contest_corpus_payload(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = load_contest_family_spec() if spec is None else deepcopy(spec)
    docs: list[dict[str, Any]] = []
    for family in loaded["families"]:
        task_group = str(family["task_group"]).strip()
        task_theme = str(family["task_theme"]).strip()
        for role in sorted(family["docs"]):
            doc = family["docs"][role]
            docs.append(
                {
                    "doc_id": str(doc["doc_id"]).strip(),
                    "task_group": task_group,
                    "task_theme": task_theme,
                    "title": str(doc["title"]).strip(),
                    "tags": list(doc["tags"]),
                    "eval_route_label": str(doc["eval_route_label"]).strip(),
                    "eval_tool_label": str(doc["eval_tool_label"]).strip(),
                    "text": str(doc["text"]).strip(),
                }
            )
    return {"corpus_metadata": deepcopy(loaded["corpus_metadata"]), "docs": docs}


def _case_order(family: dict[str, Any]) -> list[str]:
    preferred = ["clean", "distractor", "ambiguous", "replay_reusable"]
    available = list((family.get("cases", {}) or {}).keys())
    ordered = [key for key in preferred if key in available]
    ordered.extend(key for key in available if key not in ordered)
    return ordered


def _validate_contest_family_spec(
    *,
    task_set: dict[str, Any],
    corpus_metadata: dict[str, Any],
    families: list[dict[str, Any]],
) -> None:
    if str(task_set.get("pack_type", "")).strip() != "contest_dual_mode_controlled_v3":
        raise ValueError("contest family spec task_set.pack_type must be contest_dual_mode_controlled_v3")
    if bool(task_set.get("formal_structure_clean_retrieval")) is not True:
        raise ValueError("contest family spec must keep formal_structure_clean_retrieval=true")
    if bool(corpus_metadata.get("formal_structure_clean")) is not True:
        raise ValueError("contest family spec corpus_metadata.formal_structure_clean must be true")
    for family in families:
        family_id = str(family.get("family_id", "")).strip() or "<unknown-family>"
        docs = dict(family.get("docs", {}) or {})
        cases = dict(family.get("cases", {}) or {})
        thickness_contract = dict(family.get("thickness_contract", {}) or {})
        normalized_roles = {DOC_ROLE_ALIASES.get(role, role) for role in docs}
        if normalized_roles != REQUIRED_DOC_ROLES:
            missing = sorted(REQUIRED_DOC_ROLES - normalized_roles)
            extra = sorted(normalized_roles - REQUIRED_DOC_ROLES)
            raise ValueError(
                f"{family_id}: docs must cover required roles exactly; missing={missing}, extra={extra}"
            )
        if set(cases) != REQUIRED_CASE_KEYS:
            missing = sorted(REQUIRED_CASE_KEYS - set(cases))
            extra = sorted(set(cases) - REQUIRED_CASE_KEYS)
            raise ValueError(f"{family_id}: cases must be clean/distractor/ambiguous/replay_reusable; missing={missing}, extra={extra}")
        if set(thickness_contract) != REQUIRED_THICKNESS_FAMILY_FIELDS:
            missing = sorted(REQUIRED_THICKNESS_FAMILY_FIELDS - set(thickness_contract))
            extra = sorted(set(thickness_contract) - REQUIRED_THICKNESS_FAMILY_FIELDS)
            raise ValueError(
                f"{family_id}: thickness_contract must define route_competition_min/tool_competition_min exactly; missing={missing}, extra={extra}"
            )
        route_competition = list(family.get("route_competition", []) or [])
        tool_competition = list(family.get("tool_competition", []) or [])
        if int(thickness_contract["route_competition_min"]) > len(route_competition):
            raise ValueError(
                f"{family_id}: route_competition shorter than thickness_contract.route_competition_min"
            )
        if int(thickness_contract["tool_competition_min"]) > len(tool_competition):
            raise ValueError(
                f"{family_id}: tool_competition shorter than thickness_contract.tool_competition_min"
            )
        for case_key, case in cases.items():
            corpus_roles = list(case.get("corpus_doc_roles", []) or [])
            missing_roles = [role for role in corpus_roles if role not in docs]
            if missing_roles:
                raise ValueError(f"{family_id}:{case_key}: unknown corpus_doc_roles={missing_roles}")
            if not corpus_roles:
                raise ValueError(f"{family_id}:{case_key}: corpus_doc_roles must be non-empty")
            if not str(case.get("text_evidence_text", "")).strip():
                raise ValueError(f"{family_id}:{case_key}: text_evidence_text must be non-empty")
            if not str(case.get("protocol_evidence_text", "")).strip():
                raise ValueError(f"{family_id}:{case_key}: protocol_evidence_text must be non-empty")
            missing_fields = sorted(
                field for field in REQUIRED_THICKNESS_CASE_FIELDS if field not in case
            )
            if missing_fields:
                raise ValueError(
                    f"{family_id}:{case_key}: missing required thickness fields={missing_fields}"
                )
            thickness_setting = str(case.get("thickness_setting", "")).strip()
            if thickness_setting not in THICKNESS_SETTINGS:
                raise ValueError(
                    f"{family_id}:{case_key}: unsupported thickness_setting={thickness_setting!r}"
                )
            expected_setting = "S2" if case_key in S2_CASE_KEYS else "S1"
            if thickness_setting != expected_setting:
                raise ValueError(
                    f"{family_id}:{case_key}: expected thickness_setting={expected_setting}, got {thickness_setting}"
                )
            reasoning_hops_min = int(case.get("reasoning_hops_min", 0))
            dependency_depth = int(case.get("dependency_depth", 0))
            if thickness_setting == "S1" and reasoning_hops_min < 2:
                raise ValueError(f"{family_id}:{case_key}: S1 requires reasoning_hops_min >= 2")
            if thickness_setting == "S1" and dependency_depth != 1:
                raise ValueError(f"{family_id}:{case_key}: S1 requires dependency_depth == 1")
            if thickness_setting == "S2" and reasoning_hops_min < 2:
                raise ValueError(f"{family_id}:{case_key}: S2 requires reasoning_hops_min >= 2")
            if thickness_setting == "S2" and dependency_depth < 2:
                raise ValueError(f"{family_id}:{case_key}: S2 requires dependency_depth >= 2")
            intermediate = [
                str(item).strip()
                for item in case.get("expected_intermediate_decisions", [])
                if str(item).strip()
            ]
            if len(intermediate) < 2:
                raise ValueError(
                    f"{family_id}:{case_key}: expected_intermediate_decisions must contain at least two items"
                )
            required_roles = [
                str(item).strip().lower()
                for item in case.get("required_plan_semantic_roles", [])
                if str(item).strip()
            ]
            if required_roles != ["retrieve", "validate", "execute", "summarize"]:
                raise ValueError(
                    f"{family_id}:{case_key}: required_plan_semantic_roles must be retrieve/validate/execute/summarize"
                )
            abstention_boundary = str(case.get("abstention_boundary", "")).strip()
            if case_key in {"ambiguous", "replay_reusable"} and not abstention_boundary:
                raise ValueError(
                    f"{family_id}:{case_key}: ambiguous/replay_reusable must declare abstention_boundary"
                )
            if case_key in {"clean", "distractor"} and not abstention_boundary:
                raise ValueError(
                    f"{family_id}:{case_key}: thickness contract requires a non-empty abstention_boundary description"
                )
        reusable = cases["replay_reusable"]
        if not list(reusable.get("required_prior_case_ids", []) or []):
            raise ValueError(f"{family_id}: replay_reusable must declare required_prior_case_ids")
        if not list(reusable.get("required_prior_rejections", []) or []):
            raise ValueError(f"{family_id}: replay_reusable must declare required_prior_rejections")
        if not list(reusable.get("required_prior_routes", []) or []):
            raise ValueError(f"{family_id}: replay_reusable must declare required_prior_routes")
