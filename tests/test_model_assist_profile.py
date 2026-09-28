from __future__ import annotations

import pytest

from statebus.runtime.model_assist import (
    ModelAssistConfig,
    choose_model_assist_route,
    make_observation,
    route_for_profile,
)


def test_model_assist_profiles_route_without_execution_kind() -> None:
    config = ModelAssistConfig(profile="kv_continuation", parent_tokens=128)
    producer = choose_model_assist_route(
        config,
        role="executor",
        kv_ready=True,
        shared_prefix_eligible=True,
    )
    consumer = choose_model_assist_route(
        config,
        role="summarizer",
        kv_ready=True,
        shared_prefix_eligible=True,
        has_compatible_handle=True,
    )
    assert producer.effective_mode == "kv_continuation"
    assert consumer.route_reason == "explicit_same_worker_handle"


@pytest.mark.parametrize(
    ("profile", "requested_mode"),
    (("off", "ordinary"), ("kv_replay", "full_replay"), ("apc", "apc_full_prompt")),
)
def test_model_assist_observation_is_explicit_when_data_is_unavailable(
    profile: str, requested_mode: str
) -> None:
    config = ModelAssistConfig(profile=profile)
    observation = make_observation(config, route=route_for_profile(config, role="executor"))
    assert observation["profile"] == profile
    assert observation["effective_mode"] == "ordinary"
    assert observation["requested_mode"] == requested_mode
    assert observation["observations"]["logit"]["status"] == "unavailable"
