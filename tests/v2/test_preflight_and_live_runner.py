from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.benchmark.models import (
    BenchmarkComparatorSuiteReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
)
from v2.benchmark.continuous_task_family import load_continuous_task_family
from v2.runtime import runtime_preflight
from v2.benchmark.live_runner import main as live_runner_main


def test_runtime_preflight_passes_for_deterministic_defaults() -> None:
    report = runtime_preflight(role_path_mode="deterministic", embedding_mode="deterministic")
    assert report.ok is True
    assert report.missing_reasons == ()
    assert report.metadata["embedding_device"] in {"cpu", "cuda:0"}


def test_runtime_preflight_fails_for_missing_local_embedding_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_model = tmp_path / "missing-model"
    monkeypatch.setenv("STATEBUS_EMBED_MODEL_PATH", str(missing_model))
    report = runtime_preflight(role_path_mode="deterministic", embedding_mode="local")
    assert report.ok is False
    assert any("embedding model missing" in reason for reason in report.missing_reasons)


def test_live_runner_preflight_outputs_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "preflight",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["role_path_mode"] == "deterministic"
    assert payload["embedding_mode"] == "deterministic"


def test_live_runner_preflight_fails_closed_for_missing_local_embedding(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_model = tmp_path / "missing-model"
    monkeypatch.setenv("STATEBUS_EMBED_MODEL_PATH", str(missing_model))
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "preflight",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "local",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(check["name"] == "embedding_model_path" and not check["ok"] for check in payload["checks"])


def test_live_runner_formal_suite_uses_formal_family_by_default(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_sample_family", lambda _: [])

    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="formal financial family",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_minimal_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="financial_report_analysis",
            layer_reports=(
                BenchmarkFamilyReport(
                    suite_id="formal",
                    layer=BenchmarkLayer.L3,
                    task_family="financial_report_analysis",
                    profile=profile,
                    cases=(),
                    metadata={"benchmark_tier": "formal"},
                ),
            ),
            waterfall_metrics={},
            comparison_summary={
                "text_L0_total_tokens": 120000.0,
                "protocol_L3_total_tokens": 65000.0,
                "protocol_vs_text_token_delta": -55000.0,
                "protocol_vs_text_prompt_bytes_delta": -120000.0,
                "protocol_vs_text_control_bytes_delta": -30000.0,
                "text_L0_quality_pass_count": 25.0,
                "protocol_L3_quality_pass_count": 25.0,
            },
            metadata={
                "benchmark_tier": "formal",
                "formal_text_protocol_benchmark": True,
                "state_pool_mode_requested": str(kwargs["state_pool_mode"]),
                "state_pool_mode_used": "memfd",
                "memfd_transfer_count": 25.0,
                "memfd_publish_count": 25.0,
                "memfd_bytes_transferred": 247046.0,
            },
            family_case_count=0,
            report_path=str(tmp_path / "statebus-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_minimal_benchmark_suite", fake_run_minimal_benchmark_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "formal",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--state-pool-mode",
            "memfd",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["benchmark_tier"] == "formal"
    assert captured["state_pool_mode"] == "memfd"
    assert captured["seed_replay_memory_by_layer"] == {}
    assert payload["suite_id"] == "statebus-v2-benchmark-formal"
    assert payload["metadata"]["benchmark_tier"] == "formal"
    assert payload["state_pool_mode_used"] == "memfd"
    assert payload["memfd_transfer_count"] == 25.0
    assert payload["memfd_publish_count"] == 25.0
    assert payload["memfd_bytes_transferred"] == 247046.0
    assert payload["formal_text_protocol_benchmark"] is True
    assert payload["protocol_vs_text_token_delta"] == -55000.0
    assert payload["protocol_vs_text_prompt_bytes_delta"] == -120000.0
    assert payload["protocol_vs_text_control_bytes_delta"] == -30000.0
    assert payload["text_L0_quality_pass_count"] == 25.0
    assert payload["protocol_L3_quality_pass_count"] == 25.0


def test_live_runner_formal_dev_max_cases_runs_bounded_formal_subset(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    sentinel_samples = [object() for _ in range(7)]

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_registered_formal_samples", lambda: sentinel_samples)

    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="mini formal subset",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_minimal_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="mini_formal",
            layer_reports=(
                BenchmarkFamilyReport(
                    suite_id="mini-formal",
                    layer=BenchmarkLayer.L3,
                    task_family="mini_formal",
                    profile=profile,
                    cases=(),
                    metadata={"benchmark_tier": kwargs["benchmark_tier"]},
                ),
            ),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"benchmark_tier": kwargs["benchmark_tier"]},
            family_case_count=len(kwargs["samples"]),
            report_path=str(tmp_path / "mini-formal-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_minimal_benchmark_suite", fake_run_minimal_benchmark_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "formal",
            "--benchmark-tier",
            "dev",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--max-cases",
            "5",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["benchmark_tier"] == "dev"
    assert captured["claim_level"] == "dev_mini_formal"
    assert len(captured["samples"]) == 5
    assert payload["selected_case_count"] == 5
    assert payload["available_case_count"] == 7
    assert payload["max_cases"] == 5


def test_live_runner_formal_suite_threads_subprocess_transport(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_sample_family", lambda _: [])

    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="formal financial family",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_minimal_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="financial_report_analysis",
            layer_reports=(
                BenchmarkFamilyReport(
                    suite_id="formal",
                    layer=BenchmarkLayer.L3,
                    task_family="financial_report_analysis",
                    profile=profile,
                    cases=(),
                    metadata={"benchmark_tier": "formal"},
                ),
            ),
            waterfall_metrics={},
            comparison_summary={},
            metadata={
                "benchmark_tier": "formal",
                "transport": str(kwargs["executor_transport"]),
                "state_pool_mode_requested": str(kwargs["state_pool_mode"]),
                "state_pool_mode_used": "memfd",
                "memfd_transfer_count": 1.0,
                "memfd_publish_count": 1.0,
                "memfd_bytes_transferred": 1024.0,
            },
            family_case_count=0,
            report_path=str(tmp_path / "statebus-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_minimal_benchmark_suite", fake_run_minimal_benchmark_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "formal",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--state-pool-mode",
            "memfd",
            "--transport",
            "subprocess",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["executor_transport"] == "subprocess"
    assert payload["transport"] == "subprocess"


def test_live_runner_threads_statebus_mode_to_dev_compare_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])

    def fake_compare_fixed_answer_with_external(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            mode_reports=(),
            comparison_summary={},
            report_path=str(tmp_path / "compare-report.json"),
            markdown_report_path=str(tmp_path / "compare-report.md"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.compare_fixed_answer_with_external",
        fake_compare_fixed_answer_with_external,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "compare",
            "--benchmark-tier",
            "dev",
            "--statebus-mode",
            "cold-start",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["statebus_mode"] == "cold-start"
    assert captured["benchmark_tier"] == "dev"
    assert payload["suite_id"] == "statebus-v2-benchmark-cold-start-compare"
    assert payload["benchmark_tier"] == "dev"


def test_live_runner_formal_compare_uses_registered_fixed_answer_adapter(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    sentinel_samples = ["formal-fixed-answer-registry"]

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_registered_formal_fixed_answer_samples",
        lambda: sentinel_samples,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_fixed_answer_family",
        lambda _: (_ for _ in ()).throw(AssertionError("formal default compare should use registry adapter")),
    )

    def fake_compare_fixed_answer_with_external(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="formal_registry",
            mode_reports=(),
            comparison_summary={},
            metadata={
                "formal_compare_case_count": 25,
                "formal_compare_family_count": 5,
                "formal_compare_full_registry_coverage": True,
            },
            benchmark_tier="formal",
            report_path=str(tmp_path / "formal-compare-report.json"),
            markdown_report_path=str(tmp_path / "formal-compare-report.md"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.compare_fixed_answer_with_external",
        fake_compare_fixed_answer_with_external,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "compare",
            "--benchmark-tier",
            "formal",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["samples"] == sentinel_samples
    assert captured["benchmark_tier"] == "formal"
    assert captured["claim_level"] == "first_pass"
    assert payload["formal_compare_case_count"] == 25
    assert payload["formal_compare_family_count"] == 5
    assert payload["formal_compare_full_registry_coverage"] is True


def test_live_runner_formal_compare_selects_case_id_as_diagnostic(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    samples = [
        SimpleNamespace(task_id="benchmark-sample-1"),
        SimpleNamespace(task_id="benchmark-sample-7"),
    ]
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_registered_formal_fixed_answer_samples",
        lambda: samples,
    )

    def fake_compare(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="formal_registry",
            mode_reports=(),
            comparison_summary={},
            benchmark_tier="formal",
            claim_level=str(kwargs["claim_level"]),
            report_path=str(tmp_path / "compare.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.compare_fixed_answer_with_external", fake_compare)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "compare",
            "--benchmark-tier",
            "formal",
            "--case-id",
            "benchmark-sample-7",
        ],
    )

    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert [sample.task_id for sample in captured["samples"]] == ["benchmark-sample-7"]
    assert captured["claim_level"] == "diagnostic"
    assert payload["execution_scope"] == "diagnostic_partial"
    assert payload["formal_headline_eligible"] is False


def test_live_runner_continuous_max_cases_runs_two_round_l3_diagnostic(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/cross_period_financial")
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_continuous_task_family", lambda _: family)

    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="continuous diagnostic",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_family(**kwargs):
        captured.update(kwargs)
        return BenchmarkFamilyReport(
            suite_id=str(kwargs["suite_id"]),
            layer=kwargs["layer"],
            task_family=kwargs["family"].family_id,
            profile=profile,
            cases=(),
            metadata=dict(kwargs["metadata_extra"]),
            report_path=str(tmp_path / "continuous-l3.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_continuous_benchmark_family", fake_run_family)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous",
            "--family",
            "cross_period_financial",
            "--max-cases",
            "2",
            "--layer",
            "L3",
        ],
    )

    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].round_count == 2
    assert [round_.round for round_ in captured["family"].rounds] == [1, 2]
    assert captured["layer"] == BenchmarkLayer.L3
    assert captured["enforce_expected_metric_effects"] is False
    assert payload["selected_round_count"] == 2
    assert payload["available_round_count"] == 10
    assert payload["formal_headline_eligible"] is False


def test_live_runner_statebus_l3_replay_ready_uses_single_family_runner(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    samples = [SimpleNamespace(task_id="benchmark-sample-7")]
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_registered_formal_fixed_answer_samples",
        lambda: samples,
    )
    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="replay diagnostic",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_family(**kwargs):
        captured.update(kwargs)
        return BenchmarkFamilyReport(
            suite_id=str(kwargs["suite_id"]),
            layer=BenchmarkLayer.L3,
            task_family="formal_registry",
            profile=profile,
            cases=(),
            metadata={
                **dict(kwargs["metadata_extra"]),
                "statebus_mode": "replay_ready",
                "replay_history_source": "history_bootstrap",
            },
            report_path=str(tmp_path / "statebus-l3.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_fixed_answer_benchmark_family", fake_run_family)
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_fixed_answer_suite",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("full suite must not run")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "formal",
            "--statebus-mode",
            "replay-ready",
            "--case-id",
            "benchmark-sample-7",
            "--layer",
            "L3",
        ],
    )

    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["layer"] == BenchmarkLayer.L3
    assert captured["statebus_mode"] == "replay-ready"
    assert captured["claim_level"] == "diagnostic"
    assert payload["effective_replay_history_source"] == "history_bootstrap"
    assert payload["formal_headline_eligible"] is False


def test_live_runner_formal_statebus_replay_ready_uses_fixed_answer_runner(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    sentinel_samples = ["formal-statebus-1", "formal-statebus-2"]

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_registered_formal_fixed_answer_samples",
        lambda: sentinel_samples,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_minimal_benchmark_suite",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("formal statebus must not use the minimal cold-start ladder")
        ),
    )

    profile = BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="formal replay-ready",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
    )

    def fake_run_fixed_answer_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="formal_registry",
            layer_reports=(
                BenchmarkFamilyReport(
                    suite_id="formal-statebus-l3",
                    layer=BenchmarkLayer.L3,
                    task_family="formal_registry",
                    profile=profile,
                    cases=(),
                    metadata={
                        "benchmark_tier": "formal",
                        "replay_history_source": "history_bootstrap",
                    },
                ),
            ),
            waterfall_metrics={},
            comparison_summary={},
            metadata={
                "benchmark_tier": "formal",
                "statebus_mode": "replay_ready",
            },
            family_case_count=len(kwargs["samples"]),
            report_path=str(tmp_path / "formal-statebus-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_fixed_answer_suite",
        fake_run_fixed_answer_suite,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "formal",
            "--statebus-mode",
            "replay-ready",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--max-cases",
            "2",
        ],
    )

    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["samples"] == sentinel_samples
    assert captured["benchmark_tier"] == "formal"
    assert captured["claim_level"] == "first_pass"
    assert captured["statebus_mode"] == "replay-ready"
    assert payload["effective_statebus_mode"] == "replay_ready"
    assert payload["effective_replay_history_source"] == "history_bootstrap"
    assert payload["selected_case_count"] == 2
    assert payload["available_case_count"] == 2


def test_live_runner_threads_persistence_profile_to_compare_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])

    def fake_compare_fixed_answer_with_external(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            mode_reports=(),
            comparison_summary={},
            report_path=str(tmp_path / "compare-report.json"),
            markdown_report_path=str(tmp_path / "compare-report.md"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.compare_fixed_answer_with_external",
        fake_compare_fixed_answer_with_external,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "compare",
            "--benchmark-tier",
            "dev",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--persistence-profile",
            "benchmark_balanced",
        ],
    )
    live_runner_main()
    json.loads(capsys.readouterr().out)
    assert captured["persistence_profile"] == "benchmark_balanced"


def test_live_runner_routes_carrier_compare_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])

    def fake_run_fixed_answer_internal_carrier_compare_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            mode_reports=(),
            comparison_summary={},
            report_path=str(tmp_path / "carrier-report.json"),
            markdown_report_path=str(tmp_path / "carrier-report.md"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_fixed_answer_internal_carrier_compare_suite",
        fake_run_fixed_answer_internal_carrier_compare_suite,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "carrier-compare",
            "--benchmark-tier",
            "dev",
            "--statebus-mode",
            "cold-start",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["statebus_mode"] == "cold-start"
    assert captured["benchmark_tier"] == "dev"
    assert payload["suite_id"] == "statebus-v2-benchmark-cold-start-carrier-compare"


def test_live_runner_routes_formal_carrier_compare_to_registry_adapter(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    sentinel_samples = ["formal-carrier-registry"]

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_registered_formal_fixed_answer_samples",
        lambda: sentinel_samples,
    )

    def fake_run_fixed_answer_internal_carrier_compare_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkComparatorSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="formal_registry",
            mode_reports=(),
            comparison_summary={},
            metadata={
                "formal_compare_case_count": 25,
                "formal_compare_family_count": 5,
                "formal_compare_full_registry_coverage": True,
                "formal_text_protocol_benchmark": True,
            },
            benchmark_tier="formal",
            report_path=str(tmp_path / "formal-carrier-report.json"),
            markdown_report_path=str(tmp_path / "formal-carrier-report.md"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_fixed_answer_internal_carrier_compare_suite",
        fake_run_fixed_answer_internal_carrier_compare_suite,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_minimal_benchmark_suite",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("formal carrier compare should not use minimal ladder")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "carrier-compare",
            "--benchmark-tier",
            "formal",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["samples"] == sentinel_samples
    assert captured["benchmark_tier"] == "formal"
    assert payload["formal_text_protocol_benchmark"] is True


def test_live_runner_routes_flagship_ablation_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: ["fixed"])

    def fake_load_continuous_task_family(path: Path):
        return SimpleNamespace(family_id=path.name)

    def fake_run_non_text_flagship_ablation_report(**kwargs):
        captured.update(kwargs)
        return {
            "suite_id": str(kwargs["suite_id"]),
            "role_path_mode": kwargs["role_path_mode"],
            "embedding_mode": kwargs["embedding_mode"],
            "report_path": str(tmp_path / "flagship.json"),
        }

    monkeypatch.setattr("v2.benchmark.live_runner.load_continuous_task_family", fake_load_continuous_task_family)
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_non_text_flagship_ablation_report",
        fake_run_non_text_flagship_ablation_report,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "flagship-ablation",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == "statebus-v2-benchmark-non-text-flagship-ablation"
    assert captured["fixed_samples"] == ["fixed"]
    assert [family.family_id for family in captured["continuous_families"]] == [
        "formal_operating_metrics",
        "formal_financial_reports",
    ]
    assert [family.family_id for family in captured["replay_families"]] == [
        "csv_correlation_replay",
        "cross_period_financial",
        "long_doc_metric_replay",
    ]
    assert captured["role_path_mode"] == "deterministic"


def test_live_runner_routes_statebus_family_alias_to_continuous_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/incident_diagnosis")
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_continuous_task_family", lambda path: family)

    def fake_run_continuous_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family=family.family_id,
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"family_id": family.family_id},
            family_case_count=10,
            report_path=str(tmp_path / "incident-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_suite",
        fake_run_continuous_benchmark_suite,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--family",
            "incident_diagnosis_v2",
            "--replay-mode",
            "replay-ready",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--task-schedule-plan",
            "cache_hostile",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].family_id == "incident_diagnosis_v2"
    assert captured["task_schedule_plan"] == "cache_hostile"
    assert payload["suite_id"] == "statebus-v2-benchmark-continuous-incident_diagnosis_v2"


def test_live_runner_routes_replay_negative_audit_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    def fake_run_replay_negative_audit(**kwargs):
        captured.update(kwargs)
        return {
            "suite_id": str(kwargs["suite_id"]),
            "audit_pass": True,
            "report_path": str(tmp_path / "replay-negative.json"),
        }

    monkeypatch.setattr("v2.benchmark.live_runner.run_replay_negative_audit", fake_run_replay_negative_audit)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "replay-negative-audit",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == "statebus-v2-benchmark-replay-negative-audit"
    assert payload["audit_pass"] is True
    assert captured["runtime_root"].name == "replay-negative-audit"


def test_live_runner_continuous_design_audit_outputs_family_payload(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous-design-audit",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["family_id"] == "csv_table_profile_v1"
    assert payload["claim_tier"] == "formal_primary"
    assert payload["round_count"] == 10
    assert payload["dataset_count"] == 2


def test_live_runner_continuous_suite_outputs_suite_payload(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    def fake_run_continuous_benchmark_suite(**kwargs):
        captured.update(kwargs)
        profile = BenchmarkLayerProfile(
            layer=BenchmarkLayer.L3,
            description="continuous",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
        )
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="csv_table_profile_v1",
            layer_reports=(
                BenchmarkFamilyReport(
                    suite_id=str(kwargs["suite_id"]),
                    layer=BenchmarkLayer.L3,
                    task_family="csv_table_profile_v1",
                    profile=profile,
                    cases=(),
                    metadata={"continuous_execution": True},
                ),
            ),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"continuous_execution": True},
            family_case_count=10,
            report_path=str(tmp_path / "continuous-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_suite",
        fake_run_continuous_benchmark_suite,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous",
            "--family-dir",
            "v2/benchmark/samples/continuous_task_families/csv_table_profile",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].family_id == "csv_table_profile_v1"
    assert payload["suite_id"] == "statebus-v2-benchmark-continuous"
    assert payload["metadata"]["continuous_execution"] is True
    assert payload["family_case_count"] == 10


def test_live_runner_continuous_family_flag_selects_single_family_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    family = SimpleNamespace(family_id="csv_table_profile_v1")
    monkeypatch.setattr("v2.benchmark.live_runner.load_continuous_task_family", lambda path: family)

    def fake_run_continuous_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family=family.family_id,
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"continuous_execution": True, "family_id": family.family_id},
            family_case_count=10,
            report_path=str(tmp_path / "continuous-family-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_suite",
        fake_run_continuous_benchmark_suite,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_collection",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("collection path should not run for --family")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous",
            "--family",
            "csv_table_profile_v1",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].family_id == "csv_table_profile_v1"
    assert payload["task_family"] == "csv_table_profile_v1"
    assert payload["metadata"]["family_id"] == "csv_table_profile_v1"


def test_live_runner_continuous_defaults_to_formal_collection(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    def fake_load_continuous_task_family(path: Path):
        family_name = path.name
        if family_name == "formal_operating_metrics":
            return SimpleNamespace(family_id="formal_operating_metrics_v1")
        if family_name == "formal_financial_reports":
            return SimpleNamespace(family_id="formal_financial_reports_v1")
        raise AssertionError(f"unexpected family path: {path}")

    def fake_run_continuous_benchmark_collection(**kwargs):
        captured.update(kwargs)
        return BenchmarkContinuousCollectionReport(
            suite_id=str(kwargs["suite_id"]),
            family_reports=(),
            collection_summary={"family_count": 2.0, "continuous_round_count": 10.0},
            admissibility_summary={
                "formal_operating_metrics_v1": {},
                "formal_financial_reports_v1": {},
            },
            metadata={
                "continuous_execution": True,
                "supported_continuous_execution_families": [
                    "formal_operating_metrics_v1",
                    "formal_financial_reports_v1",
                ],
            },
            report_path=str(tmp_path / "continuous-collection-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_continuous_task_family",
        fake_load_continuous_task_family,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_collection",
        fake_run_continuous_benchmark_collection,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
            "--state-pool-mode",
            "shared_memory",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert [family.family_id for family in captured["families"]] == [
        "formal_operating_metrics_v1",
        "formal_financial_reports_v1",
    ]
    assert payload["metadata"]["continuous_execution"] is True
    assert payload["collection_summary"]["family_count"] == 2.0
    assert payload["collection_summary"]["continuous_round_count"] == 10.0
    assert captured["state_pool_mode"] == "shared_memory"


def test_live_runner_continuous_replay_defaults_to_replay_collection(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    def fake_load_continuous_task_family(path: Path):
        family_name = path.name
        if family_name == "csv_correlation_replay":
            return SimpleNamespace(family_id="csv_correlation_replay_v1")
        if family_name == "cross_period_financial":
            return SimpleNamespace(family_id="cross_period_financial_v1")
        if family_name == "long_doc_metric_replay":
            return SimpleNamespace(family_id="long_doc_metric_replay_v1")
        raise AssertionError(f"unexpected family path: {path}")

    def fake_run_continuous_benchmark_collection(**kwargs):
        captured.update(kwargs)
        return BenchmarkContinuousCollectionReport(
            suite_id=str(kwargs["suite_id"]),
            family_reports=(),
            collection_summary={
                "family_count": 3.0,
                "continuous_round_count": 30.0,
                "replay_headline_eligible_family_count": 3.0,
            },
            admissibility_summary={
                "csv_correlation_replay_v1": {"eligible_for_replay_headline": True},
                "cross_period_financial_v1": {"eligible_for_replay_headline": True},
                "long_doc_metric_replay_v1": {"eligible_for_replay_headline": True},
            },
            metadata={
                "continuous_execution": True,
                "collection_scope": "formal_replay_task_families",
                "supported_continuous_execution_families": [
                    "csv_correlation_replay_v1",
                    "cross_period_financial_v1",
                    "long_doc_metric_replay_v1",
                ],
            },
            report_path=str(tmp_path / "continuous-replay-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.load_continuous_task_family",
        fake_load_continuous_task_family,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_collection",
        fake_run_continuous_benchmark_collection,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous-replay",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert [family.family_id for family in captured["families"]] == [
        "csv_correlation_replay_v1",
        "cross_period_financial_v1",
        "long_doc_metric_replay_v1",
    ]
    assert captured["collection_scope"] == "formal_replay_task_families"
    assert payload["metadata"]["continuous_execution"] is True
    assert payload["metadata"]["collection_scope"] == "formal_replay_task_families"
    assert payload["collection_summary"]["family_count"] == 3.0


def test_live_runner_continuous_replay_family_flag_selects_single_family_suite(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )

    family = SimpleNamespace(family_id="long_doc_metric_replay_v1")
    monkeypatch.setattr("v2.benchmark.live_runner.load_continuous_task_family", lambda path: family)

    def fake_run_continuous_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family=family.family_id,
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"continuous_execution": True, "family_id": family.family_id},
            family_case_count=10,
            report_path=str(tmp_path / "continuous-replay-family-report.json"),
        )

    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_suite",
        fake_run_continuous_benchmark_suite,
    )
    monkeypatch.setattr(
        "v2.benchmark.live_runner.run_continuous_benchmark_collection",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("collection path should not run for --family")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "continuous-replay",
            "--family",
            "long_doc_metric_replay_v1",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].family_id == "long_doc_metric_replay_v1"
    assert payload["task_family"] == "long_doc_metric_replay_v1"
    assert payload["metadata"]["family_id"] == "long_doc_metric_replay_v1"


def test_live_runner_uses_statebus_env_defaults_for_paths(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("STATEBUS_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("STATEBUS_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])

    def fake_run_fixed_answer_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            family_case_count=0,
            report_path=str(tmp_path / "statebus-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_fixed_answer_suite", fake_run_fixed_answer_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "dev",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    json.loads(capsys.readouterr().out)
    assert captured["workspace_root"] == tmp_path / "work" / "v2-live" / "workspaces"
    assert captured["runtime_root"] == tmp_path / "runs" / "v2-live" / "runtime"
    assert captured["socket_path"] == tmp_path / "runs" / "v2-live" / "control.sock"
    assert captured["statebus_mode"] == "cold-start"


def test_live_runner_rejects_cold_start_with_synthetic_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "dev",
            "--statebus-mode",
            "cold-start",
            "--seed-replay-memory",
        ],
    )
    with pytest.raises(SystemExit, match="cold-start mode forbids synthetic replay seeding"):
        live_runner_main()


def test_live_runner_accepts_replay_ready_without_explicit_seed(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])
    
    def fake_run_fixed_answer_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"statebus_mode": "replay_ready"},
            family_case_count=0,
            report_path=str(tmp_path / "statebus-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_fixed_answer_suite", fake_run_fixed_answer_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "dev",
            "--statebus-mode",
            "replay-ready",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["statebus_mode"] == "replay-ready"
    assert captured["seed_replay_memory"] is False
    assert captured["suite_id"] == "statebus-v2-benchmark-statebus"
    assert payload["metadata"]["statebus_mode"] == "replay_ready"


def test_live_runner_accepts_replay_ready_when_explicit_seed_is_present(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "v2.benchmark.live_runner.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    monkeypatch.setattr("v2.benchmark.live_runner.load_fixed_answer_family", lambda _: [])

    def fake_run_fixed_answer_suite(**kwargs):
        captured.update(kwargs)
        return BenchmarkSuiteReport(
            suite_id=str(kwargs["suite_id"]),
            task_family="fixed_answer_route_tool",
            layer_reports=(),
            waterfall_metrics={},
            comparison_summary={},
            metadata={"statebus_mode": "replay_ready"},
            family_case_count=0,
            report_path=str(tmp_path / "statebus-report.json"),
        )

    monkeypatch.setattr("v2.benchmark.live_runner.run_fixed_answer_suite", fake_run_fixed_answer_suite)
    monkeypatch.setattr(
        "sys.argv",
        [
            "statebus-v2-live",
            "--suite",
            "statebus",
            "--benchmark-tier",
            "dev",
            "--statebus-mode",
            "replay-ready",
            "--seed-replay-memory",
            "--role-path-mode",
            "deterministic",
            "--embedding-mode",
            "deterministic",
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["statebus_mode"] == "replay-ready"
    assert captured["seed_replay_memory"] is True
    assert captured["suite_id"] == "statebus-v2-benchmark-synthetic-seed-statebus"
    assert payload["metadata"]["statebus_mode"] == "replay_ready"
