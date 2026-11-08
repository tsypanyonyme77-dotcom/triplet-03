"""HMAC-SHA256 over canonical JSON. Used to verify Twin envelopes and to sign Guardian verdicts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_json(obj: dict[str, Any], exclude: str | None = None) -> bytes:
    body = {k: v for k, v in obj.items() if k != exclude}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class Signer:
    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("HMAC key must not be empty")
        self._key = key.encode()

    def sign(self, obj: dict[str, Any], exclude: str | None = None) -> str:
        return hmac.new(self._key, canonical_json(obj, exclude), hashlib.sha256).hexdigest()

    def verify(self, obj: dict[str, Any], signature: object, exclude: str | None = None) -> bool:
        if not isinstance(signature, str):
            return False
        return hmac.compare_digest(self.sign(obj, exclude), signature.lower())
