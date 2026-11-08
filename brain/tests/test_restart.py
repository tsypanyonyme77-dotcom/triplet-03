"""A Brain that stops and starts again mid-incident carries on from what it saved."""

from brain.adapters import McpTwinAdapter, RestGuardianAdapter
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.persistence import StateFile
from brain.runtime import BrainService
from brain.scenario import inproc_partners, load_scenario
from brain.timeline import MemorySink, Timeline

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


class Life:
    """One run of the Brain process against partners that outlive it."""

    def __init__(self, twin_server, guardian_client, state_path, partners=None):
        self.sink = MemorySink()
        self.twin = McpTwinAdapter(twin_server, poll_interval_ms=10, stop_when_done=True)
        self.state = StateFile(state_path)
        self.service = BrainService(
            partners or PartnersConfig(), Policy(), self.twin, RestGuardianAdapter("", guardian_client),
            Timeline([self.sink]), MODELS, state=self.state,
        )
        self.raw: list[dict] = []

    async def __aenter__(self):
        await self.twin.__aenter__()
        await self.service.start()
        return self

    async def __aexit__(self, *exc):
        self.state.close()  # like a killed process: nothing more is saved
        await self.twin.__aexit__(*exc)

    async def handle(self, count: int) -> None:
        async for raw in self.twin.stream_readings():
            self.raw.append(raw)
            await self.service.handle(raw)
            if len(self.raw) == count:
                return

    def decisions(self) -> list[str]:
        return [e.data["action"] + ":" + str(e.data["params"].get("mode") or e.data["params"].get("unit_id") or "")
                for e in self.sink.of("brain.decision.made")]


async def start_scenario(twin_server, guardian_client, scenario):
    async with McpTwinAdapter(twin_server) as admin:
        await guardian_client.post("/admin/config", json=scenario.get("guardian", {}))
        playable = {key: scenario[key] for key in ("id", "topology", "events", "on_dispatch") if key in scenario}
        await admin.call_tool("admin_load_scenario", {"scenario": playable, "speed": 0})


async def actuator_log(twin_server) -> list[str]:
    async with McpTwinAdapter(twin_server) as admin:
        return [c["result"]["status"] for c in (await admin.call_tool("admin_actuator_log"))["calls"]]


async def test_a_restart_in_the_middle_of_a_pursuit_forgets_nothing(tmp_path):
    async with inproc_partners() as (twin_server, guardian_client):
        await start_scenario(twin_server, guardian_client, load_scenario("d3"))

        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as first:
            await first.handle(7)  # crime, pursuit, perimeter, and the suspect tracked into the Station
        assert first.decisions() == ["dispatch_unit:pursuit", "dispatch_unit:contain", "dispatch_unit:contain", "broadcast_alert:"]

        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as second:
            restored = second.sink.of("brain.state.restored")[0].data
            await second.service.handle(first.raw[3])  # an old reading sent again
            await second.service.run_until_quiet()

        assert restored["incidents_open"] == ["inc-0001"] and restored["decisions"] == 4
        assert restored["units_out"] == ["unit-p-01", "unit-p-02", "unit-p-03"]
        types = second.sink.types()
        assert "brain.incident.opened" not in types  # the same incident, not a new one
        assert types.count("brain.reading.rejected") == 1  # only the replay: the stream resumed where it stopped
        assert second.decisions() == ["recall_unit:unit-p-02", "recall_unit:unit-p-03"]  # nothing was dispatched twice
        assert [e.data["decision_id"] for e in second.sink.of("brain.decision.made")] == ["dec-0005", "dec-0006"]
        assert "brain.incident.closed" in types and second.service.store.units_out() == []
        assert second.service.store.provenance("dec-0001")["readings"]  # decisions made before the restart can still be explained
        assert await actuator_log(twin_server) == ["dispatched", "dispatched", "dispatched", "broadcast", "recalled", "recalled"]


async def test_a_crash_half_way_through_a_reading_repeats_it_without_dispatching_twice(tmp_path):
    async with inproc_partners() as (twin_server, guardian_client):
        await start_scenario(twin_server, guardian_client, load_scenario("d3"))

        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as first:
            await first.handle(5)

            async def killed_before_saving():
                raise SystemExit

            first.service._save = killed_before_saving
            try:
                await first.handle(6)  # the sighting that sends the pursuit and the perimeter out
            except SystemExit:
                pass

        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as second:
            assert second.sink.of("brain.state.restored")[0].data["decisions"] == 0
            await second.service.run_until_quiet()

        # The reading is handled again; the Twin answers `duplicate` and the Brain learns its units from that.
        assert await actuator_log(twin_server) == [
            "dispatched", "dispatched", "dispatched", "broadcast", "duplicate", "duplicate", "duplicate", "duplicate", "recalled", "recalled",
        ]
        released = second.sink.of("brain.units.released")[0].data["units"]
        assert sorted(unit["unit_id"] for unit in released) == ["unit-p-01", "unit-p-02", "unit-p-03"]
        assert "brain.incident.closed" in second.sink.types() and second.service.store.units_out() == []


async def test_state_from_another_session_is_discarded_not_restored(tmp_path):
    async with inproc_partners() as (twin_server, guardian_client):
        await start_scenario(twin_server, guardian_client, load_scenario("d3"))
        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as first:
            await first.handle(7)

        await start_scenario(twin_server, guardian_client, load_scenario("d3"))  # the Twin starts its stream again
        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as second:
            await second.service.run_until_quiet()

        assert "new stream" in second.sink.of("brain.state.discarded")[0].data["reason"]
        assert "brain.state.restored" not in second.sink.types()
        assert second.sink.types().count("brain.incident.opened") == 1 and "brain.reading.rejected" not in second.sink.types()


async def test_state_that_is_too_old_is_discarded(tmp_path):
    partners = PartnersConfig.model_validate({"brain": {"state_max_age_s": 0}})
    async with inproc_partners() as (twin_server, guardian_client):
        await start_scenario(twin_server, guardian_client, load_scenario("d3"))
        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite") as first:
            await first.handle(7)
        async with Life(twin_server, guardian_client, tmp_path / "brain.sqlite", partners) as second:
            discarded = second.sink.of("brain.state.discarded")

        assert "state_max_age_s" in discarded[0].data["reason"]


def test_the_audit_log_carries_on_across_a_restart_with_its_chain_unbroken(tmp_path):
    from brain.timeline import JsonlSink, verify_chain

    path = tmp_path / "live.jsonl"
    first = JsonlSink(path)
    Timeline([first]).emit("brain.started")
    Timeline([first]).emit("brain.incident.opened", "inc-0001")
    first.close()
    with path.open("a") as file:
        file.write('{"type": "brain.decision.made", "cut short by the cra')  # the process died mid-line

    second = JsonlSink(path, resume=True)
    Timeline([second]).emit("brain.state.restored")
    second.close()

    assert verify_chain(path) == (True, "3 records, chain intact")


def test_a_live_session_is_continued_only_while_its_state_is_fresh(tmp_path):
    from datetime import UTC, datetime, timedelta

    from brain.persistence import live_session

    def saved(age_s: float) -> None:
        state = StateFile(tmp_path / "state.sqlite")
        moment = datetime.now(UTC) - timedelta(seconds=age_s)
        state.save({"meta": {"saved_at": moment.isoformat(), "log": str(tmp_path / "earlier.jsonl")}})
        state.close()

    def session(fresh: bool = False):
        state, log, resumed = live_session("state.sqlite", 900, tmp_path, tmp_path, fresh)
        state.close()
        return log.name, resumed

    (tmp_path / "earlier.jsonl").write_text("")

    saved(age_s=5)
    assert session() == ("earlier.jsonl", True)
    assert session(fresh=True)[1] is False  # told to forget it

    saved(age_s=3600)
    assert session()[1] is False  # another day's rehearsal is not this session

    assert live_session("", 900, tmp_path, tmp_path, False)[0] is None  # no state file configured
