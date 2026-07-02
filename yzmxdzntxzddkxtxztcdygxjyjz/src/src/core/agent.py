"""
Agent基类定义

定义所有Agent的基础接口和通用功能
"""

import asyncio
import uuid
import logging
from typing import Dict, List, Any, Optional, Callable
from abc import ABC, abstractmethod
from datetime import datetime

from ..communication import LocalTransport, Transport
from .protocol import ProtocolHandler, MessageType
from .message import Message, MessageBuilder


class Agent(ABC):
    """
    Agent基类，所有具体Agent的父类
    """

    def __init__(self, agent_id: str = None, capabilities: List[Dict] = None):
        """
        初始化Agent

        Args:
            agent_id: Agent的唯一标识符，若为None则自动生成
            capabilities: Agent支持的能力列表
        """
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self.capabilities = capabilities or []
        self.protocol_handler = ProtocolHandler()
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.neighbors: Dict[str, "Agent"] = {}  # 已连接的其他Agent
        self.transports: Dict[str, Transport] = {}
        self.status = "idle"
        self.logger = logging.getLogger(f"Agent[{self.agent_id}]")
        self.created_at = datetime.now()
        self.message_count = 0
        self.error_count = 0
        # pending response futures keyed by message_id
        self._pending_responses: Dict[str, asyncio.Future] = {}

    def register_capability(
        self, name: str, func: Callable, input_schema: Dict = None, output_schema: Dict = None
    ):
        """
        注册一个能力

        Args:
            name: 能力名称
            func: 实现该能力的函数
            input_schema: 输入参数模式
            output_schema: 输出参数模式
        """
        cap = {
            "name": name,
            "func": func,
            "input_schema": input_schema or {},
            "output_schema": output_schema or {},
        }
        self.capabilities.append(cap)
        self.logger.info(f"Registered capability: {name}")

    def get_capability_by_name(self, name: str) -> Optional[Dict]:
        """获取指定名称的能力"""
        for cap in self.capabilities:
            if cap["name"] == name:
                return cap
        return None

    def connect_to_agent(self, agent: "Agent", transport: Optional[Transport] = None):
        """
        连接到另一个Agent

        Args:
            agent: 目标Agent实例
            transport: 传输层实现，如果未提供则使用 LocalTransport
        """
        self.neighbors[agent.agent_id] = agent
        if transport is None:
            transport = LocalTransport(source_agent=self, target_agent=agent)
        self.transports[agent.agent_id] = transport
        self.logger.info(f"Connected to agent: {agent.agent_id} via {transport.__class__.__name__}")

    async def handshake_with_agent(self, agent: "Agent") -> bool:
        """
        与另一个Agent进行握手

        Args:
            agent: 目标Agent

        Returns:
            握手是否成功
        """
        handshake_msg = MessageBuilder.create_handshake(
            sender_id=self.agent_id,
            receiver_id=agent.agent_id,
            capabilities=self.capabilities,
        )

        try:
            # 发送握手消息
            response = await self._send_message_internal(agent, handshake_msg, timeout=5)
            self.logger.info(f"Handshake successful with {agent.agent_id}")
            return True
        except asyncio.TimeoutError:
            self.logger.error(f"Handshake timeout with {agent.agent_id}")
            return False

    async def send_message(self, target_agent_id: str, message: Message) -> Message:
        """
        发送消息到目标Agent

        Args:
            target_agent_id: 目标Agent ID
            message: 消息对象

        Returns:
            目标Agent的响应
        """
        if target_agent_id not in self.neighbors:
            raise ValueError(f"Agent {target_agent_id} not connected")

        target_agent = self.neighbors[target_agent_id]
        self.message_count += 1

        try:
            response = await self._send_message_internal(target_agent, message, timeout=30)
            return response
        except Exception as e:
            self.error_count += 1
            self.logger.error(f"Failed to send message: {e}")
            raise

    async def _send_message_internal(
        self, target_agent: "Agent", message: Message, timeout: float = 30.0
    ) -> Message:
        """
        内部消息发送方法

        Args:
            target_agent: 目标Agent实例
            message: 消息对象
            timeout: 超时时间（秒）

        Returns:
            响应消息
        """
        # 为该请求创建一个 pending future，供等待逻辑使用
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_responses[message.message_id] = fut

        # 将消息封装到二进制帧中（将message元数据放入payload envelope）
        envelope = {
            "message_id": message.message_id,
            "sender_id": self.agent_id,
            "receiver_id": getattr(target_agent, "agent_id", ""),
            "payload": message.payload,
        }

        frame = self.protocol_handler.encode_message(
            msg_type=message.msg_type, payload=envelope, sequence_id=message.sequence_id, flags=message.flags
        )

        try:
            transport = self.transports.get(target_agent.agent_id)
            if transport is not None:
                resp_frame = await transport.send(frame)
            elif hasattr(target_agent, "receive_frame") and callable(target_agent.receive_frame):
                resp_frame = await target_agent.receive_frame(frame)
            else:
                # 回退：如果目标Agent不支持帧接口，解码并直接处理
                decoded = self.protocol_handler.decode_message(frame)
                _, _, _, payload = decoded
                dummy_msg = Message(
                    message_id=payload.get("message_id", ""),
                    sender_id=payload.get("sender_id", ""),
                    receiver_id=payload.get("receiver_id", ""),
                    msg_type=message.msg_type,
                    sequence_id=message.sequence_id,
                    payload=payload.get("payload", {}),
                )
                resp = await target_agent.handle_message(dummy_msg)
                # 将响应编码为帧
                resp_envelope = {
                    "message_id": resp.message_id,
                    "sender_id": resp.sender_id,
                    "receiver_id": resp.receiver_id,
                    "payload": resp.payload,
                }
                resp_frame = self.protocol_handler.encode_message(
                    msg_type=resp.msg_type, payload=resp_envelope, sequence_id=resp.sequence_id, flags=resp.flags
                )

            # 解码响应帧
            resp_msg_type, resp_seq, resp_flags, resp_payload = self.protocol_handler.decode_message(resp_frame)

            # 构造响应 Message 对象
            response_msg = Message(
                message_id=resp_payload.get("message_id", ""),
                sender_id=resp_payload.get("sender_id", ""),
                receiver_id=resp_payload.get("receiver_id", ""),
                msg_type=resp_msg_type,
                sequence_id=resp_seq,
                payload=resp_payload.get("payload", {}),
                flags=resp_flags,
            )

            if not fut.done():
                fut.set_result(response_msg)

            return response_msg
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            self.logger.error(f"Internal send failed: {e}")
            raise
        finally:
            # 清理 pending future
            self._pending_responses.pop(message.message_id, None)

    async def _wait_for_response(self, message_id: str):
        """等待特定消息的响应"""
        fut = self._pending_responses.get(message_id)
        if fut is None:
            # 如果没有未来对象，则创建并等待（外部会在收到响应时设置）
            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            self._pending_responses[message_id] = fut

        # 等待 future 完成并返回结果
        return await fut

    async def receive_frame(self, frame: bytes) -> bytes:
        """
        接收二进制帧，解码为 Message，处理后将响应编码为帧返回

        Returns:
            二进制响应帧
        """
        try:
            msg_type, seq, flags, payload = self.protocol_handler.decode_message(frame)

            # payload 是 envelope
            message_id = payload.get("message_id")
            sender_id = payload.get("sender_id")
            receiver_id = payload.get("receiver_id", self.agent_id)
            inner_payload = payload.get("payload", {})

            msg = Message(
                message_id=message_id or f"msg_{seq}",
                sender_id=sender_id,
                receiver_id=receiver_id,
                msg_type=msg_type,
                sequence_id=seq,
                payload=inner_payload,
                flags=flags,
            )

            # 处理消息并获取响应 Message
            response_msg = await self.handle_message(msg)

            # 将响应封装并编码为帧
            resp_envelope = {
                "message_id": response_msg.message_id,
                "sender_id": response_msg.sender_id or self.agent_id,
                "receiver_id": response_msg.receiver_id or sender_id,
                "payload": response_msg.payload,
            }

            resp_frame = self.protocol_handler.encode_message(
                msg_type=response_msg.msg_type, payload=resp_envelope, sequence_id=response_msg.sequence_id, flags=response_msg.flags
            )

            return resp_frame
        except Exception as e:
            self.logger.error(f"Failed to receive_frame: {e}")
            # 返回错误帧
            err_payload = {"error": str(e)}
            return self.protocol_handler.encode_message(msg_type=0x0B, payload=err_payload)

    async def handle_message(self, message: Message) -> Message:
        """
        处理收到的消息

        Args:
            message: 接收到的消息

        Returns:
            响应消息
        """
        if message.msg_type == MessageType.HANDSHAKE.value:
            return await self._handle_handshake(message)
        elif message.msg_type == MessageType.CAPABILITY_QUERY.value:
            return await self._handle_capability_query(message)
        elif message.msg_type == MessageType.ACTION_REQUEST.value:
            return await self._handle_action_request(message)
        else:
            self.logger.warning(f"Unknown message type: {message.msg_type}")
            return MessageBuilder.create_error(
                error_code="UNKNOWN_MESSAGE_TYPE", error_message=f"Unknown message type"
            )

    async def _handle_handshake(self, message: Message) -> Message:
        """处理握手消息"""
        self.logger.info(f"Received handshake from {message.sender_id}")
        return MessageBuilder.create_ack(message.message_id, status="ok")

    async def _handle_capability_query(self, message: Message) -> Message:
        """处理能力查询消息"""
        return MessageBuilder.create_capability_response(
            capabilities=self.capabilities, related_request_id=message.message_id
        )

    async def _handle_action_request(self, message: Message) -> Message:
        """处理动作请求消息"""
        payload = message.payload
        action_name = payload.get("action")

        capability = self.get_capability_by_name(action_name)
        if not capability:
            return MessageBuilder.create_error(
                error_code="CAPABILITY_NOT_FOUND",
                error_message=f"Capability '{action_name}' not found",
                related_request_id=message.message_id,
            )

        try:
            # 执行能力对应的函数
            func = capability["func"]
            parameters = payload.get("parameters", {})
            result = await self._execute_capability(func, parameters)

            return MessageBuilder.create_action_result(
                request_id=message.message_id, result=result, status="success", execution_time_ms=0
            )
        except Exception as e:
            self.logger.error(f"Error executing capability: {e}")
            return MessageBuilder.create_error(
                error_code="EXECUTION_ERROR",
                error_message=str(e),
                related_request_id=message.message_id,
            )

    async def _execute_capability(self, func: Callable, parameters: Dict) -> Any:
        """
        执行能力函数

        Args:
            func: 能力函数
            parameters: 参数字典

        Returns:
            执行结果
        """
        if asyncio.iscoroutinefunction(func):
            return await func(**parameters)
        else:
            return func(**parameters)

    async def run(self):
        """
        Agent主循环，持续处理消息队列中的消息
        """
        self.status = "running"
        self.logger.info(f"Agent {self.agent_id} started")

        try:
            while self.status == "running":
                try:
                    message = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                    response = await self.handle_message(message)
                    # 根据需要发送响应
                except asyncio.TimeoutError:
                    # 继续等待消息
                    continue
        except Exception as e:
            self.logger.error(f"Error in agent loop: {e}")
        finally:
            self.status = "stopped"
            self.logger.info(f"Agent {self.agent_id} stopped")

    def stop(self):
        """停止Agent运行"""
        self.status = "stopped"

    def get_stats(self) -> Dict:
        """获取Agent统计信息"""
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "capabilities_count": len(self.capabilities),
            "message_count": self.message_count,
            "error_count": self.error_count,
            "neighbors_count": len(self.neighbors),
            "created_at": self.created_at.isoformat(),
            "uptime_seconds": (datetime.now() - self.created_at).total_seconds(),
        }

    @abstractmethod
    async def execute_task(self, task: Dict) -> Dict:
        """
        执行具体任务，由子类实现

        Args:
            task: 任务定义

        Returns:
            任务执行结果
        """
        pass


class AgentFactory:
    """
    Agent工厂，用于创建和管理Agent实例
    """

    _agents: Dict[str, Agent] = {}

    @classmethod
    def create_agent(cls, agent_type: str, agent_id: str = None, **kwargs) -> Agent:
        """
        创建指定类型的Agent

        Args:
            agent_type: Agent类型
            agent_id: Agent标识符
            **kwargs: 其他参数

        Returns:
            Agent实例
        """
        from ..agents.planner_agent import PlannerAgent
        from ..agents.retriever_agent import RetrieverAgent
        from ..agents.executor_agent import ExecutorAgent
        from ..agents.summarizer_agent import SummarizerAgent

        agent_classes = {
            "planner": PlannerAgent,
            "retriever": RetrieverAgent,
            "executor": ExecutorAgent,
            "summarizer": SummarizerAgent,
        }

        if agent_type not in agent_classes:
            raise ValueError(f"Unknown agent type: {agent_type}")

        agent_class = agent_classes[agent_type]
        agent = agent_class(agent_id=agent_id, **kwargs)
        cls._agents[agent.agent_id] = agent

        return agent

    @classmethod
    def get_agent(cls, agent_id: str) -> Optional[Agent]:
        """获取指定ID的Agent实例"""
        return cls._agents.get(agent_id)

    @classmethod
    def list_agents(cls) -> List[Agent]:
        """列出所有Agent实例"""
        return list(cls._agents.values())

    @classmethod
    def remove_agent(cls, agent_id: str):
        """移除Agent实例"""
        if agent_id in cls._agents:
            del cls._agents[agent_id]
