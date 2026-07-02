"""
多智能体系统核心模块初始化
"""

__version__ = "0.1.0"
__author__ = "Multi-Agent Collab Team"

from .agent import Agent, AgentFactory
from .protocol import ProtocolHandler, MessageType
from .message import Message, MessageBuilder
from .runtime import AgentRuntime

__all__ = [
    "Agent",
    "AgentFactory",
    "ProtocolHandler",
    "MessageType",
    "Message",
    "MessageBuilder",
    "AgentRuntime",
]
