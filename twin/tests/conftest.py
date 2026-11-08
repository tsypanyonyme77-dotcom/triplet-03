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


@pytest.fixture
def guardian_mock():
    return load_mock("guardian", "mock_guardian")
