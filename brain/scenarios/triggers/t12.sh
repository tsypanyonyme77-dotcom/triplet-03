#!/usr/bin/env bash
# Test Book scenario t12: one command, one log in the repo root logs/ folder (LOG_DIR overrides).
cd "$(dirname "$0")/../.." && LOG_DIR="${LOG_DIR:-../logs}" exec uv run brain scenario t12 "$@"
