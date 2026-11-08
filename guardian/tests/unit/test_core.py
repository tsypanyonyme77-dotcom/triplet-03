"""Clock, config loading (including corrupt config failing loudly), signer, audit logger, timeline emitter."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from guardian.audit.logger import AuditLogger, scenario_id_var
from guardian.audit.timeline_emitter import TimelineEmitter
from guardian.clock import FakeClock, SystemClock, iso
from guardian.config import ConfigError, Settings, load_config, require_secrets
from guardian.trust.signer import Signer, canonical_json
from tests.conftest import CONFIG_DIR, make_settings


async def test_fake_clock_sleep_advances() -> None:
    c = FakeClock()
    t0 = c.now()
    await c.sleep(30)
    assert (c.now() - t0).total_seconds() == 30
    assert iso(t0) == "2026-11-02T14:00:00Z"
    assert SystemClock().now().tzinfo is not None
    await SystemClock().sleep(0)


def test_config_loads_and_validates(tmp_path: Path) -> None:
    cfg = load_config(CONFIG_DIR, make_settings(tmp_path))
    assert cfg.guardian.contract_version == "1.0"
    assert cfg.city.zones["zone-12"].fire_possible is False
    assert cfg.guardian.audit.log_dir == str(tmp_path / "logs")  # env override wins


def _copy(tmp_path: Path) -> Path:
    d = tmp_path / "cfg"
    shutil.copytree(CONFIG_DIR, d)
    return d


@pytest.mark.parametrize(("file", "text", "needle"), [
    ("thresholds.yaml", "scoring: {cutoffs: {trusted: 0.3, suspect: 0.5}}", "cutoffs"),
    ("guardian.yaml", "twin: {transport: carrier_pigeon, base_url: x}", "transport"),
    ("crosschecks.yaml", "adjacency: {zone-07: [zone-99]}", "zone-99"),
    ("city_model.yaml", ": : not yaml : [", "invalid YAML"),
    ("policies.yaml", "actuators: {v: {type: valve, zone_id: zone-07, verify_sensors: [v]}}", "verify itself"),
    ("sensor_registry.yaml", "sensor_types: {x: {expected_interval_s: 1, fields: {}, checks: [], bogus: 1}}",
     "bogus"),
])
def test_corrupt_config_fails_clearly(tmp_path: Path, file: str, text: str, needle: str) -> None:
    d = _copy(tmp_path)
    (d / file).write_text(text)
    with pytest.raises(ConfigError, match=needle):
        load_config(d, make_settings(tmp_path))


def test_missing_config_file(tmp_path: Path) -> None:
    d = _copy(tmp_path)
    (d / "policies.yaml").unlink()
    with pytest.raises(ConfigError, match="missing config file"):
        load_config(d, make_settings(tmp_path))
    (d / "policies.yaml").write_text("- a list")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(d, make_settings(tmp_path))


def test_require_secrets() -> None:
    with pytest.raises(ConfigError, match="GUARDIAN_HMAC_KEY"):
        require_secrets(Settings(_env_file=None, TWIN_HMAC_KEY="t"))  # type: ignore[call-arg]
    with pytest.raises(ConfigError, match="API keys"):
        require_secrets(Settings(_env_file=None, TWIN_HMAC_KEY="t", GUARDIAN_HMAC_KEY="g"))  # type: ignore[call-arg]


def test_signer_round_trip_and_tamper() -> None:
    s = Signer("k")
    obj = {"b": 1, "a": [1, 2], "hmac": "x"}
    assert canonical_json(obj, "hmac") == b'{"a":[1,2],"b":1}'
    sig = s.sign(obj, exclude="hmac")
    assert s.verify(obj, sig, exclude="hmac")
    assert s.verify(obj, sig.upper(), exclude="hmac")
    assert not s.verify({**obj, "b": 2}, sig, exclude="hmac")
    assert not Signer("other").verify(obj, sig, exclude="hmac")
    assert not s.verify(obj, None)
    with pytest.raises(ValueError):
        Signer("")


async def test_audit_logger_writes_jsonl_and_timeline(tmp_path: Path) -> None:
    clock = FakeClock()
    em = TimelineEmitter(queue_size=2)
    q = em.subscribe("timeline")
    log = AuditLogger(tmp_path, "t5-guardian", clock, em)
    token = scenario_id_var.set("T1")
    log.emit("verdict", "hello", sensor_id="s1", zone_id="z", data={"kind": "verdict"})
    scenario_id_var.reset(token)
    log.emit("system", "two", extra=1)
    log.emit("system", "three")
    lines = [json.loads(x) for x in (tmp_path / "t5-guardian-20261102.log").read_text().splitlines()]
    assert lines[0]["scenario_id"] == "T1" and lines[0]["sensor_id"] == "s1"
    assert lines[1]["data"] == {"extra": 1} and lines[1]["scenario_id"] is None
    assert q.qsize() == 2 and (await q.get())["summary"] == "two"  # oldest dropped for slow consumer
    em.unsubscribe("timeline", q)
    assert em.subscribers("timeline") == 0
    clock.advance(86400)
    log.emit("system", "next day")
    assert (tmp_path / "t5-guardian-20261103.log").exists()
    log.close()
