> Archived 2026-11-08: the suspect-pursuit pipeline this describes was removed. The incident scenarios in `TESTBOOK.md` replaced it.

# Next Delivery (from the last triplet meeting)

Source: meeting notes pasted by the user on 2026-10-14. Deadline: "next Wednesday", most likely **2026-10-21** (2026-10-14 is a Wednesday). Confirm the exact date with the user.
Scope: **Twin layer only.** The other layers are black boxes we imitate.

## Meeting outcomes relevant to us
- **Twin (us):** presented available simulators/actuators and CS2 limits. Finding: lots of readable data, limited control over actuation/modification. The shared document with current possibilities is `reference/City_Brain_Feature_Exploration_Summary.pdf` and the CS2 study (`cs2-experiment.md`).
- **Guardian:** needs API contracts from **both Twin and City Brain** to monitor and validate data flow. So our contract must be written down precisely (see `data-dictionary.md`, to be extended).
- **Zone segmentation:** idea of splitting the city/data into zones. **The Twin explores feasibility.**
- **City Brain:** presented its simulators, actuators and expected data flow. (Details not provided; ask the user for their doc, store it per `partner-docs.md`.)

## Deliverables for next Wednesday

### 1. End-to-end pipeline for ONE scenario (all layers)
Each team builds only its own black box and imitates the other two with a JSON file, dummy server, API server, or anything suitable. Inputs/outputs must follow the agreed API contracts and the discussed context. No internal logic of other layers.

**Scenario: suspect identification and police pursuit**
1. Twin exposes **citizen data**.
2. Guardian monitors that data (trust check).
3. City Brain analyzes it to identify potential criminal suspects.
4. If a suspect is found, City Brain triggers the **police pursuit actuator** in the Twin.

Each team's pipeline should trigger only the targeted layer's black box using the agreed formats.

**Our part of the flow:**
- Serve citizen data (read API) in the agreed envelope.
- Accept and execute the police pursuit actuator call, validate it, return a result, log it.
- Mock City Brain (calls our actuator) and mock Guardian (consumes our stream) so our layer runs alone (R1).
- One trigger to run the scenario, one log file out (R2).

### 2. Twin: explore simulator and actuator options
Further explore options, including **native mods and external access to CS2**, and **present feasible options**. Output: a short options document/presentation, with what is verified vs unverified.

### 3. Twin: explore city/data segmentation
Feasibility of segmenting city/data into zones and of **assigning department codes** to data (Police, Firefighters, etc.). Output: feasibility findings and a proposal.

## Gaps vs the current contract (`data-dictionary.md`)
The draft dictionary has no citizen data and no police pursuit actuator. To define with partners:
- Citizen record schema (id, location/zone, activity, status, attributes City Brain needs for suspect detection). Privacy: synthetic data only.
- Pursuit actuator: closest existing action is `dispatch_unit` with `unit_type: police`. Decide whether pursuit is a new action (e.g. `start_police_pursuit` with target citizen id) or a `dispatch_unit` variant; define params and result.
- Department code field (e.g. `department: police|fire|medical|...`) on readings, actuators and zones.
- Citizen data must pass the same envelope: `sequence_no`, HMAC `provenance`, `zone_id`.

## Open questions for the user
1. Exact deadline date and format of the presentation.
2. Is the scenario's citizen data coming from CS2 (citizens exist in-game; per-citizen control is undocumented) or from our POC / a synthetic generator?
3. City Brain team's actuator/simulator doc and the Guardian's expectations of our API contract.
4. Who owns the shared contract document going forward.

## Progress (2026-10-14)
Branch `feat/suspect-pursuit-pipeline`: Twin microservice + mock Guardian + mock City Brain console + Docker compose + scenario script + tests, all with randomized synthetic citizens. Not yet run under Docker (daemon was down in the dev session); verified by an in-process end-to-end test. CS2 adapter (`twin/src/twin/city/cs2.py`) is a documented stub for the teammate with the game. Still to do: CS2 options presentation, zone/department-code feasibility write-up (the synthetic 3x3 grid and `facilities` by department are a first sketch).
