"""Compatibility exports for the split research agent package.

There are five real agents: planner, researcher, analyst, executor, summarizer.
The legacy name retriever is an alias only, kept for old scripts.
"""

from agent.analyst import analyst
from agent.executor import executor
from agent.planner import planner
from agent.researcher import researcher
from agent.summarizer import summarizer

# Legacy alias: not an additional agent.
retriever = researcher

__all__ = ["planner", "researcher", "analyst", "executor", "summarizer"]
