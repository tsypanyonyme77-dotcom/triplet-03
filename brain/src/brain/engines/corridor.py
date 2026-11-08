"""An emergency corridor: the quickest way for a unit to reach an incident, and the signals to hold green along it.

The shortest path is not always the quickest: a congested zone can cost more than a detour. Each zone costs `hop_s` seconds to cross,
more when its latest trusted camera reading says it is congested. Dijkstra finds the quickest path; each signal controller in a zone on
that path is asked to hold green until the unit has passed (arrival time plus a margin, at most 3600 s). It only proposes `set_signal_phase`
calls: the gate checks them like any other, and a signal still held by an earlier corridor is not driven again inside its hold.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from brain.engines import Certificate, inputs_hash

HOP_S = 60.0       # seconds to cross an empty zone
CONGESTION_K = 2.0  # a fully congested zone takes (1 + K) times as long
MARGIN_S = 30
MAX_HOLD_S = 3600


@dataclass(frozen=True)
class SignalHold:
    intersection_id: str
    zone_id: str
    duration_s: int
    phase: str = "green"


@dataclass
class Corridor:
    path: list[str]
    eta_s: float
    plain_eta_s: float
    signals: list[SignalHold] = field(default_factory=list)
    certificate: Certificate | None = None

    @property
    def gain_s(self) -> float:
        return round(self.plain_eta_s - self.eta_s, 1)


def _cost(zone: str, congestion: dict[str, float], hop_s: float) -> float:
    return hop_s * (1 + CONGESTION_K * min(max(congestion.get(zone, 0.0), 0.0), 1.0))


def corridor(store: Any, origin: str, dest: str, *, congestion: dict[str, float], can_signal: bool = True, held_until: dict[str, float] | None = None,
             now_s: float = 0.0, hop_s: float = HOP_S) -> Corridor | None:
    """The quickest path from `origin` to `dest`, or None when the zones are not connected. `held_until` maps a signal to when its last hold ends."""
    started = time.perf_counter()
    graph = store.zones
    if origin not in graph or dest not in graph:
        return None
    best: dict[str, float] = {origin: 0.0}
    came: dict[str, str] = {}
    queue = [(0.0, origin)]
    while queue:
        spent, zone = heapq.heappop(queue)
        if spent > best.get(zone, math.inf):
            continue
        if zone == dest:
            break
        for nxt in sorted(graph.neighbors(zone)):
            total = spent + _cost(nxt, congestion, hop_s)
            if total < best.get(nxt, math.inf):
                best[nxt], came[nxt] = total, zone
                heapq.heappush(queue, (total, nxt))
    if dest not in best:
        return None
    path = [dest]
    while path[-1] != origin:
        path.append(came[path[-1]])
    path.reverse()

    def eta(zones: list[str]) -> float:
        return sum(_cost(z, congestion, hop_s) for z in zones[1:])

    plain = min(nx.all_shortest_paths(graph, origin, dest))  # the fewest hops; of equals, the first by name
    signals: list[SignalHold] = []
    if can_signal:
        arrival = {zone: eta(path[: i + 1]) for i, zone in enumerate(path)}
        for facility in sorted(store.facilities("signal_controller"), key=lambda f: (arrival.get(f["zone_id"], 0.0), f["id"])):
            if facility["zone_id"] not in arrival or facility.get("quarantined"):
                continue
            hold = min(MAX_HOLD_S, math.ceil(arrival[facility["zone_id"]] + MARGIN_S))
            if (held_until or {}).get(facility["actuator_id"], 0.0) > now_s:
                continue  # an earlier corridor still holds it
            signals.append(SignalHold(facility["actuator_id"], facility["zone_id"], max(hold, 1)))
    chosen = eta(path)
    return Corridor(path, round(chosen, 1), round(eta(plain), 1), signals, Certificate(
        engine="corridor", status="optimal", objective=round(chosen, 1), bound=round(chosen, 1), gap=0.0,
        inputs_hash=inputs_hash({"p": path, "c": sorted(congestion.items()), "o": origin, "d": dest}), elapsed_ms=round((time.perf_counter() - started) * 1000, 3)))
