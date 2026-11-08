"""Buildings: the boxes standing on the building line behind the sidewalks.

The engine only needs a building's place and size: where it can be reached from the street
(`front`), what it touches (`adjacent_ids`, where a fire spreads) and which street it faces.
A map names its buildings (twin/world/buildings.py generates them for the two-block map);
a Simulation without a list has none, and then nothing can burn.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TOUCH_GAP_M = 3.0   # buildings closer than this (wall to wall) are next to each other


@dataclass(frozen=True)
class Building:
    id: str
    x: float                      # footprint centre, metres
    y: float
    width: float                  # along x
    depth: float                  # along y
    height: float
    street: tuple[int, int]       # the street it faces, as node ids (smaller first)
    front: tuple[float, float]    # on its street face, inside the street corridor: where people see it from

    def gap_to(self, other: "Building") -> float:
        """Distance between the two footprints (0 when they overlap), wall to wall."""
        dx = max(abs(self.x - other.x) - (self.width + other.width) / 2, 0.0)
        dy = max(abs(self.y - other.y) - (self.depth + other.depth) / 2, 0.0)
        return math.hypot(dx, dy)

    def as_dict(self) -> dict:
        return {"id": self.id, "x": round(self.x, 2), "y": round(self.y, 2), "width": round(self.width, 2),
                "depth": round(self.depth, 2), "height": round(self.height, 2), "street": list(self.street),
                "front": [round(self.front[0], 2), round(self.front[1], 2)]}


def adjacency(buildings: list[Building], touch_gap_m: float = TOUCH_GAP_M) -> dict[str, tuple[str, ...]]:
    """Building id -> the ids of the buildings next to it (within `touch_gap_m` wall to wall)."""
    return {
        a.id: tuple(b.id for b in buildings if b.id != a.id and a.gap_to(b) <= touch_gap_m)
        for a in buildings
    }
