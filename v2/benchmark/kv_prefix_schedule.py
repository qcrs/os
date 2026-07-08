from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.continuous_task_family import (
    ContinuousTaskFamily,
    ContinuousTaskRound,
    REPO_ROOT,
    load_continuous_task_family,
)
from v2.runtime import (
    PrefixReuseScheduleHint,
    build_corpus_prefix_hash,
    order_prefix_schedule_hints,
    order_prefix_schedule_hints_by_task_ids,
)
from v2.utils import stable_json_dumps


KV_PREFIX_SCHEDULE_PLAN_SCHEMA_VERSION = "statebus.kv_prefix_schedule_plan.v1"
KV_PREFIX_SCHEDULE_CLAIM_BOUNDARY = (
    "corpus_prefix_schedule_control_plane_only_no_kv_tensor_export"
)


@dataclass(frozen=True)
class KVPrefixSchedulePlan:
    family_id: str
    mode: str
    schedule_key: str
    hints: tuple[PrefixReuseScheduleHint, ...]
    claim_boundary: str = KV_PREFIX_SCHEDULE_CLAIM_BOUNDARY
    schema_version: str = KV_PREFIX_SCHEDULE_PLAN_SCHEMA_VERSION

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(hint.task_id for hint in self.hints)

    @property
    def affinity_groups(self) -> tuple[str, ...]:
        return tuple(hint.affinity_group() for hint in self.hints)

    @property
    def max_contiguous_same_affinity_run(self) -> int:
        return _max_contiguous_run(self.affinity_groups)

    @property
    def affinity_switch_count(self) -> int:
        groups = self.affinity_groups
        if not groups:
            return 0
        return sum(1 for previous, current in zip(groups, groups[1:]) if previous != current)

    @property
    def adjacent_reuse_opportunity_count(self) -> int:
        groups = self.affinity_groups
        return sum(1 for previous, current in zip(groups, groups[1:]) if previous == current)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "claim_boundary": self.claim_boundary,
            "family_id": self.family_id,
            "mode": self.mode,
            "schedule_key": self.schedule_key,
            "task_ids": list(self.task_ids),
            "affinity_groups": list(self.affinity_groups),
            "max_contiguous_same_affinity_run": self.max_contiguous_same_affinity_run,
            "affinity_switch_count": self.affinity_switch_count,
            "adjacent_reuse_opportunity_count": self.adjacent_reuse_opportunity_count,
            "hints": [hint.canonical_payload() for hint in self.hints],
        }


def build_kv_prefix_schedule_hints(
    family: ContinuousTaskFamily,
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[PrefixReuseScheduleHint, ...]:
    return tuple(_round_schedule_hint(family_round=round_, repo_root=repo_root) for round_ in family.rounds)


def build_kv_prefix_schedule_plan(
    family: ContinuousTaskFamily,
    *,
    mode: str = "cache_friendly",
    repo_root: Path = REPO_ROOT,
) -> KVPrefixSchedulePlan:
    normalized_mode = mode.strip().lower()
    hints = build_kv_prefix_schedule_hints(family, repo_root=repo_root)
    probe_payload = dict(family.kv_prefix_probe)
    explicit_order = probe_payload.get(f"{normalized_mode}_order")
    if isinstance(explicit_order, list):
        ordered_hints = order_prefix_schedule_hints_by_task_ids(
            hints,
            tuple(str(task_id) for task_id in explicit_order),
            strict=True,
        )
    else:
        ordered_hints = order_prefix_schedule_hints(hints, mode=normalized_mode)
    return KVPrefixSchedulePlan(
        family_id=family.family_id,
        mode=normalized_mode,
        schedule_key=str(probe_payload.get("schedule_key", "corpus_prefix_hash")),
        hints=ordered_hints,
    )


def _round_schedule_hint(
    *,
    family_round: ContinuousTaskRound,
    repo_root: Path,
) -> PrefixReuseScheduleHint:
    arguments = dict(family_round.canonical_task_spec.arguments)
    document_path = str(arguments.get("document_path", "")).strip()
    source_doc_hash = _source_doc_hash(document_path=document_path, repo_root=repo_root)
    corpus_prefix_hash = build_corpus_prefix_hash(source_doc_hashes=(source_doc_hash,))
    affinity_group = str(arguments.get("kv_probe_corpus_group", "")).strip() or family_round.dataset_id
    estimated_prefix_tokens = _estimated_prefix_tokens(document_path=document_path, repo_root=repo_root)
    return PrefixReuseScheduleHint(
        task_id=family_round.task_id,
        corpus_prefix_hash=corpus_prefix_hash,
        estimated_prefix_tokens=estimated_prefix_tokens,
        cache_affinity_group=affinity_group,
        schedule_priority=float(estimated_prefix_tokens),
        metadata={
            "round": family_round.round,
            "dataset_id": family_round.dataset_id,
            "document_path": document_path,
            "source_doc_hash": source_doc_hash,
            "intent_op": family_round.canonical_task_spec.intent_op,
        },
    )


def _source_doc_hash(*, document_path: str, repo_root: Path) -> str:
    path = _resolve_repo_path(document_path=document_path, repo_root=repo_root)
    if path is None or not path.exists():
        return f"sha256:missing-{hashlib.sha256(document_path.encode('utf-8')).hexdigest()}"
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _estimated_prefix_tokens(*, document_path: str, repo_root: Path) -> int:
    path = _resolve_repo_path(document_path=document_path, repo_root=repo_root)
    if path is None or not path.exists():
        return 0
    # The runtime uses byte-based token estimates elsewhere; keep the schedule
    # probe aligned with that conservative convention.
    return max(len(path.read_bytes()) // 4, 1)


def _resolve_repo_path(*, document_path: str, repo_root: Path) -> Path | None:
    if not document_path:
        return None
    path = Path(document_path)
    return path if path.is_absolute() else (repo_root / path).resolve()


def _max_contiguous_run(values: tuple[str, ...]) -> int:
    longest = 0
    current = 0
    previous = None
    for value in values:
        if value == previous:
            current += 1
        else:
            current = 1
            previous = value
        longest = max(longest, current)
    return longest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a KV prefix schedule plan from a continuous family.")
    parser.add_argument(
        "--family-dir",
        default="v2/benchmark/samples/continuous_task_families/kv_prefix_reuse",
    )
    parser.add_argument("--mode", choices=("cache_friendly", "cache_hostile", "input"), default="cache_friendly")
    args = parser.parse_args()

    family = load_continuous_task_family(Path(args.family_dir))
    plan = build_kv_prefix_schedule_plan(family, mode=args.mode)
    print(stable_json_dumps(plan.canonical_payload()))


if __name__ == "__main__":
    main()
