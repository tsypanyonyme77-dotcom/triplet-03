"""The workspace: two slots, ignition with hysteresis, and the timeline events that make attention visible."""

from datetime import timedelta

from brain.config import WorkspacePolicy
from brain.contracts import Incident
from brain.mind.bus import IncidentClosed, IncidentTouched
from brain.mind.workspace import Workspace
from brain.timeline import MemorySink, Timeline
from tests.conftest import T0

FLOOD = {"level_m": 1.3}


class Room:
    """A workspace over the `world` city, with helpers to add incidents of chosen strength."""

    def __init__(self, world, **policy):
        policy.setdefault("slots_for", "all")  # these tests are about slots, so every type competes unless a test says otherwise
        self.world, self.sink = world, MemorySink()
        self.incidents: dict[str, Incident] = {}
        self.workspace = Workspace(WorkspacePolicy(**policy), world.store, self.incidents, Timeline([self.sink]))
        self.n = 0

    def add(self, type="flood", zone="zone-01", status="trusted", sensors=1) -> str:
        self.n += 1
        readings = [self.world.reading(f"s-{self.n}-{k}", "water_level", zone, FLOOD, 5 + k, status=status) for k in range(sensors)]
        incident = Incident(incident_id=f"inc-{self.n:04d}", type=type, zone_id=zone, occurred_at=T0, evidence=readings)
        self.world.store.add_incident(incident)
        self.incidents[incident.incident_id] = incident
        return incident.incident_id

    async def touch(self, *ids, at_s=10):
        await self.workspace.on_touched(IncidentTouched(tuple(ids), None, T0 + timedelta(seconds=at_s)))

    def events(self, name):
        return [e for e in self.sink.events if e.type == f"brain.workspace.{name}"]


async def test_a_salient_incident_ignites_and_is_broadcast_on_the_timeline(world):
    room = Room(world)
    fire = room.add("fire", sensors=2)

    await room.touch(fire)

    assert room.workspace.is_lit(fire)
    (event,) = room.events("ignited")
    assert event.subject == fire and event.data["slots"] == [fire]
    assert event.data["salience"] >= 0.5 and set(event.data["features"]) >= {"severity", "trust"}


async def test_a_low_scoring_incident_does_not_ignite(world):
    room = Room(world)
    shaky = room.add("jam", status="untrusted")

    await room.touch(shaky)

    assert not room.workspace.is_lit(shaky)
    assert room.events("ignited") == [] and room.events("deferred") == []


async def test_a_third_salient_incident_is_deferred_when_both_slots_are_taken(world):
    room = Room(world)
    first, second, third = (room.add("fire", zone=z, sensors=2) for z in ("zone-01", "zone-03", "zone-09"))

    await room.touch(first, second, third)

    assert sorted(room.workspace.lit) == sorted([first, second])
    (event,) = room.events("deferred")
    assert event.subject == third and sorted(event.data["holding"]) == sorted([first, second])


async def test_a_much_more_salient_incident_displaces_the_weakest_lit_one(world):
    room = Room(world, severity={"flood": 0.55, "fire": 1.0}, weights={"severity": 6, "trust": 1, "corroboration": 0, "novelty": 0, "clustering": 0, "freshness": 0})
    weak_a, weak_b = room.add("flood", zone="zone-01"), room.add("flood", zone="zone-03")
    await room.touch(weak_a, weak_b)
    fire = room.add("fire", zone="zone-09")

    await room.touch(fire)

    assert room.workspace.is_lit(fire)
    released = room.events("released")
    assert len(released) == 1 and released[0].data["reason"] == "out-competed"
    assert len(room.workspace.lit) == 2


async def test_a_barely_better_incident_does_not_displace_a_lit_one(world):
    room = Room(world, severity={"flood": 0.80, "accident": 0.82}, weights={"severity": 6, "trust": 1, "corroboration": 0, "novelty": 0, "clustering": 0, "freshness": 0})
    a, b = room.add("flood", zone="zone-01"), room.add("flood", zone="zone-03")
    await room.touch(a, b)
    nudge = room.add("accident", zone="zone-09")

    await room.touch(nudge)

    assert not room.workspace.is_lit(nudge)
    assert room.events("released") == []


async def test_closing_an_incident_frees_its_slot_for_a_waiting_one(world):
    room = Room(world)
    first, second, waiting = (room.add("fire", zone=z, sensors=2) for z in ("zone-01", "zone-03", "zone-09"))
    await room.touch(first, second, waiting)
    assert not room.workspace.is_lit(waiting)

    await room.workspace.on_closed(IncidentClosed(first, "cleared", None))
    await room.touch(waiting)

    assert room.workspace.is_lit(waiting) and not room.workspace.is_lit(first)
    assert [e.data["reason"] for e in room.events("released")] == ["closed"]


async def test_a_deferred_incident_is_reported_once(world):
    room = Room(world)
    ids = [room.add("fire", zone=z, sensors=2) for z in ("zone-01", "zone-03", "zone-09")]
    await room.touch(*ids)

    await room.touch(ids[2], at_s=11)
    await room.touch(ids[2], at_s=12)

    assert len(room.events("deferred")) == 1


async def test_a_lit_incident_that_goes_stale_gives_its_slot_up(world):
    room = Room(world)
    fire = room.add("fire", sensors=2)
    await room.touch(fire)

    await room.touch(at_s=100_000)  # something else happened a day later; the fire has faded from attention

    assert not room.workspace.is_lit(fire)
    assert [e.data["reason"] for e in room.events("released")] == ["faded"]


# --- slots only for the incident types an agent team can act on --------------------------------------------------------


async def test_with_every_type_competing_a_flood_takes_a_slot_a_robbery_could_have_used(world):
    room = Room(world, slots=1, slots_for="all")
    flood, robbery = room.add("flood", sensors=2), room.add("crime", zone="zone-07", sensors=2)

    await room.touch(flood, robbery)

    assert room.workspace.is_lit(flood) and not room.workspace.is_lit(robbery)
    assert [e.subject for e in room.events("deferred")] == [robbery]


async def test_with_team_slots_a_flood_is_lit_without_taking_a_slot(world):
    room = Room(world, slots=1, slots_for="team")
    flood, robbery = room.add("flood", sensors=2), room.add("crime", zone="zone-07", sensors=2)

    await room.touch(flood, robbery)

    assert room.workspace.is_lit(flood) and room.workspace.is_lit(robbery)
    by_subject = {e.subject: e.data for e in room.events("ignited")}
    assert by_subject[flood]["slot"] is False and by_subject[flood]["slots"] == []
    assert by_subject[robbery]["slot"] is True and by_subject[robbery]["slots"] == [robbery]
    assert room.events("deferred") == []


async def test_with_team_slots_two_robberies_still_fill_two_slots_and_a_third_waits(world):
    room = Room(world, slots=2, slots_for="team")
    first, second, third = (room.add("crime", zone=zone, sensors=2) for zone in ("zone-07", "zone-03", "zone-05"))

    await room.touch(first, second, third)

    assert room.workspace.is_lit(first) and room.workspace.is_lit(second) and not room.workspace.is_lit(third)


async def test_a_slotless_light_goes_out_when_its_incident_closes_or_fades(world):
    room = Room(world, slots=1, slots_for="team")
    flood = room.add("flood", sensors=2)
    await room.touch(flood)
    assert room.workspace.is_lit(flood)

    await room.workspace.on_closed(IncidentClosed(flood, "cleared", None))

    assert not room.workspace.is_lit(flood)
    (released,) = room.events("released")
    assert released.subject == flood and released.data["reason"] == "closed"


async def test_a_slotless_light_that_is_not_refreshed_fades_like_any_other(world):
    room = Room(world, slots=1, slots_for="team", freshness_halflife_s=5)
    flood = room.add("flood", sensors=2)
    await room.touch(flood, at_s=6)

    await room.touch(at_s=400)

    assert not room.workspace.is_lit(flood)
    assert [e.data["reason"] for e in room.events("released")] == ["faded"]


# --- aging: waiting counts for something, within a cap -----------------------------------------------------------------


async def two_lit_and_one_waiting(world, **policy):
    room = Room(world, slots=2, margin=0.25, **policy)
    a, b = room.add("crime", zone="zone-07", sensors=2), room.add("crime", zone="zone-03", sensors=2)
    await room.touch(a, b, at_s=10)
    waiting = room.add("crime", zone="zone-05", sensors=3)  # a little better than the lit ones, but not by the margin
    await room.touch(waiting, at_s=11)
    return room, a, b, waiting


async def test_without_aging_a_waiting_incident_waits_for_ever_however_long_it_has_been(world):
    room, a, b, waiting = await two_lit_and_one_waiting(world)
    assert not room.workspace.is_lit(waiting)

    await room.touch(waiting, at_s=200)

    assert not room.workspace.is_lit(waiting) and len(room.events("deferred")) == 1


async def test_with_aging_a_waiting_incident_displaces_the_weakest_once_it_has_waited_long_enough(world):
    room, a, b, waiting = await two_lit_and_one_waiting(world, aging_per_s=0.05, aging_cap=0.3)
    assert not room.workspace.is_lit(waiting)

    await room.touch(waiting, at_s=20)

    assert room.workspace.is_lit(waiting)
    assert [e.data["reason"] for e in room.events("released")] == ["out-competed"]


async def test_aging_is_capped_so_a_long_wait_cannot_beat_a_much_stronger_incident(world):
    room = Room(world, slots=1, aging_per_s=0.05, aging_cap=0.1, freshness_halflife_s=1e9)
    strong = room.add("fire", sensors=3)
    await room.touch(strong, at_s=10)
    weak = room.add("crime", zone="zone-05", sensors=1)
    await room.touch(weak, at_s=11)

    await room.touch(weak, at_s=5000)

    assert room.workspace.is_lit(strong) and not room.workspace.is_lit(weak)


async def test_an_incident_that_never_waited_gets_no_aging_bonus(world):
    room = Room(world, slots=1, aging_per_s=0.5, aging_cap=0.5)
    lit = room.add("crime", zone="zone-07", sensors=3)
    await room.touch(lit, at_s=10)
    newcomer = room.add("crime", zone="zone-03", sensors=2)

    await room.touch(newcomer, at_s=10)

    assert not room.workspace.is_lit(newcomer)  # first sight: no wait, so no bonus
