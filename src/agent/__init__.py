"""Research agent package with lazy exports.

Primary role names:
- planner: decomposes the task
- researcher: generates/packages source material
- analyst: ranks context and produces evidence-based analysis
- executor: runs a bounded CodeAct verification step
- summarizer: writes the final answer

Compatibility aliases remain available for older scripts.
"""

from importlib import import_module


__all__ = [
    "planner",
    "researcher",
    "retriever",
    "analyst",
    "executor",
    "summarizer",
    "codeact",
]


def __getattr__(name: str):
    if name == "planner":
        return import_module(".planner", __name__).planner
    if name in {"researcher", "retriever"}:
        return import_module(".researcher", __name__).researcher
    if name == "analyst":
        return import_module(".analyst", __name__).analyst
    if name == "executor":
        return import_module(".executor", __name__).executor
    if name == "summarizer":
        return import_module(".summarizer", __name__).summarizer
    if name == "codeact":
        return import_module(".codeact", __name__).codeact
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
