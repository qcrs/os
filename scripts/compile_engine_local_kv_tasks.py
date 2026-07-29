#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.benchmark.engine_local_kv_tasks import (
    COMPILED_CASE_SCHEMA_VERSION,
    DEFAULT_CASE_DIR,
    compile_cases,
)
from v2.integrations.vllm_kv.tokenizer_client import VllmTokenCodec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile exact Qwen token IDs for engine-local KV cases."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CASE_DIR / "compiled_cases.json",
    )
    parser.add_argument(
        "--parent-text-dir",
        type=Path,
        default=DEFAULT_CASE_DIR / "compiled_parents",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with VllmTokenCodec(base_url=args.base_url, model=args.model) as codec:
        cases = compile_cases(codec, args.case_dir)
    payload = {
        "schema_version": COMPILED_CASE_SCHEMA_VERSION,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "tokenizer_endpoint": args.base_url,
        "model": args.model,
        "cases": [case.canonical_payload() for case in cases],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.parent_text_dir.mkdir(parents=True, exist_ok=True)
    _write_text(args.output, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    for case in cases:
        _write_text(
            args.parent_text_dir / f"{case.definition.case_id}.txt",
            case.parent_text,
        )
    for case in cases:
        print(
            f"{case.definition.case_id}: parent={len(case.parent_token_ids)} "
            f"producer_suffix={len(case.producer_suffix_token_ids)} "
            f"digest={case.parent_token_digest}"
        )
    print(f"compiled={args.output}")
    return 0


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
