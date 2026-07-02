"""
演示使用 NetworkTransport 和 NetworkAgentServer 的 Agent 运行时。 
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.communication.network import NetworkAgentServer, NetworkTransport
from src.core.agent import AgentFactory
from src.core.runtime import AgentRuntime
from src.memory.memory_manager import MemoryManager


async def main():
    host = "127.0.0.1"
    port = 9010

    # 创建 Agent
    planner = AgentFactory.create_agent("planner", agent_id="planner_net")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_net")

    runtime = AgentRuntime()
    runtime.register_agent(planner)
    runtime.register_agent(retriever)

    agent_registry = {
        planner.agent_id: planner,
        retriever.agent_id: retriever,
    }

    server = NetworkAgentServer(host=host, port=port, agent_registry=agent_registry)
    await server.start()

    # 创建网络传输连接
    transport = NetworkTransport(host=host, port=port)
    await transport.connect()

    # 通过网络传输发送一个简单的动作请求
    envelope = {
        "message_id": "msg_net_001",
        "sender_id": planner.agent_id,
        "receiver_id": retriever.agent_id,
        "payload": {"action": "retrieve_documents", "parameters": {"query": "network transport demo"}},
    }

    frame = planner.protocol_handler.encode_message(
        msg_type=4,
        payload=envelope,
        sequence_id=100,
        flags=0,
    )

    response_frame = await transport.send(frame)
    msg_type, seq, flags, decoded = planner.protocol_handler.decode_message(response_frame)

    print("Network transport demo response:")
    print(f"  msg_type={msg_type}, seq={seq}, flags={flags}")
    print(f"  decoded payload keys: {list(decoded.keys())}")
    print(f"  response body: {decoded.get('payload')} ")

    await transport.close()
    await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
