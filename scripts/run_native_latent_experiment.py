#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.benchmark.native_latent_experiment import (  # noqa: E402
    DEFAULT_MANIFEST,
    ExperimentConfig,
    LANES,
    run_native_latent_experiment,
    write_preregistered_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the preregistered six-case native latent feasibility matrix."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--lanes",
        nargs="+",
        choices=LANES,
        default=list(LANES),
        help="run all lanes by default; use --lanes C0 for task-solvability preflight",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="freeze and validate the plan without making model requests",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = ExperimentConfig(
        project_root=REPO_ROOT,
        output_root=args.output_root,
        manifest_path=args.manifest,
        base_url=args.base_url,
        token_file=args.token_file,
        timeout_s=args.timeout_s,
        run_id=args.run_id,
        lanes=tuple(args.lanes),
    )
    if args.dry_run:
        path = write_preregistered_plan(config)
        print(path)
        return 0
    result = run_native_latent_experiment(config)
    print(result["artifact_path"])
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
