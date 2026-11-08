"""Is the hosted model still answering? Tells the screen, and sends the team to its scripted stand-ins at once when it is not.

A key that is rejected, a day's quota that is spent, a minute's rate limit and a lost connection all look like an exception from
the model client, and each used to cost a deliberation its whole 30 s budget before the scripted stand-in took over. Here the
first failure is classified, the model is skipped for a cool-down that fits the cause, and one call is let through afterwards to
see whether it is back. A person can also force the scripted team from the screen. Nothing here touches a decision: the team
that runs is the only thing that changes, and the gate checks either team's proposals the same way.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

# Seconds to leave the model alone after each kind of failure. A rate limit on the free plan is per minute; a spent day or a
# rejected key will not mend in the minutes a demo lasts, so those are probed rarely.
COOL_DOWN_S = {"key_rejected": 300.0, "quota_exhausted": 300.0, "rate_limited": 65.0, "unreachable": 15.0}
TRIP_AFTER = {"key_rejected": 1, "quota_exhausted": 1, "rate_limited": 1, "unreachable": 2}  # consecutive failures that trip it
WORDS = {
    "key_rejected": "the API key was rejected",
    "quota_exhausted": "the day's quota is spent",
    "rate_limited": "the per-minute limit was hit",
    "unreachable": "the model service cannot be reached",
}


class LLMDown(RuntimeError):
    """Raised instead of a model call while the model is being left alone."""


class ProbeError(Exception):
    def __init__(self, status_code: int, text: str) -> None:
        super().__init__(f"HTTP {status_code}: {text[:200]}")
        self.status_code = status_code


def classify(error: BaseException) -> str | None:
    """Which kind of outage an exception from the model client is. None: not an outage (a bad answer is not a dead model)."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None)
        text = str(current).lower()
        if status in (401, 403) or "invalid api key" in text or "invalid_api_key" in text:
            return "key_rejected"
        if status == 429 or "rate limit" in text or "rate_limit" in text:
            return "quota_exhausted" if ("per day" in text or "(tpd)" in text or "(rpd)" in text or "quota" in text) else "rate_limited"
        if (isinstance(status, int) and status >= 500) or type(current).__name__ in ("APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout", "ConnectTimeout"):
            return "unreachable"
        current = current.__cause__ or current.__context__
    return None


class LLMHealth:
    def __init__(self, emit: Callable[..., Any] | None = None, *, now: Callable[[], float] = time.monotonic) -> None:
        self.emit, self._now = emit, now
        self.reason: str | None = None  # None while the model is trusted to answer
        self.forced = False  # a person chose the scripted team
        self._until = 0.0
        self._streak = 0
        self._announced: tuple[str, str | None] | None = None

    @property
    def state(self) -> str:
        return "scripted" if self.forced else "down" if self.reason else "live"

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "why": WORDS.get(self.reason or "", None), "forced": self.forced}

    def gate(self) -> None:
        """Called before a model call. Raises while the model is left alone; lets one call through when the cool-down is over."""
        if self.forced:
            raise LLMDown("the scripted team was chosen by a person")
        if self.reason and self._now() < self._until:
            raise LLMDown(f"{WORDS[self.reason]}; using the scripted team")

    def ok(self) -> None:
        self._streak = 0
        if self.reason:
            self.reason = None
            self.announce()

    def failed(self, error: BaseException) -> None:
        kind = classify(error)
        if kind is None:
            return
        self._streak += 1
        if self._streak >= TRIP_AFTER[kind]:
            self.reason, self._until = kind, self._now() + COOL_DOWN_S[kind]
            self.announce()

    def force(self, scripted: bool) -> None:
        self.forced = scripted
        self.announce()

    def announce(self, *, again: bool = False) -> None:
        """Say the state on the timeline when it changed (or `again`, for a screen that was cleared)."""
        mark = (self.state, self.reason)
        if self.emit is not None and (again or mark != self._announced):
            self.emit("brain.llm.status", None, {"state": self.state, "reason": self.reason, "why": WORDS.get(self.reason or "", None)})
        self._announced = mark


async def probe(model: str, api_key: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    """One one-token call to a Groq model. Raises ProbeError on a refusal; returns what is left of the limits."""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        reply = await client.post(
            "https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1})
    if reply.status_code != 200:
        raise ProbeError(reply.status_code, reply.text)
    return {"remaining_tokens": reply.headers.get("x-ratelimit-remaining-tokens"), "remaining_requests": reply.headers.get("x-ratelimit-remaining-requests")}


async def probe_into(health: LLMHealth, model: str, api_key: str) -> dict[str, Any]:
    """Probe and record the result, so the screen learns of an outage before the next deliberation does."""
    try:
        left = await probe(model, api_key)
    except ProbeError as error:
        health.failed(error)
        return {"ok": False, "error": str(error), **health.snapshot()}
    except httpx.HTTPError as error:
        health.failed(error)
        return {"ok": False, "error": f"{type(error).__name__}", **health.snapshot()}
    health.ok()
    return {"ok": True, **left, **health.snapshot()}
