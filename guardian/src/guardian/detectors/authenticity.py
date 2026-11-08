"""L1 authenticity (hard gate): contract_version, schema, then constant-time HMAC check of the envelope."""

from __future__ import annotations

from typing import Any

from guardian.adapters.schemas import Envelope
from guardian.config import SensorRegistry
from guardian.detectors.base import L1, fail, ok
from guardian.ingest.validator import validate_envelope
from guardian.models import LayerResult
from guardian.trust.signer import Signer


class AuthenticityDetector:
    layer = L1

    def __init__(self, registry: SensorRegistry, contract_version: str, twin_signer: Signer) -> None:
        self.registry = registry
        self.contract_version = contract_version
        self.signer = twin_signer

    def check_raw(self, raw: Any) -> tuple[Envelope, LayerResult]:
        """Raises IngestError when the message cannot be parsed; returns a failed result on a bad HMAC."""
        env = validate_envelope(raw, self.registry, self.contract_version)
        if not self.signer.verify(raw, raw.get("hmac"), exclude="hmac"):
            return env, fail(L1, "hard", "hmac_invalid", "HMAC-SHA256 over canonical envelope does not match")
        return env, ok(L1, "schema, contract_version and HMAC valid")
