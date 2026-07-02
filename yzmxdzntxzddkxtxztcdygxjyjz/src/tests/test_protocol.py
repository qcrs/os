import pytest

from src.core.protocol import ProtocolHandler
from src.core.message import MessageType


def test_encode_decode_roundtrip():
    ph = ProtocolHandler(encoding="msgpack", compression=False)
    payload = {"k": "v", "n": 1}
    frame = ph.encode_message(msg_type=MessageType.CAPABILITY_QUERY.value, payload=payload, sequence_id=7)

    assert ph.validate_message(frame) is True

    msg_type, seq, flags, decoded = ph.decode_message(frame)
    assert msg_type == MessageType.CAPABILITY_QUERY.value
    assert seq == 7
    assert isinstance(flags, int)
    assert decoded["k"] == "v"


def test_compression_flag_and_checksum():
    ph = ProtocolHandler(encoding="msgpack", compression=True)

    # 生成大载荷以触发压缩
    payload = {"text": "x" * 5000}
    frame = ph.encode_message(msg_type=MessageType.ACTION_REQUEST.value, payload=payload, sequence_id=9)

    # 校验通过
    assert ph.validate_message(frame)

    # 解码后应能恢复原始字段
    msg_type, seq, flags, decoded = ph.decode_message(frame)
    assert msg_type == MessageType.ACTION_REQUEST.value
    assert seq == 9
    assert isinstance(flags, int)
    assert decoded.get("text", "")[:10] == "xxxxxxxxxx"
