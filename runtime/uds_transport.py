from __future__ import annotations

import socket
import struct
from pathlib import Path
from typing import Any

from protocol.messages import parse_protocol_bytes, protocol_bytes

_LENGTH_HEADER = struct.Struct("!I")


def send_message(sock: socket.socket, message: Any) -> None:
    payload = protocol_bytes(message)
    sock.sendall(_LENGTH_HEADER.pack(len(payload)))
    sock.sendall(payload)


def recv_message(sock: socket.socket) -> Any:
    header = _recv_exact(sock, _LENGTH_HEADER.size)
    if not header:
        raise EOFError("socket closed before header")
    (payload_size,) = _LENGTH_HEADER.unpack(header)
    payload = _recv_exact(sock, payload_size)
    if len(payload) != payload_size:
        raise EOFError("socket closed before full payload")
    return parse_protocol_bytes(payload)


def request_response(socket_path: str | Path, message: Any, *, timeout_s: float = 5.0) -> Any:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        sock.connect(str(socket_path))
        send_message(sock, message)
        return recv_message(sock)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)
