# Fixes and Changes Relative to the POC Engine

> This is a history. `normal` and `busy` were the two default scenarios until 2026-11-08, when one configurable `city` replaced them, and paths like `app/` and `two_blocks/` are now `src/twin/engine/` and `src/twin/world/`. Measurements are from the code of their time.

The first engine commit in this folder is the POC engine unchanged; `git log -- simulation/app` shows each change below as its own commit.
Numbers come from the tools in `simulation/tools/`, so they can be reproduced.

## 1. Pedestrian avoidance: Social Force repulsion replaced by the time-to-collision power law

- **Why**: distance-based repulsion reacts late and makes people zig-zag; the anticipatory model reacts to how soon a collision would happen.
- **What**: new `ttc_avoidance.py`; `social_force.py` keeps the goal force and edge force and uses the new avoidance. The old "step right" hack is gone (a tie-break handles exact head-on approaches).
- **Problem found while doing it**: the paper's force alone chattered at our 0.1 s tick (30-person plaza: 1456° of turning per person vs 337° before). Cause: the force switches on and off between neighbours tick to tick. Fixed with a near-miss fade-out, a 0.5 s low-pass filter, and a stiffer contact push (20).
- **Result** (`tools/avoidance_comparison/compare.py`, turning per pedestrian, lower is smoother):

| Scenario | Old | New |
|---|---|---|
| head-on, exactly in line | 109° | 55° |
| head-on, 0.2 m offset | 81° | 21° |
| crossing at 90° | 104° | 43° |
| side by side, same way | 59° | 0° |
| two groups of 5, head-on | 146° | 68° |
| plaza, 30 random | 337° | 210° (closest gap 0.41 m both; mean arrival 18.4 s to 14.9 s) |

- Also added: `SocialForceState.desired_speed` per pedestrian (default 1.4 m/s, unchanged behaviour), so some pedestrians can run.

## 2. Movement rules

Asked for: pedestrians only on sidewalks and only crossing at crosswalks; a car hitting a pedestrian is flagged as an accident; pedestrians never collide with each other; cars stop before the light instead of past it.
`tools/check_rules.py` measures each rule from positions only; it was run on the POC engine first to reproduce the problems:

| Rule (`check_rules`) | POC engine, 5 cars / 5 peds | POC engine, 15 / 25 | Now (both) |
|---|---|---|---|
| R1 walking ticks on the road outside a crosswalk | 5974 of 8210 | 28829 of 42027 | 0 |
| R2 ticks with two pedestrians overlapping | 8 | 158 | 0 |
| R3 ticks a car stood at a red light past the crosswalk | 665 | 2026 | 0 |
| R3 cars pushed backwards along their edge | 0 | 2 | 0 |
| R4 forced car-pedestrian collision flagged | no detection at all | | flagged, in `state()`, cleared by an ambulance |

Liveness after the change (`tools/liveness.py`, 300 s): 14 to 91 crosswalk crossings per run, waits at the kerb 7 to 9 s on average and 20 s at most, cars and pedestrians keep completing trips, no deadlock.
No accidents happen in normal runs, even with distracted pedestrians, because cars yield; `two_blocks.record --accident-demo` made every driver careless to show the accident handling (replaced on 2026-11-02 by the scripted `ped-hit` scenario, see `engines.md`).

### Root causes and fixes

- **Pedestrians crossed streets anywhere.** The POC put pedestrians on the car graph, offset to the right of their walking direction, so every turn or reversal cut diagonally across the street. Fixed with a separate walk network (`walk_network.py`) where the only street crossings are crosswalks, and a hard clamp that keeps each body inside its sidewalk or crosswalk strip.
- **Lateral positions disagreed.** Car lanes, parking spots (8.7 m) and the pedestrian line (9.5 m) used different formulas, so parked cars stood on the walking line. Fixed with one cross-section (`street_profile.py`) used everywhere.
- **No pedestrian rules at crossings.** Added waiting at the kerb for red and for a safe gap (`crossing_rules.py`) and cars yielding to occupied crosswalks.
- **Pedestrians could overlap.** Forces only make overlap unlikely. Added a hard separation step (`ped_separation.py`).
- **Stop line inside the intersection.** It sat 3 m from the intersection centre. Now it is 1 m before the crosswalk (12.5 m from the centre on this map).
- **Cars snapped back to the stop line.** When a light turned, every car on the approach was clamped to the stop line, including cars already past it. Now only cars the light actually holds are kept behind it.
- **Hard stops on yellow.** Every car before the line stopped on yellow, however close. Now a car that cannot stop comfortably goes through.
- **No accident detection.** Added the car-body vs pedestrian check, the accident record, injured and crashed states, ambulance dispatch and clearing (`accidents.py`, `sim.py`).
- **Ambulance never dispatched** (existing bug, found through the accident test): dispatch only tried the nearest idle ambulance, and failed for good when that ambulance was based at the crash node (route of length 1). Now it tries every idle ambulance and both ends of the crash edge.
- **Parked car positions.** Parked cars were placed by their centre while driving cars are tracked by their front bumper. Now a parked car's position is its front bumper too; parking spots keep 14 m clear of intersections.

## 3. Map passed in

`Simulation(graph=...)` accepts any road graph shaped like the OSM one; the two-block map uses it. Without an argument it still loads the OSM map.

## 4. Stricter pedestrian checks, and the crossing bugs they found (2026-11-02)

New checks in `tools/check_rules.py`, run over seeds 7, 11 and 23 in the tests (and swept over seeds 1 to 30):
R1 now also covers standing (`arrived`) pedestrians; R1b body never past the building line (into a block or off the map); R1c the straight path between two ticks never crosses asphalt outside a crosswalk; R1d a pedestrian who is not distracted steps onto a signalised crosswalk only on car-red.
A test also checks that the hand-written spec constants match `street_profile` and the walk network.

| Check, 30 seeds x 2 configs, 180 s | Before | After |
|---|---|---|
| R1b, R1c | 0 | 0 |
| R1d entered a crosswalk on car-green | 0 to 6 per run, most runs | 0 |
| R2 overlap ticks | 1 to 9 in 7 of 30 dense runs | 0 |

Root causes and fixes:
- **Committed too early.** A pedestrian decided to cross 1.5 m before the kerb node (the arrival radius) while cars had red, and reached the asphalt after it turned green. Now crossing needs the red to last the walk to the asphalt plus 1 s (`TrafficLight.seconds_until_change`, `crossing_rules.RED_MARGIN_S`), and a pedestrian slowed down on the way stops at the kerb if the light turns.
- **First step unchecked.** `_walk_to_node` started routes at `edge_index = 1`, so a route starting with a crosswalk skipped the signal and gap check. Routes now start at `edge_index = 0`.
- **Clamp undid separation.** The walkway clamp ran after separation and could push a pair back into each other (e.g. one clamped to a crosswalk edge at a corner). They now alternate until settled.

Liveness (300 s, `tools/liveness.py`): crossings 21 / 84 / 92 (were 14 / 86 / 93), trips unchanged, mean wait 6.4 to 10.2 s.

## 5. Car-car collisions (2026-11-02)

Added geometric car-car collision detection, red-light runners, and the `car-crash` scenario (see `engines.md`).
Before wiring detection in for every pair, overlaps were measured in normal traffic (`car_collisions.overlap_depth` on every pair of moving cars, 180 s, seeds 7, 11 and 23):

| | spike 5/5 | dense 15/25 |
|---|---|---|
| ticks with two car bodies overlapping, all pairs | 19 to 78 | 600 to 850 |
| ... leaving out cars on the same edge or leaving the same node | 2 to 8 | 10 to 37 |

Causes, both pre-existing engine simplifications:
- **Trips start at the node centre at distance 0**, so cars starting at the same node stand inside each other, and a car starting at an intersection sits in crossing traffic.
- **IDM sees no leader on the next edge**, so a car turning into a street drives into a car that has just turned in, and bodies trail back across the node at the instant turn.

So detection runs only for red-light runners for now. Checking every pair needs trips to start from parking spots and a cross-edge leader lookahead first.

## 6. Smooth turns and pedestrian animation (2026-11-02)

- **Cars snapped at every node.** `_update_xy` placed a car on the straight lane of its current edge, so at a node its heading turned by the whole angle in one tick and it jumped about 3.5 m sideways to the new lane. Now it follows a curve through the node (`turn_paths.py`).
  Measured with `tools/motion_smoothness.py` (normal scenario, 180 s, 6534 driving ticks):

| | Before | After |
|---|---|---|
| ticks turning more than 20 degrees | 13 | 0 |
| largest turn in one tick | 90 degrees | 11 degrees |
| sideways or backward jumps over 0.5 m | 13 (up to 3.4 m) | 0 |

- **Viewer:** gait thresholds with hysteresis, no clip restart when going back to a clip still fading out, smoothed pedestrian turning, a short fall when hit.
- **Still open:** cars leaving a parking spot teleport to the node centre (up to about 30 m), parking is a 1.6 s straight slide, and an ambulance teleports to its route's end node (up to one edge, 80 m here) when it starts back after cleaning. `motion_smoothness` reports the last one in the `ped-hit` and `car-crash` scenarios.

## 7. Vehicle dynamics: bicycle model and pure pursuit (2026-11-02, branch feat/realistic-physics)

Before, a car's position was drawn on the lane (or a turn curve) from `dist_on_edge`, and its heading was the lane's direction there. Speed jumped to 0 on arrival and on yellow-light clamps, and stop-line overshoots were snapped back.
Now the bicycle model moves the car (see `engines.md`), and `dist_on_edge` is measured from where it really is.
Removed along the way:
- the stop-line clamp (it teleported cars back);
- the rear-end crash snap;
- the instant stop on arrival (cars brake to the end of the route).

`tools/continuity.py` (normal 180 s, ped-hit and car-crash 90 s), before / after:

| | normal | ped-hit | car-crash |
|---|---|---|---|
| teleports | 201 / 81 | 30 / 28 | 56 / 16 |
| slides | 341 / 327 | 96 / 105 | 119 / 102 |
| sideways motion (crab) | 377 / 231 | 89 / 88 | 120 / 69 |
| over-turning (yaw) | 638 / 451 | 175 / 162 | 187 / 165 |
| over-braking | 42 / 10 | 12 / 5 | 15 / 5 |
| **of those, by cars while driving** | many / **0** | many / **0** | many / **0** |

All that remains comes from parking (step 3), pedestrians (step 7), crash moments (step 5) and ambulances (step 6).
Driving cars in normal traffic: acceleration at most 1.2 m/s^2, braking up to 8 m/s^2, jerk up to 46 m/s^3 (the tick a car comes to rest), lateral acceleration at most 2.5 m/s^2. The largest heading change per tick went from 11 to 3.7 degrees.
The full-braking event in `normal` is a real emergency stop: the scenario's distracted pedestrian steps onto `cw_2_1` on a car green at t = 56.7 s.

Liveness: fewer car trips (52 to 39 in 300 s, spike) and lower mean speed (5.9 to 4.2 m/s), because cars now slow for corners and brake to a stop at their destination.
The checker also changed: the vehicle checks follow the rear axle, worked out from the recorded front bumper and heading, because a real front bumper legitimately swings out in a turn.

## 8. Cars live in parking spots: no spawn overlap, no slide, no teleport (2026-11-02)

Before, cars were created at a random road node, trips ended at the node nearest the destination (an intersection centre on this map), and a car then slid sideways into a spot in 1.6 s. The next trip teleported it back to the node.
Two of your viewer observations came from this:
- **Two cars bumper to bumper at t = 23 s:** `car0` and `car3` both started trips from corner node 6 within a second of each other, their bodies overlapping by up to 0.85 m.
- **A yellow car across a crosswalk at t = 36 s, then on it at t = 48 s:** the taxi's parking slide went across `cw_2_1`, and its next trip started in the centre of node 2 and crept over `cw_2_5` from rest on a green. Neither was a red light.

Now cars spawn in spots and drive spot to spot (see `engines.md`); staged scenario cars start parked too.
New rules in `tools/check_rules.py`:
- **R5:** a car never stands on a crosswalk or in a junction box.
- **R6:** no two car bodies overlap.

Both are measured but marked open (`OPEN_RULES`, strict expected-failure tests) until step 4.

| (seeds 7 / 11 / 23, 180 s) | Before | After |
|---|---|---|
| R6 car overlap ticks, spike 5/5 | 49 / 49 / 150 | 86 / 30 / 9 |
| R6 car overlap ticks, dense 15/25 | 483 / 693 / 725 | 59 / 251 / 209 |
| R5 car standing on a crosswalk or in a junction, spike | 279 / 110 / 42 | 68 / 70 / 27 |
| R5 ... dense | 775 / 640 / 410 | 468 / 671 / 352 |
| continuity, vehicles, normal (teleport / slide / crab) | 81 / 327 / 231 | 0 / 0 / 0 |

R5 and R6 still fire because:
- cars have no leader across an intersection (a car turning in drives into one that has just turned in);
- queues back up into the junction behind a car that is parking or giving way;
- a car that entered on yellow stops in the box for a pedestrian on the exit crosswalk.

Step 4 (look-ahead across the intersection, entering only when the exit is clear) addresses all three.
Liveness (300 s): car trips 25 / 63 / 66 (spike / dense / dense with distracted pedestrians). Each trip is now a full spot-to-spot drive with pull-out and pull-in, sometimes a lap of a block because there are no U-turns. Mean speed is about 3.3 m/s.

## 9. Pedestrians no longer spin on the spot (2026-11-03)

In the viewer, pedestrians sometimes turned round and round where they stood.
The recorded heading was the velocity direction whenever the speed was above 0.001 m/s, and three things made that velocity swing:
- **Waiting at a kerb:** the goal force pulled toward the kerb point at full walking speed at any distance, so a waiting pedestrian overshot it, came back, overshot again (up to 0.7 m/s back and forth), turning 180° each time.
- **Standing:** separation nudges left a few cm/s of velocity in random directions, and the heading followed them.
- **Crowds:** in a head-on standoff, avoidance pushed a pedestrian backwards or sideways, and the body turned round to face that way.

Fix: waiting pedestrians slow down onto the kerb point, and the heading is now a body facing (see `engines.md`, Pedestrians, Facing).
`tools/ped_turning.py` counts 3 s windows where a pedestrian turns more than 360° while moving less than 1 m; `tests/test_ped_turning.py` requires none in every scenario.

| (180 s, spin windows) | Before | After |
|---|---|---|
| normal | 48 | 0 |
| busy (50 cars, 100 pedestrians) | 6676 (69 pedestrians) | 0 |
| ped-hit | 252 | 0 |
| car-crash | 133 | 0 |

Pedestrian flow is unchanged: over 6 seeds of dense 15/25 with 5 distracted pedestrians, crossings 469 before and 483 after, pedestrian trips 477 and 468.
The viewer now follows the recorded facing at any speed (before, it ignored headings below 0.05 m/s to hide the noise), so a waiting pedestrian visibly turns to the crosswalk.

## 10. Cars park straight, and are drawn their simulated size (2026-11-03)

In the viewer, parked cars stood crooked across their bay, and cars looked like they drove into each other.
- **Crooked parking:** the pull-in curve ended exactly at the stop, so the rear axle (3.7 m behind the bumper) was still on it; cars arrived at 7 to 8 m/s, and pure pursuit, looking 4.5 m+ ahead, steered gently. Every car that parked after a trip stood 19 to 25° off and up to 1.4 m sideways.
  Fix (see `engines.md`, Parking and trips): the curve ends 6 m before the stop, the car slows to 2.5 m/s first, a Stanley controller steers it in, and it parks within 0.15 m of the spot.
  A short pure pursuit lookahead (1.5 m) was tried first: it aligned cars on straight streets, but its target lies between the axles and cars after a turn swerved up to 5 m onto the sidewalk.
- **Drawn size:** the Kenney models were drawn 2.4 m wide and up to 5.2 m long on 4.5 x 2.0 m sim bodies, so cars a legal 0.2 m apart looked like they touched. Each model is now scaled to fit inside the body (`viewer/src/actors/carFit.ts`).

| | Before | After |
|---|---|---|
| parked after a trip, heading off the kerb line (normal) | 19 to 25° | median 2.3°, max 4.3° |
| ... sideways off the bay centre | up to 1.37 m | up to 0.08 m |
| test trips into bays with both neighbours parked, worst heading | 19° | 2.5° |
| overlaps between a moving and a parked car (normal / busy, pair-ticks) | 36 / 18 | 0 / 0 |
| car trips in 300 s, 6 seeds (dense 15/25 + 5 distracted) | 330 | 301 |

Parking is slower (2.5 m/s into the bay), hence about 9% fewer trips. Pedestrian waits at kerbs are unchanged (mean about 10 s over the same 6 seeds).
Overlaps between moving cars at junctions remain (rule R6): the next step.

## 11. Cars no longer drive through each other at junctions (2026-11-03)

Cars looked like they drove into each other, and in the sim they did: a car only followed the car ahead on its own edge, so it drove into one that had just turned in front of it, and nothing kept two cars from entering a junction on crossing or merging paths. Car-car collisions were only checked for red-light runners, because normal traffic overlapped all the time.
Now cars follow across nodes, measure gaps as a straight line through turns, and take a junction only when it is free for their movement and they can clear it (see `engines.md`, junction boxes). Every pair of cars is checked for collisions, and rules R5 (no car standing on a crosswalk or in a junction) and R6 (no car bodies overlapping) are enforced by the tests.

| (seeds 7 / 11 / 23, 180 s) | Before | After |
|---|---|---|
| R6 car overlap ticks, dense 15/25 | 69 / 138 / 126 | 0 / 0 / 0 |
| R6, busy 50/100 | 559 / 258 / 614 | 0 / 0 / 0 |
| R5 car standing on a crosswalk or in a junction, dense | 583 / 597 / 254 | 0 / 0 / 0 |
| R5, busy | 1642 / 1620 / 1604 | 0 / 0 / 0 |
| accidents in normal traffic | 0 | 0 |

R5 now leaves out cars giving way to a pedestrian on the crosswalk just ahead (e.g. a distracted one stepping out in front of a car already in the junction), and ambulances, which stop at the scene.

Flow (dense 15/25, 300 s, seeds 7 / 11 / 23): 168 car trips before, 129 after; the longest a car waits is 23 / 41 / 52 s (14 / 16 / 24 s before), within two 26 s light cycles. Pedestrian waits at kerbs are unchanged.
Things found and fixed on the way:
- deciding to enter a junction exactly at braking distance let cars overrun the line (brakes take time to build up): the decision now adds 0.5 s of travel;
- a car that reserved a junction on green kept it while waiting out a red, blocking the green direction: it now gives it up, but only for the junction ahead (releasing the one it was still leaving caused crashes);
- a turning car waited for a whole wide crosswalk to empty: it now only waits for people in or walking into its path, and pedestrians let a car go after it has waited 4 s;
- the pull-in braking started too late before a bay right after a junction (brakes build up over 0.5 s) and cars nearly stopped in the junction;
- an ambulance leaving its station on a junction node could appear on top of a car: it now waits until the spot is clear.
In `busy`, 100 pedestrians keep the T-junction at node 5 busy and single cars wait up to 101 to 182 s (145 s on one seed before, while driving through each other).

## 12. Pedestrians spawn spread out along the sidewalks (2026-11-03)

Pedestrians spawned on a random sidewalk node. The two-block map has 40 of them, so 100 pedestrians started on 38 points (up to 6 on one), and in the first second separation pushed some onto the road (rule R1) or past the building line (R1b): the `busy` rule test was an expected failure for this.
Now each one spawns at a random point along a sidewalk piece, at least 1 m from everyone already there (best of 50 tries when the map is crowded). A pedestrian spawned mid-sidewalk starts their first trip at whichever end of the piece makes the whole trip shorter (`sim._trip_start_node`); starting at the nearer end made some walk to it and turn straight back, which showed up as spinning.
Two knock-on fixes:
- pedestrians now keep off a crosswalk once a car holding the junction can no longer stop at its line (before: once it was past it), so a pedestrian stepping out in that half second no longer leaves a car stopped in the junction at a red light;
- the staged careless driver of `ped-hit` does not wait for the junction (`Car.respects_junctions = False`): background traffic changed with the spawn points and a car holding the junction could delay it by a second, after which it missed the pedestrian.

Rules R1, R1b, R3 and R5 to R6 are now 0 over the three rule-check configs and `busy`, seeds 7 / 11 / 23; `test_busy_scenario_keeps_the_rules` is no longer an expected failure. Staged scenarios: `ped-hit` hits on 10 of 10 background seeds, `car-crash` on 9 of 10.

## 13. Accidents happen on their own and wait for a call (2026-11-03)

Accidents only happened in the two staged scenarios, and an ambulance came by itself and cleared them within seconds. Now:
- **Random accidents:** `normal` and `busy` have reckless drivers and distracted pedestrians (see `engines.md`), so crashes and pedestrian hits are probable in any run: about 40% of `normal` runs and 50% of `busy` runs of 180 s have one (kinds in the sweep: red-light crashes and pedestrian hits). The shares were tuned by a sweep over seeds.
- **No automatic ambulance:** an accident stays open and its wrecks keep blocking their lanes until `clear_accident` or `dispatch_ambulance` is called; the viewer shows a red notice the moment it happens. A recording cannot answer the call, so wrecks in a recording stay to its end and traffic backs up behind them.
- The staged scenarios keep staging exactly one accident, which now stays open.
- Rule checks and the movement tools use clean traffic (`accident_prone=False`); the rule tests are unchanged.

## 14. Emergency vehicles start parked at their stations (2026-11-04)

Ambulances waited out of sight on a junction node, one per randomly generated hospital (5 on the two-block map). A call made one appear on the junction (pop-in), and when it started back after cleaning it was put at its route's end node (teleport). On scene it was taken out of the lane groups, so traffic could drive through it.
Now:
- The map names its stations (`two_blocks/map.py`): a hospital, a fire station and a police station, one vehicle each (`amb1`, `fire1`, `police1`), parked in a bay in front of the station from t = 0 and recorded in every frame (status = kind, 9th field = call status). Their bays are reserved: no civilian car parks there.
- A call pulls the unit out of its bay at the next gap, as a car does; it is on scene once stopped within 25 m of the wreck, stays in its lane there as an obstacle, then drives on from where it stands and parks back in its bay. No pop-in or teleport: `tests/test_stations.py` runs `tools/continuity.py` on the ambulance's whole call.
- The viewer draws the station buildings, their bays, and the police car and the new fire truck model; civilian cars no longer use the police model.
Knock-on effects of the 3 bays (every seed's background traffic is reshuffled, because cars spawn by `random.choice` over the free bays):
- `busy` has 47 cars instead of 50, so 6 bays stay free as before;
- `car-crash` default seed 2 -> 4 (with 2 a background car is now trapped behind the wreck, R3 and R5); T-bone on 6 of seeds 1-10 (7 on main before);
- the busy accident test uses seeds 3 (has one) and 2 (none) instead of 2 and 1;
- liveness, one seed each: car trips 22 -> 21 (spike), 47 -> 38 (dense), 36 -> 31 (dense + distracted); crossings and pedestrian trips about the same.

## Known gaps

See "Open Items" in `../CLAUDE.md`.

## Pedestrian signals (2026-11-08)

Crossing the road takes about 11 s and a car's red lasted 13 s, so people stepping off late were still on the road when cars got green, and turning cars always had to wait for them.
A pedestrian phase with every car light red fixed that. Measured over 6 seeds, 300 s, no reckless road users:

| | Before | After |
|---|---|---|
| 20 cars, 40 pedestrians: car trips | 41.5 | 45.7 |
| ... worst car wait, mean of seeds (max) | 87 s (135) | 57 s (76) |
| ... car-seconds standing for a crosswalk | 234 | 0 |
| ... pedestrian crossings | 108 | 104 |
| ... mean pedestrian wait | 10.8 s | 21.8 s |
| 47 cars, 100 pedestrians: car trips | 19.3 | 32.2 |
| ... worst car wait, mean of seeds (max) | 156 s (181) | 67 s (76) |

Greens of 15 and 20 s gave cars a little more (51.7 and 53.8 trips) but cost about 20% of the crossings, so 10 s stayed.
The staged accidents moved from about 31 s to about 49 s, since reds are longer.

## Emergency driving (2026-11-08)

Units followed lights and queued behind cars. Time from dispatch to arrival, mean, on 3 s after the first report, with both units sent:

| | Before | After |
|---|---|---|
| `ped-hit`: ambulance / police | 25 s / 86 s | 24 s / 39 s |
| `car-crash`: ambulance / police | 29 s / 53 s | 34 s / 22 s |
| Full city, 12 seeds, 400 s: ambulances / police arriving | 5 / 2 | 12 / 6 |
| ... mean ambulance time | 56 s | 40 s |

The `car-crash` ambulance got slower by 5 s; the cause was not traced (possibly the slowing for crosswalks with people near them).
Hits by units over 24 stress runs, most with every pedestrian ignoring signals: 0 (4550 unit-seconds). A larger sweep of 120 runs was not repeated on the final code.
Body overlaps with other vehicles remain, 87 ticks over 12 full-city runs, shallow brushes in dense traffic.
