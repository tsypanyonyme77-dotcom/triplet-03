"""Writes docs/asyncapi.yaml: the event feed (`GET /events`) as an AsyncAPI 3 description, one message per timeline event type.

    uv run python scripts/gen_asyncapi.py

The types are read from the `emit("brain.x.y", ...)` calls in the source, so a new event type appears here on the next run.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
types = set()
for path in (ROOT / "src" / "brain").rglob("*.py"):
    types |= set(re.findall(r'emit\(\s*"(brain\.[a-z_.]+)"', path.read_text()))
types |= {"brain.session.reset"}  # made by the API, not through emit()

spec = {
    "asyncapi": "3.0.0",
    "info": {"title": "City Brain event feed", "version": "2026-09-17", "description": "CloudEvents 1.0 over Server-Sent Events. Replays the run so far, then follows. Each event carries `traceid = <sensor_id>:<sequence_no>` of the reading that caused it."},
    "servers": {"brain": {"host": "localhost:8080", "protocol": "http", "description": "GET /events (text/event-stream)"}},
    "channels": {"events": {"address": "/events", "messages": {t: {"$ref": f"#/components/messages/{t}"} for t in sorted(types)}}},
    "operations": {"receiveEvents": {"action": "receive", "channel": {"$ref": "#/channels/events"}}},
    "components": {"messages": {t: {"name": t, "contentType": "application/json", "payload": {"$ref": "../contracts/schemas/TimelineEvent.schema.json"}} for t in sorted(types)}},
}
(ROOT / "docs" / "asyncapi.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
print(f"wrote docs/asyncapi.yaml with {len(types)} event types")
