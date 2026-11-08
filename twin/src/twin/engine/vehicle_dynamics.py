"""Vehicle motion: kinematic bicycle model steered by pure pursuit.

Each vehicle has a pose (front bumper x, y and heading), a speed and a front-wheel
steering angle. Heading comes from steering, not from the road direction:

    yaw rate = v * tan(steer) / wheelbase

integrated exactly along an arc of the rear axle, so the rear follows the front
through turns the way a real car's does (it cuts inside).

Steering is chosen by pure pursuit (Coulter 1992): aim the rear axle at a point
`lookahead` metres ahead on the lane centreline and take the steering angle whose
arc passes through it. It is limited in angle, in rate (a driver cannot turn the
wheel instantly) and by grip (v^2 * tan(steer) / wheelbase <= max lateral accel).

Speed is the caller's job (IDM in sim.py); this module only clamps acceleration
to the vehicle's limits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Pose = tuple[float, float, float]  # front bumper x, y, heading


@dataclass(frozen=True)
class VehicleSpec:
    length: float = 4.5
    wheelbase: float = 2.7
    front_overhang: float = 1.0        # front axle to front bumper
    max_steer: float = math.radians(35)
    max_steer_rate: float = math.radians(40)   # at the wheels, per second
    max_accel: float = 3.0             # m/s^2, engine limit (IDM asks for much less normally)
    max_brake: float = 8.0             # m/s^2, full braking with ABS on dry asphalt
    max_brake_jerk: float = 40.0       # m/s^3, brake pressure builds up in ~0.2 s, not instantly
    max_jerk: float = 10.0             # m/s^3, accelerating and releasing the brake
    max_lat_accel: float = 6.0         # m/s^2, grip limit used for steering
    comfort_lat_accel: float = 3.0     # m/s^2, what drivers plan curve speeds for
    lookahead_min: float = 4.5         # m, pure pursuit lookahead from the rear axle at standstill
    lookahead_per_speed: float = 0.5   # s, lookahead grows with speed

    @property
    def front_to_rear_axle(self) -> float:
        return self.wheelbase + self.front_overhang


CAR_SPEC = VehicleSpec()
AMBULANCE_SPEC = VehicleSpec(max_brake=7.5)  # same footprint as a car for now (IDM gaps use 4.5 m)


def rear_axle(pose: Pose, spec: VehicleSpec) -> tuple[float, float]:
    x, y, h = pose
    return x - math.cos(h) * spec.front_to_rear_axle, y - math.sin(h) * spec.front_to_rear_axle


def lookahead(speed: float, spec: VehicleSpec) -> float:
    return spec.lookahead_min + spec.lookahead_per_speed * speed


def pure_pursuit_steer(pose: Pose, target: tuple[float, float], spec: VehicleSpec) -> float:
    """Front-wheel angle whose arc takes the rear axle through `target` (unlimited)."""
    rx, ry = rear_axle(pose, spec)
    dx, dy = target[0] - rx, target[1] - ry
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return 0.0
    alpha = math.atan2(dy, dx) - pose[2]
    return math.atan2(2.0 * spec.wheelbase * math.sin(alpha), dist)


def stanley_steer(
    pose: Pose, path: Pose, speed: float, spec: VehicleSpec, gain: float, soft_speed: float = 0.5
) -> float:
    """Stanley controller: front-wheel angle that turns the car to the path's heading and
    steers its front axle back onto the path (`path` = x, y, heading of the path point
    beside the front axle). Unlimited, like pure_pursuit_steer."""
    x, y, h = pose
    fx, fy = x - math.cos(h) * spec.front_overhang, y - math.sin(h) * spec.front_overhang
    px, py, ph = path
    left_of_path = -(fx - px) * math.sin(ph) + (fy - py) * math.cos(ph)
    heading_error = math.atan2(math.sin(ph - h), math.cos(ph - h))
    return heading_error - math.atan2(gain * left_of_path, speed + soft_speed)


def limit_steer(wanted: float, current: float, speed: float, dt: float, spec: VehicleSpec) -> float:
    """Angle, rate and grip limits."""
    grip = math.atan(spec.max_lat_accel * spec.wheelbase / max(speed * speed, 1e-6))
    bound = min(spec.max_steer, grip)
    wanted = max(-bound, min(bound, wanted))
    step = spec.max_steer_rate * dt
    return max(current - step, min(current + step, wanted))


def clamp_accel(accel: float, previous: float, dt: float, spec: VehicleSpec) -> float:
    """Vehicle limits on acceleration and on how fast it can change (jerk)."""
    accel = max(-spec.max_brake, min(spec.max_accel, accel))
    if accel < previous:
        return max(accel, previous - spec.max_brake_jerk * dt)
    return min(accel, previous + spec.max_jerk * dt)


def advance(pose: Pose, distance: float, steer: float, spec: VehicleSpec) -> Pose:
    """Move `distance` metres (>= 0) at a fixed steering angle: the rear axle follows an arc."""
    x, y, h = pose
    rx, ry = rear_axle(pose, spec)
    if abs(steer) < 1e-9:
        rx, ry = rx + math.cos(h) * distance, ry + math.sin(h) * distance
    else:
        radius = spec.wheelbase / math.tan(steer)
        dh = distance / radius
        rx += radius * (math.sin(h + dh) - math.sin(h))
        ry -= radius * (math.cos(h + dh) - math.cos(h))
        h += dh
    h = math.atan2(math.sin(h), math.cos(h))
    d = spec.front_to_rear_axle
    return rx + math.cos(h) * d, ry + math.sin(h) * d, h


def curve_speed(curvature: float, spec: VehicleSpec) -> float:
    """Highest comfortable speed through a curve of this curvature (1/m)."""
    if curvature < 1e-6:
        return math.inf
    return math.sqrt(spec.comfort_lat_accel / curvature)
