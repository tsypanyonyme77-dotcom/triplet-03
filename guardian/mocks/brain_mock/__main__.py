"""CLI: `python -m mocks.brain_mock` serves the Brain mock on BRAIN_PORT (default 8102)."""

from __future__ import annotations

import os

import uvicorn

from mocks.brain_mock.app import create_brain_app

if __name__ == "__main__":
    uvicorn.run(create_brain_app(), host="0.0.0.0", port=int(os.environ.get("BRAIN_PORT", "8102")))
