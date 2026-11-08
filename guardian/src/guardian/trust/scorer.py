"""Scorer: turns LayerResults into (status, trust_score, reasons). Hard gates first, then weights, caps and
threat-level tightening. Pattern/ML results can only lower trust."""

from __future__ import annotations

from dataclasses import dataclass, field

from guardian.config import Scoring
from guardian.detectors.base import L3A, L3B, L4, L5, L6, ML
from guardian.models import LayerResult, Status, ThreatLevel

INCONSISTENT = {"rate_of_change", "flatline", "slow_drift"}


@dataclass
class Score:
    status: Status
    score: float
    reasons: list[str] = field(default_factory=list)
    self_consistent: bool = False
    corroborated: bool = False


class Scorer:
    def __init__(self, cfg: Scoring) -> None:
        self.cfg = cfg

    def status_for(self, score: float) -> Status:
        c = self.cfg.cutoffs
        if score >= c.trusted:
            return Status.trusted
        return Status.suspect if score >= c.suspect else Status.untrusted

    def score(self, results: list[LayerResult], threat: ThreatLevel = ThreatLevel.normal,
              agreeing_sources: int = 0) -> Score:
        failed = [r for r in results if not r.passed]
        reasons = list(dict.fromkeys(r.reason_code for r in failed if r.reason_code))
        if any(r.severity in ("hard", "impossible") for r in failed):
            return Score(Status.untrusted, 0.0, reasons)

        w = self.cfg.weights
        by_layer = {r.layer for r in failed}
        l5_pass = any(r.layer == L5 and r.passed and r.reason_code == "corroborated" for r in results)
        l5_strong_fail = any(r.layer == L5 and r.severity == "strong" for r in failed)
        score = 1.0
        if L3A in by_layer:
            score += w.plausibility_fail
        if L3B in by_layer:
            score += w.semantic_suspect
        if L4 in by_layer:
            score += w.dynamics_fail
        if L6 in by_layer:
            score += w.liveness_fail
        if ML in by_layer:
            score += w.pattern_fail
        if l5_strong_fail:
            score += w.corroboration_fail
        elif l5_pass:
            score += w.corroboration_pass
        score = round(min(1.0, max(0.0, score)), 4)

        # self-consistent = no evidence of lying on its own (range, context, jumps, frozen), whatever its
        # neighbours said. Merely *unusual* (z-score, baseline) still counts: real events are unusual.
        self_consistent = not ({L3A, L3B, ML} & by_layer) and not any(
            r.layer == L4 and r.reason_code in INCONSISTENT for r in failed)
        cap = (
            L3B in by_layer
            or L6 in by_layer
            or any(r.reason_code == "flatline" for r in failed)
            or (L4 in by_layer and not l5_pass)
            or any(r.layer == L5 and r.severity == "low" for r in failed)
        )
        tight = self.cfg.tightened
        if threat.rank >= ThreatLevel.elevated.rank and (
            score < tight.trusted_min_score or agreeing_sources < tight.min_corroborating_sources
        ):
            if self.status_for(score) == Status.trusted:
                reasons.append("threat_level_tightened")
            cap = True
        if cap and score >= self.cfg.cutoffs.trusted:
            score = round(self.cfg.cutoffs.trusted - 0.01, 4)
        return Score(self.status_for(score), score, reasons, self_consistent, l5_pass)
