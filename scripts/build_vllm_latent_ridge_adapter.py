#!/usr/bin/env python3
"""Build the experimental Qwen input-embedding ridge realignment artifact.

The builder only reads model weights and emits a matrix plus checksum-bound
metadata. It never loads prompt data, token IDs, or latent captures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from v2.integrations.vllm_latent.alignment import write_ridge_realign_artifact


INPUT_EMBEDDING_KEY = "model.embed_tokens.weight"
OUTPUT_EMBEDDING_KEY = "lm_head.weight"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("/data/models/Qwen3-32B"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--matrix-name", default="ridge_realign_v1.npy")
    parser.add_argument("--metadata-name", default="ridge_realign_v1.json")
    parser.add_argument("--regularization", type=float, default=0.01)
    parser.add_argument("--chunk-rows", type=int, default=2048)
    parser.add_argument(
        "--device",
        default="cpu",
        help="Torch device. For physical GPU 1, launch with CUDA_VISIBLE_DEVICES=1 and --device cuda:0.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_sha256(paths: tuple[Path, ...]) -> str:
    first_pass = "".join(f"{_sha256_file(path)}\n" for path in paths)
    return hashlib.sha256(first_pass.encode("ascii")).hexdigest()


def _weight_hasher(*, shape: tuple[int, int], dtype: Any) -> Any:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {"dtype": str(dtype), "shape": list(shape)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    )
    return digest


def _update_weight_hash(digest: Any, values: Any) -> None:
    contiguous = values.detach().contiguous()
    digest.update(contiguous.view(dtype=__import__("torch").uint8).numpy().tobytes())


def _shard_path(model_path: Path, weight_map: dict[str, str], key: str) -> Path:
    try:
        shard = weight_map[key]
    except KeyError as exc:
        raise ValueError(f"model index does not contain {key}") from exc
    path = model_path / shard
    if not path.is_file():
        raise ValueError(f"model shard is missing: {path}")
    return path


def _read_model_config(model_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    config_path = model_path / "config.json"
    index_path = model_path / "model.safetensors.index.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("model config or safetensors index is unreadable") from exc
    weight_map = index.get("weight_map")
    if not isinstance(config, dict) or not isinstance(weight_map, dict):
        raise ValueError("model config or safetensors index is invalid")
    return config, {str(key): str(value) for key, value in weight_map.items()}


def build(args: argparse.Namespace) -> dict[str, object]:
    if args.chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    if not math.isfinite(args.regularization) or args.regularization <= 0.0:
        raise ValueError("regularization must be finite and positive")

    import torch
    from safetensors import safe_open

    model_path = args.model_path.expanduser().resolve()
    config, weight_map = _read_model_config(model_path)
    hidden_size = int(config.get("hidden_size", 0))
    vocab_size = int(config.get("vocab_size", 0))
    if hidden_size <= 0 or vocab_size <= 0:
        raise ValueError("model config must provide positive hidden_size and vocab_size")
    if bool(config.get("tie_word_embeddings", True)):
        raise ValueError("ridge realignment requires untied input and output embeddings")

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("requested CUDA device is unavailable")
    input_path = _shard_path(model_path, weight_map, INPUT_EMBEDDING_KEY)
    output_path = _shard_path(model_path, weight_map, OUTPUT_EMBEDDING_KEY)
    matrix_path = (args.output_dir / args.matrix_name).expanduser().resolve()
    metadata_path = (args.output_dir / args.metadata_name).expanduser().resolve()
    if not args.overwrite and (matrix_path.exists() or metadata_path.exists()):
        raise ValueError("artifact output already exists; pass --overwrite to replace it")

    normal_matrix = torch.zeros((hidden_size, hidden_size), dtype=torch.float32, device=device)
    cross_matrix = torch.zeros_like(normal_matrix)
    input_norm_sum = torch.zeros((), dtype=torch.float64, device=device)
    input_digest = None
    output_digest = None

    with safe_open(str(input_path), framework="pt", device="cpu") as input_file, safe_open(
        str(output_path), framework="pt", device="cpu"
    ) as output_file:
        input_slice = input_file.get_slice(INPUT_EMBEDDING_KEY)
        output_slice = output_file.get_slice(OUTPUT_EMBEDDING_KEY)
        input_shape = tuple(int(value) for value in input_slice.get_shape())
        output_shape = tuple(int(value) for value in output_slice.get_shape())
        expected_shape = (vocab_size, hidden_size)
        if input_shape != expected_shape or output_shape != expected_shape:
            raise ValueError(
                f"unexpected embedding shape: input={input_shape}, output={output_shape}, expected={expected_shape}"
            )
        for start in range(0, vocab_size, args.chunk_rows):
            stop = min(start + args.chunk_rows, vocab_size)
            input_cpu = input_slice[start:stop, :]
            output_cpu = output_slice[start:stop, :]
            if input_digest is None:
                input_digest = _weight_hasher(shape=input_shape, dtype=input_cpu.dtype)
                output_digest = _weight_hasher(shape=output_shape, dtype=output_cpu.dtype)
            _update_weight_hash(input_digest, input_cpu)
            _update_weight_hash(output_digest, output_cpu)
            input_chunk = input_cpu.to(device=device, dtype=torch.float32)
            output_chunk = output_cpu.to(device=device, dtype=torch.float32)
            normal_matrix.add_(output_chunk.transpose(0, 1).matmul(output_chunk))
            cross_matrix.add_(output_chunk.transpose(0, 1).matmul(input_chunk))
            input_norm_sum.add_(torch.linalg.vector_norm(input_chunk, dim=1).sum().double())
            del input_cpu, output_cpu, input_chunk, output_chunk

    system_matrix = normal_matrix.clone()
    system_matrix.diagonal().add_(float(args.regularization))
    matrix = torch.linalg.solve(system_matrix, cross_matrix)
    if not bool(torch.isfinite(matrix).all().item()):
        raise ValueError("ridge solve produced non-finite values")
    residual = torch.linalg.vector_norm(system_matrix.matmul(matrix) - cross_matrix)
    denominator = torch.linalg.vector_norm(cross_matrix).clamp_min(1e-12)
    relative_residual = float((residual / denominator).detach().cpu().item())
    target_norm = float((input_norm_sum / vocab_size).detach().cpu().item())
    if not math.isfinite(target_norm) or target_norm <= 0.0:
        raise ValueError("input embedding mean norm is invalid")

    if input_digest is None or output_digest is None:
        raise ValueError("model embeddings are empty")
    fit_metrics = _embedding_fit_metrics(
        input_path=input_path,
        output_path=output_path,
        expected_shape=(vocab_size, hidden_size),
        matrix=matrix,
        chunk_rows=int(args.chunk_rows),
        device=device,
    )
    model_revision = _combined_sha256(
        (model_path / "config.json", model_path / "model.safetensors.index.json")
    )
    artifact = write_ridge_realign_artifact(
        matrix=matrix,
        matrix_path=matrix_path,
        metadata_path=metadata_path,
        model_revision_or_manifest_digest=model_revision,
        input_embedding_digest=input_digest.hexdigest(),
        output_embedding_digest=output_digest.hexdigest(),
        target_norm=target_norm,
        regularization=float(args.regularization),
        training_row_count=vocab_size,
        linear_system_relative_residual=relative_residual,
        embedding_fit_relative_rmse=fit_metrics["embedding_fit_relative_rmse"],
        identity_relative_rmse=fit_metrics["identity_relative_rmse"],
        embedding_fit_mean_cosine=fit_metrics["embedding_fit_mean_cosine"],
        extra_metadata={
            "builder": "scripts/build_vllm_latent_ridge_adapter.py",
            "device": str(device),
            "input_embedding_key": INPUT_EMBEDDING_KEY,
            "output_embedding_key": OUTPUT_EMBEDDING_KEY,
            "input_embedding_shard": input_path.name,
            "output_embedding_shard": output_path.name,
            "vocab_size": vocab_size,
            "chunk_rows": int(args.chunk_rows),
        },
        overwrite=args.overwrite,
    )
    return {
        "method": "ridge_realign_v1",
        "matrix_path": str(artifact.matrix_path),
        "metadata_path": str(artifact.metadata_path),
        "matrix_sha256": artifact.matrix_sha256,
        "metadata_sha256": artifact.metadata_sha256,
        "hidden_size": artifact.hidden_size,
        "target_norm": artifact.target_norm,
        "regularization": artifact.regularization,
        "linear_system_relative_residual": relative_residual,
        "embedding_fit_relative_rmse": artifact.embedding_fit_relative_rmse,
        "identity_relative_rmse": artifact.identity_relative_rmse,
        "embedding_fit_error_ratio": artifact.embedding_fit_error_ratio,
        "embedding_fit_mean_cosine": artifact.embedding_fit_mean_cosine,
    }


def _embedding_fit_metrics(
    *,
    input_path: Path,
    output_path: Path,
    expected_shape: tuple[int, int],
    matrix: Any,
    chunk_rows: int,
    device: Any,
) -> dict[str, float]:
    import torch
    from safetensors import safe_open

    fit_squared_error = torch.zeros((), dtype=torch.float64, device=device)
    identity_squared_error = torch.zeros((), dtype=torch.float64, device=device)
    target_squared_norm = torch.zeros((), dtype=torch.float64, device=device)
    cosine_sum = torch.zeros((), dtype=torch.float64, device=device)
    row_count = 0
    with safe_open(str(input_path), framework="pt", device="cpu") as input_file, safe_open(
        str(output_path), framework="pt", device="cpu"
    ) as output_file:
        input_slice = input_file.get_slice(INPUT_EMBEDDING_KEY)
        output_slice = output_file.get_slice(OUTPUT_EMBEDDING_KEY)
        input_shape = tuple(int(value) for value in input_slice.get_shape())
        output_shape = tuple(int(value) for value in output_slice.get_shape())
        if input_shape != expected_shape or output_shape != expected_shape:
            raise ValueError("embedding shape changed during ridge fit validation")
        for start in range(0, expected_shape[0], chunk_rows):
            stop = min(start + chunk_rows, expected_shape[0])
            input_chunk = input_slice[start:stop, :].to(
                device=device, dtype=torch.float32
            )
            output_chunk = output_slice[start:stop, :].to(
                device=device, dtype=torch.float32
            )
            mapped = output_chunk.matmul(matrix)
            fit_delta = mapped - input_chunk
            identity_delta = output_chunk - input_chunk
            fit_squared_error.add_(fit_delta.square().sum().double())
            identity_squared_error.add_(identity_delta.square().sum().double())
            target_squared_norm.add_(input_chunk.square().sum().double())
            cosine_sum.add_(
                torch.nn.functional.cosine_similarity(
                    mapped, input_chunk, dim=-1, eps=1e-8
                ).sum().double()
            )
            row_count += stop - start
            del input_chunk, output_chunk, mapped, fit_delta, identity_delta

    denominator = target_squared_norm.clamp_min(1e-24)
    fit_relative_rmse = float(
        torch.sqrt(fit_squared_error / denominator).detach().cpu().item()
    )
    identity_relative_rmse = float(
        torch.sqrt(identity_squared_error / denominator).detach().cpu().item()
    )
    mean_cosine = float((cosine_sum / max(row_count, 1)).detach().cpu().item())
    values = (fit_relative_rmse, identity_relative_rmse, mean_cosine)
    if (
        row_count != expected_shape[0]
        or not all(math.isfinite(value) for value in values)
        or fit_relative_rmse >= identity_relative_rmse
    ):
        raise ValueError("ridge embedding fit did not improve over identity")
    return {
        "embedding_fit_relative_rmse": fit_relative_rmse,
        "identity_relative_rmse": identity_relative_rmse,
        "embedding_fit_mean_cosine": mean_cosine,
    }


def main() -> int:
    result = build(_arguments())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
