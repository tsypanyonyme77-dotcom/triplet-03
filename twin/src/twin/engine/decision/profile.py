"""Who a road user is: traits, role, and the places that belong to them (home, duty place)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from twin.engine.decision.schema import ANCHOR, ROLES, TRAITS


@dataclass(frozen=True)
class AgentProfile:
    traits: dict[str, float]
    role: str
    home_id: str | None
    anchor_id: str | None   # the workplace or school the role goes to by duty

    def describe(self) -> str:
        """A short label for logs and the viewer (this replaces the POC's persona sentence)."""
        top = sorted(self.traits.items(), key=lambda kv: -kv[1])[:2]
        return f"{self.role} ({', '.join(f'{k.replace('_', ' ')} {v:.1f}' for k, v in top)})"


def make_profile(entity_id: str, places: list[dict], seed: int) -> AgentProfile:
    """Deterministic for a (seed, entity id): the same run gives the same people."""
    rng = random.Random(f"{seed}:{entity_id}")
    traits = {t: round(rng.random(), 2) for t in TRAITS}
    role = rng.choice(ROLES)
    homes = [p for p in places if p["category"] == "home"]
    duty = [p for p in places if p["category"] == ANCHOR.get(role)]
    return AgentProfile(
        traits=traits,
        role=role,
        home_id=rng.choice(homes)["id"] if homes else None,
        anchor_id=rng.choice(duty)["id"] if duty else None,
    )
