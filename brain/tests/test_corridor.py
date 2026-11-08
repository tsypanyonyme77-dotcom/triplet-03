"""The emergency corridor: the quickest way is not always the shortest, and signals are held only where there is one on the way."""

from brain.citygraph import MemoryGraphStore
from brain.engines.corridor import corridor

# Two ways from H (hospital) to I (incident): through M (short, three zones) or round by N1 and N2 (longer, five).
#   H - M - I
#   H - N1 - N2 - I
TOPOLOGY = {
    "zones": [{"id": z} for z in ("H", "M", "N1", "N2", "I")],
    "adjacency": [["H", "M"], ["M", "I"], ["H", "N1"], ["N1", "N2"], ["N2", "I"]],
    "facilities": [{"id": "sig-M", "type": "signal_controller", "zone_id": "M", "actuator_id": "signal-M"},
                   {"id": "sig-N1", "type": "signal_controller", "zone_id": "N1", "actuator_id": "signal-N1"},
                   {"id": "sig-far", "type": "signal_controller", "zone_id": "I", "actuator_id": "signal-I"}],
}


def city() -> MemoryGraphStore:
    store = MemoryGraphStore()
    store.load_topology(TOPOLOGY)
    return store


def test_the_corridor_avoids_a_congested_zone_when_a_longer_path_is_faster():
    free = corridor(city(), "H", "I", congestion={})
    jammed = corridor(city(), "H", "I", congestion={"M": 1.0})

    assert free.path == ["H", "M", "I"]
    assert jammed.path == ["H", "N1", "N2", "I"] and jammed.eta_s < jammed.plain_eta_s


def test_holds_are_placed_only_where_a_signal_controller_exists_in_a_zone_on_the_path():
    result = corridor(city(), "H", "I", congestion={"M": 1.0})

    assert [s.intersection_id for s in result.signals] == ["signal-N1", "signal-I"]  # in path order; N2 has none, M is not on the path


def test_no_hold_exceeds_3600_s():
    assert all(s.duration_s <= 3600 for s in corridor(city(), "H", "I", congestion={}, hop_s=5000).signals)


def test_a_twin_without_set_signal_phase_gets_no_corridor_holds():
    result = corridor(city(), "H", "I", congestion={}, can_signal=False)

    assert result.signals == [] and result.path


def test_the_gain_over_the_plain_path_is_reported():
    result = corridor(city(), "H", "I", congestion={"M": 1.0})

    assert result.gain_s == round(result.plain_eta_s - result.eta_s, 1) > 0
    assert corridor(city(), "H", "I", congestion={}).gain_s == 0


def test_two_corridors_do_not_drive_one_signal_inside_the_cooling_gap():
    first = corridor(city(), "H", "I", congestion={}, now_s=0.0)
    again = corridor(city(), "H", "I", congestion={}, now_s=30.0, held_until={s.intersection_id: 100.0 for s in first.signals})

    assert first.signals and again.signals == []


def test_disconnected_zones_have_no_corridor_and_the_certificate_names_the_problem():
    store = city()
    store.zones.add_node("X")

    assert corridor(store, "H", "X", congestion={}) is None
    assert corridor(city(), "H", "I", congestion={}).certificate.status == "optimal"
