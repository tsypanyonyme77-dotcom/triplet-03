# Guardian Interface Card (R1)

**Contract version: `1.0`** · Guardian layer of the TSYP14 City Brain Convergence triplet.
Every field name, threshold and default below is a *proposal to agree with partners* until frozen (see the last section).

The Guardian answers one question for the Brain: **"Is this data telling the truth?"**
It receives every sensor reading from the Twin, judges it in six layers, and returns a signed **verdict**.
The Brain sends actuator calls *through* the Guardian, which checks them and verifies their effect.

```
Twin ──readings──▶ Guardian ──signed verdicts + alerts──▶ Brain
Twin ◀──audited actuator calls + containment── Guardian ◀──actuator calls (trust_ref)── Brain
```

## 1. Transports

| Direction | Default | Alternatives (set in `config/guardian.yaml`) |
|---|---|---|
| Twin → Guardian readings | Twin `POST /v1/readings` (push) | `twin.mode: pull` → Guardian polls `GET {twin}/readings?cursor=N`; `twin.transport: mcp` (MCP tool `get_readings`); `twin.transport: mqtt` (topic `city/readings/#`) |
| Guardian → Twin actuator/containment calls | `POST {twin}/tools/{action}` with the actuator-call JSON | MCP tool `{action}`; MQTT `city/tools/{action}`, reply on `city/tools/{action}/reply/{call_id}` |
| Brain → Guardian | REST (below) | — |
| Guardian → Brain push | `WS /v1/ws/verdicts` (verdicts + alerts) | — |
| Guardian → timeline (R3) | `WS /v1/ws/timeline` (every audit event) | JSONL files `t5-guardian-YYYYMMDD.log` |

Repointing to real partners: edit `twin.base_url` / `twin.transport` / `twin.mode` in `config/guardian.yaml` (or
`TWIN_BASE_URL`, `TWIN_TRANSPORT`, `TWIN_MODE` in `.env`) and the keys in `.env`. No code changes.

## 2. Authentication

| What | How |
|---|---|
| REST calls to the Guardian | header `X-API-Key: <key>`; one key per partner in `.env` (`BRAIN_API_KEY`, `TWIN_API_KEY`, `OPS_API_KEY`). The key decides the caller identity used in audit logs and quarantine. `/health` and `/docs` are open. |
| WebSockets | `X-API-Key` header, or `?api_key=` query parameter (browsers cannot set WS headers). Bad key → close code `4401`. |
| Sensor envelopes | HMAC-SHA256 with the shared `TWIN_HMAC_KEY` (field `hmac`). |
| Verdicts | HMAC-SHA256 with the shared `GUARDIAN_HMAC_KEY` (field `signature`). |
| Scenario tagging | optional header `X-Scenario-Id: T1` is copied into every audit event caused by that request. |

## 3. Canonicalisation and HMAC

Both signatures use the same rule:

1. Take the JSON object **without** the signature field (`hmac` for envelopes, `signature` for verdicts).
2. Serialise with sorted keys, no whitespace, UTF-8: Python `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
3. `hex(HMAC-SHA256(key, bytes))`, compared in constant time (`hmac.compare_digest`).

The Guardian canonicalises **the JSON it received**, so sign exactly the object you send. Keep floats in plain decimal
notation (no exponents such as `1e-07`) so every language prints them the same way.

**Worked example** (example key `example-twin-key`, never use it in production). The envelope in §4.1 without `hmac`
canonicalises to:

```text
{"contract_version":"1.0","sensor_id":"wl-port-03","sensor_type":"water_level","sequence_no":4821,"sequence_reset":false,"timestamp":"2026-11-02T14:03:18Z","value":{"level_m":1.8},"zone_id":"zone-07"}
```

`HMAC-SHA256("example-twin-key", that string)` = `30d230a2d99a160d20260477e151fa91c58e98d6d76875d0d7fffcdc1195911a`.

`GET /v1/verify/signature?verdict_id=...` returns the exact canonical string and signature of any stored verdict so
the Brain team can test its verifier.

## 4. Messages

### 4.1 Sensor reading envelope (Twin → Guardian)

`POST /v1/readings` with one envelope or a JSON list of up to 1000 envelopes.

```json
{
  "contract_version": "1.0",
  "sensor_id": "wl-port-03",
  "sensor_type": "water_level",
  "zone_id": "zone-07",
  "timestamp": "2026-11-02T14:03:18Z",
  "sequence_no": 4821,
  "value": {
    "level_m": 1.8
  },
  "sequence_reset": false,
  "hmac": "30d230a2d99a160d20260477e151fa91c58e98d6d76875d0d7fffcdc1195911a"
}
```

Rules:

- `contract_version` must equal `"1.0"`; anything else is rejected with `contract_version_mismatch` (never silently read).
- `sequence_no` must strictly increase per sensor. A repeated or lower number is a **replay** → `untrusted`.
- **Sequence-reset rule (Twin restart):** send `"sequence_reset": true` (inside the signed body) on the first reading
  after a restart. It is accepted only if its `timestamp` is newer than the last reading seen, so an old reset cannot be
  replayed. It is logged as an audit event.
- `timestamp` must be ISO-8601 with a timezone and within ±30 s of the Guardian clock.
- `value` must contain exactly the fields of the sensor type (`config/sensor_registry.yaml`):

| sensor_type | value fields | interval |
|---|---|---|
| `traffic_camera` | `vehicle_count` int ≥0, `avg_speed_kmh` 0–200, `congestion_score` 0–1 | 10 s |
| `water_level` | `level_m` (0 to zone `max_water_level_m`) | 5 s |
| `power_meter` | `load_kw` ≤ `capacity_kw`, both ≥0 | 10 s |
| `air_quality` | `aqi` 0–500, `smoke` bool | 10 s |
| `emergency_call` | `call_id`, `incident_type` (fire/flood/accident/medical/crime), `caller_id` | event-driven |
| `rain_gauge` | `rainfall_mm_h` 0–300 | 10 s |
| `flow_meter` | `flow_rate_m3s` ≥0 | 5 s |
| `grid_meter` | `frequency_hz` 45–55, `voltage_v` | 10 s |

Response: `200 {"results": [{"verdict": {...}} | {"error": {...}}, ...]}` in input order. A single malformed object
gets `422` with the error model. A well-formed reading with a bad HMAC gets an `untrusted` verdict (`hmac_invalid`).

### 4.2 Verdict (Guardian → Brain)

`POST /v1/verdicts/request` with `{"sensor_id": "wl-port-03", "sequence_no": 4821}` (`sequence_no` optional = latest),
`GET /v1/verdicts/{verdict_id}`, or the `WS /v1/ws/verdicts` stream (`{"type": "verdict", "verdict": {...}}`).

```json
{
  "verdict_id": "verdict-88213",
  "reading_ref": {
    "sensor_id": "wl-port-03",
    "sequence_no": 4821
  },
  "status": "untrusted",
  "trust_score": 0.2,
  "reasons": [
    "rate_of_change",
    "no_rainfall_corroboration",
    "no_flow_corroboration"
  ],
  "layer_results": [
    {
      "layer": "L1_authenticity",
      "passed": true,
      "severity": "info",
      "reason_code": null,
      "detail": "schema, contract_version and HMAC valid"
    },
    {
      "layer": "L2_freshness",
      "passed": true,
      "severity": "info",
      "reason_code": null,
      "detail": "sequence and timestamp fresh"
    },
    {
      "layer": "L4_dynamics",
      "passed": false,
      "severity": "medium",
      "reason_code": "rate_of_change",
      "detail": "level_m changed 0.4→1.8 in 5s (0.28/s > 0.01/s)"
    },
    {
      "layer": "L5_corroboration",
      "passed": false,
      "severity": "strong",
      "reason_code": "no_rainfall_corroboration",
      "detail": "0 agree / 6 disagree of 6 independent sources"
    },
    {
      "layer": "L5_corroboration",
      "passed": false,
      "severity": "strong",
      "reason_code": "no_flow_corroboration",
      "detail": "0 agree / 6 disagree of 6 independent sources"
    }
  ],
  "action_taken": "isolate_sensor",
  "threat_level": "normal",
  "ts": "2026-11-02T14:03:23Z",
  "expires_at": "2026-11-02T14:03:53Z",
  "signature": "9caf08567015b18641dc36bc203fec522295438361ee75175a662bb191b0e81f"
}
```

(Example signed with `example-guardian-key`.)

| status | meaning | rule for the Brain |
|---|---|---|
| `trusted` | passed both hard gates and scored ≥ 0.8 (≥ 0.9 with 2 corroborating sources when the zone threat level is raised) | act |
| `suspect` | something is off, or not enough independent evidence (0.4–0.8, or capped) | corroborate before acting |
| `untrusted` | failed a hard gate, physically impossible, contained sensor, or scored < 0.4 | ignore |
| `unknown` | stale, missing, never seen, or the Guardian could not evaluate | treat as not trusted |

A verdict is valid until `expires_at` (TTL 30 s). Use its `verdict_id` as `trust_ref` in actuator calls.

### 4.3 Actuator call (Brain → Guardian → Twin)

`POST /v1/actuator-calls`. The Brain never calls the Twin's actuators directly.

```json
{
  "call_id": "call-551",
  "actuator_id": "valve-port-12",
  "action": "set_valve_state",
  "params": {
    "state": "closed"
  },
  "zone_id": "zone-07",
  "requesting_layer": "brain",
  "trust_ref": "verdict-88190",
  "justification": "flood risk zone-07",
  "incident_id": "inc-77"
}
```

Actions: `set_valve_state` (open/closed), `set_grid_state` (connected/disconnected), `set_signal` (green/red +
`duration_s`), `dispatch_unit` (`unit_type` police/ambulance/fire, needs `incident_id`). Containment actions
(`quarantine_device`, `isolate_sensor`, `clear_quarantine`) are reserved for the Guardian, which sends them with
`requesting_layer: "guardian"` and `trust_ref: null`.

The Guardian forwards the same JSON to the Twin at `POST /tools/{action}`. Twin reply:

```json
{
  "status": "ok",
  "current_state": {
    "state": "closed"
  },
  "reverts_at": null
}
```

Guardian answer to the Brain (always `200`; blocked calls never reach the Twin):

```json
{
  "call_id": "call-551",
  "decision": "forwarded",
  "reasons": [],
  "twin_reply": {
    "status": "ok",
    "current_state": {
      "state": "closed"
    },
    "reverts_at": null
  }
}
```

Block reasons: `trust_ref_missing`, `trust_ref_unknown`, `trust_ref_not_trusted`, `trust_ref_expired`,
`trust_ref_zone_mismatch`, `sensor_isolated`, `device_quarantined`, `caller_quarantined`, `actuator_unreliable`,
`unknown_actuator`, `containment_reserved`, `safety_hospital_grid`, `duplicate_dispatch`, `incident_id_missing`,
`no_switchable_grid`, `no_road_access`, `rate_limited`, `twin_unreachable`. Warnings on forwarded calls:
`odd_hour_action`, `twin_rejected`, `reply_contradicts_order`.

After forwarding, the effect verifier checks the physical effect with an **independent** sensor
(`config/policies.yaml`), e.g. valve closed → flow drops ≥ 80 % within 30 s. Failures (`no_effect`, `wrong_effect`,
`partial_effect`, `late_effect`, `reply_contradicts_order`, `unauthorised_effect`, `reverted_early`) raise an
`actuator_failure` alert telling the Brain to use a backup, and the actuator is flagged unreliable. If the verify
sensor is itself untrusted, the outcome is `unknown` and the actuator is not accused.

### 4.4 Security alert (Guardian → Brain, timeline)

On `WS /v1/ws/verdicts` as `{"type": "alert", "alert": {...}}` and `GET /v1/alerts?since=<iso>`.

```json
{
  "alert_id": "alert-3f9a1c",
  "type": "coordinated_spoofing",
  "zone_id": "zone-08",
  "evidence": [
    {
      "signal": "reading_failed",
      "ts": "2026-11-02T14:05:02Z",
      "zone_id": "zone-08",
      "device_id": "wl-res-01",
      "source": "wl-res-01",
      "verdict_id": "verdict-9a01",
      "reasons": [
        "rate_of_change",
        "no_rainfall_corroboration"
      ]
    }
  ],
  "suggested_response": "zone under attack: act only on readings corroborated by 2+ sources",
  "threat_level": "under_attack",
  "ts": "2026-11-02T14:03:23Z"
}
```

Types: `replay`, `spoofing`, `coordinated_spoofing`, `flood_dos`, `tampering`, `command_injection`,
`compromised_twin`, `slow_drift`, `attack_during_incident`, `actuator_failure`, `isolation_cap_reached`.

### 4.5 Timeline event (R3)

On `WS /v1/ws/timeline` and one JSON line per event in `${LOG_DIR}/t5-guardian-YYYYMMDD.log`.
`type` is one of `reading | verdict | decision | action | alert | containment | error | system`; `data.kind` is the
precise event (`reading`, `verdict`, `actuator_call`, `effect_verification`, `isolate_sensor`, `quarantine_device`,
`clear_quarantine`, `threat_level`, `sensor_stale`, `sequence_reset`, ...).

```json
{
  "event_id": "evt-5d2e7a90b1c3",
  "ts": "2026-11-02T14:03:23Z",
  "type": "verdict",
  "scenario_id": "T1",
  "sensor_id": "wl-port-03",
  "actuator_id": null,
  "zone_id": "zone-07",
  "summary": "untrusted wl-port-03#4821 score=0.2 [rate_of_change, no_rainfall_corroboration]",
  "data": {
    "kind": "verdict",
    "verdict_id": "verdict-88213",
    "status": "untrusted",
    "trust_score": 0.2,
    "reasons": [
      "rate_of_change",
      "no_rainfall_corroboration"
    ],
    "action_taken": "isolate_sensor",
    "threat_level": "normal"
  }
}
```

### 4.6 Error model (every endpoint)

```json
{
  "error": "contract_version_mismatch",
  "message": "contract_version '2.0' is not supported; this Guardian speaks '1.0'",
  "field": "contract_version"
}
```

Codes: `schema_invalid`, `contract_version_mismatch`, `hmac_invalid`, `auth_required`, `forbidden`,
`trust_ref_missing`, `verdict_not_found`, `sensor_not_found`, `not_contained`, `batch_too_large`, `internal_error`.

## 5. Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness, version, contract version, transport, twin status (`ok/partial/degraded/unknown`) |
| POST | `/v1/readings` | push one reading or a batch |
| POST | `/v1/verdicts/request` | verdict for a sensor's latest (or given) reading |
| GET | `/v1/verdicts/{verdict_id}` | fetch a stored verdict (check a `trust_ref`) |
| GET | `/v1/readings/{sensor_id}/latest` | latest usable value; last-known-good with `rolled_back: true` when contained/untrusted |
| GET | `/v1/sensors/{sensor_id}/status` | trust state, isolated/quarantined, stale, last verdict |
| POST | `/v1/actuator-calls` | audited actuator gateway |
| GET | `/v1/threat` | threat level per zone + open incidents |
| GET | `/v1/alerts?since=` | recent alerts |
| GET | `/v1/containment` | active isolations / quarantines / unreliable actuators |
| POST | `/v1/containment/clear` | manual release `{"device_id": "...", "reason": "..."}` |
| POST | `/v1/containment/quarantine` | operator quarantine (ops key only) |
| GET | `/v1/verify/signature` | canonical string + signature helper |
| WS | `/v1/ws/verdicts` | verdicts + alerts |
| WS | `/v1/ws/timeline` | all audit events |
| GET | `/timeline` | R3 timeline screen (HTML/JS; open, consumes `/v1/ws/timeline` with `?api_key=`) |

OpenAPI: `GET /docs`.

## 6. Fail-safe rule

**If the Guardian is unreachable, a verdict is missing, expired, or not `trusted`, the Brain treats the data as
`unknown` and does not act on it.** The Guardian itself never answers `trusted` on an error: internal errors produce
`unknown` verdicts and an `error` audit event. A silent Twin turns every sensor `unknown` after 2× its interval and
`/health` reports `twin: degraded`.

## 7. Latency budget

`POST /v1/verdicts/request` answers from memory: p95 < 500 ms (measured in-process at a few milliseconds over 200
requests, see `tests/integration/test_ws_latency_restart.py`).

## 8. Open items to agree with the Twin and Brain teams (proposals)

| # | Item | Our proposal |
|---|---|---|
| 1 | Transport and field names / units | Freeze `contract_version` 1.0 as written here after both teams confirm names and units |
| 2 | HMAC key sharing and rotation | Shared secrets via `.env`; rotate by restarting with the new key at an agreed time; constant-time compare |
| 3 | Gate or stream | Synchronous gate: the Brain asks `/v1/verdicts/request` (or uses a fresh streamed verdict) before acting |
| 4 | Location format of emergency calls | `zone_id` only for 1.0; optional coordinates later |
| 5 | Zone granularity and adjacency | Twin exposes zone metadata; until then `config/city_model.yaml` + `crosschecks.yaml` are our documented copy |
| 6 | Sequence reset after a Twin restart | `sequence_reset: true` in the signed body on the first reading, with a newer timestamp |
| 7 | Normal-day recording for baselines | Twin provides N hours of clean data; until then the baseline learns online from trusted readings only |
| 8 | Sensors/actuators in scope for Phase 1 | The eight sensor types and five actuators above |
| 9 | Owner of the shared timeline screen (R3) | One owner; each layer only emits events (ours: `WS /v1/ws/timeline`) |
| 10 | Actuator calls via Guardian | The Brain sends all actuator calls through `/v1/actuator-calls` |
