from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from v2.integrations.vllm_latent.client import AsyncVllmLatentClient
from v2.integrations.vllm_latent.middleware import LatentHandoffMiddleware

from test_vllm_latent_middleware import (
    _App,
    _FakeEngine,
    _complete_payload,
    _produce_payload,
)


@pytest.mark.asyncio
async def test_fake_engine_round_trip_through_authenticated_client(
    neural_signature, tmp_path: Path
):
    token_file = tmp_path / "latent.token"
    token_file.write_text("integration-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(
        _App(engine),
        token_file=token_file,
    )
    transport = httpx.ASGITransport(
        app=wrapped,
        client=("127.0.0.1", 53001),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"authorization": "Bearer integration-token"},
    ) as http_client:
        client = AsyncVllmLatentClient(
            base_url="http://127.0.0.1",
            token_file=token_file,
            http_client=http_client,
        )
        produced = await client.produce(_produce_payload(neural_signature))
        completed = await client.complete(_complete_payload(neural_signature))
        released = await client.release(produced["ref_id"])

    assert produced["ref_id"] == "latent-test-ref"
    assert completed["consumed_ref_id"] == produced["ref_id"]
    assert completed["consumer_forward_observed"] is True
    assert released["status"] == "released"
    assert [method for method, _ in engine.calls].count(
        "statebus_latent_capabilities"
    ) >= 2
