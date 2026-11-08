# What the Twin Needs From the Other Teams

Everything the Twin can do alone is done.
These changes live in the other teams' folders or in shared root files, so they are theirs to make.
Each was tried on a private copy of that team's configuration, except where noted.

## Guardian

**Required.** Without these the Guardian cannot judge the Twin's sensors, and the City Brain will not act.

Add to `config/city_model.yaml`, under `zones`. The Twin's `zone-03` replaces the current hospital district of that name.

```yaml
zone-01: {type: city_block, has_water_body: false, max_water_level_m: 0.0, has_buildings: true, road_access: true, fire_possible: true, hospital: false, switchable_grid: true, max_vehicles: 60}
zone-02: {type: city_block, has_water_body: false, max_water_level_m: 0.0, has_buildings: true, road_access: true, fire_possible: true, hospital: false, switchable_grid: true, max_vehicles: 60}
zone-03: {type: streets, has_water_body: true, max_water_level_m: 1.5, has_buildings: true, road_access: true, fire_possible: true, hospital: true, switchable_grid: false, max_vehicles: 100}
# one per street: zone-dip-1-2, zone-dip-1-4, zone-dip-2-3, zone-dip-2-5, zone-dip-3-6, zone-dip-4-5, zone-dip-5-6
zone-dip-2-3: {type: street_drain, has_water_body: true, max_water_level_m: 1.5, has_buildings: false, road_access: true, fire_possible: false, hospital: false, switchable_grid: false, max_vehicles: 100}
```

Add to `config/crosschecks.yaml`, under `adjacency`:

```yaml
zone-01: [zone-02, zone-03]
zone-02: [zone-01, zone-03]
zone-03: [zone-01, zone-02, zone-dip-1-2, zone-dip-1-4, zone-dip-2-3, zone-dip-2-5, zone-dip-3-6, zone-dip-4-5, zone-dip-5-6]
zone-dip-2-3: [zone-03, zone-dip-1-2, zone-dip-1-4, zone-dip-2-5, zone-dip-3-6, zone-dip-4-5, zone-dip-5-6]   # likewise for each drain
```

Add to `config/sensor_registry.yaml`, under `sensor_types`:

```yaml
cctv_anomaly: {expected_interval_s: null, fields: {anomaly_type: {type: str}, confidence: {type: float}}, checks: [semantic]}
building_fire: {expected_interval_s: null, fields: {building_id: {type: str}, smoke_detected: {type: bool}, temp_c: {type: float}, co2_ppm: {type: float}}, checks: [semantic]}
unit_status: {expected_interval_s: null, fields: {unit_id: {type: str}, incident_id: {type: str}, state: {type: str}}, checks: [semantic]}
```

Then the Twin sends them with `GUARDIAN_EXTENDED_TYPES=cctv_anomaly,building_fire,unit_status`.

**Wanted, not tried.**

- Allow one dispatch per unit type on an incident. `no_duplicate_dispatch` blocks a second dispatch for the same incident, so an ambulance and a police car cannot both go.
- Send `X-API-Key` on calls to the Twin's `POST /tools/{action}`. The door is open today, because the Guardian's client sends no key.

## City Brain

**Required.** In `deploy/compose/partners.compose.yaml`, or a new file the root stack uses:

```yaml
twin: {adapter: mcp, url: http://twin:8001/mcp, hmac_secret_env: TWIN_HMAC_SECRET, require_signature: true}
guardian: {adapter: v1, url: http://guardian:8003, api_key_env: BRAIN_API_KEY, hmac_secret_env: GUARDIAN_HMAC_KEY, dispatcher_id: dispatch-central, gateway: true, mode: sidecar}
```

**Wanted, not tried.**

- Teach the disaster department the Twin's `set_pump_state`. It asks for a valve, which this city does not have, so nothing drains a flood.

## Root files (the whole triplet)

- `.env.example`: add `TWIN_API_KEY`, `BRAIN_API_KEY`, `OPS_API_KEY` and `GUARDIAN_HMAC_KEY`. The Guardian refuses to start without an API key, and the Twin and the City Brain must share these.
- `docker-compose.yml`: pass those to the `twin`, `guardian` and `brain` services, and `GUARDIAN_EXTENDED_TYPES` to `twin`. Add a `viewer` service for the 3D city (`build: ./twin/src/viewer`, `TWIN_URL: http://twin:8001`, `TWIN_OPERATOR_KEY`) and pass the same `TWIN_OPERATOR_KEY` to `twin`.
- `TESTBOOK.md`: it is generated from `brain/scenarios/`. Agree IDs for the Twin's four scenarios, for example T17 to T20, and a way in.
- `INTEGRATION.md`: the protocol and failure sections are still empty. [`INTEGRATION-twin.md`](INTEGRATION-twin.md) has the Twin's part.

## Not yet covered by anyone

The Guardian's Test Book scenarios T1 to T11 need the Twin to emit fake readings, replays, stuck sensors, silence, call floods and actuators with no effect.
The City Brain's T14 and T16 need `citizen_activity` readings and a crime on camera.
The Twin does none of these yet. They are the next work on the Twin's side.
