from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KVApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KVSamplingModel(KVApiModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=96, ge=1, le=512)
    seed: int = Field(default=7, ge=0)


class KVProduceRequestModel(KVApiModel):
    model: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=256)
    parent_token_ids: list[int] = Field(min_length=1, max_length=8192)
    producer_suffix_token_ids: list[int] = Field(min_length=1, max_length=4096)
    capture_kv: bool = True
    ttl_s: int = Field(default=120, ge=1, le=3600)
    sampling: KVSamplingModel = Field(default_factory=KVSamplingModel)
    expected_compatibility_digest: str = Field(min_length=1, max_length=256)


class KVContinueRequestModel(KVApiModel):
    model: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=256)
    lane: Literal["full_replay", "kv_continuation"]
    handle_id: str = Field(default="", max_length=256)
    parent_token_ids: list[int] = Field(default_factory=list, max_length=8192)
    suffix_token_ids: list[int] = Field(min_length=1, max_length=4096)
    stream: bool = True
    sampling: KVSamplingModel = Field(default_factory=KVSamplingModel)
    expected_compatibility_digest: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_lane_payload(self) -> "KVContinueRequestModel":
        if self.lane == "kv_continuation":
            if not self.handle_id or self.parent_token_ids:
                raise ValueError("KV continuation requires only handle_id plus suffix")
        elif not self.parent_token_ids or self.handle_id:
            raise ValueError("full replay requires parent_token_ids and no handle")
        return self


class KVReleaseRequestModel(KVApiModel):
    handle_id: str = Field(min_length=1, max_length=256)
