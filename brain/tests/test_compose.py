"""The Compose file is the only deployment: keep its shape (profiles, loopback-only ports, the full config) from drifting."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_both_stores_start_with_the_core_profile():
    services = COMPOSE["services"]
    assert set(services) >= {"brain", "twin", "guardian", "neo4j", "qdrant"}
    assert "core" in services["neo4j"]["profiles"] and "core" in services["qdrant"]["profiles"]
    assert "core" in services["brain"]["profiles"] and "full" in services["brain"]["profiles"]


def test_every_published_port_is_on_loopback():
    for name, service in COMPOSE["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


def test_the_full_config_reaches_both_stores_by_service_name():
    graph = yaml.safe_load((ROOT / "deploy/compose/partners.full.yaml").read_text())["graph"]
    assert graph["backend"] == "neo4j" and graph["uri"] == "bolt://neo4j:7687" and graph["qdrant_url"] == "http://qdrant:6333"


OBS = yaml.safe_load((ROOT / "deploy/compose/observability.yaml").read_text())
GRAFANA = ROOT / "deploy/grafana"


def test_the_observability_services_are_opt_in_and_on_loopback():
    assert set(OBS["services"]) == {"traefik", "prometheus", "loki", "promtail", "jaeger", "grafana"}
    for name, service in OBS["services"].items():
        assert service["profiles"] == ["obs"], name
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


def test_both_compose_files_include_the_observability_stack():
    assert {"path": "deploy/compose/observability.yaml"} in COMPOSE["include"]
    root = yaml.safe_load((ROOT.parent / "docker-compose.yml").read_text())
    assert {"path": "brain/deploy/compose/observability.yaml"} in root["include"]


def test_prometheus_scrapes_the_brain_where_it_listens_and_every_target_is_a_service():
    scrape = yaml.safe_load((GRAFANA / "prometheus.yml").read_text())["scrape_configs"]
    targets = {job["job_name"]: job["static_configs"][0]["targets"][0] for job in scrape}
    services = set(OBS["services"]) | set(COMPOSE["services"]) | {"localhost"}

    assert targets["city-brain"] == "brain:8002"
    assert {t.split(":")[0] for t in targets.values()} <= services


def test_traefik_routes_every_screen_to_a_service_in_the_stack():
    dynamic = yaml.safe_load((ROOT / "deploy/traefik/dynamic.yml").read_text())["http"]
    hosts = {r["service"]: r["rule"] for r in dynamic["routers"].values()}
    known = set(OBS["services"]) | set(COMPOSE["services"])

    assert {"brain", "grafana", "prometheus", "jaeger", "neo4j", "qdrant"} <= set(dynamic["services"])
    assert all(url["url"].split("//")[1].split(":")[0] in known for s in dynamic["services"].values() for url in s["loadBalancer"]["servers"])
    assert all("localhost" in rule for rule in hosts.values())


def test_every_dashboard_panel_reads_a_provisioned_datasource():
    import json

    provisioned = {d["uid"] for d in yaml.safe_load((GRAFANA / "provisioning/datasources/prometheus.yml").read_text())["datasources"]}
    def panels(items):
        for panel in items:
            yield from panels(panel.get("panels", [])) if panel["type"] == "row" else [panel]

    dashboards = list((GRAFANA / "dashboards").glob("*.json"))
    assert [d.name for d in dashboards] == ["city-brain.json"]  # one dashboard: a status strip, then rows that open
    dashboard = json.loads(dashboards[0].read_text())
    found = list(panels(dashboard["panels"]))
    assert found and {p["datasource"]["uid"] for p in found} <= provisioned
    assert {"City Brain screen", "Traces", "City Graph: latest decision"} <= {link["title"] for link in dashboard["links"]}
