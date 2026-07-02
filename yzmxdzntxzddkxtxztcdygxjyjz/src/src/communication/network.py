"""
Network transport and server for binary frame delivery between Agents.
"""

import asyncio
import logging
from typing import Dict, Optional

from ..core.protocol import ProtocolHandler


class NetworkAgentServer:
    """简单 TCP 服务器，用于接收二进制帧并转发到本地 Agent。"""

    def __init__(self, host: str, port: int, agent_registry: Dict[str, object]):
        self.host = host
        self.port = port
        self.agent_registry = agent_registry
        self.server: Optional[asyncio.AbstractServer] = None
        self.protocol_handler = ProtocolHandler()
        self.logger = logging.getLogger("NetworkAgentServer")

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        self.logger.info(f"NetworkAgentServer started on {self.host}:{self.port}")

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.logger.info("NetworkAgentServer stopped")

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                length_bytes = await reader.readexactly(4)
                frame_length = int.from_bytes(length_bytes, byteorder="big")
                frame = await reader.readexactly(frame_length)

                try:
                    msg_type, seq, flags, envelope = self.protocol_handler.decode_message(frame)
                    receiver_id = envelope.get("receiver_id")
                    target_agent = self.agent_registry.get(receiver_id)
                    if target_agent is None:
                        raise ValueError(f"Agent {receiver_id} not registered")

                    response_frame = await target_agent.receive_frame(frame)
                except Exception as e:
                    self.logger.error(f"Error processing frame: {e}")
                    err_payload = {"error": str(e)}
                    response_frame = self.protocol_handler.encode_message(msg_type=0x0B, payload=err_payload)

                writer.write(len(response_frame).to_bytes(4, byteorder="big") + response_frame)
                await writer.drain()
        except asyncio.IncompleteReadError:
            self.logger.info("Network client disconnected")
        finally:
            writer.close()
            await writer.wait_closed()


class NetworkTransport:
    """基于 TCP 的网络传输实现。"""

    def __init__(self, host: str, port: int, *, reconnect: bool = False):
        self.host = host
        self.port = port
        self.reconnect = reconnect
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._closed = False
        self.logger = logging.getLogger("NetworkTransport")

    async def connect(self) -> None:
        if self._closed:
            raise RuntimeError("NetworkTransport is closed")

        if self.reader is not None and self.writer is not None:
            return

        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.logger.info(f"Connected to network transport {self.host}:{self.port}")

    async def send(self, frame: bytes) -> bytes:
        async with self._lock:
            if self._closed:
                raise RuntimeError("NetworkTransport is closed")

            if self.reader is None or self.writer is None:
                await self.connect()

            self.writer.write(len(frame).to_bytes(4, byteorder="big") + frame)
            await self.writer.drain()

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
