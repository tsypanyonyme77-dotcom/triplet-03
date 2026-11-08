> Archived 2026-11-08: Cities: Skylines II was dropped as an engine option and the adapter stub removed. `twin/` runs its own engine.

# Experiment: Cities: Skylines II as the Twin engine

Sources: `reference/Cities_Skylines_II_Twin_Layer_Report0.2.pdf` (24-page technical study, rev 5 Oct 2026) and `reference/City_Brain_Feature_Exploration_Summary.pdf` (6-page summary with all 36 scenario ideas). Both were written from the City Brain side but describe the game as the twin environment, so they apply to us.

**Status: desk research. The game/mod combination was never run.** Everything below is unverified until we test it. An experiment, not real work, until the user says otherwise (goes in `.temp/` once the version-control setup is accepted).

## Idea
CS2 supplies the world (roads, vehicles, citizens, fire/health services). Our code supplies scenario timing, sensors/actuators facade, APIs, logs. A C# bridge mod inside the game exposes state; the external app (ours) holds scenario logic and decisions. Loop: observe, decide, act, compare.

## Tooling
- **CS2MCP** `LancerComet/cities-skylines-2-mcp`, reviewed commit `f0894c1831153742d2a586b830418177839a2428`. In-game C# bridge, HTTP on `127.0.0.1:8642`. Optional Node (18+) MCP server on top; not needed for plain HTTP. Documented for Windows + Steam. Build: .NET SDK 8+, targets net472, needs the game's assemblies (`-p:GamePath=...`).
- Verified routes (in source): `/ping`, `/state` (cityLoaded, isLoading, simulation.frameIndex), `/city/overview`, `/city/services`, `/city/buildings?limit=`, `/city/traffic?limit=`, `/city/notifications?limit=`, `/city/road-graph?x=&z=&radius=`, `/city/terrain?resolution=`, `/sim/control?paused=`, `/sim/run?hours=&speed=` (`cancel=true` to stop), `/game/save?name=` (async), `/build/junction?index=&version=&mode=` (modes `lights`, `nolights`, `stop`, `default`).
- Optional mods: Realistic Trips (schedules), Traffic and Traffic Lights Enhancement (road control, no exact green-time), Water Features (flood sources), RWH (capacity), Carto (GIS export), Skyve (playsets). Version compatibility with our installed game is unchecked.
- Specialist models if the game is too coarse: SUMO/TraCI (traffic), SWMM (runoff/drainage).

## Known gaps
- No documented fire-start, disaster-spawn, citizen control, or deterministic replay.
- Writes are GET with query strings: keep local, wrap with explicit POST endpoints.
- `/city/traffic` is game flow diagnostics, not vehicles per hour.
- Saving and timed runs are asynchronous: poll for completion; the hours-to-frames conversion (262144/24) is an assumption to calibrate.

## Reliability rules for the bridge/adapter
Entity index **and** version; world/session token and reload detection; bounded command queues; command IDs with dedup; read back state after every write; never blindly retry a timed-out write; one controller per mechanism (signals, schedules); throttle polling and cap result sizes; snapshot operation for consistent multi-read.

## Recommended first scope
One neighborhood, one junction, live dashboard, one verified control change, comparison report. Baseline A vs intervention B from the same save and demand settings, 3 to 5 pairs, show individual runs. Record: baseline save hash, game build, mod versions, bridge commit, scenario settings, run id, frame indices, requested vs confirmed actions, missing samples. Keep synthetic sensor noise separate from true game state.

## Scenario catalog (36 ideas; N native, M mod, C custom, X external)
- Movement (01 to 12): morning commute, staggered shifts, school surge, remote work, event departure wave, **06 junction redesign (best first choice)**, roadworks/closure, **08 traffic collision**, transit cut, freight bottleneck, parking pressure, emergency corridor.
- Hazards (13 to 24): **13 building fire**, forest-edge fire, hail, tornado evacuation, **17 river overflow**, coastal surge proxy, dam-release proxy, urban flash flood (needs SWMM), drought, heatwave, snow, earthquake/landslide. Flood needs an explicit passability rule and verification that traversal actually stops.
- Services (25 to 36): **25 local blackout**, transformer bottleneck, **27 water outage**, sewage overload, pollution exposure, hospital surge, garbage backlog, supply interruption, crime hotspot, disease outbreak, evacuation inequity, **36 sensor/network outage** (drop, delay or corrupt synthetic observations while keeping true game state: the Twin-side hook for spoofing scenarios).
Useful chained scenario: flooded road, delayed ambulance, reduced hospital access, alternative route. Each link needs an explicit model and a measurable outcome.

## Mapping to the challenge (open)
| Challenge need | CS2 can provide | Gap |
|---|---|---|
| Traffic camera | `/city/traffic`, road graph | counts must be derived; flow is not vehicles/hour |
| Water-level | terrain/water grid, Water Features mod | needs adapter; no live per-sensor value |
| Power-load | `/city/overview`/services may expose supply | unverified |
| Air-quality | game pollution state | unverified route; likely synthetic |
| Emergency calls | `/city/notifications` (icons only) | not a full incident lifecycle; custom tracking |
| Dispatch | native services | no verified incident-to-vehicle link |
| Signals | `/build/junction` modes | no phase/duration control (`set_signal_phase` needs a shim) |
| Valve / grid switching / quarantine | none documented | synthetic layer on top |

## Practical concerns to settle
CS2 is Windows-centric; this dev machine is Linux. The demo must run on stage with a local fallback and nothing installed on site. The existing POC (`poc.md`) is the fallback candidate if CS2 does not pan out.

## Citizen data in the CS2MCP bridge (checked in source, 2026-10-14)
Read from the pinned commit `f0894c1` (still the repo HEAD on 2026-10-14), files `CS2MCP.Bridge/RequestHandlers*.cs`. README documents MCP tool names only, no JSON samples.

**There is no per-citizen route.** Citizens exist only as aggregates:
- `/city/overview`: `cityName, population, populationWithMoveIn, averageHappiness, averageHealth, money, xp, gameYear, gameDateTime, simulationPaused, simulationSpeed`.
- `/city/labor`: `employed, unemploymentRate, homelessCitizens, homelessnessRate, jobs{total, free, totalByEducation{uneducated, poorlyEducated, educated, wellEducated, highlyEducated}, freeByEducation{...}}, ageStructure{children, teens, adults, seniors, totalCitizens}`.
- `/city/statistics?type=<StatisticType>` time series (e.g. Population, Unemployed, CrimeRate).
- `/entity/inspect?index=&version=` on a building: `entity{index,version}, prefab, position{x,y,z}, flags[], renterCount, renters[{prefab, citizens (count), employees (count)}] (max 20), employees`.
- `/city/vehicles`: aggregate census only (`drivingVehicles, stoppedVehicles, byType, inArea, queueHeads, deadlocks`), no per-vehicle records.

**Per-entity record conventions used by the bridge** (buildings, objects): camelCase; `entity: {index, version}`; `prefab` (name string); `position: {x, y, z}` (game world metres); list responses wrapped as `{totalMatches, returned, note, <items>[]}`; errors `400/404/409`.
Example `/city/buildings`: `{"totalMatches":N,"returned":M,"note":"...","buildings":[{"entity":{"index":123,"version":4},"prefab":"...","isSubBuilding":false,"position":{"x":0.0,"y":0.0,"z":0.0}}]}`.

**Consequence:** a per-citizen JSON from CS2 needs a new bridge route (ECS query over citizen entities). Its field list is ours to define; it is not documented anywhere. The Twin's citizen records should follow the bridge conventions above once that route exists.
