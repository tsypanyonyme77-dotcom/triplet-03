"""Optional ML: trained on trusted data only, can only lower trust (skipped without scikit-learn)."""

from __future__ import annotations

import random

import pytest

from guardian.config import MlCfg
from tests.conftest import Harness
from tests.unit.helpers import reading

pytest.importorskip("sklearn")


def test_isolation_forest_lowers_trust_only(harness: Harness) -> None:
    from guardian.detectors.patterns.isolation_forest import IsolationForestDetector

    ml = IsolationForestDetector(MlCfg(enabled=True, min_train=200, contamination=0.02), harness.g.cfg.thresholds,
                                 harness.g.state)
    rng = random.Random(1)
    for i in range(250):
        ml.learn(reading(value={"level_m": 0.40 + rng.gauss(0, 0.005)}, seq=i))
    assert ml.check(reading(value={"level_m": 0.402}), None) == []
    res = ml.check(reading(value={"level_m": 2.5}), None)
    assert res and res[0].reason_code == "ml_anomaly" and res[0].severity == "low"
    assert ml.check(reading(sensor_type="emergency_call", value={}), None) == []
    sc = harness.g.pipeline.scorer.score(res)
    assert sc.status.value == "trusted" or sc.score <= 0.8  # -0.2 at most, never a raise


async def test_ml_enabled_wiring(tmp_path: object) -> None:
    from pathlib import Path

    from guardian.config import load_config
    from guardian.main import Guardian
    from tests.conftest import CONFIG_DIR, make_settings

    settings = make_settings(Path(str(tmp_path)))
    cfg = load_config(CONFIG_DIR, settings)
    cfg.guardian.ml.enabled = True
    g = Guardian(cfg, settings)
    assert g.dynamics.ml is not None and g.dynamics.ml in g.engine.learners
    await g.stop()
