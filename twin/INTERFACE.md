# Twin Layer Interface Card

Contract version `2026-09-17` (the Guardian team's draft data dictionary). HTTP and JSON. Items marked **proposed** are not in the draft yet and need partner agreement.

## What the Twin sends
**1. Readings to the Guardian** (default every second): `POST {GUARDIAN_INGEST_URL}`, one request per reading. Also on `GET /stream/readings` (server-sent events) and, the newest per sensor, on `GET /sensors`.

HMAC: SHA-256 over canonical JSON of the reading without `provenance` (keys sorted, separators `,` `:`, UTF-8), key = `TWIN_HMAC_KEY`. `sequence_no` is strictly increasing per `sensor_id`. `department` is **proposed**.

Each reading carries the simulated time it describes in `value.sim_time_s`.
- `emergency_call`: one reading per call a witness makes (a pedestrian, a driver stuck nearby, or a driver in the crash), sensor `ecall-<zone>`, `department` from the category. The Twin's call centre merges calls about the same place into one `incident_id` (**proposed** field; within 50 m of the incident's first report and 300 s of its last call). The location is what the caller said, so it can be a few metres off, the category can be wrong, and a false report (no incident) gets its own `incident_id`.
```json
{"contract_version":"2026-09-17","sensor_id":"ecall-zone-03","type":"emergency_call","zone_id":"zone-03","timestamp":"2026-11-04T21:30:07.412Z",
 "sequence_no":1,"department":"medical",
 "value":{"call_id":"call-0001","category":"medical","caller_confidence":0.83,"incident_id":"inc-0001",
          "location":{"x":71.9,"y":-0.6},"reporter_kind":"pedestrian","sim_time_s":35.6},
 "provenance":{"signed_by":"twin","hmac":"<hex sha256>"}}
```
- `traffic_camera`: every emit tick, one per signalised junction (`cam-n2`, `cam-n5`): `{congestion_score, vehicle_count, avg_speed_kmh, smoke_detected, sim_time_s}` (draft dictionary fields).
- `cctv_anomaly`: sensor `<camera>-cctv`, every emit tick while the camera flags something: `{anomaly_id, anomaly_type: collision | stopped_vehicle, confidence, location{x,y}, since_sim_s, sim_time_s}`. A crash is flagged 2 s after it; a vehicle standing still on the road for 30 s (not at a red light) is a `stopped_vehicle`. A second source next to the calls.
- `building_fire`: sensor `fire-<building id>` (e.g. `fire-bld-01-03`), `department: fire`, from the moment the smoke sensor of a burning building trips (3 s after the fire starts) on every emit tick, then once more with `smoke_detected: false` when the fire is out: `{building_id, smoke_detected, temp_c, co2_ppm, incident_id, location{x,y}, sim_time_s}`. Temperature runs from 20 to 400 C and CO2 from 420 to 5000 ppm as the fire grows (**proposed** extension of the draft's building fire/smoke sensor, which has `smoke_detected` and `temp_c`). `incident_id` is the one the dispatch actuator takes. Only buildings with smoke send readings, so a quiet city has none.
- `air_quality`: sensor `aq-<zone>`, every emit tick, one per zone: `{aqi, pm25_ugm3, pm10_ugm3, sim_time_s}` (draft dictionary fields). A fire raises the AQI of its zone (about 140 per fire at full strength over the clean 38) and a quarter of that elsewhere. The Guardian's cross-check "AQI spike without a smoke flag" holds: a burning building also sets `smoke_detected` on the traffic cameras within 60 m and sends `building_fire` readings.
- `rainfall`: one rain gauge per street, at its drain (`rain-dip-<u>-<v>`, e.g. `rain-dip-2-3`), department `water`, every emit tick: `{mm_per_hr, location{x,y}, sim_time_s}` (extended dictionary field). Rain can fall on one street only, so a water level is checked against the gauge of its own street.
- `water_level`: one per street, at its drain (`wl-dip-<u>-<v>`, e.g. `wl-dip-2-3`), department `water`, every emit tick: `{level_m, flow_rate_m3s, pump_id, pump_on, location{x,y}, sim_time_s}`. Calls about a car stalled in the water, or a pedestrian trapped in it, have category `flood`. `level_m` is the depth at the low point of street 2-3, and `flow_rate_m3s` is what drains away (storm drain plus pump). The two feeds agree: the level rises only while it rains, and never by 0.2 m in 5 s (the Guardian's check). **Proposed**: `pump_id`, `pump_on`, `location`.
`location` (metres on the two-block map, x east, y north) answers open item 4 of the dictionary with "zone_id plus approximate coordinates" (**proposed**).


**2. Notification to City Brain** (after each batch, no data): `POST {BRAIN_NOTIFY_URL}`
```json
{"contract_version":"2026-09-17","event":"readings_available","timestamp":"2026-11-08T10:00:03.200Z","readings":3}
```

## What the Twin receives
**Actuator call**: `POST /actuators/call`, header `X-Api-Key: <that layer's key>`.

**Dispatch** (draft dictionary action `dispatch_unit`): `actuator_id: dispatch-centre-01`, params `{unit_type: police | ambulance | fire, incident_id, zone_id?}`; `incident_id` comes from an `emergency_call`, `cctv_anomaly` or `building_fire` reading.
```json
{"contract_version":"2026-09-17","actuator_id":"dispatch-centre-01","action":"dispatch_unit",
 "params":{"unit_type":"ambulance","zone_id":"zone-03","incident_id":"inc-0001"},"requesting_layer":"city_brain",
 "justification":"cctv_anomaly cam-n2-cctv reported inc-0001 (police)","trust_ref":"verdict-00001"}
```
Result: `{"status":"dispatched","unit_id":"amb1","eta_minutes":0.23,"unit_type":"ambulance","incident_id":"inc-0001"}`. `status`: `dispatched | duplicate` (a unit of that type is already on the incident; same `unit_id`) `| rejected` (+ `reason`: `unknown_incident`, `no_unit_available`, `unknown_unit_type`). The unit pulls out of its station bay and drives to the reported location in the engine. A fire truck sent to a burning building stops in front of it and puts the fire out, one building after another (the ones it spread to included), then drives home. Police and ambulances sent to a fire look round and leave. `zone_id` is accepted, not required. Units move only when such a call arrives: the Twin reports incidents and never dispatches by itself. The mock City Brain (`mocks/brain/incident_rule.py`) lists incidents from Guardian-verified readings and waits for an operator (manual mode, the default); its optional auto mode (a flag, for tests and unattended demos) sends an ambulance and a police car 3 s after the first trusted report, or just a fire truck when the incident is a fire. `scenarios/incident_chain.py [--auto]` runs the whole chain in one process.

**Road closure** (draft dictionary action `set_barrier_state`): `actuator_id: road-barriers-01`, params `{state: closed | open}` plus exactly one of `road_id` (`"1-2"`: the street between two road nodes, both directions) or `incident_id` (the street of that incident's wrecks). **Proposed**: a street id instead of the draft's `barrier_id`. Result `{"status":"closed","barrier_ids":["barrier-1-2"],"state":"closed","edges":[[1,2],[2,1]]}`; `status`: `closed | opened | duplicate` (already in that state) `| rejected` (+ `reason`: `unknown_road`, `unknown_incident`, `no_open_accident_at_incident`). Cars that can are re-routed round a closed street, the others stop before it; emergency units ignore it. The police car also closes the street itself when it reaches a scene, and lifts the barrier when it leaves.

**Actuator catalog**: `GET /actuators` lists every action with `actuator_id`, `department`, a description, `params`/`result` in words, `params_schema`/`result_schema` (JSON Schema). The City Brain reads it to build its calls and buttons.

**Drainage pump** (extended dictionary action `set_pump_state`): `actuator_id: drainage-pumps-01`, params `{state: on | off}` plus exactly one of `pump_id` (`"pump-2-3"`) or `incident_id` (the pump of the flood zone the incident is in). **Proposed**: by `incident_id`, and no `flow_target` (a pump runs at its capacity). Result `{"status":"on","pump_id":"pump-2-3","state":"on","capacity_m3s":1.2}`; `status`: `on | off | duplicate` (already in that state) `| rejected` (+ `reason`: `unknown_pump`, `unknown_incident`, `no_pump_at_incident`). The pump adds its capacity to the storm drain from the next tick, which the next `water_level` reading shows.

**Idempotency key** (**proposed** optional envelope field `idempotency_key`, max 128 chars): a call retried with the same key gets the first answer back with `"replayed": true` and nothing runs twice; the same key with a different action or params is `409`. Independently, `dispatch_unit` is idempotent per incident and unit type and `set_barrier_state` per street and state (`duplicate`).


**Device containment** (draft dictionary actions; Guardian only): `actuator_id: device-control-01`. `quarantine_device` and `isolate_sensor` take `{device_id, reason}` and `clear_quarantine` takes `{device_id}`. `device_id` is a `sensor_id` from `GET /sensors`, and a device covers the sensors named after it (`cam-n2` covers `cam-n2-cctv`). The Twin keeps simulating the device but stops sending its readings, until it is cleared or a new run starts. `trust_ref` may be `null`. Result: `{"status":"quarantined","device_id":"cam-n2","quarantined_until":null}`; `status` is `quarantined | isolated | cleared | duplicate | rejected` (+ `reason: unknown_device`). `GET /quarantine` lists what is cut off.

**Fire simulator** (the committee's side of the external surface; operator key): `POST /simulators/ignite_fire` with `{"building_id": "bld-01-03"}` sets a building on fire. Result `{"status":"ignited","fire_id":"fire-0001","building_id":"bld-01-03","run_id":3}`; `status` is `ignited | duplicate` (already burning, same `fire_id`); an unknown building is `404`, a missing `building_id` `422`, a missing operator key `401`. Building ids are in the map the viewer loads (`GET /live/map`, `map.buildings`). The other layers are not told: they learn of the fire from the readings above, which is the point. The fire spreads to touching buildings after 40 s if nobody answers.

**Flood simulator** (operator key): `POST /simulators/flood_street` with `{"zone_id": "dip-1-4"}` blocks the storm drain of that street (one per street, `dip-<u>-<v>`) and brings a 120 mm/h downpour over it for about two minutes. Answer: `{"status": "started" | "duplicate", "zone_id", "street": "1-4", "pump_id": "pump-1-4", "rain_until_s"}`; an unknown zone is `404`. A blocked drain takes no water until the street is dry again, so only its pump (`set_pump_state`) drains it. The other layers learn of it from that street's rain gauge and water level, and from callers. `GET /flood` lists every street's water, rain, drain and pump. `flood_risk` (`TWIN_FLOOD_RISK`, the viewer's sandbox) does the same at random: per street, once, 20 to 150 s in.

## Errors (clear messages in `detail`)
`401` bad or missing key | `400` unsupported `contract_version`, unknown `action`, wrong `actuator_id` for the action | `403` `city_brain` call without `trust_ref` (act only on a Guardian-verified reading), or a Guardian-only action from another layer | `409` `idempotency_key` reused for a different call, or a scenario already running | `422` malformed envelope or params.

## Read endpoints
`GET /health` | `GET /zones` (`zone-01` block A, `zone-02` block B, `zone-03` streets and stations; adjacency, `facilities` by department code, bounds) | `GET /sensors` | `GET /stream/readings` | `GET /actuators` | `GET /units` | `GET /responses` (per incident: phase, units, road closed; the phase of a fire goes `dispatched`, `on_scene`, `firefighting`, `cleared`, `closed`) | `GET /quarantine` | `GET /events` (this layer's events, without the engine's ground truth).

## What the Twin asks of a partner
Only `POST /ingest` (Guardian) and `POST /notify` (City Brain) are needed, and both paths can be overridden. To appear on the timeline and in scenario logs, a layer also serves `GET /events?limit=N`:
```json
{"events":[{"ts":"2026-11-08T10:00:05.100Z","kind":"verdict_issued","message":"verdict-00012 trusted for emergency_call ecall-zone-03"}]}
```
`ts` is ISO-8601 UTC, so that events from all layers sort together. A layer without it still works, and shows as not reachable. A scenario's expected events (`src/twin/testbook.py`) use the mocks' `kind` names, so a real layer that names them differently shows as `MISSING` in the log until they are aligned.

## Operator endpoints (the demo's controls, not for partners)
Header `X-Operator-Key: <TWIN_OPERATOR_KEY>`. `POST /scenarios/{id}/run` with optional `{"seed", "speed", "brain": "auto" | "operator"}` | `GET /scenarios` | `GET /scenarios/runs` (finished runs, newest first; the last 20 are kept) | `GET /scenarios/runs/{n}` (one run with every event of the three layers: its timeline) | `GET /timeline` (all layers, with ground truth; `routine=true` adds the periodic readings and notifications, flagged `routine`) | `POST /live/control` (`pause`, `resume`, `speed`, `reset`, `load`, optional `params`). The viewer's frame stream is `GET /live/map`, `GET /live/status`, `GET /stream/frames`.

## Pointing it at a different partner (configuration only)
`GUARDIAN_URL` and `BRAIN_URL` are the partners' base addresses. `GUARDIAN_INGEST_URL` and `BRAIN_NOTIFY_URL` override where readings and notifications go. An empty address disables that link. Set them in `.env`, and see `.env.example` for every setting.

## Authentication
Inbound actuator calls: one API key per layer (`TWIN_BRAIN_API_KEY`, `TWIN_GUARDIAN_API_KEY`), so `requesting_layer` is checked and not just claimed. Outbound readings: HMAC provenance with `TWIN_HMAC_KEY`, which the Guardian needs too. All are shared secrets from the environment, not code. No TLS or mutual TLS yet.

## Known limits
Only emergency call, traffic camera and CCTV anomaly sensors, and only dispatch, barrier and device actuators; the rest of the draft dictionary is not implemented. The city is two blocks. The Twin cannot yet emit falsified readings, which Guardian scenarios will need. Read endpoints have no authentication. The operator key protects the Twin's API, but anyone who can open the viewer can use its controls, since nginx adds the key. No key rotation.
