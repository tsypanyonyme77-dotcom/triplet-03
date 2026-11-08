"""Emergency vehicles: ambulances, police cars and fire trucks.

Each one belongs to a station (app/stations.py) and starts parked in the station's
bay, like a parked car (front bumper at x, y). It is on the map, and recorded, from
the first tick. A call pulls it out of its bay; it drives with the same IDM, bicycle
model and pull-out / pull-in path as cars, and parks back in its bay when it is home.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from twin.engine.idm import IDMParams
from twin.engine.mobil import MOBILParams

UNIT_KINDS = ("ambulance", "police", "fire")


@dataclass
class EmergencyVehicle:
    id: str
    kind: str                         # one of UNIT_KINDS
    station_id: str
    home_spot_id: str                 # its station bay: stays reserved for it, also while it is out
    route_nodes: list[int]            # current route being driven, like Car.route_nodes
    edge_index: int = 0
    dist_on_edge: float = 0.0
    lane: int = 0
    speed: float = 0.0
    heading: float = 0.0
    last_lane_change_time: float = -999.0
    params: IDMParams = field(default_factory=IDMParams)
    mobil: MOBILParams = field(default_factory=MOBILParams)
    finished: bool = True   # True whenever not driving (parked at the station, or at the scene), as for Car
    x: float = 0.0
    y: float = 0.0
    steer: float = 0.0                 # front-wheel angle, rad, + = left (vehicle_dynamics.py)
    accel: float = 0.0                 # m/s^2 over the last tick (brake lights, body pitch)
    # pull-out / pull-in path, as Car (sim._park_shift_at): set when leaving or coming back to the bay
    start_dist: float | None = None
    end_dist: float | None = None
    park_shift_start: float = 0.0
    park_shift_end: float = 0.0

    # idle (parked in its bay) -> dispatched (waiting for a gap to pull out, then driving to
    # the scene) -> cleaning (task "cleanup": pause at the scene, removes the wreck) or
    # on_scene (task "respond") -> [ambulance with a casualty: to_hospital] -> returning
    # (driving back, parks in its bay) -> idle
    status: str = "idle"
    target_car_ids: tuple[str, str] | None = None  # the two crashed cars being cleaned up
    clean_t: float = 0.0                              # seconds spent on the scene so far
    pending_route: list[int] | None = None           # route to the scene, taken once it can pull out
    pending_end: float | None = None                  # ... ending this far along its last edge
    # "cleanup": the old call (dispatch_ambulance): clear the scene after CLEANUP_DURATION_S, drive home.
    # "respond": dispatch_unit: work the scene with the other units (app/incident_response.py).
    task: str | None = None
    incident_id: str | None = None
    siren: bool = False                               # lights and siren on (driving to a scene or a hospital)
    lateral_offset: float = 0.0                       # m right of its lane (negative: left, passing cars pulled over)
    scene_shift: float = 0.0                          # police: its path ends angled this far left (incident_response.py)
    casualty_id: str | None = None                    # ambulance: the casualty aboard

    @property
    def responding(self) -> bool:
        """On its way with the siren on: to a scene, or to the hospital with a casualty."""
        return self.siren and not self.finished and self.status in ("dispatched", "to_hospital")

    @property
    def obeys_signals(self) -> bool:
        return not self.responding

    @property
    def respects_junctions(self) -> bool:
        return not self.responding


# the ambulance-only engine called them Ambulance; kept for readers of older code
Ambulance = EmergencyVehicle
