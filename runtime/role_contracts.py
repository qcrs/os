from __future__ import annotations

from dataclasses import dataclass, field

from protocol.messages import StateRef

FOUR_ROLE_COMPARATOR_ORDER = ("planner", "retriever", "executor", "summarizer")
FOUR_ROLE_ROLE_ALIASES = {
    "plan": "planner",
    "planner": "planner",
    "retrieve": "retriever",
    "retriever": "retriever",
    "execute": "executor",
    "executor": "executor",
    "summarize": "summarizer",
    "summarizer": "summarizer",
}


def normalize_comparator_role_name(role: str) -> str:
    normalized = str(role).strip().lower()
    if normalized not in FOUR_ROLE_ROLE_ALIASES:
        raise ValueError(f"unsupported comparator role: {role}")
    return FOUR_ROLE_ROLE_ALIASES[normalized]


@dataclass(frozen=True)
class RoleExecutionContract:
    role: str
    owner_agent: str
    consumes_text_handoff: bool
    consumes_typed_state: bool
    allowed_input_state_kinds: tuple[str, ...] = ()
    allowed_output_state_kinds: tuple[str, ...] = ()
    required_upstream_roles: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", normalize_comparator_role_name(self.role))
        upstream = tuple(normalize_comparator_role_name(role) for role in self.required_upstream_roles)
        object.__setattr__(self, "required_upstream_roles", upstream)


@dataclass(frozen=True)
class RoleIOView:
    role: str
    task_id: str
    mode: str
    carrier: str
    visible_text: str = ""
    visible_state_refs: tuple[StateRef, ...] = ()
    upstream_roles: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", normalize_comparator_role_name(self.role))
        object.__setattr__(self, "upstream_roles", tuple(_filter_comparator_roles(self.upstream_roles)))


def default_role_execution_contracts() -> dict[str, RoleExecutionContract]:
    return {
        "planner": RoleExecutionContract(
            role="planner",
            owner_agent="planner",
            consumes_text_handoff=True,
            consumes_typed_state=False,
            required_upstream_roles=(),
        ),
        "retriever": RoleExecutionContract(
            role="retriever",
            owner_agent="retriever",
            consumes_text_handoff=True,
            consumes_typed_state=True,
            allowed_output_state_kinds=(
                "DENSE_EVIDENCE",
                "FEATURE_BUNDLE",
                "CHANNEL_PATCH",
                "CHANNEL_SNAPSHOT",
                "RANKED_EVIDENCE_BUNDLE",
                "TOOL_CANDIDATE_SET",
                "REPLAY_ELIGIBILITY_BUNDLE",
                "EXECUTOR_DECISION_PACKET",
                "TOOL_ARTIFACT",
                "EMBEDDING",
            ),
            required_upstream_roles=("planner",),
        ),
        "executor": RoleExecutionContract(
            role="executor",
            owner_agent="executor",
            consumes_text_handoff=True,
            consumes_typed_state=True,
            allowed_input_state_kinds=(
                "DENSE_EVIDENCE",
                "FEATURE_BUNDLE",
                "CHANNEL_SNAPSHOT",
                "EXECUTOR_DECISION_PACKET",
                "RANKED_EVIDENCE_BUNDLE",
                "REPLAY_ELIGIBILITY_BUNDLE",
                "TOOL_CANDIDATE_SET",
                "VALIDATION_GATE_PACKET",
                "TOOL_ARTIFACT",
            ),
            allowed_output_state_kinds=("TOOL_ARTIFACT", "VALIDATION_GATE_PACKET"),
            required_upstream_roles=("retriever",),
        ),
        "summarizer": RoleExecutionContract(
            role="summarizer",
            owner_agent="summarizer",
            consumes_text_handoff=True,
            consumes_typed_state=True,
            allowed_input_state_kinds=(
                "DENSE_EVIDENCE",
                "FEATURE_BUNDLE",
                "TOOL_ARTIFACT",
                "EXECUTOR_DECISION_PACKET",
                "RANKED_EVIDENCE_BUNDLE",
                "TOOL_CANDIDATE_SET",
                "REPLAY_ELIGIBILITY_BUNDLE",
                "EMBEDDING",
            ),
            allowed_output_state_kinds=("TOOL_ARTIFACT",),
            required_upstream_roles=("executor",),
        ),
    }


def _filter_comparator_roles(roles: tuple[str, ...]) -> tuple[str, ...]:
    normalized_roles: list[str] = []
    for role in roles:
        try:
            normalized = normalize_comparator_role_name(role)
        except ValueError:
            continue
        normalized_roles.append(normalized)
    return tuple(normalized_roles)
