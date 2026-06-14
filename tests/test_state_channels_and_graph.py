from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import msgpack

from memory.store import DeterministicEmbeddingProvider
from protocol.channels import ChannelKind, default_state_channel_registry
from agents.sample_agents import build_sample_agents
from runtime.contracts import default_state_contract_registry
from runtime.langgraph_adapter import STATEBUS_GRAPH_NODES, StateBusGraphRunner
from runtime.llm import DeterministicLLMClient
from runtime.orchestrator import Orchestrator
from statepool.store import StatePool, StatePoolConfig
from tasks.sample_tasks import default_task_chain


def test_default_state_channels_describe_typed_handoff_contracts() -> None:
    registry = default_state_channel_registry()
    feature_channel = registry.channel_for_state_kind("CHANNEL_PATCH")
    assert feature_channel is not None
    assert feature_channel.kind == ChannelKind.LAST_VALUE
    assert feature_channel.name == "route"
    assert feature_channel.replay_compatible is True
    assert registry.metadata_for_state_kind("TOOL_CANDIDATE_SET")["channel_name"] == "tool_candidates"
    assert registry.metadata_for_state_kind("DENSE_EVIDENCE")["channel_kind"] == "Topic"


def test_run_context_attaches_channel_metadata_and_contract_accepts_it() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-channel-contract-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id="channel-task-001",
            task_group="channel",
            task_theme="repo_local_cache_triage",
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile={"transfer_strategy": "state_ref"},
        )
        ref = ctx.put_channel_patch(
            state_id="channel-task-001-retrieve-route",
            patch=__import__("protocol.messages", fromlist=["ChannelPatch"]).ChannelPatch(
                channel_name="route",
                ops={"route": "cache_invalidation"},
                patch_id="patch-1",
            ),
            metadata={
                "query": "inventory cache invalidation",
                "feature_route_source": "hint_consensus",
                "feature_route_confidence": 0.91,
                "feature_fresh_evidence_sha256": "a" * 64,
            },
        )
        assert ref.metadata["channel_name"] == "route"
        assert ref.metadata["channel_kind"] == "LastValue"
        payload = msgpack.unpackb(ctx.statepool.get_bytes(ref), raw=False, strict_map_key=False)
        assert payload["channel_name"] == "route"


def test_statepool_cas_deduplicates_and_loads_refs_by_state_id() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-cas-") as tmpdir:
        pool = StatePool(Path(tmpdir), config=StatePoolConfig.from_env())
        first = pool.put_or_dedup_bytes(
            "evidence-a",
            "DENSE_EVIDENCE",
            b"same evidence payload",
        )
        second = pool.put_or_dedup_bytes(
            "evidence-b",
            "DENSE_EVIDENCE",
            b"same evidence payload",
        )
        assert first.storage == "CAS_BLOB"
        assert second.storage == "CAS_BLOB"
        assert first.blob_hash == second.blob_hash
        assert first.metadata["dedup_hit"] is False
        assert second.metadata["dedup_hit"] is True
        assert second.metadata["blob_refcount"] == 2
        assert pool.cas_refcount(first.blob_hash) == 2
        assert pool.get_bytes(second) == b"same evidence payload"
        assert pool.load_ref("evidence-b").blob_hash == first.blob_hash
        summary = pool.cas_summary()
        assert summary["logical_state_count"] == 2
        assert summary["physical_blob_count"] == 1
        assert summary["dedup_hit"] is True
        assert summary["dedup_bytes_saved"] == len(b"same evidence payload")


def test_langgraph_adapter_runs_existing_statebus_graph_path() -> None:
    task = next(task for task in default_task_chain() if task.supports_mode("protocol"))
    runner = StateBusGraphRunner(
        llm_client=DeterministicLLMClient(),
        embedder=DeterministicEmbeddingProvider(),
    )
    result = asyncio.run(runner.run_task(task, mode="protocol"))
    assert result.node_order == STATEBUS_GRAPH_NODES
    assert result.engine == "langgraph"
    assert {"retrieve", "execute", "summarize"}.issubset(result.results)
    assert result.results["summarize"].success is True
    assert result.metrics["planned_step_count"] == 3
    assert result.channel_store or result.state_channels
    assert result.state_channels["artifact"]["state_ref_count"] >= 1
    assert "artifact" in result.state_channels
    assert "evidence" in result.state_channels
    assert result.results["retrieve"].success is True
    assert "task_id" in result.graph_state


def test_text_whole_lane_contract_keeps_executor_and_summarizer_typed_inputs_empty() -> None:
    task = default_task_chain()[0]
    task = task.__class__(**{**task.__dict__, "transfer_strategy": "text_whole_lane", "handoff_profile": "text_whole_lane"})
    orchestrator = Orchestrator(
        build_sample_agents(llm_client=DeterministicLLMClient()),
        state_contract_registry=default_state_contract_registry(),
    )
    with tempfile.TemporaryDirectory(prefix="statebus-text-whole-lane-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="text",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
        )
        asyncio.run(orchestrator.run_task(task, ctx))
        assert ctx.step_input_refs("execute") == []
        summarize_kinds = [ref.kind for ref in ctx.step_input_refs("summarize")]
        assert summarize_kinds == ["TOOL_ARTIFACT"]


def test_text_whole_lane_replay_commit_keeps_proof_refs() -> None:
    task = default_task_chain()[0]
    task = task.__class__(**{**task.__dict__, "transfer_strategy": "text_whole_lane", "handoff_profile": "text_whole_lane"})
    orchestrator = Orchestrator(
        build_sample_agents(llm_client=DeterministicLLMClient()),
        state_contract_registry=default_state_contract_registry(),
    )
    with tempfile.TemporaryDirectory(prefix="statebus-text-whole-lane-proof-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="text",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
        )
        asyncio.run(orchestrator.run_task(task, ctx))
        row = ctx.memory_store.conn.execute(
            """
            SELECT me.state_ref_json
            FROM memories m
            JOIN memory_embeddings me USING(embedding_id)
            WHERE m.memory_id = ?
            """,
            (f"mem-{task.task_id}-replay",),
        ).fetchone()
        assert row is not None
        state_refs = json.loads(row["state_ref_json"])
        state_ref_kinds = {str(ref["kind"]) for ref in state_refs}
        assert "REPLAY_ELIGIBILITY_BUNDLE" in state_ref_kinds
        assert "TOOL_ARTIFACT" in state_ref_kinds
        assert all(kind not in {"FEATURE_BUNDLE", "TOOL_CANDIDATE_SET"} for kind in state_ref_kinds)


def test_text_strict_pure_lane_contract_keeps_executor_and_summarizer_typed_inputs_empty() -> None:
    task = default_task_chain()[0]
    task = task.__class__(**{**task.__dict__, "transfer_strategy": "text_strict_pure_lane", "handoff_profile": "text_strict_pure_lane"})
    orchestrator = Orchestrator(
        build_sample_agents(llm_client=DeterministicLLMClient()),
        state_contract_registry=default_state_contract_registry(),
    )
    with tempfile.TemporaryDirectory(prefix="statebus-text-strict-pure-lane-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="text",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
        )
        asyncio.run(orchestrator.run_task(task, ctx))
        assert ctx.step_input_refs("execute") == []
        summarize_kinds = [ref.kind for ref in ctx.step_input_refs("summarize")]
        assert summarize_kinds == ["TOOL_ARTIFACT"]
