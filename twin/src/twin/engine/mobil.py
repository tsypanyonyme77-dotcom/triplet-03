"""MOBIL lane-changing model (Minimizing Overall Braking Induced by Lane changes).

Standard formulation: a car changes lane if doing so improves its own
acceleration by more than a threshold, adjusted for the impact on the
follower it would leave behind (in the current lane) and the follower it
would gain (in the target lane), weighted by a politeness factor. A hard
safety constraint always applies: the new follower must never be forced to
brake harder than a fixed limit.
"""
from __future__ import annotations

from dataclasses import dataclass

from twin.engine.idm import IDMParams, idm_acceleration


@dataclass
class MOBILParams:
    politeness: float = 0.3         # how much we weigh effects on other drivers (0=selfish, 1=altruistic)
    delta_a_threshold: float = 0.2   # minimum net accel gain (m/s^2) to justify a lane change
    safe_braking: float = 4.0         # max deceleration (m/s^2) we're allowed to impose on the new follower


@dataclass
class LaneChangeInputs:
    v: float
    params: IDMParams

    # this car, staying in its current lane
    cur_lead_v: float | None
    cur_gap: float | None

    # this car, if it moved to the target lane
    tgt_lead_v: float | None
    tgt_gap_ahead: float | None

    # the car currently behind us in the target lane
    tgt_follower_v: float | None
    tgt_follower_gap_to_us: float | None       # gap follower->us, after we merge in
    tgt_follower_gap_to_its_lead: float | None  # gap follower->its current leader, before we merge in

    # the car currently behind us in our own lane (would inherit our old leader)
    cur_follower_v: float | None
    cur_follower_gap_before: float | None  # follower -> us, before we leave
    cur_follower_gap_after: float | None    # follower -> our old leader, after we leave


def should_change_lane(inp: LaneChangeInputs, mobil: MOBILParams) -> bool:
    # --- hard safety constraint on the new follower ---
    new_follower_accel_after = idm_acceleration(
        inp.tgt_follower_v or 0.0, inp.v, inp.tgt_follower_gap_to_us, inp.params
    )
    if inp.tgt_follower_v is not None and new_follower_accel_after < -mobil.safe_braking:
        return False

    # --- our own gain ---
    accel_self_current = idm_acceleration(inp.v, inp.cur_lead_v, inp.cur_gap, inp.params)
    accel_self_target = idm_acceleration(inp.v, inp.tgt_lead_v, inp.tgt_gap_ahead, inp.params)
    self_gain = accel_self_target - accel_self_current

    # --- disruption to the target-lane follower (it now has to react to us) ---
    new_follower_accel_before = idm_acceleration(
        inp.tgt_follower_v or 0.0, inp.tgt_lead_v, inp.tgt_follower_gap_to_its_lead, inp.params
    )
    target_follower_cost = new_follower_accel_after - new_follower_accel_before

    # --- disruption to our current-lane follower (it loses us as a buffer, gains our old leader) ---
    old_follower_accel_before = idm_acceleration(
        inp.cur_follower_v or 0.0, inp.v, inp.cur_follower_gap_before, inp.params
    )
    old_follower_accel_after = idm_acceleration(
        inp.cur_follower_v or 0.0, inp.cur_lead_v, inp.cur_follower_gap_after, inp.params
    )
    old_follower_gain = old_follower_accel_after - old_follower_accel_before

    incentive = self_gain + mobil.politeness * (target_follower_cost + old_follower_gain)
    return incentive > mobil.delta_a_threshold
