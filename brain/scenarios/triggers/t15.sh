#!/usr/bin/env bash
# Test Book scenario t15: one command, one log in logs/.
cd "$(dirname "$0")/../.." && exec uv run brain scenario t15 "$@"
