from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from v2.benchmark.comparator_runner import compare_fixed_answer_with_external
from v2.benchmark.continuous_runner import run_continuous_benchmark_collection, run_continuous_benchmark_suite
from v2.benchmark.continuous_task_family import load_continuous_task_family
from v2.benchmark.external_text_baseline import run_external_text_suite
from v2.benchmark.fixed_answer_runner import (
    load_fixed_answer_family,
    run_fixed_answer_internal_carrier_compare_suite,
    run_fixed_answer_suite,
)
from v2.benchmark.flagship_ablation import run_non_text_flagship_ablation_report
from v2.benchmark.minimal_runner import load_sample_family, run_minimal_benchmark_suite
from v2.benchmark.reporting import continuous_collection_report_to_dict, suite_report_to_dict
from v2.benchmark.replay_negative_audit import run_replay_negative_audit
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
        base / "csv_table_profile",
        base / "long_doc_table",
    )


def _default_continuous_replay_family_dir() -> Path:
    return Path(__file__).with_name("samples") / "continuous_task_families" / "long_doc_metric_replay"


def _default_continuous_replay_family_roots() -> tuple[Path, ...]:
    base = Path(__file__).with_name("samples") / "continuous_task_families"
    return (
        base / "csv_correlation_replay",
        base / "long_doc_metric_replay",
    )


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
        choices=("deterministic", "api"),
        help="planner/retriever/executor/summarizer mode",
    )
    parser.add_argument(
        "--embedding-mode",
        default="deterministic",
        choices=("deterministic", "local"),
        help="retrieval embedding mode",
    )
    parser.add_argument(
        "--suite-id",
        default="statebus-v2-benchmark",
        help="suite id prefix",
    )
    parser.add_argument(
        "--statebus-mode",
        default="cold-start",
        choices=("replay-ready", "cold-start"),
        help="StateBus benchmark mode",
    )
    parser.add_argument(
        "--seed-replay-memory",
        action="store_true",
        help="dev-only synthetic replay seed for assisted diagnostics",
    )
    return parser


def _resolved_family_dir(args: argparse.Namespace) -> Path:
    if args.family_dir is not None:
        return args.family_dir
    if args.suite == "continuous-design-audit":
        return _default_continuous_family_dir()
    if args.suite == "continuous-replay":
        return _default_continuous_replay_family_dir()
    if args.benchmark_tier == "formal":
        return _default_formal_family_dir()
    return _default_dev_family_dir()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
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
        if args.family_dir is None:
            families = tuple(load_continuous_task_family(path) for path in _default_continuous_family_roots())
            report = run_continuous_benchmark_collection(
                families=families,
                workspace_root=args.workspace_root,
                runtime_root=args.runtime_root,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous",
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
            )
            print(stable_json_dumps(continuous_collection_report_to_dict(report)))
            return
        family = load_continuous_task_family(family_dir)
        report = run_continuous_benchmark_suite(
            family=family,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-continuous",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
        return
    if args.suite == "continuous-replay":
        if args.family_dir is None:
            families = tuple(load_continuous_task_family(path) for path in _default_continuous_replay_family_roots())
            report = run_continuous_benchmark_collection(
                families=families,
                workspace_root=args.workspace_root,
                runtime_root=args.runtime_root,
                socket_path=args.socket_path,
                suite_id=f"{args.suite_id}-continuous-replay",
                role_path_mode=args.role_path_mode,
                embedding_mode=args.embedding_mode,
                collection_scope="formal_replay_task_families",
            )
            print(stable_json_dumps(continuous_collection_report_to_dict(report)))
            return
        family = load_continuous_task_family(family_dir)
        report = run_continuous_benchmark_suite(
            family=family,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-continuous-replay",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
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
        )
        print(stable_json_dumps(report))
        return

    if args.statebus_mode == "cold-start" and args.seed_replay_memory:
        raise SystemExit("cold-start mode forbids synthetic replay seeding")
    if args.benchmark_tier == "formal":
        if args.suite in {"external", "compare"}:
            raise SystemExit("formal tier does not expose assisted external/comparator suites")
        samples = load_sample_family(family_dir)
        report = run_minimal_benchmark_suite(
            samples=samples,
            workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            suite_id=f"{args.suite_id}-formal",
            role_path_mode=args.role_path_mode,
            embedding_mode=args.embedding_mode,
            seed_replay_memory_by_layer={},
            benchmark_tier="formal",
            claim_level="first_pass",
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
        return

    samples = load_fixed_answer_family(family_dir)
    statebus_suite_prefix = _statebus_suite_prefix(
        suite_id=args.suite_id,
        statebus_mode=args.statebus_mode,
        seed_replay_memory=args.seed_replay_memory,
    )
    if args.suite == "statebus":
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
            benchmark_tier="dev",
            claim_level="prototype",
        )
        print(stable_json_dumps(suite_report_to_dict(report)))
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
            benchmark_tier="dev",
            claim_level="prototype",
        )
        print(stable_json_dumps(report.canonical_payload()))
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
        benchmark_tier="dev",
        claim_level="prototype",
    )
    print(stable_json_dumps(report.canonical_payload()))


if __name__ == "__main__":
    main()
