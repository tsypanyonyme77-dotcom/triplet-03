"""Neo4j as the durable City Graph.

The decision path reads the in-memory graph and never waits on a database. Every write
is also queued here and applied to Neo4j in order by a background task (write-behind).
Neo4j then holds the full five-layer graph across runs, serves knowledge retrieval
(vector and full-text indexes), and can be explored in the Neo4j Browser.

If Neo4j goes away mid-run the queue reports the error once and the Brain keeps deciding.

Live and provenance nodes carry a `run_id` and a `uid` (`<run_id>:<id>`), so runs that
reuse IDs such as `inc-0001` stay separate. Topology and knowledge nodes are shared.
Time-bearing nodes and edges are bi-temporal: `valid_at` (when it was true in the city),
`ingested_at` (when the Brain learned it) and `invalid_at` (set if later withdrawn).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from brain.citygraph.store import MemoryGraphStore, Sighting
from brain.contracts import CitizenActivity, Incident, ProposedAction, SensorReading, TrustVerdict
from brain.knowledge.embedding import DIMENSIONS

SCHEMA = [
    *(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
      for label in ("Zone", "Sensor", "Facility", "Department", "Knowledge")),
    *(f"CREATE CONSTRAINT {label.lower()}_name IF NOT EXISTS FOR (n:{label}) REQUIRE n.name IS UNIQUE"
      for label in ("IncidentType", "ActionType")),
    *(f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE"
      for label in ("Reading", "Verdict", "Entity", "Incident", "Decision", "Action")),
    f"""CREATE VECTOR INDEX knowledge_embedding IF NOT EXISTS FOR (k:Knowledge) ON (k.embedding)
        OPTIONS {{indexConfig: {{`vector.dimensions`: {DIMENSIONS}, `vector.similarity_function`: 'cosine'}}}}""",
    "CREATE FULLTEXT INDEX knowledge_text IF NOT EXISTS FOR (k:Knowledge) ON EACH [k.title, k.text]",
]


class Neo4jMirror:
    def __init__(self, uri: str, user: str, password: str, database: str, run_id: str,
                 on_error: Callable[[str], None] | None = None) -> None:
        self.uri, self.database, self.run_id = uri, database, run_id
        self._auth = (user, password)
        self._on_error = on_error
        self._driver: AsyncDriver | None = None
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.errors = 0
        self.written = 0

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(self.uri, auth=self._auth, connection_timeout=5)
        await self._driver.verify_connectivity()
        for statement in SCHEMA:
            await self._driver.execute_query(statement, database_=self.database)
        await self._driver.execute_query("CALL db.awaitIndexes(30)", database_=self.database)
        self._task = asyncio.create_task(self._flush_loop())

    def uid(self, identifier: str) -> str:
        return f"{self.run_id}:{identifier}"

    def write(self, cypher: str, **params: Any) -> None:
        """Queue one statement. Never blocks and never raises: the caller is on the decision path."""
        self._queue.put_nowait((cypher, params))

    async def _flush_loop(self) -> None:
        assert self._driver is not None
        while True:
            batch = [await self._queue.get()]
            while not self._queue.empty() and len(batch) < 200:
                batch.append(self._queue.get_nowait())
            try:
                async with self._driver.session(database=self.database) as session:
                    await session.execute_write(self._apply, batch)
                self.written += len(batch)
            except Exception as error:  # noqa: BLE001 - a failed mirror write is counted and the decision path goes on
                self.errors += 1
                if self.errors == 1 and self._on_error is not None:
                    self._on_error(f"{type(error).__name__}: {str(error)[:300]}")
            finally:
                for _ in batch:
                    self._queue.task_done()

    @staticmethod
    async def _apply(tx: AsyncManagedTransaction, batch: list[tuple[str, dict[str, Any]]]) -> None:
        for cypher, params in batch:
            result = await tx.run(cypher, params)
            await result.consume()

    async def flush(self) -> None:
        """Wait until everything queued so far is in Neo4j."""
        await self._queue.join()

    async def query(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        assert self._driver is not None, "connect() first"
        result = await self._driver.execute_query(cypher, params, database_=self.database)
        return [record.data() for record in result.records]

    async def close(self) -> None:
        if self._driver is None:
            return
        await self.flush()
        if self._task is not None:
            self._task.cancel()
        await self._driver.close()
        self._driver = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class MirroredGraphStore(MemoryGraphStore):
    """The in-memory store, with every write copied to Neo4j."""

    def __init__(self, mirror: Neo4jMirror) -> None:
        super().__init__()
        self.mirror = mirror
        self._at_scene: set[tuple[str, str]] = set()

    def load_topology(self, topology: dict[str, Any]) -> None:
        super().load_topology(topology)
        write = self.mirror.write
        write("""UNWIND $zones AS z MERGE (n:Zone {id: z.id})
                 SET n.name = z.name, n.x = z.x, n.y = z.y, n.is_exit = z.id IN $exits""",
              zones=topology.get("zones", []), exits=self.exits)
        write("""UNWIND $pairs AS p MATCH (a:Zone {id: p[0]}), (b:Zone {id: p[1]})
                 MERGE (a)-[:ADJACENT_TO]->(b) MERGE (b)-[:ADJACENT_TO]->(a)""",
              pairs=topology.get("adjacency", []))
        write("""UNWIND $facilities AS f MERGE (n:Facility {id: f.id})
                 SET n.type = f.type, n.actuator_id = f.actuator_id, n.units = f.units, n.quarantined = false
                 WITH n, f MATCH (z:Zone {id: f.zone_id}) MERGE (n)-[:LOCATED_IN]->(z)""",
              facilities=self.facilities())
        write("""UNWIND $sensors AS s MERGE (n:Sensor {id: s.id}) SET n.type = s.type
                 WITH n, s MATCH (z:Zone {id: s.zone_id}) MERGE (n)-[:MONITORS]->(z)""",
              sensors=topology.get("sensors", []))

    def mark_quarantined(self, actuator_id: str) -> None:
        super().mark_quarantined(actuator_id)
        self.mirror.write("MATCH (f:Facility {actuator_id: $actuator_id}) SET f.quarantined = true", actuator_id=actuator_id)

    def add_reading(self, reading: SensorReading, verdict: TrustVerdict) -> None:
        super().add_reading(reading, verdict)
        m = self.mirror
        m.write(
            """MERGE (r:Reading {uid: $uid})
               SET r.id = $id, r.run_id = $run, r.type = $type, r.sensor_id = $sensor, r.zone_id = $zone,
                   r.sequence_no = $seq, r.value = $value, r.valid_at = $valid_at, r.ingested_at = datetime(), r.invalid_at = null
               MERGE (v:Verdict {uid: $vuid})
               SET v.id = $vid, v.run_id = $run, v.status = $status, v.confidence = $confidence,
                   v.reasons = $reasons, v.valid_at = $issued_at, v.expires_at = $expires_at
               MERGE (r)-[:VERIFIED_BY]->(v)
               MERGE (s:Sensor {id: $sensor}) MERGE (r)-[:REPORTED_BY]->(s)
               MERGE (z:Zone {id: $zone}) MERGE (r)-[:OBSERVED_AT]->(z)""",
            uid=m.uid(reading.reading_id), id=reading.reading_id, run=m.run_id, type=reading.type,
            sensor=reading.sensor_id, zone=reading.zone_id, seq=reading.sequence_no, value=_json(reading.value),
            valid_at=reading.timestamp, vuid=m.uid(verdict.verdict_id), vid=verdict.verdict_id,
            status=verdict.status.value, confidence=verdict.confidence, reasons=verdict.reasons,
            issued_at=verdict.issued_at, expires_at=verdict.expires_at,
        )

    def add_sighting(self, reading: SensorReading, value: CitizenActivity) -> Sighting:
        sighting = super().add_sighting(reading, value)
        m = self.mirror
        m.write(
            """MERGE (e:Entity {uid: $uid}) SET e.id = $id, e.run_id = $run, e.kind = 'citizen'
               MERGE (z:Zone {id: $zone})
               CREATE (e)-[:PRESENT_AT {reading_id: $reading_id, speed_kmh: $speed, activity: $activity,
                                        valid_at: $at, ingested_at: datetime()}]->(z)""",
            uid=m.uid(value.citizen_id), id=value.citizen_id, run=m.run_id, zone=sighting.zone_id,
            reading_id=reading.reading_id, speed=sighting.speed_kmh, activity=sighting.activity, at=sighting.time,
        )
        return sighting

    def add_incident(self, incident: Incident) -> None:
        super().add_incident(incident)
        m = self.mirror
        m.write(
            """MERGE (i:Incident {uid: $uid})
               SET i.id = $id, i.run_id = $run, i.type = $type, i.status = 'open', i.zone_id = $zone,
                   i.valid_at = $at, i.ingested_at = datetime()
               MERGE (t:IncidentType {name: $type}) MERGE (i)-[:OF_TYPE]->(t)
               MERGE (z:Zone {id: $zone}) MERGE (i)-[:OCCURRED_IN]->(z)""",
            uid=m.uid(incident.incident_id), id=incident.incident_id, run=m.run_id, type=incident.type,
            zone=incident.zone_id, at=incident.occurred_at,
        )

    def close_incident(self, incident: Incident) -> None:
        super().close_incident(incident)
        self.mirror.write(
            "MATCH (i:Incident {uid: $uid}) SET i.status = 'closed', i.outcome = $outcome, i.closed_at = datetime()",
            uid=self.mirror.uid(incident.incident_id), outcome=incident.outcome,
        )

    def link_evidence(self, reading_id: str, incident_id: str) -> None:
        super().link_evidence(reading_id, incident_id)
        self.mirror.write(
            "MATCH (r:Reading {uid: $r}), (i:Incident {uid: $i}) MERGE (r)-[:EVIDENCE_FOR]->(i)",
            r=self.mirror.uid(reading_id), i=self.mirror.uid(incident_id),
        )

    def mark_at_scene(self, entity_id: str, incident_id: str) -> None:
        super().mark_at_scene(entity_id, incident_id)
        if (entity_id, incident_id) in self._at_scene:  # scoring calls this on every evaluation
            return
        self._at_scene.add((entity_id, incident_id))
        self.mirror.write(
            "MATCH (e:Entity {uid: $e}), (i:Incident {uid: $i}) MERGE (e)-[:AT_SCENE]->(i)",
            e=self.mirror.uid(entity_id), i=self.mirror.uid(incident_id),
        )

    def add_decision(self, decision_id: str, proposal: ProposedAction, config_hash: str) -> None:
        super().add_decision(decision_id, proposal, config_hash)
        m = self.mirror
        uid = m.uid(decision_id)
        m.write(
            """MATCH (i:Incident {uid: $incident})
               MERGE (d:Decision {uid: $uid})
               SET d.id = $id, d.run_id = $run, d.department = $department, d.tier = $tier, d.action = $action,
                   d.actuator_id = $actuator_id, d.params = $params, d.justification = $justification,
                   d.config_hash = $config_hash, d.valid_at = datetime()
               MERGE (i)-[:HANDLED_BY]->(d)""",
            incident=m.uid(proposal.incident_id), uid=uid, id=decision_id, run=m.run_id,
            department=proposal.department, tier=proposal.tier, action=proposal.action,
            actuator_id=proposal.actuator_id, params=_json(proposal.params),
            justification=proposal.justification, config_hash=config_hash,
        )
        m.write(
            "MATCH (d:Decision {uid: $uid}) UNWIND $readings AS r MATCH (n:Reading {uid: r}) MERGE (d)-[:CITES]->(n)",
            uid=uid, readings=[m.uid(r) for r in proposal.evidence_reading_ids],
        )
        if proposal.trust_ref:
            m.write("MATCH (d:Decision {uid: $uid}), (v:Verdict {uid: $v}) MERGE (d)-[:CITES]->(v)",
                    uid=uid, v=m.uid(proposal.trust_ref))
        if proposal.knowledge_citations:
            m.write(
                "MATCH (d:Decision {uid: $uid}) UNWIND $ids AS k MATCH (n:Knowledge {id: k}) MERGE (d)-[:CITES]->(n)",
                uid=uid, ids=proposal.knowledge_citations,
            )

    def add_action(self, decision_id: str, action_id: str, call: dict, result: dict) -> None:
        super().add_action(decision_id, action_id, call, result)
        m = self.mirror
        m.write(
            """MATCH (d:Decision {uid: $decision})
               MERGE (a:Action {uid: $uid})
               SET a.id = $id, a.run_id = $run, a.status = $status, a.call = $call, a.result = $result, a.valid_at = datetime()
               MERGE (d)-[:ISSUED]->(a)""",
            decision=m.uid(decision_id), uid=m.uid(action_id), id=action_id, run=m.run_id,
            status=result.get("status"), call=_json(call), result=_json(result),
        )
