from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def stable_codeact_sandbox_backend_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATEBUS_CODEACT_SANDBOX_BACKEND", "resource")
