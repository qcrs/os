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
    normalize_transfer_strategy,
)


DEFAULT_TASK_SET = Path(__file__).with_name("sample_benchmark.yaml")


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
    expected_reuse_mode: str = "none"
    benchmark_lane: str = "internal_regression"
    transfer_strategy: str = "state_ref"
    runtime_reuse_contract_override: str = ""
    replay_source_task_id: str = ""
    allow_memory_assist_contract: bool | None = None
    allow_execute_prune_contract: bool | None = None
    allow_exact_replay_contract: bool | None = None
    evidence_text: str = ""

    @property
    def expected_reuse(self) -> bool:
        return self.expected_reuse_mode != "none"

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
        )


def load_task_set(path: str | Path | None = None) -> list[SampleTask]:
    task_path = Path(path) if path is not None else DEFAULT_TASK_SET
    payload = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    tasks = payload["tasks"] if isinstance(payload, dict) else payload
    return [
            SampleTask(
                task_id=str(item["task_id"]).strip(),
                task_group=str(item.get("task_group", "default")).strip(),
                task_order=int(item.get("task_order", 0)),
                task_theme=str(item["task_theme"]).strip(),
                goal=str(item["goal"]).strip(),
                query=str(item["query"]).strip(),
                tags=tuple(str(tag) for tag in item.get("tags", [])),
                reuse_tags=tuple(str(tag) for tag in item.get("reuse_tags", item.get("tags", []))),
                corpus_doc_ids=tuple(str(doc_id) for doc_id in item.get("corpus_doc_ids", [])),
                expected_reuse_mode=str(
                    item.get(
                        "expected_reuse_mode",
                        "assist" if bool(item.get("expected_reuse", False)) else "none",
                    )
                ).strip(),
                benchmark_lane=normalize_benchmark_lane(item.get("benchmark_lane", "internal_regression")),
                transfer_strategy=normalize_transfer_strategy(item.get("transfer_strategy", "state_ref")),
                runtime_reuse_contract_override=str(item.get("runtime_reuse_contract", "")).strip(),
                replay_source_task_id=str(item.get("replay_source_task_id", "")).strip(),
                allow_memory_assist_contract=_coerce_optional_bool(item.get("allow_memory_assist")),
                allow_execute_prune_contract=_coerce_optional_bool(item.get("allow_execute_prune")),
                allow_exact_replay_contract=_coerce_optional_bool(item.get("allow_exact_replay")),
                evidence_text=str(item.get("evidence_text", "")).strip(),
                summary_hint=str(item["summary_hint"]).strip(),
            )
            for item in tasks
        ]


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
