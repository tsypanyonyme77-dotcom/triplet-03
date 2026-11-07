# Interface Card: guardian

One page. What this layer sends and receives, with one example of each message, how to point it at a different partner, and how it authenticates.

## Role

Watches the same data as the Brain to detect sensor faults, actuator failures, spoofed data and cyber-attacks. Issues trust verdicts and contains problems (isolate, quarantine, roll back).

## Exposes (what partners can call)

Trust verdict on a reading, before the Brain acts on it.

## Consumes (what this layer calls on partners)

Twin sensor stream; Twin containment actions (isolate a sensor, quarantine a device, roll back a reading).

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
