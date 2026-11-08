# Integration

How the three layers connect, and how the teams worked together (R4).

## How the layers connect

```
              signed readings (POST /ingest)
   Twin  ------------------------------------>  Guardian
    ^                                              |
    |                                              | readings with a verdict
    |  actuator calls (POST /actuators/call)       v
    +------------------------------------------  City Brain
       (the Guardian also calls: quarantine)
```

- **Protocol:** HTTP with JSON. Live streams are server-sent events.
- **Contract:** the Guardian team's draft data dictionary, version `2026-09-17`, with the extensions marked as proposed in [`twin/INTERFACE.md`](twin/INTERFACE.md).
- **Trust:** each reading carries a per-sensor sequence number and an HMAC. Each City Brain actuator call names the Guardian verdict it relies on (`trust_ref`).
- **Configuration:** partner addresses and keys come from the environment, never from code. See [`.env.example`](.env.example).
- **Timeline:** the Twin reads `GET {layer}/events` from each layer. A layer that does not answer is shown as not reachable, and everything else keeps running.

## One scenario, end to end (T1)

1. A car hits a pedestrian. The Twin's engine knows; no other layer does.
2. A witness calls it in. The Twin signs an `emergency_call` reading and pushes it to the Guardian.
3. The Guardian checks the signature and sequence number and issues a verdict.
4. The City Brain reads the trusted report and lists the incident.
5. The City Brain calls `dispatch_unit` with the verdict as `trust_ref`.
6. The Twin sends the ambulance and the police car, which close the road, treat the casualty and take them to hospital.

## Status

Only the Twin is real in this repository so far.
It has been run with its mocks, not yet with the partner teams' layers.

## To be filled in by the triplet

The sections below need real facts from the three teams.

### Coordination
Tools and sync schedule: to be filled in.

### A partner failure or change, and how it was handled
To be filled in.
What the Twin does when a partner is down: it keeps simulating, logs `delivery_failed`, and shows the layer as not reachable on the timeline.

### Proof of a joint run
To be filled in: the date, the commit of each layer, and the log file in `logs/`.
