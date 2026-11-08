# For the Twin team: what the City Brain needs from your engine

The City Brain reads your sensor readings, asks the Guardian whether to trust each one, decides, and calls your actuators. It has only ever run against our mock Twin (`mocks/twin/`). This page is everything you need to replace that mock with your engine. Contract `2026-09-17`.

Read this page, then `../INTERFACE.md` (one page, one example of every message). The long form is `INTEGRATION-brain.md`.

## 1. The minimum your engine must do

| # | You provide | Shape | Example file in `contracts/examples/` |
| --- | --- | --- | --- |
| 1 | `get_topology()` | `{zones, adjacency, exits, facilities, sensors}`, sent once at start | `topology.json` |
| 2 | `list_readings(cursor, limit)` | `{readings: [...], next_cursor, stream_id}`, oldest first; the Brain asks every 200 ms | `reading.*.json` |
| 3 | A signed envelope on every reading | `provenance: {signed_by: "twin", hmac}` (section 3) | all `reading.*.json` |
| 4 | One tool per actuator, taking `call=<envelope>` | `dispatch_unit`, `broadcast_alert`, `recall_unit`, `set_signal_phase`, `set_valve_state`, `set_grid_connection`; offer only the ones you can really do | `actuator_call.*.json` |
| 5 | An answer to each call | `{"status": ...}`: `dispatched`, `set`, `recalled`, `broadcast`, `duplicate` or `rejected` (with `reason`) | `actuator_result.*.json` |
| 6 | `unit_status` readings after a dispatch | `{unit_id, incident_id, state}`; states `en_route`, `pursuing`, `in_position`, `on_scene`, `apprehended`, `lost`, `returning` | `reading.unit_status.json` |

The Brain calls only the tools you list, so a missing actuator costs a capability, not a crash. Plain HTTP instead of MCP is supported (`GET /readings`, `GET /topology`, `GET /capabilities`, `POST /actuators/{action}`; `python -m mocks.twin --http` shows it). MQTT delivery of readings is supported too (`twin.adapter: mqtt`, topics `{prefix}/{zone_id}/{type}/{sensor_id}`).

Sensor types the Brain understands today: `traffic_camera`, `water_level`, `power_load`, `air_quality` (Data Dictionary section 2), plus `cctv_anomaly`, `gunshot`, `emergency_call`, `citizen_activity` and `unit_status`. Another type is stored and ignored until you map it (section 5). Fields it does not know are dropped; demographic fields such as `age` and `wealth` are dropped on purpose.

Three behaviours we rely on, all in `INTEGRATION-brain.md`:

- **A repeated dispatch is answered, not repeated:** the same `incident_id`, `unit_type`, `mode` and target returns `{"status": "duplicate", "unit_id": <the unit already sent>}`.
- **`sequence_no` rises per sensor.** A reading whose number does not rise is rejected as a replay. If your stream restarts from zero, change `stream_id` (any string) so the Brain does not read it as a replay.
- **The ids you choose** (sensor, type, zone) may hold only letters, digits and `. _ : # -`, 64 at most.

## 2. Try it in ten minutes

```bash
cd brain && uv sync
uv run python -m mocks.twin --port 8765        # our mock, as a reference to read: mocks/twin/server.py and engine.py
uv run brain conformance                       # the mocks and this Brain checked against the contract: 19 pass, 1 warning
```

Point the checker at your engine (set the same secret on both sides first, section 3):

```bash
export TWIN_HMAC_SECRET=dev-only-twin-secret
uv run brain conformance --twin http://your-host:8000/mcp
uv run brain conformance --twin http://your-host:8000/mcp --probe-actuators   # also sends signed test calls
```

Each line is a pass, a warning or a fail with the fix in one line (T1 to T9 are yours). Then run the Brain on your stream:

```bash
# config/partners.yaml:  twin: {adapter: mcp, url: http://your-host:8000/mcp, hmac_secret_env: TWIN_HMAC_SECRET}
export TWIN_HMAC_SECRET=dev-only-twin-secret BRAIN_HMAC_SECRET=dev-only-brain-secret
uv run brain serve --live                      # the timeline screen at http://127.0.0.1:8080
```

Every reading, verdict, decision and refusal appears on the screen with its reason. A reading the Brain refuses shows as `brain.reading.rejected` with one of these codes: `bad_contract_version`, `schema_invalid`, `signature_missing`, `signature_invalid`, `replay_or_out_of_order`, `reading_stale` (only when `twin.max_age_s` is set), `value_invalid`.

## 3. Signing, in any language

`provenance.hmac` is HMAC-SHA256, as lower-case hex, over the envelope **without** `provenance` and `trust`, written as JSON with keys sorted at every level, no whitespace, UTF-8, non-ASCII characters left as they are. The Brain signs its calls the same way with `signed_by: "city_brain"`.

Known-answer check: every `reading.*.json` in `contracts/examples/` verifies with the secret `dev-only-twin-secret`, and every `actuator_call.*.json` with `dev-only-brain-secret`. Sign `reading.traffic_camera.json` yourself and compare. A JavaScript version that passes all of them:

```js
const canon = v => Array.isArray(v) ? '[' + v.map(canon).join(',') + ']'
  : (v && typeof v === 'object') ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}'
  : JSON.stringify(v);
const { provenance, trust, ...rest } = envelope;
const hmac = require('crypto').createHmac('sha256', secret).update(canon(rest)).digest('hex');
```

Numbers: a whole-number float is signed as an integer (`6.0` as `6`), as RFC 8785 and JavaScript write it, on both sides, so you get the same bytes in any language. The Brain also still accepts the older form (`6.0`), so a signature made before 6 Nov holds. Two rules for you: sign exactly the numbers you send, and avoid exponent notation (`1e-7`): Python writes `1e-07`, JavaScript `1e-7`.

Secrets are agreed out of band and held in environment variables, never in a file in the repository. The `dev-only-*` values are for trials on one machine. Key ids, rotation and Ed25519 are in `KEYS.md`.

## 4. Scenarios: how we test together

The Test Book is `scenarios/d1.json` to `d4.json`; `TESTBOOK-brain.md` says what each layer should do in each. A scenario file holds a `topology` (the layout your `get_topology` returns) and `events`: timed readings (`at_ms`, `sensor_id`, `type`, `zone_id`, `value`). The mock replays them through the same tools your engine will offer; `scenarios/topology/` has four city layouts. Your engine does not need to read our scenario files, but it must be able to produce an equivalent stream: for `d3` (a crime with a pursuit), citizen movements in two zones, a camera anomaly, and `unit_status` readings after our dispatch.

`scenarios/triggers/<id>.sh` starts one scenario; `uv run brain scenario d3 --no-spawn` plays it against the partners in `config/partners.yaml`. Each run writes a hash-chained log in `logs/`. **Starting a scenario on your side** (agreed): the Twin offers one call that loads a scenario and starts its stream, as our mock's admin tool does.

## 5. If your names or units differ

You do not change code and neither do we. Capture a sample and let the Brain propose the mapping:

```bash
uv run brain onboard --twin http://your-host:8000/mcp --yaml       # or --sample readings.json
```

It prints `twin.type_aliases` and `twin.profiles` lines for `config/partners.yaml` with a confidence for each, and marks anything it is unsure of for review. It never edits a file.

## 6. What we still need from you

These stop us switching on parts of the Brain that are built and waiting.

1. **Which sensors move together, and what each actuator does to a sensor.** Switches on `forward.coupled` and `forward.effects`.
2. **Whether same-type sensors in one zone are independent.** Decides how we count corroboration.
3. **When a first signed stream can exist,** even from a script, so we can run `brain conformance --twin` against it.

## 7. Where to look when something fails

| Symptom | Look at |
| --- | --- |
| `conformance` fails a T check | the one-line fix it prints; then `INTEGRATION-brain.md`, "What the Brain receives" |
| Readings arrive but are refused | `brain.reading.rejected` on the screen, its `code` (section 2) |
| Signatures never match | section 3; check both sides read the same secret and the example files verify |
| The Brain sends nothing | the Guardian's verdicts: no trusted verdict, no call. Valve and grid calls also wait for a person's approval on the screen |
| A call is refused by you | your `reason` is shown in `brain.action.result`; the incident stays open |
| Anything else | `SECURITY.md` for the threat model, `KEYS.md` for keys |

Questions go to the City Brain team.
