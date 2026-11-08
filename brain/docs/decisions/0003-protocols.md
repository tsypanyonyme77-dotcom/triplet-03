# 0003 Protocols and data formats

Status: MCP (Twin) and REST (Guardian) built and tested against our mocks; agreed with the triplet. **Decides: the triplet.** Date: 4 Nov 2026. The security design: `../SECURITY.md` and `../SECURITY-MITRE.md`.

## Question

How do the three layers talk to each other, and how do others talk to the Brain, with what a jury calls "standard, well-known protocols and data formats"?

## The links and the decision for each

| Link | Chosen | Main reason | Not the default, and why |
| --- | --- | --- | --- |
| Twin to Brain, readings | MCP tool `list_readings(cursor, limit)`, polled every 200 ms | One connection for both directions; tools describe themselves; the cursor gives backpressure and loss-free restart | MQTT: needs a broker, no schema. WebSocket: no schema or replay. gRPC: toolchain on both sides. Kafka: infrastructure |
| Brain to Twin, actions | MCP tools named after actions, one signed envelope each | Capability discovery gives the gate its `capability` check | REST POST per actuator, MQTT command topics, gRPC unary calls |
| Brain and Guardian | REST: `POST /verdicts`, `GET /quarantine/{id}` | One question, one answer, a deadline. Easiest for any team to build | MCP (not an agent's tool), gRPC |
| Brain to viewers | Server-Sent Events carrying CloudEvents 1.0 | One way, plain HTTP, reconnects, replays | WebSocket (two-way not needed), polling |
| Other agents to Brain | MCP and an agent card | The tool standard; read-only, cannot widen the gate | REST only (no tool discovery) |
| Telemetry | OTLP and Prometheus | Vendor neutral | Proprietary agents |

Formats: JSON everywhere; JSON Schema 2020-12 (`contracts/schemas/`); OpenAPI 3.1 for REST; AsyncAPI for the event feed (planned); W3C PROV-JSON for provenance (planned); canonical JSON for signatures, HMAC-SHA256 today, Ed25519 as an option.

## What we can connect to, and how fast

The ports let us connect to whatever the partners can build. This is the answer to "what your triplet can build":

| Partner offers | Brain adapter | State | Effort to add (my estimate) |
| --- | --- | --- | --- |
| Twin: MCP server | `McpTwinAdapter` | **built, tested on mocks** | none |
| Twin: REST (poll readings, POST actions) | `HttpTwinAdapter` | **built, tested on mocks** | none |
| Twin: MQTT readings, any actions | `MqttTwinAdapter` | **built, 5 Nov**: parity test `tests/test_twin_mqtt.py` (the `t14` city over a broker decides as `t14`); run once against a real broker (amqtt through `aiomqtt`): messages sent 1, 3, 2, 4 arrive 1, 2, 3, 4 | none; a Mosquitto service is in the Compose `data` profile |
| Twin: WebSocket stream | `WebSocketTwin` | could (`websockets` is installed) | 0.5 day |
| Twin: gRPC streams | `GrpcTwin` | on demand, needs their `.proto` | 1 day and a toolchain |
| Twin: no live stream, recorded files | `JournalTwin` (replays signed readings from a file) | planned in plan 0 | 0.25 day, reused from `brain replay` |
| Guardian: REST | `RestGuardianAdapter` | **built, tested on mocks** | none |
| Guardian: verdict inside the reading (`trust` field) | `guardian.mode: inline` | **built** | none |
| Guardian: MCP | `McpGuardian` | could | 0.5 day |
| Guardian: gRPC or MQTT | on demand | | 1 day each |

Every adapter is tested through the conformance kit (plan 1), which checks the port, not the protocol.

## Evidence

- The Brain has run end to end against the mock Twin over MCP and the mock Guardian over REST, in process and over the network (`brain scenario t14`, the five Test Book scenarios, `brain rehearse`).
- Spoofed, replayed and untrusted readings are refused (`t13`, `brain redteam`).
- **Against the Guardian team's live Guardian** (contract 1.0, `guardian.adapter: v1`) the Brain has run the fake flood, a real flood and `t16` (8 Nov, `docs/GUARDIAN-COMPAT.md`).
- **The Brain has not yet talked to the Twin team's real Twin**, and no run joins all three teams' layers (final report, 0.3 and 2.6). The Twin links are agreed with the partner and proven against our mocks of it.

## Cost to build

Built for the two default links, with an HTTP and an MQTT Twin adapter beside them, the Brain MCP server, the agent card, TLS and key ids. Risk: a partner protocol we did not foresee; the answer is one adapter, one day, and the conformance kit to prove it.

## If it fails

If the Twin cannot stream at all by the demo, the Brain plays recorded readings through `JournalTwin` and the screen says so. If the Guardian cannot be reached, degraded mode: track, send nothing (`b6`).

## Agreed with the triplet

The two default links and the envelope (the Data Dictionary), the signing method and key exchange, whether TLS is on in the hall, how each layer's events reach the shared timeline screen, how a scenario is triggered on the Twin. Agreed with the Twin and Guardian teams as set out in this record.

## Enforced or shown by

The conformance kit, the Interface Card, the schemas and examples (a test validates every example), the adapter parity test.

## One-line answers for the jury

- *Why MCP?* One connection, self-describing tools, discovery for the gate, the agent standard.
- *Why not MQTT, WebSocket or gRPC?* Each is a good protocol for another job; we ship an adapter for MQTT and say what the others cost.
- *What if your partner uses another protocol?* One adapter class and a day; the kit proves it.
