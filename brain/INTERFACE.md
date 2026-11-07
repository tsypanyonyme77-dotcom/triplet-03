# Interface Card: brain

One page. What this layer sends and receives, with one example of each message, how to point it at a different partner, and how it authenticates.

## Role

Detects real incidents (accidents, fires, traffic jams, floods) from the live Twin data, decides the right response and acts through the Twin's actuators. Acts on a reading only after a Guardian trust verdict.

## Exposes (what partners can call)

_Decision/status endpoints, if any._

## Consumes (what this layer calls on partners)

Twin sensor readings and actuator tools; Guardian trust verdicts.

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
