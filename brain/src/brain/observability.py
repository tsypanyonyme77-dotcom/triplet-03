"""Metrics in the Prometheus text format, computed from the timeline.

A sink on the same event stream that feeds the screen: it counts events by type, gate decisions by outcome and check, solver work, retrieval
outages and what is open right now. `GET /metrics` renders them. Labels are event types, check names and component names only: never an id,
a token or a reading's value. No client library is needed for the text format; a collector scrapes the endpoint.
"""

from __future__ import annotations

import time
import urllib.request
from collections import Counter, defaultdict

from brain.config import GraphConfig
from brain.contracts import TimelineEvent


def _labels(**labels: str) -> str:
    return "{" + ",".join(f'{k}="{str(v).replace(chr(92), "").replace(chr(34), "")}"' for k, v in labels.items()) + "}" if labels else ""


_LOGIN: dict[str, tuple[float, int]] = {}


def _neo4j_answers(graph: GraphConfig, timeout: float) -> int:
    """1 when Neo4j accepts the Brain's login. The port answering is not enough: a wrong password answers too, and the Brain then runs in memory without anyone noticing.
    The login is tried once every 30 s, so a wrong password does not keep Neo4j's own lock-out (three failures) running against the people logging in."""
    now = time.monotonic()
    if (cached := _LOGIN.get(graph.uri)) and now - cached[0] < 30:
        return cached[1]
    from neo4j import GraphDatabase

    from brain.backends import LOCAL_NEO4J_PASSWORD
    from brain.config import secret

    try:
        with GraphDatabase.driver(graph.uri, auth=(graph.user, secret(graph.password_env) or LOCAL_NEO4J_PASSWORD), connection_timeout=timeout) as driver:
            driver.verify_connectivity()
        up = 1
    except Exception:  # noqa: BLE001 - unreachable, refused or a wrong password: all mean the City Graph is not being kept
        up = 0
    _LOGIN[graph.uri] = (now, up)
    return up


def store_status(graph: GraphConfig, timeout: float = 0.5) -> dict[str, int]:
    """1 for each configured store that answers right now: Neo4j when it accepts the Brain's login, a Qdrant server on /readyz (an embedded folder is always up).
    Neo4j Community has no metrics endpoint of its own, so this is how Prometheus learns whether the City Graph is being kept."""
    status: dict[str, int] = {}
    if graph.backend == "neo4j":
        status["neo4j"] = _neo4j_answers(graph, timeout)
    if graph.backend in ("neo4j", "qdrant") and (graph.qdrant_url or graph.qdrant_location):
        if graph.qdrant_url:
            try:
                urllib.request.urlopen(graph.qdrant_url.rstrip("/") + "/readyz", timeout=timeout).close()
                status["qdrant"] = 1
            except OSError:
                status["qdrant"] = 0
        else:
            status["qdrant"] = 1
    return status


class Metrics:
    def __init__(self) -> None:
        self.events: Counter[str] = Counter()
        self.gate: Counter[tuple[str, str]] = Counter()  # (allowed, check)
        self.degraded: dict[str, int] = {}
        self.solver_ms: dict[str, list[float]] = defaultdict(list)
        self.regret: float = 0.0
        self.open_incidents = 0
        self.units_out = 0

    def write(self, event: TimelineEvent) -> None:
        kind, data = event.type, event.data or {}
        self.events[kind] += 1
        if kind == "brain.decision.made":
            self.gate["true", "passed"] += 1
        elif kind == "brain.action.blocked":
            self.gate["false", str(data.get("check", "unknown"))] += 1
        elif kind == "brain.incident.opened":
            self.open_incidents += 1
        elif kind == "brain.incident.closed":
            self.open_incidents = max(self.open_incidents - 1, 0)
        elif kind == "brain.action.result" and data.get("status") == "dispatched":
            self.units_out += 1
        elif kind == "brain.units.released":
            self.units_out = max(self.units_out - len(data.get("units", [])), 0)
        elif kind == "brain.degraded":
            self.degraded[str(data.get("component", "unknown"))] = 1
        elif kind == "brain.recovered":
            self.degraded[str(data.get("component", "unknown"))] = 0
        elif kind.startswith("brain.solver.") and event.timing and "elapsed_ms" in event.timing:
            self.solver_ms[kind.rsplit(".", 1)[1]].append(float(event.timing["elapsed_ms"]))
        if kind == "brain.solver.solved":
            self.regret = float(data.get("regret_vs_nearest") or 0.0)

    def render(self, stores: dict[str, int] | None = None) -> str:
        lines: list[str] = []

        def metric(name: str, kind: str, help_: str, rows: list[tuple[str, float]]) -> None:
            lines.extend([f"# HELP {name} {help_}", f"# TYPE {name} {kind}", *(f"{name}{labels} {value}" for labels, value in rows)])

        metric("brain_events_total", "counter", "Timeline events by type.", [(_labels(type=t), n) for t, n in sorted(self.events.items())])
        metric("brain_gate_decisions_total", "counter", "Actions the gate passed or held, by the check that decided.",
               [(_labels(allowed=a, check=c), n) for (a, c), n in sorted(self.gate.items())])
        metric("brain_degraded", "gauge", "1 while a component is answering from its fallback.", [(_labels(component=c), v) for c, v in sorted(self.degraded.items())])
        metric("brain_solver_seconds_sum", "counter", "Time spent in solvers, by outcome.", [(_labels(outcome=o), round(sum(v) / 1000, 6)) for o, v in sorted(self.solver_ms.items())])
        metric("brain_solver_seconds_count", "counter", "Solver runs, by outcome.", [(_labels(outcome=o), len(v)) for o, v in sorted(self.solver_ms.items())])
        metric("brain_solver_regret", "gauge", "How much worse nearest-first was than the last dispatch solution.", [("", self.regret)])
        metric("brain_store_up", "gauge", "1 while a configured store (neo4j: the City Graph, qdrant: the knowledge vectors) answers.", [(_labels(store=s), v) for s, v in sorted((stores or {}).items())])
        metric("brain_open_incidents", "gauge", "Incidents open now.", [("", self.open_incidents)])
        metric("brain_units_out", "gauge", "Units dispatched and not yet back.", [("", self.units_out)])
        return "\n".join(lines) + "\n"
