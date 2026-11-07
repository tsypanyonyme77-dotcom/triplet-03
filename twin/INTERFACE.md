# Interface Card: twin

One page. What this layer sends and receives, with one example of each message, how to point it at a different partner, and how it authenticates.

## Role

Simulates the city: zones, sensors (traffic cameras, water level, power load, air quality, emergency calls) and actuators (police/ambulance dispatch, traffic signals, water valves, power-grid switching, device isolation/quarantine).

## Exposes (what partners can call)

Every sensor reading and actuator action as a callable MCP-style tool.

## Consumes (what this layer calls on partners)

Nothing required; Brain and Guardian call the Twin. _(List any callbacks/subscriptions here.)_

## Messages

One example of each message sent and received.

```json
{ "TODO": "example message" }
```

## Configuration

| Variable | Meaning | Default |
|----------|---------|---------|
| `TWIN_URL` | Twin address | `http://twin:8001` |
| `BRAIN_URL` | City Brain address | `http://brain:8002` |
| `GUARDIAN_URL` | Guardian address | `http://guardian:8003` |

Switching to a different partner = changing these values. Nothing is hard-coded.

## Authentication

_TBD (e.g. bearer token from `*_TOKEN`)._

## Validation and errors

_What happens on malformed or unexpected input: status codes and error message format._
