"""Research agent package.

Primary role names:
- planner: decomposes the task
- researcher: generates/packages source material
- analyst: ranks context and produces evidence-based analysis
- executor: runs a bounded CodeAct verification step
- summarizer: writes the final answer

Compatibility alias `retriever` remains available for older scripts.
"""

from .analyst import analyst
from .executor import executor
from .planner import planner
from .researcher import researcher
from .summarizer import summarizer

# Legacy alias: not an additional agent.
retriever = researcher

__all__ = ["planner", "researcher", "analyst", "executor", "summarizer"]
