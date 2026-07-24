from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from dataclasses import dataclass


@dataclass
class CodeActResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float
    script_sha256: str


class CodeActRunner:
    """Experimental host-only CodeAct runner.

    This path is optional and is not part of the formal contest mainline. It
    uses subprocess and timeout guards only, so it must not be presented as a
    secure sandbox.
    """

    FORBIDDEN_IMPORTS = {"os", "subprocess", "shutil", "socket", "requests",
                          "ctypes", "importlib", "__import__", "compile", "exec", "eval"}

    def __init__(self, timeout_seconds: int = 10, work_dir: str | None = None) -> None:
        self.timeout = timeout_seconds
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="codeact_")

    def validate_script(self, code: str) -> tuple[bool, str]:
        for forbidden in self.FORBIDDEN_IMPORTS:
            if f"import {forbidden}" in code or f"from {forbidden}" in code:
                return False, f"Forbidden import: {forbidden}"
        dangerous_patterns = ["__import__(", "compile(", "exec(", "eval("]
        for pattern in dangerous_patterns:
            if pattern in code:
                return False, f"Forbidden builtin: {pattern}"
        return True, ""

    async def execute(self, code: str, stdin_data: str = "") -> CodeActResult:
        valid, reason = self.validate_script(code)
        if not valid:
            return CodeActResult(False, "", reason, -1, 0, _code_hash(code))

        script_path = os.path.join(self.work_dir, f"script_{int(time.time() * 1_000_000)}.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        start = time.monotonic()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", script_path,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data.encode() if stdin_data else None),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            if proc is not None:
                proc.kill()
                try:
                    await proc.communicate()
                except Exception:
                    pass
            return CodeActResult(
                False,
                "",
                "Execution timeout",
                -1,
                (time.monotonic() - start) * 1000,
                _code_hash(code),
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        elapsed = (time.monotonic() - start) * 1000
        return CodeActResult(
            success=proc.returncode == 0,
            stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
            stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
            exit_code=proc.returncode if proc.returncode is not None else -1,
            execution_time_ms=elapsed,
            script_sha256=_code_hash(code),
        )


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
