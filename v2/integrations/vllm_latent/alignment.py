from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from v2.contracts.constants import SUPPORTED_LATENT_ALIGNMENT_METHODS as _SUPPORTED_METHODS
from v2.utils import sha256_digest, stable_json_dumps


SOFT_TOKEN_TOPK_V1 = "soft_token_topk_v1"
RIDGE_REALIGN_V1 = "ridge_realign_v1"
SUPPORTED_LATENT_ALIGNMENT_METHODS = _SUPPORTED_METHODS
RIDGE_REALIGN_ARTIFACT_SCHEMA_VERSION = "statebus.latent_ridge_realign.v1"
RIDGE_REALIGN_FIT_CONTRACT = "untied_vocab_embedding_ridge.v1"
_SOFT_TOKEN_NORMALIZATION = "fixed_stride_1024_input_embedding_mean_norm"
_RIDGE_NORMALIZATION = "input_embedding_mean_norm"
_ALIGNMENT_DIAGNOSTIC_BASE_FIELDS = frozenset({
    "hidden_norm",
    "aligned_norm",
    "norm_ratio",
    "source_topk_probability_mass",
    "source_topk_conditional_entropy",
    "direct_lm_head_topk_overlap",
    "direct_lm_head_topk_kl",
})
_ALIGNMENT_DIAGNOSTIC_FIELDS = frozenset({"observation_count"}).union(
    f"{field}_{statistic}"
    for field in _ALIGNMENT_DIAGNOSTIC_BASE_FIELDS
    for statistic in ("mean", "min", "max")
)


class LatentAlignmentConfigurationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RidgeRealignArtifact:
    matrix_path: Path
    metadata_path: Path
    matrix_sha256: str
    metadata_sha256: str
    model_revision_or_manifest_digest: str
    hidden_size: int
    target_norm: float
    regularization: float
    input_embedding_digest: str
    output_embedding_digest: str
    matrix_shape: tuple[int, int]
    training_row_count: int
    linear_system_relative_residual: float
    embedding_fit_relative_rmse: float
    identity_relative_rmse: float
    embedding_fit_error_ratio: float
    embedding_fit_mean_cosine: float
    matrix_dtype: str = "float32"
    fit_contract: str = RIDGE_REALIGN_FIT_CONTRACT
    schema_version: str = RIDGE_REALIGN_ARTIFACT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": RIDGE_REALIGN_V1,
            "matrix_sha256": self.matrix_sha256,
            "metadata_sha256": self.metadata_sha256,
            "model_revision_or_manifest_digest": self.model_revision_or_manifest_digest,
            "hidden_size": self.hidden_size,
            "target_norm": self.target_norm,
            "regularization": self.regularization,
            "input_embedding_digest": self.input_embedding_digest,
            "output_embedding_digest": self.output_embedding_digest,
            "matrix_shape": list(self.matrix_shape),
            "matrix_dtype": self.matrix_dtype,
            "fit_contract": self.fit_contract,
            "training_row_count": self.training_row_count,
            "linear_system_relative_residual": self.linear_system_relative_residual,
            "embedding_fit_relative_rmse": self.embedding_fit_relative_rmse,
            "identity_relative_rmse": self.identity_relative_rmse,
            "embedding_fit_error_ratio": self.embedding_fit_error_ratio,
            "embedding_fit_mean_cosine": self.embedding_fit_mean_cosine,
            "normalization": _RIDGE_NORMALIZATION,
        }

    @classmethod
    def load(
        cls,
        *,
        matrix_path: str | os.PathLike[str],
        metadata_path: str | os.PathLike[str],
        expected_model_revision: str,
        expected_hidden_size: int,
    ) -> "RidgeRealignArtifact":
        resolved_matrix = Path(matrix_path).expanduser().resolve()
        resolved_metadata = Path(metadata_path).expanduser().resolve()
        if not resolved_matrix.is_file() or not resolved_metadata.is_file():
            raise LatentAlignmentConfigurationError("artifact_missing")
        try:
            payload = json.loads(resolved_metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid") from exc
        if not isinstance(payload, dict):
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid")

        required = {
            "schema_version",
            "method",
            "matrix_file",
            "matrix_sha256",
            "model_revision_or_manifest_digest",
            "hidden_size",
            "matrix_shape",
            "matrix_dtype",
            "target_norm",
            "regularization",
            "input_embedding_digest",
            "output_embedding_digest",
            "fit_contract",
            "training_row_count",
            "linear_system_relative_residual",
            "embedding_fit_relative_rmse",
            "identity_relative_rmse",
            "embedding_fit_error_ratio",
            "embedding_fit_mean_cosine",
        }
        if not required.issubset(payload):
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid")
        if (
            str(payload["schema_version"]) != RIDGE_REALIGN_ARTIFACT_SCHEMA_VERSION
            or str(payload["method"]) != RIDGE_REALIGN_V1
            or str(payload["matrix_file"]) != resolved_matrix.name
            or str(payload["matrix_dtype"]) != "float32"
            or str(payload["fit_contract"]) != RIDGE_REALIGN_FIT_CONTRACT
        ):
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid")

        try:
            hidden_size = int(payload["hidden_size"])
            matrix_shape = tuple(int(value) for value in payload["matrix_shape"])
            target_norm = float(payload["target_norm"])
            regularization = float(payload["regularization"])
            training_row_count = int(payload["training_row_count"])
            linear_system_relative_residual = float(
                payload["linear_system_relative_residual"]
            )
            embedding_fit_relative_rmse = float(
                payload["embedding_fit_relative_rmse"]
            )
            identity_relative_rmse = float(payload["identity_relative_rmse"])
            embedding_fit_error_ratio = float(
                payload["embedding_fit_error_ratio"]
            )
            embedding_fit_mean_cosine = float(
                payload["embedding_fit_mean_cosine"]
            )
        except (TypeError, ValueError) as exc:
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid") from exc
        if (
            hidden_size <= 0
            or matrix_shape != (hidden_size, hidden_size)
            or hidden_size != int(expected_hidden_size)
            or not math.isfinite(target_norm)
            or target_norm <= 0.0
            or not math.isfinite(regularization)
            or regularization <= 0.0
        ):
            raise LatentAlignmentConfigurationError("artifact_shape_invalid")
        fit_values = (
            linear_system_relative_residual,
            embedding_fit_relative_rmse,
            identity_relative_rmse,
            embedding_fit_error_ratio,
            embedding_fit_mean_cosine,
        )
        if (
            training_row_count < hidden_size
            or not all(math.isfinite(value) for value in fit_values)
            or linear_system_relative_residual < 0.0
            or linear_system_relative_residual > 1e-3
            or embedding_fit_relative_rmse < 0.0
            or identity_relative_rmse <= 0.0
            or embedding_fit_relative_rmse >= identity_relative_rmse
            or not 0.0 <= embedding_fit_error_ratio < 1.0
            or not math.isclose(
                embedding_fit_error_ratio,
                embedding_fit_relative_rmse / identity_relative_rmse,
                rel_tol=1e-5,
                abs_tol=1e-8,
            )
            or not -1.0 <= embedding_fit_mean_cosine <= 1.0
        ):
            raise LatentAlignmentConfigurationError("artifact_fit_invalid")

        revision = str(payload["model_revision_or_manifest_digest"])
        if not revision or revision != str(expected_model_revision):
            raise LatentAlignmentConfigurationError("artifact_model_mismatch")
        matrix_sha256 = _sha256_file(resolved_matrix)
        if matrix_sha256 != str(payload["matrix_sha256"]):
            raise LatentAlignmentConfigurationError("artifact_digest_mismatch")
        _validate_matrix_header(resolved_matrix, matrix_shape)
        input_digest = str(payload["input_embedding_digest"])
        output_digest = str(payload["output_embedding_digest"])
        if not input_digest or not output_digest:
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid")
        return cls(
            matrix_path=resolved_matrix,
            metadata_path=resolved_metadata,
            matrix_sha256=matrix_sha256,
            metadata_sha256=_sha256_file(resolved_metadata),
            model_revision_or_manifest_digest=revision,
            hidden_size=hidden_size,
            target_norm=target_norm,
            regularization=regularization,
            input_embedding_digest=input_digest,
            output_embedding_digest=output_digest,
            matrix_shape=matrix_shape,
            training_row_count=training_row_count,
            linear_system_relative_residual=linear_system_relative_residual,
            embedding_fit_relative_rmse=embedding_fit_relative_rmse,
            identity_relative_rmse=identity_relative_rmse,
            embedding_fit_error_ratio=embedding_fit_error_ratio,
            embedding_fit_mean_cosine=embedding_fit_mean_cosine,
        )


@dataclass(frozen=True)
class LatentAlignmentConfiguration:
    method: str
    config_digest: str
    diagnostics_enabled: bool
    top_k: int = 0
    temperature: float = 0.0
    ridge_artifact: RidgeRealignArtifact | None = None
    error_code: str = ""

    @property
    def ready(self) -> bool:
        return not self.error_code and self.method in SUPPORTED_LATENT_ALIGNMENT_METHODS


def resolve_alignment_configuration(
    *,
    model_revision: str,
    hidden_size: int,
    environ: Mapping[str, str] | None = None,
) -> LatentAlignmentConfiguration:
    values = os.environ if environ is None else environ
    method = str(values.get("STATEBUS_LATENT_ALIGNMENT", SOFT_TOKEN_TOPK_V1)).strip()
    diagnostics_enabled = _parse_bool(
        values.get("STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS", "false"),
        "diagnostics_invalid",
    )
    if method == SOFT_TOKEN_TOPK_V1:
        top_k = _positive_int(
            values.get("STATEBUS_LATENT_ALIGNMENT_TOP_K", "32"), "top_k_invalid"
        )
        temperature = _positive_float(
            values.get("STATEBUS_LATENT_ALIGNMENT_TEMPERATURE", "1.0"),
            "temperature_invalid",
        )
        return LatentAlignmentConfiguration(
            method=method,
            config_digest=sha256_digest({
                "method": SOFT_TOKEN_TOPK_V1,
                "top_k": top_k,
                "temperature": temperature,
                "normalization": _SOFT_TOKEN_NORMALIZATION,
                "model_revision": model_revision,
            }),
            diagnostics_enabled=diagnostics_enabled,
            top_k=top_k,
            temperature=temperature,
        )
    if method == RIDGE_REALIGN_V1:
        matrix_path = str(values.get("STATEBUS_LATENT_ALIGNMENT_ARTIFACT", "")).strip()
        metadata_path = str(values.get("STATEBUS_LATENT_ALIGNMENT_METADATA", "")).strip()
        if not matrix_path or not metadata_path:
            raise LatentAlignmentConfigurationError("artifact_path_missing")
        artifact = RidgeRealignArtifact.load(
            matrix_path=matrix_path,
            metadata_path=metadata_path,
            expected_model_revision=model_revision,
            expected_hidden_size=hidden_size,
        )
        return LatentAlignmentConfiguration(
            method=method,
            config_digest=sha256_digest({
                "method": RIDGE_REALIGN_V1,
                "artifact": artifact.canonical_payload(),
                "model_revision": model_revision,
            }),
            diagnostics_enabled=diagnostics_enabled,
            ridge_artifact=artifact,
        )
    raise LatentAlignmentConfigurationError("method_unsupported")


def invalid_alignment_configuration(
    *,
    method: str,
    diagnostics_enabled: bool,
    error_code: str,
) -> LatentAlignmentConfiguration:
    return LatentAlignmentConfiguration(
        method=method,
        config_digest=sha256_digest({
            "method": method,
            "status": "invalid",
            "error_code": error_code,
        }),
        diagnostics_enabled=diagnostics_enabled,
        error_code=error_code,
    )


def load_ridge_matrix(artifact: RidgeRealignArtifact, *, torch: Any, device: Any) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise LatentAlignmentConfigurationError("numpy_unavailable") from exc
    try:
        values = np.load(artifact.matrix_path, allow_pickle=False)
    except Exception as exc:
        raise LatentAlignmentConfigurationError("artifact_matrix_invalid") from exc
    if (
        values.ndim != 2
        or tuple(int(value) for value in values.shape) != artifact.matrix_shape
        or str(values.dtype) != "float32"
        or not bool(np.isfinite(values).all())
    ):
        raise LatentAlignmentConfigurationError("artifact_matrix_invalid")
    if _sha256_file(artifact.matrix_path) != artifact.matrix_sha256:
        raise LatentAlignmentConfigurationError("artifact_digest_mismatch")
    # Make an owned CPU copy before moving it into the worker's device cache.
    owned = np.array(values, dtype=np.float32, copy=True)
    return torch.from_numpy(owned).to(device=device, dtype=torch.float32).contiguous()


def apply_ridge_realign(
    hidden: Any,
    *,
    matrix: Any,
    target_norm: float,
    torch: Any,
) -> Any:
    if hidden.ndim == 1:
        hidden = hidden.unsqueeze(0)
    if hidden.ndim != 2 or int(hidden.shape[-1]) != int(matrix.shape[0]):
        raise LatentAlignmentConfigurationError("ridge_input_shape_invalid")
    aligned = torch.matmul(hidden.to(dtype=torch.float32), matrix)
    current_norm = aligned.norm(dim=-1, keepdim=True).clamp_min(1e-6)
    aligned = aligned * (float(target_norm) / current_norm)
    return aligned.to(dtype=torch.bfloat16)


def collect_alignment_diagnostics(
    *,
    torch: Any,
    hidden: Any,
    aligned: Any,
    source_logits: Any,
    aligned_logits: Any,
    top_k: int,
) -> dict[str, float]:
    """Return aggregate-safe alignment diagnostics without token IDs or vectors."""

    source = source_logits.to(dtype=torch.float32)
    round_trip = aligned_logits.to(dtype=torch.float32)
    if source.ndim != 2 or round_trip.shape != source.shape:
        raise LatentAlignmentConfigurationError("diagnostic_logits_shape_invalid")
    width = int(source.shape[-1])
    count = max(1, min(int(top_k), width))
    source_values, source_indices = torch.topk(source, k=count, dim=-1)
    _, round_trip_indices = torch.topk(round_trip, k=count, dim=-1)
    source_log_probs = torch.log_softmax(source, dim=-1)
    source_log_probs_top = source_log_probs.gather(-1, source_indices)
    source_probs_top = source_log_probs_top.exp()
    source_conditional_log_probs = torch.log_softmax(source_values, dim=-1)
    source_conditional = source_conditional_log_probs.exp()
    direct_selected_logits = round_trip.gather(-1, source_indices)
    direct_conditional_log_probs = torch.log_softmax(
        direct_selected_logits, dim=-1
    )
    overlap = (
        source_indices.unsqueeze(-1) == round_trip_indices.unsqueeze(-2)
    ).any(dim=-1).to(dtype=torch.float32).mean()
    conditional_kl = (
        source_conditional
        * (source_conditional_log_probs - direct_conditional_log_probs)
    ).sum(dim=-1).mean()
    entropy = -(
        source_conditional * source_conditional_log_probs
    ).sum(dim=-1).mean()
    hidden_norm = hidden.to(dtype=torch.float32).norm(dim=-1).mean()
    aligned_norm = aligned.to(dtype=torch.float32).norm(dim=-1).mean()
    return {
        "hidden_norm": _finite_float(hidden_norm),
        "aligned_norm": _finite_float(aligned_norm),
        "norm_ratio": _finite_float(aligned_norm / hidden_norm.clamp_min(1e-6)),
        "source_topk_probability_mass": _finite_float(
            source_probs_top.sum(dim=-1).mean()
        ),
        "source_topk_conditional_entropy": _finite_float(entropy),
        "direct_lm_head_topk_overlap": _finite_float(overlap),
        "direct_lm_head_topk_kl": _finite_float(conditional_kl),
    }


def summarize_alignment_diagnostics(
    observations: list[Mapping[str, float]],
) -> dict[str, float | int]:
    if not observations:
        return {}
    keys = sorted({str(key) for item in observations for key in item})
    summary: dict[str, float | int] = {"observation_count": len(observations)}
    for key in keys:
        values = [
            float(item[key])
            for item in observations
            if key in item and math.isfinite(float(item[key]))
        ]
        if values:
            summary[f"{key}_mean"] = sum(values) / len(values)
            summary[f"{key}_min"] = min(values)
            summary[f"{key}_max"] = max(values)
    return sanitize_alignment_diagnostics(summary)


def sanitize_alignment_diagnostics(value: Any) -> dict[str, float | int]:
    """Keep only bounded aggregate diagnostics, never model inputs or tokens."""

    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, float | int] = {}
    count = value.get("observation_count")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        sanitized["observation_count"] = count
    for key in sorted(_ALIGNMENT_DIAGNOSTIC_FIELDS - {"observation_count"}):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            number = float(raw)
            if math.isfinite(number):
                sanitized[key] = number
    return sanitized


def write_ridge_realign_artifact(
    *,
    matrix: Any,
    matrix_path: str | os.PathLike[str],
    metadata_path: str | os.PathLike[str],
    model_revision_or_manifest_digest: str,
    input_embedding_digest: str,
    output_embedding_digest: str,
    target_norm: float,
    regularization: float,
    training_row_count: int,
    linear_system_relative_residual: float,
    embedding_fit_relative_rmse: float,
    identity_relative_rmse: float,
    embedding_fit_mean_cosine: float,
    extra_metadata: Mapping[str, object] | None = None,
    overwrite: bool = False,
) -> RidgeRealignArtifact:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise LatentAlignmentConfigurationError("artifact_writer_dependency_missing") from exc
    resolved_matrix = Path(matrix_path).expanduser().resolve()
    resolved_metadata = Path(metadata_path).expanduser().resolve()
    if resolved_matrix.suffix != ".npy":
        raise LatentAlignmentConfigurationError("artifact_matrix_suffix_invalid")
    if not model_revision_or_manifest_digest or not input_embedding_digest or not output_embedding_digest:
        raise LatentAlignmentConfigurationError("artifact_metadata_invalid")
    if not math.isfinite(float(target_norm)) or float(target_norm) <= 0.0:
        raise LatentAlignmentConfigurationError("artifact_shape_invalid")
    if not math.isfinite(float(regularization)) or float(regularization) <= 0.0:
        raise LatentAlignmentConfigurationError("artifact_metadata_invalid")
    if not torch.is_tensor(matrix) or matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise LatentAlignmentConfigurationError("artifact_shape_invalid")
    if not bool(torch.isfinite(matrix).all().item()):
        raise LatentAlignmentConfigurationError("artifact_matrix_invalid")
    raw_fit_values = (
        float(linear_system_relative_residual),
        float(embedding_fit_relative_rmse),
        float(identity_relative_rmse),
        float(embedding_fit_mean_cosine),
    )
    if (
        not all(math.isfinite(value) for value in raw_fit_values)
        or raw_fit_values[2] <= 0.0
    ):
        raise LatentAlignmentConfigurationError("artifact_fit_invalid")
    fit_error_ratio = raw_fit_values[1] / raw_fit_values[2]
    fit_values = (*raw_fit_values[:3], fit_error_ratio, raw_fit_values[3])
    if (
        int(training_row_count) < int(matrix.shape[0])
        or not all(math.isfinite(value) for value in fit_values)
        or fit_values[0] < 0.0
        or fit_values[0] > 1e-3
        or fit_values[1] < 0.0
        or fit_values[2] <= 0.0
        or fit_values[1] >= fit_values[2]
        or not 0.0 <= fit_error_ratio < 1.0
        or not -1.0 <= fit_values[4] <= 1.0
    ):
        raise LatentAlignmentConfigurationError("artifact_fit_invalid")
    if not overwrite and (resolved_matrix.exists() or resolved_metadata.exists()):
        raise LatentAlignmentConfigurationError("artifact_exists")
    resolved_matrix.parent.mkdir(parents=True, exist_ok=True)
    resolved_metadata.parent.mkdir(parents=True, exist_ok=True)
    array = matrix.detach().to(device="cpu", dtype=torch.float32).contiguous().numpy()
    matrix_temp = resolved_matrix.with_name(f".{resolved_matrix.name}.tmp")
    with matrix_temp.open("wb") as handle:
        np.save(handle, array, allow_pickle=False)
    os.replace(matrix_temp, resolved_matrix)
    matrix_sha256 = _sha256_file(resolved_matrix)
    metadata = {
        "schema_version": RIDGE_REALIGN_ARTIFACT_SCHEMA_VERSION,
        "method": RIDGE_REALIGN_V1,
        "matrix_file": resolved_matrix.name,
        "matrix_sha256": matrix_sha256,
        "model_revision_or_manifest_digest": str(model_revision_or_manifest_digest),
        "hidden_size": int(matrix.shape[0]),
        "matrix_shape": [int(matrix.shape[0]), int(matrix.shape[1])],
        "matrix_dtype": "float32",
        "target_norm": float(target_norm),
        "regularization": float(regularization),
        "input_embedding_digest": str(input_embedding_digest),
        "output_embedding_digest": str(output_embedding_digest),
        "fit_contract": RIDGE_REALIGN_FIT_CONTRACT,
        "training_row_count": int(training_row_count),
        "linear_system_relative_residual": float(
            linear_system_relative_residual
        ),
        "embedding_fit_relative_rmse": float(embedding_fit_relative_rmse),
        "identity_relative_rmse": float(identity_relative_rmse),
        "embedding_fit_error_ratio": fit_error_ratio,
        "embedding_fit_mean_cosine": float(embedding_fit_mean_cosine),
    }
    if extra_metadata:
        overlap = set(metadata).intersection(extra_metadata)
        if overlap:
            raise LatentAlignmentConfigurationError("artifact_metadata_invalid")
        metadata.update(dict(extra_metadata))
    metadata_temp = resolved_metadata.with_name(f".{resolved_metadata.name}.tmp")
    metadata_temp.write_text(stable_json_dumps(metadata) + "\n", encoding="utf-8")
    os.replace(metadata_temp, resolved_metadata)
    return RidgeRealignArtifact.load(
        matrix_path=resolved_matrix,
        metadata_path=resolved_metadata,
        expected_model_revision=str(model_revision_or_manifest_digest),
        expected_hidden_size=int(matrix.shape[0]),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise LatentAlignmentConfigurationError("artifact_unreadable") from exc
    return digest.hexdigest()


def _validate_matrix_header(path: Path, expected_shape: tuple[int, int]) -> None:
    try:
        import numpy as np
    except ImportError as exc:
        raise LatentAlignmentConfigurationError("numpy_unavailable") from exc
    try:
        values = np.load(path, mmap_mode="r", allow_pickle=False)
    except Exception as exc:
        raise LatentAlignmentConfigurationError("artifact_matrix_invalid") from exc
    try:
        valid = (
            values.ndim == 2
            and tuple(int(value) for value in values.shape) == expected_shape
            and str(values.dtype) == "float32"
            and bool(np.isfinite(values).all())
        )
    finally:
        del values
    if not valid:
        raise LatentAlignmentConfigurationError("artifact_matrix_invalid")


def _parse_bool(value: str, error_code: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise LatentAlignmentConfigurationError(error_code)


def _positive_int(value: str, error_code: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LatentAlignmentConfigurationError(error_code) from exc
    if parsed <= 0:
        raise LatentAlignmentConfigurationError(error_code)
    return parsed


def _positive_float(value: str, error_code: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LatentAlignmentConfigurationError(error_code) from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise LatentAlignmentConfigurationError(error_code)
    return parsed


def _finite_float(value: Any) -> float:
    number = float(value.detach().cpu().item() if hasattr(value, "detach") else value)
    if not math.isfinite(number):
        raise LatentAlignmentConfigurationError("diagnostic_nonfinite")
    return number


__all__ = [
    "RIDGE_REALIGN_ARTIFACT_SCHEMA_VERSION",
    "RIDGE_REALIGN_FIT_CONTRACT",
    "RIDGE_REALIGN_V1",
    "SOFT_TOKEN_TOPK_V1",
    "SUPPORTED_LATENT_ALIGNMENT_METHODS",
    "LatentAlignmentConfiguration",
    "LatentAlignmentConfigurationError",
    "RidgeRealignArtifact",
    "apply_ridge_realign",
    "collect_alignment_diagnostics",
    "invalid_alignment_configuration",
    "load_ridge_matrix",
    "resolve_alignment_configuration",
    "sanitize_alignment_diagnostics",
    "summarize_alignment_diagnostics",
    "write_ridge_realign_artifact",
]
