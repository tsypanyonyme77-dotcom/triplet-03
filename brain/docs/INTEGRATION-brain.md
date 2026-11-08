# Integration guide: the City Brain in full

The long form of the one-page Interface Card (`../INTERFACE.md`): every message, every behaviour the Brain relies on, the failure modes, configuration for a changed Twin, retractions and learning.


Contract version `2026-09-17`. JSON Schemas for every message below are in `contracts/schemas/` (also served at `GET /schemas`), real examples in `contracts/examples/`. Items beyond the shared Data Dictionary are extensions agreed with the triplet.

## What the Brain receives

| From | Message | Transport (default) | Schema |
|---|---|---|---|
| Twin | Sensor reading envelope | MCP tool `list_readings(cursor, limit)` → `{readings, next_cursor, stream_id}`, polled every 200 ms | `SensorReading` |
| Twin | City layout | MCP tool `get_topology()` → `{zones, adjacency, exits, facilities, sensors}` | — |
| Twin | Actuator result | return value of the actuator tool | `ActuatorResult` |
| Guardian | Trust verdict for one reading | `POST /verdicts {"reading": <envelope>}` | `TrustVerdict` |
| Guardian | Is a device quarantined? | `GET /quarantine/{device_id}` → `{"device_id", "quarantined": bool}` | — |
| Twin, Guardian | Their own timeline events (optional) | `POST /api/events` on the Brain, CloudEvents 1.0 JSON | `TimelineEvent` |
| Guardian | Taking back a verdict on a reading | `POST /api/retractions {"reading_id": "<sensor_id>#<sequence_no>", "reason": "..."}` on the Brain → 202, or 404 if the Brain never saw it | — |

Reading types the Brain acts on today: `cctv_anomaly`, `gunshot`, `emergency_call`, `citizen_activity`, `unit_status`. The four sensors below are parsed, checked for range and shown on the timeline; the Brain opens jam, flood and fire incidents from the first three, an overload when `power_load` reaches 95 percent of its capacity, and smog when `air_quality` reaches an AQI of 150. A reading far outside what its own sensor usually reports is *doubted*: the Brain opens the incident but sends nothing until a second source or the sensor's next reading agrees (`brain.percept.surprise`, and a held action with the check name `surprise`). Any other type is accepted, stored and ignored.

| `type` | `value` fields (Data Dictionary section 2) | Rejected with `value_invalid` when |
|---|---|---|
| `traffic_camera` | `congestion_score` 0..1, `vehicle_count` ≥ 0, `avg_speed_kmh` ≥ 0, `smoke_detected` (default false) | a field is missing or out of range |
| `water_level` | `level_m` ≥ 0, `flow_rate_m3s` (optional) | `level_m` is negative |
| `power_load` | `load_kw` ≥ 0, `capacity_kw` > 0, `voltage_v` ≥ 0 | `capacity_kw` is zero or less |
| `air_quality` | `aqi` 0..500, `pm25_ugm3` ≥ 0, `pm10_ugm3` ≥ 0 | `aqi` is above 500 |

Fields outside these lists are dropped by perception and named in `dropped_fields` on the timeline.

```json
{"contract_version": "2026-09-17", "sensor_id": "cit-feed-07", "type": "citizen_activity",
 "zone_id": "zone-07", "timestamp": "2026-10-12T19:41:57.554Z", "sequence_no": 4,
 "value": {"citizen_id": "cit-88213", "activity": "running", "speed_kmh": 17.5, "heading_zone_id": "zone-08"},
 "department_code": "POLICE",
 "provenance": {"signed_by": "twin", "hmac": "51dd0585…"}}
```

```json
{"verdict_id": "verdict-000001", "reading_ref": {"sensor_id": "cam-07-02", "sequence_no": 1},
 "status": "trusted", "confidence": 0.97, "reasons": ["rate_ok", "hmac_ok"],
 "issued_at": "2026-10-12T19:41:56.056Z", "expires_at": "2026-10-12T19:43:56.056Z"}
```

`status` is `trusted`, `suspicious` or `untrusted`. With `guardian.mode: inline` the Brain instead reads the same object from a `trust` field on the reading.

`unit_status.state` is `en_route`, `pursuing`, `in_position`, `on_scene`, `apprehended`, `lost` or `returning`. A trusted `apprehended` or `lost` closes the incident. `on_scene` answers a `respond` dispatch and `returning` answers a recall. A trusted `returning` from a unit the Brain still counts as out also means the unit has finished: the Brain releases it, and closes a fire or accident incident (which have no other way to end) when its last unit is back, with the outcome `returned`. Agreed with the Twin team: a fire or ambulance unit reports `returning` when its task is done.

`stream_id` is any string that changes when the Twin starts its reading stream again from zero. After a restart the Brain resumes from its saved cursor only if the `stream_id` is the one it saved; without the field it trusts the cursor.

## What the Brain sends

| To | Message | Transport (default) | Schema |
|---|---|---|---|
| Twin | Actuator call envelope | MCP tool named after the action: `dispatch_unit(call=<envelope>)`, `broadcast_alert(call=<envelope>)`, `recall_unit(call=<envelope>)`, `set_signal_phase(call=<envelope>)`, `set_valve_state(call=<envelope>)`, `set_grid_connection(call=<envelope>)` | `ActuatorCall`, `DispatchUnitParams`, `BroadcastAlertParams`, `RecallUnitParams`, `SetSignalPhaseParams`, `SetValveStateParams`, `SetGridConnectionParams` |
| Anyone | Timeline events (CloudEvents 1.0 JSON) | `GET /events` (Server-Sent Events, replays then follows) and `logs/<scenario>-<time>.jsonl` | `TimelineEvent` |
| Anyone | Why a decision was made | `GET /api/decisions/{id}`, `GET /api/incidents/{id}/graph` | — |

```json
{"contract_version": "2026-09-17", "actuator_id": "police-dispatch-05", "action": "dispatch_unit",
 "params": {"unit_type": "police", "zone_id": "zone-07", "incident_id": "inc-0001",
            "mode": "pursuit", "target_id": "cit-88213"},
 "requesting_layer": "city_brain",
 "justification": "Suspect cit-88213 score 0.82: copresence (cit-feed-07#4); flight (cit-feed-07#4). Rule POL-001.",
 "trust_ref": "verdict-000004",
 "provenance": {"signed_by": "city_brain", "hmac": "846249a6…"}}
```

`mode` (`respond`, `pursuit`, `contain`, `patrol`), `target_id` and `provenance` on the call are extensions agreed with the triplet. The Brain never sends a call with a null `trust_ref`, and only calls actuators the Twin lists as tools at startup.

The three infrastructure actions are Data Dictionary section 4. Agreed with the triplet: the Brain sends them with `trust_ref` and a `provenance` signature, like every other call, and that the Twin answers `{"status": "set", ...}`:

| Action | `params` | Answer when accepted |
|---|---|---|
| `set_signal_phase` | `intersection_id`, `phase` (`green`, `red`, `yellow`, `flashing`), `duration_s` 1..3600 | `{"status": "set", "current_phase", "reverts_at"}` |
| `set_valve_state` | `valve_id`, `state` (`open`, `closed`), `flow_target_pct` 0..100 (optional) | `{"status": "set", "current_state"}` |
| `set_grid_connection` | `zone_id`, `state` (`connected`, `disconnected`) | `{"status": "set", "affected_load_kw"}` |

The gate treats valve and grid calls as high impact: they need a human approval before the Brain sends them. With `approval.mode: human` a held call waits as a pending approval (`brain.approval.requested`); a person answers `POST /api/approvals/{pending_id}` (`grant` or `deny`) and a grant is an `Approval`: signed, bound to the call's action, actuator, parameters and incident, valid for `approval.ttl_s`, used once.

What each dispatch mode means to the Brain:

| `mode` | Sent when | `target_id` |
|---|---|---|
| `pursuit` | one person stands out as the suspect | that person |
| `respond` | a crime is corroborated but several people left the scene fast, so no one is named | absent |
| `contain` | the department team places a perimeter or intercept unit in `zone_id` | the suspect the perimeter is for |

`recall_unit` stands a dispatched unit down: `params` are `{"unit_id", "incident_id"}`, the result is `{"status": "recalled", "unit_id"}`. The Brain sends it for every unit still out when an incident closes, and for a perimeter the suspect has been seen outside. A Twin that does not offer the tool is never called; the Brain then only updates its own count of free units.

Two behaviours the Brain relies on from the Twin's actuators:

- **A repeated dispatch is answered, not repeated.** The same `incident_id`, `unit_type`, `mode` and target (or zone) again returns `{"status": "duplicate", "unit_id": <the unit already sent>}`. This is how a Brain that restarted half-way through a reading learns which unit it had sent, without a second one going out.
- **A recalled unit frees its place.** After `recall_unit`, a new dispatch to the same zone is a new unit.

Event types: `brain.reading.received` / `.rejected`, `brain.verdict.received`, `brain.incident.opened` / `.closed`, `brain.suspect.assessed` / `.tracked`, `brain.decision.made`, `brain.action.requested` / `.result` / `.blocked`, `brain.deliberation.started` / `.finished`, `brain.case.reviewed`, `brain.options.prepared`, `brain.plan.verified` / `.rejected` / `.outdated`, `brain.agent.fallback`, `brain.unit.status`, `brain.units.released`, `brain.guardian.unavailable` / `.recovered`, `brain.state.restored` / `.discarded`, `brain.pack.bid` / `.uncovered` / `.rejected`, `brain.plan.compiled` (a learned plan used instead of a team run), `brain.evidence.retracted`, `brain.sleep.started` / `.rule.proposed` / `.rule.promoted` / `.rule.rejected` / `.finished` (when sleep is started from the screen), `brain.percept.surprise`, `brain.workspace.ignited` / `.released` / `.deferred` (which incidents hold the Brain's two attention slots, with the salience and its features). Measured durations (how long an agent role ran) are in an optional `timing` object, never in `data`, so a rerun of the same input has the same `data`. Each carries `traceid = <sensor_id>:<sequence_no>` of the reading that caused it, so a shared timeline can line up all three layers.

## Pointing the Brain at a different partner

Edit `config/partners.yaml`; no code changes.

```yaml
twin:     {adapter: mcp,  url: http://twin-host:8000/mcp, hmac_secret_env: TWIN_HMAC_SECRET, poll_interval_ms: 200}
guardian: {adapter: rest, url: http://guardian-host:8100, mode: sidecar, verdict_deadline_ms: 2000}
graph:    {backend: neo4j}    # with uri / user / password_env; or memory
brain:    {state_file: state/brain.sqlite, state_max_age_s: 900}   # working memory kept across restarts
```

A partner with a different protocol needs one new adapter class implementing `TwinPort` or `GuardianPort` (`src/brain/ports.py`); nothing else in the Brain changes.

## Authentication and integrity

- **Readings:** HMAC-SHA256 in `provenance.hmac`, computed over the envelope without `provenance` and `trust`, serialised as JSON with sorted keys and no whitespace (UTF-8). Secret from the env var named in `twin.hmac_secret_env`. The Brain rejects unsigned or mismatching readings.
- **Actuator calls:** signed the same way with the secret in `BRAIN_HMAC_SECRET`, `signed_by: city_brain`.
- **Replay:** a `sequence_no` that is not greater than the last one seen for that sensor is rejected.
- **Version:** a reading whose `contract_version` is not in `brain.accepted_contract_versions` is rejected.
- **Timeline push:** `POST /api/events` takes events from partners only inside their own namespace (`twin.*`, `guardian.*`); `brain.*` and `source: city-brain` are refused, and a pushed event is streamed with `pushed: true`. Off loopback (or with `security.require: always`) a push needs that partner's token (`Authorization: Bearer`), and the event's source is the token's partner, whatever the body says.
- **Tokens and scopes:** off loopback every route except `/health` and `/schemas` needs a bearer token with the scope it needs: `read`, `analyse`, `push`, `approve`, `admin`. Requests over `security.max_body_bytes` get 413, a caller over `security.rate_per_minute` gets 429 with `Retry-After`, and responses carry a content-security policy.

### Other carriers and short-lived tokens

A Twin that speaks plain HTTP instead of MCP needs only `twin: {adapter: http, url: ...}`: `GET /readings?cursor=&limit=` (the page `list_readings` returns), `GET /topology`, `GET /capabilities`, `POST /actuators/{action}` (the signed call). `python -m mocks.twin --http` serves it for a trial. Operators can use short-lived tokens: set `BRAIN_TOKEN_KEY`, then `brain token --sub ana --scope read,analyse --ttl 8h`; `brain token --revoke ID` withdraws one.

### Encrypted connections and key rotation

Off loopback, run the Brain's listener over TLS (`brain serve --tls-cert certs/brain.pem --tls-key certs/brain.key`, plus `--tls-client-ca certs/ca.pem` to demand a client certificate), and point the partner connections at `https://` URLs with `twin.tls` and `guardian.tls` (`ca`, `cert`, `key`) in `config/partners.yaml`. `scripts/make_certs.sh` makes a local authority and certificates with no network. Signing keys have ids and end dates so they can be rotated without a flag day: see [KEYS.md](KEYS.md). The threats and the test for each: [SECURITY.md](SECURITY.md).

## When the Twin changes

The Brain keeps what it knows about the Twin in configuration, so a change on the other side is usually a file edit:

| The Twin now... | Edit | Example |
|---|---|---|
| names a sensor type differently | `twin.type_aliases` in `config/partners.yaml` | `{river_gauge: water_level}` |
| sends a field under another name or unit | `twin.profiles` | `water_level: {level_m: {from: depth_cm, scale: 0.01}}` builds `level_m` from `depth_cm` (never overriding a `level_m` it really sends) |
| has a new kind of sensor or service | a pack file in `brain.packs_dir` (and its `rules/` folder) | `detectors` say what reading opens an incident, `actuators` what the pack may call, `needs` what it cannot work without, `severity` how serious each of its incident types is |
| lacks an actuator a pack needs | nothing | the pack bids low, the timeline says `brain.pack.uncovered` when no pack can answer, and the gate refuses the call with `capability` |
| changes a range or threshold | the pack's detector | `when: [{field: level_m, op: ">=", value: 1.0}]` |

Profiles and aliases are applied only after the signature and replay checks pass, to the Brain's copy of the reading; the Guardian is still asked about the original. A reading of a type the Brain does not know is stored and ignored until an alias or a pack gives it meaning. A pack file with an unknown key, an unreadable file or rules that do not load is skipped and reported as `brain.pack.rejected`; the other packs load.

### Finding the edit: `brain onboard`

`uv run brain onboard --sample readings.json [--yaml]` (or `--twin URL` to sample a live Twin over MCP) reads a sample of readings and proposes the `twin.type_aliases` and `twin.profiles` above. Each line has a confidence and its evidence; under 0.75 it is marked REVIEW, and a type nothing fits is listed as UNMAPPED, never guessed. It prints and never edits a file: a person reads it and edits the config. A suffix on a field name (`_cm`, `_mm`, `_pct`, `_w`) sets the scale.

### Checking a layer: `brain conformance` and `brain redteam`

`uv run brain conformance [--twin URL] [--guardian URL] [--brain URL]` runs the contract checks on any layer (no arguments: the shipped mocks and this Brain, in process); `--probe-actuators` also calls the Twin's actuators with signed test calls. A report is in `docs/conformance/`. `uv run brain redteam` runs 22 attacks (forged and replayed readings, hostile ids, wrong scopes, oversize bodies, floods, a reused approval, an agent tool that actuates) and exits 1 if any gets through.

## Retractions and what the Brain learns

The Brain keeps closed incidents as episodes (typed values only, people renamed inside the episode, no unit ids) when `brain.episodes_dir` is set. `brain sleep` mines them for plans the team made the same way at least twice, rehearses each in simulation against the real team, and promotes it to a reflex only if it passes six checks: provenance (every reading trusted, none retracted), safety (only contain, respond and alert, inside the Police allowlist), the size cap, rehearsal (same decisions, fewer team runs), variants (the neighbouring stories stay with the team) and the whole Test Book (identical decisions). It never reads whether a dispatch worked.

If the Guardian later takes back a verdict, `POST /api/retractions` (off loopback, only the Guardian's push token may call it; the Twin's gets 403) makes every later action that cites the reading fail the gate's `trust_ref` check, and the next `brain sleep` revokes any reflex that an episode with that reading taught. Units already sent are not recalled. Reading ids are `sensor_id#sequence_no`; a Twin that restarts its numbering would make a retraction match older episodes too, which only errs towards forgetting.

## When a partner sends something unexpected

The reading is dropped and a `brain.reading.rejected` event states why:

| `code` | Example `message` |
|---|---|
| `bad_contract_version` | `contract_version '2025-01-01' is not supported; this Brain accepts ['2026-09-17']` |
| `schema_invalid` | `reading envelope is invalid: zone_id: Field required` |
| `signature_missing` / `signature_invalid` | `cit-feed-07#4: provenance.hmac does not match the payload` |
| `replay_or_out_of_order` | `cit-feed-07: sequence_no 5 is not greater than the last seen (5)` |
| `reading_stale` | `wl-01#7: timestamp is 3600 s from the Brain's clock, more than 30 s` (only when `twin.max_age_s` is set) |
| `value_invalid` | `cit-feed-07#1: value for type 'citizen_activity' is invalid: citizen_id: Field required` |

Partner failures do not stop the Brain:

- **Guardian silent** past `verdict_deadline_ms`: degraded mode. Incidents are tracked, nothing is dispatched until verdicts return.
- **Guardian quarantines an actuator:** the call is refused, logged as `brain.action.blocked`, and the next nearest station is used.
- **Twin rejects a call or has no unit:** recorded in `brain.action.result`; the incident stays open.
- **The Brain itself restarts:** `brain run` and `brain serve --live` save their state after every reading and restore it on start (open incidents, units out, what was already sent, the replay check, the stream position). State older than `state_max_age_s`, from a different city layout, or from an earlier Twin stream is discarded and the timeline says why.
- **Neo4j or the LLM unreachable:** the Brain runs in memory, and on its rule tier and scripted team.

## Added 5 November (agreed with the partners)

- **MQTT as a way to deliver readings.** `twin.adapter: mqtt` subscribes to `{prefix}/{zone_id}/{type}/{sensor_id}` (QoS 1, a persistent session) and receives the same signed reading envelope, one per message. Actions, topology and capabilities still go over HTTP (`GET /topology`, `GET /capabilities`, `POST /actuators/{action}`). The topic is routing only: the signed body is the identity. Readings are re-ordered per sensor by `sequence_no` within `twin.mqtt.reorder_ms` (200 ms); a lost one is not waited for longer.
- **A Twin that cannot be reached.** The Brain reports `brain.degraded` with `component: twin` once, asks again every `twin.retry_s` (2 s; 0 gives up), and on an answer reports `brain.recovered` and reads on after the last reading it handled. Nothing it holds is lost.
- **A refused push is an event.** `POST /api/events` refusals (`reserved_namespace`, `source_reserved`, `type_not_allowed`) are logged as `brain.push.refused` with the attempted type and the claimed source, and nothing else from the push.
