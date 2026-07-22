from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LatentApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatentAnchorModel(LatentApiModel):
    evidence_pack_hash: str = Field(min_length=1, max_length=256)
    item_ids: list[str] = Field(min_length=1, max_length=128)
    locator_digest: str = Field(min_length=1, max_length=256)


class LatentMessageModel(LatentApiModel):
    role: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=1_000_000)


class LatentSamplingModel(LatentApiModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    seed: int = Field(default=7, ge=0)


class LatentProduceRequestModel(LatentApiModel):
    model: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=256)
    source_step_id: str = Field(min_length=1, max_length=256)
    producer_role: str = Field(default="retriever", min_length=1, max_length=64)
    consumer_role: str = Field(default="summarizer", min_length=1, max_length=64)
    messages: list[LatentMessageModel] = Field(min_length=1, max_length=64)
    latent_steps: int = Field(default=8, ge=2, le=80)
    alignment_method: str = Field(default="soft_token_topk_v1", max_length=128)
    anchor: LatentAnchorModel
    ttl_s: int = Field(default=60, ge=1, le=3600)
    expected_compatibility_digest: str = Field(min_length=1, max_length=256)


class LatentCompleteRequestModel(LatentApiModel):
    model: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    latent_ref_id: str = Field(min_length=1, max_length=256)
    rendered_prompt: str = Field(min_length=1, max_length=1_000_000)
    messages: list[LatentMessageModel] = Field(default_factory=list, max_length=64)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    sampling: LatentSamplingModel = Field(default_factory=LatentSamplingModel)
    expected_compatibility_digest: str = Field(min_length=1, max_length=256)
    anchor: LatentAnchorModel


class LatentReleaseRequestModel(LatentApiModel):
    ref_id: str = Field(min_length=1, max_length=256)


def anchor_payload(anchor: LatentAnchorModel) -> dict[str, object]:
    return {
        "evidence_pack_hash": anchor.evidence_pack_hash,
        "item_ids": list(anchor.item_ids),
        "locator_digest": anchor.locator_digest,
    }
