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

## Still open (not the Guardian adapter)

1. **The Twin's readings.** Their Twin mock sends `sensor_type` (we read `type`), signs with an `hmac` field (we read `provenance`), uses contract `1.0` (we accept `2026-09-17`), and has sensors we do not model (`rain_gauge`, `flow_meter`, `grid_meter`, `power_meter` for our `power_load`). Our Brain cannot read their Twin's stream as it stands. The Twin team's real contract decides which side moves.
2. **Who pushes readings to the Guardian.** In their design the Twin pushes; our mock Twin does not, so our own mocks cannot drive their Guardian end to end.
3. **Actuator ids.** Their registry names `valve-port-12`, `grid-port`, `sig-port-01`, `dispatch-central`; ours come from the Twin's topology. The Twin has to expose the ids the Guardian knows.
4. **Dispatch details.** `mode` and `target_id` (pursuit) are sent inside `params`; whether the Twin honours them is untested.
5. **Conformance.** `brain conformance --guardian` still checks our contract, so it fails against theirs; a v1 mode is not written.
