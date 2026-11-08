# 0004 Hosting

Status: agreed and built (`Dockerfile`, `docker-compose.yml`, `scripts/up.sh`). **Decides: the triplet** for the joint start, this team for the Brain's images. Date: 4 Nov 2026.

## Question

Where does the system run for the 14 Nov demo and afterwards, given a hall with no Wi-Fi, nothing installed on stage, one 10-minute slot, and a jury reading the repository?

## Constraints from the Phase 1 text

- "Do not rely on the venue Wi-Fi. Bring your own router or hotspot. If you use the cloud, keep a local fallback."
- "Nothing is installed on stage. Anything that cannot run within the slot is not scored."
- The system is "already running and connected" before the slot; the timeline screen shows live data.
- The repository has a `docker-compose.yml` at the triplet root that "starts the whole city with one command (recommended)". Each team folder must run on its own with mocks.

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| One laptop, local processes (`uv run brain serve`) | Works today; nothing to pull; fastest | The partners' parts are not in it; not reproducible by a stranger without `uv` and a model download | The **fallback** |
| Docker Compose on one laptop, images and models baked in, a hall kit | One command, offline, the same images everywhere, fits the triplet-root compose | Needs the images pre-pulled; 3 to 4 GB of images | **Default on stage** |
| A managed cloud service | Public URL, scales | Fails with no Wi-Fi unless a local twin exists; an account is needed; data leaves the room | Not for the demo; a runbook only (see open decision) |
| Serverless | Cheap at rest | Holds per-city state badly; cold starts; no | Rejected |

## Decision

Local first. Compose is the default start on stage and the joint stack (`brain/docker-compose.yml` is written to be included by the triplet root file: its own project name, its own network, host ports taken from the environment so two teams cannot clash). The `full` profile adds Neo4j and Qdrant; the agent teams run on real models when `.env` holds a key. A hall kit carries every image and the models. Plan 4 builds it.

## Evidence (measured on 4 Nov, this laptop)

- Machine: 20 cores, 15 GB RAM, an RTX 4050 with 6 GB, Docker 29.9.2 working from a session.
- One scenario in process: **120 MB peak with the hashing embedder; 1,419 MB peak and 11.7 s wall with the real embedder** (model load plus embedding the 68-item corpus at every start). So the Brain image needs about 1.5 GB, and start-up should not re-embed what has not changed (plan 3 persists vectors).
- Disk: the embedding model is 65 MB; the local Neo4j install is 676 MB.
- A rough budget for the full stack on this laptop: Brain 1.5 GB, Neo4j about 1 GB, Qdrant about 0.5 GB (not measured), observability about 1.5 GB (not measured), a browser with the canopy about 2 GB. It fits in 15 GB; observability stays optional on stage.
- Not yet verified: the canopy on the RTX 4050, a real projector.

## Cost to build

Images and Compose core about 1 day; telemetry 0.5 day; hall kit and offline rehearsal 0.5 day (my estimates). Risk: pulling images on the slow network (do it once, early); memory pressure when everything runs (profiles keep it optional).

## If it fails

The in-process Brain (`uv run brain serve`) is always the fallback and needs only the repository and a cached model. The demo script has a shortest path back for every beat (plan 5).

## Agreed with the triplet

Who runs which container on the stage laptop or laptops; the ports and network names; one compose file at the root that includes all three; the router and addressing; who hosts the shared timeline screen; whether the Twin and Guardian run as containers or processes. Agreed with the Twin and Guardian teams as set out in this record.

## Enforced or shown by

`scripts/compose_smoke.sh`, `brain rehearse --stack` with the network disabled, `tests/test_compose.py`, the full stack run recorded in the ledger.

## One-line answers for the jury

- *What if the Wi-Fi fails?* There is none: everything is on the laptop and in the kit.
- *Can this run in the cloud?* The same images; verified in Compose on one laptop, not claimed beyond that.
