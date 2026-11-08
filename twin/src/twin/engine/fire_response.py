"""What the city does about building fires: a mixin of Simulation (sim.py), which wires it.

The fire itself (engine/fires.py) is a model of its own. This is the part that touches the rest
of the simulation: starting fires on request, writing them into the ground-truth timeline
(`fire_started`, `fire_extinguished`), and what the frame and `state()` show of them.
"""
from __future__ import annotations

import math

import networkx as nx

from twin.engine.fire_hazard import (
    HAZARD_RADIUS_M, hazard_road_edges, hazard_walk_edges, walk_weight, with_car_penalties,
)
from twin.engine.fires import SMOKE_AT, SMOKE_VISIBLE_M, VISIBLE_AT
from twin.engine.parking import spot_world_xy
from twin.engine.routing import route_between

SCENE_REACH_M = 20.0        # a unit may stop in any lane this close to the burning building
EXTINGUISH_S = 4.0          # a fire truck on scene puts out one building in this long (as the old cleanup call: 4 s)
NOTHING_FOUND_S = 10.0      # police or an ambulance sent to a fire look round this long, then leave


class FireResponse:
    def ignite_building(self, building_id: str, cause: str = "operator") -> dict:
        """Call (the Twin's fire simulator): set a building on fire. Idempotent: a building that is
        already burning answers "duplicate" with its fire."""
        if building_id not in self.buildings:
            return {"status": "rejected", "reason": "unknown_building"}
        burning = self.fire.burning(building_id)
        if burning is not None:
            return {"status": "duplicate", "fire_id": burning["id"], "building_id": building_id}
        fire = self.fire.ignite(building_id, self._sim_time, cause)
        self._log_fire_started(fire)
        return {"status": "ignited", "fire_id": fire["id"], "building_id": building_id}

    def _tick_fires(self) -> None:
        for fire in self.fire.tick(self._sim_time):
            self._log_fire_started(fire)
        for fire in self.fire.open():
            if fire.get("smoke_t") is None and self.fire.intensity(fire, self._sim_time) >= SMOKE_AT:
                self._smoke_detected(fire)
        key = tuple(sorted(f["id"] for f in self.fire.open()))
        if key != self._hazard_key:
            self._hazard_key = key
            self._update_hazards()

    # ---- keeping away from it ---------------------------------------------------------

    def _update_hazards(self) -> None:
        """The streets and sidewalks next to a burning building are avoided: cars and pedestrians
        already on their way take another route when there is one (fire_hazard.py)."""
        points = [(f["x"], f["y"]) for f in self.fire.open()]
        self.hazard_edges = hazard_road_edges(self.graph, points)
        self.hazard_walk_edges = hazard_walk_edges(self.walk.graph, points)
        self._rebuild_turns_open()
        self._retarget_trips()
        self._reroute_around_closures()
        self._reroute_pedestrians()

    def _retarget_trips(self) -> None:
        """A car heading for a parking spot next to a burning building (or waiting to leave for one)
        picks the nearest free spot that is not, and drives there. With no other spot, a car still
        parked stays parked, and one already on the road goes on to its first spot."""
        for car in list(self.cars.values()):
            old = self.parking_spots.get(car.pending_spot_id) if car.pending_spot_id else None
            if old is None or old.edge not in self.hazard_edges or car.status not in ("parked", "driving"):
                continue
            driving = car.status == "driving"
            here = (car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]) if driving else None
            if here == old.edge:
                continue  # already on its street
            old.occupied_by, car.pending_spot_id = None, None
            new = self._choose_spot(car, *spot_world_xy(self.graph, old, 0.0)[:2])
            end = new.dist_on_edge + car.params.length / 2 if new else 0.0
            route = route_between(self._turns_open, here, car.dist_on_edge, new.edge, end, 5.0) if new and driving else None
            if new is None or (driving and route is None):
                if driving:
                    old.occupied_by, car.pending_spot_id = car.id, old.id   # no other way: on to the first spot
                else:
                    car.depart_at = self._sim_time + 30.0                  # stays where it is
                continue
            new.occupied_by, car.pending_spot_id = car.id, new.id
            if driving:
                car.end_dist, car.park_shift_end = end, self._parking_shift(new)
                self._switch_route(car, route)

    def _reroute_pedestrians(self) -> None:
        """A pedestrian whose way still crosses an avoided piece of sidewalk, or a crosswalk there, goes
        another way from the node they are heading for, when that has fewer of them."""
        weight = walk_weight(self.hazard_walk_edges)
        for ped in self.pedestrians.values():
            if ped.status not in ("walking", "waiting") or ped.finished or len(ped.route_nodes) < 2:
                continue
            nodes, i = ped.route_nodes, ped.edge_index
            here = nodes[i]
            ahead = [frozenset(e) for e in zip(nodes[i:], nodes[i + 1:])]
            if not any(e in self.hazard_walk_edges for e in ahead):
                continue
            try:
                way = nx.shortest_path(self.walk.graph, here, nodes[-1], weight=weight)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            if sum(frozenset(e) in self.hazard_walk_edges for e in zip(way, way[1:])) < sum(e in self.hazard_walk_edges for e in ahead):
                ped.route_nodes = nodes[:i] + way

    def near_fire(self, x: float, y: float, radius_m: float = HAZARD_RADIUS_M) -> bool:
        """Whether (x, y) is within `radius_m` of a burning building."""
        return any(math.hypot(f["x"] - x, f["y"] - y) <= radius_m for f in self.fire.open())

    def _smoke_detected(self, fire: dict) -> None:
        """The building's smoke sensor trips: the call centre opens an incident at the fire, or joins the
        one already open there (a neighbour that caught fire), and the sensor's readings carry its id."""
        fire["smoke_t"] = round(self._sim_time, 2)
        fire["incident_id"] = self.call_centre.alert(self._sim_time, fire["x"], fire["y"])["id"]
        self.log_event("smoke_detected", fire_id=fire["id"], building_id=fire["building_id"], incident_id=fire["incident_id"])

    def visible_fires(self) -> list[dict]:
        """The fires strong enough for people on the street to see (and call in)."""
        return [f for f in self.fire.open() if self.fire.intensity(f, self._sim_time) >= VISIBLE_AT]

    def smoke_near(self, x: float, y: float, radius_m: float = SMOKE_VISIBLE_M) -> bool:
        """Whether a camera at (x, y) sees the smoke of a fire: it rises above the roofs, so
        buildings do not hide it, only distance does."""
        return any(math.hypot(f["x"] - x, f["y"] - y) <= radius_m and self.fire.intensity(f, self._sim_time) >= SMOKE_AT
                   for f in self.fire.open())

    def _log_fire_started(self, fire: dict) -> None:
        self.log_event("fire_started", fire_id=fire["id"], building_id=fire["building_id"], cause=fire["cause"],
                       source_fire_id=fire["source_fire_id"], x=fire["x"], y=fire["y"])

    def fires_state(self) -> list[dict]:
        """The fires burning now, with their strength (0 to 1)."""
        return [{**f, "intensity": round(self.fire.intensity(f, self._sim_time), 2)} for f in self.fire.open()]

    def fires_frame(self) -> list[list]:
        """[building id, strength, fire id] per burning building, for the recording."""
        return [[f["building_id"], f["intensity"], f["id"]] for f in self.fires_state()]

    # ---- the fire brigade -------------------------------------------------------------

    def _on_unit_arrived_at_fire(self, unit, response: dict) -> None:
        """A unit reached an incident that has a fire (response_for). A fire truck starts putting it out;
        police and ambulances have nothing to do there and leave after a look round."""
        if unit.kind == "fire" and self._response_fires(response):
            response["fire_work"] = {"unit": unit.id, "current": None, "since": self._sim_time}
            self._set_phase(response, "firefighting")
            self.log_event("firefighting_started", unit_id=unit.id, incident_id=response["incident_id"],
                           fire_id=response["fire_id"])
        else:
            response.setdefault("looked_round", {})[unit.id] = self._sim_time

    def _fastest_lane_position(self, kind: str, x: float, y: float, station_id: str | None = None):
        """Where a unit of `kind` (of `station_id` when given) stops for a fire at (x, y): of the lane
        positions in front of it (a street has a lane each way, and a car cannot turn round), the one it
        reaches soonest. Returns (edge, distance along it, best unit as _best_unit gives it), the last
        None if no unit can go."""
        spots = []
        for u, v in self.graph.edges():
            if self.edge_length(u, v) < 30.0:
                continue
            ax, ay, ux, uy = self._lane_xy(u, v, 0, 0.0)
            along = max(15.0, min(self.edge_length(u, v) - 15.0, (x - ax) * ux + (y - ay) * uy))
            d = math.hypot(ax + ux * along - x, ay + uy * along - y)
            if d <= SCENE_REACH_M:
                spots.append((d, (u, v), along))
        spots.sort()
        best = None
        for _, edge, along in spots:
            found = self._best_unit(kind, edge, along, station_id)
            if found is not None and (best is None or found[2] < best[2][2]):
                best = (edge, along, found)
        if best is None:
            edge, along = self._nearest_lane_position(x, y)
            return edge, along, None
        return best

    def _response_fires(self, response: dict) -> list[dict]:
        """The fires this response is about that still burn: the one it was sent to, and every burning
        building joined to them, also the ones that caught fire after the unit was sent."""
        found: dict[str, dict] = {}
        for fire_id in list(response["fire_ids"]):
            for fire in self.fire.cluster(fire_id):
                found[fire["id"]] = fire
        response["fire_ids"] |= set(found)
        return list(found.values())

    def _tick_fire_scene(self, response: dict) -> None:
        """The truck on scene puts out the burning buildings one after another, nearest first; when the
        last is out the scene is cleared, the units drive home, and the response closes."""
        t = self._sim_time
        units = [self.units[uid] for uid in response["units"].values()]
        on_scene = [u for u in units if u.status == "on_scene" and u.incident_id == response["incident_id"]]
        burning = self._response_fires(response)
        work = response.get("fire_work")
        truck = self.units.get(work["unit"]) if work else None
        if truck is not None and truck.status == "on_scene" and "cleared_t" not in response:
            if work["current"] is None and burning:
                nearest = min(burning, key=lambda f: math.hypot(f["x"] - truck.x, f["y"] - truck.y))
                work.update(current=nearest["id"], since=t)
            elif work["current"] is not None and t - work["since"] >= EXTINGUISH_S:
                fire = self.fire.get(work["current"])
                self.fire.extinguish(fire["id"], t)
                self.log_event("fire_extinguished", fire_id=fire["id"], building_id=fire["building_id"],
                               incident_id=response["incident_id"], unit_id=truck.id)
                work["current"] = None
                burning = self._response_fires(response)
        if not burning and (work is not None or on_scene or not response["units"]) and "cleared_t" not in response:
            response["cleared_t"] = t
            self._set_phase(response, "cleared")
            self.log_event("scene_cleared", incident_id=response["incident_id"], fire_id=response["fire_id"])
        for unit in on_scene:
            looked = t - response.get("looked_round", {}).get(unit.id, math.inf)
            if "cleared_t" in response or (unit.kind != "fire" and looked >= NOTHING_FOUND_S):
                self._leave_scene(unit, response, siren=False)
        if "cleared_t" in response and "closed" not in response and all(u.status == "idle" for u in units):
            self._close(response)
