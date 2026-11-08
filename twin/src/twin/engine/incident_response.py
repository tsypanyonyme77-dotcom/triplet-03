"""What happens around an incident once units are on their way: sirens, the barrier, and
(later in this module) the crew and onlookers. A mixin of Simulation (sim.py), which wires it.

Sirens. A unit with its siren on (driving to a scene or a hospital) drives faster
(SIREN_V0_MS), and every car ahead of it in its lane within YIELD_AHEAD_M pulls right
by YIELD_SHIFT_M and stops (Car.yielding). The unit drives past on the centre line
(emergency_driving.py). Sideways moves happen only while moving (at most LATERAL_PER_M per
metre driven), so nothing slides; a car already standing still (at a red light, in a queue)
cannot pull over, and the unit passes it the same way.

Police at the scene. The police car stops 10.5 m upstream of the ambulance's spot, and its
path ends in a sideways move to the left (scene_shift, POLICE_ANGLE_SHIFT_M, centred
POLICE_ANGLE_LEAD_M before the stop): it stops about 15-25 degrees across its lane (measured
16 and 22.5 in ped-hit and car-crash), shielding the scene from traffic coming up behind. On arrival it closes the street of every wreck,
both directions (set_barrier_state): a barrier at each end. Cars that have not reached a
closed edge are re-routed round it when they can; those that cannot stop before it. Cars
already on it stay queued. Units ignore barriers.
"""
from __future__ import annotations

import math

from twin.engine.flood_response import FLOOD_KINDS
from twin.engine.fire_hazard import with_car_penalties
from twin.engine.idm import idm_acceleration
from twin.engine.models import Car
from twin.engine.ped_facing import turn_toward
from twin.engine.pedestrian import Pedestrian
from twin.engine.routing import route_between
from twin.engine.social_force import SocialForceState

SIREN_V0_MS = 19.0          # desired speed with the siren on (68 km/h)
SIREN_ACCEL_MS2 = 2.5
YIELD_AHEAD_M = 60.0        # cars this far ahead of a siren in its lane pull over
YIELD_SHIFT_M = 1.5         # ... this far to the right, then stop
YIELD_BRAKE_MS2 = 2.5
YIELD_CREEP_MS = 2.0
YIELD_CLEAR_OF_LINE_M = 6.0  # cars this close to their stop line (or past it) do not pull over        # ... rolling at most this fast until it is over
PASS_SKIP_SHIFT_M = 1.4     # a car pulled over at least this far is no longer the unit's leader
LATERAL_PER_M = 0.25        # sideways metres per metre driven
POLICE_ANGLE_SHIFT_M = 3.5  # the police car's path ends in a move this far left ...
POLICE_ANGLE_RAMP_M = 6.0
POLICE_ANGLE_LEAD_M = 3.0   # ... centred this far before its stop: it stops about 15-25 degrees across its lane
BARRIER_FROM_NODE_M = 13.0  # a barrier stands this far into a closed street, past its crosswalk
CREW_WALK_MS = 1.6          # ambulance crew walking to the casualty
CREW_ACCEL_MS2 = 2.0
CREW_DOOR_BEHIND_M = 0.8    # they get out and load at this far behind the ambulance
CREW_KNEEL_SIDE_M = 0.9     # each kneels this far from the casualty, one on either side
TREAT_S = 8.0
CARRY_MS = 1.0              # carrying the casualty back
CASUALTY_INSIDE_M = 1.5     # a loaded casualty is this far inside the ambulance from its rear
DRIVER_OUT_SIDE_M = 2.2     # the struck driver lies this far left of the car's centre line
CLEAR_AFTER_LOAD_S = 8.0    # the scene is cleared (wrecks towed) this long after the casualty is aboard,
POLICE_MIN_ON_SCENE_S = 10.0  # ... and once the police (if sent) have been there this long
NOTHING_FOUND_S = 10.0      # units at a false report look round this long, then leave


def _ease(t: float) -> float:
    return 0.0 if t <= 0 else 1.0 if t >= 1 else t * t * t * (t * (6 * t - 15) + 10)


class IncidentResponse:
    # ---- sirens ---------------------------------------------------------------------

    def _siren_units(self) -> list:
        return [u for u in self.units.values() if u.siren and not u.finished
                and u.status in ("dispatched", "to_hospital")]

    def _tick_yielding(self) -> None:
        """Marks the cars that must pull over for a siren, and releases those it has passed."""
        sirens = self._siren_units()
        for car in self.cars.values():
            if car.finished or car.status != "driving":
                car.yielding = False
                continue
            u_, v_ = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
            if car.dist_on_edge > self.edge_length(u_, v_) - self._stop_setback(u_, v_) - YIELD_CLEAR_OF_LINE_M:
                car.yielding = False  # at or past its stop line: clears the junction first, never stops in it
                continue
            # only a siren on the car's own edge makes it pull over: one still before the junction would
            # have a car stop in the junction's exit, in the way of its own turn (and wait for it, which
            # waits for the unit to pass: neither would move). A car coming the other way pulls over too.
            unit = next((u for u in sirens if self._behind_in_lane(u, car, YIELD_AHEAD_M, same_edge_only=True)
                         or self._head_on(u, car)), None)
            if unit is not None and not car.yielding:
                self.log_event("car_yielding", car_id=car.id, unit_id=unit.id)
            car.yielding = unit is not None

    def _behind_in_lane(self, unit, car, within: float, same_edge_only: bool = False) -> bool:
        """`unit`'s front is behind `car`'s front, in the same lane, at most `within` metres back
        along the unit's route (this edge or the next, unless `same_edge_only`)."""
        route, i = unit.route_nodes, unit.edge_index
        cu, cv = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
        if (route[i], route[i + 1]) == (cu, cv) and unit.lane == car.lane:
            gap = car.dist_on_edge - unit.dist_on_edge
            return 0.0 < gap <= within
        if not same_edge_only and i + 2 < len(route) and (route[i + 1], route[i + 2]) == (cu, cv) and unit.lane == car.lane:
            gap = self.edge_length(route[i], route[i + 1]) - unit.dist_on_edge + car.dist_on_edge
            return gap <= within
        return False

    def _siren_leader(self, unit, cars_here: list, i: int):
        """The vehicle a siren unit follows: the nearest ahead in its lane that has not pulled over."""
        for lead in reversed(cars_here[:i]):
            if isinstance(lead, Car) and lead.yielding and lead.lateral_offset >= PASS_SKIP_SHIFT_M:
                continue
            if self._passes(unit, lead):
                continue
            return lead
        return None

    def _yield_accel(self, car) -> float:
        """A car pulling over for a siren rolls on at a crawl while it moves right (it can only
        move sideways while moving), then brakes to a stop. One held at a red light stays."""
        if not getattr(car, "yielding", False):
            return math.inf
        if car.lateral_offset >= PASS_SKIP_SHIFT_M:
            return -YIELD_BRAKE_MS2 if car.speed > 0.0 else 0.0
        return (YIELD_CREEP_MS - car.speed) / 1.0

    def _lateral_target(self, vehicle) -> float:
        if isinstance(vehicle, Car):
            return YIELD_SHIFT_M if vehicle.yielding else 0.0
        if vehicle.siren and vehicle.status in ("dispatched", "to_hospital"):
            return self._centre_line_target(vehicle)
        return 0.0

    def _ease_lateral(self, vehicle, dist: float) -> None:
        """Moves the vehicle's sideways offset toward its target, only as far as it drove allows."""
        target = self._lateral_target(vehicle)
        step = LATERAL_PER_M * dist
        cur = vehicle.lateral_offset
        vehicle.lateral_offset = min(target, cur + step) if target > cur else max(target, cur - step)

    @staticmethod
    def _scene_shift_at(vehicle, i: int, d: float) -> float:
        """The police car's angled stop: a sideways move centred on the end of its route."""
        s = getattr(vehicle, "scene_shift", 0.0)
        end = getattr(vehicle, "end_dist", None)
        if not s or end is None or i != len(vehicle.route_nodes) - 2 or vehicle.status != "dispatched":
            return 0.0
        return s * _ease((d - (end - POLICE_ANGLE_RAMP_M / 2 - POLICE_ANGLE_LEAD_M)) / POLICE_ANGLE_RAMP_M)

    # ---- barriers ---------------------------------------------------------------------

    def set_barrier_state(self, edges: list[tuple[int, int]], closed: bool, by: str | None = None) -> None:
        """Close (or reopen) road edges to cars. Closing re-routes the cars that can avoid them."""
        changed = [e for e in edges if (e in self.closed_edges) != closed]
        if not changed:
            return
        for e in changed:
            (self.closed_edges.add if closed else self.closed_edges.discard)(e)
        self._rebuild_turns_open()
        self.log_event("barrier_placed" if closed else "barrier_removed", edges=[list(e) for e in changed], by=by)
        if closed:
            self._reroute_around_closures()

    def set_road_state(self, state: str, road_id: str | None = None, incident_id: str | None = None,
                       by: str | None = None) -> dict:
        """Call (the Twin's set_barrier_state actuator): close or reopen a street, both directions.
        The street is `road_id` ("<u>-<v>", e.g. "1-2") or the street of an incident's wrecks.
        Idempotent: closing a closed street (or opening an open one) returns "duplicate"."""
        if state not in ("closed", "open"):
            return {"status": "rejected", "reason": "unknown_state"}
        if road_id is not None:
            try:
                u, v = (int(n) for n in road_id.split("-"))
            except ValueError:
                return {"status": "rejected", "reason": "unknown_road"}
            edges = [e for e in ((u, v), (v, u)) if self.graph.has_edge(*e)]
            if not edges:
                return {"status": "rejected", "reason": "unknown_road"}
        elif incident_id is not None:
            incident = self.call_centre.incident(incident_id)
            if incident is None:
                return {"status": "rejected", "reason": "unknown_incident"}
            response = self.response_for(incident)
            accident = self._open_accident(response["accident_id"]) if response["accident_id"] else None
            if accident is None:
                return {"status": "rejected", "reason": "no_open_accident_at_incident"}
            edges = self._wreck_edges(accident)
            if state == "closed":
                response["closed_edges"] = sorted(set(response.get("closed_edges", [])) | set(edges))
        else:
            return {"status": "rejected", "reason": "road_id_or_incident_id_required"}
        closed = state == "closed"
        changed = [e for e in edges if (e in self.closed_edges) != closed]
        ids = sorted({f"barrier-{min(e)}-{max(e)}" for e in edges})
        if not changed:
            return {"status": "duplicate", "barrier_ids": ids, "state": state}
        self.set_barrier_state(edges, closed, by=by)
        return {"status": "closed" if closed else "opened", "barrier_ids": ids, "state": state,
                "edges": [list(e) for e in changed]}

    def _reroute_around_closures(self) -> None:
        """Cars whose route still has to cross a closed street, or one next to a burning building, take
        another way when there is one (and, for a closed street, a better one: it has none of them)."""
        avoid = self.closed_edges | self.hazard_edges
        for car in self.cars.values():
            if car.finished or car.status != "driving" or car.pending_spot_id is None:
                continue
            route, i = car.route_nodes, car.edge_index
            here = (route[i], route[i + 1])
            ahead = [(route[j], route[j + 1]) for j in range(i + 1, len(route) - 1)]
            no_entry = self._no_entry_edges(car)  # barriers, and flooded streets for careful drivers
            avoid = no_entry | self.hazard_edges
            if here in no_entry or not any(e in avoid for e in ahead):
                continue
            spot = self.parking_spots[car.pending_spot_id]
            new = route_between(self._turns_for(car), here, car.dist_on_edge, spot.edge, car.end_dist, 5.0)
            if new is None:
                self._park_elsewhere(car)  # its spot is on a flooded street: parks elsewhere (flood_response.py)
                continue  # otherwise no way round: it will stop before the barrier
            if sum(e in avoid for e in zip(new[1:], new[2:])) >= sum(e in avoid for e in ahead):
                continue  # no better than the way it is going
            self._switch_route(car, new)

    def _switch_route(self, car, new_route: list[int]) -> None:
        """A driving car takes `new_route`, which starts on the edge it is on."""
        if car.edge_index > 0 or car.start_dist is None or car.dist_on_edge > car.start_dist + 10.0:
            car.park_shift_start, car.start_dist = 0.0, None
        car.route_nodes, car.edge_index = new_route, 0
        self._boxes.release(car.id)
        self.log_event("car_rerouted", car_id=car.id)

    def _rebuild_turns_open(self) -> None:
        """The turn graphs cars route on, rebuilt when barriers, fires or floods change: without closed
        streets and with a penalty on streets next to a fire (_turns_barriers, for drivers who ignore
        water), and also without flooded streets (_turns_open, everyone else)."""
        turns = self._turns.copy()
        turns.remove_nodes_from([e for e in self.closed_edges if e in turns])
        self._turns_barriers = with_car_penalties(turns, self.hazard_edges) if self.hazard_edges else turns
        self._turns_open = self._turns_barriers.copy()
        self._turns_open.remove_nodes_from([e for e in self.flooded_edges if e in self._turns_open])

    def _closed_ahead_accel(self, vehicle, edge_len: float, stop_line_dist: float) -> float:
        """A car whose next edge is closed (or flooded, for a careful driver) stops at the stop line,
        as for a red light."""
        blocked = self._no_entry_edges(vehicle)
        if not blocked:
            return math.inf
        route, i = vehicle.route_nodes, vehicle.edge_index
        if i + 2 >= len(route) or (route[i + 1], route[i + 2]) not in blocked:
            return math.inf
        if vehicle.dist_on_edge >= stop_line_dist:
            return math.inf
        return idm_acceleration(vehicle.speed, 0.0, stop_line_dist - vehicle.dist_on_edge, vehicle.params)

    def barrier_geometry(self) -> list[list]:
        """[u, v, x, y, heading] per closed edge: across the street, just inside it from u."""
        out = []
        for u, v in sorted(self.closed_edges):
            a, b = self.graph.nodes[u], self.graph.nodes[v]
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            n = math.hypot(dx, dy) or 1.0
            out.append([u, v, round(a["x"] + dx / n * BARRIER_FROM_NODE_M, 2), round(a["y"] + dy / n * BARRIER_FROM_NODE_M, 2),
                        round(math.atan2(dy, dx), 4)])
        return out

    def _wreck_edges(self, accident: dict) -> list[tuple[int, int]]:
        edges = self._flood_street_edges(accident)  # flood_response.py: the flooded street, both ways
        for car_id in (accident["car_id"], accident.get("other_car_id")):
            car = self.cars.get(car_id) if car_id else None
            if car is None:
                continue
            u, v = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
            for e in ((u, v), (v, u)):
                if self.graph.has_edge(*e) and e not in edges:
                    edges.append(e)
        return edges

    # ---- arrival --------------------------------------------------------------------

    def _on_unit_arrived(self, unit) -> None:
        response = self.responses.get(unit.incident_id)
        if response is None:
            return
        if response["phase"] == "dispatched":
            self._set_phase(response, "on_scene")
        if response.get("fire_id") is not None:
            self._on_unit_arrived_at_fire(unit, response)
            return
        accident = self._open_accident(response["accident_id"]) if response["accident_id"] else None
        if accident is None and response.get("flood_zone_id"):
            # a flood scene stays one until it is cleared, even once the people trapped in it are out
            accident = next(a for a in self.accidents if a["id"] == response["accident_id"])
        if accident is None:
            response.setdefault("nothing_found_t", self._sim_time)  # a false report: leave after a look round
            return
        if unit.kind == "police":
            response["police_on_scene_t"] = self._sim_time
            edges = self._wreck_edges(accident)
            response["closed_edges"] = sorted(set(response.get("closed_edges", [])) | set(edges))
            self.set_barrier_state(edges, True, by=unit.id)
        elif unit.kind == "fire":
            self._on_fire_unit_arrived(unit, response, accident)  # flood_response.py: rescue a stranded driver
        elif unit.kind == "ambulance" and "crew" not in response and accident["kind"] not in FLOOD_KINDS:
            self._crew_out(unit, response, accident)  # a flooded car's driver is not hurt: the fire crew gets them out

    def _set_phase(self, response: dict, phase: str) -> None:
        response["phase"] = phase
        self.log_event("incident_phase", incident_id=response["incident_id"], phase=phase)

    # ---- the ambulance crew -------------------------------------------------------------

    def _crew_out(self, amb, response: dict, accident: dict) -> None:
        """Two crew members get out at the back of the ambulance and walk to the casualty: the
        pedestrian who was hit, or the driver of the struck car (who gets out beside it)."""
        if accident["kind"] == "car_pedestrian":
            casualty = self.pedestrians.get(accident["pedestrian_id"])
        else:
            casualty = self._driver_out(self.cars.get(accident["other_car_id"]) or self.cars.get(accident["car_id"]))
        if casualty is None:
            return
        rx, ry = self._unit_rear(amb, CREW_DOOR_BEHIND_M)
        hx, hy = math.cos(amb.heading), math.sin(amb.heading)
        members = []
        for side, sign in (("a", 1.0), ("b", -1.0)):
            ped = Pedestrian(id=f"crew_{amb.id}_{side}", route_nodes=[0],
                             force=SocialForceState(x=rx - hy * sign * 0.7, y=ry + hx * sign * 0.7, desired_speed=CREW_WALK_MS),
                             heading=amb.heading + math.pi, status="crew_walking", finished=True, loop=False)
            self.pedestrians[ped.id] = ped
            members.append(ped.id)
        # each kneels on one side of the casualty, seen from the ambulance
        dx, dy = casualty.x - rx, casualty.y - ry
        n = math.hypot(dx, dy) or 1.0
        px, py = -dy / n, dx / n
        paths = {}
        for mid, sign in zip(members, (1.0, -1.0)):
            goal = (casualty.x + px * sign * CREW_KNEEL_SIDE_M, casualty.y + py * sign * CREW_KNEEL_SIDE_M)
            m = self.pedestrians[mid]
            paths[mid] = self._path_round_wrecks((m.x, m.y), goal, accident)
        response["crew"] = {"unit": amb.id, "members": members, "casualty": casualty.id, "phase": "to_casualty",
                            "paths": paths, "t": self._sim_time}
        self._set_phase(response, "treating")
        self.log_event("crew_out", incident_id=response["incident_id"], unit_id=amb.id, crew=members, casualty_id=casualty.id)

    def _driver_out(self, car):
        """The struck car's driver, hurt: gets out (is taken out) and lies beside the driver's door."""
        if car is None:
            return None
        hx, hy = math.cos(car.heading), math.sin(car.heading)
        cx, cy = car.x - hx * car.params.length / 2, car.y - hy * car.params.length / 2
        x, y = cx - hy * DRIVER_OUT_SIDE_M, cy + hx * DRIVER_OUT_SIDE_M  # left of the car
        ped = Pedestrian(id=f"casualty_{car.id}", route_nodes=[0], force=SocialForceState(x=x, y=y),
                         heading=car.heading, status="injured", finished=True, loop=False)
        self.pedestrians[ped.id] = ped
        self.log_event("driver_out", car_id=car.id, casualty_id=ped.id, x=round(x, 1), y=round(y, 1))
        return ped

    def _unit_rear(self, unit, behind: float) -> tuple[float, float]:
        hx, hy = math.cos(unit.heading), math.sin(unit.heading)
        return unit.x - hx * (unit.params.length + behind), unit.y - hy * (unit.params.length + behind)

    def _path_round_wrecks(self, start, goal, accident) -> list[tuple[float, float]]:
        """Straight to the goal, going round the wrecks and the units standing at the scene: a
        point beside the middle of each body in the way (the nearer side), until the path is clear."""
        bodies = [self.cars[c] for c in (accident.get("car_id"), accident.get("other_car_id")) if c and c in self.cars]
        bodies += [u for u in self.units.values() if u.status in ("on_scene", "cleaning")]
        path = [start, goal]
        for _ in range(6):
            hit = next(((k, b) for k in range(len(path) - 1) for b in bodies
                        if self._segment_hits_body(path[k], path[k + 1], b)), None)
            if hit is None:
                break
            k, body = hit
            a, b = path[k], path[k + 1]
            hx, hy = math.cos(body.heading), math.sin(body.heading)
            cx, cy = body.x - hx * body.params.length / 2, body.y - hy * body.params.length / 2
            sides = [(cx - hy * sg * 2.0, cy + hx * sg * 2.0) for sg in (1.0, -1.0)]
            via = min(sides, key=lambda p: math.hypot(p[0] - a[0], p[1] - a[1]) + math.hypot(b[0] - p[0], b[1] - p[1]))
            if via in path:
                break
            path.insert(k + 1, via)
        return path[1:]

    @staticmethod
    def _segment_hits_body(a, b, car, margin: float = 0.5) -> bool:
        hx, hy = math.cos(car.heading), math.sin(car.heading)
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25))
        for k in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            along = (x - car.x) * hx + (y - car.y) * hy        # 0 at the front bumper, negative behind it
            side = -(x - car.x) * hy + (y - car.y) * hx
            if -car.params.length - margin <= along <= margin and abs(side) <= 1.0 + margin:
                return True
        return False

    def _walk(self, ped, path: list, speed: float, dt: float) -> bool:
        """Kinematic walk along `path` (popped as reached), easing in and out at CREW_ACCEL_MS2.
        Responders walk on the closed road, outside the walk network. True once at the end."""
        if not path:
            ped.force.vx = ped.force.vy = 0.0
            return True
        tx, ty = path[0]
        dx, dy = tx - ped.x, ty - ped.y
        dist = math.hypot(dx, dy)
        to_end = dist + sum(math.hypot(path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1]) for k in range(len(path) - 1))
        v_now = math.hypot(ped.force.vx, ped.force.vy)
        v_want = min(speed, math.sqrt(2.0 * CREW_ACCEL_MS2 * max(to_end - 0.05, 0.0)))
        v = max(v_now - CREW_ACCEL_MS2 * dt, min(v_now + CREW_ACCEL_MS2 * dt, v_want))
        if dist < 0.06 or v * dt >= dist:
            ped.force.x, ped.force.y = tx, ty
            path.pop(0)
            if not path:
                ped.force.vx = ped.force.vy = 0.0
                return True
            return False
        ux, uy = dx / dist, dy / dist
        ped.force.x += ux * v * dt
        ped.force.y += uy * v * dt
        ped.force.vx, ped.force.vy = ux * v, uy * v
        ped.heading = turn_toward(ped.heading, math.atan2(uy, ux), dt)
        return False

    def _tick_response(self, dt: float) -> None:
        for response in list(self.responses.values()):
            crew = response.get("crew")
            if crew is not None:
                self._tick_crew(response, crew, dt)
            if response.get("fire_id") is not None:
                self._tick_fire_scene(response)
            else:
                self._tick_scene(response)
        for unit in self.units.values():  # a loaded casualty travels inside the ambulance
            cid = getattr(unit, "casualty_id", None)
            if cid and cid in self.pedestrians:
                p = self.pedestrians[cid]
                p.force.x, p.force.y = self._unit_rear(unit, -CASUALTY_INSIDE_M)
                p.force.vx, p.force.vy = math.cos(unit.heading) * unit.speed, math.sin(unit.heading) * unit.speed
                p.heading = unit.heading

    def _tick_crew(self, response: dict, crew: dict, dt: float) -> None:
        members = [self.pedestrians[m] for m in crew["members"] if m in self.pedestrians]
        casualty = self.pedestrians.get(crew["casualty"])
        amb = self.units[crew["unit"]]
        t = self._sim_time
        if crew["phase"] == "to_casualty":
            done = [self._walk(m, crew["paths"][m.id], CREW_WALK_MS, dt) for m in members]
            if all(done):
                for m in members:
                    m.status = "crew_treating"
                crew.update(phase="treating", t=t)
                self.log_event("treatment_started", incident_id=response["incident_id"], casualty_id=casualty.id)
        elif crew["phase"] == "treating":
            for m in members:  # turn to face the casualty while kneeling
                m.heading = turn_toward(m.heading, math.atan2(casualty.y - m.y, casualty.x - m.x), dt)
            if t - crew["t"] >= TREAT_S:
                bx, by = self._unit_rear(amb, CREW_DOOR_BEHIND_M)
                accident = self._open_accident(response["accident_id"]) or {"car_id": None}
                # back the way they came: the casualty between them
                route = self._path_round_wrecks((casualty.x, casualty.y), (bx, by), accident)
                crew.update(phase="carrying", t=t, carry=route, offsets={
                    m.id: (m.x - casualty.x, m.y - casualty.y) for m in members})
                for m in members:
                    m.status = "crew_carrying"
                casualty.status = "carried"
                self._set_phase(response, "loading")
                self.log_event("casualty_lifted", incident_id=response["incident_id"], casualty_id=casualty.id)
        elif crew["phase"] == "carrying":
            arrived = self._walk(casualty, crew["carry"], CARRY_MS, dt)
            for m in members:
                ox, oy = crew["offsets"][m.id]
                m.force.x, m.force.y = casualty.x + ox, casualty.y + oy
                m.force.vx, m.force.vy = casualty.force.vx, casualty.force.vy
                if casualty.force.vx or casualty.force.vy:
                    m.heading = turn_toward(m.heading, math.atan2(casualty.force.vy, casualty.force.vx), dt)
            if arrived:
                casualty.status, casualty.force.vx, casualty.force.vy = "loaded", 0.0, 0.0
                amb.casualty_id = casualty.id
                for m in members:
                    m.status = "crew_boarding"
                rx, ry = self._unit_rear(amb, 0.3)
                hx, hy = math.cos(amb.heading), math.sin(amb.heading)
                doors = {m.id: [(rx - hy * sg * 0.45, ry + hx * sg * 0.45)] for m, sg in zip(members, (1.0, -1.0))}
                crew.update(phase="boarding", t=t, paths=doors)  # one rear door each
                self.log_event("casualty_loaded", incident_id=response["incident_id"], casualty_id=casualty.id, unit_id=amb.id)
        elif crew["phase"] == "boarding":
            done = [self._walk(m, crew["paths"][m.id], CREW_WALK_MS, dt) for m in members]
            if all(done):
                for m in members:
                    del self.pedestrians[m.id]  # inside the ambulance
                crew.update(phase="aboard", t=t)
                self.log_event("crew_aboard", incident_id=response["incident_id"], unit_id=amb.id)

    # ---- clearing the scene, leaving -------------------------------------------------------

    def _tick_scene(self, response: dict) -> None:
        t = self._sim_time
        units = [self.units[uid] for uid in response["units"].values()]
        on_scene = [u for u in units if u.status == "on_scene" and u.incident_id == response["incident_id"]]
        if "nothing_found_t" in response and t - response["nothing_found_t"] >= NOTHING_FOUND_S:
            for u in on_scene:
                self._leave_scene(u, response, siren=False)
            if not on_scene and "closed" not in response and all(u.status == "idle" for u in units):
                self._close(response)
            return
        crew = response.get("crew")
        if "cleared_t" not in response:
            loaded = crew is not None and crew["phase"] == "aboard"
            police = self.units.get(response["units"].get("police", ""))
            police_done = police is None or (police.status == "on_scene"
                                             and t - response.get("police_on_scene_t", t) >= POLICE_MIN_ON_SCENE_S)
            if response.get("flood_zone_id"):
                if self._flood_scene_done(response, police_done):  # flood_response.py
                    self._clear_flood_scene(response)
            elif loaded and t - crew["t"] >= CLEAR_AFTER_LOAD_S and police_done:
                self._clear_wrecks(response)
            return
        for u in on_scene:
            self._leave_scene(u, response, siren=u.kind == "ambulance" and getattr(u, "casualty_id", None) is not None)
        if response.get("closed_edges") and not any(u.kind == "police" and u.status == "on_scene" for u in units):
            self.set_barrier_state(response.pop("closed_edges"), False, by="police")
        if "closed" not in response and all(u.status == "idle" for u in units):
            self._close(response)

    def _clear_wrecks(self, response: dict) -> None:
        """The scene is cleared: the wrecks are towed away (removed) and the accident closed."""
        accident = self._open_accident(response["accident_id"])
        if accident is not None:
            for car_id in (accident["car_id"], accident.get("other_car_id")):
                if car_id:
                    self.remove_car(car_id)
            for a in self.accidents:
                if a["cleared_t"] is None and a["id"] == accident["id"]:
                    a["cleared_t"] = round(self._sim_time, 2)
        response["cleared_t"] = self._sim_time
        self._set_phase(response, "cleared")
        self.log_event("scene_cleared", incident_id=response["incident_id"], accident_id=response["accident_id"])

    def _leave_scene(self, unit, response: dict, siren: bool) -> None:
        self._head_home(unit)
        if unit.status != "returning":
            return  # no way home yet: tries again next tick
        unit.scene_shift, unit.siren = 0.0, siren
        if siren:
            unit.status = "to_hospital"
            self._set_phase(response, "transporting")
        self.log_event("unit_left_scene", unit_id=unit.id, incident_id=response["incident_id"],
                       to="hospital" if siren else "station", siren=siren)

    def _deliver(self, unit) -> None:
        cid = getattr(unit, "casualty_id", None)
        if cid:
            self.pedestrians.pop(cid, None)  # handed over to the hospital (hidden since loading)
            self.log_event("casualty_delivered", unit_id=unit.id, casualty_id=cid)
        unit.casualty_id = None

    def _close(self, response: dict) -> None:
        response["closed"] = self._sim_time
        self._set_phase(response, "closed")
