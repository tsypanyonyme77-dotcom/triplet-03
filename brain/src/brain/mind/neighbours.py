"""Coupled sensors: two gauges that should move together.

A single sensor's own baseline follows a slow creep, so a plausible, signed drift from one sensor is invisible to it.
Two sensors that measure one thing are different: the *difference* between them is steady while they move together,
and moves when only one does. This module keeps that difference as a forward model of its own, followed slowly, and a
reading whose difference with a coupled partner is a surprise is *disputed*: held as doubted for as long as the
disagreement lasts (a doubted reading holds the reflex that would act on it), until the two agree again or another kind
of source corroborates. The Twin's team says which sensors are coupled; nothing here infers it from the map.

Only readings the Guardian trusted are compared. When two coupled sensors disagree, the one that moved away from
its own slow reference is the one held; if neither clearly did, the reading being read is held, the cautious side.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from pydantic import BaseModel

from brain.config import ForwardPolicy
from brain.contracts import SensorReading
from brain.mind.forward import MODELLED, ForwardModels, Surprise


class NeighbourModels:
    def __init__(self, policy: ForwardPolicy, forward: ForwardModels) -> None:
        self.policy, self.forward = policy, forward
        self.groups = [set(group) for group in policy.coupled]
        # A difference is never "accepted as a new normal": a creep must not be able to become one.
        self.pairs = ForwardModels(policy.model_copy(update={
            "alpha": policy.coupled_alpha, "adopt_after": 10**9, "recover": False, "calibration": "fixed",
            "effects": {}, "coupled": [], "freeze_spread": True,
        }))
        # Each sensor against its own slow reference: who moved, when two disagree.
        self.solo = ForwardModels(self.pairs.policy)
        self._moved: dict[tuple[str, str], bool] = {}
        self._last: dict[tuple[str, str], tuple[datetime, float]] = {}
        self._count: dict[str, int] = {}

    def observe(self, reading: SensorReading, value: BaseModel, trusted: bool) -> list[Surprise]:
        if not trusted or reading.type not in MODELLED or not any(reading.sensor_id in group for group in self.groups):
            return []
        found: list[Surprise] = []
        moved = {own.field for own in self.solo.observe(reading, value, True)}
        for field_name in MODELLED[reading.type]:
            self._moved[(reading.sensor_id, field_name)] = field_name in moved
            x = getattr(value, field_name, None)
            if x is None or isinstance(x, bool):
                continue
            x = float(x)
            self._last[(reading.sensor_id, field_name)] = (reading.timestamp, x)
            partners = sorted({other for group in self.groups if reading.sensor_id in group for other in group} - {reading.sensor_id})
            for other in partners:
                seen = self._last.get((other, field_name))
                if seen is None or abs((reading.timestamp - seen[0]).total_seconds()) > self.policy.coupled_window_s:
                    continue
                first, second = sorted((reading.sensor_id, other))
                x_first, x_second = (x, seen[1]) if reading.sensor_id == first else (seen[1], x)
                pair_id = f"{first}~{second}"
                self._count[pair_id] = self._count.get(pair_id, 0) + 1
                pair_reading = reading.model_copy(update={"sensor_id": pair_id, "sequence_no": self._count[pair_id]})
                for surprise in self.pairs.observe(pair_reading, SimpleNamespace(**{field_name: x_first - x_second}), True):
                    if not self._moved[(reading.sensor_id, field_name)] and self._moved.get((other, field_name), False):
                        continue  # the partner is the one that moved away from its own reference: this reading is fine
                    self.forward.dispute(reading.reading_id)
                    shift = surprise.expected if reading.sensor_id == first else -surprise.expected
                    found.append(Surprise(
                        reading.sensor_id, field_name, x, round(seen[1] + shift, 4), surprise.spread, surprise.z, run=surprise.run,
                        doubted=True, rebaselined=False, kind="neighbour", neighbour=other,
                    ))
        return found
