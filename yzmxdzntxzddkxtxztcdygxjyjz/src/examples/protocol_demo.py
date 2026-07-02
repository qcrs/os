"""
协议演示：展示 ProtocolHandler 的编码/解码和校验流程
"""
from src.core.protocol import ProtocolHandler
from src.core.message import MessageType


def main():
    ph = ProtocolHandler(encoding="msgpack", compression=True)

    payload = {
        "action": "test",
        "content": "这是一个测试消息，用于验证协议的编码与校验。",
        "value": 12345,
    }

    frame = ph.encode_message(msg_type=MessageType.ACTION_REQUEST.value, payload=payload, sequence_id=42)
    print(f"Encoded frame length: {len(frame)} bytes")

    # 验证并解码
    valid = ph.validate_message(frame)
    print(f"Frame valid: {valid}")

    msg_type, seq, flags, decoded = ph.decode_message(frame)
    print(f"Decoded msg_type={msg_type} seq={seq} flags={flags} payload_keys={list(decoded.keys())}")


if __name__ == '__main__':
    main()
