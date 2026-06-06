from __future__ import annotations

from protocol.messages import MemoryCommit, MemoryQuery, StateRef, protocol_bytes


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
