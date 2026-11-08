"""Every JSON block in INTERFACE.md and README.md validates against the wire schemas, the fixtures are embedded
verbatim, and the documented example signatures verify."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from guardian.adapters.schemas import (
    ActuatorCallIn,
    AlertOut,
    AuditEventOut,
    DecisionOut,
    Envelope,
    ErrorOut,
    TwinReply,
    VerdictOut,
)
from guardian.config import load_config
from guardian.ingest.validator import validate_envelope
from guardian.trust.signer import Signer, canonical_json
from tests.conftest import CONFIG_DIR, ROOT, make_settings
from tests.fixtures.make_fixtures import EXAMPLE_GUARDIAN_KEY, EXAMPLE_TWIN_KEY, build

FIXTURES = ROOT / "tests" / "fixtures"


def schema_for(obj: dict[str, Any]) -> type[BaseModel]:
    if "hmac" in obj:
        return Envelope
    if "signature" in obj:
        return VerdictOut
    if "alert_id" in obj:
        return AlertOut
    if "event_id" in obj:
        return AuditEventOut
    if "decision" in obj:
        return DecisionOut
    if "action" in obj:
        return ActuatorCallIn
    if "error" in obj:
        return ErrorOut
    if "current_state" in obj:
        return TwinReply
    raise AssertionError(f"no schema matches JSON block with keys {sorted(obj)}")


def blocks(doc: Path) -> list[dict[str, Any]]:
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", doc.read_text(), re.S)]


@pytest.mark.parametrize("doc", ["INTERFACE.md", "README.md"])
def test_doc_json_blocks_validate(doc: str) -> None:
    found = blocks(ROOT / doc)
    if doc == "INTERFACE.md":
        assert len(found) >= 8
    for obj in found:
        schema_for(obj).model_validate(obj)


def test_fixtures_embedded_verbatim_and_current() -> None:
    docs = blocks(ROOT / "INTERFACE.md")
    fresh = build()
    for path in FIXTURES.glob("*.json"):
        fixture = json.loads(path.read_text())
        assert fixture in docs, f"{path.name} is not embedded in INTERFACE.md"
        assert fixture == json.loads(json.dumps(fresh[path.stem])), f"{path.name} is stale; rerun make_fixtures"


def test_documented_signatures_verify(tmp_path: Path) -> None:
    env = json.loads((FIXTURES / "envelope.json").read_text())
    assert Signer(EXAMPLE_TWIN_KEY).verify(env, env["hmac"], exclude="hmac")
    text = (ROOT / "INTERFACE.md").read_text()
    assert canonical_json(env, "hmac").decode() in text and env["hmac"] in text
    validate_envelope(env, load_config(CONFIG_DIR, make_settings(tmp_path)).sensors, "1.0")
    v = json.loads((FIXTURES / "verdict.json").read_text())
    assert Signer(EXAMPLE_GUARDIAN_KEY).verify(v, v["signature"], exclude="signature")
