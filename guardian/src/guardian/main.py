"""App factory: wires config, clock, state, detectors, trust, actuator watch, threat, containment and audit,
then mounts the Brain-facing API. `python -m guardian.main` runs it under uvicorn."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from guardian.actuator_watch.call_auditor import CallAuditor
from guardian.actuator_watch.effect_verifier import EffectVerifier
from guardian.adapters.brain_api import install
from guardian.adapters.twin_client import TwinClient, make_twin_client
from guardian.audit.logger import AuditLogger
from guardian.audit.timeline_emitter import TimelineEmitter
from guardian.clock import Clock, SystemClock
from guardian.config import ConfigError, GuardianConfig, Settings, load_config, require_secrets
from guardian.containment.manager import ContainmentManager
from guardian.detectors.authenticity import AuthenticityDetector
from guardian.detectors.crosscheck import CrosscheckDetector
from guardian.detectors.dynamics import DynamicsDetector
from guardian.detectors.freshness import FreshnessDetector
from guardian.detectors.liveness_rate import LivenessDetector
from guardian.detectors.patterns.baseline import BaselineModel
from guardian.detectors.plausibility import PlausibilityDetector
from guardian.detectors.semantic_plausibility import SemanticDetector
from guardian.ingest.pipeline import Pipeline
from guardian.ingest.state_store import SqliteStore, StateStore
from guardian.threat.alerts import AlertBus
from guardian.threat.attack_catalogue import AttackCatalogue
from guardian.threat.correlator import Correlator
from guardian.threat.threat_level import ThreatLevels
from guardian.trust.scorer import Scorer
from guardian.trust.signer import Signer
from guardian.trust.verdict_engine import VerdictEngine

log = structlog.get_logger("guardian")


class Guardian:
    """Holds every component. Background work is exposed as `tick()` so tests drive it with a FakeClock."""

    def __init__(self, cfg: GuardianConfig, settings: Settings, clock: Clock | None = None,
                 twin: TwinClient | None = None) -> None:
        require_secrets(settings)
        self.cfg, self.settings = cfg, settings
        self.clock = clock or SystemClock()
        g, t = cfg.guardian, cfg.thresholds
        self.emitter = TimelineEmitter()
        self.audit = AuditLogger(g.audit.log_dir, g.audit.file_prefix, self.clock, self.emitter)
        self.db = SqliteStore(g.storage.db_path)
        self.state = StateStore(self.db, g.storage.history_size, g.verdict.lru_size)
        self.twin = twin or make_twin_client(g.twin, self.clock)
        self.signer = Signer(settings.guardian_hmac_key)
        self.levels = ThreatLevels(cfg.attacks.threat_levels.quiet_period_s, self.clock, self.audit, self.db)
        self.alerts = AlertBus(self.clock, self.emitter, self.audit, self.levels)
        self.catalogue = AttackCatalogue(cfg.attacks)
        self.correlator = Correlator(self.catalogue, self.levels, self.alerts, self.clock, self.audit,
                                     cfg.attacks.threat_levels.quiet_period_s)
        self.containment = ContainmentManager(self.db, cfg.policies.containment, self.twin, self.clock,
                                              self.audit, self.alerts)
        self.baseline = BaselineModel(self.db, t.baseline)
        self.correlator.containment = self.containment
        self.correlator.baseline = self.baseline
        self.verifier = EffectVerifier(cfg.policies, self.state, self.containment, self.alerts, self.audit,
                                       self.clock)
        self.containment.on_quarantine = self.verifier.watch_quarantine
        self.semantic = SemanticDetector(cfg.city)
        self.liveness = LivenessDetector(self.state, t, cfg.sensors, self.clock)
        ml = None
        if g.ml.enabled:
            from guardian.detectors.patterns.isolation_forest import IsolationForestDetector

            ml = IsolationForestDetector(g.ml, t, self.state)
        self.dynamics = DynamicsDetector(self.state, t, cfg.city, self.baseline, ml)
        self.engine = VerdictEngine(self.state, self.signer, self.clock, g.verdict.ttl_s, self.emitter, self.audit)
        self.engine.learners.append(self.dynamics)
        if ml is not None:
            self.engine.learners.append(ml)
        self.pipeline = Pipeline(
            cfg, self.clock, self.state, self.audit,
            AuthenticityDetector(cfg.sensors, g.contract_version, Signer(settings.twin_hmac_key)),
            FreshnessDetector(self.state, self.clock, t.max_clock_skew_s),
            PlausibilityDetector(t), self.semantic, self.dynamics,
            CrosscheckDetector(self.state, t, cfg.crosschecks, self.containment.is_contained),
            self.liveness, Scorer(t.scoring), self.engine, self.correlator, self.containment, self.levels,
            self.verifier)
        self.auditor = CallAuditor(cfg.policies, cfg.city, cfg.crosschecks, self.state, self.containment,
                                   self.semantic, self.twin, self.verifier, self.correlator, self.audit, self.clock)
        self.twin_reachable: bool | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self.audit.emit("system", f"guardian started (transport={g.twin.transport}, mode={g.twin.mode})",
                        data={"kind": "startup", "version": g.service.version,
                              "contract_version": g.contract_version})

    # ---------- background work
    async def tick(self) -> None:
        """One pass of periodic work: liveness, effect verification, threat hysteresis."""
        try:
            for s in self.liveness.tick():
                self.audit.emit("system", f"sensor {s.sensor_id} stale (no reading in 2x interval)",
                                sensor_id=s.sensor_id, zone_id=s.zone_id, data={"kind": "sensor_stale"})
            await self.verifier.tick()
            self.correlator.tick()
        except Exception as e:  # fail safe
            self.audit.emit("error", f"tick failed: {e}"[:300], data={"kind": "tick_error"})

    async def check_twin(self) -> None:
        reachable = await self.twin.health()
        if reachable != self.twin_reachable:
            self.audit.emit("system", f"twin {'reachable' if reachable else 'unreachable'}",
                            data={"kind": "twin_health", "reachable": reachable})
        self.twin_reachable = reachable

    async def _loop(self, every: float, fn: Any) -> None:
        while True:
            await self.clock.sleep(every)
            with contextlib.suppress(Exception):
                await fn()

    async def _ingest_callback(self, items: list[dict[str, Any]]) -> None:
        await self.pipeline.ingest_many(items, source="twin")

    def start_background(self) -> None:
        g = self.cfg.guardian
        self._tasks.append(asyncio.create_task(self._loop(g.background.tick_s, self.tick)))
        self._tasks.append(asyncio.create_task(self._loop(g.twin.health_interval_s, self.check_twin)))
        if g.twin.mode == "pull" or g.twin.transport == "mqtt":
            self._tasks.append(asyncio.create_task(self.twin.run_ingest(self._ingest_callback)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        with contextlib.suppress(Exception):
            await self.twin.close()
        self.audit.close()

    # ---------- health
    def twin_status(self) -> str:
        sensors = [s for s in self.state.sensors.values() if self.liveness.interval(s) is not None]
        if self.twin_reachable is False:
            return "degraded"
        if not sensors:
            return "unknown"
        live = [s for s in sensors if not self.liveness.is_stale(s)]
        if not live:
            return "degraded"
        return "ok" if len(live) == len(sensors) else "partial"

    def health(self) -> dict[str, Any]:
        g = self.cfg.guardian
        twin = self.twin_status()
        return {
            "status": "ok" if twin in ("ok", "unknown", "partial") else "degraded",
            "version": g.service.version,
            "contract_version": g.contract_version,
            "config_dir": str(self.cfg.config_dir),
            "transport": {"twin": g.twin.transport, "mode": g.twin.mode, "reachable": self.twin_reachable},
            "twin": twin,
            "sensors": {"known": len(self.state.sensors),
                        "stale": sum(1 for s in self.state.sensors.values() if self.liveness.is_stale(s))},
            "threat": self.levels.snapshot(),
        }


def create_app(config_dir: str | None = None, *, settings: Settings | None = None, clock: Clock | None = None,
               twin: TwinClient | None = None, background: bool = True) -> FastAPI:
    settings = settings or Settings()
    cfg = load_config(config_dir, settings)
    guardian = Guardian(cfg, settings, clock, twin)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if background:
            guardian.start_background()
        yield
        await guardian.stop()

    app = FastAPI(title="Guardian", version=cfg.guardian.service.version, lifespan=lifespan,
                  description="Trust layer between the city Twin and the City Brain. Contract 1.0.")
    app.state.guardian = guardian
    install(app, guardian)
    return app


def run() -> None:
    import uvicorn

    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.processors.JSONRenderer()])
    settings = Settings()
    try:
        cfg = load_config(None, settings)
        app = create_app(settings=settings)
    except ConfigError as e:
        print(f"guardian: refusing to start: {e}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(app, host=cfg.guardian.service.host, port=cfg.guardian.service.port)


if __name__ == "__main__":
    run()
