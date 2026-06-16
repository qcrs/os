from __future__ import annotations

import tempfile
from pathlib import Path

import msgpack
import pytest

from protocol import statebus_pb2
from protocol.messages import (
    Capability,
    CapabilityItem,
    MemoryCommit,
    MemoryQuery,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StateRef,
    StepResult,
    parse_protocol_bytes,
    protocol_bytes,
    state_ref_lite_wire_bytes,
    total_state_ref_lite_wire_bytes,
)
from runtime.contracts import (
    CapabilityTable,
    SchemaInterceptor,
    SchemaValidationError,
    default_state_contract_registry,
)
from statepool.store import StatePool, StatePoolConfig


def test_memory_commit_wire_ignores_rich_state_ref_payloads() -> None:
    rich_refs = [
        StateRef(
            state_id="state-evidence-1",
            kind="DENSE_EVIDENCE",
            storage="MMAP_FILE",
            handle="/tmp/very/long/path/that/should/not/appear/in/wire/evidence-1.bin",
            length=4096,
            checksum="a" * 64,
            metadata={
                "query": "cache staleness stale inventory invalidation lag",
                "extra": "x" * 256,
            },
        ),
        StateRef(
            state_id="state-embedding-1",
            kind="EMBEDDING",
            storage="PY_SHARED_MEMORY",
            handle="psm_very_long_segment_name_that_should_not_be_counted",
            length=128,
            checksum="b" * 64,
            metadata={
                "encoder_id": "sentence-transformers:Qwen3-Embedding-0.6B",
                "vector_dim": 32,
                "dtype": "float32",
                "extra": "y" * 256,
            },
        ),
    ]
    minimal_refs = [
        StateRef(
            state_id=ref.state_id,
            kind=ref.kind,
            storage=ref.storage,
            handle="",
            length=ref.length,
        )
        for ref in rich_refs
    ]
    rich = MemoryCommit(
        memory_id="mem-1",
        source_agent_id="summarizer",
        source_task_id="task-1",
        task_theme="repo_local_cache_triage",
        summary="Stale inventory cache after sync.",
        tags=["cache", "inventory"],
        evidence_state_ids=[ref.state_id for ref in rich_refs],
        reusable_steps=["retrieve", "execute"],
        confidence=0.95,
        embedding_state_id="state-embedding-1",
        encoder_id="sentence-transformers:Qwen3-Embedding-0.6B",
        metadata={
            "reuse_signature": "repo_local_cache_triage:inventory|cache|invalidation",
            "trace_id": "trace-" + "z" * 64,
            "llm_model": "deepseek-v4-flash",
        },
        evidence_state_refs=rich_refs,
    )
    minimal = MemoryCommit(
        **{
            **rich.__dict__,
            "encoder_id": None,
            "metadata": {"reuse_signature": rich.metadata["reuse_signature"]},
            "evidence_state_refs": minimal_refs,
        }
    )
    assert protocol_bytes(rich) == protocol_bytes(minimal)


def test_memory_query_wire_keeps_only_reuse_signature_metadata() -> None:
    rich = MemoryQuery(
        task_theme="repo_local_cache_triage",
        query_text="cache staleness stale inventory invalidation lag",
        top_k=1,
        tags=["cache", "inventory"],
        tags_any=["cache", "inventory"],
        tags_all=["inventory", "cache"],
        min_confidence=0.6,
        encoder_id="sentence-transformers:Qwen3-Embedding-0.6B",
        required_metadata={
            "reuse_signature": "repo_local_cache_triage:inventory|cache|invalidation",
            "trace_id": "trace-" + "q" * 64,
            "llm_model": "deepseek-v4-flash",
        },
    )
    minimal = MemoryQuery(
        **{
            **rich.__dict__,
            "encoder_id": None,
            "required_metadata": {
                "reuse_signature": rich.required_metadata["reuse_signature"]
            },
        }
    )
    assert protocol_bytes(rich) == protocol_bytes(minimal)


def test_step_result_protobuf_round_trip_preserves_core_fields() -> None:
    message = StepResult(
        step_id="execute",
        success=True,
        output_state_refs=[
            StateRef(
                state_id="artifact-1",
                kind="TOOL_ARTIFACT",
                storage="MMAP_FILE",
                handle="/tmp/artifact-1.bin",
                length=128,
                checksum="c" * 64,
                metadata={"tool_name": "tool.db_pool_triage"},
            )
        ],
        payload={"tool_name": "tool.db_pool_triage", "route": "db_pool_saturation"},
        skipped=False,
    )
    parsed = parse_protocol_bytes(protocol_bytes(message))
    assert isinstance(parsed, StepResult)
    assert parsed.step_id == "execute"
    assert parsed.output_state_refs[0].state_id == "artifact-1"
    assert parsed.output_state_refs[0].kind == "TOOL_ARTIFACT"
    assert parsed.output_state_refs[0].length == 128
    assert parsed.payload["route"] == "db_pool_saturation"


def test_state_ref_lite_wire_bytes_ignore_rich_payload_fields() -> None:
    rich_ref = StateRef(
        state_id="artifact-1",
        kind="TOOL_ARTIFACT",
        storage="MMAP_FILE",
        handle="/tmp/very/long/path/not-on-wire.bin",
        length=1024,
        checksum="a" * 64,
        metadata={"tool_name": "tool.db_pool_triage", "extra": "x" * 256},
    )
    minimal_ref = StateRef(
        state_id=rich_ref.state_id,
        kind=rich_ref.kind,
        storage="PY_SHARED_MEMORY",
        handle="ignored",
        length=rich_ref.length,
    )
    assert state_ref_lite_wire_bytes(rich_ref) == state_ref_lite_wire_bytes(minimal_ref)
    assert total_state_ref_lite_wire_bytes([rich_ref, minimal_ref]) == (
        state_ref_lite_wire_bytes(rich_ref) + state_ref_lite_wire_bytes(minimal_ref)
    )


def test_remote_step_request_protobuf_round_trip_preserves_full_state_refs() -> None:
    request = RemoteStepRequest(
        mode="protocol",
        task_id="sample-cache-001",
        task_theme="repo_local_cache_triage",
        state_root="/tmp/statebus-artifacts",
        step=PlanStep(
            step_id="execute",
            owner_agent="executor",
            action="EXECUTE_PLAYBOOK",
            input_state_refs=["state-evidence-1", "state-features-1"],
            params={"transport": "uds"},
            depends_on=["retrieve"],
            semantic_role="execute",
        ),
        input_state_refs=[
            StateRef(
                state_id="state-evidence-1",
                kind="DENSE_EVIDENCE",
                storage="MMAP_FILE",
                handle="/tmp/evidence.bin",
                length=256,
                checksum="d" * 64,
                metadata={"query": "inventory invalidation"},
            ),
            StateRef(
                state_id="state-features-1",
                kind="FEATURE_BUNDLE",
                storage="MMAP_FILE",
                handle="/tmp/features.bin",
                length=128,
                checksum="e" * 64,
                metadata={"schema": "statebus.feature_bundle.v1"},
            ),
            StateRef(
                state_id="state-tool-candidates-1",
                kind="TOOL_CANDIDATE_SET",
                storage="MMAP_FILE",
                handle="/tmp/tool-candidates.bin",
                length=96,
                checksum="f" * 64,
                metadata={"schema": "statebus.tool_candidate_set.v1"},
            ),
        ],
    )
    payload = protocol_bytes(request)
    envelope = statebus_pb2.WireEnvelope()
    envelope.ParseFromString(payload)
    assert envelope.WhichOneof("body") == "remote_step_request"
    parsed = parse_protocol_bytes(payload)
    assert isinstance(parsed, RemoteStepRequest)
    assert parsed.step.params["transport"] == "uds"
    assert parsed.input_state_refs[0].handle == "/tmp/evidence.bin"
    assert parsed.input_state_refs[1].kind == "FEATURE_BUNDLE"
    assert parsed.input_state_refs[2].kind == "TOOL_CANDIDATE_SET"


def test_remote_step_response_protobuf_round_trip_preserves_result_payload() -> None:
    response = RemoteStepResponse(
        result=StepResult(
            step_id="execute",
            success=True,
            output_state_refs=[
                StateRef(
                    state_id="artifact-1",
                    kind="TOOL_ARTIFACT",
                    storage="PY_SHARED_MEMORY",
                    handle="psm_artifact_1",
                    length=96,
                    metadata={"sandbox_mode": "subprocess"},
                )
            ],
            payload={"tool_name": "tool.cache_invalidation_playbook", "sandbox_mode": "subprocess"},
        )
    )
    payload = protocol_bytes(response)
    envelope = statebus_pb2.WireEnvelope()
    envelope.ParseFromString(payload)
    assert envelope.WhichOneof("body") == "remote_step_response"
    parsed = parse_protocol_bytes(payload)
    assert isinstance(parsed, RemoteStepResponse)
    assert parsed.result.output_state_refs[0].handle == "psm_artifact_1"
    assert parsed.result.payload["tool_name"] == "tool.cache_invalidation_playbook"


def test_schema_interceptor_rejects_invalid_structured_state_at_producer_boundary() -> None:
    capability_table = CapabilityTable()
    capability_table.register(
        Capability(
            agent_id="retriever",
            items=[
                CapabilityItem(
                    name="RETRIEVE_EVIDENCE",
                    kind="TOOLCHAIN",
                    input_schema="dict",
                    output_schema="StepResult",
                    produced_state_kinds=["TOOL_CANDIDATE_SET"],
                )
            ],
        )
    )
    with tempfile.TemporaryDirectory(prefix="statebus-bad-producer-state-") as tmpdir:
        statepool = StatePool(Path(tmpdir), config=StatePoolConfig.from_env())
        bad_ref = statepool.put_bytes(
            state_id="bad-tool-candidates",
            kind="TOOL_CANDIDATE_SET",
            payload=msgpack.packb(
                {
                    "schema": "statebus.not_tool_candidate.v1",
                    "tool_candidates": [],
                },
                use_bin_type=True,
            ),
            metadata={
                "encoding": "msgpack",
                "schema": "statebus.not_tool_candidate.v1",
                "query": "inventory invalidation",
                "feature_route": "cache_invalidation",
                "feature_route_source": "hint_consensus",
                "feature_route_confidence": 0.91,
            },
        )
        with pytest.raises(SchemaValidationError, match="registered contract|schema mismatch"):
            SchemaInterceptor.validate_result(
                step=PlanStep(
                    step_id="retrieve",
                    owner_agent="retriever",
                    action="RETRIEVE_EVIDENCE",
                    input_state_refs=[],
                    params={"query": "inventory invalidation"},
                    depends_on=[],
                    semantic_role="retrieve",
                ),
                result=StepResult(
                    step_id="retrieve",
                    success=True,
                    output_state_refs=[bad_ref],
                ),
                capability_table=capability_table,
                state_contract_registry=default_state_contract_registry(),
                statepool=statepool,
            )
