# Twin Layer Architecture

Sources: `../../docs/diagrams/twin-layer-architecture.png` (our diagram), `reference/city-brain-convergence-architecture-report.pdf` (cross-layer design; we only cover the Twin parts here).

## Transport decision (current)
The architecture report and diagram specify MCP servers. **For now we talk to the other layers over plain HTTP APIs, not MCP.** Keep the interface layer thin and separate from simulation logic so MCP can be added later as another adapter over the same operations (tools map 1:1 to API endpoints). The tool/operation list in the diagram and the shapes in `data-dictionary.md` stay valid.

## Diagram (twin-layer-architecture.png)
```
External surface  <-- controlled by TSYP evaluation committee
  |- Simulators   idempotent ops that set context / inject events (e.g. set flood=true)
  '- Actuators    ops that spawn/redirect privileged subjects (e.g. dispatch ambulance to x,y)

Simulation
  |- Shared LLM Service --serves--> Subjects (vehicles, pedestrians, emergency units, ...)
  |- Events (Context)   --feeds-->  Subjects   (time, weather, active event flags)
  |- Actions (Tools)    <-used by-- Subjects --> Simulation Engine
  '- Simulation Engine: Driving engine, Crowd engine, Interaction engine

Control surface   privileged state-mutating ops for the other layers (spawn/despawn subject, freeze agent, patch context)
Logs surface      read-only drill-down on an already streamed log line
Streaming simulation logs --> other layers (TLS with certificates)
```

## Planned design (from the architecture report; mostly NOT built yet)
- **Three surfaces:** External (committee-facing: Simulators + Actuators), Control (privileged), Logs (read-only). Today each is an HTTP API group.
- **Telemetry is a stream, not request/response.** NDJSON log stream over TLS 1.3 with mutual TLS. Each record has a monotonic sequence number and an HMAC so a receiver can detect dropped, reordered, duplicated or altered lines. The data dictionary envelope has matching `sequence_no` and `provenance.hmac` fields.
- **Subjects** (vehicle, pedestrian, emergency unit) each carry a random trait vector `t` in `[0,1]^d` (urgency, risk-aversion, compliance...). Next action = policy(traits, context, action space). The policy emits an **intent only** (e.g. `GOTO(park)`), never integrates motion.
- **Decision/physics separation.** Intents go to domain engines: driving (report suggests SUMO via TraCI, Krauss model; POC uses its own IDM + MOBIL), crowd (social-force, Helbing-Molnar), interaction (cross-domain effects: fire spreading, jam backing into a side street). Engine state is pushed to a visual layer over pub/sub.
- **Teacher LLM to student model (cost control).** LLM labels (trait, context) pairs offline as soft labels; XGBoost student (`multi:softprob`) serves per-tick decisions in one batched call; confidence below threshold falls back to the shared LLM service; a canary sample is shadow-checked against the LLM and drift triggers retraining. Goal: avoid one LLM call per subject per tick.
- **Collision example:** two vehicle subjects near zero velocity at overlapping coordinates beyond a dwell time = collision. A dispatch actuator call spawns an ambulance subject routed to the crash coordinates.
- **Incoming calls get validated.** The external surface is the only one reachable by outside actors: schema-validate every argument, rate-limit per client, reject replays (sequence/nonce), return clear errors.
- **Health and load shedding.** The Guardian team may read latency (P50/P95/P99), throughput, and queue depth from our subject-model request path and engine, and may freeze low-priority subjects to drain backlog. We should expose those metrics and support freeze/unfreeze.

## What we implement vs ignore
Implement: everything on the Twin side above, the sensor/actuator contract, mocks of the other two layers for standalone runs, fault/spoof injection with preserved ground truth.
Ignore for now: City Brain internals (micro-batching, problem/solution sub-agents), Guardian internals (log monitor, reasoning judge, health matrix logic, IPS). We only meet them at the API boundary.
