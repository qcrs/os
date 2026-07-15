from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.minimal_runner import run_minimal_benchmark_family
from v2.benchmark.models import BenchmarkLayer
from v2.benchmark.reporting import family_report_to_dict, write_json_report
from v2.benchmark.task_registry import load_registered_formal_samples


@dataclass(frozen=True)
class BackendMatrixVariant:
    variant_id: str
    state_pool_mode: str
    executor_transport: str
    expected_backend: str
    expected_metric: str


DEFAULT_BACKEND_MATRIX: tuple[BackendMatrixVariant, ...] = (
    BackendMatrixVariant(
        variant_id="mmap_loopback",
        state_pool_mode="mmap",
        executor_transport="loopback",
        expected_backend="mmap_file",
        expected_metric="state_pool_mmap_mode_count",
    ),
    BackendMatrixVariant(
        variant_id="shared_memory_loopback",
        state_pool_mode="shared_memory",
        executor_transport="loopback",
        expected_backend="shared_memory",
        expected_metric="state_pool_shared_memory_mode_count",
    ),
    BackendMatrixVariant(
        variant_id="memfd_subprocess",
        state_pool_mode="memfd",
        executor_transport="subprocess",
        expected_backend="memfd",
        expected_metric="state_pool_memfd_mode_count",
    ),
)


def validate_backend_report(
    report: dict[str, object],
    *,
    variant: BackendMatrixVariant,
    expected_case_count: int,
) -> dict[str, object]:
    """Validate backend realization without making a cross-backend speed claim."""
    errors: list[str] = []
    metadata = dict(report.get("metadata", {}))
    metrics = dict(report.get("aggregated_metrics", {}))
    telemetry = dict(report.get("telemetry_summary", {}))
    cases = list(report.get("cases", []))

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    case_count = int(metrics.get("case_count", 0) or 0)
    quality_pass_count = int(metrics.get("quality_floor_pass_count", 0) or 0)
    require(not report.get("missing_reason"), "runtime_missing")
    require(case_count == expected_case_count, f"case_coverage:{case_count}/{expected_case_count}")
    require(quality_pass_count == expected_case_count, f"quality_coverage:{quality_pass_count}/{expected_case_count}")
    require(len(cases) == expected_case_count, f"case_detail_coverage:{len(cases)}/{expected_case_count}")
    require(
        metadata.get("state_pool_mode_requested") == variant.state_pool_mode,
        f"requested_backend:{metadata.get('state_pool_mode_requested')}",
    )
    require(
        metadata.get("transport") == variant.executor_transport,
        f"transport:{metadata.get('transport')}",
    )
    require(
        metadata.get("state_pool_mode_used") == variant.expected_backend,
        f"actual_backend:{metadata.get('state_pool_mode_used')}",
    )
    require(
        int(telemetry.get(variant.expected_metric, 0) or 0) == expected_case_count,
        f"backend_metric:{variant.expected_metric}",
    )
    require(int(telemetry.get("state_pool_fallback_count", 0) or 0) == 0, "unexpected_backend_fallback")
    require(
        all(
            bool(dict(case).get("output_artifact_hash"))
            and bool(dict(case).get("quality_floor", {}).get("quality_floor_pass"))
            for case in cases
        ),
        "case_output_or_quality_contract",
    )
    if variant.expected_backend == "memfd":
        require(
            int(telemetry.get("memfd_transfer_count", 0) or 0) == expected_case_count,
            "memfd_transfer_coverage",
        )
        require(
            int(telemetry.get("memfd_publish_count", 0) or 0) == expected_case_count,
            "memfd_publish_coverage",
        )

    return {
        "ok": not errors,
        "errors": errors,
        "expected_case_count": expected_case_count,
        "observed_case_count": case_count,
        "observed_quality_pass_count": quality_pass_count,
        "requested_state_pool_mode": variant.state_pool_mode,
        "actual_state_pool_mode": metadata.get("state_pool_mode_used", ""),
        "executor_transport": metadata.get("transport", ""),
        "fallback_count": int(telemetry.get("state_pool_fallback_count", 0) or 0),
    }


def run_backend_matrix(
    *,
    output_path: Path,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "statebus-v2-p1-backend-matrix",
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    persistence_profile: str = "audit_full",
    variants: tuple[BackendMatrixVariant, ...] = DEFAULT_BACKEND_MATRIX,
) -> dict[str, object]:
    samples = load_registered_formal_samples()
    entries: list[dict[str, object]] = []
    for index, variant in enumerate(variants, start=1):
        report = run_minimal_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / variant.variant_id,
            runtime_root=runtime_root / variant.variant_id,
            socket_path=socket_path.with_name(f"p1b{index}.sock"),
            suite_id=f"{suite_id}-{variant.variant_id}",
            layer=BenchmarkLayer.L2,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            benchmark_tier="formal",
            claim_level="p1_backend_matrix_diagnostic",
            state_pool_mode=variant.state_pool_mode,
            persistence_profile=persistence_profile,
            executor_transport=variant.executor_transport,
        )
        report_payload = family_report_to_dict(report)
        validation = validate_backend_report(
            report_payload,
            variant=variant,
            expected_case_count=len(samples),
        )
        entries.append(
            {
                "variant": {
                    "id": variant.variant_id,
                    "state_pool_mode": variant.state_pool_mode,
                    "executor_transport": variant.executor_transport,
                    "expected_backend": variant.expected_backend,
                },
                "validation": validation,
                "report_path": report.report_path,
                "report": report_payload,
            }
        )

    payload = {
        "schema_version": "statebus.v2_backend_matrix.v1",
        "suite_id": suite_id,
        "claim_level": "matched_backend_realization_diagnostic",
        "claim_boundary": (
            "matched L2 semantic-state backend realization only; task_ms is recorded as diagnostic telemetry, "
            "not a cross-backend superiority claim; mmap/CAS lifecycle durability is distinct from "
            "shared_memory and memfd process-lifetime behavior"
        ),
        "benchmark_contract": {
            "benchmark_tier": "formal_registry",
            "layer": "L2",
            "case_count": len(samples),
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "persistence_profile": persistence_profile,
        },
        "entries": entries,
        "overall_ok": bool(entries) and all(bool(entry["validation"]["ok"]) for entry in entries),
    }
    write_json_report(output_path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the v2 P1 mmap/shared_memory/memfd backend matrix.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--socket-path", type=Path, required=True)
    parser.add_argument("--suite-id", default="statebus-v2-p1-backend-matrix")
    parser.add_argument("--role-path-mode", choices=("deterministic", "api", "local_vllm"), default="deterministic")
    parser.add_argument("--embedding-mode", choices=("deterministic", "local"), default="deterministic")
    parser.add_argument("--persistence-profile", choices=("audit_full", "benchmark_balanced"), default="audit_full")
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = run_backend_matrix(
        output_path=args.output,
        workspace_root=args.workspace_root,
        runtime_root=args.runtime_root,
        socket_path=args.socket_path,
        suite_id=args.suite_id,
        role_path_mode=args.role_path_mode,
        embedding_mode=args.embedding_mode,
        persistence_profile=args.persistence_profile,
    )
    print(args.output)
    return 0 if payload["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
