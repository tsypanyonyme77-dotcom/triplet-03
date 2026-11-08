"""How sure are we that an incident is real? A sum of evidence, in log-odds, that can be read line by line.

Start from how often incidents of this type are real (the prior). Each independent witness adds the log of how much likelier its report is
if the incident is real than if it is not, taken from the Guardian's confidence in that reading; a reading the forward models doubt subtracts
instead. Two cameras in the same zone count as one witness or two according to the independence setting. The belief is advisory: it is shown,
never used to open the gate. The calibration table below says how far to trust the number; if it is poor the number is not shown.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from brain.contracts import VerdictStatus

PRIORS = {"crime": 0.35, "fire": 0.4, "accident": 0.4, "flood": 0.3, "jam": 0.5, "overload": 0.4, "smog": 0.4}
DEFAULT_PRIOR = 0.3
LR_MIN, LR_MAX = 1.2, 20.0  # a witness is never worthless and never worth more than 20 to 1


@dataclass
class Belief:
    p: float
    prior: float
    contributions: list[tuple[str, float]] = field(default_factory=list)

    @property
    def log_odds(self) -> float:
        return math.log(self.prior / (1 - self.prior)) + sum(c for _, c in self.contributions)


def _witness_weight(confidence: float) -> float:
    confidence = min(max(confidence, 0.01), 0.99)
    return math.log(min(max(confidence / (1 - confidence), LR_MIN), LR_MAX))


def belief(incident: Any, store: Any, doubted: Callable[[str], bool] | None = None, *, independence: str = "sensor") -> Belief:
    prior = PRIORS.get(incident.type, DEFAULT_PRIOR)
    by_witness: dict[str, float] = {}
    for reading_id in incident.evidence:
        verdict, reading = store.verdict_of(reading_id), store.reading(reading_id)
        if verdict is None or reading is None or verdict.status != VerdictStatus.TRUSTED:
            continue
        weight = _witness_weight(verdict.confidence) * (-1.0 if doubted is not None and doubted(reading_id) else 1.0)
        key = reading.zone_id if independence == "zone" else reading.sensor_id
        if key not in by_witness or abs(weight) > abs(by_witness[key]):  # a witness counts once, by its strongest reading
            by_witness[key] = weight
    contributions = sorted(by_witness.items())
    total = math.log(prior / (1 - prior)) + sum(w for _, w in contributions)
    return Belief(round(1 / (1 + math.exp(-total)), 4), prior, [(k, round(w, 4)) for k, w in contributions])


def calibration(seeds: list[int], bins: int = 5, cases: int = 200) -> list[dict[str, float]]:
    """A reliability table on synthetic incidents with a known truth. Witnesses report confidence 0.5 + a signal shifted toward the truth and noise,
    with a few confidently wrong ones; the table says, for each band of belief, how often the incident was in fact real. This checks that the number
    is not wildly over- or under-confident for witnesses like these; it says nothing about real witnesses until real data exists."""
    rows: list[tuple[float, bool]] = []
    for seed in seeds:
        rng = random.Random(seed)
        for _ in range(cases):
            real = rng.random() < 0.4
            witnesses = rng.choice((1, 2, 3))
            total = math.log(0.4 / 0.6)
            for _w in range(witnesses):
                said_real = rng.random() < (0.85 if real else 0.2)
                confidence = min(max(rng.gauss(0.8 if said_real else 0.35, 0.1), 0.05), 0.95)
                if said_real:
                    total += _witness_weight(confidence)
                else:
                    total -= _witness_weight(1 - confidence) * 0.5
            rows.append((1 / (1 + math.exp(-total)), real))
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [real for p, real in rows if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if inside:
            table.append({"band": f"{lo:.1f}-{hi:.1f}", "n": len(inside), "share_real": round(sum(inside) / len(inside), 3), "mean_belief": round(sum(p for p, _ in rows if lo <= p < hi) / max(len(inside), 1), 3)})
    return table
