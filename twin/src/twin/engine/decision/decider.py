"""Chooses where each road user goes next, with the student model.

Replaces the coin toss (`decide_randomly`) and the POC's per-decision LLM call. When the model
cannot score (not installed, bad file), the decider gives no place and the sim falls back to a
random one, so a missing model never stops the city.
"""
from __future__ import annotations

import logging
import random
from collections import deque

from twin.engine.decision.profile import AgentProfile, make_profile
from twin.engine.decision.situation import START_HOUR, build_situation, map_scale, place_here
from twin.engine.decision.student import Student

log = logging.getLogger(__name__)

HISTORY = 3        # past choices kept per road user, for the viewer
ALTERNATIVES = 3   # runners-up shown next to a choice


class Decider:
    def __init__(self, student: Student | None, seed: int = 0, temperature: float = 1.0,
                 start_hour: int = START_HOUR) -> None:
        """`temperature` above 1 flattens the choice (more variety), below 1 sharpens it."""
        self.student = student
        self.seed = seed
        self.temperature = temperature
        self.start_hour = start_hour
        self.profiles: dict[str, AgentProfile] = {}
        self._rng = random.Random(seed)   # its own stream: deciding does not change the traffic of a seed
        self._scale: float | None = None
        self.choices: dict[str, deque[dict]] = {}   # road user id -> its latest choices, newest last

    @classmethod
    def load(cls, seed: int = 0, **kwargs) -> "Decider":
        try:
            student = Student.load()
        except Exception as exc:  # noqa: BLE001  (missing xgboost, missing or mismatching model file)
            log.warning("decision model unavailable (%s); agents choose places at random", exc)
            student = None
        return cls(student, seed, **kwargs)

    def profile(self, entity, sim) -> AgentProfile:
        profile = self.profiles.get(entity.id)
        if profile is None:
            profile = self.profiles[entity.id] = make_profile(entity.id, sim.places, self.seed)
            entity.persona = profile.describe()
        return profile

    def choose(self, sim, entity, kind: str) -> tuple[str | None, str | None]:
        """(place id, reason), or (None, None) to let the sim pick randomly."""
        if self.student is None or not sim.places:
            return None, None
        if self._scale is None:
            self._scale = map_scale(sim.places)
        try:
            situation, places = build_situation(sim, entity, kind, self.profile(entity, sim), self._scale,
                                                self._rng, self.start_hour)
            if not places:
                return None, None
            weights = [max(float(s), 1e-6) ** (1.0 / self.temperature) for s in self.student.scores(situation)]
        except Exception:  # noqa: BLE001
            log.exception("decision failed for %s; choosing at random", entity.id)
            return None, None
        index = self._rng.choices(range(len(places)), weights)[0]
        place = places[index]
        total = sum(weights)
        runners_up = sorted((i for i in range(len(places)) if i != index), key=lambda i: -weights[i])
        self.choices.setdefault(entity.id, deque(maxlen=HISTORY)).append({
            "t": round(sim._sim_time, 1), "place_id": place["id"], "p": round(weights[index] / total, 3),
            "alternatives": [{"place_id": places[i]["id"], "p": round(weights[i] / total, 3)}
                             for i in runners_up[:ALTERNATIVES]],
        })
        return place["id"], f"{place['category'].replace('_', ' ')} (student model, p={weights[index] / total:.2f})"

    def decide(self, sim) -> None:
        """Every road user that is due a decision gets one."""
        for car in sim.cars_needing_decision():
            place_id, reason = self.choose(sim, car, "car")
            sim.apply_decision(car.id, place_id, reason)
        for ped in sim.pedestrians_needing_decision():
            place_id, reason = self.choose(sim, ped, "pedestrian")
            sim.apply_pedestrian_decision(ped.id, place_id, reason)

    def agents(self, sim) -> list[dict]:
        """Everyone on the road, for the viewer: who they are, where they stand, where they are
        heading and why. Someone not yet decided has no destination."""
        by_id = {pl["id"]: pl for pl in sim.places}
        brief = lambda pl: {"id": pl["id"], "name": pl["name"], "category": pl["category"]}  # noqa: E731
        out = []
        for kind, entities in (("car", sim.cars), ("pedestrian", sim.pedestrians)):
            for entity in list(entities.values()):
                profile = self.profile(entity, sim)
                here, at_place = place_here(sim.places, entity.x, entity.y)
                history = list(self.choices.get(entity.id, ()))
                last = history[-1] if history else None
                dest = by_id.get(last["place_id"]) if last else None
                out.append({
                    "id": entity.id, "kind": kind, "status": entity.status, "label": profile.describe(),
                    "role": profile.role, "traits": profile.traits,
                    "home": brief(by_id[profile.home_id]) if profile.home_id in by_id else None,
                    "duty": brief(by_id[profile.anchor_id]) if profile.anchor_id in by_id else None,
                    "at": brief(here) if at_place else None,
                    "destination": {**brief(dest), "x": dest["x"], "y": dest["y"]} if dest else None,
                    "decided_at_s": last["t"] if last else None, "probability": last["p"] if last else None,
                    "alternatives": [{**brief(by_id[a["place_id"]]), "p": a["p"]} for a in last["alternatives"]] if last else [],
                    "history": [{"t": h["t"], **brief(by_id[h["place_id"]])} for h in history[:-1]],
                })
        return out
