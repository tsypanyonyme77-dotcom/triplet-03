#!/usr/bin/env bash
# The hall has no Wi-Fi and nothing may be installed on stage. `save` (online, once) packs everything the demo needs into hall-kit/;
# `load` (on the demo laptop, offline) checks the sums and loads it; `check` says what is missing.
#   scripts/hall_kit.sh save | load | check
set -euo pipefail
cd "$(dirname "$0")/.."
kit=hall-kit
images=("city-brain/brain:dev")
cmd=${1:-check}

case "$cmd" in
  save)
    mkdir -p "$kit/images"
    for image in "${images[@]}"; do
      file="$kit/images/$(echo "$image" | tr '/:' '__').tar"
      docker save "$image" -o "$file"
      echo "$image $(docker image inspect "$image" --format '{{.Id}}')" >> "$kit/images/MANIFEST"
    done
    mkdir -p "$kit/fastembed" && cp -r "${FASTEMBED_CACHE_PATH:-$HOME/.cache/city-brain/fastembed}/." "$kit/fastembed/" 2>/dev/null || true
    (cd "$kit" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    du -sh "$kit"
    ;;
  load)
    (cd "$kit" && sha256sum -c SHA256SUMS --quiet) && echo "sums ok"
    for file in "$kit"/images/*.tar; do docker load -i "$file"; done
    scripts/compose_smoke.sh
    ;;
  check)
    missing=0
    [ -f "$kit/SHA256SUMS" ] || { echo "missing: $kit/SHA256SUMS (run: scripts/hall_kit.sh save)"; missing=1; }
    for image in "${images[@]}"; do docker image inspect "$image" >/dev/null 2>&1 && echo "image present: $image" || { echo "missing image: $image"; missing=1; }; done
    [ -d "${FASTEMBED_CACHE_PATH:-$HOME/.cache/city-brain/fastembed}" ] && echo "embedding model cached" || { echo "missing: embedding model cache"; missing=1; }
    exit $missing
    ;;
  *) echo "usage: $0 save|load|check"; exit 2 ;;
esac
