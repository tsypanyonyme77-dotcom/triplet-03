# Challenge Overview

Source PDFs: `reference/challenge-overview.pdf`, `reference/phase1-specifications.pdf`. Scope here: only what matters to the **Twin team**.

## What it is
TSYP14 Technical Challenge "City Brain Convergence". Three independently built layers must work as one smart city: **Twin**, City Brain, Guardian. Teams (max 4 members) are grouped in triplets, one team per layer. Emphasis: engineer to an interface you do not control, and prove the system stays reliable when connected to external systems. Security and trust are core requirements.

## Our layer: Twin
Build the digital twin: the simulated city the other two layers connect to.
- Simulate sensors: traffic cameras, water-level, power-load, air-quality, emergency-call feeds.
- Simulate actuators: police/ambulance dispatch, traffic-signal control, water-valve control, power-grid switching, device isolation/quarantine.
- Expose every sensor reading and actuator action as a callable interface so the other layers can read and act. **Current decision: plain HTTP APIs, not MCP** (see `twin-architecture.md`).
- The other two layers are out of scope for our work. We only need mocks of them (see `phase1-requirements.md`) and a clean contract (see `data-dictionary.md`).

## Timeline
| Date (2026) | Event |
|---|---|
| 1 to 17 Sep | Phase 0 ideation, 10-page report (done) |
| 22 Sep (overview) / 24 Sep (Phase 1 spec) | Team-layer assignment (PDFs disagree) |
| 31 Oct | Random triplet matching, round 1 |
| **7 Nov** | **Phase 1 deliverables due** (Phase 1 spec). Overview PDF says 12 Nov. Use 7 Nov. |
| 9 to 13 Nov | Jury reviews repos, reports, logs |
| **14 Nov** | **CSTAM pitching**: 10 min per triplet (2 min pitch + 8 min live demo) |
| 14 Nov to 14 Dec | Phase 2: reshuffled triplets, organizer-run scenarios |
| 1 Dec | Triplet matching, round 2 |
| 11 Dec | Final submission deadline |

## Scoring (100 pts total)
- **Phase 1: 50 pts** (each team scored individually): individual prototype functionality 10, technical implementation and features 5, **interoperability, connectivity, collaboration between the 3 teams 15**, security and trust mechanisms 10, documentation and code quality 5, demonstration and presence 5.
- **Phase 2: 45 pts**: final prototype 10, 3-layer integration and reliability 10, response to adversarial/simulated scenarios 15, final presentation 5, documentation and repo 5.
- **Bonus 5 pts**: at least one CS, one PE, one CN member (1 pt each); Collabrec workspaces for CyberSecurity and AI learning groups (0.25 pt per member, max 1 pt each).
- Only N teams advance to Phase 2, balanced across layers, then get reshuffled into new triplets. Interoperability with partners we never worked with is the ticket to the finals.

## Contact
yp@ieee.tn, cs@ieee.tn, cn@ieee.tn
