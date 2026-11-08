"""Hour-of-day baseline per sensor/field (Welford mean/std), learned only from trusted readings, freezable.

Also tracks slow drift: a long run of same-sign deviations from the baseline (poisoning defence)."""

from __future__ import annotations

import json
import math
from collections import deque
from datetime import datetime
from pathlib import Path

from guardian.config import BaselineCfg
from guardian.ingest.state_store import SqliteStore


class BaselineModel:
    def __init__(self, db: SqliteStore, cfg: BaselineCfg) -> None:
        self.db, self.cfg = db, cfg
        self.buckets: dict[tuple[str, str, int], list[float]] = {
            (s, f, h): [n, mean, m2] for s, f, h, n, mean, m2 in db.baselines()
        }
        self.frozen: set[str] = set(db.get_kv("baseline_frozen", []))
        self._dev: dict[tuple[str, str], deque[float]] = {}

    def update(self, sensor_id: str, field: str, hour: int, x: float) -> None:
        if sensor_id in self.frozen:
            return
        b = self.buckets.setdefault((sensor_id, field, hour), [0, 0.0, 0.0])
        b[0] += 1
        d = x - b[1]
        b[1] += d / b[0]
        b[2] += d * (x - b[1])
        self.db.put_baseline(sensor_id, field, hour, int(b[0]), b[1], b[2])

    def zscore(self, sensor_id: str, field: str, hour: int, x: float, floor: float) -> float | None:
        b = self.buckets.get((sensor_id, field, hour))
        if not b or b[0] < self.cfg.min_samples:
            return None
        std = max(math.sqrt(b[2] / (b[0] - 1)), floor, 1e-9)
        return (x - b[1]) / std

    def observe_deviation(self, sensor_id: str, field: str, z: float) -> bool:
        """True when the recent window shows a consistent one-directional drift that stays *under* the
        outlier threshold (that is what evades the other checks). A big deviation is an event, not drift."""
        dq = self._dev.setdefault((sensor_id, field), deque(maxlen=self.cfg.drift_window))
        if abs(z) > self.cfg.sigma:
            dq.clear()
            return False
        dq.append(z)
        if len(dq) < self.cfg.drift_window:
            return False
        mean = sum(dq) / len(dq)
        same = sum(1 for v in dq if (v > 0) == (mean > 0)) / len(dq)
        return abs(mean) >= self.cfg.drift_sigma and same >= self.cfg.drift_fraction

    def freeze(self, sensor_id: str) -> None:
        self.frozen.add(sensor_id)
        self.db.put_kv("baseline_frozen", sorted(self.frozen))

    def export(self, directory: str | Path, now: datetime) -> Path:
        """Write a versioned snapshot to config/baselines/ for review and reuse."""
        path = Path(directory) / f"baseline-{now:%Y%m%dT%H%M%S}.json"
        rows = [{"sensor_id": s, "field": f, "hour": h, "n": b[0], "mean": b[1],
                 "std": math.sqrt(b[2] / (b[0] - 1)) if b[0] > 1 else 0.0}
                for (s, f, h), b in sorted(self.buckets.items())]
        path.write_text(json.dumps({"frozen": sorted(self.frozen), "buckets": rows}, indent=1))
        return path
