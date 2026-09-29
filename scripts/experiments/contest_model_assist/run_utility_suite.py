#!/usr/bin/env python3
"""CLI for the long-text model-assist utility demonstration.

Offline modes never contact a service. Formal execution owns one report
directory, records the preflight decision, and refuses service switching when
the GPU/container owner contract is not satisfied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from statebus.benchmark.model_assist_utility.runner import (
    DEFAULT_REPORT_ROOT,
    UtilitySuiteError,
    recover_only,
    run_dry_run,
    run_execute,
    run_prepare,
    _target_slot_identity,
    _validate_failed_target_slot,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StateBus long-text utility suite")
    parser.add_argument("--mode", choices=("prepare", "formal", "smoke"), required=True)
    parser.add_argument("--phase", choices=("standard", "apc", "logit", "kv", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--poll-interval-s", type=float, default=60.0)
    parser.add_argument("--wall-budget-s", type=float, default=5400.0)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--slot-id", default="")
    parser.add_argument("--allow-external-gpu-pid", type=int, action="append", default=[])
    parser.add_argument("--recover-only", action="store_true")
    parser.add_argument("--resume", metavar="ID", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.poll_interval_s <= 0 or args.wall_budget_s <= 0:
        print("poll and wall budgets must be positive", file=sys.stderr)
        return 2
    try:
        target_module = None
        if args.slot_id:
            try:
                target_module, _case_id, _condition = _target_slot_identity(args.slot_id)
            except UtilitySuiteError as exc:
                print(f"invalid --slot-id: {exc}", file=sys.stderr)
                return 2
            if args.mode != "formal" or args.phase != target_module:
                print(f"--slot-id requires --mode formal --phase {target_module}", file=sys.stderr)
                return 2
        if args.slot_id and args.execute and not args.resume:
            print("--slot-id execution requires --resume", file=sys.stderr)
            return 2
        if args.allow_external_gpu_pid and not (
            args.mode == "formal"
            and target_module in {"apc", "logit"}
            and args.slot_id
            and args.resume
            and args.execute
            and args.yes
        ):
            print("--allow-external-gpu-pid requires one authorized --resume APC slot", file=sys.stderr)
            return 2
        if args.recover_only:
            if not args.run_id or args.resume or args.slot_id:
                print("--recover-only requires --run-id", file=sys.stderr)
                return 2
            code, root = recover_only(args.run_id, report_root=args.report_root)
            print(json.dumps({"status": "recovered" if code == 0 else "recovery_failed", "run_root": str(root)}, ensure_ascii=False))
            return code
        if args.resume:
            if args.mode != "formal" or args.run_id or args.dry_run or not args.yes:
                print("--resume requires --mode formal --yes and cannot be combined with --run-id or --dry-run", file=sys.stderr)
                return 2
            if args.slot_id:
                _validate_failed_target_slot(
                    args.report_root / args.resume,
                    args.slot_id,
                    expected_module=target_module,
                )
            recovery_code, recovery_root = recover_only(args.resume, report_root=args.report_root)
            if recovery_code != 0:
                print(json.dumps({"status": "recovery_failed", "run_root": str(recovery_root)}, ensure_ascii=False))
                return recovery_code
            code, root, summary = run_execute(mode="formal", phase=args.phase, quiet=args.quiet, poll_interval_s=args.poll_interval_s, wall_budget_s=args.wall_budget_s, report_root=args.report_root, run_id=args.resume, yes=True, resume=True, target_slot_id=args.slot_id or None, allow_external_gpu_pids=args.allow_external_gpu_pid)
            if args.quiet:
                print(json.dumps({"status": summary.get("status"), "run_root": str(root), "slot_counts": summary.get("slot_counts")}, ensure_ascii=False))
            else:
                print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return code
        if args.mode == "prepare":
            if args.slot_id:
                print("--slot-id is unavailable in prepare mode", file=sys.stderr)
                return 2
            payload = run_prepare(report_root=args.report_root)
            print(json.dumps({"status": "offline_passed", "output_root": payload["output_root"], "suite_revision": payload["manifest"]["suite_revision"], "cases": payload["cases"], "necessity_checks_passed": payload["manifest"]["necessity_checks_passed"]}, ensure_ascii=False, indent=2))
            return 0
        if args.mode == "smoke" and not args.execute:
            args.dry_run = True
        if args.dry_run or not args.execute:
            payload = run_dry_run(phase=args.phase, mode=args.mode, target_slot_id=args.slot_id or None, wall_budget_s=args.wall_budget_s)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        code, root, summary = run_execute(mode=args.mode, phase=args.phase, quiet=args.quiet, poll_interval_s=args.poll_interval_s, wall_budget_s=args.wall_budget_s, report_root=args.report_root, run_id=args.resume or args.run_id or None, yes=args.yes, resume=bool(args.resume), target_slot_id=args.slot_id or None, allow_external_gpu_pids=args.allow_external_gpu_pid)
        if args.quiet:
            print(json.dumps({"status": summary.get("status"), "run_root": str(root), "slot_counts": summary.get("slot_counts")}, ensure_ascii=False))
        else:
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return code
    except (UtilitySuiteError, ValueError, OSError) as exc:
        print(f"utility suite error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
