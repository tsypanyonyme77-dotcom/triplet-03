"""Optional Isolation Forest per sensor type (ml.enabled, needs scikit-learn). Trained only on trusted readings;
it can lower trust (ML_pattern, low severity), never make a reading trusted."""

from __future__ import annotations

from collections import deque
from typing import Any

from guardian.config import MlCfg, Thresholds
from guardian.detectors.base import ML, fail
from guardian.ingest.state_store import SensorState, StateStore
from guardian.models import LayerResult, Reading


class IsolationForestDetector:
    layer = ML

    def __init__(self, cfg: MlCfg, t: Thresholds, state: StateStore) -> None:
        try:
            from sklearn.ensemble import IsolationForest
        except ImportError as e:
            raise RuntimeError("ml.enabled needs the optional dependency: pip install 'guardian[ml]'") from e
        self._cls = IsolationForest
        self.cfg, self.t, self.state = cfg, t, state
        self.samples: dict[str, deque[list[float]]] = {}
        self.models: dict[str, Any] = {}
        self._since_fit: dict[str, int] = {}

    def features(self, r: Reading, s: SensorState | None) -> list[float]:
        out = []
        for f in self.t.fields.get(r.sensor_type, {}):
            x = r.value.get(f)
            if isinstance(x, int | float) and not isinstance(x, bool):
                prev = s.lkg.value.get(f, x) if s and s.lkg else x
                out += [float(x), abs(float(x) - float(prev))]
        return out

    def learn(self, r: Reading) -> None:
        x = self.features(r, self.state.get(r.sensor_id))
        if not x:
            return
        buf = self.samples.setdefault(r.sensor_type, deque(maxlen=self.cfg.min_train * 5))
        buf.append(x)
        n = self._since_fit[r.sensor_type] = self._since_fit.get(r.sensor_type, 0) + 1
        if len(buf) >= self.cfg.min_train and (r.sensor_type not in self.models or n >= self.cfg.min_train):
            model = self._cls(contamination=self.cfg.contamination, random_state=0)
            model.fit(list(buf))
            self.models[r.sensor_type] = model
            self._since_fit[r.sensor_type] = 0

    def check(self, r: Reading, s: SensorState | None) -> list[LayerResult]:
        model = self.models.get(r.sensor_type)
        x = self.features(r, s)
        if model is None or not x:
            return []
        score = float(model.decision_function([x])[0])
        if model.predict([x])[0] == -1:
            return [fail(ML, "low", "ml_anomaly", f"isolation-forest score {score:.3f} < 0 for {r.sensor_type}")]
        return []
