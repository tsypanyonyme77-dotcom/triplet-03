"""The Docker image installs the Twin read-only for the user that runs it, so importing must write nothing."""
import importlib
import pathlib

import pytest

from twin.engine import road_network


def test_importing_the_road_network_creates_no_folder(monkeypatch):
    def refuse(self, *_args, **_kwargs):
        raise PermissionError(f"read-only install: {self}")

    monkeypatch.setattr(pathlib.Path, "mkdir", refuse)
    importlib.reload(road_network)


def test_loading_a_real_map_creates_its_cache_folder_only_then(monkeypatch, tmp_path):
    pytest.importorskip("osmnx")  # optional, `--group osm`
    from unittest import mock

    cache = tmp_path / "data"
    monkeypatch.setattr(road_network, "CACHE_DIR", cache)
    with (mock.patch("osmnx.graph_from_address"), mock.patch("osmnx.routing.add_edge_speeds"),
          mock.patch("osmnx.routing.add_edge_travel_times"), mock.patch("osmnx.project_graph"),
          mock.patch.object(road_network, "_add_lane_counts"), mock.patch("osmnx.save_graphml")):
        assert not cache.exists()
        road_network.load_road_graph()
    assert cache.is_dir()
