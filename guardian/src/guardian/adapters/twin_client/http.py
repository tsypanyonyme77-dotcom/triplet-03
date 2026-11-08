"""REST TwinClient: POST {base_url}/tools/{name}; pull mode polls GET {base_url}/readings?cursor=N."""

from __future__ import annotations

import contextlib
from typing import Any

import httpx

from guardian.adapters.twin_client.base import OnReadings, TwinUnavailable
from guardian.clock import Clock
from guardian.config import TwinCfg


class HttpTwinClient:
    transport = "rest"

    def __init__(self, cfg: TwinCfg, clock: Clock, client: httpx.AsyncClient | None = None) -> None:
        self.cfg, self.clock = cfg, clock
        self.client = client or httpx.AsyncClient(base_url=cfg.base_url, timeout=cfg.timeout_s)
        self.cursor = 0

    async def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = await self.client.post(f"/tools/{name}", json=payload)
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TwinUnavailable(f"twin tool {name} failed: {e}") from e
        if not isinstance(body, dict):
            raise TwinUnavailable(f"twin tool {name} returned a non-object reply")
        return body

    async def health(self) -> bool:
        try:
            r = await self.client.get("/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def poll_once(self, on_readings: OnReadings) -> int:
        r = await self.client.get("/readings", params={"cursor": self.cursor})
        r.raise_for_status()
        body = r.json()
        self.cursor = int(body.get("cursor", self.cursor))
        items = body.get("readings", [])
        if items:
            await on_readings(items)
        return len(items)

    async def run_ingest(self, on_readings: OnReadings) -> None:
        while True:
            # a failing poll is not fatal: liveness turns a silent Twin into stale/unknown verdicts
            with contextlib.suppress(httpx.HTTPError, ValueError):
                await self.poll_once(on_readings)
            await self.clock.sleep(self.cfg.poll_interval_s)

    async def close(self) -> None:
        await self.client.aclose()
