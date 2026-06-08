from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

from protocol.messages import RemoteStepRequest, RemoteStepResponse
from runtime.executor_runtime import execute_playbook_step
from runtime.uds_transport import recv_message, send_message
from statepool.store import MMAP_FILE_STORAGE, StatePool, StatePoolConfig


def serve(
    *,
    socket_path: str | Path,
    max_requests: int | None = None,
    statepool_config: StatePoolConfig | None = None,
) -> int:
    socket_file = Path(socket_path)
    socket_file.parent.mkdir(parents=True, exist_ok=True)
    if socket_file.exists():
        socket_file.unlink()
    active_config = statepool_config or StatePoolConfig.from_env()
    handled = 0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_file))
        server.listen(8)
        try:
            while max_requests is None or handled < max_requests:
                conn, _addr = server.accept()
                with conn:
                    message = recv_message(conn)
                    if not isinstance(message, RemoteStepRequest):
                        raise TypeError(
                            f"remote executor expected RemoteStepRequest, got {type(message).__name__}"
                        )
                    statepool = StatePool(message.state_root, config=active_config)
                    result = execute_playbook_step(
                        task_id=message.task_id,
                        task_theme=message.task_theme,
                        step=message.step,
                        statepool=statepool,
                        input_state_refs=message.input_state_refs,
                        output_storage=MMAP_FILE_STORAGE,
                        transfer_strategy=str(message.step.params.get("transfer_strategy", "state_ref")),
                    )
                    send_message(conn, RemoteStepResponse(result=result))
                    handled += 1
        finally:
            try:
                socket_file.unlink()
            except FileNotFoundError:
                pass
    return handled


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a remote StateBus executor over UDS.")
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--statepool-backend", default=None)
    parser.add_argument("--embed-state-backend", default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.statepool_backend is not None:
        os.environ["STATEBUS_STATEPOOL_BACKEND"] = str(args.statepool_backend)
    if args.embed_state_backend is not None:
        os.environ["STATEBUS_EMBED_STATE_BACKEND"] = str(args.embed_state_backend)
    config = StatePoolConfig.from_env(
        default_backend=args.statepool_backend,
        embedding_backend=args.embed_state_backend,
    )
    serve(
        socket_path=args.socket_path,
        max_requests=args.max_requests,
        statepool_config=config,
    )


if __name__ == "__main__":
    main()
