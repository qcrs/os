from __future__ import annotations

import argparse
import json
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import sys
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from v2.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.memory import build_embedding_encoder, default_embedding_model_path, resolve_embed_device
from v2.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from v2.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    publish_dense_semantic_state,
    query_embedding_from_dense_state,
)
from v2.utils import sha256_digest


def _run(*, model_path: Path, device: str, work_root: Path) -> dict[str, object]:
    encoder = build_embedding_encoder("local", model_path=model_path, device=device)
    query_text = "ACME revenue growth and margin pressure"
    candidate_texts = (
        "ACME revenue increased while gross margin declined.",
        "Supply delays created margin pressure in the third quarter.",
        "An unrelated network maintenance window completed successfully.",
    )
    query = encoder.encode(embedding_id="local-query", text=query_text)
    candidates = tuple(
        encoder.encode(embedding_id=f"local-candidate-{index}", text=text)
        for index, text in enumerate(candidate_texts, start=1)
    )
    source_doc_hash = sha256_digest(candidate_texts)
    manifest = HydrateManifest(
        manifest_id=f"local-semantic-manifest-{os.getpid()}-{time.time_ns()}",
        source_doc_hashes=(source_doc_hash,),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=f"candidate-{index}",
                bucket="semantic_context",
                locator=FragmentLocator(
                    source_doc_hash=source_doc_hash,
                    fragment_id=f"fragment-{index}",
                    extractor_version="local-embedding-check-v1",
                ),
                stable_key=f"fragment-{index}",
                byte_hint=len(text.encode("utf-8")),
                importance_score=1.0,
            )
            for index, text in enumerate(candidate_texts, start=1)
        ),
        canonicalizer_version="canon-v1",
        extractor_version="local-embedding-check-v1",
    )

    with tempfile.TemporaryDirectory(prefix="statebus-local-semantic-", dir=work_root) as tmp_dir:
        root = Path(tmp_dir)
        store = LayeredStateStore(
            root=root / "state",
            policy=LayeredStoragePolicy.for_state_pool_mode("shared_memory"),
        )
        state_id = f"local-semantic-state-{os.getpid()}-{time.time_ns()}"
        publication = publish_dense_semantic_state(
            store=store,
            state_id=state_id,
            query_embedding=query,
            candidate_embeddings=candidates,
            hydrate_manifest=manifest,
            owner_session_id="local-embedding-cross-process-check",
            encoder_revision=model_path.name,
        )
        shared_memory_name = publication.handle.shared_memory_name
        try:
            request = ExecRequest(
                header=ControlHeader(
                    trace_id="local-embedding-cross-process-check",
                    task_id="local-embedding-check",
                    step_id="semantic-consumer",
                    attempt_id="attempt-1",
                    target_role="executor",
                    timeout_ms=30_000,
                    event_type=EventType.REQ_EXEC,
                ),
                state_refs=(RefHandle(ref_id=state_id, ref_kind="semantic_state"),),
                artifact_refs=(),
                runtime_reuse_contract="semantic_state_required",
                output_contract_version="statebus.evidence_selection.v1",
                workspace_root=str(root / "workspace"),
                input_manifest_hash=publication.contract.hydrate_manifest_hash,
                operation="semantic_select_v1",
                state_root=str(store.root),
                hydrate_manifest_id=manifest.manifest_id,
                semantic_top_k=2,
                evidence_budget_bytes=4096,
                expected_encoder_signature=publication.contract.encoder_signature,
                capability_grant_hash="local-embedding-check-grant",
            )
            response = SubprocessExecutorTransport(
                socket_path=root / "semantic-consumer.sock",
                timeout_s=30.0,
            ).execute(request)
            if isinstance(response, ErrorResult):
                raise RuntimeError(
                    f"semantic consumer failed: {response.error_code}:{response.error_detail}"
                )
            if not isinstance(response, SuccessResult):
                raise RuntimeError("semantic consumer returned an unexpected response")
            if response.consumer_pid == response.producer_pid or response.consumer_pid == os.getpid():
                raise RuntimeError("semantic consumer did not run in another process")
            if response.producer_pid != os.getpid():
                raise RuntimeError("semantic producer pid mismatch")
            reused_query = query_embedding_from_dense_state(
                state_root=store.root,
                ref=publication.ref,
                embedding_id=query.embedding_id,
                expected_encoder_signature=publication.contract.encoder_signature,
            )
            max_query_row_delta = max(
                abs(left - right) for left, right in zip(query.vector, reused_query.vector)
            )
            if max_query_row_delta > 1e-6:
                raise RuntimeError(f"query row reuse mismatch: {max_query_row_delta}")

            store.release(state_id)
            try:
                probe = SharedMemory(name=shared_memory_name)
            except FileNotFoundError:
                owner_release_verified = True
            else:
                probe.close()
                owner_release_verified = False
            if not owner_release_verified:
                raise RuntimeError("owner release did not unlink shared memory")
            return {
                "schema_version": "statebus.local_embedding_semantic_state_check.v1",
                "ok": True,
                "model_path": str(model_path),
                "device": device,
                "encoding": query.encoding,
                "dims": query.dims,
                "shape": list(publication.contract.shape),
                "size_bytes": publication.contract.size_bytes,
                "storage_kind": publication.handle.storage_kind.value,
                "producer_pid": response.producer_pid,
                "consumer_pid": response.consumer_pid,
                "selected_candidate_ids": list(response.selected_candidate_ids),
                "selected_row_indices": list(response.selected_row_indices),
                "selected_evidence_bytes": response.selected_evidence_bytes,
                "query_row_reused_without_encode": True,
                "max_query_row_delta": max_query_row_delta,
                "owner_release_verified": owner_release_verified,
            }
        finally:
            store.teardown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify local embedding binary state through a typed cross-process UDS consumer."
    )
    parser.add_argument("--model-path", type=Path, default=default_embedding_model_path())
    parser.add_argument("--device", default=resolve_embed_device())
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.getenv("STATEBUS_WORK_DIR", "/tmp")),
    )
    args = parser.parse_args()
    args.work_root.mkdir(parents=True, exist_ok=True)
    try:
        payload = _run(
            model_path=args.model_path.resolve(),
            device=str(args.device),
            work_root=args.work_root.resolve(),
        )
    except Exception as exc:
        payload = {
            "schema_version": "statebus.local_embedding_semantic_state_check.v1",
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
