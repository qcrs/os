#!/usr/bin/env python3
"""Measure immutable-model reuse in one fresh process, without task state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new")
    start = time.perf_counter_ns()
    import sentence_transformers
    import torch
    from statebus.memory.embedding import SentenceTransformerEmbeddingEncoder, _MODEL_CACHE

    import_ms = (time.perf_counter_ns() - start) / 1_000_000
    torch.set_num_threads(2)
    on_cuda = args.device.startswith("cuda")

    def sync():
        if on_cuda:
            torch.cuda.synchronize(args.device)

    def memory():
        if not on_cuda:
            return None
        return {"allocated_bytes": torch.cuda.memory_allocated(args.device),
                "reserved_bytes": torch.cuda.memory_reserved(args.device)}

    if on_cuda:
        assert torch.cuda.is_available(), "requested CUDA device unavailable"
    memory_before = memory()
    assert not _MODEL_CACHE, "run the probe in a fresh interpreter"
    loads, encodes, operations = [], [], []
    constructor = sentence_transformers.SentenceTransformer

    def load(*values, **kwargs):
        sync()
        started = time.perf_counter_ns()
        model = constructor(*values, **kwargs)
        sync()
        loads.append({"duration_ms": (time.perf_counter_ns() - started) / 1_000_000})
        return model

    def operation(name, callback):
        sync()
        started = time.perf_counter_ns()
        result = callback()
        sync()
        operations.append({"name": name, "duration_ms": (time.perf_counter_ns() - started) / 1_000_000})
        return result

    first = SentenceTransformerEmbeddingEncoder(model_path=args.model_path, device=args.device)
    second = SentenceTransformerEmbeddingEncoder(model_path=args.model_path, device=args.device)
    with patch.object(sentence_transformers, "SentenceTransformer", side_effect=load):
        model = operation("first_ensure_model", first._ensure_model)
        encode = model.encode

        def timed_encode(*values, **kwargs):
            sync()
            started = time.perf_counter_ns()
            result = encode(*values, **kwargs)
            sync()
            encodes.append({"duration_ms": (time.perf_counter_ns() - started) / 1_000_000})
            return result

        with patch.object(model, "encode", side_effect=timed_encode):
            dims = operation("first_dims", lambda: first.dims)
            operation("first_query", lambda: first.encode(embedding_id="probe-1", text="quarterly revenue"))
            shared = operation("second_ensure_model", second._ensure_model) is model
            operation("second_dims", lambda: second.dims)
            operation("second_query", lambda: second.encode(embedding_id="probe-2", text="quarterly revenue"))
            operation("repeated_dims", lambda: second.dims)
    result = {
        "schema_version": "statebus.embedding_lifecycle_probe.v1", "pid": os.getpid(),
        "device": args.device, "model_path": str(args.model_path.resolve()), "torch_threads": torch.get_num_threads(),
        "scope": "isolated_loader_probe_not_campaign_e2e", "import_ms": import_ms,
        "model_load_count": len(loads), "model_loads": loads, "encode_count": len(encodes), "encodes": encodes,
        "operations": operations, "shared_model_object": shared, "dims": dims,
        "gpu_memory": {"before": memory_before, "after": memory(),
                       "peak_allocated_bytes": torch.cuda.max_memory_allocated(args.device) if on_cuda else None},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "loads": len(loads), "encodes": len(encodes), "shared": shared}))
    return 0 if shared and len(loads) == 1 and len(encodes) == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
