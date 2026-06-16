from __future__ import annotations

from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.contest_family_spec import (
    CONTEST_BENCHMARK_PATH,
    CONTEST_CORPUS_PATH,
    generate_contest_benchmark_payload,
    generate_contest_corpus_payload,
)


def _write_yaml(path: Path, payload: dict) -> None:
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    _write_yaml(CONTEST_BENCHMARK_PATH, generate_contest_benchmark_payload())
    _write_yaml(CONTEST_CORPUS_PATH, generate_contest_corpus_payload())


if __name__ == "__main__":
    main()
