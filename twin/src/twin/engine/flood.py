"""Rain and street flooding: how much it rains, and how deep the water gets in a dip of a street.

Rain (RainProfile): intensity in mm/h over sim time, linear between the points of the profile.

A flood zone (FloodZone) is one low point of a street. The water surface is flat over a dip whose
ground follows a parabola along the street, z(s) = -H (1 - (s / L)^2) for |s| < L (s from the low
point, H the dip's depth, L its half length), across the whole road and parking lanes (W). With a
depth d at the low point the water covers |s| < L sqrt(d / H), and holds

    V = 4/3 W L d^1.5 / sqrt(H)     so     d = (3 V sqrt(H) / (4 W L))^(2/3)

Water in: rain on the catchment that drains into the dip, Q = C i A (the rational method: runoff
coefficient C, intensity i, area A). Water out: the storm drain, up to its capacity (none while it is
blocked, e.g. by leaves after a storm), plus the drainage pump when it is on (set_pump_state). Above H the water spills on down the street, so the
depth stops at MAX_DEPTH_M. The kerb is KERB_HEIGHT_M high: the sidewalks get wet only above it.

What the depth means for road users (used by flood_response.py):
  WADE_DEPTH_M      vehicles slow down in deeper water, to WADE_SPEED_MS at NO_ENTRY_DEPTH_M
  NO_ENTRY_DEPTH_M  at the low point: careful drivers no longer drive into the street
                    (it opens to them again below REOPEN_DEPTH_M)
  STALL_DEPTH_M     at a car's front: water reaches the engine's air intake and the car stalls
  TOW_DEPTH_M       at a stalled car: shallow enough to tow it away
  PED_WADE_DEPTH_M  on a sidewalk: pedestrians slow down and new routes go round it
  PED_STOP_DEPTH_M  on a sidewalk: careful pedestrians do not walk into water this deep, they turn back
  PED_TRAP_DEPTH_M  on a sidewalk: moving water this deep can knock an adult off their feet, so a
                    pedestrian in it holds on where they are and has to be rescued
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

KERB_HEIGHT_M = 0.15
MAX_DEPTH_M = 0.45
WADE_DEPTH_M = 0.05
NO_ENTRY_DEPTH_M = 0.20
REOPEN_DEPTH_M = 0.15
STALL_DEPTH_M = 0.30
TOW_DEPTH_M = 0.15
PED_WADE_DEPTH_M = 0.05
WADE_SPEED_MS = 2.8        # 10 km/h: driving through water without a bow wave
PED_WADE_SPEED_MS = 0.7
PED_STOP_DEPTH_M = 0.10
PED_TRAP_DEPTH_M = 0.20

MM_PER_HOUR = 1.0 / 1000.0 / 3600.0  # mm/h -> m/s


@dataclass(frozen=True)
class RainProfile:
    """Rain intensity in mm/h at sim time t: linear between `points` [(t, mm_per_hr), ...], sorted
    by t; 0 before the first point and the last value after the last one."""
    points: tuple[tuple[float, float], ...] = ()

    def intensity(self, t: float) -> float:
        pts = self.points
        if not pts or t < pts[0][0]:
            return 0.0
        for (t0, i0), (t1, i1) in zip(pts, pts[1:]):
            if t <= t1:
                return i0 if t1 == t0 else i0 + (i1 - i0) * (t - t0) / (t1 - t0)
        return pts[-1][1]


@dataclass
class FloodZone:
    id: str
    street: tuple[int, int]          # u, v: the street the dip is in (both directions)
    ax: float                        # the street's centreline, from node u ...
    ay: float
    bx: float                        # ... to node v
    by: float
    centre_s: float                  # the low point, metres from u along the street
    half_length_m: float             # L
    dip_depth_m: float               # H
    road_half_width_m: float         # from the centreline to the kerb: W / 2
    sidewalk_width_m: float
    catchment_m2: float              # A
    runoff_coeff: float = 0.9        # C: streets and roofs
    drain_m3s: float = 0.3           # storm drain capacity
    pump_m3s: float = 1.2            # drainage pump capacity
    pump_id: str = ""
    pump_on: bool = False
    volume_m3: float = 0.0
    inflow_m3s: float = 0.0          # over the last step
    outflow_m3s: float = 0.0
    no_entry: bool = False           # careful drivers stay out (hysteresis, see flood_response.py)
    rain: RainProfile = field(default_factory=RainProfile)  # a downpour over this street only
    drain_blocked: bool = False      # the storm drain takes nothing until it is cleared
    raining: bool = False            # for the rain_started / rain_stopped events

    # ---- the water ----------------------------------------------------------------

    @property
    def width_m(self) -> float:
        return 2.0 * self.road_half_width_m

    def _k(self) -> float:
        """V = k d^1.5."""
        return 4.0 / 3.0 * self.width_m * self.half_length_m / math.sqrt(self.dip_depth_m)

    @property
    def depth_m(self) -> float:
        """Depth at the low point."""
        if self.volume_m3 <= 0.0:
            return 0.0
        return min(MAX_DEPTH_M, (self.volume_m3 / self._k()) ** (2.0 / 3.0))

    def volume_at(self, depth_m: float) -> float:
        return self._k() * max(depth_m, 0.0) ** 1.5

    @property
    def wet_half_length_m(self) -> float:
        d = min(self.depth_m, self.dip_depth_m)
        return self.half_length_m * math.sqrt(d / self.dip_depth_m) if d > 0 else 0.0

    def step(self, dt: float, rain_mm_per_hr: float) -> None:
        """Rain runs off into the dip; the drain (and the pump, when on) take water out."""
        self.inflow_m3s = self.runoff_coeff * rain_mm_per_hr * MM_PER_HOUR * self.catchment_m2
        capacity = (0.0 if self.drain_blocked else self.drain_m3s) + (self.pump_m3s if self.pump_on else 0.0)
        available = self.volume_m3 / dt + self.inflow_m3s
        self.outflow_m3s = min(capacity, available)
        self.volume_m3 = min(self.volume_at(MAX_DEPTH_M), max(0.0, self.volume_m3 + (self.inflow_m3s - self.outflow_m3s) * dt))

    # ---- where the water is -------------------------------------------------------------

    def _local(self, x: float, y: float) -> tuple[float, float]:
        """(s from the low point along the street, distance from the centreline)."""
        dx, dy = self.bx - self.ax, self.by - self.ay
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        along = (x - self.ax) * ux + (y - self.ay) * uy
        across = -(x - self.ax) * uy + (y - self.ay) * ux
        return along - self.centre_s, abs(across)

    def road_depth_at_s(self, s: float) -> float:
        """Water depth on the asphalt at s metres from the low point."""
        d = self.depth_m
        if d <= 0.0 or abs(s) >= self.half_length_m:
            return 0.0
        return max(0.0, d - self.dip_depth_m * (s / self.half_length_m) ** 2)

    def depth_at(self, x: float, y: float) -> float:
        """Water depth at a point: on the road and parking lanes, or on the sidewalks (above the kerb)."""
        if self.volume_m3 <= 0.0:
            return 0.0
        s, across = self._local(x, y)
        road = self.road_depth_at_s(s)
        if across <= self.road_half_width_m:
            return road
        if across <= self.road_half_width_m + self.sidewalk_width_m:
            return max(0.0, road - KERB_HEIGHT_M)
        return 0.0

    @property
    def centre_xy(self) -> tuple[float, float]:
        dx, dy = self.bx - self.ax, self.by - self.ay
        n = math.hypot(dx, dy) or 1.0
        return self.ax + dx / n * self.centre_s, self.ay + dy / n * self.centre_s

    def geometry(self) -> dict:
        """For the viewer: the low point, the street's heading, the wet length and width, the depth."""
        cx, cy = self.centre_xy
        return {"id": self.id, "x": round(cx, 2), "y": round(cy, 2),
                "heading": round(math.atan2(self.by - self.ay, self.bx - self.ax), 4),
                "half_length_m": self.half_length_m, "dip_depth_m": self.dip_depth_m,
                "road_half_width_m": self.road_half_width_m, "sidewalk_width_m": self.sidewalk_width_m,
                "kerb_height_m": KERB_HEIGHT_M}
