# 0007 User interface

Status: accepted, built (the RTX 4050 frame rate is not yet checked). Decides: this team, for a screen the **triplet** is required to show (R3). Date: 4 Nov 2026.

## Question

What does the jury look at during the 8-minute demo, and how do we show reading, verdict, decision and action across three layers with timestamps?

## What the Phase 1 text requires

R3: "A live timeline screen shows what happens across the three layers with timestamps, e.g. reading, Guardian verdict, Brain decision, actuator action." The jury "must see cause and effect during the demo". The system is running and the screen shows live data before the slot starts.

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| One static page served by the Brain, vanilla JavaScript, SSE | Offline; projector-friendly; nothing to build or install; the same page serves the jury and the screenshots | Hand-written state handling | **Chosen** (the Strip Board, plus a 3D canopy) |
| A single-page-app framework with a build chain | Components, ecosystem | A build step and a package tree to break on stage | Rejected |
| Grafana only | Standard, easy | Cannot show the Brain's reasoning, held actions or the Why | Used for operators only (plan 4) |
| A terminal UI | Light | A jury at a projector wants a picture | Rejected |
| A shared screen owned by another team | One screen for all | We cannot control it; our reasoning would not fit | Rejected; ours accepts their events |

## Decision

The Strip Board (air-traffic flight strips) is the primary view: one strip per reading, with the verdict, the decision and the action in a row with times, a held action shown as prominently as a taken one, and a Why panel with a replay. The canopy is a second, deliberate world: a transparent three.js brain with eleven regions over the city, a camera directed by events, and a rack of instruments. The library is vendored (three.js r160, 672 KB, served at `/vendor`); nothing is fetched. Design records are in `DESIGN.md` and `.impeccable/`.

The strips are built from the Brain's own events (a reading received, a verdict received, an action result), so the three-layer line shows even if a partner pushes nothing. When a partner does push its own events (CloudEvents to `POST /api/events`, authenticated and namespaced after plan 6), they appear as extra rows with their source.

## Evidence

- Checked at 1920 by 1080 and 1440 by 900 in headless Chromium with software rendering, with the free camera, pause, reduced motion, the flat fallback with WebGL blocked and both quality tiers (`scripts/screenshot.py`, `scripts/canopy_smoke.py`).
- The high tier draws about 41,000 vertices for the glass; bloom drew half the canvas black on the Intel laptop, so no post-processing pass is used.
- **Not verified:** the canopy's frame rate and GPU on the RTX 4050 laptop, a real projector in a lit hall, the Why panel at phone width.

## Cost to build

Built. Plans 1 and 2 add an approval strip and an Optimiser instrument (about 0.5 day each through the `impeccable` skill, with a recorded adaptation). Risk: the RTX check; a `light` tier exists.

## If it fails

`?quality=light`, or the Strip Board alone (key `C` toggles). A WebGL failure leaves the flat canopy.

## Agreed with the triplet

How the Twin's and the Guardian's events reach the screen (push with a token and a namespace, or only what the Brain observes); whether the jury sees one screen or each team's; the timestamp format and clock source so rows line up; who presses the keys. Agreed with the Twin and Guardian teams as set out in this record.

## Enforced or shown by

Screenshots in the ledgers, `scripts/canopy_smoke.py` feeding every event type, a content-security policy and a source check in the reducer (plan 6), accessibility checks (reduced motion, keyboard, contrast).

## One-line answers for the jury

- *How do I see cause and effect?* Press `2`: the reading, the verdict, the decision and the action land in one strip with times.
- *Does it work with no internet?* Yes: one page, one vendored library.
- *Can a partner fake a decision on your screen?* Not after plan 6: pushed events are namespaced and the screen checks the source.
