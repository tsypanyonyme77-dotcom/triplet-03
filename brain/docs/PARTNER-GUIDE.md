# Connecting your layer to the City Brain: a ten-minute guide for the Twin and Guardian teams

The Brain does not need your code; it needs your messages to follow the shared contract. Everything below runs on your laptop with no cloud. Twin team: `TWIN-HANDOVER.md` is the page written for you.

## 1. See what the Brain expects (2 minutes)

Read `INTERFACE.md` (one page: what it sends and receives, an example of each message, how to point it at you, how it authenticates). Every message in it is agreed by the triplet; a contract change is four small edits (see `README.md`).

## 2. Check your layer against the contract (3 minutes)

```bash
uv run brain conformance --twin http://your-twin:8000/mcp          # a Twin over MCP
uv run brain conformance --guardian http://your-guardian:8100      # a Guardian over REST
uv run brain conformance                                           # the shipped mocks and this Brain, as a reference run
```

Each check prints a pass, a warning or a fail with the fix in one line (an unsigned reading, a repeated sequence number, a missing capability...). Add `--probe-actuators` to a Twin check to send signed test calls. Reports for the shipped mocks are in `docs/conformance/`.

## 3. Name things your way (2 minutes)

If your sensors or fields have other names or units, you do not change code: capture a sample and let the Brain propose the mapping.

```bash
uv run brain onboard --twin http://your-twin:8000/mcp --yaml        # or --sample readings.json
```

It prints `twin.type_aliases` and `twin.profiles` lines with a confidence for each and marks anything it is unsure of for review. It never edits a file; you paste the lines into `config/partners.yaml`.

## 4. Point the Brain at you (1 minute)

```yaml
twin:     {adapter: mcp, url: http://your-twin:8000/mcp, hmac_secret_env: TWIN_HMAC_SECRET}   # adapter: http if you speak plain HTTP
guardian: {adapter: rest, url: http://your-guardian:8100, mode: sidecar}
```

A Twin that speaks plain HTTP needs `GET /readings`, `GET /topology`, `GET /capabilities` and `POST /actuators/{action}`; see `docs/INTEGRATION-brain.md` ("Other carriers"). Then `uv run brain serve --live`.

## 5. Sign what you send (2 minutes)

Readings and calls carry an HMAC-SHA256 over canonical JSON in `provenance.hmac`. Agree a secret out of band, put it in `TWIN_HMAC_SECRET` on both sides, and see `docs/KEYS.md` for key ids, rotation and Ed25519. The Brain refuses an unsigned, replayed, or wrongly versioned reading and says why in a `brain.reading.rejected` event.

## 6. Run a scenario together

`uv run brain scenario d3 --no-spawn` plays a Test Book scenario against the partners in `config/partners.yaml`. Inside Compose: `make full-scenario S=d3`. `docs/TESTBOOK-brain.md` lists every scenario with what each layer should do.

## If something fails

The timeline screen (`uv run brain serve`) shows every reading, verdict, decision and refusal with its reason. `uv run brain redteam` shows what the Brain itself defends against.
