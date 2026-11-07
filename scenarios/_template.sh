#!/usr/bin/env bash
# Copy to scenarios/<id>-<name>.sh, set ID and fill trigger(). One run = one log in logs/.
set -euo pipefail
ID="${ID:-T0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/${ID,,}-$(date +%Y%m%dT%H%M%S).log"

trigger() { echo "TODO: fire the trigger for $ID"; return 1; }

{ echo "$(date -Is) START $ID"; trigger; echo "$(date -Is) END $ID"; } 2>&1 | tee "$LOG"
