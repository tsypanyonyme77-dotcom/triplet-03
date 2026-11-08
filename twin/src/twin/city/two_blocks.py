"""City source backed by the traffic engine (twin.engine, twin.world), in process.

What the Twin sees of the engine, as readings (sensor_readings, signed by the emitter):
  emergency_call   one reading per call a witness makes (call centre: twin/engine/emergency_calls.py),
                   sensor "ecall-<zone>", department from the caller's category
  traffic_camera   one reading per camera per emit tick: congestion, count, mean speed
  cctv_anomaly     per camera, while it flags something: collision | stopped_vehicle
  building_fire    per burning building once its smoke sensor trips, every emit tick, then once more
                   with smoke_detected false when the fire is out: smoke, temperature and CO2
  air_quality      per zone, every emit tick: AQI and particulates, rising with the fires in the zone
                   (and a quarter as much in the others); the cameras' smoke_detected flag is true
                   within 60 m of a burning building, so the three tell the same story
  water_level      one reading per flood zone per emit tick: depth at its low point, outflow
  rainfall         one rain gauge per flood zone per emit tick: intensity in mm/h over that street
  unit_status      one reading per emergency unit each time its state changes while it is out:
                   en_route, on_scene, returning (what a dispatcher needs to close an incident)
The engine's ground truth (which accident a call is about, true positions) stays here: it is
in `timeline()` for the Twin's own logs, never in a reading.

Zones (a Twin decision, docs/data-dictionary.md section 6): one per block plus one for the
streets. A point on the asphalt, or outside the two blocks (the outer sidewalks, the
stations), is in zone-03; a point on a block's sidewalk or in its buildings is in that block's zone.
"""
from __future__ import annotations

from typing import Any

from twin.city.base import station_actuator_id

# `exit`: a road leaves the map from this zone (the streets ring the two blocks)
ZONES = {
    "zone-01": {"name": "block A", "exit": False, "bounds_m": {"x_min": 0.0, "x_max": 80.0, "y_min": 0.0, "y_max": 80.0}},
    "zone-02": {"name": "block B", "exit": False, "bounds_m": {"x_min": 80.0, "x_max": 160.0, "y_min": 0.0, "y_max": 80.0}},
    "zone-03": {"name": "streets", "exit": True, "bounds_m": {"x_min": -20.0, "x_max": 180.0, "y_min": -20.0, "y_max": 100.0}},
}
ADJACENT = {"zone-01": ["zone-02", "zone-03"], "zone-02": ["zone-01", "zone-03"], "zone-03": ["zone-01", "zone-02"]}
STATION_DEPARTMENT = {"hospital": "medical", "police_station": "police", "fire_station": "fire"}
CATEGORY_DEPARTMENT = {"medical": "medical", "police": "police", "fire": "fire", "flood": "fire", "other": "police"}
FREE_FLOW_MS = 40 / 3.6   # the two-block map's speed limit: congestion 0 at this mean speed
AQI_CLEAN, AQI_PER_FIRE = 38, 140     # air quality index of clean air, and what one full-strength fire adds in its zone
NEIGHBOUR_SHARE = 0.25                # the share of a zone's fire load that drifts into the others
# an engine unit's status as a dispatcher hears it (unit_status readings); idle units send nothing
UNIT_STATE = {"dispatched": "en_route", "on_scene": "on_scene", "cleaning": "on_scene", "to_hospital": "returning",
              "returning": "returning"}
UNIT_DEPARTMENT = {"ambulance": "medical", "police": "police", "fire": "fire"}
ALERT_CHANNELS = ("sms", "siren", "app")


class TwoBlocksCity:
    SCENARIOS = ("city", "ped-hit", "car-crash", "building-fire", "flood")

    def __init__(self, scenario: str = "city", seed: int | None = None, params=None,
                 decision: str = "random") -> None:
        """`decision`: "student" = road users choose places with the decision model, "random" = coin toss."""
        from twin.engine.street_profile import kerb_offset
        from twin.world.scenario import DT  # noqa: PLC0415

        self.dt = DT
        self.run_id = 0
        self.decision = decision
        self.params = params
        self.reset(scenario, seed)
        self._kerb = kerb_offset(self.sim.graph, 1, 2)

    def reset(self, scenario: str | None = None, seed: int | None = None, params=None) -> None:
        """Starts the scenario again from t = 0 (a new run_id). Sensor sequence numbers are the
        emitter's and keep increasing, so the Guardian sees no replay."""
        from twin.world import scenarios  # noqa: PLC0415

        scenario = scenario or self.scenario_name
        if scenario not in self.SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; one of {', '.join(self.SCENARIOS)}")
        self.scenario_name, self.seed, self.params = scenario, seed, params or self.params
        self.scenario = scenarios.build(scenario, seed, self.params)
        self.sim = self.scenario.sim
        if self.decision == "student":
            from twin.engine.decision import Decider  # noqa: PLC0415
            self.scenario.decider = Decider.load(seed=seed or 0)
        self._calls_sent = 0
        self._timeline_sent = 0
        self._fire_all_clear: set[str] = set()   # fires whose "smoke gone" reading has been sent
        self._unit_reported: dict[str, tuple[str, str | None]] = {}   # unit -> (state, incident) last sent
        self.alerts: list[dict[str, Any]] = []   # public alerts broadcast this run
        self.run_id += 1

    def params_dict(self) -> dict[str, Any]:
        from twin.world.scenarios import CityParams  # noqa: PLC0415
        return (self.params or CityParams()).as_dict()

    @property
    def sim_time(self) -> float:
        return round(self.sim._sim_time, 2)

    def agents(self) -> list[dict[str, Any]]:
        decider = self.scenario.decider
        return decider.agents(self.sim) if decider else []

    def frame(self) -> dict[str, Any]:
        """The current tick in the recording frame format (twin/world/record.py), for the live viewer."""
        from twin.world.record import frame  # noqa: PLC0415
        return frame(self.sim, self.sim._sim_time)

    def map(self) -> dict[str, Any]:
        """The recording's map section (roads, parking, walkways, stations), for the live viewer."""
        from twin.world.record import map_section  # noqa: PLC0415
        return {"dt": self.dt, "map": map_section(self.sim)}

    def units(self) -> list[dict[str, Any]]:
        """Emergency units as the dispatch centre sees them: kind, station, status, incident, ETA."""
        out = []
        for u in self.sim.units.values():
            eta = None
            if u.status in ("dispatched", "to_hospital", "returning") and not u.finished:
                eta = round(self.sim._distance_to_route_end(u) / max(u.speed, 6.0), 0)
            elif u.status == "dispatched":
                eta = None  # waiting for a gap to pull out
            out.append({"unit_id": u.id, "unit_type": u.kind, "station_id": u.station_id, "status": u.status,
                        "incident_id": u.incident_id, "siren": u.siren, "eta_seconds": eta,
                        "position": {"x": round(u.x, 1), "y": round(u.y, 1)}, "zone_id": self.zone_of(u.x, u.y)})
        return out

    def responses(self) -> list[dict[str, Any]]:
        """What the Twin's units are doing per incident (actuator feedback): phase and units sent."""
        return [{"incident_id": r["incident_id"], "phase": r["phase"], "units": dict(r["units"]),
                 "road_closed": bool(r.get("closed_edges"))} for r in self.sim.responses.values()]

    # ---- CitySource -----------------------------------------------------------------

    def zones(self) -> list[dict[str, Any]]:
        facilities: dict[str, list[str]] = {z: [] for z in ZONES}
        for st in self.sim.stations_geometry()["stations"]:
            facilities[self.zone_of(*st["front"])].append(STATION_DEPARTMENT[st["kind"]])
        return [{"zone_id": z, **ZONES[z], "adjacent": ADJACENT[z], "facilities": sorted(set(facilities[z]))} for z in ZONES]

    def step(self, dt_s: float) -> list[dict[str, Any]]:
        """Advances the engine by dt_s and returns its new ground-truth timeline entries as events."""
        for _ in range(max(1, round(dt_s / self.dt))):
            self.scenario.step()
        new = self.sim.timeline[self._timeline_sent:]
        self._timeline_sent = len(self.sim.timeline)
        return [{**e, "kind": f"sim_{e['kind']}", "message": f"sim t={e['t']}: {e['kind']}"} for e in new]

    def set_barrier_state(self, state: str, road_id: str | None = None, incident_id: str | None = None) -> dict[str, Any]:
        """The set_barrier_state actuator: close or reopen a street (idempotent)."""
        return self.sim.set_road_state(state, road_id=road_id, incident_id=incident_id, by="actuator")

    def dispatch_unit(self, unit_type: str, incident_id: str, station_id: str | None = None) -> dict[str, Any]:
        """The dispatch_unit actuator: the engine sends its nearest idle unit, or one of `station_id`
        (idempotent per incident and type)."""
        return self.sim.dispatch_unit(unit_type, incident_id, station_id)

    def broadcast_alert(self, zone_id: str, channel: str, message: str) -> dict[str, Any]:
        """The broadcast_alert actuator: a public alert to everyone in a zone. Recorded and shown on the
        timeline; the simulated people do not react to it yet."""
        if zone_id not in ZONES:
            return {"status": "rejected", "reason": "unknown_zone", "zone_id": zone_id}
        if channel not in ALERT_CHANNELS:
            return {"status": "rejected", "reason": "unknown_channel", "channel": channel}
        alert = {"alert_id": f"alert-{len(self.alerts) + 1:04d}", "zone_id": zone_id, "channel": channel, "message": message,
                 "sim_time_s": self.sim_time}
        self.alerts.append(alert)
        self.sim.log_event("alert_broadcast", alert_id=alert["alert_id"], zone_id=zone_id, channel=channel)
        return {"status": "broadcast", "alert_id": alert["alert_id"], "zone_id": zone_id, "channel": channel}

    def stations(self) -> list[dict[str, Any]]:
        """The emergency stations: id, kind (hospital, police_station, fire_station), unit kind, zone, units."""
        units: dict[str, int] = {}
        for u in self.sim.units.values():
            units[u.station_id] = units.get(u.station_id, 0) + 1
        return [{"station_id": st["id"], "kind": st["kind"], "unit_kind": st["unit_kind"], "zone_id": self.zone_of(*st["front"]),
                 "units": units.get(st["id"], 0), "location": {"x": st["front"][0], "y": st["front"][1]}}
                for st in self.sim.stations_geometry()["stations"]]

    def pumps(self) -> list[dict[str, Any]]:
        """The drainage pumps, one per street's low point: pump id, flood zone, city zone."""
        return [{"pump_id": z.pump_id, "flood_zone_id": z.id, "zone_id": self.zone_of(*z.centre_xy)} for z in self.sim.flood_zones]

    def sensors(self) -> list[dict[str, Any]]:
        """Every sensor that can send a reading, with its type and zone (the topology a partner reads at start)."""
        out = [{"sensor_id": f"ecall-{z}", "type": "emergency_call", "zone_id": z} for z in ZONES]
        out += [{"sensor_id": f"aq-{z}", "type": "air_quality", "zone_id": z} for z in ZONES]
        for cam in self.sim.cameras:
            zone = self.zone_of(cam.x, cam.y)
            out += [{"sensor_id": cam.id, "type": "traffic_camera", "zone_id": zone},
                    {"sensor_id": f"{cam.id}-cctv", "type": "cctv_anomaly", "zone_id": zone}]
        for fz in self.sim.flood_zones:
            zone = self.zone_of(*fz.centre_xy)
            out += [{"sensor_id": f"rain-{fz.id}", "type": "rainfall", "zone_id": zone},
                    {"sensor_id": f"wl-{fz.id}", "type": "water_level", "zone_id": zone}]
        out += [{"sensor_id": f"fire-{b.id}", "type": "building_fire", "zone_id": self.zone_of(b.x, b.y)}
                for b in self.sim.buildings.values()]
        out += [{"sensor_id": f"unit-{u.id}", "type": "unit_status", "zone_id": self.zone_of(u.x, u.y)} for u in self.sim.units.values()]
        return out

    def open_incidents(self) -> list[dict[str, Any]]:
        """The call centre's incidents still open, oldest first: id, zone, place, what is there (accident,
        fire or unknown) and the unit kinds already sent. An incident whose response has closed is left out."""
        out = []
        open_fires = self.sim.fire.open()
        for inc in self.sim.call_centre.incidents:
            response = self.sim.responses.get(inc["id"])
            if response is not None and response.get("phase") in ("closed", "cleared"):
                continue
            near = self.sim.INCIDENT_FIND_RADIUS_M
            accident = any(a["cleared_t"] is None and abs(a["x"] - inc["x"]) <= near and abs(a["y"] - inc["y"]) <= near
                           for a in self.sim.accidents)
            fire = any(abs(f["x"] - inc["x"]) <= near and abs(f["y"] - inc["y"]) <= near for f in open_fires)
            out.append({"incident_id": inc["id"], "zone_id": self.zone_of(inc["x"], inc["y"]), "x": inc["x"], "y": inc["y"],
                        "first_call_t": inc["first_call_t"], "kind": "fire" if fire else "accident" if accident else "unknown",
                        "units": dict(response["units"]) if response is not None else {}})
        return out

    def ignite_fire(self, building_id: str) -> dict[str, Any]:
        """The fire simulator: set a building on fire (idempotent; a building already burning is a duplicate)."""
        return self.sim.ignite_building(building_id, cause="operator")

    def set_pump_state(self, state: str, pump_id: str | None = None, incident_id: str | None = None) -> dict[str, Any]:
        """The set_pump_state actuator: start or stop a drainage pump (idempotent)."""
        return self.sim.set_pump(state, pump_id=pump_id, incident_id=incident_id, by="actuator")

    def flood_street(self, zone_id: str) -> dict[str, Any]:
        """The flood simulator: block a street's drain and bring a downpour over it (idempotent)."""
        return self.sim.flood_street(zone_id, cause="operator")

    def flood_state(self) -> list[dict[str, Any]]:
        return self.sim.flood_state()

    def device_ids(self) -> set[str]:
        zones = {f"ecall-{z}" for z in ZONES} | {f"aq-{z}" for z in ZONES}
        water = {f"wl-{z.id}" for z in self.sim.flood_zones} | {f"rain-{z.id}" for z in self.sim.flood_zones}
        stations = {station_actuator_id(st.id) for st in self.sim.stations}   # a quarantined station sends no unit
        units = {f"unit-{u}" for u in self.sim.units}
        return (zones | water | {cam.id for cam in self.sim.cameras} | {f"{cam.id}-cctv" for cam in self.sim.cameras}
                | {f"fire-{b}" for b in self.sim.buildings} | stations | units)

    # ---- readings ---------------------------------------------------------------------

    def sensor_readings(self) -> list[dict[str, Any]]:
        """Unsigned readings since the last call: new emergency calls, then every camera."""
        out = []
        for call in self.sim.call_centre.calls[self._calls_sent:]:
            zone = self.zone_of(call["x"], call["y"])
            out.append({"sensor_id": f"ecall-{zone}", "type": "emergency_call", "zone_id": zone,
                        "department": CATEGORY_DEPARTMENT[call["category"]],
                        "value": {"call_id": call["call_id"], "category": call["category"], "caller_id": call["reporter_id"],
                                  "caller_confidence": call["caller_confidence"], "incident_id": call["incident_id"],
                                  "location": {"x": call["x"], "y": call["y"]}, "reporter_kind": call["reporter_kind"],
                                  "sim_time_s": call["t"], "run_id": self.run_id}})
        self._calls_sent = len(self.sim.call_centre.calls)
        t = round(self.sim._sim_time, 2)
        for cam in self.sim.cameras:
            zone = self.zone_of(cam.x, cam.y)
            congestion = 0.0 if cam.vehicle_count == 0 else max(0.0, min(1.0, 1.0 - cam.avg_speed_ms / FREE_FLOW_MS))
            out.append({"sensor_id": cam.id, "type": "traffic_camera", "zone_id": zone, "department": "police",
                        "value": {"congestion_score": round(congestion, 2), "vehicle_count": cam.vehicle_count,
                                  "avg_speed_kmh": round(cam.avg_speed_ms * 3.6, 1),
                                  "smoke_detected": self.sim.smoke_near(cam.x, cam.y), "sim_time_s": t}})
            for anomaly in cam.anomalies.values():
                out.append({"sensor_id": f"{cam.id}-cctv", "type": "cctv_anomaly", "zone_id": self.zone_of(anomaly["x"], anomaly["y"]),
                            "department": "police",
                            "value": {"anomaly_id": anomaly["anomaly_id"], "anomaly_type": anomaly["anomaly_type"],
                                      "incident_id": anomaly.get("incident_id"),
                                      "confidence": anomaly["confidence"], "location": {"x": anomaly["x"], "y": anomaly["y"]},
                                      "since_sim_s": anomaly["since_t"], "sim_time_s": t, "run_id": self.run_id}})
        for zone in self.sim.flood_zones:  # a rain gauge and a water level at every street's drain
            cx, cy = zone.centre_xy
            out.append({"sensor_id": f"rain-{zone.id}", "type": "rainfall", "zone_id": self.zone_of(cx, cy), "department": "water",
                        "value": {"mm_per_hr": round(self.sim.rain_at(zone), 1), "location": {"x": round(cx, 1), "y": round(cy, 1)},
                                  "sim_time_s": t}})
            out.append({"sensor_id": f"wl-{zone.id}", "type": "water_level", "zone_id": self.zone_of(cx, cy), "department": "water",
                        "value": {"level_m": round(zone.depth_m, 3), "flow_rate_m3s": round(zone.outflow_m3s, 3),
                                  "pump_id": zone.pump_id, "pump_on": zone.pump_on, "location": {"x": round(cx, 1), "y": round(cy, 1)},
                                  "sim_time_s": t}})
        return out + self._fire_readings(t) + self._unit_readings(t)

    def _unit_readings(self, t: float) -> list[dict[str, Any]]:
        """A unit_status reading for each unit whose state (or incident) changed since the last one."""
        out = []
        for u in self.sim.units.values():
            state = UNIT_STATE.get(u.status)
            key = (state, u.incident_id)
            if state is None or u.incident_id is None or self._unit_reported.get(u.id) == key:
                continue
            self._unit_reported[u.id] = key
            out.append({"sensor_id": f"unit-{u.id}", "type": "unit_status", "zone_id": self.zone_of(u.x, u.y),
                        "department": UNIT_DEPARTMENT[u.kind],
                        "value": {"unit_id": u.id, "incident_id": u.incident_id, "state": state, "unit_type": u.kind,
                                  "station_id": u.station_id, "location": {"x": round(u.x, 1), "y": round(u.y, 1)},
                                  "sim_time_s": t, "run_id": self.run_id}})
        return out

    def _fire_readings(self, t: float) -> list[dict[str, Any]]:
        """Smoke sensors of the burning buildings, then the air quality of every zone."""
        from twin.engine.fires import FireModel  # noqa: PLC0415

        out = []
        for fire in self.sim.fire.fires:
            if fire.get("smoke_t") is None or fire["id"] in self._fire_all_clear:
                continue
            if fire["cleared_t"] is not None:
                self._fire_all_clear.add(fire["id"])     # one last reading: the smoke is gone
            b = self.sim.buildings[fire["building_id"]]
            zone = self.zone_of(b.x, b.y)
            out.append({"sensor_id": f"fire-{b.id}", "type": "building_fire", "zone_id": zone, "department": "fire",
                        "value": {"building_id": b.id, **FireModel.sensor_values(self.sim.fire.intensity(fire, self.sim._sim_time)),
                                  "incident_id": fire["incident_id"], "location": {"x": fire["x"], "y": fire["y"]},
                                  "sim_time_s": t, "run_id": self.run_id}})
        load = dict.fromkeys(ZONES, 0.0)
        smoky: set[str] = set()   # zones with a building whose smoke sensor has tripped and whose fire still burns
        for fire in self.sim.fires_state():
            b = self.sim.buildings[fire["building_id"]]
            load[self.zone_of(b.x, b.y)] += fire["intensity"]
        for fire in self.sim.fire.open():
            if fire.get("smoke_t") is not None:
                b = self.sim.buildings[fire["building_id"]]
                smoky.add(self.zone_of(b.x, b.y))
        for zone in ZONES:
            effective = load[zone] + NEIGHBOUR_SHARE * (sum(load.values()) - load[zone])
            aqi = min(500, round(AQI_CLEAN + AQI_PER_FIRE * effective))
            pm25 = round(aqi * 0.35, 1)
            out.append({"sensor_id": f"aq-{zone}", "type": "air_quality", "zone_id": zone,
                        "value": {"aqi": aqi, "pm25_ugm3": pm25, "pm10_ugm3": round(pm25 * 1.8, 1),
                                  "smoke_detected": zone in smoky, "sim_time_s": t}})
        return out

    def timeline(self) -> list[dict[str, Any]]:
        """The engine's ground truth (for logs and tests, never sent to partners)."""
        return list(self.sim.timeline)

    def zone_of(self, x: float, y: float) -> str:
        on_asphalt = (abs(y) <= self._kerb or abs(y - 80.0) <= self._kerb or abs(x) <= self._kerb
                      or abs(x - 80.0) <= self._kerb or abs(x - 160.0) <= self._kerb)
        if on_asphalt or not (0.0 < y < 80.0 and 0.0 < x < 160.0):
            return "zone-03"
        return "zone-01" if x < 80.0 else "zone-02"
