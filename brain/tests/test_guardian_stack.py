"""The Compose stack for the Guardian team's real Guardian: the bridge over their Twin mock, the Brain's config for contract 1.0, the file itself."""
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from brain.adapters import GuardianGateway, open_guardian, with_gateway
from brain.adapters.guardian_v1 import GuardianV1Adapter
from brain.citygraph import MemoryGraphStore
from brain.config import PartnersConfig
from mocks.guardian_twin.bridge import ACTIONS, build_app, topology
from mocks.twin.engine import MockTwin

ROOT = Path(__file__).resolve().parent.parent
GUARDIAN_CONFIG = ROOT.parent / "guardian" / "config"
needs_guardian = pytest.mark.skipif(not GUARDIAN_CONFIG.is_dir(), reason="the Guardian team's folder is not next to brain/")
COMPOSE = yaml.safe_load((ROOT / "docker-compose.guardian.yml").read_text())
SENSORS = [{"id": "wl-port-03", "type": "water_level", "zone_id": "zone-07"}]


def bridge(pages: list[dict]) -> TestClient:
    seen: list[dict] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=pages[0])

    client = httpx.AsyncClient(base_url="http://twin", transport=httpx.MockTransport(upstream))
    return TestClient(build_app(client, MockTwin(None, None), GUARDIAN_CONFIG))


@needs_guardian
def test_the_guardians_city_loads_as_a_brain_topology_with_its_actuators_as_facilities():
    store, city = MemoryGraphStore(), topology(GUARDIAN_CONFIG, SENSORS)

    store.load_topology(city)
    kinds = {f["actuator_id"]: f["type"] for f in city["facilities"]}

    assert kinds["valve-port-12"] == "valve" and kinds["grid-port"] == "grid_breaker" and kinds["sig-port-01"] == "signal_controller"
    assert {"police_station", "fire_station", "hospital"} <= set(kinds.values())
    assert ["zone-07", "zone-08"] in [list(pair) for pair in city["adjacency"]]


@needs_guardian
def test_their_page_comes_back_with_the_cursor_name_and_a_stream_id_the_brain_reads():
    reading = {"sensor_id": "wl-port-03", "sensor_type": "water_level", "zone_id": "zone-07", "sequence_no": 1}
    web = bridge([{"cursor": 4, "readings": [reading]}])

    page = web.get("/readings", params={"cursor": 2}).json()

    assert page["readings"] == [reading] and page["next_cursor"] == 4 and page["stream_id"]
    assert web.get("/readings").json()["stream_id"] == page["stream_id"]
    assert web.get("/topology").json()["sensors"] == SENSORS


@needs_guardian
def test_the_twin_answers_broadcast_and_recall_and_leaves_the_audited_four_to_the_guardian():
    web = bridge([{"cursor": 0, "readings": []}])
    call = {"contract_version": "2026-09-17", "actuator_id": "alert-07", "action": "broadcast_alert", "requesting_layer": "city_brain", "justification": "t", "trust_ref": "v-1",
            "params": {"zone_id": "zone-07", "channel": "siren", "message": "Flood warning in the port"}}

    assert set(web.get("/capabilities").json()) == set(ACTIONS) and len(ACTIONS) == 6
    assert web.post("/actuators/broadcast_alert", json=call).json()["status"] == "broadcast"
    assert web.post("/actuators/recall_unit", json={**call, "action": "recall_unit", "params": {"unit_id": "u-1", "incident_id": "inc-1"}}).json() == {"status": "recalled", "unit_id": "u-1"}
    for audited in ("dispatch_unit", "set_valve_state", "set_grid_connection", "set_signal_phase"):
        assert web.post(f"/actuators/{audited}", json=call).status_code == 404


def test_the_brain_config_for_the_guardian_team_is_contract_1_0_with_the_gateway_on():
    partners = PartnersConfig.model_validate(yaml.safe_load((ROOT / "deploy/compose/partners.guardian-v1.yaml").read_text()))

    assert partners.twin.dialect == "guardian-v1" and partners.twin.adapter == "http" and partners.twin.require_signature
    assert (partners.guardian.adapter, partners.guardian.gateway, partners.guardian.dispatcher_id) == ("v1", True, "dispatch-central")
    assert partners.guardian.url.endswith(":8003") and partners.guardian.hmac_secret_env == "GUARDIAN_HMAC_KEY"


def test_that_config_opens_the_v1_adapter_and_puts_the_gateway_in_front_of_the_twin(monkeypatch):
    monkeypatch.setenv("GUARDIAN_HMAC_KEY", "k")
    partners = PartnersConfig.model_validate(yaml.safe_load((ROOT / "deploy/compose/partners.guardian-v1.yaml").read_text()))

    guardian = open_guardian(partners.guardian, httpx.AsyncClient(base_url="http://guardian"))

    assert isinstance(guardian, GuardianV1Adapter) and isinstance(with_gateway(object(), guardian, partners.guardian), GuardianGateway)


def test_the_stack_is_its_own_project_on_loopback_and_every_service_it_waits_for_exists():
    services = COMPOSE["services"]

    assert COMPOSE["name"] == "city-brain-guardian" and set(services) == {"guardian", "twin", "twin-bridge", "brain", "neo4j", "qdrant"}
    for name, service in services.items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)
        assert set(service.get("depends_on", {})) <= set(services), name
    assert "--live" in services["brain"]["command"] and "deploy/compose/partners.guardian-v1.yaml" in services["brain"]["command"]  # live: the real partners, not in-process mocks
    assert (ROOT / "deploy/compose/partners.guardian-v1.yaml").is_file()


def test_the_guardian_gets_the_keys_it_refuses_to_start_without_and_listens_where_the_brain_looks():
    env = COMPOSE["services"]["guardian"]["environment"]
    partners = yaml.safe_load((ROOT / "deploy/compose/partners.guardian-v1.yaml").read_text())

    assert {"GUARDIAN_HMAC_KEY", "TWIN_HMAC_KEY", "BRAIN_API_KEY", "OPS_API_KEY"} <= set(env)
    assert env["GUARDIAN_URL"] == partners["guardian"]["url"]
    assert env["TWIN_HMAC_KEY"] == COMPOSE["services"]["twin"]["environment"]["TWIN_HMAC_KEY"]
