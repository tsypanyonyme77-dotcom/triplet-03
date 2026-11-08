"""Keys with ids, algorithms and validity windows, so a key can be rotated without a flag day.

A peer (`twin`, `guardian`, `brain`) has a list of keys; the first is the current one. A signed envelope may name the key it used in
`provenance.kid` and `provenance.alg`; without them the current key is tried, which is how every envelope was checked before. The signed bytes
are the same canonical form as ever, so an old signature still verifies. Two algorithms: HS256 (a shared secret, as today) and EdDSA
(Ed25519: the verifier holds only a public key, which the Brain publishes at `/.well-known/jwks.json`). `alg: none` and any other algorithm are refused.
The signature goes in `provenance.hmac` for both (the field kept its name so the contract did not change).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from brain.contracts.signing import payloads, signature, verify

ALGORITHMS = ("HS256", "EdDSA")


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Key:
    kid: str | None
    alg: str = "HS256"
    secret: str | None = None
    public: Ed25519PublicKey | None = None
    private: Ed25519PrivateKey | None = None
    not_before: datetime | None = None
    not_after: datetime | None = None


def _end_of(day: date | None) -> datetime | None:
    return datetime.combine(day, time.max, tzinfo=UTC) if day else None


class KeyRing:
    def __init__(self, keys: dict[str, list[Key]]) -> None:
        self.keys = keys

    @classmethod
    def from_secret(cls, peer: str, secret: str) -> "KeyRing":
        """One shared secret and no key id: exactly the old behaviour."""
        return cls({peer: [Key(None, "HS256", secret=secret)]})

    @classmethod
    def from_config(cls, config: dict[str, list[Any]], environ: dict[str, str] | None = None) -> "KeyRing":
        env = os.environ if environ is None else environ
        keys: dict[str, list[Key]] = {}
        for peer, entries in config.items():
            for e in entries:
                public = private = None
                if e.alg == "EdDSA":
                    if e.private_key_env and env.get(e.private_key_env):
                        private = Ed25519PrivateKey.from_private_bytes(_b64(env[e.private_key_env]))
                        public = private.public_key()
                    elif e.public_key:
                        text = Path(e.public_key).read_text().strip() if os.path.exists(e.public_key) else e.public_key
                        public = Ed25519PublicKey.from_public_bytes(_b64(text))
                keys.setdefault(peer, []).append(Key(e.kid, e.alg, env.get(e.secret_env or "") or None, public, private, _end_of(e.not_before) and datetime.combine(e.not_before, time.min, tzinfo=UTC), _end_of(e.not_after)))
        return cls(keys)

    def has(self, peer: str) -> bool:
        return bool(self.keys.get(peer))

    def verify(self, peer: str, envelope: dict[str, Any], now: datetime) -> str | None:
        """None when the signature is good; otherwise the reason code."""
        provenance = envelope.get("provenance")
        if not isinstance(provenance, dict) or not isinstance(provenance.get("hmac"), str):
            return "signature_missing"
        ring = self.keys.get(peer) or []
        alg, kid = provenance.get("alg"), provenance.get("kid")
        if alg is not None and alg not in ALGORITHMS:
            return "signature_alg_not_allowed"
        key = next((k for k in ring if k.kid == kid), None) if kid is not None else (ring[0] if ring else None)
        if key is None or (key.not_before and now < key.not_before):
            return "signature_unknown_key"
        if alg is not None and alg != key.alg:
            return "signature_alg_not_allowed"
        if key.not_after and now > key.not_after:
            return "signature_key_expired"
        if key.alg == "EdDSA":
            if key.public is None:
                return "signature_unknown_key"
            for body in dict.fromkeys(payloads(envelope)):
                try:
                    key.public.verify(bytes.fromhex(provenance["hmac"]), body)
                    return None
                except (InvalidSignature, ValueError):
                    continue
            return "signature_invalid"
        return None if key.secret and verify(envelope, key.secret) else "signature_invalid"

    def sign(self, peer: str, envelope: dict[str, Any], signed_by: str) -> dict[str, Any]:
        """Sign with the peer's current key, naming it (`kid`, `alg`) when it has an id."""
        key = (self.keys.get(peer) or [None])[0]
        if key is None:
            raise KeyError(f"no signing key for {peer}")
        if key.alg == "EdDSA":
            if key.private is None:
                raise KeyError(f"{peer}'s key {key.kid} has no private half here")
            digest = key.private.sign(payloads(envelope)[0]).hex()
        else:
            digest = signature(envelope, key.secret or "")
        provenance = {"signed_by": signed_by, "hmac": digest, **({"kid": key.kid, "alg": key.alg} if key.kid else {})}
        return {**envelope, "provenance": provenance}

    def jwks(self, peer: str) -> dict[str, list[dict[str, str]]]:
        """The public halves of a peer's EdDSA keys as a JSON Web Key Set (RFC 8037 OKP/Ed25519)."""
        out = []
        for key in self.keys.get(peer, []):
            if key.alg == "EdDSA" and key.public is not None:
                raw = key.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                out.append({"kty": "OKP", "crv": "Ed25519", "kid": key.kid or "", "alg": "EdDSA", "use": "sig", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()})
        return {"keys": out}
