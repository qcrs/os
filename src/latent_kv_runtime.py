"""Latent KV runtime for multi-agent collaboration with non-text state transfer.

D mode (latent_kv) enables agents to pass intermediate KV cache states instead
of natural language text. Each "latent step" is a real transformer forward pass:
  hidden_state → latent_aligner → next_input_embedding (bypasses LM head)

Backend selection (auto-detected at runtime):
  1. RealLatentKVBackend — calls latent_kv_model_server (FastAPI, port 8101)
       Uses real past_key_values tensors via HuggingFace Transformers.
  2. SimLatentKVBackend  — time.sleep simulation (fallback, no model needed)

The public LatentKVRuntime class has the same API as before; callers do not
need to know which backend is in use.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from config import (
    ANALYST_LATENT_STEPS,
    EXECUTOR_LATENT_STEPS,
    LATENT_ALIGNMENT,
    LATENT_KV_DOCKER_CONTAINER,
    LATENT_KV_USE_DOCKER,
    POST_EXEC_LATENT_STEPS,
    VLLM_DTYPE,
    VLLM_MODEL_PATH,
)
from metrics import metrics

# ---------------------------------------------------------------------------
# Model-server connection settings
# ---------------------------------------------------------------------------
_SERVER_PORT = int(os.getenv("LATENT_KV_SERVER_PORT", "8101"))
_SERVER_HOST = os.getenv("LATENT_KV_SERVER_HOST", "localhost")
_SERVER_BASE_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_SERVER_TIMEOUT = float(os.getenv("LATENT_KV_SERVER_TIMEOUT", "120"))

# Docker container for the model server
_DOCKER_CONTAINER = LATENT_KV_DOCKER_CONTAINER


# ---------------------------------------------------------------------------
# LatentKVHandle — serialisable proxy (no tensors)
# ---------------------------------------------------------------------------
@dataclass
class LatentKVHandle:
    """Serialisable handle representing a latent KV state in the agent chain."""

    handle_id: str
    seq_len: int
    latent_steps_added: int
    kv_bytes: int
    agent: str
    parent_handle_id: str | None
    created_at: float
    mode: str  # "prefill" | "latent" | "decode" | "inject" | "sim"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# In-process handle registry (so graph nodes can look up by ID)
# ---------------------------------------------------------------------------
_latent_handles: dict[str, dict] = {}


def register_handle(handle: LatentKVHandle) -> str:
    _latent_handles[handle.handle_id] = {"handle": handle, "timestamp": time.time()}
    return handle.handle_id


def get_handle(handle_id: str) -> LatentKVHandle | None:
    entry = _latent_handles.get(handle_id)
    return entry["handle"] if entry else None


def release_handle(handle_id: str):
    _latent_handles.pop(handle_id, None)


# ---------------------------------------------------------------------------
# RealLatentKVBackend — calls latent_kv_model_server via HTTP
# ---------------------------------------------------------------------------
class RealLatentKVBackend:
    """Calls the FastAPI model server running inside the Docker container.

    The server manages actual past_key_values tensors on GPU.  This backend
    talks to it via HTTP, either directly (if server is on localhost) or via
    docker-exec curl (if running outside the container).
    """

    def __init__(self, base_url: str = _SERVER_BASE_URL, container: str = _DOCKER_CONTAINER):
        self.base_url = base_url
        self.container = container
        self._use_direct = self._check_direct_access()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _check_direct_access(self) -> bool:
        """Returns True if the server is reachable directly (no docker exec needed)."""
        try:
            import urllib.request
            urllib.request.urlopen(f"{self.base_url}/health", timeout=2)
            return True
        except Exception:
            return False

    def _http_post(self, path: str, payload: dict, timeout: float = _SERVER_TIMEOUT) -> dict:
        """POST JSON to the model server; use docker exec if direct access fails."""
        import urllib.error
        import urllib.request

        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError):
            if not self._use_direct:
                return self._docker_exec_post(path, payload, timeout)
            raise

    def _docker_exec_post(self, path: str, payload: dict, timeout: float) -> dict:
        """Fallback: call the server inside the container via docker exec curl."""
        cmd = (
            f"curl -s -X POST http://localhost:{_SERVER_PORT}{path} "
            f"-H 'Content-Type: application/json' "
            f"-d '{json.dumps(payload)}'"
        )
        try:
            result = subprocess.run(
                ["docker", "exec", self.container, "bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            return json.loads(result.stdout.strip())
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            raise RuntimeError(f"docker exec POST {path} failed: {e}")

    def _http_get(self, path: str, timeout: float = 10.0) -> dict:
        import urllib.request
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            # Try via docker exec
            cmd = f"curl -s http://localhost:{_SERVER_PORT}{path}"
            try:
                result = subprocess.run(
                    ["docker", "exec", self.container, "bash", "-c", cmd],
                    capture_output=True, text=True, timeout=timeout, check=True,
                )
                return json.loads(result.stdout.strip())
            except Exception as e:
                raise RuntimeError(f"GET {path} failed: {e}")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        try:
            resp = self._http_get("/health", timeout=5.0)
            return resp.get("status") == "ok"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core operations — mirror the SimLatentKVBackend interface
    # ------------------------------------------------------------------
    def prefill(self, text: str, task_group: str, created_by: str) -> LatentKVHandle:
        resp = self._http_post("/prefill", {
            "text": text, "task_group": task_group, "created_by": created_by,
        })
        handle = LatentKVHandle(
            handle_id=resp["handle_id"],
            seq_len=resp["seq_len"],
            latent_steps_added=0,
            kv_bytes=resp["kv_bytes"],
            agent=created_by,
            parent_handle_id=None,
            created_at=time.time(),
            mode="prefill",
        )
        register_handle(handle)
        return handle

    def run_latent_steps(self, handle_id: str, n_steps: int, agent_name: str) -> LatentKVHandle:
        parent = get_handle(handle_id)
        resp = self._http_post("/latent_steps", {
            "handle_id": handle_id, "n_steps": n_steps, "agent_name": agent_name,
        }, timeout=max(_SERVER_TIMEOUT, n_steps * 0.5))
        handle = LatentKVHandle(
            handle_id=resp["handle_id"],
            seq_len=resp["seq_len"],
            latent_steps_added=resp["latent_steps_added"],
            kv_bytes=resp["kv_bytes"],
            agent=agent_name,
            parent_handle_id=handle_id,
            created_at=time.time(),
            mode="latent",
        )
        register_handle(handle)
        return handle

    def inject_tokens(self, handle_id: str, text: str) -> LatentKVHandle:
        resp = self._http_post("/inject_tokens", {"handle_id": handle_id, "text": text})
        parent = get_handle(handle_id)
        handle = LatentKVHandle(
            handle_id=resp["handle_id"],
            seq_len=resp["seq_len"],
            latent_steps_added=0,
            kv_bytes=resp["kv_bytes"],
            agent=parent.agent if parent else "unknown",
            parent_handle_id=handle_id,
            created_at=time.time(),
            mode="inject",
        )
        register_handle(handle)
        return handle

    def decode(
        self, handle_id: str, prompt: str, max_new_tokens: int = 256, temperature: float = 0.0
    ) -> tuple[str, LatentKVHandle]:
        resp = self._http_post("/decode", {
            "handle_id": handle_id,
            "prompt": prompt,
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "keep_handle": True,
        }, timeout=max(_SERVER_TIMEOUT, max_new_tokens * 0.1))
        parent = get_handle(handle_id)
        new_handle_id = resp.get("handle_id") or f"{handle_id}_decode_{uuid.uuid4().hex[:6]}"
        # Fetch updated metadata from server if available
        try:
            meta = self._http_get(f"/handle/{new_handle_id}", timeout=5.0)
            seq_len = meta["seq_len"]
            kv_bytes = meta["kv_bytes"]
        except Exception:
            seq_len = (parent.seq_len if parent else 0) + resp.get("tokens_generated", 0)
            kv_bytes = parent.kv_bytes if parent else 0
        handle = LatentKVHandle(
            handle_id=new_handle_id,
            seq_len=seq_len,
            latent_steps_added=0,
            kv_bytes=kv_bytes,
            agent="decoder",
            parent_handle_id=handle_id,
            created_at=time.time(),
            mode="decode",
        )
        register_handle(handle)
        return resp["generated_text"], handle

    def delete_handle(self, handle_id: str):
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.base_url}/handle/{handle_id}",
                method="DELETE",
            )
            with urllib.request.urlopen(req, timeout=5.0):
                pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SimLatentKVBackend — pure simulation fallback (time.sleep, no model)
# ---------------------------------------------------------------------------
class SimLatentKVBackend:
    """Simulation backend: reproduces the same API using time.sleep estimates.

    Used when the real model server is unavailable. Metrics are accurate
    (KV byte estimates match Qwen3-8B GQA layout); only timing is synthetic.
    """

    # Qwen3-8B GQA parameters
    _N_LAYERS = 32
    _N_KV_HEADS = 8
    _HEAD_DIM = 128
    _DTYPE_BYTES = 2  # bfloat16
    _STEP_MS = 8.0    # empirical latent step time on A100

    def _kv_bytes(self, seq_len: int) -> int:
        return 2 * self._N_LAYERS * self._N_KV_HEADS * self._HEAD_DIM * self._DTYPE_BYTES * seq_len

    def prefill(self, text: str, task_group: str, created_by: str) -> LatentKVHandle:
        seq_len = max(len(text) // 4, 10)
        time.sleep(min(seq_len * 0.001, 0.5))
        handle_id = f"sim_{task_group}_{hashlib.sha256(text.encode()).hexdigest()[:12]}"
        handle = LatentKVHandle(
            handle_id=handle_id, seq_len=seq_len, latent_steps_added=0,
            kv_bytes=self._kv_bytes(seq_len), agent=created_by,
            parent_handle_id=None, created_at=time.time(), mode="sim",
        )
        register_handle(handle)
        return handle

    def run_latent_steps(self, handle_id: str, n_steps: int, agent_name: str) -> LatentKVHandle:
        parent = get_handle(handle_id)
        if not parent:
            raise ValueError(f"Handle {handle_id} not found")
        time.sleep(min(n_steps * self._STEP_MS / 1000.0, 1.0))
        new_seq = parent.seq_len + n_steps
        new_id = f"{handle_id}_{agent_name}_{uuid.uuid4().hex[:6]}"
        handle = LatentKVHandle(
            handle_id=new_id, seq_len=new_seq, latent_steps_added=n_steps,
            kv_bytes=self._kv_bytes(new_seq), agent=agent_name,
            parent_handle_id=handle_id, created_at=time.time(), mode="sim",
        )
        register_handle(handle)
        return handle

    def inject_tokens(self, handle_id: str, text: str) -> LatentKVHandle:
        parent = get_handle(handle_id)
        if not parent:
            raise ValueError(f"Handle {handle_id} not found")
        tok = max(len(text) // 4, 1)
        new_seq = parent.seq_len + tok
        new_id = f"{handle_id}_inj_{uuid.uuid4().hex[:6]}"
        handle = LatentKVHandle(
            handle_id=new_id, seq_len=new_seq, latent_steps_added=0,
            kv_bytes=self._kv_bytes(new_seq), agent=parent.agent,
            parent_handle_id=handle_id, created_at=time.time(), mode="sim",
        )
        register_handle(handle)
        return handle

    def decode(
        self, handle_id: str, prompt: str, max_new_tokens: int = 256, temperature: float = 0.0
    ) -> tuple[str, LatentKVHandle]:
        parent = get_handle(handle_id)
        if not parent:
            raise ValueError(f"Handle {handle_id} not found")
        time.sleep(min(max_new_tokens * 0.005, 0.5))
        prompt_tok = max(len(prompt) // 4, 4)
        new_seq = parent.seq_len + prompt_tok + max_new_tokens
        new_id = f"{handle_id}_decode_{uuid.uuid4().hex[:6]}"
        text = f"[sim] latent_steps={parent.latent_steps_added}, seq={parent.seq_len}"
        handle = LatentKVHandle(
            handle_id=new_id, seq_len=new_seq, latent_steps_added=0,
            kv_bytes=self._kv_bytes(new_seq), agent="decoder",
            parent_handle_id=handle_id, created_at=time.time(), mode="sim",
        )
        register_handle(handle)
        return text, handle

    def delete_handle(self, handle_id: str):
        release_handle(handle_id)


# ---------------------------------------------------------------------------
# LatentKVRuntime — public facade with auto-backend selection
# ---------------------------------------------------------------------------
class LatentKVRuntime:
    """Unified latent KV runtime.

    On first use, probes whether the real model server is available. If yes,
    delegates all operations to RealLatentKVBackend; otherwise falls back to
    SimLatentKVBackend. Backend can be forced via LATENT_KV_BACKEND env var
    ("real" | "sim").
    """

    def __init__(
        self,
        *,
        model_path: str = VLLM_MODEL_PATH,
        use_docker: bool = LATENT_KV_USE_DOCKER,
    ):
        self.model_path = model_path
        self.use_docker = use_docker

        # Qwen3-8B params (for KV byte estimates in sim mode)
        self.hidden_dim = 4096
        self.n_layers = 32
        self.n_kv_heads = 8
        self.head_dim = 128
        self.dtype_bytes = 2
        self.latent_step_time_ms = 8.0

        force = os.getenv("LATENT_KV_BACKEND", "").lower()
        if force == "sim":
            self._backend: RealLatentKVBackend | SimLatentKVBackend = SimLatentKVBackend()
            self._mode = "sim"
        elif force == "real":
            self._backend = RealLatentKVBackend()
            self._mode = "real"
        else:
            real = RealLatentKVBackend()
            if real.is_available():
                self._backend = real
                self._mode = "real"
            else:
                self._backend = SimLatentKVBackend()
                self._mode = "sim"

    @property
    def backend_mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Public API (same as the original LatentKVRuntime)
    # ------------------------------------------------------------------
    def prefill(self, prefix_text: str, task_group: str, created_by: str = "prefill") -> LatentKVHandle:
        t0 = time.perf_counter()
        handle = self._backend.prefill(prefix_text, task_group, created_by)
        duration = time.perf_counter() - t0
        metrics.record_timing("latent_kv_prefill", duration)
        return handle

    def run_latent_steps(
        self, handle_id: str, n_steps: int, agent_name: str
    ) -> LatentKVHandle:
        t0 = time.perf_counter()
        parent = get_handle(handle_id)

        handle = self._backend.run_latent_steps(handle_id, n_steps, agent_name)
        duration = time.perf_counter() - t0

        kv_bytes_added = handle.kv_bytes - (parent.kv_bytes if parent else 0)
        metrics.record_latent_steps(agent_name, n_steps, duration, max(kv_bytes_added, 0))
        metrics.record_kv_transfer(
            parent.agent if parent else "unknown",
            agent_name,
            handle.kv_bytes,
            copied_bytes=0,
        )
        return handle

    def inject_role_transition(self, handle_id: str, role_text: str) -> LatentKVHandle:
        return self._backend.inject_tokens(handle_id, role_text)

    def generate_code(
        self, handle_id: str, max_tokens: int = 256, temperature: float = 0.0
    ) -> tuple[str, LatentKVHandle]:
        t0 = time.perf_counter()
        prompt = (
            "# Based on the latent reasoning above, write a concise Python snippet "
            "to compute final metrics from the evidence list.\n"
            "evidence = []  # filled at runtime\n"
            "metrics = "
        )
        text, handle = self._backend.decode(handle_id, prompt, max_tokens, temperature)
        duration = time.perf_counter() - t0
        parent = get_handle(handle_id)
        metrics.record_tokens("executor_code", parent.seq_len if parent else 0, max_tokens)
        metrics.record_timing("latent_kv_code_generation", duration)
        return text, handle

    def inject_result_text(self, handle_id: str, result_text: str) -> LatentKVHandle:
        return self._backend.inject_tokens(handle_id, result_text)

    def decode_text(
        self,
        handle_id: str,
        instruction: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.0,
        metric_name: str = "latent_decode",
    ) -> tuple[str, LatentKVHandle]:
        """Decode a small explicit payload from a latent KV state."""
        t0 = time.perf_counter()
        text, handle = self._backend.decode(handle_id, instruction, max_tokens, temperature)
        duration = time.perf_counter() - t0
        parent = get_handle(handle_id)
        metrics.record_tokens(metric_name, parent.seq_len if parent else 0, max_tokens)
        metrics.record_timing(f"latent_kv_{metric_name}", duration)
        return text, handle

    def generate_summary(
        self,
        handle_id: str,
        instruction: str,
        max_tokens: int = 512,
        temperature: float = 0.5,
    ) -> tuple[str, LatentKVHandle]:
        t0 = time.perf_counter()
        text, handle = self._backend.decode(handle_id, instruction, max_tokens, temperature)
        duration = time.perf_counter() - t0
        parent = get_handle(handle_id)
        metrics.record_tokens("summarizer", parent.seq_len if parent else 0, max_tokens)
        metrics.record_timing("latent_kv_summary_generation", duration)
        avoided = (parent.seq_len if parent else 0) - (parent.latent_steps_added if parent else 0)
        metrics.increment("avoided_prefill_tokens", avoided)
        return text, handle

    def get_metrics(self, handle_id: str) -> dict:
        handle = get_handle(handle_id)
        if not handle:
            return {}
        return {
            "seq_len": handle.seq_len,
            "latent_steps": handle.latent_steps_added,
            "kv_bytes": handle.kv_bytes,
            "kv_mb": handle.kv_bytes / 1024 / 1024,
            "agent": handle.agent,
            "mode": handle.mode,
            "backend": self._mode,
        }

    def delete_handle(self, handle_id: str):
        self._backend.delete_handle(handle_id)
        release_handle(handle_id)

    # Kept for API compatibility
    def _compute_kv_bytes(self, seq_len: int) -> int:
        return 2 * self.n_layers * self.n_kv_heads * self.head_dim * self.dtype_bytes * seq_len

    def _compute_kv_bytes_delta(self, n_steps: int) -> int:
        return self._compute_kv_bytes(n_steps)


@lru_cache(maxsize=1)
def get_latent_kv_runtime() -> LatentKVRuntime:
    """Process-local singleton."""
    return LatentKVRuntime()
