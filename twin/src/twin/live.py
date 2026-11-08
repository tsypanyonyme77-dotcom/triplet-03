"""Live mode: the two-blocks engine runs in real time inside the Twin and streams its frames.

The LiveRunner steps the city every dt (0.1 s) of wall time (times `speed`), puts the
engine's ground-truth timeline into the Twin's event log, and publishes each tick in the
recording frame format to every subscriber of GET /stream/frames (server-sent events). The
emitter keeps signing and pushing readings on its own interval but no longer advances the
city (Emitter(step_city=False)).

The clock is a task on the server's event loop, not a thread: a tick costs well under a
millisecond (3 ms in `busy`), and actuator calls never interleave with a tick. A tick that
raises is logged with its traceback and the clock goes on; after MAX_FAILED_TICKS in a row
the engine stops stepping and reports why (`engine_error` in GET /live/status and /health),
while the HTTP API stays up. A reset or load restarts it.

Controls (POST /live/control): pause, resume, speed, reset (the same scenario from t = 0) and
load (another scenario). A reset or load starts a new run_id; subscribers get a `reset` event
and fetch /live/map again.

A stream starts with `hello` (the status, so a client that reconnects can tell whether it is
still the same run of the same server: `instance` changes when the Twin restarts) and sends
`ping` when nothing else happened for PING_S (paused), so a client can tell a quiet stream
from a dead one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from twin.events import EventLog

MAX_LAG_S = 1.0  # behind wall time by more than this (a slow tick): skip ahead instead of racing
MAX_FAILED_TICKS = 20  # in a row (2 s): the engine is not coming back by itself
PING_S = 5.0

log = logging.getLogger("twin.live")


class LiveRunner:
    def __init__(self, city, events: EventLog, speed: float = 1.0) -> None:
        self.city = city
        self.events = events
        self.speed = speed
        self.paused = False
        self.instance = uuid.uuid4().hex[:8]
        self.engine_error: str | None = None
        self._failed_ticks = 0
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    # ---- the clock ----------------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        dt = self.city.dt
        next_at = loop.time()
        while True:
            if not self.paused and self.engine_error is None:
                async with self._lock:
                    self.tick()
            next_at += dt / max(self.speed, 0.05)
            now = loop.time()
            if now - next_at > MAX_LAG_S:
                next_at = now
            await asyncio.sleep(max(0.0, next_at - now))

    def tick(self) -> None:
        """One engine step, published. Whatever it raises stays here: see the module docstring."""
        try:
            for ev in self.city.step(self.city.dt):
                ev = dict(ev)
                kind = ev.pop("kind")
                self.events.emit(kind, ev.pop("message", kind), **ev)
            self._publish("frame", self.city.frame())
            self._failed_ticks = 0
        except Exception as exc:
            self._tick_failed(exc)

    def _tick_failed(self, exc: Exception) -> None:
        self._failed_ticks += 1
        error = repr(exc)[:300]
        if self._failed_ticks == 1:  # the same failure at 10 Hz would bury the log
            log.exception("live tick failed at sim t = %s", getattr(self.city, "sim_time", "?"))
            self.events.emit("live_tick_error", f"live tick failed: {exc}", error=error)
        if self._failed_ticks >= MAX_FAILED_TICKS:
            self.engine_error = error
            message = (f"engine stopped after {MAX_FAILED_TICKS} failed ticks in a row: {error}. "
                       "The HTTP API stays up; POST /live/control reset restarts it.")
            log.error(message)
            self.events.emit("live_engine_stopped", message, error=error)

    async def control(self, action: str, scenario: str | None = None, seed: int | None = None,
                      speed: float | None = None, params: Any = None) -> dict[str, Any]:
        async with self._lock:
            if action == "pause":
                self.paused = True
            elif action == "resume":
                self.paused = False
            elif action == "speed":
                if speed is None or not 0.1 <= speed <= 8.0:
                    raise ValueError("speed must be between 0.1 and 8")
                self.speed = speed
            elif action in ("reset", "load"):
                self.city.reset(scenario if action == "load" else None, seed, params)
                self.paused = False
                self.engine_error, self._failed_ticks = None, 0
                self.events.emit("live_reset", f"live run {self.city.run_id}: scenario {self.city.scenario_name}",
                                 run_id=self.city.run_id, scenario=self.city.scenario_name, seed=seed)
                self._publish("reset", {"instance": self.instance, "run_id": self.city.run_id,
                                        "scenario": self.city.scenario_name})
            else:
                raise ValueError("action must be pause, resume, speed, reset or load")
        return self.status()

    def status(self) -> dict[str, Any]:
        return {"instance": self.instance, "run_id": self.city.run_id, "scenario": self.city.scenario_name,
                "seed": self.city.seed, "sim_time_s": self.city.sim_time, "paused": self.paused, "speed": self.speed,
                "engine_error": self.engine_error, "scenarios": list(self.city.SCENARIOS),
                "params": self.city.params_dict()}

    # ---- streaming ----------------------------------------------------------------------

    async def stream(self, ping_s: float = PING_S) -> AsyncIterator[str]:
        """The server-sent events of one client: hello, then frames, resets and pings."""
        queue = self.subscribe()
        try:
            yield f"event: hello\ndata: {json.dumps(self.status())}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), ping_s)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            self.unsubscribe(queue)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=600)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _publish(self, event: str, data: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        for queue in list(self._subscribers):
            if queue.full():  # a client that stopped reading: drop its oldest frame
                queue.get_nowait()
            queue.put_nowait(message)
