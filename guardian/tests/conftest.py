"""Shared fixtures: FakeClock, in-process Guardian app + Twin mock (httpx ASGITransport), signed-reading factory."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from guardian.adapters.twin_client.http import HttpTwinClient
from guardian.clock import FakeClock, iso
from guardian.config import Settings, load_config
from guardian.main import Guardian, create_app
from mocks.brain_mock.brain import BrainMock
from mocks.common.signing import sign_envelope
from mocks.twin_mock.app import create_twin_app
from mocks.twin_mock.sim import Simulator

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
TWIN_KEY, GUARDIAN_KEY = "test-twin-key", "test-guardian-key"
BRAIN_API, TWIN_API, OPS_API = "brain-key", "twin-key", "ops-key"


def make_settings(tmp: Path) -> Settings:
    return Settings(_env_file=None, GUARDIAN_HMAC_KEY=GUARDIAN_KEY, TWIN_HMAC_KEY=TWIN_KEY,  # type: ignore[call-arg]
                    BRAIN_API_KEY=BRAIN_API, TWIN_API_KEY=TWIN_API, OPS_API_KEY=OPS_API,
                    LOG_DIR=str(tmp / "logs"), GUARDIAN_DB_PATH=str(tmp / "guardian.db"))


class Harness:
    """Guardian + Twin mock + Brain mock in one process on a shared FakeClock."""

    def __init__(self, tmp: Path, start: datetime | None = None, seed: int = 7) -> None:
        self.tmp = tmp
        self.clock = FakeClock(start)
        self.settings = make_settings(tmp)
        self.sim = Simulator(self.clock, TWIN_KEY, seed)
        self.twin_app = create_twin_app(self.sim, push=False)
        self.twin_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.twin_app), base_url="http://twin")
        cfg = load_config(CONFIG_DIR, self.settings)
        self.twin_client = HttpTwinClient(cfg.guardian.twin, self.clock, self.twin_http)
        self.app = create_app(str(CONFIG_DIR), settings=self.settings, clock=self.clock, twin=self.twin_client,
                              background=False)
        self.g: Guardian = self.app.state.guardian
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://guardian")
        self.brain = BrainMock(self.client, BRAIN_API)
        self.verdicts: list[dict[str, Any]] = []

    async def push(self, envs: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
        r = await self.client.post("/v1/readings", json=envs, headers={"X-API-Key": TWIN_API})
        assert r.status_code in (200, 422), r.text
        out = [x["verdict"] for x in r.json().get("results", []) if "verdict" in x]
        self.verdicts += out
        return out

    async def step(self) -> list[dict[str, Any]]:
        batch = self.sim.step()
        return await self.push(batch) if batch else []

    async def advance(self, seconds: float, step: float = 5.0) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        t = 0.0
        while t < seconds:
            self.clock.advance(step)
            t += step
            out += await self.step()
            await self.g.tick()
        return out

    def latest(self, sensor_id: str) -> dict[str, Any]:
        return next(v for v in reversed(self.verdicts) if v["reading_ref"]["sensor_id"] == sensor_id)

    def of(self, sensor_id: str, verdicts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return [v for v in (verdicts if verdicts is not None else self.verdicts)
                if v["reading_ref"]["sensor_id"] == sensor_id]

    async def api(self, method: str, path: str, key: str = BRAIN_API, **kw: Any) -> httpx.Response:
        return await self.client.request(method, path, headers={"X-API-Key": key}, **kw)

    def events(self) -> list[dict[str, Any]]:
        return [json.loads(line) for p in sorted((self.tmp / "logs").glob("t5-guardian-*.log"))
                for line in p.read_text().splitlines() if line.strip()]

    async def close(self) -> None:
        await self.g.stop()
        await self.client.aclose()
        await self.twin_http.aclose()


def assert_in_order(events: list[dict[str, Any]], expected: list[Callable[[dict[str, Any]], bool]]) -> None:
    """Each predicate must match an event strictly after the previous match."""
    i = 0
    for n, pred in enumerate(expected):
        while i < len(events) and not pred(events[i]):
            i += 1
        assert i < len(events), f"expected event #{n} not found in order"
        i += 1


def ev(type_: str, kind: str | None = None, **match: Any) -> Callable[[dict[str, Any]], bool]:
    def pred(e: dict[str, Any]) -> bool:
        if e["type"] != type_ or (kind and e["data"].get("kind") != kind):
            return False
        return all((e.get(k) if k in e else e["data"].get(k)) == v for k, v in match.items())
    return pred


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    h = Harness(tmp_path)
    yield h
    await h.close()


@pytest.fixture
async def city(harness: Harness) -> Harness:
    """A harness after two minutes of normal city data, so every sensor has trusted history."""
    await harness.advance(120)
    return harness


@pytest.fixture
def envelope() -> Callable[..., dict[str, Any]]:
    """Signed-reading factory."""

    def make(sensor_id: str = "wl-port-03", sensor_type: str = "water_level", zone_id: str = "zone-07",
             value: dict[str, Any] | None = None, seq: int = 1, ts: datetime | None = None, key: str = TWIN_KEY,
             **extra: Any) -> dict[str, Any]:
        env = {"contract_version": "1.0", "sensor_id": sensor_id, "sensor_type": sensor_type, "zone_id": zone_id,
               "timestamp": iso(ts or FakeClock().now()), "sequence_no": seq,
               "value": value if value is not None else {"level_m": 0.4}, "sequence_reset": False, **extra}
        return sign_envelope(env, key)

    return make
