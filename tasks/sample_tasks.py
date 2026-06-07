from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from protocol.messages import Plan, PlanStep


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
    evidence_text: str = ""

    @property
    def expected_reuse(self) -> bool:
        return self.expected_reuse_mode == "assist"

    @property
    def reuse_signature(self) -> str:
        tags = self.reuse_tags or self.tags
        normalized = "|".join(sorted(set(tags)))
        return f"{self.task_theme}:{normalized}"


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
                    "corpus_doc_ids": list(task.corpus_doc_ids),
                    "evidence_text": task.evidence_text,
                    "tags": list(task.tags),
                    "reuse_tags": list(task.reuse_tags or task.tags),
                    "reuse_signature": task.reuse_signature,
                    "expected_reuse_mode": task.expected_reuse_mode,
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
                    "reuse_tags": list(task.reuse_tags or task.tags),
                    "reuse_signature": task.reuse_signature,
                    "expected_reuse_mode": task.expected_reuse_mode,
                },
                depends_on=["retrieve", "execute"],
            ),
        ],
    )
