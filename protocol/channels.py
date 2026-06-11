from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChannelKind(StrEnum):
    LAST_VALUE = "LastValue"
    TOPIC = "Topic"
    AGGREGATE = "Aggregate"
    EPHEMERAL = "Ephemeral"


@dataclass(frozen=True)
class StateChannel:
    name: str
    kind: ChannelKind
    state_kinds: tuple[str, ...]
    producer_agents: tuple[str, ...] = ()
    consumer_agents: tuple[str, ...] = ()
    schema: str = ""
    replay_compatible: bool = False
    description: str = ""

    def metadata(self) -> dict[str, Any]:
        return {
            "channel_name": self.name,
            "channel_kind": self.kind.value,
            "channel_state_kinds": list(self.state_kinds),
            "channel_schema": self.schema,
            "channel_replay_compatible": self.replay_compatible,
        }


@dataclass(frozen=True)
class StateChannelRegistry:
    channels: dict[str, StateChannel] = field(default_factory=dict)
    by_state_kind: dict[str, tuple[StateChannel, ...]] = field(default_factory=dict)

    def channel(self, name: str) -> StateChannel:
        try:
            return self.channels[name]
        except KeyError as exc:
            raise KeyError(f"unknown state channel: {name}") from exc

    def channel_for_state_kind(self, state_kind: str) -> StateChannel | None:
        candidates = self.by_state_kind.get(state_kind, ())
        if not candidates:
            return None
        return candidates[0]

    def metadata_for_state_kind(self, state_kind: str) -> dict[str, Any]:
        channel = self.channel_for_state_kind(state_kind)
        return {} if channel is None else channel.metadata()


def default_state_channel_registry() -> StateChannelRegistry:
    channels = (
        StateChannel(
            name="evidence",
            kind=ChannelKind.TOPIC,
            state_kinds=("DENSE_EVIDENCE",),
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            replay_compatible=True,
            description="Retrieved evidence and ranking context for downstream steps.",
        ),
        StateChannel(
            name="ranked_evidence",
            kind=ChannelKind.AGGREGATE,
            state_kinds=("RANKED_EVIDENCE_BUNDLE",),
            producer_agents=("retriever",),
            consumer_agents=("summarizer",),
            replay_compatible=True,
            description="Aggregated ranked corpus evidence for summarization and replay audit.",
        ),
        StateChannel(
            name="features",
            kind=ChannelKind.LAST_VALUE,
            state_kinds=(
                "FEATURE_BUNDLE",
                "TOOL_CANDIDATE_SET",
                "REPLAY_ELIGIBILITY_BUNDLE",
                "EXECUTOR_DECISION_PACKET",
            ),
            producer_agents=("retriever",),
            consumer_agents=("executor", "summarizer"),
            replay_compatible=True,
            description="Typed route, tool, and replay-gate state derived from retrieval.",
        ),
        StateChannel(
            name="embedding",
            kind=ChannelKind.EPHEMERAL,
            state_kinds=("EMBEDDING",),
            producer_agents=("retriever",),
            consumer_agents=("summarizer",),
            replay_compatible=True,
            description="Non-text vector state used by memory and replay validation.",
        ),
        StateChannel(
            name="artifact",
            kind=ChannelKind.TOPIC,
            state_kinds=("TOOL_ARTIFACT",),
            producer_agents=("retriever", "executor", "summarizer"),
            consumer_agents=("executor", "summarizer"),
            replay_compatible=True,
            description="Textual tool handoff, execution output, and summary artifacts.",
        ),
    )
    by_name = {channel.name: channel for channel in channels}
    by_kind: dict[str, list[StateChannel]] = {}
    for channel in channels:
        for state_kind in channel.state_kinds:
            by_kind.setdefault(state_kind, []).append(channel)
    return StateChannelRegistry(
        channels=by_name,
        by_state_kind={state_kind: tuple(items) for state_kind, items in by_kind.items()},
    )


def attach_channel_metadata(
    metadata: dict[str, object] | None,
    *,
    state_kind: str,
    registry: StateChannelRegistry | None = None,
) -> dict[str, object]:
    active_registry = registry or default_state_channel_registry()
    return {
        **active_registry.metadata_for_state_kind(state_kind),
        **dict(metadata or {}),
    }
