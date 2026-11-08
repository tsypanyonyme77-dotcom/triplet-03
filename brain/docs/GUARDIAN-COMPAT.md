# Working with the Guardian team's Guardian

Checked on 8 Nov 2026 against their repository (`guardian/`, contract 1.0): their Guardian and its Twin mock were built from a fresh clone and our Brain was run against them. Their Interface Card is `guardian/INTERFACE.md`; ours is `INTERFACE.md`.

## Where the Guardian sits

Checked against both codebases on 8 Nov: the Guardian receives every reading from the Twin (`POST /v1/readings`, pushed, or pulled) and judges it, but it **forwards none to the Brain**. The Brain reads the Twin directly and asks the Guardian for a verdict by sensor and sequence number. Valve, grid, signal and dispatch calls go through the Guardian (`POST /v1/actuator-calls`) to the Twin; broadcast and recall go to the Twin directly. The Guardian's alert feed (`WS /v1/ws/verdicts`, `GET /v1/alerts`) is not read by the Brain. All of it is drawn in [Figure 9](diagrams/print/fig9-guardian-wiring.svg) and explained in [HOW-IT-WORKS.md](HOW-IT-WORKS.md#where-the-guardian-sits).

## What was incompatible, and where it is handled

The two contracts differ in versions, endpoints, login, verdict fields, status names and in who sends the actuator calls. None of it is changed in the Brain's logic: it is one adapter, chosen by `guardian.adapter: v1`.

| | Our contract | Theirs (1.0) | Handled by |
| --- | --- | --- | --- |
| Verdict | `POST /verdicts` with the reading | `POST /v1/verdicts/request` with `{sensor_id, sequence_no}`; the Twin pushes the reading to `/v1/readings` | `GuardianV1Adapter.get_verdict`, which asks again while the Guardian says `unknown` (the reading may not have arrived) |
| Verdict fields | `confidence`, `issued_at`, `suspicious` | `trust_score`, `ts`, `suspect`, plus `layer_results`, `threat_level`, `action_taken` | `to_verdict`; the extras stay on the verdict |
| Verdict signature | none | HMAC-SHA256 with `GUARDIAN_HMAC_KEY` | checked by the adapter; a bad signature is no verdict. Our code reproduces the signature printed in their card |
| Login | Bearer token | `X-API-Key` (`BRAIN_API_KEY`) | the adapter |
| Quarantine | `GET /quarantine/{id}` | `GET /v1/containment` | `is_quarantined` |
| Actuator calls | the Gate calls the Twin | every audited call goes through `POST /v1/actuator-calls`, which checks the trust reference and the effect | `GuardianGateway`: valve, grid, signal and dispatch go through the Guardian; broadcast and recall (which it does not know) go to the Twin |
| Names | `set_grid_connection`, `set_signal_phase` | `set_grid_state`, `set_signal` | `to_guardian_call` |

## Use it

```yaml
guardian:
  adapter: v1
  url: http://guardian:8003
  dispatcher_id: dispatch-central     # their registry has one dispatcher; ours has one per station (the station is named in params.station_id)
```

with `BRAIN_API_KEY` and `GUARDIAN_HMAC_KEY` set to the values the Guardian team gives us. If the signing key is named but not set the Brain stops at start-up rather than trust unsigned verdicts.

## What ran against their live Guardian

Verdicts verified and parsed; the quarantine check; a valve, grid and signal call forwarded to their Twin mock; a dispatch through `dispatch-central` (a unit came back); and refusals with their reasons for an unknown and a missing trust reference. `tests/test_guardian_v1.py` holds the same cases offline, using payloads from their card.

## The Twin's readings: `twin.dialect: guardian-v1`

Their Twin sends `sensor_type`, a signed `hmac`, contract `1.0` and `sequence_reset`; ours reads `type` and `provenance`. With `twin.dialect: guardian-v1` the Brain reads theirs: it checks the `hmac` as they document it (with the Twin secret, `TWIN_HMAC_SECRET`), accepts `1.0`, turns `sensor_type` into `type`, believes a counter reset only when the reading is newer than the last one seen, and maps their emergency incident types onto our categories (the caller id is dropped). The signature check is proved on a reading their Twin mock really sent and on the example in their card.

Chained for real: 60 readings from their Twin mock, 50 accepted (signatures verified), and their Guardian's verdict on each of the 50 came back `trusted` and parsed.

The 10 that were refused, and the readings the Brain cannot use yet, are differences in the sensor values, which the Data Dictionary has to settle:

| Sensor | Theirs | Ours | Effect |
| --- | --- | --- | --- |
| `air_quality` | `aqi` a decimal, `smoke` | `aqi` 0..500 (a decimal is accepted), `pm25_ugm3` and `pm10_ugm3` optional | **fixed 8 Nov**: accepted; `smoke` is dropped (a smoke source is not wired) |
| `power_meter` | `load_kw`, `capacity_kw` | `power_load`, `voltage_v` optional | **fixed 8 Nov**: `twin.type_aliases: {power_meter: power_load}` in `partners.guardian-v1.yaml` |
| `rain_gauge`, `flow_meter`, `grid_meter` | in their registry | not modelled | stored, not used |

The Twin team's own card (still the template) lists "power load" and "air quality", which are our names from the shared Data Dictionary: their Guardian is the one that departs from it.

## Run it against the real Guardian (Compose)

```bash
make guardian-up     # builds the Guardian from ../guardian and the Brain image, starts six containers, waits for health (about a minute once built)
make guardian-down   # stops them; the volumes stay
```

`docker-compose.guardian.yml` is a separate stack (project `city-brain-guardian`, its own volumes and host ports); the mock stack in `docker-compose.yml` is untouched, and the two can run side by side. The Brain runs `serve --live` with `deploy/compose/partners.guardian-v1.yaml`, so it really connects to its partners (plain `serve` uses in-process mocks).

| Service | What it is | Host port (loopback) |
| --- | --- | --- |
| `guardian` | the Guardian team's Guardian, listening on 8003 as in the root compose; `/timeline` is its screen | 8103 |
| `twin` | their Twin mock: signed 1.0 readings pushed to the Guardian, `POST /inject/{kind}` to start an incident | 8111 |
| `twin-bridge` | `mocks/guardian_twin`: their Twin mock as the Brain's Twin (below) | none |
| `brain` | the Brain, `guardian.adapter: v1`, `twin.dialect: guardian-v1`, gateway on; the screen | 8081 |
| `neo4j`, `qdrant` | the Brain's two stores | 7475, 7688 (Neo4j) |

**Why a bridge.** Their Twin mock cannot be read by the Brain as it is: it has no `/topology` or `/capabilities`, calls its cursor `cursor` and sends no stream id, and it does not know `broadcast_alert` or `recall_unit`. `mocks/guardian_twin` fills exactly those gaps. The readings pass through untouched, so the Guardian's signature still checks. The topology is built from the Guardian's own `city_model.yaml`, `crosschecks.yaml` and `policies.yaml` (mounted read-only) and the sensors seen on the stream. The Twin team's real Twin replaces both `twin` and `twin-bridge` when it exists: set `twin.url`.

**Secrets.** `TWIN_HMAC_SECRET` is the one Twin key (the Guardian reads it as `TWIN_HMAC_KEY` too); `GUARDIAN_HMAC_KEY` signs verdicts; `BRAIN_API_KEY` is the Brain's login on the Guardian. Dev values are the defaults; set real ones in `.env`.

**What was run (8 Nov 2026), all against the real Guardian.** Every reading reached the Brain and the Guardian, and each got a verdict (247 readings, 247 verdicts in the first minute). `POST /inject/fake_flood` on their Twin: the Guardian called the reading `suspicious`, the Brain opened an incident and the gate refused the alert and the valve call (`no Guardian verdict referenced`). A real flood: once the Guardian trusted it the Brain sent `broadcast_alert` with a `trust_ref` and the Twin answered `broadcast`; the valve call stayed held (two independent trusted sources and a person's approval are needed). A restarted Twin: the Brain reported `brain.degraded`, noticed the new stream and discarded its saved state. `tests/test_guardian_stack.py` keeps the bridge, the config and the file honest.

**What this does not show.** A valve, grid, signal or dispatch call going through `POST /v1/actuator-calls` in this stack (the first two are held for approval; their Twin mock emits no crime readings, so no dispatch). Those paths were run piece by piece earlier (above) and are tested with their payloads. Air quality and the power meter were refused in that first run (47 readings in a minute); they are accepted now (table above), by making the fields the Brain never decides on optional. Units dispatched through the Guardian never report `unit_status`, so a fire or ambulance incident would not close by itself here.

## Still open

1. **The Twin's other endpoints.** Their Twin mock has no `/topology` or `/capabilities`, which the Brain reads at start-up; `mocks/guardian_twin` stands in for them (above). The real Twin must offer them, or the Brain's MCP tools. The real Twin's endpoints are the Twin team's to say.
2. **Who pushes readings to the Guardian.** In their design the Twin pushes; our mock Twin does not, so our own mocks cannot drive their Guardian. The Compose stack above uses their Twin mock, which does.
3. **Actuator ids.** Their registry names `valve-port-12`, `grid-port`, `sig-port-01`, `dispatch-central`; ours come from the Twin's topology. The Twin has to expose the ids the Guardian knows.
4. **Dispatch details.** `mode` and `target_id` (pursuit) are sent inside `params`; whether the Twin honours them is untested.
5. **Conformance.** `brain conformance --guardian` still checks our contract, so it fails against theirs; a v1 mode is not written.
