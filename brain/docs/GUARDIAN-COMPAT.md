# Working with the Guardian team's Guardian

Checked on 8 Nov 2026 against their repository (`guardian/`, contract 1.0): their Guardian and its Twin mock were built from a fresh clone and our Brain was run against them. Their Interface Card is `guardian/INTERFACE.md`; ours is `INTERFACE.md`.

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
| `air_quality` | `aqi` a decimal, `smoke` | `aqi` a whole number, `pm25_ugm3`, `pm10_ugm3` required | refused (`value_invalid`) |
| `power_meter` | `load_kw`, `capacity_kw` | `power_load` with `voltage_v` required | stored, not used (alias `power_meter: power_load` would be refused for the missing voltage) |
| `rain_gauge`, `flow_meter`, `grid_meter` | in their registry | not modelled | stored, not used |

The Twin team's own card (still the template) lists "power load" and "air quality", which are our names from the shared Data Dictionary: their Guardian is the one that departs from it.

## Still open

1. **The Twin's other endpoints.** Their Twin mock has no `/topology` or `/capabilities`, which the Brain reads at start-up, so the whole Brain service cannot yet run against it; the readings, verdicts and actuator calls above were chained piece by piece. The real Twin's endpoints are the Twin team's to say.
2. **Who pushes readings to the Guardian.** In their design the Twin pushes; our mock Twin does not, so our own mocks cannot drive their Guardian end to end.
3. **Actuator ids.** Their registry names `valve-port-12`, `grid-port`, `sig-port-01`, `dispatch-central`; ours come from the Twin's topology. The Twin has to expose the ids the Guardian knows.
4. **Dispatch details.** `mode` and `target_id` (pursuit) are sent inside `params`; whether the Twin honours them is untested.
5. **Conformance.** `brain conformance --guardian` still checks our contract, so it fails against theirs; a v1 mode is not written.
