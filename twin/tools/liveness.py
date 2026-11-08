"""Sanity stats next to check_rules.py: are people and cars still getting places?
The rules could all pass in a frozen city; this shows crossings, waits and trips.
Usage (from twin/): uv run python -m tools.liveness
"""
from twin.world.scenario import build_simulation, step

def run(label, seconds=300, **kw):
    sim = build_simulation(**kw)
    crossings = 0; wait_start = {}; waits = []; ped_trips = 0; car_trips = 0; car_speed = []
    prev_status = {}
    on_cw = {}
    for _ in range(int(seconds / 0.1)):
        step(sim)
        t = sim._sim_time
        for p in sim.pedestrians.values():
            s = p.status
            if s == "waiting" and p.id not in wait_start: wait_start[p.id] = t
            if s != "waiting" and p.id in wait_start: waits.append(t - wait_start.pop(p.id))
            if prev_status.get(p.id) == "walking" and s == "arrived": ped_trips += 1
            cw = None
            if p.edge_index > 0 and s == "walking":
                cw = sim.walk.crosswalk_between(p.route_nodes[p.edge_index - 1], p.route_nodes[p.edge_index])
            if cw and on_cw.get(p.id) != cw.id: crossings += 1
            on_cw[p.id] = cw.id if cw else None
            prev_status[p.id] = s
        for c in sim.cars.values():
            if prev_status.get(c.id) == "driving" and c.status in ("parking", "parked", "unparked"): car_trips += 1
            if c.status == "driving": car_speed.append(c.speed)
            prev_status[c.id] = c.status
    still = [t for t in wait_start.values()]
    print(f"{label}: crossings {crossings}, ped trips {ped_trips}, car trips {car_trips}, "
          f"mean car speed {sum(car_speed)/max(len(car_speed),1):.1f} m/s, "
          f"waits n={len(waits)} mean {sum(waits)/max(len(waits),1):.1f}s max {max(waits, default=0):.1f}s, "
          f"still waiting {len(still)} (longest {sim._sim_time - min(still, default=sim._sim_time):.0f}s), "
          f"accidents {len(sim.accidents)}, cars left {len(sim.cars)}, peds left {len(sim.pedestrians)}")

if __name__ == "__main__":
    run("spike 5/5 + 1 distracted", cars=5, pedestrians=5, runners=2, distracted=1)
    run("dense 15/25", cars=15, pedestrians=25, runners=5)
    run("dense 15/25 + 5 distracted", cars=15, pedestrians=25, runners=5, distracted=5)
