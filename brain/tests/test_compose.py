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
