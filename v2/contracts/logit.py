from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from v2.utils import sha256_digest


LOGIT_STATE_SCHEMA_VERSION = "statebus.logit_state.v1"
LOGIT_PRODUCER_RECEIPT_SCHEMA_VERSION = "statebus.logit_producer_receipt.v1"
EXECUTOR_CHOICE_DECISION_TYPE = "executor_choice_v1"
LOGIT_PROBABILITY_SEMANTICS = "candidate_order_plus_other_mass_v1"
LOGIT_DTYPE = "<f4"
LOGIT_BYTE_ORDER = "little"
LOGIT_GATE_MARGIN_THRESHOLD = 0.10
LOGIT_GATE_RECEIPT_SCHEMA_VERSION = "statebus.logit_gate_receipt.v1"
_ALIASES = tuple("ABCDEFGH")


class LogitProducerStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class LogitGateAction(StrEnum):
    ACCEPT = "accept"
    RETRY = "retry"


@dataclass(frozen=True)
class CandidateAliasBinding:
    ordinal: int
    alias: str
    candidate_id: str
    candidate_digest: str

    def __post_init__(self) -> None:
        if not 0 <= self.ordinal < len(_ALIASES):
            raise ValueError("candidate alias ordinal out of range")
        if self.alias != _ALIASES[self.ordinal]:
            raise ValueError("candidate aliases must be canonical A..H order")
        if not self.candidate_id.strip() or not self.candidate_digest.strip():
            raise ValueError("candidate alias binding requires identity")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "alias": self.alias,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "token_bytes_hex": self.alias.encode("ascii").hex(),
        }


@dataclass(frozen=True)
class CandidateSurfaceV2:
    bindings: tuple[CandidateAliasBinding, ...]
    decision_type: str = EXECUTOR_CHOICE_DECISION_TYPE
    schema_version: str = "statebus.candidate_surface.v1"

    def __post_init__(self) -> None:
        if not 2 <= len(self.bindings) <= len(_ALIASES):
            raise ValueError("candidate surface requires 2..8 candidates")
        if tuple(item.ordinal for item in self.bindings) != tuple(range(len(self.bindings))):
            raise ValueError("candidate surface ordinals must be contiguous")
        if len({item.candidate_id for item in self.bindings}) != len(self.bindings):
            raise ValueError("candidate surface candidate IDs must be unique")
        if self.decision_type != EXECUTOR_CHOICE_DECISION_TYPE:
            raise ValueError("unsupported LogitState decision type")

    @classmethod
    def from_candidate_ids(
        cls,
        candidate_ids: tuple[str, ...],
        *,
        candidate_digests: tuple[str, ...] = (),
    ) -> "CandidateSurfaceV2":
        if not 2 <= len(candidate_ids) <= len(_ALIASES):
            raise ValueError("candidate surface requires 2..8 candidates")
        if candidate_digests and len(candidate_digests) != len(candidate_ids):
            raise ValueError("candidate digest count mismatch")
        bindings = tuple(
            CandidateAliasBinding(
                ordinal=index,
                alias=_ALIASES[index],
                candidate_id=str(candidate_id),
                candidate_digest=(
                    candidate_digests[index]
                    if candidate_digests
                    else sha256_digest({"candidate_id": candidate_id})
                ),
            )
            for index, candidate_id in enumerate(candidate_ids)
        )
        return cls(bindings=bindings)

    @classmethod
    def from_payload(cls, payload: object) -> "CandidateSurfaceV2":
        if not isinstance(payload, dict):
            raise ValueError("candidate surface payload must be an object")
        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list):
            raise ValueError("candidate surface bindings missing")
        bindings = tuple(
            CandidateAliasBinding(
                ordinal=int(item.get("ordinal", -1)),
                alias=str(item.get("alias", "")),
                candidate_id=str(item.get("candidate_id", "")),
                candidate_digest=str(item.get("candidate_digest", "")),
            )
            for item in raw_bindings
            if isinstance(item, dict)
        )
        return cls(
            bindings=bindings,
            decision_type=str(payload.get("decision_type", EXECUTOR_CHOICE_DECISION_TYPE)),
            schema_version=str(payload.get("schema_version", "statebus.candidate_surface.v1")),
        )

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(item.alias for item in self.bindings)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.bindings)

    @property
    def candidate_count(self) -> int:
        return len(self.bindings)

    @property
    def alias_mapping_digest(self) -> str:
        return sha256_digest([
            {
                "ordinal": item.ordinal,
                "alias": item.alias,
                "candidate_id": item.candidate_id,
            }
            for item in self.bindings
        ])

    @property
    def candidate_surface_digest(self) -> str:
        return sha256_digest(self.canonical_payload())

    def candidate_id_for_alias(self, alias: str) -> str:
        for item in self.bindings:
            if item.alias == alias:
                return item.candidate_id
        raise KeyError(alias)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_type": self.decision_type,
            "bindings": [item.canonical_payload() for item in self.bindings],
            "candidate_count": self.candidate_count,
            "alias_mapping_digest": self.alias_mapping_digest,
        }


@dataclass(frozen=True)
class LogitProducerReceipt:
    request_id: str
    attempt_id: str
    status: LogitProducerStatus
    candidate_surface_digest: str
    alias_mapping_digest: str
    selected_alias: str = ""
    selected_candidate_id: str = ""
    decision_token_position: int = -1
    sequence_length: int = 0
    top_k: int = 0
    unavailable_reason: str = ""
    schema_version: str = LOGIT_PRODUCER_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.request_id or not self.attempt_id:
            raise ValueError("producer receipt requires request and attempt IDs")
        if self.status is LogitProducerStatus.AVAILABLE and self.unavailable_reason:
            raise ValueError("available producer receipt cannot have unavailable reason")
        if self.status is LogitProducerStatus.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("unavailable producer receipt requires a reason")

    @property
    def available(self) -> bool:
        return self.status is LogitProducerStatus.AVAILABLE

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "candidate_surface_digest": self.candidate_surface_digest,
            "alias_mapping_digest": self.alias_mapping_digest,
            "selected_alias": self.selected_alias,
            "selected_candidate_id": self.selected_candidate_id,
            "decision_token_position": self.decision_token_position,
            "sequence_length": self.sequence_length,
            "top_k": self.top_k,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class LogitGateReceipt:
    state_id: str
    decision_id: str
    action: LogitGateAction
    reason: str
    selected_alias: str
    selected_candidate_id: str
    top1_alias: str
    selected_probability: float
    top_margin: float
    normalized_entropy: float
    other_mass: float
    candidate_count: int
    producer_pid: int
    consumer_pid: int
    margin_threshold: float = LOGIT_GATE_MARGIN_THRESHOLD
    schema_version: str = LOGIT_GATE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.state_id or not self.decision_id:
            raise ValueError("logit gate receipt requires state and decision IDs")
        if not self.selected_alias or not self.selected_candidate_id or not self.top1_alias:
            raise ValueError("logit gate receipt requires candidate bindings")
        if not 2 <= self.candidate_count <= len(_ALIASES):
            raise ValueError("logit gate receipt candidate count out of range")
        if self.producer_pid <= 0 or self.consumer_pid <= 0:
            raise ValueError("logit gate receipt requires positive PIDs")
        if self.producer_pid == self.consumer_pid:
            raise ValueError("logit gate must consume state in an independent PID")
        numeric = (
            self.selected_probability,
            self.top_margin,
            self.normalized_entropy,
            self.other_mass,
            self.margin_threshold,
        )
        if any(not isinstance(value, (int, float)) for value in numeric):
            raise ValueError("logit gate receipt requires numeric features")
        if not 0.0 <= self.selected_probability <= 1.0:
            raise ValueError("selected probability out of range")
        if not 0.0 <= self.top_margin <= 1.0:
            raise ValueError("top margin out of range")
        if not 0.0 <= self.normalized_entropy <= 1.0 + 1e-6:
            raise ValueError("normalized entropy out of range")
        if not 0.0 <= self.other_mass <= 1.0:
            raise ValueError("other mass out of range")
        if not 0.0 <= self.margin_threshold <= 1.0:
            raise ValueError("margin threshold out of range")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "decision_id": self.decision_id,
            "action": self.action.value,
            "reason": self.reason,
            "selected_alias": self.selected_alias,
            "selected_candidate_id": self.selected_candidate_id,
            "top1_alias": self.top1_alias,
            "selected_probability": self.selected_probability,
            "top_margin": self.top_margin,
            "normalized_entropy": self.normalized_entropy,
            "other_mass": self.other_mass,
            "candidate_count": self.candidate_count,
            "producer_pid": self.producer_pid,
            "consumer_pid": self.consumer_pid,
            "margin_threshold": self.margin_threshold,
        }
