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
        tags=["alpha", "beta"],
        metadata={"lane": "statebus"},
    )

    assert slice_view.role == "summarizer"
    assert slice_view.upstream_roles == ("executor",)
    assert slice_view.visible_state_ids == ("state-1",)


def test_context_slice_converts_to_role_io_view() -> None:
    ref = StateRef(state_id="state-2", kind="TOOL_ARTIFACT", length=5)
    slice_view = build_context_slice(
        role="retrieve",
        task_id="task-2",
        mode="text",
        carrier="text",
        visible_state_refs=[ref],
    )

    io_view = slice_view.to_role_io_view()

    assert io_view.role == "retriever"
    assert io_view.visible_state_refs[0].state_id == "state-2"
