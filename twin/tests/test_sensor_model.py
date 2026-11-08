"""What a real sensor reports from what is really there: within the limits an honest sensor keeps
(guardian/config/thresholds.yaml), and the same truth underneath."""
from twin.sensor_model import LEVEL_RATE_M_S, SensorModel, shaft_level


def _feed(model, kind, sensor_id, values):
    return [model.apply({"sensor_id": sensor_id, "type": kind, "zone_id": "z", "value": dict(v)})["value"] for v in values]


def _max_rate(series, tick_s=1.0):
    return max(abs(b - a) / tick_s for a, b in zip(series, series[1:]))


def test_a_rain_gauge_rises_no_faster_than_the_guardians_limit_however_sudden_the_downpour():
    out = _feed(SensorModel(tick_s=1.0, seed=1), "rainfall", "rain-a", [{"mm_per_hr": 0.0}] * 5 + [{"mm_per_hr": 120.0}] * 120)
    series = [v["mm_per_hr"] for v in out]
    assert _max_rate(series) <= 2.0
    assert 115 <= series[-1] <= 125                     # it does get there
    assert series[0] == 0.0                             # and a dry gauge reads exactly dry


def test_air_quality_follows_a_fire_within_the_limit_and_never_reads_exactly_the_same_for_long():
    out = _feed(SensorModel(tick_s=1.0, seed=1), "air_quality", "aq-a",
                [{"aqi": 38, "pm25_ugm3": 13.3, "pm10_ugm3": 23.9}] * 60 + [{"aqi": 178, "pm25_ugm3": 62.3, "pm10_ugm3": 112.1}] * 90)
    series = [v["aqi"] for v in out]
    assert _max_rate(series) <= 5.0 and 170 <= series[-1] <= 186
    assert len(set(series[:50])) > 1                    # the Guardian calls 50 identical readings a stuck sensor
    assert all(isinstance(a, int) and 0 <= a <= 500 for a in series)
    assert out[-1]["pm25_ugm3"] > 50                    # the particulates follow


def test_a_camera_reports_its_window_not_each_car():
    flicker = [{"congestion_score": 1.0 if i % 2 else 0.0, "vehicle_count": 4 if i % 2 else 0, "avg_speed_kmh": 0.0 if i % 2 else 40.0,
                "smoke_detected": False} for i in range(120)]
    out = _feed(SensorModel(tick_s=1.0, seed=1), "traffic_camera", "cam", flicker)
    assert _max_rate([v["congestion_score"] for v in out[1:]]) <= 0.03
    assert 0.4 <= out[-1]["congestion_score"] <= 0.6 and isinstance(out[-1]["vehicle_count"], int)


def test_the_smoke_flag_of_a_camera_is_not_averaged_away():
    out = _feed(SensorModel(tick_s=1.0, seed=1), "traffic_camera", "cam",
                [{"congestion_score": 0.0, "vehicle_count": 0, "avg_speed_kmh": 0.0, "smoke_detected": s} for s in (False, True)])
    assert out[1]["smoke_detected"] is True


def test_a_water_level_reads_the_drain_shaft_and_keeps_the_road_depth():
    assert shaft_level(0.0) == 0.0 and abs(shaft_level(0.1) - 0.4) < 1e-9
    assert 1.0 <= shaft_level(0.5) < 1.2       # the City Brain opens a flood at 1.0, the Guardian calls 1.2 notable
    model = SensorModel(tick_s=1.0, seed=1)
    (dry,) = _feed(model, "water_level", "wl-a", [{"level_m": 0.0, "flow_rate_m3s": 0.0}])
    assert dry["level_m"] == 0.0 and dry["road_depth_m"] == 0.0     # a dry drain reads exactly dry
    wet = _feed(model, "water_level", "wl-a", [{"level_m": 0.5, "flow_rate_m3s": 0.0}] * 200)
    assert wet[0]["road_depth_m"] == 0.5 and 1.09 <= wet[-1]["level_m"] <= 1.11


def test_the_gauge_is_damped_within_the_guardians_limit_both_ways_and_ends_exactly_dry():
    model = SensorModel(tick_s=1.0, seed=1)
    depths = [0.0] * 3 + [0.5] * 200 + [0.0] * 200
    levels = [v["level_m"] for v in _feed(model, "water_level", "wl-a", [{"level_m": d, "flow_rate_m3s": 0.0} for d in depths])]
    every_5_s = levels[::5]                    # what the Guardian compares: one reading per interval
    assert _max_rate(every_5_s, tick_s=5.0) <= 0.01 and LEVEL_RATE_M_S < 0.01
    assert levels[-1] == 0.0


def test_a_steady_flow_wobbles_a_stopped_one_does_not():
    out = _feed(SensorModel(tick_s=1.0, seed=1), "water_level", "wl-a", [{"level_m": 0.2, "flow_rate_m3s": 0.3}] * 20)
    assert len({v["flow_rate_m3s"] for v in out}) > 1 and all(v["flow_rate_m3s"] >= 0 for v in out)
    still = _feed(SensorModel(tick_s=1.0, seed=1), "water_level", "wl-b", [{"level_m": 0.0, "flow_rate_m3s": 0.0}] * 5)
    assert {v["flow_rate_m3s"] for v in still} == {0.0}


def test_other_readings_pass_untouched_and_the_input_is_not_changed():
    model = SensorModel(tick_s=1.0, seed=1)
    call = {"sensor_id": "ecall-z", "type": "emergency_call", "zone_id": "z", "value": {"call_id": "call-1"}}
    assert model.apply(call) is call
    original = {"sensor_id": "rain", "type": "rainfall", "zone_id": "z", "value": {"mm_per_hr": 10.0}}
    model.apply(original)
    assert original["value"] == {"mm_per_hr": 10.0}


def test_each_sensor_has_its_own_window_and_the_same_seed_repeats():
    series = [{"mm_per_hr": 50.0}] * 10
    assert _feed(SensorModel(tick_s=1.0, seed=3), "rainfall", "r", series) == _feed(SensorModel(tick_s=1.0, seed=3), "rainfall", "r", series)
    model = SensorModel(tick_s=1.0, seed=3)
    _feed(model, "rainfall", "wet", series)
    assert _feed(model, "rainfall", "dry", [{"mm_per_hr": 0.0}])[0]["mm_per_hr"] == 0.0
