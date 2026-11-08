import hmac
import json
from pathlib import Path

import pytest
import yaml

from brain import contracts
from brain.commands.run import SCHEMA_MODELS
from brain.config import ModelsConfig, PartnersConfig, Policy

ROOT = Path(__file__).resolve().parent.parent

EXAMPLES = {
    "reading.citizen_activity.json": contracts.SensorReading,
    "reading.cctv_anomaly.json": contracts.SensorReading,
    "reading.unit_status.json": contracts.SensorReading,
    "reading.traffic_camera.json": contracts.SensorReading,
    "reading.water_level.json": contracts.SensorReading,
    "reading.power_load.json": contracts.SensorReading,
    "reading.air_quality.json": contracts.SensorReading,
    "verdict.json": contracts.TrustVerdict,
    "actuator_call.dispatch_unit.json": contracts.ActuatorCall,
    "actuator_call.dispatch_unit.contain.json": contracts.ActuatorCall,
    "actuator_call.dispatch_unit.respond.json": contracts.ActuatorCall,
    "actuator_call.broadcast_alert.json": contracts.ActuatorCall,
    "actuator_call.recall_unit.json": contracts.ActuatorCall,
    "actuator_call.set_signal_phase.json": contracts.ActuatorCall,
    "actuator_call.set_valve_state.json": contracts.ActuatorCall,
    "actuator_call.set_grid_connection.json": contracts.ActuatorCall,
    "actuator_result.dispatch_unit.json": contracts.ActuatorResult,
    "actuator_result.recall_unit.json": contracts.ActuatorResult,
    "actuator_result.broadcast_alert.json": contracts.ActuatorResult,
    "actuator_result.set_signal_phase.json": contracts.ActuatorResult,
    "timeline_event.json": contracts.TimelineEvent,
}


@pytest.mark.parametrize(("file_name", "model"), EXAMPLES.items())
def test_documented_examples_match_the_models(file_name, model):
    example = json.loads((ROOT / "contracts/examples" / file_name).read_text())

    parsed = model.model_validate(example)

    if isinstance(parsed, contracts.SensorReading):
        contracts.VALUE_MODELS[parsed.type].model_validate(parsed.value)
    if isinstance(parsed, contracts.ActuatorCall):
        contracts.PARAM_MODELS[parsed.action].model_validate(parsed.params)


@pytest.mark.parametrize("model", SCHEMA_MODELS, ids=lambda m: m.__name__)
def test_exported_schemas_are_current(model):
    """If this fails, run `uv run brain export-schemas` and send partners the new files."""
    path = ROOT / "contracts/schemas" / f"{model.__name__}.schema.json"

    assert json.loads(path.read_text()) == model.model_json_schema()


@pytest.mark.parametrize(
    ("file_name", "model"),
    [("partners.yaml", PartnersConfig), ("policy.yaml", Policy), ("models.yaml", ModelsConfig)],
)
def test_shipped_config_equals_built_in_defaults(file_name, model):
    shipped = model.model_validate(yaml.safe_load((ROOT / "config" / file_name).read_text()))

    assert shipped == model()


SECRETS = {"twin": "dev-only-twin-secret", "city_brain": "dev-only-brain-secret"}


@pytest.mark.parametrize("path", sorted((ROOT / "contracts/examples").glob("[ra][ec]*.json")), ids=lambda p: p.name)
def test_signed_examples_verify_with_the_dev_secrets(path):
    """A partner checking their signer against our examples must not be told it is wrong."""
    example = json.loads(path.read_text())
    if "provenance" not in example or "hmac" not in example["provenance"]:
        pytest.skip("not a signed reading or call")

    assert contracts.signing.verify(example, SECRETS[example["provenance"]["signed_by"]])


def test_the_topology_example_lists_every_zone_it_refers_to():
    topology = json.loads((ROOT / "contracts/examples/topology.json").read_text())
    zones = {z["id"] for z in topology["zones"]}

    assert set(topology) == {"zones", "adjacency", "exits", "facilities", "sensors"}
    assert {z for pair in topology["adjacency"] for z in pair} | set(topology["exits"]) <= zones
    assert {x["zone_id"] for x in topology["facilities"] + topology["sensors"]} <= zones


def test_a_whole_number_float_is_signed_as_javascript_writes_it_and_older_signatures_still_verify():
    envelope = {"a": 1, "value": {"speed": 6.0, "nested": [2.0, 0.5]}}
    as_integers = {"a": 1, "value": {"speed": 6, "nested": [2, 0.5]}}

    new = contracts.signing.sign(envelope, "s", "twin")
    older = {**envelope, "provenance": {"signed_by": "twin", "hmac": hmac.new(b"s", contracts.signing.canonical_json(envelope), "sha256").hexdigest()}}

    assert new["provenance"]["hmac"] == contracts.signing.sign(as_integers, "s", "twin")["provenance"]["hmac"]
    assert contracts.signing.verify(new, "s") and contracts.signing.verify(older, "s")
    assert not contracts.signing.verify(new, "other")


def test_the_triplets_partner_addresses_override_the_file(monkeypatch, tmp_path):
    from brain import config

    file = tmp_path / "partners.yaml"
    file.write_text("twin: {adapter: mcp, url: 'http://127.0.0.1:8765/mcp'}\nguardian: {url: 'http://127.0.0.1:8766'}\n")
    monkeypatch.setenv("TWIN_URL", "http://twin:8001")
    monkeypatch.setenv("GUARDIAN_URL", "http://guardian:8003")

    partners = config.load(PartnersConfig, "partners", file)

    assert partners.twin.url == "http://twin:8001/mcp" and partners.guardian.url == "http://guardian:8003"

    monkeypatch.setenv("TWIN_URL", "http://twin:8001/tools/mcp")
    assert config.load(PartnersConfig, "partners", file).twin.url == "http://twin:8001/tools/mcp"
