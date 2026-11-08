"""Kinematic bicycle model and pure pursuit (app/vehicle_dynamics.py)."""
import math

from twin.engine import vehicle_dynamics as vd

SPEC = vd.CAR_SPEC


def test_straight_ahead_moves_along_the_heading():
    x, y, h = vd.advance((0.0, 0.0, math.pi / 2), 5.0, 0.0, SPEC)
    assert math.isclose(x, 0.0, abs_tol=1e-9) and math.isclose(y, 5.0) and math.isclose(h, math.pi / 2)


def test_heading_comes_from_steering_and_the_rear_axle_follows_an_arc():
    steer = math.radians(20)
    radius = SPEC.wheelbase / math.tan(steer)
    pose = (0.0, 0.0, 0.0)
    rear0 = vd.rear_axle(pose, SPEC)
    centre = (rear0[0], rear0[1] + radius)  # turning left: centre on the left of the rear axle
    for _ in range(20):
        pose = vd.advance(pose, 0.5, steer, SPEC)
        rx, ry = vd.rear_axle(pose, SPEC)
        assert math.isclose(math.hypot(rx - centre[0], ry - centre[1]), radius, rel_tol=1e-9)
    assert math.isclose(pose[2], 10.0 / radius)  # turned by distance / radius


def test_front_swings_outside_the_rear_in_a_turn():
    steer = math.radians(30)
    pose = vd.advance((0.0, 0.0, 0.0), 6.0, steer, SPEC)
    radius = SPEC.wheelbase / math.tan(steer)
    rear0 = vd.rear_axle((0.0, 0.0, 0.0), SPEC)
    centre = (rear0[0], rear0[1] + radius)
    front_r = math.hypot(pose[0] - centre[0], pose[1] - centre[1])
    assert front_r > radius  # the bumper runs on a wider circle than the rear axle


def test_standing_still_never_turns():
    assert vd.advance((1.0, 2.0, 0.3), 0.0, math.radians(30), SPEC) == (1.0, 2.0, 0.3)


def test_pure_pursuit_steers_toward_the_target_side():
    assert vd.pure_pursuit_steer((0.0, 0.0, 0.0), (5.0, 3.0), SPEC) > 0   # target on the left
    assert vd.pure_pursuit_steer((0.0, 0.0, 0.0), (5.0, -3.0), SPEC) < 0  # on the right
    assert abs(vd.pure_pursuit_steer((0.0, 0.0, 0.0), (8.0, 0.0), SPEC)) < 1e-12


def test_steering_is_limited_by_angle_rate_and_grip():
    assert vd.limit_steer(1.0, 0.0, 1.0, 10.0, SPEC) == SPEC.max_steer                      # angle
    assert math.isclose(vd.limit_steer(1.0, 0.0, 1.0, 0.1, SPEC), SPEC.max_steer_rate * 0.1)  # rate
    fast = vd.limit_steer(1.0, 0.0, 14.0, 10.0, SPEC)                                          # grip at 50 km/h
    assert math.isclose(14.0 ** 2 * math.tan(fast) / SPEC.wheelbase, SPEC.max_lat_accel)


def test_acceleration_limits_and_jerk():
    assert vd.clamp_accel(-50.0, -SPEC.max_brake, 0.1, SPEC) == -SPEC.max_brake   # full ABS braking
    assert math.isclose(vd.clamp_accel(-8.0, 0.0, 0.1, SPEC), -SPEC.max_brake_jerk * 0.1)  # builds up
    assert math.isclose(vd.clamp_accel(2.0, -8.0, 0.1, SPEC), -8.0 + SPEC.max_jerk * 0.1)  # releases gradually


def test_curve_speed_keeps_lateral_acceleration_comfortable():
    r = 7.0
    v = vd.curve_speed(1 / r, SPEC)
    assert math.isclose(v * v / r, SPEC.comfort_lat_accel)


def test_stanley_holds_a_car_that_is_on_the_path_and_aligned():
    assert vd.stanley_steer((5.0, 0.0, 0.0), (4.0, 0.0, 0.0), 2.0, vd.CAR_SPEC, gain=1.0) == 0.0


def test_stanley_turns_the_car_to_the_path_heading_and_back_onto_it():
    spec = vd.CAR_SPEC
    # pointing 10 degrees left of the path with the front axle on it: steer right by those 10 degrees
    h = math.radians(10)
    bumper = (4.0 + math.cos(h) * spec.front_overhang, math.sin(h) * spec.front_overhang, h)
    assert math.isclose(vd.stanley_steer(bumper, (4.0, 0.0, 0.0), 2.0, spec, 1.0), -h, abs_tol=1e-9)
    # parallel to the path but 0.5 m left of it: steer right
    assert vd.stanley_steer((5.0, 0.5, 0.0), (4.0, 0.0, 0.0), 2.0, spec, 1.0) < 0.0
