"""L3b semantic plausibility: is this event possible *here*? Compares readings and actions with city_model.yaml."""

from __future__ import annotations

from datetime import timedelta

from guardian.config import CityModel
from guardian.detectors.base import L3B, fail, ok
from guardian.models import ActuatorCall, LayerResult, Reading


class SemanticDetector:
    layer = L3B

    def __init__(self, city: CityModel) -> None:
        self.city = city

    def local_hour(self, r: Reading) -> int:
        return (r.ts + timedelta(hours=self.city.timezone_offset_h)).hour

    def check(self, r: Reading) -> list[LayerResult]:
        z = self.city.zones.get(r.zone_id)
        if z is None:
            return [fail(L3B, "medium", "unknown_zone", f"zone {r.zone_id!r} is not in the city model")]
        v, out = r.value, []
        if r.sensor_type == "emergency_call":
            kind = v.get("incident_type")
            if kind == "fire" and not z.fire_possible:
                out.append(fail(L3B, "impossible", "impossible_location",
                                f"fire reported in {r.zone_id} ({z.type}) where fire_possible is false"))
            elif kind == "fire" and not z.has_buildings:
                out.append(fail(L3B, "medium", "location_sanity", f"fire call in {z.type} zone with no buildings"))
            if kind == "flood" and not z.has_water_body:
                out.append(fail(L3B, "medium", "sensor_environment_mismatch",
                                f"flood call in {r.zone_id} which has no water body"))
        elif r.sensor_type == "water_level":
            if not z.has_water_body:
                out.append(fail(L3B, "medium", "sensor_environment_mismatch",
                                f"water-level sensor in {r.zone_id} which has no water body"))
            elif v["level_m"] > z.max_water_level_m:
                out.append(fail(L3B, "medium", "physical_coupling",
                                f"level {v['level_m']} m above zone max {z.max_water_level_m} m"))
        elif r.sensor_type == "air_quality" and v.get("smoke") and not z.fire_possible:
            out.append(fail(L3B, "medium", "location_sanity", f"smoke reported in {z.type} zone"))
        elif r.sensor_type == "traffic_camera":
            if z.max_vehicles is not None and v["vehicle_count"] > z.max_vehicles:
                out.append(fail(L3B, "medium", "sensor_environment_mismatch",
                                f"{v['vehicle_count']} vehicles in a zone allowing {z.max_vehicles}"))
            hour = self.local_hour(r)
            if v["congestion_score"] > 0.8 and hour in self.city.quiet_hours:
                out.append(fail(L3B, "medium", "implausible_time_context",
                                f"congestion {v['congestion_score']} at {hour:02d}:00 local"))
        return out or [ok(L3B, "consistent with city model")]

    def action_capability(self, call: ActuatorCall, zone_id: str | None) -> str | None:
        """Capability check for actuator calls; returns a reason code when the zone cannot do it."""
        z = self.city.zones.get(zone_id or "")
        if z is None:
            return None
        if call.action == "set_grid_state" and not z.switchable_grid:
            return "no_switchable_grid"
        if call.action == "dispatch_unit" and not z.road_access:
            return "no_road_access"
        return None
