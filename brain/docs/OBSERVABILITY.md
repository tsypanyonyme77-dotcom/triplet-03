# Observability

One command starts the City Brain with its two stores and the whole observability stack:

```bash
OTLP_ENDPOINT=http://jaeger:4318 docker compose --profile obs up -d --build      # from the triplet root
make obs                                                                          # from brain/ (the same, with the mock Twin and Guardian)
```

Every screen is behind one door, Traefik, on `*.localhost` (a browser resolves that to your machine; port `TRAEFIK_PORT`, default 8000):

| Address | What | Fed by |
| --- | --- | --- |
| http://brain.localhost:8000/ | The timeline screen and API (press `1` to `4` to run a scenario) | the Brain |
| http://grafana.localhost:8000/ | One dashboard, "City Brain" (below) | Prometheus, Loki, Jaeger |
| http://prometheus.localhost:8000/ | Metrics and scrape targets | Brain, Traefik, Qdrant, Loki |
| http://jaeger.localhost:8000/ | One trace per scenario: reading, verdict, decision, action | the Brain (OTLP) |
| http://neo4j.localhost:8000/ | The City Graph (log in with `neo4j` and `NEO4J_PASSWORD`; the Browser connects to bolt on 127.0.0.1:7687) | the Brain |
| http://qdrant.localhost:8000/dashboard | The knowledge vectors | the Brain |
| http://traefik.localhost:8000/ | The routes and their health | Traefik |

## The two screens are linked both ways

The Brain's timeline screen has an **Observe** button (top right) that opens the Grafana dashboard; the dashboard has a **City Brain screen** link back. The button appears only when `observability.dashboard_url` is set (the Compose configs set it), so a plain `uv run brain serve` shows no dead link.

## The dashboard

One page, Grafana "City Brain". The top row is the whole system at a glance; anything red needs a look. Everything else is in rows that stay closed until you open them.

| Top row | Goes red when |
| --- | --- |
| Stores | Neo4j or Qdrant cannot be reached |
| Services | a scrape target (Brain, Traefik, Qdrant, Loki) is down |
| Fallbacks active | a component is answering from its in-memory fallback |
| Log errors (5m) | any container but Loki and Grafana logged a warning or error (amber from 1, red from 20). Those two are left out: their logs repeat the dashboard's own queries, which would count themselves |
| Open incidents, Held by the gate (5m) | never: they are information (a held action is the gate doing its job) |

Rows: **Decisions** (what the gate passed and held, by check; events; solver time), **Stores and traffic** (Traefik requests, errors and latency; Qdrant), **Logs** (warnings and errors from every service, then the Brain's and the stores'), **Traces** (the recent ones; open one to follow a reading to its action). Two links sit above it: **Traces** (Jaeger) and **City Graph: latest decision** (opens the Neo4j Browser with the query for the latest decision, what it cited and the action it caused; log in first). The links use port 8000; if you change `TRAEFIK_PORT`, edit them in `deploy/grafana/dashboards/city-brain.json`.

## How the pieces are connected

```text
 browser ──► Traefik ──► Brain (screen, API, /metrics, event stream) ──┬─► Neo4j    the City Graph, written behind the in-memory graph
                │              │                                       └─► Qdrant   the knowledge vectors the agent teams search
                │              └─ spans (OTLP) ─► Jaeger ─────────────────────┐
                ├─ access log (JSON) ──┐                                      │
                └─ request metrics ─┐  │   every container's log ─► Promtail ─► Loki ─┤
   Prometheus scrapes: Brain, Traefik, Qdrant, Loki ◄┘                               ▼
                       └────────────────────────────────────────────────────────► Grafana
```

- **Metrics.** Prometheus scrapes the Brain's `/metrics` (events by type, gate decisions by the check that decided, incidents open, units out, solver time, degraded components and `brain_store_up`), Traefik (requests, errors and latency per service), Qdrant (collections, vectors, REST traffic, memory) and Loki.
- **Neo4j** Community has no metrics endpoint, so the Brain reports whether it can reach Neo4j and Qdrant as `brain_store_up{store}`. The Grafana tile goes red when either is down, and `brain_degraded` shows when the Brain is answering from its in-memory fallback.
- **Logs.** Promtail reads the log of every container of the Compose project and Loki keeps seven days of it, labelled by `service`. Traefik's JSON access log gets `status` and `router` labels. In the dashboard's Logs row: every warning and error, then the Brain's log and the stores' and Traefik's.
- **The tamper-evident record is separate.** The Brain's hash-chained log (`logs/<id>-<time>.jsonl`, checked by `brain verify-log`) is the evidence of what it decided; Loki is for operating the system and is not evidence.
- **Traces.** With `OTLP_ENDPOINT` set, the Brain emits one span per timeline event to Jaeger.

## Limits, stated plainly

- Promtail needs the Docker socket, mounted read-only. It is the one container that can see Docker; it exists only in the `obs` profile.
- Traefik is routing and measuring, not securing: the stack publishes to `127.0.0.1` only, and the Brain runs without tokens there (`security.require: never`). Do not expose it as it is.
- Neo4j has no request metrics, only reachability and its log.
- Grafana is anonymous read-only; the admin password is `GRAFANA_ADMIN_PASSWORD` (default `citybrain-local-pw`, change it).
