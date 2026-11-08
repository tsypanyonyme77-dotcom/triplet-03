from brain.config import ScoringPolicy
from brain.departments.police import assess

POLICY = ScoringPolicy()


def test_bystander_at_the_scene_is_not_a_suspect(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-1", "zone-07", at_s=8)
    world.sighting("cit-1", "zone-07", at_s=14)

    result = assess(incident, "cit-1", world.store, POLICY)

    assert result.level == "none"
    assert [f.name for f in result.features] == ["copresence"]


def test_presence_plus_flight_from_two_trusted_sensors_is_a_suspect(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-2", "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running", heading="zone-09")

    result = assess(incident, "cit-2", world.store, POLICY)

    assert result.level == "suspect"
    assert result.score >= POLICY.suspect_threshold
    assert result.trusted_sources == ["cam-07-02", "cit-feed-07", "cit-feed-08"]
    assert result.last_zone_id == "zone-08"


def test_runner_far_from_the_scene_is_ignored(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-3", "zone-03", at_s=20, speed=18, activity="running")

    result = assess(incident, "cit-3", world.store, POLICY)

    assert result.level == "none"
    assert result.features == []


def test_untrusted_crime_evidence_cannot_make_a_suspect(world):
    incident = world.crime(at_s=10, status="untrusted")
    world.sighting("cit-2", "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")

    result = assess(incident, "cit-2", world.store, POLICY)

    assert result.raw_score >= POLICY.suspect_threshold  # the data alone says "suspect"
    assert result.score < 0.1  # the trust-weighted evidence does not
    assert result.level == "none"
    assert result.discounted[0]["status"] == "untrusted"


def test_suspicious_flight_reading_is_discounted(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-2", "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running", status="suspicious")

    result = assess(incident, "cit-2", world.store, POLICY)

    assert result.level == "none"
    assert "cit-feed-08" not in result.trusted_sources


def test_when_two_people_run_flight_singles_no_one_out(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-3", "zone-04", at_s=14, speed=15, activity="running", heading="zone-01")
    world.sighting("cit-2", "zone-08", at_s=15, speed=18, activity="running", heading="zone-09")

    offender, bystander = (assess(incident, c, world.store, POLICY) for c in ("cit-2", "cit-3"))

    assert (offender.level, bystander.level) == ("poi", "poi")
    assert offender.fled_with == ["cit-3"] and bystander.fled_with == ["cit-2"]
    flight = next(f for f in offender.features if f.name == "flight")
    assert flight.x == 0.5 and "one of 2 people who left the scene fast" in flight.note


def test_a_doubtful_report_of_another_runner_cannot_shield_a_suspect(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-3", "zone-04", at_s=14, speed=15, activity="running", status="untrusted")
    world.sighting("cit-2", "zone-08", at_s=15, speed=18, activity="running")

    result = assess(incident, "cit-2", world.store, POLICY)

    assert result.level == "suspect" and result.fled_with == []
    assert result.raw_score < POLICY.suspect_threshold  # believed as it stands, the data would not single them out


def test_flight_names_no_one_until_the_others_at_the_scene_are_accounted_for(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=12, speed=18, activity="running")

    waiting = assess(incident, "cit-2", world.store, POLICY)
    world.sighting("cit-3", "zone-07", at_s=13)  # still there, walking
    settled = assess(incident, "cit-2", world.store, POLICY)

    assert (waiting.level, waiting.unaccounted) == ("poi", ["cit-3"])
    assert (settled.level, settled.unaccounted) == ("suspect", [])


def test_someone_who_is_never_seen_again_holds_the_decision_up_only_briefly(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=12, speed=18, activity="running")
    world.sighting("cit-2", "zone-08", at_s=10 + POLICY.settle_s, speed=18, activity="running")

    assert assess(incident, "cit-2", world.store, POLICY).level == "suspect"


def test_a_trusted_sensor_can_confirm_a_flight_first_reported_by_a_doubtful_one(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-2", "zone-07", at_s=9)
    world.reading("cit-wifi-07", "citizen_activity", "zone-07",
                  {"citizen_id": "cit-2", "activity": "running", "speed_kmh": 17, "heading_zone_id": "zone-08"}, 12, "suspicious")
    doubtful = assess(incident, "cit-2", world.store, POLICY)
    world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")
    confirmed = assess(incident, "cit-2", world.store, POLICY)

    assert doubtful.level == "none" and doubtful.raw_score >= POLICY.suspect_threshold
    assert confirmed.level == "suspect" and "cit-feed-08#1" in confirmed.evidence_reading_ids


def test_a_camera_identification_names_one_of_several_runners(world):
    incident = world.crime(at_s=10, entity_id="cit-2")
    for citizen in ("cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-3", "zone-04", at_s=14, speed=15, activity="running")
    world.sighting("cit-2", "zone-08", at_s=15, speed=18, activity="running")

    assert assess(incident, "cit-2", world.store, POLICY).level == "suspect"
    assert assess(incident, "cit-3", world.store, POLICY).level == "poi"


def test_direct_identification_by_a_trusted_camera(world):
    incident = world.crime(at_s=10, entity_id="cit-9")
    world.sighting("cit-9", "zone-07", at_s=9)

    result = assess(incident, "cit-9", world.store, POLICY)

    assert result.level == "suspect"
    assert result.direct_reading_id == incident.evidence[0]


def test_demographic_fields_never_reach_scoring(world):
    from brain.contracts import CitizenActivity

    value = CitizenActivity.model_validate({"citizen_id": "cit-1", "age": 19, "wealth": "low", "education": 1})
    assert set(value.model_dump()) == {"citizen_id", "zone_id", "node_id", "activity", "speed_kmh", "heading_zone_id", "flags"}
