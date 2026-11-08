"""Traffic cameras: one at every signalised junction, looking down its streets.

A camera sees vehicles within CAMERA_RANGE_M with a clear line of sight (witnesses.Corridors).
Every tick it updates:
  - traffic counts (vehicles in view, mean speed) for the periodic traffic_camera reading;
  - anomalies, each flagged after a detection delay and then kept until it clears:
      collision        a crashed vehicle (DETECT_COLLISION_S after it stopped)
      stopped_vehicle  a vehicle on the road (not parked) standing still for STOPPED_S,
                       e.g. stuck in a queue behind a wreck. Not raised at a red light:
                       a car waiting for its signal is normal.
An anomaly's `since_t` is when the camera flagged it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from twin.engine.witnesses import Corridors

CAMERA_RANGE_M = 45.0
DETECT_COLLISION_S = 2.0
STOPPED_S = 30.0


@dataclass
class Camera:
    id: str
    node: int
    x: float
    y: float
    vehicle_count: int = 0
    avg_speed_ms: float = 0.0
    anomalies: dict[str, dict] = field(default_factory=dict)  # vehicle id -> anomaly


def build_cameras(graph, light_nodes) -> list[Camera]:
    return [Camera(id=f"cam-n{n}", node=n, x=graph.nodes[n]["x"], y=graph.nodes[n]["y"]) for n in sorted(light_nodes)]


def update(cameras: list[Camera], corridors: Corridors, vehicles: list[dict], t: float) -> list[dict]:
    """`vehicles`: dicts with id, x, y, speed, status, stopped_since (t or None), at_red (bool).
    Returns the anomalies raised this tick (for the timeline)."""
    raised = []
    for cam in cameras:
        seen = [v for v in vehicles
                if math.hypot(v["x"] - cam.x, v["y"] - cam.y) <= CAMERA_RANGE_M
                and corridors.line_of_sight(cam.x, cam.y, v["x"], v["y"])]
        moving = [v for v in seen if v["status"] not in ("parked",)]
        cam.vehicle_count = len(moving)
        cam.avg_speed_ms = sum(v["speed"] for v in moving) / len(moving) if moving else 0.0
        current = {}
        for v in moving:
            if v["stopped_since"] is None:
                continue
            still = t - v["stopped_since"]
            if v["status"] == "crashed" and still >= DETECT_COLLISION_S:
                kind, confidence = "collision", 0.9
            elif v["status"] != "crashed" and not v["at_red"] and still >= STOPPED_S:
                kind, confidence = "stopped_vehicle", 0.7
            else:
                continue
            old = cam.anomalies.get(v["id"])
            if old and old["anomaly_type"] == kind:
                current[v["id"]] = old
                continue
            anomaly = {"anomaly_id": f"{cam.id}-{v['id']}-{kind}", "anomaly_type": kind, "confidence": confidence,
                       "vehicle_id": v["id"], "x": round(v["x"], 1), "y": round(v["y"], 1), "since_t": round(t, 2)}
            current[v["id"]] = anomaly
            raised.append({"camera_id": cam.id, **anomaly})
        cam.anomalies = current
    return raised
