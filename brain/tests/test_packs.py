"""Packs are files: dropping one into a folder teaches the Brain a new service without touching its code."""

import textwrap

from brain.config import BrainConfig, PartnersConfig
from brain.departments import discover_manifests
from tests.test_conditions import scenario
from tests.test_scenarios import play

NOISE_PACK = textwrap.dedent("""
    code: NOISE
    name: Noise control
    version: "1"
    incident_types: [noise]
    actuators: [broadcast_alert]
    reflex_rules: noise.yaml
    severity: {noise: 0.45}
    detectors:
      - reading: noise_level
        incident: noise
        when: [{field: db, op: ">=", value: 85}]
        clear: [{field: db, op: "<=", value: 70}]
""")
NOISE_RULES = textwrap.dedent("""
    rules:
      - id: NOI-001
        name: noise.advisory
        scope: condition
        when: {incident.type: noise}
        do:
          - action: broadcast_alert
            params: {message: "Noise is high. Please keep it down.", channel: app, zone_id: $incident.zone_id}
""")


def noise(at_ms, db, sensor="nl-02-01"):
    return {"at_ms": at_ms, "sensor_id": sensor, "type": "noise_level", "zone_id": "zone-02", "value": {"db": db}}


def partners_with(folder) -> PartnersConfig:
    return PartnersConfig(brain=BrainConfig(packs_dir=str(folder)))


def write_pack(folder, name="noise", pack=NOISE_PACK, rules=NOISE_RULES):
    (folder / "rules").mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(pack)
    (folder / "rules" / "noise.yaml").write_text(rules)


def test_the_built_in_packs_are_all_discovered():
    packs, problems = discover_manifests()

    assert sorted(packs) == ["DISASTER", "FIRE", "MEDICAL", "MOBILITY", "POLICE", "UTILITIES"] and problems == []


def test_a_pack_can_replace_a_built_in_pack_by_code(tmp_path):
    (tmp_path / "mobility.yaml").write_text("code: MOBILITY\nname: Mobility, city edition\nversion: '2'\nactuators: [set_signal_phase]\n")

    packs, problems = discover_manifests(tmp_path)

    assert packs["MOBILITY"].name == "Mobility, city edition" and packs["MOBILITY"].version == "2" and problems == []
    assert "POLICE" in packs


def test_a_broken_pack_file_is_reported_and_skipped(tmp_path):
    (tmp_path / "garbage.yaml").write_text("code: [unclosed\n  name: :")
    (tmp_path / "typo.yaml").write_text("code: TYPO\nname: Typo\nactuators: []\nincident_type: [x]\n")
    (tmp_path / "badop.yaml").write_text("code: BADOP\nname: Bad\ndetectors:\n  - {reading: a, incident: b, when: [{field: x, op: '~=', value: 1}]}\n")
    (tmp_path / "norules.yaml").write_text("code: NORULES\nname: No rules\nreflex_rules: missing.yaml\n")

    packs, problems = discover_manifests(tmp_path)

    assert sorted(file for file, _ in problems) == ["badop.yaml", "garbage.yaml", "norules.yaml", "typo.yaml"]
    assert all(reason for _, reason in problems)
    assert sorted(packs) == ["DISASTER", "FIRE", "MEDICAL", "MOBILITY", "POLICE", "UTILITIES"]


async def test_a_pack_dropped_into_the_packs_folder_is_discovered_and_answers(tmp_path):
    write_pack(tmp_path)

    result = await play(scenario([noise(100, 90), noise(300, 92), noise(900, 60)]), partners=partners_with(tmp_path))

    assert len(result.sink.of("brain.incident.opened")) == 1
    alerts = [c["call"]["params"] for c in result.actuator_calls if c["call"]["action"] == "broadcast_alert"]
    assert alerts == [{"message": "Noise is high. Please keep it down.", "channel": "app", "zone_id": "zone-02"}]
    assert result.sink.of("brain.incident.opened")[0].data["departments"] == ["NOISE"]
    assert len(result.sink.of("brain.incident.closed")) == 1
    assert result.sink.of("brain.started")[0].data["departments"] == ["POLICE", "FIRE", "MEDICAL", "MOBILITY", "DISASTER", "UTILITIES", "NOISE"]


async def test_without_the_pack_the_same_readings_open_nothing():
    result = await play(scenario([noise(100, 90), noise(300, 92)]))

    assert result.sink.of("brain.incident.opened") == []


async def test_a_broken_pack_is_reported_on_the_timeline_and_the_brain_carries_on(tmp_path):
    (tmp_path / "typo.yaml").write_text("code: TYPO\nname: Typo\nincident_type: [x]\n")

    result = await play(scenario([noise(100, 90)]), partners=partners_with(tmp_path))

    (event,) = result.sink.of("brain.pack.rejected")
    assert event.data["file"] == "typo.yaml" and "incident_type" in event.data["reason"]
    assert result.sink.of("brain.started")


async def test_a_twin_that_renames_its_sensor_and_field_is_absorbed_by_two_lines_of_config():
    from brain.config import TwinConfig

    twin = TwinConfig.model_validate({"type_aliases": {"river_gauge": "water_level"},
                                      "profiles": {"water_level": {"level_m": {"from": "depth_cm", "scale": 0.01}}}})
    gauge = {"at_ms": 100, "sensor_id": "wl-01-01", "type": "river_gauge", "zone_id": "zone-01", "value": {"depth_cm": 135}}

    renamed = await play(scenario([gauge]), partners=PartnersConfig(twin=twin))
    plain = await play(scenario([gauge]))

    assert [c["call"]["action"] for c in renamed.actuator_calls] == ["broadcast_alert"]
    assert plain.actuator_calls == [] and plain.sink.of("brain.incident.opened") == []  # a type the Brain does not know is stored and ignored
