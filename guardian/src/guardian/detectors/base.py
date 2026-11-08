"""Detector protocol and LayerResult helpers shared by every layer."""

from __future__ import annotations

from typing import Protocol

from guardian.models import LayerResult, Reading, Severity

L1, L2, L3A, L3B, L4, L5, L6, ML = (
    "L1_authenticity", "L2_freshness", "L3a_plausibility", "L3b_semantic",
    "L4_dynamics", "L5_corroboration", "L6_liveness", "ML_pattern",
)


class Detector(Protocol):
    layer: str

    def check(self, reading: Reading) -> list[LayerResult]: ...


def ok(layer: str, detail: str = "", reason: str | None = None) -> LayerResult:
    return LayerResult(layer=layer, passed=True, severity="info", reason_code=reason, detail=detail)


def fail(layer: str, severity: Severity, reason: str, detail: str) -> LayerResult:
    return LayerResult(layer=layer, passed=False, severity=severity, reason_code=reason, detail=detail)
