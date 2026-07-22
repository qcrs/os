from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np
import torch

from v2.integrations.vllm_latent.alignment import (
    RIDGE_REALIGN_V1,
    SOFT_TOKEN_TOPK_V1,
    LatentAlignmentConfigurationError,
    apply_ridge_realign,
    resolve_alignment_configuration,
    sanitize_alignment_diagnostics,
    write_ridge_realign_artifact,
)
from v2.runtime.latent_handoff import latent_telemetry_audit_view
from v2.utils import sha256_digest


def _write_artifact(tmp_path, *, hidden_size: int = 8):
    return write_ridge_realign_artifact(
        matrix=torch.eye(hidden_size),
        matrix_path=tmp_path / "ridge.npy",
        metadata_path=tmp_path / "ridge.json",
        model_revision_or_manifest_digest="sha256:model-revision",
        input_embedding_digest="sha256:input",
        output_embedding_digest="sha256:output",
        target_norm=1.25,
        regularization=0.01,
        training_row_count=16,
        linear_system_relative_residual=1e-7,
        embedding_fit_relative_rmse=0.25,
        identity_relative_rmse=0.5,
        embedding_fit_mean_cosine=0.95,
    )


def _ridge_env(artifact) -> dict[str, str]:
    return {
        "STATEBUS_LATENT_ALIGNMENT": RIDGE_REALIGN_V1,
        "STATEBUS_LATENT_ALIGNMENT_ARTIFACT": str(artifact.matrix_path),
        "STATEBUS_LATENT_ALIGNMENT_METADATA": str(artifact.metadata_path),
    }


def _builder_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "build_vllm_latent_ridge_adapter.py"
    )
    spec = importlib.util.spec_from_file_location("statebus_ridge_builder", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_soft_alignment_config_digest_remains_compatible() -> None:
    config = resolve_alignment_configuration(
        model_revision="sha256:model-revision",
        hidden_size=5120,
        environ={
            "STATEBUS_LATENT_ALIGNMENT": SOFT_TOKEN_TOPK_V1,
            "STATEBUS_LATENT_ALIGNMENT_TOP_K": "32",
            "STATEBUS_LATENT_ALIGNMENT_TEMPERATURE": "1.0",
        },
    )

    assert config.method == SOFT_TOKEN_TOPK_V1
    assert config.config_digest == sha256_digest(
        {
            "method": SOFT_TOKEN_TOPK_V1,
            "top_k": 32,
            "temperature": 1.0,
            "normalization": "fixed_stride_1024_input_embedding_mean_norm",
            "model_revision": "sha256:model-revision",
        }
    )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("model", "artifact_model_mismatch"),
        ("hash", "artifact_digest_mismatch"),
        ("shape", "artifact_shape_invalid"),
        ("fit", "artifact_fit_invalid"),
    ),
)
def test_ridge_artifact_rejects_model_digest_and_shape_mismatch(
    tmp_path, mutation: str, expected_error: str
) -> None:
    artifact = _write_artifact(tmp_path)
    environ = _ridge_env(artifact)
    expected_revision = "sha256:model-revision"
    if mutation == "model":
        expected_revision = "sha256:other-model"
    elif mutation == "hash":
        with artifact.matrix_path.open("ab") as handle:
            handle.write(b"x")
    elif mutation == "shape":
        metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
        metadata["hidden_size"] = 4
        metadata["matrix_shape"] = [4, 4]
        artifact.metadata_path.write_text(
            json.dumps(metadata, sort_keys=True), encoding="utf-8"
        )
    else:
        metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
        metadata["embedding_fit_relative_rmse"] = 0.75
        metadata["embedding_fit_error_ratio"] = 1.5
        artifact.metadata_path.write_text(
            json.dumps(metadata, sort_keys=True), encoding="utf-8"
        )

    with pytest.raises(LatentAlignmentConfigurationError) as exc_info:
        resolve_alignment_configuration(
            model_revision=expected_revision,
            hidden_size=8,
            environ=environ,
        )
    assert exc_info.value.code == expected_error


def test_ridge_alignment_normalizes_to_artifact_target_norm(tmp_path) -> None:
    artifact = _write_artifact(tmp_path)
    matrix = torch.eye(8, dtype=torch.float32)
    hidden = torch.full((1, 8), 2.0, dtype=torch.bfloat16)

    aligned = apply_ridge_realign(
        hidden,
        matrix=matrix,
        target_norm=artifact.target_norm,
        torch=torch,
    )

    assert tuple(aligned.shape) == (1, 8)
    assert aligned.dtype == torch.bfloat16
    assert torch.allclose(
        aligned.float().norm(dim=-1),
        torch.tensor([artifact.target_norm]),
        atol=0.02,
    )


def test_ridge_artifact_rejects_nonfinite_matrix_even_with_matching_digest(
    tmp_path,
) -> None:
    artifact = _write_artifact(tmp_path)
    values = np.load(artifact.matrix_path, allow_pickle=False)
    values[0, 0] = np.nan
    np.save(artifact.matrix_path, values, allow_pickle=False)
    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    metadata["matrix_sha256"] = hashlib.sha256(
        artifact.matrix_path.read_bytes()
    ).hexdigest()
    artifact.metadata_path.write_text(
        json.dumps(metadata, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(LatentAlignmentConfigurationError) as exc_info:
        resolve_alignment_configuration(
            model_revision="sha256:model-revision",
            hidden_size=8,
            environ=_ridge_env(artifact),
        )
    assert exc_info.value.code == "artifact_matrix_invalid"


def test_streaming_builder_writes_parseable_ridge_artifact(tmp_path) -> None:
    safetensors_torch = pytest.importorskip("safetensors.torch")
    model_path = tmp_path / "model"
    model_path.mkdir()
    input_weight = torch.arange(24, dtype=torch.float32).reshape(6, 4) / 20.0
    output_weight = torch.flip(input_weight, dims=(0,)) + 0.1
    safetensors_torch.save_file(
        {"model.embed_tokens.weight": input_weight},
        str(model_path / "input.safetensors"),
    )
    safetensors_torch.save_file(
        {"lm_head.weight": output_weight},
        str(model_path / "output.safetensors"),
    )
    (model_path / "config.json").write_text(
        json.dumps(
            {"hidden_size": 4, "vocab_size": 6, "tie_word_embeddings": False}
        ),
        encoding="utf-8",
    )
    (model_path / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    "model.embed_tokens.weight": "input.safetensors",
                    "lm_head.weight": "output.safetensors",
                }
            }
        ),
        encoding="utf-8",
    )
    builder = _builder_module()
    result = builder.build(
        SimpleNamespace(
            model_path=model_path,
            output_dir=tmp_path / "artifact",
            matrix_name="ridge.npy",
            metadata_name="ridge.json",
            regularization=0.1,
            chunk_rows=2,
            device="cpu",
            overwrite=False,
        )
    )

    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    parsed = resolve_alignment_configuration(
        model_revision=builder._combined_sha256(
            (model_path / "config.json", model_path / "model.safetensors.index.json")
        ),
        hidden_size=4,
        environ={
            "STATEBUS_LATENT_ALIGNMENT": RIDGE_REALIGN_V1,
            "STATEBUS_LATENT_ALIGNMENT_ARTIFACT": str(result["matrix_path"]),
            "STATEBUS_LATENT_ALIGNMENT_METADATA": str(result["metadata_path"]),
        },
    )

    assert parsed.ready
    assert parsed.ridge_artifact is not None
    assert parsed.ridge_artifact.matrix_shape == (4, 4)
    assert metadata["input_embedding_shard"] == "input.safetensors"
    assert metadata["output_embedding_shard"] == "output.safetensors"
    assert result["linear_system_relative_residual"] < 1e-4
    assert result["embedding_fit_relative_rmse"] < result["identity_relative_rmse"]
    assert -1.0 <= result["embedding_fit_mean_cosine"] <= 1.0


def test_alignment_diagnostics_and_audit_view_drop_unsafe_fields() -> None:
    raw = {
        "observation_count": 3,
        "hidden_norm_mean": 1.2,
        "direct_lm_head_topk_overlap_max": 0.8,
        "token_ids": [1, 2],
        "prompt": "must-not-escape",
        "hidden_states": [0.1, 0.2],
        "matrix": "must-not-escape",
    }

    sanitized = sanitize_alignment_diagnostics(raw)
    projected = latent_telemetry_audit_view(
        {
            "alignment_diagnostics": raw,
            "prompt": "must-not-escape",
            "raw_hidden_states": [0.1, 0.2],
        }
    )

    assert sanitized == {
        "observation_count": 3,
        "hidden_norm_mean": 1.2,
        "direct_lm_head_topk_overlap_max": 0.8,
    }
    assert projected == {"alignment_diagnostics": sanitized}
