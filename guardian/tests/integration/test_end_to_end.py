"""End-to-end on mock data: a normal city produces trusted verdicts and a healthy /health."""

from __future__ import annotations

from collections import Counter

from tests.conftest import Harness


async def test_normal_city_is_trusted(city: Harness) -> None:
    verdicts = await city.advance(300)
    counts = Counter(v["status"] for v in verdicts)
    bad = [v for v in verdicts if v["status"] != "trusted"]
    assert counts["trusted"] / len(verdicts) > 0.97, (counts, bad[:3])
    h = (await city.client.get("/health")).json()
    assert h["twin"] == "ok" and h["status"] == "ok"
    assert all(level == "normal" for level in h["threat"].values())
