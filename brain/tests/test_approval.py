"""A person's approval of a valve or grid call: signed, bound to the call's parameters, used once, and checked again by the gate."""

import asyncio
import os
from datetime import UTC, datetime

from brain import clock
from brain.approval import ApprovalStore, proposal_hash, verify
from brain.config import PartnersConfig
from brain.contracts import ProposedAction
from tests.test_conditions import call, scenario, water
from tests.test_scenarios import play

SECRET = "approval-test-secret"
os.environ.setdefault("BRAIN_APPROVAL_SECRET", "approval-flow-test-secret")
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def valve(**params) -> ProposedAction:
    return ProposedAction(
        department="UTILITIES", tier="reflex", incident_id="inc-0001", action="set_valve_state", actuator_id="valve-01",
        params={"valve_id": "valve-01", "state": "closed", **params}, justification="flood", trust_ref="verdict-000001",
        evidence_reading_ids=["wl-01-01#5"],
    )


def store(**kw) -> ApprovalStore:
    return ApprovalStore(":memory:", SECRET, **kw)


def test_the_hash_covers_the_action_the_actuator_the_parameters_and_the_incident():
    base = proposal_hash(valve())

    assert proposal_hash(valve()) == base
    assert proposal_hash(valve(state="open")) != base
    assert proposal_hash(valve().model_copy(update={"incident_id": "inc-0002"})) != base
    assert proposal_hash(valve().model_copy(update={"justification": "other words"})) == base  # prose is not what is approved


def test_a_granted_approval_is_found_for_the_same_call_once():
    approvals, proposal = store(), valve()
    pending = approvals.hold(proposal, trace_id="t")
    granted = approvals.grant(pending, "operator")

    found, reason = approvals.find(proposal)
    assert found.approval_id == granted.approval_id and reason is None
    approvals.consume(granted.approval_id)
    assert approvals.find(proposal)[0] is None


def test_an_approval_for_other_parameters_is_not_found_and_verify_says_hash_mismatch():
    approvals = store()
    granted = approvals.grant(approvals.hold(valve(), None), "operator")

    assert approvals.find(valve(state="open"))[0] is None
    assert verify(granted, valve(state="open"), SECRET) == "hash_mismatch"
    assert verify(granted, valve(), SECRET) is None


def test_an_expired_approval_is_refused():
    with clock.use(clock.DeterministicClock(EPOCH)) as fixed:
        approvals = store(ttl_s=120)
        granted = approvals.grant(approvals.hold(valve(), None), "operator")
        fixed.advance_to(121)

        assert approvals.find(valve())[0] is None
        assert verify(granted, valve(), SECRET) == "expired"


def test_an_approval_signed_with_another_secret_is_refused():
    approvals = store()
    granted = approvals.grant(approvals.hold(valve(), None), "operator")

    assert verify(granted, valve(), "another-secret") == "signature_invalid"
    forged = granted.model_copy(update={"approver": "someone else"})
    assert verify(forged, valve(), SECRET) == "signature_invalid"


def test_a_denied_pending_action_stays_held_and_says_why():
    approvals = store()
    pending = approvals.hold(valve(), None)

    approvals.deny(pending, "operator", "not now")

    assert approvals.find(valve())[0] is None
    assert approvals.status(pending)["state"] == "denied" and approvals.status(pending)["reason"] == "not now"


def test_pending_approvals_survive_a_restart(tmp_path):
    path = tmp_path / "approvals.sqlite"
    first = ApprovalStore(path, SECRET)
    pending = first.hold(valve(), "trace-1")
    first.grant(pending, "operator")

    second = ApprovalStore(path, SECRET)

    assert second.find(valve())[0] is not None


def test_holding_the_same_call_twice_gives_one_pending_entry():
    approvals = store()

    assert approvals.hold(valve(), None) == approvals.hold(valve(), None)
    assert len(approvals.pending()) == 1


FLOOD = [water(100, 1.2), water(200, 1.4), call(300, "flood", "call-feed-01", "zone-01")]


async def run_flood(mode, approve):
    partners = PartnersConfig.model_validate({"approval": {"mode": mode, "path": ":memory:"}})
    approver = []

    def attach(service):
        if approve and service.approvals is not None:
            async def answer(pending):
                granted = service.approvals.grant(pending["pending_id"], "operator")
                approver.append(granted)
                await service.reoffer(pending["pending_id"])

            answers = []
            service.approvals.on_request = lambda pending: answers.append(asyncio.get_running_loop().create_task(answer(pending)))
            run_until_quiet = service.run_until_quiet

            async def quiet():  # the run is over only when the person's answer has been put through the gate too (it was a race)
                await run_until_quiet()
                await asyncio.gather(*answers)

            service.run_until_quiet = quiet

    return await play(scenario(FLOOD), partners=partners, on_service=attach), approver


async def test_with_approval_off_a_valve_call_is_held_as_recorded():
    result, _ = await run_flood("off", approve=False)

    assert [c["call"]["action"] for c in result.actuator_calls] == ["broadcast_alert"]
    assert "human_approval" in [e.data["check"] for e in result.sink.of("brain.action.blocked")]


async def test_in_human_mode_the_valve_call_is_held_and_a_pending_approval_is_requested():
    result, _ = await run_flood("human", approve=False)

    assert [c["call"]["action"] for c in result.actuator_calls] == ["broadcast_alert"]
    requested = result.sink.of("brain.approval.requested")
    assert len(requested) == 1 and requested[0].data["action"] == "set_valve_state"
    held = next(e for e in result.sink.of("brain.action.blocked") if e.data["check"] == "human_approval")
    assert held.data["gate"]["pending_id"] == requested[0].data["pending_id"]


async def test_a_granted_approval_lets_the_held_valve_call_through_once_and_the_decision_names_it():
    result, approver = await run_flood("human", approve=True)

    valves = [c for c in result.actuator_calls if c["call"]["action"] == "set_valve_state"]
    assert len(valves) == 1  # sent once, although the rule fired on more than one reading
    assert result.sink.of("brain.approval.granted")
    decision = next(e for e in result.sink.of("brain.decision.made") if e.data["action"] == "set_valve_state")
    assert decision.data["gate"]["human_approval_id"] == approver[0].approval_id
    assert "human_approval" in decision.data["gate"]["checks"]


def test_the_approval_model_has_a_schema_and_an_example():
    from pathlib import Path

    contracts = Path(__file__).parents[1] / "contracts"
    assert (contracts / "schemas/Approval.schema.json").exists() and (contracts / "examples/approval.json").exists()
