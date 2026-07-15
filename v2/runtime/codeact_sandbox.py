from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import resource
import shutil
import subprocess
from typing import Sequence


@dataclass(frozen=True)
class CodeActSandboxConfig:
    requested_backend: str = "auto"
    timeout_seconds: float = 30.0
    cpu_seconds: int = 15
    address_space_bytes: int = 2 * 1024 * 1024 * 1024
    file_size_bytes: int = 64 * 1024 * 1024
    nofile_limit: int = 128
    nproc_limit: int = 64

    @classmethod
    def from_env(cls) -> "CodeActSandboxConfig":
        def _float_env(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except ValueError:
                return default

        def _int_env(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except ValueError:
                return default

        return cls(
            requested_backend=os.getenv("STATEBUS_CODEACT_SANDBOX_BACKEND", "auto").strip() or "auto",
            timeout_seconds=_float_env("STATEBUS_CODEACT_SANDBOX_TIMEOUT_SECONDS", 30.0),
            cpu_seconds=_int_env("STATEBUS_CODEACT_SANDBOX_CPU_SECONDS", 15),
            address_space_bytes=_int_env(
                "STATEBUS_CODEACT_SANDBOX_ADDRESS_SPACE_BYTES",
                2 * 1024 * 1024 * 1024,
            ),
            file_size_bytes=_int_env("STATEBUS_CODEACT_SANDBOX_FILE_SIZE_BYTES", 64 * 1024 * 1024),
            nofile_limit=_int_env("STATEBUS_CODEACT_SANDBOX_NOFILE_LIMIT", 128),
            nproc_limit=_int_env("STATEBUS_CODEACT_SANDBOX_NPROC_LIMIT", 64),
        )


@dataclass(frozen=True)
class CodeActSandboxResult:
    completed: subprocess.CompletedProcess[str]
    requested_backend: str
    actual_backend: str
    fallback_reason: str = ""


class CodeActSandboxRunner:
    def __init__(self, config: CodeActSandboxConfig | None = None) -> None:
        self.config = config or CodeActSandboxConfig.from_env()

    def run(
        self,
        *,
        host_command: Sequence[str],
        bwrap_command: Sequence[str],
        cwd: Path,
        host_env: dict[str, str],
        bwrap_env: dict[str, str],
        workspace_root: Path,
        project_root: Path,
    ) -> CodeActSandboxResult:
        requested = self.config.requested_backend.lower()
        if requested not in {"auto", "bwrap", "resource", "none"}:
            requested = "auto"
        if requested in {"auto", "bwrap"}:
            bwrap_path = shutil.which("bwrap")
            if bwrap_path:
                completed = self._run_bwrap(
                    bwrap_path=bwrap_path,
                    command=bwrap_command,
                    env=bwrap_env,
                    workspace_root=workspace_root,
                    project_root=project_root,
                )
                if requested == "bwrap" or completed.returncode == 0:
                    return CodeActSandboxResult(
                        completed=completed,
                        requested_backend=requested,
                        actual_backend="bwrap",
                    )
                fallback_reason = self._fallback_reason(completed)
                resource_completed = self._run_resource(host_command=host_command, cwd=cwd, env=host_env)
                return CodeActSandboxResult(
                    completed=resource_completed,
                    requested_backend=requested,
                    actual_backend="resource",
                    fallback_reason=fallback_reason,
                )
            if requested == "bwrap":
                completed = subprocess.CompletedProcess(
                    args=list(host_command),
                    returncode=127,
                    stdout="",
                    stderr="bwrap backend requested but bwrap is not installed",
                )
                return CodeActSandboxResult(
                    completed=completed,
                    requested_backend=requested,
                    actual_backend="bwrap_missing",
                    fallback_reason="bwrap_not_installed",
                )
        if requested == "none":
            completed = subprocess.run(
                list(host_command),
                cwd=str(cwd),
                text=True,
                capture_output=True,
                check=False,
                env=host_env,
                timeout=self.config.timeout_seconds,
            )
            return CodeActSandboxResult(
                completed=completed,
                requested_backend=requested,
                actual_backend="none",
            )
        completed = self._run_resource(host_command=host_command, cwd=cwd, env=host_env)
        return CodeActSandboxResult(
            completed=completed,
            requested_backend=requested,
            actual_backend="resource",
            fallback_reason="bwrap_not_installed" if requested == "auto" else "",
        )

    def _run_resource(
        self,
        *,
        host_command: Sequence[str],
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(host_command),
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=self.config.timeout_seconds,
            preexec_fn=self._resource_preexec,
        )

    def _run_bwrap(
        self,
        *,
        bwrap_path: str,
        command: Sequence[str],
        env: dict[str, str],
        workspace_root: Path,
        project_root: Path,
    ) -> subprocess.CompletedProcess[str]:
        bwrap_env_args: list[str] = []
        for key, value in sorted(env.items()):
            bwrap_env_args.extend(("--setenv", key, value))
        argv = [
            bwrap_path,
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-net",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/sandbox",
            *self._ro_bind_args(Path("/usr")),
            *self._ro_bind_args(Path("/bin")),
            *self._ro_bind_args(Path("/lib")),
            *self._ro_bind_args(Path("/lib64")),
            *self._ro_bind_args(Path("/etc/ld.so.cache")),
            *self._ro_bind_args(Path("/etc/ld.so.conf")),
            *self._ro_bind_args(Path("/etc/ld.so.conf.d")),
            *self._ro_bind_args(Path("/etc/passwd")),
            *self._ro_bind_args(Path("/etc/group")),
            *self._ro_bind_args(project_root, Path("/sandbox/project")),
            *self._ro_bind_args(Path("/statebus/runs")),
            *self._ro_bind_args(Path("/statebus/work")),
            "--tmpfs",
            "/sandbox/project/deploy",
            "--bind",
            str(workspace_root),
            "/sandbox/workspace",
            "--chdir",
            "/sandbox/workspace",
            *bwrap_env_args,
            *command,
        ]
        return subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            env={},
            timeout=self.config.timeout_seconds,
            preexec_fn=self._resource_preexec,
        )

    def _resource_preexec(self) -> None:
        self._set_limit(resource.RLIMIT_CPU, self.config.cpu_seconds)
        self._set_limit(resource.RLIMIT_AS, self.config.address_space_bytes)
        self._set_limit(resource.RLIMIT_FSIZE, self.config.file_size_bytes)
        self._set_limit(resource.RLIMIT_NOFILE, self.config.nofile_limit)
        if hasattr(resource, "RLIMIT_NPROC"):
            self._set_limit(resource.RLIMIT_NPROC, self.config.nproc_limit)

    @staticmethod
    def _set_limit(kind: int, value: int) -> None:
        try:
            resource.setrlimit(kind, (value, value))
        except (OSError, ValueError):
            return

    @staticmethod
    def _ro_bind_args(source: Path, dest: Path | None = None) -> list[str]:
        if not source.exists():
            return []
        return ["--ro-bind", str(source), str(dest or source)]

    @staticmethod
    def _fallback_reason(completed: subprocess.CompletedProcess[str]) -> str:
        stderr = completed.stderr.strip().splitlines()
        if stderr:
            return f"bwrap_failed:{stderr[-1][:180]}"
        return f"bwrap_failed:returncode={completed.returncode}"
