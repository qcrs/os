from __future__ import annotations

import os

import pytest

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")


@pytest.fixture(autouse=True)
def stable_codeact_sandbox_backend_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATEBUS_CODEACT_SANDBOX_BACKEND", "resource")
