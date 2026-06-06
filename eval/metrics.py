from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class TaskMetrics:
    message_count: int = 0
    text_chars: int = 0
    text_bytes: int = 0
    protocol_bytes: int = 0
    mmap_state_ref_count: int = 0
    mmap_state_bytes: int = 0
    shared_memory_state_ref_count: int = 0
    shared_memory_state_bytes: int = 0
    state_ref_count: int = 0
    state_bytes: int = 0
    memory_hits: int = 0
    memory_query_count: int = 0
    memory_hit_task_count: int = 0
    planned_step_count: int = 0
    skipped_step_count: int = 0
    llm_request_count: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    task_ms: float = 0.0

    @property
    def memory_hit_rate(self) -> float:
        if self.memory_query_count == 0:
            return 0.0
        return self.memory_hit_task_count / self.memory_query_count

    @property
    def reuse_gain(self) -> float:
        if self.planned_step_count == 0:
            return 0.0
        return self.skipped_step_count / self.planned_step_count

    def to_dict(self) -> dict[str, int | float]:
        payload = asdict(self)
        payload["memory_hit_rate"] = self.memory_hit_rate
        payload["reuse_gain"] = self.reuse_gain
        return payload
