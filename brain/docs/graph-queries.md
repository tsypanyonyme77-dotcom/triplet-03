# Graph queries for the demo

Neo4j holds the City Graph by default (Qdrant holds the knowledge vectors). Start the database with `make neo4j` (or the whole stack with `scripts/up.sh`), run a scenario into it with `uv run brain scenario t14`, and open the Neo4j Browser at <http://127.0.0.1:7474> (user `neo4j`, password `NEO4J_PASSWORD` from `.env`, or `citybrain-local-pw` when it is unset). Every run is kept apart by its `run_id`; the queries below use the latest run. Each returns a graph the Browser draws, so they are meant to be pasted one at a time.

## 1. Why was this unit sent?

The decision, everything it cited (readings, the Guardian's verdict, the rule or playbook item), and the action it caused.

```cypher
MATCH (d:Decision {id: 'dec-0001'})
WITH d ORDER BY d.run_id DESC LIMIT 1
MATCH p = (d)-[:CITES]->(c)
OPTIONAL MATCH q = (d)-[:ISSUED]->(:Action)
RETURN p, q
```

## 2. Everything one reading caused

From one reading: the verdict on it, the incident it was evidence for, the decisions that incident led to, and their actions.

```cypher
MATCH (r:Reading {id: 'cit-feed-07#4'})
WITH r ORDER BY r.run_id DESC LIMIT 1
MATCH p = (r)-[:VERIFIED_BY|EVIDENCE_FOR]->(x)
OPTIONAL MATCH q = (r)-[:EVIDENCE_FOR]->(:Incident)-[:HANDLED_BY]->(:Decision)-[:ISSUED]->(:Action)
RETURN p, q
```

## 3. The path from a reading to an action

The shortest chain of links, in either direction, between one reading and the last action: the "show your working" query.

```cypher
MATCH (r:Reading {id: 'cit-feed-07#4'}), (a:Action {run_id: r.run_id})
WITH r, a ORDER BY r.run_id DESC, a.id DESC LIMIT 1
MATCH p = shortestPath((r)-[*..6]-(a))
RETURN p
```

## 4. Which playbook items apply to a kind of incident

The knowledge graph around one incident type: the items that apply to it and the actuator actions they use.

```cypher
MATCH p = (k:Knowledge)-[:APPLIES_TO]->(:IncidentType {name: 'crime'})
OPTIONAL MATCH q = (k)-[:USES]->(:ActionType)
RETURN p, q
```

## 5. Where a person was seen, and when

The zones one entity was present in, in order. The identifier is the pseudonymous one the Guardian's feed carries; no demographic field is stored.

```cypher
MATCH (e:Entity {id: 'cit-88213'})-[p:PRESENT_AT]->(z:Zone)
WITH e, p, z ORDER BY p.valid_at
RETURN e.id AS entity, z.name AS zone, p.valid_at AS seen_at
```

## 6. The city around an incident

The same picture `GET /api/incidents/{id}/context` serves: the zones within two hops of the latest incident, and the facilities and sensors in them.

```cypher
MATCH (i:Incident)-[:OCCURRED_IN]->(here:Zone)
WITH i, here ORDER BY i.run_id DESC LIMIT 1
MATCH path = (here)-[:ADJACENT_TO*0..2]-(z:Zone)
OPTIONAL MATCH (f:Facility)-[:LOCATED_IN]->(z)
OPTIONAL MATCH (s:Sensor)-[:MONITORS]->(z)
RETURN i, here, path, f, s
```
