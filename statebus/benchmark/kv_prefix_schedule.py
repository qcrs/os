from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from statebus.benchmark.continuous_task_family import (
    ContinuousTaskFamily,
    ContinuousTaskRound,
    REPO_ROOT,
    load_continuous_task_family,
)
from statebus.runtime import (
    PrefixReuseScheduleHint,
    build_corpus_prefix_hash,
    order_prefix_schedule_hints,
    order_prefix_schedule_hints_by_task_ids,
)
from statebus.utils import sha256_digest, stable_json_dumps


KV_PREFIX_SCHEDULE_PLAN_SCHEMA_VERSION = "statebus.kv_prefix_schedule_plan.v2"
KV_PREFIX_SCHEDULE_CLAIM_BOUNDARY = (
    "corpus_prefix_schedule_control_plane_only_no_kv_tensor_export"
)


@dataclass(frozen=True)
class KVPrefixSchedulePlan:
    family_id: str
    mode: str
    schedule_key: str
    hints: tuple[PrefixReuseScheduleHint, ...]
    dependency_ids_by_task: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dependency_proof_digest: str = ""
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
            "dependency_ids_by_task": {
                task_id: list(dependency_ids)
                for task_id, dependency_ids in sorted(self.dependency_ids_by_task.items())
            },
            "dependency_proof_digest": self.dependency_proof_digest,
        }


@dataclass(frozen=True)
class PrefixScheduleNode:
    hint: PrefixReuseScheduleHint
    dependency_ids: tuple[str, ...] = ()

    @property
    def task_id(self) -> str:
        return self.hint.task_id


@dataclass(frozen=True)
class DependencyAwarePrefixScheduler:
    nodes: tuple[PrefixScheduleNode, ...]

    def __post_init__(self) -> None:
        task_ids = tuple(node.task_id for node in self.nodes)
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("prefix dependency schedule contains duplicate task ids")
        known = set(task_ids)
        for node in self.nodes:
            missing = tuple(dep for dep in node.dependency_ids if dep not in known)
            if missing:
                raise ValueError(
                    f"prefix dependency schedule references missing dependencies for {node.task_id}: "
                    + ", ".join(missing)
                )
            if node.task_id in node.dependency_ids:
                raise ValueError(f"prefix dependency schedule contains self dependency: {node.task_id}")
        self._validate_acyclic()

    @property
    def dependency_proof_digest(self) -> str:
        return sha256_digest(
            {
                node.task_id: list(node.dependency_ids)
                for node in sorted(self.nodes, key=lambda item: item.task_id)
            }
        )

    def ready_task_ids(
        self,
        *,
        completed_task_ids: tuple[str, ...] | set[str] = (),
        failed_task_ids: tuple[str, ...] | set[str] = (),
    ) -> tuple[str, ...]:
        completed = set(completed_task_ids)
        failed = set(failed_task_ids)
        return tuple(
            sorted(
                node.task_id
                for node in self.nodes
                if node.task_id not in completed
                and node.task_id not in failed
                and not (set(node.dependency_ids) & failed)
                and set(node.dependency_ids).issubset(completed)
            )
        )

    def choose_next(
        self,
        *,
        completed_task_ids: tuple[str, ...] | set[str] = (),
        failed_task_ids: tuple[str, ...] | set[str] = (),
        warmed_affinity_groups: tuple[str, ...] | set[str] = (),
        adaptive_affinity_scores: dict[str, float] | None = None,
        preferred_task_ids: tuple[str, ...] = (),
    ) -> PrefixScheduleNode | None:
        completed = set(completed_task_ids)
        failed = set(failed_task_ids)
        pending = tuple(
            node for node in self.nodes if node.task_id not in completed and node.task_id not in failed
        )
        if not pending:
            return None
        ready_ids = set(
            self.ready_task_ids(completed_task_ids=completed, failed_task_ids=failed)
        )
        if not ready_ids:
            blocked_by_failed = tuple(
                sorted(
                    node.task_id
                    for node in pending
                    if set(node.dependency_ids) & failed
                )
            )
            if blocked_by_failed:
                raise RuntimeError(
                    "prefix schedule blocked by failed dependency: " + ", ".join(blocked_by_failed)
                )
            raise RuntimeError("prefix dependency schedule has no ready task")
        ready = tuple(node for node in pending if node.task_id in ready_ids)
        preferred_rank = {task_id: index for index, task_id in enumerate(preferred_task_ids)}
        warmed = set(warmed_affinity_groups)
        adaptive = dict(adaptive_affinity_scores or {})
        return min(
            ready,
            key=lambda node: (
                preferred_rank.get(node.task_id, len(preferred_rank)),
                -int(node.hint.affinity_group() in warmed),
                -float(adaptive.get(node.hint.affinity_group(), 0.0)),
                -float(node.hint.schedule_priority),
                -int(node.hint.estimated_prefix_tokens),
                node.task_id,
            ),
        )

    def validate_order(self, task_ids: tuple[str, ...] | list[str]) -> None:
        ordered = tuple(task_ids)
        known = {node.task_id for node in self.nodes}
        if len(ordered) != len(known) or set(ordered) != known:
            raise ValueError("prefix schedule order must contain every task exactly once")
        dependencies = {node.task_id: set(node.dependency_ids) for node in self.nodes}
        completed: set[str] = set()
        for task_id in ordered:
            missing = dependencies[task_id] - completed
            if missing:
                raise ValueError(
                    f"prefix schedule runs {task_id} before dependencies: {', '.join(sorted(missing))}"
                )
            completed.add(task_id)

    def build_order(
        self,
        *,
        preferred_task_ids: tuple[str, ...] = (),
    ) -> tuple[PrefixScheduleNode, ...]:
        completed: set[str] = set()
        warmed: set[str] = set()
        ordered: list[PrefixScheduleNode] = []
        while len(completed) < len(self.nodes):
            chosen = self.choose_next(
                completed_task_ids=completed,
                warmed_affinity_groups=warmed,
                preferred_task_ids=preferred_task_ids,
            )
            if chosen is None:
                break
            ordered.append(chosen)
            completed.add(chosen.task_id)
            warmed.add(chosen.hint.affinity_group())
        self.validate_order(tuple(node.task_id for node in ordered))
        return tuple(ordered)

    def _validate_acyclic(self) -> None:
        completed: set[str] = set()
        remaining = {node.task_id: set(node.dependency_ids) for node in self.nodes}
        while remaining:
            ready = tuple(sorted(task_id for task_id, deps in remaining.items() if deps <= completed))
            if not ready:
                raise ValueError("prefix dependency schedule contains a cycle")
            completed.update(ready)
            for task_id in ready:
                del remaining[task_id]


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
    dependencies = _dependency_ids_by_task(family)
    scheduler = DependencyAwarePrefixScheduler(
        tuple(
            PrefixScheduleNode(
                hint=hint,
                dependency_ids=dependencies.get(hint.task_id, ()),
            )
            for hint in hints
        )
    )
    probe_payload = dict(family.kv_prefix_probe)
    explicit_order = probe_payload.get(f"{normalized_mode}_order")
    if isinstance(explicit_order, list):
        ordered_hints = order_prefix_schedule_hints_by_task_ids(
            hints,
            tuple(str(task_id) for task_id in explicit_order),
            strict=True,
        )
        scheduler.validate_order(tuple(hint.task_id for hint in ordered_hints))
    else:
        preferred = tuple(
            hint.task_id for hint in order_prefix_schedule_hints(hints, mode=normalized_mode)
        )
        ordered_hints = tuple(
            node.hint for node in scheduler.build_order(preferred_task_ids=preferred)
        )
    return KVPrefixSchedulePlan(
        family_id=family.family_id,
        mode=normalized_mode,
        schedule_key=str(probe_payload.get("schedule_key", "corpus_prefix_hash")),
        hints=ordered_hints,
        dependency_ids_by_task=dependencies,
        dependency_proof_digest=scheduler.dependency_proof_digest,
    )


def _dependency_ids_by_task(family: ContinuousTaskFamily) -> dict[str, tuple[str, ...]]:
    task_id_by_round = {round_.round: round_.task_id for round_ in family.rounds}
    return {
        round_.task_id: tuple(task_id_by_round[number] for number in round_.depends_on_rounds)
        for round_ in family.rounds
    }


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
        default="statebus/benchmark/samples/continuous_task_families/kv_prefix_reuse",
    )
    parser.add_argument("--mode", choices=("cache_friendly", "cache_hostile", "input"), default="cache_friendly")
    args = parser.parse_args()

    family = load_continuous_task_family(Path(args.family_dir))
    plan = build_kv_prefix_schedule_plan(family, mode=args.mode)
    print(stable_json_dumps(plan.canonical_payload()))


if __name__ == "__main__":
    main()
