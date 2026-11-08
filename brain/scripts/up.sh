#!/usr/bin/env bash
# One command to start the city: scripts/up.sh [core|full] [obs]   (core: Brain + mock Twin + mock Guardian; full adds Neo4j and Qdrant;
# obs adds Jaeger :16686, Prometheus :9090 and Grafana :3000 and sends the Brain's spans to Jaeger)
set -euo pipefail
cd "$(dirname "$0")/.."
profile="${1:-core}"
docker image inspect city-brain/brain:dev >/dev/null 2>&1 || docker build -t city-brain/brain:dev .
if [ "$profile" = full ]; then
  export BRAIN_CONFIG=deploy/compose/partners.full.yaml
  grep -qs '^GROQ_API_KEY=.' .env && export BRAIN_FLAGS=--llm   # the agent teams on a real model when there is a key
fi
extra=()
if [ "${2:-}" = obs ]; then
  export OTLP_ENDPOINT=http://jaeger:4318
  extra=(--profile obs)
fi
docker compose --profile "$profile" "${extra[@]}" up -d --wait
[ "${2:-}" = obs ] && echo "Traces http://127.0.0.1:${JAEGER_UI_PORT:-16686}/   Metrics http://127.0.0.1:${PROMETHEUS_PORT:-9090}/   Dashboard http://127.0.0.1:${GRAFANA_PORT:-3000}/"
echo "City Brain: http://127.0.0.1:${BRAIN_PORT:-8080}/   (number keys run scenarios, C opens the canopy)"
