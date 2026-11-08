from __future__ import annotations

from dataclasses import dataclass

from twin.engine.social_force import SocialForceState


@dataclass
class Pedestrian:
    id: str
    route_nodes: list[int]      # sequence of graph node ids to walk along, like Car.route_nodes
    edge_index: int = 0
    force: SocialForceState = None  # type: ignore[assignment]  # set in __post_init__
    heading: float = 0.0
    finished: bool = False

    # LLM agent: same shape as Car's agent fields, so main.py's decision dispatch
    # can treat cars and pedestrians uniformly (see agent_types.py)
    # a pedestrian spawned mid-sidewalk stands between these two nodes (the ends of its
    # sidewalk piece) until its first trip, which starts at whichever end is cheaper
    spawn_piece: tuple[int, int] | None = None
    persona: str | None = None
    current_place_name: str | None = None
    awaiting_decision: bool = False
    last_reason: str | None = None
    # "walking" | "waiting" (at a crosswalk kerb) | "arrived" (dwelling at a place)
    # | "injured" (hit by a car; terminal, removed when the ambulance clears the scene)
    # | "trapped" (stuck in deep floodwater until firefighters lead them out; flood_response.py)
    status: str = "walking"
    distracted: bool = False  # ignores signals and traffic gaps at crosswalks (still uses crosswalks)
    ignores_flood: bool = False  # walks into deep water the careful ones turn back from (scenarios only; flood_response.py)
    depart_at: float | None = None
    loop: bool = True

    def __post_init__(self) -> None:
        if self.force is None:
            self.force = SocialForceState(x=0.0, y=0.0)

    @property
    def x(self) -> float:
        return self.force.x

    @property
    def y(self) -> float:
        return self.force.y
