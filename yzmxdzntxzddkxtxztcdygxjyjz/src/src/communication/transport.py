"""
Transport abstraction for frame-based Agent communication.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional


class Transport(ABC):
    """抽象传输层接口。"""

    @abstractmethod
    async def send(self, frame: bytes) -> bytes:
        """发送一个二进制帧并返回响应帧。"""
        raise NotImplementedError

    async def close(self) -> None:
        """关闭传输连接。"""
        return None


class LocalTransport(Transport):
    """本地进程内传输实现，直接调用远端 Agent 的 receive_frame。"""

    def __init__(self, source_agent: Any, target_agent: Any):
        self.source_agent = source_agent
        self.target_agent = target_agent
        self._closed = False

    async def send(self, frame: bytes) -> bytes:
        if self._closed:
            raise RuntimeError("LocalTransport is closed")

        if not hasattr(self.target_agent, "receive_frame"):
            raise RuntimeError("Target agent does not support receive_frame")

        return await self.target_agent.receive_frame(frame)

    async def close(self) -> None:
        self._closed = True


class NetworkTransport(Transport):
    """基于 TCP 的网络传输实现。"""

    def __init__(self, host: str, port: int, *, reconnect: bool = False):
        self.host = host
        self.port = port
        self.reconnect = reconnect
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def connect(self) -> None:
        if self._closed:
            raise RuntimeError("NetworkTransport is closed")

        if self.reader is not None and self.writer is not None:
            return

        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def send(self, frame: bytes) -> bytes:
        async with self._lock:
            if self._closed:
                raise RuntimeError("NetworkTransport is closed")

            if self.reader is None or self.writer is None:
                await self.connect()

            length = len(frame)
            self.writer.write(length.to_bytes(4, byteorder="big") + frame)
            await self.writer.drain()

            # 读取响应长度和响应数据
            length_bytes = await self.reader.readexactly(4)
            resp_length = int.from_bytes(length_bytes, byteorder="big")
            response = await self.reader.readexactly(resp_length)
            return response

    async def close(self) -> None:
        self._closed = True
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()
            self.reader = None
            self.writer = None
