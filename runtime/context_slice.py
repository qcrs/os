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
    slice_kind: str = ""
    projection_class: str = ""
    included_fields: tuple[str, ...] = ()
    omitted_fields: tuple[str, ...] = ()
    text_budget_class: str = ""
    typed_state_budget_class: str = ""
    role_visible_contract: str = ""
    helper_visibility: str = ""
    model_visibility: str = ""
    tool_visibility: str = ""
    corpus_visibility: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", normalize_comparator_role_name(self.role))
        object.__setattr__(
            self,
            "upstream_roles",
            tuple(
                normalized
                for role in self.upstream_roles
                for normalized in [_maybe_normalize_comparator_role(role)]
                if normalized
            ),
        )
        object.__setattr__(
            self,
            "included_fields",
            tuple(str(field_name).strip() for field_name in self.included_fields if str(field_name).strip()),
        )
        object.__setattr__(
            self,
            "omitted_fields",
            tuple(str(field_name).strip() for field_name in self.omitted_fields if str(field_name).strip()),
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
            slice_kind=self.slice_kind,
            projection_class=self.projection_class,
            included_fields=self.included_fields,
            omitted_fields=self.omitted_fields,
            text_budget_class=self.text_budget_class,
            typed_state_budget_class=self.typed_state_budget_class,
            role_visible_contract=self.role_visible_contract,
            helper_visibility=self.helper_visibility,
            model_visibility=self.model_visibility,
            tool_visibility=self.tool_visibility,
            corpus_visibility=self.corpus_visibility,
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
    slice_kind: str = "",
    projection_class: str = "",
    included_fields: list[str] | tuple[str, ...] | None = None,
    omitted_fields: list[str] | tuple[str, ...] | None = None,
    text_budget_class: str = "",
    typed_state_budget_class: str = "",
    role_visible_contract: str = "",
    helper_visibility: str = "",
    model_visibility: str = "",
    tool_visibility: str = "",
    corpus_visibility: str = "",
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
        slice_kind=str(slice_kind).strip(),
        projection_class=str(projection_class).strip(),
        included_fields=tuple(included_fields or ()),
        omitted_fields=tuple(omitted_fields or ()),
        text_budget_class=str(text_budget_class).strip(),
        typed_state_budget_class=str(typed_state_budget_class).strip(),
        role_visible_contract=str(role_visible_contract).strip(),
        helper_visibility=str(helper_visibility).strip(),
        model_visibility=str(model_visibility).strip(),
        tool_visibility=str(tool_visibility).strip(),
        corpus_visibility=str(corpus_visibility).strip(),
        tags=tuple(str(tag) for tag in (tags or ()) if str(tag).strip()),
        metadata=dict(metadata or {}),
    )


def _maybe_normalize_comparator_role(role: str) -> str:
    try:
        return normalize_comparator_role_name(role)
    except ValueError:
        return ""
