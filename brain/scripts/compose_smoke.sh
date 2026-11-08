#!/usr/bin/env bash
# Starts the core stack, runs scenario t14 over the network mocks inside it, checks the log's hash chain, tears down.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'docker compose --profile core down -v >/dev/null 2>&1' EXIT
scripts/up.sh core
docker compose exec -T brain brain scenario t14 --no-spawn --quiet --config deploy/compose/partners.full.yaml | tail -3
log=$(docker compose exec -T brain sh -c 'ls -t logs/t14-*.jsonl | grep -v inputs | head -1' | tr -d '\r')
docker compose exec -T brain brain audit verify "$log"
echo "compose smoke: ok"
