#!/usr/bin/env bash
# Test Book scenario t13: one command, one log in logs/.
cd "$(dirname "$0")/../.." && exec uv run brain scenario t13 "$@"
