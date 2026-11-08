# Integration

How the three layers connect, and how the teams worked together (R4).

## How the layers connect

```
              signed readings, contract 1.0 (POST /v1/readings)
   Twin  ------------------------------------------------------>  Guardian
   ^  ^ \                                                        ^   |
   |  |  \ readings, contract 2026-09-17 (MCP list_readings        |   | verdict by sensor and sequence number
   |  |   \ or GET /readings)                                      |   v
   |  |    '------------------------------------------------->  City Brain
   |  |                                                            |
   |  |  audited actions and containment (POST /tools/{action})    | audited actions (POST /v1/actuator-calls)
   |  '------------------------- Guardian <------------------------'
   |
   '-- broadcast and recall, signed (MCP tool or POST /actuators/{action}) -- City Brain
```

- **Protocol:** MCP or plain HTTP with JSON. See [`../INTERFACE.md`](../INTERFACE.md) for every message.
- **Contracts:** the City Brain reads `2026-09-17`, the Guardian `1.0`. The Twin renders one canonical reading in both, with the same sensor id and sequence number, because the Brain asks for a verdict by that pair.
- **Trust:** readings are signed for each partner. The City Brain's calls are signed and carry the Guardian verdict they rely on (`trust_ref`).
- **Configuration:** partner addresses and keys come from the environment, never from code. See [`../.env.example`](../.env.example).
- **Timeline:** the Twin pushes its events to the City Brain's timeline (`POST /api/events`).

## One scenario, end to end (pedestrian hit)

1. A car hits a pedestrian. The Twin's engine knows; no other layer does.
2. The camera flags a collision and a witness calls. Both leave the Twin as signed readings, pushed to the Guardian and pulled by the City Brain.
3. The City Brain asks the Guardian for a verdict on each. Both are trusted, so two independent sources stand behind the accident it opens.
4. The City Brain sends `dispatch_unit` to the Guardian with the verdict as `trust_ref`. The Guardian audits it and forwards it to the Twin (`POST /tools/dispatch_unit`), naming the hospital as the station.
5. The Twin links the Brain's incident number to its own and sends the ambulance, which reports `en_route`, `on_scene` and `returning` as `unit_status` readings carrying the Brain's incident number.
6. On `returning`, the City Brain closes the incident.

## Status

The chain has run with all three real layers as local processes (not yet through the root `docker-compose.yml`), with a Guardian configuration that knows the Twin's zones and sensor types.

## To be filled in by the triplet

The sections below need real facts from the three teams.

### Coordination
Tools and sync schedule: to be filled in.

### A partner failure or change, and how it was handled
To be filled in.
What the Twin does when a partner is down: it keeps simulating, logs `delivery_failed`, and shows the layer as not reachable on the timeline.

### Proof of a joint run
To be filled in: the date, the commit of each layer, and the log file in `logs/`.
