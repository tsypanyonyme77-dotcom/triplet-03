"""Isolation guardrail: at most max_isolations_per_zone, so a fake attack cannot get our healthy sensors cut."""

from __future__ import annotations

from collections.abc import Iterable

from guardian.models import ContainmentRecord


def isolation_allowed(records: Iterable[ContainmentRecord], zone_id: str | None, cap: int) -> bool:
    active = sum(1 for r in records if r.active and r.kind == "isolation" and r.zone_id == zone_id)
    return active < cap
