from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.executor_runtime import run_registered_tool


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a repo-local StateBus tool worker.")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    result = run_registered_tool(args.tool, request)
    Path(args.response).write_text(
        json.dumps(result, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
