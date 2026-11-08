"""Junction boxes (app/junctions.py): conflicting movements and who holds the box."""
from twin.engine.junctions import JunctionBoxes, curves_conflict


def _line(x0, y0, x1, y1, n=10):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


# a + junction at node 0: west 1, east 2, south 3, north 4; driving on the right, lanes 2.5 m off
PATHS = {
    (1, 0, 2): _line(-8, -2.5, 8, -2.5),   # west to east
    (2, 0, 1): _line(8, 2.5, -8, 2.5),     # east to west, the opposite lane
    (3, 0, 4): _line(2.5, -8, 2.5, 8),     # south to north: crosses both
    (1, 0, 3): _line(-8, -2.5, -2.5, -8),  # west, turning right to the south: a tight corner
}


def _boxes():
    return JunctionBoxes(lambda node: [m for m in PATHS if m[1] == node], lambda m: PATHS[m])


def test_crossing_paths_conflict_and_opposite_lanes_do_not():
    boxes = _boxes()
    assert boxes.conflicts((1, 0, 2), (3, 0, 4))
    assert not boxes.conflicts((1, 0, 2), (2, 0, 1))
    assert boxes.conflicts((1, 0, 2), (1, 0, 3))  # same lane in, different ways out
    assert boxes.is_junction(0)


def test_a_vehicle_waits_while_a_conflicting_one_holds_the_box():
    boxes = _boxes()
    boxes.reserve("a", (1, 0, 2))
    assert not boxes.may_enter((3, 0, 4))
    assert boxes.may_enter((2, 0, 1))
    assert boxes.may_enter((1, 0, 2))  # the same movement: car-following handles it
    boxes.release("a")
    assert boxes.may_enter((3, 0, 4))


def test_curves_conflict_by_closest_approach():
    assert curves_conflict(_line(0, 0, 10, 0), _line(0, 2.0, 10, 2.0))
    assert not curves_conflict(_line(0, 0, 10, 0), _line(0, 3.0, 10, 3.0))
