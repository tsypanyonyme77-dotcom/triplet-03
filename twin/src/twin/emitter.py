"""Periodic feed: signs the readings the city offers, keeps them for readers that poll (the City Brain's
GET /readings and list_readings), and pushes them to the Guardian in its contract 1.0 (guardian_push)."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx

from twin.city.base import CitySource
from twin.config import Settings
from twin.devices import DeviceRegistry
from twin.contract import build_reading
from twin.events import EventLog
from twin.partners.brain_timeline import BrainTimeline
from twin.partners.guardian_push import GuardianPush
from twin.partners.reading_log import ReadingLog
from twin.reading_cadence import ReadingCadence
from twin.sensor_model import SensorModel


class Emitter:
    def __init__(self, settings: Settings, city: CitySource, events: EventLog, step_city: bool = True,
                 devices: DeviceRegistry | None = None, log: ReadingLog | None = None,
                 guardian: GuardianPush | None = None, view: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 timeline: BrainTimeline | None = None) -> None:
        """`log`: where readings are kept for readers that poll. `guardian`: the push in the Guardian's
        contract. `view`: applied to each reading before
        it is signed (unit_status as the partner that sent the unit knows it). `timeline`: our events on the
        City Brain's screen."""
        self.timeline = timeline
        self.cadence = ReadingCadence(dict(settings.reading_intervals), settings.emit_interval_s, call_limits=settings.realistic_sensors)
        self.sensors = SensorModel(settings.emit_interval_s, settings.seed) if settings.realistic_sensors else None
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
        self.cadence.next_tick()
        for spec in self.city.sensor_readings():
            sensor_id = spec["sensor_id"]
            if self.sensors is not None:
                spec = self.sensors.apply(spec)   # every tick, reported or not: a sensor measures all the time
            if self.devices.blocks(sensor_id) or not self.cadence.due(spec):
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
            # the City Brain asks the Guardian about every reading it pulls, and one with no verdict costs it the whole
            # verdict deadline and puts it in degraded mode: it is offered only what the Guardian can judge
            if self.guardian is None or self.guardian.judges(reading):
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
        if self.guardian is not None and self.client is not None:
            await self.guardian.push(self.client, readings)
        if self.timeline is not None and self.client is not None:
            await self.timeline.flush(self.client)
        return readings

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=2.0) as client:
            self.client = client
            while True:
                try:
                    await self.tick()
                except Exception as exc:  # keep the feed alive whatever happens in one tick
                    self.events.emit("tick_error", f"emitter tick failed: {exc}", error=repr(exc)[:300])
                await asyncio.sleep(self.settings.emit_interval_s)
