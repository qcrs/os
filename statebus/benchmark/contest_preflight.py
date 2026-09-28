"""Small real GPU embedding probe for the contest interpreter; no LLM request."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from statebus.benchmark.contest_stage1 import write_json, effective_configuration, effective_budget
from statebus.integrations.llm import LLMConfig
from statebus.memory.embedding import SentenceTransformerEmbeddingEncoder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--embedding-model-path", required=True)
    parser.add_argument("--gpu-uuid", required=True)
    args = parser.parse_args()
    import torch
    import statebus

    config = LLMConfig.from_runtime().with_mode("local_vllm")
    for role in ("planner", "retriever", "executor", "summarizer"):
        values = config.role_config(role)
        if values.model != args.model or config.provider_config(values.provider).base_url.rstrip("/") != args.base_url.rstrip("/"):
            raise RuntimeError("effective_role_profile_mismatch:" + role)
    if Path(statebus.__file__).resolve() != Path("/workspace/statebus/os/statebus/__init__.py"):
        raise RuntimeError("source_checkout_mismatch")
    if not torch.cuda.is_available():
        raise RuntimeError(f"runtime_python_has_no_cuda:{sys.executable}:{torch.__version__}")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("expected_exactly_one_mapped_embedding_gpu")
    actual_uuid = str(torch.cuda.get_device_properties(0).uuid)
    if actual_uuid.removeprefix("GPU-") != args.gpu_uuid.removeprefix("GPU-"):
        raise RuntimeError(f"embedding_gpu_uuid_mismatch:{actual_uuid}:{args.gpu_uuid}")
    encoder = SentenceTransformerEmbeddingEncoder(model_path=args.embedding_model_path, device="cuda:0")
    embedding = encoder.encode(embedding_id="contest-preflight", text="Current financial context and service quality review.")
    devices = sorted({str(p.device) for p in encoder._ensure_model().parameters()})
    if devices != ["cuda:0"] or embedding.dims != 1024 or not all(math.isfinite(v) for v in embedding.vector):
        raise RuntimeError("embedding_output_or_device_invalid")
    report = {"ok": True, "python": sys.executable, "python_version": sys.version,
              "torch": torch.__version__, "torch_file": torch.__file__, "torch_cuda": torch.version.cuda,
              "gpu_uuid": actual_uuid, "embedding_parameter_devices": devices, "embedding_dims": embedding.dims,
              "model": args.model, "source": statebus.__file__, "budget": effective_budget(effective_configuration()),
              "probe_scope": "one_embedding_no_llm_request_not_a_performance_sample"}
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
