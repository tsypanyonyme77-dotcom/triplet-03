from __future__ import annotations

from dataclasses import dataclass, field

from twin.engine.idm import IDMParams
from twin.engine.mobil import MOBILParams


@dataclass
class Car:
    id: str
    route_nodes: list[int]          # sequence of OSM node ids, A -> B
    edge_index: int = 0               # which edge of route_nodes we're currently on
    dist_on_edge: float = 0.0          # meters traveled along current edge
    lane: int = 0                        # 0-indexed lane on the current edge (0 = rightmost)
    speed: float = 0.0                    # m/s
    heading: float = 0.0                    # radians, for sprite rotation
    last_lane_change_time: float = -999.0    # sim time of last lane change, for cooldown
    params: IDMParams = field(default_factory=IDMParams)
    mobil: MOBILParams = field(default_factory=MOBILParams)
    yield_to_pedestrians: bool = True  # brake for people on crosswalks ahead (off only in tests)
    respects_junctions: bool = True  # waits for a free junction box; False: a reckless driver who does not (scenarios only)
    obeys_signals: bool = True         # stop for red / yellow lights (off: a red-light runner, scenarios only)
    slows_for_turns: bool = True       # brake to a comfortable turning speed (off: a reckless driver, scenarios only)
    ignores_flood: bool = False        # drives into a flooded street (a reckless driver, scenarios only; flood_response.py)
    stalled: bool = False              # stalled in deep water: status "crashed", but no collision
    through_flood: bool = False        # caught with no other way when its street flooded: drives on through it
    finished: bool = False
    x: float = 0.0
    y: float = 0.0
    steer: float = 0.0                 # front-wheel angle, rad, + = left (vehicle_dynamics.py)
    accel: float = 0.0                 # m/s^2 over the last tick (brake lights, body pitch)

    # parking state machine: driving -> parking (short pull-in maneuver) -> parked
    # -> (dwell) -> driving again, looping to a new random place forever
    # "crashed" is a terminal state: the car stops dead and blocks its lane until
    # something else (an operator, or a future ambulance actuator) removes it.
    status: str = "driving"  # "driving" | "parking" | "parked" | "unparked" | "crashed"
    parking_spot_id: str | None = None
    parking_t: float = 0.0       # 0..1 progress of the pull-in maneuver
    parking_from_xy: tuple[float, float] = (0.0, 0.0)
    parking_from_heading: float = 0.0
    parking_to_xy: tuple[float, float] = (0.0, 0.0)
    parking_to_heading: float = 0.0
    depart_at: float | None = None  # sim time to leave again, set once parked/unparked
    # trips run from parking spot to parking spot (sim._start_trip):
    pending_spot_id: str | None = None   # reserved destination, waiting for a gap to pull out
    leaving_spot_id: str | None = None   # the spot being pulled out of, freed once clear of it
    start_dist: float | None = None      # front bumper on the first edge when the trip started
    end_dist: float | None = None        # front bumper on the last edge when parked at the destination
    park_shift_start: float = 0.0        # m to the right of the lane: parking lane at the start
    park_shift_end: float = 0.0          # ... and at the end of the trip
    loop: bool = False               # if True, re-route to a new random place after dwelling instead of stopping
    yielding: bool = False           # pulling over and stopping for a siren behind it (incident_response.py)
    lateral_offset: float = 0.0      # m to the right of its lane while pulling over

    # LLM agent: persona shapes which place the car chooses each time it needs a new destination
    persona: str | None = None
    current_place_name: str | None = None   # human-readable name of where the car currently is
    awaiting_decision: bool = False           # True while a background agent call is in flight
    last_reason: str | None = None             # the LLM's stated reason for its most recent choice
