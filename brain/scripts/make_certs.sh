#!/usr/bin/env bash
# A local certificate authority, a server certificate for the Brain, and client certificates for the Twin and the Guardian.
# No network. Output goes to certs/ (git-ignored). Usage: scripts/make_certs.sh [extra-hostname ...]
set -euo pipefail
cd "$(dirname "$0")/.."
out=${CERTS_DIR:-certs}
mkdir -p "$out"
sans="DNS:localhost,DNS:brain,DNS:city-brain,IP:127.0.0.1,IP:::1"
for extra in "$@"; do sans="$sans,DNS:$extra"; done

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 -subj "/CN=city-brain-local-ca" \
  -keyout "$out/ca.key" -out "$out/ca.pem" 2>/dev/null

issue() {  # name, subject CN, extensions
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -subj "/CN=$2" -keyout "$out/$1.key" -out "$out/$1.csr" 2>/dev/null
  printf '%s\n' "$3" > "$out/$1.ext"
  openssl x509 -req -in "$out/$1.csr" -CA "$out/ca.pem" -CAkey "$out/ca.key" -CAcreateserial -days 30 -extfile "$out/$1.ext" -out "$out/$1.pem" 2>/dev/null
  rm -f "$out/$1.csr" "$out/$1.ext"
}
issue brain brain "subjectAltName=$sans
extendedKeyUsage=serverAuth,clientAuth"
issue twin twin "extendedKeyUsage=clientAuth"
issue guardian guardian "extendedKeyUsage=clientAuth"
rm -f "$out/ca.srl"
chmod 600 "$out"/*.key
echo "wrote $out/: ca.pem (trust this), brain.pem/key (server), twin.pem/key and guardian.pem/key (clients)"
