# City Brain: Interface Card

Contract `2026-09-17`. Schemas: `contracts/schemas/` (also `GET /schemas`); one example of every message: `contracts/examples/`. The full guide is `docs/INTEGRATION-brain.md`; the Twin team's start page is `docs/TWIN-HANDOVER.md`.

## What the Brain receives

| From | Message | Transport (default) |
|---|---|---|
| Twin | Sensor readings, polled every 200 ms | MCP `list_readings(cursor, limit)` → `{readings, next_cursor, stream_id}` |
| Twin | City layout | MCP `get_topology()` → zones, adjacency, exits, facilities, sensors |
| Guardian | Trust verdict per reading | REST `POST /verdicts {"reading": <envelope>}`; `GET /quarantine/{device_id}` |
| Twin, Guardian | Their own timeline events (optional) | `POST /api/events`, CloudEvents 1.0, only `twin.*` or `guardian.*` types |

```json
{"contract_version": "2026-09-17", "sensor_id": "tcam-05-01", "type": "traffic_camera", "zone_id": "zone-05", "timestamp": "2026-10-12T19:41:57.054Z", "sequence_no": 1, "value": {"congestion_score": 0.82, "vehicle_count": 47, "avg_speed_kmh": 6.4, "smoke_detected": false}, "provenance": {"signed_by": "twin", "hmac": "d53e70d8…"}}
```

```json
{"verdict_id": "verdict-000001", "reading_ref": {"sensor_id": "cam-07-02", "sequence_no": 1}, "status": "trusted", "confidence": 0.97, "reasons": ["rate_ok", "hmac_ok"], "issued_at": "2026-10-12T19:41:56Z", "expires_at": "2026-10-12T19:43:56Z"}
```

## What the Brain sends

| To | Message | Transport (default) |
|---|---|---|
| Twin | Signed actuator call: `dispatch_unit`, `broadcast_alert`, `recall_unit`, `set_signal_phase`, `set_valve_state`, `set_grid_connection` | MCP tool named after the action, `call=<envelope>`; only tools the Twin lists |
| Anyone | Timeline events, replayed then followed | `GET /events` (Server-Sent Events, CloudEvents) and `logs/<scenario>-<time>.jsonl` |
| Anyone | Why a decision was made | `GET /api/decisions/{id}`, `/api/decisions/{id}/explanation` |

```json
{"contract_version": "2026-09-17", "actuator_id": "police-dispatch-05", "action": "dispatch_unit", "params": {"unit_type": "police", "zone_id": "zone-07", "incident_id": "inc-0001", "mode": "pursuit", "target_id": "cit-88213"}, "requesting_layer": "city_brain", "justification": "Suspect cit-88213 score 0.82. Rule POL-001.", "trust_ref": "verdict-000004", "provenance": {"signed_by": "city_brain", "hmac": "846249a6…"}}
```

```json
{"status": "dispatched", "unit_id": "unit-p-01", "eta_minutes": 3}
```

```json
{"specversion": "1.0", "id": "evt-000012", "source": "city-brain", "type": "brain.decision.made", "time": "2026-10-12T20:28:33.980Z", "subject": "inc-0001", "traceid": "cit-feed-07:4", "data": {"decision_id": "dec-0002", "action": "dispatch_unit", "trust_ref": "verdict-000004"}}
```

A repeated dispatch returns `{"status": "duplicate", "unit_id": <the unit already sent>}`. Valve and grid calls are high impact: they wait for a person's signed approval.

## Pointing the Brain at a different partner

Edit `config/partners.yaml`: no code changes. Partner addresses, adapters, signing-secret variable names, renames and units are all there. The environment variables `TWIN_URL` and `GUARDIAN_URL` (the triplet's root `.env`) override the two addresses; a bare `http://host:port` for an MCP Twin means `/mcp`.

```yaml
twin:     {adapter: mcp,  url: http://twin-host:8000/mcp, hmac_secret_env: TWIN_HMAC_SECRET}
guardian: {adapter: rest, url: http://guardian-host:8100, mode: sidecar}
```

`uv run brain onboard --sample readings.json` proposes those two edits for a renamed Twin; `uv run brain conformance` checks any Twin, Guardian or Brain against this card; `uv run brain redteam` attacks the Brain. The Brain also serves read-only MCP tools at `/mcp` and an agent card at `/.well-known/agent-card.json`.

A Twin may speak plain HTTP instead of MCP (`twin.adapter: http`: `GET /readings`, `POST /actuators/{action}`, same envelopes), or publish readings to an MQTT broker (`twin.adapter: mqtt`: topic `{prefix}/{zone_id}/{type}/{sensor_id}`, QoS 1, same envelopes; actions and topology stay on `twin.url` over HTTP). Another protocol needs one adapter class (`src/brain/ports.py`); `twin.type_aliases` and `twin.profiles` rename sensor types and fields.

## Authentication and integrity

- **Readings and calls:** HMAC-SHA256 over canonical JSON (sorted keys, no whitespace) in `provenance.hmac`. Secrets come from the environment variables in config; the Brain signs with `BRAIN_HMAC_SECRET`.
- **Key ids and rotation**: `provenance` may carry `kid` and `alg` (`HS256` or `EdDSA`); without them the peer's current key is used. A call carries `issued_at` and a one-time `nonce`, and a receiver may refuse one more than 30 s from now or seen before. The Brain's public keys are at `/.well-known/jwks.json`.
- **Replay and version:** a `sequence_no` that does not increase, or a `contract_version` not accepted, is rejected with a stated reason.
- **The Brain's API:** off loopback every route needs a bearer token with a scope (`read`, `push`, `approve`, `admin`); a pushed event takes its source from the token. Sensor, type and zone ids may hold only letters, digits and `. _ : # -` (64 at most).
