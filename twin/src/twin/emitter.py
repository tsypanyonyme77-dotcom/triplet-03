"""Periodic feed: signs the readings the city offers, keeps them for readers that poll (the City Brain's
GET /readings and list_readings), and pushes them to the Guardian, in its contract 1.0 (guardian_push)
or, for the mock Guardian, as our own envelopes. The mock City Brain can be notified after each batch
(no data); the real one polls."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx

from twin.city.base import CitySource
from twin.config import Settings
from twin.devices import DeviceRegistry
from twin.contract import CONTRACT_VERSION, build_reading, now_iso
from twin.events import EventLog
from twin.partners.guardian_push import GuardianPush
from twin.partners.reading_log import ReadingLog


class Emitter:
    def __init__(self, settings: Settings, city: CitySource, events: EventLog, step_city: bool = True,
                 devices: DeviceRegistry | None = None, log: ReadingLog | None = None,
                 guardian: GuardianPush | None = None, view: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> None:
        """`log`: where readings are kept for readers that poll. `guardian`: the push in the Guardian's
        contract (else our own envelopes go to guardian_ingest_url). `view`: applied to each reading before
        it is signed (unit_status as the partner that sent the unit knows it)."""
        self.settings = settings
        self.step_city = step_city  # False in live mode: the LiveRunner advances the city
        self.city = city
        self.events = events
        self.devices = devices or DeviceRegistry()
        self.log = log if log is not None else ReadingLog()
        self.guardian = guardian
        self.view = view or (lambda reading: reading)
        self.client: httpx.AsyncClient | None = None
        self.latest: dict[str, dict[str, Any]] = {}  # the newest reading by sensor_id
        self._seq: dict[str, int] = {}
        self._announced: set[tuple] = set()   # smoke readings already put on the timeline: (run, sensor, smoke)
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def build_readings(self) -> list[dict[str, Any]]:
        readings = []
        for spec in self.city.sensor_readings():
            sensor_id = spec["sensor_id"]
            if self.devices.blocks(sensor_id):
                continue
            spec = self.view(spec)
            self._seq[sensor_id] = self._seq.get(sensor_id, 0) + 1
            readings.append(build_reading(
                sensor_id=sensor_id, sensor_type=spec["type"], zone_id=spec["zone_id"], sequence_no=self._seq[sensor_id],
                value=spec["value"], key=self.settings.hmac_key, department=spec.get("department")))
        return readings

    async def tick(self) -> list[dict[str, Any]]:
        for ev in (self.city.step(self.settings.emit_interval_s) if self.step_city else []):
            ev = dict(ev)
            kind = ev.pop("kind")  # not passed twice to emit (it raised TypeError before)
            self.events.emit(kind, ev.pop("message", kind), **ev)
        readings = self.build_readings()
        for reading in readings:
            self.latest[reading["sensor_id"]] = reading
            self.log.append(reading)
            if reading["type"] == "emergency_call":
                v = reading["value"]
                self.events.emit("emergency_call_reading", f"emergency call {v['call_id']} ({v['category']}) -> {v['incident_id']}",
                                 sensor_id=reading["sensor_id"], sequence_no=reading["sequence_no"], zone_id=reading["zone_id"], **v)
            if reading["type"] == "building_fire":
                v = reading["value"]
                key = (v.get("run_id"), reading["sensor_id"], v["smoke_detected"])
                if key not in self._announced:   # the first reading of each kind: the sensor sends one per tick
                    self._announced.add(key)
                    state = f"smoke detected, {v['temp_c']} C, CO2 {v['co2_ppm']} ppm" if v["smoke_detected"] else "smoke gone"
                    self.events.emit("building_fire_reading", f"{reading['sensor_id']}: {state} -> {v['incident_id']}",
                                     sensor_id=reading["sensor_id"], sequence_no=reading["sequence_no"], zone_id=reading["zone_id"], **v)
            for queue in list(self._subscribers):
                if not queue.full():
                    queue.put_nowait(reading)
        if self.guardian is not None:
            if self.client is not None:
                await self.guardian.push(self.client, readings)
        else:
            await self._push_to_guardian(readings)
        await self._notify_brain(len(readings))
        return readings

    async def _push_to_guardian(self, readings: list[dict[str, Any]]) -> None:
        url = self.settings.guardian_ingest_url
        if not url or self.client is None or not readings:
            return
        results = await asyncio.gather(*(self.client.post(url, json=r) for r in readings), return_exceptions=True)
        failed = [r for r in results if isinstance(r, Exception) or r.status_code >= 400]
        seq = readings[0]["sequence_no"]
        if failed:
            self.events.emit("delivery_failed", f"guardian delivery failed for {len(failed)}/{len(readings)} readings", target="guardian",
                             sequence_no=seq, first_error=str(failed[0])[:200])
        else:
            self.events.emit("reading_emitted", f"feed sent to Guardian: {len(readings)} readings (seq {seq})",
                             target="guardian", sequence_no=seq, count=len(readings))

    async def _notify_brain(self, count: int) -> None:
        url = self.settings.brain_notify_url
        if not url or self.client is None:
            return
        body = {"contract_version": CONTRACT_VERSION, "event": "readings_available",
                "timestamp": now_iso(), "readings": count}  # deliberately no data
        try:
            resp = await self.client.post(url, json=body)
            resp.raise_for_status()
            self.events.emit("brain_notified", "notified City Brain that new readings are available", target="city_brain")
        except httpx.HTTPError as exc:
            self.events.emit("delivery_failed", "city brain notification failed", target="city_brain", error=str(exc)[:200])

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=2.0) as client:
            self.client = client
            while True:
                try:
                    await self.tick()
                except Exception as exc:  # keep the feed alive whatever happens in one tick
                    self.events.emit("tick_error", f"emitter tick failed: {exc}", error=repr(exc)[:300])
                await asyncio.sleep(self.settings.emit_interval_s)
