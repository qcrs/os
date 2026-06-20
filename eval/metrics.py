from __future__ import annotations

from dataclasses import asdict, dataclass, field

from runtime.role_contracts import FOUR_ROLE_COMPARATOR_ORDER, normalize_comparator_role_name


@dataclass
class RoleUsageMetrics:
    llm_request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


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
    planner_repair_attempt_count: int = 0
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
    expected_gate_block_count: int = 0
    true_invariant_violation_count: int = 0
    role_usage: dict[str, RoleUsageMetrics] = field(
        default_factory=lambda: {
            role: RoleUsageMetrics() for role in FOUR_ROLE_COMPARATOR_ORDER
        }
    )

    def record_role_llm_usage(
        self,
        *,
        role: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        request_count: int = 1,
    ) -> None:
        usage = self.role_usage.setdefault(
            normalize_comparator_role_name(role),
            RoleUsageMetrics(),
        )
        usage.llm_request_count += request_count
        usage.prompt_tokens += prompt_tokens
        usage.completion_tokens += completion_tokens
        usage.total_tokens += total_tokens

    def record_role_latency(self, *, role: str, elapsed_ms: float) -> None:
        usage = self.role_usage.setdefault(
            normalize_comparator_role_name(role),
            RoleUsageMetrics(),
        )
        usage.latency_ms += elapsed_ms

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
    def planner_one_shot_valid(self) -> float:
        if self.planner_llm_request_count == 0:
            return 1.0
        return 1.0 if self.planner_repair_attempt_count == 0 else 0.0

    @property
    def planner_repair_rate(self) -> float:
        if self.planner_llm_request_count == 0:
            return 0.0
        return min(self.planner_repair_attempt_count / self.planner_llm_request_count, 1.0)

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
        payload["planner_one_shot_valid"] = self.planner_one_shot_valid
        payload["planner_repair_rate"] = self.planner_repair_rate
        payload["phase_accounted_ms"] = self.phase_accounted_ms
        payload["phase_overhead_ms"] = self.phase_overhead_ms
        payload["blob_cache_hit_rate"] = self.blob_cache_hit_rate
        payload["dag_integrity_ok"] = self.dag_integrity_ok
        payload["invariant_violation_count"] = self.true_invariant_violation_count
        return payload
