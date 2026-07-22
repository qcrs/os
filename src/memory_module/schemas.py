from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchMode(str, Enum):
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"


class AddMemoryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    memory_type: str = Field(min_length=1)
    source_agent: str = Field(min_length=1)
    source_task_id: str = Field(min_length=1)
    task_topic: str = Field(min_length=1)
    infer: bool = False

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for value in values:
            keyword = value.strip()
            if keyword and keyword not in seen:
                normalized.append(keyword)
                seen.add(keyword)
        return normalized


class MemoryPayload(BaseModel):
    content: str
    keywords: list[str]
    memory_type: str
    source_agent: str
    source_task_id: str
    task_topic: str
    content_hash: str
    created_at: datetime


class Memory(BaseModel):
    id: str
    payload: MemoryPayload


class SearchResult(Memory):
    score: float
    dense_score: float | None = None
    bm25_score: float | None = None


class DeleteMemoryResult(BaseModel):
    memory_id: str
    deleted: bool


PayloadFilters = dict[str, Any]
