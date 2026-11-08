"""When a pedestrian may step onto a crosswalk.

Signalised crosswalk: only on the junction's WALK signal (traffic_lights.py), when every car
light there is red, and the crosswalk is not about to be hit by a car already committed to
it. Unsignalised crosswalk: only with an acceptable gap: no car on or about to reach the
crosswalk within SAFE_GAP_S, or closer than SAFE_GAP_MIN_M.
Cars, in turn, yield to a pedestrian on a crosswalk who is in their path, or walking
toward it fast enough to get there while the car drives over (pedestrian_in_path):
those who ignored the signal, and those still finishing a crossing;
someone on the far half of a wide crosswalk, walking away, does not hold them up.
"""
from __future__ import annotations

from twin.engine.traffic_lights import WALK

SAFE_GAP_S = 4.0
SAFE_GAP_MIN_M = 10.0
PATH_HALF_WIDTH_M = 3.8  # a car's path over a crosswalk: half a 5 m lane + half a 2 m car + a 0.3 m body
PATH_CLEAR_S = 3.0      # about how long a car takes to drive over a crosswalk


def gap_is_safe(car_distances_and_speeds: list[tuple[float, float]]) -> bool:
    """Each entry: (distance from the car's front to the near edge of the crosswalk, speed).
    A distance <= 0 means the car is already on the crosswalk."""
    for dist, speed in car_distances_and_speeds:
        if dist <= SAFE_GAP_MIN_M:
            return False
        if dist / max(speed, 0.1) < SAFE_GAP_S:
            return False
    return True


def may_cross(walk_state: str | None, car_distances_and_speeds: list[tuple[float, float]]) -> bool:
    """walk_state: the junction's pedestrian signal, or None for an unsignalised crosswalk."""
    if walk_state is not None and walk_state != WALK:
        return False
    return gap_is_safe(car_distances_and_speeds)


def pedestrian_in_path(offset_m: float, speed_toward_m_s: float) -> bool:
    """offset_m: how far a pedestrian on a crosswalk is from the centreline of the car's lane;
    speed_toward_m_s: how fast they walk toward it (negative: away). True if they are in the
    car's path, or will be within PATH_CLEAR_S."""
    reach = abs(offset_m) - max(speed_toward_m_s, 0.0) * PATH_CLEAR_S
    return reach < PATH_HALF_WIDTH_M
