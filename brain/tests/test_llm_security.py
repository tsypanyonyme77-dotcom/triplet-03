"""Hostile text meets the Brain: ids are refused at the door, values are typed, the gate stops what a fooled model proposes, and a changed Twin tool list is reported."""

from pathlib import Path

import pytest
import yaml

from brain.contracts import CONTRACT_VERSION
from brain.contracts.signing import sign
from brain.perception import ContractError, Perception

CASES = yaml.safe_load((Path(__file__).parent / "data/injection_corpus.yaml").read_text())["cases"]
SECRET = "llm-security-secret"


def reading(**over):
    base = {"contract_version": CONTRACT_VERSION, "sensor_id": "wl-01", "type": "water_level", "zone_id": "zone-01", "timestamp": "2026-11-05T10:00:00.000Z",
            "sequence_no": 1, "value": {"level_m": 0.4, "flow_rate_m3s": 1.0}}
    return sign({**base, **over}, SECRET, "twin")


def test_the_corpus_has_thirty_cases_each_with_an_owasp_category():
    assert len(CASES) >= 30 and all(c["owasp"].startswith("LLM") and c["kind"] and c["text"] for c in CASES)


@pytest.mark.parametrize("field", ["sensor_id", "zone_id", "type"])
def test_hostile_ids_are_rejected_by_the_id_pattern_before_they_reach_a_brief(field):
    for case in CASES:
        with pytest.raises(ContractError) as error:
            Perception([CONTRACT_VERSION], SECRET).ingest(reading(**{field: case["text"]}))
        assert error.value.code == "schema_invalid", (field, case["kind"])


def test_hostile_text_in_a_field_the_contract_does_not_know_is_dropped_before_any_brief():
    for case in CASES:
        perceived = Perception([CONTRACT_VERSION], SECRET).ingest(reading(value={"level_m": 0.4, "flow_rate_m3s": 1.0, "note": case["text"]}))
        assert case["text"] not in str(perceived.reading.value) and perceived.dropped_fields == ["note"]


def test_hostile_text_in_a_typed_field_is_refused_not_passed_on():
    for case in CASES:
        with pytest.raises(ContractError) as error:
            Perception([CONTRACT_VERSION], SECRET).ingest(reading(value={"level_m": case["text"], "flow_rate_m3s": 1.0}))
        assert error.value.code == "value_invalid"


def test_every_brief_value_that_came_from_a_partner_is_a_typed_field_not_free_text():
    """The only free strings a Twin can send are short words and ids, and each carries the safe-id pattern; anything else is a number, a boolean or a fixed choice."""
    from brain.contracts import VALUE_MODELS

    def bounded(info):
        text = str(info.annotation)
        return "str" not in text or any("pattern" in repr(m) or getattr(m, "pattern", None) for m in info.metadata) or "Safe" in text or "Annotated" in text

    loose = {name: [f for f, info in model.model_fields.items() if not bounded(info)] for name, model in VALUE_MODELS.items()}

    assert all(not fields for fields in loose.values()), loose


def test_hostile_text_in_a_free_looking_value_field_is_refused():
    for case in CASES:
        with pytest.raises(ContractError):
            Perception([CONTRACT_VERSION], SECRET).ingest(reading(type="cctv_anomaly", sensor_id="cam-01", value={"anomaly_type": case["text"], "confidence": 0.9}))
        with pytest.raises(ContractError):
            Perception([CONTRACT_VERSION], SECRET).ingest(reading(type="citizen_activity", sensor_id="cit-01", value={"citizen_id": "c1", "activity": case["text"]}))


async def test_a_model_that_obeys_an_injected_instruction_is_stopped_by_the_gate():
    """A proposal to dispatch from a quarantined station, which is what an injected 'send everything' would ask for, never reaches the Twin."""
    from brain.config import ModelsConfig
    from brain.scenario import inproc_partners, load_scenario, run_scenario

    scenario = load_scenario("t14")
    scenario["guardian"] = {"default": "trusted", "overrides": {}, "quarantined": ["police-dispatch-05"]}  # the nearest dispatch actuator
    result = await run_scenario(scenario, inproc_partners(), models=ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), speed=0, timeout_s=30)
    quarantined = [c for c in result.actuator_calls if c["call"]["actuator_id"] == "police-dispatch-05"]

    assert quarantined == [] and "brain.action.blocked" in result.sink.types()  # refused by the gate, not merely not asked


async def test_a_twin_that_adds_an_actuator_tool_mid_run_is_reported_and_not_used():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from brain.runtime import BrainService

    events, tools = [], {"dispatch_unit": "d"}

    class Twin:
        async def list_capabilities(self):
            return dict(tools)

    service = SimpleNamespace(twin=Twin(), timeline=SimpleNamespace(emit=lambda type, subject, data: events.append((type, data))),
                              _capabilities={"dispatch_unit"}, _reported_capabilities={"dispatch_unit"}, _capabilities_checked=datetime.min.replace(tzinfo=UTC))
    tools["open_every_valve"] = "a new tool"
    await BrainService._recheck_capabilities(service)
    service._capabilities_checked = datetime.min.replace(tzinfo=UTC)
    await BrainService._recheck_capabilities(service)  # unchanged since the report: said once

    assert [e[0] for e in events] == ["brain.twin.capabilities.changed"] and events[0][1]["added"] == ["open_every_valve"]
    assert service._capabilities == {"dispatch_unit"}  # the gate's list did not grow
