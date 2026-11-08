"""`python -m mocks.guardian_twin --upstream http://twin:8101 --guardian-config /guardian-config --port 8765`"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx
import uvicorn

from mocks.guardian_twin.bridge import build_app
from mocks.twin.engine import MockTwin


def main() -> None:
    parser = argparse.ArgumentParser(description="The Guardian team's Twin mock, as the Brain's Twin (plain HTTP)")
    parser.add_argument("--upstream", default=os.environ.get("TWIN_MOCK_URL", "http://127.0.0.1:8101"))
    parser.add_argument("--guardian-config", default=os.environ.get("GUARDIAN_CONFIG_DIR", "../guardian/config"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    twin = MockTwin(os.environ.get("TWIN_HMAC_SECRET"), os.environ.get("BRAIN_HMAC_SECRET"))
    uvicorn.run(build_app(httpx.AsyncClient(base_url=args.upstream, timeout=5), twin, Path(args.guardian_config)), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
