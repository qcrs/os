from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Mapping
from urllib.parse import urlparse

from v2.integrations.vllm_kv.middleware import KV_ERROR_CODES


@dataclass(frozen=True)
class VllmKVClientConfig:
    base_url: str = "http://127.0.0.1:53334"
    token_file: str = ""
    timeout_s: float = 180.0

    @classmethod
    def from_env(cls) -> "VllmKVClientConfig":
        return cls(
            base_url=os.environ.get(
                "STATEBUS_KV_API_BASE_URL", "http://127.0.0.1:53334"
            ),
            token_file=os.environ.get("STATEBUS_KV_API_TOKEN_FILE", ""),
            timeout_s=float(os.environ.get("STATEBUS_KV_API_TIMEOUT_S", "180")),
        )


@dataclass(frozen=True)
class KVStreamResult:
    payload: dict[str, Any]
    client_ttft_ms: float
    client_wall_ms: float
    api_request_bytes: int
    token_event_count: int


class VllmKVClientError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str = "",
        *,
        status_code: int = 0,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail
        self.status_code = int(status_code)


class VllmKVClient:
    """Synchronous loopback client with client-observed SSE TTFT timing."""

    def __init__(
        self,
        config: VllmKVClientConfig | None = None,
        *,
        base_url: str | None = None,
        token_file: str | os.PathLike[str] | None = None,
        timeout_s: float | None = None,
        http_client: Any | None = None,
    ) -> None:
        resolved = config or VllmKVClientConfig.from_env()
        self.base_url = (base_url or resolved.base_url).rstrip("/")
        configured_token = token_file or resolved.token_file
        self.token_file = Path(configured_token) if configured_token else None
        self.timeout_s = float(timeout_s or resolved.timeout_s)
        _require_loopback_base_url(self.base_url)
        self._client = http_client
        self._owns_client = http_client is None

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/statebus/kv/health")

    def produce(self, payload: Any) -> dict[str, Any]:
        return self._request_json(
            "POST", "/statebus/kv/produce", payload=_json_payload(payload)
        )

    def continue_request(self, payload: Any) -> dict[str, Any]:
        body = _json_payload(payload)
        body["stream"] = False
        return self._request_json("POST", "/statebus/kv/continue", payload=body)

    def continue_stream(self, payload: Any) -> KVStreamResult:
        body = _json_payload(payload)
        body["stream"] = True
        serialized = json.dumps(
            body,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        client = self._get_client()
        started = time.perf_counter_ns()
        first_token_ns = 0
        token_event_count = 0
        final_payload: dict[str, Any] | None = None
        try:
            with client.stream(
                "POST",
                f"{self.base_url}/statebus/kv/continue",
                headers={
                    **_authorization_headers(self.token_file),
                    "accept": "text/event-stream",
                },
                content=serialized,
                timeout=self.timeout_s,
            ) as response:
                status_code = int(response.status_code)
                if status_code >= 400:
                    raw = response.read()
                    raise _error_from_bytes(raw, status_code=status_code)
                event_name = ""
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if line == "":
                        if event_name:
                            event_payload = _decode_sse_data(data_lines)
                            if event_name == "token":
                                token_event_count += 1
                                if first_token_ns == 0 and (
                                    event_payload.get("text_delta")
                                    or event_payload.get("token_ids")
                                ):
                                    first_token_ns = time.perf_counter_ns()
                            elif event_name == "final":
                                final_payload = event_payload
                            elif event_name == "error":
                                raise _error_from_payload(
                                    event_payload,
                                    status_code=status_code,
                                )
                        event_name = ""
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line.partition(":")[2].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.partition(":")[2].lstrip())
        except VllmKVClientError:
            raise
        except Exception as exc:
            raise VllmKVClientError(
                "kv_plugin_not_ready", "transport_failed"
            ) from exc
        finished = time.perf_counter_ns()
        if final_payload is None:
            raise VllmKVClientError("kv_plugin_not_ready", "final_event_missing")
        ttft_ms = (
            0.0
            if first_token_ns == 0
            else (first_token_ns - started) / 1_000_000.0
        )
        client_telemetry = {
            "client_ttft_ms": ttft_ms,
            "client_wall_ms": (finished - started) / 1_000_000.0,
            "api_request_bytes": len(serialized),
            "token_event_count": token_event_count,
        }
        final_payload["client_telemetry"] = client_telemetry
        return KVStreamResult(
            payload=final_payload,
            client_ttft_ms=ttft_ms,
            client_wall_ms=float(client_telemetry["client_wall_ms"]),
            api_request_bytes=len(serialized),
            token_event_count=token_event_count,
        )

    def release(self, handle_id: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/statebus/kv/release",
            payload={"handle_id": str(handle_id)},
        )

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
        self._client = None

    def __enter__(self) -> "VllmKVClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._get_client()
        try:
            response = client.request(
                method,
                f"{self.base_url}{path}",
                headers=_authorization_headers(self.token_file),
                json=payload,
                timeout=self.timeout_s,
            )
        except VllmKVClientError:
            raise
        except Exception as exc:
            raise VllmKVClientError(
                "kv_plugin_not_ready", "transport_failed"
            ) from exc
        return _decode_response(response)

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise VllmKVClientError(
                    "kv_plugin_not_ready", "http_client_unavailable"
                ) from exc
            self._client = httpx.Client(timeout=self.timeout_s, trust_env=False)
        return self._client


def _authorization_headers(token_file: Path | None) -> dict[str, str]:
    return {
        "authorization": f"Bearer {_read_token(token_file)}",
        "content-type": "application/json",
    }


def _read_token(token_file: Path | None) -> str:
    if token_file is None:
        raise VllmKVClientError("kv_auth_failed", "token_file_unavailable")
    try:
        metadata = token_file.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise VllmKVClientError("kv_auth_failed", "token_file_permissions")
        token = token_file.read_text(encoding="utf-8").strip()
    except VllmKVClientError:
        raise
    except OSError as exc:
        raise VllmKVClientError("kv_auth_failed", "token_file_unavailable") from exc
    if not token or any(character.isspace() for character in token):
        raise VllmKVClientError("kv_auth_failed", "token_file_invalid")
    return token


def _decode_response(response: Any) -> dict[str, Any]:
    status_code = int(getattr(response, "status_code", 0))
    try:
        payload = response.json()
    except Exception as exc:
        raise VllmKVClientError(
            "kv_plugin_not_ready",
            "invalid_json_response",
            status_code=status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise VllmKVClientError(
            "kv_plugin_not_ready", "invalid_response", status_code=status_code
        )
    if status_code >= 400:
        raise _error_from_payload(payload, status_code=status_code)
    return payload


def _error_from_bytes(raw: bytes, *, status_code: int) -> VllmKVClientError:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return VllmKVClientError(
            "kv_plugin_not_ready",
            "invalid_error_response",
            status_code=status_code,
        )
    return _error_from_payload(payload, status_code=status_code)


def _error_from_payload(
    payload: Mapping[str, Any],
    *,
    status_code: int,
) -> VllmKVClientError:
    code = str(payload.get("error_code", "kv_plugin_not_ready"))
    if code not in KV_ERROR_CODES:
        code = "kv_plugin_not_ready"
    return VllmKVClientError(
        code,
        str(payload.get("detail", "")),
        status_code=status_code,
    )


def _decode_sse_data(lines: list[str]) -> dict[str, Any]:
    try:
        value = json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise VllmKVClientError(
            "kv_plugin_not_ready", "invalid_sse_event"
        ) from exc
    if not isinstance(value, dict):
        raise VllmKVClientError("kv_plugin_not_ready", "invalid_sse_event")
    return value


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("KV client payload must be a mapping or data model")


def _require_loopback_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("KV API base URL must use a loopback host")


__all__ = [
    "KVStreamResult",
    "VllmKVClient",
    "VllmKVClientConfig",
    "VllmKVClientError",
]
