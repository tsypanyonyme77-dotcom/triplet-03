"""HMAC provenance for readings (contract: provenance = {signed_by, hmac}).

The HMAC covers the canonical JSON of the whole reading except `provenance`:
keys sorted, no whitespace, UTF-8. Receivers recompute it the same way.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical(payload: dict[str, Any]) -> bytes:
    body = {k: v for k, v in payload.items() if k != "provenance"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: dict[str, Any], key: str) -> str:
    return hmac.new(key.encode(), canonical(payload), hashlib.sha256).hexdigest()


def verify(payload: dict[str, Any], key: str) -> bool:
    given = (payload.get("provenance") or {}).get("hmac", "")
    return hmac.compare_digest(given, sign(payload, key))
