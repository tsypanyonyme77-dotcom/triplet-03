"""The life of a lesson: a learned rule is a cache of what the team planned once, and it has to earn its keep.

At each sleep every learned rule is looked at again against the episodes recorded since it was made. An episode
of its pattern (same incident zone, same place the suspect was last seen, same heading) either

  * *confirms* it: the team planned that pattern the same way again,
  * *contradicts* it: the team planned the same pattern differently (so the city, or the playbook, has moved on), or
  * only shows the pattern *recurs*: the learned plan answered it, so no team plan was made.

Using a rule never counts as proof that it is right: only the team planning the pattern the same way confirms it.
A rule is retired when its contradictions outnumber its confirmations, and it fades when its pattern has not recurred
for more sleeps than `fade_after_sleeps` (0 means it never fades). Everything here is counting over episodes: no model,
and nothing about whether a dispatch worked.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from brain.config import LearningPolicy
from brain.mind.episodes import DROPPED_PARAMS, Episode


def episode_signature(episode: Episode) -> tuple[str, str, str] | None:
    if episode.incident.type != "crime" or len(episode.pursuits) != 1:
        return None
    pursuit = episode.pursuits[0]
    return (episode.incident.zone_id, pursuit.zone_id, pursuit.heading_zone_id or "")


def team_plan(episode: Episode) -> tuple[str, ...] | None:
    plan = next((p for p in episode.plans if p.reason == "plan"), None)
    return None if plan is None else tuple(json.dumps({"action": a.action, "params": a.params}, sort_keys=True) for a in plan.actions)


def rule_plan(rule: dict[str, Any]) -> tuple[str, ...]:
    """What the rule does, in the form an episode records the team's plan (no incident, target or unit)."""
    return tuple(
        json.dumps({"action": step["action"], "params": {k: v for k, v in step["params"].items() if k not in DROPPED_PARAMS}}, sort_keys=True)
        for step in rule["do"]
    )


def review(rules: list[dict[str, Any]], episodes: list[Episode], policy: LearningPolicy) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the rules that stay, with their counts brought up to date; the rules retired, each with the check and the reason)."""
    kept, retired = [], []
    for original in rules:
        rule = copy.deepcopy(original)
        learned = rule["learned"]
        for key, start in (("confirmed", 0), ("contradicted", 0), ("uses", 0), ("sleeps_idle", 0), ("seen", [])):
            learned.setdefault(key, start)
        signature, taught, seen, plan = tuple(learned["signature"]), set(learned["sources"]), set(learned["seen"]), rule_plan(rule)
        fresh = [e for e in episodes if e.episode_id not in taught | seen and episode_signature(e) == signature]
        confirming = [e for e in fresh if team_plan(e) == plan]
        contradicting = [e for e in fresh if team_plan(e) not in (None, plan)]
        learned["confirmed"] += len(confirming)
        learned["contradicted"] += len(contradicting)
        learned["uses"] += sum(1 for e in fresh if rule["id"] in e.lessons_used)
        learned["seen"] = sorted(seen | {e.episode_id for e in fresh})
        learned["sleeps_idle"] = 0 if fresh else learned["sleeps_idle"] + 1
        if policy.retire_on_contradiction and learned["contradicted"] > learned["confirmed"]:
            retired.append({"rule": rule["id"], "check": "contradicted", "signature": list(signature), "sources": list(learned["sources"]),
                            "reason": f"the team later planned this pattern differently {learned['contradicted']} time(s) against "
                                      f"{learned['confirmed']} time(s) the same way, for example in {', '.join(e.episode_id for e in contradicting[:3]) or 'an earlier sleep'}"})
        elif policy.fade_after_sleeps and learned["sleeps_idle"] > policy.fade_after_sleeps:
            retired.append({"rule": rule["id"], "check": "faded", "signature": list(signature), "sources": list(learned["sources"]),
                            "reason": f"its pattern has not recurred for {learned['sleeps_idle']} sleeps (the limit is {policy.fade_after_sleeps}), so the city may no longer need it"})
        else:
            kept.append(rule)
    return kept, retired
