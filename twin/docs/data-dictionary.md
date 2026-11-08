# Sensors & Actuators Data Dictionary (shared contract draft)

Source PDF: `reference/sensors-actuators-data-dictionary.pdf` (8 pages). Written by the **Guardian** team as a **proposal for triplet negotiation, not a settled standard**. It is what the Twin is expected to emit and accept, so it is our main interface reference. `contract_version` in the draft: `"2026-09-17"`.
When the other teams send their own docs, record differences here and in `partner-docs.md`.

## 1. Common envelope
**Sensor reading** (type-specific data goes in `value`):
| Field | Type | Example | Notes |
|---|---|---|---|
| contract_version | string (date) | "2026-09-17" | versioned from day one |
| sensor_id | string | "wl-port-03" | stable unique id |
| type | enum | "water_level" | see sections 2 and 3 |
| zone_id | string | "zone-07" | city zone |
| timestamp | ISO-8601 UTC, ms | "2026-11-02T14:03:21Z" | |
| sequence_no | integer | 4821 | monotonic **per sensor**, replay detection |
| value | object | | type-specific |
| provenance | object | {"signed_by":"twin","hmac":"..."} | HMAC over the payload, signed by Twin |

**Actuator call** (what we receive):
| Field | Type | Example | Notes |
|---|---|---|---|
| contract_version | string | "2026-09-17" | |
| actuator_id | string | "valve-port-12" | |
| action | enum | "set_valve_state" | see sections 4 and 5 |
| params | object | | action-specific |
| requesting_layer | enum | "city_brain" | `city_brain` or `guardian` |
| justification | string | "flood threshold exceeded, zone-07" | goes to our audit log |
| trust_ref | string or null | "verdict-88213" | Guardian verdict relied on; null only for Guardian's own containment calls |

## 2. Required sensors (named in the challenge brief)
| Sensor (`type`) | `value` fields |
|---|---|
| Traffic camera | congestion_score float 0-1; vehicle_count int per interval; avg_speed_kmh float; smoke_detected bool |
| Water-level | level_m float (metres); flow_rate_m3s float optional |
| Power-load meter | load_kw; capacity_kw; voltage_v (float) |
| Air-quality monitor | aqi int 0-500; pm25_ugm3 float; pm10_ugm3 float |
| Emergency-call feed | call_id string; category enum fire/medical/police/flood/other; caller_confidence float 0-1 optional |

## 3. Extended sensors (predicted; phase 1 scope undecided)
- **Mobility:** inductive loop/speed (speed_kmh, vehicle_class); parking occupancy (occupied, spot_id); transit tracker (route_id, occupancy_pct, delay_min); pedestrian counter (count_5min).
- **Utilities:** grid frequency/voltage (frequency_hz, voltage_v); renewable generation (output_kw, capacity_kw); gas leak (concentration_ppm, threshold_breach); smart building water meter (consumption_l).
- **Environmental:** rainfall (mm_per_hr); soil moisture (moisture_pct); noise (db_level); temperature/humidity (temp_c, humidity_pct); UV (uv_index).
- **Public safety:** building fire/smoke (smoke_detected, temp_c); structural health (vibration_mms, tilt_deg); CCTV anomaly (anomaly_type, confidence); gunshot detection (detected, confidence).
- **Waste and services:** smart bin (fill_pct, bin_id); streetlight status (brightness_pct, fault); manhole/sewer (blockage_detected, level_cm).

## 4. Required actuators (we must implement)
| Action | params | Result |
|---|---|---|
| `dispatch_unit` (police/ambulance/fire) | unit_type police\|ambulance\|fire, zone_id, incident_id | status dispatched\|rejected\|duplicate, eta_minutes, unit_id |
| `set_signal_phase` | intersection_id, phase green\|red\|yellow\|flashing, duration_s | status, reverts_at |
| `set_valve_state` | valve_id, state open\|closed, flow_target_pct optional | status, current_state |
| `set_grid_connection` | zone_id, state connected\|disconnected | status, affected_load_kw |
| `quarantine_device` / `isolate_sensor` / `clear_quarantine` | device_id, reason | status, quarantined_until or cleared |

Quarantine/isolate is normally requested by `guardian`, with `trust_ref` possibly null (Guardian self-authorizes containment). `dispatch_unit` has a `duplicate` result: **actuator calls need idempotency**.

## 5. Extended actuators (predicted)
set_sign_message (sign_id, message_text); set_barrier_state (barrier_id, open|closed); reroute_transit (route_id, new_path); set_streetlight (light_id, brightness_pct, on); set_charging_station (station_id, enabled, max_kw); set_pump_state (pump_id, on|off, flow_target); set_floodgate (gate_id, position_pct); dispatch_collection (bin_ids[], route); broadcast_alert (message, channel sms|siren|app, zone_id); set_network_access (client_id, revoke|restore).

## 6. Zones
Every sensor and actuator belongs to a `zone_id` string (e.g. `zone-07`), not raw GPS. Number and shape of zones (grid, named districts, or road graph) is **a Twin-side decision**. Contract only needs `zone_id` to be stable and resolvable by every layer without hard-coded geometry. **Twin must expose a zone list/topology endpoint (zone ids, adjacency).**

## 7. How the Guardian will check our data (design our sensors to survive this)
| Sensor | Check | Starting threshold |
|---|---|---|
| Traffic camera | rate of change, cross-check vs speed sensor | congestion_score jump > 0.5 in < 5 s |
| Water-level | rate of change, cross-check vs rainfall sensor | rise > 0.2 m per 5 s with no matching rainfall |
| Power-load | rate of change, capacity ceiling | load_kw > capacity_kw, or jump > 30% per tick |
| Air-quality | cross-check vs camera smoke flag | AQI spike without smoke_detected |
| Emergency calls | arrival-rate limit, duplicate detection | > 5 calls/zone/minute, or call_id reused |
| All | sequence_no monotonic, HMAC provenance | any non-increasing sequence_no or HMAC mismatch |
| All | heartbeat | no reading within 2x expected interval |

Implications for the Twin: honest sensors must be mutually consistent (rainfall vs water level, smoke vs AQI, speed vs congestion), emit at a regular interval, and keep sequence numbers strictly increasing per sensor.

## 8. Open items to negotiate with the other teams
1. Zone/grid granularity; road graph or flat zones.
2. Confirm field names and units before freezing `contract_version`.
3. Whether extended sensors/actuators are in the Phase 1 demo or Phase 2 stretch.
4. Emergency-call location: `zone_id` only, or plus approximate coordinates.

## Twin-side questions this raises (ours to decide)
- HMAC key management and what exactly is signed (canonical JSON of the payload without `provenance`).
- How the existing POC (OSM road graph of Avenue Habib Bourguiba) maps to zones.
- Ground-truth vs reported value: keep true state internally, emit possibly-falsified readings (needed for scenarios like T5).

## Proposed extensions implemented by the Twin (need partner agreement)
See `twin/INTERFACE.md` for examples.
- **Envelope field `department`** (e.g. `police`, `fire`, `medical`) on readings. Zones list `facilities` by department code (`GET /zones`).
- **Auth/trust rules enforced by the Twin:** one `X-Api-Key` per layer on actuator calls; `city_brain` calls without `trust_ref` are refused (403).
- **Incident sensors from the two-blocks engine (2026-11-04):** `emergency_call` readings add `incident_id` (the Twin's call centre merges calls about one place), `location{x,y}` (approximate, what the caller said; our answer to open item 4), `reporter_kind` and `sim_time_s` to the draft's `call_id`, `category`, `caller_confidence`. `traffic_camera` uses the draft fields. `cctv_anomaly` uses `anomaly_type` (`collision`, `stopped_vehicle`) and `confidence`, plus `anomaly_id`, `location`, `since_sim_s`. Zones of the two-block map: `zone-01`, `zone-02` (the blocks), `zone-03` (streets and stations).
- **Actuators for incidents (2026-11-05):** `dispatch_unit` as drafted (`unit_type`, `incident_id`, `zone_id`; result `dispatched | duplicate | rejected`, `unit_id`, `eta_minutes`). `quarantine_device`, `isolate_sensor` and `clear_quarantine` as drafted, Guardian only (2026-11-08). `set_barrier_state` takes a street (`road_id`, "u-v") or an `incident_id` instead of a `barrier_id`, `state: closed | open`; result `closed | opened | duplicate | rejected` with `barrier_ids`. Optional `idempotency_key` on every actuator call (a retry returns the first answer, `replayed: true`). `GET /actuators` is the catalog, with JSON Schemas of params and results.
- **Fires (2026-11-08):** the draft's extended `building fire/smoke` sensor is implemented as type `building_fire`, with sensor id `fire-<building id>`, department `fire` and the draft's `smoke_detected` and `temp_c`, plus `co2_ppm`, `building_id`, `incident_id` (the Twin's call centre, so the reading can be dispatched to), `location{x,y}` and `sim_time_s`. It sends only while a building has smoke, then once with `smoke_detected: false`. `air_quality` is sent per zone (`aq-<zone>`) with the draft's `aqi`, `pm25_ugm3` and `pm10_ugm3`, and `traffic_camera.smoke_detected` is true within 60 m of a burning building, so the Guardian's smoke against AQI cross-check (section 7) holds. `emergency_call` uses category `fire` for witnesses of a burning building. Fires start through the Twin's fire simulator (`POST /simulators/ignite_fire`, operator key), which is not for the other layers.
- **Flood sensors and the pump (2026-11-08):** `rainfall` (`mm_per_hr`, extended) and `water_level` (`level_m` and `flow_rate_m3s` as drafted, plus `pump_id`, `pump_on`, `location`), both `department: water`, every emit tick. `set_pump_state` takes `state: on | off` and a `pump_id` or an `incident_id`, without the draft's `flow_target`; the result is `on | off | duplicate | rejected` with `capacity_m3s`. Emergency calls about a car stalled in water use category `flood`.
- **A rain gauge per street (2026-11-08):** rain can fall on one street only, so each street has its own gauge (`rain-dip-<u>-<v>`) next to its water level (`wl-dip-<u>-<v>`), and the Guardian can check each level against its own street's rain.
- **HMAC definition:** SHA-256 over canonical JSON of the reading without `provenance` (sorted keys, `,` `:` separators, UTF-8).
