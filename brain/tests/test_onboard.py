"""`brain onboard`: proposes renames and units for a Twin that names things differently. It proposes; a person edits the config."""

import json
from pathlib import Path

from brain.cli import build_parser
from brain.contracts.signing import sign
from brain.onboard import propose
from brain.perception import Perception

SAMPLE = json.loads((Path(__file__).parent / "data" / "renamed_twin_sample.json").read_text())["readings"]


def line(proposal, theirs, kind="type"):
    return next(l for l in proposal.lines if l["kind"] == kind and l["theirs"] == theirs)


def test_a_river_gauge_with_depth_cm_maps_to_water_level_with_scale_0_01():
    proposal = propose(SAMPLE)

    assert proposal.type_aliases["river_gauge"] == "water_level"
    assert proposal.profiles["water_level"]["level_m"] == {"from": "depth_cm", "scale": 0.01, "offset": 0.0}
    assert line(proposal, "river_gauge")["confidence"] >= 0.75 and not line(proposal, "river_gauge")["review"]


def test_a_percent_becomes_a_fraction_and_a_plain_name_is_matched_by_its_words():
    proposal = propose(SAMPLE)

    assert proposal.type_aliases["vehicle_counter"] == "traffic_camera"
    assert proposal.profiles["traffic_camera"]["congestion_score"]["scale"] == 0.01
    assert proposal.profiles["traffic_camera"]["vehicle_count"]["from"] == "cars"


def test_a_type_with_no_good_match_is_listed_unmapped_not_guessed():
    proposal = propose(SAMPLE)

    assert "bin_fill_sensor" in proposal.unmapped and "bin_fill_sensor" not in proposal.type_aliases


def test_a_mapping_below_the_confidence_floor_is_marked_review():
    proposal = propose(SAMPLE)

    loop = line(proposal, "sensor_loop")
    assert loop["ours"] == "power_load" and loop["review"] is True and loop["confidence"] < 0.75


def test_the_command_never_writes_the_config_file(tmp_path, capsys):
    from brain.cli import cmd_onboard

    config = Path(__file__).parents[1] / "config" / "partners.yaml"
    before = config.read_text()
    sample = tmp_path / "s.json"
    sample.write_text(json.dumps(SAMPLE))

    code = cmd_onboard(build_parser().parse_args(["onboard", "--sample", str(sample), "--yaml"]))

    assert code == 0 and config.read_text() == before
    assert "type_aliases" in capsys.readouterr().out


def test_the_proposal_applied_by_hand_makes_the_renamed_twin_pass_perception():
    proposal = propose(SAMPLE)
    perception = Perception(["2026-09-17"], "s", True, {t: {f: _profile(p) for f, p in fields.items()} for t, fields in proposal.profiles.items()}, proposal.type_aliases)
    reading = {"contract_version": "2026-09-17", "sensor_id": "rg-03", "type": "river_gauge", "zone_id": "zone-01", "timestamp": "2026-11-04T10:00:00.000Z",
               "sequence_no": 7, "value": {"depth_cm": 42.0}}

    perceived = perception.ingest(sign(reading, "s", "twin"))

    assert perceived.reading.type == "water_level" and abs(perceived.value.level_m - 0.42) < 1e-9


def _profile(raw):
    from brain.config import FieldProfile

    return FieldProfile(**{"from": raw["from"], "scale": raw["scale"], "offset": raw["offset"]})
