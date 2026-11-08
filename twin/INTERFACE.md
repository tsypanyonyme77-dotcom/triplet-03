# Interface Card: twin

The Twin simulates a two-block city and is the only layer that touches it: sensors report as signed readings, actuators change it.
It speaks each partner's own contract through adapters in `src/twin/partners/`, so neither partner has to change for it.
HTTP and JSON, plus MCP for the City Brain.
Port `8001`.

## Readings (what the Twin sends)

One canonical reading per sensor per tick (every `TWIN_EMIT_INTERVAL_S`, default 1 s), shown to each partner in its dialect.
The sensor id and `sequence_no` are the same in both dialects, because the City Brain asks the Guardian for its verdict by that pair.
`sequence_no` rises strictly per sensor.

**To the City Brain** (contract `2026-09-17`, the shared data dictionary): it pulls them, by MCP tool `list_readings(cursor, limit)` at `/mcp` or `GET /readings?cursor=&limit=`, and gets `{readings, next_cursor, stream_id}`.
The cursor is the absolute position in this Twin's stream; `stream_id` changes when the Twin restarts.
HMAC-SHA256 over the reading without `provenance`, keys sorted, no whitespace, UTF-8, with `TWIN_HMAC_SECRET`.

```json
{"contract_version":"2026-09-17","sensor_id":"ecall-zone-03","type":"emergency_call","zone_id":"zone-03","timestamp":"2026-11-08T10:00:07.412Z",
 "sequence_no":1,"department":"medical",
 "value":{"call_id":"call-0001","category":"medical","caller_id":"ped0","caller_confidence":0.83,"incident_id":"inc-0001",
          "location":{"x":71.9,"y":-0.6},"reporter_kind":"pedestrian","sim_time_s":35.6,"run_id":1},
 "provenance":{"signed_by":"twin","hmac":"<hex>"}}
```

**To the Guardian** (its contract `1.0`): pushed, one batch per tick, `POST {GUARDIAN_URL}/v1/readings` with `X-API-Key: <TWIN_API_KEY>`.
Its envelope holds exactly its fields, and `value` exactly what its sensor registry lists for the type; types it does not know are not sent.
HMAC over the envelope without `hmac`, same rule and key. `sequence_reset: true` on the first reading of each sensor after a restart.

```json
{"contract_version":"1.0","sensor_id":"wl-dip-2-3","sensor_type":"water_level","zone_id":"zone-03","timestamp":"2026-11-08T10:00:07.412Z",
 "sequence_no":42,"value":{"level_m":0.31},"sequence_reset":false,"hmac":"<hex>"}
```

| Sensor (`type`) | Id | `value` (City Brain dialect) | Guardian dialect |
|---|---|---|---|
| `emergency_call` | `ecall-<zone>` | `call_id, category, caller_id, caller_confidence, incident_id, location, reporter_kind` | `emergency_call {call_id, incident_type, caller_id}`; `police` is `crime`, `other` is not sent |
| `traffic_camera` | `cam-n2`, `cam-n5` | `congestion_score, vehicle_count, avg_speed_kmh, smoke_detected` | `traffic_camera` without `smoke_detected` |
| `cctv_anomaly` | `<camera>-cctv` | `anomaly_type (collision, stopped_vehicle), confidence, anomaly_id, incident_id, location` | not in its registry |
| `building_fire` | `fire-<building>` | `smoke_detected, temp_c, co2_ppm, building_id, incident_id, location`, while a building smokes | not in its registry |
| `air_quality` | `aq-<zone>` | `aqi, pm25_ugm3, pm10_ugm3, smoke_detected` | `air_quality {aqi, smoke}` |
| `rainfall` | `rain-dip-<u>-<v>` | `mm_per_hr, location` | `rain_gauge {rainfall_mm_h}` |
| `water_level` | `wl-dip-<u>-<v>` | `level_m, flow_rate_m3s, pump_id, pump_on, location` | `water_level {level_m}` and `flow_meter {flow_rate_m3s}` as `flow-dip-<u>-<v>` |
| `unit_status` | `unit-<unit>` | `unit_id, incident_id, state (en_route, on_scene, returning), unit_type, station_id`, on each change | not in its registry |

Every value also has `sim_time_s`. `location` is metres on the map (x east, y north). `incident_id` in a call or alarm is the Twin's call-centre incident.

## Layout

`get_topology()` (MCP) or `GET /topology`: zones (`zone-01` block A, `zone-02` block B, `zone-03` streets) with `adjacency` and `exits`, `facilities` and `sensors`.
Each station is a facility a dispatch is addressed to: `dispatch-hospital` (ambulance), `dispatch-police-station`, `dispatch-fire-station`, one unit each; the drainage pumps are facilities of `drainage-pumps-01`.

## Actuator calls (what the Twin receives)

**From the City Brain**: MCP tool `<action>(call=<envelope>)` at `/mcp`, or `POST /actuators/{action}` with the envelope; `GET /capabilities` and the tool list say what it may call: `dispatch_unit`, `broadcast_alert`, `set_pump_state`, `set_barrier_state`.
Authenticated by `provenance.hmac` with `BRAIN_HMAC_SECRET` (its form, whole-number floats as integers, and the older one), or `X-Api-Key`.
A call stamped more than 30 s from now is refused; its `nonce` is the idempotency key, so a resent call runs once and gets the first answer.

```json
{"contract_version":"2026-09-17","actuator_id":"dispatch-hospital","action":"dispatch_unit",
 "params":{"unit_type":"ambulance","zone_id":"zone-03","incident_id":"inc-0042"},"requesting_layer":"city_brain",
 "justification":"accident on the south street","trust_ref":"verdict-000004","issued_at":"2026-11-08T10:01:00Z","nonce":"a1b2",
 "provenance":{"signed_by":"city_brain","hmac":"<hex>"}}
```
Answer, flat: `{"status":"dispatched","unit_id":"amb1","eta_minutes":0.23,"incident_id":"inc-0042","twin_incident_id":"inc-0001"}`.
The City Brain numbers its own incidents; its id is linked to the Twin's open incident in the zone it names (then by kind, then the oldest), and the unit's `unit_status` readings carry its id.
`status`: `dispatched | duplicate` (same `unit_id`) `| rejected` with `reason` (`unknown_incident`, `no_unit_available`, `wrong_station_for_unit_type`, `station_quarantined`).
`broadcast_alert` is addressed `broadcast-alert-<zone>`: `{zone_id, channel: sms | siren | app, message}` answers `broadcast`.

**From the Guardian**: `POST /tools/{action}` with its call `{call_id, actuator_id, action, params, zone_id, requesting_layer, trust_ref, justification, incident_id}`.
The City Brain's calls it audited and forwards (`requesting_layer: "brain"`; a dispatch names the station in `params.station_id`), and its own containment: `quarantine_device`, `isolate_sensor`, `clear_quarantine` with `params.device_id` (a sensor, a `flow-` meter meaning its water level, or a station: a quarantined station sends no unit).
Answer, always HTTP 200: `{"status":"ok","current_state":{...the actuator's result},"reverts_at":null,"unit_id":"amb1","eta_s":13.8}` or `{"status":"rejected","reason":"..."}`.
`set_valve_state`, `set_grid_state` and `set_signal` are `rejected` with `not_supported`: this city has no valves, grid switches or controllable signals yet.

**Errors** (City Brain and our own door, with a clear `detail`): `401` bad signature, key or stale call | `400` wrong `actuator_id` or `contract_version` | `403` `city_brain` call without `trust_ref`, or containment from another layer | `404` an action not offered | `409` an idempotency key reused for a different call | `422` malformed call.

## Pointing it at a different partner (configuration only)

`GUARDIAN_URL` and `BRAIN_URL` are the partners' base addresses; `GUARDIAN_DIALECT` is `guardian-v1` (the real Guardian, default) or `twin` (our mock).
`GUARDIAN_INGEST_URL` overrides where readings go; `BRAIN_NOTIFY_URL` pings our mock City Brain after each batch (the real one polls).
`TWIN_MCP_ALLOWED_HOSTS` lists the Host headers `/mcp` accepts (default `127.0.0.1:*`, `localhost:*`, `twin:*`, `twin`).
All in the environment: `twin/.env.example` alone with mocks, the root `.env.example` in the triplet.

## Authentication

Outbound: readings signed with `TWIN_HMAC_SECRET` (or `TWIN_HMAC_KEY`); `X-API-Key: TWIN_API_KEY` on the Guardian.
Inbound: City Brain calls by its HMAC (`BRAIN_HMAC_SECRET`) or `X-Api-Key`; the Guardian's `/tools` by `X-API-Key: TWIN_TOOLS_API_KEY` when set (the Guardian sends none today); our own `POST /actuators/call` by one key per layer (`TWIN_BRAIN_API_KEY`, `TWIN_GUARDIAN_API_KEY`).
Shared secrets from the environment, never code. No TLS yet.

## Also served

Our own door `POST /actuators/call` (every action, including the Guardian-only ones, catalog at `GET /actuators` with JSON Schemas) and the operator's demo controls (`X-Operator-Key`): scenarios (`POST /scenarios/{id}/run`), the fire and flood simulators (`POST /simulators/ignite_fire`, `/simulators/flood_street`), the live viewer and timeline.
Read endpoints: `GET /health`, `/zones`, `/sensors`, `/units`, `/responses`, `/quarantine`, `/flood`, `/events` (no ground truth).

## Known limits

The city is two blocks with one unit per station; no valves, grid switches, power meters or recall of a unit yet.
The Twin cannot yet emit falsified readings, replays, silence or call floods, which the Guardian's scenarios need.
Some honest readings jump faster than the Guardian's rate-of-change limits (a downpour, smoke from a fire, camera congestion) and clean air never wobbles, so they can be judged suspect or untrusted.
Read endpoints have no authentication.
