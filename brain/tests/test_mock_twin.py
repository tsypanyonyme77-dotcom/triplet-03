"""The mock Twin's wider actuators: signals, valves and the grid, spoken to as the contract describes."""

from brain.contracts import CONTRACT_VERSION
from mocks.twin.engine import MockTwin


def call(action, actuator_id, params, trust_ref="verdict-000001"):
    return {
        "contract_version": CONTRACT_VERSION, "actuator_id": actuator_id, "action": action, "params": params,
        "requesting_layer": "city_brain", "justification": "test", "trust_ref": trust_ref,
    }


def test_a_signal_phase_call_is_accepted_and_reports_when_it_reverts():
    twin = MockTwin(None, None)

    result = twin.set_signal_phase(call("set_signal_phase", "signal-05-01",
                                        {"intersection_id": "sig-05-01", "phase": "green", "duration_s": 120}))

    assert result["status"] == "set"
    assert result["current_phase"] == "green"
    assert "reverts_at" in result
    assert twin.actuator_log[-1]["result"] == result


def test_a_valve_call_with_a_bad_state_is_rejected_with_a_reason():
    twin = MockTwin(None, None)

    result = twin.set_valve_state(call("set_valve_state", "valve-01-01", {"valve_id": "valve-01-01", "state": "ajar"}))

    assert result["status"] == "rejected"
    assert "state" in result["reason"]


def test_a_grid_call_is_accepted_and_reports_the_load_it_affects():
    twin = MockTwin(None, None)

    result = twin.set_grid_connection(call("set_grid_connection", "grid-04", {"zone_id": "zone-04", "state": "disconnected"}))

    assert result == {"status": "set", "affected_load_kw": 0.0}


def test_a_call_without_a_trust_ref_is_rejected_by_the_twin():
    twin = MockTwin(None, None)

    result = twin.set_signal_phase(call("set_signal_phase", "signal-05-01",
                                        {"intersection_id": "sig-05-01", "phase": "green", "duration_s": 60}, trust_ref=None))

    assert result["status"] == "rejected"
    assert "trust_ref" in result["reason"]
