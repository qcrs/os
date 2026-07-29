#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.benchmark.engine_local_kv_experiment import (
    A_LANE,
    B_LANE,
    DEFAULT_LANE_ORDER,
    EngineLocalKVExperiment,
    KVExperimentConfig,
)
from v2.benchmark.engine_local_kv_tasks import (
    DEFAULT_CASE_DIR,
    CompiledKVCase,
    load_compiled_cases,
)
from v2.integrations.vllm_kv.client import VllmKVClient, VllmKVClientConfig
from v2.integrations.vllm_kv.tokenizer_client import VllmTokenCodec
from v2.utils import sha256_digest


DEFAULT_COMPILED_CASES = DEFAULT_CASE_DIR / "compiled_cases.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run serialized Qwen3-32B full-replay/KV-continuation A/B evidence."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=(
            Path(os.environ["STATEBUS_KV_API_TOKEN_FILE"])
            if os.environ.get("STATEBUS_KV_API_TOKEN_FILE")
            else None
        ),
    )
    parser.add_argument("--compiled-cases", type=Path, default=DEFAULT_COMPILED_CASES)
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Select a compiled case. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--parent-tokens",
        type=int,
        help="Use a block-aligned prefix of one selected case for a mechanism probe.",
    )
    parser.add_argument(
        "--microprobe",
        action="store_true",
        help="Run one A/B pair at 512, 2048, 4096, and 6144 parent tokens.",
    )
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument("--warmup-count-per-lane", type=int, default=1)
    parser.add_argument("--ttl-s", type=int, default=300)
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--container-image-id",
        default=os.environ.get("STATEBUS_CONTAINER_IMAGE_ID", ""),
    )
    parser.add_argument(
        "--vllm-launch-manifest-digest",
        default=os.environ.get("STATEBUS_VLLM_LAUNCH_MANIFEST_DIGEST", ""),
    )
    parser.add_argument("--gpu-name", default=os.environ.get("STATEBUS_GPU_NAME", ""))
    parser.add_argument("--model-path", default="/data/models/Qwen3-32B")
    parser.add_argument("--git-branch", default=os.environ.get("STATEBUS_GIT_BRANCH", ""))
    parser.add_argument("--git-commit", default=os.environ.get("STATEBUS_GIT_COMMIT", ""))
    parser.add_argument(
        "--git-status-file",
        type=Path,
        help="Optional newline-delimited git status captured outside the container.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or _default_run_id("microprobe" if args.microprobe else "formal")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise SystemExit("run-id must contain only letters, digits, dot, underscore, or dash")
    if not args.token_file:
        raise SystemExit("--token-file or STATEBUS_KV_API_TOKEN_FILE is required")

    all_cases = load_compiled_cases(args.compiled_cases)
    selected = _select_cases(all_cases, tuple(args.case_id))
    repeat_count = args.repeat_count
    warmup_count = args.warmup_count_per_lane
    with VllmTokenCodec(base_url=args.base_url, model=args.model) as codec:
        _validate_compiled_tokenizer(codec, selected)
        if args.microprobe:
            if args.case_id or args.parent_tokens is not None:
                raise SystemExit("--microprobe cannot be combined with case selection")
            selected = (_slice_case(selected[0], 512, codec, rename=True),) + selected
            repeat_count = 1
            warmup_count = 0
        elif args.parent_tokens is not None:
            if len(selected) != 1:
                raise SystemExit("--parent-tokens requires exactly one selected case")
            selected = (_slice_case(selected[0], args.parent_tokens, codec, rename=True),)

        lane_order = _lane_order(repeat_count)
        output_dir = args.output_dir or _default_output_dir(run_id)
        config = KVExperimentConfig(
            run_id=run_id,
            output_dir=output_dir,
            model=args.model,
            repeat_count=repeat_count,
            warmup_count_per_lane=warmup_count,
            lane_order=lane_order,
            seed=args.seed,
            ttl_s=args.ttl_s,
            fail_fast=args.fail_fast,
            container_image_id=args.container_image_id,
            vllm_launch_manifest_digest=args.vllm_launch_manifest_digest,
            gpu_name=args.gpu_name,
            model_path=args.model_path,
            git_branch=args.git_branch,
            git_commit=args.git_commit,
            git_status=_read_status_file(args.git_status_file),
        )
        client_config = VllmKVClientConfig(
            base_url=args.base_url,
            token_file=str(args.token_file),
            timeout_s=args.timeout_s,
        )
        with VllmKVClient(client_config) as client:
            summary = EngineLocalKVExperiment(
                client=client,
                codec=codec,
                cases=selected,
                config=config,
            ).run()

    print(f"run_id={run_id}")
    print(f"output_dir={output_dir}")
    print(f"formal_records={summary['formal_record_count']}")
    print(f"headline={summary['headline']['text']}")
    return 0 if _mechanism_checks_pass(summary) else 2


def _select_cases(
    cases: tuple[CompiledKVCase, ...],
    case_ids: tuple[str, ...],
) -> tuple[CompiledKVCase, ...]:
    if not case_ids:
        return cases
    if len(set(case_ids)) != len(case_ids):
        raise SystemExit("--case-id values must be unique")
    by_id = {case.definition.case_id: case for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
    return tuple(by_id[case_id] for case_id in case_ids)


def _slice_case(
    case: CompiledKVCase,
    parent_tokens: int,
    codec: VllmTokenCodec,
    *,
    rename: bool,
) -> CompiledKVCase:
    if (
        parent_tokens <= 0
        or parent_tokens > len(case.parent_token_ids)
        or parent_tokens % case.block_size
    ):
        raise SystemExit(
            f"parent token count must be in 1..{len(case.parent_token_ids)} "
            f"and aligned to block size {case.block_size}"
        )
    parent_ids = case.parent_token_ids[:parent_tokens]
    parent_text = codec.decode(parent_ids)
    if codec.encode(parent_text) != parent_ids:
        raise SystemExit("sliced parent failed tokenizer roundtrip")
    case_id = (
        f"{case.definition.case_id}-p{parent_tokens}"
        if rename and parent_tokens != len(case.parent_token_ids)
        else case.definition.case_id
    )
    definition = replace(
        case.definition,
        case_id=case_id,
        target_parent_tokens=parent_tokens,
    )
    return replace(
        case,
        definition=definition,
        parent_token_ids=parent_ids,
        parent_text=parent_text,
        source_digest=sha256_digest(parent_text),
        parent_token_digest=sha256_digest(list(parent_ids)),
    )


def _validate_compiled_tokenizer(
    codec: VllmTokenCodec,
    cases: tuple[CompiledKVCase, ...],
) -> None:
    for case in cases:
        if codec.encode(case.parent_text) != case.parent_token_ids:
            raise SystemExit(
                f"compiled tokenizer mismatch for {case.definition.case_id}"
            )


def _lane_order(repeat_count: int) -> tuple[str, ...]:
    if repeat_count == 3:
        return DEFAULT_LANE_ORDER
    if repeat_count <= 0:
        raise SystemExit("repeat-count must be positive")
    return tuple(lane for _ in range(repeat_count) for lane in (A_LANE, B_LANE))


def _mechanism_checks_pass(summary: dict[str, object]) -> bool:
    by_case = summary.get("by_case", {})
    if not isinstance(by_case, dict) or not by_case:
        return False
    for case_summary in by_case.values():
        if not isinstance(case_summary, dict):
            return False
        lanes = case_summary.get("lanes", {})
        if not isinstance(lanes, dict):
            return False
        for lane in (A_LANE, B_LANE):
            lane_summary = lanes.get(lane, {})
            if not isinstance(lane_summary, dict) or lane_summary.get(
                "success_count"
            ) != lane_summary.get("count"):
                return False
        pair_count = int(case_summary.get("pair_count", 0))
        if pair_count <= 0:
            return False
        for key in (
            "pair_digest_match_count",
            "pair_first_output_token_match_count",
            "pair_output_token_digest_match_count",
            "pair_producer_output_token_digest_match_count",
        ):
            if int(case_summary.get(key, 0)) != pair_count:
                return False
    return True


def _default_run_id(kind: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"engine-local-kv-{kind}-{timestamp}"


def _default_output_dir(run_id: str) -> Path:
    configured = os.environ.get("STATEBUS_RUN_ROOT", "")
    if configured:
        root = Path(configured)
    elif Path("/statebus/runs").is_dir():
        root = Path("/statebus/runs")
    else:
        root = REPO_ROOT / "runs"
    return root / "engine_local_kv_continuation" / run_id


def _read_status_file(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    return tuple(
        line for line in path.read_text(encoding="utf-8").splitlines() if line
    )


if __name__ == "__main__":
    raise SystemExit(main())
