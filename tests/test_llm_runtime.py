from __future__ import annotations

import json
from pathlib import Path

import asyncio

from agents.sample_agents import (
    _plan_from_llm_output,
    _planner_messages,
    _summarizer_messages,
    _summary_from_llm_output,
)
from runtime.llm import DeterministicLLMClient, LLMConfig
from tasks.sample_tasks import SampleTask, build_plan, default_task_chain


def test_llm_config_supports_role_specific_models_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_LLM_MODE", "api")
    monkeypatch.setenv("STATEBUS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STATEBUS_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("STATEBUS_LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("STATEBUS_LLM_PLANNER_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("STATEBUS_LLM_SUMMARIZER_MODEL", "gpt-4.1-mini")

    config = LLMConfig.from_env()

    assert config.use_api is True
    assert config.provider_config("default").base_url == "https://api.deepseek.com"
    assert config.role_config("planner").model == "deepseek-v4-flash"
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
""".strip(),
        encoding="utf-8",
    )

    config = LLMConfig.from_file(config_path)

    assert config.use_api is True
    assert config.source == str(config_path)
    assert config.role_config("planner").extra_body["thinking"]["type"] == "disabled"
    assert config.role_config("summarizer").request_kwargs["top_p"] == 0.8
    assert config.role_config("summarizer").model == "gpt-4.1-mini"


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
    task = default_task_chain()[5]
    output_text = json.dumps(
        {
            "steps": [
                {
                    "step_id": 1,
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
                    "owner_agent": "executor",
                    "action": "EXECUTE_PLAYBOOK",
                    "input_state_refs": [],
                    "params": {},
                    "depends_on": [1],
                },
                {
                    "step_id": 3,
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
    }
    assert task.runtime_gates == {
        "allow_memory_assist": False,
        "allow_execute_prune": False,
        "allow_exact_replay": True,
    }


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
    assert _plan_from_llm_output(task, planner_result.text) == build_plan(task)
    parsed_plan = _plan_from_llm_output(task, planner_result.text)
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
