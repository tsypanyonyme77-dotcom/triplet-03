#!/usr/bin/env bash
# Test Book scenario d1: one command, one log in logs/.
cd "$(dirname "$0")/../.." && exec uv run brain scenario d1 "$@"
