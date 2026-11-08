"""Car body (behind the front bumper) vs pedestrian disc."""
import math

from twin.engine.accidents import car_hits_pedestrian

FRONT = (10.0, 0.0)
EAST = 0.0
LENGTH = 4.5


def hits(px, py, radius=0.3):
    return car_hits_pedestrian(*FRONT, EAST, LENGTH, px, py, radius)


def test_pedestrian_just_ahead_of_bumper_is_hit():
    assert hits(10.2, 0.0)


def test_pedestrian_beside_the_body_is_hit():
    assert hits(8.0, 1.2)  # body is 2 m wide: lateral reach 1.0 + radius 0.3


def test_pedestrian_clear_of_the_car_is_not_hit():
    assert not hits(10.5, 0.0)
    assert not hits(8.0, 1.4)
    assert not hits(5.0, 0.0)  # behind the rear bumper (10 - 4.5 = 5.5) by more than the radius


def test_heading_rotates_the_body():
    assert car_hits_pedestrian(0.0, 10.0, math.pi / 2, LENGTH, 0.0, 7.0, 0.3)  # northbound, body below the front
    assert not car_hits_pedestrian(0.0, 10.0, math.pi / 2, LENGTH, 2.0, 7.0, 0.3)
