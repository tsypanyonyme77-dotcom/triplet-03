# guardian (black box)

Watches the same data as the Brain to detect sensor faults, actuator failures, spoofed data and cyber-attacks. Issues trust verdicts and contains problems (isolate, quarantine, roll back).

## Run this layer alone

Runs without partners, using the stand-ins in [`mocks/`](mocks/).

```bash
# TODO: one command that starts this layer + its mocks
```

## Configuration

Partner addresses and tokens come from environment variables (`TWIN_URL`, `BRAIN_URL`, `GUARDIAN_URL`, `*_TOKEN`; see root `.env.example`). To point this layer at a different partner, change them there; no code change needed.

## Layout

| Path | Content |
|------|---------|
| `INTERFACE.md` | The Interface Card |
| `src/` | Layer code |
| `mocks/` | Stand-ins for twin + brain |
| `tests/` | Tests |

## Members

_Listed by the team._
