#!/usr/bin/env bash
# Neo4j Community for the City Graph, with no Docker: the release tarball and a Java 21, kept under ~/.cache/city-brain/neo4j.
#
#   scripts/neo4j_local.sh install    # downloads Neo4j and Java 21 once (needs the network), sets the password, binds to 127.0.0.1
#   scripts/neo4j_local.sh start      # starts it in the background and waits until it answers
#   scripts/neo4j_local.sh status     # running or not, and the node count per label
#   scripts/neo4j_local.sh stop
#   scripts/neo4j_local.sh reset --yes   # stop and delete the data (not the install)
#
# The password is NEO4J_PASSWORD, read from the environment or from .env; `install` makes a random one and appends it to .env
# if there is none. Nothing here prints it. Then: uv run --env-file .env brain scenario d3 --graph neo4j
set -euo pipefail

VERSION="${NEO4J_VERSION:-5.26.32}"
ROOT="${NEO4J_LOCAL:-${XDG_CACHE_HOME:-$HOME/.cache}/city-brain/neo4j}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="$ROOT/neo4j-community-$VERSION"
PORT_BOLT=7687

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

java21() {
  # Neo4j 5.26 supports Java 17 and 21 only; the machine's default Java is newer.
  local home
  home="$(mise where java@21 2>/dev/null)" || home=""
  [ -n "$home" ] && [ -x "$home/bin/java" ] || die "no Java 21: run 'mise install java@21' (or this script's install)"
  printf '%s' "$home"
}

password() {
  if [ -z "${NEO4J_PASSWORD:-}" ] && [ -f "$HERE/.env" ]; then
    NEO4J_PASSWORD="$(grep -E '^NEO4J_PASSWORD=.' "$HERE/.env" | tail -1 | cut -d= -f2- || true)"
  fi
  printf '%s' "${NEO4J_PASSWORD:-}"
}

reachable() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT_BOLT") 2>/dev/null; }

neo() { JAVA_HOME="$(java21)" NEO4J_HOME="$HOME_DIR" "$HOME_DIR/bin/$1" "${@:2}"; }

cmd_install() {
  mkdir -p "$ROOT"
  if ! mise where java@21 >/dev/null 2>&1; then say "installing Java 21 with mise ..."; mise install java@21; fi
  if [ ! -d "$HOME_DIR" ]; then
    local tarball="$ROOT/neo4j-community-$VERSION-unix.tar.gz"
    say "downloading Neo4j $VERSION (about 150 MB; resumes if interrupted) ..."
    curl -fL -C - -o "$tarball" "https://dist.neo4j.org/neo4j-community-$VERSION-unix.tar.gz"
    tar -xzf "$tarball" -C "$ROOT"
    rm -f "$tarball"
  fi
  local conf="$HOME_DIR/conf/neo4j.conf"
  if ! grep -q '# city-brain' "$conf"; then
    cat >>"$conf" <<'EOF'

# city-brain: local only, small, and quiet
server.default_listen_address=127.0.0.1
server.memory.heap.initial_size=512m
server.memory.heap.max_size=512m
server.memory.pagecache.size=256m
dbms.usage_report.enabled=false
EOF
  fi
  if [ -z "$(password)" ]; then
    NEO4J_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)"
    printf '\nNEO4J_PASSWORD=%s\n' "$NEO4J_PASSWORD" >>"$HERE/.env"
    say "made a password and appended NEO4J_PASSWORD to .env"
  fi
  if [ ! -d "$HOME_DIR/data/databases/system" ]; then
    neo neo4j-admin dbms set-initial-password "$(password)" >/dev/null
    say "initial password set"
  fi
  say "installed: $HOME_DIR"
}

cmd_start() {
  [ -d "$HOME_DIR" ] || die "not installed: run '$0 install'"
  if reachable; then say "already answering on $PORT_BOLT"; return; fi
  neo neo4j start >/dev/null
  for _ in $(seq 1 120); do reachable && { say "up: bolt://127.0.0.1:$PORT_BOLT, browser http://127.0.0.1:7474 (user neo4j)"; return; }; sleep 1; done
  die "did not answer on $PORT_BOLT within 120 s: see $HOME_DIR/logs/neo4j.log"
}

cmd_stop() {
  [ -d "$HOME_DIR" ] || die "not installed"
  neo neo4j stop >/dev/null 2>&1 && say "stopped" || say "was not running"
}

cmd_status() {
  [ -d "$HOME_DIR" ] || { say "not installed"; return; }
  if ! reachable; then say "not running"; return; fi
  say "running on $PORT_BOLT"
  local pw; pw="$(password)"
  [ -n "$pw" ] || { say "(no NEO4J_PASSWORD: cannot count nodes)"; return; }
  local counts
  counts="$(neo cypher-shell -u neo4j -p "$pw" --format plain \
    "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS nodes ORDER BY label" 2>&1 | head -40)"
  [ -n "$counts" ] && say "$counts" || say "no nodes yet"
}

cmd_reset() {
  [ "${1:-}" = "--yes" ] || die "this deletes every node: run '$0 reset --yes'"
  cmd_stop
  rm -rf "$HOME_DIR/data/databases" "$HOME_DIR/data/transactions"
  say "data removed: run '$0 install' to set the password again, then start"
}

case "${1:-}" in
  install) cmd_install ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  reset) shift; cmd_reset "$@" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
