"""Run the mock Guardian: `python -m mocks.guardian --port 8766`."""

from __future__ import annotations

import argparse
import os

import uvicorn

from mocks.guardian.engine import MockGuardian
from mocks.guardian.server import build_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Guardian (REST)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    app = build_app(MockGuardian(os.environ.get("TWIN_HMAC_SECRET")))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
