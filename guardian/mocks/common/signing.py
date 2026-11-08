"""Envelope signing exactly as the contract says: HMAC-SHA256 over canonical JSON without `hmac`.
Deliberately independent of guardian/src so the mocks double as a second implementation of the contract."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical(obj: dict[str, Any], exclude: str) -> bytes:
    return json.dumps({k: v for k, v in obj.items() if k != exclude}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()


def sign_envelope(env: dict[str, Any], key: str) -> dict[str, Any]:
    env = dict(env)
    env["hmac"] = hmac.new(key.encode(), canonical(env, "hmac"), hashlib.sha256).hexdigest()
    return env


def verify_verdict(verdict: dict[str, Any], key: str) -> bool:
    sig = hmac.new(key.encode(), canonical(verdict, "signature"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, str(verdict.get("signature", "")))
