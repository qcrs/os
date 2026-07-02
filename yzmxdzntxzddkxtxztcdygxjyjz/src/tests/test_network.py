import asyncio

from src.communication.network import NetworkAgentServer, NetworkTransport
from src.core.agent import AgentFactory


async def run_network_test():
    planner = AgentFactory.create_agent("planner", agent_id="planner_net")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_net")

    agent_registry = {
        planner.agent_id: planner,
        retriever.agent_id: retriever,
    }

    server = NetworkAgentServer(host="127.0.0.1", port=9009, agent_registry=agent_registry)
    await server.start()

    transport = NetworkTransport(host="127.0.0.1", port=9009)
    await transport.connect()

    envelope = {
        "message_id": "msg_net_test",
        "sender_id": planner.agent_id,
        "receiver_id": retriever.agent_id,
        "payload": {"action": "retrieve_documents", "parameters": {"query": "network test"}},
    }

    frame = planner.protocol_handler.encode_message(
        msg_type=4,
        payload=envelope,
        sequence_id=1,
        flags=0,
    )

    response_frame = await transport.send(frame)
    assert planner.protocol_handler.validate_message(response_frame)

    await transport.close()
    await server.stop()


def test_network_transport():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_network_test())
    loop.close()
