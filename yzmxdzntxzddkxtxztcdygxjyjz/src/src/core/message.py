"""
消息定义和构造模块

定义系统中各类消息的数据结构和构造方法
"""

import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime


class MessageType(Enum):
    """消息类型枚举"""

    RESERVED = 0x00
    HANDSHAKE = 0x01
    CAPABILITY_QUERY = 0x02
    CAPABILITY_RESPONSE = 0x03
    ACTION_REQUEST = 0x04
    ACTION_RESULT = 0x05
    STATE_TRANSFER = 0x06
    STATE_REQUEST = 0x07
    MEMORY_SAVE = 0x08
    MEMORY_QUERY = 0x09
    MEMORY_RESPONSE = 0x0A
    ERROR = 0x0B
    ACK = 0x0C
    HEARTBEAT = 0x0D


@dataclass
class Message:
    """
    消息对象基类
    """

    message_id: str
    sender_id: str
    receiver_id: str
    msg_type: int
    sequence_id: int
    payload: Dict[str, Any]
    flags: int = 0  # bit0: 需要ACK, bit1: 压缩
    timestamp: float = None
    timeout_ms: int = 30000

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().timestamp()

    def requires_ack(self) -> bool:
        """是否需要确认"""
        return bool(self.flags & 0x01)

    def is_compressed(self) -> bool:
        """是否压缩"""
        return bool(self.flags & 0x02)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class MessageBuilder:
    """
    消息构造器，提供便利的方法构造各类消息
    """

    _sequence_counter = 0

    @classmethod
    def _get_next_sequence(cls) -> int:
        """获取下一个序列号"""
        cls._sequence_counter += 1
        return cls._sequence_counter

    @classmethod
    def create_handshake(
        cls,
        sender_id: str,
        receiver_id: str,
        protocol_version: int = 1,
        supported_types: List[int] = None,
        capabilities: List[Dict] = None,
    ) -> Message:
        """
        创建握手消息

        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID
            protocol_version: 协议版本
            supported_types: 支持的消息类型列表
            capabilities: Agent支持的能力列表

        Returns:
            握手消息
        """
        if supported_types is None:
            supported_types = [
                MessageType.ACTION_REQUEST.value,
                MessageType.CAPABILITY_QUERY.value,
                MessageType.STATE_TRANSFER.value,
            ]

        payload = {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "protocol_version": protocol_version,
            "supported_message_types": supported_types,
            "capabilities": capabilities or [],
            "nonce": uuid.uuid4().hex,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id=receiver_id,
            msg_type=MessageType.HANDSHAKE.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
            flags=0x01,  # 需要ACK
        )

    @classmethod
    def create_capability_query(cls, sender_id: str, receiver_id: str) -> Message:
        """创建能力查询消息"""
        payload = {
            "query_type": "all",
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id=receiver_id,
            msg_type=MessageType.CAPABILITY_QUERY.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
            flags=0x01,  # 需要ACK
        )

    @classmethod
    def create_capability_response(
        cls, sender_id: str = "system", capabilities: List[Dict] = None, related_request_id: str = None
    ) -> Message:
        """创建能力响应消息"""
        payload = {
            "capabilities": capabilities or [],
        }

        if related_request_id:
            payload["related_request_id"] = related_request_id

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id="",
            msg_type=MessageType.CAPABILITY_RESPONSE.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )

    @classmethod
    def create_action_request(
        cls,
        sender_id: str,
        receiver_id: str,
        action: str,
        parameters: Dict = None,
        context: Dict = None,
    ) -> Message:
        """
        创建动作请求消息

        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID
            action: 动作名称
            parameters: 动作参数
            context: 上下文信息

        Returns:
            动作请求消息
        """
        payload = {
            "request_id": f"req_{uuid.uuid4().hex[:8]}",
            "action": action,
            "agent_id": sender_id,
            "parameters": parameters or {},
            "context": context or {"task_id": None, "session_id": None},
            "require_state_transfer": False,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id=receiver_id,
            msg_type=MessageType.ACTION_REQUEST.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
            flags=0x01,  # 需要ACK
            timeout_ms=30000,
        )

    @classmethod
    def create_action_result(
        cls,
        request_id: str,
        result: Dict = None,
        status: str = "success",
        execution_time_ms: int = 0,
        error: str = None,
    ) -> Message:
        """创建动作结果消息"""
        payload = {
            "request_id": request_id,
            "status": status,
            "execution_time_ms": execution_time_ms,
            "result": result or {},
            "error": error,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id="",
            receiver_id="",
            msg_type=MessageType.ACTION_RESULT.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )

    @classmethod
    def create_state_transfer(
        cls,
        sender_id: str,
        receiver_id: str,
        state_type: str,
        data: Any,
        metadata: Dict = None,
    ) -> Message:
        """
        创建状态传递消息

        Args:
            sender_id: 发送者
            receiver_id: 接收者
            state_type: 状态类型 (embedding/hidden_state/vector)
            data: 状态数据
            metadata: 元数据

        Returns:
            状态传递消息
        """
        payload = {
            "state_id": f"state_{uuid.uuid4().hex[:8]}",
            "source_agent": sender_id,
            "state_type": state_type,
            "data": data,
            "metadata": metadata or {},
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id=receiver_id,
            msg_type=MessageType.STATE_TRANSFER.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )

    @classmethod
    def create_memory_save(
        cls, sender_id: str, memory_unit: Dict
    ) -> Message:
        """创建记忆保存消息"""
        payload = {
            "memory_unit": memory_unit,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id="memory_store",
            msg_type=MessageType.MEMORY_SAVE.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
            flags=0x01,  # 需要ACK
        )

    @classmethod
    def create_memory_query(
        cls, sender_id: str, query_text: str, query_type: str = "hybrid", top_k: int = 5
    ) -> Message:
        """创建记忆查询消息"""
        payload = {
            "query_id": f"query_{uuid.uuid4().hex[:8]}",
            "query_type": query_type,
            "query_text": query_text,
            "top_k": top_k,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            receiver_id="memory_store",
            msg_type=MessageType.MEMORY_QUERY.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
            flags=0x01,  # 需要ACK
        )

    @classmethod
    def create_error(
        cls, error_code: str, error_message: str, related_request_id: str = None, error_level: str = "ERROR"
    ) -> Message:
        """创建错误消息"""
        payload = {
            "error_code": error_code,
            "error_message": error_message,
            "error_level": error_level,
            "related_request_id": related_request_id,
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id="system",
            receiver_id="",
            msg_type=MessageType.ERROR.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )

    @classmethod
    def create_ack(cls, message_id: str, status: str = "ok") -> Message:
        """创建确认消息"""
        payload = {
            "ack_for_message_id": message_id,
            "status": status,
            "ack_type": "received",
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id="",
            receiver_id="",
            msg_type=MessageType.ACK.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )

    @classmethod
    def create_heartbeat(cls, agent_id: str) -> Message:
        """创建心跳消息"""
        payload = {
            "agent_id": agent_id,
            "status": "healthy",
        }

        return Message(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=agent_id,
            receiver_id="",
            msg_type=MessageType.HEARTBEAT.value,
            sequence_id=cls._get_next_sequence(),
            payload=payload,
        )
