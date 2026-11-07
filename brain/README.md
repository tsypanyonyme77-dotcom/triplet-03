# brain (Tatsu)

Detects real incidents (accidents, fires, traffic jams, floods) from the live Twin data, decides the right response and acts through the Twin's actuators. Acts on a reading only after a Guardian trust verdict.

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
| `mocks/` | Stand-ins for twin + guardian |
| `tests/` | Tests |

## Members

_Listed by the team._
