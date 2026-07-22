from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from v2.integrations.vllm_latent.client import (
    AsyncVllmLatentClient,
    VllmLatentClient,
    VllmLatentClientError,
)


def _token(tmp_path: Path) -> Path:
    path = tmp_path / "api.token"
    path.write_text("client-secret\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_sync_client_reads_token_from_file_without_exposing_it(tmp_path):
    token_file = _token(tmp_path)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"status": "ready"})

    client = VllmLatentClient(
        base_url="http://127.0.0.1:53334",
        token_file=token_file,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.health() == {"status": "ready"}
    assert seen["authorization"] == "Bearer client-secret"
    assert "client-secret" not in repr(client)
    client.close()


def test_client_maps_stable_error_codes_and_rejects_insecure_token(tmp_path):
    token_file = _token(tmp_path)
    token_file.chmod(0o644)
    client = VllmLatentClient(base_url="http://127.0.0.1", token_file=token_file)
    with pytest.raises(VllmLatentClientError) as caught:
        client.health()
    assert caught.value.error_code == "latent_auth_failed"

    token_file.chmod(0o600)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"error": {"code": "latent_ref_already_consumed"}},
        )

    client = VllmLatentClient(
        base_url="http://127.0.0.1",
        token_file=token_file,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(VllmLatentClientError) as caught:
        client.release("opaque-ref")
    assert caught.value.error_code == "latent_ref_already_consumed"


@pytest.mark.asyncio
async def test_async_client_posts_json_and_uses_same_loopback_contract(tmp_path):
    token_file = _token(tmp_path)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"ref_id": "r", "status": "released"})

    transport = httpx.MockTransport(handler)
    async with AsyncVllmLatentClient(
        base_url="http://127.0.0.1",
        token_file=token_file,
        http_client=httpx.AsyncClient(transport=transport),
    ) as client:
        result = await client.release("opaque-ref")
    assert result["status"] == "released"
    assert seen == {
        "authorization": "Bearer client-secret",
        "path": "/statebus/latent/release",
    }
