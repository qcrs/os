from __future__ import annotations

import json
from pathlib import Path

import asyncio
import pytest

from agents.sample_agents import (
    ExecutorAgent,
    PlannerAgent,
    _canonicalize_planner_dependencies,
    _plan_from_llm_output,
    _build_protocol_summary_input_packet,
    _planner_repair_messages,
    _planner_messages,
    _render_protocol_summary_input_text,
    _summarizer_messages,
    _summary_from_llm_output,
)
from protocol.messages import Capability, CapabilityItem, StepResult
from runtime.llm import ChatMessage, DeterministicLLMClient, LLMConfig, OpenAICompatibleLLMClient
from runtime.llm import LLMResult, LLMUsage
from runtime.llm import ProviderConfig, RoleLLMConfig
from runtime.llm import parse_tagged_json
from runtime.task_profile import RuntimeTaskProfile
from runtime import executor_runtime
from tasks.sample_tasks import SampleTask, build_plan, default_task_chain, load_task_set_bundle


def test_llm_config_supports_role_specific_models_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_LLM_MODE", "api")
    monkeypatch.setenv("STATEBUS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STATEBUS_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("STATEBUS_LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("STATEBUS_LLM_PLANNER_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("STATEBUS_LLM_RETRIEVER_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("STATEBUS_LLM_EXECUTOR_MODEL", "gpt-4.1-nano")
    monkeypatch.setenv("STATEBUS_LLM_SUMMARIZER_MODEL", "gpt-4.1-mini")

    config = LLMConfig.from_env()

    assert config.use_api is True
    assert config.provider_config("default").base_url == "https://api.deepseek.com"
    assert config.role_config("planner").model == "deepseek-v4-flash"
    assert config.role_config("retriever").model == "gpt-4.1-mini"
    assert config.role_config("executor").model == "gpt-4.1-nano"
    assert config.role_config("summarizer").model == "gpt-4.1-mini"


def test_llm_config_supports_yaml_role_decoupling(tmp_path: Path) -> None:
    config_path = tmp_path / "statebus_llm.yaml"
    config_path.write_text(
        """
mode: api
providers:
  deepseek:
    kind: openai_compatible
    base_url: https://api.deepseek.com
    api_key: test-key
roles:
  planner:
    provider: deepseek
    model: deepseek-v4-flash
    json_output: true
    max_tokens: 1200
    extra_body:
      thinking:
        type: disabled
  summarizer:
    provider: deepseek
    model: gpt-4.1-mini
    json_output: true
    request_kwargs:
      top_p: 0.8
  retriever:
    provider: deepseek
    model: gpt-4.1-nano
  executor:
    provider: deepseek
    model: gpt-4.1
""".strip(),
        encoding="utf-8",
    )

    config = LLMConfig.from_file(config_path)

    assert config.use_api is True
    assert config.source == str(config_path)
    assert config.role_config("planner").extra_body["thinking"]["type"] == "disabled"
    assert config.role_config("retriever").model == "gpt-4.1-nano"
    assert config.role_config("executor").model == "gpt-4.1"
    assert config.role_config("summarizer").request_kwargs["top_p"] == 0.8
    assert config.role_config("summarizer").model == "gpt-4.1-mini"


def test_openai_compatible_llm_client_closes_provider_client_per_complete(monkeypatch) -> None:
    created_clients: list[object] = []
    closed_clients: list[object] = []

    class FakeUsage:
        prompt_tokens = 12
        completion_tokens = 5
        total_tokens = 17

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        model = "fake-openai-model"
        usage = FakeUsage()

    class FakeCompletions:
        def __init__(self, owner) -> None:  # type: ignore[no-untyped-def]
            self.owner = owner

        async def create(self, **request):  # type: ignore[no-untyped-def]
            self.owner.requests.append(request)
            return FakeResponse()

    class FakeChat:
        def __init__(self, owner) -> None:  # type: ignore[no-untyped-def]
            self.completions = FakeCompletions(owner)

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs
            self.requests: list[dict[str, object]] = []
            self.chat = FakeChat(self)
            created_clients.append(self)

        async def close(self) -> None:
            closed_clients.append(self)

    monkeypatch.setattr("runtime.llm.AsyncOpenAI", FakeAsyncOpenAI)
    config = LLMConfig(
        mode="api",
        providers={"default": ProviderConfig(api_key="test-key")},
        roles={
            "planner": RoleLLMConfig(provider="default", model="fake-model"),
            "retriever": RoleLLMConfig(provider="default", model="fake-model"),
            "executor": RoleLLMConfig(provider="default", model="fake-model"),
            "summarizer": RoleLLMConfig(provider="default", model="fake-model"),
        },
    )
    client = OpenAICompatibleLLMClient(config)

    first = asyncio.run(client.complete([ChatMessage(role="user", content="hello")], purpose="planner"))
    second = asyncio.run(client.complete([ChatMessage(role="user", content="world")], purpose="planner"))

    assert first.text == '{"ok": true}'
    assert second.model == "fake-openai-model"
    assert len(created_clients) == 2
    assert len(closed_clients) == 2
    assert closed_clients == created_clients


def test_plan_parser_accepts_nested_deepseek_shape() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "retrieve": {
                        "owner_agent": "retriever",
                        "action": "RETRIEVE_EVIDENCE",
                        "params": {
                            "query": task.query,
                            "evidence_text": task.evidence_text,
                            "tags": list(task.tags),
                            "allow_memory_reuse": True,
                        },
                    }
                },
                {
                    "execute": {
                        "owner_agent": "executor",
                        "action": "EXECUTE_PLAYBOOK",
                        "params": {},
                    }
                },
                {
                    "summarize": {
                        "owner_agent": "summarizer",
                        "action": "SUMMARIZE_AND_COMMIT",
                        "params": {
                            "summary_hint": task.summary_hint,
                            "tags": list(task.tags),
                        },
                    }
                },
            ]
        },
        ensure_ascii=False,
    )

    plan = _plan_from_llm_output(task, output_text)
    expected = build_plan(task)

    assert plan == expected


def test_plan_parser_accepts_numeric_step_ids_from_text_llm() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": 1,
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "corpus_doc_ids": list(task.corpus_doc_ids),
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "reuse_tags": list(task.reuse_tags),
                        "reuse_signature": task.reuse_signature,
                        "runtime_reuse_contract": task.runtime_reuse_contract,
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": 2,
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": [1],
                },
                {
                    "step_id": 3,
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                        "reuse_tags": list(task.reuse_tags),
                        "reuse_signature": task.reuse_signature,
                        "runtime_reuse_contract": task.runtime_reuse_contract,
                    },
                    "depends_on": [2],
                },
            ]
        },
        ensure_ascii=False,
    )

    plan = _plan_from_llm_output(task, output_text)

    assert plan == build_plan(task)


def test_plan_parser_requires_explicit_semantic_role_for_non_compact_steps() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "gather-001",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "act-002",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["gather-001"],
                    "semantic_role": "execute",
                },
                {
                    "step_id": "wrap-003",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["gather-001", "act-002"],
                    "semantic_role": "summarize",
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="missing semantic_role"):
        _plan_from_llm_output(task, output_text)


@pytest.mark.asyncio
async def test_deterministic_llm_supports_retriever_and_executor_roles() -> None:
    client = DeterministicLLMClient()

    retriever = await client.complete(
        [
            client_message
            for client_message in [
                type("Msg", (), {"role": "system", "content": "sys"})(),
                type(
                    "Msg",
                    (),
                    {
                        "role": "user",
                        "content": "<sb-retriever-v1>\n"
                        + json.dumps(
                            {
                                "query": "q",
                                "retrieved_doc_ids": ["doc-1"],
                                "tool_candidates": [
                                    {"route": "cache_invalidation", "tool_name": "tool.cache_invalidation_playbook", "score": 3}
                                ],
                                "route_candidates": [
                                    {"route": "cache_invalidation", "tool_name": "tool.cache_invalidation_playbook", "score": 3}
                                ],
                            }
                        )
                        + "\n</sb-retriever-v1>",
                    },
                )(),
            ]
        ],
        purpose="retriever",
    )
    executor = await client.complete(
        [
            type("Msg", (), {"role": "system", "content": "sys"})(),
            type(
                "Msg",
                (),
                {
                    "role": "user",
                    "content": "<sb-executor-v1>\n"
                    + json.dumps(
                        {
                            "route": "cache_invalidation",
                            "tool_name": "tool.cache_invalidation_playbook",
                            "validated_route": "cache_invalidation",
                            "validated_tool_name": "tool.cache_invalidation_playbook",
                            "validated_action_contract": "execute_validated_tool",
                            "tool_candidates": [],
                        }
                    )
                    + "\n</sb-executor-v1>",
                },
            )(),
        ],
        purpose="executor",
    )

    assert json.loads(retriever.text)["tool_name"] == "tool.cache_invalidation_playbook"
    assert json.loads(executor.text)["action_contract"] == "execute_validated_tool"


@pytest.mark.asyncio
async def test_deterministic_llm_supports_compact_v2_retriever_and_executor_payloads() -> None:
    client = DeterministicLLMClient()

    retriever = await client.complete(
        [
            type("Msg", (), {"role": "system", "content": "sys"})(),
            type(
                "Msg",
                (),
                {
                    "role": "user",
                    "content": "<sb-retriever-v1>\n"
                    + json.dumps(
                        {
                            "q": "compare ACME revenue",
                            "rd": ["doc-1", "doc-2"],
                            "tc": [
                                {"r": "compare_metric", "t": "table_retriever", "d": ["doc-1"], "s": ["compare"]},
                                {"r": "summarize_risk", "t": "semantic_retriever", "d": ["doc-2"], "s": ["risk"]},
                            ],
                        }
                    )
                    + "\n</sb-retriever-v1>",
                },
            )(),
        ],
        purpose="retriever",
    )
    executor = await client.complete(
        [
            type("Msg", (), {"role": "system", "content": "sys"})(),
            type(
                "Msg",
                (),
                {
                    "role": "user",
                    "content": "<sb-executor-v1>\n"
                    + json.dumps(
                        {
                            "r": "compare_metric",
                            "t": "table_retriever",
                            "a": "execute_validated_tool",
                            "tc": [
                                {"r": "compare_metric", "t": "table_retriever"},
                                {"r": "summarize_risk", "t": "semantic_retriever"},
                            ],
                        }
                    )
                    + "\n</sb-executor-v1>",
                },
            )(),
        ],
        purpose="executor",
    )

    assert json.loads(retriever.text)["tool_name"] == "table_retriever"
    assert json.loads(executor.text)["action_contract"] == "execute_validated_tool"


@pytest.mark.asyncio
async def test_executor_uses_retrieve_payload_tool_candidates_when_validation_candidates_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ExecutorAgent(
        agent_id="executor",
        capability=Capability(
            agent_id="executor",
            items=[
                CapabilityItem(
                    name="EXECUTE_PLAYBOOK",
                    kind="action",
                    input_schema="step",
                    output_schema="step_result",
                    accepted_state_kinds=["DENSE_EVIDENCE"],
                    produced_state_kinds=["TOOL_ARTIFACT"],
                )
            ],
        ),
        llm_client=DeterministicLLMClient(),
    )

    retrieve_result = type(
        "Result",
        (),
        {
            "payload": {
                "feature_route": "auth_session_drift",
                "feature_tool_name": "tool.auth_session_repair",
                "tool_candidates": [
                    {
                        "route": "auth_session_drift",
                        "tool_name": "tool.auth_session_repair",
                        "score": 7,
                    },
                    {
                        "route": "auth_rate_limit",
                        "tool_name": "tool.auth_rate_limit_triage",
                        "score": 6,
                    },
                ],
                "retrieved_doc_ids": ["rr-auth-incident"],
                "inline_handoff_text": "",
            }
        },
    )()

    class Ctx:
        task_id = "t1"
        task_theme = "contest_auth"
        statepool = None
        runtime_profile = RuntimeTaskProfile()
        mode = "text"
        metrics = type("M", (), {"expected_gate_block_count": 0})()
        task = default_task_chain()[0]

        def transfer_strategy(self):
            return "text_strict_pure_lane"

        def step_input_refs(self, step_id):
            return []

        def record_transfer_inputs(self, refs):
            return None

        def handoff_profile(self):
            return "text_strict_pure_lane"

        def result_for_role(self, role):
            if role == "retrieve":
                return retrieve_result
            return None

        def record_llm_result(self, result, purpose):
            return None

    task = default_task_chain()[0]
    step = build_plan(task).steps[2]

    monkeypatch.setattr(
        "agents.sample_agents.execute_playbook_step",
        lambda **kwargs: StepResult(
            step_id="execute",
            success=True,
            output_state_refs=[],
            semantic_trace={},
            payload={},
        ),
    )

    result = await agent.execute_step(step, Ctx())
    assert result.payload["actual_tool_candidates"] == [
        "auth_session_drift::tool.auth_session_repair",
        "auth_rate_limit::tool.auth_rate_limit_triage",
    ]


@pytest.mark.asyncio
async def test_deterministic_llm_retriever_uses_neutral_query_affinity_ranking_for_visible_candidates() -> None:
    client = DeterministicLLMClient()
    retriever = await client.complete(
        [
            type("Msg", (), {"role": "system", "content": "sys"})(),
            type(
                "Msg",
                (),
                {
                    "role": "user",
                    "content": "<sb-retriever-v1>\n"
                    + json.dumps(
                        {
                            "query": "auth login rate limiter callback issuer",
                            "retrieved_doc_ids": ["doc-1", "doc-2"],
                            "tool_candidates": [
                                {
                                    "route": "auth_rate_limit",
                                    "tool_name": "tool.auth_rate_limit_triage",
                                    "score": 5,
                                    "helper_rank": 1,
                                    "supporting_doc_ids": ["doc-1"],
                                },
                                {
                                    "route": "auth_session_drift",
                                    "tool_name": "tool.auth_session_repair",
                                    "score": 5,
                                    "helper_rank": 2,
                                    "supporting_doc_ids": ["doc-2"],
                                },
                                {
                                    "route": "cache_invalidation",
                                    "tool_name": "tool.cache_invalidation_playbook",
                                    "score": 1,
                                    "helper_rank": 3,
                                    "supporting_doc_ids": ["doc-2"],
                                },
                            ],
                        }
                    )
                    + "\n</sb-retriever-v1>",
                },
            )(),
        ],
        purpose="retriever",
    )

    payload = json.loads(retriever.text)
    assert payload["candidate_rank"] == 1
    assert payload["route"] == "auth_rate_limit"
    assert payload["tool_name"] == "tool.auth_rate_limit_triage"


def test_text_candidate_notes_parse_support_terms_and_doc_count_without_helper_rank_bias() -> None:
    from runtime.llm import _parse_text_candidate_notes

    parsed = _parse_text_candidate_notes(
        "auth_rate_limit::tool.auth_rate_limit_triage|matched_issue_ids=auth_control_surface,traffic_shaping_surface|support_terms=auth,rate,login|support_doc_count=2|support_docs=doc-1,doc-2"
    )

    assert parsed == [
        {
            "route": "auth_rate_limit",
            "tool_name": "tool.auth_rate_limit_triage",
            "matched_issue_ids": ["auth_control_surface", "traffic_shaping_surface"],
            "support_terms": ["auth", "rate", "login"],
            "support_doc_count": 2,
            "supporting_doc_ids": ["doc-1", "doc-2"],
        }
    ]


class _RepairingPlannerClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def complete(self, messages, *, purpose: str, temperature=None):  # type: ignore[no-untyped-def]
        del temperature
        assert purpose == "planner"
        self.calls.append([msg.content for msg in messages])
        if len(self.calls) == 1:
            return LLMResult(
                text=json.dumps(
                    {
                        "steps": [
                            {
                                "step_id": 1,
                                "owner_agent": "retriever",
                                "action": "RETRIEVE_EVIDENCE",
                                "description": "retrieve evidence",
                            },
                            {
                                "step_id": 2,
                                "owner_agent": "executor",
                                "action": "EXECUTE_PLAYBOOK",
                                "semantic_role": "execute",
                                "depends_on": [1],
                                "input_state_refs": [],
                                "params": {},
                            },
                            {
                                "step_id": 3,
                                "owner_agent": "summarizer",
                                "action": "SUMMARIZE_AND_COMMIT",
                                "semantic_role": "summarize",
                                "depends_on": [2],
                                "input_state_refs": [],
                                "params": {
                                    "summary_hint": "h",
                                    "tags": [],
                                },
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                model="test",
                usage=LLMUsage(),
            )
        return LLMResult(
            text=json.dumps(
                {
                    "steps": [
                        {
                            "step_id": "retrieve",
                            "semantic_role": "retrieve",
                            "owner_agent": "retriever",
                            "action": "RETRIEVE_EVIDENCE",
                            "input_state_refs": [],
                            "params": {
                                "query": "q",
                                "evidence_text": "e",
                                "tags": [],
                                "allow_memory_reuse": True,
                            },
                            "depends_on": [],
                        },
                        {
                            "step_id": "validate",
                            "semantic_role": "validate",
                            "owner_agent": "executor",
                            "action": "VALIDATE_ROUTE",
                            "input_state_refs": [],
                            "params": {},
                            "depends_on": ["retrieve"],
                        },
                        {
                            "step_id": "execute",
                            "semantic_role": "execute",
                            "owner_agent": "executor",
                            "action": "EXECUTE_PLAYBOOK",
                            "input_state_refs": [],
                            "params": {},
                            "depends_on": ["retrieve", "validate"],
                        },
                        {
                            "step_id": "summarize",
                            "semantic_role": "summarize",
                            "owner_agent": "summarizer",
                            "action": "SUMMARIZE_AND_COMMIT",
                            "input_state_refs": [],
                            "params": {
                                "summary_hint": "h",
                                "tags": [],
                            },
                            "depends_on": ["retrieve", "execute"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            model="test",
            usage=LLMUsage(),
        )


def test_planner_agent_retries_until_planner_contract_is_valid() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    client = _RepairingPlannerClient()
    agent = PlannerAgent(agent_id="planner", capability=Capability(agent_id="planner", items=[]), llm_client=client)

    class _Ctx:
        mode = "protocol"
        planner_one_shot_valid = True
        planner_repair_attempt_count = 0
        planner_contract_valid = False
        planner_contract_valid_final = False

        class _Metrics:
            planner_repair_attempt_count = 0

        metrics = _Metrics()
        def record_llm_result(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    ctx = _Ctx()
    plan = asyncio.run(agent.plan_task(task, ctx))

    assert [step.semantic_role for step in plan.steps] == ["retrieve", "validate", "execute", "summarize"]
    assert len(client.calls) == 2
    assert ctx.planner_one_shot_valid is False
    assert ctx.planner_repair_attempt_count == 1


def test_plan_parser_rejects_unsupported_memory_reuse_action() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "gather-001",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "reuse-002",
                    "semantic_role": "reuse_check",
                    "owner_agent": "planner",
                    "action": "CHECK_MEMORY_REUSE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["gather-001"],
                },
                {
                    "step_id": "wrap-003",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["gather-001", "reuse-002"],
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="unsupported"):
        _plan_from_llm_output(task, output_text)


def test_planner_prompt_does_not_advertise_unsupported_memory_reuse_action() -> None:
    task = default_task_chain()[0]
    payload = {
        "task_id": task.task_id,
        "task_group": task.task_group,
        "task_theme": task.task_theme,
        "tags": list(task.tags),
        "goal": task.goal,
        "query": task.query,
        "summary_hint": task.summary_hint,
        "evidence_text": task.evidence_text,
    }

    for mode in ("text", "protocol"):
        messages = _planner_messages(payload, mode=mode)
        system_prompt = messages[0].content
        assert "CHECK_MEMORY_REUSE" not in system_prompt
        assert "VALIDATE_ROUTE" in system_prompt


def test_plan_parser_rejects_missing_required_semantic_coverage() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "gather-001",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "check-002",
                    "semantic_role": "validate",
                    "owner_agent": "executor",
                    "action": "VALIDATE_ROUTE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["gather-001"],
                },
                {
                    "step_id": "wrap-003",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["gather-001", "check-002"],
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="missing required semantics: execute"):
        _plan_from_llm_output(task, output_text)


def test_plan_parser_rejects_missing_validate_for_validate_first_task() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "gather-001",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "act-002",
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["gather-001"],
                },
                {
                    "step_id": "wrap-003",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["gather-001", "act-002"],
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="missing required semantics: validate"):
        _plan_from_llm_output(task, output_text)


def test_plan_parser_rejects_semantic_role_owner_action_mismatch() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "retrieve",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "validate",
                    "semantic_role": "validate",
                    "owner_agent": "planner",
                    "action": "VALIDATE_ROUTE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["retrieve"],
                },
                {
                    "step_id": "execute",
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["retrieve", "validate"],
                },
                {
                    "step_id": "summarize",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["retrieve", "execute"],
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="binding mismatch"):
        _plan_from_llm_output(task, output_text)


def test_plan_parser_repairs_execute_action_mislabeled_as_validate_route() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-billing-llm-001"
    )
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "retrieve",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "execute",
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "VALIDATE_ROUTE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["retrieve"],
                },
                {
                    "step_id": "summarize",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["retrieve", "execute"],
                },
            ]
        },
        ensure_ascii=False,
    )

    plan = _plan_from_llm_output(task, output_text)

    assert [step.semantic_role for step in plan.steps] == ["retrieve", "execute", "summarize"]
    execute = next(step for step in plan.steps if step.semantic_role == "execute")
    assert execute.owner_agent == "executor"
    assert execute.action == "EXECUTE_PLAYBOOK"


def test_plan_parser_normalizes_validate_route_dependency_alias_for_summarize() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "retrieve_evidence",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "validate_route",
                    "semantic_role": "validate",
                    "owner_agent": "executor",
                    "action": "VALIDATE_ROUTE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["retrieve_evidence"],
                },
                {
                    "step_id": "execute_playbook",
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["retrieve_evidence", "validate_route"],
                },
                {
                    "step_id": "summarize_and_commit",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["retrieve_evidence", "validate_route", "execute_playbook"],
                },
            ]
        },
        ensure_ascii=False,
    )

    plan = _plan_from_llm_output(task, output_text)

    assert [step.step_id for step in plan.steps] == ["retrieve", "validate", "execute", "summarize"]
    summarize = next(step for step in plan.steps if step.semantic_role == "summarize")
    assert summarize.depends_on == ["retrieve", "validate", "execute"]


def test_canonicalize_planner_dependencies_maps_unique_step_alias() -> None:
    canonicalized = _canonicalize_planner_dependencies(
        normalized_steps=[
            {"step_id": "step_1", "depends_on": []},
            {"step_id": "execute", "depends_on": ["step1"]},
        ]
    )

    assert canonicalized[1]["depends_on"] == ["step_1"]


def test_canonicalize_planner_dependencies_keeps_ambiguous_alias_unresolved() -> None:
    canonicalized = _canonicalize_planner_dependencies(
        normalized_steps=[
            {"step_id": "step_1", "depends_on": []},
            {"step_id": "step-1", "depends_on": []},
            {"step_id": "execute", "depends_on": ["step1"]},
        ]
    )

    assert canonicalized[2]["depends_on"] == ["step1"]


def test_plan_parser_fails_closed_on_ambiguous_dependency_alias() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": "step_1",
                    "semantic_role": "retrieve",
                    "owner_agent": "retriever",
                    "action": "RETRIEVE_EVIDENCE",
                    "input_state_refs": [],
                    "params": {
                        "query": task.query,
                        "evidence_text": task.evidence_text,
                        "tags": list(task.tags),
                        "allow_memory_reuse": True,
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "step-1",
                    "semantic_role": "validate",
                    "owner_agent": "executor",
                    "action": "VALIDATE_ROUTE",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["step_1"],
                },
                {
                    "step_id": "execute",
                    "semantic_role": "execute",
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": ["step1"],
                },
                {
                    "step_id": "summarize",
                    "semantic_role": "summarize",
                    "owner_agent": "summarizer",
                    "action": "SUMMARIZE_AND_COMMIT",
                    "input_state_refs": [],
                    "params": {
                        "summary_hint": task.summary_hint,
                        "tags": list(task.tags),
                    },
                    "depends_on": ["execute"],
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="unknown step_id: step1"):
        _plan_from_llm_output(task, output_text)


def test_plan_builder_keeps_runtime_profile_out_of_live_plan_steps() -> None:
    task = SampleTask(
        task_id="explicit-contract-001",
        task_group="contract_chain",
        task_order=2,
        task_theme="repo_local_contract_probe",
        goal="Check that runtime gates do not collapse back into expectation labels.",
        query="runtime gate separation",
        tags=("contract", "runtime"),
        reuse_tags=("contract", "runtime"),
        summary_hint="Runtime gates should remain explicit.",
        expected_reuse_mode="assist",
        replay_source_task_id="explicit-contract-000",
        allow_memory_assist_contract=False,
        allow_execute_prune_contract=True,
        allow_exact_replay_contract=True,
    )

    plan = build_plan(task)

    assert "expected_reuse_mode" not in plan.steps[0].params
    assert "runtime_reuse_contract" not in plan.steps[0].params
    assert "reuse_signature" not in plan.steps[0].params
    assert "corpus_doc_ids" not in plan.steps[0].params
    assert plan.steps[0].params["allow_memory_reuse"] is True
    assert "runtime_reuse_contract" not in plan.steps[2].params
    assert "reuse_signature" not in plan.steps[2].params
    assert task.runtime_profile.runtime_reuse_contract == "exact_replay"
    assert task.runtime_profile.resolved_benchmark_lane == "internal_regression"
    assert task.runtime_profile.resolved_transfer_strategy == "state_ref"
    assert task.runtime_profile.as_dict() == {
        "runtime_reuse_contract": "exact_replay",
        "benchmark_lane": "internal_regression",
        "transfer_strategy": "state_ref",
        "handoff_profile": "protocol_feature_only_typed_state",
    }
    assert task.runtime_gates == {
        "allow_memory_assist": False,
        "allow_execute_prune": False,
        "allow_exact_replay": True,
    }


def test_runtime_profile_keeps_natural_and_inline_protocol_profiles_distinct() -> None:
    natural = RuntimeTaskProfile.from_mapping({"transfer_strategy": "natural_handoff_text"})
    inline = RuntimeTaskProfile.from_mapping({"transfer_strategy": "inline_text_handoff"})

    assert natural.resolved_handoff_profile == "protocol_natural_handoff_text"
    assert natural.effective_transfer_strategy("protocol") == "natural_handoff_text"
    assert inline.resolved_handoff_profile == "protocol_inline_text_handoff"
    assert inline.effective_transfer_strategy("protocol") == "inline_text_handoff"


def test_runtime_profile_rejects_legacy_mode_split_strategy() -> None:
    with pytest.raises(ValueError, match="unsupported transfer_strategy"):
        RuntimeTaskProfile.from_mapping({"transfer_strategy": "mode_split_text_brief_vs_state_ref"})


def test_runtime_profile_rejects_text_whole_lane_in_protocol_mode() -> None:
    profile = RuntimeTaskProfile.from_mapping({"handoff_profile": "text_whole_lane"})

    try:
        profile.effective_transfer_strategy("protocol")
    except ValueError as exc:
        assert "only valid in mode=text" in str(exc)
    else:
        raise AssertionError("expected protocol mode to reject text_whole_lane")


def test_strict_pure_text_handoff_does_not_call_build_feature_bundle(monkeypatch) -> None:
    def _boom(**_: object) -> dict[str, object]:
        raise AssertionError("build_feature_bundle should not run for text_strict_pure_lane")

    monkeypatch.setattr(executor_runtime, "build_feature_bundle", _boom)
    bundle = executor_runtime._feature_bundle_from_strict_pure_text_handoff(
        query_text="checkout release has pool waits",
        handoff_text="Use release notes and logs only. Connection pool waits increased.",
        registry=executor_runtime.default_tool_registry(),
    )
    assert bundle["transfer_strategy"] == "text_strict_pure_lane"
    assert bundle["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert bundle["tool_candidates"][0]["source"] == "retriever_handoff"
    assert bundle["hint_route"] == ""
    assert bundle["hint_tool_name"] == ""
    assert bundle["hint_doc_ids"] == []
    assert bundle["matched_tags"] == []


def test_summary_parser_normalizes_scalar_reusable_steps() -> None:
    payload = _summary_from_llm_output(
        json.dumps(
            {
                "summary": "db saturation and slow query",
                "confidence": 0.9,
                "tags": ["latency"],
                "reusable_steps": "retrieve",
            }
        )
    )

    assert payload["summary"] == "db saturation and slow query"
    assert payload["reusable_steps"] == ["retrieve"]


def test_summary_parser_normalizes_string_confidence() -> None:
    payload = _summary_from_llm_output(
        json.dumps(
            {
                "summary": "cache invalidation lag",
                "confidence": "high",
                "tags": ["cache"],
                "reusable_steps": ["retrieve", "execute"],
            }
        )
    )

    assert payload["confidence"] == 0.95


def test_text_mode_uses_natural_language_prompts() -> None:
    task = default_task_chain()[0]
    planner_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "corpus_doc_ids": list(task.corpus_doc_ids),
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "reuse_tags": list(task.reuse_tags),
            "reuse_signature": task.reuse_signature,
            "expected_reuse_mode": task.expected_reuse_mode,
            "runtime_reuse_contract": task.runtime_reuse_contract,
            "replay_source_task_id": task.replay_source_task_id,
            "summary_hint": task.summary_hint,
        },
        mode="text",
    )
    protocol_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "corpus_doc_ids": list(task.corpus_doc_ids),
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "expected_reuse_mode": task.expected_reuse_mode,
            "runtime_reuse_contract": task.runtime_reuse_contract,
            "summary_hint": task.summary_hint,
        },
        mode="protocol",
    )
    assert "Planner brief for a text-only multi-agent workflow." in planner_messages[-1].content
    assert "Benchmark reuse expectation:" not in planner_messages[-1].content
    assert "Runtime reuse contract:" not in planner_messages[-1].content
    assert "Corpus docs:" not in planner_messages[-1].content
    assert "<statebus-planner-input>" not in planner_messages[-1].content
    assert "<sb-plan-v1>" in protocol_messages[-1].content
    assert '"erm"' not in protocol_messages[-1].content
    assert '"task_id"' not in protocol_messages[-1].content
    assert '"cd"' not in protocol_messages[-1].content
    assert '"rrc"' not in protocol_messages[-1].content

    validate_task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    validate_messages = _planner_messages(
        {
            "task_id": validate_task.task_id,
            "task_group": validate_task.task_group,
            "task_theme": validate_task.task_theme,
            "goal": validate_task.goal,
            "query": validate_task.query,
            "evidence_text": validate_task.evidence_text,
            "tags": list(validate_task.tags),
            "summary_hint": validate_task.summary_hint,
            "required_plan_semantic_roles": list(validate_task.required_plan_semantic_roles),
        },
        mode="protocol",
    )
    validate_payload = parse_tagged_json(validate_messages[-1].content, "sb-plan-v1")
    assert validate_payload["rr"] == ["retrieve", "validate", "execute", "summarize"]
    assert "Return compact protocol plan JSON with top-level keys r, x, s." in validate_messages[0].content
    assert "Do not emit a top-level steps array." in validate_messages[0].content

    summary_messages = _summarizer_messages(
        {
            "task_id": task.task_id,
            "task_theme": task.task_theme,
            "summary_hint": task.summary_hint,
            "evidence_text": task.evidence_text,
            "actions_text": "rollback release-17",
            "tags": list(task.tags),
            "reusable_steps": ["retrieve", "execute"],
        },
        mode="text",
    )
    assert "Summarizer handoff for a text-only multi-agent workflow." in summary_messages[-1].content
    assert "<statebus-summary-input>" not in summary_messages[-1].content
    protocol_summary_messages = _summarizer_messages(
        {
            "task_id": task.task_id,
            "task_theme": task.task_theme,
            "summary_hint": task.summary_hint,
            "evidence_text": task.evidence_text,
            "actions_text": "rollback release-17",
            "tags": list(task.tags),
            "reusable_steps": ["retrieve", "execute"],
        },
        mode="protocol",
    )
    assert "<sb-summary-v1>" in protocol_summary_messages[-1].content
    assert '"task_theme"' not in protocol_summary_messages[-1].content


def test_deterministic_llm_parses_text_mode_prompts() -> None:
    task = default_task_chain()[0]
    client = DeterministicLLMClient()
    planner_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "corpus_doc_ids": list(task.corpus_doc_ids),
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "reuse_tags": list(task.reuse_tags),
            "reuse_signature": task.reuse_signature,
            "expected_reuse_mode": task.expected_reuse_mode,
            "runtime_reuse_contract": task.runtime_reuse_contract,
            "replay_source_task_id": task.replay_source_task_id,
            "summary_hint": task.summary_hint,
        },
        mode="text",
    )
    planner_result = asyncio.run(client.complete(planner_messages, purpose="planner"))
    assert _plan_from_llm_output(task, planner_result.text) == build_plan(task)

    summary_messages = _summarizer_messages(
        {
            "task_id": task.task_id,
            "task_theme": task.task_theme,
            "summary_hint": task.summary_hint,
            "evidence_text": task.evidence_text,
            "actions_text": "rollback release-17\ncreate orders_created_at index",
            "tags": list(task.tags),
            "reusable_steps": ["retrieve", "execute"],
        },
        mode="text",
    )
    summary_result = asyncio.run(client.complete(summary_messages, purpose="summarizer"))
    payload = _summary_from_llm_output(summary_result.text)
    assert payload["summary"]
    assert payload["reusable_steps"] == ["retrieve", "execute"]


def test_deterministic_llm_uses_compact_protocol_shapes() -> None:
    task = default_task_chain()[0]
    client = DeterministicLLMClient()
    planner_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "corpus_doc_ids": list(task.corpus_doc_ids),
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "reuse_tags": list(task.reuse_tags),
            "reuse_signature": task.reuse_signature,
            "expected_reuse_mode": task.expected_reuse_mode,
            "runtime_reuse_contract": task.runtime_reuse_contract,
            "summary_hint": task.summary_hint,
        },
        mode="protocol",
    )
    planner_result = asyncio.run(client.complete(planner_messages, purpose="planner"))
    planner_payload = json.loads(planner_result.text)
    assert set(planner_payload) == {"r", "s", "x"}
    assert "reuse" not in planner_payload["r"]
    assert "erm" not in planner_payload["r"]
    assert "cd" not in planner_payload["r"]
    assert "rrc" not in planner_payload["r"]
    assert "sig" not in planner_payload["r"]
    parsed_plan = _plan_from_llm_output(task, planner_result.text)
    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]
    assert parsed_plan.steps[0].params["allow_memory_reuse"] is True
    assert "expected_reuse_mode" not in parsed_plan.steps[0].params
    assert "runtime_reuse_contract" not in parsed_plan.steps[0].params
    assert "reuse_signature" not in parsed_plan.steps[0].params
    assert "corpus_doc_ids" not in parsed_plan.steps[0].params

    summary_messages = _summarizer_messages(
        {
            "task_id": task.task_id,
            "task_theme": task.task_theme,
            "summary_hint": task.summary_hint,
            "evidence_text": task.evidence_text,
            "actions_text": "rollback release-17\ncreate orders_created_at index",
            "tags": list(task.tags),
            "reusable_steps": ["retrieve", "execute"],
        },
        mode="protocol",
    )
    summary_result = asyncio.run(client.complete(summary_messages, purpose="summarizer"))
    summary_payload = json.loads(summary_result.text)
    assert set(summary_payload) == {"c", "r", "s", "t"}
    normalized = _summary_from_llm_output(summary_result.text)
    assert normalized["summary"]
    assert normalized["reusable_steps"] == ["retrieve", "execute"]
    assert "Evidence:" not in normalized["summary"]
    assert "Playbook:" not in normalized["summary"]
    assert "Actions:" in normalized["summary"]


def test_deterministic_protocol_planner_validate_path_uses_compact_shape() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    client = DeterministicLLMClient()
    planner_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
            "required_plan_semantic_roles": list(task.required_plan_semantic_roles),
        },
        mode="protocol",
    )

    planner_result = asyncio.run(client.complete(planner_messages, purpose="planner"))
    planner_payload = json.loads(planner_result.text)

    assert set(planner_payload) == {"r", "s", "x"}
    assert planner_payload["x"]["vsid"] == "validate"
    assert planner_payload["x"]["vrole"] == "validate"
    assert planner_payload["x"]["vowner"] == "executor"
    assert planner_payload["x"]["vaction"] == "VALIDATE_ROUTE"
    assert planner_payload["x"]["vdep"] == ["retrieve"]
    assert planner_payload["x"]["dep"] == ["retrieve", "validate"]

    parsed_plan = _plan_from_llm_output(task, planner_result.text)
    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]


def test_compact_protocol_planner_skeleton_falls_back_to_task_payload() -> None:
    task = default_task_chain()[0]
    output_text = json.dumps(
        {
            "r": {
                "sid": "retrieve",
                "role": "retrieve",
                "owner": "retriever",
                "action": "RETRIEVE_EVIDENCE",
                "dep": [],
            },
            "x": {
                "sid": "execute",
                "role": "execute",
                "owner": "executor",
                "action": "EXECUTE_PLAYBOOK",
                "dep": ["retrieve", "validate"],
                "vsid": "validate",
                "vrole": "validate",
                "vowner": "executor",
                "vaction": "VALIDATE_ROUTE",
                "vdep": ["retrieve"],
            },
            "s": {
                "sid": "summarize",
                "role": "summarize",
                "owner": "summarizer",
                "action": "SUMMARIZE_AND_COMMIT",
                "dep": ["retrieve", "execute"],
            },
        }
    )

    parsed_plan = _plan_from_llm_output(task, output_text)

    retrieve_step = parsed_plan.steps[0]
    summarize_step = parsed_plan.steps[-1]
    assert retrieve_step.params["query"] == task.query
    assert retrieve_step.params["evidence_text"] == task.evidence_text
    assert retrieve_step.params["tags"] == list(task.tags)
    assert summarize_step.params["summary_hint"] == task.summary_hint
    assert summarize_step.params["tags"] == list(task.tags)


def test_validate_compact_protocol_planner_skeleton_preserves_validate_dag_and_payload() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "r": {
                "sid": "retrieve",
                "role": "retrieve",
                "owner": "retriever",
                "action": "RETRIEVE_EVIDENCE",
                "dep": [],
            },
            "x": {
                "sid": "execute",
                "role": "execute",
                "owner": "executor",
                "action": "EXECUTE_PLAYBOOK",
                "dep": ["retrieve", "validate"],
                "vsid": "validate",
                "vrole": "validate",
                "vowner": "executor",
                "vaction": "VALIDATE_ROUTE",
                "vdep": ["retrieve"],
            },
            "s": {
                "sid": "summarize",
                "role": "summarize",
                "owner": "summarizer",
                "action": "SUMMARIZE_AND_COMMIT",
                "dep": ["retrieve", "execute"],
            },
        }
    )

    parsed_plan = _plan_from_llm_output(task, output_text)

    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]
    assert parsed_plan.steps[0].params["query"] == task.query
    assert parsed_plan.steps[0].params["evidence_text"] == task.evidence_text
    assert parsed_plan.steps[-1].params["summary_hint"] == task.summary_hint


def test_compact_protocol_planner_accepts_full_key_aliases_and_nested_validate_block() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "r": {
                "step_id": "retrieve",
                "semantic_role": "retrieve",
                "owner_agent": "retriever",
                "action": "RETRIEVE_EVIDENCE",
                "depends_on": [],
                "query": task.query,
                "evidence_text": task.evidence_text,
                "tags": list(task.tags),
            },
            "x": {
                "step_id": "execute",
                "semantic_role": "execute",
                "owner_agent": "executor",
                "action": "EXECUTE_PLAYBOOK",
                "depends_on": ["retrieve", "validate"],
                "validate": {
                    "step_id": "validate",
                    "semantic_role": "validate",
                    "owner_agent": "executor",
                    "action": "VALIDATE_ROUTE",
                    "depends_on": ["retrieve"],
                },
            },
            "s": {
                "step_id": "summarize",
                "semantic_role": "summarize",
                "owner_agent": "summarizer",
                "action": "SUMMARIZE_AND_COMMIT",
                "depends_on": ["retrieve", "execute"],
                "summary_hint": task.summary_hint,
                "tags": list(task.tags),
            },
        }
    )

    parsed_plan = _plan_from_llm_output(task, output_text)

    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]
    assert parsed_plan.steps[0].params["query"] == task.query
    assert parsed_plan.steps[-1].params["summary_hint"] == task.summary_hint


def test_compact_protocol_planner_normalizes_agent_noun_semantic_role_aliases() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "r": {
                "sid": "retrieve",
                "role": "retriever",
                "owner": "retriever",
                "action": "RETRIEVE_EVIDENCE",
                "dep": [],
            },
            "x": {
                "sid": "execute",
                "role": "executor",
                "owner": "executor",
                "action": "EXECUTE_PLAYBOOK",
                "dep": ["retrieve", "validate"],
                "vsid": "validate",
                "vrole": "validator",
                "vowner": "executor",
                "vaction": "VALIDATE_ROUTE",
                "vdep": ["retrieve"],
            },
            "s": {
                "sid": "summarize",
                "role": "summarizer",
                "owner": "summarizer",
                "action": "SUMMARIZE_AND_COMMIT",
                "dep": ["retrieve", "execute"],
            },
        }
    )

    parsed_plan = _plan_from_llm_output(task, output_text)

    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]


def test_compact_protocol_planner_repairs_swapped_validate_and_execute_slots() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    output_text = json.dumps(
        {
            "r": {
                "sid": "retrieve",
                "role": "retrieve",
                "owner": "retriever",
                "action": "RETRIEVE_EVIDENCE",
                "dep": [],
            },
            "x": {
                "sid": "validate",
                "role": "validate",
                "owner": "executor",
                "action": "VALIDATE_ROUTE",
                "dep": ["retrieve"],
                "vsid": "execute",
                "vrole": "execute",
                "vowner": "executor",
                "vaction": "EXECUTE_PLAYBOOK",
                "vdep": ["retrieve", "validate"],
            },
            "s": {
                "sid": "summarize",
                "role": "summarize",
                "owner": "summarizer",
                "action": "SUMMARIZE_AND_COMMIT",
                "dep": ["retrieve", "execute"],
            },
        }
    )

    parsed_plan = _plan_from_llm_output(task, output_text)

    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.step_id for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    assert [step.depends_on for step in parsed_plan.steps] == [
        [],
        ["retrieve"],
        ["retrieve", "validate"],
        ["retrieve", "execute"],
    ]


def test_protocol_summarizer_prompt_avoids_duplicate_top_level_fields() -> None:
    packet = _build_protocol_summary_input_packet(
        query="query",
        route="generic_triage",
        route_source="protocol",
        route_confidence=0.91,
        retrieved_doc_ids=["doc-1", "doc-2"],
        matched_signals=["signal-a"],
        actions_text="restart worker",
        summary_hint="mention rollback",
        memory_assist_hint="reused prior auth fix",
    )
    messages = _summarizer_messages(
        {
            "task_id": "task-1",
            "task_theme": "theme-1",
            "summary_hint": "mention rollback",
            "evidence_text": _render_protocol_summary_input_text(packet),
            "actions_text": "restart worker",
            "tags": ["ops"],
            "reusable_steps": ["retrieve", "execute"],
        },
        mode="protocol",
    )

    payload = parse_tagged_json(messages[-1].content, "sb-summary-v1")
    assert set(payload) == {"a", "e", "h", "r", "t"}
    assert payload["h"] == "mention rollback"
    assert payload["a"] == "restart worker"
    assert payload["e"]
    assert payload["r"] == ["retrieve", "execute"]
    assert payload["t"] == ["ops"]
    assert '"schema"' not in messages[-1].content
    assert '{"schema"' not in payload["e"]


def test_compact_protocol_retriever_and_executor_parsers_accept_inline_evidence() -> None:
    from runtime.llm import parse_compact_protocol_executor_handoff, parse_compact_protocol_retriever_handoff

    retriever_payload = parse_compact_protocol_retriever_handoff(
        '<sb-retriever-v1>\n'
        + json.dumps(
            {
                "q": "auth session issue",
                "rd": ["doc-1"],
                "e": "line1\nline2",
                "tc": [{"r": "auth_session_drift", "t": "semantic_retriever"}],
            }
        )
        + "\n</sb-retriever-v1>"
    )
    executor_payload = parse_compact_protocol_executor_handoff(
        '<sb-executor-v1>\n'
        + json.dumps(
            {
                "r": "auth_session_drift",
                "t": "semantic_retriever",
                "a": "execute_validated_tool",
                "e": "line1\nline2",
                "tc": [{"r": "auth_session_drift", "t": "semantic_retriever"}],
            }
        )
        + "\n</sb-executor-v1>"
    )

    assert retriever_payload["evidence_text"] == "line1\nline2"
    assert executor_payload["evidence_text"] == "line1\nline2"


def test_render_protocol_summary_input_text_is_flat_text_handoff() -> None:
    packet = _build_protocol_summary_input_packet(
        query="query",
        route="db_pool_saturation",
        route_source="protocol",
        route_confidence=0.91,
        retrieved_doc_ids=["doc-1", "doc-2", "doc-3", "doc-4"],
        matched_signals=["signal-a", "signal-b", "signal-c", "signal-d", "signal-e"],
        actions_text="restart worker\nverify pool cap\nrecheck queue depth",
        summary_hint="mention rollback boundary",
        memory_assist_hint="reused prior auth fix",
    )

    rendered = _render_protocol_summary_input_text(packet)

    assert rendered.startswith("q: query\n")
    assert "route: db_pool_saturation" in rendered
    assert "src: protocol" not in rendered
    assert "conf: 0.91" not in rendered
    assert "docs: doc-1, doc-2, doc-3" in rendered
    assert "doc-4" not in rendered
    assert "signals: signal-a, signal-b, signal-c, signal-d" in rendered
    assert "signal-e" not in rendered
    assert "mention rollback boundary" not in rendered
    assert "restart worker" not in rendered
    assert "verify pool cap" not in rendered
    assert "mem: reused prior auth fix" in rendered
    assert '"schema"' not in rendered
    assert '{"schema"' not in rendered
    assert '\\"schema\\"' not in rendered


def test_protocol_planner_prompts_bias_canonical_steps_without_relaxing_contract() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    protocol_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
            "required_plan_semantic_roles": list(task.required_plan_semantic_roles),
        },
        mode="protocol",
    )
    text_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
            "required_plan_semantic_roles": list(task.required_plan_semantic_roles),
        },
        mode="text",
    )
    repair_messages = _planner_repair_messages(
        base_messages=protocol_messages,
        invalid_output='{"steps":[{"step_id":"step1"}]}',
        validation_error="planner step missing semantic_role",
        required_plan_semantic_roles=list(task.required_plan_semantic_roles),
        mode="protocol",
    )

    protocol_system = protocol_messages[0].content
    text_system = text_messages[0].content
    repair_prompt = repair_messages[-1].content

    assert "Prefer canonical step_id values retrieve, validate, execute, summarize" in protocol_system
    assert "Allowed semantic_role values exactly: retrieve, validate, execute, summarize." in protocol_system
    assert "Do not use retriever, validator, executor, or summarizer as semantic_role values." in protocol_system
    assert "The x slot body itself must encode execute, and the vsid/vrole/vowner/vaction/vdep fields must encode validate." in protocol_system
    assert "Do not swap execute and validate between the x slot body and the nested v* fields." in protocol_system
    assert 'depends_on=[] for retrieve' in protocol_system
    assert 'depends_on=["retrieve","execute"] for summarize' in protocol_system
    assert "Return compact protocol plan JSON with top-level keys r, x, s." in protocol_system
    assert "Inside each slot prefer compact keys sid, role, owner, action, dep; include q, e, t in r and h, t in s." in protocol_system
    assert "Do not emit a top-level steps array." in protocol_system
    assert "Do not omit semantic_role on any encoded step." in protocol_system
    assert "No markdown." in protocol_system

    assert "Prefer canonical step_id values retrieve, validate, execute, summarize" in repair_prompt
    assert "Allowed semantic_role values exactly: retrieve, validate, execute, summarize." in repair_prompt
    assert "Do not use retriever, validator, executor, or summarizer as semantic_role values." in repair_prompt
    assert "The x slot body itself must encode execute, and the vsid/vrole/vowner/vaction/vdep fields must encode validate." in repair_prompt
    assert "Do not swap execute and validate between the x slot body and the nested v* fields." in repair_prompt
    assert "Inside each slot prefer compact keys sid, role, owner, action, dep; include q, e, t in r and h, t in s." in repair_prompt
    assert "Every depends_on entry must exactly reference a step_id implied by the compact output." in repair_prompt
    assert "Return top-level keys r, x, s only." in repair_prompt
    assert "Do not emit a top-level steps array." in repair_prompt

    assert "Planner brief for a text-only multi-agent workflow." in text_messages[-1].content
    assert "You are the StateBus Planner in a text-only collaboration baseline." in text_system
    assert "Prefer canonical step_id values retrieve, validate, execute, summarize" not in text_system


def test_deterministic_llm_emits_validate_step_when_task_contract_requires_it() -> None:
    task = next(
        item
        for item in load_task_set_bundle("planner_support_v3").tasks
        if item.task_id == "planner-support-auth-llm-002"
    )
    client = DeterministicLLMClient()
    planner_messages = _planner_messages(
        {
            "task_id": task.task_id,
            "task_group": task.task_group,
            "task_theme": task.task_theme,
            "goal": task.goal,
            "query": task.query,
            "evidence_text": task.evidence_text,
            "tags": list(task.tags),
            "summary_hint": task.summary_hint,
            "required_plan_semantic_roles": list(task.required_plan_semantic_roles),
        },
        mode="protocol",
    )

    planner_result = asyncio.run(client.complete(planner_messages, purpose="planner"))
    planner_payload = json.loads(planner_result.text)
    assert set(planner_payload) == {"r", "s", "x"}
    assert planner_payload["x"]["vsid"] == "validate"
    parsed_plan = _plan_from_llm_output(task, planner_result.text)

    assert [step.semantic_role for step in parsed_plan.steps] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
