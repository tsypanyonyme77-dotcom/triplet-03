"""Zone criticality: articulation points, betweenness and the cut weight, and a one-batch idempotent write-back."""

import json
from pathlib import Path

import networkx as nx

from brain.citygraph import MemoryGraphStore
from brain.citygraph.analytics import criticality, write_back_query


def path_city() -> MemoryGraphStore:
    store = MemoryGraphStore()
    store.load_topology({"zones": [{"id": z} for z in "abc"], "adjacency": [["a", "b"], ["b", "c"]],
                         "facilities": [{"id": "h", "type": "hospital", "zone_id": "c"}]})
    return store


def test_an_articulation_zone_is_flagged_on_a_path_graph():
    result = criticality(path_city(), {})

    assert [z for z, c in result.items() if c.is_articulation] == ["b"] and result["c"].n_minus_1_weight == 10.0


def test_betweenness_matches_networkx_on_the_small_city():
    store = MemoryGraphStore()
    store.load_topology(json.loads((Path(__file__).parents[1] / "scenarios/topology/small-city.json").read_text()))
    expected = nx.betweenness_centrality(store.zones)

    assert {z: c.betweenness for z, c in criticality(store, {}).items()} == {z: round(v, 4) for z, v in expected.items()}


def test_write_back_is_one_batch_and_idempotent():
    results = criticality(path_city(), {})
    query, params = write_back_query(results)

    assert query.count("UNWIND") == 1 and len(params["rows"]) == 3 and write_back_query(results) == (query, params)
    assert "CREATE" not in query and "MERGE" not in query  # it sets properties on existing zones, so running it twice changes nothing
