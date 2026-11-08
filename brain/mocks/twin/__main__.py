"""Run the mock Twin: `python -m mocks.twin --port 8765` (MCP endpoint at /mcp)."""

from __future__ import annotations

import argparse
import asyncio
import os

from mocks.twin.engine import MockTwin
from mocks.twin.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Twin (MCP, Streamable HTTP)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--http", action="store_true", help="serve plain HTTP (GET /readings, POST /actuators/{action}) instead of MCP")
    args = parser.parse_args()

    twin = MockTwin(os.environ.get("TWIN_HMAC_SECRET"), os.environ.get("BRAIN_HMAC_SECRET"))
    if args.http:
        import uvicorn

        from mocks.twin.http_server import build_app

        uvicorn.run(build_app(twin), host=args.host, port=args.port, log_level="warning")
        return
    asyncio.run(build_server(twin).run_streamable_http_async(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
