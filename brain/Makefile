# Everything you run, in one place.   make help
#
# Run from this folder (brain/). Uses uv, Docker.
# Recipes start with ">" instead of a tab (see .RECIPEPREFIX), so an editor cannot break them.

.RECIPEPREFIX = >
.DEFAULT_GOAL := help
SHELL := /bin/bash

# S: a scenario id for the targets that take one (make scenario S=d3).
# FLAGS: extra flags for brain scenario, e.g. FLAGS="--no-departments".
S ?= d3
FLAGS ?=
IMAGE ?= city-brain/brain
TAG ?= dev
NEO4J_PW ?= citybrain-test-pw
SERVERS_ENV = NEO4J_PASSWORD=$(NEO4J_PW) QDRANT_URL=http://127.0.0.1:6333 MQTT_URL=mqtt://127.0.0.1:1883
ENVFILE = $(if $(wildcard .env),--env-file .env,)

.PHONY: neo4j sleep full-sleep full full-scenario full-agents full-state full-logs full-down help setup serve scenario scenarios llm llm-all reliability \
        test test-all servers-up servers-down servers-status \
        obs bench bench-quick baselines variants redteam security-report conformance check \
        image up down smoke hall-kit \
        clean

help: ## this list
> @grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
> @echo; echo "  Variables: S=<scenario> FLAGS=<flags> TAG=<image tag> NEO4J_PW=<password>"

# ---------------------------------------------------------------- run it

setup: ## install the Python environment with every extra (llm, mqtt, otel); make .env from the example
> uv sync --extra llm --extra mqtt --extra otel
> @test -f .env || (cp .env.example .env && echo "created .env: put your GROQ_API_KEY in it (only real-model runs need it)")

serve: ## the timeline screen at http://127.0.0.1:8080 (number key runs a scenario, C opens the canopy); closed incidents are kept in state/episodes so Sleep now works
> uv run brain serve --episodes state/episodes --learned state/learned

scenario: ## one scenario in process, fast: make scenario S=d3
> uv run brain scenario $(S) --inproc --speed 0 $(FLAGS)

scenarios: ## all 38 scenarios in process, with the temporal promises and every frozen baseline (about 30 s)
> uv run brain bench --quick

llm: ## one scenario with the agent teams on a real model (needs GROQ_API_KEY in .env): make llm S=d3
> uv run $(ENVFILE) brain scenario $(S) --llm --speed 0.5 $(FLAGS)

llm-all: ## every department's agents on the real model, spaced for the free plan (Police, Fire, Utilities, Mobility)
> @for s in d3 d2 d4; do echo "== $$s"; uv run $(ENVFILE) brain scenario $$s --llm --speed 0.5 | grep -E "desk\.|case.reviewed|plan.verified|agent.fallback|^(PASSED|FAILED)" | cut -c1-200; sleep 65; done

sleep: ## learn from the episodes `make serve` kept in state/episodes (reflexes go to state/learned; add FLAGS=--dry-run to write nothing)
> uv run brain sleep --episodes state/episodes --learned state/learned $(FLAGS)

reliability: ## the Police team on the real model, 3 trials, spaced 65 s
> uv run $(ENVFILE) brain reliability $(S) --trials 3 --llm --pause 65

# ---------------------------------------------------------------- tests and checks

test: ## the full test suite with no servers (the tests that need them skip): 4 to 9 minutes
> uv run pytest tests -q

test-all: servers-up ## the full suite against live Qdrant, Neo4j and Mosquitto: 0 skipped
> $(SERVERS_ENV) uv run pytest tests -q -p no:cacheprovider; code=$$?; $(MAKE) --no-print-directory servers-down; exit $$code

neo4j: ## start only Neo4j (the city graph) on 127.0.0.1:7687, browser at http://127.0.0.1:7474 (user neo4j, password NEO4J_PASSWORD or citybrain-local-pw); serve and scenario then use it
> docker compose --profile core up -d --wait neo4j

servers-up: ## start Qdrant, Neo4j and Mosquitto in Docker (ports on 127.0.0.1 only)
> @docker rm -f vq vn vm >/dev/null 2>&1; true
> docker run -d --name vq -p 127.0.0.1:6333:6333 qdrant/qdrant:v1.20.0 >/dev/null
> docker run -d --name vn -p 127.0.0.1:7687:7687 -e NEO4J_AUTH=neo4j/$(NEO4J_PW) neo4j:5.26-community >/dev/null
> docker run -d --name vm -p 127.0.0.1:1883:1883 -v $(CURDIR)/deploy/compose/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro eclipse-mosquitto:2 >/dev/null
> @until curl -s http://127.0.0.1:6333/readyz >/dev/null; do sleep 2; done; echo "qdrant up"
> @until docker exec vn cypher-shell -u neo4j -p $(NEO4J_PW) "RETURN 1" >/dev/null 2>&1; do sleep 3; done; echo "neo4j up"
> @echo "mosquitto up. For your own commands: export $(SERVERS_ENV)"

servers-down: ## stop and remove those three containers
> @docker rm -f vq vn vm >/dev/null 2>&1; echo "servers removed"

servers-status: ## which of them are running
> @docker ps --filter name=vq --filter name=vn --filter name=vm --format '{{.Names}}: {{.Status}}'

bench: ## the full evidence table: scenarios, baselines, variants (345), dispatch, retrieval, forward, interop, red team, learning curve
> uv run brain bench

bench-quick: ## the same without the slow steps (about 30 s)
> uv run brain bench --quick

baselines: ## every frozen baseline must still read "no differences"
> @for f in docs/baseline/*-frozen.json; do echo -n "$$(basename $$f): "; uv run brain baseline --check $$f | tail -1; done

variants: ## shifted, reseeded and decoyed variants of every scenario must decide as their base (held-out seeds)
> uv run brain variants --seeds 1000-1004

redteam: ## 24 attacks on the Brain; all must be refused
> uv run brain redteam

security-report: ## each documented threat with the tests that prove it (writes docs/security/<date>.md)
> uv run brain security-report --out docs/security/$$(date +%F).md

conformance: ## the contract checks on the shipped mocks and this Brain
> uv run brain conformance

check: bench-quick redteam conformance ## the quick confidence pass: bench, red team, conformance

# ---------------------------------------------------------------- containers

image: ## build the Docker image (the embedding model is baked in)
> docker build -t $(IMAGE):$(TAG) .

up: ## the Brain and both mock partners in containers on http://127.0.0.1:8080
> scripts/up.sh

down: ## stop that stack
> docker compose --profile core --profile full --profile mqtt --profile obs down

smoke: ## start the stack, run d3 over the network mocks, verify the log, stop
> scripts/compose_smoke.sh

hall-kit: ## pack the image and model cache for a venue with no network (hall-kit/), then check it
> scripts/hall_kit.sh save && scripts/hall_kit.sh check

# ---------------------------------------------------------------- the full stack in Docker Compose

full: image ## the Brain, mock Twin and Guardian, Neo4j (city graph) and Qdrant (knowledge vectors); the agent teams on real models when .env holds a GROQ_API_KEY
> scripts/up.sh full
> @docker compose ps --format 'table {{.Service}}\t{{.Status}}'

obs: image ## `make full` plus Traefik, Prometheus, Grafana, Loki and Jaeger (docs/OBSERVABILITY.md): http://brain.localhost:8000 and http://grafana.localhost:8000
> scripts/up.sh full obs

full-scenario: ## run one scenario inside the full stack and print its verdict: make full-scenario S=d4 (FLAGS="--llm --speed 0.5" for real models)
> docker compose exec -T brain brain scenario $(S) --no-spawn --config deploy/compose/partners.full.yaml $(FLAGS) | grep -E "desk\.|agent.fallback|^(PASSED|FAILED)" | cut -c1-200

full-agents: ## every department's agents on the real model in the full stack, 65 s apart (the crime, the fake flood and the layer-down flood)
> @for s in d3 d2 d4; do echo "== $$s"; $(MAKE) --no-print-directory full-scenario S=$$s FLAGS="--llm --speed 0.5"; sleep 65; done

full-state: ## what is inside the stack's Neo4j and Qdrant
> -docker compose exec -T neo4j sh -c 'cypher-shell -u neo4j -p "$${NEO4J_AUTH#neo4j/}" "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC LIMIT 8"'
> -docker compose exec -T brain python -c "import urllib.request as u,json;g=lambda p:json.load(u.urlopen('http://qdrant:6333'+p))['result'];[print('qdrant',c['name'],g('/collections/'+c['name'])['points_count'],'points') for c in g('/collections')['collections']]"

full-sleep: ## learn from the closed incidents the stack kept (run some scenarios first): reflexes are promoted only if every check passes
> docker compose exec -T brain brain sleep --config deploy/compose/partners.full.yaml

full-logs: ## follow the Brain's log
> docker compose logs -f brain

full-down: ## stop the stack and delete its volumes (Neo4j keeps the password it first started with in its volume, so a changed NEO4J_PASSWORD needs this)
> docker compose --profile full --profile mqtt --profile obs down -v

# ---------------------------------------------------------------- housekeeping

clean: ## delete run logs and journals (logs/canonical stays), caches and state/
> find logs -maxdepth 1 -type f \( -name '*.jsonl' -o -name '*.head' \) -delete
> rm -rf state .pytest_cache hall-kit certs
> find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
