"""Run a scenario on the two-block map (IDM + MOBIL cars, TTC pedestrians on the
walk network) and write every tick to a JSON recording the 3D viewer plays.

Scenarios are in twin/world/scenarios.py:
  city     the default city (scenarios.CityParams), random trips;
           written to recording.json (viewer: no query string)
  ped-hit  a careless driver hits a distracted pedestrian on a crosswalk, and
           the accident waits for a call; written to recording-ped-hit.json
           (viewer: ?rec=ped-hit)
  car-crash  a red-light runner hits the side of a car crossing on green;
           recording-car-crash.json (viewer: ?rec=car-crash)
  building-fire  a building catches fire and spreads until a truck is called;
           recording-building-fire.json (viewer: ?rec=building-fire)
  flood    a cloudburst floods the dip of street 2-3: a car stalls and a pedestrian is trapped;
           recording-flood.json (viewer: ?rec=flood)

Emergency vehicles (ambulance, police car, fire truck) are parked at their stations from the
first frame. `--call-ambulance-at T` dispatches the ambulance to every open accident at
t = T s (the way City Brain's call will), to watch it pull out, work the scene and park back.
`--call-fire-at T` does the same for fires: it sends the fire truck to every incident with a fire.
A flood needs a fire truck, the police and the pump instead: `uv run python tests/incident_chain.py
flood --auto --seconds 520` runs the whole chain and writes recording-flood.json too.

Usage (from twin/):
    uv run python -m twin.world.record [seconds] [--scenario NAME] [--call-ambulance-at T] [--call-fire-at T]
"""
from __future__ import annotations

import json
import sys

from pathlib import Path

from twin.engine.accidents import CAR_WIDTH_M
from twin.engine.vehicle_dynamics import CAR_SPEC
from twin.world import scenarios
from twin.world.scenario import DT

PUBLIC = Path(__file__).resolve().parents[2] / "viewer" / "public"


def map_section(sim) -> dict:
    return {
        "lane_width_m": 5.0,
        "roads": sim.road_geometry(),
        "parking": sim.parking_geometry()["spots"],
        # named destinations the road users choose from, labelled in the viewer
        "places": [{k: p.get(k) for k in ("id", "name", "category", "x", "y", "building_id")} for p in sim.places],
        # the body every vehicle occupies (front bumper at x, y): the viewer fits its models inside
        "vehicle": {"length": CAR_SPEC.length, "width": CAR_WIDTH_M},
        **sim.walk_geometry(),
        **sim.stations_geometry(),
        **sim.cameras_geometry(),
        **sim.buildings_geometry(),
        # low points of streets where rain collects (engine/flood.py): where the viewer draws the water
        "flood_zones": [z.geometry() for z in sim.flood_zones],
    }


def frame(sim, t: float) -> dict:
    r = lambda v: round(v, 3)  # noqa: E731
    state = sim.state()
    return {
        "t": r(t),
        # [id, x, y, heading, speed, status, steer, accel]: steer and accel were appended
        # (2026-11-02), the first six fields keep their meaning
        "cars": [[c["id"], r(c["x"]), r(c["y"]), c["heading"], c["speed"], c["status"], c["steer"], c["accel"]]
                 for c in state["cars"]]
        # emergency vehicles, from the first frame (parked at their station until called):
        # status is the kind (ambulance | police | fire), then the call status
        # (idle | dispatched | cleaning | returning) appended as a 9th field
        + [[u["id"], r(u["x"]), r(u["y"]), u["heading"], u["speed"], u["kind"], u["steer"], u["accel"], u["status"]]
           for u in state["units"]],
        "pedestrians": [[p["id"], r(p["x"]), r(p["y"]), p["heading"], p["speed"], p["status"]] for p in state["pedestrians"]],
        "lights": {
            str(light["node_id"]): light["approaches"] for light in state["traffic_lights"]
        },
        # the pedestrian signal per junction: walk | flash | dont_walk
        "walk": {str(light["node_id"]): light["walk"] for light in state["traffic_lights"]},
        # who is on the phone to the emergency number: [reporter id, pedestrian | driver, call id]
        "calls": [[c["reporter_id"], c["reporter_kind"], c["call_id"]] for c in sim.active_calls()],
        # [building id, strength 0..1, fire id] per burning building
        "fires": sim.fires_frame(),
        # [id, x, y, car_id, other party (pedestrian or car) id, kind]
        # the heaviest rain in mm/h, and per flood zone [id, depth at the low point (m), pump on, rain there (mm/h), drain blocked]
        "rain": state["rain_mm_per_hr"],
        "flood": [[z["id"], z["depth_m"], z["pump_on"], z["rain_mm_per_hr"], z["drain_blocked"]] for z in state["flood"]],
        # [id, x, y, car_id, other party (pedestrian or car) id or None (flooded_car), kind]
        "accidents": [
            [a["id"], a["x"], a["y"], a["car_id"], a["pedestrian_id"] or a.get("other_car_id"), a.get("kind", "car_pedestrian")]
            for a in state["accidents"]
        ],
    }


def recording_path(name: str) -> Path:
    return PUBLIC / ("recording.json" if name == "city" else f"recording-{name}.json")


def main() -> None:
    args = sys.argv[1:]
    name = "city"
    if "--scenario" in args:
        i = args.index("--scenario")
        name = args[i + 1]
        del args[i:i + 2]
    call_at = None
    if "--call-ambulance-at" in args:
        i = args.index("--call-ambulance-at")
        call_at = float(args[i + 1])
        del args[i:i + 2]
    fire_at = None
    if "--call-fire-at" in args:
        i = args.index("--call-fire-at")
        fire_at = float(args[i + 1])
        del args[i:i + 2]
    seconds = float(args[0]) if args else 180.0
    scenario = scenarios.build(name)
    sim = scenario.sim
    out = recording_path(name)
    frames = []
    t = 0.0
    for _ in range(int(seconds / DT)):
        scenario.step()
        t += DT
        if call_at is not None and t >= call_at - 1e-9:
            for accident in sim.state()["accidents"]:
                print(f"t={t:.1f}: ambulance called to {accident['id']}: {sim.dispatch_ambulance(accident['id'])}")
            call_at = None
        if fire_at is not None and t >= fire_at - 1e-9:
            for fire in sim.fire.open():
                print(f"t={t:.1f}: fire truck called to {fire['incident_id']}: {sim.dispatch_unit('fire', fire['incident_id'])}")
            fire_at = None
        frames.append(frame(sim, t))

    out.write_text(json.dumps({"dt": DT, "map": map_section(sim), "frames": frames}, separators=(",", ":")))
    statuses: dict[str, int] = {}
    for f in frames:
        for c in f["cars"] + f["pedestrians"]:
            statuses[c[5]] = statuses.get(c[5], 0) + 1
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(frames)} frames)")
    print("status tick counts:", statuses)
    print("accidents:", sim.accidents)


if __name__ == "__main__":
    main()
