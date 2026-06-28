"""Compatibility exports for the split research agent package.

There are five real agents: planner, researcher, analyst, executor, summarizer.
The legacy name retriever is an alias only, kept for old scripts.
"""

from agent import analyst, executor, planner, researcher, summarizer

# Legacy alias: not an additional agent.
retriever = researcher

__all__ = ["planner", "researcher", "analyst", "executor", "summarizer"]
