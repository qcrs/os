import asyncio

from src.communication.transport import LocalTransport
from src.core.agent import AgentFactory
from src.core.message import MessageBuilder


async def test_local_transport_send_receive():
    planner = AgentFactory.create_agent("planner", agent_id="planner_test")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_test")

    planner.connect_to_agent(retriever)

    envelope = {
        "message_id": "msg_test",
        "sender_id": planner.agent_id,
        "receiver_id": retriever.agent_id,
        "payload": {"action": "retrieve_documents", "parameters": {"query": "test"}},
    }

    frame = planner.protocol_handler.encode_message(
        msg_type=MessageBuilder.create_action_request(
            sender_id=planner.agent_id,
            receiver_id=retriever.agent_id,
            action="retrieve_documents",
            parameters={"query": "test"},
        ).msg_type,
        payload=envelope,
        sequence_id=1,
        flags=0,
    )

    transport = planner.transports[retriever.agent_id]
    assert isinstance(transport, LocalTransport)
    response_frame = await transport.send(frame)
    assert planner.protocol_handler.validate_message(response_frame)

    msg_type, seq, flags, decoded = planner.protocol_handler.decode_message(response_frame)
    assert decoded["payload"]["status"] in {"success", "failure"} if "status" in decoded["payload"] else True


def test_local_transport_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(test_local_transport_send_receive())
    loop.close()
