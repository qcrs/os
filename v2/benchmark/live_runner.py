from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

from v2.benchmark.comparator_runner import compare_fixed_answer_with_external
from v2.benchmark.continuous_runner import (
    run_continuous_benchmark_collection,
    run_continuous_benchmark_family,
    run_continuous_benchmark_suite,
)
from v2.benchmark.continuous_task_family import ContinuousTaskFamily, load_continuous_task_family
from v2.benchmark.external_text_baseline import run_external_text_suite
from v2.benchmark.fixed_answer_runner import (
    load_fixed_answer_family,
    run_fixed_answer_benchmark_family,
    run_fixed_answer_internal_carrier_compare_suite,
    run_fixed_answer_suite,
)
from v2.benchmark.flagship_ablation import run_non_text_flagship_ablation_report
from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples
from v2.benchmark.minimal_runner import load_sample_family, run_minimal_benchmark_suite
from v2.benchmark.models import BenchmarkLayer
from v2.benchmark.reporting import (
    continuous_collection_report_to_dict,
    family_report_to_dict,
    suite_report_to_dict,
)
from v2.benchmark.replay_negative_audit import run_replay_negative_audit
from v2.benchmark.task_registry import formal_family_payload, load_registered_formal_samples
from v2.runtime import runtime_preflight
from v2.utils import stable_json_dumps


def _default_dev_family_dir() -> Path:
    return Path(__file__).with_name("samples") / "fixed_answer_family"


def _default_formal_family_dir() -> Path:
    return Path(__file__).with_name("samples") / "formal_financial_family"


def _default_continuous_family_dir() -> Path:
    return Path(__file__).with_name("samples") / "continuous_task_families" / "csv_table_profile"


def _default_continuous_family_roots() -> tuple[Path, ...]:
    base = Path(__file__).with_name("samples") / "continuous_task_families"
    return (
        base / "formal_operating_metrics",
        base / "formal_financial_reports",
    )


def _default_continuous_replay_family_dir() -> Path:
    return Path(__file__).with_name("samples") / "continuous_task_families" / "long_doc_metric_replay"


def _default_continuous_replay_family_roots() -> tuple[Path, ...]:
    base = Path(__file__).with_name("samples") / "continuous_task_families"
    return (
        base / "csv_correlation_replay",
        base / "cross_period_financial",
        base / "long_doc_metric_replay",
    )


def _continuous_family_dir_by_id(family_id: str) -> Path:
    base = Path(__file__).with_name("samples") / "continuous_task_families"
    mapping = {
        "csv_table_profile_v1": base / "csv_table_profile",
        "csv_table_profile": base / "csv_table_profile",
        "csv_correlation_replay_v1": base / "csv_correlation_replay",
        "csv_correlation_replay": base / "csv_correlation_replay",
        "long_doc_table_v1": base / "long_doc_table",
        "long_doc_table": base / "long_doc_table",
        "long_doc_metric_replay_v1": base / "long_doc_metric_replay",
        "long_doc_metric_replay": base / "long_doc_metric_replay",
        "incident_diagnosis_v2": base / "incident_diagnosis",
        "incident_diagnosis": base / "incident_diagnosis",
        "cross_period_financial_v1": base / "cross_period_financial",
        "cross_period_financial": base / "cross_period_financial",
        "kv_prefix_reuse_v1": base / "kv_prefix_reuse",
        "kv_prefix_reuse": base / "kv_prefix_reuse",
        "formal_operating_metrics_v1": base / "formal_operating_metrics",
        "formal_operating_metrics": base / "formal_operating_metrics",
        "formal_financial_reports_v1": base / "formal_financial_reports",
        "formal_financial_reports": base / "formal_financial_reports",
    }
    resolved = mapping.get(family_id.strip())
    if resolved is None:
        raise SystemExit(f"unsupported continuous family id: {family_id}")
    return resolved


def _default_workspace_root() -> Path:
    return Path(os.getenv("STATEBUS_WORKDIR", "/tmp")) / "v2-live" / "workspaces"


def _default_runtime_root() -> Path:
    return Path(os.getenv("STATEBUS_RUNS_DIR", "/tmp")) / "v2-live" / "runtime"


def _default_socket_path() -> Path:
    return _default_runtime_root().parent / "control.sock"


def _statebus_suite_prefix(
    *,
    suite_id: str,
    statebus_mode: str,
    seed_replay_memory: bool,
) -> str:
    if statebus_mode == "cold-start":
        return f"{suite_id}-{statebus_mode}"
    if seed_replay_memory:
        return f"{suite_id}-synthetic-seed"
    return suite_id


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run StateBus v2 benchmark suites.")
    parser.add_argument(
        "--suite",
        choices=(
            "formal",
            "statebus",
            "external",
            "compare",
            "carrier-compare",
            "continuous",
            "continuous-replay",
            "continuous-design-audit",
            "flagship-ablation",
            "replay-negative-audit",
            "preflight",
        ),
        default="preflight",
        help="suite to run",
    )
    parser.add_argument(
        "--benchmark-tier",
        choices=("formal", "dev"),
        default="formal",
        help="formal financial benchmark tier or dev fixed-answer tier",
    )
    parser.add_argument(
        "--family-dir",
        type=Path,
        default=None,
        help="sample family directory; defaults to the tier-appropriate family",
    )
    parser.add_argument(
        "--family",
        default="",
        help="continuous family id alias; resolves to a built-in continuous family directory",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="workspace root",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=_default_runtime_root(),
        help="runtime root",
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=_default_socket_path(),
        help="control socket path",
    )
    parser.add_argument(
        "--role-path-mode",
        default="deterministic",
        choices=("deterministic", "api", "local_vllm"),
        help="planner/retriever/executor/summarizer mode",
    )
    parser.add_argument(
        "--embedding-mode",
        default="deterministic",
        choices=("deterministic", "local"),
        help="retrieval embedding mode",
    )
    parser.add_argument(
        "--state-pool-mode",
        default="auto",
        choices=("auto", "mmap", "shared_memory", "memfd"),
        help="semantic state pool backend selection for StateBus runtime lanes",
    )
    parser.add_argument(
        "--suite-id",
        default="statebus-v2-benchmark",
        help="suite id prefix",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="optional cap for fixed/formal cases or continuous rounds; 0 means no cap",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="select an exact fixed/formal task id; repeat for multiple cases",
    )
    parser.add_argument(
        "--layer",
        choices=tuple(layer.value for layer in BenchmarkLayer),
        default="",
        help="diagnostic single-layer execution for statebus or continuous suites",
    )
    parser.add_argument(
        "--statebus-mode",
        default="cold-start",
        choices=("replay-ready", "cold-start"),
        help="StateBus benchmark mode",
    )
    parser.add_argument(
        "--replay-mode",
        default="",
        choices=("", "replay-ready", "cold-start"),
        help="alias for --statebus-mode",
    )
    parser.add_argument(
        "--seed-replay-memory",
        action="store_true",
        help="dev-only synthetic replay seed for assisted diagnostics",
    )
    parser.add_argument(
        "--persistence-profile",
        default="audit_full",
        choices=("audit_full", "benchmark_balanced"),
        help="audit persistence profile",
    )
    parser.add_argument(
        "--transport",
        default="loopback",
        choices=("loopback", "subprocess"),
        help="executor control-plane transport for supported suites",
    )
    parser.add_argument(
        "--task-schedule-plan",
        default="input",
        choices=("input", "cache_friendly", "cache_hostile"),
        help="continuous task order for KV prefix probes",
    )
    return parser


def _resolved_family_dir(args: argparse.Namespace) -> Path:
    if args.family:
        return _continuous_family_dir_by_id(args.family)
    if args.family_dir is not None:
        return args.family_dir
    if args.suite == "continuous-design-audit":
        return _default_continuous_family_dir()
    if args.suite == "continuous-replay":
        return _default_continuous_replay_family_dir()
    if args.benchmark_tier == "formal":
        return _default_formal_family_dir()
    return _default_dev_family_dir()


def _uses_explicit_single_family(args: argparse.Namespace) -> bool:
    return bool(args.family) or args.family_dir is not None


def _limit_cases(samples: list, max_cases: int) -> list:
    if max_cases <= 0:
        return samples
    return samples[:max_cases]


def _select_cases(samples: list, case_ids: list[str], max_cases: int) -> list:
    selected = samples
    normalized_ids = tuple(dict.fromkeys(item.strip() for item in case_ids if item.strip()))
    if normalized_ids:
        by_id = {str(sample.task_id): sample for sample in samples}
        missing = [case_id for case_id in normalized_ids if case_id not in by_id]
        if missing:
            raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
        selected = [by_id[case_id] for case_id in normalized_ids]
    return _limit_cases(selected, max_cases)


def _limit_continuous_family(
    family: ContinuousTaskFamily,
    max_cases: int,
) -> tuple[ContinuousTaskFamily, int]:
    original_round_count = int(
        getattr(family, "round_count", len(getattr(family, "rounds", ())) or 10)
    )
    if max_cases <= 0 or max_cases >= original_round_count:
        return family, original_round_count
    selected_rounds = family.rounds[:max_cases]
    return (
        replace(
            family,
            round_count=len(selected_rounds),
            rounds=selected_rounds,
        ),
        original_round_count,
    )


def _continuous_round_count(family: ContinuousTaskFamily) -> int:
    return int(getattr(family, "round_count", len(getattr(family, "rounds", ()))))


def _diagnostic_scope(*, selected_count: int, available_count: int, layer: str) -> str:
    if layer or selected_count < available_count:
        return "diagnostic_partial"
    return "full"


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.replay_mode:
        args.statebus_mode = args.replay_mode
    preflight = runtime_preflight(
        role_path_mode=args.role_path_mode,
        embedding_mode=args.embedding_mode,
    )
    if args.suite == "preflight":
        print(stable_json_dumps(preflight.canonical_payload()))
        return

    if not preflight.ok:
        print(stable_json_dumps(preflight.canonical_payload()))
        raise SystemExit(2)

    if args.transport != "loopback" and not (args.suite == "formal" and args.benchmark_tier == "formal"):
        raise SystemExit("--transport is currently only supported for --suite formal --benchmark-tier formal")
    if args.case_id and args.suite in {"continuous", "continuous-replay", "continuous-design-audit"}:
        raise SystemExit("--case-id is only supported for fixed/formal suites; use --max-cases for continuous rounds")
    if args.layer and args.suite not in {"statebus", "continuous", "continuous-replay"}:
        raise SystemExit("--layer is only supported for statebus or continuous diagnostic suites")

    family_dir = _resolved_family_dir(args)
    if args.suite == "replay-negative-audit":
        report = run_replay_negative_audit(
            runtime_root=args.runtime_root / "replay-negative-audit",
            suite_id=f"{args.suite_id}-replay-negative-audit",
        )
        print(stable_json_dumps(report))
        return
    if args.suite == "continuous-design-audit":
        family = load_continuous_task_family(family_dir)
        print(stable_json_dumps(family.design_audit_payload()))
        return
    if args.suite == "continuous":
        if not _uses_explicit_single_family(args):
            loaded_families = tuple(
                load_continuous_task_family(path) for path in _default_continuous_family_roots()
            )
            limited = tuple(
                _limit_continuous_family(family, args.max_cases)
                for family in loaded_families
            )
            families = tuple(item[0] for item in limited)
            execution_scope = (
                "diagnostic_partial"
                if any(_continuous_round_count(family) < original for family, original in limited)
                else "full"
            )
            report = run_continuous_benchmark_collection(
                families=families,
                workspace_root=args.workspace_root,
                runtime_root=args.runtime_root,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous",
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                state_pool_mode=args.state_pool_mode,
                persistence_profile=args.persistence_profile,
                task_schedule_plan=args.task_schedule_plan,
                execution_scope=execution_scope,
            )
            payload = continuous_collection_report_to_dict(report)
            payload["execution_scope"] = execution_scope
            payload["formal_headline_eligible"] = execution_scope == "full" and report.eligible_for_headline
            print(stable_json_dumps(payload))
            return
        loaded_family = load_continuous_task_family(family_dir)
        family, original_round_count = _limit_continuous_family(loaded_family, args.max_cases)
        execution_scope = _diagnostic_scope(
            selected_count=_continuous_round_count(family),
            available_count=original_round_count,
            layer=args.layer,
        )
        if args.layer:
            layer = BenchmarkLayer(args.layer)
            report = run_continuous_benchmark_family(
                family=family,
                workspace_root=args.workspace_root / layer.value,
                runtime_root=args.runtime_root / layer.value,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous",
                layer=layer,
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                state_pool_mode=args.state_pool_mode,
                persistence_profile=args.persistence_profile,
                task_schedule_plan=args.task_schedule_plan,
                enforce_expected_metric_effects=False,
                metadata_extra={
                    "claim_level": "diagnostic",
                    "execution_scope": execution_scope,
                    "selected_round_count": _continuous_round_count(family),
                    "available_round_count": original_round_count,
                    "formal_headline_eligible": False,
                },
            )
            payload = family_report_to_dict(report)
            payload.update(
                {
                    "execution_scope": execution_scope,
                    "selected_round_count": _continuous_round_count(family),
                    "available_round_count": original_round_count,
                    "formal_headline_eligible": False,
                }
            )
            print(stable_json_dumps(payload))
            return
        report = run_continuous_benchmark_suite(
            family=family,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-continuous",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
            task_schedule_plan=args.task_schedule_plan,
            claim_level="diagnostic" if execution_scope != "full" else "first_pass",
            execution_scope=execution_scope,
            original_round_count=original_round_count,
        )
        payload = suite_report_to_dict(report)
        payload["selected_round_count"] = _continuous_round_count(family)
        payload["available_round_count"] = original_round_count
        payload["execution_scope"] = execution_scope
        payload["formal_headline_eligible"] = bool(
            report.metadata.get("formal_headline_eligible", False)
        )
        print(stable_json_dumps(payload))
        return
    if args.suite == "continuous-replay":
        if not _uses_explicit_single_family(args):
            loaded_families = tuple(
                load_continuous_task_family(path)
                for path in _default_continuous_replay_family_roots()
            )
            limited = tuple(
                _limit_continuous_family(family, args.max_cases)
                for family in loaded_families
            )
            families = tuple(item[0] for item in limited)
            execution_scope = (
                "diagnostic_partial"
                if any(_continuous_round_count(family) < original for family, original in limited)
                else "full"
            )
            report = run_continuous_benchmark_collection(
                families=families,
                workspace_root=args.workspace_root,
                runtime_root=args.runtime_root,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous-replay",
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                state_pool_mode=args.state_pool_mode,
                collection_scope="formal_replay_task_families",
                persistence_profile=args.persistence_profile,
                task_schedule_plan=args.task_schedule_plan,
                execution_scope=execution_scope,
            )
            payload = continuous_collection_report_to_dict(report)
            payload["execution_scope"] = execution_scope
            payload["formal_headline_eligible"] = execution_scope == "full" and report.eligible_for_headline
            print(stable_json_dumps(payload))
            return
        loaded_family = load_continuous_task_family(family_dir)
        family, original_round_count = _limit_continuous_family(loaded_family, args.max_cases)
        execution_scope = _diagnostic_scope(
            selected_count=_continuous_round_count(family),
            available_count=original_round_count,
            layer=args.layer,
        )
        if args.layer:
            layer = BenchmarkLayer(args.layer)
            report = run_continuous_benchmark_family(
                family=family,
                workspace_root=args.workspace_root / layer.value,
                runtime_root=args.runtime_root / layer.value,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous-replay",
                layer=layer,
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                state_pool_mode=args.state_pool_mode,
                persistence_profile=args.persistence_profile,
                task_schedule_plan=args.task_schedule_plan,
                enforce_expected_metric_effects=False,
                metadata_extra={
                    "claim_level": "diagnostic",
                    "execution_scope": execution_scope,
                    "selected_round_count": _continuous_round_count(family),
                    "available_round_count": original_round_count,
                    "formal_headline_eligible": False,
                },
            )
            payload = family_report_to_dict(report)
            payload.update(
                {
                    "execution_scope": execution_scope,
                    "selected_round_count": _continuous_round_count(family),
                    "available_round_count": original_round_count,
                    "formal_headline_eligible": False,
                }
            )
            print(stable_json_dumps(payload))
            return
        report = run_continuous_benchmark_suite(
            family=family,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-continuous-replay",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
            task_schedule_plan=args.task_schedule_plan,
            claim_level="diagnostic" if execution_scope != "full" else "first_pass",
            execution_scope=execution_scope,
            original_round_count=original_round_count,
        )
        payload = suite_report_to_dict(report)
        payload["selected_round_count"] = _continuous_round_count(family)
        payload["available_round_count"] = original_round_count
        payload["execution_scope"] = execution_scope
        payload["formal_headline_eligible"] = bool(
            report.metadata.get("formal_headline_eligible", False)
        )
        print(stable_json_dumps(payload))
        return

    if args.suite == "flagship-ablation":
        fixed_samples = load_fixed_answer_family(_default_dev_family_dir())
        continuous_families = tuple(load_continuous_task_family(path) for path in _default_continuous_family_roots())
        replay_families = tuple(load_continuous_task_family(path) for path in _default_continuous_replay_family_roots())
        report = run_non_text_flagship_ablation_report(
            fixed_samples=fixed_samples,
            continuous_families=continuous_families,
            replay_families=replay_families,
            workspace_root=args.workspace_root / "flagship-ablation",
            runtime_root=args.runtime_root / "flagship-ablation",
            socket_path=args.socket_path.with_name(f"{args.socket_path.stem}-flagship{args.socket_path.suffix}"),
            suite_id=f"{args.suite_id}-non-text-flagship-ablation",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            persistence_profile=args.persistence_profile,
        )
        print(stable_json_dumps(report))
        return

    if args.suite == "statebus" and args.family:
        family = load_continuous_task_family(family_dir)
        report = run_continuous_benchmark_suite(
            family=family,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-continuous-{family.family_id}",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
            task_schedule_plan=args.task_schedule_plan,
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
        return

    if args.statebus_mode == "cold-start" and args.seed_replay_memory:
        raise SystemExit("cold-start mode forbids synthetic replay seeding")
    if args.suite == "formal" and args.benchmark_tier != "formal":
        formal_samples = (
            load_registered_formal_samples()
            if args.family_dir is None and not args.family
            else load_sample_family(family_dir)
        )
        selected_samples = _select_cases(formal_samples, args.case_id, args.max_cases)
        execution_scope = _diagnostic_scope(
            selected_count=len(selected_samples),
            available_count=len(formal_samples),
            layer="",
        )
        formal_report = run_minimal_benchmark_suite(
            samples=selected_samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-formal",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            seed_replay_memory_by_layer={},
            benchmark_tier=args.benchmark_tier,
            claim_level="dev_mini_formal",
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
            executor_transport=args.transport,
        )
        payload = suite_report_to_dict(formal_report)
        if args.family_dir is None and not args.family:
            payload["formal_registry"] = formal_family_payload()
        payload["selected_case_count"] = len(selected_samples)
        payload["available_case_count"] = len(formal_samples)
        payload["max_cases"] = args.max_cases
        payload["execution_scope"] = execution_scope
        payload["formal_headline_eligible"] = False
        print(stable_json_dumps(payload))
        return
    if args.benchmark_tier == "formal":
        if args.suite in {"external"}:
            raise SystemExit("formal tier does not expose standalone external suites; use --suite compare")
        if args.suite not in {"statebus", "compare", "carrier-compare"}:
            # Non-compare formal suites: use MinimalBenchmarkSample via load_sample_family
            formal_samples = (
                load_registered_formal_samples()
                if args.family_dir is None and not args.family
                else load_sample_family(family_dir)
            )
            selected_samples = _select_cases(formal_samples, args.case_id, args.max_cases)
            execution_scope = _diagnostic_scope(
                selected_count=len(selected_samples),
                available_count=len(formal_samples),
                layer="",
            )
            formal_report = run_minimal_benchmark_suite(
                samples=selected_samples,
                workspace_root=args.workspace_root,
                runtime_root=args.runtime_root,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-formal",
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                seed_replay_memory_by_layer={},
                benchmark_tier="formal",
                claim_level="diagnostic" if execution_scope != "full" else "first_pass",
                state_pool_mode=args.state_pool_mode,
                persistence_profile=args.persistence_profile,
                executor_transport=args.transport,
            )
            payload = suite_report_to_dict(formal_report)
            payload["formal_registry"] = formal_family_payload()
            payload["selected_case_count"] = len(selected_samples)
            payload["available_case_count"] = len(formal_samples)
            payload["max_cases"] = args.max_cases
            payload["execution_scope"] = execution_scope
            payload["formal_headline_eligible"] = execution_scope == "full"
            print(stable_json_dumps(payload))
            return
        # formal compare/carrier-compare: fall through to fixed-answer compare paths.
        # The default formal path adapts the full registered 25-case/5-family registry.

    samples = (
        load_registered_formal_fixed_answer_samples()
        if args.benchmark_tier == "formal" and args.family_dir is None and not args.family
        else load_fixed_answer_family(family_dir)
    )
    available_sample_count = len(samples)
    samples = _select_cases(samples, args.case_id, args.max_cases)
    execution_scope = _diagnostic_scope(
        selected_count=len(samples),
        available_count=available_sample_count,
        layer=args.layer,
    )
    statebus_suite_prefix = _statebus_suite_prefix(
        suite_id=args.suite_id,
        statebus_mode=args.statebus_mode,
        seed_replay_memory=args.seed_replay_memory,
    )
    if args.suite == "statebus":
        if args.layer:
            layer = BenchmarkLayer(args.layer)
            report = run_fixed_answer_benchmark_family(
                samples=samples,
                workspace_root=args.workspace_root / layer.value,
                runtime_root=args.runtime_root / layer.value,
                socket_path=args.socket_path,
                suite_id=f"{statebus_suite_prefix}-statebus-{layer.value.lower()}",
                layer=layer,
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                statebus_mode=args.statebus_mode,
                seed_replay_memory=args.seed_replay_memory,
                benchmark_tier=args.benchmark_tier,
                claim_level="diagnostic",
                state_pool_mode=args.state_pool_mode,
                persistence_profile=args.persistence_profile,
                metadata_extra={
                    "execution_scope": "diagnostic_partial",
                    "selected_case_count": len(samples),
                    "available_case_count": available_sample_count,
                    "formal_headline_eligible": False,
                },
            )
            payload = family_report_to_dict(report)
            payload.update(
                {
                    "selected_case_count": len(samples),
                    "available_case_count": available_sample_count,
                    "max_cases": args.max_cases,
                    "selected_layer": layer.value,
                    "execution_scope": "diagnostic_partial",
                    "formal_headline_eligible": False,
                    "effective_statebus_mode": report.metadata.get("statebus_mode"),
                    "effective_replay_history_source": report.metadata.get(
                        "replay_history_source", "none"
                    ),
                }
            )
            print(stable_json_dumps(payload))
            return
        report = run_fixed_answer_suite(
            samples=samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{statebus_suite_prefix}-statebus",
            role_path_modes=(args.role_path_mode,),
            embedding_mode=args.embedding_mode,
            statebus_mode=args.statebus_mode,
            seed_replay_memory=args.seed_replay_memory,
            benchmark_tier=args.benchmark_tier,
            claim_level=(
                "diagnostic"
                if execution_scope != "full"
                else "first_pass"
                if args.benchmark_tier == "formal"
                else "prototype"
            ),
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
        )
        payload = suite_report_to_dict(report)
        payload["selected_case_count"] = len(samples)
        payload["available_case_count"] = available_sample_count
        payload["max_cases"] = args.max_cases
        payload["execution_scope"] = execution_scope
        payload["formal_headline_eligible"] = execution_scope == "full"
        payload["effective_statebus_mode"] = report.metadata.get("statebus_mode")
        payload["effective_replay_history_source"] = report.layer_reports[-1].metadata.get(
            "replay_history_source"
        ) if report.layer_reports else "none"
        if args.benchmark_tier == "formal" and args.family_dir is None and not args.family:
            payload["formal_registry"] = formal_family_payload()
        print(stable_json_dumps(payload))
        return

    if args.suite == "external":
        report = run_external_text_suite(
            samples=samples,
            runtime_root=args.runtime_root,
            suite_id=f"{args.suite_id}-external",
            role_path_modes=(args.role_path_mode,),
            embedding_mode=args.embedding_mode,
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
        return

    if args.suite == "carrier-compare":
        report = run_fixed_answer_internal_carrier_compare_suite(
            samples=samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{statebus_suite_prefix}-carrier-compare",
            role_path_modes=(args.role_path_mode,),
            embedding_mode=args.embedding_mode,
            statebus_mode=args.statebus_mode,
            benchmark_tier=args.benchmark_tier,
            claim_level=(
                "diagnostic"
                if execution_scope != "full"
                else "first_pass"
                if args.benchmark_tier == "formal"
                else "prototype"
            ),
            state_pool_mode=args.state_pool_mode,
            persistence_profile=args.persistence_profile,
        )
        payload = report.canonical_payload()
        payload["selected_case_count"] = len(samples)
        payload["available_case_count"] = available_sample_count
        payload["max_cases"] = args.max_cases
        payload["execution_scope"] = execution_scope
        payload["formal_headline_eligible"] = False
        print(stable_json_dumps(payload))
        return

    report = compare_fixed_answer_with_external(
        samples=samples,
        workspace_root=args.workspace_root,
        runtime_root=args.runtime_root,
        socket_path=args.socket_path,
        suite_id=f"{statebus_suite_prefix}-compare",
        role_path_modes=(args.role_path_mode,),
        embedding_mode=args.embedding_mode,
        statebus_mode=args.statebus_mode,
        seed_replay_memory=args.seed_replay_memory,
        benchmark_tier=args.benchmark_tier,
        claim_level=(
            "diagnostic"
            if execution_scope != "full"
            else "first_pass"
            if args.benchmark_tier == "formal"
            else "prototype"
        ),
        state_pool_mode=args.state_pool_mode,
        persistence_profile=args.persistence_profile,
    )
    payload = report.canonical_payload()
    payload["selected_case_count"] = len(samples)
    payload["available_case_count"] = available_sample_count
    payload["execution_scope"] = execution_scope
    payload["formal_headline_eligible"] = execution_scope == "full" and bool(
        payload.get("formal_superiority_claim_allowed", False)
    )
    print(stable_json_dumps(payload))


if __name__ == "__main__":
    main()
