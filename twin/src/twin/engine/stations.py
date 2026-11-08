"""Stations: a hospital, police station or fire station, with its vehicles' bays.

A station is a building behind the sidewalk with one or more parking bays in front of
it, reserved for its vehicles (no civilian car parks there). A map can name its
stations (twin/world/map.py); without, every generated hospital place becomes an
ambulance station at the free bay nearest to it.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from twin.engine.parking import ParkingSpot, free_spots_near

STATION_UNIT = {"hospital": "ambulance", "police_station": "police", "fire_station": "fire"}


@dataclass(frozen=True)
class Station:
    id: str
    kind: str                       # one of STATION_UNIT: hospital | police_station | fire_station
    label: str
    spot_ids: tuple[str, ...]       # one bay per vehicle

    @property
    def unit_kind(self) -> str:
        return STATION_UNIT[self.kind]


def stations_from_hospitals(graph: nx.MultiDiGraph, places: list[dict], spots: dict[str, ParkingSpot]) -> list[Station]:
    """The engine's default before named stations: one ambulance per generated hospital,
    in the free bay nearest to it. Bays already given to a station are skipped."""
    taken: set[str] = set()
    stations = []
    for place in places:
        if place["category"] != "hospital":
            continue
        near = [s for s, _ in free_spots_near(graph, spots, place["x"], place["y"], 4) if s.id not in taken]
        if not near:
            continue
        taken.add(near[0].id)
        stations.append(Station(id=place["id"], kind="hospital", label=place["name"], spot_ids=(near[0].id,)))
    return stations
