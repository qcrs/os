from __future__ import annotations

from protocol.messages import StateRef
from runtime.context_slice import build_context_slice


def test_context_slice_normalizes_role_and_tracks_state_ids() -> None:
    ref = StateRef(state_id="state-1", kind="DENSE_EVIDENCE", length=12)

    slice_view = build_context_slice(
        role="summarize",
        task_id="task-1",
        mode="protocol",
        carrier="statebus",
        visible_text="visible handoff",
        visible_state_refs=[ref],
        upstream_roles=["execute"],
        slice_kind="summarizer_visible_slice",
        projection_class="summarizer_statebus_projection",
        included_fields=["summary_hint", "executor_artifact"],
        omitted_fields=["full_typed_packet_dump"],
        text_budget_class="brief",
        typed_state_budget_class="bounded_typed_refs_only",
        role_visible_contract="summarizer_visible_contract_v1",
        helper_visibility="declared_only",
        model_visibility="same_model_required",
        tool_visibility="artifact_only",
        corpus_visibility="retrieved_only",
        tags=["alpha", "beta"],
        metadata={"lane": "statebus"},
    )

    assert slice_view.role == "summarizer"
    assert slice_view.upstream_roles == ("executor",)
    assert slice_view.visible_state_ids == ("state-1",)
    assert slice_view.projection_class == "summarizer_statebus_projection"
    assert slice_view.included_fields == ("summary_hint", "executor_artifact")
    assert slice_view.role_visible_contract == "summarizer_visible_contract_v1"


def test_context_slice_converts_to_role_io_view() -> None:
    ref = StateRef(state_id="state-2", kind="TOOL_ARTIFACT", length=5)
    slice_view = build_context_slice(
        role="retrieve",
        task_id="task-2",
        mode="text",
        carrier="text",
        visible_state_refs=[ref],
        slice_kind="retriever_visible_slice",
        projection_class="retriever_text_brief",
        included_fields=["query"],
        omitted_fields=["typed_state_payloads"],
        text_budget_class="brief",
        typed_state_budget_class="none",
        role_visible_contract="retriever_visible_contract_v1",
        helper_visibility="declared_only",
        model_visibility="same_model_required",
        tool_visibility="catalog_visible",
        corpus_visibility="task_scope_only",
    )

    io_view = slice_view.to_role_io_view()

    assert io_view.role == "retriever"
    assert io_view.visible_state_refs[0].state_id == "state-2"
    assert io_view.projection_class == "retriever_text_brief"
    assert io_view.typed_state_budget_class == "none"
