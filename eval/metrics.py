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
    handoff_ref_count: int = 0
    handoff_bytes: int = 0
    handoff_payload_bytes: int = 0
    handoff_wire_bytes: int = 0
    handoff_textual_ref_count: int = 0
    handoff_textual_bytes: int = 0
    handoff_nontext_ref_count: int = 0
    handoff_nontext_bytes: int = 0
    memory_hits: int = 0
    memory_query_count: int = 0
    memory_hit_task_count: int = 0
    replay_probe_count: int = 0
    replay_probe_hits: int = 0
    replay_probe_hit_task_count: int = 0
    memory_assist_task_count: int = 0
    memory_assist_prior_applied_task_count: int = 0
    memory_assist_candidate_reduction: int = 0
    memory_assist_route_agreement_task_count: int = 0
    memory_assist_rescue_task_count: int = 0
    validated_reuse_task_count: int = 0
    memory_rejected_task_count: int = 0
    planned_step_count: int = 0
    skipped_step_count: int = 0
    llm_request_count: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    planner_llm_request_count: int = 0
    planner_prompt_tokens: int = 0
    planner_completion_tokens: int = 0
    planner_total_tokens: int = 0
    summarizer_llm_request_count: int = 0
    summarizer_prompt_tokens: int = 0
    summarizer_completion_tokens: int = 0
    summarizer_total_tokens: int = 0
    planner_ms: float = 0.0
    retrieve_ms: float = 0.0
    execute_ms: float = 0.0
    summarize_ms: float = 0.0
    task_ms: float = 0.0
    blob_fetch_count: int = 0
    blob_fetch_bytes: int = 0
    blob_fetch_hits: int = 0
    trajectory_step_count: int = 0
    trajectory_commit_count: int = 0
    trajectory_diff_count: int = 0
    dag_integrity_check_count: int = 0
    dag_integrity_violation_count: int = 0
    invariant_check_count: int = 0
    invariant_violation_count: int = 0

    @property
    def assist_memory_hit_rate(self) -> float:
        if self.memory_query_count == 0:
            return 0.0
        return self.memory_hit_task_count / self.memory_query_count

    @property
    def memory_hit_rate(self) -> float:
        return self.assist_memory_hit_rate

    @property
    def replay_probe_hit_rate(self) -> float:
        if self.replay_probe_count == 0:
            return 0.0
        return self.replay_probe_hit_task_count / self.replay_probe_count

    @property
    def reuse_gain(self) -> float:
        if self.planned_step_count == 0:
            return 0.0
        return self.skipped_step_count / self.planned_step_count

    @property
    def replay_apply_rate(self) -> float:
        if self.replay_probe_count == 0:
            return 0.0
        return self.validated_reuse_task_count / self.replay_probe_count

    @property
    def phase_accounted_ms(self) -> float:
        return self.planner_ms + self.retrieve_ms + self.execute_ms + self.summarize_ms

    @property
    def phase_overhead_ms(self) -> float:
        return max(self.task_ms - self.phase_accounted_ms, 0.0)

    @property
    def blob_cache_hit_rate(self) -> float:
        if self.blob_fetch_count == 0:
            return 0.0
        return self.blob_fetch_hits / self.blob_fetch_count

    @property
    def dag_integrity_ok(self) -> float:
        return 1.0 if self.dag_integrity_violation_count == 0 else 0.0

    def to_dict(self) -> dict[str, int | float]:
        payload = asdict(self)
        payload["assist_memory_hit_rate"] = self.assist_memory_hit_rate
        payload["replay_probe_hit_rate"] = self.replay_probe_hit_rate
        payload["replay_apply_rate"] = self.replay_apply_rate
        payload["reuse_gain"] = self.reuse_gain
        payload["phase_accounted_ms"] = self.phase_accounted_ms
        payload["phase_overhead_ms"] = self.phase_overhead_ms
        payload["blob_cache_hit_rate"] = self.blob_cache_hit_rate
        payload["dag_integrity_ok"] = self.dag_integrity_ok
        return payload
