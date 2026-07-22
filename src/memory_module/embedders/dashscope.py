from __future__ import annotations

import os
from typing import Any

from .api import OpenAICompatibleEmbedder


class DashScopeEmbedder(OpenAICompatibleEmbedder):
    """Alibaba Cloud Model Studio embedding adapter."""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-v4",
        dimension: int = 1024,
        base_url: str = DEFAULT_BASE_URL,
        client: Any | None = None,
    ) -> None:
        resolved_api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        super().__init__(
            model=model,
            dimension=dimension,
            api_key=resolved_api_key,
            base_url=base_url,
            client=client,
            pass_dimensions=True,
        )
