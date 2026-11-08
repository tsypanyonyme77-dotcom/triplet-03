"""GuardianPort over REST.

  POST /verdicts {"reading": <envelope>}  -> TrustVerdict
  GET  /quarantine/<device_id>            -> {"device_id", "quarantined": bool}

Pass an `httpx.AsyncClient` to reuse a transport (tests and `--inproc` pass an ASGI one).
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from brain.contracts import TrustVerdict
from brain.ports import GuardianUnavailable


class RestGuardianAdapter:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> TrustVerdict:
        try:
            response = await self._client.post("/verdicts", json={"reading": reading}, timeout=deadline_s)
            response.raise_for_status()
            return TrustVerdict.model_validate(response.json())
        except httpx.HTTPError as error:
            raise GuardianUnavailable(f"{type(error).__name__}: {error}") from error
        except (ValidationError, ValueError) as error:
            raise GuardianUnavailable(f"guardian sent an invalid verdict: {error}") from error

    async def is_quarantined(self, device_id: str) -> bool:
        try:
            response = await self._client.get(f"/quarantine/{device_id}", timeout=2.0)
            response.raise_for_status()
            return bool(response.json()["quarantined"])
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise GuardianUnavailable(f"{type(error).__name__}: {error}") from error
