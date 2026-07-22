from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hmac
import os
from pathlib import Path
import stat
from typing import Any, Mapping
from urllib.parse import urlparse

from v2.integrations.vllm_latent.middleware import LATENT_ERROR_CODES
from v2.runtime.role_model_backend import LatentBackendError


@dataclass(frozen=True)
class VllmLatentClientConfig:
    base_url: str = "http://127.0.0.1:53334"
    token_file: str = ""
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls) -> "VllmLatentClientConfig":
        return cls(
            base_url=os.environ.get(
                "STATEBUS_LATENT_API_BASE_URL", "http://127.0.0.1:53334"
            ),
            token_file=os.environ.get(
                "STATEBUS_LATENT_API_TOKEN_FILE",
                os.environ.get("STATEBUS_LATENT_TOKEN_FILE", ""),
            ),
            timeout_s=float(os.environ.get("STATEBUS_LATENT_API_TIMEOUT_S", "120")),
        )


class VllmLatentClientError(LatentBackendError):
    def __init__(
        self,
        error_code: str,
        detail: str = "",
        *,
        status_code: int = 0,
    ) -> None:
        super().__init__(error_code, detail)
        self.status_code = int(status_code)


class VllmLatentClient:
    """Synchronous authenticated client for the loopback latent API."""

    def __init__(
        self,
        config: VllmLatentClientConfig | None = None,
        *,
        base_url: str | None = None,
        token_file: str | os.PathLike[str] | None = None,
        timeout_s: float | None = None,
        http_client: Any | None = None,
    ) -> None:
        resolved = config or VllmLatentClientConfig.from_env()
        self.base_url = (base_url or resolved.base_url).rstrip("/")
        configured_token_file = token_file or resolved.token_file
        self.token_file = Path(configured_token_file) if configured_token_file else None
        self.timeout_s = float(timeout_s or resolved.timeout_s)
        _require_loopback_base_url(self.base_url)
        self._client = http_client
        self._owns_client = http_client is None

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/statebus/latent/health")

    def produce(self, payload: Any) -> dict[str, Any]:
        return self._request(
            "POST", "/statebus/latent/produce", payload=_json_payload(payload)
        )

    def complete(self, payload: Any) -> dict[str, Any]:
        return self._request(
            "POST", "/statebus/latent/complete", payload=_json_payload(payload)
        )

    def release(self, ref_id: str) -> dict[str, Any]:
        return self._request(
            "POST", "/statebus/latent/release", payload={"ref_id": str(ref_id)}
        )

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
        self._client = None

    def __enter__(self) -> "VllmLatentClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._client
        if client is None:
            try:
                import httpx
            except ImportError as exc:
                raise VllmLatentClientError(
                    "latent_plugin_not_ready", "http_client_unavailable"
                ) from exc
            client = httpx.Client(timeout=self.timeout_s, trust_env=False)
            self._client = client
        try:
            response = client.request(
                method,
                f"{self.base_url}{path}",
                headers=_authorization_headers(self.token_file),
                json=payload,
                timeout=self.timeout_s,
            )
        except VllmLatentClientError:
            raise
        except Exception as exc:
            raise VllmLatentClientError(
                "latent_plugin_not_ready", "transport_failed"
            ) from exc
        return _decode_response(response)


class AsyncVllmLatentClient:
    """Async client variant used by ASGI and integration tests."""

    def __init__(
        self,
        config: VllmLatentClientConfig | None = None,
        *,
        base_url: str | None = None,
        token_file: str | os.PathLike[str] | None = None,
        timeout_s: float | None = None,
        http_client: Any | None = None,
    ) -> None:
        resolved = config or VllmLatentClientConfig.from_env()
        self.base_url = (base_url or resolved.base_url).rstrip("/")
        configured_token_file = token_file or resolved.token_file
        self.token_file = Path(configured_token_file) if configured_token_file else None
        self.timeout_s = float(timeout_s or resolved.timeout_s)
        _require_loopback_base_url(self.base_url)
        self._client = http_client
        self._owns_client = http_client is None

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/statebus/latent/health")

    async def produce(self, payload: Any) -> dict[str, Any]:
        return await self._request(
            "POST", "/statebus/latent/produce", payload=_json_payload(payload)
        )

    async def complete(self, payload: Any) -> dict[str, Any]:
        return await self._request(
            "POST", "/statebus/latent/complete", payload=_json_payload(payload)
        )

    async def release(self, ref_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/statebus/latent/release", payload={"ref_id": str(ref_id)}
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "AsyncVllmLatentClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._client
        if client is None:
            try:
                import httpx
            except ImportError as exc:
                raise VllmLatentClientError(
                    "latent_plugin_not_ready", "http_client_unavailable"
                ) from exc
            client = httpx.AsyncClient(timeout=self.timeout_s, trust_env=False)
            self._client = client
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=_authorization_headers(self.token_file),
                json=payload,
                timeout=self.timeout_s,
            )
        except VllmLatentClientError:
            raise
        except Exception as exc:
            raise VllmLatentClientError(
                "latent_plugin_not_ready", "transport_failed"
            ) from exc
        return _decode_response(response)


def _authorization_headers(token_file: Path | None) -> dict[str, str]:
    token = _read_token(token_file)
    return {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
    }


def _read_token(token_file: Path | None) -> str:
    if token_file is None:
        raise VllmLatentClientError("latent_auth_failed", "token_file_unavailable")
    try:
        metadata = token_file.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise VllmLatentClientError(
                "latent_auth_failed", "token_file_permissions"
            )
        token = token_file.read_text(encoding="utf-8").strip()
    except VllmLatentClientError:
        raise
    except OSError as exc:
        raise VllmLatentClientError(
            "latent_auth_failed", "token_file_unavailable"
        ) from exc
    if not token or any(character.isspace() for character in token):
        raise VllmLatentClientError("latent_auth_failed", "token_file_invalid")
    return token


def _decode_response(response: Any) -> dict[str, Any]:
    status_code = int(getattr(response, "status_code", 0))
    try:
        payload = response.json()
    except Exception as exc:
        raise VllmLatentClientError(
            "latent_plugin_not_ready", "invalid_json_response", status_code=status_code
        ) from exc
    if not isinstance(payload, dict):
        raise VllmLatentClientError(
            "latent_plugin_not_ready", "invalid_response", status_code=status_code
        )
    if status_code >= 400:
        error = payload.get("error", {})
        code = payload.get("error_code")
        if not code and isinstance(error, Mapping):
            code = error.get("code")
        code = str(code or "latent_plugin_not_ready")
        if code not in LATENT_ERROR_CODES:
            code = "latent_plugin_not_ready"
        raise VllmLatentClientError(code, status_code=status_code)
    return payload


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = dict(value)
    elif hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif is_dataclass(value):
        payload = asdict(value)
    else:
        raise TypeError("latent client payload must be a mapping or data model")
    return payload


def _require_loopback_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("latent API base URL must use a loopback host")


LatentHandoffClient = VllmLatentClient
AsyncLatentHandoffClient = AsyncVllmLatentClient
LatentClientError = VllmLatentClientError


__all__ = [
    "AsyncLatentHandoffClient",
    "AsyncVllmLatentClient",
    "LatentClientError",
    "LatentHandoffClient",
    "VllmLatentClient",
    "VllmLatentClientConfig",
    "VllmLatentClientError",
]
