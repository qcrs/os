from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class VllmTokenCodecError(RuntimeError):
    pass


class VllmTokenCodec:
    """Exact token encode/decode through the serving model's tokenizer API."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:53334",
        model: str = "qwen3-32b",
        timeout_s: float = 60.0,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = str(model)
        self.timeout_s = float(timeout_s)
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or (
            parsed.hostname or ""
        ).lower() not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("tokenizer API must use a loopback host")
        if not self.model or self.timeout_s <= 0:
            raise ValueError("model and timeout must be configured")
        self._client = http_client
        self._owns_client = http_client is None

    def encode(self, text: str) -> tuple[int, ...]:
        response = self._request("/tokenize", {"model": self.model, "prompt": text})
        values = response.get("tokens")
        if not isinstance(values, list):
            raise VllmTokenCodecError("tokenize_response_invalid")
        try:
            token_ids = tuple(int(value) for value in values)
        except (TypeError, ValueError) as exc:
            raise VllmTokenCodecError("tokenize_response_invalid") from exc
        if any(value < 0 for value in token_ids) or int(
            response.get("count", -1)
        ) != len(token_ids):
            raise VllmTokenCodecError("tokenize_response_invalid")
        return token_ids

    def decode(self, token_ids: tuple[int, ...]) -> str:
        if not token_ids or any(int(value) < 0 for value in token_ids):
            raise VllmTokenCodecError("detokenize_request_invalid")
        response = self._request(
            "/detokenize",
            {"model": self.model, "tokens": [int(value) for value in token_ids]},
        )
        prompt = response.get("prompt")
        if not isinstance(prompt, str):
            raise VllmTokenCodecError("detokenize_response_invalid")
        return prompt

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
        self._client = None

    def __enter__(self) -> "VllmTokenCodec":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        try:
            response = client.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            value = response.json()
        except Exception as exc:
            raise VllmTokenCodecError("tokenizer_api_failed") from exc
        if not isinstance(value, dict):
            raise VllmTokenCodecError("tokenizer_response_invalid")
        return value

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise VllmTokenCodecError("http_client_unavailable") from exc
            self._client = httpx.Client(timeout=self.timeout_s, trust_env=False)
        return self._client


__all__ = ["VllmTokenCodec", "VllmTokenCodecError"]
