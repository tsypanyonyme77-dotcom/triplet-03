# Guardian: run alone with mocks. `make install && make test`, then `make demo`.
PY ?= .venv/bin/python
T ?= T1
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo docker-compose)
.PHONY: install env run mocks test lint scenario demo docker clean

install: env
	test -x $(PY) || python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"

env:
	@mkdir -p logs data
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example; replace the keys")

run:
	set -a; . ./.env; set +a; $(PY) -m guardian.main

mocks:
	set -a; . ./.env; set +a; \
	GUARDIAN_URL=http://localhost:8100 $(PY) -m mocks.twin_mock serve & \
	GUARDIAN_URL=http://localhost:8100 $(PY) -m mocks.brain_mock & \
	wait

test:
	$(PY) -m pytest -q --cov=src/guardian --cov-report=term-missing:skip-covered

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy src

scenario:
	set -a; . ./.env; set +a; $(PY) -m scenarios.run $(T)

# Starts guardian + both mocks locally, waits for health, runs scenario $(T), stops everything.
demo: env
	@set -a; . ./.env; set +a; \
	$(PY) -m guardian.main & G=$$!; \
	GUARDIAN_URL=http://localhost:8100 $(PY) -m mocks.twin_mock serve & W=$$!; \
	GUARDIAN_URL=http://localhost:8100 $(PY) -m mocks.brain_mock & B=$$!; \
	trap "kill $$G $$W $$B 2>/dev/null" EXIT; \
	for i in $$(seq 30); do curl -sf localhost:8100/health >/dev/null && curl -sf localhost:8101/health >/dev/null && break; sleep 1; done; \
	sleep 20; $(PY) -m scenarios.run $(T)

docker: env
	$(COMPOSE) up --build

clean:
	rm -rf data logs .pytest_cache .mypy_cache .ruff_cache .hypothesis .coverage
