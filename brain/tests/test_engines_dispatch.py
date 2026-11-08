"""Dispatch by min-cost flow: all the open incidents solved together, with a certificate, never worse than nearest-first, and off by default."""

from datetime import UTC, datetime
from types import SimpleNamespace

from brain.citygraph import MemoryGraphStore
from brain.config import OptimiserConfig, Policy
from brain.contracts import Incident
from brain.departments import Manifest
from brain.engines.dispatch import Demand, OptimalChooser, Supply, solve_dispatch

LINE = lambda a, b: abs(int(a) - int(b))  # noqa: E731  zones are numbers on a line

# Two stations, one unit each, at the two ends of a line. X arrives first and is the nearer to A; Y is more serious and sits on A.
A, B = Supply("A", "1", 1), Supply("B", "6", 1)
X, Y = Demand("X", "2", 1.0), Demand("Y", "1", 5.0)


def test_the_optimal_assignment_beats_nearest_first_when_two_incidents_want_one_unit():
    solution = solve_dispatch([X, Y], [A, B], LINE)

    assert solution.nearest == {"X": "A", "Y": "B"} and solution.nearest_cost == 1 + 25
    assert solution.assignment == {"X": "B", "Y": "A"} and solution.certificate.objective == 4
    assert solution.regret_vs_nearest == 22 and solution.certificate.status == "optimal"


def test_the_solver_equals_nearest_when_there_is_no_contention():
    solution = solve_dispatch([X], [A, B], LINE)

    assert solution.assignment == solution.nearest == {"X": "A"} and solution.regret_vs_nearest == 0


def test_the_same_problem_gives_the_same_assignment_and_hash_every_time():
    runs = [solve_dispatch([Y, X], [B, A], LINE) for _ in range(5)]

    assert len({(tuple(sorted(r.assignment.items())), r.certificate.inputs_hash) for r in runs}) == 1


def test_an_incident_no_unit_can_reach_is_left_unmet_not_dropped():
    solution = solve_dispatch([X, Y], [A], LINE)

    assert sorted(v for v in solution.assignment.values() if v is None) == [None] and solution.assignment["Y"] == "A"


def test_a_timeout_falls_back_to_nearest_and_says_so():
    solution = solve_dispatch([X, Y], [A, B], LINE, time_limit_ms=-1)

    assert solution.certificate.status == "timeout" and solution.assignment == solution.nearest


# ---- through the chooser, on a real store

def city() -> tuple[MemoryGraphStore, SimpleNamespace]:
    store = MemoryGraphStore()
    store.load_topology({
        "zones": [{"id": str(n)} for n in range(1, 7)], "adjacency": [[str(n), str(n + 1)] for n in range(1, 6)],
        "facilities": [{"id": "ps-A", "type": "police_station", "zone_id": "1", "units": 1, "actuator_id": "dispatch-A"},
                       {"id": "ps-B", "type": "police_station", "zone_id": "6", "units": 1, "actuator_id": "dispatch-B"}]})
    police = Manifest(code="POLICE", name="Police", incident_types=["robbery", "fire"], actuators=["dispatch_unit:police"], facility_type="police_station")
    events: list[tuple] = []
    timeline = SimpleNamespace(emit=lambda type, subject, data, *a, **k: events.append((type, data)))
    return store, SimpleNamespace(store=store, manifests={"POLICE": police}, timeline=timeline, events=events)


def incident(store, id_, zone, type_, minute) -> Incident:
    item = Incident(incident_id=id_, type=type_, zone_id=zone, occurred_at=datetime(2026, 11, 4, 10, minute, tzinfo=UTC))
    store.add_incident(item)
    return item


def test_the_chooser_gives_the_serious_incident_the_close_unit_and_reports_the_regret():
    store, act = city()
    incident(store, "inc-1", "2", "robbery", 0)
    asking = incident(store, "inc-2", "1", "fire", 1)
    chooser = OptimalChooser({"robbery": 1.0, "fire": 5.0})

    station = chooser.choose(act, asking, "1", {}, "police_station")

    assert station["id"] == "ps-A"
    solved = next(data for type, data in act.events if type == "brain.solver.solved")
    assert solved["regret_vs_nearest"] > 0 and solved["status"] == "optimal" and solved["nearest"] == "ps-B"


def test_the_solver_never_uses_a_quarantined_station_or_the_reserve():
    store, act = city()
    asking = incident(store, "inc-2", "1", "fire", 1)
    store.mark_quarantined("dispatch-A")

    assert OptimalChooser({}).choose(act, asking, "1", {}, "police_station")["id"] == "ps-B"
    assert OptimalChooser({}).choose(act, asking, "1", {"ps-B": 1}, "police_station") is None


def test_a_failing_solver_falls_back_to_the_nearest_station_and_says_so():
    store, act = city()
    asking = incident(store, "inc-2", "1", "fire", 1)
    chooser = OptimalChooser({})
    chooser._demands = lambda *a: 1 / 0

    assert chooser.choose(act, asking, "1", {}, "police_station")["id"] == "ps-A"
    assert [d["why"] for t, d in act.events if t == "brain.solver.fallback"] == ["ZeroDivisionError"]


def test_the_solvers_are_on_by_default_and_the_plain_policy_turns_them_off():
    from tests.plain import plain

    assert Policy().optimiser == OptimiserConfig() and Policy().optimiser.dispatch == "on"
    assert plain().optimiser.dispatch == plain().optimiser.shed == plain().optimiser.perimeter == "off"
