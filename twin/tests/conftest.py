import importlib.util
import sys
from pathlib import Path

import pytest

MOCKS = Path(__file__).resolve().parents[1] / "mocks"


def load_mock(layer: str, name: str):
    """Load a mock app as an isolated module (fresh in-memory state each call)."""
    spec = importlib.util.spec_from_file_location(name, MOCKS / layer / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # pydantic resolves string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


ALL_TYPES = ("cctv_anomaly", "building_fire", "unit_status")   # the mock Guardian takes every type the Twin has


def send_to_guardian(client, reading, dialect):
    """A Twin reading through the mock Guardian's real door; its verdict, or None for one the dialect does not send."""
    verdict = None
    for envelope in dialect.render(reading):
        got = client.post("/v1/readings", json=envelope).json()["results"][0]["verdict"]
        verdict = verdict or got
    return verdict


@pytest.fixture(autouse=True)
def _chain_logs_in_a_temporary_folder(tmp_path_factory, monkeypatch):
    """Incident chain logs from tests never land in the triplet's logs/ folder, which holds scenario runs (R2)."""
    monkeypatch.setenv("TWIN_CHAIN_LOG_DIR", str(tmp_path_factory.mktemp("chain-logs")))


@pytest.fixture
def guardian_mock():
    return load_mock("guardian", "mock_guardian")
