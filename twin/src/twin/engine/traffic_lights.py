"""Fixed-time traffic lights at intersections (degree >= 3 nodes).

Incoming approaches at each intersection are grouped into 2 phases by bearing
(roughly opposite directions share a phase, e.g. N/S vs E/W), since that's how
real 2-phase signals are laid out. Each phase cycles green -> yellow -> red.

After both car phases comes a pedestrian phase, with every car light red: WALK (step
onto any crosswalk of the junction), then WALK_FLASH (do not start; those already on
the road finish crossing), then DONT_WALK while cars move. People following the signal
are never on a crosswalk while a car has green, so turning cars do not wait for them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx

GREEN_S = 10.0
YELLOW_S = 3.0
WALK_S = 6.0
WALK_FLASH_S = 12.0  # someone stepping off at the last moment clears the 16 m of asphalt at 1.4 m/s

WALK = "walk"
WALK_FLASH = "flash"
DONT_WALK = "dont_walk"


def phase_s() -> float:
    """One car phase: green + yellow."""
    return GREEN_S + YELLOW_S


def cycle_s() -> float:
    return 2 * phase_s() + WALK_S + WALK_FLASH_S


@dataclass
class TrafficLight:
    node_id: int
    # approach edge (u -> this node) -> phase index (0 or 1)
    approach_phase: dict[int, int]
    offset: float = 0.0  # phase offset in seconds, for de-synchronizing adjacent lights
    phase_a_state: str = "green"
    phase_b_state: str = "red"
    walk_state: str = DONT_WALK  # every crosswalk of this junction shares it
    cycle_t: float = 0.0  # position in the cycle, set by tick_lights

    def state_for_approach(self, from_node: int) -> str:
        phase = self.approach_phase.get(from_node)
        if phase is None:
            return "green"  # unknown approach (shouldn't happen), fail open
        return self.phase_a_state if phase == 0 else self.phase_b_state

    def seconds_until_change(self, from_node: int) -> float:
        """Time left in the current state (green, yellow or red) of this approach."""
        t = self.cycle_t
        if self.approach_phase.get(from_node, 0) == 1:
            t = (t - phase_s()) % cycle_s()  # phase B starts when phase A ends
        for end in (GREEN_S, phase_s(), cycle_s()):
            if t < end:
                return end - t
        return 0.0


def _bearing(dx: float, dy: float) -> float:
    return math.atan2(dy, dx) % math.pi  # 0..pi, opposite directions collapse together


def build_traffic_lights(graph: nx.MultiDiGraph) -> dict[int, TrafficLight]:
    """One light per intersection node (in-degree + out-degree implies degree >= 3)."""
    lights: dict[int, TrafficLight] = {}
    node_index = 0
    for node in graph.nodes:
        predecessors = list(graph.predecessors(node))
        if len(predecessors) < 3:
            continue

        nd = graph.nodes[node]
        bearings: list[tuple[int, float]] = []
        for pred in predecessors:
            pd = graph.nodes[pred]
            dx, dy = nd["x"] - pd["x"], nd["y"] - pd["y"]
            bearings.append((pred, _bearing(dx, dy)))

        # cluster into 2 phases: sort by bearing, split at the largest angular gap
        bearings.sort(key=lambda t: t[1])
        n = len(bearings)
        if n < 2:
            continue
        gaps = [
            (bearings[(i + 1) % n][1] - bearings[i][1]) % math.pi for i in range(n)
        ]
        split_at = gaps.index(max(gaps))

        approach_phase = {}
        for i, (pred, _) in enumerate(bearings):
            approach_phase[pred] = 0 if i <= split_at else 1

        lights[node] = TrafficLight(
            node_id=node,
            approach_phase=approach_phase,
            offset=(node_index * 1.7) % cycle_s(),  # de-sync neighboring lights a bit
        )
        node_index += 1

    return lights


def tick_lights(lights: dict[int, TrafficLight], sim_time: float) -> None:
    for light in lights.values():
        t = (sim_time + light.offset) % cycle_s()
        light.cycle_t = t
        # phase A: green, yellow, then phase B: green, yellow, then the pedestrian phase
        if t < GREEN_S:
            light.phase_a_state, light.phase_b_state, light.walk_state = "green", "red", DONT_WALK
        elif t < phase_s():
            light.phase_a_state, light.phase_b_state, light.walk_state = "yellow", "red", DONT_WALK
        elif t < phase_s() + GREEN_S:
            light.phase_a_state, light.phase_b_state, light.walk_state = "red", "green", DONT_WALK
        elif t < 2 * phase_s():
            light.phase_a_state, light.phase_b_state, light.walk_state = "red", "yellow", DONT_WALK
        else:
            walking = t < 2 * phase_s() + WALK_S
            light.phase_a_state, light.phase_b_state = "red", "red"
            light.walk_state = WALK if walking else WALK_FLASH
