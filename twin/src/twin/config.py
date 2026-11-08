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
    # Security. Each layer has its own key, so `requesting_layer` is checked and not just claimed.
    # All empty = auth disabled (tests only).
    hmac_key: str = "dev-only-hmac-key"
    brain_api_key: str = ""
    guardian_api_key: str = ""
    operator_key: str = ""  # demo controls and the timeline; empty = open
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
        return cls(
            guardian_url=guardian,
            brain_url=brain,
            guardian_ingest_url=os.environ.get("GUARDIAN_INGEST_URL") or (f"{guardian}/ingest" if guardian else ""),
            brain_notify_url=os.environ.get("BRAIN_NOTIFY_URL") or (f"{brain}/notify" if brain else ""),
            hmac_key=os.environ.get("TWIN_HMAC_KEY", cls.hmac_key),
            brain_api_key=os.environ.get("TWIN_BRAIN_API_KEY", ""),
            guardian_api_key=os.environ.get("TWIN_GUARDIAN_API_KEY", ""),
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
