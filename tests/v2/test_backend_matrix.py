from __future__ import annotations

from v2.benchmark.backend_matrix import DEFAULT_BACKEND_MATRIX, validate_backend_report


def _report_for_variant(variant, *, fallback_count: int = 0) -> dict[str, object]:
    case_count = 2
    telemetry = {
        "state_pool_mmap_mode_count": 0,
        "state_pool_shared_memory_mode_count": 0,
        "state_pool_memfd_mode_count": 0,
        "state_pool_fallback_count": fallback_count,
        "memfd_transfer_count": 0,
        "memfd_publish_count": 0,
    }
    telemetry[variant.expected_metric] = case_count
    if variant.expected_backend == "memfd":
        telemetry["memfd_transfer_count"] = case_count
        telemetry["memfd_publish_count"] = case_count
    return {
        "missing_reason": "",
        "metadata": {
            "state_pool_mode_requested": variant.state_pool_mode,
            "state_pool_mode_used": variant.expected_backend,
            "transport": variant.executor_transport,
        },
        "aggregated_metrics": {
            "case_count": case_count,
            "quality_floor_pass_count": case_count,
        },
        "telemetry_summary": telemetry,
        "cases": [
            {
                "output_artifact_hash": "sha256:one",
                "quality_floor": {"quality_floor_pass": True},
            },
            {
                "output_artifact_hash": "sha256:two",
                "quality_floor": {"quality_floor_pass": True},
            },
        ],
    }


def test_backend_matrix_accepts_realized_mmap_shared_memory_and_memfd_variants() -> None:
    for variant in DEFAULT_BACKEND_MATRIX:
        validation = validate_backend_report(
            _report_for_variant(variant),
            variant=variant,
            expected_case_count=2,
        )
        assert validation["ok"] is True
        assert validation["actual_state_pool_mode"] == variant.expected_backend


def test_backend_matrix_rejects_fallback_or_missing_memfd_transfer() -> None:
    memfd = next(variant for variant in DEFAULT_BACKEND_MATRIX if variant.expected_backend == "memfd")
    report = _report_for_variant(memfd, fallback_count=1)
    report["telemetry_summary"]["memfd_transfer_count"] = 0

    validation = validate_backend_report(report, variant=memfd, expected_case_count=2)

    assert validation["ok"] is False
    assert "unexpected_backend_fallback" in validation["errors"]
    assert "memfd_transfer_coverage" in validation["errors"]
