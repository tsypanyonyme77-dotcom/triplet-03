"""CLI: `python -m mocks.twin_mock serve` or `python -m mocks.twin_mock inject fake_flood sensor_id=wl-port-03`."""

from __future__ import annotations

import json
import os
import sys

import httpx


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "serve":
        import uvicorn

        from mocks.twin_mock.app import create_twin_app

        uvicorn.run(create_twin_app(), host="0.0.0.0", port=int(os.environ.get("TWIN_PORT", "8101")))
        return 0
    if argv[0] == "inject" and len(argv) >= 2:
        params: dict[str, object] = {}
        for kv in argv[2:]:
            k, _, v = kv.partition("=")
            try:
                params[k] = json.loads(v)
            except ValueError:
                params[k] = v
        url = os.environ.get("TWIN_URL", "http://localhost:8101")
        r = httpx.post(f"{url}/inject/{argv[1]}", json=params, timeout=5)
        print(r.status_code, r.text)
        return 0 if r.status_code == 200 else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
