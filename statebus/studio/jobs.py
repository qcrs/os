from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
from typing import Any, AsyncIterator
from uuid import uuid4

from statebus.studio.models import RunEvent, RunStatus, RunView
from statebus.studio.recipes import RECIPE_BY_ID, build_command


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELED}
VISIBLE_EVENT_TYPES = {
    "ADAPTIVE_PLAN_APPROVED",
    "ARTIFACT_INVALIDATED",
    "ARTIFACT_PUBLISHED",
    "ARTIFACT_VALIDATED",
    "EVIDENCE_PACK_BUILT",
    "MEMORY_COMMIT_VERIFIED",
    "MEMORY_HYBRID_QUERIED",
    "REPLAY_DECIDED",
    "RETRIEVAL_PRUNED",
    "STATE_CONSUMED",
    "STATE_PUBLISHED",
    "STATE_RELEASED",
    "STEP_COMPLETED",
    "STEP_DISPATCHED",
    "STEP_FAILED",
    "STEP_REJECTED_PRE_DISPATCH",
    "STEP_RUNNING",
    "TASK_SUMMARY_METRICS",
}
METRIC_KEYS = {
    "control_bytes",
    "llm_prompt_tokens",
    "llm_total_tokens",
    "memory_behavioral_effect_count",
    "memory_candidate_count",
    "memory_consumed_count",
    "memory_rejected_incompatible_count",
    "pruning_gain_bytes",
    "retrieval_candidate_count",
    "retrieval_selected_count",
    "semantic_state_consume_count",
    "semantic_state_publish_count",
    "semantic_state_release_count",
    "semantic_state_selected_bytes",
    "semantic_state_transfer_count",
    "skipped_llm_call_count",
    "skipped_step_count",
    "task_ms",
    "total_wire_bytes",
    "verified_artifact_count",
}
PAYLOAD_KEYS = {
    "artifact_id",
    "artifact_ref",
    "backend",
    "consumer_pid",
    "decision",
    "memory_id",
    "memory_ref_id",
    "pack_id",
    "producer_pid",
    "reason",
    "ref_id",
    "selected_candidate_ids",
    "state_ref_id",
    "target_role",
    "validation_status",
}

STAGE_LABELS = {
    "run_created": "运行目录已创建",
    "adaptive_case_started": "Planner 正在生成任务计划",
    "adaptive_case_completed": "单任务执行完成",
    "studio_test": "Studio 自检",
}

ROLE_LABELS = {
    "planner": "Planner",
    "retriever": "Retriever",
    "executor": "Executor",
    "summarizer": "Summarizer",
    "runtime_driver": "Runtime",
    "runtime_supervisor": "Runtime",
}

EVENT_LABELS = {
    "ADAPTIVE_PLAN_APPROVED": "计划已通过策略门",
    "ARTIFACT_INVALIDATED": "产物验证失败",
    "ARTIFACT_PUBLISHED": "执行产物已发布",
    "ARTIFACT_VALIDATED": "执行产物已验证",
    "EVIDENCE_PACK_BUILT": "证据包已组装",
    "MEMORY_COMMIT_VERIFIED": "记忆提交已验证",
    "MEMORY_HYBRID_QUERIED": "共享记忆检索完成",
    "REPLAY_DECIDED": "记忆复用决策完成",
    "RETRIEVAL_PRUNED": "检索候选已裁剪",
    "STATE_CONSUMED": "StateRef 已消费",
    "STATE_PUBLISHED": "StateRef 已发布",
    "STATE_RELEASED": "StateRef 已释放",
    "STEP_COMPLETED": "步骤已完成",
    "STEP_DISPATCHED": "步骤已调度",
    "STEP_FAILED": "步骤执行失败",
    "STEP_REJECTED_PRE_DISPATCH": "步骤在调度前被拒绝",
    "STEP_RUNNING": "步骤运行中",
    "TASK_SUMMARY_METRICS": "任务指标已汇总",
}

EVENT_PROGRESS = {
    "ADAPTIVE_PLAN_APPROVED": 0.20,
    "EVIDENCE_PACK_BUILT": 0.42,
    "ARTIFACT_PUBLISHED": 0.68,
    "ARTIFACT_VALIDATED": 0.76,
    "MEMORY_COMMIT_VERIFIED": 0.94,
    "TASK_SUMMARY_METRICS": 0.96,
}

RESTORED_STAGE_LABELS = {
    "Queued": "等待调度",
    "Runtime preflight": "Runtime 运行前检查",
    "Canceled before start": "排队任务已取消",
    "Canceled": "运行已取消",
    "Completed": "运行完成",
    "Failed": "运行失败",
}

ROLE_PROGRESS = {
    ("retriever", "STEP_RUNNING"): 0.30,
    ("retriever", "STEP_COMPLETED"): 0.44,
    ("executor", "STEP_RUNNING"): 0.54,
    ("executor", "STEP_COMPLETED"): 0.76,
    ("summarizer", "STEP_RUNNING"): 0.82,
    ("summarizer", "STEP_COMPLETED"): 0.91,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[:8]
    if isinstance(value, str):
        return value if len(value) <= 240 else value[:237] + "..."
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:240]


def _diagnose_runner_failure(console_path: Path, return_code: int) -> tuple[str, str]:
    try:
        tail = console_path.read_text(encoding="utf-8", errors="replace")[-24_000:]
    except OSError:
        tail = ""
    if "ModuleNotFoundError: No module named 'runtime'" in tail:
        return (
            "Planner 启动失败",
            "隔离 Agent Worker 无法导入 StateBus Runtime，请重新启动 Studio 以加载项目环境。",
        )
    if "formal_planner_worker_failed" in tail:
        return "Planner 执行失败", "Planner Worker 未能生成有效计划，请查看保留的运行诊断。"
    if "CUDA out of memory" in tail:
        return "Embedding 资源不足", "Embedding GPU 显存不足，请等待其他任务释放资源后重试。"
    if "No CUDA GPUs are available" in tail or "PyTorch cannot access a CUDA device" in tail:
        return "Embedding GPU 不可用", "当前进程无法访问指定 CUDA 设备，请检查容器 GPU 映射与 Embedding device。"
    if "Connection refused" in tail or "APIConnectionError" in tail:
        return "模型服务连接失败", "无法连接既有 vLLM 服务，请检查 53334 健康状态。"
    return "运行失败", f"受控 Runner 退出，代码 {return_code}。完整诊断已保留在 console.log。"


@dataclass
class JobRecord:
    run_id: str
    recipe_id: str
    status: RunStatus
    created_at: str
    run_dir: Path
    started_at: str = ""
    completed_at: str = ""
    progress: float = 0.0
    current_stage: str = "等待调度"
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    process: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    def view(self) -> RunView:
        recipe = RECIPE_BY_ID[self.recipe_id]
        return RunView(
            run_id=self.run_id,
            recipe_id=self.recipe_id,
            recipe_name=recipe.name,
            mode=recipe.mode,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            progress=self.progress,
            current_stage=self.current_stage,
            run_dir=str(self.run_dir),
            error=self.error,
            result=self.result,
            latest_events=self.events[-80:],
        )


class JobManager:
    def __init__(self, runs_root: Path | None = None) -> None:
        self.runs_root = runs_root or Path(
            os.getenv("STATEBUS_STUDIO_RUNS_DIR", str(Path.home() / "statebus" / "runs" / "studio"))
        )
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, JobRecord] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None
        self._restore_jobs()

    def _restore_jobs(self) -> None:
        for status_path in sorted(self.runs_root.glob("*/studio_job.json")):
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                recipe_id = str(payload["recipe_id"])
                if recipe_id not in RECIPE_BY_ID:
                    continue
                status = RunStatus(str(payload["status"]))
                events: list[RunEvent] = []
                events_path = status_path.parent / "studio_events.jsonl"
                if events_path.is_file():
                    for line in events_path.read_text(encoding="utf-8").splitlines()[-1000:]:
                        try:
                            events.append(RunEvent.model_validate_json(line))
                        except (ValueError, TypeError):
                            continue
                interrupted = status in {RunStatus.QUEUED, RunStatus.RUNNING}
                stored_stage = str(payload.get("current_stage", ""))
                restored_stage = (
                    "运行被 Studio 重启中断"
                    if interrupted
                    else RESTORED_STAGE_LABELS.get(stored_stage, stored_stage)
                )
                restored_error = (
                    "Studio 在 Runner 到达终态前停止。"
                    if interrupted
                    else str(payload.get("error", ""))
                )
                console_path = status_path.parent / "console.log"
                if status == RunStatus.FAILED and console_path.is_file():
                    restored_stage, restored_error = _diagnose_runner_failure(
                        console_path,
                        int(payload.get("return_code", 1)),
                    )
                job = JobRecord(
                    run_id=str(payload["run_id"]),
                    recipe_id=recipe_id,
                    status=RunStatus.FAILED if interrupted else status,
                    created_at=str(payload.get("created_at", "")) or _now(),
                    run_dir=status_path.parent,
                    started_at=str(payload.get("started_at", "")),
                    completed_at=str(payload.get("completed_at", "")) or (_now() if interrupted else ""),
                    progress=float(payload.get("progress", 0.0)),
                    current_stage=restored_stage,
                    error=restored_error,
                    result=dict(payload.get("result", {})),
                    events=events,
                )
                self.jobs[job.run_id] = job
                if interrupted:
                    self._persist(job)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue

    async def start(self) -> None:
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker(), name="statebus-studio-worker")

    async def stop(self) -> None:
        for job in self.jobs.values():
            if job.process is not None and job.process.returncode is None:
                self._terminate_process_group(job.process)
        if self.worker_task is not None:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None

    async def create(self, recipe_id: str) -> RunView:
        if recipe_id not in RECIPE_BY_ID:
            raise KeyError(recipe_id)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{uuid4().hex[:8]}"
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        job = JobRecord(
            run_id=run_id,
            recipe_id=recipe_id,
            status=RunStatus.QUEUED,
            created_at=_now(),
            run_dir=run_dir,
        )
        self.jobs[run_id] = job
        await self._emit(job, "RUN_QUEUED", message="任务已加入单 Worker 队列")
        self._persist(job)
        await self.queue.put(run_id)
        return job.view()

    def get(self, run_id: str) -> RunView:
        job = self.jobs.get(run_id)
        if job is None:
            raise KeyError(run_id)
        return job.view()

    def list(self) -> list[RunView]:
        ordered = sorted(self.jobs.values(), key=lambda row: row.created_at, reverse=True)
        return [job.view() for job in ordered]

    async def cancel(self, run_id: str) -> RunView:
        job = self.jobs.get(run_id)
        if job is None:
            raise KeyError(run_id)
        if job.status in TERMINAL_STATUSES:
            return job.view()
        job.cancel_requested = True
        if job.status == RunStatus.QUEUED:
            job.status = RunStatus.CANCELED
            job.current_stage = "排队任务已取消"
            job.completed_at = _now()
            await self._emit(job, "RUN_CANCELED", message="排队任务已取消")
            self._persist(job)
            return job.view()
        process = job.process
        if process is not None and process.returncode is None:
            self._terminate_process_group(process)
        return job.view()

    @staticmethod
    def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                process.send_signal(signal.SIGTERM)

    async def stream(self, run_id: str, after: int = 0) -> AsyncIterator[str]:
        job = self.jobs.get(run_id)
        if job is None:
            raise KeyError(run_id)
        cursor = max(0, after)
        while True:
            fresh = [event for event in job.events if event.sequence > cursor]
            for event in fresh:
                cursor = event.sequence
                yield f"id: {event.sequence}\nevent: run-event\ndata: {event.model_dump_json()}\n\n"
            if job.status in TERMINAL_STATUSES and cursor >= len(job.events):
                yield f"event: stream-end\ndata: {json.dumps({'status': job.status.value})}\n\n"
                break
            try:
                async with job.condition:
                    await asyncio.wait_for(job.condition.wait(), timeout=12.0)
            except TimeoutError:
                yield ": keepalive\n\n"

    async def _worker(self) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                job = self.jobs.get(run_id)
                if job is not None and job.status == RunStatus.QUEUED:
                    await self._run(job)
            finally:
                self.queue.task_done()

    async def _run(self, job: JobRecord) -> None:
        job.status = RunStatus.RUNNING
        job.started_at = _now()
        job.current_stage = "Runtime 运行前检查"
        job.progress = 0.03
        command = build_command(job.recipe_id, job.run_dir, job.run_id)
        (job.run_dir / "command.json").write_text(
            json.dumps({"recipe_id": job.recipe_id, "argv": command}, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        await self._emit(job, "RUN_STARTED", message="受控 Runner 已启动")
        self._persist(job)
        environment = os.environ.copy()
        environment.setdefault("PYTHONUNBUFFERED", "1")
        environment.setdefault("TOKENIZERS_PARALLELISM", "false")
        stdout_path = job.run_dir / "console.log"
        last_payload: dict[str, Any] = {}
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(PROJECT_ROOT),
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            job.process = process
            stdout_task = asyncio.create_task(
                self._capture_stdout(job, process, stdout_path, last_payload),
                name=f"studio-stdout-{job.run_id}",
            )
            telemetry_task = asyncio.create_task(
                self._tail_telemetry(job, process),
                name=f"studio-telemetry-{job.run_id}",
            )
            return_code = await process.wait()
            await stdout_task
            await telemetry_task
            if job.cancel_requested:
                job.status = RunStatus.CANCELED
                job.current_stage = "运行已取消"
                await self._emit(job, "RUN_CANCELED", message="运行任务已取消")
            elif return_code == 0:
                job.status = RunStatus.COMPLETED
                job.current_stage = "运行完成"
                job.progress = 1.0
                job.result = self._result_payload(job, last_payload)
                await self._emit(job, "RUN_COMPLETED", message="运行完成，产物已建立索引")
            else:
                job.status = RunStatus.FAILED
                job.current_stage, job.error = _diagnose_runner_failure(stdout_path, return_code)
                await self._emit(job, "RUN_FAILED", message=job.error)
        except Exception as exc:
            job.status = RunStatus.FAILED
            job.current_stage = "运行失败"
            job.error = f"{type(exc).__name__}: {exc}"
            await self._emit(job, "RUN_FAILED", message=job.error)
        finally:
            job.process = None
            job.completed_at = _now()
            self._persist(job)

    async def _capture_stdout(
        self,
        job: JobRecord,
        process: asyncio.subprocess.Process,
        stdout_path: Path,
        last_payload: dict[str, Any],
    ) -> None:
        assert process.stdout is not None
        with stdout_path.open("w", encoding="utf-8") as handle:
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                handle.write(line)
                handle.flush()
                stripped = line.strip()
                if not stripped.startswith("{"):
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                last_payload.clear()
                last_payload.update(payload)
                stage = str(payload.get("stage", ""))
                if stage:
                    job.current_stage = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                    job.progress = min(0.9, max(job.progress, job.progress + 0.04))
                    await self._emit(job, "RUN_STAGE", message=job.current_stage)

    async def _tail_telemetry(self, job: JobRecord, process: asyncio.subprocess.Process) -> None:
        offsets: dict[Path, int] = {}
        idle_after_exit = 0
        while process.returncode is None or idle_after_exit < 2:
            found = False
            for path in sorted(job.run_dir.glob("**/telemetry/runtime_events.jsonl")):
                offset = offsets.get(path, 0)
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        handle.seek(offset)
                        for line in handle:
                            found = True
                            await self._ingest_runtime_event(job, line)
                        offsets[path] = handle.tell()
                except OSError:
                    continue
            if process.returncode is not None:
                idle_after_exit = 0 if found else idle_after_exit + 1
            await asyncio.sleep(0.35)

    async def _ingest_runtime_event(self, job: JobRecord, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return
        event_type = str(payload.get("event_type", ""))
        if event_type not in VISIBLE_EVENT_TYPES:
            return
        metrics = {
            key: float(value)
            for key, value in dict(payload.get("metrics", {})).items()
            if key in METRIC_KEYS and isinstance(value, (int, float))
        }
        detail = {
            key: _compact_value(value)
            for key, value in dict(payload.get("payload", {})).items()
            if key in PAYLOAD_KEYS
        }
        role = str(payload.get("role", ""))
        task_id = str(payload.get("task_id", ""))
        step_id = str(payload.get("step_id", ""))
        event_label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
        role_label = ROLE_LABELS.get(role, role)
        message = f"{role_label}：{event_label}" if role_label else event_label
        job.current_stage = message
        target_progress = max(
            EVENT_PROGRESS.get(event_type, 0.0),
            ROLE_PROGRESS.get((role, event_type), 0.0),
        )
        if target_progress:
            job.progress = max(job.progress, target_progress)
        await self._emit(
            job,
            event_type,
            role=role,
            task_id=task_id,
            step_id=step_id,
            message=message,
            metrics=metrics,
            payload=detail,
        )

    async def _emit(
        self,
        job: JobRecord,
        event_type: str,
        *,
        role: str = "",
        task_id: str = "",
        step_id: str = "",
        message: str = "",
        metrics: dict[str, float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = RunEvent(
            sequence=len(job.events) + 1,
            timestamp=_now(),
            event_type=event_type,
            role=role,
            task_id=task_id,
            step_id=step_id,
            message=message,
            metrics=metrics or {},
            payload=payload or {},
        )
        job.events.append(event)
        with (job.run_dir / "studio_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        async with job.condition:
            job.condition.notify_all()

    def _result_payload(self, job: JobRecord, stdout_payload: dict[str, Any]) -> dict[str, Any]:
        summaries = sorted(
            job.run_dir.glob("**/summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        summary_path = summaries[0] if summaries else None
        summary: dict[str, Any] = {}
        if summary_path is not None:
            try:
                loaded = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    summary = loaded
            except (OSError, json.JSONDecodeError):
                summary = {}
        return {
            "stdout": stdout_payload,
            "summary": summary,
            "summary_path": "" if summary_path is None else str(summary_path),
            "event_count": len(job.events),
        }

    def _persist(self, job: JobRecord) -> None:
        payload = job.view().model_dump(mode="json")
        target = job.run_dir / "studio_job.json"
        temporary = job.run_dir / ".studio_job.json.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
