"""HMAC-SHA256 over a canonical JSON form of the envelope.

Canonical form: keys sorted, no whitespace, UTF-8. The `provenance` field (the signature
itself) and `trust` (added later by an inline Guardian) are left out of the signed bytes.
A whole-number float is signed as an integer (6.0 as 6), as RFC 8785 and JavaScript write it, so a signer in another
language gets the same bytes. `verify` also accepts the older form (6.0 as `6.0`) so signatures made before 6 Nov still hold.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

UNSIGNED_FIELDS = ("provenance", "trust")


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _whole(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    if isinstance(value, dict):
        return {k: _whole(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_whole(v) for v in value]
    return value


def payloads(envelope: dict[str, Any]) -> tuple[bytes, bytes]:
    """The bytes a signature covers: the current form, then the older one (identical unless a whole-number float is present)."""
    signed = {k: v for k, v in envelope.items() if k not in UNSIGNED_FIELDS}
    return canonical_json(_whole(signed)), canonical_json(signed)


def signature(envelope: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), payloads(envelope)[0], hashlib.sha256).hexdigest()


def sign(envelope: dict[str, Any], secret: str, signed_by: str) -> dict[str, Any]:
    return {**envelope, "provenance": {"signed_by": signed_by, "hmac": signature(envelope, secret)}}


def verify(envelope: dict[str, Any], secret: str) -> bool:
    provided = (envelope.get("provenance") or {}).get("hmac")
    if not isinstance(provided, str):
        return False
    return any(
        hmac.compare_digest(provided, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest())
        for body in dict.fromkeys(payloads(envelope))
    )


def hmac_hex(body: dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 of the plain canonical form, no field left out and no float rewritten: how the Guardian team's contract 1.0 signs (the caller drops the signature field)."""
    return hmac.new(secret.encode(), canonical_json(body), hashlib.sha256).hexdigest()
