# Test Book: the City Brain

Generated from `scenarios/` by `scripts/gen_testbook.py`; do not edit by hand. Each scenario is launched by one command (`scenarios/triggers/<id>.sh`, or the number key on the timeline screen) and leaves a log in `logs/`; a verified, repeatable log of each is in `logs/canonical/`.

## d1: A calm day

| Field | |
| --- | --- |
| ID | d1 |
| Name | A calm day |
| Layers involved | Twin, Guardian, City Brain |
| Description | Citizens walk and jog, traffic flows, and one camera raises a weak crowd-gathering alert that is not a crime. Nothing is wrong. |
| Trigger | `./scenarios/triggers/t12.sh`, or `uv run brain scenario t12` |
| Expected: Twin | Streams 6 signed readings from 4 sensors (cctv_anomaly, citizen_activity, traffic_camera); answers each actuator call. |
| Expected: Guardian | Judges every reading `trusted` by default. |
| Expected: Brain | Opens no incident and calls no actuator. Every reading is trusted and every reading is read. |
| How to verify | Timeline screen (key `1`); `logs/canonical/t12.jsonl`; Visible on the timeline screen; log logs/t12-*.jsonl; `uv run brain scenario t12`. |

Checked: dispatched units none; forbidden events ['brain.incident.opened', 'brain.action.requested', 'brain.action.blocked', 'brain.reading.rejected'].

## d2: A fake flood

| Field | |
| --- | --- |
| ID | d2 |
| Name | A fake flood |
| Layers involved | Twin, Guardian, City Brain |
| Description | The harbour gauge reads a steady 0.3 m. Then a second, compromised gauge reports 1.8 m, which would be a flood. Its readings are signed but the Guardian marks them untrusted. |
| Trigger | `./scenarios/triggers/t13.sh`, or `uv run brain scenario t13` |
| Expected: Twin | Streams 1 signed readings from 2 sensors (water_level); answers each actuator call. |
| Expected: Guardian | Judges every reading `trusted` by default except wl-01-02: `untrusted`. |
| Expected: Brain | Notices the doubtful reading and opens a flood incident, but the Safety gate refuses both the warning and the valve call: no trusted Guardian verdict stands behind them. The honest gauge then clears the incident. Nothing reaches the city. |
| How to verify | Timeline screen (key `2`); `logs/canonical/t13.jsonl`; Visible on the timeline screen; log logs/t13-*.jsonl; `uv run brain scenario t13`. |

Checked: dispatched units none; forbidden events ['brain.reading.rejected'].

## d3: A crime and a pursuit

| Field | |
| --- | --- |
| ID | d3 |
| Name | A crime and a pursuit |
| Layers involved | Twin, Guardian, City Brain |
| Description | A robbery is caught on camera in Downtown. One citizen who was at the scene runs toward the Station; a commuter keeps walking and a jogger runs on the other side of the city. All readings are trusted. |
| Trigger | `./scenarios/triggers/t14.sh`, or `uv run brain scenario t14` |
| Expected: Twin | Streams 9 signed readings from 4 sensors (cctv_anomaly, citizen_activity); answers each actuator call. |
| Expected: Guardian | Judges every reading `trusted` by default. |
| Expected: Brain | Opens a crime incident, identifies cit-88213 as the suspect (and nobody else), and dispatches one police unit in pursuit at once with a trust_ref. The department team then adds a tight perimeter (one unit each in Market and Station, keeping one in reserve) and a public alert for Downtown, citing the playbook. The incident closes when the pursuit unit reports the arrest, and the Brain recalls the two perimeter units. |
| How to verify | Timeline screen (key `3`); `logs/canonical/t14.jsonl`; Visible on the timeline screen; log logs/t14-*.jsonl; `uv run brain scenario t14`. |

Checked: dispatched units [{'unit_type': 'police', 'mode': 'pursuit', 'target_id': 'cit-88213'}]; forbidden events ['brain.action.blocked', 'brain.reading.rejected'].

## d4: A flood, an attack and a layer down

| Field | |
| --- | --- |
| ID | d4 |
| Name | A flood, an attack and a layer down |
| Layers involved | Twin, Guardian, City Brain |
| Description | A real flood is rising at the harbour. At the same time a compromised camera reports a robbery, one sensor floods the Brain with readings, and the Guardian stops answering. |
| Trigger | `./scenarios/triggers/t15.sh`, or `uv run brain scenario t15` |
| Expected: Twin | Streams 6 signed readings from 4 sensors (cctv_anomaly, emergency_call, traffic_camera, water_level); answers each actuator call. |
| Expected: Guardian | Judges every reading `trusted` by default except cam-07-02: `untrusted` and goes silent after 120 verdicts. |
| Expected: Brain | Warns the harbour from the evidence it holds, but holds the valve call: only one trusted source vouches for the flood. Tracks the forged robbery report without sending police. When the Guardian goes quiet it says so once and keeps going in degraded mode, with low-impact alerts only. |
| How to verify | Timeline screen (key `4`); `logs/canonical/t15.jsonl`; Visible on the timeline screen; log logs/t15-*.jsonl; `uv run brain scenario t15`. |

## Which scenario covers which interaction

| Interaction (Phase 1) | Scenarios |
| --- | --- |
| Twin to Brain: a calm day, a crime and a pursuit | d1, d3 |
| Twin to Guardian: a fake reading the Guardian does not trust | d2 |
| Brain to Guardian: every call carries a trusted verdict, or is held | d2, d3 |
| All three: an attack, a flood and a layer down at once | d4 |
