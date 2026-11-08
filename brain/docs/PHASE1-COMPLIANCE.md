# Phase 1 requirements: where the City Brain meets them

Against *Phase 1 City Brain Convergence* (the three required rules R1 to R3, the repository structure, the report and the scoring). `tests/test_phase1_requirements.py` keeps R1 and R2 true. The same map file by file, with the test behind each line, the jury's criteria, the Test Book interactions and the demo-day rules, is in the [README](../README.md#phase-1-map-requirement-to-source).

## R1: the layer runs on its own

| Part | Met by |
| --- | --- |
| Mocks of the two other layers | `mocks/twin/` (MCP server), `mocks/guardian/` (REST server); `--inproc` runs them in process |
| Runs alone | `README.md`: `uv run brain serve`, `uv run brain scenario t14 --inproc --speed 0`, or `scripts/up.sh` in containers |
| One-page Interface Card | `INTERFACE.md`: what the Brain receives and sends, one example of each message, how to point it at a different partner, how it authenticates (a test fails if it grows past one page or loses an example) |
| Configuration, never hard-coded | `config/partners.yaml` (or `--config`); secrets from the environment |

## R2: one trigger, one log

| Part | Met by |
| --- | --- |
| One command per scenario | `scenarios/triggers/t12.sh` to `t16.sh` (`uv run brain scenario <id>`); on the screen, number keys `1` to `5` or `POST /api/scenarios/{id}/run` |
| A log per run, in the repository | `logs/<id>-<time>.jsonl`, hash-chained, with its input journal; `logs/` is not git-ignored |
| Checkable after the event | `logs/canonical/`: one verified log per scenario, replayable with `brain replay`; `brain verify-log` checks the temporal promises (trust before action, nothing after close) |

## R3: a live timeline screen

`uv run brain serve` at `http://127.0.0.1:8080`: one strip per reading with its timestamp, the Guardian verdict, the Brain's decision and the actuator action in a row, held actions shown as prominently as taken ones, and a "why" for each step. Partners may push their own events (`POST /api/events`, CloudEvents with a token), shown as rows with their source.

## Repository structure

| Phase 1 layout | Here |
| --- | --- |
| `brain/README.md`: how to run this layer alone | `README.md` |
| `brain/INTERFACE.md`: the Interface Card | `INTERFACE.md` |
| `brain/src/` | `src/brain/` |
| `brain/mocks/`: twin + guardian | `mocks/twin/`, `mocks/guardian/` |
| `brain/tests/` | `tests/` |
| Root `INTEGRATION.md`, `TESTBOOK.md`, `docker-compose.yml`, `scenarios/`, `logs/`, `docs/` | Shared by the triplet. Our input: `docs/TESTBOOK-brain.md` (the Test Book fields for `t12` to `t16`), `docker-compose.yml` here (written to be included by the root file), our scenario triggers and logs, `docs/report/` |

## Report, Part 2: The City Brain

`docs/report/report-city-brain.pdf`, in the six shared subheadings: role and goals, architecture, tech stack and why, interfaces in/out, security measures, known limitations. Depth behind each: `HOW-IT-WORKS.md`, `decisions/`, `INTEGRATION-brain.md`, `SECURITY.md`.

## Scoring, and where each line is carried

| Line | Points | Here |
| --- | --- | --- |
| Individual prototype functionality | 10 | The pipeline, the five scenarios (`t12` to `t16`), the decision engines |
| Technical implementation and features | 5 | `decisions/`, `HOW-IT-WORKS.md`, `baseline/` |
| Interoperability and connectivity between the 3 teams | 15 | Adapters behind two small ports (MCP, REST, MQTT), the conformance kit (`brain conformance`), `brain onboard`, the shared decisions in `decisions/` |
| Security and trust mechanisms | 10 | The Safety gate, HMAC signing and replay checks, scoped tokens, signed human approval, `brain redteam` (24 attacks), `SECURITY.md` |
| Documentation and code quality | 5 | Interface Card, README, Test Book, tests named as sentences, lint |
| Demonstration and presence | 5 | The timeline screen and the 3D view |

**Known limit:** the Brain has run end to end against its mocks only; nothing in this folder proves a joint run with the real Twin or Guardian.
