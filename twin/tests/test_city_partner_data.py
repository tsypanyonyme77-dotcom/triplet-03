"""What the city offers the partner adapters: stations, sensors, open incidents, unit status readings,
and the value fields the partners' contracts need (caller id, a smoke flag on air quality)."""
from twin.city.two_blocks import TwoBlocksCity


def _of_type(readings, kind):
    return [r for r in readings if r["type"] == kind]


def test_stations_sensors_and_pumps_are_listed():
    city = TwoBlocksCity("city", 1)
    stations = {s["station_id"]: s for s in city.stations()}
    assert {s: (v["kind"], v["unit_kind"], v["units"]) for s, v in stations.items()} == {
        "hospital": ("hospital", "ambulance", 1), "police_station": ("police_station", "police", 1),
        "fire_station": ("fire_station", "fire", 1)}
    sensors = {s["sensor_id"]: s["type"] for s in city.sensors()}
    assert sensors["unit-amb1"] == "unit_status" and sensors["cam-n2"] == "traffic_camera" and sensors["wl-dip-2-3"] == "water_level"
    assert {p["pump_id"] for p in city.pumps()} >= {"pump-2-3"}


def test_a_unit_reports_each_state_once_with_its_incident():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    city.sensor_readings()                      # the backlog of calls and cameras before the dispatch
    (incident,) = city.open_incidents()
    assert incident["kind"] == "accident" and incident["units"] == {}
    city.dispatch_unit("ambulance", incident["incident_id"])
    states = []
    for _ in range(400):
        city.step(1.0)
        states += [(r["value"]["state"], r["value"]["incident_id"]) for r in _of_type(city.sensor_readings(), "unit_status")
                   if r["value"]["unit_id"] == "amb1"]
        if states and states[-1][0] == "returning":
            break
    assert [s for s, _ in states] == ["en_route", "on_scene", "returning"]
    assert {i for _, i in states} == {incident["incident_id"]}


def test_calls_name_their_caller_and_air_quality_says_where_the_smoke_is():
    city = TwoBlocksCity("building-fire")
    city.step(48.0)
    readings = city.sensor_readings()
    assert all(r["value"]["caller_id"] for r in _of_type(readings, "emergency_call"))
    smoke = {r["zone_id"]: r["value"]["smoke_detected"] for r in _of_type(readings, "air_quality")}
    assert smoke == {"zone-01": True, "zone-02": False, "zone-03": False}
    (incident,) = city.open_incidents()
    assert incident["kind"] == "fire" and incident["zone_id"] in ("zone-01", "zone-03")


def test_a_public_alert_is_kept_for_the_run():
    city = TwoBlocksCity("city", 1)
    assert city.broadcast_alert("zone-02", "siren", "Stay indoors.")["status"] == "broadcast"
    assert city.broadcast_alert("zone-02", "pigeon", "x")["reason"] == "unknown_channel"
    assert [a["zone_id"] for a in city.alerts] == ["zone-02"]
    city.reset()
    assert city.alerts == []
