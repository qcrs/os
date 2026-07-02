"""
协议处理器 - 处理消息编解码和序列化
"""

import struct
import zlib
import logging
from typing import Dict, Any, Tuple, Optional
import msgpack
import json

from .message import MessageType


class ProtocolHandler:
    """
    处理Agent通信协议的编解码
    """

    MAGIC_BYTES = b"\xAB\xCD"
    VERSION = 0x01
    HEADER_FORMAT = ">2sBBBHIH"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, encoding: str = "msgpack", compression: bool = False):
        """
        初始化协议处理器

        Args:
            encoding: 编码格式 (msgpack/json/protobuf)
            compression: 是否启用压缩
        """
        self.encoding = encoding
        self.compression = compression
        self.logger = logging.getLogger("ProtocolHandler")

    def encode_message(self, msg_type: int, payload: Dict[str, Any], sequence_id: int = 0, flags: int = 0) -> bytes:
        """
        将消息编码为二进制格式

        Args:
            msg_type: 消息类型
            payload: 消息负载（字典）
            sequence_id: 序列号
            flags: 标志位

        Returns:
            二进制编码的消息
        """
        # 序列化负载
        serialized_payload = self._serialize_payload(payload)

        # 检查是否需要压缩
        if self.compression and len(serialized_payload) > 1024:  # 1KB以上才压缩
            serialized_payload = zlib.compress(serialized_payload, level=6)
            flags |= 0x02  # 设置压缩标志

        payload_length = len(serialized_payload)

        # 构造头部
        header = struct.pack(
            self.HEADER_FORMAT,
            self.MAGIC_BYTES,
            self.VERSION,
            msg_type,
            flags,
            0,  # reserved
            payload_length,
            sequence_id,
        )

        # 计算校验和 (CRC32)
        frame = header + serialized_payload
        checksum = zlib.crc32(frame) & 0xFFFFFFFF

        # 添加校验和
        full_message = frame + struct.pack(">I", checksum)

        return full_message

    def decode_message(self, data: bytes) -> Tuple[int, int, int, Dict[str, Any]]:
        """
        将二进制数据解码为消息

        Args:
            data: 二进制数据

        Returns:
            (消息类型, 序列号, 负载字典)

        Raises:
            ValueError: 如果数据格式不正确
        """
        if len(data) < self.HEADER_SIZE + 4:  # header + checksum
            raise ValueError(f"Message too short: {len(data)} bytes")

        # 验证Magic字节
        if data[:2] != self.MAGIC_BYTES:
            raise ValueError(f"Invalid magic bytes: {data[:2].hex()}")

        # 解析头部
        header = data[: self.HEADER_SIZE]
        (magic, version, msg_type, flags, reserved, payload_length, sequence_id) = struct.unpack(
            self.HEADER_FORMAT, header
        )

        # 验证版本
        if version != self.VERSION:
            raise ValueError(f"Protocol version mismatch: {version} != {self.VERSION}")

        # 验证数据长度
        expected_length = self.HEADER_SIZE + payload_length + 4  # +4 for checksum
        if len(data) != expected_length:
            raise ValueError(
                f"Data length mismatch: {len(data)} != {expected_length}"
            )

        # 验证校验和
        frame = data[: self.HEADER_SIZE + payload_length]
        received_checksum = struct.unpack(">I", data[self.HEADER_SIZE + payload_length :])[0]
        calculated_checksum = zlib.crc32(frame) & 0xFFFFFFFF

        if received_checksum != calculated_checksum:
            raise ValueError(
                f"Checksum mismatch: {received_checksum:08x} != {calculated_checksum:08x}"
            )

        # 提取负载
        payload_data = data[self.HEADER_SIZE : self.HEADER_SIZE + payload_length]

        # 如果压缩，先解压
        if flags & 0x02:
            payload_data = zlib.decompress(payload_data)

        # 反序列化负载
        payload = self._deserialize_payload(payload_data)

        return msg_type, sequence_id, flags, payload

    def _serialize_payload(self, payload: Dict[str, Any]) -> bytes:
        """序列化负载为二进制"""
        if self.encoding == "msgpack":
            return msgpack.packb(payload, use_bin_type=True)
        elif self.encoding == "json":
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            raise ValueError(f"Unknown encoding: {self.encoding}")

    def _deserialize_payload(self, data: bytes) -> Dict[str, Any]:
        """反序列化二进制为负载"""
        if self.encoding == "msgpack":
            return msgpack.unpackb(data, raw=False)
        elif self.encoding == "json":
            return json.loads(data.decode("utf-8"))
        else:
            raise ValueError(f"Unknown encoding: {self.encoding}")

    def get_handshake_payload(self, agent_id: str, capabilities: list = None) -> Dict:
        """生成握手有效载荷"""
        return {
            "sender_id": agent_id,
            "protocol_version": 1,
            "supported_types": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            "capabilities": capabilities or [],
        }

    def validate_message(self, data: bytes) -> bool:
        """验证消息是否有效"""
        try:
            _ = self.decode_message(data)
            return True
        except (ValueError, struct.error, Exception):
            return False


class ProtocolNegotiator:
    """
    协议协商器 - 处理Agent间的协议协商
    """

    def __init__(self):
        self.logger = logging.getLogger("ProtocolNegotiator")
        self.supported_encodings = ["msgpack", "json"]
        self.supported_versions = [1]

    def negotiate_protocol(
        self, local_caps: Dict, remote_caps: Dict
    ) -> Tuple[str, int]:
        """
        协商通信协议

        Args:
            local_caps: 本地支持的能力
            remote_caps: 远程支持的能力

        Returns:
            (编码格式, 协议版本)
        """
        # 选择编码格式
        encoding = "msgpack"  # 默认选择msgpack
        if "json" in remote_caps.get("supported_encodings", []):
            encoding = "json"

        # 选择版本
        version = 1
        remote_versions = remote_caps.get("supported_versions", [1])
        if 1 in remote_versions:
            version = 1

        self.logger.info(f"Negotiated protocol: encoding={encoding}, version={version}")
        return encoding, version
