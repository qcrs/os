from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


TASKS_DIR = Path(__file__).resolve().parent
CONTEST_SPEC_PATH = TASKS_DIR / "contest_family_spec.yaml"
CONTEST_BENCHMARK_PATH = TASKS_DIR / "contest_dual_mode_controlled_v3_benchmark.yaml"
CONTEST_CORPUS_PATH = TASKS_DIR / "contest_release_regression_corpus.yaml"


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
