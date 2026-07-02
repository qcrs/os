"""
主要源代码模块初始化
"""

__version__ = "0.1.0"
__author__ = "Multi-Agent Collaboration Team"

from .core import Agent, AgentFactory, ProtocolHandler, Message, MessageBuilder, AgentRuntime
from .agents import PlannerAgent, RetrieverAgent, ExecutorAgent, SummarizerAgent
from .memory import MemoryManager, MemoryUnit
from .evaluation import MetricsCollector, PerformanceAnalyzer

__all__ = [
    # Core
    "Agent",
    "AgentFactory",
    "ProtocolHandler",
    "Message",
    "MessageBuilder",
    "AgentRuntime",
    # Agents
    "PlannerAgent",
    "RetrieverAgent",
    "ExecutorAgent",
    "SummarizerAgent",
    # Memory
    "MemoryManager",
    "MemoryUnit",
    # Evaluation
    "MetricsCollector",
    "PerformanceAnalyzer",
]
