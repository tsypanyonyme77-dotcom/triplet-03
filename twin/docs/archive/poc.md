> Archived 2026-11-08 as a description of the local `poc/` folder, which is kept for its citizen decision model. The engine moved on in `twin/src/twin/engine/`.

# Existing POC (`poc/`)

The POC engine was copied into `two-blocks-base-simulation/simulation/app/` on 2026-11-02 and improved there (time-to-collision pedestrian avoidance, sidewalks and crosswalks, accidents, stop lines, bug fixes); see `two-blocks-base-simulation/docs/fixes-and-changes.md`.
The file map below describes the original POC.

A custom Python/React twin of Avenue Habib Bourguiba, Tunis, built before the CS2 experiment. This is the working proof of concept to present to the team. Moved from repo-root `backend/` and `frontend/` on 2026-10-14. After the move, recreate the venv: `uv sync` in `poc/backend` (old `.venv` has stale absolute paths).

## Backend (`poc/backend`)
Python 3.12, `uv`. Deps: fastapi, groq, networkx, numpy, osmnx, python-dotenv, uvicorn. Entry `app/main.py` (FastAPI app "Twin Layer POC"). OSM road graph cached in `app/data/*.graphml` (git-ignored); `cache/` holds 7 JSON cache files (content unchecked). Secrets in `poc/backend/.env` (`GROQ_API_KEY`), git-ignored, never print.

| File | Role |
|---|---|
| `sim.py` | `Simulation`: tick loop (dt 0.1 s, 10 Hz), routing, lanes, lights, parking, crashes, ambulances, pedestrians, state export |
| `idm.py` | Intelligent Driver Model car-following |
| `mobil.py` | MOBIL lane-change decisions |
| `traffic_lights.py` | signal timing per intersection |
| `parking.py` | parking spots and pull-in state machine (driving, parking, parked, unparked, crashed) |
| `crashes.py` | crash probability (`/api/crash-risk`) |
| `ambulance.py` | ambulances per hospital, dispatched to crash nodes, on-scene cleanup |
| `pedestrian.py`, `social_force.py` | pedestrians with social-force model |
| `places.py` | points of interest generated from the map |
| `road_network.py` | loads and caches the road graph |
| `agents.py` | per-subject LLM (Groq `openai/gpt-oss-20b`): picks the next place at decision points only (spawn, end of dwell), never per tick; max 15 concurrent calls; free-text personas |
| `models.py` | dataclasses (`Car`, etc.) |

API: `GET /api/road-network, /api/parking, /api/places, /api/nodes, /api/state, /api/decisions?since=`; `POST /api/cars, /api/cars/random, /api/cars/agent, /api/cars/bulk, /api/pedestrians/agent, /api/crash-risk`; `DELETE /api/cars/{id}, /api/pedestrians/{id}`; WebSocket `/ws/state`. CORS is wide open (`*`), no auth.

## Frontend (`poc/frontend`)
React 19, TypeScript, Vite, PixiJS 8, oxlint. `src/MapView.tsx` (~960 lines) renders map and live state. `App.tsx` and `main.tsx` are thin.

## Covers vs target (`twin-architecture.md`, `data-dictionary.md`)
Has: driving engine, crowd engine, crash-to-ambulance interaction, per-subject LLM decisions, live viewer, real road graph.
Missing: zones, any sensor (traffic cameras, water, power, air, emergency calls), actuators other than the implicit ambulance dispatch (signals, valves, grid, quarantine, explicit dispatch), contract envelope (versioned, sequence numbers, HMAC), event/context injection (flood, fire, outage), spoof/fault injection with ground truth, log stream, audit log, auth, input validation, config-driven partner addresses, mocks, `INTERFACE.md`, scenario scripts and logs, tests, timeline screen.
