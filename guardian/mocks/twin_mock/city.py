"""The mock city: zones, sensors and actuators. Matches guardian/config/city_model.yaml and policies.yaml."""

from __future__ import annotations

TZ_OFFSET_H = 1

ZONES = ["zone-07", "zone-08", "zone-03", "zone-12"]

# sensor_id: (sensor_type, zone_id, interval_s or None for event-driven)
SENSORS: dict[str, tuple[str, str, float | None]] = {
    "wl-port-03": ("water_level", "zone-07", 5),
    "rg-port-01": ("rain_gauge", "zone-07", 10),
    "fm-port-01": ("flow_meter", "zone-07", 5),
    "aq-port-01": ("air_quality", "zone-07", 10),
    "tc-port-01": ("traffic_camera", "zone-07", 10),
    "pm-port-01": ("power_meter", "zone-07", 10),
    "gm-port-01": ("grid_meter", "zone-07", 10),
    "wl-res-01": ("water_level", "zone-08", 5),
    "rg-res-01": ("rain_gauge", "zone-08", 10),
    "fm-res-01": ("flow_meter", "zone-08", 5),
    "aq-res-01": ("air_quality", "zone-08", 10),
    "tc-res-01": ("traffic_camera", "zone-08", 10),
    "pm-res-01": ("power_meter", "zone-08", 10),
    "gm-res-01": ("grid_meter", "zone-08", 10),
    "rg-hosp-01": ("rain_gauge", "zone-03", 10),
    "aq-hosp-01": ("air_quality", "zone-03", 10),
    "tc-hosp-01": ("traffic_camera", "zone-03", 10),
    "pm-hosp-01": ("power_meter", "zone-03", 10),
    "gm-hosp-01": ("grid_meter", "zone-03", 10),
    "rg-sea-01": ("rain_gauge", "zone-12", 10),
    "aq-sea-01": ("air_quality", "zone-12", 10),
    "ec-gw-07": ("emergency_call", "zone-07", None),
    "ec-gw-08": ("emergency_call", "zone-08", None),
    "ec-gw-03": ("emergency_call", "zone-03", None),
    "ec-gw-12": ("emergency_call", "zone-12", None),
}

ACTUATORS = {
    "valve-port-12": ("valve", "zone-07"),
    "valve-res-02": ("valve", "zone-08"),
    "grid-port": ("grid_switch", "zone-07"),
    "grid-hosp": ("grid_switch", "zone-03"),
    "sig-port-01": ("traffic_signal", "zone-07"),
    "dispatch-central": ("dispatcher", None),
}

BASE_LEVEL = {"zone-07": 0.40, "zone-08": 0.30}
BASE_FLOW = {"zone-07": 1.2, "zone-08": 0.9}
CAPACITY_KW = {"zone-07": 800.0, "zone-08": 500.0, "zone-03": 1200.0}
