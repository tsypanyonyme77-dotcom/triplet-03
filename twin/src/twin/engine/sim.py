"""Simulation core: tick loop, routing, car-following (IDM) + lane-changing (MOBIL)
over a real, multi-lane road graph.
"""
from __future__ import annotations

import math
import random
import uuid

import networkx as nx

from twin.engine.accidents import MIN_IMPACT_SPEED_MS, car_hits_pedestrian
from twin.engine.buildings import Building
from twin.engine import cameras as cams
from twin.engine import witnesses as wit
from twin.engine.car_collisions import body_corners, overlap_depth
from twin.engine.emergency_calls import CallCentre
from twin.engine.fire_hazard import walk_weight
from twin.engine.fire_response import FireResponse
from twin.engine.fires import FireModel
from twin.engine.incident_response import SIREN_ACCEL_MS2, SIREN_V0_MS, POLICE_ANGLE_SHIFT_M, IncidentResponse
from twin.engine.agents import random_persona
from twin.engine.crashes import should_crash
from twin.engine.emergency_driving import EmergencyDriving
from twin.engine.emergency_units import EmergencyVehicle
from twin.engine.flood import RainProfile
from twin.engine.flood_response import FloodResponse
from twin.engine.crossing_rules import may_cross, pedestrian_in_path
from twin.engine import vehicle_dynamics as vd
from twin.engine.idm import idm_acceleration
from twin.engine.junctions import SAMPLES as JUNCTION_SAMPLES, JunctionBoxes, Movement
from twin.engine.mobil import LaneChangeInputs, should_change_lane
from twin.engine.models import Car
from twin.engine.parking import SPOT_LENGTH_M, ParkingSpot, build_parking_spots, free_spots_near, spot_front_pose, spot_world_xy
from twin.engine.ped_facing import turn_toward, walking_facing
from twin.engine.ped_separation import separate
from twin.engine.pedestrian import Pedestrian
from twin.engine.places import generate_places, places_from_buildings
from twin.engine.road_network import LANE_WIDTH_M, load_road_graph
from twin.engine.routing import build_turn_graph, route_between, route_length
from twin.engine.social_force import BODY_RADIUS_M, SocialForceState, step_pedestrian
from twin.engine.stations import Station, stations_from_hospitals
from twin.engine.street_profile import (
    CROSSWALK_WIDTH_M,
    PARKING_LANE_M,
    SIDEWALK_WIDTH_M,
    STOP_LINE_GAP_M,
    driving_outer_offset,
    kerb_offset,
)
from twin.engine.traffic_lights import WALK, build_traffic_lights, tick_lights
from twin.engine.turn_paths import TurnCurve, turn_zone
from twin.engine.walk_network import CROSSWALK_HALF_WIDTH_M, SIDEWALK_HALF_WIDTH_M, Crosswalk, build_walk_network

STOP_LINE_SETBACK = 3.0     # meters before an intersection without a crosswalk where cars queue
JUNCTION_DECIDE_MARGIN_M = 1.0   # a vehicle decides whether to enter a junction this far before it must brake
JUNCTION_BRAKE_LEAD_S = 0.5      # ... plus the distance it covers while its brakes build up (jerk limit)
TURN_PRIORITY_AFTER_S = 4.0      # a car waiting this long for its exit crosswalk: pedestrians let it go
EXIT_ROOM_LOOKAHEAD_S = 2.0      # a vehicle ahead on the exit still makes room for this long at its speed
WALKWAY_MARGIN_M = 0.1        # pedestrians keep their body this far inside the sidewalk / crosswalk edge
LANE_CHANGE_COOLDOWN_S = 3.0  # min time between lane changes for one car, avoids flip-flopping
LANE_CHANGE_HORIZON_M = 50.0    # ignore leaders/followers farther than this for MOBIL entirely
COURTESY_HORIZON_M = 12.0         # followers beyond this range don't factor into the politeness term
                                    # (IDM's interaction term is never exactly 0 even at large gaps, so
                                    # without this cutoff cars drift lanes to "help" someone 30m+ back)
ARRIVAL_TOLERANCE_M = 0.6       # a vehicle braking to the end of its route counts as arrived this close
SPOT_CANDIDATES = 8              # destination spots considered: the nearest free ones to the place
WALK_COST_FACTOR = 3.0           # 1 m walked from the spot counts like 3 m driven when choosing a spot
PULL_OUT_M = 10.0                # a car leaves its parking lane over this distance along the road
# Pulling in: the curve into the parking lane ends PULL_IN_STRAIGHT_M before the stop, so the
# rear axle (3.7 m behind the bumper) is straight in the bay too; curve + straight + rear
# overhang stay clear of a car parked in the bay behind (12 m spacing).
PULL_IN_M = 10.0                 # ... and steers into a parking spot over this distance
PULL_IN_STRAIGHT_M = 6.0         # ... ending this far before the stop, so it rolls in straight
PARKING_SPEED_MS = 2.5           # pulls into a spot no faster than this (9 km/h)
PARKING_DECEL_MS2 = 2.0          # comfortable braking down to the parking speed, started just in time
PARKING_BRAKE_LEAD_S = 0.5       # ... counting on the brakes taking this long to bite
PARKING_STANLEY_GAIN = 1.0       # pulling out or in, steering lines the car up with the path (stanley_steer)
PARKING_ARRIVAL_TOLERANCE_M = 0.15  # parked this close to the end of the trip (centred in the bay)
PARKING_TRIP_MIN_M = PULL_OUT_M + PULL_IN_M + PULL_IN_STRAIGHT_M  # shortest trip from spot to spot
PULL_OUT_CLEAR_BEHIND_M = 35.0   # pull out only if no vehicle is this close behind in the lane
SIREN_PULL_OUT_CLEAR_BEHIND_M = 15.0  # ... for a unit with its siren on
PULL_OUT_CLEAR_AHEAD_M = 8.0     # ... or this close ahead of the parked car's front
PARKING_MANEUVER_S = 1.6    # duration of the pull-in tween from lane position to the parking spot
DWELL_MIN_S = 10.0             # min/max time a looping car stays parked before heading to a new place
DWELL_MAX_S = 60.0
PED_SPAWN_GAP_M = 1.0            # pedestrians spawn at least this far from each other (bodies are 0.6 m across)
PED_SPAWN_TRIES = 50
PED_ARRIVAL_RADIUS_M = 1.5       # how close to the goal node before a pedestrian counts as "arrived"
PED_MAX_TRIP_RADIUS_M = 400.0         # cap how far an LLM decision can send a pedestrian, real walking
                                        # speed means a cross-city walk would take unreasonably long
CAR_CONTACT_DEPTH_M = 0.05                     # car bodies this deep into each other count as a crash
SEPARATION_ROUNDS = 10                         # max separate / clamp-to-walkway alternations per tick
CLEANUP_DURATION_S = 4.0                   # how long an ambulance pauses on-scene before returning
CALLER_STOP_S = 0.5                        # a witness taking out a phone stops this many seconds of walking ahead
UNIT_MEAN_SPEED_MS = 8.0                   # for the dispatch ETA: pull-out, junctions and queues included
POLICE_BEHIND_AMBULANCE_M = 10.5          # the police car's spot is this much further back than the ambulance's
SCENE_STOP_BEHIND_M = 4.0                  # a unit stops this far behind the wreck it is called to


def _park_ease(t: float) -> float:
    """Sideways progress (0 to 1) of pulling out or in, over its distance: the quintic
    smootherstep, whose curvature is zero at both ends, so the car can come out of the
    curve with straight wheels (smoothstep ends on a curvature step the car lags behind)."""
    return 0.0 if t <= 0 else 1.0 if t >= 1 else t * t * t * (t * (6 * t - 15) + 10)


class Simulation(EmergencyDriving, IncidentResponse, FireResponse, FloodResponse):
    def __init__(
        self, graph: nx.MultiDiGraph | None = None, stations: list[Station] | None = None, incident_seed: int = 1,
        buildings: list[Building] | None = None, building_places: bool = False,
    ) -> None:
        """`graph`: a road graph shaped like road_network.load_road_graph()'s (projected
        x/y in metres; edges with length, lanes, oneway, highway, travel_time).
        Defaults to the OSM map of Avenue Habib Bourguiba.
        `stations`: hospitals, police and fire stations with their bays (app/stations.py);
        defaults to one ambulance station per generated hospital place.
        `incident_seed`: seeds witnesses' and callers' choices, on their own generator so they do
        not change the traffic of a given seed.
        `buildings`: the boxes behind the sidewalks (engine/buildings.py); none by default.
        `building_places`: the places road users go to are the buildings themselves (one each, named on
        their walls) instead of points scattered along the roads. Off by default: the staged scenarios
        and their pinned seeds were tuned against the scattered places."""
        self.graph: nx.MultiDiGraph = graph if graph is not None else load_road_graph()
        self.buildings: dict[str, Building] = {b.id: b for b in buildings or []}
        self.fire = FireModel(self.buildings, incident_seed)   # building fires, engine/fires.py
        self.cars: dict[str, Car] = {}
        self.pedestrians: dict[str, Pedestrian] = {}
        self._tick_count = 0
        self._sim_time = 0.0
        self.traffic_lights = build_traffic_lights(self.graph)
        self.walk = build_walk_network(self.graph, set(self.traffic_lights))
        self.parking_spots: dict[str, ParkingSpot] = build_parking_spots(self.graph)
        self._turns = build_turn_graph(self.graph)  # routing without U-turns, see routing.py
        # with buildings every place is one of them (its name goes on its walls); without, scattered places
        self.places: list[dict] = (
            places_from_buildings(self.graph, list(self.buildings.values())) if self.buildings and building_places else generate_places(self.graph)
        )
        # pedestrians walk to the sidewalk node nearest each place
        self._place_walk_node = {p["id"]: self.walk.nearest_node(p["x"], p["y"]) for p in self.places}
        self.accidents: list[dict] = []          # car-pedestrian and car-car accidents, oldest first
        self._turn_curves: dict[tuple[int, int, int, int], TurnCurve] = {}  # drawn paths through nodes
        self._boxes = JunctionBoxes(self._movements_at, self._movement_points)  # who may enter a junction
        self._crosswalk_waits: dict[str, dict[str, float]] = {}  # crosswalk id -> {vehicle id: waiting since}
        self._occupied_crosswalks: set[str] = set()  # crosswalk ids with someone on them, per tick
        self.crash_risk_multiplier: float = 1.0  # scaled up by external events (heat wave, etc.)
        self.decision_log: list[dict] = []  # ring buffer of recent agent decisions, newest last
        self._decision_seq = 0                # monotonic id, survives ring-buffer trimming
        self.stations: list[Station] = (
            stations if stations is not None
            else stations_from_hospitals(self.graph, self.places, self.parking_spots)
        )
        # emergency vehicles, parked in their station bays from the start
        self.units: dict[str, EmergencyVehicle] = {}
        self._spawn_units()
        # incidents as the city sees them: witnesses, their calls, cameras (app/witnesses.py, cameras.py)
        self.incident_rng = random.Random(incident_seed)
        self.corridors = wit.Corridors.of(self.graph)
        self.call_centre = CallCentre()
        self.cameras = cams.build_cameras(self.graph, self.traffic_lights)
        self.timeline: list[dict] = []          # ground-truth events, oldest first (scenario logs)
        self.false_call_rate_per_min = 0.0      # false reports (a call about nothing), city-wide
        self._witnessed: set[tuple[str, str]] = set()   # (accident id, witness id) already decided
        self._callers: dict[str, dict] = {}     # witness id -> noticed / calling state
        self._stopped_since: dict[str, float] = {}      # vehicle id -> when it came to a stop
        self.responses: dict[str, dict] = {}    # incident id -> units sent, accident found, phase
        self.closed_edges: set[tuple[int, int]] = set()  # barriers (set_barrier_state): no car drives in
        self._turns_open = self._turns                   # the turn graph without closed edges, for cars
        self.hazard_edges: set[tuple[int, int]] = set()  # streets next to a burning building, avoided (fire_hazard.py)
        self.hazard_walk_edges: set[frozenset] = set()   # ... and the sidewalk pieces and crosswalks there
        self._hazard_key: tuple[str, ...] = ()           # the fires the hazards were last worked out for
        self._turns_barriers = self._turns               # ... without barriers only: drivers who ignore flooding
        # rain and flooding (flood.py, flood_response.py): none unless a scenario sets them
        self.rain = RainProfile()
        self.flood_zones: list = []
        self.flooded_edges: set[tuple[int, int]] = set()  # careful drivers do not drive in (both directions)
        self._planned_floods: dict[str, float] = {}     # flood_risk: zone id -> when it floods
        self._flood_seed = incident_seed
        self._dry_speed: dict[str, float] = {}          # pedestrian id -> walking speed, while wading
        self._trapped_peds: set[str] = set()            # stuck in deep water, waiting for the fire crew
        self._rescued_peds: set[str] = set()            # led out by the fire crew, still in the water
        self._walk_depths: tuple[float, dict] = (-1.0, {})  # sim time, walk edge -> deepest water on it
        self._dt = 0.1
        self.pending_crashes: list[tuple[str, str, str]] = []  # (unit kind, car_a_id, car_b_id)
                                                                   # queued while every unit of the kind is busy

    UNIT_ID_PREFIX = {"ambulance": "amb", "police": "police", "fire": "fire"}

    def _spawn_units(self) -> None:
        """One vehicle per station bay, parked there; the bay stays reserved for it."""
        count: dict[str, int] = {}
        for station in self.stations:
            kind = station.unit_kind
            for spot_id in station.spot_ids:
                count[kind] = count.get(kind, 0) + 1
                spot = self.parking_spots[spot_id]
                if spot.occupied_by is not None:
                    raise ValueError(f"station {station.id}: bay {spot_id} is taken by {spot.occupied_by}")
                unit = EmergencyVehicle(
                    id=f"{self.UNIT_ID_PREFIX[kind]}{count[kind]}", kind=kind, station_id=station.id,
                    home_spot_id=spot_id, route_nodes=list(spot.edge),
                )
                spot.occupied_by = unit.id
                self._park_unit(unit)
                self.units[unit.id] = unit

    def _park_unit(self, unit: EmergencyVehicle) -> None:
        """Parked in its bay, as Simulation._park does for a car."""
        spot = self.parking_spots[unit.home_spot_id]
        unit.route_nodes, unit.edge_index, unit.lane = list(spot.edge), 0, 0
        unit.dist_on_edge = spot.dist_on_edge + unit.params.length / 2
        unit.x, unit.y, unit.heading = spot_front_pose(self.graph, spot, unit.params.length)
        unit.speed = unit.accel = unit.steer = 0.0
        unit.start_dist = unit.end_dist = None
        unit.park_shift_start = unit.park_shift_end = 0.0
        unit.status, unit.finished = "idle", True

    @property
    def ambulances(self) -> dict[str, EmergencyVehicle]:
        return {k: u for k, u in self.units.items() if u.kind == "ambulance"}

    # ---- routing / spawning ----------------------------------------------

    def node_ids(self) -> list[int]:
        return list(self.graph.nodes)

    def graph_bounds(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) of the road network, in its projected CRS."""
        xs = [d["x"] for _, d in self.graph.nodes(data=True)]
        ys = [d["y"] for _, d in self.graph.nodes(data=True)]
        return min(xs), min(ys), max(xs), max(ys)

    def edge_data(self, u: int, v: int) -> dict:
        data = self.graph.get_edge_data(u, v)
        if not data:
            # graph is directed; if no forward edge, this route step is invalid
            raise ValueError(f"no edge {u}->{v}")
        return data[0]  # multigraph: take first parallel edge

    def edge_length(self, u: int, v: int) -> float:
        return self.edge_data(u, v).get("length", 1.0)

    def edge_lanes(self, u: int, v: int) -> int:
        return self.edge_data(u, v).get("lanes", 1)

    def spawn_car(self, origin: int, dest: int, car_id: str | None = None, loop: bool = False) -> Car:
        route = nx.shortest_path(self.graph, origin, dest, weight="travel_time")
        if len(route) < 2:
            raise ValueError("origin and destination resolve to the same node")
        first_lanes = self.edge_lanes(route[0], route[1])
        car = Car(
            id=car_id or uuid.uuid4().hex[:8],
            route_nodes=route,
            lane=random.randrange(first_lanes),
            loop=loop,
        )
        self._place_on_route(car)
        self.cars[car.id] = car
        return car

    def _random_place_node(self, exclude_node: int | None = None) -> int | None:
        if not self.places:
            return None
        candidates = self.places
        if exclude_node is not None and len(self.places) > 1:
            candidates = [p for p in self.places if p["nearest_node"] != exclude_node] or self.places
        return random.choice(candidates)["nearest_node"]

    def spawn_agent_car(self, car_id: str | None = None) -> Car:
        """Spawn a car with a persona, parked in a random free spot, awaiting its first LLM
        decision on where to drive. Caller (main.py) must trigger a decision for it."""
        free = [s for s in self.parking_spots.values() if s.occupied_by is None]
        if not free:
            raise RuntimeError("no free parking spot to spawn a car in")
        return self.spawn_parked_car(random.choice(free).id, car_id=car_id, loop=True)

    def spawn_parked_car(self, spot_id: str, car_id: str | None = None, loop: bool = False) -> Car:
        """A car standing in parking spot `spot_id` (must be free). With loop=False it stays
        there until start_trip() sends it somewhere (scenarios)."""
        spot = self.parking_spots[spot_id]
        if spot.occupied_by is not None:
            raise ValueError(f"spot {spot_id} is taken by {spot.occupied_by}")
        car = Car(
            id=car_id or uuid.uuid4().hex[:8],
            route_nodes=list(spot.edge),
            loop=loop,
            persona=random_persona(),
            status="parked",  # sits still until its first decision resolves
            finished=True,
            awaiting_decision=False,
        )
        self._park(car, spot)
        self.cars[car.id] = car
        return car

    def _park(self, car: Car, spot: ParkingSpot) -> None:
        spot.occupied_by = car.id
        car.parking_spot_id = spot.id
        car.route_nodes, car.edge_index, car.lane = list(spot.edge), 0, 0
        car.dist_on_edge = spot.dist_on_edge + car.params.length / 2
        car.x, car.y, car.heading = spot_front_pose(self.graph, spot, car.params.length)
        car.speed = car.accel = car.steer = 0.0
        car.status, car.finished = "parked", True

    def spawn_random_car(self) -> Car:
        nodes = self.node_ids()
        for _ in range(20):
            origin = random.choice(nodes)
            dest = self._random_place_node(exclude_node=origin) or random.choice(nodes)
            if origin == dest:
                continue
            try:
                return self.spawn_car(origin, dest, loop=True)
            except (nx.NetworkXNoPath, ValueError):
                continue
        raise RuntimeError("could not find a routable node pair after 20 tries")

    def spawn_agent_pedestrian(self, ped_id: str | None = None) -> Pedestrian:
        """Spawn a pedestrian with a persona, standing at a random node, awaiting its
        first LLM decision on where to walk. Caller (main.py) must trigger a decision.
        Stands at a random point along a sidewalk, away from everyone already there: a map
        has only a few dozen sidewalk nodes, so spawning on nodes stacked a crowd on one
        point and separation then pushed some of them onto the road."""
        origin, piece, (x, y) = self._free_sidewalk_spot()
        ped = Pedestrian(
            id=ped_id or uuid.uuid4().hex[:8],
            route_nodes=[origin],
            spawn_piece=piece,
            force=SocialForceState(x=x, y=y),
            persona=random_persona(),
            status="arrived",  # stands still until its first decision resolves
            finished=True,
        )
        self.pedestrians[ped.id] = ped
        return ped

    def _free_sidewalk_spot(self) -> tuple[int, tuple[int, int], tuple[float, float]]:
        """(nearest end node, the piece's two end nodes, point) for a random spot on a sidewalk piece at
        least PED_SPAWN_GAP_M from every pedestrian; a crowded map takes the best of
        PED_SPAWN_TRIES tries."""
        pieces = [(a, b) for a, b, d in self.walk.graph.edges(data=True) if d["kind"] == "sidewalk"]
        others = [(p.x, p.y) for p in self.pedestrians.values()]
        best = None
        for _ in range(PED_SPAWN_TRIES):
            a, b = random.choice(pieces)
            t = random.random()
            (ax, ay), (bx, by) = self.walk.xy(a), self.walk.xy(b)
            point = (ax + (bx - ax) * t, ay + (by - ay) * t)
            nearest = min((math.hypot(point[0] - ox, point[1] - oy) for ox, oy in others), default=math.inf)
            if best is None or nearest > best[0]:
                best = (nearest, a if t < 0.5 else b, (a, b), point)
            if nearest >= PED_SPAWN_GAP_M:
                break
        return best[1], best[2], best[3]

    def _trip_start_node(self, ped: Pedestrian, dest_node: int) -> int:
        """Where a trip from the pedestrian's standing place starts. Normally the node they
        stand at; a pedestrian spawned mid-sidewalk walks to whichever end of their sidewalk
        piece makes the whole trip shorter, so they never walk to one end and turn back."""
        piece, ped.spawn_piece = ped.spawn_piece, None
        if piece is None:
            return ped.route_nodes[-1]
        best = None
        for node in piece:
            try:
                length = nx.shortest_path_length(self.walk.graph, node, dest_node, weight="length")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            x, y = self.walk.xy(node)
            total = math.hypot(x - ped.x, y - ped.y) + length
            if best is None or total < best[0]:
                best = (total, node)
        return best[1] if best else ped.route_nodes[-1]

    # ---- agent decision points (LLM calls happen outside sim.py, in main.py's async loop) ----

    def cars_needing_decision(self) -> list[Car]:
        """Cars ready for their next LLM decision: either brand new (no depart_at set
        yet, never dwelled) or dwell-expired. main.py polls this each tick."""
        return [
            c
            for c in self.cars.values()
            if c.loop
            and not c.awaiting_decision
            and c.status in ("parked", "unparked")
            and c.pending_spot_id is None
            and (c.depart_at is None or self._sim_time >= c.depart_at)
        ]

    def pedestrians_needing_decision(self) -> list[Pedestrian]:
        return [
            p
            for p in self.pedestrians.values()
            if p.loop
            and not p.awaiting_decision
            and p.status == "arrived"
            and (p.depart_at is None or self._sim_time >= p.depart_at)
        ]

    def nearby_places(self, entity) -> list[dict]:
        if isinstance(entity, Pedestrian):
            # keep pedestrian trips short (real walking speed, so a cross-city walk
            # would take unreasonably long) by only offering nearby places to choose from
            ex, ey = entity.x, entity.y
            nearby = [
                p
                for p in self.places
                if math.hypot(p["x"] - ex, p["y"] - ey) <= PED_MAX_TRIP_RADIUS_M
            ]
            return nearby or self.places  # fall back to full list if nothing is close enough
        return self.places

    DECISION_LOG_MAX = 200

    def _log_decision(
        self, entity_id: str, entity_type: str, persona, from_place, place_name, reason, fallback
    ) -> None:
        self._decision_seq += 1
        self.decision_log.append(
            {
                "seq": self._decision_seq,
                "sim_time": round(self._sim_time, 1),
                "entity_id": entity_id,
                "entity_type": entity_type,  # "car" | "pedestrian"
                "persona": persona,
                "from_place": from_place,
                "to_place": place_name,
                "reason": reason,
                "fallback": fallback,  # True if the LLM call failed and we picked randomly instead
            }
        )
        if len(self.decision_log) > self.DECISION_LOG_MAX:
            self.decision_log = self.decision_log[-self.DECISION_LOG_MAX :]

    def apply_decision(self, car_id: str, place_id: str | None, reason: str | None = None) -> None:
        car = self.cars.get(car_id)
        if car is None:
            return
        car.awaiting_decision = False

        place = next((p for p in self.places if p["id"] == place_id), None) if place_id else None
        fallback = place is None
        if place is None:
            # LLM call failed or returned nothing usable: fall back to a random place
            dest = self._random_place_node(exclude_node=car.route_nodes[-1])
            place = next((p for p in self.places if p["nearest_node"] == dest), None)
            reason = None

        if place is None:
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        car.last_reason = reason
        self._log_decision(
            car.id, "car", car.persona, car.current_place_name, place["name"], reason, fallback
        )
        self.request_trip(car, place["x"], place["y"], place["name"])

    def request_trip(self, car: Car, x: float, y: float, place_name: str | None = None) -> bool:
        """Reserve a free spot near (x, y): of the nearest few, the one with the least driving
        plus walking (a spot across the street can mean a lap of the block without U-turns).
        The car pulls out once there is a gap (_tick_departures). False if none is reachable."""
        spot = self._choose_spot(car, x, y)
        if spot is None:
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return False
        spot.occupied_by = car.id
        car.pending_spot_id = spot.id
        car.current_place_name = place_name
        return True

    def _choose_spot(self, car: Car, x: float, y: float) -> ParkingSpot | None:
        here = self.parking_spots.get(car.parking_spot_id) if car.parking_spot_id else None
        best, best_cost = None, math.inf
        # nobody parks next to a burning building: those spots are left out before the nearest are taken
        for spot, walk in free_spots_near(self.graph, self.parking_spots, x, y, SPOT_CANDIDATES,
                                          exclude=car.parking_spot_id, avoid_edges=self.hazard_edges):
            if here is None:
                cost = walk
            else:
                start, end = car.dist_on_edge, spot.dist_on_edge + car.params.length / 2
                route = route_between(self._turns_for(car), here.edge, start, spot.edge, end, PARKING_TRIP_MIN_M)
                if route is None:
                    continue
                cost = route_length(self.graph, route, start, end) + WALK_COST_FACTOR * walk
            if cost < best_cost:
                best, best_cost = spot, cost
        return best

    def start_trip(self, car: Car, dest_spot_id: str, force: bool = False) -> bool:
        """Scenarios: reserve `dest_spot_id` and pull out now (force) or at the next gap."""
        spot = self.parking_spots[dest_spot_id]
        if spot.occupied_by not in (None, car.id):
            raise ValueError(f"spot {dest_spot_id} is taken by {spot.occupied_by}")
        spot.occupied_by = car.id
        car.pending_spot_id = spot.id
        if force:
            return self._start_trip(car)
        return True

    def _tick_departures(self) -> None:
        for car in self.cars.values():
            if car.pending_spot_id is not None and car.status == "parked" and self._can_pull_out(car):
                self._start_trip(car)

    def _can_pull_out(self, car: Car | EmergencyVehicle) -> bool:
        """No vehicle close behind in the lane (or about to turn into it), none just ahead."""
        spot_id = car.home_spot_id if isinstance(car, EmergencyVehicle) else car.parking_spot_id
        spot = self.parking_spots[spot_id]
        # with its siren on a unit pulls out into a shorter gap: traffic behind sees it and brakes
        behind = SIREN_PULL_OUT_CLEAR_BEHIND_M if getattr(car, "siren", False) else PULL_OUT_CLEAR_BEHIND_M
        u, v = spot.edge
        front = car.dist_on_edge
        for other in self._moving_vehicles():
            if other is car:
                continue
            route, i = other.route_nodes, other.edge_index
            if (route[i], route[i + 1]) == (u, v):
                rel = other.dist_on_edge - front
                if -behind <= rel <= PULL_OUT_CLEAR_AHEAD_M + other.params.length:
                    return False
            elif i + 2 < len(route) and (route[i + 1], route[i + 2]) == (u, v):
                if self.edge_length(route[i], route[i + 1]) - other.dist_on_edge + front <= behind:
                    return False
        return True

    def _parking_shift(self, spot: ParkingSpot) -> float:
        """Sideways distance from the rightmost lane's centre to the spot's centre."""
        u, v = spot.edge
        lx, ly, _, _ = self._lane_xy(u, v, 0, spot.dist_on_edge)
        sx, sy, _ = spot_world_xy(self.graph, spot, 0.0)
        return math.hypot(sx - lx, sy - ly)

    def _start_trip(self, car: Car) -> bool:
        """Pull out of the current spot toward the reserved one. The car does not move here:
        it starts from where it is parked, and the lane it steers along begins in the parking
        lane (see _park_shift_at)."""
        here = self.parking_spots[car.parking_spot_id]
        dest = self.parking_spots[car.pending_spot_id]
        start_dist = car.dist_on_edge
        end_dist = dest.dist_on_edge + car.params.length / 2
        route = route_between(self._turns_for(car), here.edge, start_dist, dest.edge, end_dist, PARKING_TRIP_MIN_M)
        if route is None:
            dest.occupied_by = None
            car.pending_spot_id = None
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return False
        car.route_nodes, car.edge_index, car.lane = route, 0, 0
        car.start_dist, car.end_dist = start_dist, end_dist
        car.park_shift_start, car.park_shift_end = self._parking_shift(here), self._parking_shift(dest)
        car.leaving_spot_id, car.parking_spot_id = here.id, None
        car.speed = car.accel = 0.0
        car.status, car.finished, car.depart_at = "driving", False, None
        return True

    def _release_spot_left_behind(self, car: Car) -> None:
        """The spot pulled out of is free once the car is past the pull-out."""
        if car.leaving_spot_id is None:
            return
        if car.edge_index > 0 or car.dist_on_edge > (car.start_dist or 0.0) + PULL_OUT_M:
            spot = self.parking_spots.get(car.leaving_spot_id)
            if spot and spot.occupied_by == car.id:
                spot.occupied_by = None
            car.leaving_spot_id = None

    def _finish_trip(self, car: Car) -> None:
        """Arrived, nearly stopped, in the destination spot: park where it stands."""
        spot = self.parking_spots[car.pending_spot_id]
        car.parking_spot_id, car.pending_spot_id = spot.id, None
        car.end_dist = car.start_dist = None
        car.park_shift_start = car.park_shift_end = 0.0
        car.speed = car.accel = 0.0
        car.status, car.finished = "parked", True
        car.through_flood = False  # it was caught by a flood on that trip only
        if car.loop:
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)

    def apply_pedestrian_decision(
        self, ped_id: str, place_id: str | None, reason: str | None = None
    ) -> None:
        ped = self.pedestrians.get(ped_id)
        if ped is None:
            return
        ped.awaiting_decision = False

        place = next((p for p in self.places if p["id"] == place_id), None) if place_id else None
        fallback = place is None
        if place is None:
            # fall back within walking range, not a global random place (keeps trip length capped)
            candidates = [p for p in self.nearby_places(ped) if p["nearest_node"] != ped.route_nodes[-1]
                          and not self.near_fire(p["x"], p["y"])]
            place = random.choice(candidates) if candidates else None
            reason = None

        if place is None:
            ped.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        ped.last_reason = reason
        self._log_decision(
            ped.id, "pedestrian", ped.persona, ped.current_place_name, place["name"], reason, fallback
        )
        self._walk_to_node(ped, self._place_walk_node[place["id"]], place["name"])

    def remove_car(self, car_id: str) -> None:
        car = self.cars.pop(car_id, None)
        if car is None:
            return
        for spot_id in (car.parking_spot_id, car.pending_spot_id, car.leaving_spot_id):
            spot = self.parking_spots.get(spot_id) if spot_id else None
            if spot and spot.occupied_by == car_id:
                spot.occupied_by = None

    def remove_pedestrian(self, ped_id: str) -> None:
        self.pedestrians.pop(ped_id, None)

    # ---- physics tick -------------------------------------------------------

    def _moving_vehicles(self) -> list[Car | EmergencyVehicle]:
        """Cars and emergency units that currently occupy a road edge and need physics.

        Ambulances share the exact same IDM/MOBIL treatment as cars while
        driving (dispatched/returning) -- this is what lets them interact
        realistically with traffic instead of teleporting through it.
        """
        vehicles: list[Car | EmergencyVehicle] = [c for c in self.cars.values() if not c.finished]
        vehicles.extend(u for u in self.units.values() if not u.finished)
        return vehicles

    def _lane_groups(self) -> dict[tuple[int, int, int], list[Car | EmergencyVehicle]]:
        """Vehicles grouped by (u, v, lane), sorted leader-first (largest dist_on_edge first)."""
        groups: dict[tuple[int, int, int], list[Car | EmergencyVehicle]] = {}
        for vehicle in self._moving_vehicles():
            u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
            groups.setdefault((u, v, vehicle.lane), []).append(vehicle)
        for vehicles_here in groups.values():
            vehicles_here.sort(key=lambda c: c.dist_on_edge, reverse=True)
        return groups

    def _leader_follower(
        self, groups: dict[tuple[int, int, int], list[Car]], u: int, v: int, lane: int, car: Car
    ) -> tuple[Car | None, Car | None]:
        """Return (leader, follower) for `car` in the given (u, v, lane) group."""
        lane_cars = groups.get((u, v, lane), [])
        idx = None
        for i, c in enumerate(lane_cars):
            if c is car:
                idx = i
                break
        if idx is None:
            return None, None
        leader = lane_cars[idx - 1] if idx > 0 else None
        follower = lane_cars[idx + 1] if idx + 1 < len(lane_cars) else None
        return leader, follower

    def _within_horizon(
        self, car: Car, other: Car | None, horizon: float = LANE_CHANGE_HORIZON_M
    ) -> Car | None:
        """Treat a leader/follower as imperceptible for lane-change purposes beyond the horizon."""
        if other is None:
            return None
        if abs(other.dist_on_edge - car.dist_on_edge) > horizon:
            return None
        return other

    def _crash_cars(self, follower: Car, leader: Car) -> None:
        """Both cars stop dead at the point of impact and stay there, blocking the lane,
        until the accident is cleared."""
        follower.status = "crashed"
        follower.speed = 0.0
        leader.status = "crashed"
        leader.speed = 0.0
        self._record_car_accident(follower, leader, cause="rear_end")

    def _open_accident(self, accident_id: str) -> dict | None:
        return next((a for a in self.accidents if a["id"] == accident_id and a["cleared_t"] is None), None)

    def dispatch_ambulance(self, accident_id: str) -> bool:
        """Call: send the nearest idle ambulance to an open accident; it cleans the scene up on
        arrival (see _tick_ambulance_cleanups) and drives home. Nothing sends one on its own.
        If every ambulance is busy the call waits in the queue. False for an unknown or
        already cleared accident."""
        accident = self._open_accident(accident_id)
        if accident is None:
            return False
        car = self.cars.get(accident["car_id"])
        other_id = accident["other_car_id"] or accident["pedestrian_id"]
        if car is None:
            return False
        if not self._send_unit("ambulance", car.id, other_id):
            self.pending_crashes.append(("ambulance", car.id, other_id))
        return True

    def clear_accident(self, accident_id: str) -> bool:
        """Call: take the wrecked cars and the injured pedestrian of an open accident off the
        map at once. False for an unknown or already cleared accident."""
        accident = self._open_accident(accident_id)
        if accident is None:
            return False
        self._clear_scene([accident["car_id"], accident["other_car_id"] or accident["pedestrian_id"]])
        return True

    def _clear_scene(self, target_ids: list[str]) -> None:
        """Removes the cars and pedestrians in `target_ids` and marks their accidents cleared."""
        for target_id in target_ids:
            self.remove_car(target_id)
            self.remove_pedestrian(target_id)
        for accident in self.accidents:
            if accident["cleared_t"] is None and accident["car_id"] in target_ids:
                accident["cleared_t"] = round(self._sim_time, 2)

    INCIDENT_FIND_RADIUS_M = 40.0  # a unit sent to a reported location finds an accident this close to it

    def dispatch_unit(self, kind: str, incident_id: str, station_id: str | None = None) -> dict:
        """Call (the Twin's dispatch_unit actuator): send the nearest idle unit of `kind` to an
        incident of the call centre. Idempotent: a second call for the same incident and kind
        returns "duplicate" with the unit already sent. The unit drives to the reported
        location; the accident it works is the open one nearest to it (within 40 m).
        With `station_id`, only a unit of that station may go (a dispatcher that picked the station,
        for instance because another one is quarantined)."""
        if kind not in self.UNIT_ID_PREFIX:
            return {"status": "rejected", "reason": "unknown_unit_type"}
        if station_id is not None and not any(st.id == station_id and st.unit_kind == kind for st in self.stations):
            return {"status": "rejected", "reason": "unknown_station"}
        incident = self.call_centre.incident(incident_id)
        if incident is None:
            return {"status": "rejected", "reason": "unknown_incident"}
        response = self.response_for(incident)
        if kind in response["units"]:
            return {"status": "duplicate", "unit_id": response["units"][kind]}
        accident = self._open_accident(response["accident_id"]) if response["accident_id"] else None
        fire = self.fire.get(response.get("fire_id"))
        best = None
        wreck = self.cars.get(accident["car_id"]) if accident is not None and accident["car_id"] else None
        if accident is not None and wreck is None:  # a trapped pedestrian: the lane next to them
            dest, end = self._nearest_lane_position(accident["x"], accident["y"])
            if kind == "police":  # behind the fire truck, as at a wreck, or it queues behind it for good
                end = max(end - POLICE_BEHIND_AMBULANCE_M, 0.5)
            targets = None  # no wreck to stop behind: it stops at the end of its route
        elif accident is not None:
            dest, end = self._scene_target(wreck)
            if kind == "police":  # stops upstream of the ambulance's spot, shielding the scene
                end = max(end - POLICE_BEHIND_AMBULANCE_M, 0.5)
            targets = (accident["car_id"], accident["other_car_id"] or accident["pedestrian_id"])
        elif fire is not None and fire["cleared_t"] is None:
            dest, end, best = self._fastest_lane_position(kind, fire["x"], fire["y"], station_id)  # either lane in front of it
            targets = None
        else:
            dest, end = self._nearest_lane_position(incident["x"], incident["y"])
            targets = None
        best = best or self._best_unit(kind, dest, end, station_id)
        if best is None:
            return {"status": "rejected", "reason": "no_unit_available"}
        unit, route, length, end = best
        unit.status, unit.task, unit.incident_id, unit.siren = "dispatched", "respond", incident_id, True
        unit.params.v0, unit.params.a = SIREN_V0_MS, SIREN_ACCEL_MS2
        unit.scene_shift = -POLICE_ANGLE_SHIFT_M if kind == "police" else 0.0
        unit.target_car_ids = targets
        unit.pending_route, unit.pending_end = route, end
        response["units"][kind] = unit.id
        eta = round(length / UNIT_MEAN_SPEED_MS, 1)
        self.log_event("unit_dispatched", unit_id=unit.id, unit_kind=kind, incident_id=incident_id, eta_s=eta)
        return {"status": "dispatched", "unit_id": unit.id, "eta_seconds": eta}

    def recall_unit(self, unit_id: str) -> dict:
        """Call (the Twin's recall_unit actuator): stand a unit down, so it drives home and can be sent again.
        Idempotent: a unit going home or at home answers "duplicate". A unit at work that cannot just leave
        (an ambulance crew out or a casualty aboard, a fire truck fighting a fire or rescuing) is "unit_busy"."""
        unit = self.units.get(unit_id)
        if unit is None:
            return {"status": "rejected", "reason": "unknown_unit", "unit_id": unit_id}
        if unit.status in ("idle", "returning"):
            return {"status": "duplicate", "unit_id": unit_id}
        response = self.responses.get(unit.incident_id)
        if self._unit_busy(unit, response):
            return {"status": "rejected", "reason": "unit_busy", "unit_id": unit_id}
        if unit.pending_route is not None:   # still in its bay, waiting for a gap to pull out
            unit.pending_route = unit.pending_end = None
            self._unit_home(unit)
        else:
            self._head_home(unit)
            if unit.status != "returning":
                return {"status": "rejected", "reason": "no_way_home", "unit_id": unit_id}
            unit.scene_shift, unit.siren, unit.target_car_ids = 0.0, False, None
        if response is not None:
            response["units"].pop(unit.kind, None)
            if unit.kind == "police" and response.get("closed_edges"):
                self.set_barrier_state(response.pop("closed_edges"), False, by="police")
        self.log_event("unit_recalled", unit_id=unit_id)
        return {"status": "recalled", "unit_id": unit_id}

    @staticmethod
    def _unit_busy(unit: EmergencyVehicle, response: dict | None) -> bool:
        if unit.status == "to_hospital" or getattr(unit, "casualty_id", None):
            return True
        if response is None:
            return False
        return ((response.get("crew") or {}).get("unit") == unit.id or (response.get("fire_work") or {}).get("unit") == unit.id
                or response.get("rescue_unit") == unit.id)

    def response_for(self, incident: dict) -> dict:
        """What is being done about a call-centre incident; created on the first dispatch."""
        response = self.responses.get(incident["id"])
        if response is None:
            near = [a for a in self.accidents if a["cleared_t"] is None
                    and math.hypot(a["x"] - incident["x"], a["y"] - incident["y"]) <= self.INCIDENT_FIND_RADIUS_M]
            near.sort(key=lambda a: (a["car_id"] is None, math.hypot(a["x"] - incident["x"], a["y"] - incident["y"])))
            fires = sorted((f for f in self.fire.open() if math.hypot(f["x"] - incident["x"], f["y"] - incident["y"])
                            <= self.INCIDENT_FIND_RADIUS_M),
                           key=lambda f: math.hypot(f["x"] - incident["x"], f["y"] - incident["y"]))
            response = {"incident_id": incident["id"], "accident_id": near[0]["id"] if near else None,
                        "fire_id": fires[0]["id"] if fires else None, "fire_ids": {fires[0]["id"]} if fires else set(),
                        "units": {}, "phase": "dispatched", "x": incident["x"], "y": incident["y"],
                        "flood_zone_id": near[0].get("flood_zone_id") if near else None}
            self.responses[incident["id"]] = response
        return response

    def _best_unit(self, kind: str, dest: tuple[int, int], end: float, station_id: str | None = None):
        """The idle unit of `kind` (of `station_id` when given) with the shortest way to the spot, from
        either end of its street: (unit, route, length, where the route ends on its last edge)."""
        best, best_len = None, math.inf
        for unit in self.units.values():
            if unit.kind != kind or unit.status != "idle" or (station_id is not None and unit.station_id != station_id):
                continue
            start = (unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1])
            for edge, stop in self.scene_targets(dest, end):
                route = route_between(self._turns, start, unit.dist_on_edge, edge, stop, PULL_OUT_M + 5.0)
                if route is None:
                    continue
                length = route_length(self.graph, route, unit.dist_on_edge, stop)
                if length < best_len:
                    best, best_len = (unit, route, length, stop), length
        return best

    def _nearest_lane_position(self, x: float, y: float) -> tuple[tuple[int, int], float]:
        """The point of a lane 0 nearest to (x, y), kept 15 m clear of the nodes."""
        best, best_d = None, math.inf
        for u, v in self.graph.edges():
            length = self.edge_length(u, v)
            if length < 30.0:
                continue
            ax, ay, ux, uy = self._lane_xy(u, v, 0, 0.0)
            along = max(15.0, min(length - 15.0, (x - ax) * ux + (y - ay) * uy))
            d = math.hypot(ax + ux * along - x, ay + uy * along - y)
            if d < best_d:
                best, best_d = ((u, v), along), d
        return best

    def _scene_target(self, wreck: Car) -> tuple[tuple[int, int], float]:
        """Where a unit stops for a wreck: in its lane, SCENE_STOP_BEHIND_M behind its rear."""
        edge = (wreck.route_nodes[wreck.edge_index], wreck.route_nodes[wreck.edge_index + 1])
        end = wreck.dist_on_edge - wreck.params.length - SCENE_STOP_BEHIND_M
        return edge, max(end, 0.5)  # a wreck just past a node: the unit stops behind it by IDM

    def _send_unit(self, kind: str, car_a_id: str, car_b_id: str) -> bool:
        """Gives the idle unit of `kind` with the shortest drive to wreck `car_a_id` the call.
        It pulls out of its bay at the next gap in traffic (_tick_unit_departures).
        False if none is idle or none can get there."""
        wreck = self.cars.get(car_a_id)
        if wreck is None:
            return False
        dest, end = self._scene_target(wreck)
        best, best_len = None, math.inf
        for unit in self.units.values():
            if unit.kind != kind or unit.status != "idle":
                continue
            start = (unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1])
            route = route_between(self._turns, start, unit.dist_on_edge, dest, end, PULL_OUT_M + 5.0)
            if route is None:
                continue
            length = route_length(self.graph, route, unit.dist_on_edge, end)
            if length < best_len:
                best, best_len = (unit, route), length
        if best is None:
            return False
        unit, route = best
        unit.status, unit.target_car_ids, unit.task = "dispatched", (car_a_id, car_b_id), "cleanup"
        unit.pending_route, unit.pending_end = route, end
        return True

    def _tick_unit_departures(self) -> None:
        """A unit with a call pulls out of its bay as soon as there is a gap, like a car."""
        for unit in self.units.values():
            if unit.pending_route is None or not self._can_pull_out(unit):
                continue
            spot = self.parking_spots[unit.home_spot_id]
            unit.route_nodes, unit.edge_index, unit.lane = unit.pending_route, 0, 0
            unit.start_dist, unit.end_dist = unit.dist_on_edge, unit.pending_end
            unit.park_shift_start, unit.park_shift_end = self._parking_shift(spot), 0.0
            unit.pending_route = unit.pending_end = None
            unit.speed = unit.accel = 0.0
            unit.finished = False
            self.log_event("unit_pulled_out", unit_id=unit.id, incident_id=unit.incident_id, task=unit.task)

    def _try_dispatch_from_queue(self) -> None:
        if not self.pending_crashes:
            return
        still_pending = []
        for kind, car_a_id, car_b_id in self.pending_crashes:
            if car_a_id not in self.cars:
                continue  # already cleared some other way, drop from the queue
            if not self._send_unit(kind, car_a_id, car_b_id):
                still_pending.append((kind, car_a_id, car_b_id))
        self.pending_crashes = still_pending

    def _try_lane_change(
        self, groups: dict[tuple[int, int, int], list[Car]], car: Car, u: int, v: int, num_lanes: int
    ) -> None:
        if num_lanes < 2:
            return
        if self._sim_time - car.last_lane_change_time < LANE_CHANGE_COOLDOWN_S:
            return

        cur_lead, cur_follower = self._leader_follower(groups, u, v, car.lane, car)
        cur_lead = self._within_horizon(car, cur_lead)
        cur_follower = self._within_horizon(car, cur_follower, horizon=COURTESY_HORIZON_M)
        cur_gap = (cur_lead.dist_on_edge - car.dist_on_edge - cur_lead.params.length) if cur_lead else None
        cur_follower_gap_before = (
            car.dist_on_edge - cur_follower.dist_on_edge - car.params.length if cur_follower else None
        )
        cur_follower_gap_after = (
            cur_lead.dist_on_edge - cur_follower.dist_on_edge - cur_lead.params.length
            if (cur_follower and cur_lead)
            else None
        )

        for target_lane in (car.lane - 1, car.lane + 1):
            if target_lane < 0 or target_lane >= num_lanes:
                continue
            # target lane cars are sorted leader-first (descending dist_on_edge); find where car would slot in
            tgt_lane_cars = groups.get((u, v, target_lane), [])
            candidates_ahead = [c for c in tgt_lane_cars if c.dist_on_edge > car.dist_on_edge]
            tgt_lead = candidates_ahead[-1] if candidates_ahead else None
            candidates_behind = [c for c in tgt_lane_cars if c.dist_on_edge <= car.dist_on_edge]
            tgt_follower = candidates_behind[0] if candidates_behind else None
            tgt_lead = self._within_horizon(car, tgt_lead)
            tgt_follower = self._within_horizon(car, tgt_follower, horizon=COURTESY_HORIZON_M)

            tgt_gap_ahead = (
                tgt_lead.dist_on_edge - car.dist_on_edge - tgt_lead.params.length if tgt_lead else None
            )
            tgt_follower_gap_to_us = (
                car.dist_on_edge - tgt_follower.dist_on_edge - car.params.length if tgt_follower else None
            )
            tgt_follower_gap_to_its_lead = (
                tgt_lead.dist_on_edge - tgt_follower.dist_on_edge - tgt_lead.params.length
                if (tgt_follower and tgt_lead)
                else None
            )

            inputs = LaneChangeInputs(
                v=car.speed,
                params=car.params,
                cur_lead_v=cur_lead.speed if cur_lead else None,
                cur_gap=cur_gap,
                tgt_lead_v=tgt_lead.speed if tgt_lead else None,
                tgt_gap_ahead=tgt_gap_ahead,
                tgt_follower_v=tgt_follower.speed if tgt_follower else None,
                tgt_follower_gap_to_us=tgt_follower_gap_to_us,
                tgt_follower_gap_to_its_lead=tgt_follower_gap_to_its_lead,
                cur_follower_v=cur_follower.speed if cur_follower else None,
                cur_follower_gap_before=cur_follower_gap_before,
                cur_follower_gap_after=cur_follower_gap_after,
            )
            if should_change_lane(inputs, car.mobil):
                # move car to target lane group immediately so subsequent cars this tick see it
                groups.setdefault((u, v, car.lane), [])
                if car in groups[(u, v, car.lane)]:
                    groups[(u, v, car.lane)].remove(car)
                car.lane = target_lane
                car.last_lane_change_time = self._sim_time
                groups.setdefault((u, v, target_lane), []).append(car)
                groups[(u, v, target_lane)].sort(key=lambda c: c.dist_on_edge, reverse=True)
                return

    def tick(self, dt: float = 0.1) -> None:
        self._dt = dt
        self._tick_count += 1
        self._sim_time += dt
        tick_lights(self.traffic_lights, self._sim_time)
        self._tick_flood(dt)

        self._tick_departures()
        self._tick_unit_departures()
        self._release_junctions()
        groups = self._lane_groups()
        self._tick_yielding()
        self._occupied_crosswalks = self._crosswalks_in_use()
        self._tick_priority_claims()

        # lane-change evaluation (before car-following accel, so accel reflects new lane)
        for vehicle in self._moving_vehicles():
            if self._standing(vehicle):
                continue
            u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
            num_lanes = self.edge_lanes(u, v)
            self._try_lane_change(groups, vehicle, u, v, num_lanes)

        # car-following (IDM) + red-light braking, per lane group
        for (u, v, lane), cars_here in groups.items():
            edge_len = self.edge_length(u, v)
            stop_line_dist = max(0.0, edge_len - self._stop_setback(u, v))
            light_state = self._light_state(u, v)

            for i, car in enumerate(cars_here):
                if self._standing(car):
                    continue  # a wreck, or a unit working a scene: stays put, blocking the lane for others
                lead = cars_here[i - 1] if i > 0 else None
                if isinstance(car, EmergencyVehicle) and car.siren:
                    lead = self._siren_leader(car, cars_here, i)  # drives past cars pulled over for it
                if lead is not None:
                    gap = self._gap(car, lead, lead.dist_on_edge - car.dist_on_edge - lead.params.length)
                    # only two real Cars can crash into each other -- an ambulance never
                    # crashes, and never gets crashed into (it's the emergency responder)
                    lead_is_crashable = isinstance(lead, Car) and lead.status != "crashed"
                    if (
                        isinstance(car, Car)
                        and lead_is_crashable
                        and should_crash(car.speed, gap, self.crash_risk_multiplier)
                    ):
                        self._crash_cars(car, lead)
                        continue
                    accel = idm_acceleration(car.speed, lead.speed, gap, car.params)
                else:
                    across = self._leader_across(groups, car, edge_len)
                    if across is not None and isinstance(car, EmergencyVehicle) and car.responding and self._passes(car, across[0]):
                        across = None
                    if across is not None:
                        ahead, gap = across
                        accel = idm_acceleration(car.speed, ahead.speed, gap, car.params)
                    else:
                        accel = idm_acceleration(car.speed, None, None, car.params)

                must_stop = getattr(car, "obeys_signals", True) and self._must_stop_for_light(
                    car, light_state, stop_line_dist
                )
                if must_stop:
                    stop_gap = stop_line_dist - car.dist_on_edge
                    stop_accel = idm_acceleration(car.speed, 0.0, stop_gap, car.params)
                    accel = min(accel, stop_accel)
                    held = self._boxes.held_by(car.id)
                    if held is not None and held[1] == v:  # waits at this line: leave the junction ahead
                        self._boxes.release(car.id)        # to green traffic (not one it is still leaving)
                else:
                    accel = min(accel, self._junction_accel(car, groups, stop_line_dist))
                accel = min(accel, self._priority_accel(car, stop_line_dist), self._crosswalk_caution_accel(car, u, v, edge_len))
                accel = min(accel, self._path_block_accel(car), self._person_accel(car))
                accel = min(accel, self._crosswalk_yield_accel(car, u, v, edge_len))
                accel = min(accel, self._yield_accel(car), self._closed_ahead_accel(car, edge_len, stop_line_dist))
                accel = min(accel, self._curve_accel(car), self._route_end_accel(car, edge_len))
                accel = min(accel, self._pull_in_accel(car), self._water_accel(car))
                self._drive(car, vd.clamp_accel(accel, car.accel, dt, self._spec(car)), dt)

        # advance cars that reached the end of their current edge
        for car in self.cars.values():
            if car.finished or car.status == "crashed":
                continue
            self._advance_edge_if_needed(car)
            self._release_spot_left_behind(car)

        # advance emergency units the same way; arriving means working the scene, or parking
        # back in the station bay (_unit_advance_if_needed)
        for unit in self.units.values():
            if unit.finished:
                continue
            self._unit_advance_if_needed(unit)

        self._tick_unit_scenes(dt)
        self._tick_response(dt)
        self._detect_car_collisions()
        self._tick_stalls()
        self._tick_waders()
        self._tick_ped_flood()
        self._tick_pedestrians(dt)
        self._detect_pedestrian_accidents()
        self._tick_fires()
        self._tick_witnesses()
        self._tick_cameras()

    # ---- traffic lights, crosswalks, accidents -------------------------------

    @staticmethod
    def _standing(vehicle) -> bool:
        """A wreck, or a unit working a scene: in its lane, not driving."""
        if isinstance(vehicle, EmergencyVehicle):
            return vehicle.status in ("cleaning", "on_scene")
        return vehicle.status == "crashed"

    def _light_state(self, u: int, v: int) -> str | None:
        """Car signal for traffic on u->v arriving at v, or None if v has no light."""
        light = self.traffic_lights.get(v)
        return None if light is None else light.state_for_approach(u)

    def _stop_setback(self, u: int, v: int) -> float:
        """Metres before v where cars on u->v stop: before v's crosswalk if it has one."""
        setback = self.walk.stop_setback(u, v)
        return STOP_LINE_SETBACK if setback is None else setback

    @staticmethod
    def _must_stop_for_light(vehicle, light_state: str | None, stop_line_dist: float) -> bool:
        """Red: stop if still before the line. Yellow: stop only if it can be done at a
        comfortable deceleration; a car too close to stop goes through (dilemma zone)."""
        if light_state not in ("red", "yellow") or vehicle.dist_on_edge >= stop_line_dist:
            return False
        if light_state == "red":
            return True
        braking_distance = vehicle.speed * vehicle.speed / (2 * vehicle.params.b)
        return stop_line_dist - vehicle.dist_on_edge >= braking_distance

    # ---- junctions: following across a node, and entering the box -------------

    def _movements_at(self, node: int) -> list[Movement]:
        """Every way through `node`: in on a->node, out on node->c (no U-turns)."""
        return [(a, node, c) for a in self.graph.predecessors(node) for c in self.graph.successors(node) if c != a]

    def _movement_points(self, m: Movement) -> list[tuple[float, float]]:
        curve = self._turn_curve(*m, 0)  # rightmost lane; the two-block map has one per direction
        return [curve.at(i / JUNCTION_SAMPLES)[:2] for i in range(JUNCTION_SAMPLES + 1)]

    def _vehicle(self, vehicle_id: str):
        return self.cars.get(vehicle_id) or self.units.get(vehicle_id)

    def _leader_across(self, groups, vehicle, edge_len: float):
        """The last vehicle on the next edge of the route, with the gap to it: the car ahead
        after the node, e.g. one that has just turned in. None if the next edge is empty."""
        route, i = vehicle.route_nodes, vehicle.edge_index
        if i + 2 >= len(route):
            return None
        v, c = route[i + 1], route[i + 2]
        lane = min(vehicle.lane, self.edge_lanes(v, c) - 1)
        ahead = [o for o in groups.get((v, c, lane), []) if o is not vehicle]
        if not ahead:
            return None
        tail = ahead[-1]  # groups are sorted leader-first
        along = (edge_len - vehicle.dist_on_edge) + tail.dist_on_edge - tail.params.length
        return tail, self._gap(vehicle, tail, along)

    @staticmethod
    def _gap(follower, leader, along_route: float) -> float:
        """Bumper-to-bumper gap: along the route, but never more than the straight line from
        the follower's front to the leader's rear. Through a turn the curve cuts the corner,
        so the distance along the two edges overstates the real gap by up to a few metres."""
        rear_x = leader.x - math.cos(leader.heading) * leader.params.length
        rear_y = leader.y - math.sin(leader.heading) * leader.params.length
        return min(along_route, math.hypot(rear_x - follower.x, rear_y - follower.y))

    def _exit_has_room(self, vehicle, groups, b: int, c: int) -> bool:
        """Room on b->c for the whole vehicle past the box and the exit crosswalk, counting on
        traffic ahead to go on for EXIT_ROOM_LOOKAHEAD_S at its current speed and braking:
        entering must not leave it standing in the junction or on the crosswalk."""
        a = vehicle.route_nodes[vehicle.edge_index]
        clear_of = turn_zone(self.edge_length(a, b), self.edge_length(b, c))
        exit_cw = self.walk.crosswalk_at(b, c)
        if exit_cw is not None:
            clear_of = max(clear_of, exit_cw.along_m + CROSSWALK_HALF_WIDTH_M)
        need = clear_of + vehicle.params.length + vehicle.params.s0
        t = EXIT_ROOM_LOOKAHEAD_S
        for ln in range(self.edge_lanes(b, c)):
            for other in groups.get((b, c, ln), []):
                if other is vehicle:
                    continue
                v, acc = other.speed, min(other.accel, 0.0)
                still_to_go = v * t + 0.5 * acc * t * t if acc >= 0.0 or v + acc * t > 0.0 else v * v / (-2.0 * acc)
                if other.dist_on_edge - other.params.length + max(still_to_go, 0.0) < need:
                    return False
        return True

    def _junction_accel(self, vehicle, groups, stop_line_dist: float) -> float:
        """Before the stop line of a junction, take the box only if no vehicle in it drives a
        conflicting movement, there is room on the exit, and (for drivers who yield) nobody
        is in its path on the crosswalk it enters or leaves over; otherwise brake to the
        stop line and ask again next tick. Red-light runners ignore it. +inf when nothing holds the vehicle back."""
        route, i = vehicle.route_nodes, vehicle.edge_index
        if i + 2 >= len(route) or not getattr(vehicle, "obeys_signals", True):
            return math.inf
        if not getattr(vehicle, "respects_junctions", True):
            return math.inf
        movement = (route[i], route[i + 1], route[i + 2])
        if not self._boxes.is_junction(movement[1]):
            return math.inf
        to_line = stop_line_dist - vehicle.dist_on_edge
        braking = vehicle.speed * vehicle.speed / (2.0 * vehicle.params.b)
        exit_cw = self.walk.crosswalk_at(movement[1], movement[2])
        entry_cw = self.walk.crosswalk_at(movement[1], movement[0])
        yields = getattr(vehicle, "yield_to_pedestrians", True)
        crosswalk_busy = yields and (
            (exit_cw is not None and self._crosswalk_blocks(exit_cw, movement[1], movement[2], 0))
            or (entry_cw is not None and self._crosswalk_blocks(entry_cw, movement[0], movement[1], vehicle.lane))
        )
        if self._boxes.held_by(vehicle.id) == movement:
            if not (crosswalk_busy and to_line >= braking):
                return math.inf
            self._boxes.release(vehicle.id)  # someone stepped onto its crosswalk: wait at the line
            return idm_acceleration(vehicle.speed, 0.0, max(to_line, 0.01), vehicle.params)
        if to_line > braking + vehicle.speed * JUNCTION_BRAKE_LEAD_S + JUNCTION_DECIDE_MARGIN_M:
            return math.inf  # too far to decide yet: as late as it can still stop comfortably
        clear = self._boxes.may_enter(movement) and self._exit_has_room(vehicle, groups, *movement[1:])
        if to_line <= 0.0 or (clear and not crosswalk_busy):
            self._boxes.reserve(vehicle.id, movement)  # past the line already: it can only go on
            self._stop_waiting_for_crosswalks(vehicle.id)
            return math.inf
        if clear and crosswalk_busy and exit_cw is not None:  # only pedestrians in the way: they let it go in time
            self._crosswalk_waits.setdefault(exit_cw.id, {}).setdefault(vehicle.id, self._sim_time)
        return idm_acceleration(vehicle.speed, 0.0, max(to_line, 0.01), vehicle.params)

    def _stop_waiting_for_crosswalks(self, vehicle_id: str) -> None:
        for waits in self._crosswalk_waits.values():
            waits.pop(vehicle_id, None)

    def _release_junctions(self) -> None:
        """A vehicle leaves the box once its rear is past the turn curve on the exit edge (or
        it is gone, crashed, or no longer on that movement). Crosswalk waits of vehicles that
        are gone or no longer right before that crosswalk's junction are dropped too."""
        for cw_id, waits in self._crosswalk_waits.items():
            node = self.walk.crosswalks[cw_id].node
            for vid in list(waits):
                vehicle = self._vehicle(vid)
                if vehicle is None or vehicle.finished or vehicle.route_nodes[vehicle.edge_index + 1] != node:
                    del waits[vid]
        for vid, (a, b, c) in self._boxes.holders().items():
            vehicle = self._vehicle(vid)
            if vehicle is None or vehicle.finished or getattr(vehicle, "status", "") == "crashed":
                self._boxes.release(vid)
                continue
            route, i = vehicle.route_nodes, vehicle.edge_index
            here = (route[i], route[i + 1])
            if here == (a, b):
                continue  # still approaching or in the first half of the curve
            if here == (b, c):
                zone = turn_zone(self.edge_length(a, b), self.edge_length(b, c))
                if vehicle.dist_on_edge - vehicle.params.length < zone + 0.5:
                    continue
            self._boxes.release(vid)

    def _crosswalks_in_use(self) -> set[str]:
        """Crosswalks with a pedestrian on them (walking over, or lying injured)."""
        used = set()
        for ped in self.pedestrians.values():
            if ped.edge_index == 0 or ped.status not in ("walking", "injured"):
                continue
            cw = self.walk.crosswalk_between(ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index])
            if cw is not None:
                used.add(cw.id)
        return used

    def _crosswalk_yield_accel(self, vehicle, u: int, v: int, edge_len: float) -> float:
        """IDM braking toward the nearest occupied crosswalk ahead (this edge, or just past
        the next node), as if a stopped car stood just before it. +inf if nothing to yield to."""
        if not getattr(vehicle, "yield_to_pedestrians", True) or not self._occupied_crosswalks:
            return math.inf
        ahead = [(cw, centre, (u, v, vehicle.lane)) for cw, centre in self.walk.crosswalks_on_edge(u, v, edge_len)]
        if vehicle.edge_index + 2 < len(vehicle.route_nodes):
            w = vehicle.route_nodes[vehicle.edge_index + 2]
            nxt = self.walk.crosswalk_at(v, w)
            if nxt is not None:
                ahead.append((nxt, edge_len + nxt.along_m, (v, w, 0)))
        accel = math.inf
        for cw, centre, lane in ahead:
            if not self._crosswalk_blocks(cw, *lane, shift=vehicle.lateral_offset if isinstance(vehicle, EmergencyVehicle) else 0.0):
                continue
            stop_at = centre - CROSSWALK_HALF_WIDTH_M - STOP_LINE_GAP_M
            if vehicle.dist_on_edge > stop_at + STOP_LINE_GAP_M:
                continue  # already at or on the crosswalk: braking now would not help
            gap = max(stop_at - vehicle.dist_on_edge, 0.01)
            accel = min(accel, idm_acceleration(vehicle.speed, 0.0, gap, vehicle.params))
        return accel

    def _crosswalk_blocks(self, cw: Crosswalk, u: int, v: int, lane: int, shift: float = 0.0) -> bool:
        """Someone on `cw` is in the path of a vehicle in `lane` of edge u->v, or walking into
        it (crossing_rules.pedestrian_in_path). People on the far half of a wide crosswalk,
        walking away, let a turning car through instead of holding it for the whole crossing."""
        if cw.id not in self._occupied_crosswalks:
            return False
        x, y, ux, uy = self._lane_xy(u, v, lane, 0.0)
        for ped in self.pedestrians.values():
            if ped.edge_index == 0 or ped.status not in ("walking", "injured"):
                continue
            on = self.walk.crosswalk_between(ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index])
            if on is not cw:
                continue
            offset = -(ped.x - x) * uy + (ped.y - y) * ux + shift  # to the left of the path (shift: right of the lane)
            across = -ped.force.vx * uy + ped.force.vy * ux
            toward = -across if offset > 0 else across
            if pedestrian_in_path(offset, toward):
                return True
        return False

    def _vehicles_toward_crosswalk(self, cw: Crosswalk, held_by_red: bool) -> list[tuple[float, float]]:
        """(distance from front bumper to the crosswalk's near edge, speed) for every vehicle
        that will drive over `cw` next. Vehicles that a red light holds before their stop
        line are left out when `held_by_red` (they are not a threat while it stays red)."""
        n, m = cw.node, cw.arm
        out = []
        for vehicle in self._moving_vehicles():
            if isinstance(vehicle, Car) and vehicle.status == "crashed":
                continue
            u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
            length = self.edge_length(u, v)
            front = vehicle.dist_on_edge
            rear = front - vehicle.params.length
            if (u, v) == (m, n):          # driving toward the crosswalk on the crossed arm
                near = length - cw.along_m - CROSSWALK_HALF_WIDTH_M
                if held_by_red and getattr(vehicle, "obeys_signals", True) and front < length - self._stop_setback(u, v):
                    continue
            elif (u, v) == (n, m):        # leaving the intersection over it
                near = cw.along_m - CROSSWALK_HALF_WIDTH_M
            elif v == n and vehicle.edge_index + 2 < len(vehicle.route_nodes) and vehicle.route_nodes[vehicle.edge_index + 2] == m:
                # about to turn into the crossed arm
                held = self._light_state(u, v) == "red" and getattr(vehicle, "obeys_signals", True)
                if held and front < length - self._stop_setback(u, v):
                    continue
                near = length + cw.along_m - CROSSWALK_HALF_WIDTH_M
            else:
                continue
            if rear > near + CROSSWALK_WIDTH_M:
                continue  # already fully past it
            out.append((near - front, vehicle.speed))
        return out

    def _pedestrian_may_cross(self, cw: Crosswalk, ped: Pedestrian, start_node: int) -> bool:
        walk_state = self.traffic_lights[cw.node].walk_state if cw.signalised else None
        if self._crosswalk_claimed_by_junction(cw):
            return False
        cars = self._vehicles_toward_crosswalk(cw, held_by_red=walk_state is not None)
        return may_cross(walk_state, cars)

    def _crosswalk_claimed_by_junction(self, cw: Crosswalk) -> bool:
        """A vehicle holding the junction that can no longer stop at its stop line will drive over this
        crosswalk: the one it enters over (across its approach arm), or the one it leaves
        over (across its exit arm) until its rear is past it. It can no longer stop before
        the junction, and stopping now would leave it standing in it. (Before the line, a
        holder lets a pedestrian go first: see _junction_accel.) Also claimed for a car that
        has waited TURN_PRIORITY_AFTER_S at its line with only this crosswalk in its way, or
        a stream of pedestrians could keep turning traffic waiting forever."""
        waits = self._crosswalk_waits.get(cw.id, {}) if not cw.signalised else {}  # a signal already shares the time
        if any(self._sim_time - since >= TURN_PRIORITY_AFTER_S for since in waits.values()):
            return True
        for vid, (a, b, c) in self._boxes.holders().items():
            if b != cw.node or cw.arm not in (a, c):
                continue
            vehicle = self._vehicle(vid)
            if vehicle is None:
                continue
            here = (vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1])
            if here == (a, b):
                to_line = self.edge_length(a, b) - self._stop_setback(a, b) - vehicle.dist_on_edge
                braking = vehicle.speed * vehicle.speed / (2.0 * vehicle.params.b)
                can_stop_in = braking + vehicle.speed * JUNCTION_BRAKE_LEAD_S
                if to_line <= can_stop_in:  # it can no longer stop at its line
                    return True
                continue
            if cw.arm == c and here == (b, c):
                if vehicle.dist_on_edge - vehicle.params.length < cw.along_m + CROSSWALK_HALF_WIDTH_M:
                    return True
        return False

    def _detect_pedestrian_accidents(self) -> None:
        vehicles = [
            v for v in self._moving_vehicles()
            if v.speed >= MIN_IMPACT_SPEED_MS and not (isinstance(v, Car) and v.status == "crashed")
        ]
        if not vehicles:
            return
        for ped in self.pedestrians.values():
            if ped.status in ("injured", "carried", "loaded"):  # already a casualty (loaded: inside the ambulance)
                continue
            for vehicle in vehicles:
                if abs(vehicle.x - ped.x) > 8 or abs(vehicle.y - ped.y) > 8:
                    continue
                if car_hits_pedestrian(
                    vehicle.x, vehicle.y, vehicle.heading, vehicle.params.length, ped.x, ped.y, BODY_RADIUS_M
                ):
                    self._record_pedestrian_accident(vehicle, ped)
                    break

    def _detect_car_collisions(self) -> None:
        """Any two car bodies overlapping is a crash. Normal traffic keeps its distance, also
        across nodes and in junctions (rule R6 in tools/check_rules.py), so an overlap only
        happens when a driver breaks the rules, e.g. runs a red light. A red-light runner is
        the striking car; otherwise the faster one is."""
        cars = [c for c in self.cars.values() if not c.finished and c.status in ("driving", "crashed")]
        bodies = {c.id: body_corners(c.x, c.y, c.heading, c.params.length) for c in cars}
        for i, a in enumerate(cars):
            for b in cars[i + 1:]:
                if a.status == "crashed" and b.status == "crashed":
                    continue
                if abs(a.x - b.x) > 10 or abs(a.y - b.y) > 10:
                    continue
                if a.speed < MIN_IMPACT_SPEED_MS and b.speed < MIN_IMPACT_SPEED_MS:
                    continue
                if overlap_depth(bodies[a.id], bodies[b.id]) > CAR_CONTACT_DEPTH_M:
                    if a.obeys_signals != b.obeys_signals:  # the one who ran the light struck
                        striking, struck = (b, a) if a.obeys_signals else (a, b)
                    else:
                        striking, struck = (a, b) if a.speed >= b.speed else (b, a)
                    cause = "collision" if striking.obeys_signals else "ran_red_light"
                    self._crash_pair(striking, struck, cause)

    def _crash_pair(self, striking: Car, struck: Car, cause: str) -> None:
        """Both cars stop where they are and block their lanes until the accident is cleared
        (clear_accident, or an ambulance asked for with dispatch_ambulance)."""
        self._record_car_accident(striking, struck, cause=cause)
        for car in (striking, struck):
            car.status = "crashed"
            car.speed = 0.0

    def log_event(self, kind: str, **data) -> dict:
        """Ground-truth timeline entry at the current sim time."""
        event = {"t": round(self._sim_time, 2), "kind": kind, **data}
        self.timeline.append(event)
        return event

    def _record_car_accident(self, striking: Car, struck: Car, cause: str) -> None:
        self.accidents.append(
            {
                "id": f"acc{len(self.accidents) + 1}",
                "kind": "car_car",
                "cause": cause,
                "t": round(self._sim_time, 2),
                "x": round(striking.x, 2),
                "y": round(striking.y, 2),
                "car_id": striking.id,
                "pedestrian_id": None,
                "other_car_id": struck.id,
                "car_speed_ms": round(striking.speed, 2),
                "other_car_speed_ms": round(struck.speed, 2),
                "pedestrian_on_crosswalk": False,
                "cleared_t": None,
            }
        )
        a = self.accidents[-1]
        self.log_event("incident", accident_id=a["id"], accident_kind="car_car", cause=cause, x=a["x"], y=a["y"],
                       car_id=striking.id, other_id=struck.id)

    def _record_pedestrian_accident(self, vehicle, ped: Pedestrian) -> None:
        on_crosswalk = ped.edge_index > 0 and self.walk.crosswalk_between(
            ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index]
        ) is not None
        self.accidents.append(
            {
                "id": f"acc{len(self.accidents) + 1}",
                "kind": "car_pedestrian",
                "t": round(self._sim_time, 2),
                "x": round(ped.x, 2),
                "y": round(ped.y, 2),
                "car_id": vehicle.id,
                "pedestrian_id": ped.id,
                "other_car_id": None,
                "car_speed_ms": round(vehicle.speed, 2),
                "pedestrian_on_crosswalk": on_crosswalk,
                "cleared_t": None,
            }
        )
        a = self.accidents[-1]
        self.log_event("incident", accident_id=a["id"], accident_kind="car_pedestrian", x=a["x"], y=a["y"],
                       car_id=vehicle.id, other_id=ped.id)
        ped.status = "injured"
        ped.finished = True
        ped.loop = False
        ped.force.vx = ped.force.vy = 0.0
        vehicle.speed = 0.0
        if isinstance(vehicle, Car):
            vehicle.status = "crashed"  # stays at the scene, blocking its lane, until the accident is cleared

    # ---- witnesses, emergency calls, cameras ---------------------------------

    WITNESS_STATUSES = ("walking", "waiting", "arrived")

    def _tick_witnesses(self) -> None:
        """People who see an open accident may call it in (app/witnesses.py): a pedestrian
        stops and stands on the phone, a driver stuck nearby calls from the car. Each call
        goes to the call centre, which merges calls about the same incident."""
        t, rng = self._sim_time, self.incident_rng
        for acc in self.accidents + self.visible_fires():   # fires are records like accidents (engine/fires.py)
            if acc["cleared_t"] is not None:
                continue
            involved = {acc.get("car_id"), acc.get("other_car_id"), acc.get("pedestrian_id")}
            for ped in self.pedestrians.values():
                if ped.status in self.WITNESS_STATUSES and ped.id not in involved:
                    self._maybe_witness(acc, ped.id, "pedestrian", ped.x, ped.y, wit.PEDESTRIAN_REPORT_PROB)
                elif ped.status == "trapped" and ped.id == acc.get("pedestrian_id"):  # calls for help themselves
                    self._maybe_witness(acc, ped.id, "pedestrian", ped.x, ped.y, wit.STRANDED_DRIVER_REPORT_PROB)
            for car in self.cars.values():
                if car.status == "driving" and car.speed < 0.1 and car.id not in involved:
                    self._maybe_witness(acc, car.id, "driver", car.x, car.y, wit.DRIVER_REPORT_PROB)
                elif car.id in involved and car.status == "crashed":  # a driver in the crash, not hurt
                    prob = wit.STRANDED_DRIVER_REPORT_PROB if car.stalled else wit.INVOLVED_DRIVER_REPORT_PROB
                    self._maybe_witness(acc, car.id, "driver", car.x, car.y, prob)
        if self.false_call_rate_per_min > 0 and rng.random() < self.false_call_rate_per_min / 60.0 * self._dt:
            idle = [p for p in self.pedestrians.values() if p.status in self.WITNESS_STATUSES and p.id not in self._callers]
            if idle:
                ped = rng.choice(idle)
                angle, dist = rng.uniform(0, 2 * math.pi), rng.uniform(10.0, 30.0)
                spot = (ped.x + dist * math.cos(angle), ped.y + dist * math.sin(angle))
                self._callers[ped.id] = {"accident_id": None, "kind": "pedestrian", "phase": "noticed",
                                         "dial_at": t + rng.uniform(*wit.REACTION_S), "looks_at": spot}
                self.log_event("false_report_started", reporter_id=ped.id, x=round(spot[0], 1), y=round(spot[1], 1))
        for rid in list(self._callers):
            self._advance_caller(rid)

    def _maybe_witness(self, acc: dict, rid: str, kind: str, x: float, y: float, prob: float) -> None:
        key = (acc["id"], rid)
        if key in self._witnessed or rid in self._callers:
            return
        if math.hypot(acc["x"] - x, acc["y"] - y) > wit.WITNESS_RANGE_M:
            return
        if not self.corridors.line_of_sight(x, y, acc["x"], acc["y"]):
            return
        self._witnessed.add(key)
        if self.incident_rng.random() >= prob:
            return
        self._callers[rid] = {"accident_id": acc["id"], "kind": kind, "phase": "noticed",
                              "dial_at": self._sim_time + self.incident_rng.uniform(*wit.REACTION_S),
                              "looks_at": (acc["x"], acc["y"])}
        self.log_event("witness_noticed", accident_id=acc["id"], reporter_id=rid, reporter_kind=kind)

    def _advance_caller(self, rid: str) -> None:
        c, t = self._callers[rid], self._sim_time
        ped = self.pedestrians.get(rid) if c["kind"] == "pedestrian" else None
        car = self.cars.get(rid) if c["kind"] == "driver" else None
        if (ped is None and car is None) or (ped is not None and ped.status == "injured"):
            self._callers.pop(rid)
            return
        if c["phase"] == "noticed":
            if t < c["dial_at"]:
                return
            if ped is not None and self._on_crosswalk(ped):
                return  # finishes crossing first
            accident = next((a for a in self.accidents + self.fire.fires if a["id"] == c["accident_id"]), None)
            said = wit.report(accident, *c["looks_at"], self.incident_rng)
            call = self.call_centre.receive(t, rid, c["kind"], said, c["accident_id"])
            c.update(phase="calling", call_id=call["call_id"], ends_at=t + self.incident_rng.uniform(*wit.CALL_DURATION_S))
            if ped is not None:
                c["before"] = (ped.status, ped.finished)
                # where they come to rest at the goal force's 0.5 s relaxation: no stepping back
                c["hold"] = (ped.x + ped.force.vx * CALLER_STOP_S, ped.y + ped.force.vy * CALLER_STOP_S)
                ped.status, ped.finished = "calling", False
            self.log_event("call_started", call_id=call["call_id"], incident_id=call["incident_id"], reporter_id=rid,
                           reporter_kind=c["kind"], accident_id=c["accident_id"], category=said["category"],
                           x=said["x"], y=said["y"])
        elif t >= c["ends_at"]:
            if ped is not None:
                ped.status, ped.finished = c["before"]
            self._callers.pop(rid)
            self.log_event("call_ended", call_id=c["call_id"], reporter_id=rid)

    def _on_crosswalk(self, ped: Pedestrian) -> bool:
        if ped.status != "walking" or ped.edge_index == 0:
            return False
        return self.walk.crosswalk_between(ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index]) is not None

    def active_calls(self) -> list[dict]:
        """Who is on the phone right now, and for which call."""
        return [{"reporter_id": rid, "reporter_kind": c["kind"], "call_id": c["call_id"]}
                for rid, c in self._callers.items() if c["phase"] == "calling"]

    def _tick_cameras(self) -> None:
        t = self._sim_time
        vehicles = []
        for v in list(self.cars.values()) + list(self.units.values()):
            if isinstance(v, EmergencyVehicle) and v.status in ("on_scene", "cleaning"):
                continue  # a unit working a scene is not an anomaly
            if v.finished and v.status != "crashed":
                self._stopped_since.pop(v.id, None)
                continue
            if v.speed < 0.1:
                self._stopped_since.setdefault(v.id, t)
            else:
                self._stopped_since.pop(v.id, None)
            u, w = v.route_nodes[v.edge_index], v.route_nodes[v.edge_index + 1]
            at_red = self._light_state(u, w) in ("red", "yellow") and self.edge_length(u, w) - v.dist_on_edge < 40.0
            status = "stalled" if getattr(v, "stalled", False) else v.status  # a camera sees a stopped car, not a crash
            vehicles.append({"id": v.id, "x": v.x, "y": v.y, "speed": v.speed, "status": status,
                             "stopped_since": self._stopped_since.get(v.id), "at_red": at_red})
        for anomaly in cams.update(self.cameras, self.corridors, vehicles, t):
            if anomaly["anomaly_type"] == "collision":  # the call centre opens or joins an incident for it
                incident = self.call_centre.alert(t, anomaly["x"], anomaly["y"])
                anomaly["incident_id"] = incident["id"]
                self._camera_anomaly(anomaly["camera_id"], anomaly["vehicle_id"])["incident_id"] = incident["id"]
            self.log_event("camera_anomaly", **anomaly)

    def _camera_anomaly(self, camera_id: str, vehicle_id: str) -> dict:
        return next(c for c in self.cameras if c.id == camera_id).anomalies[vehicle_id]

    def _walkway_frame(self, ped: Pedestrian) -> tuple[float, float, float, float, float, float] | None:
        """(start x, y, unit dx, dy, length, free half-width) of the walk-network segment
        the pedestrian is on, or None while standing on a node."""
        if ped.edge_index == 0:
            return None
        a, b = ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index]
        ax, ay = self.walk.xy(a)
        bx, by = self.walk.xy(b)
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            return None
        on_crosswalk = self.walk.crosswalk_between(a, b) is not None
        half = (CROSSWALK_HALF_WIDTH_M if on_crosswalk else SIDEWALK_HALF_WIDTH_M) - BODY_RADIUS_M - WALKWAY_MARGIN_M
        return ax, ay, (bx - ax) / length, (by - ay) / length, length, half

    def _keep_on_walkway(self, ped: Pedestrian) -> None:
        """Hard limit: the body stays inside its sidewalk / crosswalk strip."""
        frame = self._walkway_frame(ped)
        if frame is None:
            return
        ax, ay, ux, uy, _, half = frame
        rx, ry = ped.force.x - ax, ped.force.y - ay
        along = rx * ux + ry * uy
        lateral = -rx * uy + ry * ux
        clamped = max(-half, min(half, lateral))
        if clamped != lateral:
            ped.force.x = ax + ux * along - uy * clamped
            ped.force.y = ay + uy * along + ux * clamped

    def _tick_pedestrians(self, dt: float) -> None:
        moving = [p for p in self.pedestrians.values() if not p.finished]

        # coarse neighbor lookup: only pedestrians within interaction range matter,
        # fine to brute-force at the pedestrian counts this sim targets (tens-hundreds)
        for ped in moving:
            calling = ped.status == "calling"
            if not calling:
                self._hold_at_kerb_if_signal_changed(ped)
            goal_x, goal_y = self._callers[ped.id]["hold"] if calling else self.walk.xy(ped.route_nodes[ped.edge_index])
            nearby = [
                other.force
                for other in self.pedestrians.values()
                if other is not ped
                and abs(other.force.x - ped.force.x) < 6.0
                and abs(other.force.y - ped.force.y) < 6.0
            ]
            frame = self._walkway_frame(ped)
            if frame is None:
                walkway_perp, offset = None, 0.0
            else:
                ax, ay, ux, uy, _, _ = frame
                walkway_perp = (-uy, ux)
                offset = -(ped.force.x - ax) * uy + (ped.force.y - ay) * ux
            step_pedestrian(
                ped.force,
                goal_x,
                goal_y,
                nearby,
                walkway_perp=walkway_perp,
                walkway_signed_offset=offset,
                dt=dt,
                stop_at_goal=ped.status in ("waiting", "calling"),
            )
            self._keep_on_walkway(ped)
            self._update_pedestrian_facing(ped, dt)

        # bodies never overlap; standing and injured people count as obstacles too.
        # Clamping to the walkway can push a separated pair back together, so alternate.
        bodies = [p.force for p in self.pedestrians.values()]
        for _ in range(SEPARATION_ROUNDS):
            if not separate(bodies, 2 * BODY_RADIUS_M):
                break
            for ped in moving:
                self._keep_on_walkway(ped)

        for ped in moving:
            if ped.status == "calling":
                continue  # stands where they took the phone out (_tick_witnesses)
            goal_x, goal_y = self.walk.xy(ped.route_nodes[ped.edge_index])
            if math.hypot(ped.force.x - goal_x, ped.force.y - goal_y) <= PED_ARRIVAL_RADIUS_M:
                self._pedestrian_advance(ped)

    def _update_pedestrian_facing(self, ped: Pedestrian, dt: float) -> None:
        """Turns the body toward where the pedestrian means to go (see ped_facing.py):
        across the crosswalk while waiting at a kerb, otherwise along the walk."""
        here = self.walk.xy(ped.route_nodes[ped.edge_index])
        if ped.status == "calling":  # on the phone, looking at what they report
            sx, sy = self._callers[ped.id]["looks_at"]
            target = math.atan2(sy - ped.y, sx - ped.x)
        elif ped.status == "waiting" and ped.edge_index + 1 < len(ped.route_nodes):
            there = self.walk.xy(ped.route_nodes[ped.edge_index + 1])
            target = math.atan2(there[1] - here[1], there[0] - here[0]) if there != here else None
        else:
            target = walking_facing(ped.force.vx, ped.force.vy, here[0] - ped.x, here[1] - ped.y)
        if target is not None:
            ped.heading = turn_toward(ped.heading, target, dt)

    def _hold_at_kerb_if_signal_changed(self, ped: Pedestrian) -> None:
        """A pedestrian who set off toward a signalised crosswalk but has not reached the
        asphalt yet goes back to waiting at the kerb when WALK ends (e.g. slowed down by a
        crowd). Distracted pedestrians keep going."""
        if ped.distracted or ped.edge_index == 0:
            return
        a, b = ped.route_nodes[ped.edge_index - 1], ped.route_nodes[ped.edge_index]
        cw = self.walk.crosswalk_between(a, b)
        if cw is None or not cw.signalised:
            return
        if self.traffic_lights[cw.node].walk_state == WALK:
            return
        (ax, ay), (bx, by) = self.walk.xy(a), self.walk.xy(b)
        length = math.hypot(bx - ax, by - ay) or 1.0
        along = ((ped.x - ax) * (bx - ax) + (ped.y - ay) * (by - ay)) / length
        if along < SIDEWALK_WIDTH_M / 2:  # the crosswalk end node is mid-sidewalk; asphalt starts here
            ped.edge_index -= 1
            ped.status = "waiting"
            ped.force.vx = ped.force.vy = 0.0  # stop at the kerb, momentum would carry them onto the road

    def _pedestrian_advance(self, ped: Pedestrian) -> None:
        if ped.edge_index >= len(ped.route_nodes) - 1:
            # just reached the final node in the route
            self._arrive_pedestrian(ped)
            return
        here, nxt = ped.route_nodes[ped.edge_index], ped.route_nodes[ped.edge_index + 1]
        cw = self.walk.crosswalk_between(here, nxt)
        if cw is not None and not ped.distracted and not self._pedestrian_may_cross(cw, ped, here):
            ped.status = "waiting"  # stands at the kerb until the signal / a gap allows it
            return
        ped.status = "walking"
        ped.edge_index += 1
        if cw is not None:
            self._occupied_crosswalks.add(cw.id)  # cars see them from this tick on

    def _arrive_pedestrian(self, ped: Pedestrian) -> None:
        ped.force.vx = 0.0
        ped.force.vy = 0.0
        ped.status = "arrived"
        ped.finished = True
        if ped.loop:
            ped.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)

    def _walk_to_node(self, ped: Pedestrian, dest_node: int, place_name: str | None = None) -> None:
        origin = self._trip_start_node(ped, dest_node)
        if origin == dest_node:
            ped.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        try:
            route = nx.shortest_path(self.walk.graph, origin, dest_node, weight=self._walk_weight())
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            ped.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return
        if len(route) < 2:
            ped.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        ped.route_nodes = route
        # goal is route_nodes[0], where we already stand: the first step then goes through
        # _pedestrian_advance, so a route that starts with a crosswalk waits for it too
        ped.edge_index = 0
        ped.status = "walking"
        ped.finished = False
        ped.depart_at = None
        ped.current_place_name = place_name

    def _route_to_node(self, car: Car, dest_node: int, place_name: str | None = None) -> None:
        # free the current spot, if any, before leaving
        if car.parking_spot_id:
            spot = self.parking_spots.get(car.parking_spot_id)
            if spot and spot.occupied_by == car.id:
                spot.occupied_by = None
            car.parking_spot_id = None

        origin = car.route_nodes[-1]
        if origin == dest_node:
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        try:
            route = nx.shortest_path(self.graph, origin, dest_node, weight="travel_time")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return
        if len(route) < 2:
            car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        car.route_nodes = route
        car.edge_index = 0
        car.dist_on_edge = 0.0
        car.lane = random.randrange(self.edge_lanes(route[0], route[1]))
        car.speed = 0.0
        car.status = "driving"
        car.finished = False
        car.depart_at = None
        car.parking_t = 0.0
        car.current_place_name = place_name
        self._place_on_route(car)

    @staticmethod
    def _route_end_dist(vehicle, length: float) -> float:
        end = getattr(vehicle, "end_dist", None)
        return length if end is None else min(end, length)

    def _arrived_at_route_end(self, vehicle, length: float, tolerance: float = ARRIVAL_TOLERANCE_M) -> bool:
        last_edge = vehicle.edge_index >= len(vehicle.route_nodes) - 2
        end = self._route_end_dist(vehicle, length)
        return last_edge and vehicle.dist_on_edge >= end - tolerance and vehicle.speed < 0.5

    def _advance_edge_if_needed(self, car: Car) -> None:
        u, v = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
        length = self.edge_length(u, v)
        if car.pending_spot_id is not None:  # a trip ending in a parking spot
            if self._arrived_at_route_end(car, length, PARKING_ARRIVAL_TOLERANCE_M):
                self._finish_trip(car)
                return
        elif self._arrived_at_route_end(car, length):
            car.dist_on_edge = length
        if car.dist_on_edge < length:
            return

        overflow = car.dist_on_edge - length
        car.edge_index += 1
        car.dist_on_edge = overflow

        if car.edge_index >= len(car.route_nodes) - 1:
            # end of a route without a parking spot (spawn_car, scenarios): stop here
            car.edge_index -= 1
            car.dist_on_edge = length
            car.speed = car.accel = 0.0
            car.status, car.finished = "unparked", True
            if car.loop:
                car.depart_at = self._sim_time + random.uniform(DWELL_MIN_S, DWELL_MAX_S)
            return

        # entering a new edge: clamp lane index to however many lanes it has
        nu, nv = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
        new_lanes = self.edge_lanes(nu, nv)
        car.lane = min(car.lane, new_lanes - 1)

    SCENE_ARRIVAL_RADIUS_M = 30.0  # stopped this close to the wreck, the crew walks the rest: a car
                                      # queued behind the wreck can hold the unit back (nobody
                                      # drives round a wreck yet)

    def _unit_reached_scene(self, unit: EmergencyVehicle) -> bool:
        """Close to the scene: to a wreck it was sent to, or to a unit already working the same incident."""
        for other in self.units.values():
            if (other is not unit and other.incident_id == unit.incident_id and other.status in ("on_scene", "cleaning")
                    and math.hypot(other.x - unit.x, other.y - unit.y) <= self.SCENE_ARRIVAL_RADIUS_M):
                return True
        if not unit.target_car_ids:
            return False
        for car_id in unit.target_car_ids:
            car = self.cars.get(car_id)
            if car is not None and math.hypot(car.x - unit.x, car.y - unit.y) <= self.SCENE_ARRIVAL_RADIUS_M:
                return True
        return False

    def _unit_advance_if_needed(self, unit: EmergencyVehicle) -> None:
        """Edge to edge like a car. A unit on a call stops behind the wreck (its IDM leader) or at
        its route end and works the scene; a returning one parks in its bay where it stands."""
        if unit.status in ("cleaning", "on_scene"):
            return  # standing at the scene, still in its lane (other traffic queues behind it)
        blocked_since = self._stopped_since.get(unit.id)
        if (unit.status == "dispatched" and blocked_since is not None and self._sim_time - blocked_since >= 2.0
                and self._unit_reached_scene(unit)):
            self._start_on_scene(unit)  # held up short of its spot (by a queue): the crew walks the rest
            return
        u, v = unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1]
        length = self.edge_length(u, v)
        if unit.edge_index >= len(unit.route_nodes) - 2:  # last edge: never runs past its end
            home = unit.status in ("returning", "to_hospital")
            tolerance = PARKING_ARRIVAL_TOLERANCE_M if home else ARRIVAL_TOLERANCE_M
            if self._arrived_at_route_end(unit, length, tolerance):
                if unit.status == "dispatched":
                    self._start_on_scene(unit)
                elif home:
                    if unit.status == "to_hospital":
                        self._deliver(unit)  # the station is the hospital: the casualty is handed over
                    self._unit_home(unit)
            return
        if unit.dist_on_edge < length:
            return
        unit.dist_on_edge -= length
        unit.edge_index += 1
        nu, nv = unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1]
        unit.lane = min(unit.lane, self.edge_lanes(nu, nv) - 1)

    def _start_on_scene(self, unit: EmergencyVehicle) -> None:
        unit.speed = unit.accel = 0.0
        unit.clean_t = 0.0
        unit.status = "on_scene" if unit.task == "respond" else "cleaning"
        unit.siren = unit.task == "respond"  # lights stay on at the scene; the old cleanup call has none
        self.log_event("unit_arrived", unit_id=unit.id, unit_kind=unit.kind, incident_id=unit.incident_id,
                       x=round(unit.x, 1), y=round(unit.y, 1))
        if unit.task == "respond":
            self._on_unit_arrived(unit)

    def _unit_home(self, unit: EmergencyVehicle) -> None:
        """Back in its bay, nearly stopped: parks where it stands (as Simulation._finish_trip)."""
        unit.speed = unit.accel = 0.0
        unit.start_dist = unit.end_dist = None
        unit.park_shift_start = unit.park_shift_end = 0.0
        unit.status, unit.finished, unit.target_car_ids = "idle", True, None
        unit.task = unit.incident_id = None
        unit.siren = False
        unit.params.v0, unit.params.a = type(unit.params)().v0, type(unit.params)().a
        unit.scene_shift = unit.lateral_offset = 0.0
        self.log_event("unit_back_at_station", unit_id=unit.id)
        self._try_dispatch_from_queue()

    def _tick_unit_scenes(self, dt: float) -> None:
        """Units on scene work for CLEANUP_DURATION_S, clear it, then drive back to their bay."""
        self._try_dispatch_from_queue()  # calls that waited for a free unit
        for unit in self.units.values():
            if unit.status != "cleaning":
                continue
            unit.clean_t += dt
            if unit.clean_t < CLEANUP_DURATION_S:
                continue
            if unit.target_car_ids:
                self._clear_scene(list(unit.target_car_ids))  # the crashed cars, or a car and the pedestrian it hit
            unit.target_car_ids = None
            self._head_home(unit)

    def _head_home(self, unit: EmergencyVehicle) -> None:
        """From where it stands, on along its lane and round the block to its bay (no U-turns)."""
        spot = self.parking_spots[unit.home_spot_id]
        here = (unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1])
        end = spot.dist_on_edge + unit.params.length / 2
        route = route_between(self._turns, here, unit.dist_on_edge, spot.edge, end, PULL_IN_M + PULL_IN_STRAIGHT_M)
        if route is None:
            return  # stays on scene; retried next tick
        unit.route_nodes, unit.edge_index = route, 0
        unit.start_dist, unit.end_dist = unit.dist_on_edge, end
        unit.park_shift_start, unit.park_shift_end = 0.0, self._parking_shift(spot)
        unit.status = "returning"

    def _lane_xy(self, u: int, v: int, lane: int, dist: float) -> tuple[float, float, float, float]:
        """(x, y, unit dx, unit dy) of a point `dist` metres along lane `lane` of edge u->v."""
        length = self.edge_length(u, v)
        num_lanes = self.edge_lanes(u, v)
        lane = min(lane, num_lanes - 1)
        t = 0.0 if length == 0 else min(1.0, max(dist, 0.0) / length)
        nu, nv = self.graph.nodes[u], self.graph.nodes[v]
        dx, dy = nv["x"] - nu["x"], nv["y"] - nu["y"]
        seg_len = math.hypot(dx, dy) or 1.0
        ux, uy = dx / seg_len, dy / seg_len  # unit vector along travel direction

        # perpendicular unit vector (right-hand side of travel direction), lane 0 = rightmost (curb side)
        perp_x, perp_y = uy, -ux

        # on a two-way street each direction's lanes must clear the centerline rather than
        # straddle it (lanes here are already this direction's half, see road_network.py),
        # so push the whole block outward by half its width; true one-way edges have no
        # opposing block to avoid and stay centered on the road
        is_oneway = bool(self.edge_data(u, v).get("oneway")) or not self.graph.has_edge(v, u)
        median_offset = 0.0 if is_oneway else num_lanes / 2.0

        lane_center_offset = (num_lanes - 1) / 2.0 - lane
        offset = (median_offset + lane_center_offset) * LANE_WIDTH_M
        return nu["x"] + dx * t + perp_x * offset, nu["y"] + dy * t + perp_y * offset, ux, uy

    def _turn_curve(self, a: int, b: int, c: int, lane: int) -> TurnCurve:
        """Drawn path through node b, from edge a->b onto edge b->c (cached: the graph is static)."""
        key = (a, b, c, lane)
        curve = self._turn_curves.get(key)
        if curve is None:
            len_in, len_out = self.edge_length(a, b), self.edge_length(b, c)
            zone = turn_zone(len_in, len_out)
            x0, y0, dx0, dy0 = self._lane_xy(a, b, lane, len_in - zone)
            x2, y2, dx2, dy2 = self._lane_xy(b, c, lane, zone)
            curve = TurnCurve.build((x0, y0), (dx0, dy0), (x2, y2), (dx2, dy2))
            self._turn_curves[key] = curve
        return curve

    def _reference_pose(self, route: list[int], i: int, dist: float, lane: int) -> tuple[float, float, float]:
        """Lane centreline point (x, y, heading) `dist` metres along route edge i: straight
        along the lane, on the turn curve within the turn zone of a node (turn_paths.py)."""
        u, v = route[i], route[i + 1]
        length = self.edge_length(u, v)
        if i + 2 < len(route):  # approaching a node with a next edge
            zone = turn_zone(length, self.edge_length(v, route[i + 2]))
            if dist > length - zone:
                return self._turn_curve(u, v, route[i + 2], lane).at((dist - (length - zone)) / (2 * zone))
        if i > 0:  # just past a node, coming from a previous edge
            zone = turn_zone(self.edge_length(route[i - 1], u), length)
            if dist < zone:
                return self._turn_curve(route[i - 1], u, v, lane).at((zone + dist) / (2 * zone))
        x, y, ux, uy = self._lane_xy(u, v, lane, dist)
        return x, y, math.atan2(uy, ux)

    def _reference_ahead(self, vehicle, offset: float) -> tuple[float, float, float]:
        """Reference pose `offset` metres ahead of (negative: behind) the vehicle's progress
        along its route, across edges; clamped to the route's start and end."""
        route, i = vehicle.route_nodes, vehicle.edge_index
        d = vehicle.dist_on_edge + offset
        while d < 0 and i > 0:
            i -= 1
            d += self.edge_length(route[i], route[i + 1])
        d = max(d, 0.0)
        while i + 2 < len(route) and d > self.edge_length(route[i], route[i + 1]):
            d -= self.edge_length(route[i], route[i + 1])
            i += 1
        d = min(d, self.edge_length(route[i], route[i + 1]))
        x, y, h = self._reference_pose(route, i, d, vehicle.lane)
        shift = self._park_shift_at(vehicle, i, d)
        if shift:
            x, y = x + math.sin(h) * shift, y - math.cos(h) * shift  # to the right of the lane
        return x, y, h

    def _path_pose(self, vehicle, offset: float) -> tuple[float, float, float]:
        """The path the vehicle steers along `offset` metres ahead of its progress, with its
        real direction: _reference_ahead gives the lane's heading, which ignores the sideways
        shift of pulling out or in."""
        x, y, _ = self._reference_ahead(vehicle, offset)
        bx, by, _ = self._reference_ahead(vehicle, offset - 0.25)
        ax, ay, _ = self._reference_ahead(vehicle, offset + 0.25)
        return x, y, math.atan2(ay - by, ax - bx)

    @staticmethod
    def _park_shift_at(vehicle, i: int, d: float) -> float:
        """How far right of its lane the vehicle should be at distance d on route edge i:
        in the parking lane before pulling out / after pulling in, easing (_park_ease)
        between the two over PULL_OUT_M / PULL_IN_M; a pull-in ends PULL_IN_STRAIGHT_M before
        the stop."""
        smooth = _park_ease
        shift = 0.0
        start_shift = getattr(vehicle, "park_shift_start", 0.0)
        if start_shift and i == 0 and vehicle.start_dist is not None:
            shift = start_shift * (1.0 - smooth((d - vehicle.start_dist) / PULL_OUT_M))
        end_shift = getattr(vehicle, "park_shift_end", 0.0)
        if end_shift and i == len(vehicle.route_nodes) - 2 and vehicle.end_dist is not None:
            curve_end = vehicle.end_dist - PULL_IN_STRAIGHT_M
            shift = max(shift, end_shift * smooth((d - (curve_end - PULL_IN_M)) / PULL_IN_M))
        # pulling over for a siren / passing cars pulled over; the police car's angled stop
        return shift + getattr(vehicle, "lateral_offset", 0.0) + IncidentResponse._scene_shift_at(vehicle, i, d)

    def _place_on_route(self, vehicle) -> None:
        """Puts a vehicle on its lane at its current progress, wheels straight."""
        vehicle.x, vehicle.y, vehicle.heading = self._reference_ahead(vehicle, 0.0)
        vehicle.steer = 0.0
        vehicle.accel = 0.0

    @staticmethod
    def _spec(vehicle) -> vd.VehicleSpec:
        return vd.AMBULANCE_SPEC if isinstance(vehicle, EmergencyVehicle) else vd.CAR_SPEC

    def _drive(self, vehicle, accel: float, dt: float) -> None:
        """One tick of motion: speed from `accel`, steering by pure pursuit toward the lane
        centreline ahead, pose from the bicycle model, progress (dist_on_edge) from where the
        front bumper actually is along the lane."""
        spec = self._spec(vehicle)
        v0 = vehicle.speed
        v1 = max(0.0, v0 + accel * dt)
        if v1 == 0.0 and accel < 0.0:
            dist = v0 * v0 / (-2.0 * accel)  # stops within the tick
        else:
            dist = (v0 + v1) / 2.0 * dt
        pose = (vehicle.x, vehicle.y, vehicle.heading)
        if self._in_parking_manoeuvre(vehicle):
            path = self._path_pose(vehicle, -spec.front_overhang)  # beside the front axle
            wanted = vd.stanley_steer(pose, path, v0, spec, PARKING_STANLEY_GAIN)
        else:
            target = self._reference_ahead(vehicle, -spec.front_to_rear_axle + vd.lookahead(v0, spec))
            wanted = vd.pure_pursuit_steer(pose, target[:2], spec)
        vehicle.steer = vd.limit_steer(wanted, vehicle.steer, max(v0, v1), dt, spec)
        if dist > 0.0:
            pose = vd.advance(pose, dist, vehicle.steer, spec)
        vehicle.x, vehicle.y, vehicle.heading = pose
        vehicle.accel = (v1 - v0) / dt
        vehicle.speed = v1
        self._ease_lateral(vehicle, dist)
        # progress: the reference point nearest the bumper, searched around where it should be
        rx, ry, rh = self._reference_ahead(vehicle, dist)
        along_error = (pose[0] - rx) * math.cos(rh) + (pose[1] - ry) * math.sin(rh)
        vehicle.dist_on_edge = max(vehicle.dist_on_edge, vehicle.dist_on_edge + dist + along_error)

    def _curve_accel(self, vehicle) -> float:
        """Braking needed to enter the next turns at a comfortable speed (lateral accel within
        comfort_lat_accel); +inf if no turn ahead is too fast."""
        if not getattr(vehicle, "slows_for_turns", True):
            return math.inf
        spec = self._spec(vehicle)
        route, i = vehicle.route_nodes, vehicle.edge_index
        v = vehicle.speed
        accel = math.inf
        to_node = -vehicle.dist_on_edge  # becomes the distance to node route[j + 1]
        for j in range(i, min(i + 3, len(route) - 2)):
            len_in, len_out = self.edge_length(route[j], route[j + 1]), self.edge_length(route[j + 1], route[j + 2])
            to_node += len_in
            if to_node > 80.0:
                break
            zone = turn_zone(len_in, len_out)
            to_curve = to_node - zone
            if to_curve < -2 * zone:
                continue  # already through it
            curve = self._turn_curve(route[j], route[j + 1], route[j + 2], vehicle.lane)
            v_allow = vd.curve_speed(curve.max_curvature, spec)
            if v > v_allow:
                accel = min(accel, (v_allow * v_allow - v * v) / (2.0 * max(to_curve, 1.0)))
        if i > 0:  # still inside the turn just taken
            len_in, len_out = self.edge_length(route[i - 1], route[i]), self.edge_length(route[i], route[i + 1])
            if vehicle.dist_on_edge < turn_zone(len_in, len_out):
                curve = self._turn_curve(route[i - 1], route[i], route[i + 1], vehicle.lane)
                v_allow = vd.curve_speed(curve.max_curvature, spec)
                if v > v_allow:
                    accel = min(accel, (v_allow - v) / 0.5)
        return accel

    def _distance_to_route_end(self, vehicle) -> float:
        """Metres the front bumper still has to go to the end of its route."""
        route, i = vehicle.route_nodes, vehicle.edge_index
        last = len(route) - 2
        rest = sum(self.edge_length(route[j], route[j + 1]) for j in range(i, last))
        end = self._route_end_dist(vehicle, self.edge_length(route[last], route[last + 1]))
        return rest + end - vehicle.dist_on_edge

    def _in_parking_manoeuvre(self, vehicle) -> bool:
        """Pulling out of the parking lane, or into it at the end of the trip."""
        start = getattr(vehicle, "start_dist", None)
        if getattr(vehicle, "park_shift_start", 0.0) and start is not None and vehicle.edge_index == 0:
            if vehicle.dist_on_edge < start + PULL_OUT_M:
                return True
        if getattr(vehicle, "park_shift_end", 0.0) and getattr(vehicle, "end_dist", None) is not None:
            return self._distance_to_route_end(vehicle) <= PULL_IN_M + PULL_IN_STRAIGHT_M
        return False

    def _pull_in_accel(self, car) -> float:
        """Slow to PARKING_SPEED_MS before the pull-in curve starts and stay that slow in it,
        like a driver turning into a bay: braking at PARKING_DECEL_MS2, started just in time."""
        if not getattr(car, "park_shift_end", 0.0) or getattr(car, "end_dist", None) is None:
            return math.inf  # not parking at the end of this trip
        if car.speed <= PARKING_SPEED_MS:
            return math.inf
        to_curve = self._distance_to_route_end(car) - PULL_IN_STRAIGHT_M - PULL_IN_M
        v, vp = car.speed, PARKING_SPEED_MS
        if to_curve <= 0.0:  # already in the pull-in: get down to parking speed now
            return (vp - v) / 0.5
        # brake only once it is time; brakes take PARKING_BRAKE_LEAD_S to build up (jerk
        # limit), so measure from where they will really bite, or the car overshoots and
        # brakes hard (once nearly stopping in the junction before the first bay)
        needed = (v * v - vp * vp) / (2.0 * max(to_curve - v * PARKING_BRAKE_LEAD_S, 0.1))
        return -needed if needed >= PARKING_DECEL_MS2 else math.inf

    def _route_end_accel(self, vehicle, edge_len: float) -> float:
        """Brake to a stop with the front bumper at the end of the route."""
        if vehicle.edge_index < len(vehicle.route_nodes) - 2:
            return math.inf
        end = self._route_end_dist(vehicle, edge_len)
        gap = end - vehicle.dist_on_edge + vehicle.params.s0  # IDM keeps s0: this stops it at the end
        return idm_acceleration(vehicle.speed, 0.0, gap, vehicle.params)

    # ---- serialization for websocket streaming -------------------------------

    def state(self) -> dict:
        return {
            "tick": self._tick_count,
            "cars": [
                {
                    "id": c.id,
                    "x": c.x,
                    "y": c.y,
                    "heading": round(c.heading, 3),
                    "speed": round(c.speed, 2),
                    "steer": round(c.steer, 3),
                    "accel": round(c.accel, 2),
                    "lane": c.lane,
                    "finished": c.finished,
                    "status": c.status,
                    "persona": c.persona,
                    "current_place_name": c.current_place_name,
                    "last_reason": c.last_reason,
                }
                for c in self.cars.values()
            ],
            "pedestrians": [
                {
                    "id": p.id,
                    "x": p.x,
                    "y": p.y,
                    "heading": round(p.heading, 3),
                    "speed": round(math.hypot(p.force.vx, p.force.vy), 2),
                    "status": p.status,  # walking | waiting (at a crosswalk) | arrived | injured
                    "persona": p.persona,
                    "current_place_name": p.current_place_name,
                    "last_reason": p.last_reason,
                }
                for p in self.pedestrians.values()
            ],
            # emergency vehicles, also while parked at their station (status "idle")
            "units": [
                {
                    "id": u.id,
                    "kind": u.kind,
                    "station_id": u.station_id,
                    "x": u.x,
                    "y": u.y,
                    "heading": round(u.heading, 3),
                    "speed": round(u.speed, 2),
                    "steer": round(u.steer, 3),
                    "accel": round(u.accel, 2),
                    "status": u.status,  # idle | dispatched | cleaning | on_scene | to_hospital | returning
                    "siren": u.siren,
                    "incident_id": u.incident_id,
                }
                for u in self.units.values()
            ],
            "traffic_lights": [
                {
                    "node_id": light.node_id,
                    # per-approach state, keyed by the upstream node id as a string (JSON keys are strings)
                    "approaches": {
                        str(u): light.state_for_approach(u) for u in light.approach_phase
                    },
                    "walk": light.walk_state,
                }
                for light in self.traffic_lights.values()
            ],
            "accidents": [a for a in self.accidents if a["cleared_t"] is None],
            "fires": self.fires_state(),
            "rain_mm_per_hr": round(self.rain_intensity(), 1),
            "flood": self.flood_state(),
            "occupied_spots": [
                spot.id for spot in self.parking_spots.values() if spot.occupied_by is not None
            ],
        }

    def road_geometry(self) -> dict:
        nodes = [
            {"id": n, "x": d["x"], "y": d["y"], "has_light": n in self.traffic_lights}
            for n, d in self.graph.nodes(data=True)
        ]
        edges = [
            {
                "u": u,
                "v": v,
                "length": d.get("length", 0.0),
                "lanes": d.get("lanes", 1),
                "width": d.get("width", LANE_WIDTH_M),
            }
            for u, v, d in self.graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}

    def parking_geometry(self) -> dict:
        spots = []
        for spot in self.parking_spots.values():
            x, y, heading = spot_world_xy(self.graph, spot, LANE_WIDTH_M)
            spots.append({
                "id": spot.id, "x": round(x, 2), "y": round(y, 2), "heading": round(heading, 3),
                "length": SPOT_LENGTH_M, "width": PARKING_LANE_M,  # the bay, for drawing its markings
            })
        return {"spots": spots}

    def walk_geometry(self) -> dict:
        """Street cross-section, crosswalks and stop lines, for drawing the map."""
        u0, v0 = next(iter(self.graph.edges()))
        crosswalks = []
        for cw in self.walk.crosswalks.values():
            (ax, ay), (bx, by) = self.walk.xy(cw.a), self.walk.xy(cw.b)
            crosswalks.append(
                {"id": cw.id, "a": [round(ax, 2), round(ay, 2)], "b": [round(bx, 2), round(by, 2)],
                 "width": CROSSWALK_WIDTH_M, "signalised": cw.signalised, "node": cw.node}
            )
        stop_lines = []
        for u, v in self.graph.edges():
            if self.walk.stop_setback(u, v) is None:
                continue
            nu, nv = self.graph.nodes[u], self.graph.nodes[v]
            length = self.edge_length(u, v)
            t = max(0.0, length - self._stop_setback(u, v)) / length
            ux, uy = (nv["x"] - nu["x"]) / length, (nv["y"] - nu["y"]) / length
            outer = driving_outer_offset(self.graph, u, v)
            inner = outer - self.edge_lanes(u, v) * LANE_WIDTH_M  # 0 on a two-way street, -outer on a one-way
            cx = nu["x"] + (nv["x"] - nu["x"]) * t
            cy = nu["y"] + (nv["y"] - nu["y"]) * t
            mid = (inner + outer) / 2
            stop_lines.append(
                {"approach": [u, v], "x": round(cx + uy * mid, 2), "y": round(cy - ux * mid, 2),
                 "heading": round(math.atan2(uy, ux), 3), "length": round(outer - inner, 2)}
            )
        return {
            "profile": {
                "driving_outer_m": driving_outer_offset(self.graph, u0, v0),
                "parking_lane_m": PARKING_LANE_M,
                "kerb_m": kerb_offset(self.graph, u0, v0),
                "sidewalk_width_m": SIDEWALK_WIDTH_M,
            },
            "crosswalks": crosswalks,
            "stop_lines": stop_lines,
        }

    def places_geometry(self) -> dict:
        return {"places": self.places}

    def cameras_geometry(self) -> dict:
        """The traffic (CCTV) cameras, for the viewer's camera view: id, where (its junction), how far it sees,
        and the streets it looks down (the junction's neighbours)."""
        return {"cameras": [{"id": c.id, "node": c.node, "x": c.x, "y": c.y, "range_m": cams.CAMERA_RANGE_M,
                             "looks_toward": sorted(set(self.graph.successors(c.node)))} for c in self.cameras]}

    def stations_geometry(self) -> dict:
        """Each station: its bays (centre and the lane's heading) and the point on the building
        line behind the sidewalk, facing the street, where the viewer draws the building."""
        out = []
        for st in self.stations:
            bays = []
            for spot_id in st.spot_ids:
                x, y, h = spot_world_xy(self.graph, self.parking_spots[spot_id], 0.0)
                bays.append({"spot_id": spot_id, "x": round(x, 3), "y": round(y, 3), "heading": round(h, 4)})
            x, y, h = bays[0]["x"], bays[0]["y"], bays[0]["heading"]
            back = PARKING_LANE_M / 2 + SIDEWALK_WIDTH_M  # bay centre to the building line, to the right
            out.append({
                "id": st.id, "kind": st.kind, "unit_kind": st.unit_kind, "label": st.label, "bays": bays,
                "front": [round(x + math.sin(h) * back, 3), round(y - math.cos(h) * back, 3)],
                "facing": round(h + math.pi / 2, 4),  # from the building toward the street
            })
        return {"stations": out}

    def buildings_geometry(self) -> dict:
        return {"buildings": [b.as_dict() for b in self.buildings.values()]}

    def recent_decisions(self, since: int = 0) -> dict:
        """Decision log entries with seq > `since`, plus the cursor (latest seq) to poll from next."""
        new_entries = [d for d in self.decision_log if d["seq"] > since]
        return {
            "decisions": new_entries,
            "cursor": self._decision_seq,
        }
