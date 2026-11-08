"""How a unit with its siren on drives: it takes the shortest way and breaks the traffic rules to
get there, without hitting anyone. A mixin of Simulation (sim.py), which wires it.

The way there. Both directions of the street count: a unit may reach a wreck from the far side, in
the opposite lane (scene_targets), whichever is shorter.

Signals and junctions. A responding unit ignores lights. Instead it claims the junction ahead: no
new car enters a movement that conflicts with its own, and a car that has reserved one but can
still stop at its line gives it up. Cars already past their line clear the box. It crosses against
a red at RED_CROSS_MS at most, and brakes for whatever is physically in its path (below).

Queues. Lanes are 5 m wide and cars 2 m, so a unit moved CENTRE_LINE_SHIFT_M left of its lane
drives down the centre line, clear of the cars in its own lane and of oncoming ones. It does so
whenever a car is ahead in its lane, and no longer follows them. Sideways moves need rolling
(LATERAL_PER_M, incident_response.py), so it starts early (PASS_LOOK_AHEAD_M). It stays in its lane
near the end of its route, and when another unit comes the other way on the same street.
Oncoming cars pull over for it (_head_on). Whatever else stands in its way, a wreck across a
junction or a car turning, it sees by checking its own path against every vehicle body
(_path_block): it brakes for it, and takes the other side of the lane if that is free.

People. It yields to anyone in its path on a crosswalk, like any driver, measured from where it
really is, and slows for a crosswalk with someone on or beside it (CAUTION_*) so that it can still
stop for someone stepping out. As a last line of defence it checks its own path for people, also
where they will be in a moment, and brakes as hard as it can (_person_in_path). Waiting pedestrians do not step in front of it: it counts as a threat
at the kerb even on WALK (sim._vehicles_toward_crosswalk), since it does not obey the red.
"""
from __future__ import annotations

import math

from twin.engine.car_collisions import body_corners, overlap_depth
from twin.engine.emergency_units import EmergencyVehicle
from twin.engine.idm import idm_acceleration
from twin.engine.models import Car

CENTRE_LINE_SHIFT_M = 2.6   # clears a car in its lane by 0.6 m and an oncoming one by 0.4 m (cars 2 m wide, lanes 5 m)
PASS_CLEAR_SHIFT_M = 2.4    # from this far left, a car in its lane is no longer ahead of it
PASS_LOOK_AHEAD_M = 50.0
BACK_IN_LANE_BEFORE_END_M = 25.0
ONCOMING_UNIT_M = 70.0
CLAIM_JUNCTION_M = 45.0     # cars stop entering what conflicts with it from this far out
RED_CROSS_MS = 7.0
CAUTION_LOOK_AHEAD_M = 40.0
CAUTION_NEAR_M = 5.0        # a pedestrian this close to a crosswalk's end may step out
CAUTION_CROSS_MS = 5.0      # speed over such a crosswalk: stops within 2 m
CAUTION_BRAKE_MS2 = 4.0
HEAD_ON_M = 45.0            # oncoming cars this far ahead of a unit on the centre line pull over
PATH_SAMPLE_M = 1.5
PATH_MARGIN_M = 1.5         # stops this far short of something in its path
PATH_MIN_LOOK_M = 10.0
STANDING_MS = 0.5
DODGE_CREEP_MS = 1.5        # rolling this fast lets it move sideways round something close ahead
PERSON_CLEAR_M = 1.8        # half a car (1 m) + half a person (0.3 m) + a margin
PERSON_AHEAD_S = 1.0        # also where someone walking will be this soon
PERSON_MARGIN_M = 3.0


class EmergencyDriving:
    # ---- the way there ----------------------------------------------------------------

    def scene_targets(self, edge: tuple[int, int], end: float) -> list[tuple[tuple[int, int], float]]:
        """Where to stop for a spot `end` metres along `edge`: that lane, or level with it in the opposite lane."""
        u, v = edge
        targets = [(edge, end)]
        if self.graph.has_edge(v, u):
            targets.append(((v, u), max(self.edge_length(v, u) - end, 0.5)))
        return targets

    # ---- junctions --------------------------------------------------------------------

    @staticmethod
    def _next_movement(vehicle) -> tuple[int, int, int] | None:
        route, i = vehicle.route_nodes, vehicle.edge_index
        return (route[i], route[i + 1], route[i + 2]) if i + 2 < len(route) else None

    def _to_stop_line(self, vehicle) -> float:
        u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
        return self.edge_length(u, v) - self._stop_setback(u, v) - vehicle.dist_on_edge

    def _tick_priority_claims(self) -> None:
        """Which movements cars must keep out of this tick: those responding units are about to drive."""
        claims = {}
        for unit in self.units.values():
            movement = self._next_movement(unit) if unit.responding else None
            if movement is None or not self._boxes.is_junction(movement[1]) or self._boxes.held_by(unit.id) == movement:
                continue
            if self._to_stop_line(unit) <= CLAIM_JUNCTION_M:
                claims[unit.id] = movement
        self._boxes.set_claims(claims)
        for vid, held in self._boxes.holders().items():
            car = self.cars.get(vid)
            if car is None or not any(self._boxes.conflicts(held, claim) for claim in claims.values()):
                continue
            here = (car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1])
            braking = car.speed * car.speed / (2.0 * car.params.b)
            if here == held[:2] and self._to_stop_line(car) > braking:
                self._boxes.release(vid)

    def _priority_accel(self, vehicle, stop_line_dist: float) -> float:
        """A responding unit takes the box, and goes through a red at RED_CROSS_MS at most. +inf for everyone else."""
        if not (isinstance(vehicle, EmergencyVehicle) and vehicle.responding):
            return math.inf
        movement = self._next_movement(vehicle)
        if movement is None or not self._boxes.is_junction(movement[1]):
            return math.inf
        to_line = stop_line_dist - vehicle.dist_on_edge
        if to_line > CLAIM_JUNCTION_M:
            return math.inf
        if self._boxes.held_by(vehicle.id) != movement:
            self._boxes.reserve(vehicle.id, movement)
            self._stop_waiting_for_crosswalks(vehicle.id)
        if to_line <= 0.0 or self._light_state(movement[0], movement[1]) not in ("red", "yellow"):
            return math.inf
        return self._speed_limit_accel(vehicle, RED_CROSS_MS, to_line, vehicle.params.b * 2.0)

    @staticmethod
    def _speed_limit_accel(vehicle, limit_ms: float, distance: float, brake_ms2: float) -> float:
        """Braking that brings it down to `limit_ms` `distance` metres ahead. +inf if it is slow enough."""
        allowed = math.sqrt(limit_ms * limit_ms + 2.0 * brake_ms2 * max(distance, 0.0))
        return math.inf if vehicle.speed <= allowed else (allowed - vehicle.speed) / 0.5

    # ---- queues -----------------------------------------------------------------------

    def _on_centre_line(self, unit) -> bool:
        return unit.lateral_offset <= -PASS_CLEAR_SHIFT_M

    def _car_ahead_in_lane(self, unit) -> bool:
        return any(not c.finished and self._behind_in_lane(unit, c, PASS_LOOK_AHEAD_M) for c in self.cars.values())

    def _oncoming_unit(self, unit) -> bool:
        """Another unit with its siren on is coming the other way along this street: one of them must keep its lane."""
        u, v = unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1]
        for other in self.units.values():
            if other is unit or not other.responding:
                continue
            ou, ov = other.route_nodes[other.edge_index], other.route_nodes[other.edge_index + 1]
            if (ou, ov) == (v, u) and abs(self.edge_length(u, v) - other.dist_on_edge - unit.dist_on_edge) <= ONCOMING_UNIT_M:
                return True
        return False

    def _centre_line_target(self, unit) -> float:
        """How far left of its lane a responding unit wants to be: its lane or the centre line,
        whichever it prefers here, unless that way is blocked and the other is free."""
        oncoming = self._oncoming_unit(unit)
        if self._distance_to_route_end(unit) < BACK_IN_LANE_BEFORE_END_M or oncoming:
            wanted = 0.0
        else:
            wanted = -CENTRE_LINE_SHIFT_M if self._car_ahead_in_lane(unit) else 0.0
        other = 0.0 if wanted else -CENTRE_LINE_SHIFT_M
        options = [wanted] if oncoming else [wanted, other]
        for lateral in options:
            # moving right, count what is alongside too: never back into a car beside it
            block = self._path_block(unit, lateral, beside=lateral > unit.lateral_offset)
            if block is None or block[1].speed >= STANDING_MS:
                return lateral
        return unit.lateral_offset

    def _head_on(self, unit, car) -> bool:
        """`car` comes the other way along the street of a responding unit that is leaving its lane."""
        if unit.lateral_offset > -1.0 and self._centre_line_target(unit) == 0.0:
            return False
        route, i = unit.route_nodes, unit.edge_index
        u, v = route[i], route[i + 1]
        cu, cv = car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]
        if (cu, cv) != (v, u):
            return False
        return 0.0 <= self.edge_length(u, v) - car.dist_on_edge - unit.dist_on_edge <= HEAD_ON_M

    def _path_block(self, unit, lateral: float | None = None, beside: bool = False):
        """The first vehicle body its path runs into, with how far ahead: (distance, vehicle) or None.
        `lateral`: as if it drove this far from its lane (default: where it is now). `beside`: also
        count what is alongside it now, for a move sideways."""
        look = max(PATH_MIN_LOOK_M, unit.speed * unit.speed / (2.0 * CAUTION_BRAKE_MS2) + PATH_MARGIN_M * 2)
        near = [o for o in list(self.cars.values()) + list(self.units.values())
                if o is not unit and not o.finished and math.hypot(o.x - unit.x, o.y - unit.y) <= look + 8.0]
        if not near:
            return None
        bodies = [(o, body_corners(o.x, o.y, o.heading, o.params.length)) for o in near]
        kept = unit.lateral_offset
        if lateral is not None:
            unit.lateral_offset = lateral
        try:
            d = -unit.params.length if beside else PATH_SAMPLE_M
            limit = self._distance_to_route_end(unit)
            while d <= min(look, limit):
                x, y, h = self._reference_ahead(unit, d)
                body = body_corners(x, y, h, unit.params.length)
                for other, corners in bodies:
                    if overlap_depth(body, corners) > 0.0:
                        return d, other
                d += PATH_SAMPLE_M
        finally:
            unit.lateral_offset = kept
        return None

    def _path_block_accel(self, vehicle) -> float:
        """A responding unit brakes for whatever its path runs into."""
        if not (isinstance(vehicle, EmergencyVehicle) and vehicle.responding):
            return math.inf
        block = self._path_block(vehicle)
        if block is None:
            return math.inf
        distance, other = block
        target = self._lateral_target(vehicle)
        if target != vehicle.lateral_offset and other.speed < STANDING_MS and self._path_block(vehicle, target, beside=True) is None:
            return DODGE_CREEP_MS - vehicle.speed  # going round it: sideways moves need rolling
        return idm_acceleration(vehicle.speed, other.speed, max(distance - PATH_MARGIN_M, 0.01), vehicle.params)

    def _passes(self, unit, other) -> bool:
        """`other` ahead in its lane does not hold the unit up: a car it drives past on the centre line."""
        return isinstance(other, Car) and self._on_centre_line(unit)

    # ---- people -----------------------------------------------------------------------

    def _crosswalk_caution_accel(self, vehicle, u: int, v: int, edge_len: float) -> float:
        """A responding unit slows for a crosswalk ahead with someone on it or beside it."""
        if not (isinstance(vehicle, EmergencyVehicle) and vehicle.responding):
            return math.inf
        ahead = list(self.walk.crosswalks_on_edge(u, v, edge_len))
        movement = self._next_movement(vehicle)
        if movement is not None:
            nxt = self.walk.crosswalk_at(v, movement[2])
            if nxt is not None:
                ahead.append((nxt, edge_len + nxt.along_m))
        accel = math.inf
        for cw, centre in ahead:
            distance = centre - vehicle.dist_on_edge
            if -CAUTION_NEAR_M < distance <= CAUTION_LOOK_AHEAD_M and self._someone_at(cw):
                accel = min(accel, self._speed_limit_accel(vehicle, CAUTION_CROSS_MS, distance - CAUTION_NEAR_M, CAUTION_BRAKE_MS2))
        return accel

    def _person_in_path(self, unit) -> bool:
        """Someone on its path within stopping distance, now or PERSON_AHEAD_S from now."""
        spec = self._spec(unit)
        look = unit.speed * unit.speed / (2.0 * spec.max_brake) + PERSON_MARGIN_M
        near = []
        for ped in self.pedestrians.values():
            if ped.status in ("carried", "loaded") or math.hypot(ped.x - unit.x, ped.y - unit.y) > look + 8.0:
                continue
            near.append((ped.x, ped.y))
            near.append((ped.x + ped.force.vx * PERSON_AHEAD_S, ped.y + ped.force.vy * PERSON_AHEAD_S))
        if not near:
            return False
        d = -unit.params.length + PATH_SAMPLE_M / 2.0  # the whole body: someone can walk into its rear corner too
        limit = min(look, self._distance_to_route_end(unit))
        while d <= limit:
            x, y, h = self._reference_ahead(unit, d)
            ux, uy = math.cos(h), math.sin(h)
            for px, py in near:
                along, across = (px - x) * ux + (py - y) * uy, -(px - x) * uy + (py - y) * ux
                if abs(along) <= PATH_SAMPLE_M and abs(across) <= PERSON_CLEAR_M:
                    return True
            d += PATH_SAMPLE_M
        return False

    def _person_accel(self, vehicle) -> float:
        """Full braking for someone in a unit's path, siren on or off. +inf if nobody is."""
        if not isinstance(vehicle, EmergencyVehicle) or not self._person_in_path(vehicle):
            return math.inf
        return -self._spec(vehicle).max_brake

    def _someone_at(self, cw) -> bool:
        ends = [self.walk.xy(cw.a), self.walk.xy(cw.b)]
        for ped in self.pedestrians.values():
            if ped.status in ("carried", "loaded"):
                continue
            if self.walk.crosswalk_between(*self._ped_edge(ped)) is cw or any(
                    math.hypot(ped.x - x, ped.y - y) <= CAUTION_NEAR_M for x, y in ends):
                return True
        return False

    @staticmethod
    def _ped_edge(ped) -> tuple[int, int]:
        i = max(ped.edge_index, 1)
        return (ped.route_nodes[i - 1], ped.route_nodes[i]) if len(ped.route_nodes) > 1 else (-1, -1)
