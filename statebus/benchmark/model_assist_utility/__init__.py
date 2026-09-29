"""Long-text model-assist utility suite.

The package is deliberately separate from the contest mainline task catalog.
It owns only the frozen long-text demonstration taskpack and its observers.
"""

from .taskpack import (
    CASE_IDS,
    LOGIT_CASE_IDS,
    PLAN_POSITIONS,
    CompiledCase,
    LogitCase,
    Taskpack,
    compile_taskpack,
    load_taskpack,
    prepare_taskpack,
)

__all__ = [
    "CASE_IDS",
    "LOGIT_CASE_IDS",
    "PLAN_POSITIONS",
    "CompiledCase",
    "LogitCase",
    "Taskpack",
    "compile_taskpack",
    "load_taskpack",
    "prepare_taskpack",
]
