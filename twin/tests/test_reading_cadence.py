"""How often each sensor reports: the intervals the Guardian's registry expects, so that nobody is flooded."""
from twin.reading_cadence import ReadingCadence, parse_intervals


def _spec(sensor_id, kind, **value):
    return {"sensor_id": sensor_id, "type": kind, "value": value}


def test_a_periodic_sensor_reports_at_once_then_at_its_interval():
    cadence = ReadingCadence({"traffic_camera": 10.0}, tick_s=1.0)
    sent = []
    for tick in range(25):
        cadence.next_tick()
        if cadence.due(_spec("cam-n2", "traffic_camera")):
            sent.append(tick)
    assert sent == [0, 10, 20]


def test_each_sensor_keeps_its_own_clock_and_unlisted_types_always_report():
    cadence = ReadingCadence({"water_level": 5.0}, tick_s=1.0)
    cadence.next_tick()
    assert cadence.due(_spec("wl-a", "water_level"))
    cadence.next_tick()
    assert cadence.due(_spec("wl-b", "water_level"))     # first of its own
    assert not cadence.due(_spec("wl-a", "water_level"))
    assert cadence.due(_spec("ecall-zone-03", "emergency_call", call_id="call-0001"))


def test_the_last_word_of_a_fire_sensor_is_never_held_back():
    cadence = ReadingCadence({"building_fire": 5.0}, tick_s=1.0)
    cadence.next_tick()
    assert cadence.due(_spec("fire-b", "building_fire", smoke_detected=True))
    cadence.next_tick()
    assert not cadence.due(_spec("fire-b", "building_fire", smoke_detected=True))
    assert cadence.due(_spec("fire-b", "building_fire", smoke_detected=False))


def test_intervals_come_from_configuration_and_a_bad_one_is_named():
    assert parse_intervals("traffic_camera=10, water_level=2.5") == {"traffic_camera": 10.0, "water_level": 2.5}
    assert parse_intervals("") == {}
    for bad in ("traffic_camera", "traffic_camera=fast", "traffic_camera=-1"):
        try:
            parse_intervals(bad)
        except ValueError as exc:
            assert "TWIN_READING_INTERVALS" in str(exc)
        else:
            raise AssertionError(bad)


def _call(incident, zone="zone-01"):
    return {"sensor_id": f"ecall-{zone}", "type": "emergency_call", "zone_id": zone, "value": {"incident_id": incident}}


def test_the_call_centre_forwards_two_calls_per_incident_a_minute():
    cadence = ReadingCadence({}, tick_s=1.0, call_limits=True)
    cadence.next_tick()
    assert [cadence.due(_call("inc-1")) for _ in range(3)] == [True, True, False]
    assert cadence.due(_call("inc-2"))                 # another incident is news
    for _ in range(60):
        cadence.next_tick()
    assert cadence.due(_call("inc-1"))                 # a minute on, it is worth saying again


def test_no_zone_sends_more_calls_than_the_guardians_limit():
    cadence = ReadingCadence({}, tick_s=1.0, call_limits=True)
    cadence.next_tick()
    sent = sum(cadence.due(_call(f"inc-{n}")) for n in range(9))
    assert sent == 5 and cadence.due(_call("inc-99", zone="zone-02"))


def test_without_call_limits_every_call_goes_out():
    cadence = ReadingCadence({}, tick_s=1.0)
    assert all(cadence.due(_call("inc-1")) for _ in range(9))
