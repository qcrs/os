from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from v2.contracts import CanonicalTaskSpec


CONTINUOUS_TASK_FAMILY_SCHEMA_VERSION = "statebus.continuous_task_family.v1"
CONTINUOUS_TASK_WORLD_SCHEMA_VERSION = "statebus.gridops_world.v1"
REPO_ROOT = Path(__file__).resolve().parents[2]

_VALID_CLAIM_TIERS = {"formal_primary", "formal_secondary", "demo_secondary"}
_VALID_REUSE_CLASSES = {"none", "assist", "validated_replay", "exact_replay"}


def _default_canonical_task_spec_schema_version() -> str:
    return CanonicalTaskSpec(task_family="", intent_op="").schema_version


def _canonical_task_spec_from_payload(payload: dict[str, object]) -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family=str(payload["task_family"]),
        intent_op=str(payload["intent_op"]),
        target_entities=tuple(str(item) for item in payload.get("target_entities", [])),
        time_scope=str(payload.get("time_scope", "")),
        required_outputs=tuple(str(item) for item in payload.get("required_outputs", [])),
        required_tools=tuple(str(item) for item in payload.get("required_tools", [])),
        arguments=dict(payload.get("arguments", {})),
        schema_version=str(payload.get("schema_version", _default_canonical_task_spec_schema_version())),
    )


class ContinuousTaskFamilyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ContinuousTaskDataset:
    dataset_id: str
    path: str
    kind: str
    metadata: dict[str, object] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "dataset_id": self.dataset_id,
            "path": self.path,
            "kind": self.kind,
        }
        payload.update(dict(sorted(self.metadata.items())))
        return payload


@dataclass(frozen=True)
class ContinuousTaskReuseContract:
    produces: tuple[str, ...]
    consumes: tuple[str, ...]
    minimum_reuse_class: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "produces": list(self.produces),
            "consumes": list(self.consumes),
            "minimum_reuse_class": self.minimum_reuse_class,
        }


@dataclass(frozen=True)
class ContinuousPreRunFixture:
    kind: str
    source_round: int
    runtime_signature_version: str
    output_contract_version: str
    validator_digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_round": self.source_round,
            "runtime_signature_version": self.runtime_signature_version,
            "output_contract_version": self.output_contract_version,
            "validator_digest": self.validator_digest,
        }


@dataclass(frozen=True)
class ContinuousTaskRound:
    round: int
    task_id: str
    dataset_id: str
    request_text: str
    canonical_task_spec: CanonicalTaskSpec
    depends_on_rounds: tuple[int, ...]
    reuse_contract: ContinuousTaskReuseContract
    expected_facts: dict[str, object] = field(default_factory=dict)
    quality_checks: tuple[str, ...] = ()
    expected_metric_effects: dict[str, object] = field(default_factory=dict)
    pre_run_fixtures: tuple[ContinuousPreRunFixture, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "round": self.round,
            "task_id": self.task_id,
            "dataset_id": self.dataset_id,
            "request_text": self.request_text,
            "canonical_task_spec": self.canonical_task_spec.canonical_payload(),
            "depends_on_rounds": list(self.depends_on_rounds),
            "reuse_contract": self.reuse_contract.canonical_payload(),
            "expected_facts": dict(sorted(self.expected_facts.items())),
            "quality_checks": list(self.quality_checks),
            "expected_metric_effects": dict(sorted(self.expected_metric_effects.items())),
            "pre_run_fixtures": [fixture.canonical_payload() for fixture in self.pre_run_fixtures],
        }


@dataclass(frozen=True)
class ContinuousTaskFamily:
    family_id: str
    display_name: str
    claim_tier: str
    round_count: int
    manifest_path: str
    datasets: tuple[ContinuousTaskDataset, ...]
    rounds: tuple[ContinuousTaskRound, ...]
    experiment_views: dict[str, tuple[int, ...]] = field(default_factory=dict)
    selected_experiment_view: str = ""
    quality_floor: dict[str, object] = field(default_factory=dict)
    l0_l3_expectations: dict[str, object] = field(default_factory=dict)
    kv_prefix_probe: dict[str, object] = field(default_factory=dict)
    source_basis: dict[str, object] = field(default_factory=dict)
    schema_version: str = CONTINUOUS_TASK_FAMILY_SCHEMA_VERSION

    def l3_target_nonzero_rounds(self) -> tuple[int, ...]:
        payload = self.l0_l3_expectations.get("L3", {})
        if not isinstance(payload, dict):
            return ()
        selected_round_numbers = {round_.round for round_ in self.rounds}
        return tuple(
            round_number
            for item in payload.get("target_nonzero_rounds", [])
            if (round_number := int(item)) in selected_round_numbers
        )

    def replay_target_rounds_by_class(self) -> dict[str, tuple[int, ...]]:
        exact_replay_rounds = tuple(
            round_.round
            for round_ in self.rounds
            if round_.reuse_contract.minimum_reuse_class == "exact_replay"
        )
        validated_replay_rounds = tuple(
            round_.round
            for round_ in self.rounds
            if round_.reuse_contract.minimum_reuse_class == "validated_replay"
        )
        return {
            "validated_replay": validated_replay_rounds,
            "exact_replay": exact_replay_rounds,
        }

    def rounds_for_view(self, view_name: str) -> tuple[ContinuousTaskRound, ...]:
        normalized = view_name.strip()
        if not normalized:
            return self.rounds
        round_numbers = self.experiment_views.get(normalized)
        if round_numbers is None:
            raise ContinuousTaskFamilyValidationError(
                f"unknown experiment view in {self.family_id}: {normalized}"
            )
        rounds_by_number = {round_.round: round_ for round_ in self.rounds}
        return tuple(rounds_by_number[round_number] for round_number in round_numbers)

    def select_view(self, view_name: str) -> "ContinuousTaskFamily":
        normalized = view_name.strip()
        selected_rounds = self.rounds_for_view(normalized)
        return replace(
            self,
            round_count=len(selected_rounds),
            rounds=selected_rounds,
            selected_experiment_view=normalized,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "display_name": self.display_name,
            "claim_tier": self.claim_tier,
            "round_count": self.round_count,
            "manifest_path": self.manifest_path,
            "datasets": [dataset.canonical_payload() for dataset in self.datasets],
            "experiment_views": {
                name: list(round_numbers)
                for name, round_numbers in sorted(self.experiment_views.items())
            },
            "selected_experiment_view": self.selected_experiment_view,
            "quality_floor": dict(sorted(self.quality_floor.items())),
            "l0_l3_expectations": dict(sorted(self.l0_l3_expectations.items())),
            "kv_prefix_probe": dict(sorted(self.kv_prefix_probe.items())),
            "source_basis": dict(sorted(self.source_basis.items())),
            "rounds": [round_.canonical_payload() for round_ in self.rounds],
        }

    def design_audit_payload(self) -> dict[str, object]:
        reuse_edge_count = sum(len(round_.depends_on_rounds) for round_ in self.rounds)
        replay_target_rounds = self.replay_target_rounds_by_class()
        rounds_by_number = {round_.round: round_ for round_ in self.rounds}
        view_audits = {
            name: {
                "rounds": list(round_numbers),
                "round_count": len(round_numbers),
                "strictly_increasing": list(round_numbers) == sorted(set(round_numbers)),
                "available_in_current_selection": all(
                    round_number in rounds_by_number for round_number in round_numbers
                ),
                "dependency_closed": all(
                    round_number in rounds_by_number
                    and
                    set(rounds_by_number[round_number].depends_on_rounds).issubset(
                        set(round_numbers[:index])
                    )
                    for index, round_number in enumerate(round_numbers)
                ),
                "task_ids": [
                    rounds_by_number[round_number].task_id
                    for round_number in round_numbers
                    if round_number in rounds_by_number
                ],
            }
            for name, round_numbers in sorted(self.experiment_views.items())
        }
        return {
            "ok": True,
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "display_name": self.display_name,
            "claim_tier": self.claim_tier,
            "manifest_path": self.manifest_path,
            "round_count": self.round_count,
            "selected_experiment_view": self.selected_experiment_view,
            "experiment_views": view_audits,
            "dataset_count": len(self.datasets),
            "reuse_edge_count": reuse_edge_count,
            "exact_replay_target_rounds": list(replay_target_rounds["exact_replay"]),
            "validated_replay_target_rounds": list(replay_target_rounds["validated_replay"]),
            "l3_target_rounds": list(self.l3_target_nonzero_rounds()),
            "kv_prefix_probe": dict(sorted(self.kv_prefix_probe.items())),
            "datasets": [dataset.canonical_payload() for dataset in self.datasets],
            "rounds": [
                {
                    "round": round_.round,
                    "task_id": round_.task_id,
                    "dataset_id": round_.dataset_id,
                    "intent_op": round_.canonical_task_spec.intent_op,
                    "depends_on_rounds": list(round_.depends_on_rounds),
                    "minimum_reuse_class": round_.reuse_contract.minimum_reuse_class,
                    "produces": list(round_.reuse_contract.produces),
                    "consumes": list(round_.reuse_contract.consumes),
                    "pre_run_fixtures": [
                        fixture.canonical_payload()
                        for fixture in round_.pre_run_fixtures
                    ],
                }
                for round_ in self.rounds
            ],
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContinuousTaskFamilyValidationError(message)


def _validate_dataset_path(*, family_dir: Path, dataset: ContinuousTaskDataset) -> None:
    dataset_path = Path(dataset.path)
    if not dataset_path.is_absolute():
        dataset_path = (REPO_ROOT / dataset_path).resolve()
    _require(dataset_path.exists(), f"dataset path missing for {dataset.dataset_id}: {dataset.path}")
    if dataset.kind == "grid_world":
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        _require(
            payload.get("schema_version") == CONTINUOUS_TASK_WORLD_SCHEMA_VERSION,
            f"grid world fixture schema mismatch for {dataset.dataset_id}",
        )


def load_continuous_task_family(directory: Path) -> ContinuousTaskFamily:
    manifest_path = directory / "manifest.json"
    _require(manifest_path.exists(), f"continuous task family manifest missing: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(
        payload.get("schema_version") == CONTINUOUS_TASK_FAMILY_SCHEMA_VERSION,
        f"unsupported continuous task family schema: {payload.get('schema_version', '')}",
    )

    family_id = str(payload.get("family_id", "")).strip()
    _require(bool(family_id), "continuous task family requires family_id")
    claim_tier = str(payload.get("claim_tier", "")).strip()
    _require(claim_tier in _VALID_CLAIM_TIERS, f"unsupported claim_tier: {claim_tier}")
    round_count = int(payload.get("round_count", 0) or 0)
    # A family describes a related sequence, not the size of the whole
    # benchmark collection.  Two rounds are enough to express a dependency;
    # the collection runner owns the aggregate minimum of ten executions.
    _require(round_count >= 2, f"continuous task family must declare at least 2 rounds: {family_id}")

    datasets = tuple(
        ContinuousTaskDataset(
            dataset_id=str(item["dataset_id"]),
            path=str(item["path"]),
            kind=str(item["kind"]),
            metadata={
                key: value
                for key, value in item.items()
                if key not in {"dataset_id", "path", "kind"}
            },
        )
        for item in payload.get("datasets", [])
    )
    dataset_ids = {dataset.dataset_id for dataset in datasets}
    _require(dataset_ids, f"continuous task family requires datasets: {family_id}")
    for dataset in datasets:
        _validate_dataset_path(family_dir=directory.resolve(), dataset=dataset)

    rounds_payload = payload.get("rounds", [])
    _require(isinstance(rounds_payload, list), f"rounds must be a list: {family_id}")
    _require(len(rounds_payload) == round_count, f"round_count mismatch in {family_id}")
    rounds: list[ContinuousTaskRound] = []
    seen_task_ids: set[str] = set()
    for expected_round, round_payload in enumerate(rounds_payload, start=1):
        _require(isinstance(round_payload, dict), f"round payload must be an object: {family_id}:{expected_round}")
        round_number = int(round_payload.get("round", 0) or 0)
        _require(round_number == expected_round, f"round sequence mismatch in {family_id}: {round_number}")
        task_id = str(round_payload.get("task_id", "")).strip()
        _require(bool(task_id), f"task_id missing in {family_id} round {round_number}")
        _require(task_id not in seen_task_ids, f"duplicate task_id in {family_id}: {task_id}")
        seen_task_ids.add(task_id)
        dataset_id = str(round_payload.get("dataset_id", "")).strip()
        _require(dataset_id in dataset_ids, f"unknown dataset_id in {family_id}: {dataset_id}")
        request_text = str(round_payload.get("request_text", "")).strip()
        _require(bool(request_text), f"request_text missing in {family_id}:{task_id}")
        canonical_payload = round_payload.get("canonical_task_spec")
        _require(
            isinstance(canonical_payload, dict),
            f"canonical_task_spec missing or invalid in {family_id}:{task_id}",
        )
        canonical_task_spec = _canonical_task_spec_from_payload(canonical_payload)
        _require(
            bool(canonical_task_spec.required_outputs),
            f"required_outputs missing in {family_id}:{task_id}",
        )
        _require(
            bool(canonical_task_spec.required_tools),
            f"required_tools missing in {family_id}:{task_id}",
        )
        depends_on_rounds = tuple(int(item) for item in round_payload.get("depends_on_rounds", []))
        _require(
            all(dep > 0 and dep < round_number for dep in depends_on_rounds),
            f"depends_on_rounds must point backward in {family_id}:{task_id}",
        )
        reuse_payload = round_payload.get("reuse_contract")
        _require(isinstance(reuse_payload, dict), f"reuse_contract missing in {family_id}:{task_id}")
        minimum_reuse_class = str(reuse_payload.get("minimum_reuse_class", "")).strip()
        _require(
            minimum_reuse_class in _VALID_REUSE_CLASSES,
            f"unsupported reuse class in {family_id}:{task_id}: {minimum_reuse_class}",
        )
        produces = tuple(str(item) for item in reuse_payload.get("produces", []))
        consumes = tuple(str(item) for item in reuse_payload.get("consumes", []))
        _require(bool(produces), f"reuse_contract.produces missing in {family_id}:{task_id}")
        quality_checks = tuple(str(item) for item in round_payload.get("quality_checks", []))
        _require(bool(quality_checks), f"quality_checks missing in {family_id}:{task_id}")
        expected_metric_effects = dict(round_payload.get("expected_metric_effects", {}))
        _require(
            isinstance(expected_metric_effects, dict),
            f"expected_metric_effects invalid in {family_id}:{task_id}",
        )
        fixtures_payload = round_payload.get("pre_run_fixtures", [])
        _require(
            isinstance(fixtures_payload, list),
            f"pre_run_fixtures must be a list in {family_id}:{task_id}",
        )
        pre_run_fixtures: list[ContinuousPreRunFixture] = []
        for fixture_payload in fixtures_payload:
            _require(
                isinstance(fixture_payload, dict),
                f"pre_run fixture must be an object in {family_id}:{task_id}",
            )
            kind = str(fixture_payload.get("kind", "")).strip()
            _require(
                kind == "incompatible_history_candidate",
                f"unsupported pre_run fixture kind in {family_id}:{task_id}: {kind}",
            )
            source_round = int(fixture_payload.get("source_round", 0) or 0)
            _require(
                0 < source_round < round_number,
                f"pre_run fixture source_round must point backward in {family_id}:{task_id}",
            )
            signature_version = str(
                fixture_payload.get("runtime_signature_version", "")
            ).strip()
            output_contract_version = str(
                fixture_payload.get("output_contract_version", "")
            ).strip()
            validator_digest = str(fixture_payload.get("validator_digest", "")).strip()
            _require(
                bool(signature_version and output_contract_version and validator_digest),
                f"pre_run fixture compatibility fields are required in {family_id}:{task_id}",
            )
            pre_run_fixtures.append(
                ContinuousPreRunFixture(
                    kind=kind,
                    source_round=source_round,
                    runtime_signature_version=signature_version,
                    output_contract_version=output_contract_version,
                    validator_digest=validator_digest,
                )
            )
        rounds.append(
            ContinuousTaskRound(
                round=round_number,
                task_id=task_id,
                dataset_id=dataset_id,
                request_text=request_text,
                canonical_task_spec=canonical_task_spec,
                depends_on_rounds=depends_on_rounds,
                reuse_contract=ContinuousTaskReuseContract(
                    produces=produces,
                    consumes=consumes,
                    minimum_reuse_class=minimum_reuse_class,
                ),
                expected_facts=dict(round_payload.get("expected_facts", {})),
                quality_checks=quality_checks,
                expected_metric_effects=expected_metric_effects,
                pre_run_fixtures=tuple(pre_run_fixtures),
            )
        )

    experiment_views_payload = payload.get("experiment_views", {})
    _require(
        isinstance(experiment_views_payload, dict),
        f"experiment_views must be an object: {family_id}",
    )
    rounds_by_number = {round_.round: round_ for round_ in rounds}
    experiment_views: dict[str, tuple[int, ...]] = {}
    for raw_name, raw_round_numbers in experiment_views_payload.items():
        view_name = str(raw_name).strip()
        _require(bool(view_name), f"experiment view name missing in {family_id}")
        _require(
            isinstance(raw_round_numbers, list) and bool(raw_round_numbers),
            f"experiment view must contain at least one round in {family_id}:{view_name}",
        )
        round_numbers = tuple(int(item) for item in raw_round_numbers)
        _require(
            list(round_numbers) == sorted(set(round_numbers)),
            f"experiment view rounds must be strictly increasing and unique in {family_id}:{view_name}",
        )
        _require(
            all(round_number in rounds_by_number for round_number in round_numbers),
            f"experiment view references an unknown round in {family_id}:{view_name}",
        )
        selected_prefix: set[int] = set()
        for round_number in round_numbers:
            dependencies = set(rounds_by_number[round_number].depends_on_rounds)
            _require(
                dependencies.issubset(selected_prefix),
                "experiment view must include every dependency before its consumer in "
                f"{family_id}:{view_name}:round_{round_number}",
            )
            selected_prefix.add(round_number)
        experiment_views[view_name] = round_numbers

    l0_l3_expectations = dict(payload.get("l0_l3_expectations", {}))
    l3_payload = l0_l3_expectations.get("L3", {})
    _require(isinstance(l3_payload, dict), f"L3 expectations missing in {family_id}")
    target_nonzero_rounds = [int(item) for item in l3_payload.get("target_nonzero_rounds", [])]
    _require(
        all(1 <= item <= round_count for item in target_nonzero_rounds),
        f"L3 target_nonzero_rounds out of range in {family_id}",
    )

    return ContinuousTaskFamily(
        family_id=family_id,
        display_name=str(payload.get("display_name", family_id)),
        claim_tier=claim_tier,
        round_count=round_count,
        manifest_path=str(manifest_path),
        datasets=datasets,
        rounds=tuple(rounds),
        experiment_views=experiment_views,
        quality_floor=dict(payload.get("quality_floor", {})),
        l0_l3_expectations=l0_l3_expectations,
        kv_prefix_probe=dict(payload.get("kv_prefix_probe", {})),
        source_basis=dict(payload.get("source_basis", {})),
    )
