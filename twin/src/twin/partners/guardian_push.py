"""Readings pushed to the Guardian in its contract 1.0: one batch per emit tick, POST {GUARDIAN_URL}/v1/readings
with `X-API-Key` (the Twin's key on the Guardian, TWIN_API_KEY). The Guardian answers each reading in
order with a verdict or an error; errors are reported on the Twin's timeline with their code, so a
contract mismatch shows instead of failing in silence.
"""
from __future__ import annotations

from typing import Any

import httpx

from twin.events import EventLog
from twin.partners.guardian_dialect import GuardianDialect

MAX_BATCH = 1000   # the Guardian's limit per request


class GuardianPush:
    def __init__(self, url: str, api_key: str, dialect: GuardianDialect, events: EventLog) -> None:
        self.url, self.api_key, self.dialect, self.events = url, api_key, dialect, events

    def judges(self, reading: dict[str, Any]) -> bool:
        """False for a reading the Guardian will have no verdict on. With no Guardian configured, nothing is withheld."""
        return not self.url or self.dialect.judges(reading)

    async def push(self, client: httpx.AsyncClient, readings: list[dict[str, Any]]) -> None:
        if not self.url:
            return
        envelopes = [e for r in readings for e in self.dialect.render(r)]
        if not envelopes:
            return
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        refused: list[dict[str, Any]] = []
        for start in range(0, len(envelopes), MAX_BATCH):
            batch = envelopes[start:start + MAX_BATCH]
            try:
                resp = await client.post(self.url, json=batch, headers=headers)
            except httpx.HTTPError as exc:
                self.events.emit("delivery_failed", f"guardian unreachable: {type(exc).__name__}", target="guardian",
                                 count=len(envelopes), error=str(exc)[:200])
                return
            if resp.status_code >= 400:
                self.events.emit("delivery_failed", f"guardian refused the batch: HTTP {resp.status_code}", target="guardian",
                                 count=len(batch), error=resp.text[:300])
                return
            results = _results(resp)
            refused += [{"sensor_id": e["sensor_id"], **r["error"]} for e, r in zip(batch, results) if isinstance(r, dict) and "error" in r]
        if refused:
            first = refused[0]
            self.events.emit("delivery_failed", f"guardian refused {len(refused)}/{len(envelopes)} readings: "
                                                f"{first.get('error')} ({first.get('sensor_id')}: {first.get('message', '')})"[:300],
                             target="guardian", count=len(refused), first_error=first)
        else:
            self.events.emit("reading_emitted", f"feed sent to Guardian: {len(envelopes)} readings", target="guardian",
                             count=len(envelopes))


def _results(resp: httpx.Response) -> list[Any]:
    try:
        body = resp.json()
    except ValueError:
        return []
    return body.get("results", []) if isinstance(body, dict) else []
