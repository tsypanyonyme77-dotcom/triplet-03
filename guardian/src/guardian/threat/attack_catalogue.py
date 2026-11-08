"""Attack-pattern catalogue loaded from attack_patterns.yaml, plus the human text for each response."""

from __future__ import annotations

from guardian.config import AttackPatterns, Pattern

SUGGESTED = {
    "block_and_flag_source": "replayed data blocked; source flagged; do not act on it",
    "isolate_and_rollback": "sensor isolated; use the rolled-back last-known-good value",
    "zone_high_distrust": "zone under attack: act only on readings corroborated by 2+ sources",
    "rate_limit_and_throttle": "throttling the source; corroborate calls before dispatching",
    "reject_and_alert_key_compromise": "possible key compromise: rotate TWIN_HMAC_KEY",
    "block_and_quarantine_caller": "caller quarantined for actuator calls without a valid trust_ref",
    "alert_and_freeze_baseline": "baseline frozen for this sensor; inspect it for slow poisoning",
    "brain_safe_mode": "corroboration collapsing city-wide: fall back to safe mode",
    "keep_acting_on_trusted_data": "real incident in progress: keep acting on trusted data only, ignore the rest",
    "use_backup_actuator": "actuator did not perform: use a backup actuator or a unit dispatch",
    "isolation_cap_reached": "isolation cap reached in zone: manual review, not more isolations",
}


class AttackCatalogue:
    def __init__(self, cfg: AttackPatterns) -> None:
        self.patterns = cfg.patterns

    def listening(self, signal_type: str) -> list[tuple[str, Pattern]]:
        return [(n, p) for n, p in self.patterns.items() if p.kind == "generic" and signal_type in p.signals]

    def special(self, kind: str) -> tuple[str, Pattern] | None:
        return next(((n, p) for n, p in self.patterns.items() if p.kind == kind), None)

    @staticmethod
    def suggested(response: str) -> str:
        return SUGGESTED.get(response, response)
