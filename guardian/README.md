# Guardian

The Guardian is the trust layer of the TSYP14 *City Brain Convergence* triplet. It sits between the city **Twin**
(sensors, actuators) and the **City Brain** (decisions) and answers one question: **"Is this data telling the
truth?"** Each sensor reading passes six layers of evidence: authenticity, freshness, range/unit, semantic
plausibility, dynamics, corroboration and liveness. The result is a signed verdict
(`trusted | suspect | untrusted | unknown`) with a score and the reasons. Actuator calls from the Brain go through the
Guardian, which checks their `trust_ref` and safety policies and then verifies the physical effect with independent
sensors. A threat correlator spots attack patterns across readings (replay, coordinated spoofing, call floods,
command injection, compromised Twin…) and raises zone threat levels. Containment isolates sensors, quarantines devices
and callers, rolls back to the last-known-good value, and releases with hysteresis. Every step is written to a JSONL
audit log (R2) and streamed to a timeline WebSocket (R3).

```
                     TWIN (partner)                            BRAIN (partner)
            sensors │ actuators ▲                      verdict req │ ▲ verdict + alerts
                    ▼           │ containment calls               ▼ │ actuator calls
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ ADAPTERS (only code that knows partner formats)                              │
   │ twin_client (REST/MCP/MQTT) │ brain_api (REST/WS) │ schemas (Pydantic)       │
   └───────────────┬──────────────────────────────┬───────────────────────────────┘
                   ▼                              ▼
          ┌─────────────────┐            ┌────────────────────┐
          │ INGEST          │            │ B. ACTUATOR WATCH  │
          │ validate,       │            │ call auditor +     │
          │ normalize       │            │ effect verifier    │
          └───────┬─────────┘            └─────────┬──────────┘
                  ▼                                │
          ┌─────────────────────┐                  │
          │ A. DETECTION 1 → 6  │◄── STATE STORE ──┤ (history, baselines,
          └───────┬─────────────┘    + config      │  last-known-good)
                  ▼                                │
          ┌─────────────────────┐                  │
          │ VERDICT ENGINE      │──────────────────┤
          │ score + reasons     │                  │
          └───────┬─────────────┘                  │
                  ▼                                ▼
          ┌──────────────────────────────────────────────┐
          │ C. THREAT CORRELATION → threat level, alerts │
          └──────────────────────┬───────────────────────┘
                                 ▼
          ┌──────────────────────────────────────────────┐
          │ D. CONTAINMENT (isolate / quarantine / roll) │
          └──────────────────────┬───────────────────────┘
                                 ▼
          ┌──────────────────────────────────────────────┐
          │ AUDIT: JSONL logs (R2) + timeline events (R3)│
          └──────────────────────────────────────────────┘
```

The wire contract (messages, HMAC rules, auth, fail-safe rule) is in **[INTERFACE.md](INTERFACE.md)**.

## Quick start (Guardian alone, with mocks)

```bash
cd guardian
make install          # venv + deps + .env from .env.example
make test             # unit, integration, fuzzing and the 11 Test Book scenarios (in-process, FakeClock)
make demo             # starts guardian :8100, twin mock :8101, brain mock :8102, runs scenario T1, stops
```

Or with Docker:

```bash
make env && docker compose up --build    # guardian + twin_mock + brain_mock
curl localhost:8100/health
python -m scenarios.run T1               # in another shell (export the .env keys first, e.g. `set -a; . ./.env`)
```

OpenAPI docs: <http://localhost:8100/docs>. Live timeline screen (R3): <http://localhost:8100/timeline> —
a dependency-free HTML page that subscribes to `WS /v1/ws/timeline` and shows reading → verdict → decision →
action as they happen. Paste an API key (or open `/timeline?api_key=<key>`); filter by sensor/actuator/zone to
follow one chain of cause and effect.

## Test Book scenarios

Each scenario has an in-process test (`tests/scenarios/test_tXX_*.py`, simulated time, asserts the API outcome
**and** the ordered audit events) and a live trigger against the running stack that writes
`logs/t5-scenario-TX-<ts>.log`:

```bash
make scenario T=T1        # or: python -m scenarios.run T1 | all
```

The physics-heavy scenario **T11** (a real flood that rises over minutes) is slow at real time. Start the twin
mock with `TWIN_SPEED=8` (env, `.env`, or `TWIN_SPEED=8 docker compose up`) to speed the simulated physics —
not the timestamps — so T11 finishes in ~80 s. Run scenarios one at a time (or leave a short gap); back to back,
a raised zone threat level from one scenario can still be decaying when the next starts.

| ID | Scenario | Guardian behaviour |
|---|---|---|
| T1 | Fake flood at the port (1.80 m vs 0.40 m, no rain) | `untrusted` (rate_of_change + no corroboration) within 10 s, sensor isolated, rollback serves 0.40 m, Brain does not move the valve |
| T2 | Stuck / dead sensor | flatline → `suspect`; silence → stale → `unknown` |
| T3 | Replayed readings | repeated `sequence_no` with valid HMAC → `untrusted` `replay`; `sequence_reset` accepted |
| T4 | Emergency-call flood | > 5 calls/zone/min → `call_flood`, `suspect`, throttled, none dropped; duplicate `call_id` → `untrusted` |
| T5 | Valve closed, no effect | `actuator_failure` alert ("use a backup"); untrusted flow sensor → `unknown` instead |
| T6 | Brain uses a quarantined device | blocked `device_quarantined` |
| T7 | Twin goes silent | every sensor `unknown`, `/health` degraded |
| T8 | Fire in the open sea | `untrusted` (`impossible_location`), dispatch blocked |
| T9 | Coordinated spoofing in a zone | zone `under_attack`, trusted needs ≥ 0.9 and 2 sources, hysteresis back to normal |
| T10 | Command injection without `trust_ref` | blocked, caller quarantined after 3, `command_injection` alert |
| T11 | Real flood + attack elsewhere | corroborated flood `trusted`, valve call forwarded and verified, fake alarm `untrusted` |

Attacks can also be injected by hand: `python -m mocks.twin_mock inject fake_flood sensor_id=wl-port-03`
(`spike`, `stuck`, `replay`, `bad_hmac`, `call_flood`, `duplicate_call`, `silence`, `fire_in_sea`, `coordinated`,
`valve_stuck`, `slow_drift`, `real_flood`, `sequence_reset`, `call`, `clear`).

## Configuration

Everything partner- or tuning-specific is in `config/` (validated at startup; a bad file stops the service with the
file and field named) and secrets are in `.env`:

| File | Contents |
|---|---|
| `guardian.yaml` | partner URLs, transport (`rest/mcp/mqtt`), mode (`push/pull`), timeouts, log dir, verdict TTL, ML switch |
| `sensor_registry.yaml` | per sensor type: value fields, types, units, expected interval, which checks apply |
| `thresholds.yaml` | ranges, rate-of-change limits, flatline N, z-score, baseline, call flood, notable-event conditions, scoring weights and cut-offs |
| `crosschecks.yaml` | which sensors corroborate which, zone adjacency, window, minimum sources |
| `city_model.yaml` | zones and their features (water body, buildings, `fire_possible`, hospital, …) |
| `policies.yaml` | actuator registry + independent verify sensors, expected effects (tiny DSL), safety invariants, rate limits, containment caps |
| `attack_patterns.yaml` | threat signatures, windows, thresholds, threat-level hysteresis |
| `baselines/` | exported hour-of-day baseline snapshots (gitignored) |

### Pointing at a real Twin / Brain

Change `config/guardian.yaml` (`twin.base_url`, `twin.transport`, `twin.mode`) or the matching `.env` overrides
(`TWIN_BASE_URL`, `TWIN_TRANSPORT`, `TWIN_MODE`), and put the agreed keys in `.env`. Nothing else changes: only
`src/guardian/adapters/` knows partner formats. Install `.[mcp]` or `.[mqtt]` for those transports. Set
`LOG_DIR=../logs` to write into the triplet's root `logs/`.

## Scoring in one paragraph

L1 (schema, `contract_version`, HMAC) and L2 (sequence, ±30 s skew) are hard gates: failing either gives
`untrusted`. Otherwise the score starts at 1.0, with penalties applied once per layer: plausibility −0.5, semantic
−0.3, dynamics −0.3, liveness −0.3, failed corroboration −0.5, passed corroboration +0.2. The result is clamped to
[0, 1]. Some findings cap the verdict at `suspect`: a semantic issue, a call flood, a flatline, a dynamics failure that
corroboration did not confirm, or fewer than 2 independent sources. A physically impossible event is `untrusted`.
When a zone is `elevated` or `under_attack`, `trusted` needs ≥ 0.9 **and** 2 agreeing sources. Pattern/ML findings
can only lower trust. All weights are in `thresholds.yaml`.

Every API error uses one model:

```json
{
  "error": "contract_version_mismatch",
  "message": "contract_version '2.0' is not supported; this Guardian speaks '1.0'",
  "field": "contract_version"
}
```

## Repository layout

```
config/            YAML config (see above)
src/guardian/      adapters/ ingest/ detectors/ trust/ actuator_watch/ threat/ containment/ audit/
mocks/             twin_mock (city sim, physics, injector, tools), brain_mock, common signing
scenarios/run.py   live scenario triggers → logs/t5-scenario-*.log
tests/             unit/ integration/ scenarios/ fixtures/ (fixtures are embedded in INTERFACE.md)
```

## Design decisions and deviations from the design PDF

- **Corroboration sources.** The PDF says only *currently trusted* sources count. Applied literally, this deadlocks
  real events: rain rises before flow, which rises before level, so each sensor waits for the others to be trusted
  and all stay `suspect`. A source therefore counts when it is not contained, not stale, not `untrusted`, and
  *self-consistent*: no range, semantic, rate-of-change, flatline or drift failure. Merely unusual values (z-score,
  baseline) still count, because real events are unusual. A spoofed sensor that jumps is still excluded.
- **Actuator-explained changes.** While the Guardian is verifying an order it forwarded (e.g. valve closed), the
  verify sensor's sudden change is *explained*. Rate and z-score alarms on that sensor are suppressed, and weather
  corroboration is skipped, so a correct valve closure does not get its own flow meter isolated. The suppression is
  bounded by the expectation window.
- **Physical coupling (level above zone maximum)** is in L3b (needs the city model). L3a checks the sensor's
  absolute range (0–10 m) and the unit heuristic (a value an order of magnitude over range that fits after ÷100).
- **Schema errors vs verdicts.** Unparseable input gets a 4xx error, because there is no reading to judge. A
  well-formed reading with a bad HMAC gets an `untrusted` verdict.
- **Containment-forced `untrusted`** (isolated sensor) does not count as a new attack signal. The correlator looks at
  the detection result, so threat levels can decay while a sensor stays isolated.
- **Extra endpoint** `POST /v1/containment/quarantine` (ops key only), so operators and the T6 scenario can
  quarantine by hand.
- **Slow drift** counts only *sub-threshold*, same-sign deviations; a large deviation is an event and resets the
  window.
- **Containment outranks staleness in a verdict request.** A sensor we are actively watching and have isolated or
  quarantined is reported `untrusted` even if its stream briefly pauses (e.g. right at the 2× stale boundary), so
  the Brain gets the precise "we contained this" signal instead of a less specific `unknown`. A sensor never heard
  from since a restart (`last_seen` is None) still falls through to the `unknown` fail-safe.
- **Effect verification works in a raised-threat zone.** A verify sensor's reading counts as independent evidence of
  a physical effect when it is `trusted`, or `suspect` *only because of threat-level tightening while self-consistent*.
  Corroboration is skipped for a sensor whose change we explained with our own in-flight order, so under `elevated`/
  `under_attack` it would otherwise be capped to `suspect` and the actuator could never be checked — exactly when it
  matters most. An `untrusted`/`unknown` verify sensor still yields `unknown` and does not accuse the actuator.

## Known limitations

- **Compromised Twin.** If the Twin itself lies, HMAC does not help. Corroboration across independent sensors is the
  defence, and it gets weaker as more sensors are spoofed together. City-wide corroboration collapse raises
  `compromised_twin` (safe mode) but cannot say which value is true.
- **Two independent trusted sources** are needed to reach `trusted` for notable readings. An isolated sensor, or one
  with no corroboration path (grid meters under a raised threat level), can only be `suspect`.
- **Thresholds trade false alarms against missed attacks.** Every decision is logged with its reasons so they can
  be tuned during integration. The defaults suit the mock city.
- **HMAC proves origin, not truth.** A compromised sensor signs lies perfectly, which is why layers 3–6 exist.
- **Real events can look like attacks.** A burst pipe or a disaster produces abrupt changes and many calls. We
  throttle and corroborate rather than drop.
- **Incomplete city model.** A wrong zone map causes false semantic alarms, so those are `suspect` unless physically
  impossible.
- **Baselines** learn online from trusted readings only and need ≥ 200 samples per hour bucket. A recorded
  normal day from the Twin team would make them useful sooner. An attack that starts before the baseline exists is
  caught only by the other layers.
- **ML** (Isolation Forest, `ml.enabled: false`) can only lower trust and stays off the critical path.
- **Defence can be abused.** Isolation caps per zone, release after clean readings with a growing cooldown, and the
  manual release endpoint stop an attacker from using our quarantine against healthy sensors. Quarantining a caller
  after repeated bad calls is still a lever an attacker with a stolen Brain key could pull.
- **Guardian outage.** The Brain must treat data as `unknown` when the Guardian is down (INTERFACE.md §6).
- **Effect windows** are fixed per action. Slow actuators need their `within_s` tuned.
- **Single process.** State lives in memory plus SQLite. Running several replicas would need shared state.
