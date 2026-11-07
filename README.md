# triplet-03

A connected three-layer smart-city system: a simulated city (Twin), an operational decision-maker (City Brain) and a trust/security watchdog (Guardian). Each layer is built by a different team and runs on its own; the root of this repo shows the complete triplet.

| Layer | Team | Folder | Key question |
|-------|------|--------|--------------|
| Twin | Onymous | [`twin/`](twin/) | What is happening in the city? |
| City Brain | Tatsu | [`brain/`](brain/) | What should we do? |
| Guardian | black box | [`guardian/`](guardian/) | Is this data telling the truth? |

**Members:** _each team lists its members in its own layer README._

## One-command start

```bash
cp .env.example .env     # partner addresses and tokens live here, never in code
docker compose up --build
```

Run a Test Book scenario (one trigger script per scenario, one log per run in `logs/`):

```bash
./scenarios/<id>-<name>.sh
```

Run a single layer alone with its mocks: see `<layer>/README.md`.

## Map

| Path | What it is |
|------|-----------|
| [`INTEGRATION.md`](INTEGRATION.md) | How the 3 layers connect: diagram, protocol, one scenario end to end |
| [`TESTBOOK.md`](TESTBOOK.md) | Test scenarios and expected outputs |
| `<layer>/INTERFACE.md` | Each layer's Interface Card |
| `scenarios/`, `logs/` | Trigger scripts and the log of every run |
| `docs/` | Report, pitch deck, diagrams |

## Ownership

Each team commits only inside its own folder (enforced by [`.github/CODEOWNERS`](.github/CODEOWNERS)). Root files are shared by the triplet.
