from __future__ import annotations

from protocol import statebus_pb2
from protocol.messages import (
    MemoryCommit,
    MemoryQuery,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StateRef,
    StepResult,
    parse_protocol_bytes,
    protocol_bytes,
)


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
