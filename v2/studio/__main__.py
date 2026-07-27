from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "v2.studio.app:app",
        host=os.getenv("STATEBUS_STUDIO_HOST", "127.0.0.1"),
        port=int(os.getenv("STATEBUS_STUDIO_PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    main()

