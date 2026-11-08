"""Car body vs car body (oriented rectangles behind the front bumper)."""
import math

from twin.engine.car_collisions import body_corners, overlap_depth

LENGTH = 4.5


def depth(a, b):
    return overlap_depth(body_corners(*a, LENGTH), body_corners(*b, LENGTH))


def test_cars_in_line_with_a_gap_do_not_touch():
    assert depth((10.0, 0.0, 0.0), (4.0, 0.0, 0.0)) < 0     # front of the second 1.5 m behind the first's rear


def test_rear_end_overlap_is_measured_along_the_road():
    assert math.isclose(depth((10.0, 0.0, 0.0), (6.5, 0.0, 0.0)), 1.0)


def test_side_impact_at_right_angles():
    # westbound car with its body from x = 75 to 79.5 on y = 2.5; southbound car's front at y = 2.5, x = 77.5
    assert depth((75.0, 2.5, math.pi), (77.5, 2.5, -math.pi / 2)) > 0.5


def test_neighbouring_lanes_do_not_touch():
    assert depth((10.0, -2.5, 0.0), (10.0, 2.5, math.pi)) < 0   # opposite lanes, 5 m apart, 2 m wide cars


def test_any_two_cars_that_touch_are_flagged_as_a_crash():
    """Normal traffic no longer overlaps (rule R6), so every car-car overlap is a real crash,
    not only one involving a red-light runner."""
    from twin.world.scenario import build_simulation

    sim = build_simulation(cars=0, pedestrians=0, runners=0, seed=3)
    ahead = sim.spawn_parked_car("1_2_1", car_id="ahead")
    behind = sim.spawn_parked_car("1_2_0", car_id="behind")
    assert sim.start_trip(ahead, "2_3_2", force=True) and sim.start_trip(behind, "2_3_3", force=True)
    # put the follower's front 1 m into the leader's rear, closing at 5 m/s
    behind.x = ahead.x - math.cos(ahead.heading) * (LENGTH - 1.0)
    behind.y = ahead.y - math.sin(ahead.heading) * (LENGTH - 1.0)
    behind.heading, behind.speed = ahead.heading, 5.0
    sim._detect_car_collisions()
    assert [(a["kind"], a["car_id"], a["other_car_id"], a["cause"]) for a in sim.accidents] == [
        ("car_car", "behind", "ahead", "collision")
    ]
    assert ahead.status == behind.status == "crashed"
