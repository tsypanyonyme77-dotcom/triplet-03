"""Pedestrian network derived from the road graph: sidewalks on both sides of every
street, joined at street corners, plus crosswalks across every arm of every real
intersection (3+ streets). Pedestrians route on this graph only, so they can
reach the other side of a street only over a crosswalk.

Geometry per road node n, for each arm a (the street toward neighbour m) and
side s (left/right of travel n->m), there is a sidewalk end point E(n, a, s):
  - between two arms that form a corner of less than 180 degrees, both arms'
    sidewalk lines meet at the inner corner point, which is the end point of both;
  - otherwise the end point sits `t_a` metres along the arm, on its sidewalk line,
    where t_a clears the crossing streets' sidewalks (0 at simple bends);
  - corners of 180 degrees or more are walked round via an outer corner point.
A crosswalk across arm a joins E(n, a, left) and E(n, a, right).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx

from twin.engine.street_profile import CROSSWALK_WIDTH_M, SIDEWALK_WIDTH_M, STOP_LINE_GAP_M, right_sidewalk_offset

MAX_SIDEWALK_SEGMENT_M = 20.0   # long sidewalks are split so destinations have nearby nodes
MERGE_EPS_M = 0.05                # end points closer than this are the same walk node
COLLINEAR_SIN = 0.05                # |sin(angle)| below this: two arms count as a straight line
MAX_CORNER_DIST_M = 60.0              # sharper corners than this are joined directly


@dataclass(frozen=True)
class Crosswalk:
    id: str
    node: int          # road node of the intersection
    arm: int           # the crossed street runs node <-> arm
    a: int             # walk node at one end
    b: int             # walk node at the other end
    along_m: float     # distance from the intersection centre, along the arm, to the crosswalk centre
    signalised: bool


@dataclass
class WalkNetwork:
    graph: nx.Graph                                   # walk nodes: x, y, kind; edges: length, kind, crosswalk
    crosswalks: dict[str, Crosswalk] = field(default_factory=dict)

    def crosswalk_between(self, a: int, b: int) -> Crosswalk | None:
        cw_id = self.graph.edges[a, b].get("crosswalk") if self.graph.has_edge(a, b) else None
        return self.crosswalks.get(cw_id) if cw_id else None

    def crosswalk_at(self, node: int, arm: int) -> Crosswalk | None:
        return self.crosswalks.get(f"cw_{node}_{arm}")

    def stop_setback(self, u: int, v: int) -> float | None:
        """Metres before node v where cars on u->v stop: just before v's crosswalk across u."""
        cw = self.crosswalk_at(v, u)
        return None if cw is None else cw.along_m + CROSSWALK_WIDTH_M / 2 + STOP_LINE_GAP_M

    def crosswalks_on_edge(self, u: int, v: int, length: float) -> list[tuple[Crosswalk, float]]:
        """Crosswalks a car on u->v drives over, with the crosswalk centre's distance from u."""
        out = []
        leaving = self.crosswalk_at(u, v)
        if leaving:
            out.append((leaving, leaving.along_m))
        arriving = self.crosswalk_at(v, u)
        if arriving:
            out.append((arriving, length - arriving.along_m))
        return out

    def nearest_node(self, x: float, y: float, kind: str = "sidewalk") -> int:
        return min(
            (n for n, d in self.graph.nodes(data=True) if d["kind"] == kind),
            key=lambda n: math.hypot(self.graph.nodes[n]["x"] - x, self.graph.nodes[n]["y"] - y),
        )

    def xy(self, node: int) -> tuple[float, float]:
        d = self.graph.nodes[node]
        return d["x"], d["y"]


class _Builder:
    def __init__(self) -> None:
        self.g = nx.Graph()
        self._by_point: dict[tuple[int, int], int] = {}

    def node(self, x: float, y: float, kind: str) -> int:
        key = (round(x / MERGE_EPS_M), round(y / MERGE_EPS_M))
        if key not in self._by_point:
            node_id = len(self._by_point)
            self._by_point[key] = node_id
            self.g.add_node(node_id, x=x, y=y, kind=kind)
        elif kind == "corner":
            self.g.nodes[self._by_point[key]]["kind"] = "corner"
        return self._by_point[key]

    def edge(self, a: int, b: int, kind: str, **attrs) -> None:
        if a == b:
            return
        pa, pb = self.g.nodes[a], self.g.nodes[b]
        self.g.add_edge(a, b, kind=kind, length=math.hypot(pb["x"] - pa["x"], pb["y"] - pa["y"]), **attrs)

    def sidewalk(self, a: int, b: int) -> None:
        pa, pb = self.g.nodes[a], self.g.nodes[b]
        length = math.hypot(pb["x"] - pa["x"], pb["y"] - pa["y"])
        pieces = max(1, math.ceil(length / MAX_SIDEWALK_SEGMENT_M))
        prev = a
        for i in range(1, pieces):
            f = i / pieces
            mid = self.node(pa["x"] + (pb["x"] - pa["x"]) * f, pa["y"] + (pb["y"] - pa["y"]) * f, "sidewalk")
            self.edge(prev, mid, "sidewalk")
            prev = mid
        self.edge(prev, b, "sidewalk")


def _arms(road: nx.MultiDiGraph, n: int) -> list[tuple[int, float, float]]:
    """Neighbours of n as (neighbour, unit dx, unit dy), counter-clockwise by angle."""
    nd = road.nodes[n]
    out = []
    for m in set(road.predecessors(n)) | set(road.successors(n)):
        if m == n:
            continue
        md = road.nodes[m]
        dx, dy = md["x"] - nd["x"], md["y"] - nd["y"]
        dist = math.hypot(dx, dy)
        if dist > 1e-6:
            out.append((m, dx / dist, dy / dist))
    return sorted(out, key=lambda a: math.atan2(a[2], a[1]))


def _line_intersection(n1: tuple[float, float], c1: float, n2: tuple[float, float], c2: float):
    """Point p with p.n1 = c1 and p.n2 = c2, or None if the lines are parallel."""
    det = n1[0] * n2[1] - n1[1] * n2[0]
    if abs(det) < COLLINEAR_SIN:
        return None
    return (c1 * n2[1] - c2 * n1[1]) / det, (n1[0] * c2 - n2[0] * c1) / det


def build_walk_network(road: nx.MultiDiGraph, signalised_nodes: set[int]) -> WalkNetwork:
    b = _Builder()
    ends: dict[tuple[int, int, str], int] = {}  # (node, arm, "L"|"R") -> walk node
    crosswalks: dict[str, Crosswalk] = {}

    for n in road.nodes:
        nx_, ny_ = road.nodes[n]["x"], road.nodes[n]["y"]
        arms = _arms(road, n)
        if not arms:
            continue
        # sidewalk offsets: left of n->m is the right of m->n
        w_left = {m: right_sidewalk_offset(road, m, n) for m, _, _ in arms}
        w_right = {m: right_sidewalk_offset(road, n, m) for m, _, _ in arms}
        is_intersection = len(arms) >= 3

        # corners between consecutive arms (a, then b counter-clockwise): local coordinates
        inner: dict[tuple[int, str], tuple[float, float]] = {}
        outer: list[tuple[int, int, tuple[float, float] | None]] = []
        for i, (ma, ax, ay) in enumerate(arms):
            mb, bx, by = arms[(i + 1) % len(arms)]
            if len(arms) == 1:
                break
            gap = (math.atan2(by, bx) - math.atan2(ay, ax)) % (2 * math.pi)
            corner = _line_intersection((-ay, ax), w_left[ma], (by, -bx), w_right[mb])
            if corner is not None and math.hypot(*corner) > MAX_CORNER_DIST_M:
                corner = None
            if gap < math.pi - 1e-3 and corner is not None:
                inner[(ma, "L")] = corner
                inner[(mb, "R")] = corner
            else:
                outer.append((ma, mb, corner))

        # how far along each arm its free sidewalk ends sit
        clearance = max(max(w_left.values()), max(w_right.values()))
        along: dict[int, float] = {}
        for m, ux, uy in arms:
            t = clearance if is_intersection else 0.0
            for side in ("L", "R"):
                if (m, side) in inner:
                    cx, cy = inner[(m, side)]
                    t = max(t, cx * ux + cy * uy)
            along[m] = t

        for m, ux, uy in arms:
            for side, (px, py), w in (("L", (-uy, ux), w_left[m]), ("R", (uy, -ux), w_right[m])):
                if (m, side) in inner:
                    lx, ly = inner[(m, side)]
                    kind = "corner"
                else:
                    lx, ly = ux * along[m] + px * w, uy * along[m] + py * w
                    kind = "sidewalk"
                ends[(n, m, side)] = b.node(nx_ + lx, ny_ + ly, kind)

        for ma, mb, corner in outer:
            a_end, b_end = ends[(n, ma, "L")], ends[(n, mb, "R")]
            if corner is None:
                b.edge(a_end, b_end, "sidewalk")
            else:
                c = b.node(nx_ + corner[0], ny_ + corner[1], "corner")
                b.edge(a_end, c, "sidewalk")
                b.edge(c, b_end, "sidewalk")

        if is_intersection:
            for m, ux, uy in arms:
                left, right = ends[(n, m, "L")], ends[(n, m, "R")]
                cw = Crosswalk(
                    id=f"cw_{n}_{m}",
                    node=n,
                    arm=m,
                    a=left,
                    b=right,
                    along_m=along[m],
                    signalised=n in signalised_nodes,
                )
                crosswalks[cw.id] = cw
                b.edge(left, right, "crosswalk", crosswalk=cw.id)

    # sidewalks along every street, both sides, end to end
    seen = set()
    for u, v in road.edges():
        key = (min(u, v), max(u, v))
        if u == v or key in seen:
            continue
        seen.add(key)
        if (u, v, "L") in ends and (v, u, "R") in ends:
            b.sidewalk(ends[(u, v, "L")], ends[(v, u, "R")])
            b.sidewalk(ends[(u, v, "R")], ends[(v, u, "L")])

    return WalkNetwork(graph=b.g, crosswalks=crosswalks)


SIDEWALK_HALF_WIDTH_M = SIDEWALK_WIDTH_M / 2
CROSSWALK_HALF_WIDTH_M = CROSSWALK_WIDTH_M / 2
