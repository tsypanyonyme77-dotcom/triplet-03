# twin (Onymous)

The simulated city that the City Brain and the Guardian connect to.
Cars, pedestrians, signals and emergency units run in real time on a two-block map.
Sensors report what they see as signed readings, and actuators change the city.

```
twin/
  INTERFACE.md     what the Twin sends and receives (R1)
  src/twin/        the service: main.py (API), emitter, actuators, devices, timeline, scenario_runs, testbook
  src/twin/city/   the seam between the API and the simulation (CitySource)
  src/twin/engine/ the simulation: cars, pedestrians, accidents, witnesses, emergency units
  src/twin/world/  the two-block map, the scenarios, the recorder
  src/viewer/      the 3D viewer and the live timeline (React, three.js)
  mocks/           stand-ins for the Guardian and the City Brain, with consoles (mocks/ui)
  tests/  tools/   tests, and rule checks and measurements for the engine
  docs/            how the engine and viewer work, and notes on the challenge
```

## Run the layer alone (R1)

From `twin/`, with its two mocks:

```
cd twin && docker compose up --build
```

| Open | What |
|---|---|
| http://localhost:8080 | The city in 3D, live, with scenario buttons and city controls |
| http://localhost:8080/timeline | The live timeline across the three layers (R3) |
| http://localhost:8002 | Mock City Brain console: incidents, dispatch, road closures |
| http://localhost:8003 | Mock Guardian console: stream with verdicts, quarantine |
| http://localhost:8001/docs | The Twin's API |

With no partners at all, `docker compose up --build twin viewer` still runs the city: deliveries fail softly, are logged as `delivery_failed`, and the timeline shows the layers as not reachable.

## Run it with the real layers

From the repository root, `docker compose up --build` starts the Twin with the real City Brain and Guardian (the root `docker-compose.yml`).
The same image serves both: only the addresses and keys in the environment differ, and the Twin speaks each partner's own contract through `src/twin/partners/` (see [`INTERFACE.md`](INTERFACE.md)).

## The city

The default scenario, `city`, is random traffic with four settings, as environment variables or from the viewer's controls:

| Setting | Default | Meaning |
|---|---|---|
| `TWIN_CARS` | 20 | 0 to 47 |
| `TWIN_PEDESTRIANS` | 40 | 0 to 100 |
| `TWIN_CAR_CRASH_RISK` | 0.1 | Chance per car of running red lights. Causes car crashes only. |
| `TWIN_PED_HIT_RISK` | 0.1 | Chance per car of not yielding and per pedestrian of ignoring the pedestrian signal. Causes pedestrian hits only. |
| `TWIN_FLOOD_RISK` | 0 | Chance per street that its drain blocks and a downpour floods it, once, 20 to 150 s in. Red-light runners drive into the water and pedestrians who ignore signals walk into it, so they are the ones who get caught. Never changes the traffic of a seed. |
| `TWIN_FIRE_RISK` | 0 | Chance per building of catching fire once, at a random moment in the first 20 to 150 s. A fire spreads to touching buildings until a fire truck puts it out. Never changes the traffic of a seed. |

Measured with 20 cars and 40 pedestrians over 24 seeds, chance of at least one accident in 180 s:

| Risk, the other at 0 | 0.05 | 0.1 | 0.2 | 0.3 | 0.5 |
|---|---|---|---|---|---|
| `TWIN_CAR_CRASH_RISK`: car crash | 0.08 | 0.12 | 0.25 | 0.38 | 0.71 |
| `TWIN_PED_HIT_RISK`: pedestrian hit | 0.00 | 0.08 | 0.50 | 0.62 | 0.83 |

With 24 seeds these are rough: one seed is 0.04.

`ped-hit` and `car-crash` stage exactly one accident, and they are what the Test Book's T1 and T2 run.
`building-fire` stages one fire (building `bld-01-03` at 10 s) and is what T3 runs.
In the viewer, select any building and press `Start a fire here` to set it alight by hand.
Every street has a storm drain: click one (the grate by the kerb, or the street around it) and press `Block and flood` to block it and bring a downpour over that street.

Measured with the default city over 12 seeds, 240 s each:

| `TWIN_FLOOD_RISK` | 0.1 | 0.2 | 0.3 | 0.5 |
|---|---|---|---|---|
| Streets flooded per run | 0.7 | 1.4 | 1.9 | 3.8 |
| Runs where someone is caught in the water | 5 | 7 | 8 | 11 |

`flood` (T4) rains on the city until the dip of street 2-3 floods: one driver stalls in it and one pedestrian is trapped, while the careful ones turn back.

## Tests

```
cd twin
uv sync
uv run pytest                                # the service, mocks and engine
uv run python -m tools.check_rules           # the movement rules, with violation counts
uv run python -m tools.liveness              # proves nothing is frozen
cd src/viewer && npm ci && npm test          # the viewer
cd mocks/ui && npm ci && npm test            # the consoles (from twin/)
```

## Development without Docker

```
cd twin && GUARDIAN_URL=http://127.0.0.1:8003 GUARDIAN_DIALECT=twin BRAIN_URL=http://127.0.0.1:8002 LOG_DIR=../logs uv run uvicorn twin.main:app --port 8001
cd twin/src/viewer && npm run dev            # http://localhost:5173, proxies /twin to port 8001
```

## Recordings

`uv run python -m twin.world.record --scenario ped-hit` writes a recording, and the dev viewer plays it at `?rec=ped-hit`.
Recordings are generated and not committed, and the Docker image has none.

## Known limits

See [`INTERFACE.md`](INTERFACE.md).

## Members

_Listed by the team._
