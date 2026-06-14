from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from protocol.messages import Plan, PlanStep
from runtime.reuse_contract import (
    normalize_runtime_reuse_contract,
    resolve_runtime_reuse_contract,
    runtime_reuse_contract_gates,
)
from runtime.task_profile import (
    RuntimeTaskProfile,
    build_reuse_signature,
    normalize_benchmark_lane,
    normalize_handoff_profile,
    normalize_transfer_strategy,
)


DEFAULT_TASKS_DIR = Path(__file__).resolve().parent
DEFAULT_TASK_SET = DEFAULT_TASKS_DIR / "contest_dual_mode_controlled_v3_benchmark.yaml"
DEFAULT_BENCHMARK_TASK_SET = DEFAULT_TASKS_DIR / "contest_dual_mode_controlled_v3_benchmark.yaml"

TASK_SET_ALIASES = {
    "default": "contest_dual_mode_controlled_v3_benchmark.yaml",
    "contest_dual_mode_controlled_v3": "contest_dual_mode_controlled_v3_benchmark.yaml",
    "memory_dual_mode_fairness_v3": "memory_dual_mode_fairness_v3_benchmark.yaml",
    "typed_state_mechanism_v3": "typed_state_mechanism_v3_benchmark.yaml",
    "external_text_baseline_audit_v3": "external_text_baseline_audit_v3_benchmark.yaml",
    "text_definition_audit_v3": "text_definition_audit_v3_benchmark.yaml",
    "typed_state_authenticity_v3": "typed_state_authenticity_v3_benchmark.yaml",
    "typed_state_full_rich_audit_v3": "typed_state_full_rich_audit_v3_benchmark.yaml",
    "carrier_microbench_v3": "carrier_microbench_v3_benchmark.yaml",
    "memory_reuse_v3": "memory_reuse_v3_benchmark.yaml",
    "memory_policy_controlled_v3": "memory_policy_controlled_v3_benchmark.yaml",
    "planner_support_v3": "planner_support_v3_benchmark.yaml",
}

V3_FORMAL_TASK_PACK_TYPES = (
    "contest_dual_mode_controlled_v3",
    "memory_dual_mode_fairness_v3",
    "typed_state_mechanism_v3",
    "external_text_baseline_audit_v3",
    "text_definition_audit_v3",
    "typed_state_authenticity_v3",
    "typed_state_full_rich_audit_v3",
    "carrier_microbench_v3",
    "memory_reuse_v3",
    "memory_policy_controlled_v3",
    "planner_support_v3",
)

TASK_PACK_TYPES = (*V3_FORMAL_TASK_PACK_TYPES, "ad_hoc")

STATE_TRANSFER_THEME_EXPECTATIONS = {
    "contest_release_checkout_regression": {
        "expected_route": "db_pool_saturation",
        "expected_tool_name": "tool.db_pool_triage",
    },
    "contest_release_auth_rotation": {
        "expected_route": "auth_session_drift",
        "expected_tool_name": "tool.auth_session_repair",
    },
    "contest_release_inventory_rollout": {
        "expected_route": "cache_invalidation",
        "expected_tool_name": "tool.cache_invalidation_playbook",
    },
    "contest_release_billing_queue": {
        "expected_route": "worker_queue_starvation",
        "expected_tool_name": "tool.worker_queue_triage",
    },
    "contest_release_billing_queue_backlog": {
        "expected_route": "worker_queue_starvation",
        "expected_tool_name": "tool.worker_queue_triage",
    },
    "contest_release_deployment_config_drift": {
        "expected_route": "db_pool_saturation",
        "expected_tool_name": "tool.db_pool_triage",
    },
}

TASK_MODES = (
    "text",
    "protocol",
)

PLAN_SOURCES = (
    "yaml",
    "llm",
)

COMPLEXITY_BUCKETS = (
    "simple",
    "distractor",
    "ambiguous",
    "reusable",
)

SUMMARY_CONTRACTS = (
    "actions_plus_evidence",
    "protocol_handoff_audit",
)

CASE_TYPES = (
    "exact_single_solution",
    "bounded_alternative",
    "abstention_allowed",
)


def normalize_task_pack_type(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    alias_map = {
        "": "ad_hoc",
        "contest_dual_mode_controlled_v3": "contest_dual_mode_controlled_v3",
        "memory_dual_mode_fairness_v3": "memory_dual_mode_fairness_v3",
        "typed_state_mechanism_v3": "typed_state_mechanism_v3",
        "external_text_baseline_audit_v3": "external_text_baseline_audit_v3",
        "text_definition_audit_v3": "text_definition_audit_v3",
        "typed_state_authenticity_v3": "typed_state_authenticity_v3",
        "typed_state_full_rich_audit_v3": "typed_state_full_rich_audit_v3",
        "carrier_microbench_v3": "carrier_microbench_v3",
        "memory_reuse_v3": "memory_reuse_v3",
        "memory_policy_controlled_v3": "memory_policy_controlled_v3",
        "planner_support_v3": "planner_support_v3",
        "adhoc": "ad_hoc",
        "ad_hoc": "ad_hoc",
    }
    normalized = alias_map.get(text, text)
    if normalized not in TASK_PACK_TYPES:
        raise ValueError(f"unsupported task pack type: {value!r}")
    return normalized


def _normalize_task_pack_type_for_metadata(value: object) -> tuple[str, str]:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return ("ad_hoc", "")
    try:
        return (normalize_task_pack_type(text), "")
    except ValueError:
        return ("ad_hoc", text)


def normalize_plan_source(value: object) -> str:
    text = str(value or "").strip().lower()
    normalized = "yaml" if not text else text
    if normalized not in PLAN_SOURCES:
        raise ValueError(f"unsupported plan_source: {value!r}")
    return normalized


def normalize_case_type(value: object) -> str:
    text = str(value or "").strip().lower()
    normalized = text or "exact_single_solution"
    if normalized not in CASE_TYPES:
        raise ValueError(f"unsupported case_type: {value!r}")
    return normalized


def normalize_complexity_bucket(value: object) -> str:
    text = str(value or "").strip().lower()
    normalized = text or "simple"
    if normalized not in COMPLEXITY_BUCKETS:
        raise ValueError(f"unsupported complexity_bucket: {value!r}")
    return normalized


def normalize_summary_contract(value: object) -> str:
    text = str(value or "").strip().lower()
    normalized = text or "actions_plus_evidence"
    if normalized not in SUMMARY_CONTRACTS:
        raise ValueError(f"unsupported summary_contract: {value!r}")
    return normalized


def normalize_task_modes(values: object) -> tuple[str, ...]:
    if values is None or values == "":
        return TASK_MODES
    if isinstance(values, str):
        candidates = [values]
    else:
        try:
            candidates = list(values)
        except TypeError as exc:
            raise ValueError(f"unsupported allowed_modes payload: {values!r}") from exc
    normalized: list[str] = []
    for value in candidates:
        text = str(value or "").strip().lower()
        if not text:
            continue
        if text not in TASK_MODES:
            raise ValueError(f"unsupported task mode: {value!r}")
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized) if normalized else TASK_MODES


@dataclass(frozen=True)
class TaskSetMetadata:
    name: str
    pack_type: str = "ad_hoc"
    description: str = ""
    reading_contract: str = ""
    claim_lanes: tuple[str, ...] = ()
    single_variable: bool = False
    variable_axes: tuple[str, ...] = ()
    public_surface: str = ""
    evidence_tier: str = "formal_headline"
    benchmark_version: str = "v3"
    historical_pack_type: str = ""

    @property
    def support_only(self) -> bool:
        return self.evidence_tier == "support_only"

    @property
    def audit_only(self) -> bool:
        return self.evidence_tier == "audit_only"

    @property
    def formal_secondary(self) -> bool:
        return self.evidence_tier == "formal_secondary"

    @property
    def historical(self) -> bool:
        return self.evidence_tier in {"historical", "archived"}


@dataclass(frozen=True)
class TaskSetBundle:
    path: Path
    metadata: TaskSetMetadata
    tasks: tuple["SampleTask", ...]


@dataclass(frozen=True)
class SampleTask:
    task_id: str
    task_group: str
    task_order: int
    task_theme: str
    goal: str
    query: str
    tags: tuple[str, ...]
    reuse_tags: tuple[str, ...]
    summary_hint: str
    corpus_doc_ids: tuple[str, ...] = ()
    corpus_path: str = ""
    expected_reuse_mode: str = "none"
    benchmark_lane: str = "internal_regression"
    transfer_strategy: str = "state_ref"
    handoff_profile: str = "protocol_feature_only_typed_state"
    runtime_reuse_contract_override: str = ""
    replay_source_task_id: str = ""
    allow_memory_assist_contract: bool | None = None
    allow_execute_prune_contract: bool | None = None
    allow_exact_replay_contract: bool | None = None
    evidence_text: str = ""
    expected_route: str = ""
    expected_route_source: str = ""
    expected_tool_name: str = ""
    expected_top_doc_id: str = ""
    case_id: str = ""
    case_type: str = "exact_single_solution"
    eval_scope: str = "family_level"
    expected_family: str = ""
    primary_expected_route: str = ""
    primary_expected_tool: str = ""
    acceptable_routes: tuple[str, ...] = ()
    acceptable_tools: tuple[str, ...] = ()
    disallowed_families: tuple[str, ...] = ()
    abstention_allowed: bool = False
    allowed_abstain_tool: str = ""
    abstain_only_when: str = ""
    allowed_modes: tuple[str, ...] = TASK_MODES
    plan_source: str = "yaml"
    complexity_bucket: str = "simple"
    summary_contract: str = "actions_plus_evidence"
    audit_disable_state_kinds: tuple[str, ...] = ()

    @property
    def agent_visible(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "query": self.query,
            "summary_hint": self.summary_hint,
            "evidence_text": self.evidence_text,
            "tags": list(self.tags),
        }

    @property
    def eval_only(self) -> dict[str, object]:
        return {
            "corpus_doc_ids": list(self.corpus_doc_ids),
            "expected_route": self.expected_route,
            "expected_route_source": self.expected_route_source,
            "expected_tool_name": self.expected_tool_name,
            "expected_top_doc_id": self.expected_top_doc_id,
            "acceptable_routes": list(self.acceptable_routes),
            "acceptable_tools": list(self.acceptable_tools),
            "case_contract": self.case_contract,
            "reuse_tags": list(self.reuse_tags),
            "benchmark_lane": self.benchmark_lane,
            "runtime_reuse_contract": self.runtime_reuse_contract,
            "audit_disable_state_kinds": list(self.audit_disable_state_kinds),
        }

    @property
    def expected_reuse(self) -> bool:
        return self.expected_reuse_mode != "none"

    @property
    def artifact_expectations(self) -> dict[str, str]:
        return {
            "route": self.expected_route,
            "route_source": self.expected_route_source,
            "tool_name": self.expected_tool_name,
            "top_doc_id": self.expected_top_doc_id,
        }

    @property
    def case_contract(self) -> dict[str, object]:
        return {
            "case_id": self.case_id or self.task_id,
            "case_type": self.case_type,
            "eval_scope": self.eval_scope,
            "expected_family": self.expected_family,
            "primary_expected_route": self.primary_expected_route,
            "primary_expected_tool": self.primary_expected_tool,
            "acceptable_routes": list(self.acceptable_routes),
            "acceptable_tools": list(self.acceptable_tools),
            "disallowed_families": list(self.disallowed_families),
            "abstention_allowed": self.abstention_allowed,
            "allowed_abstain_tool": self.allowed_abstain_tool,
            "abstain_only_when": self.abstain_only_when,
        }

    @property
    def reuse_signature(self) -> str:
        return build_reuse_signature(self.task_theme, self.reuse_tags or self.tags)

    @property
    def runtime_gates(self) -> dict[str, bool]:
        return runtime_reuse_contract_gates(self.runtime_reuse_contract)

    @property
    def allow_memory_assist(self) -> bool:
        return self.runtime_gates["allow_memory_assist"]

    @property
    def allow_execute_prune(self) -> bool:
        return self.runtime_gates["allow_execute_prune"]

    @property
    def allow_exact_replay(self) -> bool:
        return self.runtime_gates["allow_exact_replay"]

    @property
    def runtime_reuse_contract(self) -> str:
        if self.runtime_reuse_contract_override.strip():
            return normalize_runtime_reuse_contract(self.runtime_reuse_contract_override)
        return resolve_runtime_reuse_contract(
            {
                "expected_reuse_mode": self.expected_reuse_mode,
                "allow_memory_assist": self.allow_memory_assist_contract,
                "allow_execute_prune": self.allow_execute_prune_contract,
                "allow_exact_replay": self.allow_exact_replay_contract,
            }
        )

    @property
    def runtime_profile(self) -> RuntimeTaskProfile:
        return RuntimeTaskProfile(
            runtime_reuse_contract=self.runtime_reuse_contract,
            benchmark_lane=self.benchmark_lane,
            transfer_strategy=self.transfer_strategy,
            handoff_profile=self.handoff_profile,
        )

    def supports_mode(self, mode: str) -> bool:
        return str(mode).strip().lower() in self.allowed_modes


def resolve_task_set_path(path: str | Path | None = None) -> Path:
    if path is None:
        return DEFAULT_TASK_SET.resolve()
    text = str(path).strip()
    if not text:
        return DEFAULT_TASK_SET.resolve()
    alias = TASK_SET_ALIASES.get(text.lower())
    if alias is not None:
        return (DEFAULT_TASKS_DIR / alias).resolve()
    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    repo_relative = DEFAULT_TASKS_DIR.parent / candidate
    if repo_relative.exists():
        return repo_relative.resolve()
    tasks_relative = DEFAULT_TASKS_DIR / candidate
    if tasks_relative.exists():
        return tasks_relative.resolve()
    return candidate.resolve()


def load_task_set_bundle(path: str | Path | None = None) -> TaskSetBundle:
    task_path = resolve_task_set_path(path)
    payload = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    metadata_raw: dict[str, object] = {}
    tasks = payload
    if isinstance(payload, dict):
        metadata_raw = dict(payload.get("task_set", {}) or {})
        tasks = payload["tasks"]
    if not isinstance(tasks, list):
        raise ValueError(f"task set must contain a list of tasks: {task_path}")
    metadata = _load_task_set_metadata(task_path, metadata_raw)
    loaded_tasks = tuple(_load_sample_task(task_path, item) for item in tasks)
    return TaskSetBundle(path=task_path, metadata=metadata, tasks=loaded_tasks)


def load_task_set(path: str | Path | None = None) -> list[SampleTask]:
    return list(load_task_set_bundle(path).tasks)


def default_task_chain() -> list[SampleTask]:
    return load_task_set()


def build_plan(task: SampleTask) -> Plan:
    return Plan(
        task_id=task.task_id,
        goal=task.goal,
        steps=[
            PlanStep(
                step_id="retrieve",
                owner_agent="retriever",
                action="RETRIEVE_EVIDENCE",
                input_state_refs=[],
                params={
                    "query": task.query,
                    "evidence_text": task.evidence_text,
                    "tags": list(task.tags),
                    "allow_memory_reuse": True,
                    "audit_disable_state_kinds": list(task.audit_disable_state_kinds),
                },
                depends_on=[],
            ),
            PlanStep(
                step_id="execute",
                owner_agent="executor",
                action="EXECUTE_PLAYBOOK",
                input_state_refs=[],
                params={},
                depends_on=["retrieve"],
            ),
            PlanStep(
                step_id="summarize",
                owner_agent="summarizer",
                action="SUMMARIZE_AND_COMMIT",
                input_state_refs=[],
                params={
                    "summary_hint": task.summary_hint,
                    "tags": list(task.tags),
                },
                depends_on=["retrieve", "execute"],
            ),
        ],
    )


def _coerce_optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"cannot coerce to bool: {value!r}")


def _resolve_optional_path(task_path: Path, raw_value: object) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    path = Path(text)
    if not path.is_absolute():
        path = task_path.parent / path
    return str(path.resolve())


def _load_task_set_metadata(task_path: Path, raw: dict[str, object]) -> TaskSetMetadata:
    pack_type, historical_pack_type = _normalize_task_pack_type_for_metadata(
        raw.get("pack_type", "ad_hoc")
    )
    claim_lanes = tuple(
        normalize_benchmark_lane(item)
        for item in raw.get("claim_lanes", [])
        if str(item).strip()
    )
    single_variable = bool(raw.get("single_variable", False))
    variable_axes = tuple(
        str(item).strip()
        for item in raw.get("variable_axes", [])
        if str(item).strip()
    )
    public_surface = str(raw.get("public_surface", "")).strip()
    evidence_tier = str(raw.get("evidence_tier", "formal_headline")).strip() or "formal_headline"
    benchmark_version = str(raw.get("benchmark_version", "v3")).strip() or "v3"
    if historical_pack_type:
        evidence_tier = "historical"
        benchmark_version = "historical_v1"
    return TaskSetMetadata(
        name=str(raw.get("name", task_path.stem)).strip() or task_path.stem,
        pack_type=pack_type,
        description=str(raw.get("description", "")).strip(),
        reading_contract=str(raw.get("reading_contract", "")).strip(),
        claim_lanes=claim_lanes,
        single_variable=single_variable,
        variable_axes=variable_axes,
        public_surface=public_surface,
        evidence_tier=evidence_tier,
        benchmark_version=benchmark_version,
        historical_pack_type=historical_pack_type,
    )


def _default_state_transfer_expectations(
    *,
    task_theme: str,
    benchmark_lane: str,
    expected_route: str,
    expected_tool_name: str,
) -> dict[str, str]:
    if benchmark_lane != "state_transfer":
        return {
            "expected_route": expected_route,
            "expected_tool_name": expected_tool_name,
        }
    defaults = STATE_TRANSFER_THEME_EXPECTATIONS.get(task_theme, {})
    return {
        "expected_route": expected_route or str(defaults.get("expected_route", "")).strip(),
        "expected_tool_name": expected_tool_name or str(defaults.get("expected_tool_name", "")).strip(),
    }


def _load_sample_task(task_path: Path, item: dict[str, object]) -> SampleTask:
    task_theme = str(item["task_theme"]).strip()
    benchmark_lane = normalize_benchmark_lane(item.get("benchmark_lane", "internal_regression"))
    expected_route = str(item.get("expected_route", "")).strip()
    expected_tool_name = str(item.get("expected_tool_name", "")).strip()
    default_expectations = _default_state_transfer_expectations(
        task_theme=task_theme,
        benchmark_lane=benchmark_lane,
        expected_route=expected_route,
        expected_tool_name=expected_tool_name,
    )
    case_id = str(item.get("case_id", "")).strip() or str(item["task_id"]).strip()
    expected_family = str(item.get("expected_family", "")).strip() or default_expectations["expected_route"]
    primary_expected_route = (
        str(item.get("primary_expected_route", "")).strip() or default_expectations["expected_route"]
    )
    primary_expected_tool = (
        str(item.get("primary_expected_tool", "")).strip() or default_expectations["expected_tool_name"]
    )
    acceptable_routes = tuple(
        str(value).strip()
        for value in item.get("acceptable_routes", [primary_expected_route])
        if str(value).strip()
    )
    acceptable_tools = tuple(
        str(value).strip()
        for value in item.get("acceptable_tools", [primary_expected_tool] if primary_expected_tool else [])
        if str(value).strip()
    )
    disallowed_families = tuple(
        str(value).strip() for value in item.get("disallowed_families", []) if str(value).strip()
    )
    abstention_allowed = bool(item.get("abstention_allowed", False))
    raw_transfer_strategy = str(item.get("transfer_strategy", "")).strip()
    raw_handoff_profile = str(item.get("handoff_profile", "")).strip()
    transfer_strategy = normalize_transfer_strategy(raw_transfer_strategy or "state_ref")
    if raw_handoff_profile:
        handoff_profile = normalize_handoff_profile(raw_handoff_profile)
    elif raw_transfer_strategy:
        transfer_strategy = normalize_transfer_strategy(raw_transfer_strategy)
        handoff_profile = RuntimeTaskProfile(
            transfer_strategy=transfer_strategy
        ).resolved_handoff_profile
    else:
        handoff_profile = "protocol_feature_only_typed_state"
    task = SampleTask(
        task_id=str(item["task_id"]).strip(),
        task_group=str(item.get("task_group", "default")).strip(),
        task_order=int(item.get("task_order", 0)),
        task_theme=task_theme,
        goal=str(item["goal"]).strip(),
        query=str(item["query"]).strip(),
        tags=tuple(str(tag) for tag in item.get("tags", [])),
        reuse_tags=tuple(str(tag) for tag in item.get("reuse_tags", item.get("tags", []))),
        corpus_doc_ids=tuple(str(doc_id) for doc_id in item.get("corpus_doc_ids", [])),
        corpus_path=_resolve_optional_path(task_path, item.get("corpus_path")),
        expected_reuse_mode=str(
            item.get(
                "expected_reuse_mode",
                "assist" if bool(item.get("expected_reuse", False)) else "none",
            )
        ).strip(),
        benchmark_lane=benchmark_lane,
        transfer_strategy=transfer_strategy,
        handoff_profile=handoff_profile,
        runtime_reuse_contract_override=str(item.get("runtime_reuse_contract", "")).strip(),
        replay_source_task_id=str(item.get("replay_source_task_id", "")).strip(),
        allow_memory_assist_contract=_coerce_optional_bool(item.get("allow_memory_assist")),
        allow_execute_prune_contract=_coerce_optional_bool(item.get("allow_execute_prune")),
        allow_exact_replay_contract=_coerce_optional_bool(item.get("allow_exact_replay")),
        evidence_text=str(item.get("evidence_text", "")).strip(),
        expected_route=default_expectations["expected_route"],
        expected_route_source=str(item.get("expected_route_source", "")).strip(),
        expected_tool_name=default_expectations["expected_tool_name"],
        expected_top_doc_id=str(item.get("expected_top_doc_id", "")).strip(),
        case_id=case_id,
        case_type=normalize_case_type(item.get("case_type", "exact_single_solution")),
        eval_scope=str(item.get("eval_scope", "family_level")).strip() or "family_level",
        expected_family=expected_family,
        primary_expected_route=primary_expected_route,
        primary_expected_tool=primary_expected_tool,
        acceptable_routes=acceptable_routes,
        acceptable_tools=acceptable_tools,
        disallowed_families=disallowed_families,
        abstention_allowed=abstention_allowed,
        allowed_abstain_tool=str(item.get("allowed_abstain_tool", "")).strip(),
        abstain_only_when=str(item.get("abstain_only_when", "")).strip(),
        summary_hint=str(item["summary_hint"]).strip(),
        allowed_modes=normalize_task_modes(item.get("allowed_modes", TASK_MODES)),
        plan_source=normalize_plan_source(item.get("plan_source", "yaml")),
        complexity_bucket=normalize_complexity_bucket(item.get("complexity_bucket", "simple")),
        summary_contract=normalize_summary_contract(
            item.get("summary_contract", "actions_plus_evidence")
        ),
        audit_disable_state_kinds=tuple(
            str(value).strip()
            for value in item.get("audit_disable_state_kinds", [])
            if str(value).strip()
        ),
    )
    _validate_task_profile_contract(task, raw_transfer_strategy=raw_transfer_strategy, raw_handoff_profile=raw_handoff_profile)
    return task


def _validate_task_profile_contract(
    task: SampleTask,
    *,
    raw_transfer_strategy: str,
    raw_handoff_profile: str,
) -> None:
    if "text" in task.allowed_modes and task.handoff_profile != "text_whole_lane" and task.transfer_strategy == "text_whole_lane":
        raise ValueError(f"{task.task_id}: transfer_strategy=text_whole_lane requires handoff_profile=text_whole_lane")
    if task.handoff_profile == "text_whole_lane" and "protocol" in task.allowed_modes:
        raise ValueError(f"{task.task_id}: handoff_profile=text_whole_lane cannot be used in protocol mode")
    if raw_transfer_strategy and not raw_handoff_profile:
        if task.transfer_strategy == "natural_handoff_text" and task.handoff_profile != "protocol_natural_handoff_text":
            raise ValueError(f"{task.task_id}: natural_handoff_text compatibility mapping lost semantic fidelity")
        if task.transfer_strategy == "inline_text_handoff" and task.handoff_profile != "protocol_inline_text_handoff":
            raise ValueError(f"{task.task_id}: inline_text_handoff compatibility mapping lost semantic fidelity")
    if task.transfer_strategy == "state_ref" and task.handoff_profile not in {
        "protocol_feature_only_typed_state",
        "protocol_full_rich_audit",
    }:
        raise ValueError(
            f"{task.task_id}: state_ref must map to protocol_feature_only_typed_state or protocol_full_rich_audit"
        )
    if task.transfer_strategy == "text_whole_lane" and task.handoff_profile != "text_whole_lane":
        raise ValueError(f"{task.task_id}: text_whole_lane must stay on the whole-lane text profile")
    if task.summary_contract == "actions_plus_evidence" and task.handoff_profile == "protocol_full_rich_audit":
        raise ValueError(
            f"{task.task_id}: protocol_full_rich_audit rows must use summary_contract=protocol_handoff_audit"
        )
