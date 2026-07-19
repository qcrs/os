from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence

from v2.utils import sha256_digest


@dataclass(frozen=True)
class CodeActSandboxConfig:
    requested_backend: str = "auto"
    timeout_seconds: float = 30.0
    cpu_seconds: int = 15
    address_space_bytes: int = 2 * 1024 * 1024 * 1024
    file_size_bytes: int = 64 * 1024 * 1024
    nofile_limit: int = 128
    nproc_limit: int = 64
    sandbox_uid: int = 65534
    sandbox_gid: int = 65534
    sandbox_launcher_uid: int = 1021
    sandbox_launcher_gid: int = 1021
    # qcrs owns host-side orchestration processes; a lower inherited RLIMIT_NPROC
    # prevents the nested user-namespace launcher from execing at all.
    llm_nproc_limit: int = 65_536

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
            sandbox_uid=_int_env("STATEBUS_CODEACT_SANDBOX_UID", 65534),
            sandbox_gid=_int_env("STATEBUS_CODEACT_SANDBOX_GID", 65534),
            sandbox_launcher_uid=_int_env("STATEBUS_CODEACT_SANDBOX_LAUNCH_UID", 1021),
            sandbox_launcher_gid=_int_env("STATEBUS_CODEACT_SANDBOX_LAUNCH_GID", 1021),
            llm_nproc_limit=_int_env("STATEBUS_LLM_CODEACT_SANDBOX_NPROC_LIMIT", 65_536),
        )


@dataclass(frozen=True)
class CodeActSandboxResult:
    completed: subprocess.CompletedProcess[str]
    requested_backend: str
    actual_backend: str
    fallback_reason: str = ""


@dataclass(frozen=True)
class CodeActSandboxReadiness:
    ready: bool
    actual_backend: str
    sandbox_uid: int
    sandbox_gid: int
    policy_version: str
    bwrap_version: str = ""
    reason: str = ""
    schema_version: str = "statebus.llm_bwrap_readiness.v1"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "actual_backend": self.actual_backend,
            "sandbox_uid": self.sandbox_uid,
            "sandbox_gid": self.sandbox_gid,
            "policy_version": self.policy_version,
            "bwrap_version": self.bwrap_version,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @property
    def readiness_digest(self) -> str:
        return sha256_digest(self.canonical_payload())


class CodeActSandboxRunner:
    def __init__(self, config: CodeActSandboxConfig | None = None) -> None:
        self.config = config or CodeActSandboxConfig.from_env()
        self._llm_readiness_cache: dict[str, CodeActSandboxReadiness] = {}

    def check_llm_bwrap_readiness(
        self,
        *,
        policy_version: str = "statebus.llm_bwrap.v1",
        refresh: bool = False,
    ) -> CodeActSandboxReadiness:
        """Probe the actual unprivileged bwrap profile; PATH discovery alone is not readiness."""
        cache_key = f"{policy_version}:{self.config.sandbox_uid}:{self.config.sandbox_gid}"
        if not refresh and cache_key in self._llm_readiness_cache:
            return self._llm_readiness_cache[cache_key]
        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            readiness = CodeActSandboxReadiness(
                ready=False, actual_backend="bwrap_missing", sandbox_uid=self.config.sandbox_uid,
                sandbox_gid=self.config.sandbox_gid, policy_version=policy_version, reason="bwrap_not_installed",
            )
            self._llm_readiness_cache[cache_key] = readiness
            return readiness
        version_result = subprocess.run([bwrap_path, "--version"], text=True, capture_output=True, check=False)
        bwrap_version = (version_result.stdout or version_result.stderr).strip()[:160]
        with tempfile.TemporaryDirectory(prefix="statebus-llm-bwrap-readiness-") as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            outputs = root / "outputs"
            inputs.mkdir()
            outputs.mkdir()
            (inputs / "probe.json").write_text("{}\n", encoding="utf-8")
            (inputs / "probe.json").chmod(0o444)
            inputs.chmod(0o555)
            outputs.chmod(0o777)
            source = root / "readiness_probe.py"
            source.write_text(
                "import os, socket\n"
                "from pathlib import Path\n"
                "assert os.getuid() != 0 and os.getgid() != 0, 'sandbox_identity_is_root'\n"
                "try:\n"
                "    socket.create_connection(('1.1.1.1', 53), timeout=0.2)\n"
                "    raise RuntimeError('sandbox_network_available')\n"
                "except OSError:\n"
                "    pass\n"
                "for target in ('/sandbox/inputs/deny', '/sandbox/outside'):\n"
                "    try:\n"
                "        Path(target).write_text('deny', encoding='utf-8')\n"
                "        raise RuntimeError('sandbox_write_escape:' + target)\n"
                "    except OSError:\n"
                "        pass\n"
                "assert not Path('/sandbox/project').exists(), 'repo_mounted'\n"
                "assert not Path('/workspace/statebus/project').exists(), 'host_repo_mounted'\n"
                "assert not Path('/sandbox/other-task').exists(), 'other_workspace_mounted'\n"
                "Path('/sandbox/outputs/probe.json').write_text('{\\\"ok\\\":true}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            source.chmod(0o444)
            completed = self._run_llm_bwrap(
                bwrap_path=bwrap_path,
                command=(sys.executable, "/sandbox/generated.py"),
                env={},
                source_path=source,
                inputs_dir=inputs,
                outputs_dir=outputs,
            )
            probe_output = outputs / "probe.json"
            ready = completed.returncode == 0 and probe_output.is_file() and not probe_output.is_symlink()
            readiness = CodeActSandboxReadiness(
                ready=ready,
                actual_backend="bwrap" if ready else "bwrap_failed",
                sandbox_uid=self.config.sandbox_uid,
                sandbox_gid=self.config.sandbox_gid,
                policy_version=policy_version,
                bwrap_version=bwrap_version,
                reason="" if ready else self._fallback_reason(completed),
            )
        self._llm_readiness_cache[cache_key] = readiness
        return readiness

    def run_llm_bwrap(
        self,
        *,
        source_path: Path,
        inputs_dir: Path,
        outputs_dir: Path,
        policy_version: str,
    ) -> CodeActSandboxResult:
        """Execute untrusted generated code only under the minimal bwrap policy, never resource/none."""
        readiness = self.check_llm_bwrap_readiness(policy_version=policy_version)
        if not readiness.ready:
            completed = subprocess.CompletedProcess(
                args=[str(source_path)], returncode=127, stdout="", stderr=readiness.reason or "bwrap_not_ready",
            )
            return CodeActSandboxResult(
                completed=completed,
                requested_backend="bwrap_required",
                actual_backend=readiness.actual_backend,
                fallback_reason=readiness.reason or "bwrap_not_ready",
            )
        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            raise RuntimeError("bwrap_disappeared_after_readiness")
        completed = self._run_llm_bwrap(
            bwrap_path=bwrap_path,
            command=(sys.executable, "/sandbox/generated.py"),
            env={},
            source_path=source_path,
            inputs_dir=inputs_dir,
            outputs_dir=outputs_dir,
        )
        return CodeActSandboxResult(
            completed=completed,
            requested_backend="bwrap_required",
            actual_backend="bwrap" if completed.returncode == 0 else "bwrap",
            fallback_reason="" if completed.returncode == 0 else self._fallback_reason(completed),
        )

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

    def _run_llm_bwrap(
        self,
        *,
        bwrap_path: str,
        command: Sequence[str],
        env: dict[str, str],
        source_path: Path,
        inputs_dir: Path,
        outputs_dir: Path,
    ) -> subprocess.CompletedProcess[str]:
        env_args: list[str] = []
        safe_env = {
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            **env,
        }
        for key, value in sorted(safe_env.items()):
            env_args.extend(("--setenv", key, value))
        python_runtime_root = Path(sys.executable).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="statebus-llm-bwrap-root-") as root_dir:
            sandbox_root = Path(root_dir)
            (sandbox_root / "inputs").mkdir()
            (sandbox_root / "outputs").mkdir()
            (sandbox_root / "generated.py").touch()
            # The formal container starts the runtime as root. Its seccomp profile
            # disallows a nested user namespace, so retain bwrap's mount/process/
            # network isolation and drop privileges only after entering bwrap.
            # The directory is freshly created for one execution and is the sole
            # writable mount exposed to generated code.
            sandbox_root.chmod(0o555)
            outputs_dir.chmod(0o777)
            identity_args: list[str] = []
            sandbox_command = list(command)
            if os.geteuid() == 0:
                sandbox_command = [
                    "/usr/bin/setpriv",
                    "--reuid", str(self.config.sandbox_uid),
                    "--regid", str(self.config.sandbox_gid),
                    "--clear-groups",
                    "--",
                    *command,
                ]
            else:
                # Outside the formal root-launched container, only a user
                # namespace can provide the required non-root execution identity.
                identity_args = [
                    "--unshare-user",
                    "--uid", str(self.config.sandbox_uid),
                    "--gid", str(self.config.sandbox_gid),
                ]
            argv = [
                bwrap_path,
                "--die-with-parent", "--new-session",
                *identity_args,
                "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-net",
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc",
                *self._ro_bind_args(Path("/usr")), *self._ro_bind_args(Path("/usr/local")),
                *self._ro_bind_args(Path("/bin")), *self._ro_bind_args(Path("/lib")), *self._ro_bind_args(Path("/lib64")),
                # Host tests use a user-owned Python 3.11 prefix. Mount only that runtime,
                # not the repository or any task workspace.
                *self._ro_bind_args(python_runtime_root),
                *self._ro_bind_args(Path("/etc/ld.so.cache")), *self._ro_bind_args(Path("/etc/ld.so.conf")),
                *self._ro_bind_args(Path("/etc/ld.so.conf.d")),
                *self._ro_bind_args(Path("/etc/passwd")), *self._ro_bind_args(Path("/etc/group")),
                *self._ro_bind_args(Path("/etc/subuid")), *self._ro_bind_args(Path("/etc/subgid")),
                # The skeleton is host-owned and read-only in the user namespace.
                # bwrap overlays only the generated source, inputs, and output mount.
                "--ro-bind", str(sandbox_root), "/sandbox",
                "--ro-bind", str(source_path), "/sandbox/generated.py",
                "--ro-bind", str(inputs_dir), "/sandbox/inputs",
                "--bind", str(outputs_dir), "/sandbox/outputs",
                # subprocess.run(env={}) already clears inherited host variables. bwrap
                # 0.4 lacks --clearenv, while --setenv is supported by both host and container versions.
                "--chdir", "/sandbox", *env_args,
                *sandbox_command,
            ]
            try:
                return subprocess.run(
                    argv, text=True, capture_output=True, check=False, env={},
                    timeout=self.config.timeout_seconds, preexec_fn=self._llm_resource_preexec,
                )
            except subprocess.TimeoutExpired as exc:
                return subprocess.CompletedProcess(
                    args=argv, returncode=124, stdout=exc.stdout or "", stderr=(exc.stderr or "") + "\nsandbox_timeout",
                )

    def _resource_preexec(self) -> None:
        self._set_limit(resource.RLIMIT_CPU, self.config.cpu_seconds)
        self._set_limit(resource.RLIMIT_AS, self.config.address_space_bytes)
        self._set_limit(resource.RLIMIT_FSIZE, self.config.file_size_bytes)
        self._set_limit(resource.RLIMIT_NOFILE, self.config.nofile_limit)
        if hasattr(resource, "RLIMIT_NPROC"):
            self._set_limit(resource.RLIMIT_NPROC, self.config.nproc_limit)

    def _llm_resource_preexec(self) -> None:
        self._set_limit(resource.RLIMIT_CPU, self.config.cpu_seconds)
        self._set_limit(resource.RLIMIT_AS, self.config.address_space_bytes)
        self._set_limit(resource.RLIMIT_FSIZE, self.config.file_size_bytes)
        self._set_limit(resource.RLIMIT_NOFILE, self.config.nofile_limit)
        if hasattr(resource, "RLIMIT_NPROC"):
            self._set_limit(resource.RLIMIT_NPROC, self.config.llm_nproc_limit)

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
