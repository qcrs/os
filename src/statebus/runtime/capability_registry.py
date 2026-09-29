from __future__ import annotations

from dataclasses import dataclass, field

from statebus.contracts import CapabilityDescriptor
from statebus.utils import sha256_digest


class CapabilityRegistryError(ValueError):
    pass


@dataclass
class CapabilityRegistry:
    _descriptors: dict[str, CapabilityDescriptor] = field(default_factory=dict)

    def register(self, descriptor: CapabilityDescriptor) -> None:
        if not descriptor.capability_id or not descriptor.owner_role:
            raise CapabilityRegistryError("capability_id_and_owner_role_required")
        if descriptor.capability_id in self._descriptors:
            raise CapabilityRegistryError(f"duplicate_capability:{descriptor.capability_id}")
        if descriptor.max_runtime_ms <= 0:
            raise CapabilityRegistryError(f"invalid_runtime_budget:{descriptor.capability_id}")
        if not descriptor.input_contract_version or not descriptor.output_contract_version:
            raise CapabilityRegistryError(f"missing_contract_version:{descriptor.capability_id}")
        if not set(descriptor.required_input_ref_kinds) <= set(descriptor.input_ref_kinds):
            raise CapabilityRegistryError(f"required_input_kind_not_accepted:{descriptor.capability_id}")
        if len(set(descriptor.required_input_ref_kinds)) != len(descriptor.required_input_ref_kinds):
            raise CapabilityRegistryError(f"duplicate_required_input_kind:{descriptor.capability_id}")
        self._descriptors[descriptor.capability_id] = descriptor

    def get(self, capability_id: str) -> CapabilityDescriptor:
        try:
            return self._descriptors[capability_id]
        except KeyError as exc:
            raise CapabilityRegistryError(f"unknown_capability:{capability_id}") from exc

    def contains(self, capability_id: str) -> bool:
        return capability_id in self._descriptors

    def descriptors_for(self, capability_ids: tuple[str, ...]) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self.get(capability_id) for capability_id in capability_ids)

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    def logical_descriptor(self, capability_id: str):
        from statebus.runtime.provider_registry import project_legacy_capability

        return project_legacy_capability(self.get(capability_id))

    def logical_public_view(
        self,
        capability_ids: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            self.logical_descriptor(capability_id).public_view()
            for capability_id in sorted(set(capability_ids))
        )

    def logical_canonical_payload(self) -> dict[str, object]:
        return {
            "logical_capabilities": [
                self.logical_descriptor(descriptor.capability_id).canonical_payload()
                for descriptor in self.descriptors()
            ]
        }

    @property
    def logical_digest(self) -> str:
        return sha256_digest(self.logical_canonical_payload())

    def public_view(self, capability_ids: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        return tuple(
            self.get(capability_id).public_view()
            for capability_id in sorted(set(capability_ids))
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capabilities": [
                self._descriptors[capability_id].canonical_payload()
                for capability_id in sorted(self._descriptors)
            ]
        }

    @property
    def digest(self) -> str:
        return sha256_digest(self.canonical_payload())
