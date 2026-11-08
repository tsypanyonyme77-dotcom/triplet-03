"""Which way a pedestrian faces (app/ped_facing.py) and stopping at a kerb (social_force)."""
import math

from twin.engine.ped_facing import MAX_TURN_DEG_S, MIN_SPEED_MS, angle_diff, turn_toward, walking_facing
from twin.engine.social_force import SocialForceState, step_pedestrian


def test_walking_toward_the_goal_faces_the_walking_direction():
    v = (math.cos(0.5), math.sin(0.5))  # 0.5 rad (29 deg) off the goal direction, +x
    assert walking_facing(*v, 10.0, 0.0) == math.atan2(v[1], v[0])


def test_stepping_back_or_aside_keeps_facing_the_goal():
    assert walking_facing(-0.6, 0.0, 10.0, 0.0) == 0.0  # pushed back in a head-on standoff
    assert walking_facing(0.0, 0.6, 10.0, 0.0) == 0.0  # sidestep


def test_a_shuffle_keeps_the_current_facing():
    assert walking_facing(MIN_SPEED_MS * 0.9, 0.0, 0.0, 10.0) is None


def test_the_body_turns_at_most_the_turn_rate():
    step = math.radians(MAX_TURN_DEG_S) * 0.1
    assert turn_toward(0.0, math.pi, 0.1) == step
    assert turn_toward(0.0, 0.05, 0.1) == 0.05
    assert abs(angle_diff(turn_toward(3.1, -3.1, 0.1), -3.1)) < 1e-9  # the short way across +-pi


def test_a_pedestrian_stopping_at_a_kerb_settles_without_overshooting():
    s = SocialForceState(x=0.0, y=0.0, vx=1.4, vy=0.0)
    xs = []
    for _ in range(100):  # 10 s
        step_pedestrian(s, 1.0, 0.0, [], None, 0.0, 0.1, stop_at_goal=True)
        xs.append(s.x)
    assert max(xs) < 1.0 + 0.15  # the momentum carries them only slightly past the kerb point
    assert abs(xs[-1] - 1.0) < 0.02 and math.hypot(s.vx, s.vy) < 0.02
    reversals = sum(1 for a, b, c in zip(xs, xs[1:], xs[2:]) if (b - a) * (c - b) < -1e-9)
    assert reversals <= 1  # at most one step back, no back-and-forth
