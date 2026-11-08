"""A car only waits for pedestrians in or heading into its path over a crosswalk."""
from twin.engine.crossing_rules import PATH_CLEAR_S, PATH_HALF_WIDTH_M, pedestrian_in_path


def test_a_pedestrian_in_the_cars_lane_holds_it():
    assert pedestrian_in_path(0.0, 0.0)
    assert pedestrian_in_path(-(PATH_HALF_WIDTH_M - 0.1), -1.4)  # just inside, walking away


def test_a_pedestrian_on_the_far_half_walking_away_does_not():
    assert not pedestrian_in_path(8.0, -1.4)
    assert not pedestrian_in_path(PATH_HALF_WIDTH_M + 0.1, 0.0)  # standing just outside


def test_a_pedestrian_walking_toward_the_lane_holds_it_if_they_get_there_in_time():
    assert pedestrian_in_path(PATH_HALF_WIDTH_M + 1.4 * PATH_CLEAR_S - 0.5, 1.4)
    assert not pedestrian_in_path(PATH_HALF_WIDTH_M + 1.4 * PATH_CLEAR_S + 0.5, 1.4)
