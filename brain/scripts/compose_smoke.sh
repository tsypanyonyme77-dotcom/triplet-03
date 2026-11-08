#!/usr/bin/env bash
# Starts the core stack, runs scenario d3 over the network mocks inside it, checks the log's hash chain, tears down.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'docker compose --profile core down -v >/dev/null 2>&1' EXIT
scripts/up.sh core
docker compose exec -T brain brain scenario d3 --no-spawn --quiet --config deploy/compose/partners.compose.yaml | tail -3
log=$(docker compose exec -T brain sh -c 'ls -t logs/d3-*.jsonl | grep -v inputs | head -1' | tr -d '\r')
docker compose exec -T brain brain audit verify "$log"
echo "compose smoke: ok"
