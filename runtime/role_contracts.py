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
        object.__setattr__(
            self,
            "upstream_roles",
            tuple(normalize_comparator_role_name(role) for role in self.upstream_roles),
        )


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
            allowed_output_state_kinds=("DENSE_EVIDENCE", "RANKED_EVIDENCE_BUNDLE"),
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
                "EXECUTOR_DECISION_PACKET",
                "RANKED_EVIDENCE_BUNDLE",
            ),
            allowed_output_state_kinds=("TOOL_ARTIFACT",),
            required_upstream_roles=("retriever",),
        ),
        "summarizer": RoleExecutionContract(
            role="summarizer",
            owner_agent="summarizer",
            consumes_text_handoff=True,
            consumes_typed_state=True,
            allowed_input_state_kinds=(
                "DENSE_EVIDENCE",
                "TOOL_ARTIFACT",
                "EXECUTOR_DECISION_PACKET",
            ),
            required_upstream_roles=("executor",),
        ),
    }
