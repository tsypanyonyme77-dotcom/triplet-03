"""Junction boxes: which movements through a node get in each other's way, and who is in
the box now.

A movement (a, b, c) drives from edge a->b through node b onto edge b->c, along its turn
curve (turn_paths.py). Two different movements conflict when their curves come closer
than CONFLICT_M anywhere: they cross, merge into the same exit, or leave the same lane in
different directions. A vehicle holds the box from when it commits to its movement (just
before its stop line) until its rear has left the box; a vehicle may only commit when no
holder's movement conflicts with its own. Identical movements never conflict: the second
car follows the first (car-following across the node, see sim._leader_across).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable

CONFLICT_M = 2.5      # a car is 2 m wide: closer than this, two bodies on the curves can touch
SAMPLES = 24          # points per curve when measuring how close two curves come

Movement = tuple[int, int, int]
Point = tuple[float, float]


def curves_conflict(a: list[Point], b: list[Point], min_gap: float = CONFLICT_M) -> bool:
    """True if two sampled curves come closer than `min_gap` anywhere."""
    return any(math.hypot(p[0] - q[0], p[1] - q[1]) < min_gap for p in a for q in b)


class JunctionBoxes:
    def __init__(
        self, movements_at: Callable[[int], Iterable[Movement]], sample: Callable[[Movement], list[Point]]
    ) -> None:
        """`movements_at(node)`: every (a, node, c) a vehicle can drive through that node;
        `sample(movement)`: points along its curve. Conflicts are worked out per node, the
        first time it is asked about (a city map has thousands of nodes)."""
        self._movements_at = movements_at
        self._sample = sample
        self._conflicts: dict[int, dict[Movement, set[Movement]]] = {}
        self._held: dict[str, Movement] = {}
        self._claims: dict[str, Movement] = {}  # emergency units about to drive these: keep out

    def _node(self, node: int) -> dict[Movement, set[Movement]]:
        table = self._conflicts.get(node)
        if table is None:
            ms = list(self._movements_at(node))
            points = {m: self._sample(m) for m in ms}
            table = {}
            for i, m in enumerate(ms):
                for n in ms[i + 1:]:
                    if curves_conflict(points[m], points[n]):
                        table.setdefault(m, set()).add(n)
                        table.setdefault(n, set()).add(m)
            self._conflicts[node] = table
        return table

    def is_junction(self, node: int) -> bool:
        """A node where some movements conflict (a corner of two streets is not one)."""
        return bool(self._node(node))

    def conflicts(self, m: Movement, n: Movement) -> bool:
        return m[1] == n[1] and n in self._node(m[1]).get(m, ())

    def may_enter(self, movement: Movement, ignore_claims: bool = False) -> bool:
        """No vehicle in the box drives a movement that conflicts with this one, and no emergency
        unit has claimed one (a unit itself goes by who is in the box: ignore_claims)."""
        if any(self.conflicts(movement, held) for held in self._held.values()):
            return False
        return ignore_claims or not any(self.conflicts(movement, claim) for claim in self._claims.values())

    def set_claims(self, claims: dict[str, Movement]) -> None:
        self._claims = claims

    def reserve(self, vehicle_id: str, movement: Movement) -> None:
        self._held[vehicle_id] = movement

    def release(self, vehicle_id: str) -> None:
        self._held.pop(vehicle_id, None)

    def held_by(self, vehicle_id: str) -> Movement | None:
        return self._held.get(vehicle_id)

    def holders(self) -> dict[str, Movement]:
        return dict(self._held)
