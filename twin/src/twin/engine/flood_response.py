"""What a flood does in the city, and how it is answered. A mixin of Simulation (sim.py), which wires it;
the water itself is in flood.py.

Every tick the rain fills each flood zone (Simulation.flood_zones, one per street) and the drain and pump
empty it. Rain over a zone is the heavier of the city's (Simulation.rain) and the zone's own downpour
(FloodZone.rain). flood_street blocks a zone's drain and brings a downpour over it: the fire-simulator
of floods, which flood_risk also fires at random. A blocked drain is cleared once the water is gone. Then:

Vehicles. In water deeper than WADE_DEPTH_M at its front a vehicle slows down, to WADE_SPEED_MS at
NO_ENTRY_DEPTH_M. Once the low point is NO_ENTRY_DEPTH_M deep, careful drivers no longer drive into
the street (both directions): they are re-routed when they can, and otherwise stop at their stop line,
as for a barrier. Below REOPEN_DEPTH_M it opens to them again. A car whose front is in water of
STALL_DEPTH_M or more stalls: it stops where it is (status "crashed", Car.stalled), blocks its lane,
and is an incident (accident kind "flooded_car") with its driver stranded inside. Only a driver who
ignores the water (Car.ignores_flood: a red-light runner, or a staged driver) drives in that deep; water rising round a car
already in the dip can catch a careful one too. Emergency units wade through and never stall.

Pedestrians. On a sidewalk deeper than PED_WADE_DEPTH_M they slow to PED_WADE_SPEED_MS. Routes go
round wet sidewalks when there is a way, and never along a piece with water of PED_STOP_DEPTH_M or more
anywhere on it. A careful pedestrian who sees water that deep just ahead, and deeper than where they
stand, turns back and takes another way (or, when there is none, waits at the dry end). One who stands
still (dwelling, on the phone) as the water reaches their feet walks out to the nearest dry spot. In
PED_TRAP_DEPTH_M or more anyone is trapped (status "trapped"): they hold on where they are and call for
help, an incident (accident kind "trapped_pedestrian"). Only someone who ignores the water
(Pedestrian.ignores_flood: someone who ignores signals too, or a staged walker) walks in that deep; water rising fast round a careful one
could catch them too.

The answer. A fire truck (dispatch_unit, unit_type fire) at a flood starts a rescue: its crew gets out
everyone trapped in that zone, one at a time, RESCUE_S each (a stranded driver, a trapped pedestrian,
anyone trapped later while they are there). A pedestrian is led out to the nearest dry sidewalk and walks
on from there. The scene is cleared (stalled cars towed away, the accidents closed) once nobody is left
in the water, the water at every stalled car is down to TOW_DEPTH_M, and the police (if sent) have been
there POLICE_MIN_ON_SCENE_S. The drainage pump of a zone (set_pump_state) adds its capacity to the storm
drain's.
"""
from __future__ import annotations

import math
import random

import networkx as nx

from twin.engine import flood as fl
from twin.engine.fire_hazard import walk_weight
from twin.engine.flood import RainProfile
from twin.engine.models import Car
from twin.engine.parking import free_spots_near, spot_world_xy
from twin.engine.routing import route_between

RAIN_THRESHOLD_MM_H = 0.5   # lighter than this counts as dry, for the rain_started / rain_stopped events
RESCUE_S = 20.0             # firefighters wade to the car, open it and help the driver out
WADE_TAU_S = 1.0            # a vehicle in water brakes to its wading speed over about this long
WET_WALK_PENALTY = 50.0     # a wet sidewalk piece counts as this many times its length when routing
PUMP_FIND_RADIUS_M = 60.0   # set_pump_state by incident_id: the pump of the zone this close to it
FLOOD_KINDS = ("flooded_car", "trapped_pedestrian")
LOOK_AHEAD_M = 1.5          # a walking pedestrian looks this far ahead for deep water
EDGE_SAMPLES = 12           # points along a walk edge where the water is measured, for routing
ESCAPE_DEPTH_COST = 40.0    # leading someone out: a metre in 0.1 m of water costs as 5 dry ones
# flood_street's downpour: (seconds from now, mm/h); 120 mm/h for two minutes floods a dip with a blocked drain
DOWNPOUR = ((0.0, 0.0), (20.0, 120.0), (140.0, 120.0), (170.0, 0.0))
FLOOD_WINDOW_S = (20.0, 150.0)  # flood_risk: when a street prone to it floods


class FloodResponse:
    # ---- the water ---------------------------------------------------------------------

    def rain_intensity(self) -> float:
        """The heaviest rain falling anywhere now (mm/h)."""
        return max([self.rain.intensity(self._sim_time)] + [self.rain_at(z) for z in self.flood_zones])

    def rain_at(self, zone) -> float:
        return max(self.rain.intensity(self._sim_time), zone.rain.intensity(self._sim_time))

    # ---- floods on demand, and at random -------------------------------------------------

    def flood_street(self, zone_id: str, cause: str = "operator") -> dict:
        """Block the storm drain of a street's flood zone and bring a downpour over it (the flood
        simulator). Idempotent: a zone already under its own downpour answers "duplicate"."""
        zone = next((z for z in self.flood_zones if z.id == zone_id), None)
        if zone is None:
            return {"status": "rejected", "reason": "unknown_zone"}
        t = self._sim_time
        result = {"zone_id": zone.id, "street": f"{zone.street[0]}-{zone.street[1]}", "pump_id": zone.pump_id}
        if zone.rain.points and zone.rain.points[-1][0] > t:
            return {"status": "duplicate", **result, "rain_until_s": round(zone.rain.points[-1][0], 1)}
        zone.rain = RainProfile(tuple((t + dt, mm) for dt, mm in DOWNPOUR))
        zone.drain_blocked = True
        self.log_event("flood_triggered", zone_id=zone.id, street=list(zone.street), cause=cause)
        return {"status": "started", **result, "rain_until_s": round(zone.rain.points[-1][0], 1)}

    def arm_floods(self, risk: float, window: tuple[float, float] = FLOOD_WINDOW_S) -> list[str]:
        """Each zone floods (flood_street) with probability `risk`, once, at a random moment in `window`.
        On its own generator, so a seed's traffic stays the same. Returns the zones that will flood."""
        rng = random.Random(f"floods-{self._flood_seed}")
        self._planned_floods = {z.id: rng.uniform(*window) for z in self.flood_zones if risk and rng.random() < risk}
        return sorted(self._planned_floods)

    def _tick_planned_floods(self) -> None:
        for zone_id, at in list(self._planned_floods.items()):
            if self._sim_time >= at:
                del self._planned_floods[zone_id]
                self.flood_street(zone_id, cause="random")

    def _tick_flood(self, dt: float) -> None:
        if not self.flood_zones and not self.rain.points:
            return
        self._tick_planned_floods()
        changed = False
        for zone in self.flood_zones:
            rain = self.rain_at(zone)
            raining = rain >= RAIN_THRESHOLD_MM_H
            if raining != zone.raining:
                zone.raining = raining
                self.log_event("rain_started" if raining else "rain_stopped", zone_id=zone.id, mm_per_hr=round(rain, 1))
            before = zone.depth_m
            zone.step(dt, rain)
            depth = zone.depth_m
            if before < fl.WADE_DEPTH_M <= depth:
                self.log_event("water_rising", zone_id=zone.id, depth_m=round(depth, 3))
            if not zone.no_entry and depth >= fl.NO_ENTRY_DEPTH_M:
                zone.no_entry, changed = True, True
                self.log_event("street_flooded", zone_id=zone.id, depth_m=round(depth, 3), street=list(zone.street))
            elif zone.no_entry and depth < fl.REOPEN_DEPTH_M:
                zone.no_entry, changed = False, True
                self.log_event("street_passable", zone_id=zone.id, depth_m=round(depth, 3), street=list(zone.street))
            if before > 0.0 and depth == 0.0:
                self.log_event("water_drained", zone_id=zone.id)
            if zone.drain_blocked and depth == 0.0 and not raining:
                zone.drain_blocked = False
                self.log_event("drain_cleared", zone_id=zone.id)
        if changed:
            self.flooded_edges = {e for z in self.flood_zones if z.no_entry
                                  for e in (z.street, z.street[::-1]) if self.graph.has_edge(*e)}
            self._rebuild_turns_open()
            if self.flooded_edges:
                self._reroute_around_closures()

    def water_depth_at(self, x: float, y: float) -> float:
        return max((z.depth_at(x, y) for z in self.flood_zones), default=0.0)

    def flood_state(self) -> list[dict]:
        """Per zone: depth, wet length, flows, pump, whether careful drivers stay out."""
        return [{"id": z.id, "depth_m": round(z.depth_m, 3), "wet_half_length_m": round(z.wet_half_length_m, 2),
                 "inflow_m3s": round(z.inflow_m3s, 3), "outflow_m3s": round(z.outflow_m3s, 3),
                 "pump_id": z.pump_id, "pump_on": z.pump_on, "no_entry": z.no_entry,
                 "rain_mm_per_hr": round(self.rain_at(z), 1), "drain_blocked": z.drain_blocked,
                 "street": list(z.street)} for z in self.flood_zones]

    # ---- vehicles ------------------------------------------------------------------------

    def _no_entry_edges(self, vehicle) -> set:
        """Edges this vehicle will not drive into: barriers (cars only), and flooded streets for careful drivers."""
        if not isinstance(vehicle, Car):
            return set()
        if getattr(vehicle, "ignores_flood", False) or vehicle.through_flood or not self.flooded_edges:
            return self.closed_edges
        return self.closed_edges | self.flooded_edges

    def _turns_for(self, car):
        """The turn graph a car's trips are routed on."""
        return self._turns_barriers if getattr(car, "ignores_flood", False) else self._turns_open

    def _water_accel(self, vehicle) -> float:
        """A vehicle in water brakes to a speed it can wade at, the deeper the slower."""
        if not self.flood_zones:
            return math.inf
        depth = self.water_depth_at(vehicle.x, vehicle.y)
        if depth < fl.WADE_DEPTH_M:
            return math.inf
        frac = min(1.0, (depth - fl.WADE_DEPTH_M) / (fl.NO_ENTRY_DEPTH_M - fl.WADE_DEPTH_M))
        cap = vehicle.params.v0 + (fl.WADE_SPEED_MS - vehicle.params.v0) * frac
        return (cap - vehicle.speed) / WADE_TAU_S

    def _park_elsewhere(self, car) -> bool:
        """A careful driver who cannot reach their reserved spot without driving through a flooded street
        (the spot is on it, or the only way there is: no U-turns) takes the nearest free spot they can
        reach instead, nearest to the old one first (on a corner street that leads only into the flood, that
        is a spot further along it). Barriers alone (no flood) keep the old rule: the car stops before them."""
        spot = self.parking_spots.get(car.pending_spot_id) if car.pending_spot_id else None
        if spot is None or not self.flooded_edges or getattr(car, "ignores_flood", False):
            return False
        route, i = car.route_nodes, car.edge_index
        here = (route[i], route[i + 1])
        x, y, _ = spot_world_xy(self.graph, spot, 0.0)
        for cand, _walk in free_spots_near(self.graph, self.parking_spots, x, y, len(self.parking_spots), exclude=spot.id):
            if cand.edge in self.flooded_edges or cand.edge in self.closed_edges:
                continue
            end = cand.dist_on_edge + car.params.length / 2
            new = route_between(self._turns_open, here, car.dist_on_edge, cand.edge, end, 5.0)
            if new is None:
                continue
            spot.occupied_by, cand.occupied_by = None, car.id
            if i > 0 or car.start_dist is None or car.dist_on_edge > car.start_dist + 10.0:
                car.park_shift_start, car.start_dist = 0.0, None
            car.pending_spot_id, car.end_dist, car.park_shift_end = cand.id, end, self._parking_shift(cand)
            car.route_nodes, car.edge_index = new, 0
            self._boxes.release(car.id)
            self.log_event("car_parks_elsewhere", car_id=car.id, from_spot=spot.id, to_spot=cand.id, reason="flooded")
            return True
        # no way round and no spot it can reach: it can only drive on (it cannot turn round), so it does,
        # while the water is still shallow (the street has only just flooded)
        car.through_flood = True
        self.log_event("car_drives_through_flood", car_id=car.id)
        return True

    def _tick_stalls(self) -> None:
        if not self.flood_zones:
            return
        for car in self.cars.values():
            if car.finished or car.status != "driving":
                continue
            depth = self.water_depth_at(car.x, car.y)
            if depth >= fl.STALL_DEPTH_M:
                self._stall(car, depth)

    def _stall(self, car: Car, depth: float) -> None:
        car.status, car.stalled = "crashed", True
        car.speed = car.accel = 0.0
        car.yielding = False
        self._boxes.release(car.id)
        zone = max(self.flood_zones, key=lambda z: z.depth_at(car.x, car.y))
        self.accidents.append({
            "id": f"acc{len(self.accidents) + 1}", "kind": "flooded_car", "cause": "drove_into_flood",
            "t": round(self._sim_time, 2), "x": round(car.x, 2), "y": round(car.y, 2),
            "car_id": car.id, "pedestrian_id": None, "other_car_id": None,
            "car_speed_ms": 0.0, "pedestrian_on_crosswalk": False, "water_depth_m": round(depth, 3),
            "flood_zone_id": zone.id, "cleared_t": None,
        })
        a = self.accidents[-1]
        self.log_event("incident", accident_id=a["id"], accident_kind="flooded_car", cause="drove_into_flood",
                       x=a["x"], y=a["y"], car_id=car.id, other_id=None, water_depth_m=a["water_depth_m"])

    # ---- pedestrians -------------------------------------------------------------------

    def _tick_waders(self) -> None:
        """Pedestrians in water slow down; they get their own pace back on dry ground."""
        if not self.flood_zones:
            return
        for ped in self.pedestrians.values():
            wet = self.water_depth_at(ped.x, ped.y) >= fl.PED_WADE_DEPTH_M
            if wet and ped.id not in self._dry_speed:
                self._dry_speed[ped.id] = ped.force.desired_speed
                ped.force.desired_speed = min(ped.force.desired_speed, fl.PED_WADE_SPEED_MS)
            elif not wet and ped.id in self._dry_speed:
                ped.force.desired_speed = self._dry_speed.pop(ped.id)

    def _walk_edge_depths(self) -> dict:
        """The deepest water along each wet walk edge (sampled), at most once per tick. Water on a
        sidewalk mid-edge counts, not only at its ends: the sidewalk nodes are 20 m apart."""
        t, depths = self._walk_depths
        if t == self._sim_time:
            return depths
        depths = {}
        if any(z.depth_m > fl.KERB_HEIGHT_M for z in self.flood_zones):
            for u, v in self.walk.graph.edges:
                (ax, ay), (bx, by) = self.walk.xy(u), self.walk.xy(v)
                deepest = max(self.water_depth_at(ax + (bx - ax) * k / EDGE_SAMPLES, ay + (by - ay) * k / EDGE_SAMPLES)
                              for k in range(EDGE_SAMPLES + 1))
                if deepest > 0.0:
                    depths[(u, v)] = depths[(v, u)] = deepest
        self._walk_depths = (self._sim_time, depths)
        return depths

    def _walk_weight(self):
        """Edge weight for pedestrian routes: length on dry ground (plus the fire penalty); a wet piece costs WET_WALK_PENALTY
        times its length, and one with water of PED_STOP_DEPTH_M or more is not walked at all (None)."""
        dry = walk_weight(self.hazard_walk_edges)  # fire_hazard.py: a penalty next to a burning building
        depths = self._walk_edge_depths() if self.flood_zones else {}
        if not depths:
            return dry

        def weight(u, v, d):
            deepest = depths.get((u, v), 0.0)
            if deepest >= fl.PED_STOP_DEPTH_M:
                return None
            return dry(u, v, d) * (WET_WALK_PENALTY if deepest >= fl.PED_WADE_DEPTH_M else 1.0)
        return weight

    def _tick_ped_flood(self) -> None:
        """Careful pedestrians keep out of deep water; anyone caught in it is trapped (see the docstring)."""
        if not self.flood_zones or all(z.depth_m <= fl.KERB_HEIGHT_M for z in self.flood_zones):
            return
        for ped in list(self.pedestrians.values()):
            if ped.status in ("injured", "trapped", "calling") or ped.id in self._trapped_peds:
                continue
            depth = self.water_depth_at(ped.x, ped.y)
            if ped.id in self._rescued_peds:
                if depth < fl.PED_WADE_DEPTH_M:
                    self._rescued_peds.discard(ped.id)  # out of the water: careful from now on
                continue
            if depth >= fl.PED_TRAP_DEPTH_M:
                self._trap(ped, depth)
                continue
            if ped.ignores_flood:
                continue
            if ped.finished or ped.status == "waiting":  # standing still
                if depth >= fl.PED_WADE_DEPTH_M:
                    self._walk_out(ped, depth)
                continue
            gx, gy = self.walk.xy(ped.route_nodes[ped.edge_index])
            dist = math.hypot(gx - ped.x, gy - ped.y)
            if dist < 1e-6:
                continue
            ahead = self.water_depth_at(ped.x + (gx - ped.x) / dist * LOOK_AHEAD_M, ped.y + (gy - ped.y) / dist * LOOK_AHEAD_M)
            if ahead >= fl.PED_STOP_DEPTH_M and ahead > depth + 0.01:
                self._turn_back(ped, ahead)

    def _turn_back(self, ped, ahead: float) -> None:
        """Back to the node behind, then on to the destination by a way without deep water, if any."""
        i = ped.edge_index
        behind, dest = ped.route_nodes[i - 1] if i > 0 else ped.route_nodes[i], ped.route_nodes[-1]
        try:
            route = nx.shortest_path(self.walk.graph, behind, dest, weight=self._walk_weight())
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            route = [behind]  # no dry way: waits at the dry end, and tries again on their next trip
        ped.route_nodes, ped.edge_index, ped.status = route, 0, "walking"
        self.log_event("pedestrian_turned_back", pedestrian_id=ped.id, water_depth_m=round(ahead, 3),
                       way_round=len(route) > 1)

    def _escape_route(self, ped) -> list[int] | None:
        """The way out of the water: from either end of the piece the pedestrian is on to the nearest
        sidewalk node with dry feet, shallow water preferred to deep."""
        depths = self._walk_edge_depths()

        def cost(u, v, d):
            return d["length"] * (1.0 + ESCAPE_DEPTH_COST * depths.get((u, v), 0.0))
        i = ped.edge_index
        starts = {ped.route_nodes[i], ped.route_nodes[i - 1] if i > 0 else ped.route_nodes[i]}
        if ped.spawn_piece:
            starts |= set(ped.spawn_piece)
        best, best_cost = None, math.inf
        for start in starts:
            sx, sy = self.walk.xy(start)
            here = math.hypot(sx - ped.x, sy - ped.y) * (1.0 + ESCAPE_DEPTH_COST * self.water_depth_at(ped.x, ped.y))
            dist, paths = nx.single_source_dijkstra(self.walk.graph, start, weight=cost)
            for node, c in dist.items():
                if here + c < best_cost and self.water_depth_at(*self.walk.xy(node)) < fl.PED_WADE_DEPTH_M:
                    best, best_cost = paths[node], here + c
        return best

    def _walk_out(self, ped, depth: float) -> None:
        route = self._escape_route(ped)
        if route is None:
            return
        ped.route_nodes, ped.edge_index, ped.status, ped.finished, ped.depart_at = route, 0, "walking", False, None
        ped.spawn_piece = None
        self._rescued_peds.add(ped.id)  # on their way out: no turning back on the way
        self.log_event("pedestrian_leaves_water", pedestrian_id=ped.id, water_depth_m=round(depth, 3))

    def _trap(self, ped, depth: float) -> None:
        ped.status, ped.finished = "trapped", True
        ped.force.vx = ped.force.vy = 0.0
        self._trapped_peds.add(ped.id)
        zone = max(self.flood_zones, key=lambda z: z.depth_at(ped.x, ped.y))
        cause = "walked_into_flood" if ped.ignores_flood else "caught_by_rising_water"
        self.accidents.append({
            "id": f"acc{len(self.accidents) + 1}", "kind": "trapped_pedestrian", "cause": cause,
            "t": round(self._sim_time, 2), "x": round(ped.x, 2), "y": round(ped.y, 2),
            "car_id": None, "pedestrian_id": ped.id, "other_car_id": None,
            "car_speed_ms": 0.0, "pedestrian_on_crosswalk": False, "water_depth_m": round(depth, 3),
            "flood_zone_id": zone.id, "cleared_t": None,
        })
        a = self.accidents[-1]
        self.log_event("incident", accident_id=a["id"], accident_kind="trapped_pedestrian", cause=cause,
                       x=a["x"], y=a["y"], car_id=None, other_id=ped.id, pedestrian_id=ped.id,
                       water_depth_m=a["water_depth_m"])

    # ---- the answer: rescue, towing, the pump --------------------------------------------

    def _flood_accidents(self, zone_id: str) -> list[dict]:
        return [a for a in self.accidents if a["cleared_t"] is None and a.get("flood_zone_id") == zone_id]

    def _flood_street_edges(self, accident: dict) -> list[tuple[int, int]]:
        """The street a flood accident is in, both ways (the police close it all); none for other accidents."""
        zone = next((z for z in self.flood_zones if z.id == accident.get("flood_zone_id")), None)
        if zone is None:
            return []
        return [e for e in (zone.street, zone.street[::-1]) if self.graph.has_edge(*e)]

    def _on_fire_unit_arrived(self, unit, response: dict, accident: dict) -> None:
        if accident["kind"] in FLOOD_KINDS and "rescue_start_t" not in response:
            response.update(rescue_start_t=self._sim_time, rescue_unit=unit.id, rescued=[], rescuing=None)
            self._set_phase(response, "rescuing")
            self.log_event("rescue_started", incident_id=response["incident_id"], unit_id=unit.id,
                           car_id=accident["car_id"], pedestrian_id=accident["pedestrian_id"],
                           trapped=len(self._flood_accidents(accident["flood_zone_id"])))

    def _tick_rescue(self, response: dict) -> None:
        """The fire crew gets the people trapped in the zone out, one at a time, nearest the truck first."""
        if "rescue_start_t" not in response:
            return
        t, current = self._sim_time, response["rescuing"]
        if current is None:
            waiting = [a for a in self._flood_accidents(response["flood_zone_id"]) if a["id"] not in response["rescued"]]
            if not waiting:
                return
            truck = self.units.get(response["rescue_unit"])
            nxt = min(waiting, key=lambda a: math.hypot(a["x"] - truck.x, a["y"] - truck.y) if truck else 0.0)
            response["rescuing"] = {"accident_id": nxt["id"], "since": t}
            if response["phase"] != "rescuing":
                self._set_phase(response, "rescuing")
            return
        if t - current["since"] < RESCUE_S:
            return
        accident = next(a for a in self.accidents if a["id"] == current["accident_id"])
        response["rescued"].append(accident["id"])
        response["rescuing"] = None
        if accident["kind"] == "flooded_car":
            self.log_event("driver_rescued", incident_id=response["incident_id"], car_id=accident["car_id"])
            return
        ped = self.pedestrians.get(accident["pedestrian_id"])
        accident["cleared_t"] = round(t, 2)  # safe on dry ground: nothing left to clear for them
        if ped is not None:
            self._lead_out(ped)
        self.log_event("pedestrian_rescued", incident_id=response["incident_id"], pedestrian_id=accident["pedestrian_id"],
                       accident_id=accident["id"])

    def _lead_out(self, ped) -> None:
        """Firefighters walk a rescued pedestrian out of the water; then they carry on with their day."""
        self._trapped_peds.discard(ped.id)
        self._rescued_peds.add(ped.id)
        ped.ignores_flood = False
        ped.loop = True
        route = self._escape_route(ped)
        if route is not None:
            ped.route_nodes, ped.edge_index = route, 0
        ped.status, ped.finished, ped.depart_at = "walking", False, None

    def _flood_scene_done(self, response: dict, police_done: bool) -> bool:
        """Nobody left in the water, every stalled car shallow enough to tow, police done: the scene can be cleared."""
        self._tick_rescue(response)
        if "rescue_start_t" not in response:
            return False
        open_ = self._flood_accidents(response["flood_zone_id"])
        if response["rescuing"] is not None or any(a["id"] not in response["rescued"] for a in open_):
            return False
        deep = any(self._depth_at_accident(a) > fl.TOW_DEPTH_M for a in open_ if a["kind"] == "flooded_car")
        phase = "waiting_for_water" if deep else "towing"
        if response["phase"] != phase:
            self._set_phase(response, phase)
        return not deep and police_done

    def _clear_flood_scene(self, response: dict) -> None:
        """Tows away every stalled car of the zone and closes its flood accidents, then clears the scene."""
        for a in self._flood_accidents(response["flood_zone_id"]):
            if a["car_id"]:
                self.remove_car(a["car_id"])
            a["cleared_t"] = round(self._sim_time, 2)
        self._clear_wrecks(response)

    def _depth_at_accident(self, accident: dict) -> float:
        car = self.cars.get(accident["car_id"]) if accident["car_id"] else None
        return self.water_depth_at(car.x, car.y) if car is not None else 0.0

    def set_pump(self, state: str, pump_id: str | None = None, incident_id: str | None = None, by: str | None = None) -> dict:
        """Call (the Twin's set_pump_state actuator): start or stop a drainage pump. The pump is `pump_id`,
        or the one of the flood zone at an incident. Idempotent: "duplicate" when it already is in that state."""
        if state not in ("on", "off"):
            return {"status": "rejected", "reason": "unknown_state"}
        if pump_id is not None:
            zone = next((z for z in self.flood_zones if z.pump_id == pump_id), None)
            if zone is None:
                return {"status": "rejected", "reason": "unknown_pump"}
        elif incident_id is not None:
            incident = self.call_centre.incident(incident_id)
            if incident is None:
                return {"status": "rejected", "reason": "unknown_incident"}
            near = [(math.hypot(z.centre_xy[0] - incident["x"], z.centre_xy[1] - incident["y"]), z) for z in self.flood_zones]
            near = [nz for nz in near if nz[0] <= PUMP_FIND_RADIUS_M]
            if not near:
                return {"status": "rejected", "reason": "no_pump_at_incident"}
            zone = min(near, key=lambda nz: nz[0])[1]
        else:
            return {"status": "rejected", "reason": "pump_id_or_incident_id_required"}
        on = state == "on"
        result = {"pump_id": zone.pump_id, "state": state, "capacity_m3s": zone.pump_m3s if on else 0.0}
        if zone.pump_on == on:
            return {"status": "duplicate", **result}
        zone.pump_on = on
        self.log_event("pump_started" if on else "pump_stopped", pump_id=zone.pump_id, zone_id=zone.id, by=by,
                       depth_m=round(zone.depth_m, 3))
        return {"status": state, **result}
