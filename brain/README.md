# brain (Tatsu)

The City Brain: it detects real incidents (accidents, fires, jams, floods, crimes) from the Twin's live readings, waits for the Guardian's trust verdict on each reading, decides the response, and acts through the Twin's actuators. Every actuator call leaves through one checked door, the **Safety gate**: no trusted verdict, no action.

Python 3.12 with uv, FastAPI, LangGraph, MCP. It is **brain-inspired**: attention, prediction error, sleep and habit are modelled as engineering, nothing more.

## Run this layer alone (R1)

It runs with no partner, using the stand-ins in [`mocks/`](mocks/) (a mock Twin over MCP, a mock Guardian over REST). Requires [uv](https://docs.astral.sh/uv/), which installs Python and the dependencies.

```bash
uv run brain serve                            # the live timeline screen (R3) at http://127.0.0.1:8080 ; press 1 to 4 to run a scenario, C for the 3D view
uv run brain scenario d3 --inproc --speed 0   # one Test Book scenario in a second: pass/fail verdict and a log
uv run pytest tests -q                        # the test suite (tests that need Neo4j, Qdrant or a broker skip)
```

Or in containers, with both mocks, Neo4j and Qdrant: `scripts/up.sh` (Docker Compose, profile `core`; it builds the image and waits for health).

**Two databases are on by default, each for one job** (`graph.backend: neo4j`):
- **Neo4j keeps the City Graph:** every reading, verdict, incident, decision and action, linked, so a run can be explored as a graph at http://127.0.0.1:7474 ("why was this unit sent?" is one query, in [`docs/graph-queries.md`](docs/graph-queries.md)). Start it alone with `make neo4j`.
- **Qdrant keeps the knowledge vectors:** the playbooks, rules and past incidents the agent teams search by similarity. Embedded (a folder, no server) for `uv run`; a server in Compose.

Why both, and what happens when one is down: [`docs/decisions/0005-databases.md`](docs/decisions/0005-databases.md). Decisions never wait on either: an unreachable store is reported once and the Brain keeps going from memory.

The first run downloads a 65 MB embedding model once. The agent teams run on a real model only with `--llm` and a `GROQ_API_KEY` in `.env` (copy `.env.example`); without it, scripted agents answer the same way every time and every scenario still passes.

## Scenarios and logs (R2)

| ID | Name | Trigger |
| --- | --- | --- |
| d1 | A calm day | `scenarios/triggers/d1.sh` |
| d2 | A fake flood | `scenarios/triggers/d2.sh` |
| d3 | A crime and a pursuit | `scenarios/triggers/d3.sh` |
| d4 | A flood, an attack and a layer down | `scenarios/triggers/d4.sh` |

Each run writes a hash-chained log to `logs/<id>-<time>.jsonl` with its input journal beside it. One verified, replayable log per scenario is kept in [`logs/canonical/`](logs/canonical/) (`uv run brain replay logs/canonical/d3.inputs.jsonl` plays it back). Fields and expected outputs: [`docs/TESTBOOK-brain.md`](docs/TESTBOOK-brain.md).

## Configuration

Partner addresses, protocols and the names of the secret variables are in [`config/partners.yaml`](config/partners.yaml); pointing the Brain at a different Twin or Guardian is an edit there (or `--config <file>`), never a code change. Secrets come from the environment (`.env`, git-ignored). A Twin that names its sensors differently is mapped with `twin.type_aliases` and `twin.profiles`; `uv run brain onboard` proposes them. Details: [`INTERFACE.md`](INTERFACE.md).

## Layout

| Path | Content |
|------|---------|
| [`INTERFACE.md`](INTERFACE.md) | The Interface Card (R1) |
| `src/brain/` | Layer code (map: [`docs/codebase/CODEBASE.md`](docs/codebase/CODEBASE.md)) |
| `mocks/` | Stand-ins for twin + guardian |
| `tests/` | Tests, named as sentences |
| `scenarios/` | The Test Book scenarios (`d1` to `d4`), city topologies, one trigger script per scenario |
| `logs/canonical/` | One verified log per scenario |
| `config/`, `contracts/` | Partner settings and policy; JSON schemas and one example of every message |
| `docs/` | Our report part, how it works, security, decisions, diagrams ([`docs/README.md`](docs/README.md)) |
| `Dockerfile`, `docker-compose.yml`, `deploy/`, `scripts/`, `Makefile` | Containers and helpers (`make help` lists every target) |

## Members

_Listed by the team._
