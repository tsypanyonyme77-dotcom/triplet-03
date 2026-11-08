"""Drawn vehicle paths through nodes: smooth turns instead of snaps."""
import math

from twin.engine.turn_paths import TurnCurve, turn_zone
from tools.motion_smoothness import measure


def test_right_angle_turn_starts_and_ends_on_the_lanes_with_their_headings():
    # eastbound lane y = -2.5 turning left onto northbound lane x = 82.5 around node (80, 0)
    curve = TurnCurve.build((72.0, -2.5), (1.0, 0.0), (82.5, 8.0), (0.0, 1.0))
    x0, y0, h0 = curve.at(0.0)
    x1, y1, h1 = curve.at(1.0)
    assert math.isclose(x0, 72.0) and math.isclose(y0, -2.5) and abs(h0) < 1e-6
    assert math.isclose(x1, 82.5) and math.isclose(y1, 8.0) and math.isclose(h1, math.pi / 2)
    assert curve.p1 == (82.5, -2.5)  # control point: where the two lane lines cross


def test_curve_is_walked_at_constant_speed_along_its_length():
    curve = TurnCurve.build((72.0, -2.5), (1.0, 0.0), (82.5, 8.0), (0.0, 1.0))
    points = [curve.at(i / 20)[:2] for i in range(21)]
    steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
    assert max(steps) / min(steps) < 1.05


def test_going_straight_stays_straight():
    curve = TurnCurve.build((72.0, -2.5), (1.0, 0.0), (88.0, -2.5), (1.0, 0.0))
    for i in range(11):
        x, y, h = curve.at(i / 10)
        assert math.isclose(y, -2.5) and abs(h) < 1e-9


def test_turn_zone_shrinks_on_short_edges():
    assert turn_zone(80.0, 80.0) == 8.0
    assert turn_zone(10.0, 80.0) == 4.5


def test_cars_never_snap_heading_or_jump_in_city_traffic():
    result = measure("city", 120.0)
    assert result["car_ticks"] > 1000
    assert result["heading_snaps"] == 0 and result["jumps"] == 0, result
