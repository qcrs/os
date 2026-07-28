from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from v2.studio.catalog import PROJECT_ROOT, load_catalog, load_evidence_snapshot
from v2.studio.jobs import JobManager
from v2.studio.models import RunCreate, RunView
from v2.studio.recipes import RECIPES, RECIPE_BY_ID, resolve_embedding_model_path
from v2.studio.task_flow import build_task_flow_index


manager = JobManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await manager.start()
    yield
    await manager.stop()


app = FastAPI(
    title="StateBus Studio API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _probe_url(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=1.5) as response:
            return {"ok": 200 <= response.status < 300, "status": response.status, "url": url}
    except (OSError, URLError) as exc:
        return {"ok": False, "status": 0, "url": url, "detail": str(exc)}


@lru_cache(maxsize=8)
def _probe_embedding_runtime(device: str) -> dict[str, Any]:
    normalized = device.strip().lower() or "auto"
    if normalized == "cpu":
        return {"ok": True, "device": "cpu", "detail": "CPU runtime ready"}
    try:
        import torch
    except ImportError as exc:
        return {"ok": False, "device": normalized, "detail": f"PyTorch unavailable: {exc}"}
    try:
        if normalized == "auto":
            resolved = "cuda:0" if torch.cuda.is_available() else "cpu"
            return {
                "ok": True,
                "device": resolved,
                "detail": "CUDA runtime ready" if resolved.startswith("cuda") else "CPU runtime ready",
                "visible_device_count": int(torch.cuda.device_count()),
            }
        if not normalized.startswith("cuda"):
            return {"ok": False, "device": normalized, "detail": f"Unsupported embedding device: {device}"}
        if not torch.cuda.is_available():
            return {"ok": False, "device": normalized, "detail": "PyTorch cannot access a CUDA device"}
        device_index = int(normalized.split(":", 1)[1]) if ":" in normalized else 0
        device_count = int(torch.cuda.device_count())
        if device_index < 0 or device_index >= device_count:
            return {
                "ok": False,
                "device": normalized,
                "detail": f"CUDA device index {device_index} is outside the visible range 0..{device_count - 1}",
                "visible_device_count": device_count,
            }
        return {
            "ok": True,
            "device": normalized,
            "detail": str(torch.cuda.get_device_name(device_index)),
            "visible_device_count": device_count,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        return {"ok": False, "device": normalized, "detail": f"CUDA runtime probe failed: {exc}"}


@lru_cache(maxsize=1)
def _probe_role_worker_import() -> dict[str, Any]:
    environment = os.environ.copy()
    completed = subprocess.run(
        [sys.executable, "-c", "import runtime.llm; import v2.contracts"],
        cwd=tempfile.gettempdir(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    detail = (completed.stderr or completed.stdout).strip()[-600:]
    return {
        "ok": completed.returncode == 0,
        "detail": detail,
        "project_root_in_pythonpath": str(PROJECT_ROOT) in environment.get("PYTHONPATH", "").split(os.pathsep),
    }


@app.get("/api/v1/system/health")
async def system_health() -> dict[str, Any]:
    model_config = Path(
        os.getenv("STATEBUS_LLM_CONFIG_FILE", str(PROJECT_ROOT / "deploy" / "statebus_llm.yaml.local"))
    )
    embedding_model_path = resolve_embedding_model_path()
    embedding_device = os.getenv("STATEBUS_EMBED_DEVICE", "auto")
    health_url = os.getenv("STATEBUS_LOCAL_VLLM_HEALTH_URL", "http://127.0.0.1:53334/health")
    model_service, role_worker, embedding_runtime = await asyncio.gather(
        asyncio.to_thread(_probe_url, health_url),
        asyncio.to_thread(_probe_role_worker_import),
        asyncio.to_thread(_probe_embedding_runtime, embedding_device),
    )
    queue_ready = manager.worker_task is not None and not manager.worker_task.done()
    embedding_ready = embedding_model_path.is_dir() and embedding_runtime["ok"]
    ready = bool(
        model_config.is_file()
        and embedding_ready
        and model_service["ok"]
        and role_worker["ok"]
        and queue_ready
    )
    return {
        "ok": ready,
        "api": {"ok": True},
        "worker": {"ok": queue_ready, "concurrency": 1},
        "role_worker": role_worker,
        "python": {"ok": True, "executable": sys.executable, "version": sys.version.split()[0]},
        "model_config": {"ok": model_config.is_file(), "path": str(model_config)},
        "embedding_model": {
            "ok": embedding_ready,
            "path": str(embedding_model_path),
            "device": embedding_device,
            "runtime": embedding_runtime,
        },
        "model_service": model_service,
        "policy": "reuse-existing-model-service-never-restart",
    }


@app.get("/api/v1/evidence/current")
async def evidence_current() -> dict[str, Any]:
    return load_evidence_snapshot()


@app.get("/api/v1/catalog")
async def catalog() -> dict[str, Any]:
    payload = load_catalog()
    payload["recipes"] = [recipe.public_payload() for recipe in RECIPES]
    return payload


@app.get("/api/v1/runs", response_model=list[RunView])
async def list_runs() -> list[RunView]:
    return manager.list()


@app.post("/api/v1/runs", response_model=RunView, status_code=202)
async def create_run(request: RunCreate) -> RunView:
    if request.recipe_id not in RECIPE_BY_ID:
        raise HTTPException(status_code=422, detail="Unknown or disabled recipe_id")
    embedding_model_path = resolve_embedding_model_path()
    embedding_device = os.getenv("STATEBUS_EMBED_DEVICE", "auto")
    health_url = os.getenv("STATEBUS_LOCAL_VLLM_HEALTH_URL", "http://127.0.0.1:53334/health")
    role_worker, embedding_runtime, model_service = await asyncio.gather(
        asyncio.to_thread(_probe_role_worker_import),
        asyncio.to_thread(_probe_embedding_runtime, embedding_device),
        asyncio.to_thread(_probe_url, health_url),
    )
    if not role_worker["ok"]:
        raise HTTPException(
            status_code=503,
            detail="隔离 Agent Worker 环境未就绪，请通过 scripts/run_statebus_studio.sh 重新启动 Studio。",
        )
    if not embedding_model_path.is_dir():
        raise HTTPException(
            status_code=503,
            detail=f"Embedding 模型目录不存在：{embedding_model_path}。",
        )
    if not embedding_runtime["ok"]:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding 运行环境未就绪：{embedding_runtime['detail']}。",
        )
    if not model_service["ok"]:
        raise HTTPException(status_code=503, detail="既有 vLLM 服务不可用，请检查 53334 健康状态。")
    return await manager.create(request.recipe_id)


@app.get("/api/v1/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str) -> RunView:
    try:
        return manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/v1/runs/{run_id}/events")
async def run_events(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    try:
        stream = manager.stream(run_id, after=after)
        manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/runs/{run_id}/result")
async def run_result(run_id: str) -> dict[str, Any]:
    try:
        run = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return {"run_id": run.run_id, "status": run.status, "result": run.result, "error": run.error}


@app.get("/api/v1/runs/{run_id}/artifacts")
async def run_artifacts(run_id: str) -> dict[str, Any]:
    try:
        run = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    root = Path(run.run_dir)
    artifacts = []
    for path in sorted(root.glob("**/*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(root)
        if len(relative.parts) > 8:
            continue
        artifacts.append({"path": str(relative), "size_bytes": path.stat().st_size})
        if len(artifacts) >= 300:
            break
    return {"run_id": run_id, "artifacts": artifacts}


@app.get("/api/v1/runs/{run_id}/task-flow")
async def run_task_flow(
    run_id: str,
    task_id: str = Query(default="", max_length=160, pattern=r"^[A-Za-z0-9_.:-]*$"),
) -> dict[str, Any]:
    try:
        run = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    payload = build_task_flow_index(Path(run.run_dir), task_id=task_id)
    return {"run_id": run_id, **payload}


@app.post("/api/v1/runs/{run_id}/cancel", response_model=RunView)
async def cancel_run(run_id: str) -> RunView:
    try:
        return await manager.cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


DIST_DIR = PROJECT_ROOT / "studio-ui" / "dist"
if DIST_DIR.is_dir():
    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="studio-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def studio_frontend(path: str) -> FileResponse:
        candidate = (DIST_DIR / path).resolve()
        try:
            candidate.relative_to(DIST_DIR.resolve())
        except ValueError:
            return FileResponse(DIST_DIR / "index.html")
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def studio_not_built() -> JSONResponse:
        return JSONResponse(
            {
                "service": "StateBus Studio API",
                "frontend": "not built",
                "hint": "Run npm install && npm run build in studio-ui",
            }
        )
