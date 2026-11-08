# Phase 1 Requirements

Source PDF: `reference/phase1-specifications.pdf`. Deliverables due **7 Nov 2026**, demo at CSTAM **14 Nov 2026**.

## Free vs required
Free: architecture, languages, protocols (REST, MQTT, WebSocket, gRPC, MCP...), hosting, databases, AI/ML, UI, scenarios. No imposed technical contract.
Required: rules R1 to R4.

| # | Requirement | Why |
|---|---|---|
| R1 | Layer runs on its own. We ship simple **mocks** of City Brain and Guardian. We write a one-page **Interface Card** (`INTERFACE.md`): what we send and receive, one example message each, how to point at a different partner (config, never hard-coded), how we authenticate. | Shows the layer works independently and can connect to others |
| R2 | Every scenario starts with **one trigger** (one command or button) and leaves a **log file** in the repo. | Short demos; jury can check reliability afterwards |
| R3 | A **live timeline screen** shows what happens across the three layers with timestamps (reading, Guardian verdict, Brain decision, actuator action). | Judges see cause and effect |
| R4 | Document how the three teams coordinated (tools, sync schedule), how a partner failure or change was handled, proof of a joint run. | Shows teamwork |

## Interoperability, what the jury reads from our code
- Clear separation between our layer's logic and the way it talks to partners.
- Complete Interface Card with message formats and examples.
- Partner addresses and settings in config files, not hard-coded.
- Standard, well-known protocols and data formats.
- Input validation and clear error messages when a partner sends something unexpected.
- Layer runs alone with mocks (R1).
- A team is not penalized for a partner's failure if it shows its own layer behaving correctly with its mocks.

## Repository (one per triplet, `triplet-XX`, one folder per team)
```
triplet-XX/
  README.md  INTEGRATION.md  TESTBOOK.md  docker-compose.yml  .github/CODEOWNERS
  scenarios/   one trigger script per Test Book scenario (R2)
  logs/        one log file per scenario run (R2)
  twin/        README.md (run alone)  INTERFACE.md (R1)  src/  mocks/ (brain + guardian stand-ins)  tests/
  brain/  guardian/
  docs/        report.pdf  pitch.pdf  diagrams/
```
Each team commits only inside its own folder (CODEOWNERS). Root files are shared. A one-command start of the whole city is recommended. **Our code is in `twin/` in this shape.** We are triplet 03, and everything here will be copied into the shared triplet repository.

## Report (PDF, max 20 pages)
| Part | Pages |
|---|---|
| 0 Triplet overview and integration (diagram, communication, one scenario end to end) | 3 |
| **1 The City (Twin)**: city plan and zones, sensors and actuators, simulation model, how scenarios are played, tech stack | 5 |
| 2 City Brain | 5 |
| 3 Guardian | 5 |
| 4 Test Book (your scenarios with expected outputs) | 1 |
| 5 Collaboration process | 1 |

Parts 1 to 3 use the same six subheadings: Role and goals, Architecture, Tech stack and why, Interfaces in/out, Security measures, Known limitations. Plus a pitch deck PDF, about 5 slides.

## Test Book
Scenarios are ours; no mandatory list. Together they must test all three layers and every interaction: Twin to Brain, Brain to Guardian, Twin to Guardian, all three at once. Fields per scenario: ID, Name, Layers involved, Description, Trigger, Expected (per layer), How to verify.
Example (T5 Fake flood at the port): Twin streams a fake 180 cm water reading while keeping the true 40 cm internally; Guardian marks it untrusted within 10 s and isolates the sensor; Brain does not open the valve and records why. Verified on the timeline screen and `logs/t5-*.log`.
**Twin duty in such scenarios:** be able to inject falsified readings while keeping ground truth internally, on a single trigger.

## Demo day (CSTAM, 10 min)
0:00 to 2:00 pitch. 2:00 to 10:00 live demo of chosen scenarios on the timeline screen; unrun scenarios are checked through logs. Before the slot: set up in the prep area, system already running, timeline shows live data. Nothing installed on stage. Bring own router/hotspot, do not rely on venue Wi-Fi. If cloud is used, keep a local fallback. If the live connection fails, 2 minutes to recover, then the jury relies on code and logs and live-demo points drop. Anything that cannot run within the slot is not scored.

## Selection for Phase 2
N teams chosen on Phase 1 team score, balanced across layers, then reshuffled into new triplets right after CSTAM.
