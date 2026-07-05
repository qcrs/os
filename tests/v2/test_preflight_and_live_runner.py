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
            comparison_summary={},
            metadata={"benchmark_tier": "formal"},
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
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["benchmark_tier"] == "formal"
    assert captured["seed_replay_memory_by_layer"] == {}
    assert payload["suite_id"] == "statebus-v2-benchmark-formal"
    assert payload["metadata"]["benchmark_tier"] == "formal"


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
        "csv_table_profile",
        "incident_diagnosis",
        "long_doc_table",
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
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert captured["family"].family_id == "incident_diagnosis_v2"
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
        if family_name == "csv_table_profile":
            return SimpleNamespace(family_id="csv_table_profile_v1")
        if family_name == "incident_diagnosis":
            return SimpleNamespace(family_id="incident_diagnosis_v2")
        if family_name == "long_doc_table":
            return SimpleNamespace(family_id="long_doc_table_v1")
        raise AssertionError(f"unexpected family path: {path}")

    def fake_run_continuous_benchmark_collection(**kwargs):
        captured.update(kwargs)
        return BenchmarkContinuousCollectionReport(
            suite_id=str(kwargs["suite_id"]),
            family_reports=(),
            collection_summary={"family_count": 3.0, "continuous_round_count": 30.0},
            admissibility_summary={
                "csv_table_profile_v1": {},
                "incident_diagnosis_v2": {},
                "long_doc_table_v1": {},
            },
            metadata={
                "continuous_execution": True,
                "supported_continuous_execution_families": [
                    "csv_table_profile_v1",
                    "incident_diagnosis_v2",
                    "long_doc_table_v1",
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
        ],
    )
    live_runner_main()
    payload = json.loads(capsys.readouterr().out)
    assert [family.family_id for family in captured["families"]] == [
        "csv_table_profile_v1",
        "incident_diagnosis_v2",
        "long_doc_table_v1",
    ]
    assert payload["metadata"]["continuous_execution"] is True
    assert payload["collection_summary"]["family_count"] == 3.0


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
