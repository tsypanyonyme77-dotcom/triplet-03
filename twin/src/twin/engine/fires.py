"""Building fires: they start, grow, spread to the buildings next to them, and go out.

A fire is a plain record like an accident (`Simulation.accidents`), so witnesses, the call
centre and the response code can treat both as "something open that people can see":

    id, kind = "building_fire", building_id, x, y (the building's `front`, where people see it
    from), t (when it started), cause, source_fire_id (the fire it spread from), cleared_t
    (when it was put out, None while it burns), incident_id (the call centre's, set once the
    city notices it)

Three things start one: an operator (`ignite`), a building drawn as fire-prone by `arm` (it
catches fire once, at a random time inside a window), and spread. A fire grows from 0 to 1 over
RAMP_S. A building that has burnt for SPREAD_DELAY_S may set each neighbour alight, with
SPREAD_PROB, every SPREAD_EVERY_S while it burns. Spread stays inside a block: buildings across
a street are 24 m apart and do not catch from each other.

The model owns its own random generator, seeded apart from the traffic, so arming it never
changes what the cars and pedestrians of a seed do.
"""
from __future__ import annotations

import random

from twin.engine.buildings import Building, adjacency

RAMP_S = 30.0               # a fire reaches full strength this long after it starts
SPREAD_DELAY_S = 40.0       # a fire this old can start setting its neighbours alight ...
SPREAD_EVERY_S = 15.0       # ... and tries again this often
SPREAD_PROB = 0.5           # chance per neighbour per try
PRONE_WINDOW_S = (20.0, 150.0)   # a fire-prone building ignites at a random moment in here
SMOKE_AT = 0.1              # a building's smoke sensor trips at this strength (3 s after it starts)
VISIBLE_AT = 0.2            # people on the street notice the flames at this strength (6 s)
SMOKE_VISIBLE_M = 60.0      # a camera sees the smoke column of a fire this close


class FireModel:
    def __init__(self, buildings: dict[str, Building], seed: int = 1) -> None:
        self.buildings = buildings
        self.next_to = adjacency(list(buildings.values()))
        self.rng = random.Random(seed)
        self.fires: list[dict] = []
        self._planned: dict[str, float] = {}      # building id -> when it catches fire by itself
        self._next_spread: dict[str, float] = {}  # fire id -> when it next tries to spread

    def arm(self, risk: float, window: tuple[float, float] = PRONE_WINDOW_S) -> list[str]:
        """Each building is fire-prone with probability `risk`, and then ignites once, at a random
        moment inside `window` (seconds of simulated time). Returns the fire-prone buildings."""
        for bid in sorted(self.buildings):
            if risk and self.rng.random() < risk:
                self._planned[bid] = self.rng.uniform(*window)
        return sorted(self._planned)

    # ---- state -----------------------------------------------------------------------

    def open(self) -> list[dict]:
        return [f for f in self.fires if f["cleared_t"] is None]

    def get(self, fire_id: str | None) -> dict | None:
        return next((f for f in self.fires if f["id"] == fire_id), None)

    def burning(self, building_id: str) -> dict | None:
        return next((f for f in self.open() if f["building_id"] == building_id), None)

    @staticmethod
    def intensity(fire: dict, t: float) -> float:
        """0 when it starts, 1 from RAMP_S on; 0 once put out."""
        if fire["cleared_t"] is not None:
            return 0.0
        return max(0.0, min(1.0, (t - fire["t"]) / RAMP_S))

    @staticmethod
    def sensor_values(intensity: float) -> dict:
        """What a smoke and heat sensor inside a building with this fire reads: smoke, temperature
        (20 C to 400 C) and CO2 (420 ppm, the open-air level, up to 5000 ppm)."""
        return {"smoke_detected": intensity >= SMOKE_AT, "temp_c": round(20.0 + 380.0 * intensity, 1),
                "co2_ppm": round(420.0 + 4580.0 * intensity)}

    def cluster(self, fire_id: str) -> list[dict]:
        """The open fires joined to this one through neighbouring burning buildings (itself first)."""
        start = self.get(fire_id)
        if start is None or start["cleared_t"] is not None:
            return []
        seen, queue = {start["building_id"]}, [start]
        for fire in queue:
            for other in self.next_to[fire["building_id"]]:
                nxt = self.burning(other)
                if nxt is not None and other not in seen:
                    seen.add(other)
                    queue.append(nxt)
        return queue

    # ---- changes ---------------------------------------------------------------------

    def ignite(self, building_id: str, t: float, cause: str, source_fire_id: str | None = None) -> dict | None:
        """Sets a building alight. None if there is no such building or it is already burning."""
        building = self.buildings.get(building_id)
        if building is None or self.burning(building_id) is not None:
            return None
        fire = {"id": f"fire-{len(self.fires) + 1:04d}", "kind": "building_fire", "building_id": building_id,
                "x": building.front[0], "y": building.front[1], "t": round(t, 2), "cause": cause,
                "source_fire_id": source_fire_id, "cleared_t": None, "incident_id": None}
        self.fires.append(fire)
        self._next_spread[fire["id"]] = t + SPREAD_DELAY_S
        return fire

    def extinguish(self, fire_id: str, t: float) -> bool:
        fire = self.get(fire_id)
        if fire is None or fire["cleared_t"] is not None:
            return False
        fire["cleared_t"] = round(t, 2)
        return True

    def tick(self, t: float) -> list[dict]:
        """Starts the fires that are due and spreads the old ones. Returns the new fires."""
        started = []
        for bid in sorted(self._planned):
            if t >= self._planned[bid]:
                del self._planned[bid]
                fire = self.ignite(bid, t, "random")
                if fire:
                    started.append(fire)
        for fire in self.open():
            if fire["id"] not in self._next_spread or t < self._next_spread[fire["id"]]:
                continue
            self._next_spread[fire["id"]] = t + SPREAD_EVERY_S
            for other in self.next_to[fire["building_id"]]:
                if self.burning(other) is None and self.rng.random() < SPREAD_PROB:
                    new = self.ignite(other, t, "spread", fire["id"])
                    if new:
                        started.append(new)
        return started
