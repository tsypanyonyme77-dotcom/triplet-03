# Simulation Scenarios: Twin Layer

## 1. Purpose

The simulation supports scenarios.
Each scenario is an event or chain of events in the simulated city.
The event is detected by witnesses and sensors, it changes how simulated civilians and vehicles behave, and it is answered through actuators.

This document describes the scenario lifecycle and the responsibilities of the **Twin Layer**.
It uses the implemented **Car Crash / Pedestrian Hit** scenario as the worked example and **Building Fire** as a conceptual, not implemented, scenario.

Status of this document: corrected on 2026-11-08 against the code on branch `refactor/twin-engine-layout` (`twin/src/twin/engine/`, `twin/src/twin/city/two_blocks.py`, `twin/src/twin/actuators.py`, `twin/mocks/`, `scenarios/incident_chain.py`).

## 2. Scope and system boundaries

The project has three layers.

-   **Twin Layer:** The simulated world in which events occur and entities behave. This is the focus of this document.
-   **Guardian Layer (mock):** Checks every reading the Twin emits and returns a verdict (`trusted` or not). Its internals are out of scope, but it is part of the implemented chain: the Brain only acts on readings the Guardian trusts.
-   **City Brain Layer (mock):** Receives verified reports, builds an incident board, and issues actuator commands. Its internals are out of scope.

The Twin Layer is responsible for:

-   representing the environment (a two-block city map with traffic lights, parking, stations and cameras);
-   causing events (by simulation rules or by a scripted scenario);
-   simulating who sees an event and what they report;
-   applying civilian and vehicle reactions;
-   validating and executing actuator commands.

The mock Brain has an incident board with a UI-style API.
In the default **manual mode** it only lists incidents and waits for an operator action (dispatch ambulance, police or fire, close or open a road).
In **auto mode** (a flag, for tests and unattended demos) a rule answers the first trusted report of an incident with an ambulance and a police car, after a short decision delay.

## 3. The scenario lifecycle

1.  **Event occurrence:** An event takes place in the simulated environment.
2.  **Detection and reporting:** Witnesses and sensors report it as readings in the Twin's data contract. The Guardian verifies them and the Brain receives the trusted ones.
3.  **Civilian and traffic reactions:** Entities respond. Some reactions are implicit, some are explicit.
4.  **Actuation and resolution:** The Brain decides and sends actuator calls. The Twin moves the units and simulates what they do on scene.

The lifecycle is a conceptual flow, not a requirement that every scenario uses every stage in the same way.
Some reactions happen immediately, before any actuator is dispatched.

``` mermaid
flowchart TD
    A[Event occurs in the Twin] --> B[Witnesses and cameras detect it]
    B --> C[Twin emits readings: emergency_call, cctv_anomaly, traffic_camera]
    C --> D[Guardian verifies each reading]
    D --> E[Brain incident board lists trusted incidents]
    A --> F[Cars and pedestrians react]
    E --> G[Brain decides: manual operator or auto rule]
    G --> H[Actuator calls: dispatch_unit, set_barrier_state]
    H --> I[Twin simulates units, barrier and scene work]
    F --> J[Environment changes]
    I --> K[Scene cleared, units back at station]
    J --> K
```

### 3.1 Event occurrence

An **event** is something that happens in the simulated world and may need intervention.

Mechanisms in the current implementation:

-   **Indirect, from simulation parameters (the default `city` scenario):** accidents arise on their own from random traffic. The city has configurable `cars` (default 20, max 47), `pedestrians` (default 40, max 100), `car_crash_risk` (default 0.1) and `ped_hit_risk` (default 0.1). The risks are drawn once per road user when the city is built: a car with the crash risk runs red lights and does not wait for a free junction. A car with the pedestrian risk does not yield to pedestrians. A pedestrian with the pedestrian risk ignores signals and traffic gaps at crosswalks.
-   **Direct, scripted scenarios:** `ped-hit` (a careless driver hits a distracted pedestrian on crosswalk `cw_2_1`) and `car-crash` (a red-light runner hits the side of a car crossing on green). Each stages its event by watching the actors, so it still works with background traffic. They are chosen at start-up (`TWIN_SCENARIO`), through `POST /live/control` (action `load`), or with `scenarios/incident_chain.py`.

Not implemented:

-   There is no endpoint or UI control that triggers an event on demand in a running city.
-   There is no autonomous "probability per time interval" event. The risks above are per-agent behaviour traits, set when the city is built.
-   The Brain cannot request or trigger events. It only reads reports and sends actuator calls.

A scenario should define, where applicable: the event type, the conditions, how it can be triggered, the settings, and the location and affected entities.

### 3.2 Detection and reporting

Detection comes from two kinds of sources.

**Witnesses (emergency calls).**
A pedestrian, a driver standing in traffic, or a driver in the crash itself sees an incident when:

-   it is within 40 m;
-   the straight line to it stays inside the street corridors (buildings block the view; streets and sidewalks do not).

Each witness decides once, at random, whether to call: 50% of pedestrians, 30% of nearby drivers, 70% of an uninjured driver in the crash.
A caller dials after a reaction delay of 1 to 8 s, stops, and stands on the phone for 15 to 25 s.
The call carries what the caller says, not the truth:

-   the location is usually a few metres off, and 10% of the time 15 to 30 m off;
-   the category can be wrong (10%), for example "fire" for a crash;
-   confidence varies;
-   false reports (a call about nothing) are generated at a configurable rate.

A call centre merges calls about one place (within 50 m and 300 s) into one `incident_id`.
Ground truth stays inside the Twin and is never emitted.

**CCTV cameras.**
There is one camera at every signalised junction, with a 45 m range and the same line-of-sight rule.
A camera does **not** call 911.
It produces sensor readings:

-   `traffic_camera`: periodic vehicle count and mean speed.
-   `cctv_anomaly`: `collision` (a crashed vehicle, flagged 2 s after it stops) or `stopped_vehicle` (a vehicle on the road, not at a red light, standing still for 30 s, for example in a queue behind a wreck).

A camera alert joins the open incident at that place, or opens a new one.

**Reading format.**
Reports are not free-form notifications.
They are readings in the shared envelope (`contract_version`, `sensor_id`, `type`, `zone_id`, `timestamp`, `sequence_no`, `value`, `provenance` with an HMAC), with a `department` field.
`emergency_call` carries `call_id`, `incident_id`, `category`, `caller_confidence`, approximate `location`, `reporter_kind`.
The Twin delivers them to the Guardian over HTTP, and the Guardian's verdict goes with them to the Brain.
Zones of the map: `zone-01`, `zone-02` (the two blocks), `zone-03` (streets and stations).

The Brain's incident board only uses readings the Guardian marked `trusted`, and only `emergency_call` and `cctv_anomaly` of kind `collision`.

### 3.3 Civilian and traffic reactions

#### Implicit reactions

These arise from the engine's rules, without any command.
After a crash:

-   the crashed vehicle stops and stays as a wreck;
-   a struck pedestrian becomes a casualty at the scene;
-   cars behind queue up and may stop, which can raise a `stopped_vehicle` camera anomaly;
-   witnesses who decide to call stop and stand on the phone.

Note: the engine does not yet route traffic around a wreck on its own. A car that follows a red-light runner into a junction can be trapped behind the wreck (open item in the engine notes).

#### Explicit reactions

These are changes caused by a command or by response logic.
After units are dispatched:

-   cars ahead of a unit with its siren on pull right and stop, and the unit passes them;
-   once the police arrive they close the street of the wreck (barriers at both ends); cars that have not reached it are re-routed when they can, the others stop before it; emergency units ignore barriers.

The distinction is based on how the reaction is started, not on how visible it is.

### 3.4 Actuation and resolution

The Brain sends actuator calls to the Twin: `requesting_layer`, a `justification`, a `trust_ref` (the Guardian verdict it relied on) and an optional `idempotency_key`.
Calls need an API key, and `city_brain` calls without a `trust_ref` are refused.
The Twin validates the params against the catalog (`GET /actuators`), returns a result, and logs it.

Implemented actuators:

-   `dispatch_unit` (`unit_type`: `police`, `ambulance` or `fire`; `incident_id` from an `emergency_call` or `cctv_anomaly` reading). The target is the incident, not raw coordinates. Idempotent per incident and unit type: a second call returns `duplicate`. Other results: `dispatched` (with `unit_id`, `eta_minutes`) and `rejected` (`unknown_incident`, `no_unit_available`, `unknown_unit_type`).
-   `set_barrier_state` (`state`: `closed` or `open`; `road_id` such as `1-2`, or `incident_id`). Results: `closed`, `opened`, `duplicate`, `rejected`.

Units belong to stations on the outer streets: a hospital (ambulance), a police station and a fire station.
A dispatched unit leaves its bay when there is a gap, drives with its siren on, and goes home when done.

## 4. Implemented scenario: Car Crash / Pedestrian Hit

Two accident kinds exist: `car_pedestrian` (a car hits a pedestrian) and a car-car crash.

### 4.1 Event

-   In the default `city` scenario, accidents happen on their own from the car and pedestrian counts and the two risk settings.
-   `ped-hit` and `car-crash` stage the accident deterministically for demos and tests.
-   The accident stays open until it is handled. Nothing is dispatched automatically (except in the Brain's auto mode).

### 4.2 Detection and reporting

-   Witnesses (pedestrians and drivers, with line of sight within 40 m) may make emergency calls, with noisy location, possible wrong category and a call centre that merges them into incidents.
-   Junction cameras raise `cctv_anomaly` readings (`collision`, `stopped_vehicle`).
-   False calls can open incidents that have nothing behind them. A unit sent to one looks around for about 10 s and leaves.
-   A caller who gets it right reports `medical` for a pedestrian hit and `police` for a car crash.

### 4.3 Reactions

As in section 3.3: the wreck and casualty stay, traffic queues behind them, witnesses stand on the phone.
These do not depend on the Brain dispatching anything.

### 4.4 Actuators and what the units do

Dispatched by the Brain (by an operator in manual mode, or by the auto rule):

-   **Ambulance:** drives to the scene with its siren. The crew walk to the casualty, treat them (about 8 s), carry them back and load them. The ambulance then takes the casualty to the hospital with its siren on, and returns home.
-   **Police car:** stops about 10.5 m upstream of the ambulance's spot, angled across its lane to shield the scene. On arrival it closes the street of the wreck (`set_barrier_state`). It stays at least 10 s, and reopens the street when it leaves.
-   **Fire truck:** the unit exists and can be dispatched, but no fire behaviour is simulated. Fire is only a call category.
-   The Brain can also send `set_barrier_state` itself to close or open a road.

### 4.5 Resolution

The scene is cleared when the casualty is aboard, 8 s have passed, and the police (if sent) have been on scene for at least 10 s.
Then the wrecks are towed away (removed), the accident is closed, barriers opened by the police are lifted, and the units drive home and park.
The Brain's incident status moves `reported`, `unit_dispatched`, `on_scene`, `resolved`, from the actuator answers and the Twin's unit feedback (`GET /units`, `GET /responses`).

In manual mode with no operator action, nothing moves: the wreck and the casualty stay.

### 4.6 Scenario flow summary

``` mermaid
flowchart TD
    A[Risky traffic, or scripted ped-hit / car-crash] --> B[Car crash / pedestrian hit]
    B --> C[Witnesses call, junction cameras flag collision]
    C --> D[emergency_call and cctv_anomaly readings with incident_id]
    D --> E[Guardian verdict]
    E --> F[Brain incident board]
    B --> G[Wreck and casualty stay, traffic queues]
    F --> H[Operator or auto rule: dispatch_unit]
    H --> I[Ambulance and police drive with sirens, cars pull over]
    I --> J[Police close street, crew treat and load casualty]
    J --> K[Ambulance to hospital, wrecks towed, street reopened, units home]
```

One command runs the whole chain in one process and writes a log: `uv run python ../scenarios/incident_chain.py [ped-hit|car-crash] [--auto]` from `twin/`.
It writes `logs/<scenario>-chain-<timestamp>.log` and a recording for the 3D viewer.

## 5. Conceptual future scenario: Building Fire

Not implemented.
The engine has no buildings that burn, no smoke or CO2 sensors in the two-blocks city, no fire spread and no evacuation behaviour.
What exists is only the groundwork: a fire station with a dispatchable fire truck, `fire` as a call category, and `smoke_detected` on the contract's camera and building sensors.
This section shows how the same lifecycle could support a different event.

### 5.1 Event

A fire in a building, started by a UI selection, an API request naming a building, or an autonomous per-building probability.
The scenario would track the building and the fire's state and progression.

### 5.2 Detection and reporting

Smoke detectors, CO2 or other emission sensors, and witness calls (category `fire`).
A sensor reports when its threshold is met, as a reading in the same envelope, with the Guardian's cross-checks in mind (for example air quality against a smoke flag).

### 5.3 Reactions

-   The fire spreads to neighbouring buildings by proximity rules.
-   The building is damaged or destroyed.
-   Civilians inside or near it evacuate, pedestrians move away.
-   Vehicles avoid or reroute around the area.
-   The building or area is unavailable as a destination, and streets may be marked blocked.

### 5.4 Actuators

The primary actuator is the fire truck (`dispatch_unit` with `unit_type: fire`), plus road closure through `set_barrier_state`.
The scenario would define when the fire is reduced or put out, for example by the arrival and work of the unit.

### 5.5 Scenario flow summary

``` mermaid
flowchart TD
    A[Trigger or probability] --> B[Fire starts in a building]
    B --> C[Smoke sensors and callers report]
    C --> D[Guardian verdict, then Brain]
    B --> E[Fire spreads, building damaged]
    E --> F[Civilians evacuate, traffic avoids area]
    D --> G[Brain dispatches fire truck]
    G --> H[Twin simulates arrival and firefighting]
    H --> I[Fire contained or extinguished]
```

## 6. Cross-scenario concepts

  -----------------------------------------------------------------------
  Concept                 Meaning                 Examples
  ----------------------- ----------------------- -----------------------
  Event                   Something that happens  Car crash, pedestrian
                          in the simulated world  hit, building fire

  Trigger                 Mechanism that causes   Simulation risks,
                          an event to begin       scripted scenario,
                                                  (future) API call

  Simulator / observer    Entity or component     Pedestrian, driver,
                          that observes the       junction camera,
                          environment and detects (future) smoke detector
                          an event

  Detection condition     Rule that determines    Range, line of sight,
                          whether an observer     reporting probability,
                          detects an event        detection delay

  Report                  Reading sent after      emergency_call,
                          detection, in the       cctv_anomaly,
                          contract envelope       traffic_camera

  Verdict                 Guardian's trust        trusted / not trusted,
                          decision on a reading   verdict id (trust_ref)

  Reaction                Behavior or state       Wreck stays, queue,
                          change caused by the    cars pull over for a
                          event or the response   siren, street closed

  Actuator                Entity that carries out Ambulance, police car,
                          a response              fire truck, barrier

  Actuator command        Call from the Brain to  dispatch_unit for an
                          the Twin, validated     incident_id,
                          and idempotent          set_barrier_state
  -----------------------------------------------------------------------

### 6.1 Important distinctions

-   **Triggering is not detection.** A rule or a script causes the event; observers detect it afterward.
-   **Detection is not actuation.** A witness or camera reports what it saw; it does not decide or perform the response.
-   **Reporting is not dispatching.** A call (or camera alert) sends information. Dispatching a unit is a later, separate decision.
-   **A camera is not a caller.** Cameras emit `cctv_anomaly` readings; only witnesses make `emergency_call` readings.
-   **Reports are imperfect.** Location, category and confidence can be wrong, and false calls exist. The incident id comes from the Twin's call centre, not from the truth.
-   **Reactions are not necessarily actuator-driven.** Traffic stopping after a crash is an implicit consequence of the event.
-   **The Guardian sits between Twin and Brain.** The Brain acts on trusted readings and cites the verdict (`trust_ref`) in its actuator calls.
-   **The Brain decides; the Twin executes.**

## 7. Suggested scenario definition structure

1.  **Scenario name and description**
2.  **Event definition**
    -   Event type and affected entities.
    -   Scripted trigger, if any.
    -   Indirect conditions and risk settings.
    -   Autonomous probability, if applicable.
3.  **Detection and reporting**
    -   Eligible witnesses and sensors.
    -   Range, line of sight, delays, thresholds.
    -   Reading types and fields sent, and how they can be wrong.
4.  **Reactions**
    -   Implicit reactions.
    -   Explicit reactions.
    -   Entities affected and state changes.
5.  **Actuators**
    -   Available actuator actions and their params.
    -   Movement, arrival and on-scene behavior in the Twin.
6.  **Resolution conditions**
    -   When the event is considered handled.
    -   How normal behavior and availability are restored.

Not every field needs to be enabled for every scenario.

## 8. Overall responsibility split

  -----------------------------------------------------------------------
  Responsibility          Twin Layer              Other layers
  ----------------------- ----------------------- -----------------------
  Represent the simulated Yes                     No
  environment

  Cause an event in the   Yes (risks, scripted    No: the Brain cannot
  simulation              scenarios)              trigger events today

  Simulate witnesses and  Yes                     No
  cameras

  Emit reports as signed  Yes                     Guardian and Brain
  readings                                        receive them

  Judge whether a reading No                      Guardian
  is trustworthy

  Simulate civilian and   Yes                     Brain influences them
  vehicle reactions                               only through actuator
                                                  calls (for example a
                                                  road closure)

  Decide which response   No                      Brain (operator in
  is needed                                       manual mode, rule in
                                                  auto mode)

  Validate and execute    Yes (API key, schema,   Brain sends the calls
  actuator calls          trust_ref, idempotency)

  Simulate unit movement  Yes                     No
  and on-scene work
  -----------------------------------------------------------------------

## 9. Key takeaway

A scenario describes how an incident begins, how the simulated world detects and reports it, how entities react, and how a response is carried out.

The Twin Layer owns the event and its effects: causing it, simulating who sees it and what they report, the reactions, and the execution of actuator calls.
The Guardian checks the readings.
The Brain turns trusted reports into incidents, decides, and sends actuator calls back.

The implemented Car Crash / Pedestrian Hit scenario shows the full chain: an accident from risky traffic or a script, noisy witness calls and camera anomalies merged into incidents, a Guardian verdict, a Brain dispatch, an ambulance and a police car with sirens and a street closure, casualty treatment and transport, wrecks towed, and units back at their stations.
Building Fire is a design sketch that reuses the same structure and would need new engine work.
