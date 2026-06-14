from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import msgpack

from protocol.messages import Capability, MemoryCommit, Plan, PlanStep, StateRef, StepResult


class SchemaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StateContract:
    name: str
    kind: str
    producer_agents: tuple[str, ...] = ()
    consumer_agents: tuple[str, ...] = ()
    schema: str = ""
    required_metadata: tuple[str, ...] = ()
    lifecycle: str = "task_scoped"
    replay_compatible: bool = False


@dataclass(frozen=True)
class StepInputSource:
    step_id: str
    include_kinds: tuple[str, ...]
    required_kind_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class StepInputContract:
    agent_id: str
    action: str
    variant: str = "default"
    sources: tuple[StepInputSource, ...] = ()


@dataclass
class StateContractRegistry:
    state_contracts: dict[str, list[StateContract]] = field(default_factory=dict)
    step_input_contracts: dict[tuple[str, str, str], StepInputContract] = field(default_factory=dict)

    def register_state_contract(self, contract: StateContract) -> None:
        self.state_contracts.setdefault(contract.kind, []).append(contract)

    def register_step_input_contract(self, contract: StepInputContract) -> None:
        key = (contract.agent_id, contract.action, contract.variant)
        self.step_input_contracts[key] = contract

    def step_input_contract(
        self,
        *,
        agent_id: str,
        action: str,
        variant: str = "default",
    ) -> StepInputContract:
        key = (agent_id, action, variant)
        contract = self.step_input_contracts.get(key)
        if contract is not None:
            return contract
        if variant != "default":
            fallback = self.step_input_contracts.get((agent_id, action, "default"))
            if fallback is not None:
                return fallback
        raise SchemaValidationError(
            f"missing step input contract for {agent_id}:{action}:{variant}"
        )

    def validate_state_ref(
        self,
        ref: object,
        *,
        producer_agent: str | None = None,
        consumer_agent: str | None = None,
        require_replay_compatible: bool | None = None,
        statepool: object | None = None,
    ) -> StateContract:
        contracts = self.state_contracts.get(getattr(ref, "kind", ""))
        if not contracts:
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} has unregistered kind {getattr(ref, 'kind', '<unknown>')}"
            )
        matches: list[StateContract] = []
        metadata = dict(getattr(ref, "metadata", {}) or {})
        for contract in contracts:
            if producer_agent and contract.producer_agents and producer_agent not in contract.producer_agents:
                continue
            if consumer_agent and contract.consumer_agents and consumer_agent not in contract.consumer_agents:
                continue
            if require_replay_compatible is True and not contract.replay_compatible:
                continue
            if contract.schema and str(metadata.get("schema", "")).strip() != contract.schema:
                continue
            if any(not _metadata_value_present(metadata.get(key)) for key in contract.required_metadata):
                continue
            matches.append(contract)
        if not matches:
            producer_label = producer_agent or "unknown-producer"
            consumer_label = consumer_agent or "unknown-consumer"
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} of kind {getattr(ref, 'kind', '<unknown>')} "
                f"does not satisfy a registered contract for {producer_label}->{consumer_label}"
            )
        matches.sort(key=lambda item: (-len(item.required_metadata), item.name))
        contract = matches[0]
        if statepool is not None and contract.schema:
            self._validate_structured_payload(ref, contract=contract, statepool=statepool)
        return contract

    def _validate_structured_payload(
        self,
        ref: object,
        *,
        contract: StateContract,
        statepool: object,
    ) -> None:
        metadata = dict(getattr(ref, "metadata", {}) or {})
        encoding = str(metadata.get("encoding", "msgpack")).strip() or "msgpack"
        if encoding != "msgpack":
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} expected msgpack encoding, got {encoding}"
            )
        try:
            payload = statepool.get_bytes(ref)
        except Exception as exc:
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} payload could not be loaded"
            ) from exc
        try:
            bundle = msgpack.unpackb(payload, raw=False, strict_map_key=False)
        except Exception as exc:
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} payload is not valid msgpack"
            ) from exc
        if not isinstance(bundle, dict):
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} payload must decode to a map"
            )
        payload_schema = str(bundle.get("schema", "")).strip()
        if payload_schema != contract.schema:
            raise SchemaValidationError(
                f"state {getattr(ref, 'state_id', '<unknown>')} schema mismatch: "
                f"expected {contract.schema}, got {payload_schema or '<missing>'}"
            )


@dataclass
class CapabilityTable:
    by_agent: dict[str, Capability] = field(default_factory=dict)
    by_action: dict[tuple[str, str], object] = field(default_factory=dict)

    def register(self, capability: Capability) -> None:
        self.by_agent[capability.agent_id] = capability
        for item in capability.items:
            self.by_action[(capability.agent_id, item.name)] = item

    def action_item(self, agent_id: str, action: str) -> object:
        key = (agent_id, action)
        if key not in self.by_action:
            raise SchemaValidationError(f"capability not registered for {agent_id}:{action}")
        return self.by_action[key]


class SchemaInterceptor:
    @staticmethod
    def validate_plan(plan: Plan, capability_table: CapabilityTable) -> None:
        if not plan.task_id.strip():
            raise SchemaValidationError("plan.task_id is required")
        if not plan.goal.strip():
            raise SchemaValidationError("plan.goal is required")
        if not plan.steps:
            raise SchemaValidationError("plan.steps must not be empty")
        seen_step_ids: set[str] = set()
        known_step_ids: set[str] = set()
        for step in plan.steps:
            SchemaInterceptor.validate_step(step, capability_table)
            if step.step_id in seen_step_ids:
                raise SchemaValidationError(f"duplicate plan step_id: {step.step_id}")
            missing_deps = [dep for dep in step.depends_on if dep not in known_step_ids]
            if missing_deps:
                raise SchemaValidationError(
                    f"plan step {step.step_id} depends on unknown steps: {', '.join(missing_deps)}"
                )
            seen_step_ids.add(step.step_id)
            known_step_ids.add(step.step_id)

    @staticmethod
    def validate_step(step: PlanStep, capability_table: CapabilityTable) -> None:
        if not step.step_id.strip():
            raise SchemaValidationError("plan_step.step_id is required")
        if not step.owner_agent.strip():
            raise SchemaValidationError(f"plan_step {step.step_id} missing owner_agent")
        if not step.action.strip():
            raise SchemaValidationError(f"plan_step {step.step_id} missing action")
        capability_table.action_item(step.owner_agent, step.action)

    @staticmethod
    def validate_result(
        *,
        step: PlanStep,
        result: StepResult,
        capability_table: CapabilityTable,
        state_contract_registry: StateContractRegistry | None = None,
        statepool: object | None = None,
    ) -> None:
        if result.step_id != step.step_id:
            raise SchemaValidationError(
                f"step result mismatch: expected {step.step_id}, got {result.step_id}"
            )
        item = capability_table.action_item(step.owner_agent, step.action)
        allowed = set(getattr(item, "produced_state_kinds", []))
        if allowed:
            for ref in result.output_state_refs:
                if ref.kind not in allowed:
                    raise SchemaValidationError(
                        f"step {step.step_id} emitted unsupported state kind {ref.kind}"
                    )
                if state_contract_registry is not None:
                    state_contract_registry.validate_state_ref(
                        ref,
                        producer_agent=step.owner_agent,
                        statepool=statepool,
                    )

    @staticmethod
    def validate_input_state_refs(
        *,
        step: PlanStep,
        input_state_refs: list[object],
        capability_table: CapabilityTable,
        state_contract_registry: StateContractRegistry,
        statepool: object | None = None,
        producer_agents_by_state_id: dict[str, str] | None = None,
    ) -> None:
        item = capability_table.action_item(step.owner_agent, step.action)
        allowed = set(getattr(item, "accepted_state_kinds", []))
        if allowed:
            for ref in input_state_refs:
                if getattr(ref, "kind", "") not in allowed:
                    raise SchemaValidationError(
                        f"step {step.step_id} received unsupported state kind {getattr(ref, 'kind', '<unknown>')}"
                    )
        producer_lookup = producer_agents_by_state_id or {}
        for ref in input_state_refs:
            state_contract_registry.validate_state_ref(
                ref,
                producer_agent=producer_lookup.get(getattr(ref, "state_id", "")),
                consumer_agent=step.owner_agent,
                statepool=statepool,
            )

    @staticmethod
    def validate_memory_commit(commit: MemoryCommit) -> None:
        if not commit.memory_id.strip():
            raise SchemaValidationError("memory_commit.memory_id is required")
        if not commit.source_agent_id.strip():
            raise SchemaValidationError("memory_commit.source_agent_id is required")
        if not commit.source_task_id.strip():
            raise SchemaValidationError("memory_commit.source_task_id is required")
        if not commit.task_theme.strip():
            raise SchemaValidationError("memory_commit.task_theme is required")
        if not commit.summary.strip():
            raise SchemaValidationError("memory_commit.summary is required")
        if not commit.evidence_state_ids:
            raise SchemaValidationError("memory_commit.evidence_state_ids must not be empty")
        if commit.evidence_state_refs:
            ref_ids = {ref.state_id for ref in commit.evidence_state_refs}
            missing = [state_id for state_id in commit.evidence_state_ids if state_id not in ref_ids]
            if missing:
                raise SchemaValidationError(
                    "memory_commit.evidence_state_ids missing refs for: " + ", ".join(missing)
                )

    @staticmethod
    def validate_result_memory_commits(result: StepResult) -> None:
        for commit in result.memory_commits:
            SchemaInterceptor.validate_memory_commit(commit)


def default_state_contract_registry() -> StateContractRegistry:
    registry = StateContractRegistry()
    registry.register_state_contract(
        StateContract(
            name="dense_evidence",
            kind="DENSE_EVIDENCE",
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            required_metadata=("channel_name", "channel_kind"),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="feature_bundle",
            kind="FEATURE_BUNDLE",
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            schema="statebus.feature_bundle.v1",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route_source",
                "feature_route_confidence",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="channel_patch",
            kind="CHANNEL_PATCH",
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            schema="statebus.channel_patch.v2",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route_source",
                "feature_route_confidence",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="channel_snapshot",
            kind="CHANNEL_SNAPSHOT",
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            schema="statebus.channel_snapshot.v2",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route_source",
                "feature_route_confidence",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="ranked_evidence_bundle",
            kind="RANKED_EVIDENCE_BUNDLE",
            producer_agents=("retriever",),
            consumer_agents=("summarizer",),
            schema="statebus.ranked_evidence_bundle.v1",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "retrieved_doc_ids",
                "feature_route",
                "feature_route_source",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="tool_candidate_set",
            kind="TOOL_CANDIDATE_SET",
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            schema="statebus.tool_candidate_set.v1",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route",
                "feature_route_source",
                "feature_route_confidence",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="replay_eligibility_bundle",
            kind="REPLAY_ELIGIBILITY_BUNDLE",
            producer_agents=("retriever",),
            consumer_agents=("summarizer",),
            schema="statebus.replay_eligibility_bundle.v1",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route",
                "feature_route_source",
                "feature_route_confidence",
                "feature_route_provenance",
                "retrieved_doc_ids",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="replay_gate",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="executor_decision_packet",
            kind="EXECUTOR_DECISION_PACKET",
            producer_agents=("retriever",),
            consumer_agents=("executor",),
            schema="statebus.executor_decision_packet.v1",
            required_metadata=(
                "channel_name",
                "channel_kind",
                "encoding",
                "schema",
                "query",
                "feature_route",
                "feature_route_source",
                "feature_route_confidence",
                "feature_fresh_evidence_sha256",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="transfer_brief_artifact",
            kind="TOOL_ARTIFACT",
            producer_agents=("retriever",),
            consumer_agents=("executor",),
            required_metadata=(
                "channel_name",
                "channel_kind",
                "query",
                "transfer_strategy",
                "retrieved_doc_ids",
                "feature_route",
                "feature_route_source",
            ),
            lifecycle="task_scoped",
            replay_compatible=False,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="natural_handoff_transfer_brief_artifact",
            kind="TOOL_ARTIFACT",
            producer_agents=("retriever",),
            consumer_agents=("executor",),
            required_metadata=(
                "channel_name",
                "channel_kind",
                "query",
                "transfer_strategy",
                "retrieved_doc_ids",
            ),
            lifecycle="task_scoped",
            replay_compatible=False,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="inline_text_execution_artifact",
            kind="TOOL_ARTIFACT",
            producer_agents=("executor",),
            consumer_agents=("summarizer",),
            required_metadata=(
                "channel_name",
                "channel_kind",
                "tool_name",
                "route",
                "sandbox_mode",
                "transfer_strategy",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="execution_artifact",
            kind="TOOL_ARTIFACT",
            producer_agents=("executor",),
            consumer_agents=("summarizer",),
            required_metadata=(
                "channel_name",
                "channel_kind",
                "source_evidence",
                "source_features",
                "tool_name",
                "route",
                "sandbox_mode",
                "transfer_strategy",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="execution_artifact_natural_handoff",
            kind="TOOL_ARTIFACT",
            producer_agents=("executor",),
            consumer_agents=("summarizer",),
            required_metadata=(
                "channel_name",
                "channel_kind",
                "source_features",
                "tool_name",
                "route",
                "sandbox_mode",
                "transfer_strategy",
            ),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="summary_artifact",
            kind="TOOL_ARTIFACT",
            producer_agents=("summarizer",),
            required_metadata=("channel_name", "channel_kind", "task_theme"),
            lifecycle="memory_summary",
            replay_compatible=False,
        )
    )
    registry.register_state_contract(
        StateContract(
            name="embedding_state",
            kind="EMBEDDING",
            producer_agents=("retriever",),
            consumer_agents=("summarizer",),
            required_metadata=("channel_name", "channel_kind", "encoder_id", "vector_dim", "dtype"),
            lifecycle="task_scoped",
            replay_compatible=True,
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="text_strict_pure_lane",
            sources=(),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="text_whole_lane",
            sources=(),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="state_ref",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=(
                        "DENSE_EVIDENCE",
                        "FEATURE_BUNDLE",
                    ),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("FEATURE_BUNDLE",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="protocol_feature_only_typed_state",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=(
                        "DENSE_EVIDENCE",
                        "FEATURE_BUNDLE",
                    ),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("FEATURE_BUNDLE",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="protocol_full_rich_audit",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=(
                        "DENSE_EVIDENCE",
                        "CHANNEL_SNAPSHOT",
                        "FEATURE_BUNDLE",
                        "TOOL_CANDIDATE_SET",
                    ),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("FEATURE_BUNDLE",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="text_brief",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE", "TOOL_ARTIFACT"),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("TOOL_ARTIFACT",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="text_packet_minimal",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE", "TOOL_ARTIFACT"),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("TOOL_ARTIFACT",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="natural_handoff_text",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(
                        ("TOOL_ARTIFACT",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="state_packet_minimal",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE", "EXECUTOR_DECISION_PACKET"),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("EXECUTOR_DECISION_PACKET",),
                    ),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="executor",
            action="EXECUTE_PLAYBOOK",
            variant="inline_text_handoff",
            sources=(),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="text_strict_pure_lane",
            sources=(
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="text_whole_lane",
            sources=(
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="natural_handoff_text",
            sources=(
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="inline_text_handoff",
            sources=(
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="state_packet_minimal",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE",),
                    required_kind_groups=(("DENSE_EVIDENCE",),),
                ),
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="text_packet_minimal",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE",),
                    required_kind_groups=(("DENSE_EVIDENCE",),),
                ),
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            variant="text_brief",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=("DENSE_EVIDENCE",),
                    required_kind_groups=(("DENSE_EVIDENCE",),),
                ),
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    registry.register_step_input_contract(
        StepInputContract(
            agent_id="summarizer",
            action="SUMMARIZE_AND_COMMIT",
            sources=(
                StepInputSource(
                    step_id="retrieve",
                    include_kinds=(
                        "DENSE_EVIDENCE",
                        "FEATURE_BUNDLE",
                    ),
                    required_kind_groups=(
                        ("DENSE_EVIDENCE",),
                        ("FEATURE_BUNDLE",),
                    ),
                ),
                StepInputSource(
                    step_id="execute",
                    include_kinds=("TOOL_ARTIFACT",),
                    required_kind_groups=(("TOOL_ARTIFACT",),),
                ),
            ),
        )
    )
    return registry


def _metadata_value_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


class InvariantChecker:
    """协议不变量检查器：从Schema定义自动生成，在benchmark中运行"""

    def check_plan(self, plan: Plan) -> list[str]:
        violations: list[str] = []
        if not plan.task_id:
            violations.append("[plan_has_task_id] Plan must have a non-empty task_id")
        if not plan.goal:
            violations.append("[plan_has_goal] Plan must have a non-empty goal")
        if not plan.steps:
            violations.append("[plan_steps_non_empty] Plan must have at least one step")
        step_ids = [s.step_id for s in plan.steps]
        if len(set(step_ids)) != len(step_ids):
            violations.append("[step_ids_unique] Plan step_ids must be unique")
        for step in plan.steps:
            if not step.owner_agent:
                violations.append(f"[step_has_owner] Step {step.step_id} must have an owner_agent")
            if not step.action:
                violations.append(f"[step_has_action] Step {step.step_id} must have an action")
            for dep in step.depends_on:
                if dep not in step_ids:
                    violations.append(
                        f"[deps_reference_valid_steps] Step {step.step_id} depends_on '{dep}' "
                        f"which is not a valid step_id"
                    )
        visited: set[str] = set()
        temp: set[str] = set()

        def _has_cycle(node: str) -> bool:
            if node in temp:
                return True
            if node in visited:
                return False
            temp.add(node)
            for step in plan.steps:
                if step.step_id == node:
                    for dep in step.depends_on:
                        if _has_cycle(dep):
                            return True
                    break
            temp.discard(node)
            visited.add(node)
            return False

        for sid in step_ids:
            if _has_cycle(sid):
                violations.append("[no_circular_deps] Step dependencies must form a DAG")
                break
        return violations

    def check_state_refs(self, refs: list[StateRef]) -> list[str]:
        violations: list[str] = []
        for ref in refs:
            meta = ref.metadata or {}
            if not ref.state_id:
                violations.append("[state_ref_has_id] StateRef must have a non-empty state_id")
            if not ref.kind:
                violations.append(
                    f"[state_ref_has_kind] StateRef {ref.state_id or '<unknown>'} missing kind"
                )
            if ref.length < 0:
                violations.append(
                    f"[state_ref_has_non_negative_length] StateRef {ref.state_id} has negative length"
                )
            has_source_agent = bool(meta.get("source_agent_id"))
            has_created_at = bool(meta.get("created_at"))
            if has_source_agent and not has_created_at:
                violations.append(
                    f"[state_ref_has_created_at] StateRef {ref.state_id} advertises source_agent_id without created_at"
                )
            if has_created_at and not has_source_agent:
                violations.append(
                    f"[state_ref_has_agent_id] StateRef {ref.state_id} advertises created_at without source_agent_id"
                )
        return violations

    def check_results(self, plan: Plan, results: dict[str, StepResult]) -> list[str]:
        violations: list[str] = []
        for step in plan.steps:
            if step.step_id not in results:
                violations.append(
                    f"[result_matches_step] PlanStep {step.step_id} has no corresponding StepResult"
                )
                continue
            result = results[step.step_id]
            if not result.success and not result.error:
                violations.append(
                    f"[error_on_failure] StepResult {step.step_id} failed but has no error message"
                )
        for result_id in results:
            if result_id not in {s.step_id for s in plan.steps}:
                violations.append(
                    f"[result_matches_step] StepResult {result_id} has no corresponding PlanStep"
                )
        return violations
