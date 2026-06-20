from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from protocol.messages import StateRef
from runtime.role_contracts import RoleIOView, normalize_comparator_role_name


@dataclass(frozen=True)
class LLMContextSlice:
    role: str
    task_id: str
    mode: str
    carrier: str
    visible_text: str = ""
    visible_state_refs: tuple[StateRef, ...] = ()
    upstream_roles: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", normalize_comparator_role_name(self.role))
        object.__setattr__(
            self,
            "upstream_roles",
            tuple(normalize_comparator_role_name(role) for role in self.upstream_roles),
        )

    @property
    def visible_state_ids(self) -> tuple[str, ...]:
        return tuple(ref.state_id for ref in self.visible_state_refs)

    def to_role_io_view(self) -> RoleIOView:
        return RoleIOView(
            role=self.role,
            task_id=self.task_id,
            mode=self.mode,
            carrier=self.carrier,
            visible_text=self.visible_text,
            visible_state_refs=self.visible_state_refs,
            upstream_roles=self.upstream_roles,
            metadata=dict(self.metadata),
        )


def build_context_slice(
    *,
    role: str,
    task_id: str,
    mode: str,
    carrier: str,
    visible_text: str = "",
    visible_state_refs: list[StateRef] | tuple[StateRef, ...] | None = None,
    upstream_roles: list[str] | tuple[str, ...] | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> LLMContextSlice:
    return LLMContextSlice(
        role=role,
        task_id=task_id,
        mode=mode,
        carrier=carrier,
        visible_text=visible_text,
        visible_state_refs=tuple(visible_state_refs or ()),
        upstream_roles=tuple(upstream_roles or ()),
        tags=tuple(str(tag) for tag in (tags or ()) if str(tag).strip()),
        metadata=dict(metadata or {}),
    )
