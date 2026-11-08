# Engines

How each part of the simulation works, where it lives in `src/twin/engine/`, and its main parameters.
`sim.py` (class `Simulation`) owns the state and the tick loop; every other module is one engine or one rule.

## The Tick

- Fixed step `dt = 0.1 s` (10 Hz). One `Simulation.tick(dt)` does, in order:
  1. traffic lights advance (`traffic_lights.tick_lights`);
  2. vehicles are grouped per lane, then MOBIL lane changes, then IDM car-following with light and crosswalk braking;
  3. vehicles move along their edges (`_advance_edge_if_needed`, `_update_xy`);
  4. emergency vehicles pull out of their bays when called, move, work the scene, drive back and park; parking manoeuvres advance;
  5. pedestrians step (`_tick_pedestrians`), then are separated and kept on their walkway;
  6. car-pedestrian accidents are detected.
- Decisions about *where to go* happen outside `tick()`: the caller asks `cars_needing_decision()` / `pedestrians_needing_decision()` and answers with `apply_decision()` / `apply_pedestrian_decision()`.
  The POC answers with an LLM (`agents.py`); `world/scenario.py` answers with a random place.

## Map and Routing

- **Road graph**: a NetworkX `MultiDiGraph`, nodes with projected `x`, `y` in metres, edges with `length`, `lanes` (per direction), `oneway`, `highway`, `travel_time`.
  `road_network.py` builds it from OpenStreetMap with OSMnx (Avenue Habib Bourguiba, Tunis); `world/map.py` builds the two-block grid by hand with the same attributes.
- **Cars route** with `nx.shortest_path(..., weight="travel_time")` once per trip, from free-flow speeds. No rerouting on congestion.
- **Pedestrians route** on the walk network (below) with `weight="length"`.
- **Places** (`places.py`): 100 synthetic destinations (homes, offices, shops, hospitals...) placed along eligible streets with a fixed seed. Cars drive to a place's nearest road node; pedestrians walk to the sidewalk node nearest the place.

## Street Cross-Section (`street_profile.py`)

Measured sideways from the street centreline, for one direction of travel:

| Band | Two-way street, 1 lane per direction |
|---|---|
| driving lane | 0 to 5 m (lane width 5 m, `road_network.LANE_WIDTH_M`) |
| parking lane | 5 to 8 m (`PARKING_LANE_M = 3`) |
| kerb | 8 m |
| sidewalk | 8 to 12 m (`SIDEWALK_WIDTH_M = 4`), pedestrians walk around 10 m |
| crosswalk | 3 m wide (`CROSSWALK_WIDTH_M`), stop line 1 m before it |

On a one-way street the lanes are centred on the centreline instead.
Every module that needs a lateral position calls these functions; nothing hard-codes offsets.

## Cars

- **Car-following: IDM, Intelligent Driver Model** (`idm.py`).
  Acceleration from own speed, desired speed and the gap and speed difference to the car ahead.
  Parameters (`IDMParams`): desired speed 13.9 m/s (50 km/h), max acceleration 1.2 m/s², comfortable braking 2.0 m/s², minimum gap 2 m, time headway 1.5 s, car length 4.5 m.
- **Lane changes: MOBIL** (`mobil.py`).
  Change lane if own acceleration improves by more than 0.2 m/s² after weighing the effect on others (politeness 0.3), and never force the new follower to brake harder than 4 m/s².
  Cooldown 3 s, only cars within 50 m considered, courtesy only for followers within 12 m (`sim.py` constants).
- **Positions**: `x`, `y` are the **front bumper**. The body is the 4.5 m behind it. `dist_on_edge` is the vehicle's progress along its lane: where the front bumper projects onto the lane centreline.
- **Motion: kinematic bicycle model** (`vehicle_dynamics.py`, `sim._drive`). Heading comes from steering: yaw rate = v tan(steer) / wheelbase (2.7 m), integrated exactly along the rear axle's arc, so the rear follows the front and cuts inside a turn.
  Steering is pure pursuit: aim the rear axle at the lane centreline 4.5 m + 0.5 s x speed ahead. The steering angle is limited to 35 degrees, to 40 degrees/s, and by grip (lateral accel at most 6 m/s^2).
  IDM still sets the acceleration (car-following, lights, crosswalks). On top of it the vehicle:
  - brakes ahead of each turn to a comfortable speed (lateral accel 3 m/s^2: about 14 km/h for a right turn, 17 km/h for a left turn);
  - brakes to a stop at the end of its route;
  - is held to 3 m/s^2 accelerating, 8 m/s^2 braking (ABS), brake build-up of 40 m/s^3 (about 0.2 s), and 10 m/s^3 when accelerating or releasing the brake.
  `Car.slows_for_turns = False` (scenarios only) is a reckless driver who does not slow for corners; their steering is then held by grip and they run wide.
- **Lane path through nodes** (`turn_paths.py`, `sim._reference_pose`): within 8 m of a node (less on short edges) the lane centreline that cars steer along is a quadratic Bezier curve from the incoming lane to the outgoing lane, its control point where the two lane lines cross. Each curve's peak curvature sets the turning speed. MOBIL lane changes move the target lane, and the car steers across.
  `dist_on_edge`, IDM, lights and the rule checks still work on the straight edges; only the drawn position changes. Accident bodies follow the drawn position and heading.
- **Traffic lights** (`traffic_lights.py`): fixed-time, two phases per intersection with 3+ incoming streets.
  Approaches are split into two phases by bearing (opposite directions share a phase).
  Green 10 s, yellow 3 s, the other phase red meanwhile; adjacent lights offset by 1.7 s.
- **Stopping at a light** (`sim._must_stop_for_light`): on red, every car still before the stop line stops; on yellow, only a car that can stop at comfortable braking (`v² / 2b` fits before the line), otherwise it goes through (dilemma zone).
  The stop line is 1 m before the crosswalk (`WalkNetwork.stop_setback`), 12.5 m from the intersection centre on the two-block map.
  IDM treats the stop line as a stopped car, so cars come to rest about 2 m (its minimum gap) before it.
- **Yielding to pedestrians** (`sim._crosswalk_yield_accel`): if a crosswalk on the current edge, or just past the next node, has someone on it, the car brakes as if a stopped car stood 1 m before it. A car already at the crosswalk does not brake (it could not stop anyway).
- **Parking and trips** (`parking.py`, `routing.py`, `sim.request_trip` / `_start_trip` / `_finish_trip`):
  - **Spots:** every 12 m along the parking lane of residential-type streets (a 5.5 m bay plus room to drive in forwards), none within 14 m of an intersection.
  - **Spawning:** cars start parked in random free spots, so they never spawn overlapping or in an intersection.
  - **Choosing a spot:** a trip goes from the car's spot to a free spot near the destination. Of the 8 nearest free spots, the car takes the one with the least driving plus 3x the walk, and reserves it.
  - **Routes:** searched on the edge graph without U-turns (`routing.py`), since a 2.7 m wheelbase car cannot turn round in a 5 m lane. A spot on the far side of a street can mean a lap of the block.
  - **Pulling out:** only with a gap: no vehicle within 35 m behind in the lane (or about to turn into it) and none within 8 m ahead.
  - **Pull-out and pull-in:** the lane centreline the car steers along begins in the parking lane and shifts into the lane over 10 m, and at the end shifts back into the parking lane over 10 m, finishing 6 m before the stop so the car rolls into the bay straight (`sim._park_shift_at`, `PULL_IN_M`, `PULL_IN_STRAIGHT_M`). The shift follows a quintic smootherstep, whose curvature is zero at both ends. Curve + straight + rear overhang stay clear of a car in the bay behind.
  - **Steering while pulling out or in:** a Stanley controller (`vehicle_dynamics.stanley_steer`, gain 1) instead of pure pursuit: it turns the car to the path's heading at the front axle, so the heading settles within about a wheelbase. Pure pursuit (4.5 m+ lookahead from the rear axle) could not straighten the car in the space of a bay, and a shorter lookahead is unstable. Nothing slides or jumps.
  - **Slowing down:** the car brakes at 2 m/s² just in time to enter the pull-in at 2.5 m/s (`_pull_in_accel`).
  - **Stopping:** the car brakes to a stop at the spot, parks where it stands once within 0.15 m of it, and dwells 10 to 60 s (3 to 10 s in the two-block scenario). It ends about 2.5° off the kerb line (up to 6° in the first bay after a junction, where the pull-in starts during the turn) and within a few cm of the bay centre.
  - **Freeing the spot:** the spot it left is freed once it is 10 m clear of it.
  - `spawn_car` (a car at a node) is kept for tests and stops where its route ends (`unparked`).
- **Car-car crashes** (`crashes.py`): driver error, not physics.
  A follower closer than 1.5 m at more than 3 m/s crashes with 0.5% chance per tick, times `crash_risk_multiplier` (0 in the two-block scenario).
  Recorded in `Simulation.accidents` as `kind = "car_car"`, `cause = "rear_end"`.
- **Red-light runners** (`Car.obeys_signals = False`, scenarios only): ignore red and yellow. Pedestrians do not count them as held by a red when judging a gap.
- **Car-car collisions** (`car_collisions.py`, `sim._detect_car_collisions`): car bodies (4.5 x 2 m behind the front bumper) tested for overlap with the separating axis theorem; more than 5 cm counts.
  **Every pair of cars is checked.** Normal traffic keeps its distance, also across nodes and in junctions (rule R6), so an overlap is a real crash, e.g. a red-light runner.
  A crash records `kind = "car_car"`, `cause = "ran_red_light"` (a runner is the striking car) or `"collision"` (the faster car strikes), `car_id` (striking), `other_car_id` (struck), both speeds; both cars stop (`crashed`); nothing is dispatched until a call answers it (below).
- **Following across a node** (`sim._leader_across`): with nobody ahead on its own edge, a vehicle follows the last vehicle on the next edge of its route, e.g. one that has just turned in. Every gap is the smaller of the distance along the route and the straight line from the front bumper to the leader's rear (`sim._gap`): a turn curve cuts the corner, so the distance along the two edges overstates the real gap by up to a few metres.
- **Junction boxes** (`junctions.py`, `sim._junction_accel`): at a node where movements conflict (their turn curves come within 2.5 m: crossing, merging into one exit, or leaving one lane in different directions), a vehicle takes the box only when
  - no vehicle holding the box drives a conflicting movement,
  - there is room past the box and the exit crosswalk for its whole length (counting on the vehicle ahead to go on for 2 s at its current speed and braking), and
  - nobody is in its path on the crosswalk it enters or leaves over (`crossing_rules.pedestrian_in_path`: within 3.8 m of its lane centreline, or walking into it within 3 s; people on the far half walking away do not hold it).
  It decides as late as it can still stop comfortably (braking distance + 0.5 s of travel + 1 m before its stop line); otherwise it brakes to the line and asks again. It holds the box until its rear is past the turn curve on the exit, and gives it up if it stops at a red light or can still stop for a pedestrian. Red-light runners ignore boxes. Corners of two streets have no conflicts and no box.
  Pedestrians do not step onto a crosswalk that a holder past its stop line will drive over, nor in front of a car that has waited 4 s at its line with only them in its way (otherwise a stream of pedestrians can keep turning traffic waiting forever).
  Cars yield at any crosswalk by the same in-path rule.

## Pedestrians

- **Goal force**: steer toward the next walk node at the desired speed (1.4 m/s walking; `SocialForceState.desired_speed` per pedestrian, 3 m/s for runners), relaxation time 0.5 s. This is the Social Force model's driving term (Helbing and Molnar).
  A pedestrian waiting at a kerb slows down near the kerb point instead (desired speed at most distance / 1 s, `stop_at_goal`), so they stop there rather than overshooting and walking back again.
- **Facing** (`ped_facing.py`, `sim._update_pedestrian_facing`): the heading is the body's facing, not the velocity direction.
  Waiting at a kerb, a pedestrian faces across the crosswalk.
  Walking, they face their walking direction when it is within 60° of the direction to their goal; stepping aside or back in a crowd, they keep facing the goal; below 0.3 m/s the facing stays as it is.
  The body turns toward that facing at most 180°/s.
- **Avoiding each other: time-to-collision power law** (`ttc_avoidance.py`, Karamouzas, Skinner and Guy 2014).
  Each pedestrian reacts to how soon it would collide with a neighbour at current velocities, with energy `k / tau² * exp(-tau / tau0)`, k = 1.5, tau0 = 3 s, neighbours within 6 m.
  Our additions, needed at a 0.1 s tick: the force fades to zero for near-misses (no on/off chattering), it is capped at 8 m/s², it is low-pass filtered over 0.5 s (`social_force._filtered_avoidance`), a contact push of 20 per metre applies when bodies touch, and a perfectly head-on pair both keep right.
- **No overlap, guaranteed** (`ped_separation.py`): after the step, any two bodies closer than 0.6 m (2 x 0.3 m radius) are pushed apart along the line between them, a few passes.
  Separation and the walkway clamp alternate (up to `SEPARATION_ROUNDS` = 10, until nothing moves), because clamping a body back onto its strip can push it into a neighbour again.
- **Staying on the walkway**: a soft edge force toward the walkway centre, then a hard clamp so the body stays inside its sidewalk (±1.6 m) or crosswalk (±1.1 m) strip (`sim._keep_on_walkway`).
- **Walk network** (`walk_network.py`), derived from the road graph:
  - sidewalks on both sides of every street, split into pieces of at most 20 m (destinations have nearby nodes);
  - at each road node, the sidewalks of neighbouring streets join at the inner corner point; corners of 180° or more are walked round;
  - every arm of every intersection with 3+ streets gets a crosswalk joining its two sidewalks, signalised if the intersection has a light.
- **Pedestrian signals** (`traffic_lights.py`): after both car phases comes a pedestrian phase with every car light red, shared by all crosswalks of the junction.
  The cycle is 44 s: phase A 10 s green + 3 s yellow, phase B the same, then 6 s `walk` and 12 s `flash`, the time to clear 16 m of asphalt at 1.4 m/s.
  The viewer shows a signal at both ends of each crosswalk (`scene/PedestrianSignal.tsx`, from `frame.walk`): red, green, blinking green.
- **Crossing** (`crossing_rules.py`, `sim._pedestrian_may_cross`): a pedestrian arriving at a crosswalk waits at the kerb (`status = "waiting"`) until
  - signalised: the signal says `walk`, and
  - always: no vehicle that will drive over the crosswalk is closer than 10 m or less than 4 s away (cars held behind a red stop line are not counted).
  The first step of a route goes through the same check (a route can start with a crosswalk).
  If `walk` ends before a pedestrian who set off reaches the asphalt (e.g. slowed by a crowd), they stop at the kerb and wait again (`sim._hold_at_kerb_if_signal_changed`).
  Once on the asphalt a pedestrian keeps going, and cars yield to them.
  A `distracted` pedestrian (`ped_hit_risk`) ignores the signal and the gap, though still only crosses at crosswalks.

## Accidents, reckless road users, and what answers them

- **Car-pedestrian accidents** (`accidents.py`, `sim._detect_pedestrian_accidents`): every tick, each moving vehicle (at least 0.3 m/s) is a 4.5 x 2 m rectangle behind its front bumper; if it touches a pedestrian's 0.3 m disc, an accident is recorded in `Simulation.accidents`:
  `id, kind="car_pedestrian", t, x, y, car_id, pedestrian_id, car_speed_ms, pedestrian_on_crosswalk, cleared_t`.
  The car stops (`status = "crashed"`, blocks its lane), the pedestrian lies down (`status = "injured"`). **Nothing is dispatched**: the accident stays open, and its wrecks stay and block their lanes, until a call answers it (below).
  Open accidents are in `state()["accidents"]`.
- **Accidents on their own**: `build_simulation(car_crash_risk, ped_hit_risk)` draws per road user. A car with `car_crash_risk` runs red lights and does not wait for a free junction. A car with `ped_hit_risk` does not yield, and a pedestrian with it ignores signals and traffic gaps at crosswalks. Each risk causes only its own kind of accident; `twin/README.md` has the measured chances.
- **Calls that answer an accident** (the way City Brain's dispatch will, later):
  - `Simulation.clear_accident(id)` takes the wrecked cars and the injured pedestrian off the map at once and sets `cleared_t`.
  - `Simulation.dispatch_ambulance(id)` sends the nearest idle ambulance, which cleans up when it arrives, as below.
  Both return False for an unknown or already cleared accident.
- **Stations and emergency vehicles** (`stations.py`, `emergency_units.py`): `Simulation(stations=...)` takes a list of stations (`hospital`, `police_station`, `fire_station`), each with one parking bay per vehicle. The two-block map has three (`world/map.py`): a hospital (bay `4_1_1`) and a fire station (`4_1_3`) on the west street, a police station (`6_5_2`) on the north street, all on the outer side and on bays no staged scenario or parking test uses. Without a list, each generated hospital place becomes an ambulance station at its nearest free bay (the OSM map).
  - Each vehicle (`amb1`, `fire1`, `police1`, kinds `ambulance`, `fire`, `police`) starts **parked in its bay**, exactly as a parked car, and is in `state()["units"]` and in every recorded frame. Its bay stays reserved for it, also while it is out: civilian cars never park there.
  - A call (`dispatch_ambulance`, for now the only one) picks the idle unit of that kind with the shortest drive (`routing.route_between`, no U-turns) to a point 4 m behind the wreck in its lane, and sets it `dispatched`. It pulls out at the next gap, with the same check and pull-out path as a car (`_can_pull_out`, `_tick_unit_departures`). If none is idle the call waits in a queue, retried every tick.
  - It drives with IDM, MOBIL and the bicycle model like a car; with its siren on it breaks the rules (below). It is on scene once stopped within 25 m of the wreck: a car queued behind the wreck can hold it back, and nobody drives round a wreck, so the crew walks the rest.
  - On scene (`cleaning`) it stays in its lane as an obstacle that traffic queues behind (the old ambulance left the lane groups, so traffic could drive through it). After 4 s it removes the wreck and the injured pedestrian (they still vanish; towing and loading come with dispatch), sets `cleared_t`, and drives on from where it stands, round the block, back to its bay, where it pulls in like a car (`_head_home`, `_unit_home`).
  - Example, `ped-hit` with the ambulance called at t = 40 s: out of its bay at 40.0, on scene at 70.2 (queued behind a car that is stuck behind the wreck, 13 m from it), scene cleared at 74.1, parked back in its bay at 156.2, within 0.13 m and 2.3° of where it started.

## Emergency driving (`emergency_driving.py`)

A unit with its siren on, on its way to a scene or the hospital (`EmergencyVehicle.responding`):

- **The shortest way:** it can reach a wreck from either end of its street, in the opposite lane if that is shorter (`scene_targets`).
- **No signals:** it ignores lights, crossing against a red at 7 m/s at most, and drives at up to 19 m/s (68 km/h).
- **Junctions:** from 45 m out it claims the junction: no new car enters a movement conflicting with its own, and a car that reserved one but can still stop gives it up.
- **Queues:** with a car ahead in its lane it moves 2.6 m left and drives down the centre line, clear of its own lane by 0.6 m and of oncoming cars by 0.4 m. Oncoming cars pull over for it.
- **Obstacles:** it checks its own path against every vehicle body, brakes for what is there, and takes the other side if that is free (`_path_block`).
- **People:** it yields on crosswalks from where it really is, slows to 5 m/s for a crosswalk with someone on or beside it, and brakes fully for anyone in its path, now or a second from now, along its whole body (`_person_in_path`). The last check also applies with the siren off. Pedestrians do not step off on WALK in front of a responding unit.

## Witnesses, emergency calls and cameras

How the city finds out about an accident. Ground truth goes to `Simulation.timeline` (events `incident`, `witness_noticed`, `call_started`, `call_ended`, `camera_anomaly`, `false_report_started`, each with sim time `t`); the Twin turns calls and cameras into readings (`twin/src/twin/city/world.py`).
- **Witnesses** (`witnesses.py`, `sim._tick_witnesses`): a pedestrian (walking, waiting or dwelling), a driver standing still in traffic, or a driver in the crash itself (not hurt) sees an open accident within 40 m when the line to it stays in the street corridors (`Corridors.line_of_sight`: within the building line of some street; blocks hide it). Each one decides once whether to call: pedestrians 50%, drivers in traffic 30%, drivers in the crash 70%.
- **Calling**: after a reaction delay of 1 to 8 s (a pedestrian on a crosswalk finishes crossing first) the witness dials. A pedestrian gets `status = "calling"`, slows to a stop half a second of walking ahead (social-force goal, about 1.5 s, no stepping back), faces the accident, stands on the phone for 15 to 25 s, then carries on with what they were doing. A driver calls from the car.
- **What a caller says** (`witnesses.report`): the location with a 3 m error (10% of callers place it 15 to 30 m away), the category (`medical` for a pedestrian hit, `police` for a crash; 10% say something else), a confidence of 0.6 to 0.95. `Simulation.false_call_rate_per_min` (default 0) makes random pedestrians report something 10 to 30 m away where nothing happened.
- **Call centre** (`emergency_calls.py`): numbers calls (`call-0001`) and merges them into incidents (`inc-0001`): a call within 50 m of an open incident's first report, and within 300 s of its latest call, joins it. It does not use the truth; each call keeps `truth_accident_id` for the Twin's tests only.
- **Cameras** (`cameras.py`): one per signalised junction (`cam-n2`, `cam-n5` on the two-block map), seeing vehicles within 45 m in line of sight. Every tick: vehicle count and mean speed, and anomalies: `collision` (a crashed vehicle, after 2 s) and `stopped_vehicle` (on the road, not parked, not at a red light, still for 30 s).
- Witnesses and callers draw from their own generator (`Simulation(incident_seed=...)`, the scenario seed), so they do not change a seed's traffic.
- Measured (90 s runs, seeds default and 1-5): `ped-hit` gets 1 or 2 calls on every seed, all merged into `inc-0001`, the first 2 to 41 s after the hit; `car-crash` gets 2 to 5 calls when the crash happens, the first 2 to 33 s after it. The camera flags both crashes 2 s after them.

## Buildings and fires

A map names its buildings; `world/buildings.py` makes them for the two-block map.
Without a list (the OSM map) nothing can burn.

- **Buildings** (`buildings.py`, `world/buildings.py`): a ring of boxes around every block, behind the sidewalks (12 m from a street's centreline), each 14 m deep and about 12 m wide, with a metre between neighbours.
  That is 12 per block and 24 in all, ids `bld-<block>-<n>`.
  Heights are drawn per block from a fixed seed (8 to 30 m).
  `front` is the point on the street face, half a metre inside the street corridor: where people see the building from.
  `adjacency` says which buildings touch (within 3 m wall to wall).
  Nothing touches across a street (24 m), so a fire never jumps one.
  The viewer draws the boxes from `map.buildings` (older recordings without it get the viewer's own ring).
- **Fires** (`fires.py`, `FireModel`): a fire is a record like an accident, with `kind = "building_fire"`, `building_id`, `x`, `y` (the building's `front`), `t`, `cause` (`operator`, `scenario`, `random` or `spread`), `source_fire_id`, `cleared_t` and `incident_id`.
  It grows from 0 to 1 over 30 s.
  Three things start one: `Simulation.ignite_building(id)` (the fire simulator; idempotent, a burning building answers `duplicate`), a building drawn as fire-prone by `fire_risk`, and spread.
  `fire_risk` is per building: with that chance it catches fire once, at a random moment 20 to 150 s in (`build_simulation(fire_risk=...)`, `CityParams.fire_risk`, `TWIN_FIRE_RISK`; default 0).
  A fire that has burnt for 40 s tries every 15 s to set each touching neighbour alight, with 50% chance each.
  The model has its own random generator, seeded from `incident_seed`, so arming it never changes what the traffic of a seed does.
- **How the city notices**:
  - the building's smoke sensor trips at strength 0.1 (3 s after it starts): `smoke_detected` in the timeline, and the call centre opens an incident at the fire or joins the one already open there (`CallCentre.alert`, as for a camera's collision), so the fire has an `incident_id` the Brain can dispatch to;
  - witnesses see a fire at strength 0.2 (6 s) from up to 40 m with a clear line of sight to its `front`, and call it in like an accident: pedestrians 50%, drivers stuck nearby 30%, category `fire` (10% say something else);
  - a camera sets `smoke_detected` while a burning building is within 60 m (smoke rises above the roofs, so only distance matters);
  - sensor values come from `FireModel.sensor_values`: 20 to 400 C and 420 to 5000 ppm CO2, as the strength goes from 0 to 1.
- **Keeping away** (`fire_hazard.py`, `FireResponse._update_hazards`): streets, sidewalk pieces and crosswalks within 25 m of a burning building cost more to route through (+600 s for a car street, +1000 m for a walk).
  They are an avoidance, not a closure: with no other way, drivers and pedestrians go through, so a fire never freezes the city.
  - Cars: `_turns_open` carries the penalty. Cars on their way take a better route when there is one (`_reroute_around_closures`, now also for avoided streets). A car heading for a parking spot on an avoided street picks the nearest free spot that is not (`_retarget_trips`), and nobody parks there (`free_spots_near(avoid_edges=...)`).
  - Pedestrians: routes through avoided pieces are recomputed from the node they are heading for (`_reroute_pedestrians`), and places within 25 m are not chosen as destinations.
  - Emergency units ignore the penalty.
  - Measured (busy city, fire at 20 s, 4 seeds): pedestrian time within 25 m of the building falls from 1342 to 4117 ticks to 373 to 824 (2.4 to 5.5 times less); nobody stands still longer than 17 s (15 s without a fire).
  - On the two-block ring most trips have no other way (a car parked on the west street has to drive through the south street), so cars avoid it only when they can. The routing is tested on a 3 x 3 grid, where there are detours (`tests/engine/test_fire_avoidance.py`).
- **Fire brigade** (`fire_response.py`): `dispatch_unit("fire", incident_id)` works as for the other units, and the response also holds the fire (`fire_id`, `fire_ids`).
  - The truck stops in the lane in front of the building it reaches soonest (either direction of the street within 20 m, `_fastest_lane_position`; a car cannot turn round, so the nearer lane can mean a lap of the block).
  - On arrival the phase goes `on_scene`, then `firefighting`.
  - It puts out the nearest burning building of the connected cluster (the one it was sent to, everything burning that touches it, and what catches fire meanwhile), 4 s each (`EXTINGUISH_S`).
  - When none is left the phase is `cleared`, the unit drives home, and the response is `closed` once every unit is back.
  - Police and ambulances sent to a fire look round for 10 s and leave.
  - Timeline events: `fire_started`, `smoke_detected`, `unit_dispatched`, `unit_pulled_out`, `unit_arrived`, `firefighting_started`, `fire_extinguished`, `scene_cleared`, `unit_left_scene`, `unit_back_at_station`.
  - Example, `building-fire` with the truck called at 6 s: out of its bay at 6.1, on scene at 22.3 (a 16 s drive), the fire out at 26.3, back in its bay at 110.4.
  - A fire that nobody answers spreads: with seed 7 and no truck, a second and third building catch fire at 50 s, and ten buildings burn at 145 s.
- **Sirens and junctions** (`incident_response._tick_yielding`): a car pulls over for a siren only when the unit is on the car's own edge, not when it is still before the junction behind it.
  Before, a car just past a corner could pull over and stop in the junction's exit, in the way of the unit's turn, and the unit waited for it while the car waited for the unit to pass, so neither moved.
  This showed up as soon as the fire station's truck had to turn the corner at node 1 with traffic on the street after it.
  A first try (skipping pulled-over cars across the node, or delaying the yield until 20 m past it) made the unit squeeze past with overlapping bodies, and was dropped.
  Measured with an ambulance and a police car sent to `ped-hit` and `car-crash` (seeds 1 to 6), and a fire truck in `building-fire` (seeds 7, 3, 11): no car body overlaps beyond the crash itself.

## Rain and floods (`flood.py`, `flood_response.py`)

- **Rain** (`RainProfile`): intensity in mm/h, linear between `(t, mm_per_hr)` points, 0 outside them. A zone gets the heavier of the city's rain (`Simulation.rain`, dry by default) and its own (`FloodZone.rain`): the `flood` scenario and `flood_street` rain on one street only.
- **Flood zones** (`FloodZone`, `flood_zones` in `world/map.py`): one per street, each with a storm drain and a pump, `dip-<u>-<v>` and `pump-<u>-<v>`. `dip-2-3` is the flood scenario's, its low point 38 m from node 2; the others have theirs mid-street. The rest of this section describes `dip-2-3`; the others have the same size.
- **Flooding a street** (`flood_street(zone_id)`, the flood simulator): blocks the zone's drain and brings a downpour over it, 0 to 120 mm/h in 20 s, two minutes at 120, then off over 30 s. Idempotent while it pours. A blocked drain takes nothing (`drain_blocked`), so only the pump empties the dip; the drain is clear again once the street is dry and it no longer rains (`drain_cleared`).
- **`flood_risk`** (`arm_floods`, `CityParams.flood_risk`, `TWIN_FLOOD_RISK`): each street floods this way with that chance, once, at a random moment 20 to 150 s in, on its own random generator. In the city, red-light runners also ignore the water (`Car.ignores_flood`) and pedestrians who ignore signals walk into it (`Pedestrian.ignores_flood`), with no extra draws, so a seed's traffic is the same.
  - The street dips 0.5 m below its ends, as a parabola z(s) = -H (1 - (s/L)^2) along it. Its low point is 38 m from node 2, and the dip reaches L = 24 m either side of it.
  - Across, the water fills the road kerb to kerb (8 m from the centreline). It reaches the sidewalks only where it is deeper than the kerb (0.15 m).
  - Each tick, water comes in by the rational method Q = C i A (C = 0.9, catchment 80 000 m²): 2.4 m³/s at 120 mm/h.
  - It drains through the storm drain (0.3 m³/s) and, when it is on, the pump (`pump-2-3`, 1.2 m³/s).
  - The volume in the dip is V = 4/3 W L d^1.5 / sqrt(H), so the depth at the low point is d = (3 V sqrt(H) / (4 W L))^(2/3). It tops out at 0.45 m, where the water would spill on down the street.
  - `water_depth_at(x, y)` gives the depth anywhere: deepest at the low point, thinner up the dip, less by the kerb height on a sidewalk.
- **What the water does** (`FloodResponse`, mixed into `Simulation`). Timeline events: `rain_started`, `rain_stopped`, `water_rising`, `street_flooded`, `street_passable`, `water_drained`, `pump_started`, `pump_stopped`.
  - At 0.2 m the street is **no entry** in both directions (`flooded_edges`), until it is below 0.15 m again. Cars that can reroute do, on a turn graph without the flooded edges.
  - A car whose only route, or whose parking spot, is through the water parks in the nearest free spot it can reach on a dry street (`car_parks_elsewhere`). If there is none, it drives through slowly (`car_drives_through_flood`).
  - Cars already in water deeper than 0.05 m slow to 2.8 m/s, a wading speed.
  - A car with `ignores_flood` (the staged driver) drives in. With 0.3 m of water under its front bumper it **stalls** (`status = "crashed"`, `stalled`).
  - The stall is an accident: `kind = "flooded_car"`, `cause = "drove_into_flood"`, `water_depth_m`, `flood_zone_id`. The driver calls (95%) and witnesses report it, with category `flood`.
  - A camera that sees the car flags a `stopped_vehicle`, not a collision.
- **Pedestrians and the water.** Depths here are on the sidewalk: the road's depth less the 0.15 m kerb.
  - In water deeper than 0.05 m they walk at 0.7 m/s at most.
  - Routes cost 50 times the length on a wet sidewalk piece, and never use a piece with 0.10 m or more anywhere on it (`PED_STOP_DEPTH_M`). The water is sampled along each piece, because sidewalk nodes are 20 m apart and the low point lies between two of them.
  - A walking pedestrian looks 1.5 m ahead. If the water there is 0.10 m deep or more, and deeper than where they stand, they turn back (`pedestrian_turned_back`) and take another way, or wait at the dry end when there is none.
  - Someone standing still (dwelling, waiting) when the water reaches 0.05 m at their feet walks out to the nearest dry sidewalk node (`pedestrian_leaves_water`).
  - In 0.20 m or more (`PED_TRAP_DEPTH_M`: moving water that deep can knock an adult over) anyone is **trapped**: `status = "trapped"`, standing still. That is an accident `kind = "trapped_pedestrian"` (`car_id` None, `pedestrian_id`, `cause` `walked_into_flood` or `caught_by_rising_water`, `water_depth_m`, `flood_zone_id`). They call for help themselves (95%), and witnesses report it with category `flood`.
  - Only a pedestrian with `ignores_flood` (the staged one) walks in that deep. Rising water could in principle catch a careful one; it has not on 12 seeds.
- **Response**:
  - A fire truck on scene starts the rescue (`rescue_started`). Its crew gets out everyone trapped in the zone, one at a time and nearest first, 20 s each: a driver (`driver_rescued`), a pedestrian (`pedestrian_rescued`), and anyone trapped later while they are still there. A rescued pedestrian is led to the nearest dry sidewalk node and carries on walking from there. No ambulance is needed.
  - A unit sent to an incident goes to its car when there is one. For a trapped pedestrian alone it goes to the nearest lane, with the police a few metres behind the fire truck. The police close the flooded street both ways.
  - The scene is cleared once nobody is left in the water, the water at every stalled car is down to 0.15 m, and the police have closed the street. Every stalled car is then towed and every flood accident closed. Until then the phase is `waiting_for_water` (or `towing`).
  - `set_pump(state, pump_id | incident_id)` starts or stops the pump. It answers `duplicate` if the pump is already in that state.
  - With the pump, the default seed clears at about 270 s. On the storm drain alone it takes about 850 s.
- **Yield deadlocks:** the flood branch fixed two with its own rules (`YIELD_CLEAR_OF_EXIT_M`, `SIREN_BLOCKED_S`). When it was rebased onto the emergency driving, those were dropped for the rules already on `main`: cars yield only to a unit on their own edge, and a unit passes on the centre line (Emergency driving, below).

## Scenarios (`world/scenarios.py`)

A scenario is random background traffic plus a script run before every tick that stages one event.
Scripts trigger on what the actors are doing (light state and time left, the road being clear, a car's distance and speed), not on fixed times, so the event still happens with other background seeds.

- `city` (the default): `CityParams(cars=20, pedestrians=40, car_crash_risk=0.1, ped_hit_risk=0.1)`, a tenth of the pedestrians run, seed 7. `CityParams().clean()` is the same traffic with nobody reckless: no accidents expected, though a car queuing over 30 s does raise a `stopped_vehicle` camera alert.
- Staged cars start parked in the first free spot of their street, with a destination spot reserved, and pull out on cue (`sim.start_trip(car, spot, force=True)`). Nothing appears mid-street.
- `ped-hit`: `careless_car` (`yield_to_pedestrians = False`) is parked on street 1-2 near node 1, and a distracted pedestrian stands at the south kerb of crosswalk `cw_2_1` (x = 70).
  The car pulls out in the last 5 s before the west-east green if the road ahead is clear. The pedestrian steps out without looking when the car's estimated arrival, from its speed and acceleration, is 6.4 s away.
  The car hits them in the eastbound lane at about 10 m/s, at t = 48.7 s with seed 7, the default. The accident is flagged with `pedestrian_on_crosswalk = True` and stays open. Over seeds 1-12 it hits within 93 s on all of them (measured 2026-11-08), most at 48.7 s. Witnesses are random: the default seed is chosen for a call 1.5 s after the hit, and on seeds 5 and the like no call comes within 120 s.
- `car-crash` (default seed 4): `crossing_car` is parked on street 3-2, and `red_light_runner` on street 5-2 (`obeys_signals`, `yield_to_pedestrians` and `slows_for_turns` all False).
  The crossing car pulls out in the last 5 s before its green when:
  - nothing is ahead of either car;
  - nobody is near crosswalk `cw_2_5`;
  - the runner can pull out.
  The runner pulls out 0.6 s later (tuned by a sweep).
  The runner's front hits the crossing car's side in the westbound lane at node 2 (78.9, 3.0) at about 10.4 m/s, at t = 49.7 s with seed 4. It crashes within 240 s on 12 of background seeds 1-12 (measured 2026-11-08), between 50 and 140 s, since the longer cycle leaves fewer windows. With seeds 1, 2 and 10 a background car follows the runner into node 2 and is trapped behind the wreck past its stop line, which the rule check counts as R3 and R5 violations.
  The background is lighter (2 cars, 2 pedestrians): with more, a car is almost always queued on one of the two streets, or someone waits at `cw_2_5`.
- `flood` (default seed 3; 6 cars, 10 pedestrians, one runner).
  - A cloudburst rains 120 mm/h from t = 30 s to 150 s, ramping up from 10 s and down to 180 s.
  - `flood_driver` (`ignores_flood`) is parked on street 6-3, with a trip through street 3-2 to street 2-1. It pulls out once the water is 0.27 m deep and the road ahead is clear.
  - `flood_walker` (`ignores_flood`) stands at the west end of the north sidewalk of street 2-3 and walks along it once the water is 0.33 m deep. They are trapped about 7 m before the low point, at about 108 s.
  - Street 2-3 is no entry from about 52 s, and the car stalls in about 0.35 m of water at about 94 s. Nothing is dispatched until a call is answered.
  - Measured 2026-11-08: on 12 of 12 seeds, exactly the driver stalls and the walker is trapped, and nobody else. 0 to 3 careful pedestrians turn back at the water each run. With fire, police and the pump sent 8 s after the first call, all 12 close, at 432 to 509 s.

- `building-fire`: `bld-01-03`, on the south street 47 m from the camera at node 2, catches fire at 10 s (`FIRE_START_S`).
  The background is light and clean (6 cars, 12 pedestrians).
  Everything else is the engine: the smoke sensor, the witnesses, the drivers and pedestrians who keep away, the spread if nobody answers, and the truck once it is called.
  It starts on every background seed.

`python -m twin.world.record --scenario NAME` records one (`--call-fire-at T` sends the fire truck at T s); `tools.check_rules.run_movement_checks(seconds, scenario=...)` checks the rules on one.

## Exports

- `active_calls()`: who is on the phone right now; `call_centre.calls` / `.incidents`; `cameras`; `timeline`.
- `state()`: per tick, cars, pedestrians (with `speed` and `status`), emergency units (with `kind`, `station_id`, `status`), light states, active accidents, burning fires (with `intensity`), occupied parking spots.
- `stations_geometry()`: each station's bays and the point on its building line, for the viewer.
- `road_geometry()`, `parking_geometry()`, `walk_geometry()` (street profile numbers, crosswalk end points, stop lines), `places_geometry()`, `buildings_geometry()`.
  `world/record.py` writes these into the viewer's recording.
