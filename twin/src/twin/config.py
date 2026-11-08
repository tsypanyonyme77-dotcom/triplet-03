"""Runtime configuration. Everything partner-facing comes from environment variables, never hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Partners: base addresses (their GET /events feeds the timeline) and where readings and
    # notifications go. An empty string disables that link.
    guardian_url: str = ""
    brain_url: str = ""
    guardian_ingest_url: str = ""
    brain_notify_url: str = ""
    # How readings reach the Guardian: "guardian-v1" = its contract 1.0, batches to /v1/readings (the real
    # Guardian); "twin" = our own envelopes, one POST each (the mock Guardian in twin/mocks)
    guardian_dialect: str = "twin"
    guardian_push_api_key: str = ""   # the Twin's key on the Guardian (its TWIN_API_KEY)
    # The City Brain's timeline screen takes our events here (R3); the token is its TWIN_PUSH_TOKEN, if it asks for one
    brain_events_url: str = ""
    brain_push_token: str = ""
    # Security. Each layer has its own key, so `requesting_layer` is checked and not just claimed.
    # All empty = auth disabled (tests only).
    hmac_key: str = "dev-only-hmac-key"
    brain_api_key: str = ""
    guardian_api_key: str = ""
    brain_hmac_secret: str = ""   # the City Brain signs its actuator calls with this (its BRAIN_HMAC_SECRET)
    tools_api_key: str = ""       # required on the Guardian's POST /tools/{action} when set
    operator_key: str = ""  # demo controls and the timeline; empty = open
    # MCP (the City Brain's default carrier): Host headers accepted at /mcp; empty = any
    mcp_allowed_hosts: tuple[str, ...] = ("127.0.0.1:*", "localhost:*", "twin:*", "twin")
    # Emission
    emit_enabled: bool = True
    emit_interval_s: float = 1.0
    # The city (twin.world.scenarios.CityParams checks the ranges)
    scenario: str = "city"
    seed: int | None = None
    cars: int = 20
    pedestrians: int = 40
    car_crash_risk: float = 0.1
    ped_hit_risk: float = 0.1
    fire_risk: float = 0.0
    flood_risk: float = 0.0
    decision: str = "student"  # who picks the places road users go to: student (model) | random
    # The real-time clock and the frame stream; off only in tests that step the city themselves
    live: bool = True
    live_speed: float = 1.0
    # Logs
    log_dir: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        seed = os.environ.get("TWIN_SEED")
        guardian = os.environ.get("GUARDIAN_URL", "").rstrip("/")
        brain = os.environ.get("BRAIN_URL", "").rstrip("/")
        dialect = os.environ.get("GUARDIAN_DIALECT", "guardian-v1")
        if dialect not in ("guardian-v1", "twin"):
            raise ValueError(f"GUARDIAN_DIALECT must be 'guardian-v1' or 'twin', got {dialect!r}")
        ingest_path = "/v1/readings" if dialect == "guardian-v1" else "/ingest"
        hosts = os.environ.get("TWIN_MCP_ALLOWED_HOSTS")
        events_url = os.environ.get("BRAIN_EVENTS_URL")
        return cls(
            guardian_url=guardian,
            brain_url=brain,
            guardian_ingest_url=os.environ.get("GUARDIAN_INGEST_URL") or (f"{guardian}{ingest_path}" if guardian else ""),
            # the real City Brain polls for readings; only the mock wants to be told (set BRAIN_NOTIFY_URL for it)
            brain_notify_url=os.environ.get("BRAIN_NOTIFY_URL", ""),
            guardian_dialect=dialect,
            guardian_push_api_key=os.environ.get("TWIN_API_KEY", ""),
            # unset: the real City Brain's route; empty: off (the mock has no such route)
            brain_events_url=(f"{brain}/api/events" if brain else "") if events_url is None else events_url,
            brain_push_token=os.environ.get("TWIN_PUSH_TOKEN", ""),
            # one Twin signing key, under the name the triplet uses (TWIN_HMAC_SECRET) or the Guardian's (TWIN_HMAC_KEY)
            hmac_key=os.environ.get("TWIN_HMAC_SECRET") or os.environ.get("TWIN_HMAC_KEY") or cls.hmac_key,
            brain_api_key=os.environ.get("TWIN_BRAIN_API_KEY", ""),
            guardian_api_key=os.environ.get("TWIN_GUARDIAN_API_KEY", ""),
            brain_hmac_secret=os.environ.get("BRAIN_HMAC_SECRET", ""),
            tools_api_key=os.environ.get("TWIN_TOOLS_API_KEY", ""),
            mcp_allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()) if hosts is not None else cls.mcp_allowed_hosts,
            operator_key=os.environ.get("TWIN_OPERATOR_KEY", ""),
            emit_interval_s=float(os.environ.get("TWIN_EMIT_INTERVAL_S", cls.emit_interval_s)),
            scenario=os.environ.get("TWIN_SCENARIO", cls.scenario),
            seed=int(seed) if seed else None,
            cars=int(os.environ.get("TWIN_CARS", cls.cars)),
            pedestrians=int(os.environ.get("TWIN_PEDESTRIANS", cls.pedestrians)),
            car_crash_risk=float(os.environ.get("TWIN_CAR_CRASH_RISK", cls.car_crash_risk)),
            ped_hit_risk=float(os.environ.get("TWIN_PED_HIT_RISK", cls.ped_hit_risk)),
            fire_risk=float(os.environ.get("TWIN_FIRE_RISK", cls.fire_risk)),
            flood_risk=float(os.environ.get("TWIN_FLOOD_RISK", cls.flood_risk)),
            decision=os.environ.get("TWIN_DECISION", cls.decision),
            live_speed=float(os.environ.get("TWIN_LIVE_SPEED", cls.live_speed)),
            log_dir=os.environ.get("LOG_DIR", ""),
        )
